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

from taxfill_core import residency
from taxfill_core.calc import (
    additional_medicare_tax,
    niit,
    se_tax,
    standard_deduction,
    tax_from_taxable_income,
)
from taxfill_core.knowledge import Citation
from taxfill_core.schemas.profile import Profile

__all__ = [
    "IncomeSnapshot",
    "CompositionLine",
    "StatusComparison",
    "Roadmap",
    "RefundEstimate",
    "estimate_refund",
]

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


class StatusCandidate(BaseModel):
    """One filing status that was computed, with its signed bottom line."""

    model_config = ConfigDict(extra="forbid")

    status: str
    bottom_line: int = Field(description="Signed bottom line under this status (+ refund, - owed).")


class StatusComparison(BaseModel):
    """MFJ-vs-MFS (and other) side-by-side comparison (eval (l)).

    Shows BOTH amounts, the dollar delta between best and worst, a recommendation
    (the status with the most refund / least owed), and the joint-liability caveat
    whenever both MFJ and MFS are on the table.
    """

    model_config = ConfigDict(extra="forbid")

    candidates: list[StatusCandidate] = Field(description="Every computed status with its signed bottom line.")
    recommended_status: str = Field(description="The status with the highest signed bottom line (most refund / least owed).")
    delta: int = Field(description="Absolute dollar difference between the best and worst computed status.")
    joint_liability_caveat: str | None = Field(
        default=None,
        description=(
            "Set when both MFJ and MFS are candidates: MFJ is jointly-and-severally liable; MFS "
            "avoids that but usually costs more. None otherwise."
        ),
    )


class Roadmap(BaseModel):
    """The personalized roadmap (dev plan section 2 step 3): returns/forms, missing docs, time."""

    model_config = ConfigDict(extra="forbid")

    returns_and_forms: list[str] = Field(
        default_factory=list,
        description="Which federal returns/forms this filer needs (best-effort from residency / us_person).",
    )
    missing_documents: list[str] = Field(
        default_factory=list,
        description="Income documents not yet in hand (status != 'have') — honest gaps, never invented.",
    )
    estimated_time: str = Field(default="", description="Coarse honest estimate of time to finish.")


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
    comparison: StatusComparison | None = Field(
        default=None,
        description="Side-by-side status comparison (eval (l)); present whenever >=2 candidate statuses were computed.",
    )
    roadmap: Roadmap | None = Field(default=None, description="Returns/forms, missing documents, and time-to-finish.")
    assumptions: list[str] = Field(default_factory=list)
    what_would_change_it: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


def _marital(profile: Profile) -> str | None:
    """The closed marital-status fact ('married' / 'unmarried' / 'widowed'), or None."""
    hh = profile.household
    if hh is None or hh.marital_status is None or hh.marital_status.value is None:
        return None
    return str(hh.marital_status.value)


def _is_married(profile: Profile) -> bool:
    return _marital(profile) == "married"


def _confirmed_true(answer) -> bool:
    """True only when an Answer is present with value True (not a gap, not False)."""
    return answer is not None and answer.value is True


def _qss_window_open(hh, year: int | None) -> bool:
    """Qualifying surviving spouse is available ONLY for the two tax years AFTER the spouse's
    death (tax year == death year + 1 or + 2).

    The year of death itself is normally a joint-return year, and more than two years out is
    single/HOH. An unknown death year or unknown tax year returns False (conservative).
    """
    if hh is None or year is None:
        return False
    dy = hh.spouse_death_year
    return dy is not None and dy.value is not None and 1 <= year - dy.value <= 2


def _candidate_statuses(
    profile: Profile, classification: str | None = None, year: int | None = None
) -> tuple[list[str], bool]:
    """Return (ordered candidate statuses, status_assumed). Primary (headline) is first.

    ``classification`` is the computed federal residency result ('resident' /
    'nonresident' / 'dual_status_candidate' / None). A confirmed NONRESIDENT
    alien files Form 1040-NR, which cannot use married_filing_jointly or
    head_of_household, so those statuses are dropped from the candidate set.
    """
    hh = profile.household
    if hh is not None and hh.filing_status is not None and hh.filing_status.value:
        return [str(hh.filing_status.value)], False
    nonresident = classification == "nonresident"
    if _is_married(profile):
        # A nonresident-alien (1040-NR) filer cannot use MFJ; the primary becomes MFS.
        if nonresident:
            return ["married_filing_separately"], True
        return ["married_filing_jointly", "married_filing_separately"], True
    if _marital(profile) == "widowed":
        # Recent widow(er) who maintained a home for a dependent child may file as a
        # qualifying surviving spouse — but ONLY within the death-year window (the two tax
        # years after death). Outside it (unknown death year, the year of death itself, or
        # >2 years out), QSS is unavailable and single is the fallback. Within the window,
        # confirmed-True makes QSS the PRIMARY (headline), symmetric to the HOH branch below;
        # a None fact with dependents keeps QSS as a NON-primary candidate so the range still
        # brackets it; explicitly False never offers QSS.
        if _qss_window_open(hh, year):
            if _confirmed_true(hh.maintained_home_for_dependent_child):
                return ["qualifying_surviving_spouse", "single"], True
            if hh.maintained_home_for_dependent_child is None and hh.dependents:
                return ["single", "qualifying_surviving_spouse"], True
        return ["single"], True
    # Unmarried. Head of household is offered only as the PRIMARY (headline) when the
    # qualifying-person test is confirmed True; otherwise single is the conservative
    # headline but HoH stays in the candidate list (with a dependent) so the range
    # still brackets the HoH outcome. A nonresident alien (1040-NR) cannot use HOH at all.
    if hh is not None and not nonresident and _confirmed_true(hh.hoh_qualifying_person):
        return ["head_of_household", "single"], True
    if hh is not None and not nonresident and hh.dependents:
        return ["single", "head_of_household"], True
    return ["single"], True


_MFJ = "married_filing_jointly"
_MFS = "married_filing_separately"

_JOINT_LIABILITY_CAVEAT = (
    "Filing jointly (MFJ) makes both spouses jointly and severally liable for the whole tax; "
    "filing separately (MFS) avoids that shared liability but usually costs more in tax. Weigh "
    "the dollar difference against the liability you take on."
)

# Mirrors intake.py's §6013(g)/(h) wording: a nonresident alien filing 1040-NR cannot
# use MFJ unless they elect to be treated as a U.S. resident, which taxes worldwide income.
_SECTION_6013_CAVEAT = (
    "As a nonresident alien (Form 1040-NR) you cannot file jointly (MFJ); filing jointly "
    "requires electing under §6013(g)/(h) to treat the nonresident alien as a U.S. resident "
    "— which makes their worldwide income taxable. Showing married-filing-separately instead."
)

# When residency is not yet computable for a visa holder, the 1040-NR restriction is conditional.
_SECTION_6013_CONDITIONAL_CAVEAT = (
    "If your residency result is nonresident alien, Form 1040-NR cannot use MFJ/HOH; filing "
    "jointly would then require electing under §6013(g)/(h) to treat the nonresident alien as a "
    "U.S. resident — which makes their worldwide income taxable. Confirm your residency to "
    "tighten this."
)


def _build_comparison(outcomes: dict[str, tuple[int, list, list]]) -> StatusComparison | None:
    """Build the side-by-side comparison when >=2 statuses were computed (eval (l))."""
    if len(outcomes) < 2:
        return None
    candidates = [StatusCandidate(status=s, bottom_line=v) for s, (v, _c, _cit) in outcomes.items()]
    values = [c.bottom_line for c in candidates]
    # Recommended = the most-favorable signed bottom line (most refund / least owed).
    recommended = max(candidates, key=lambda c: c.bottom_line).status
    delta = abs(max(values) - min(values))
    statuses = {c.status for c in candidates}
    caveat = _JOINT_LIABILITY_CAVEAT if {_MFJ, _MFS} <= statuses else None
    return StatusComparison(
        candidates=candidates,
        recommended_status=recommended,
        delta=delta,
        joint_liability_caveat=caveat,
    )


def _classify_residency(profile: Profile, year: int):
    """Best-effort residency classification from the profile, or None when not computable."""
    rf = profile.residency_facts
    imm = profile.immigration
    if rf is None or not rf.days_in_us or imm is None or not imm.visa_timeline:
        return None
    days_by_year = {y: a.value for y, a in rf.days_in_us.items() if a is not None and a.value is not None}
    if not days_by_year:
        return None
    try:
        return residency.classify(imm.visa_timeline, days_by_year, year)
    except (ValueError, AssertionError):
        # An incomplete/contradictory timeline cannot be classified yet — fall back
        # to the us_person best-effort rather than guessing.
        return None


def _build_roadmap(profile: Profile, year: int, result=None) -> Roadmap:
    """Returns/forms (from residency when computable, else us_person), missing docs, time."""
    forms: list[str] = []
    if result is not None:
        if result.classification == "resident":
            forms = ["Form 1040"]
        elif result.classification == "nonresident":
            forms = ["Form 1040-NR", "Form 8843"]
        else:  # dual_status_candidate — both may apply for one split year
            forms = ["Form 1040", "Form 1040-NR (dual-status: both may apply for the split year)", "Form 8843"]
    else:
        ident = profile.identity
        if ident is not None and ident.us_person is not None and ident.us_person.value is True:
            forms = ["Form 1040"]
        elif ident is not None and ident.us_person is not None and ident.us_person.value is False:
            forms = ["Form 1040-NR", "Form 8843"]

    missing = sorted({d.kind for d in profile.income_documents if d.status != "have"})

    if missing:
        time = "Roughly 1-2 hours once the missing documents are in hand."
    elif profile.income_documents:
        time = "Roughly 30-60 minutes — the income documents are in hand."
    else:
        time = "Hard to estimate until the income documents are inventoried."

    return Roadmap(returns_and_forms=forms, missing_documents=missing, estimated_time=time)


def _bottom_line(income: IncomeSnapshot, status: str, year: int, knowledge_dir, *, nonresident: bool = False):
    """Compute the signed bottom line for one filing status. Returns (value, composition, citations).

    ``nonresident`` skips NIIT (Form 8960 does not apply to nonresident aliens);
    Additional Medicare Tax applies to NRA Medicare wages, so it is kept.
    """
    citations: list[Citation] = []
    comp: list[CompositionLine] = []

    comp.append(CompositionLine(label="Total income", amount=income.total_income()))
    half_se = 0
    se_amount = 0
    if income.self_employment_net >= 400:
        # Schedule SE lines 8a-9: W-2 wages consume the social-security wage base first
        # (box-1 wages stand in for box-3 SS wages — disclosed as an assumption).
        se = se_tax(income.self_employment_net, year, knowledge_dir, w2_ss_wages=income.wages)
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

    # High-income surtaxes (Schedule 2 lines 11/12). Computed on the same deterministic
    # engine; zero for most filers, so composition lines appear only when they bite.
    addmed_amount = 0
    if income.wages or income.self_employment_net:
        addmed = additional_medicare_tax(
            income.wages, status, year, se_net_profit=income.self_employment_net, knowledge_dir=knowledge_dir
        )
        if addmed.additional_medicare_tax:
            addmed_amount = addmed.additional_medicare_tax
            citations.append(addmed.citation)
            comp.append(
                CompositionLine(
                    label="Plus: Additional Medicare Tax (Form 8959, 0.9% over threshold)",
                    amount=addmed_amount,
                )
            )

    niit_amount = 0
    investment_income = income.interest + income.dividends
    if investment_income and not nonresident:  # NRAs are generally not subject to NIIT
        niit_res = niit(investment_income, agi, status, year, knowledge_dir=knowledge_dir)
        if niit_res.niit:
            niit_amount = niit_res.niit
            citations.append(niit_res.citation)
            comp.append(
                CompositionLine(
                    label="Plus: Net investment income tax (Form 8960, 3.8% over MAGI threshold)",
                    amount=niit_amount,
                )
            )

    total_tax = income_tax + se_amount + addmed_amount + niit_amount
    comp.append(CompositionLine(label="Total tax", amount=total_tax))
    # Negative, like every other "Less:" composition line (it reduces what you owe).
    comp.append(CompositionLine(label="Less: federal tax withheld / payments", amount=-income.federal_withholding))

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
    # Classify residency once and thread it into both status selection and the roadmap
    # (H1): a confirmed nonresident alien files 1040-NR, which cannot use MFJ/HOH.
    residency_result = _classify_residency(profile, year)
    classification = residency_result.classification if residency_result is not None else None

    statuses, status_assumed = _candidate_statuses(profile, classification, year)

    outcomes = {
        s: _bottom_line(income, s, year, knowledge_dir, nonresident=(classification == "nonresident"))
        for s in statuses
    }
    primary = statuses[0]
    point, composition, citations = outcomes[primary]
    values = [v for (v, _c, _cit) in outcomes.values()]
    low, high = min(values), max(values)

    comparison = _build_comparison(outcomes)
    roadmap = _build_roadmap(profile, year, residency_result)

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
    labels = " ".join(line.label for line in composition)
    if "Form 8959" in labels:
        assumptions.append(
            "Additional Medicare Tax (Form 8959) included: 0.9% of wages/SE earnings over the status "
            "threshold. Box 1 wages stand in for box 5 Medicare wages; if your employer already withheld "
            "extra Medicare tax (W-2 box 6 above 1.45% of box 5), include that excess in the withholding "
            "input — it credits against this."
        )
    if "Form 8960" in labels:
        assumptions.append(
            "Net investment income tax (Form 8960) included: 3.8% of interest + dividends over the MAGI "
            "threshold, with MAGI approximated by AGI. Capital gains and other investment income are not "
            "captured by this snapshot and would increase it."
        )
    if income.wages and income.self_employment_net >= 400:
        assumptions.append(
            "Self-employment tax applies Schedule SE lines 8a-9 (W-2 wages consume the Social Security "
            "wage base first), using box-1 wages as the box-3 proxy — box 3 can differ (e.g. 401(k) deferrals)."
        )
    if status_assumed and {"married_filing_jointly", "married_filing_separately"} <= set(statuses):
        assumptions.append(
            "The married-filing-separately figure puts ALL combined income and withholding on one MFS "
            "return — a worst-case bound, not a real two-return MFS outcome. Provide each spouse's own "
            "amounts for a true MFJ-vs-MFS comparison."
        )
    assumptions.append(
        "Not modeled in this estimate: above-the-line adjustments (student-loan interest, IRA/HSA), "
        "capital gains/losses, taxable Social Security benefits, premium-tax-credit reconciliation "
        "(Form 8962), education credits, excess Social Security withholding (multiple employers), "
        "and AMT — each could change the number."
    )
    assumptions.append("Before unclaimed credits — see what could change it.")

    # §6013(g)/(h) caveat (H1): surfaced in BOTH assumptions and what-would-change-it.
    ident = profile.identity
    us_person_false = (
        ident is not None and ident.us_person is not None and ident.us_person.value is False
    )
    residency_caveat: str | None = None
    if classification == "nonresident" and _is_married(profile):
        # MFJ was dropped for a confirmed married NRA — explain the §6013 election.
        residency_caveat = _SECTION_6013_CAVEAT
    elif classification is None and us_person_false:
        # Visa holder whose residency is not yet determined — frame it conditionally.
        residency_caveat = _SECTION_6013_CONDITIONAL_CAVEAT
    if residency_caveat is not None:
        assumptions.append(residency_caveat)

    changes: list[str] = []
    if residency_caveat is not None:
        changes.append(residency_caveat)
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
        comparison=comparison,
        roadmap=roadmap,
        assumptions=assumptions,
        what_would_change_it=changes,
        citations=unique_citations,
    )
