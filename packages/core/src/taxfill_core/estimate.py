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
  AOTC, premium tax credit, excess-SS withholding), with every approximation
  disclosed as an assumption — never silently omitted and never silently
  invented;
- qualified dividends / net capital gain use the preferential-rate worksheet
  (``calc.tax_with_preferential_rates``) whenever such income is present — for
  RESIDENTS only: a nonresident's investment income follows ECI/FDAP rules the
  estimate does not model, so it is taxed at ordinary rates and disclosed.

The profile supplies the qualitative picture (filing status, dependents, which
documents are still missing); ``income`` supplies the confirmed dollar amounts
from extracted-and-confirmed documents (the profile schema holds an inventory,
not amounts).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taxfill_core import residency
from taxfill_core.calc import (
    additional_medicare_tax,
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
)
from taxfill_core.knowledge import Citation, load_knowledge
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
        default=0, ge=0, description="Taxable pension/IRA distributions (1099-R box 2a), taxed as ordinary income."
    )
    social_security_benefits: int = Field(
        default=0, ge=0,
        description="SSA-1099 box 5 net benefits; the TAXABLE portion is computed by the engine (0-85%).",
    )
    other_income: int = Field(default=0, ge=0, description="Other taxable income not in the fields above.")
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
        """The MFJ view: every amount summed across both spouses (lists concatenated)."""
        if self.spouse is None:
            return self
        s = self.spouse
        return IncomeSnapshot(
            **{
                f: getattr(self, f) + getattr(s, f)
                for f in (
                    "wages", "federal_withholding", "interest", "dividends", "qualified_dividends",
                    "capital_gain_long", "capital_gain_short", "self_employment_net",
                    "retirement_income_taxable", "social_security_benefits", "other_income",
                    "student_loan_interest_paid", "pre_agi_adjustments",
                    "aca_premiums", "aca_slcsp", "aca_aptc",
                )
            },
            ss_withheld_by_employer=[*self.ss_withheld_by_employer, *s.ss_withheld_by_employer],
            aotc_qualified_expenses=[*self.aotc_qualified_expenses, *s.aotc_qualified_expenses],
            itemized_deductions=(
                None
                if self.itemized_deductions is None and s.itemized_deductions is None
                else (self.itemized_deductions or 0) + (s.itemized_deductions or 0)
            ),
        )


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
    A DUAL-STATUS candidate year carries the same restrictions (Pub 519:
    generally no joint return absent a §6013(g)/(h) election, no HOH), so
    MFJ/HOH are dropped there too — disclosed loudly upstream.
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

_JOINT_LIABILITY_CAVEAT = (
    "Filing jointly (MFJ) makes both spouses jointly and severally liable for the whole tax; "
    "filing separately (MFS) avoids that shared liability but usually costs more in tax. Weigh "
    "the dollar difference against the liability you take on."
)

# Mirrors intake.py's §6013(g)/(h) wording: a nonresident alien filing 1040-NR cannot
# use MFJ unless they elect to be treated as a U.S. resident, which taxes worldwide income.
# The election makes the COUPLE'S worldwide income taxable, so an elected-MFJ number is
# only meaningful when the nonresident spouse's foreign income is in the inputs.
_SECTION_6013_CAVEAT = (
    "As a nonresident alien (Form 1040-NR) you cannot file jointly (MFJ); filing jointly "
    "requires electing under §6013(g)/(h) to treat the nonresident alien as a U.S. resident "
    "— which makes their worldwide income taxable. Showing married-filing-separately instead. "
    "If you weigh that election: an elected-MFJ figure is only valid when the nonresident "
    "spouse's WORLDWIDE (foreign) income is included in the inputs — put it in the spouse "
    "snapshot's other_income — otherwise an MFJ-vs-MFS comparison overstates the MFJ advantage."
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
    not model — taxed at ordinary rates and disclosed upstream). ``deps`` is
    the dependents' (age at year end, has_ssn) list — the profile itself is
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
    """
    citations: list[Citation] = []
    comp: list[CompositionLine] = []
    pack = load_knowledge("federal", year, base_dir=knowledge_dir)
    pack_tax = pack.tax
    credits_block = pack.credits
    mfs = status == _MFS

    # ── Income ──────────────────────────────────────────────────────────────
    base = income.total_income()

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
    st, lt = income.capital_gain_short, income.capital_gain_long
    combined_gain = st + lt
    capital = combined_gain
    if combined_gain > 0:
        comp.append(CompositionLine(label="Capital gain (net short-term + long-term)", amount=capital))
    elif combined_gain < 0:
        loss_cap = 1500 if mfs else 3000
        capital = max(combined_gain, -loss_cap)
        if capital != combined_gain:
            comp.append(
                CompositionLine(
                    label=f"Capital loss (limited to ${loss_cap:,} — the annual capital-loss cap)",
                    amount=capital,
                )
            )
        else:
            comp.append(CompositionLine(label="Capital loss (net short-term + long-term)", amount=capital))

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
                CompositionLine(label="Taxable Social Security benefits (worksheet)", amount=taxable_ss)
            )

    total_income = base + capital + taxable_ss
    comp.append(CompositionLine(label="Total income", amount=total_income))

    # ── Above-the-line adjustments ──────────────────────────────────────────
    if half_se:
        comp.append(CompositionLine(label="Less: ½ self-employment tax (adjustment)", amount=-half_se))

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
            comp.append(CompositionLine(label="Less: student loan interest deduction", amount=-sli))
        elif notes is not None:
            # A supplied 1098-E must never vanish silently: the deduction computed
            # to $0 (MFS by rule, or MAGI at/above the phase-out ceiling) — cite the
            # op's own work and surface the why upstream.
            citations.append(sli_res.citation)
            notes.add("sli_zero_mfs" if mfs else "sli_zero_phaseout")

    if income.pre_agi_adjustments > 0:
        comp.append(
            CompositionLine(
                label="Less: other above-the-line adjustments (confirmed)",
                amount=-income.pre_agi_adjustments,
            )
        )

    agi = total_income - half_se - sli - income.pre_agi_adjustments
    comp.append(CompositionLine(label="Adjusted gross income (AGI)", amount=agi))

    # ── Deduction and taxable income ────────────────────────────────────────
    if nonresident:
        # Form 1040-NR line 12 is ITEMIZED-ONLY (typically state/local income tax
        # withheld): a nonresident alien cannot take the standard deduction (Pub 519;
        # the India treaty Art. 21(2) student exception is disclosed upstream). The
        # max(itemized, standard) logic must never run here.
        deduction = income.itemized_deductions or 0
        label = "Less: itemized deductions (1040-NR — nonresidents cannot take the standard deduction)"
    else:
        sd = standard_deduction(status, year, knowledge_dir=knowledge_dir)
        citations.append(sd.citation)
        if income.itemized_deductions is not None:
            deduction = max(income.itemized_deductions, sd.amount)
            label = "Less: itemized deductions" if deduction == income.itemized_deductions else "Less: standard deduction"
        else:
            deduction, label = sd.amount, "Less: standard deduction"
    comp.append(CompositionLine(label=label, amount=-deduction))

    taxable = max(0, agi - deduction)
    comp.append(CompositionLine(label="Taxable income", amount=taxable))

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
            CompositionLine(
                label="Income tax (qualified dividends / net capital gain at preferential rates)",
                amount=income_tax,
            )
        )
    else:
        tax_res = tax_from_taxable_income(taxable, status, year, knowledge_dir)
        income_tax = tax_res.tax
        citations.append(tax_res.citation)
        comp.append(CompositionLine(label="Income tax", amount=income_tax))

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
            comp.append(CompositionLine(label="Less: education credits (nonrefundable part)", amount=-used_edu))

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
                    CompositionLine(label="Less: credit for other dependents (nonrefundable)", amount=-used_odc)
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
                    CompositionLine(
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
        comp.append(CompositionLine(label="Plus: self-employment tax", amount=se_amount))

    addmed_amount = 0
    if (income.wages or income.self_employment_net) and pack_tax.additional_medicare_tax is not None:
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
    investment_income = income.interest + income.dividends + capital
    # NRAs are generally not subject to NIIT (Form 8960 instructions).
    if investment_income > 0 and not nonresident and pack_tax.niit is not None:
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
                CompositionLine(
                    label="Plus: excess advance premium tax credit repayment (Form 8962)",
                    amount=ptc_repayment,
                )
            )

    total_tax = income_tax_after_credits + se_amount + addmed_amount + niit_amount + ptc_repayment
    comp.append(CompositionLine(label="Total tax", amount=total_tax))

    # ── Payments and refundable credits ─────────────────────────────────────
    # Negative, like every other "Less:" composition line (they reduce what you owe).
    comp.append(CompositionLine(label="Less: federal tax withheld / payments", amount=-income.federal_withholding))
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
                CompositionLine(
                    label="Less: excess Social Security withholding credit (Schedule 3)",
                    amount=-xss_credit,
                )
            )

    if actc:
        payments += actc
        comp.append(CompositionLine(label="Less: additional child tax credit (refundable)", amount=-actc))
    if rctc:
        payments += rctc
        comp.append(CompositionLine(label="Less: child tax credit (2021 — fully refundable)", amount=-rctc))

    # EITC: never for a nonresident alien or (as modeled) married filing separately;
    # gated by the investment-income limit; needs positive earned income.
    eitc_cfg = getattr(credits_block, "earned_income_tax_credit", None) if credits_block is not None else None
    if eitc_cfg and not nonresident and not mfs and earned > 0:
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
                    CompositionLine(
                        label="Less: earned income tax credit (refundable, formula approximation)",
                        amount=-eitc,
                    )
                )

    if aotc_refundable:
        payments += aotc_refundable
        comp.append(
            CompositionLine(label="Less: American opportunity credit (refundable 40%)", amount=-aotc_refundable)
        )
    if net_ptc:
        payments += net_ptc
        comp.append(CompositionLine(label="Less: net premium tax credit (Form 8962)", amount=-net_ptc))

    bottom = payments - total_tax
    comp.append(CompositionLine(label=_BOTTOM_LINE_LABEL, amount=bottom))
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
    residency_result = _classify_residency(profile, year)
    classification = residency_result.classification if residency_result is not None else None
    nonresident = classification == "nonresident"

    statuses, status_assumed = _candidate_statuses(profile, classification, year)
    deps = _dependent_infos(profile, year)
    married = _is_married(profile)
    spouse_split = income.spouse is not None and married
    notes: set[str] = set()  # disclosure keys accumulated across every candidate status

    def _outcome(status: str) -> tuple[int, list[CompositionLine], list[Citation]]:
        if spouse_split:
            if status == _MFS:
                # F10: a TRUE two-return MFS comparison — one MFS return per spouse,
                # bottom lines summed. All dependents go to the primary taxpayer
                # (disclosed as an assumption; reallocating them could change it).
                self_income = income.model_copy(update={"spouse": None})
                b_self, comp_self, cit_self = _bottom_line(
                    self_income, status, year, knowledge_dir, nonresident=nonresident, deps=deps, notes=notes
                )
                b_spouse, _comp_spouse, cit_spouse = _bottom_line(
                    income.spouse, status, year, knowledge_dir, nonresident=nonresident, deps=[], notes=notes
                )
                total = b_self + b_spouse
                comp = [
                    *comp_self[:-1],  # drop the per-return bottom line
                    CompositionLine(label="Spouse's MFS return (computed separately)", amount=b_spouse),
                    CompositionLine(label=_BOTTOM_LINE_LABEL, amount=total),
                ]
                return total, comp, [*cit_self, *cit_spouse]
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
        return _bottom_line(income, status, year, knowledge_dir, nonresident=nonresident, deps=deps, notes=notes)

    outcomes = {s: _outcome(s) for s in statuses}
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

    # Everything the candidates' compositions mention, for conditional disclosures
    # (the MFS low end can trigger a line the headline status does not).
    labels = " ".join(line.label for (_v, comp, _c) in outcomes.values() for line in comp)

    assumptions: list[str] = []
    if status_assumed:
        assumptions.append(
            f"Filing status not confirmed — showing the range across {', '.join(statuses)}. "
            f"Confirm your status to get a single number."
        )
    else:
        assumptions.append(f"Filing status: {primary}.")
    if income.itemized_deductions is None and not nonresident:
        assumptions.append("Standard deduction assumed (no itemizing, and no age-65+/blind adjustment).")
    if nonresident:
        # 1040-NR deduction law: itemized-only, never the standard deduction.
        assumptions.append(
            f"Nonresident aliens cannot take the standard deduction: Form 1040-NR line 12 is "
            f"ITEMIZED-only (typically state/local income tax withheld), so this estimate used "
            f"${income.itemized_deductions or 0:,} of itemized deductions."
        )
        assumptions.append(
            "Exception: students/business apprentices from India MAY claim the standard deduction "
            "under US-India treaty Art. 21(2) — confirm nationality and treaty eligibility, and if "
            "it applies, rerun with itemized_deductions set to the standard-deduction amount."
        )
    nra_investment_income = nonresident and any(
        snap is not None
        and (snap.interest or snap.dividends or snap.capital_gain_long or snap.capital_gain_short)
        for snap in (income, income.spouse)
    )
    if nra_investment_income:
        assumptions.append(
            "Nonresident investment income is NOT modeled: US-source FDAP income (dividends, "
            "non-portfolio interest, certain gains) is taxed at a flat 30% or treaty rate on "
            "Schedule NEC — never at the resident preferential rates — while only effectively "
            "connected income uses graduated rates. This estimate taxed every amount entered as "
            "ECI ordinary income; confirm the ECI-vs-FDAP treatment (Pub 519 ch. 4) before "
            "relying on it."
        )
    if nonresident and (
        income.interest or (income.spouse is not None and income.spouse.interest)
    ):
        assumptions.append(
            "US bank deposit interest is typically NOT taxable to a nonresident (the "
            "portfolio/deposit-interest exemption, IRC 871(i)) — the interest entered was taxed "
            "as ordinary income here, so this estimate may OVERTAX it."
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
            "separately); the disallowed remainder carries FORWARD to future years. Carryovers are "
            "not modeled here — a prior-year carryover coming in would also change this estimate."
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
    if "(Form 8962)" in labels:
        assumptions.append(
            "Premium tax credit reconciled with the Form 8962 ANNUAL method using the contiguous-48/DC "
            "poverty table; Alaska/Hawaii tables exist via the calc tool. Household income approximated "
            "as AGI plus nontaxable Social Security; monthly allocation, shared policies, and the "
            "alternative marriage-year computation are out of scope."
        )
    if (income.aca_slcsp > 0 or income.aca_aptc > 0):
        pack = load_knowledge("federal", year, base_dir=knowledge_dir)
        if pack.tax.ptc is None:
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
    nra_fica_msg: str | None = None
    if nonresident and sum(income.ss_withheld_by_employer) > 0:
        nra_fica_msg = (
            f"${sum(income.ss_withheld_by_employer):,} of Social Security tax (W-2 box 4) was "
            f"withheld, but exempt F/J students and scholars are generally FICA-EXEMPT (IRC "
            f"3121(b)(19)): Social Security/Medicare withheld in error is recovered from the "
            f"EMPLOYER first, otherwise with Form 843 + Form 8316 — a separate claim, NOT on the "
            f"1040-NR. This estimate does not include it."
        )
        assumptions.append(nra_fica_msg)
    assumptions.append(
        "Not modeled in this estimate: AMT, LLC (available via the calc tool), itemized-deduction "
        "sub-limits, EITC official-table $50 banding (formula used), capital-loss carryovers, and "
        "dependent-care/retirement-savers credits — each could change the number."
    )
    assumptions.append("Before unclaimed credits not captured by these inputs — see what could change it.")

    # §6013(g)/(h) caveat (H1): surfaced in BOTH assumptions and what-would-change-it.
    ident = profile.identity
    us_person_false = (
        ident is not None and ident.us_person is not None and ident.us_person.value is False
    )
    residency_caveat: str | None = None
    if classification == "dual_status_candidate":
        # A dual-status year restricts statuses and the deduction; MFJ/HOH were
        # dropped and the numbers are full-year approximations — say so loudly.
        residency_caveat = _DUAL_STATUS_CAVEAT
    elif classification == "nonresident" and _is_married(profile):
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
