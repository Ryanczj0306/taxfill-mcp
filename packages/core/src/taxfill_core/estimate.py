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
- credits are ESTIMATED whenever their inputs are present (CTC/ODC, EITC,
  AOTC, the dependent-care credit, premium tax credit, excess-SS
  withholding), with every approximation disclosed as an assumption — never
  silently omitted and never silently invented;
- qualified dividends / net capital gain use the preferential-rate worksheet
  (``calc.tax_with_preferential_rates``) whenever such income is present — for
  RESIDENTS only: a nonresident's investment income follows ECI/FDAP rules the
  estimate does not model, so it is taxed at ordinary rates and disclosed;
- a nonresident's US bank-deposit interest is EXCLUDED when the snapshot
  characterizes it (``bank_deposit_interest``, IRC 871(i)(2)(A) — N-8, P-013):
  the amount excluded and the statute are disclosed, interest entered without
  that character is taxed as effectively connected income and SAID to be, and
  on a joint return (which a nonresident reaches only through the §6013(g)/(h)
  election) the exclusion is switched OFF, because the election — not the
  marriage — makes the payee a resident;
- the §6013(g)/(h) election is RESIDENCY, applied before any rule runs
  (P-018): recorded as ``residency_facts.section_6013_election`` on a household
  married for the year (the year of a spouse's death included), or read from
  a confirmed joint status of a filer whose own residency is nonresident — a
  joint return that exists only under the election — it makes both spouses
  "residents for your entire tax year" (Pub 519 ch. 1), so the standard
  deduction, the preferential rates and NIIT apply and the deposit exclusion
  is off on a joint AND a separate status, while FICA keeps following the
  day-count answer (IRC 6013(g)(1) reaches chapters 1 and 24 only). Its texts
  quote IRC 6013(g) or 6013(h) — two choices with different statements,
  durations and NIIT defaults — whichever the facts point to. It is NOT
  applied onto a status with no spouse, nor when the recorded facts show
  neither spouse a U.S. citizen or resident (IRC 6013(g)(3)); a recorded
  DECLINE drops married-filing-jointly for a couple with a nonresident in it,
  and a joint status those facts rule out is priced married-filing-separately
  with the contradiction named first;
- each spouse's separate (two-return MFS) return follows that spouse's OWN
  classification (P-018), never the taxpayer's: a US-citizen spouse's Form
  1040 gets the standard deduction (unless the couple itemizes — IRC
  63(c)(6)(A); both methods are priced) and the preferential rates; a
  nonresident spouse's Form 1040-NR gets no standard deduction and, in this
  estimate, ordinary rates on investment income (the graduated rates are the
  same; FDAP is not modeled — disclosed); a spouse of unknown residency is
  priced both ways in the range.

The profile supplies the qualitative picture (filing status, dependents, which
documents are still missing); ``income`` supplies the confirmed dollar amounts
from extracted-and-confirmed documents (the profile schema holds an inventory,
not amounts).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taxfill_core import residency
from taxfill_core.calc import (
    additional_medicare_tax,
    dependent_care_credit,
    education_credits,
    excess_ss,
    irs_round,
    niit,
    ptc_annual,
    se_tax,
    standard_deduction,
    student_loan_interest_deduction,
    tax_from_taxable_income,
    tax_with_preferential_rates,
    taxable_social_security,
    treaty_benefit,
)
from taxfill_core.knowledge import Citation, form_line, load_knowledge, load_treaty, provisional_marker
from taxfill_core.schemas.profile import Profile

__all__ = [
    "IncomeSnapshot",
    "CompositionLine",
    "BottomLineResult",
    "DeltaLine",
    "MissingBlock",
    "StatusComparison",
    "Roadmap",
    "RefundEstimate",
    "estimate_refund",
]

_LABEL = "ESTIMATE"
# The forward-looking sibling (H4): a bottom line computed on a PROVISIONAL
# (planning-only) pack is labeled PROJECTION, never ESTIMATE. ESTIMATE means
# "partial data for a CLOSED year — this converges to the filed number";
# PROJECTION means "a future year whose forms do not exist — this can never
# converge to a filed number, and fill/verify refuse the year outright".
_PROJECTION_LABEL = "PROJECTION"

# One dependent as threaded into the per-status computation: (age at the end of
# the tax year, or None when the date of birth is unknown; has_ssn as answered).
_DepInfo = tuple[int | None, bool | None]


class IncomeSnapshot(BaseModel):
    """Confirmed dollar amounts so far (whole dollars).

    Every field defaults to 0 so an estimate can run off a single confirmed
    document. ``itemized_deductions`` is None unless the user is itemizing (then
    the larger of it and the standard deduction is used). For a married couple,
    amounts are taxpayer + spouse COMBINED unless ``spouse`` is provided — then
    this snapshot is the primary taxpayer's own amounts and ``spouse`` carries the
    other spouse's, enabling a TRUE two-return MFS comparison (MFJ combines them).
    """

    model_config = ConfigDict(extra="forbid")

    wages: int = Field(default=0, ge=0, description="W-2 box 1 wages (all W-2s).")
    federal_withholding: int = Field(default=0, ge=0, description="Federal income tax withheld + estimated payments.")
    interest: int = Field(default=0, ge=0, description="Taxable interest (1099-INT).")
    bank_deposit_interest: int = Field(
        default=0, ge=0,
        description=(
            "The part of `interest` that is interest on DEPOSITS — with a US bank (a person carrying on "
            "the banking business), a savings institution (S&L / credit union / building and loan), or an "
            "insurance company holding amounts under an agreement to pay interest (IRC 871(i)(3)) — and "
            "that is NOT effectively connected with a US trade or business. A SUBSET of `interest`, like "
            "qualified_dividends of dividends (enter the deposit portion of 1099-INT box 1 in BOTH). For a "
            "NONRESIDENT alien this amount is excluded from income: IRC 871(i)(1)-(2)(A) impose no tax on "
            "'interest on deposits, if such interest is not effectively connected with the conduct of a "
            "trade or business within the United States'; Pub 519 ch. 3 (Exclusions From Gross Income — "
            "Interest Income) excludes it from gross income; the Instructions for Form 1040-NR (line 2b, "
            "Exception 3) say not to report it on line 2b. For a RESIDENT it changes nothing (all interest "
            "is taxable). Under the §6013(g)/(h) election, which treats both spouses as residents for the "
            "whole year (Pub 519 ch. 1), it is taxed on a JOINT and on a SEPARATE return alike (a joint "
            "return is the only way a nonresident reaches one): the election, not the marriage, ends the "
            "exclusion. Interest left in `interest` "
            "without this character is taxed here as effectively connected ordinary income. Treasury / "
            "savings-bond interest (1099-INT box 3) and bond interest are NOT deposits — leave them out."
        ),
    )
    dividends: int = Field(default=0, ge=0, description="Ordinary dividends, 1099-DIV box 1a (includes qualified).")
    qualified_dividends: int = Field(
        default=0, ge=0,
        description="1099-DIV box 1b — the subset of `dividends` taxed at preferential rates.",
    )
    capital_gain_long: int = Field(
        default=0,
        description="Net LONG-term capital gain (+) or loss (-) — 1099-B/Schedule D. Signed.",
    )
    capital_gain_short: int = Field(
        default=0,
        description="Net SHORT-term capital gain (+) or loss (-) — taxed as ordinary income. Signed.",
    )
    self_employment_net: int = Field(
        default=0,
        description="Net profit (+) or loss (-) from self-employment (Schedule C line 31). Signed.",
    )
    retirement_income_taxable: int = Field(
        default=0, ge=0,
        description=(
            "The TAXABLE amount of IRA distributions and pensions/annuities — what Form 1040's two "
            "'taxable amount' lines for them take — taxed as ordinary income. It is NOT simply 1099-R box "
            "2a: for a traditional-IRA distribution or a Roth conversion the payer reports the GROSS "
            "amount in box 2a with box 2b 'Taxable amount not determined' checked (Instructions for "
            "Forms 1099-R and 5498 (2026): 'report the total amount distributed from a traditional IRA "
            "in box 2a. This will be the same amount reported in box 1'), so a filer with nondeductible "
            "basis would overstate AGI by that basis — run calc op ira_pro_rata (Form 8606) and enter "
            "its taxable figure. Box 7 codes N and R (a recharacterized IRA contribution) and H (a "
            "designated Roth account rolled directly to a Roth IRA) are $0 taxable; code G (a direct "
            "rollover) is $0 too when box 2a is -0-, EXCEPT where the payer puts the taxable amount in box "
            "2a: a direct rollover from a pre-tax plan to a Roth IRA (calc op roth_conversion, source "
            "plan_to_roth_ira) or to a designated Roth account in the same plan (an in-plan Roth rollover), "
            "and designated Roth matching/nonelective contributions."
        ),
    )
    social_security_benefits: int = Field(
        default=0, ge=0,
        description="SSA-1099 box 5 net benefits; the TAXABLE portion is computed by the engine (0-85%).",
    )
    other_income: int = Field(default=0, ge=0, description="Other taxable income not in the fields above.")
    treaty_exempt_income: int = Field(
        default=0, ge=0,
        description=(
            "Income exempt under a tax treaty (1042-S box 2, or the treaty-exempt part of W-2 wages when the "
            "employer did not honor the treaty) — excluded from income before tax. WHERE it is reported "
            "turns on residency (P-016): a nonresident uses Schedule OI item L and the Form 1040-NR "
            "treaty-exempt line; a RESIDENT alien claiming a saving-clause exception enters it in "
            "parentheses on Schedule 1's other-income line with 'Exempt income', the country and the "
            "article (Pub 519 ch. 9). The estimate's assumption names the year's line for the profile's "
            "classification. The treaty country, article, dollar cap, and saving-clause analysis are the "
            "AGENT'S confirmed judgment (trust-the-agent semantics, like itemized_deductions) — the engine "
            "does not validate treaty eligibility."
        ),
    )
    student_loan_interest_paid: int = Field(
        default=0, ge=0,
        description="1098-E box 1 — the engine applies the $2,500 cap and the MAGI phase-out (MFS: not allowed).",
    )
    pre_agi_adjustments: int = Field(
        default=0, ge=0,
        description=(
            "Other above-the-line adjustments the agent has CONFIRMED eligible (IRA/HSA/educator...); "
            "eligibility and limits are the agent's judgment, like itemized_deductions."
        ),
    )
    ss_withheld_by_employer: list[int] = Field(
        default_factory=list,
        description="W-2 box 4 Social Security tax withheld, ONE ENTRY PER EMPLOYER (excess-SS credit needs 2+).",
    )
    aotc_qualified_expenses: list[int] = Field(
        default_factory=list,
        description="AOTC-qualified education expenses, one entry per eligible student (1098-T-informed).",
    )
    dependent_care_expenses: int = Field(
        default=0, ge=0,
        description=(
            "Qualified child/dependent-care expenses paid so you (and your spouse) could work — the "
            "Form 2441 line 2 total, BEFORE the caps. Household-level: put it on the primary snapshot."
        ),
    )
    dependent_care_persons: int = Field(
        default=0, ge=0,
        description=(
            "Number of qualifying persons the care expenses were for (child under 13 / spouse or "
            "dependent incapable of self-care) — 1 vs 2+ sets the Form 2441 expense cap."
        ),
    )
    aca_premiums: int = Field(default=0, ge=0, description="Form 1095-A line 33A — annual enrollment premiums.")
    aca_slcsp: int = Field(default=0, ge=0, description="Form 1095-A line 33B — annual SLCSP premiums.")
    aca_aptc: int = Field(default=0, ge=0, description="Form 1095-A line 33C — annual advance PTC paid.")
    itemized_deductions: int | None = Field(default=None, ge=0, description="Total itemized deductions, if itemizing.")
    spouse: "IncomeSnapshot | None" = Field(
        default=None,
        description="The spouse's own amounts (enables a true two-return MFS comparison). One level only.",
    )

    @model_validator(mode="after")
    def _check_internal_consistency(self) -> "IncomeSnapshot":
        if self.qualified_dividends > self.dividends:
            raise ValueError(
                f"qualified_dividends ({self.qualified_dividends}) cannot exceed dividends "
                f"({self.dividends}) — box 1b is a subset of box 1a"
            )
        if self.bank_deposit_interest > self.interest:
            raise ValueError(
                f"bank_deposit_interest ({self.bank_deposit_interest}) cannot exceed interest "
                f"({self.interest}) — it is the deposit-character SUBSET of the 1099-INT box 1 total, so "
                f"enter the deposit portion in both fields"
            )
        if self.dependent_care_expenses > 0 and self.dependent_care_persons < 1:
            raise ValueError(
                f"dependent_care_expenses ({self.dependent_care_expenses}) requires "
                f"dependent_care_persons >= 1 — the number of qualifying persons sets the Form 2441 "
                f"expense cap, so the credit cannot be estimated without it (never silently dropped)"
            )
        if self.spouse is not None and self.spouse.spouse is not None:
            raise ValueError("spouse.spouse must be None — one nesting level only")
        return self

    def total_income(self) -> int:
        """Ordinary-income components only — capital gains/losses and the taxable part of
        Social Security are status-dependent and computed by the estimate, not here."""
        return (
            self.wages + self.interest + self.dividends + self.self_employment_net
            + self.retirement_income_taxable + self.other_income
        )

    def combined_with_spouse(self) -> "IncomeSnapshot":
        """The MFJ view: every amount summed across both spouses (lists concatenated).

        ``dependent_care_persons`` is household-level, so the combined view takes
        the MAX (the same qualifying persons must never double the expense cap)."""
        if self.spouse is None:
            return self
        s = self.spouse
        return IncomeSnapshot(
            **{
                f: getattr(self, f) + getattr(s, f)
                for f in (
                    "wages", "federal_withholding", "interest", "bank_deposit_interest", "dividends",
                    "qualified_dividends",
                    "capital_gain_long", "capital_gain_short", "self_employment_net",
                    "retirement_income_taxable", "social_security_benefits", "other_income",
                    "treaty_exempt_income", "student_loan_interest_paid", "pre_agi_adjustments",
                    "dependent_care_expenses", "aca_premiums", "aca_slcsp", "aca_aptc",
                )
            },
            ss_withheld_by_employer=[*self.ss_withheld_by_employer, *s.ss_withheld_by_employer],
            aotc_qualified_expenses=[*self.aotc_qualified_expenses, *s.aotc_qualified_expenses],
            dependent_care_persons=max(self.dependent_care_persons, s.dependent_care_persons),
            itemized_deductions=(
                None
                if self.itemized_deductions is None and s.itemized_deductions is None
                else (self.itemized_deductions or 0) + (s.itemized_deductions or 0)
            ),
        )


class CompositionLine(BaseModel):
    """One line of the 'how we got here' breakdown — and one row of a reconciling LEDGER.

    The breakdown reads as a worksheet narrative (income → AGI → taxable income →
    tax → credits → payments), so the raw ``amount`` column deliberately mixes
    altitudes and does NOT sum to the bottom line. ``slot``/``role``/``effect``
    are the machine-readable layer underneath the narrative:

    * ``slot`` — a stable key from the closed ``_LEDGER_SLOTS`` registry, so two
      computations of the same shape (two filing statuses, two scenarios, two
      years) can be diffed row-by-row instead of by fuzzy label matching.
    * ``role`` — ``operand`` rows are the ones that independently move the bottom
      line; ``explanatory`` rows (income items, adjustments, the deduction) only
      explain HOW the income-tax operand got its magnitude; ``subtotal`` rows
      (Total income, AGI, Taxable income, Total tax, the bottom line itself) are
      printed running totals.
    * ``effect`` — the row's signed contribution to the bottom line (+ pushes
      toward refund). Zero for every non-operand row. The invariant the whole
      Phase H stack leans on: ``sum(line.effect) == bottom``, exactly, in
      integers — enforced at runtime by ``_reconcile``, so a new line added
      without its effect fails loudly instead of silently unbalancing every
      downstream delta.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    amount: int
    slot: str = Field(default="", description="Stable ledger key from _LEDGER_SLOTS ('' only in legacy constructions).")
    role: Literal["operand", "explanatory", "subtotal"] = Field(
        default="explanatory",
        description="operand = independently moves the bottom line; explanatory/subtotal = narrative only.",
    )
    effect: int = Field(
        default=0,
        description="Signed contribution to the bottom line (+ toward refund); 0 for non-operand rows.",
    )


_OPERAND, _EXPLANATORY, _SUBTOTAL = "operand", "explanatory", "subtotal"

# The closed slot registry. Adding a composition line means adding its slot HERE
# first — _line() refuses unknown slots, so the ledger vocabulary can never grow
# by accident, and every consumer (status comparison today; H4's projection and
# H7's scenario diff next) can treat the set as total.
_LEDGER_SLOTS: dict[str, str] = {
    # narrative (effect 0)
    "capital_gain": _EXPLANATORY,
    "capital_loss": _EXPLANATORY,
    "taxable_social_security": _EXPLANATORY,
    "treaty_exempt_exclusion": _EXPLANATORY,
    "deposit_interest_exclusion": _EXPLANATORY,
    "half_se_adjustment": _EXPLANATORY,
    "student_loan_interest_deduction": _EXPLANATORY,
    "other_adjustments": _EXPLANATORY,
    "deduction": _EXPLANATORY,
    "total_income": _SUBTOTAL,
    "agi": _SUBTOTAL,
    "taxable_income": _SUBTOTAL,
    "total_tax": _SUBTOTAL,
    "bottom_line": _SUBTOTAL,
    # operands (effect = -amount unless overridden)
    "income_tax": _OPERAND,
    "education_credits_nonrefundable": _OPERAND,
    "dependent_care_credit_nonrefundable": _OPERAND,
    "odc_nonrefundable": _OPERAND,
    "ctc_odc_nonrefundable": _OPERAND,
    "se_tax": _OPERAND,
    "additional_medicare_tax": _OPERAND,
    "niit": _OPERAND,
    "aptc_repayment": _OPERAND,
    "withholding": _OPERAND,
    "excess_ss_credit": _OPERAND,
    "actc_refundable": _OPERAND,
    "ctc_refundable_2021": _OPERAND,
    "dependent_care_credit_refundable_2021": _OPERAND,
    "eitc": _OPERAND,
    "aotc_refundable": _OPERAND,
    "net_ptc": _OPERAND,
    # the true-two-return MFS path folds the spouse's whole return into one row;
    # its effect is +amount (the spouse's bottom line adds directly), the one
    # exception to effect = -amount.
    "spouse_mfs_return": _OPERAND,
}


def _line(slot: str, label: str, amount: int, *, effect: int | None = None) -> CompositionLine:
    """Build a ledger-aware composition line; the slot decides the role and default effect."""
    role = _LEDGER_SLOTS.get(slot)
    if role is None:
        raise RuntimeError(
            f"composition slot {slot!r} is not in _LEDGER_SLOTS — register it (and decide its role) "
            f"before emitting it; the closed registry is what keeps status/scenario diffs total"
        )
    if effect is None:
        effect = -amount if role == _OPERAND else 0
    if role != _OPERAND and effect != 0:
        raise RuntimeError(f"slot {slot!r} is {role}, whose effect must be 0 — got {effect}")
    return CompositionLine(label=label, amount=amount, slot=slot, role=role, effect=effect)


def _reconcile(bottom: int, lines: list[CompositionLine]) -> None:
    """Enforce the ledger invariant: the operand effects sum EXACTLY to the bottom line.

    Runs on every computation (it is integer arithmetic over a few dozen rows, not
    a test-only property), so a composition line added without its effect — or an
    operand mislabeled explanatory — fails the very first estimate it touches
    instead of silently unbalancing every downstream comparison and scenario diff.
    """
    unslotted = [ln.label for ln in lines if ln.slot not in _LEDGER_SLOTS]
    if unslotted:
        raise RuntimeError(
            f"composition line(s) built without a registered slot: {unslotted} — construct lines "
            f"via _line() so the ledger stays total"
        )
    total_effect = sum(ln.effect for ln in lines)
    if total_effect != bottom:
        by_slot = {ln.slot: ln.effect for ln in lines if ln.effect}
        raise RuntimeError(
            f"ledger does not reconcile: sum(effect) = {total_effect} but bottom = {bottom} "
            f"(residue {bottom - total_effect}); nonzero effects: {by_slot}. A line that moves "
            f"the bottom line was added without its effect (or with the wrong sign) — fix the "
            f"emitting site, never this check."
        )


class BottomLineResult(BaseModel):
    """One filing status's computed bottom line with its reconciling ledger."""

    model_config = ConfigDict(extra="forbid")

    bottom: int = Field(description="Signed bottom line (+ refund, - owed).")
    lines: list[CompositionLine]
    citations: list[Citation]


class MissingBlock(BaseModel):
    """A knowledge block an INPUT engaged but the year's pack does not carry.

    The machine-readable twin of the 'NOT ESTIMATED' assumptions: same gates,
    same computation, produced side by side — prose for the human, this for the
    consumers (H4's projection contract and H7's scenario diff need to know which
    rows of a planning-year ledger are missing rather than zero).
    """

    model_config = ConfigDict(extra="forbid")

    block: str = Field(description="Pack path of the absent block, e.g. 'credits.child_tax_credit'.")
    item: str = Field(description="The human item that went unpriced, e.g. 'child tax credit / ODC (and EITC)'.")
    direction: Literal["understates_refund", "overstates_refund", "either"] = Field(
        description="Which way the ABSENCE skews this estimate's bottom line."
    )


class StatusCandidate(BaseModel):
    """One filing status that was computed, with its signed bottom line."""

    model_config = ConfigDict(extra="forbid")

    status: str
    bottom_line: int = Field(description="Signed bottom line under this status (+ refund, - owed).")


class DeltaLine(BaseModel):
    """One ledger row of the best-vs-worst diff: WHERE the dollar difference comes from.

    ``delta`` is the row's contribution to the headline difference (best minus
    worst, in bottom-line effect terms). The rows sum EXACTLY to
    ``StatusComparison.delta`` — enforced at construction — which is the table a
    caller would otherwise rebuild by hand.
    """

    model_config = ConfigDict(extra="forbid")

    slot: str = Field(description="Ledger slot from the closed registry (same key on both sides).")
    label: str = Field(description="Human label for the row (taken from the best side when both have it).")
    best_effect: int = Field(description="This slot's signed bottom-line effect under the recommended status.")
    worst_effect: int = Field(description="This slot's signed bottom-line effect under the worst status.")
    delta: int = Field(description="best_effect - worst_effect; the rows sum exactly to the headline delta.")


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
    delta_lines: list[DeltaLine] = Field(
        default_factory=list,
        description=(
            "Itemized best-vs-worst attribution: which ledger slots the delta comes from, largest "
            "first. The rows sum exactly to `delta` — a diff that does not reconcile is never emitted."
        ),
    )
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
    """A preliminary, honest bottom line.

    ``label`` is the output CONTRACT (H4): 'ESTIMATE' for a closed year (partial
    data converging to the filed number) and 'PROJECTION' for a planning year
    computed on a provisional pack (can never converge to a filed number —
    fill/verify refuse the year, and `provisional`/`missing_blocks` say why).
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        default=_LABEL,
        description="'ESTIMATE' (closed year) or 'PROJECTION' (planning year on a provisional pack).",
    )
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
    provisional: dict | None = Field(
        default=None,
        description=(
            "Set when the year's knowledge pack is planning-only (authored before that year's forms "
            "published). The bottom line is then PROJECTION-grade: sound for budgeting, never for a "
            "filed return. Absent on filing-grade years."
        ),
    )
    missing_blocks: list[MissingBlock] = Field(
        default_factory=list,
        description=(
            "Knowledge blocks an input ENGAGED but the year's pack does not carry — the structured twin "
            "of the 'NOT ESTIMATED' assumptions. Empty on a fully-covered year; never silently empty on "
            "a planning year whose absent blocks were engaged."
        ),
    )
    assumptions: list[str] = Field(default_factory=list)
    what_would_change_it: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    residency_caveat: str | None = Field(
        default=None,
        description=(
            "The residency caveat these figures ran under (also in assumptions and what_would_change_it): the "
            "§6013(g)/(h) election in effect (P-018), a dual-status year, or a nonresident spouse direction — "
            "None when there is none. compare_scenarios surfaces it per scenario."
        ),
    )


def _marital(profile: Profile) -> str | None:
    """The closed marital-status fact ('married' / 'unmarried' / 'widowed'), or None."""
    hh = profile.household
    if hh is None or hh.marital_status is None or hh.marital_status.value is None:
        return None
    return str(hh.marital_status.value)


def _is_married(profile: Profile) -> bool:
    return _marital(profile) == "married"


def _married_for_year(profile: Profile, year: int | None) -> bool:
    """Married for the tax year's filing-status purposes: married on Dec 31, or widowed
    in the tax year itself. Pub 501 (2025), Spouse died during the year: "If your spouse
    died during the year, you are considered married for the whole year for filing
    status purposes. If you didn't remarry before the end of the tax year, you can file
    a joint return for yourself and your deceased spouse." The §6013(g)/(h) election
    survives that year too — Pub 519 ch. 1, Ending the Choice: "The death of either
    spouse ends the choice, beginning with the first tax year following the year the
    spouse died."
    """
    marital = _marital(profile)
    if marital == "married":
        return True
    hh = profile.household
    return (
        marital == "widowed" and year is not None and hh is not None and hh.spouse_death_year is not None
        and hh.spouse_death_year.value == year
    )


def _confirmed_status(profile: Profile) -> str | None:
    hh = profile.household
    if hh is None or hh.filing_status is None or not hh.filing_status.value:
        return None
    return str(hh.filing_status.value)


_MARRIED_STATUSES = ("married_filing_jointly", "married_filing_separately")


def _election_marriage_ok(profile: Profile, year: int | None) -> bool:
    """The marriage the §6013(g)/(h) election needs, on a figure that has a spouse (P-018).

    Married for the year, or an unanswered marital status with a confirmed married
    status — MFJ or MFS is itself a statement of marriage (Pub 501: "You can choose
    married filing separately as your filing status if you are married"). Never onto
    a status with no spouse on it: a confirmed single / head-of-household / QSS status,
    or the year of a spouse's death with no confirmed status, whose only candidate
    here is 'single' (the candidate gap JF1b.9 closes). An explicit 'unmarried' (or a
    widowed status outside the year of death) is not a marriage at all.
    """
    status = _confirmed_status(profile)
    if status is not None and status not in _MARRIED_STATUSES:
        return False
    if status is None and _marital(profile) != "married":
        return False
    if _married_for_year(profile, year):
        return True
    return _marital(profile) is None and status in _MARRIED_STATUSES


def _election_not_applied_reason(profile: Profile, year: int | None, *, unavailable: bool = False) -> str:
    """Why a recorded election was not applied on the marriage test (P-018) — the facts as
    they stand, never a guessed 'not married' for an unanswered question. ``unavailable``:
    the IRC 6013(g)(3) facts hold, which answers first (intake says the same)."""
    status = _confirmed_status(profile)
    marital = _marital(profile)
    if unavailable and _married_for_year(profile, year):
        if marital == "married":
            # The residency caveat already quotes the rule in full for a married nonresident.
            return (
                "neither spouse is a U.S. citizen or resident at any time in the year on the recorded facts, so the "
                "election does not apply (IRC 6013(g)(3) — the residency caveat quotes it)"
            )
        return residency.SECTION_6013_SUSPENDED.rstrip(".") + (
            ". This estimate prices 'single' only in the year of your spouse's death (JF1b.9) — Pub 501: \"If your "
            "spouse died during the year, you are considered married for the whole year for filing status purposes\""
            if status is None else ""
        )
    if status == "head_of_household":
        return (
            "the confirmed status is head of household, which exists only WITHOUT the election (Pub 501, Considered "
            "Unmarried: \"You are considered unmarried for head of household purposes if your spouse was a "
            "nonresident alien at any time during the year and you don't choose to treat your nonresident spouse as "
            "a resident alien\") — for an election made in an earlier year that means ending it, and Pub 519 ch. 1 "
            "(Ending the Choice): \"If the choice is ended in one of the following ways, neither spouse can make "
            "this choice in any later tax year.\""
        )
    if status is not None and status not in _MARRIED_STATUSES:
        return f"the confirmed status ({status}) has no spouse on the return, and the election needs one"
    if marital == "widowed" and _married_for_year(profile, year):
        return (
            "this is the year of your spouse's death, and with no confirmed filing status this estimate prices "
            "'single' only — Pub 501: \"If your spouse died during the year, you are considered married for the "
            "whole year for filing status purposes\"; confirm married_filing_jointly (or married_filing_separately) "
            "to price the election"
        )
    needs = (
        " — the election needs a spouse at year end (Pub 519 ch. 1: \"If, at the end of your tax year, you are "
        "married and one spouse is a U.S. citizen or a resident alien and the other spouse is a nonresident alien, "
        "you can choose ...\")"
    )
    if marital is None:
        return "household.marital_status is not answered (and no married filing status is confirmed)" + needs
    return "the household is not married for the year (married on December 31, or widowed during the year)" + needs


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
    profile: Profile, classification: str | None = None, year: int | None = None, *, no_joint: bool = False,
) -> tuple[list[str], bool]:
    """Return (ordered candidate statuses, status_assumed). Primary (headline) is first.

    ``classification`` is the computed federal residency result ('resident' /
    'nonresident' / 'dual_status_candidate' / None). A confirmed NONRESIDENT
    alien files Form 1040-NR, which cannot use married_filing_jointly or
    head_of_household, so those statuses are dropped from the candidate set.
    A DUAL-STATUS candidate year carries the same restrictions (Pub 519:
    generally no joint return absent a §6013(g)/(h) election, no HOH), so
    MFJ/HOH are dropped there too — disclosed loudly upstream.

    ``no_joint`` (P-018): the §6013(g)/(h) election is recorded as DECLINED and the
    no-election facts put a nonresident in the couple, so there is no joint return
    (Pub 519 FAQ: "Generally, you cannot file as married filing jointly if either
    spouse was a nonresident alien at any time during the tax year"): MFS is the
    primary, and a citizen or resident filer keeps head of household as a candidate
    on the same qualifying-person test as below — Pub 501, Considered Unmarried.
    """
    hh = profile.household
    if hh is not None and hh.filing_status is not None and hh.filing_status.value:
        return [str(hh.filing_status.value)], False
    restricted = classification in ("nonresident", "dual_status_candidate")
    if _is_married(profile):
        # A nonresident-alien (1040-NR) filer cannot use MFJ; neither (generally) can a
        # dual-status-year filer absent a §6013 election — the primary becomes MFS.
        if restricted:
            return ["married_filing_separately"], True
        if no_joint:
            hoh_qp = hh.hoh_qualifying_person
            hoh = _confirmed_true(hoh_qp) or (bool(hh.dependents) and not (hoh_qp is not None and hoh_qp.value is False))
            return ["married_filing_separately", *(["head_of_household"] if hoh else [])], True
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
    # still brackets the HoH outcome. A nonresident alien (1040-NR) cannot use HOH at
    # all, and a dual-status-year filer generally cannot either (Pub 519).
    if hh is not None and not restricted and _confirmed_true(hh.hoh_qualifying_person):
        return ["head_of_household", "single"], True
    if hh is not None and not restricted and hh.dependents:
        return ["single", "head_of_household"], True
    return ["single"], True


_MFJ = "married_filing_jointly"
_MFS = "married_filing_separately"

_BOTTOM_LINE_LABEL = "Estimated refund (+) or amount owed (-)"
_DEPOSIT_EXCLUSION_LABEL = (
    "Less: US bank-deposit interest excluded (IRC 871(i)(2)(A) — not income to a nonresident)"
)

_JOINT_LIABILITY_CAVEAT = (
    "Filing jointly (MFJ) makes both spouses jointly and severally liable for the whole tax; "
    "filing separately (MFS) avoids that shared liability but usually costs more in tax. Weigh "
    "the dollar difference against the liability you take on."
)

# Mirrors intake.py's §6013(g)/(h) wording: a nonresident alien filing 1040-NR cannot
# use MFJ unless they elect to be treated as a U.S. resident, which taxes worldwide income.
# The election makes the COUPLE'S worldwide income taxable, so an elected-MFJ number is
# only meaningful when the nonresident spouse's foreign income is in the inputs. The
# shared worldwide-income-inputs warning is one fragment reused by every §6013 caveat
# direction (primary-filer-NRA, conditional, and NRA-spouse).
_WORLDWIDE_INPUT_WARNING = (
    "an elected-MFJ figure is only valid when the nonresident "
    "spouse's WORLDWIDE (foreign) income is included in the inputs — put it in the spouse "
    "snapshot's other_income — otherwise an MFJ-vs-MFS comparison overstates the MFJ advantage."
)

_SECTION_6013_CAVEAT = (
    "As a nonresident alien (Form 1040-NR) you cannot file jointly (MFJ); filing jointly "
    "requires electing under §6013(g)/(h) to treat the nonresident alien as a U.S. resident "
    "— which makes their worldwide income taxable. Showing married-filing-separately instead. "
    "If you weigh that election: " + _WORLDWIDE_INPUT_WARNING
)

# When residency is not yet computable for a visa holder, the 1040-NR restriction is conditional.
_SECTION_6013_CONDITIONAL_CAVEAT = (
    "If your residency result is nonresident alien, Form 1040-NR cannot use MFJ/HOH; filing "
    "jointly would then require electing under §6013(g)/(h) to treat the nonresident alien as a "
    "U.S. resident — which makes their worldwide income taxable. Confirm your residency to "
    "tighten this. Under that election any MFJ figure is only valid when the nonresident "
    "spouse's WORLDWIDE (foreign) income is included in the inputs (the spouse snapshot's "
    "other_income) — without it the MFJ-vs-MFS delta overstates the MFJ advantage."
)

# The OTHER direction of the same election (H1 follow-up): the PRIMARY filer is a US
# person / resident alien, and it is the SPOUSE who is (or may be) the nonresident.
# §6013(a)(1) bars a joint return when EITHER spouse is a nonresident alien absent the
# election, so MFJ stays a CANDIDATE here but only with the election + its trade-offs.
def _spouse_6013_caveat(direction: str, spouse_has_tin: bool, *, mfj_shown: bool = True) -> str:
    """Compose the NRA-spouse §6013(g)/(h) caveat: confirmed vs conditional lead, the
    shared worldwide-income-inputs warning, and the W-7/ITIN last mile when the spouse
    has no SSN/ITIN on file. ``mfj_shown`` False (a confirmed non-joint status) drops the
    'shown as a candidate' clause the figure would contradict (P-018)."""
    lead = (
        "Your spouse's own residency result is NONRESIDENT alien"
        if direction == "nonresident"
        else "Your spouse may be a nonresident alien (their residency is not confirmed)"
    )
    shown = "married-filing-jointly is shown as a candidate, but " if mfj_shown else ""
    text = (
        f"{lead}: {shown}a joint return with a "
        "nonresident-alien spouse is only valid by electing under §6013(g)/(h) to treat the "
        "spouse as a U.S. resident — which makes the spouse's WORLDWIDE income taxable, and the "
        "election statement (signed by BOTH spouses) must be attached to the first joint return. "
        "If you weigh that election: " + _WORLDWIDE_INPUT_WARNING
    )
    if not spouse_has_tin:
        text += (
            " Your spouse has no SSN/ITIN on file: filing jointly requires applying for an ITIN — "
            "Form W-7 is filed WITH the return, and the whole package mails to the IRS ITIN "
            "Operation in Austin, TX; on a married-filing-separately return, if your spouse doesn't have "
            "and isn't required to have an SSN or ITIN, enter 'NRA' in the entry space below the filing "
            "status checkboxes instead (Pub 501)."
        )
    return text


def _spouse_own_classification(profile: Profile, year: int) -> str | None:
    """The SPOUSE's residency from the spouse's OWN visa timeline and day counts, or None.

    None when the spouse is absent, a declared US person (no SPT applies), or has no
    facts that classify — never borrowed from the taxpayer, and never guessed. It
    ignores the §6013(g)/(h) election: callers that honor the election ask for it
    separately (it makes both spouses residents; this is the answer without it).
    """
    hh = profile.household
    sp = hh.spouse if hh is not None else None
    if sp is None or (sp.us_person is not None and sp.us_person.value is True):
        return None
    imm, rf = sp.immigration, sp.residency_facts
    if imm is None or not imm.visa_timeline or rf is None or not rf.days_in_us:
        return None
    days_by_year = {y: a.value for y, a in rf.days_in_us.items() if a is not None and a.value is not None}
    if not days_by_year:
        return None
    try:
        return residency.classify(imm.visa_timeline, days_by_year, year).classification
    except (ValueError, AssertionError):
        return None


def _spouse_nra_direction(profile: Profile, year: int) -> str | None:
    """Detect the US-person/RA-filer + NRA-spouse direction from the profile.

    Returns 'nonresident' when the spouse's OWN facts classify nonresident,
    'conditional' when the spouse is a declared non-US-person whose residency is
    not computable (unknown stays conditional — never asserted; a full classify
    is not attempted when the facts are absent), and None when there is no NRA
    direction (no spouse, a US-person spouse, or spouse facts classifying
    resident). Like :func:`_spouse_own_classification` it is the answer WITHOUT
    the §6013(g)/(h) election; estimate_refund drops the direction when the
    election is in effect (both spouses are then residents).
    """
    hh = profile.household
    sp = hh.spouse if hh is not None else None
    if sp is None:
        return None
    if sp.us_person is not None and sp.us_person.value is True:
        return None
    classification = _spouse_own_classification(profile, year)
    if classification == "resident":
        return None
    if classification == "nonresident":
        return "nonresident"
    if classification == "dual_status_candidate":
        return "conditional"
    us_person_false = sp.us_person is not None and sp.us_person.value is False
    return "conditional" if us_person_false else None


def _spouse_separate_return_note(
    profile: Profile, year: int, *, spouse_nonresident: bool, income: "IncomeSnapshot",
    deduction_method: str | None = None, assumed: bool = False, dual_status: bool = False,
) -> str:
    """Which rules the spouse's SEPARATE (two-return MFS) return ran under, and why (P-018).

    Each spouse's separate return follows that spouse's OWN classification —
    Pub 519, Frequently Asked Questions: "If your spouse does not make this
    choice, you must file a separate return on Form 1040 or 1040-SR. Your spouse
    must file Form 1040-NR." — so a US
    citizen spouse of a nonresident gets the regular rates and (unless the
    couple itemizes — IRC 63(c)(6)(A)) the standard deduction, and a nonresident
    spouse of a resident gets none of them. ``deduction_method`` is the couple's
    method on the two returns ('itemize' / 'standard' / None when neither had
    itemized deductions to weigh). ``assumed``: the spouse's residency is unknown and the
    nonresident reading is the one a recorded decline rests on (P-018).
    """
    sp = profile.household.spouse if profile.household is not None else None
    if spouse_nonresident:
        used = 0 if deduction_method == "standard" else (income.itemized_deductions or 0)
        if assumed and dual_status:
            because = (
                "the spouse's own facts show a dual-status year (a nonresident alien for part of it) and the recorded "
                "decline rests on a nonresident alien in the couple — you are a U.S. person or a resident — so the "
                "point prices the spouse's return as a nonresident's"
            )
        elif assumed:
            because = (
                "the recorded decline rests on a nonresident alien in the couple and you are a U.S. person or a "
                "resident, so the spouse of unknown residency is priced as the nonresident"
            )
        else:
            because = "the spouse's own visa timeline and day counts classify them as a nonresident alien"
        if assumed and dual_status:
            return (
                f"The spouse's separate return was computed under NONRESIDENT rules (Form 1040-NR), because "
                f"{because}. That approximates a dual-status year as a full-year nonresident's return — Pub 519 "
                f"ch. 6: \"You must file Form 1040 or 1040-SR if you are a dual-status taxpayer who becomes a "
                f"resident during the year and who is a U.S. resident on the last day of the tax year\" — so the "
                f"range also prices the resident reading."
            )
        return (
            f"The spouse's separate return was computed under NONRESIDENT rules (Form 1040-NR), because "
            f"{because} — without the "
            f"§6013(g)/(h) election, \"Your spouse must file Form 1040-NR\" (Pub 519, Frequently Asked "
            f"Questions): no standard deduction (\"Nonresident aliens cannot claim the standard deduction\", "
            f"Pub 519 ch. 5 — ${used:,} of the spouse's itemized deductions used), ordinary rates on "
            f"investment income, and no NIIT."
        )
    if sp is not None and sp.us_person is not None and sp.us_person.value is True:
        why = "the spouse is a declared U.S. citizen or lawful permanent resident"
    elif _spouse_own_classification(profile, year) in ("resident", "dual_status_candidate"):
        why = "the spouse's own visa timeline and day counts do not classify them as a nonresident alien"
    else:
        why = (
            "the spouse's own residency is not established (no visa timeline and day counts that classify them) — "
            "if the spouse is a nonresident alien, their Form 1040-NR takes no standard deduction (\"Nonresident "
            "aliens cannot claim the standard deduction\", Pub 519 ch. 5), so record the spouse's visa timeline "
            "and days in the US and rerun"
        )
    deduction = (
        "their own itemized deductions — the couple itemizes, so the standard deduction is zero on both returns "
        "(IRC 63(c)(6)(A); see the married-filing-separately deduction note)"
        if deduction_method == "itemize"
        else "the standard deduction"
    )
    return (
        f"The spouse's separate return was computed under RESIDENT rules (Form 1040 — {deduction}, and the "
        f"regular and preferential rates), not under your nonresident classification: each spouse's separate "
        f"return follows that spouse's OWN residency, and {why}."
    )


# IRC 63(c)(6) (uscode.house.gov) and Pub 501 (2025), Married persons who filed separate
# returns — read 2026-09-25. The two separate returns of a married couple share one
# deduction method; the estimate prices both and keeps the better total.
_MFS_DEDUCTION_LAW = (
    "IRC 63(c)(6): \"In the case of- (A) a married individual filing a separate return where either spouse "
    "itemizes deductions, (B) a nonresident alien individual, ... the standard deduction shall be zero.\" Pub "
    "501: \"You and your spouse can use the method that gives you the lower total tax, even though one of you "
    "may pay more tax than you would have paid by using the other method. You both must use the same method of "
    "claiming deductions. If one itemizes deductions, the other should itemize because the other spouse won't "
    "qualify for the standard deduction.\" Itemizing is itself an election — IRC 63(e)(1): \"Unless an "
    "individual makes an election under this subsection for the taxable year, no itemized deduction shall be "
    "allowed for the taxable year\" — so a nonresident spouse's Form 1040-NR may claim none, which is the "
    "'neither itemizes' method."
)


def _mfs_deduction_method_note(
    method: str, self_income: "IncomeSnapshot", spouse_income: "IncomeSnapshot", *,
    self_nonresident: bool, spouse_nonresident: bool,
) -> str:
    """Disclose the couple's deduction method on the two-return MFS pair (IRC 63(c)(6)(A))."""
    rows = [("your", self_income, self_nonresident), ("the spouse's", spouse_income, spouse_nonresident)]
    if method == "itemize":
        amounts = " and ".join(f"${snap.itemized_deductions or 0:,} on {who} return" for who, snap, _ in rows)
        chosen = (
            f"BOTH ITEMIZE — each separate return deducts its own itemized deductions ({amounts}) and neither "
            "takes the standard deduction."
        )
    else:
        forgone = [
            f"{who} ${snap.itemized_deductions:,} of itemized deductions"
            + (" (a nonresident alien has no standard deduction, so its Form 1040-NR claims none)" if nra else "")
            for who, snap, nra in rows
            if (snap.itemized_deductions or 0) > 0
        ]
        chosen = (
            "NEITHER ITEMIZES — each resident return takes the standard deduction, so "
            + " and ".join(forgone)
            + " go unused."
        )
    return (
        "Married filing separately (two returns): the couple uses ONE deduction method. "
        f"{_MFS_DEDUCTION_LAW} Both methods were priced and the better combined total is shown: {chosen}"
    )


def _citizenship_country(profile: Profile) -> str | None:
    """The filer's declared citizenship country (raw string), or None when not on file."""
    ident = profile.identity
    if ident is None or ident.citizenship_country is None or not ident.citizenship_country.value:
        return None
    return str(ident.citizenship_country.value)


def _treaty_cross_check(
    country: str, treaty_amount: int, year: int, knowledge_dir, total_wages: int = 0
) -> str | None:
    """Cross-check the entered treaty-exempt amount against the country's student-wage rule.

    Returns an ASSUMPTION string when the amount is not fully supported as
    student WAGES (it exceeds the country's dollar limit, or the country has
    no wage exclusion at all) — never a hard block, because scholarship /
    payments-from-abroad components are legitimately exempt without the wage
    limit. ``total_wages`` (snapshot wages, spouse-combined) matters for the
    de-minimis countries: their rule is an all-or-nothing cliff on TOTAL
    employment remuneration, so a partial claim under the threshold is still
    unsupported when total wages exceed it. Returns None when the country is
    not a shipped treaty pack (the generic trust-the-agent disclosure stands
    alone) or the amount is within the wage limit.
    """
    try:
        check = treaty_benefit(country, "student_wages", treaty_amount, year=year, knowledge_dir=knowledge_dir)
    except FileNotFoundError:
        return None  # country not shipped — keep today's generic disclosure only
    if check.taxable_remainder <= 0:
        # Within the claimed-amount rule. But a de-minimis country's rule (Canada
        # Art. XV) is an ALL-OR-NOTHING CLIFF on TOTAL US employment remuneration,
        # not a cap on the claimed portion (final-review finding).
        try:
            pack = load_treaty(country, base_dir=knowledge_dir)
        except (FileNotFoundError, ValueError):
            return None
        dm = pack.employment_de_minimis
        has_wage_limit = pack.student is not None and pack.student.compensation_limit is not None
        if dm is not None and dm.amount is not None and not has_wage_limit and total_wages > dm.amount:
            return (
                f"Treaty cross-check ({pack.country}): the {dm.article} ${dm.amount:,} rule is "
                f"ALL-OR-NOTHING on TOTAL US employment remuneration — the wages entered "
                f"(${total_wages:,}) exceed it, so NO part of them is exempt under that rule (the "
                f"${treaty_amount:,} entered as treaty-exempt is unsupported as wages); only the "
                f"treaty's alternative test (183-day/employer/PE) could exempt them. Validate with "
                f"the calc op treaty_benefit before relying on this estimate."
            )
        return None
    if check.exempt_amount > 0:
        # A dollar limit exists (China $5,000 / Korea $2,000) and the entry exceeds it.
        return (
            f"${treaty_amount:,} entered as treaty-exempt EXCEEDS the {check.country} student-wage limit — "
            f"{check.limits_applied[0]} — confirm the breakdown before filing: scholarship grants and "
            f"payments from abroad are SEPARATELY exempt without that limit (so a mixed amount can be "
            f"legitimate), but wages beyond it are not. Validate each component with the calc op "
            f"treaty_benefit (income_class 'scholarship' / 'payments_from_abroad')."
        )
    return (
        f"Treaty cross-check ({check.country}): the ${treaty_amount:,} entered as treaty-exempt is NOT "
        f"supported as student WAGES by the {check.country} treaty pack. {check.work}"
    )


def _treaty_reporting_text(
    year: int, classification: str | None, declared_us_person: bool, knowledge_dir
) -> str:
    """Where treaty-exempt income is reported, branched on residency (P-016).

    A nonresident reports it on Schedule OI item L and the Form 1040-NR
    treaty-exempt line. A resident alien files Form 1040, which has no
    Schedule OI: Pub 519 ch. 9 ('Resident Aliens') pairs the income on its
    usual line, when an information return (W-2, 1042-S, 1099) reported it as
    taxable, with the amount claimed "in parentheses" on Schedule 1's
    other-income line, "Exempt income", the treaty country and the article —
    the parenthetical offsets that inclusion, which is how this estimate
    models it (the income in full, the exempt amount subtracted).
    Resident means a computed 'resident' classification. A profile with no
    computed classification that declares a US person files Form 1040 too,
    but it may be a US CITIZEN, whom the saving clause keeps taxable, so its
    text says "Form 1040" (not "a resident alien's") and carries that caveat.
    A dual-status candidate or an unknown residency gets both, conditionally.
    Each line is read off the year's face through ``form_line``.
    """
    nonresident = (
        f"on Form 1040-NR, Schedule OI item L and Form 1040-NR line "
        f"{form_line(year, 'f1040nr.treaty_exempt', base_dir=knowledge_dir)} (attach the 1042-S when one "
        f"was issued)"
    )
    entry = (
        f"when a W-2, 1042-S, 1099 or other information return reported the income as taxable, the income "
        f"stays on its usual line AND the amount claimed is entered IN PARENTHESES on Schedule 1 line "
        f"{form_line(year, 'sched1.other_income', base_dir=knowledge_dir)} (Schedule 1 (Form 1040), other "
        f"income), with \"Exempt income,\" the treaty country and the article — the parenthetical offsets "
        f"that inclusion, as this estimate models it (Pub 519 ch. 9, 'Resident Aliens'); income no "
        f"information return reported may instead be left off the return, and is then not also entered in "
        f"parentheses"
    )
    exception = (
        "generally keeps a treaty benefit only through a saving-clause exception, and no Form 8833 is needed "
        "for a student, trainee or teacher article (Pub 519 ch. 9, Form 8833 exception 2)"
    )
    resident = f"on a resident alien's Form 1040: {entry}; a resident {exception}"
    if classification == "resident":
        return (
            f"On the return it is reported {resident} — Schedule OI and the Form 1040-NR treaty line belong "
            f"to a NONRESIDENT's return, not this one."
        )
    if classification is None and declared_us_person:
        return (
            f"This profile declares a US person with no residency computed, so the return is Form 1040: {entry}. "
            f"If the filer is a US CITIZEN, the treaty exemption generally does not apply at all — the saving "
            f"clause \"preserves or 'saves' the right of the United States to tax its citizens and residents "
            f"as if the tax treaty had not come into effect\" (Pub 519 ch. 9), and every shipped treaty "
            f"pack's student and teacher exception excludes US citizens (the calc op treaty_benefit quotes "
            f"each exception); a resident alien {exception}. Schedule OI and the Form "
            f"1040-NR treaty line belong to a NONRESIDENT's return, not this one."
        )
    if classification == "nonresident":
        return f"On the return it is reported {nonresident}."
    why = (
        "this is a dual-status candidate year: one return plus a statement for the other part of the "
        "year (Pub 519 ch. 6), each part under its own rules"
        if classification == "dual_status_candidate"
        else "this profile's residency is not established"
    )
    return (
        f"Where it is reported depends on residency ({why}): as a NONRESIDENT, {nonresident}; as a "
        f"RESIDENT alien, {resident}."
    )


def _spouse_has_tin(profile: Profile) -> bool:
    """True when a real spouse SSN/ITIN is on file ('NRA' is the no-TIN box literal)."""
    hh = profile.household
    sp = hh.spouse if hh is not None else None
    if sp is None or sp.tax_id is None or not sp.tax_id.value:
        return False
    return str(sp.tax_id.value).strip().upper() != "NRA"


# A dual-status candidate year restricts the return itself (Pub 519): the estimate can
# only show full-year approximations, and it must say so loudly.
_DUAL_STATUS_CAVEAT = (
    "Your residency result flags a possible DUAL-STATUS year, but every number here is a "
    "FULL-YEAR approximation — the real return is a split-year Form 1040 + Form 1040-NR. A "
    "dual-status year restricts filing: generally NO joint return (absent a §6013(g)/(h) "
    "election to be treated as a full-year resident, which makes worldwide income taxable), "
    "NO head of household, and NO standard deduction (Pub 519). Confirm the split-year "
    "treatment before relying on these numbers."
)


# The W-7 / ITIN last mile under the election (eval (o); P-018) — Pub 519 (2025),
# Frequently Asked Questions and ch. 5, Identification Number (read 2026-09-25): the
# joint return and its statement carry each spouse's TIN, so a spouse with neither an
# SSN nor an ITIN applies for one with Form W-7 filed WITH the return.
_SECTION_6013_ITIN_NOTE = (
    " Your spouse has no SSN/ITIN on file — Pub 519, Frequently Asked Questions: \"If you are a U.S. citizen or "
    "resident and you choose to treat your nonresident spouse as a resident and file a joint tax return, your "
    "nonresident spouse needs an SSN or ITIN\", and the election statement carries each spouse's TIN. Apply "
    "for an ITIN (Pub 519 ch. 5: \"If you do not have an ITIN and are not eligible to get an SSN, you must apply "
    "for an ITIN. For details on how to do so, see Form W-7 and its instructions.\"): Form W-7 is filed WITH "
    "the return, and the whole package mails to the IRS ITIN Operation in Austin, TX."
)


def _section_6013_caveat_in_effect(
    *, implied: bool, mfs_candidate: bool, own_classification: str | None = None, kind: str = "either",
    marital_inferred: bool = False, spouse_needs_itin: bool = False,
) -> str:
    """The caveat for an estimate computed UNDER the §6013(g)/(h) election (P-018).

    The worldwide-income and FICA caveats stay (the ROADMAP's rule): the election
    makes both spouses residents for income tax only. ``implied`` is the confirmed
    married-filing-jointly status of a filer whose own residency is nonresident (or
    a dual-status year, ``own_classification``) — a joint return that exists only
    under the election. ``kind`` is residency.section_6013_kind's answer — IRC
    6013(g), 6013(h) or 'either' — and picks the quoted effect, precondition and
    statement. ``marital_inferred`` means the marital status is unanswered and the
    confirmed married status stood in for it; ``spouse_needs_itin`` adds the W-7 last
    mile for a non-US spouse with no TIN. (An election the facts rule out is never
    applied — see :func:`_section_6013_no_joint_caveat`.)
    """
    effect, precondition, statement = residency.section_6013_texts(kind)
    if implied:
        own = (
            "a dual-status year (nonresident for part of it)"
            if own_classification == "dual_status_candidate"
            else "nonresident alien"
        )
        lead = (
            f"Your filing status is married-filing-jointly and your own residency result is {own}: a joint "
            f"return with a nonresident alien exists only under the §6013(g)/(h) election ({residency.SECTION_6013_NO_JOINT}), "
            "so this estimate applies the election — record it as residency_facts.section_6013_election: true."
        )
    else:
        lead = "A §6013(g)/(h) election is recorded (residency_facts.section_6013_election)."
        if marital_inferred:
            lead += (
                " household.marital_status is unanswered, so the confirmed married filing status was read as the "
                "marriage the election needs — confirm the marital status."
            )
    text = (
        f"{lead} {effect} So every figure here uses RESIDENT rules for both spouses: the standard deduction, "
        "the regular and preferential rates, NIIT evaluated, and no IRC 871(i)(2)(A) deposit-interest "
        "exclusion. Every figure is only valid when BOTH spouses' WORLDWIDE (foreign) income is in the inputs "
        "(other_income on each snapshot) — otherwise it overstates the election's advantage. "
        f"{residency.SECTION_6013_FICA} {statement} (file_and_pay's manifest flag section_6013_election adds "
        "the statement to the assembly checklist.)"
    )
    if spouse_needs_itin:
        text += _SECTION_6013_ITIN_NOTE
    if mfs_candidate:
        g_mfs = (
            "under IRC 6013(g) it is the posture of a LATER year of a continuing election — for the year the "
            "choice is made the return must be joint, so there filing separately means NOT electing; rerun "
            "without the election for that figure."
        )
        h_mfs = (
            "under a NEW IRC 6013(h) choice there is none — the return for the year of the choice must be joint "
            "and the choice covers that one year only, so filing separately means NOT making it; rerun without "
            "the election for that figure — UNLESS an IRC 6013(g) election made in an earlier year remains in "
            "effect (IRC 6013(g)(3)): this is then a later year of that election, separate returns are available, "
            "and no new statement is attached."
        )
        text += " A married-filing-separately figure under the election: " + (
            g_mfs if kind == "g" else h_mfs if kind == "h" else f"{g_mfs} And {h_mfs}"
        )
    return f"{text} {precondition}"


def _section_6013_no_joint_caveat(
    *, joint_blocked: bool, precondition_unmet: bool, recorded: bool, spouse_unknown: bool = False,
    unavailable: bool = False,
) -> str:
    """The caveat when the facts rule out a joint return (P-018): a recorded DECLINE with a
    nonresident in the couple, or an election that cannot apply because neither spouse is
    a U.S. citizen or resident (IRC 6013(g)(3)). ``joint_blocked``: a confirmed joint
    status those facts rule out — named FIRST, priced married-filing-separately, and the
    user asked to correct one of the two facts. ``unavailable``: the IRC 6013(g)(3) facts
    hold, so a DECLINE is never answered with "record the election as true" — on those
    facts the election is not available at all."""
    if precondition_unmet or unavailable:
        if precondition_unmet:
            source = (
                "A §6013(g)/(h) election is recorded (residency_facts.section_6013_election), but it was NOT applied."
                if recorded else
                "Your filing status is married-filing-jointly, which with a nonresident alien exists only under the "
                "§6013(g)/(h) election — and that election was NOT applied."
            )
        else:
            source = (
                "residency_facts.section_6013_election is recorded as FALSE (declined) — and on these facts the "
                "election is not available in any case."
            )
        body = f"{source} {residency.SECTION_6013_SUSPENDED}"
        if joint_blocked:
            return (
                "CONTRADICTION — the confirmed status married-filing-jointly is not a filing option on these facts: "
                f"{residency.SECTION_6013_NO_JOINT} {body} This estimate prices married-filing-separately instead "
                "and shows no joint figure: change the filing status to married-filing-separately — each of you "
                "who meets the nonresident filing requirements files Form 1040-NR — or correct the residency "
                "facts, and rerun."
            )
        return body
    # A recorded decline — the user's explicit residency fact.
    may = " (or may be)" if spouse_unknown else ""
    if joint_blocked:
        lead = (
            "CONTRADICTION — the confirmed status is married-filing-jointly, but residency_facts.section_6013_election "
            f"is recorded as FALSE (declined), and on the facts without the election one of you is{may} a nonresident "
            f"alien. {residency.SECTION_6013_NO_JOINT} So a joint return exists only under the election you declined: "
            "this estimate prices married-filing-separately WITHOUT the election and shows no joint figure. Correct "
            "one of the two facts — record the election as true (you are making it, or one made in an earlier year "
            "remains in effect), or change the filing status — and rerun."
        )
    else:
        lead = (
            "residency_facts.section_6013_election is recorded as FALSE (declined), and on the facts without the "
            f"election one of you is{may} a nonresident alien — so there is no joint return, and married-filing-"
            f"jointly is not a candidate here. {residency.SECTION_6013_NO_JOINT}"
        )
    unknown = (
        " If your spouse is in fact a U.S. resident (they pass the substantial presence test), no election is "
        "needed and a joint return is open: record the spouse's visa timeline and days in the US and rerun."
        if spouse_unknown else ""
    )
    return f"{lead} {residency.SECTION_6013_DECLINE}{unknown}"


# NIIT under the election (P-018). Treas. Reg. 1.1411-2(a)(2)(iii) and (iv) on eCFR
# and the Instructions for Form 8960 (2025), 'Election To File Jointly With
# Nonresident Spouse—Section 6013(g) or 6013(h)', read 2026-09-25: the chapter-1
# election does not by itself reach chapter 2A, so the joint NIIT figure is the one
# a SECOND election produces, and the default differs between the two choices.
_SECTION_6013G_NIIT = (
    "For IRC 6013(g), Treas. Reg. 1.1411-2(a)(2)(iii)(B): \"Married taxpayers who file a joint Federal income "
    "tax return pursuant to a section 6013(g) election for purposes of chapter 1 and chapter 24 also may elect "
    "to be treated as making a section 6013(g) election for purposes of chapter 2A\"; without it the default "
    "applies — (iii)(A): \"the spouses will be treated as married filing separately for purposes of section "
    "1411\", the U.S. citizen or resident spouse figures their own net investment income and modified AGI "
    "against the $125,000 married-filing-separately threshold, and \"the nonresident alien spouse will not be "
    "subject to tax under section 1411\"."
)
_SECTION_6013H_NIIT = (
    "For IRC 6013(h), Treas. Reg. 1.1411-2(a)(2)(iv)(B): \"Married taxpayers who file a joint Federal income "
    "tax return pursuant to a section 6013(h) election for purposes of chapter 1 and chapter 24 also may elect "
    "to be treated as making a section 6013(h) election for purposes of chapter 2A for such tax year\"; "
    "without it the default applies — (iv)(A): \"each spouse will be treated as married filing separately for "
    "the entire year for purposes of section 1411\" (each against the $125,000 threshold), and \"The spouse "
    "who becomes a United States resident during the tax year will be subject to section 1411 only with "
    "respect to income received for the portion of the year for which he or she is treated as a United States "
    "resident.\""
)
_SECTION_6013_NIIT_I8960 = (
    "The Instructions for Form 8960: \"To make either election under section 6013(g) or section 6013(h), for "
    "NIIT purposes, use your combined items of income, gain, loss, and deduction from your joint return to "
    "figure your NII and MAGI; use the married filing jointly return applicable threshold amount ($250,000); "
    "and check the appropriate checkbox near the top of Form 8960, Part I\", and \"The election must be made "
    "for the first tax year in which the U.S. taxpayer is subject to NIIT.\""
)


_SECTION_6013G_NIIT_TIMING = (
    "for IRC 6013(g), 1.1411-2(a)(2)(iii)(B)(2): it must be made \"for the first taxable year beginning after "
    "December 31, 2013, in which the United States taxpayer is subject to tax under section 1411\", and \"The "
    "determination of whether the United States taxpayer is subject to tax under section 1411 is made without "
    "regard to the effect of the section 6013(g) election\" — so it is not yet available in a year the U.S. "
    "spouse would owe no NIIT on their own."
)
_SECTION_6013H_NIIT_TIMING = (
    "for IRC 6013(h), 1.1411-2(a)(2)(iv)(B)(2): taxpayers making the chapter-1 election \"may elect to have "
    "their section 6013(h) election apply for purposes of chapter 2A\", on \"an original or amended return for "
    "the taxable year for which the election is made\"."
)


def _section_6013_niit_note(*, joint: bool, separate: bool, kind: str = "either") -> str:
    """How NIIT was evaluated under the §6013(g)/(h) election, and what the default is.

    ``joint`` / ``separate``: which candidate figures carry the election (both when a
    recorded election leaves MFJ and MFS open). ``kind`` picks the 1.1411-2(a)(2)
    paragraph — (iii) for IRC 6013(g), (iv) for IRC 6013(h), both for 'either'.
    """
    regs = (
        _SECTION_6013G_NIIT if kind == "g"
        else _SECTION_6013H_NIIT if kind == "h"
        else f"{_SECTION_6013G_NIIT} {_SECTION_6013H_NIIT}"
    )
    parts = ["NIIT under the §6013(g)/(h) election:"]
    if joint:
        timing = {
            "g": _SECTION_6013G_NIIT_TIMING,
            "h": _SECTION_6013H_NIIT_TIMING,
        }.get(kind, f"{_SECTION_6013G_NIIT_TIMING.rstrip('.')}; {_SECTION_6013H_NIIT_TIMING}")
        parts.append(
            "the joint-return figure evaluates the net investment income tax on the couple's combined income "
            "against the joint threshold — it ASSUMES the optional SECOND election, to apply the election for NIIT "
            "(chapter 2A) too. Without it the DEFAULT applies — the spouses are treated as married filing "
            "separately for NIIT, each against the separate threshold, and under IRC 6013(g) the nonresident "
            "spouse is not subject at all — which may be HIGHER or LOWER than the joint figure and is not priced "
            f"here. When the second election is available: {timing} " + _SECTION_6013_NIIT_I8960
        )
    if separate:
        parts.append(
            ("And each" if joint else "Each")
            + " separate return here evaluates the net investment income tax on that spouse's own income "
            "against the married-filing-separately threshold, as a resident's would — so if the spouse who is a "
            "nonresident without the election has investment income, their NIIT on a separate figure may be "
            "overstated (the defaults below)."
        )
    parts.append(
        "The chapter-1 election does not by itself reach NIIT (chapter 2A). " + regs
    )
    return " ".join(parts)


def _hoh_pair_note(
    *, spouse_nra: bool, weighed: bool, unsettled: bool, alternative: int | None, snapshot: bool = True,
    taxpayer_nonresident: bool = False, eitc_child: bool = True,
) -> str:
    """What a married filer's head-of-household figure is, by route (P-018; Pub 501 and Pub 519)."""
    if taxpayer_nonresident:
        return (
            "The head-of-household figure prices the confirmed status as given — the residency caveat explains why "
            "a nonresident alien cannot use it (Pub 519 ch. 5)."
            + (" The spouse's separate return inside it is priced on resident rules, and the spouse's residency is "
               "not settled — record the spouse's visa timeline and days in the US." if unsettled and snapshot else "")
        )
    text = (
        "The head-of-household figure is your own head-of-household return PLUS the spouse's separate return"
        if snapshot else
        "The head-of-household figure is your own head-of-household return (no spouse income snapshot was given, "
        "so the spouse's separate return is not in it)"
    )
    eitc_quote = (
        "Pub 519 ch. 5: \"Even if you are considered unmarried for head of household purposes because you are "
        "married to a nonresident alien, you may still be considered married for purposes of the earned income "
        "credit (EIC). In that case, you will need to meet the special rule for separated spouses to claim the "
        "credit.\" — that rule is not modeled."
    )
    if spouse_nra:
        text += (
            (" on Form 1040-NR rules" if snapshot else "")
            + " — head of household here rests on your spouse being a nonresident alien (Pub 501, Considered "
            "Unmarried: \"You are considered unmarried for head of household purposes if your spouse was a "
            "nonresident alien at any time during the year and you don't choose to treat your nonresident spouse "
            f"as a resident alien.\"). No earned income credit is computed on it — {eitc_quote}"
        )
        if weighed:
            text += (
                " The couple's one deduction method is used, as on the married-filing-separately pair — the lower "
                "reading: IRC 63(c)(6)(A) zeroes the standard deduction of \"a married individual filing a separate "
                "return where either spouse itemizes deductions\", and whether it reaches this return is not "
                "settled here."
            )
    else:
        text += (
            (" on resident rules" if snapshot else "")
            + " — head of household through living apart (Pub 501, Considered Unmarried: \"Your spouse didn't "
            "live in your home during the last 6 months of the tax year\", among its tests)."
        )
        if not eitc_child:
            text += (
                " No earned income credit is computed on it: Pub 501, \"You may be considered unmarried for the "
                "purpose of using head of household status but not for other purposes, such as claiming the EIC\", "
                "and the separated-spouse rule for the EIC needs a qualifying child."
            )
        if weighed:
            text += (
                " You may take the standard deduction even if your spouse itemizes (Pub 501: \"The head of "
                "household filing status allows you to choose the standard deduction even if your spouse chooses "
                "to itemize deductions.\"), so the better combination is used; the spouse's separate return "
                "itemizes whenever you do (IRC 63(c)(6)(A))."
            )
    if unsettled and alternative is not None:
        if snapshot:
            other = "resident rules (head of household through living apart)" if spouse_nra else (
                "Form 1040-NR rules (head of household through the nonresident-spouse rule, no EITC)")
            priced = f"the spouse's return on {other}"
        else:
            priced = "the other route (" + (
                "head of household through living apart" if spouse_nra
                else "head of household through the nonresident-spouse rule, no EITC") + ")"
        text += (
            f" Your spouse's residency is not settled, so the range also prices {priced}: "
            f"{'+' if alternative >= 0 else '-'}${abs(alternative):,}. Record the spouse's visa timeline and days "
            "in the US to settle it."
        )
    elif unsettled:
        text += (
            " Your spouse's residency is not settled: if the spouse is a U.S. resident, head of household would "
            "instead need the living-apart test — record the spouse's visa timeline and days in the US to settle it."
            if spouse_nra else
            " Your spouse's residency is not settled — record the spouse's visa timeline and days in the US."
        )
    return text


def _slot_effects(lines: list[CompositionLine]) -> tuple[dict[str, int], dict[str, str]]:
    """Aggregate a ledger's operand effects (and a label) per slot."""
    effects: dict[str, int] = {}
    lbls: dict[str, str] = {}
    for ln in lines:
        if ln.role != _OPERAND:
            continue
        effects[ln.slot] = effects.get(ln.slot, 0) + ln.effect
        lbls.setdefault(ln.slot, ln.label)
    return effects, lbls


def _delta_lines(best: "BottomLineResult", worst: "BottomLineResult") -> list[DeltaLine]:
    """Itemize best-minus-worst per ledger slot; the rows sum EXACTLY to the headline delta.

    This is the attribution the _build_comparison of old threw away (it kept only
    the two bottom lines), forcing callers to rebuild the "where does the
    difference come from" table by hand.
    Because both sides reconcile (sum(effect) == bottom, enforced per computation),
    the per-slot differences sum to best.bottom - worst.bottom by construction —
    still re-checked here so a future aggregation bug fails loudly, never quietly.
    """
    best_fx, best_lbl = _slot_effects(best.lines)
    worst_fx, worst_lbl = _slot_effects(worst.lines)
    rows = []
    for slot in best_fx.keys() | worst_fx.keys():
        b, w = best_fx.get(slot, 0), worst_fx.get(slot, 0)
        if b == w:
            continue
        rows.append(DeltaLine(
            slot=slot,
            label=best_lbl.get(slot) or worst_lbl.get(slot) or slot,
            best_effect=b,
            worst_effect=w,
            delta=b - w,
        ))
    rows.sort(key=lambda r: (-abs(r.delta), r.slot))
    residue = (best.bottom - worst.bottom) - sum(r.delta for r in rows)
    if residue != 0:
        raise RuntimeError(
            f"delta attribution does not reconcile: rows sum to "
            f"{sum(r.delta for r in rows)} but the bottom lines differ by "
            f"{best.bottom - worst.bottom} (residue {residue}) — a ledger stopped reconciling "
            f"or a non-operand row grew a nonzero effect; fix the emitting site, never this check."
        )
    return rows


def _build_comparison(outcomes: dict[str, "BottomLineResult"]) -> StatusComparison | None:
    """Build the side-by-side comparison when >=2 statuses were computed (eval (l))."""
    if len(outcomes) < 2:
        return None
    candidates = [StatusCandidate(status=s, bottom_line=r.bottom) for s, r in outcomes.items()]
    values = [c.bottom_line for c in candidates]
    # Recommended = the most-favorable signed bottom line (most refund / least owed).
    best_status = max(outcomes, key=lambda s: outcomes[s].bottom)
    worst_status = min(outcomes, key=lambda s: outcomes[s].bottom)
    delta = abs(max(values) - min(values))
    statuses = {c.status for c in candidates}
    caveat = _JOINT_LIABILITY_CAVEAT if {_MFJ, _MFS} <= statuses else None
    return StatusComparison(
        candidates=candidates,
        recommended_status=best_status,
        delta=delta,
        delta_lines=_delta_lines(outcomes[best_status], outcomes[worst_status]),
        joint_liability_caveat=caveat,
    )


def _section_6013_recorded(profile: Profile) -> bool:
    """True when residency_facts.section_6013_election is answered True (P-018)."""
    rf = profile.residency_facts
    return rf is not None and _confirmed_true(rf.section_6013_election)


def _classify_residency(profile: Profile, year: int, *, section_6013_election: bool | None = None):
    """Best-effort residency classification from the profile, or None when not computable.

    The §6013(g)/(h) election (P-018) wins over the visa timeline and day counts:
    under it the couple are "treated for income tax purposes as residents for your
    entire tax year" (Pub 519 ch. 1), so the result is resident-shaped — even with
    no facts on file — and keeps the day-count answer as
    ``classification_without_election``. ``section_6013_election`` None follows the
    profile: the recorded fact, applied only on the marriage the choice needs
    (:func:`_election_marriage_ok` — married for the year, the year of a spouse's
    death included, or an unanswered marital status with a confirmed joint status).
    """
    elected = (
        _section_6013_recorded(profile) and _election_marriage_ok(profile, year)
        if section_6013_election is None
        else section_6013_election
    )
    rf = profile.residency_facts
    imm = profile.immigration
    days_by_year = (
        {y: a.value for y, a in rf.days_in_us.items() if a is not None and a.value is not None}
        if rf is not None
        else {}
    )
    if not days_by_year or imm is None or not imm.visa_timeline:
        return residency.classify([], {}, year, section_6013_election=True) if elected else None
    try:
        return residency.classify(imm.visa_timeline, days_by_year, year, section_6013_election=elected)
    except (ValueError, AssertionError):
        # An incomplete/contradictory timeline cannot be classified yet — fall back
        # to the us_person best-effort rather than guessing (the election still
        # decides residency when it is in effect; its no-election answer is unknown).
        return residency.classify([], {}, year, section_6013_election=True) if elected else None


def _spouse_6013_status(profile: Profile, year: int) -> str | None:
    """The spouse's residency WITHOUT the election, for residency.section_6013_kind:
    'us' for a declared U.S. person, else the spouse's own classification (or None)."""
    hh = profile.household
    sp = hh.spouse if hh is not None else None
    if sp is None:
        return None
    if sp.us_person is not None and sp.us_person.value is True:
        return "us"
    return _spouse_own_classification(profile, year)


def _gate_classification(classification: str | None, imm, rf, year: int) -> str | None:
    """``classification`` for the IRC 6013(g)(3) gate: 'nonresident' only when it is CERTAIN —
    a nonresident answer that real presence in a missing lookback year could flip is
    unknown (None). The rule intake's gate shares (residency.certain_nonresident)."""
    if classification != "nonresident" or imm is None or not imm.visa_timeline or rf is None:
        return classification
    days = {y: a.value for y, a in rf.days_in_us.items() if a is not None and a.value is not None}
    return classification if residency.certain_nonresident(imm.visa_timeline, days, year) else None


class _ElectionState(NamedTuple):
    """How the §6013(g)/(h) election stands for one profile and year (P-018)."""

    residency_result: Any
    election: bool          # the figures run under the election
    implied: bool           # read from a confirmed joint status, not recorded
    declined: bool          # residency_facts.section_6013_election recorded False
    marital_inferred: bool  # a recorded election applied on an unanswered marital status + a married status
    own_classification: str | None  # the taxpayer's residency WITHOUT the election
    kind: str               # residency.section_6013_kind: 'g' / 'h' / 'either'
    precondition_unmet: bool  # sought (recorded or implied) but NOT applied: neither spouse a US citizen/resident
    unavailable: bool       # the IRC 6013(g)(3) facts hold (sought or not): neither spouse a US citizen/resident
    nonresident_in_couple: bool  # the no-election facts put a (possible) nonresident in the couple
    no_joint: bool          # no joint return on these facts: a recorded decline, or precondition_unmet
    joint_blocked: bool     # a confirmed MFJ status that no_joint rules out — priced MFS, named first


def _election_state(profile: Profile, year: int) -> _ElectionState:
    """Classify residency once, applying the §6013(g)/(h) election before any rule (P-018).

    A recorded election applies on the marriage it needs (:func:`_election_marriage_ok`).
    A confirmed joint status of a filer whose own residency is nonresident (or a
    dual-status year) IS the election posture: a joint return with a nonresident alien
    exists only under it (Pub 519, FAQ: "Generally, you cannot file as married filing
    jointly if either spouse was a nonresident alien at any time during the tax year"),
    so the figure is never a joint return under 1040-NR rules — unless the election is
    recorded as DECLINED, the user's explicit fact, which beats that reading. An
    election (recorded or implied) is NOT applied when the recorded facts show neither
    spouse a U.S. citizen or resident (IRC 6013(g)(3); a spouse of unknown residency
    cannot be judged, so it applies). ``joint_blocked``: a confirmed joint status those
    facts rule out, which the estimate prices married-filing-separately and names
    first. compare_scenarios reads this too, so a comparison says what each scenario
    ran under.
    """
    base = _classify_residency(profile, year, section_6013_election=False)
    own = base.classification if base is not None else None
    rf = profile.residency_facts
    declined = rf is not None and rf.section_6013_election is not None and rf.section_6013_election.value is False
    confirmed = _confirmed_status(profile)
    marriage_ok = _election_marriage_ok(profile, year)
    recorded = _section_6013_recorded(profile) and marriage_ok
    implied = (
        not recorded and not declined and own in ("nonresident", "dual_status_candidate")
        and marriage_ok and confirmed == _MFJ
    )
    ident = profile.identity
    us_declared = ident is not None and ident.us_person is not None and ident.us_person.value is True
    taxpayer = "us" if us_declared else own
    spouse = _spouse_6013_status(profile, year)
    # IRC 6013(g)(3): "shall not apply for any taxable year if neither spouse is a citizen or
    # resident of the United States at any time during such year" — judged on the recorded
    # facts (both classify full-year nonresident; neither declared a U.S. person), and a
    # nonresident answer that a missing lookback year could flip is unknown, never
    # asserted (residency.certain_nonresident — intake's gate shares it).
    hh = profile.household
    sp = hh.spouse if hh is not None else None
    unavailable = (
        _gate_classification(taxpayer, profile.immigration, profile.residency_facts, year) == "nonresident"
        and sp is not None
        and _gate_classification(spouse, sp.immigration, sp.residency_facts, year) == "nonresident"
    )
    unmet = (recorded or implied) and unavailable
    election = (recorded or implied) and not unmet
    residency_result = _classify_residency(profile, year, section_6013_election=True) if election else base
    spouse_direction = _spouse_nra_direction(profile, year) if _married_for_year(profile, year) or (
        _marital(profile) is None and confirmed in _MARRIED_STATUSES) else None
    nonresident_in_couple = own in ("nonresident", "dual_status_candidate") or spouse_direction is not None
    no_joint = not election and ((declined and nonresident_in_couple) or unmet)
    return _ElectionState(
        residency_result=residency_result,
        election=election,
        implied=implied and election,
        declined=declined,
        marital_inferred=election and not implied and _marital(profile) is None,
        own_classification=own,
        kind=residency.section_6013_kind(taxpayer, spouse, recorded=not implied),
        precondition_unmet=unmet,
        unavailable=unavailable,
        nonresident_in_couple=nonresident_in_couple,
        no_joint=no_joint,
        joint_blocked=no_joint and confirmed == _MFJ,
    )


# Form 8843 (2025), Who Must File and When and Where To File (irs.gov/pub/irs-pdf/
# f8843.pdf, read 2026-09-25). The election changes residency for income tax, not the
# substantial presence test's day count, so an exempt individual's days are still
# excluded — and FICA and every later year's SPT follow that count (P-018).
_FORM_8843_UNDER_ELECTION = (
    "Form 8843 — the exempt-individual days are still excluded from the substantial presence test under the "
    "election (FICA and later years' residency follow that count). Form 8843 (2025), Who Must File: an alien "
    "individual \"must file Form 8843 to explain the basis of your claim that you can exclude days of presence "
    "in the United States for purposes of the substantial presence test because you: • Were an exempt "
    "individual\". Its When and Where To File covers only attaching it to the nonresident return and mailing "
    "it alone when no return is due — it does not address a joint Form 1040, so confirm how to file it with "
    "the election return."
)


def _build_roadmap(profile: Profile, year: int, result=None, *, kind: str = "either") -> Roadmap:
    """Returns/forms (from residency when computable, else us_person), missing docs, time.

    ``kind`` is the §6013 choice (residency.section_6013_kind) when the election is applied."""
    forms: list[str] = []
    if result is not None:
        if result.section_6013_election:
            # P-018: under the election both spouses file as residents; the election is
            # made ON the return, and IRC 6013(g) and 6013(h) take different statements
            # (Pub 519 ch. 1, How To Make the Choice / Choosing Resident Alien Status).
            forms = ["Form 1040", "§6013(g)/(h) election: " + residency.section_6013_texts(kind)[2]]
            exempt_this_year = year in result.exempt_years.fully_exempt_years or (
                year in result.exempt_years.partially_exempt_years
            )
            if result.classification_without_election in ("nonresident", "dual_status_candidate") and (
                exempt_this_year
            ):
                forms.append(_FORM_8843_UNDER_ELECTION)
        elif result.classification == "resident":
            forms = ["Form 1040"]
        elif result.classification == "nonresident":
            forms = ["Form 1040-NR", "Form 8843"]
        else:  # dual_status_candidate — ONE return + ONE statement for the split year (Pub 519 ch. 6)
            forms = [
                "Form 1040 — the dual-status RETURN for an arrival year (resident on December 31): "
                "write 'Dual-Status Return' across the top; it reports worldwide income for the "
                "resident part of the year (Pub 519 ch. 6).",
                "Form 1040-NR — attached as the dual-status STATEMENT for the nonresident part of the "
                "year, marked 'Dual-Status Statement' across the top (it is not signed separately). "
                "For a DEPARTURE year (nonresident on December 31) the roles reverse: Form 1040-NR is "
                "the return and Form 1040 is the statement (Pub 519 ch. 6).",
                "Form 8843 — documents the exempt-individual days of the nonresident part of the year.",
                "Residency start date: under the substantial presence test, residency starts on the "
                "FIRST DAY you were present in the US during the year the test is met (days as an "
                "exempt individual do not count); under the green-card test, on the first day you were "
                "a lawful permanent resident (Pub 519 ch. 1, 'Residency starting date').",
                "First-Year Choice election (IRC 7701(b)(4); Pub 519 ch. 1): if you arrived too late "
                "to meet the SPT, you may ELECT residency from the first day of a qualifying presence "
                "period — at least 31 consecutive days present, and present for at least 75% of the "
                "days from that first day through December 31 — but only once the FOLLOWING year's SPT "
                "is met (usually: extend with Form 4868 and wait). The election is a signed statement "
                "attached to the return declaring the facts (the 31-day period, the presence dates, "
                "that you were not a resident the prior year and meet the SPT the following year); it "
                "is a recorded POSITION — record it with workspace_record_position, citing Pub 519.",
                "Dual-status restrictions: NO standard deduction (deductions must be itemized), and "
                "married filers use married-filing-separately (single if unmarried) — no joint return "
                "and no head of household absent a §6013(g)/(h) election to be treated as a full-year "
                "resident (Pub 519 ch. 6, 'Restrictions for Dual-Status Taxpayers').",
                "Due date: an arrival-year dual-status return (resident at year end) is due April 15; "
                "a departure-year return (nonresident at year end) is due April 15 when you had wages "
                "subject to US withholding, otherwise June 15 — the 15th day of the 6th month "
                "(Pub 519 ch. 7, 'When To File').",
            ]
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


# ---------------------------------------------------------------------------
# Credit helpers (parameters come from the knowledge pack's cited credits block;
# no calc op exists for CTC/EITC yet, so the worksheet arithmetic lives here —
# deterministic, data-driven, and disclosed as formula approximations).
# ---------------------------------------------------------------------------


def _dependent_infos(profile: Profile, year: int) -> list[_DepInfo]:
    """(age at Dec 31 of ``year``, has_ssn) per dependent; age None when DOB unknown.

    A DOB after the tax year yields a NEGATIVE age — downstream logic excludes
    such a dependent from every credit without triggering the provide-DOB nudge.
    """
    hh = profile.household
    if hh is None:
        return []
    return [
        ((year - d.dob.year) if d.dob is not None else None, d.has_ssn)
        for d in hh.dependents
    ]


def _phaseout_reduction(magi: int, threshold: int) -> int:
    """Schedule 8812 phase-out: $50 per $1,000 (or FRACTION — the excess is rounded
    UP to the next $1,000 first) of MAGI above the threshold."""
    excess = max(0, magi - threshold)
    return 50 * -(-excess // 1000)


def _earned_income_proxy(income: IncomeSnapshot) -> Decimal:
    """Earned income for EITC/ACTC, approximated as W-2 wages + 92.35% of positive
    self-employment profit (Schedule SE net earnings). The formal worksheet also
    subtracts the ½-SE-tax deduction and handles more categories — disclosed as
    an assumption wherever this proxy feeds a credit."""
    se_earnings = max(Decimal(0), Decimal("0.9235") * Decimal(max(0, income.self_employment_net)))
    return Decimal(income.wages) + se_earnings


def _eitc_amount(cfg: dict, status: str, agi: int, earned: Decimal, n_qc: int) -> int:
    """EITC by the Rev. Proc. formula: phase-in at max_credit/earned_income_amount,
    phase-out (on the GREATER of AGI or earned income) at max_credit/(complete-begin).
    The official EIC table uses $50 income bands, so this can differ by ~±$27."""
    key = "3+" if n_qc >= 3 else str(n_qc)
    row = cfg["by_qualifying_children"][key]
    max_credit = Decimal(row["max_credit"])
    credit = min(max_credit, max_credit / Decimal(row["earned_income_amount"]) * earned)
    mfj = status == _MFJ
    begin = Decimal(row["phaseout_begins_mfj" if mfj else "phaseout_begins_other"])
    complete = Decimal(row["phaseout_complete_mfj" if mfj else "phaseout_complete_other"])
    phase_base = max(Decimal(agi), earned)
    if phase_base > begin:
        phaseout_rate = max_credit / (complete - begin)
        credit = min(credit, max_credit - phaseout_rate * (phase_base - begin))
    return irs_round(max(Decimal(0), credit))


def _bottom_line(
    income: IncomeSnapshot,
    status: str,
    year: int,
    knowledge_dir,
    *,
    nonresident: bool = False,
    deps: list[_DepInfo] | tuple[_DepInfo, ...] = (),
    ss_withheld_groups: list[list[int]] | None = None,
    se_persons: list[tuple[int, int]] | None = None,
    notes: set[str] | None = None,
    deduction_mode: str | None = None,
    married_for_eitc: bool = False,
):
    """Compute the signed bottom line for one filing status. Returns (value, composition, citations).

    Pipeline: income (capital-loss limit, taxable Social Security) -> above-the-line
    adjustments (½ SE tax, student-loan interest) -> deduction -> tax (preferential
    rates when qualified dividends / net capital gain are present) -> nonrefundable
    credits (education, CTC/ODC) -> other taxes (SE, 8959, 8960, excess-APTC
    repayment) -> payments and refundable credits (withholding, excess-SS, ACTC,
    EITC, refundable AOTC, net PTC).

    ``nonresident`` skips NIIT (Form 8960 does not apply to nonresident aliens),
    the EITC, and education credits (NRAs are ineligible for both absent a
    residency election); Additional Medicare Tax applies to NRA Medicare wages,
    so it is kept. A nonresident also gets NO standard deduction (Form 1040-NR
    line 12 is itemized-only — the supplied itemized_deductions or $0 is used,
    never max()ed against the standard deduction) and NO preferential-rate
    worksheet (NRA investment income follows ECI/FDAP rules the estimate does
    not model — taxed at ordinary rates and disclosed upstream). The one NRA
    exclusion that IS modeled is US bank-deposit interest (IRC 871(i)(2)(A)):
    ``income.bank_deposit_interest`` comes off income BEFORE the total, never on
    a joint return, which a nonresident reaches only through the §6013(g)/(h)
    election that treats both spouses as residents for the whole year (Pub 519
    ch. 1). ``nonresident`` describes THIS snapshot's payee (P-018): the
    spouse's separate MFS return passes the spouse's OWN classification, never
    the taxpayer's, and under the election every snapshot is resident. ``deps``
    is the dependents' (age at year end, has_ssn) list — the profile itself is
    never needed here.

    Per-person taxes/credits on a COMBINED (joint) snapshot: both the excess-SS
    credit and Schedule SE are per person, so the MFJ spouse-split path passes
    ``ss_withheld_groups`` (one box-4 list per spouse — each computed
    independently with its own 2+-employer gate) and ``se_persons`` (one
    ``(se_net, own_wages)`` tuple per spouse — each spouse's own W-2 wages
    consume only their own SS wage base). When None, the snapshot is treated
    as one person's amounts (the single/no-split behavior).

    ``notes`` is an optional accumulator of disclosure keys the caller turns
    into assumptions (e.g. the below-100%-FPL PTC eligibility caveat, read off
    the PtcAnnualResult). Pure and deterministic.

    ``deduction_mode`` is the COUPLE's deduction method on a two-return MFS pair
    (IRC 63(c)(6)(A): "a married individual filing a separate return where either
    spouse itemizes deductions" has a standard deduction of zero): 'itemize' — this
    return deducts its own itemized amount (or $0), never the standard deduction;
    'standard' — this return takes the standard deduction, and a nonresident's
    Form 1040-NR claims no itemized deductions so the other spouse keeps theirs;
    None — this return alone (the larger of the two for a resident).
    """
    citations: list[Citation] = []
    comp: list[CompositionLine] = []
    pack = load_knowledge("federal", year, base_dir=knowledge_dir)
    pack_tax = pack.tax
    credits_block = pack.credits
    mfs = status == _MFS

    # ── Income ──────────────────────────────────────────────────────────────
    base = income.total_income()

    # The §871(i)(2)(A) bank-deposit-interest exclusion (N-8, P-013). Statute read
    # on uscode.house.gov: 871(i)(1) "No tax shall be imposed under paragraph (1)(A)
    # or (1)(C) of subsection (a) on any amount described in paragraph (2)";
    # 871(i)(2)(A) "Interest on deposits, if such interest is not effectively
    # connected with the conduct of a trade or business within the United States";
    # 871(i)(3) defines "deposits" (banking business / savings institutions /
    # insurance-company amounts held under an agreement to pay interest). Pub 519
    # ch. 3 (Exclusions From Gross Income — Interest Income) excludes it from income,
    # and the Instructions for Form 1040-NR (line 2b, Exception 3) keep it off line
    # 2b — so it comes off BEFORE "Total income", which then matches the return.
    # Only the CHARACTERIZED subset is excluded: the 871(i)(2)(A) condition is about
    # character, so interest left in `interest` stays taxed as ECI (871(b)) and is
    # disclosed upstream. The exclusion is OFF under the §6013(g)/(h) election: "you
    # and your spouse are treated for income tax purposes as residents for your
    # entire tax year" (Pub 519 ch. 1, Nonresident Spouse Treated as a Resident) —
    # the election, not the marriage, ends it (the N-14 trap). estimate_refund
    # applies the election as RESIDENCY (P-018), so an elected snapshot arrives with
    # nonresident=False on MFJ and MFS alike; the MFJ gate below stays as the last
    # line of defense, because a nonresident is on a joint return ONLY through it.
    deposit_excluded = 0
    if nonresident and status != _MFJ and income.bank_deposit_interest > 0:
        deposit_excluded = income.bank_deposit_interest
        base -= deposit_excluded
        comp.append(
            _line(
                "deposit_interest_exclusion",
                label=_DEPOSIT_EXCLUSION_LABEL,
                amount=-deposit_excluded,
            )
        )

    half_se = 0
    se_amount = 0
    # Schedule SE is PER PERSON: the MFJ spouse-split path passes each spouse's own
    # (se_net, own_wages) so one spouse's W-2 wages never absorb the other spouse's
    # SE wage base; without a split the snapshot is one person's amounts.
    se_citation = None
    for se_net, own_wages in (se_persons if se_persons is not None else [(income.self_employment_net, income.wages)]):
        if se_net >= 400:
            # Schedule SE lines 8a-9: W-2 wages consume the social-security wage base first
            # (box-1 wages stand in for box-3 SS wages — disclosed as an assumption).
            se = se_tax(se_net, year, knowledge_dir, w2_ss_wages=own_wages)
            se_amount += se.se_tax
            half_se += se.deduction_half
            se_citation = se.citation
    if se_citation is not None:
        citations.append(se_citation)

    # Capital gains/losses: short + long combined; a net LOSS is deductible only up
    # to $3,000 per year ($1,500 MFS) — the disallowed remainder carries forward.
    # This snapshot has no year-to-year state, so it clamps and DISCLOSES rather than
    # carrying: calc.capital_loss_limitation owns the IRC 1212(b) carryover chain, with
    # the short/long character preserved. Keep the two in step if either changes.
    st, lt = income.capital_gain_short, income.capital_gain_long
    combined_gain = st + lt
    capital = combined_gain
    if combined_gain > 0:
        comp.append(_line("capital_gain", label="Capital gain (net short-term + long-term)", amount=capital))
    elif combined_gain < 0:
        loss_cap = 1500 if mfs else 3000
        capital = max(combined_gain, -loss_cap)
        if capital != combined_gain:
            comp.append(
                _line("capital_loss", 
                    label=f"Capital loss (limited to ${loss_cap:,} — the annual capital-loss cap)",
                    amount=capital,
                )
            )
        else:
            comp.append(_line("capital_loss", label="Capital loss (net short-term + long-term)", amount=capital))

    # Taxable Social Security (worksheet). The worksheet's 'other income' input is
    # approximated as every other AGI item net of the above-the-line adjustments
    # EXCLUDING the student-loan-interest deduction (IRC 86(b)(2) figures modified
    # AGI without section 221); tax-exempt interest is not tracked (assumed $0).
    taxable_ss = 0
    if income.social_security_benefits > 0 and pack_tax.taxable_social_security is not None:
        ss_other_income = base + capital - half_se - income.pre_agi_adjustments
        ss_res = taxable_social_security(
            income.social_security_benefits,
            ss_other_income,
            0,  # tax-exempt interest not tracked — disclosed as an assumption
            filing_status=status,
            year=year,
            mfs_lived_with_spouse=mfs,  # MFS candidate assumes living with the spouse (common case)
            knowledge_dir=knowledge_dir,
        )
        taxable_ss = ss_res.taxable_benefits
        citations.append(ss_res.citation)
        if taxable_ss:
            comp.append(
                _line("taxable_social_security", label="Taxable Social Security benefits (worksheet)", amount=taxable_ss)
            )

    total_income = base + capital + taxable_ss
    comp.append(_line("total_income", label="Total income", amount=total_income))

    # Treaty-exempt income (1042-S box 2 / Schedule OI) comes off BEFORE tax. The
    # exclusion is clamped so income can never go negative overall: it takes total
    # income to a floor of 0, and a clamp is disclosed upstream (a treaty amount
    # larger than the income entered is an input problem, never a negative income).
    if income.treaty_exempt_income > 0:
        treaty_excluded = min(income.treaty_exempt_income, max(0, total_income))
        if treaty_excluded < income.treaty_exempt_income and notes is not None:
            notes.add("treaty_exclusion_clamped")
        if treaty_excluded:
            comp.append(
                _line("treaty_exempt_exclusion", 
                    label="Less: treaty-exempt income (tax treaty — confirm the article and your state's conformity)",
                    amount=-treaty_excluded,
                )
            )
            total_income -= treaty_excluded

    # ── Above-the-line adjustments ──────────────────────────────────────────
    if half_se:
        comp.append(_line("half_se_adjustment", label="Less: ½ self-employment tax (adjustment)", amount=-half_se))

    sli = 0
    if income.student_loan_interest_paid > 0 and pack_tax.student_loan_interest is not None:
        # Section 221 MAGI = AGI computed WITHOUT the SLI deduction itself.
        magi_for_sli = total_income - half_se - income.pre_agi_adjustments
        sli_res = student_loan_interest_deduction(
            income.student_loan_interest_paid, magi_for_sli, status, year, knowledge_dir
        )
        sli = sli_res.deduction  # MFS gets $0 by rule inside the op
        if sli:
            citations.append(sli_res.citation)
            comp.append(_line("student_loan_interest_deduction", label="Less: student loan interest deduction", amount=-sli))
        elif notes is not None:
            # A supplied 1098-E must never vanish silently: the deduction computed
            # to $0 (MFS by rule, or MAGI at/above the phase-out ceiling) — cite the
            # op's own work and surface the why upstream.
            citations.append(sli_res.citation)
            notes.add("sli_zero_mfs" if mfs else "sli_zero_phaseout")

    if income.pre_agi_adjustments > 0:
        comp.append(
            _line("other_adjustments", 
                label="Less: other above-the-line adjustments (confirmed)",
                amount=-income.pre_agi_adjustments,
            )
        )

    agi = total_income - half_se - sli - income.pre_agi_adjustments
    comp.append(_line("agi", label="Adjusted gross income (AGI)", amount=agi))

    # ── Deduction and taxable income ────────────────────────────────────────
    if nonresident:
        # Form 1040-NR line 12 is ITEMIZED-ONLY (typically state/local income tax
        # withheld): a nonresident alien cannot take the standard deduction (Pub 519;
        # the India treaty Art. 21(2) student exception is disclosed upstream). The
        # max(itemized, standard) logic must never run here.
        if deduction_mode == "standard":
            deduction = 0
            label = (
                "Less: itemized deductions (1040-NR — none claimed, so the spouse's separate return keeps "
                "the standard deduction: IRC 63(c)(6)(A))"
            )
        else:
            deduction = income.itemized_deductions or 0
            label = "Less: itemized deductions (1040-NR — nonresidents cannot take the standard deduction)"
    else:
        sd = standard_deduction(status, year, knowledge_dir=knowledge_dir)
        citations.append(sd.citation)
        if deduction_mode == "itemize":
            deduction = income.itemized_deductions or 0
            label = (
                "Less: itemized deductions (married filing separately — the couple itemizes, so the standard "
                "deduction is zero: IRC 63(c)(6)(A))"
                if status == _MFS else
                "Less: itemized deductions (the better method on the couple's two returns)"
            )
        elif deduction_mode == "standard":
            deduction, label = sd.amount, "Less: standard deduction"
        elif income.itemized_deductions is not None:
            deduction = max(income.itemized_deductions, sd.amount)
            label = "Less: itemized deductions" if deduction == income.itemized_deductions else "Less: standard deduction"
        else:
            deduction, label = sd.amount, "Less: standard deduction"
    comp.append(_line("deduction", label=label, amount=-deduction))

    taxable = max(0, agi - deduction)
    comp.append(_line("taxable_income", label="Taxable income", amount=taxable))

    # ── Income tax (preferential rates when QD / net capital gain present) ──
    # Residents only: preferential rates never apply to a nonresident's non-ECI
    # investment income (FDAP is flat 30%/treaty-rate on Schedule NEC — not modeled,
    # disclosed upstream), so the NRA path stays on ordinary rates.
    net_gain_preferential = max(0, lt + min(st, 0))  # Schedule D 'smaller of 15/16, floor 0'
    if (
        (income.qualified_dividends + net_gain_preferential) > 0
        and not nonresident
        and pack_tax.capital_gains_brackets is not None
    ):
        pref = tax_with_preferential_rates(
            taxable, income.qualified_dividends, lt, st, status, year, knowledge_dir
        )
        income_tax = pref.tax
        citations.append(pref.citation)
        comp.append(
            _line("income_tax", 
                label="Income tax (qualified dividends / net capital gain at preferential rates)",
                amount=income_tax,
            )
        )
    else:
        tax_res = tax_from_taxable_income(taxable, status, year, knowledge_dir)
        income_tax = tax_res.tax
        citations.append(tax_res.citation)
        comp.append(_line("income_tax", label="Income tax", amount=income_tax))

    # ── Nonrefundable credits (limited by the income tax, floor 0) ──────────
    remaining_tax = income_tax
    earned = _earned_income_proxy(income)

    # Education credits first — the Schedule 8812 credit-limit worksheet subtracts
    # Schedule 3 credits before the CTC gets what is left. A nonresident alien
    # cannot claim them (Form 8863 bars NRAs absent a residency election).
    aotc_refundable = 0
    if income.aotc_qualified_expenses and not nonresident and pack_tax.education_credits is not None:
        edu = education_credits(
            income.aotc_qualified_expenses, 0, magi=agi, filing_status=status, year=year,
            knowledge_dir=knowledge_dir,
        )
        if edu.total_credit:
            citations.append(edu.citation)
        aotc_refundable = edu.aotc_refundable
        used_edu = min(edu.total_credit - edu.aotc_refundable, remaining_tax)
        if used_edu:
            remaining_tax -= used_edu
            comp.append(_line("education_credits_nonrefundable", label="Less: education credits (nonrefundable part)", amount=-used_edu))

    # Child and dependent care credit (Form 2441 -> Schedule 3 line 2), when the
    # expenses and qualifying-person count are supplied. Per-spouse earned income
    # comes from the spouse split (se_persons) when available; a combined MFJ
    # snapshot assumes both spouses earn at least the allowed expenses — disclosed
    # upstream. MFS gets $0 by rule inside the op (also disclosed). 2021 (ARPA):
    # refundable per the pack flag — it joins the payments, not this bucket.
    dc_refundable = 0
    if (
        income.dependent_care_expenses > 0
        and income.dependent_care_persons > 0
        and pack_tax.dependent_care is not None
    ):
        if mfs:
            if notes is not None:
                notes.add("dependent_care_mfs")
        else:
            if status == _MFJ:
                if se_persons is not None and len(se_persons) >= 2:
                    per_spouse_earned = [
                        Decimal(w) + max(Decimal(0), Decimal("0.9235") * Decimal(max(0, se)))
                        for se, w in se_persons
                    ]
                    dc_earned, dc_spouse_earned = per_spouse_earned[0], per_spouse_earned[1]
                else:
                    # Combined amounts cannot split earned income per spouse: assume
                    # both spouses clear the limitation (disclosed as an assumption).
                    dc_earned = dc_spouse_earned = earned
                    if notes is not None:
                        notes.add("dependent_care_mfj_combined")
            else:
                dc_earned, dc_spouse_earned = earned, None
            dc = dependent_care_credit(
                income.dependent_care_expenses,
                income.dependent_care_persons,
                dc_earned,
                spouse_earned_income=dc_spouse_earned,
                agi=max(0, agi),
                filing_status=status,
                year=year,
                knowledge_dir=knowledge_dir,
            )
            if dc.credit:
                citations.append(dc.citation)
                if dc.refundable:
                    dc_refundable = dc.credit
                else:
                    used_dc = min(dc.credit, remaining_tax)
                    if used_dc:
                        remaining_tax -= used_dc
                        comp.append(
                            _line("dependent_care_credit_nonrefundable", 
                                label="Less: child and dependent care credit (Form 2441, nonrefundable)",
                                amount=-used_dc,
                            )
                        )
                    elif notes is not None:
                        # The credit computed but earlier credits consumed all the income
                        # tax — supplied inputs must never vanish silently.
                        notes.add("dependent_care_squeezed")
            elif notes is not None:
                # Credit computed to $0 — disclose WHY instead of dropping the inputs.
                if dc_spouse_earned is not None and min(dc_earned, dc_spouse_earned) <= 0:
                    notes.add("dependent_care_spouse_no_earned")
                else:
                    notes.add("dependent_care_zero")

    # Child tax credit / credit for other dependents. Qualifying child = DOB known,
    # age at year end under the year's limit (17; 18 in 2021), and a work-eligible
    # SSN; every other dependent WITH a known DOB gets the $500 ODC. Dependents
    # without a DOB are excluded entirely (surfaced as an assumption upstream).
    known_deps = [(a, s) for a, s in deps if a is not None and a >= 0]
    ctc_cfg = getattr(credits_block, "child_tax_credit", None) if credits_block is not None else None
    actc = 0
    rctc = 0
    if ctc_cfg and known_deps:
        child_age_limit = int(ctc_cfg.get("child_under_age", 17))
        qc_ages = [a for a, s in known_deps if a < child_age_limit and s is True]
        n_odc = len(known_deps) - len(qc_ages)
        odc_total = int(ctc_cfg["credit_for_other_dependents"]) * n_odc
        if qc_ages or n_odc:
            citations.append(Citation(**ctc_cfg["citation"]))
        if ctc_cfg.get("arpa_expanded"):
            # 2021 (ARPA): $3,600 under age 6 / $3,000 otherwise; a two-tier phase-out
            # (tier 1 trims only the increase over the $2,000 base, capped per status;
            # tier 2 trims the remainder at the regular thresholds); FULLY refundable
            # (no 15%-of-earned-income ACTC computation). ODC stays nonrefundable.
            under6 = int(ctc_cfg["per_qualifying_child_under_6"])
            per_child = int(ctc_cfg["per_qualifying_child"])
            expanded = sum(under6 if a < 6 else per_child for a in qc_ages)
            base_credit = int(ctc_cfg["pre_arpa_base_per_child"]) * len(qc_ages)
            increase = expanded - base_credit
            tier1_reduction = min(
                _phaseout_reduction(agi, int(ctc_cfg["increased_amount_phaseout_threshold"][status])),
                int(ctc_cfg["increased_amount_phaseout_cap"][status]),
                increase,
            )
            combined = base_credit + increase - tier1_reduction + odc_total
            after_phaseout = max(
                0, combined - _phaseout_reduction(agi, int(ctc_cfg["base_credit_phaseout_threshold"][status]))
            )
            # The 2021 Schedule 8812 preserves the ODC part first (line 14a); the CTC
            # remainder is the fully refundable RCTC.
            odc_part = min(odc_total, after_phaseout)
            rctc = after_phaseout - odc_part
            used_odc = min(odc_part, remaining_tax)
            if used_odc:
                remaining_tax -= used_odc
                comp.append(
                    _line("odc_nonrefundable", label="Less: credit for other dependents (nonrefundable)", amount=-used_odc)
                )
        elif qc_ages or n_odc:
            per_child = int(ctc_cfg["per_qualifying_child"])
            combined = per_child * len(qc_ages) + odc_total
            after_phaseout = max(
                0, combined - _phaseout_reduction(agi, int(ctc_cfg["magi_phaseout_threshold"][status]))
            )
            used_ctc = min(after_phaseout, remaining_tax)
            if used_ctc:
                remaining_tax -= used_ctc
                comp.append(
                    _line("ctc_odc_nonrefundable", 
                        label="Less: child tax credit / credit for other dependents (nonrefundable)",
                        amount=-used_ctc,
                    )
                )
            if qc_ages:
                # Additional CTC (refundable): min(leftover credit, per-child cap,
                # 15% of earned income over $2,500). ODC never refunds, but the
                # per-child cap bounds any leftover the way Schedule 8812 does.
                actc_cap = int(ctc_cfg["additional_ctc_refundable_cap_per_child"]) * len(qc_ages)
                ei_limit = irs_round(max(Decimal(0), Decimal("0.15") * (earned - 2500)))
                actc = max(0, min(after_phaseout - used_ctc, actc_cap, ei_limit))

    income_tax_after_credits = remaining_tax

    # ── Other taxes (Schedule 2) ────────────────────────────────────────────
    if se_amount:
        comp.append(_line("se_tax", label="Plus: self-employment tax", amount=se_amount))

    addmed_amount = 0
    if (income.wages or income.self_employment_net) and pack_tax.additional_medicare_tax is not None:
        addmed = additional_medicare_tax(
            income.wages, status, year, se_net_profit=income.self_employment_net, knowledge_dir=knowledge_dir
        )
        if addmed.additional_medicare_tax:
            addmed_amount = addmed.additional_medicare_tax
            citations.append(addmed.citation)
            comp.append(
                _line("additional_medicare_tax", 
                    label="Plus: Additional Medicare Tax (Form 8959, 0.9% over threshold)",
                    amount=addmed_amount,
                )
            )

    niit_amount = 0
    investment_income = income.interest + income.dividends + capital
    # NRAs are generally not subject to NIIT (Form 8960 instructions).
    if investment_income > 0 and not nonresident and pack_tax.niit is not None:
        niit_res = niit(investment_income, agi, status, year, knowledge_dir=knowledge_dir)
        if niit_res.niit:
            niit_amount = niit_res.niit
            citations.append(niit_res.citation)
            comp.append(
                _line("niit", 
                    label="Plus: Net investment income tax (Form 8960, 3.8% over MAGI threshold)",
                    amount=niit_amount,
                )
            )

    # Premium tax credit reconciliation (Form 8962, annual method). Household income
    # is approximated as AGI + the NONTAXABLE part of Social Security (the 8962 MAGI
    # add-back); household size counts the filer, the spouse on a joint return, and
    # every dependent. The contiguous-48 table is used ('other') — AK/HI differ.
    net_ptc = 0
    ptc_repayment = 0
    if (income.aca_slcsp > 0 or income.aca_aptc > 0) and pack_tax.ptc is not None:
        household_income = max(0, agi + (income.social_security_benefits - taxable_ss))
        household_size = 1 + (1 if status == _MFJ else 0) + len(deps)
        ptc_res = ptc_annual(
            household_income,
            household_size,
            income.aca_premiums,
            income.aca_slcsp,
            income.aca_aptc,
            filing_status=status,
            year=year,
            state="other",
            knowledge_dir=knowledge_dir,
        )
        citations.append(ptc_res.citation)
        net_ptc, ptc_repayment = ptc_res.net_ptc, ptc_res.repayment
        if notes is not None and ptc_res.fpl_pct < 100:
            # Below-100%-FPL applicable-taxpayer floor — surfaced as an assumption upstream.
            notes.add("ptc_below_100_fpl_with_aptc" if income.aca_aptc > 0 else "ptc_below_100_fpl_no_aptc")
        if ptc_repayment:
            comp.append(
                _line("aptc_repayment", 
                    label="Plus: excess advance premium tax credit repayment (Form 8962)",
                    amount=ptc_repayment,
                )
            )

    total_tax = income_tax_after_credits + se_amount + addmed_amount + niit_amount + ptc_repayment
    comp.append(_line("total_tax", label="Total tax", amount=total_tax))

    # ── Payments and refundable credits ─────────────────────────────────────
    # Negative, like every other "Less:" composition line (they reduce what you owe).
    comp.append(_line("withholding", label="Less: federal tax withheld / payments", amount=-income.federal_withholding))
    payments = income.federal_withholding

    # The excess-SS cap is PER PERSON (Schedule 3 / Topic 608): on a spouse-split
    # joint return each spouse's box-4 list is computed independently — each with
    # its own 2+-employer gate — and the credits are summed. Two or more employers
    # can over-withhold Social Security; a single employer's over-withholding is
    # an employer error, never a return credit.
    if pack_tax.employee_social_security is not None:
        xss_credit = 0
        xss_citation = None
        for group in (ss_withheld_groups if ss_withheld_groups is not None else [list(income.ss_withheld_by_employer)]):
            if len(group) >= 2:
                xss = excess_ss(list(group), year, knowledge_dir)
                if xss.credit:
                    xss_credit += xss.credit
                    xss_citation = xss.citation
        if xss_credit:
            payments += xss_credit
            citations.append(xss_citation)
            comp.append(
                _line("excess_ss_credit", 
                    label="Less: excess Social Security withholding credit (Schedule 3)",
                    amount=-xss_credit,
                )
            )

    if actc:
        payments += actc
        comp.append(_line("actc_refundable", label="Less: additional child tax credit (refundable)", amount=-actc))
    if rctc:
        payments += rctc
        comp.append(_line("ctc_refundable_2021", label="Less: child tax credit (2021 — fully refundable)", amount=-rctc))
    if dc_refundable:
        payments += dc_refundable
        comp.append(
            _line("dependent_care_credit_refundable_2021", 
                label="Less: child and dependent care credit (2021 — refundable, Form 2441)",
                amount=-dc_refundable,
            )
        )

    # EITC: never for a nonresident alien or (as modeled) married filing separately —
    # nor for a head of household who "may still be considered married for purposes of the
    # earned income credit (EIC)" (``married_for_eitc``, Pub 519 ch. 5: the nonresident-spouse
    # route to head of household, or a lived-apart one with no qualifying child; the
    # separated-spouse rule is not modeled); gated by
    # the investment-income limit; needs positive earned income.
    eitc_cfg = getattr(credits_block, "earned_income_tax_credit", None) if credits_block is not None else None
    if eitc_cfg and not nonresident and not mfs and not married_for_eitc and earned > 0:
        # Pub 596 Worksheet 1: investment income uses the NET capital gain (Form 1040
        # line 7, floored at 0) — the loss-limited `capital` figure — never the gross
        # positive short/long legs summed separately.
        eitc_investment_income = income.interest + income.dividends + max(0, capital)
        if eitc_investment_income <= int(eitc_cfg["investment_income_limit"]):
            # EITC qualifying child: DOB known, under 19 at year end, with an SSN.
            # (19-23 full-time students and disabled children of any age are NOT
            # modeled — disclosed upstream.)
            n_qc_eitc = sum(1 for a, s in known_deps if a < 19 and s is True)
            eitc = _eitc_amount(eitc_cfg, status, agi, earned, n_qc_eitc)
            if eitc:
                payments += eitc
                citations.append(Citation(**eitc_cfg["citation"]))
                comp.append(
                    _line("eitc", 
                        label="Less: earned income tax credit (refundable, formula approximation)",
                        amount=-eitc,
                    )
                )

    if aotc_refundable:
        payments += aotc_refundable
        comp.append(
            _line("aotc_refundable", label="Less: American opportunity credit (refundable 40%)", amount=-aotc_refundable)
        )
    if net_ptc:
        payments += net_ptc
        comp.append(_line("net_ptc", label="Less: net premium tax credit (Form 8962)", amount=-net_ptc))

    bottom = payments - total_tax
    comp.append(_line("bottom_line", label=_BOTTOM_LINE_LABEL, amount=bottom))
    _reconcile(bottom, comp)
    return BottomLineResult(bottom=bottom, lines=comp, citations=citations)


def estimate_refund(
    profile: Profile,
    year: int,
    income: IncomeSnapshot,
    *,
    knowledge_dir: str | Path | None = None,
) -> RefundEstimate:
    """Compute a preliminary refund/owed RANGE from a partial profile + confirmed income.

    The range width reflects unconfirmed filing status (computed by running the
    deterministic ``calc`` engine under each plausible status). Credits are
    estimated whenever their inputs are present — CTC/ODC and EITC from the
    dependents' dates of birth and SSN answers, education credits from 1098-T
    expenses, the premium tax credit from 1095-A amounts — with every
    approximation disclosed; unconfirmed/missing documents stay directional
    caveats in ``what_would_change_it``. The result is always labeled ESTIMATE.

    When ``income.spouse`` is provided for a married couple, the
    married-filing-separately candidate is a TRUE two-return comparison (the sum
    of two separately computed MFS returns) instead of the all-on-one worst-case
    bound used when only combined amounts are known.

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
    # P-018: the §6013(g)/(h) election is RESIDENCY — "you and your spouse are treated
    # for income tax purposes as residents for your entire tax year" (Pub 519 ch. 1) —
    # so it is applied here, once (_election_state: recorded, or read from a confirmed
    # joint status of a nonresident), and every rule downstream (the deduction, NIIT, the
    # rates, the 871(i)(2)(A) exclusion, the candidate statuses) follows from the
    # classification.
    married = _is_married(profile)
    state = _election_state(profile, year)
    residency_result = state.residency_result
    election_implied = state.implied
    own_classification = state.own_classification
    election = state.election
    classification = residency_result.classification if residency_result is not None else None
    nonresident = classification == "nonresident"
    # The election reaches chapter 1 and chapter 24 only (IRC 6013(g)(1)), so the FICA
    # disclosure keeps following the day-count answer.
    fica_nonresident = (
        residency_result.classification_without_election if election else classification
    ) == "nonresident"

    statuses, status_assumed = _candidate_statuses(profile, classification, year, no_joint=state.no_joint)
    if state.joint_blocked:
        # P-018: a confirmed joint status the facts rule out (a recorded decline with a
        # nonresident in the couple, or neither spouse a U.S. citizen or resident) is
        # never priced as a joint return under nonresident rules, nor under an election
        # the facts refuse — it is priced married-filing-separately, named FIRST below.
        statuses = [_MFS]
    deps = _dependent_infos(profile, year)
    spouse_split = income.spouse is not None and married
    # P-018 (the J0 re-verify follow-up) and P-013 rule (e): each spouse's SEPARATE
    # return follows that spouse's OWN classification — never the taxpayer's. A US
    # citizen or resident spouse of a nonresident files Form 1040 (standard deduction,
    # regular and preferential rates, deposit interest taxed); a spouse whose own facts
    # classify nonresident files Form 1040-NR (no standard deduction, the 871(i)(2)(A)
    # exclusion) in either direction; a spouse whose residency is unknown is not
    # assumed nonresident (resident rules, with a disclosure — the no-guessing rule —
    # and the range prices that return under nonresident rules too) — EXCEPT on the
    # no-joint path (a recorded decline), whose premise is a nonresident in the couple:
    # when the taxpayer is not that nonresident, the spouse of unknown residency is
    # (spouse_nra_assumed), every candidate prices the spouse on that one reading, and
    # the range prices the resident one. Under the election both spouses are residents,
    # so the direction is moot.
    spouse_direction = _spouse_nra_direction(profile, year) if married and not election else None
    tp_ident = profile.identity
    taxpayer_not_nra = own_classification == "resident" or (
        tp_ident is not None and tp_ident.us_person is not None and tp_ident.us_person.value is True
        and own_classification not in ("nonresident", "dual_status_candidate")
    )
    spouse_nra_assumed = state.no_joint and spouse_direction == "conditional" and taxpayer_not_nra
    spouse_dual_status = spouse_direction == "conditional" and _spouse_own_classification(profile, year) == (
        "dual_status_candidate")
    spouse_nra_reading = spouse_direction == "nonresident" or spouse_nra_assumed
    spouse_nonresident = spouse_split and spouse_nra_reading
    spouse_mfs_return = spouse_split and _MFS in statuses
    # A married filer's head of household (Pub 501, Considered Unmarried) comes by one of two
    # routes. The NONRESIDENT-SPOUSE route (spouse_nra_reading) — the spouse's return on Form
    # 1040-NR rules, and the filer "may still be considered married for purposes of the earned
    # income credit (EIC)" (Pub 519 ch. 5; the separated-spouse rule is not modeled), so no
    # EITC, with or without a spouse snapshot, and the couple's one deduction method (the
    # literal IRC 63(c)(6)(A) reading). The LIVED-APART route ("Your spouse didn't live in your
    # home during the last 6 months of the tax year") — a resident spouse and a free deduction
    # method (Pub 501); for the EITC the separated-spouse rule needs a qualifying child, so a
    # lived-apart figure with none computes no EITC either.
    hoh_spouse_nra = spouse_nra_reading
    eitc_qualifying_child = any(a is not None and 0 <= a < 19 and ssn is True for a, ssn in deps)
    # The separated-spouse rule (IRC 32(d)(2)) starts in TY2021; before it a lived-apart HOH was
    # unmarried for the EITC under IRC 7703(b), so the qualifying-child gate is year-bound.
    lived_apart_no_eitc = year >= 2021 and not eitc_qualifying_child
    notes: set[str] = set()  # disclosure keys accumulated across every candidate status
    mfs_method: dict[str, str | None] = {}  # the couple's deduction method on the two-return MFS pair

    def _mfs_pair(
        spouse_nra: bool, self_status: str = _MFS, *, lived_apart_hoh: bool = False, married_for_eitc: bool = False,
    ) -> tuple[BottomLineResult, str | None, set[str]]:
        """F10: a TRUE two-return MFS comparison — one MFS return per spouse, bottom lines
        summed. All dependents go to the primary taxpayer (disclosed as an assumption;
        reallocating them could change it).

        The couple uses ONE deduction method (IRC 63(c)(6)(A): the standard deduction is
        zero for "a married individual filing a separate return where either spouse
        itemizes deductions"), so when either return has itemized deductions both
        methods are priced and the better total is kept — Pub 501: "You and your spouse
        can use the method that gives you the lower total tax". Each run keeps its own
        disclosure keys; only the kept run's reach ``notes``.

        ``lived_apart_hoh``: a head of household considered unmarried because the spouses
        live apart may take the standard deduction while the spouse itemizes — Pub 501,
        Married Filing Separately: "The head of household filing status allows you to
        choose the standard deduction even if your spouse chooses to itemize deductions"
        — so that combination ('standard+itemize') is priced too; the spouse's separate
        return itemizes whenever the head of household does (IRC 63(c)(6)(A)).
        ``married_for_eitc``: the head of household is still married for the EITC (the
        nonresident-spouse route, Pub 519 ch. 5), so no EITC on that return.
        """
        self_income = income.model_copy(update={"spouse": None})

        def _run(self_mode: str | None, spouse_mode: str | None):
            local: set[str] = set()
            rs = _bottom_line(
                self_income, self_status, year, knowledge_dir, nonresident=nonresident, deps=deps, notes=local,
                deduction_mode=self_mode, married_for_eitc=married_for_eitc,
            )
            rp = _bottom_line(
                income.spouse, _MFS, year, knowledge_dir, nonresident=spouse_nra, deps=[], notes=local,
                deduction_mode=spouse_mode,
            )
            return rs, rp, local

        # Two nonresident returns have no standard deduction to lose (IRC 63(c)(6)(B)), so
        # the method is weighed only when at least one return is a resident's.
        if (not nonresident or not spouse_nra) and any(
            (snap.itemized_deductions or 0) > 0 for snap in (self_income, income.spouse)
        ):
            combos = {"standard": ("standard", "standard"), "itemize": ("itemize", "itemize")}
            if lived_apart_hoh:
                combos["standard+itemize"] = ("standard", "itemize")
            runs = {m: _run(*modes) for m, modes in combos.items()}
            method: str | None = max(runs, key=lambda m: (runs[m][0].bottom + runs[m][1].bottom, m == "standard"))
        else:
            method = None
            runs = {None: _run(None, None)}
        res_self, res_spouse, local = runs[method]
        total = res_self.bottom + res_spouse.bottom
        comp = [
            *res_self.lines[:-1],  # drop the per-return bottom line (a zero-effect subtotal)
            # The spouse's whole return folds into ONE operand row; its bottom
            # line ADDS to the combined total, so effect = +amount — the single
            # exception to the effect = -amount convention.
            _line(
                "spouse_mfs_return",
                label="Spouse's MFS return (computed separately)",
                amount=res_spouse.bottom,
                effect=res_spouse.bottom,
            ),
            _line("bottom_line", label=_BOTTOM_LINE_LABEL, amount=total),
        ]
        _reconcile(total, comp)
        result = BottomLineResult(bottom=total, lines=comp, citations=[*res_self.citations, *res_spouse.citations])
        return result, method, local

    def _outcome(status: str) -> BottomLineResult:
        if spouse_split:
            if status == _MFS:
                result, method, local = _mfs_pair(spouse_nonresident)
                notes.update(local)
                mfs_method["method"] = method
                return result
            if status == "head_of_household":
                # Every married head-of-household figure with a spouse snapshot (a married
                # filer reaches HOH only as "considered unmarried", Pub 501, and only MFJ
                # combines two people's income): your head-of-household return plus the
                # spouse's separate one, on the route hoh_spouse_nra names (above).
                result, method, local = _mfs_pair(
                    hoh_spouse_nra, "head_of_household", lived_apart_hoh=not hoh_spouse_nra,
                    married_for_eitc=hoh_spouse_nra or lived_apart_no_eitc,
                )
                notes.update(local)
                mfs_method["hoh_method"] = method
                return result
            # Combined (joint) return: income is summed, but the per-PERSON pieces —
            # the excess-SS credit and Schedule SE — are computed per spouse.
            return _bottom_line(
                income.combined_with_spouse(), status, year, knowledge_dir, nonresident=nonresident, deps=deps,
                ss_withheld_groups=[
                    list(income.ss_withheld_by_employer),
                    list(income.spouse.ss_withheld_by_employer),
                ],
                se_persons=[
                    (income.self_employment_net, income.wages),
                    (income.spouse.self_employment_net, income.spouse.wages),
                ],
                notes=notes,
            )
        # A married head of household with no spouse snapshot: the same EITC rule (above).
        married_hoh = status == "head_of_household" and married and not election
        return _bottom_line(
            income, status, year, knowledge_dir, nonresident=nonresident, deps=deps, notes=notes,
            married_for_eitc=married_hoh and (hoh_spouse_nra or lived_apart_no_eitc),
        )

    outcomes = {s: _outcome(s) for s in statuses}
    primary = statuses[0]
    point, composition, citations = outcomes[primary].bottom, outcomes[primary].lines, outcomes[primary].citations
    # A DEFINITE 6013(h) choice (read from a joint status, never a recorded answer that an
    # earlier 6013(g) election may explain) has no separate figure: "You and your spouse
    # must file a joint return for the year of the choice" (Pub 519 ch. 1). It stays in
    # the disclosure but leaves the range and the comparison.
    priced = {
        s: r for s, r in outcomes.items()
        if not (election and state.kind == "h" and s == _MFS and s != primary)
    }
    values = [r.bottom for r in priced.values()]
    # A spouse whose residency is not settled (a declared non-US person with no facts
    # that classify them, or a dual-status year) has the separate return computed under
    # RESIDENT rules — never the taxpayer's borrowed flag — and the range brackets the
    # other reading: the same pair with the spouse on Form 1040-NR rules (P-018).
    spouse_nra_alternative: int | None = None
    if spouse_mfs_return and spouse_direction == "conditional":
        spouse_nra_alternative = _mfs_pair(not spouse_nonresident)[0].bottom
        values.append(spouse_nra_alternative)
    # The same for a CONFIRMED head-of-household figure: the other route (P-018, above). An
    # unconfirmed candidate's lived-apart reading rests on an unrecorded fact, so the note
    # names it without widening the range.
    hoh_alternative: int | None = None
    if (
        "head_of_household" in priced and married and not election and spouse_direction == "conditional"
        and _confirmed_status(profile) == "head_of_household"
        and classification not in ("nonresident", "dual_status_candidate")  # priced as given (JF1b.12)
    ):
        alt_nra = not hoh_spouse_nra
        if spouse_split:
            hoh_alternative = _mfs_pair(
                alt_nra, "head_of_household", lived_apart_hoh=not alt_nra,
                married_for_eitc=alt_nra or lived_apart_no_eitc,
            )[0].bottom
        else:
            hoh_alternative = _bottom_line(
                income, "head_of_household", year, knowledge_dir, nonresident=nonresident, deps=deps,
                married_for_eitc=alt_nra or lived_apart_no_eitc,
            ).bottom
        values.append(hoh_alternative)
    low, high = min(values), max(values)

    comparison = _build_comparison(priced)
    roadmap = _build_roadmap(profile, year, residency_result, kind=state.kind)

    # De-duplicate citations by (source, url).
    seen, unique_citations = set(), []
    for c in citations:
        key = (c.source, c.url)
        if key not in seen:
            seen.add(key)
            unique_citations.append(c)

    # Everything the candidates' compositions mention, for conditional disclosures
    # (the MFS low end can trigger a line the headline status does not).
    labels = " ".join(line.label for r in outcomes.values() for line in r.lines)

    assumptions: list[str] = []
    missing_blocks: list[MissingBlock] = []
    if status_assumed:
        assumptions.append(
            f"Filing status not confirmed — showing the range across {', '.join(statuses)}. "
            f"Confirm your status to get a single number."
        )
    elif state.joint_blocked:
        assumptions.append(
            f"Filing status: {primary} — priced in place of the confirmed married_filing_jointly, which these "
            "facts rule out (see the first note)."
        )
    else:
        assumptions.append(f"Filing status: {primary}.")
    if income.itemized_deductions is None and not nonresident:
        assumptions.append("Standard deduction assumed (no itemizing, and no age-65+/blind adjustment).")
    method = mfs_method.get("method")
    if nonresident:
        # 1040-NR deduction law: itemized-only, never the standard deduction.
        forgone = (
            " (on the married-filing-separately figure the couple's deduction method claims none of them — see "
            "the married-filing-separately deduction note)"
            if method == "standard" and (income.itemized_deductions or 0) > 0
            else ""
        )
        assumptions.append(
            f"Nonresident aliens cannot take the standard deduction: Form 1040-NR line 12 is "
            f"ITEMIZED-only (typically state/local income tax withheld), so this estimate used "
            f"${income.itemized_deductions or 0:,} of itemized deductions{forgone}."
        )
        assumptions.append(
            "Exception: students/business apprentices from India MAY claim the standard deduction "
            "under US-India treaty Art. 21(2) — confirm nationality and treaty eligibility, and if "
            "it applies, rerun with itemized_deductions set to the standard-deduction amount."
        )
    if _section_6013_recorded(profile) and not election and not state.precondition_unmet:
        assumptions.append(
            "residency_facts.section_6013_election is recorded, but it was NOT applied: "
            f"{_election_not_applied_reason(profile, year, unavailable=state.unavailable)}. Residency follows the "
            "visa timeline and day counts."
        )
    if method is not None:
        assumptions.append(_mfs_deduction_method_note(
            method, income.model_copy(update={"spouse": None}), income.spouse,
            self_nonresident=nonresident, spouse_nonresident=spouse_nonresident,
        ))
    if "head_of_household" in outcomes and married and not election:
        assumptions.append(_hoh_pair_note(
            spouse_nra=hoh_spouse_nra, weighed=mfs_method.get("hoh_method") is not None,
            unsettled=spouse_direction == "conditional", alternative=hoh_alternative, snapshot=spouse_split,
            taxpayer_nonresident=classification in ("nonresident", "dual_status_candidate"),
            eitc_child=not lived_apart_no_eitc,
        ))
    if spouse_mfs_return and (nonresident != spouse_nonresident):
        # P-018: the spouse's separate return ran under the spouse's OWN rules — say which.
        assumptions.append(_spouse_separate_return_note(
            profile, year, spouse_nonresident=spouse_nonresident, income=income.spouse, deduction_method=method,
        assumed=spouse_nra_assumed, dual_status=spouse_dual_status,
        ))
    if spouse_nra_alternative is not None:
        if spouse_nra_assumed:
            reading = (
                "NONRESIDENT rules (Form 1040-NR) for the point estimate — the reading the recorded decline rests "
                "on, since a joint return is ruled out only when a spouse is a nonresident alien — and the range "
                "ALSO prices it under RESIDENT rules (Form 1040: the standard deduction, the regular and "
                "preferential rates, deposit interest taxed)"
            )
        else:
            reading = (
                "RESIDENT rules for the point estimate — never by borrowing your classification — and the range "
                "ALSO prices it under NONRESIDENT rules (Form 1040-NR: no standard deduction, ordinary rates, the "
                "IRC 871(i)(2)(A) deposit-interest exclusion)"
            )
        assumptions.append(
            "The spouse's own residency is not settled (no visa timeline and day counts that classify them, or a "
            f"dual-status year), so the spouse's separate return was computed under {reading}: "
            "married-filing-separately would then total "
            f"{'+' if spouse_nra_alternative >= 0 else '-'}${abs(spouse_nra_alternative):,} (+ refund / - owed). "
            "Record the spouse's visa timeline and days in the US to settle it."
        )
    # The nonresident-income disclosures name only amounts that sit on a NONRESIDENT's
    # return (P-018): the primary's when the primary classifies nonresident, and the
    # spouse's SEPARATE (MFS) return when the spouse's OWN facts classify nonresident —
    # in either direction, since each return follows its own payee. spouse_split also
    # requires a confirmed marriage, so an ignored spouse snapshot never inflates a
    # disclosed amount. The FDAP note covers exactly the same returns: every return
    # computed under the nonresident rules, and no other.
    # The spouse's separate return inside a head-of-household figure on the nonresident-spouse
    # route runs on Form 1040-NR rules too, so its amounts are disclosed alike (P-013 rule (c)).
    spouse_hoh_nra_return = spouse_split and "head_of_household" in statuses and hoh_spouse_nra and not election
    spouse_nra_return = (spouse_nonresident and spouse_mfs_return) or spouse_hoh_nra_return
    nra_snapshots = ([income] if nonresident else []) + ([income.spouse] if spouse_nra_return else [])
    nra_investment_income = any(
        (snap.interest - snap.bank_deposit_interest) or snap.dividends
        or snap.capital_gain_long or snap.capital_gain_short
        for snap in nra_snapshots
    )
    if nra_investment_income:
        assumptions.append(
            "Nonresident investment income is NOT modeled: US-source FDAP income (dividends, "
            "non-portfolio interest, certain gains) is taxed at a flat 30% or treaty rate on "
            "Schedule NEC — never at the resident preferential rates — while only effectively "
            "connected income uses graduated rates. This estimate taxed every such amount entered as "
            "ECI ordinary income (characterized bank_deposit_interest is the one exclusion it does "
            "model — see its own line); confirm the ECI-vs-FDAP treatment (Pub 519 ch. 4) before "
            "relying on it."
        )
    # N-8 / P-013: the §871(i)(2)(A) exclusion is MODELED, and each disclosure names
    # the amount it applies to — never a generic "may OVERTAX". The EXCLUDED amounts
    # come from the returns _bottom_line actually excluded them on: a nonresident's
    # non-joint return (the MFJ gate taxes it — a nonresident is on a joint return only
    # through the election), and the spouse's separate return when the spouse's own
    # facts classify nonresident. Deriving them from the flag alone once told a
    # nonresident on a contradictory joint status the interest was excluded while the
    # joint figure taxed it (P-013 rule (c): the text must match the number).
    primary_excludes = nonresident and any(s != _MFJ for s in statuses)
    spouse_excludes = spouse_nra_return
    excluded_snapshots = ([income] if primary_excludes else []) + ([income.spouse] if spouse_excludes else [])
    deposit_total = sum(snap.bank_deposit_interest for snap in excluded_snapshots)
    uncharacterized_interest = sum(snap.interest - snap.bank_deposit_interest for snap in excluded_snapshots)
    # A JOINT return taxes BOTH spouses' interest whatever either one's residency, and so
    # does every return under the election; those disclosures name the household amounts.
    joint_snapshots = [income] + ([income.spouse] if spouse_split else [])
    joint_deposit = sum(snap.bank_deposit_interest for snap in joint_snapshots)
    joint_uncharacterized = sum(snap.interest - snap.bank_deposit_interest for snap in joint_snapshots)
    # The ELECTION posture: every figure under the election, or the joint candidate of a
    # couple whose spouse's own facts classify nonresident (that joint return, too,
    # exists only under the election). Its figures tax the interest whatever its character.
    election_figures = election or (_MFJ in statuses and spouse_nonresident)
    # ... and every joint figure of a nonresident: the MFJ gate taxes the interest there
    # too, even on a contradictory profile the election was not read into.
    joint_posture = election_figures or (nonresident and _MFJ in statuses)
    recorded_election = election and not election_implied
    if deposit_total > 0:
        where = (
            ""
            if primary_excludes
            else " on the spouse's separate (married-filing-separately) return — the spouse's own facts classify "
            "them as a nonresident alien"
            if not spouse_nra_assumed
            else " on the spouse's separate return — priced as a nonresident alien's, the reading the recorded "
            "decline rests on ("
            + ("the spouse's own facts show a dual-status year" if spouse_dual_status
               else "the spouse's residency is not on file") + ")"
        )
        assumptions.append(
            f"US bank-deposit interest of ${deposit_total:,} was EXCLUDED from income{where}: IRC 871(i)(1) "
            f"imposes no 30% tax on 871(i)(2)(A) 'interest on deposits, if such interest is not "
            f"effectively connected with the conduct of a trade or business within the United States' "
            f"('deposits' per 871(i)(3): deposits with persons carrying on the banking business, "
            f"deposits or withdrawable accounts with savings institutions, and amounts held by an "
            f"insurance company under an agreement to pay interest); Pub 519 ch. 3 (Exclusions From "
            f"Gross Income — Interest Income) excludes it from gross income, and the Instructions for "
            f"Form 1040-NR (line 2b, Exception 3) say not to report it on line 2b. The exclusion is "
            f"conditioned on the CHARACTER you entered — confirm the payer is a bank, savings "
            f"institution or insurance company and the account is not part of a US trade or business. "
            f"It ENDS if a §6013(g)/(h) election treats you as a resident (the election, not the "
            f"marriage, makes the interest taxable)."
        )
    spouse_deposit_taxed = (
        income.spouse.bank_deposit_interest
        if spouse_mfs_return and not spouse_nonresident and not election
        and (nonresident or spouse_direction is not None)
        else 0
    )
    if spouse_deposit_taxed > 0:
        assumptions.append(
            f"On the spouse's separate return the spouse's ${spouse_deposit_taxed:,} of "
            f"bank_deposit_interest was NOT excluded: the IRC 871(i)(2)(A) exclusion belongs to a "
            f"NONRESIDENT payee, and the spouse's own facts do not classify them as a nonresident "
            f"alien (a US citizen or resident spouse is taxed on it on their Form 1040). If the "
            f"spouse is a nonresident, record the spouse's visa timeline and days in the US and "
            f"rerun."
        )
    if joint_posture and joint_deposit > 0:
        lead = (
            f"Under the §6013(g)/(h) election recorded on this profile the ${joint_deposit:,} of "
            f"bank_deposit_interest was NOT excluded on any figure here — joint or separate alike: under the "
            f"election"
            if recorded_election
            else f"On the joint-return figure the ${joint_deposit:,} of bank_deposit_interest was NOT "
            f"excluded: a nonresident alien is on a joint return only through the §6013(g)/(h) election, "
            f"under which"
        )
        quote = residency.section_6013_effect_quote(state.kind)
        assumptions.append(
            f"{lead} {quote} — so the IRC 871(i)(2)(A) exclusion does not apply and the interest is taxed. It is "
            f"the ELECTION, not the marriage, that ends the exclusion: married filing separately on Form 1040-NR "
            f"WITHOUT the election keeps it."
        )
    # Under the election the character of the interest no longer matters: telling the
    # filer 871(i)(2)(A) "excludes it — rerun" about an ELECTION figure would contradict
    # the disclosure above (P-013 rule (c)); that note speaks only for a nonresident's
    # own non-election return.
    if joint_posture and joint_uncharacterized > 0:
        figure = "every figure here (joint or separate)" if recorded_election else "the joint-return figure"
        assumptions.append(
            f"${joint_uncharacterized:,} of interest was entered without deposit character and was "
            f"taxed on {figure}. Under the §6013(g)/(h) election both spouses are treated "
            f"as residents for the entire tax year (Pub 519 ch. 1), so that interest is taxable whatever "
            f"its character — the IRC 871(i)(2)(A) deposit-interest exclusion and the Form 1040-NR "
            f"Schedule NEC treatment do not apply under the election."
        )
    if uncharacterized_interest > 0:
        where = "" if primary_excludes else "On the spouse's separate (married-filing-separately) return, "
        assumptions.append(
            f"{where}${uncharacterized_interest:,} of interest was entered WITHOUT deposit character "
            f"(interest minus bank_deposit_interest) and was taxed as effectively connected ordinary "
            f"income. If it is interest on a deposit with a US bank, savings institution or insurance "
            f"company that is not effectively connected with a US trade or business, IRC 871(i)(2)(A) "
            f"excludes it — rerun with that portion in bank_deposit_interest. If it is other "
            f"US-source interest not effectively connected with a US trade or business (bond or "
            f"brokerage interest; Treasury interest in 1099-INT box 3), it belongs on Schedule NEC "
            f"line 2 at 30%/treaty rate unless the 871(h) portfolio-interest exemption applies — "
            f"neither is modeled here."
        )
    ident = profile.identity
    declared_non_us_person = (
        ident is not None and ident.us_person is not None and ident.us_person.value is False
    )
    if not nonresident and declared_non_us_person and classification != "resident":
        # P-013 rule (b)'s "taxed and SAID to be" shape for the primary: a filer who
        # DECLARES they are not a US person but whose residency is not established as
        # nonresident (no visa timeline/day counts that classify it, or a dual-status
        # year, whose nonresident period is not modeled — JF5b.3) is taxed on a
        # characterized amount, and the note says why instead of leaving the field
        # silently inert. A resident (or a profile with no identity facts) keeps the
        # resident control: the field changes nothing and says nothing.
        entered_deposit = income.bank_deposit_interest + (
            income.spouse.bank_deposit_interest if spouse_split else 0
        )
        if entered_deposit > 0:
            assumptions.append(
                f"${entered_deposit:,} of bank_deposit_interest was taxed as ordinary interest: the IRC "
                f"871(i)(2)(A) deposit-interest exclusion applies only to a confirmed NONRESIDENT alien, and "
                f"this profile's residency is not established (record the visa timeline and days in the US "
                f"to classify it; a dual-status year's nonresident period is not modeled)."
            )
    treaty_amount = income.treaty_exempt_income + (
        income.spouse.treaty_exempt_income if income.spouse is not None else 0
    )
    if treaty_amount > 0:
        declared_us_person = (
            ident is not None and ident.us_person is not None and ident.us_person.value is True
        )
        assumptions.append(
            f"Treaty-exempt income (${treaty_amount:,}) was excluded exactly as supplied: this engine does NOT "
            f"validate treaty eligibility — the treaty country, article, dollar cap, saving-clause analysis, and "
            f"time limits are the agent's confirmed judgment (trust-the-agent semantics, like "
            f"itemized_deductions); confirm the article against the treaty text via get_sources before filing. "
            + _treaty_reporting_text(year, classification, declared_us_person, knowledge_dir)
            + " STATE conformity varies — some states re-tax federally treaty-exempt income; "
            "state_scope shows your state's treatment."
        )
        # Phase G cross-check: when the profile carries a citizenship country with a
        # shipped treaty pack, sanity-check the entered amount against that country's
        # student-wage rule. Advisory only — never a hard block (scholarship and
        # payments-from-abroad components are separately exempt without the wage limit).
        treaty_country = _citizenship_country(profile)
        if treaty_country is not None:
            total_wages = income.wages + (income.spouse.wages if income.spouse is not None else 0)
            cross_check = _treaty_cross_check(
                treaty_country, treaty_amount, year, knowledge_dir, total_wages=total_wages
            )
            if cross_check is not None:
                assumptions.append(cross_check)
    if "treaty_exclusion_clamped" in notes:
        assumptions.append(
            "The treaty-exempt amount entered exceeds the income in this snapshot, so the exclusion was CLAMPED "
            "— income components never go negative overall here. Check the treaty-exempt amount against the "
            "income actually entered before relying on this estimate."
        )
    if "preferential rates" in labels:
        assumptions.append(
            "Qualified dividends / net capital gain taxed at preferential rates via the Qualified "
            "Dividends and Capital Gain Tax Worksheet (the 25%/28% Schedule D Tax Worksheet cases — "
            "unrecaptured section 1250 gain, collectibles — are not modeled)."
        )
    if "Capital loss (limited" in labels:
        assumptions.append(
            "Net capital losses are deductible only up to $3,000 per year ($1,500 married filing "
            "separately) under IRC 1211(b); the disallowed remainder carries FORWARD indefinitely and "
            "KEEPS its short- or long-term character (IRC 1212(b)(1)). This snapshot clamps the "
            "deduction and tracks NO carryover, in either direction: a prior-year carryover coming in "
            "is not applied, and this year's excess is not carried out. Run calc op "
            "capital_loss_limitation for the real numbers — it reproduces Schedule D's Capital Loss "
            "Carryover Worksheet, splits the carryover short/long, and shows the trap this snapshot "
            "cannot see, that a LOW taxable income consumes less of the loss than it deducts and so "
            "leaves a LARGER carryover than 'loss minus $3,000'."
        )
    ss_benefits_present = income.social_security_benefits > 0 or (
        income.spouse is not None and income.spouse.social_security_benefits > 0
    )
    if ss_benefits_present:
        assumptions.append(
            "Taxable Social Security is computed with the benefits worksheet using this snapshot's "
            "other income (tax-exempt interest is not tracked — assumed $0; the student-loan-interest "
            "deduction is excluded from the worksheet's modified AGI per Pub 915). A "
            "married-filing-separately candidate assumes the spouses lived together during the year "
            "(both thresholds $0)."
        )
    # Disclose a surtax whenever ANY candidate status includes it (the MFS low end can
    # trigger Form 8959 while the MFJ headline does not).
    if "Form 8959" in labels:
        assumptions.append(
            "Additional Medicare Tax (Form 8959) included: 0.9% of wages/SE earnings over the status "
            "threshold. Box 1 wages stand in for box 5 Medicare wages; if your employer already withheld "
            "extra Medicare tax (W-2 box 6 above 1.45% of box 5), include that excess in the withholding "
            "input — it credits against this."
        )
    if "Form 8960" in labels:
        assumptions.append(
            "Net investment income tax (Form 8960) included: 3.8% of interest + dividends + net capital "
            "gain over the MAGI threshold, with MAGI approximated by AGI. Rents, royalties, and passive "
            "K-1 income are not captured by this snapshot and would increase it."
        )
    if income.wages and income.self_employment_net >= 400:
        assumptions.append(
            "Self-employment tax applies Schedule SE lines 8a-9 (W-2 wages consume the Social Security "
            "wage base first), using box-1 wages as the box-3 proxy — box 3 can differ (e.g. 401(k) deferrals)."
        )

    # Married-status candidates: worst-case bound vs true two-return split.
    if (
        status_assumed
        and {_MFJ, _MFS} <= set(statuses)
        and income.spouse is None
    ):
        assumptions.append(
            "The married-filing-separately figure puts ALL combined income and withholding on one MFS "
            "return — a worst-case bound, not a real two-return MFS outcome. Provide each spouse's own "
            "amounts for a true MFJ-vs-MFS comparison."
        )
    if spouse_split and _MFS in statuses:
        assumptions.append(
            "Married-filing-separately shown as a TRUE two-return comparison: each spouse's MFS return "
            "is computed separately from their own amounts and the bottom lines are summed (the MFJ "
            "figure combines both spouses on one return)."
        )
        if deps:
            assumptions.append(
                "For the MFS split, ALL dependents were allocated to the primary taxpayer's return; "
                "reallocating dependents between the spouses could change the comparison."
            )
    if married and not spouse_split and len(income.ss_withheld_by_employer) >= 2:
        assumptions.append(
            "The excess-Social-Security credit treats every ss_withheld_by_employer entry as ONE "
            "person's employers — on a joint return the per-person cap applies to each spouse "
            "separately. If these entries mix both spouses' W-2s, provide each spouse's own amounts "
            "(the spouse snapshot) for a per-spouse computation."
        )
    if income.spouse is not None and not spouse_split:
        # Never infer 'married' from income data: the spouse snapshot is IGNORED until
        # the marital-status fact is confirmed — disclosed loudly, never silently.
        assumptions.append(
            "IMPORTANT: a spouse income snapshot was provided but marital status is NOT confirmed as "
            "married, so the spouse's amounts (wages, withholding, everything) were NOT included in "
            "this estimate. Confirm your marital status to enable the MFJ/MFS spouse-split comparison."
        )

    # Dependent-credit disclosures.
    n_no_dob = sum(1 for a, _s in deps if a is None)
    if n_no_dob:
        assumptions.append(
            f"{n_no_dob} dependent(s) have no date of birth on file and were EXCLUDED from the Child "
            f"Tax Credit / Credit for Other Dependents and the EITC — provide each dependent's date of "
            f"birth (and whether they have a work-eligible SSN) to include them."
        )
    # A dependent with a known DOB but an UNANSWERED has_ssn (None — never asked) is
    # conservatively demoted from the per-child CTC to the ODC. Keep the math
    # conservative, but never silently: name the count and the dollar path.
    ssn_demotion_msg: str | None = None
    dep_ctc_cfg = None
    if any(a is not None and a >= 0 and s is None for a, s in deps):
        dep_credits = load_knowledge("federal", year, base_dir=knowledge_dir).credits
        dep_ctc_cfg = getattr(dep_credits, "child_tax_credit", None) if dep_credits is not None else None
    if dep_ctc_cfg:
        child_age_limit = int(dep_ctc_cfg.get("child_under_age", 17))
        n_ssn_unconfirmed = sum(1 for a, s in deps if a is not None and 0 <= a < child_age_limit and s is None)
        if n_ssn_unconfirmed:
            odc = int(dep_ctc_cfg["credit_for_other_dependents"])
            per_child = int(dep_ctc_cfg["per_qualifying_child"])
            ssn_demotion_msg = (
                f"{n_ssn_unconfirmed} dependent(s) under {child_age_limit} were counted for the "
                f"${odc:,} Credit for Other Dependents ONLY because SSN status was not confirmed — "
                f"with a work-eligible SSN each qualifies for the ${per_child:,} Child Tax Credit "
                f"instead (${(per_child - odc) * n_ssn_unconfirmed:,} more across "
                f"{n_ssn_unconfirmed} dependent(s), and they would count for the EITC). Confirm "
                f"each dependent's has_ssn."
            )
            assumptions.append(ssn_demotion_msg)
    if "fully refundable" in labels:
        assumptions.append(
            "2021 ARPA Child Tax Credit applied ($3,600 under age 6 / $3,000 under 18, two-tier "
            "phase-out, fully refundable) — this assumes a U.S. principal place of abode for more than "
            "half of 2021, and advance CTC payments already received (Letter 6419) are NOT reconciled "
            "here; they would reduce the credit left to claim."
        )
    if "additional child tax credit" in labels or "earned income tax credit" in labels:
        assumptions.append(
            "Earned income for the EITC / additional CTC is approximated as W-2 wages + 92.35% of "
            "self-employment profit; the official worksheets subtract the ½-SE-tax deduction and "
            "handle more categories."
        )
    if "earned income tax credit" in labels:
        assumptions.append(
            "EITC approximated by the formula; the official EIC table uses $50 income bands, so the "
            "filed amount can differ by roughly ±$27."
        )
        assumptions.append(
            "EITC qualifying children counted from dates of birth (under 19 at year end, with an SSN); "
            "19-23-year-old full-time students and permanently disabled children of any age are NOT "
            "counted here — tell us about them to raise the credit."
        )
        eitc_qc = sum(1 for a, s in deps if a is not None and 0 <= a < 19 and s is True)
        if eitc_qc == 0:
            assumptions.append(
                "The childless EITC also requires the filer (and spouse, if any) to be age 25-64 "
                "(2021: 19 or older) — your date of birth is not in this snapshot, so confirm the "
                "age test before counting on it."
            )
        if _MFS in statuses:
            assumptions.append(
                "EITC is never computed for the married-filing-separately candidate here; the narrow "
                "post-2021 separated-spouse exception (IRC 32(d)) is not modeled."
            )
    if "American opportunity credit" in labels:
        assumptions.append(
            "American opportunity credit: 40% treated as refundable — the Form 8863 line 7 "
            "under-age-24 exception (which makes the whole credit nonrefundable) is not evaluated."
        )
    # Dependent-care credit (Form 2441) disclosures — the credit is never silently
    # computed or silently dropped.
    if "child and dependent care credit" in labels:
        assumptions.append(
            "Child and dependent care credit (Form 2441) estimated from the expenses and "
            "qualifying-person count supplied. Not verified here: that the care let you (and your "
            "spouse) work, the qualifying-person tests, and each provider's name/address/TIN — "
            "Form 2441 Part I requires the provider TIN or the credit can be denied. "
            "Employer-provided dependent care benefits (W-2 box 10) REDUCE the credit and are NOT "
            "tracked in this snapshot — if box 10 is nonzero, recompute with the calc op "
            "dependent_care_credit (employer_benefits). The deemed $250/$500-per-month income rule "
            "for a full-time-student or disabled spouse is not applied."
        )
    if "child and dependent care credit (2021" in labels:
        assumptions.append(
            "2021 ARPA: the dependent-care credit was treated as REFUNDABLE, which requires a "
            "principal place of abode in the US (50 states or DC) for more than half of 2021 "
            "(Form 2441 line B) — if that test fails, the credit is nonrefundable and limited by tax."
        )
    if "dependent_care_mfs" in notes:
        assumptions.append(
            "The dependent-care credit is $0 on the married-filing-separately candidate — MFS filers "
            "are generally INELIGIBLE (Form 2441); the narrow treated-as-unmarried exception (lived "
            "apart the last 6 months + kept up the qualifying person's main home) is not modeled."
        )
    if "dependent_care_mfj_combined" in notes:
        assumptions.append(
            "The MFJ dependent-care credit assumed BOTH spouses have earned income of at least the "
            "allowed expenses — couple-combined amounts cannot split earned income per spouse, and "
            "the credit is limited by the LOWER-earning spouse's earned income (a spouse with no "
            "earned income makes it $0 absent the student/disabled deemed-income rule). Provide each "
            "spouse's own amounts (the spouse snapshot) for the real limitation."
        )
    if "dependent_care_squeezed" in notes:
        assumptions.append(
            "The Form 2441 dependent-care credit computed a positive amount but earlier nonrefundable "
            "credits already consumed the entire income tax, so $0 of it is used in this estimate — "
            "it is nonrefundable and cannot exceed the tax (2021 was the one refundable year)."
        )
    if "dependent_care_spouse_no_earned" in notes:
        assumptions.append(
            "The dependent-care credit is $0 because one spouse shows NO earned income — the Form 2441 "
            "limitation uses the LOWER-earning spouse. If that spouse was a full-time student or "
            "disabled, the deemed $250/$500-per-month income rule can restore the credit (agent "
            "judgment; recompute with calc op dependent_care_credit using the deemed amount)."
        )
    if "dependent_care_zero" in notes:
        assumptions.append(
            "The dependent-care expenses you supplied produced a $0 Form 2441 credit under the "
            "earned-income and expense-cap limitations — the inputs were evaluated, not dropped; "
            "see the calc op dependent_care_credit for the line-by-line work."
        )
    if income.dependent_care_expenses > 0:
        pack = load_knowledge("federal", year, base_dir=knowledge_dir)
        if pack.tax.dependent_care is None:
            missing_blocks.append(MissingBlock(
                block="tax.dependent_care",
                item="child and dependent care credit (Form 2441)",
                direction="understates_refund",
            ))
            assumptions.append(
                f"Dependent-care expenses were provided but the child and dependent care credit is "
                f"NOT computed for {year} (no Form 2441 parameters in the knowledge pack) — resolve "
                f"it separately; it could change the bottom line."
            )
    if "(Form 8962)" in labels:
        assumptions.append(
            "Premium tax credit reconciled with the Form 8962 ANNUAL method using the contiguous-48/DC "
            "poverty table; Alaska/Hawaii tables exist via the calc tool. Household income approximated "
            "as AGI plus nontaxable Social Security. The 1095-A amounts here are treated as FULL-YEAR "
            "totals — for part-year or month-varying coverage, compute the real Form 8962 lines 12-23 "
            "grid with the calc op ptc_monthly (12 rows of 1095-A monthly premium/SLCSP/APTC) and use "
            "that result on the return; shared policies and the alternative marriage-year computation "
            "remain out of scope."
        )
    if (income.aca_slcsp > 0 or income.aca_aptc > 0):
        pack = load_knowledge("federal", year, base_dir=knowledge_dir)
        if pack.tax.ptc is None:
            missing_blocks.append(MissingBlock(
                block="tax.ptc",
                item="premium tax credit reconciliation (Form 8962)",
                direction="either",
            ))
            assumptions.append(
                f"Form 1095-A amounts were provided but the premium tax credit is NOT computed for "
                f"{year} (Form 8962 parameters ship for 2023-2024 only) — reconcile it separately; "
                f"it could change the bottom line in either direction."
            )
        elif _MFS in statuses:
            assumptions.append(
                "MFS filers are generally not eligible for the premium tax credit (IRC 36B(c)(1)(C)); "
                "the estimate assumes no relief exception (domestic abuse / spousal abandonment) — "
                "APTC is repaid up to the Table 5 cap."
            )
    # ── Engaged-but-absent blocks: name every input that ENGAGED a block this
    # year's pack does not carry, with the direction of the error. The 2026
    # planning pack declares whole blocks deliberately absent, and before this
    # disclosure the estimator silently priced them at ZERO — a HoH parent's
    # $2,200 child tax credit simply vanished between the 2025 and 2026 numbers
    # with not one word in the assumptions. That violates this file's own
    # "evaluated, not dropped" rule and made the provisional marker's
    # "sufficient for projections" claim an overstatement. dependent_care and
    # ptc already had this treatment above; these are the gates that did not.
    # (excess-SS / Additional Medicare Tax / NIIT ship in every current pack —
    # instrumenting those gates lands with H4's ledger, not here.)
    pack_for_gaps = load_knowledge("federal", year, base_dir=knowledge_dir)
    known_dep_count = sum(1 for a, s in deps if a is not None and a >= 0)
    if known_dep_count and (
        pack_for_gaps.credits is None or getattr(pack_for_gaps.credits, "child_tax_credit", None) is None
    ):
        missing_blocks.append(MissingBlock(
            block="credits.child_tax_credit",
            item="child tax credit / credit for other dependents (and the EITC)",
            direction="understates_refund",
        ))
        assumptions.append(
            f"NOT ESTIMATED — child tax credit / credit for other dependents (and the EITC): the {year} "
            f"pack carries no credits block, so the {known_dep_count} dependent(s) on the profile added "
            f"$0 here. On a filing-grade year these credits are typically worth four figures per child, "
            f"so this bottom line likely UNDERSTATES your refund. Resolve them separately before "
            f"relying on a year-over-year comparison."
        )
    if income.social_security_benefits > 0 and pack_for_gaps.tax.taxable_social_security is None:
        missing_blocks.append(MissingBlock(
            block="tax.taxable_social_security",
            item="taxable Social Security worksheet",
            direction="overstates_refund",
        ))
        assumptions.append(
            f"NOT ESTIMATED — taxable Social Security: benefits were supplied but the {year} pack has "
            f"no taxable-Social-Security worksheet, so they were treated as $0 taxable. Up to 85% is "
            f"typically taxable, so this bottom line likely OVERSTATES your refund."
        )
    if (
        not nonresident
        and income.aotc_qualified_expenses
        and pack_for_gaps.tax.education_credits is None
    ):
        missing_blocks.append(MissingBlock(
            block="tax.education_credits",
            item="education credits (Form 8863 AOTC/LLC)",
            direction="understates_refund",
        ))
        assumptions.append(
            f"NOT ESTIMATED — education credits: 1098-T expenses were supplied but the {year} pack has "
            f"no Form 8863 parameters, so no AOTC/LLC was credited. This bottom line likely "
            f"UNDERSTATES your refund."
        )
    if (
        income.student_loan_interest_paid + (income.spouse.student_loan_interest_paid if income.spouse else 0)
    ) > 0 and pack_for_gaps.tax.student_loan_interest is None:
        missing_blocks.append(MissingBlock(
            block="tax.student_loan_interest",
            item="student-loan interest deduction (IRC 221)",
            direction="understates_refund",
        ))
        assumptions.append(
            f"NOT ESTIMATED — student-loan interest deduction: 1098-E interest was supplied but the "
            f"{year} pack has no IRC 221 phase-out parameters, so the deduction was $0. This bottom "
            f"line likely UNDERSTATES your refund."
        )
    if (
        not nonresident
        and (income.qualified_dividends > 0 or income.capital_gain_long > 0)
        and pack_for_gaps.tax.capital_gains_brackets is None
    ):
        missing_blocks.append(MissingBlock(
            block="tax.capital_gains_brackets",
            item="preferential rates for qualified dividends / net capital gain",
            direction="understates_refund",
        ))
        assumptions.append(
            f"NOT ESTIMATED — preferential rates: qualified dividends / long-term gains were supplied "
            f"but the {year} pack has no 0/15/20% breakpoints, so they were taxed at ORDINARY rates. "
            f"This bottom line likely OVERSTATES your tax."
        )
    if "ptc_below_100_fpl_no_aptc" in notes:
        assumptions.append(
            "Household income is below 100% of the federal poverty line and no advance PTC was paid, "
            "so the estimated-income safe harbor cannot apply — the premium tax credit is $0 (the "
            "lawfully-present-immigrant exception is not modeled)."
        )
    if "ptc_below_100_fpl_with_aptc" in notes:
        assumptions.append(
            "Household income is below 100% of the federal poverty line: the premium tax credit was "
            "still computed assuming the estimated-income safe harbor applies (APTC was paid based on "
            "a projected income of 100-400% FPL); if no exception (safe harbor / lawfully-present "
            "immigrant) applies, the PTC is $0 and the APTC repayment could grow."
        )
    if nonresident and (
        income.aotc_qualified_expenses
        or (income.spouse is not None and income.spouse.aotc_qualified_expenses)
    ):
        assumptions.append(
            "Education expenses were provided but NO education credit was estimated: nonresident "
            "aliens cannot claim education credits (Form 8863 AOTC/LLC) absent a residency election."
        )
    # A supplied 1098-E that computes to a $0 deduction is disclosed, never dropped.
    sli_paid = income.student_loan_interest_paid + (
        income.spouse.student_loan_interest_paid if income.spouse is not None else 0
    )
    if "sli_zero_phaseout" in notes:
        assumptions.append(
            f"The ${sli_paid:,} of student-loan interest (1098-E) gives a $0 deduction — modified "
            f"AGI is at or above the {year} IRC 221 phase-out ceiling for that status, so the "
            f"deduction phases out entirely. It was computed, not ignored — do NOT re-enter it "
            f"elsewhere (e.g. pre_agi_adjustments)."
        )
    if "sli_zero_mfs" in notes:
        assumptions.append(
            f"The ${sli_paid:,} of student-loan interest (1098-E) gives a $0 deduction on the "
            f"married-filing-separately candidate — MFS filers are not allowed the student-loan-"
            f"interest deduction (IRC 221). It was computed, not ignored."
        )
    # FICA withheld in error on an exempt nonresident is recovered OFF-return.
    # The election does not reach FICA (IRC 6013(g)(1): chapters 1 and 24 only), so this
    # note follows the day-count answer, not the elected one (P-018).
    nra_fica_msg: str | None = None
    if fica_nonresident and sum(income.ss_withheld_by_employer) > 0:
        ss_total = sum(income.ss_withheld_by_employer)
        nra_fica_msg = (
            f"${ss_total:,} of Social Security tax (W-2 box 4) was "
            f"withheld, but exempt F/J students and scholars are generally FICA-EXEMPT (IRC "
            f"3121(b)(19)): Social Security/Medicare withheld in error is recovered from the "
            f"EMPLOYER first, otherwise with Form 843 + Form 8316 — a separate claim, NOT on the "
            f"{'Form 1040' if election else '1040-NR'}. This estimate does not include it. The claim "
            f"would recover AT LEAST the "
            f"${ss_total:,} of box-4 Social Security tax PLUS the box-6 Medicare tax withheld — "
            f"Medicare withholding is not tracked in this snapshot, so add box 4 + box 6 from each "
            f"W-2 for the actual claim amount."
            + (f" {residency.SECTION_6013_FICA}" if election else "")
        )
        assumptions.append(nra_fica_msg)
    if election_figures and any(
        snap.interest + snap.dividends + snap.capital_gain_long + snap.capital_gain_short > 0
        for snap in joint_snapshots
    ):
        # P-018: the joint NIIT figure is a SECOND election's result (Treas. Reg.
        # 1.1411-2(a)(2)(iii)(B) for 6013(g), (iv)(B) for 6013(h)); the default is
        # married-filing-separately for NIIT. Every election figure carries it — the
        # recorded election's (joint AND separate), and the joint candidate of a couple
        # whose spouse's own facts classify nonresident.
        assumptions.append(_section_6013_niit_note(
            joint=_MFJ in statuses, separate=election and _MFS in statuses, kind=state.kind,
        ))
    assumptions.append(
        "Not modeled in this estimate: AMT, LLC (available via the calc tool), itemized-deduction "
        "sub-limits, EITC official-table $50 banding (formula used), capital-loss carryovers, and "
        "the retirement-savers credit — each could change the number. (The dependent-care credit IS "
        "estimated when dependent_care_expenses/persons are supplied.)"
    )
    assumptions.append("Before unclaimed credits not captured by these inputs — see what could change it.")

    # §6013(g)/(h) caveat (H1): surfaced in BOTH assumptions and what-would-change-it.
    ident = profile.identity
    us_person_false = (
        ident is not None and ident.us_person is not None and ident.us_person.value is False
    )
    residency_caveat: str | None = None
    if election:
        # P-018: the figures ran UNDER the election — say so, with the worldwide-income,
        # FICA, how-to and precondition caveats (the direction caveats below are moot).
        residency_caveat = _section_6013_caveat_in_effect(
            implied=election_implied,
            own_classification=own_classification,
            mfs_candidate=_MFS in statuses,
            kind=state.kind,
            marital_inferred=state.marital_inferred,
            # The W-7 last mile rides the election too (eval (o)): a spouse who is not a
            # U.S. person on the no-election facts and has no SSN/ITIN on file.
            spouse_needs_itin=_spouse_nra_direction(profile, year) is not None and not _spouse_has_tin(profile),
        )
    elif state.no_joint:
        # P-018: a recorded decline with a nonresident in the couple, or an election the
        # facts rule out — no caveat here presents a joint return as available.
        residency_caveat = _section_6013_no_joint_caveat(
            joint_blocked=state.joint_blocked,
            precondition_unmet=state.precondition_unmet,
            recorded=_section_6013_recorded(profile),
            spouse_unknown=spouse_direction == "conditional" and own_classification not in (
                "nonresident", "dual_status_candidate"),
            unavailable=state.unavailable,
        )
        if classification == "dual_status_candidate":
            residency_caveat += " " + _DUAL_STATUS_CAVEAT
    elif classification == "dual_status_candidate":
        # A dual-status year restricts statuses and the deduction; MFJ/HOH were
        # dropped and the numbers are full-year approximations — say so loudly.
        residency_caveat = _DUAL_STATUS_CAVEAT
    elif classification == "nonresident" and _is_married(profile):
        # MFJ was dropped for a confirmed married NRA — explain the §6013 election, or, when
        # the spouse's own facts classify nonresident too, that it is not available (P-018).
        residency_caveat = (
            "As a nonresident alien (Form 1040-NR) you cannot file jointly (MFJ). " + residency.SECTION_6013_SUSPENDED
            if state.unavailable
            else _SECTION_6013_CAVEAT.replace(
                "Showing married-filing-separately instead. ",
                "Married filing separately is generally the status open to you (the exceptions above). "
            ) if _confirmed_status(profile) == "head_of_household"
            else _SECTION_6013_CAVEAT
        )
    elif classification is None and us_person_false:
        # Visa holder whose residency is not yet determined — frame it conditionally.
        residency_caveat = _SECTION_6013_CONDITIONAL_CAVEAT
    elif spouse_direction is not None:
        # The common direction the primary-filer branches miss: a US-person or
        # resident-alien filer whose SPOUSE is (or may be) the nonresident. MFJ
        # stayed a candidate, so the §6013 election trade-offs (worldwide income,
        # the signed statement, the W-7/ITIN last mile) must ride along.
        residency_caveat = _spouse_6013_caveat(spouse_direction, _spouse_has_tin(profile), mfj_shown=_MFJ in statuses)
    if classification in ("nonresident", "dual_status_candidate") and _confirmed_status(profile) == "head_of_household":
        # Pub 519 ch. 5 (read 2026-09-27) bars the status outright; the confirmed status is
        # priced as given (JF1b.12), and the caveat says it is not open — prepended to whatever
        # residency caveat the facts carry, never replacing it (P-018).
        hoh_bar = (
            "A nonresident alien cannot file as head of household — Pub 519 ch. 5: \"You cannot file as head of "
            "household if you are a nonresident alien at any time during the tax year.\" This figure prices the "
            "confirmed head_of_household status as given; change it (generally married filing separately for a "
            "married filer — Pub 519 ch. 5 lists exceptions — otherwise single or, if eligible, qualifying "
            "surviving spouse) and rerun."
        )
        residency_caveat = hoh_bar if residency_caveat is None else f"{hoh_bar} {residency_caveat}"
    if residency_caveat is not None:
        # A joint status the facts rule out is the first thing the user reads (P-018).
        if state.joint_blocked:
            assumptions.insert(0, residency_caveat)
        else:
            assumptions.append(residency_caveat)

    changes: list[str] = []
    if residency_caveat is not None:
        changes.append(residency_caveat)
    if ssn_demotion_msg is not None:
        changes.append(ssn_demotion_msg)
    if nra_fica_msg is not None:
        changes.append(nra_fica_msg)
    if income.spouse is not None and not spouse_split:
        changes.append(
            "A spouse income snapshot was provided but NOT included (marital status is unconfirmed, "
            "and married is never inferred from income data); confirming your marital status enables "
            "the MFJ/MFS spouse-split comparison and would change this estimate materially."
        )
    pending = [d for d in profile.income_documents if d.status != "have"]
    if pending:
        kinds = ", ".join(sorted({d.kind for d in pending}))
        changes.append(f"You have unconfirmed or missing documents ({kinds}); confirming them changes income and tightens this estimate.")
    changes.append(
        "Child Tax Credit, EITC, education credits, and the premium tax credit are estimated when "
        "their inputs are present; missing inputs (dependent dates of birth and SSNs, Form 1098-T "
        "expenses, Form 1095-A amounts, your own age for the childless EITC) keep those parts "
        "directional — providing them changes the number."
    )
    if income.self_employment_net >= 400:
        changes.append("Self-employment tax is included; quarterly estimated payments you already made would reduce what you owe.")
    if status_assumed:
        changes.append("Confirming your filing status collapses the range to one number.")

    def _phrase(v: int) -> str:
        return f"a refund of about ${v:,}" if v > 0 else (f"owing about ${-v:,}" if v < 0 else "breaking even")

    if low == high:
        headline = f"Estimated bottom line: {_phrase(point)} (estimate — see assumptions)."
    elif low > 0:
        headline = f"Estimated refund between ${low:,} and ${high:,} (estimate — see assumptions)."
    elif high < 0:
        headline = f"You likely owe between ${-high:,} and ${-low:,} (estimate — see assumptions)."
    else:
        headline = f"Estimate ranges from {_phrase(low)} to {_phrase(high)} (estimate — see assumptions)."

    # A planning-only year (a pack authored before that year's forms published) must
    # never hand back a bottom line shaped exactly like a filing-grade one. calc got
    # this treatment when the guard landed; estimate_refund is the surface an agent
    # actually leads with, so it needs it more, not less.
    marker = provisional_marker("federal", year, base_dir=knowledge_dir)
    provisional = None
    if marker is not None:
        provisional = {
            "status": marker.status,
            "authored": marker.authored,
            "meaning": (
                f"PROJECTION-GRADE ONLY. The federal {year} knowledge pack was authored before that "
                f"year's forms, instructions and Tax Table published, and some blocks are deliberately "
                f"ABSENT — any 'NOT ESTIMATED' entries in the assumptions name real items this bottom "
                f"line omits, so read them before comparing it against a filing-grade year. Present "
                f"this as a PROJECTION, never as an estimate of a return you can file — fill_form, "
                f"verify_form and verify_filing all refuse this year."
            ),
            "still_assumed": marker.still_assumed,
        }
        assumptions = [
            f"PROJECTION, not an estimate of a filed return: the {year} federal knowledge pack is "
            f"marked '{marker.status}' because that year's forms and Tax Table are not published yet.",
            *assumptions,
        ]
        headline = f"PROJECTION (not filing-grade) — {headline}"

    return RefundEstimate(
        label=_PROJECTION_LABEL if provisional is not None else _LABEL,
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
        provisional=provisional,
        missing_blocks=missing_blocks,
        assumptions=assumptions,
        what_would_change_it=changes,
        citations=unique_citations,
        residency_caveat=residency_caveat,
    )
