"""Early bottom-line estimator — dev plan sections 2 (step 3) and 12 (UX).

``estimate_refund(profile, year, income)`` puts a preliminary refund/owed RANGE
on the table as soon as the first income document is confirmed, with its
composition, the assumptions behind it, and what would tighten it. It is built
on the SAME deterministic ``calc`` engine as the final return (never model
arithmetic) and every result is labeled ESTIMATE.

Honesty rules baked in (UX principle 1; eval scenario (j)):
- a RANGE, never fake point precision — the width comes from what is still
  unconfirmed (most importantly the filing status), computed by running calc
  under each plausible assumption;
- the range is "before unclaimed credits" — refundable credits (EITC/CTC) are
  surfaced as a directional caveat, not silently omitted;
- it is the ordinary tax computation (preferential cap-gain/qualified-dividend
  rates are out of scope here, as in ``calc.tax_from_taxable_income``).

The profile supplies the qualitative picture (filing status, dependents, which
documents are still missing); ``income`` supplies the confirmed dollar amounts
from extracted-and-confirmed documents (the profile schema holds an inventory,
not amounts).
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.calc import se_tax, standard_deduction, tax_from_taxable_income
from taxfill_core.knowledge import Citation
from taxfill_core.schemas.profile import Profile

__all__ = ["IncomeSnapshot", "CompositionLine", "RefundEstimate", "estimate_refund"]

_LABEL = "ESTIMATE"


class IncomeSnapshot(BaseModel):
    """Confirmed dollar amounts so far (whole dollars; taxpayer + spouse combined).

    Every field defaults to 0 so an estimate can run off a single confirmed
    document. ``itemized_deductions`` is None unless the user is itemizing (then
    the larger of it and the standard deduction is used).
    """

    model_config = ConfigDict(extra="forbid")

    wages: int = Field(default=0, ge=0, description="W-2 box 1 wages (all W-2s).")
    federal_withholding: int = Field(default=0, ge=0, description="Federal income tax withheld + estimated payments.")
    interest: int = Field(default=0, ge=0, description="Taxable interest (1099-INT).")
    dividends: int = Field(default=0, ge=0, description="Ordinary dividends (1099-DIV).")
    self_employment_net: int = Field(default=0, ge=0, description="Net profit from self-employment (Schedule C line 31).")
    other_income: int = Field(default=0, ge=0, description="Other taxable income not in the fields above.")
    itemized_deductions: int | None = Field(default=None, ge=0, description="Total itemized deductions, if itemizing.")

    def total_income(self) -> int:
        return self.wages + self.interest + self.dividends + self.self_employment_net + self.other_income


class CompositionLine(BaseModel):
    """One line of the 'how we got here' breakdown."""

    model_config = ConfigDict(extra="forbid")

    label: str
    amount: int


class RefundEstimate(BaseModel):
    """A preliminary, honest bottom line. ``label`` is always 'ESTIMATE'."""

    model_config = ConfigDict(extra="forbid")

    label: str = _LABEL
    year: int
    filing_status_used: str = Field(description="The status the composition is shown for (primary candidate).")
    status_assumed: bool = Field(description="True when filing status was not confirmed and had to be assumed.")
    low: int = Field(description="Low end of the bottom line (signed: + refund, - owed) — least favorable plausible case.")
    high: int = Field(description="High end (signed) — most favorable plausible case.")
    point: int = Field(description="Bottom line under the primary status (signed: + refund, - owed).")
    headline: str = Field(description="One-line plain-language summary of the range.")
    composition: list[CompositionLine] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    what_would_change_it: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


def _is_married(profile: Profile) -> bool:
    hh = profile.household
    if hh is None or hh.marital_status is None or hh.marital_status.value is None:
        return False
    return str(hh.marital_status.value).strip().lower() in {
        "married", "yes", "true", "married_filing_jointly", "married_filing_separately",
    }


def _candidate_statuses(profile: Profile) -> tuple[list[str], bool]:
    """Return (ordered candidate statuses, status_assumed). Primary is first."""
    hh = profile.household
    if hh is not None and hh.filing_status is not None and hh.filing_status.value:
        return [str(hh.filing_status.value)], False
    if _is_married(profile):
        return ["married_filing_jointly", "married_filing_separately"], True
    if hh is not None and hh.dependents:
        return ["head_of_household", "single"], True  # HoH is the usually-better unmarried-with-dependent path
    return ["single"], True


def _bottom_line(income: IncomeSnapshot, status: str, year: int, knowledge_dir):
    """Compute the signed bottom line for one filing status. Returns (value, composition, citations)."""
    citations: list[Citation] = []
    comp: list[CompositionLine] = []

    comp.append(CompositionLine(label="Total income", amount=income.total_income()))
    half_se = 0
    se_amount = 0
    if income.self_employment_net >= 400:
        se = se_tax(income.self_employment_net, year, knowledge_dir)
        se_amount, half_se = se.se_tax, se.deduction_half
        citations.append(se.citation)
        comp.append(CompositionLine(label="Less: ½ self-employment tax (adjustment)", amount=-half_se))

    agi = income.total_income() - half_se
    comp.append(CompositionLine(label="Adjusted gross income (AGI)", amount=agi))

    if income.itemized_deductions is not None:
        sd = standard_deduction(status, year, knowledge_dir=knowledge_dir)
        deduction = max(income.itemized_deductions, sd.amount)
        label = "Less: itemized deductions" if deduction == income.itemized_deductions else "Less: standard deduction"
        citations.append(sd.citation)
    else:
        sd = standard_deduction(status, year, knowledge_dir=knowledge_dir)
        deduction, label = sd.amount, "Less: standard deduction"
        citations.append(sd.citation)
    comp.append(CompositionLine(label=label, amount=-deduction))

    taxable = max(0, agi - deduction)
    comp.append(CompositionLine(label="Taxable income", amount=taxable))

    tax_res = tax_from_taxable_income(taxable, status, year, knowledge_dir)
    citations.append(tax_res.citation)
    income_tax = tax_res.tax
    comp.append(CompositionLine(label="Income tax", amount=income_tax))
    if se_amount:
        comp.append(CompositionLine(label="Plus: self-employment tax", amount=se_amount))
    total_tax = income_tax + se_amount
    comp.append(CompositionLine(label="Total tax", amount=total_tax))
    comp.append(CompositionLine(label="Less: federal tax withheld / payments", amount=income.federal_withholding))

    bottom = income.federal_withholding - total_tax
    comp.append(CompositionLine(label="Estimated refund (+) or amount owed (-)", amount=bottom))
    return bottom, comp, citations


def estimate_refund(
    profile: Profile,
    year: int,
    income: IncomeSnapshot,
    *,
    knowledge_dir: str | Path | None = None,
) -> RefundEstimate:
    """Compute a preliminary refund/owed RANGE from a partial profile + confirmed income.

    The range width reflects unconfirmed filing status (computed by running the
    deterministic ``calc`` engine under each plausible status); credits and
    unconfirmed/missing documents are surfaced as directional caveats in
    ``what_would_change_it`` rather than folded into a fabricated number. The
    result is always labeled ESTIMATE.

    Args:
        profile: the partial intake profile (filing status, dependents, document
            inventory). Drives which statuses are plausible and which gaps to flag.
        year: tax year.
        income: confirmed dollar amounts from extracted-and-confirmed documents.
        knowledge_dir: override the knowledge directory (installed-wheel use).

    Returns:
        A :class:`RefundEstimate` with low/high/point (signed: + refund, - owed),
        the composition for the primary status, assumptions, what-would-change-it,
        and the calc citations behind the numbers.
    """
    statuses, status_assumed = _candidate_statuses(profile)

    outcomes = {s: _bottom_line(income, s, year, knowledge_dir) for s in statuses}
    primary = statuses[0]
    point, composition, citations = outcomes[primary]
    values = [v for (v, _c, _cit) in outcomes.values()]
    low, high = min(values), max(values)

    # De-duplicate citations by (source, url).
    seen, unique_citations = set(), []
    for c in citations:
        key = (c.source, c.url)
        if key not in seen:
            seen.add(key)
            unique_citations.append(c)

    assumptions: list[str] = []
    if status_assumed:
        assumptions.append(
            f"Filing status not confirmed — showing the range across {', '.join(statuses)}. "
            f"Confirm your status to get a single number."
        )
    else:
        assumptions.append(f"Filing status: {primary}.")
    if income.itemized_deductions is None:
        assumptions.append("Standard deduction assumed (no itemizing, and no age-65+/blind adjustment).")
    assumptions.append("Ordinary tax computation only — qualified dividends / capital gains at preferential rates are not modeled here.")
    assumptions.append("Before unclaimed credits — see what could change it.")

    changes: list[str] = []
    pending = [d for d in profile.income_documents if d.status != "have"]
    if pending:
        kinds = ", ".join(sorted({d.kind for d in pending}))
        changes.append(f"You have unconfirmed or missing documents ({kinds}); confirming them changes income and tightens this estimate.")
    changes.append("Refundable credits (e.g. EITC, Child Tax Credit) are not yet evaluated — they could increase your refund.")
    if income.self_employment_net >= 400:
        changes.append("Self-employment tax is included; quarterly estimated payments you already made would reduce what you owe.")
    if status_assumed:
        changes.append("Confirming your filing status collapses the range to one number.")

    def _phrase(v: int) -> str:
        return f"a refund of about ${v:,}" if v > 0 else (f"owing about ${-v:,}" if v < 0 else "breaking even")

    if low == high:
        headline = f"Estimated bottom line: {_phrase(point)} (before credits)."
    elif low > 0:
        headline = f"Estimated refund between ${low:,} and ${high:,} (before credits)."
    elif high < 0:
        headline = f"You likely owe between ${-high:,} and ${-low:,} (before credits)."
    else:
        headline = f"Estimate ranges from {_phrase(low)} to {_phrase(high)} (before credits)."

    return RefundEstimate(
        year=year,
        filing_status_used=primary,
        status_assumed=status_assumed,
        low=low,
        high=high,
        point=point,
        headline=headline,
        composition=composition,
        assumptions=assumptions,
        what_would_change_it=changes,
        citations=unique_citations,
    )
