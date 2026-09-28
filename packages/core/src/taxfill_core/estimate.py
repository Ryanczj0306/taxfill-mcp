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

import re
from datetime import date
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
    schedule_1a_deductions,
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
    "safe_harbor_inputs_from_estimate",
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


# The IncomeSnapshot fields its validator checks against each other (JF1b.6): a subset and
# its parent (qualified_dividends of dividends; bank_deposit_interest of interest, and
# bank_deposit_interest_nonresident_period of bank_deposit_interest), and the dependent-care
# expenses that need a qualifying person. A change to one member alone can leave an
# intermediate snapshot invalid, so compare_scenarios' input walk applies the overridden
# members of a group together, as ONE step. Keep this beside _check_internal_consistency:
# test_compare_scenarios fails for a validator whose fields are not grouped here.
INCOME_LINKED_FIELDS: tuple[frozenset[str], ...] = (
    frozenset({"interest", "bank_deposit_interest", "bank_deposit_interest_nonresident_period"}),
    frozenset({"dividends", "qualified_dividends"}),
    frozenset({"dependent_care_expenses", "dependent_care_persons"}),
    frozenset({"medicare_wages", "medicare_tax_withheld"}),  # box 6 needs box 5 (JF3)
)


class RetirementDistribution(BaseModel):
    """One Form 1099-R as read (JR3a): the estimator decides its taxable amount from the box 7 codes.

    Instructions for Forms 1099-R and 5498 (2026): a recharacterization carries "-0- (zero) in box 2a" with code
    N or R; a direct rollover is code G (box 2a -0- except a Roth-bound rollover of pre-tax money); code Q is a
    qualified Roth distribution; code P marks an excess contribution "taxable in" the PRIOR year. A traditional
    IRA's box 2a is the GROSS amount with box 2b 'Taxable amount not determined' checked, so an IRA with basis
    needs its own taxable figure (calc op ira_pro_rata) in ``taxable_override``."""

    model_config = ConfigDict(extra="forbid")

    gross: int = Field(ge=0, description="Box 1 — gross distribution.")
    taxable_amount: int | None = Field(default=None, ge=0, description="Box 2a — taxable amount; None when blank.")
    taxable_not_determined: bool = Field(default=False, description="Box 2b, 'Taxable amount not determined'.")
    total_distribution: bool = Field(default=False, description="Box 2b, 'Total distribution'.")
    codes: str = Field(default="", description="Box 7 (7a from 2026) distribution code(s), e.g. '7', 'G', '1B', 'JP'.")
    ira_sep_simple: bool = Field(default=False, description="Box 7 (7b from 2026) IRA/SEP/SIMPLE checkbox.")
    rolled_over: int = Field(
        default=0, ge=0,
        description="The recipient's disposition: what they rolled over within 60 days (not on the form).",
    )
    taxable_override: int | None = Field(
        default=None, ge=0,
        description="The recipient's own taxable figure (e.g. calc op ira_pro_rata's for an IRA with basis); wins "
                    "over box 2a.",
    )
    early_exception_amount: int = Field(
        default=0, ge=0, description="The part that meets an IRC 72(t)(2) exception (the additional tax: JR3c).",
    )
    federal_withholding: int = Field(
        default=0, ge=0,
        description="Box 4 — informational only: include it in the snapshot's federal_withholding as well.",
    )
    converted_to_roth: bool = Field(
        default=False,
        description="JR3b: this traditional/SEP/SIMPLE IRA distribution was converted to a Roth IRA (Form 8606 line "
                    "8), not kept (line 7).",
    )
    label: str = Field(default="", description="Which 1099-R (payer / account), for the assumptions.")


class IraPoolFacts(BaseModel):
    """One person's traditional/SEP/SIMPLE IRA pool for Form 8606 Part I (JR3b). IRC 408(d)(2) treats all of a
    person's such IRAs as one contract, and Form 8606 is filed per person, so a spouse's pool never merges."""

    model_config = ConfigDict(extra="forbid")

    basis_carryforward: int = Field(
        ge=0, description="Form 8606 line 2: nondeductible basis from earlier years. 0 is the explicit no-basis answer.",
    )
    nondeductible_contributions_this_year: int = Field(default=0, ge=0, description="Form 8606 line 1.")
    contributions_made_after_year_end: int = Field(
        default=0, ge=0, description="Form 8606 line 4: the part of line 1 made January 1 - April 15 of the next year.",
    )
    dec31_total_value: int | None = Field(
        default=None, ge=0,
        description="Form 8606 line 6: the December 31 value of ALL the person's traditional/SEP/SIMPLE IRAs "
                    "(extract.dec31_total_value_from_statements sums the year-end statements). Needed when there "
                    "is basis.",
    )


# Box 7 codes the estimator prices at $0 whatever box 2a says, and the one it moves to the prior year.
_RETIREMENT_ZERO_CODES = {"N": "a recharacterization", "R": "a recharacterization", "Q": "a qualified Roth distribution"}


def _retirement_taxable(item: RetirementDistribution) -> tuple[int, str | None]:
    """(taxable amount, the disclosure key or None) for one 1099-R, from its box 7 codes (JR3a)."""
    from taxfill_core.distribution_codes import parse_box7  # noqa: PLC0415

    codes = parse_box7(item.codes)
    if item.taxable_override is not None:
        return max(0, item.taxable_override - item.rolled_over), None
    if "P" in codes:
        return 0, "prior_year"
    if set(codes) & set(_RETIREMENT_ZERO_CODES):
        return 0, None
    if item.taxable_amount is None:
        if set(codes) & {"G", "H"}:
            return 0, None
        return max(0, item.gross - item.rolled_over), "blank_2a"
    note = "ira_gross" if item.taxable_not_determined and item.ira_sep_simple else ("roth_j" if "J" in codes else None)
    return max(0, item.taxable_amount - item.rolled_over), note


class W2Box12(BaseModel):
    """One box 12 entry (JT4a)."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="The code as printed (D, W, TT, ...) — knowledge/forms/w2_box12_codes.yaml.")
    amount: int = Field(ge=0)


class W2Facts(BaseModel):
    """One Form W-2 as read (JT4a) — the boxes the estimator prices. Give ``IncomeSnapshot.w2s`` and the
    aggregates (wages, ss_wages, medicare_wages, the per-employer box 4 / box 6 lists, the box 10 benefits,
    the box 12 TT overtime) are derived from them; an aggregate given as well must agree, or the snapshot is
    refused."""

    model_config = ConfigDict(extra="forbid")

    employer: str = Field(default="", description="Which W-2 (employer name), for the assumptions.")
    box1: int = Field(default=0, ge=0, description="Wages, tips, other compensation.")
    box2: int = Field(default=0, ge=0, description="Federal income tax withheld.")
    box3: int = Field(default=0, ge=0, description="Social security wages.")
    box4: int = Field(default=0, ge=0, description="Social security tax withheld.")
    box5: int = Field(default=0, ge=0, description="Medicare wages and tips.")
    box6: int = Field(default=0, ge=0, description="Medicare tax withheld.")
    box7: int = Field(default=0, ge=0, description="Social security tips.")
    box10: int = Field(default=0, ge=0, description="Dependent care benefits.")
    box12: list[W2Box12] = Field(default_factory=list)
    box14b: list[str] = Field(default_factory=list, description="2026 onward: Treasury Tipped Occupation Code(s).")

    def coded(self, *codes: str) -> int:
        return sum(e.amount for e in self.box12 if e.code.strip().upper() in codes)


_W2_402G_CODES = ("D", "E", "F", "S", "AA", "BB")   # IRC 402(g)(3) and 402A(c)(1) (w2_box12_codes.yaml)


def _w2_aggregates(w2s: list[W2Facts]) -> dict[str, Any]:
    return {
        "wages": sum(w.box1 for w in w2s),
        "ss_wages": sum(w.box3 + w.box7 for w in w2s),
        "medicare_wages": sum(w.box5 for w in w2s),
        "ss_withheld_by_employer": [w.box4 for w in w2s if w.box4],
        "medicare_tax_withheld": [w.box6 for w in w2s if w.box6],
        "dependent_care_benefits": sum(w.box10 for w in w2s),
    }


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
    interest: int = Field(
        default=0, ge=0,
        description=(
            "Taxable interest (1099-INT). A money market fund's payout is a DIVIDEND, not interest (Pub 550: "
            "\"amounts you receive from money market funds should be reported as dividends, not as "
            "interest\") — enter it in `dividends` (JF2.3, P-013 rule (g))."
        ),
    )
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
            "Interest Income) excludes it from gross income; the Instructions for Form 1040-NR (Exception 3 "
            "under the taxable-interest line, form_lines f1040nr.taxable_interest) say not to report it there. "
            "For a RESIDENT it changes nothing (all interest "
            "is taxable). In a DUAL-STATUS year only the part received before the residency starting date "
            "is excluded — record it in bank_deposit_interest_nonresident_period; the rest is taxed as "
            "resident-period interest. Under the §6013(g)/(h) election, which treats both spouses as residents for the "
            "whole year (Pub 519 ch. 1), it is taxed on a JOINT and on a SEPARATE return alike (a joint "
            "return is the only way a nonresident reaches one): the election, not the marriage, ends the "
            "exclusion. Interest left in `interest` "
            "without this character is taxed here as effectively connected ordinary income. Treasury / "
            "savings-bond interest (1099-INT box 3) and bond interest are NOT deposits — leave them out."
        ),
    )
    bank_deposit_interest_nonresident_period: int = Field(
        default=0, ge=0,
        description=(
            "The part of `bank_deposit_interest` RECEIVED before the residency starting date of a DUAL-STATUS "
            "year (a nonresident alien for part of the year, a resident for the rest) — a SUBSET of "
            "bank_deposit_interest, as that is of interest. Only on a return whose payee's OWN residency is a "
            "dual-status year and no §6013(g)/(h) election is in effect, this amount is excluded from income "
            "and the rest of bank_deposit_interest is taxed as resident-period interest: Treas. Reg. "
            "1.871-13(a)(1) taxes the year 'under two different sets of rules, one relating to resident aliens "
            "for the period of residence and the other relating to nonresident aliens for the period of "
            "nonresidence', and IRC 871(i)(1)-(2)(A) impose no tax on the nonresident's 'interest on deposits, "
            "if such interest is not effectively connected with the conduct of a trade or business within the "
            "United States' (Pub 519 ch. 6: U.S.-source income of either part is taxable 'unless specifically "
            "exempt under the Internal Revenue Code'). The law keys on receipt, so take the amount paid or "
            "credited before that date from the account statements — never a proration. The residency "
            "starting date under the substantial presence test is generally the first day of presence in the "
            "year (Pub 519 ch. 1). Under the election 1.871-13 'does not apply', so nothing is excluded; for a "
            "full-year resident or nonresident the field changes nothing (a nonresident's whole "
            "bank_deposit_interest is excluded)."
        ),
    )
    dividends: int = Field(
        default=0, ge=0,
        description=(
            "Ordinary dividends, 1099-DIV box 1a (includes qualified) — money market fund payouts included "
            "(Pub 550). For a NONRESIDENT alien, a fund's interest-related dividend (IRC 871(k)(1)(A)) is "
            "exempt from the 30% tax — never `bank_deposit_interest`, and not modeled here (P-013 rule (g))."
        ),
    )
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
    retirement_distributions: list[RetirementDistribution] = Field(
        default_factory=list,
        description="JR3a: each Form 1099-R as read — the estimator prices each from its box 7 codes (Q/N/R $0, "
                    "G/H box 2a, P moved to the prior year, an IRA's 2b-checked gross flagged for ira_pro_rata). "
                    "Mutually exclusive with retirement_income_taxable, the manual figure.",
    )
    # JR3c: IRC 4973 — 6% of an IRA excess contribution left in at year end, capped per person at the IRAs'
    # December 31 value (4973(a): "shall not exceed 6 percent of the value of the account").
    traditional_ira_excess: int = Field(
        default=0, ge=0, description="Form 5329 line 16: the traditional-IRA excess contributions at year end.")
    roth_ira_excess: int = Field(
        default=0, ge=0, description="Form 5329 line 24: the Roth IRA excess contributions at year end.")
    traditional_ira_dec31_value: int | None = Field(
        default=None, ge=0,
        description="The Dec 31 value of the traditional IRAs (with that year's contributions made next year) — the "
                    "excise cap. None: no cap applied (disclosed).")
    roth_ira_dec31_value: int | None = Field(
        default=None, ge=0, description="The same for the Roth IRAs.")
    ira_pool: IraPoolFacts | None = Field(
        default=None,
        description="JR3b: THIS person's IRA pool — required when a traditional-IRA 1099-R has box 2b 'Taxable amount "
                    "not determined' (Form 8606 Part I prices it). Per person: the joint view never merges pools.",
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
    # JF7 (LD-09): the OBBBA Schedule 1-A deductions (P.L. 119-21, taxable years 2025-2028) are taken
    # BELOW AGI, after the standard or itemized deduction: pre_agi_adjustments would move every MAGI test,
    # and itemized_deductions is max()'d away against the standard deduction. calc op
    # schedule_1a_deductions prices them; eligibility stays the caller's judgment, quoted in its work.
    qualified_tips: int = Field(
        default=0, ge=0,
        description="Qualified tips (Schedule 1-A Part II): voluntary cash tips in an occupation on the IRS tipped list.",
    )
    qualified_overtime_premium: int = Field(
        default=0, ge=0,
        description="Qualified overtime compensation (Schedule 1-A Part III): the FLSA-required PREMIUM half only.",
    )
    car_loan_interest: int = Field(
        default=0, ge=0,
        description="Qualified passenger vehicle loan interest (Schedule 1-A Part IV): a new, US-assembled vehicle for "
                    "personal use, the loan made after 2024 and secured by it, the VIN on the return.",
    )
    # JF9: IRC 170(p) (P.L. 119-21, taxable years beginning after December 31, 2025).
    charitable_cash_nonitemizer: int = Field(
        default=0, ge=0,
        description="Cash gifts that count for the non-itemizer deduction (IRC 170(p)): to a 170(b)(1)(A) "
                    "organization, not a 509(a)(3) supporting organization and not a donor advised fund — calc op "
                    "charitable_deduction checks each gift. Capped per return and used only when the standard "
                    "deduction wins; 2026 onward.",
    )
    senior_taxpayer: bool | None = Field(
        default=None,
        description="Schedule 1-A Part V: this snapshot's filer is 65 or older at year end with a valid SSN. None = "
                    "derived by estimate_refund from the profile's date of birth and tax ID.",
    )
    senior_spouse: bool | None = Field(
        default=None,
        description="The same for the spouse, counted on a joint return only. None = derived from the profile.",
    )
    ss_withheld_by_employer: list[int] = Field(
        default_factory=list,
        description="W-2 box 4 Social Security tax withheld, ONE ENTRY PER EMPLOYER (excess-SS credit needs 2+).",
    )
    # JF3 (pitfall P-019, box1-standin): box 1 leaves out the 401(k)/403(b) deferrals that boxes 3
    # and 5 keep, and an exempt F/J student's boxes 3 and 5 are $0 — so neither Form 8959 nor
    # Schedule SE may be priced on box 1 when the box itself is known.
    medicare_wages: int | None = Field(
        default=None, ge=0,
        description=(
            "W-2 box 5 Medicare wages and tips, the total of all W-2s — what Form 8959 prices (\"Medicare "
            "wages and tips from Form W-2, box 5. If you have more than one Form W-2, enter the total of the "
            "amounts from box 5\"). None: box 1 `wages` stands in, disclosed."
        ),
    )
    ss_wages: int | None = Field(
        default=None, ge=0,
        description=(
            "W-2 boxes 3 + 7 (social security wages and tips), the total of all W-2s — what Schedule SE "
            "subtracts from the social security wage base (\"total of boxes 3 and 7 on Form(s) W-2\"). "
            "None: box 1 `wages` stands in, disclosed."
        ),
    )
    medicare_tax_withheld: list[int] = Field(
        default_factory=list,
        description=(
            "W-2 box 6 Medicare tax withheld, ONE ENTRY PER EMPLOYER. What exceeds 1.45% of box 5 is Additional "
            "Medicare Tax withholding (Form 8959's withholding reconciliation), credited with federal income "
            "tax withholding — do NOT also add it to federal_withholding. Requires medicare_wages."
        ),
    )
    aotc_qualified_expenses: list[int] = Field(
        default_factory=list,
        description="AOTC-qualified education expenses, one entry per eligible student (1098-T-informed).",
    )
    aotc_students_ssn_ok: list[bool | None] = Field(
        default_factory=list,
        description="JT1e (2026 onward, P-024): one entry per aotc_qualified_expenses entry — True when the student is "
                    "you or your spouse, or a dependent issued a valid SSN (valid for employment) before the return's "
                    "due date including extensions; False for a dependent with only an ITIN/ATIN; missing or None = "
                    "not known, and that student's credit is NOT ESTIMATED.",
    )
    education_ssn_taxpayer: bool | None = Field(
        default=None,
        description="JT1e: this snapshot's filer holds a valid SSN issued before the due date. None = derived by "
                    "estimate_refund from the profile's tax ID (an ITIN starts with 9); still None = not known.",
    )
    education_ssn_spouse: bool | None = Field(
        default=None, description="The same for the spouse, counted on a joint return only. None = derived.",
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
    # JT4a: the W-2s as read. The aggregates above derive from them when not given, and must agree when given.
    w2s: list[W2Facts] = Field(
        default_factory=list,
        description="THIS person's Forms W-2 (boxes 1-7, 10, 12, 14b). wages, ss_wages, medicare_wages, "
                    "ss_withheld_by_employer, medicare_tax_withheld and dependent_care_benefits derive from them; "
                    "federal_withholding defaults to the box 2 total and may only be larger (estimated payments, other "
                    "withholding); qualified_overtime_premium defaults to the code TT total.",
    )
    dependent_care_benefits: int = Field(
        default=0, ge=0,
        description="W-2 box 10 employer-provided dependent care benefits (Form 2441 Part III) — they reduce the "
                    "dependent care credit's expense limit.",
    )

    @model_validator(mode="before")
    @classmethod
    def _derive_from_w2s(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not data.get("w2s"):
            return data
        w2s = [w if isinstance(w, W2Facts) else W2Facts.model_validate(w) for w in data["w2s"]]
        derived = _w2_aggregates(w2s)
        out = dict(data)
        mismatches = []
        for key, value in derived.items():
            given = out.get(key)
            if given in (None, [], 0) and key not in ("ss_withheld_by_employer", "medicare_tax_withheld"):
                out[key] = value
            elif key in ("ss_withheld_by_employer", "medicare_tax_withheld") and not given:
                out[key] = value
            elif (sorted(given) if isinstance(given, list) else given) != (
                    sorted(value) if isinstance(value, list) else value):
                mismatches.append(f"{key} {given!r} vs the W-2s' {value!r}")
        box2 = sum(w.box2 for w in w2s)
        if out.get("federal_withholding") in (None, 0):
            out["federal_withholding"] = box2
        elif out["federal_withholding"] < box2:
            mismatches.append(f"federal_withholding {out['federal_withholding']} is below the W-2s' box 2 total {box2}")
        tt = sum(w.coded("TT") for w in w2s)
        if tt and out.get("qualified_overtime_premium") in (None, 0):
            out["qualified_overtime_premium"] = tt
        if mismatches:
            raise ValueError(
                "the W-2 facts and the aggregates disagree: " + "; ".join(mismatches) + " — pass the W-2s alone "
                "(the aggregates derive from them) or fix the figure that was typed from the wrong box")
        return out

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
        if self.bank_deposit_interest_nonresident_period > self.bank_deposit_interest:
            raise ValueError(
                f"bank_deposit_interest_nonresident_period ({self.bank_deposit_interest_nonresident_period}) "
                f"cannot exceed bank_deposit_interest ({self.bank_deposit_interest}) — it is the SUBSET of the "
                f"deposit interest received before the residency starting date, so the same dollars are also in "
                f"bank_deposit_interest (and in interest)"
            )
        if self.medicare_tax_withheld and self.medicare_wages is None:
            raise ValueError(
                "medicare_tax_withheld (W-2 box 6) requires medicare_wages (W-2 box 5) — the Additional Medicare "
                "Tax withholding is box 6 less 1.45% of box 5, so it cannot be credited without box 5"
            )
        if any(v < 0 for v in self.medicare_tax_withheld):
            raise ValueError("medicare_tax_withheld entries are W-2 box 6 amounts and cannot be negative")
        if self.dependent_care_expenses > 0 and self.dependent_care_persons < 1:
            raise ValueError(
                f"dependent_care_expenses ({self.dependent_care_expenses}) requires "
                f"dependent_care_persons >= 1 — the number of qualifying persons sets the Form 2441 "
                f"expense cap, so the credit cannot be estimated without it (never silently dropped)"
            )
        if self.spouse is not None and self.spouse.spouse is not None:
            raise ValueError("spouse.spouse must be None — one nesting level only")
        if self.retirement_distributions and self.retirement_income_taxable:
            raise ValueError(
                "pass retirement_distributions (each 1099-R, interpreted per box 7 code) OR "
                "retirement_income_taxable (your own taxable total), not both — the same distributions "
                "would be counted twice"
            )
        return self

    def total_income(self) -> int:
        """Ordinary-income components only — capital gains/losses and the taxable part of
        Social Security are status-dependent and computed by the estimate, not here."""
        return (
            self.wages + self.interest + self.dividends + self.self_employment_net
            + self.retirement_income_taxable + self.other_income
            + sum(_retirement_taxable(item)[0] for item in self.retirement_distributions)
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
                    "wages", "federal_withholding", "interest", "bank_deposit_interest",
                    "bank_deposit_interest_nonresident_period", "dividends", "qualified_dividends",
                    "capital_gain_long", "capital_gain_short", "self_employment_net",
                    "social_security_benefits", "other_income",
                    "treaty_exempt_income", "student_loan_interest_paid", "pre_agi_adjustments",
                    "dependent_care_expenses", "aca_premiums", "aca_slcsp", "aca_aptc",
                    "qualified_tips", "qualified_overtime_premium", "car_loan_interest", "charitable_cash_nonitemizer",
                    "dependent_care_benefits",
                )
            },
            w2s=[*self.w2s, *s.w2s],
            **_joint_retirement(self, s),
            traditional_ira_excess=_capped_excess(self, "traditional") + _capped_excess(s, "traditional"),
            roth_ira_excess=_capped_excess(self, "roth") + _capped_excess(s, "roth"),
            senior_taxpayer=self.senior_taxpayer,
            senior_spouse=s.senior_taxpayer,
            ss_withheld_by_employer=[*self.ss_withheld_by_employer, *s.ss_withheld_by_employer],
            aotc_qualified_expenses=[*self.aotc_qualified_expenses, *s.aotc_qualified_expenses],
            aotc_students_ssn_ok=[*_ssn_oks(self), *_ssn_oks(s)],
            education_ssn_taxpayer=self.education_ssn_taxpayer,
            education_ssn_spouse=s.education_ssn_taxpayer,
            medicare_tax_withheld=[*self.medicare_tax_withheld, *s.medicare_tax_withheld],
            # JF3: a W-2 box summed across the couple; a spouse who did not give it contributes box 1 (the
            # stand-in, disclosed by the caller), and neither giving it keeps it None.
            medicare_wages=_box_or_wages_sum(self, s, "medicare_wages"),
            ss_wages=_box_or_wages_sum(self, s, "ss_wages"),
            dependent_care_persons=max(self.dependent_care_persons, s.dependent_care_persons),
            itemized_deductions=(
                None
                if self.itemized_deductions is None and s.itemized_deductions is None
                else (self.itemized_deductions or 0) + (s.itemized_deductions or 0)
            ),
        )


def _pooled(item: RetirementDistribution) -> bool:
    """A traditional/SEP/SIMPLE IRA item whose taxable part Form 8606 Part I decides (JR3b)."""
    from taxfill_core.distribution_codes import parse_box7  # noqa: PLC0415

    codes = set(parse_box7(item.codes))
    return (item.ira_sep_simple and item.taxable_not_determined and item.taxable_override is None
            and not codes & (set(_RETIREMENT_ZERO_CODES) | {"P", "G", "H"}))


def _resolve_ira_pool(snap: "IncomeSnapshot", year: int, knowledge_dir, who: str) -> "IncomeSnapshot":
    """Price one person's 2b-checked IRA items through calc op ira_pro_rata with THEIR pool (JR3b); the result
    rides on each item as taxable_override, so the joint view can concatenate without merging pools."""
    items = snap.retirement_distributions
    pooled = [i for i in items if _pooled(i)]
    if not pooled:
        return snap
    pool = snap.ira_pool
    if pool is None:
        raise ValueError(
            f"the {who}'s traditional-IRA 1099-R has box 2b 'Taxable amount not determined', so Form 8606 Part I "
            f"decides the taxable part (IRC 408(d)(2) pro-rata) — pass ira_pool for the {who}: "
            f"{{basis_carryforward: <Form 8606 line 2>, nondeductible_contributions_this_year: <line 1>, "
            f"dec31_total_value: <line 6>}}, or {{basis_carryforward: 0}} when there is no nondeductible basis")
    conv = [i for i in pooled if i.converted_to_roth]
    kept = [i for i in pooled if not i.converted_to_roth]
    basis = pool.basis_carryforward + pool.nondeductible_contributions_this_year
    if basis == 0:
        taxable_conv = sum(i.gross for i in conv)
        taxable_kept = sum(max(0, i.gross - i.rolled_over) for i in kept)
    else:
        if pool.dec31_total_value is None:
            raise ValueError(
                f"the {who}'s IRA pool carries basis, so Form 8606 line 6 is needed: pass ira_pool.dec31_total_value "
                f"(the December 31 value of every traditional/SEP/SIMPLE IRA — the year-end statements, "
                f"extract.dec31_total_value_from_statements)")
        from taxfill_core.calc import ira_pro_rata  # noqa: PLC0415

        pr = ira_pro_rata(
            dec31_total_value=pool.dec31_total_value, amount_converted=sum(i.gross for i in conv),
            other_distributions=sum(max(0, i.gross - i.rolled_over) for i in kept),
            nondeductible_basis_carryforward=pool.basis_carryforward,
            nondeductible_contributions_this_year=pool.nondeductible_contributions_this_year,
            contributions_made_after_year_end=pool.contributions_made_after_year_end, year=year,
            knowledge_dir=knowledge_dir)
        taxable_conv, taxable_kept = pr.taxable_conversion, pr.taxable_other_distributions

    def share(group: list[RetirementDistribution], total: int, base) -> dict[int, int]:
        weights = [base(i) for i in group]
        whole = sum(weights)
        out, given = {}, 0
        for n, (i, w) in enumerate(zip(group, weights)):
            part = total - given if n == len(group) - 1 else (total * w // whole if whole else 0)
            out[id(i)] = part
            given += part
        return out

    parts = {**share(conv, taxable_conv, lambda i: i.gross), **share(kept, taxable_kept, lambda i: max(0, i.gross - i.rolled_over))}
    resolved = [i.model_copy(update={"taxable_override": parts[id(i)], "rolled_over": 0,
                                     "label": (i.label or f"box 7 {i.codes or '(blank)'}") + f" ({who}'s Form 8606)"})
                if id(i) in parts else i for i in items]
    return snap.model_copy(update={"retirement_distributions": resolved})


def _capped_excess(snap: "IncomeSnapshot", kind: str) -> int:
    """One person's IRA excess, capped at that person's December 31 value (IRC 4973(a)) — JR3c."""
    excess, value = getattr(snap, f"{kind}_ira_excess"), getattr(snap, f"{kind}_ira_dec31_value")
    return excess if value is None else min(excess, value)


# IRC 72(t)(1): "10 percent of the portion of such amount which is includible in gross income"; 72(t)(6): 25% for a
# SIMPLE IRA distribution in the first 2 years; 72(t)(2)(A)(ix): not on the net income of a 408(d)(4) return
# (box 7 code 8 with J or 1). IRC 4973(a): 6 percent. Read 2026-09-27 (uscode.house.gov).
_EARLY_RATE, _EARLY_RATE_SIMPLE, _EXCESS_EXCISE_RATE = Decimal("0.10"), Decimal("0.25"), Decimal("0.06")


def _early_distribution_tax(items: list[RetirementDistribution]) -> tuple[int, set[str]]:
    """Form 5329 Part I: the additional tax on the early distributions (codes 1, J; S at 25%) — JR3c."""
    from taxfill_core.distribution_codes import parse_box7  # noqa: PLC0415

    base10 = base25 = 0
    keys: set[str] = set()
    for item in items:
        codes = set(parse_box7(item.codes))
        taxable, key = _retirement_taxable(item)
        if key == "prior_year" or not codes & {"1", "J", "S"}:
            continue
        if "8" in codes:
            keys.add("early_corrective")
            continue
        part = max(0, taxable - item.early_exception_amount)
        if item.early_exception_amount:
            keys.add("early_exception")
        if "S" in codes:
            base25 += part
        else:
            base10 += part
    return irs_round(_EARLY_RATE * base10 + _EARLY_RATE_SIMPLE * base25), keys


def _joint_retirement(a: "IncomeSnapshot", b: "IncomeSnapshot") -> dict[str, Any]:
    """The joint view of retirement income (JR3a): the manual figures summed when neither spouse lists 1099-Rs;
    otherwise the lists concatenated, a spouse's manual figure riding along as an override item."""
    if not a.retirement_distributions and not b.retirement_distributions:
        return {"retirement_income_taxable": a.retirement_income_taxable + b.retirement_income_taxable}
    items = []
    for snap, who in ((a, "taxpayer"), (b, "spouse")):
        items += snap.retirement_distributions
        if snap.retirement_income_taxable:
            items.append(RetirementDistribution(gross=snap.retirement_income_taxable,
                                                taxable_override=snap.retirement_income_taxable,
                                                label=f"{who}'s retirement_income_taxable"))
    return {"retirement_distributions": items}


def _box_or_wages_sum(a: "IncomeSnapshot", b: "IncomeSnapshot", field: str) -> int | None:
    """A W-2 box (medicare_wages / ss_wages) summed over two snapshots, box 1 standing in where one is
    missing; None when neither snapshot carries it (JF3)."""
    va, vb = getattr(a, field), getattr(b, field)
    if va is None and vb is None:
        return None
    return (a.wages if va is None else va) + (b.wages if vb is None else vb)


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
    "schedule_1a_deductions": _EXPLANATORY,
    "nonitemizer_charitable_deduction": _EXPLANATORY,
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
    "early_distribution_additional_tax": _OPERAND,
    "ira_excess_contribution_excise": _OPERAND,
    "withholding": _OPERAND,
    "additional_medicare_withholding": _OPERAND,
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
    federal_public_benefit: int = Field(
        default=0, ge=0,
        description="JT1c: Schedule 3-A's federal public benefit on this return (0 in a year without the block).")
    spouse_federal_public_benefit: int = Field(
        default=0, ge=0, description="JT1c: the same on the spouse's separate return of a two-return MFS pair.")


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
            "§6013(g)/(h) election in effect (P-018), the election as a joint CANDIDATE for a nonresident or "
            "dual-status taxpayer, a dual-status year, or a nonresident spouse direction — "
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
    here was 'single' until JF1b.9 gave it the married candidates. An explicit 'unmarried'
    (or a widowed status outside the year of death) is not a marriage at all.
    """
    status = _confirmed_status(profile)
    if status is not None and status not in _MARRIED_STATUSES:
        return False
    if _married_for_year(profile, year):   # the year of death has MFJ/MFS candidates (JF1b.9)
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
        return residency.SECTION_6013_SUSPENDED.rstrip(".")
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
    election_candidate: bool = False, nra_spouse_hoh: bool = False,
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

    ``election_candidate`` (JF5b part 3b, P-018): a married NONRESIDENT or dual-status
    filer with no election answer, no decline and the election not ruled out (IRC
    6013(g)(3)) keeps married-filing-JOINTLY as a CANDIDATE — the figure under the
    §6013(g)/(h) election, priced on resident rules by the caller — behind the
    no-election married-filing-separately primary. The choice belongs to the COUPLE
    (Pub 519 ch. 1: "one spouse is a U.S. citizen or a resident alien and the other spouse
    is a nonresident alien"), so the nonresident filer sees it as the citizen filer does.

    ``nra_spouse_hoh`` (JF1b.10, P-018): a citizen or resident whose spouse is, or may be, a
    nonresident alien, with no election recorded and none declined, keeps head of household as a
    candidate behind the joint and separate figures, on the same qualifying-person test — Pub 501,
    Considered Unmarried: "You are considered unmarried for head of household purposes if your
    spouse was a nonresident alien at any time during the year and you don't choose to treat your
    nonresident spouse as a resident alien." It exists only if the couple does not elect.
    """
    hh = profile.household
    restricted = classification in ("nonresident", "dual_status_candidate")
    if hh is not None and hh.filing_status is not None and hh.filing_status.value:
        confirmed = str(hh.filing_status.value)
        if confirmed == "head_of_household" and restricted:
            # JF1b.12: a nonresident alien (Pub 519 ch. 5: "You cannot file as head of household if you
            # are a nonresident alien at any time during the tax year") or a dual-status year (ch. 6:
            # "You cannot use the head of household Tax Table column") cannot use the confirmed status,
            # so the figure is the status the filer CAN use — married filing separately for a married
            # filer, single otherwise — and the caveat names the swap.
            usable = "married_filing_separately" if (_is_married(profile) or _married_for_year(profile, year)) else "single"
            return [usable], False
        return [confirmed], False
    # JF1b.9: the year of a spouse's death is a married year for filing status (Pub 501: "If your
    # spouse died during the year, you are considered married for the whole year for filing status
    # purposes. If you didn't remarry before the end of the tax year, you can file a joint return for
    # yourself and your deceased spouse").
    if _married_for_year(profile, year):
        # A nonresident-alien (1040-NR) filer cannot use MFJ; neither (generally) can a
        # dual-status-year filer absent a §6013 election — the primary becomes MFS, and the
        # joint return the election opens stays a candidate (JF5b part 3b).
        if restricted:
            return ["married_filing_separately", *(["married_filing_jointly"] if election_candidate else [])], True
        if no_joint or nra_spouse_hoh:
            hoh_qp = hh.hoh_qualifying_person
            hoh = _confirmed_true(hoh_qp) or (bool(hh.dependents) and not (hoh_qp is not None and hoh_qp.value is False))
            first = [] if no_joint else ["married_filing_jointly"]
            return [*first, "married_filing_separately", *(["head_of_household"] if hoh else [])], True
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
# JF5b (P-018, P-013): a dual-status year's nonresident part — Treas. Reg. 1.871-13(a)(1).
_DUAL_DEPOSIT_EXCLUSION_LABEL = (
    "Less: US bank-deposit interest received before the residency starting date excluded (IRC 871(i)(2)(A); "
    "Treas. Reg. 1.871-13(a)(1) — the nonresident part of a dual-status year)"
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

# JF1b.2: the same conditional frame for a filer with no spouse on the facts (unmarried, or
# the marital status unanswered and no married status confirmed) — the election needs a
# spouse at year end, so it is not named; the 1040-NR restrictions are. Pub 519 (2025) ch. 5,
# read 2026-09-27: "Nonresident aliens cannot claim the standard deduction." and "You cannot
# file as head of household if you are a nonresident alien at any time during the tax year."
_NONRESIDENT_CONDITIONAL_CAVEAT = (
    "If your residency result is nonresident alien, you file Form 1040-NR and this figure — priced on resident "
    "rules until your residency is known — changes: Pub 519 ch. 5, \"Nonresident aliens cannot claim the standard "
    "deduction\", and \"You cannot file as head of household if you are a nonresident alien at any time during "
    "the tax year.\" Record your visa timeline and days in the U.S. (the residency tool) to tighten this."
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
            "status checkboxes instead (Pub 501) — never in the spouse-SSN box (P-026)."
        )
    return text


def _section_6013_candidate_caveat(
    *, own_classification: str, kind: str, joint: int, spouse_class: str | None, spouse_needs_itin: bool,
    continuing_from: int | None = None,
) -> str:
    """The §6013(g)/(h) caveat when the election is a CANDIDATE for a nonresident or dual-status
    TAXPAYER (JF5b part 3b, P-018): the point is the no-election married-filing-separately
    return, and the married-filing-jointly candidate is the figure IF the couple makes the
    election — priced on resident rules — with the same worldwide-income, FICA, statement
    and W-7 caveats as the reverse couple's. ``spouse_class`` is the spouse's residency
    without the election ('us' for a declared U.S. person; None when not on file): the
    precondition cannot be judged without it, and the caveat says what to record."""
    dual = own_classification == "dual_status_candidate"
    own = "a DUAL-STATUS year (a nonresident alien for part of it)" if dual else "NONRESIDENT alien"
    point_return = (
        "the dual-status return and statement Pub 519 ch. 6 describes" if dual else "Form 1040-NR")
    effect, precondition, statement = residency.section_6013_texts(kind)
    record_spouse = (
        "record household.spouse.us_person (a U.S. citizen or green-card holder) or, if your spouse is not one, "
        "the spouse's visa timeline (household.spouse.immigration.visa_timeline) and days in the US "
        "(household.spouse.residency_facts.days_in_us), and rerun"
    )
    if spouse_class is None and dual:
        condition = (
            "Which choice it is turns on your spouse's residency at the end of the year, which is not on file: IRC "
            "6013(h) if your spouse is a U.S. citizen or resident then, IRC 6013(g) if your spouse is a nonresident "
            "alien (Pub 519 ch. 1: \"This includes situations in which one spouse is a nonresident alien at the "
            "beginning of the tax year, but a resident alien at the end of the year, and the other spouse is a "
            f"nonresident alien at the end of the year.\") — {record_spouse}. {precondition}"
        )
    elif spouse_class is None:
        condition = (
            "Whether you can make it is NOT settled on these facts: the choice needs a spouse who is a U.S. citizen or "
            "resident at the end of the year (Pub 519 ch. 1: \"If, at the end of your tax year, you are married and one "
            "spouse is a U.S. citizen or a resident alien and the other spouse is a nonresident alien, you can choose "
            "to treat the nonresident spouse as a U.S. resident.\"), and your spouse's residency is not on file — "
            f"{record_spouse}. If your spouse is a nonresident alien all year too, the election is not available at "
            "all (IRC 6013(g)(3))."
        )
    elif spouse_class == "nonresident" and not dual:
        condition = (
            "On the recorded facts your spouse classifies nonresident too, which would rule the election out — IRC "
            "6013(g)(3): it \"shall not apply for any taxable year if neither spouse is a citizen or resident of the "
            "United States at any time during such year\" — but one of the nonresident answers is not settled (it "
            "rests on a lookback year missing from the day counts, or on the prior-year return), so the candidate is "
            f"kept: record the missing facts and rerun. {precondition}"
        )
    else:
        condition = precondition
    text = (
        f"Your own residency result is {own}, and no §6013(g)/(h) election is recorded, so the point is married "
        f"filing separately WITHOUT it ({point_return}). {residency.SECTION_6013_NO_JOINT} Married-filing-jointly is "
        f"shown as a CANDIDATE ({_signed_dollars(joint)}, + refund / - owed): "
        + (f"the figure IF the election made for {continuing_from} is still in effect — a later year of it, so no new "
           "statement (check the box and enter the spouse's name) — "
           if continuing_from is not None else "the figure IF you and your spouse make the election — ")
        + "priced under RESIDENT rules for both spouses for the whole year: the standard deduction, the "
        "regular and preferential rates, NIIT evaluated (see the NIIT note), the credits a resident may claim, and "
        f"no IRC 871(i)(2)(A) deposit-interest exclusion. {effect} That figure is only valid when BOTH spouses' "
        "WORLDWIDE (foreign) income is in the inputs (other_income on each snapshot) — yours included: foreign "
        "income a nonresident's return leaves out becomes taxable under the election — otherwise the MFJ-vs-MFS "
        f"comparison overstates the MFJ advantage. {residency.SECTION_6013_FICA} "
        + ("" if continuing_from is not None else f"{statement} ") + condition
    )
    if spouse_needs_itin:
        # The joint return and the election statement name EACH spouse's TIN (Pub 519 ch. 1: "The name,
        # address, and TIN of each spouse") — whichever spouse is the nonresident.
        text += (
            " Your spouse has no SSN/ITIN on file: the joint return and the election statement need each spouse's "
            "TIN (Pub 519 ch. 1: \"The name, address, and TIN of each spouse\") — apply with Form W-7, filed WITH the "
            "return."
        )
    return text + (
        " To price the election as your choice, record residency_facts.section_6013_election: true to elect (or if "
        "one made in an earlier year remains in effect), false to decline — and then the filing status."
    )


def _spouse_own_classification(profile: Profile, year: int) -> str | None:
    """The SPOUSE's residency from the spouse's OWN visa timeline and day counts, or None.

    None when the spouse is absent, a declared US person (no SPT applies), or has no
    facts that classify — never borrowed from the taxpayer, and never guessed. It
    ignores the §6013(g)/(h) election: callers that honor the election ask for it
    separately (it makes both spouses residents; this is the answer without it).
    :func:`_spouse_own_result` is the full result (its ``nonresident_may_flip``).
    """
    result = _spouse_own_result(profile, year)
    return result.classification if result is not None else None


def _spouse_own_result(profile: Profile, year: int):
    """The SPOUSE's own :class:`residency.ClassificationResult` (see
    :func:`_spouse_own_classification`), or None — so a caller can read
    ``nonresident_may_flip`` (JF5b.6), not only the string.

    The spouse has no prior-filings fact (PriorFilings is the taxpayer's; the Spouse
    model has no prior_filings), so the prior-year residency fact is None here — the
    classifier's reading without it.
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
        return residency.classify(imm.visa_timeline, days_by_year, year)
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
    deduction_method: str | None = None, assumed: bool = False, dual_status: bool = False, dual_point: bool = False,
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
    nonresident reading is the one a recorded decline rests on (P-018). ``dual_point`` (JF5b
    part 3b): the spouse's own dual-status year, priced under Pub 519 ch. 6 at the point.
    """
    sp = profile.household.spouse if profile.household is not None else None
    if dual_point:
        used = 0 if deduction_method == "standard" else (income.itemized_deductions or 0)
        decline = (
            " — the nonresident alien the recorded decline rests on is this spouse, a nonresident alien for part of "
            "the year" if assumed else ""
        )
        return (
            "The spouse's separate return was computed under Pub 519 ch. 6's DUAL-STATUS restrictions for the point, "
            "because the spouse's own visa timeline and day counts show a dual-status year (a nonresident alien before "
            f"the residency starting date, a resident after it){decline}: NO standard deduction "
            f"({_DUAL_STATUS_STANDARD_DEDUCTION} — ${used:,} of the spouse's itemized deductions used), "
            "married-filing-separately rates (Pub 519 ch. 6, Tax rates: a married dual-status filer who does not "
            "choose to file jointly \"must use the Tax Table column or Tax Computation Worksheet for married filing "
            f"separately\"), and no earned income or education credit ({_DUAL_STATUS_CREDITS}). It is a FULL-YEAR "
            "approximation — one snapshot: the preferential rates and NIIT are kept on the whole year's income (the "
            f"NIIT may be OVERSTATED: {_DUAL_STATUS_NIIT}), and nonresident-period U.S.-source income that is not "
            "effectively connected \"is subject to the flat 30% rate or lower treaty rate\" (Pub 519 ch. 6, How To "
            "Figure Your Tax), which is not split out here. The range also prices that return for the whole year "
            "under resident and under nonresident rules (the note on the spouse's residency)."
        )
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
    self_nonresident: bool, spouse_nonresident: bool, self_dual: bool = False, spouse_dual: bool = False,
) -> str:
    """Disclose the couple's deduction method on the two-return MFS pair (IRC 63(c)(6)(A)).
    ``self_dual`` / ``spouse_dual``: that return is a dual-status year's, which has no standard
    deduction either (Pub 519 ch. 6 — JF5b)."""
    no_sd = {
        "nra": " (a nonresident alien has no standard deduction, so its Form 1040-NR claims none)",
        "dual": " (a dual-status year has no standard deduction — Pub 519 ch. 6 — so that return claims none)",
    }
    rows = [
        ("your", self_income, "nra" if self_nonresident else "dual" if self_dual else None),
        ("the spouse's", spouse_income, "nra" if spouse_nonresident else "dual" if spouse_dual else None),
    ]
    if method == "itemize":
        amounts = " and ".join(f"${snap.itemized_deductions or 0:,} on {who} return" for who, snap, _ in rows)
        chosen = (
            f"BOTH ITEMIZE — each separate return deducts its own itemized deductions ({amounts}) and neither "
            "takes the standard deduction."
        )
    else:
        forgone = [
            f"{who} ${snap.itemized_deductions:,} of itemized deductions" + (no_sd[kind] if kind else "")
            for who, snap, kind in rows
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
    """True when a real spouse SSN/ITIN is on file.

    The answer 'NRA' is the no-TIN marker the profile may hold as a fact; on the form it
    goes in the MFS entry space, never the spouse-SSN box (P-026)."""
    hh = profile.household
    sp = hh.spouse if hh is not None else None
    if sp is None or sp.tax_id is None or not sp.tax_id.value:
        return False
    return str(sp.tax_id.value).strip().upper() != "NRA"


# A dual-status year with no §6013(g)/(h) election (JF5b.2, P-018). Pub 519 (2025) ch. 6,
# Restrictions for Dual-Status Taxpayers and Tax Credits and Payments; ch. 1, Dual-Status
# Aliens and Choosing Resident Alien Status; IRC 32(c)(1)(D), 25A(g)(7), 22(f); Treas. Reg.
# 1.1411-2(a)(2)(ii) — read 2026-09-27. The point prices the restrictions; the range's other
# end is the full-year-resident figure, only where some route could make it lawful.
_DUAL_STATUS_STANDARD_DEDUCTION = (
    "\"You cannot use the standard deduction allowed on Form 1040 or 1040-SR. However, you can itemize any "
    "allowable deductions.\""
)
_DUAL_STATUS_CREDITS = (
    "\"You cannot claim the education credits, EIC, or credit for the elderly or the disabled unless you are "
    "married and you choose to be treated as a resident\" for the whole year by filing jointly (Pub 519 ch. 6; "
    "IRC 32(c)(1)(D), 25A(g)(7), 22(f))"
)
_DUAL_STATUS_NIIT = (
    "Treas. Reg. 1.1411-2(a)(2)(ii): \"The only income the individual must take into account for purposes of "
    "section 1411 is the income he or she receives during the portion of the year for which he or she is "
    "treated as a resident of the United States.\""
)
_DUAL_STATUS_TWO_RULES = (
    "Treas. Reg. 1.871-13(a)(1) figures a dual-status year \"under two different sets of rules, one relating to "
    "resident aliens for the period of residence and the other relating to nonresident aliens for the period of "
    "nonresidence\""
)
_DUAL_STATUS_ELECTION_ENDS = (
    "A §6013(g)/(h) election ENDS it: Treas. Reg. 1.871-13(a)(1) — \"This section does not apply to alien "
    "individuals treated as residents for the entire taxable year under section 6013 (g) or (h).\""
)


class _DualRoutes(NamedTuple):
    """Which routes could make a dual-status year's full-year-resident figure lawful (JF5b.2)."""

    prior_year: bool      # (i) the prior-year residency fact is not recorded False
    married: str | None   # (ii) 'married' / 'unanswered' — the election is open; None = closed
    prior_form: str | None
    declined: bool

    def resident_figure_open(self, *, joint_candidate: bool) -> bool:
        """The same status under resident rules is lawful by some route: (i), or (ii) when the
        election's joint figure is not priced as its own candidate (JF5b part 3b — then route
        (ii) points at that candidate). (iii), the dates on the timeline, is always named but
        never opens the range alone."""
        return self.prior_year or (self.married is not None and not joint_candidate)


def _dual_status_routes(profile: Profile, year: int, *, declined: bool) -> _DualRoutes:
    """The routes open on the recorded facts for a dual-status year (JF5b.2, P-018).

    (i) A prior-year resident is a resident from January 1 (Pub 519 ch. 1, "Residency
    during the preceding year"), so the year is not dual-status — open unless the
    prior-year fact is recorded False (a Form 1040-NR). (ii) The §6013(g)/(h) election
    (Pub 519 ch. 6: "the rules of this chapter do not apply to you for that year") needs a
    spouse at year end — "If you are single at the end of the year, you cannot make this
    choice." (Pub 519 ch. 1) — so it is open when the household is married for the year
    (or the marital status is unanswered with a confirmed married status), 'unanswered'
    when neither the marital status nor a status is on file, and closed after a recorded
    DECLINE (the user's explicit fact) or on facts with no spouse. (iii) Wrong dates on the
    visa timeline is a labeled judgment the caveat always names.
    """
    prior = _prior_year_resident(profile, year)
    marital, status = _marital(profile), _confirmed_status(profile)
    married: str | None = None
    if not declined:
        if marital == "married" or (marital is None and status in _MARRIED_STATUSES):
            married = "married"
        elif _married_for_year(profile, year):
            married = "death_year"   # widowed in the tax year: not ruled out, never asserted
        elif marital is None and status is None:
            married = "unanswered"
    return _DualRoutes(prior_year=prior is not False, married=married, prior_form=_prior_year_form(profile, year),
                       declined=declined)


def _dual_status_caveat(
    year: int, primary: str, *, itemized_used: int, routes: _DualRoutes, resident_reading: int | None,
    niit: bool, married: bool = False, confirmed: bool = False, otherwise_bracketed: bool = False,
    marital_unanswered: bool = False, hoh_not_priced: bool = False, joint_candidate: int | None = None,
) -> str:
    """The dual-status caveat: the point (Pub 519 ch. 6's restrictions), the approximation it
    is, and the range — the full-year-resident figure with the route that would make it
    lawful, or why no route is open (JF5b.2, P-018). ``joint_candidate`` (JF5b part 3b): the
    married-filing-jointly candidate's bottom line — the §6013(g)/(h) election's joint figure,
    priced on its own, so route (ii) points at it instead of the same status under resident
    rules."""
    if primary == _MFS:
        rates = (
            "married-filing-separately rates (Pub 519 ch. 6, Tax rates: a married dual-status filer who does not "
            "choose to file jointly \"must use the Tax Table column or Tax Computation Worksheet for married filing "
            "separately\")"
        )
    elif married:
        # Pub 519 ch. 6 names the column for a MARRIED dual-status filer whatever status is priced.
        why = "it is the confirmed status" if confirmed else "it is the status priced here"
        rates = (
            f"the {primary} rates as priced, because {why} — but Pub 519 ch. 6, Tax rates, names married filing "
            "separately for a married dual-status filer who does not choose to file jointly: \"You cannot use the "
            "Tax Table column or Tax Computation Worksheet for married filing jointly or single. However, you may be "
            "able to file as single if you lived apart from your spouse during the last 6 months of the year and you "
            "are a: • Married resident of Canada, Mexico, or South Korea; or • Married U.S. national.\""
        )
    elif primary == "head_of_household":
        rates = (
            "the head_of_household rates as priced, only because that status is confirmed — Pub 519 ch. 6: \"You "
            "cannot use the head of household Tax Table column or Tax Computation Worksheet.\" (single is the "
            "column left for an unmarried filer)"
        )
    elif primary == "single" and marital_unanswered:
        rates = (
            "single rates IF you are unmarried (household.marital_status is not answered) — a married dual-status "
            "filer who does not choose to file jointly \"must use the Tax Table column or Tax Computation Worksheet "
            "for married filing separately\" (Pub 519 ch. 6, Tax rates)"
        )
    elif primary == "single":
        rates = (
            "single rates — an inference: ch. 6 names the rate column only for a married filer, and it bars the "
            "joint return and head of household, which leaves single"
        )
    else:
        rates = f"the {primary} rates as priced (ch. 6 names the rate column only for a married filer)"
    # JF1b.2: the election is a married couple's choice, so an unmarried filer's caveat never
    # names it (no spouse at year end on these facts, and no recorded decline).
    unmarried = routes.married is None and not routes.declined and not married
    text = (
        "Your residency result flags a DUAL-STATUS year — a nonresident alien before the residency starting date "
        "and a resident after it (Pub 519 ch. 1: \"You are a nonresident alien for the part of the year before that "
        "date.\")" + ("" if unmarried else " — and no §6013(g)/(h) election is recorded") + ". The point applies "
        "Pub 519 ch. 6, Restrictions for "
        f"Dual-Status Taxpayers: NO standard deduction ({_DUAL_STATUS_STANDARD_DEDUCTION} — ${itemized_used:,} of "
        f"itemized deductions used); no joint return and no head of household; {rates}; and no earned income credit, "
        f"education credit or credit for the elderly or the disabled — {_DUAL_STATUS_CREDITS}; the elderly credit is "
        "not modeled here at all. Every number is still a FULL-YEAR approximation — one snapshot for the whole "
        "year, where the real return is a split-year Form 1040 + Form 1040-NR (one of them the statement for the "
        "other part of the year): resident-period income from all sources and nonresident-period effectively "
        "connected income are taxed at the graduated rates, while nonresident-period U.S.-source income that is "
        "not effectively connected \"is subject to the flat 30% rate or lower treaty rate. You cannot take any "
        "deductions against this income.\" (Pub 519 ch. 6, How To Figure Your Tax). This estimate splits nothing "
        "by period except the deposit interest recorded in bank_deposit_interest_nonresident_period."
    )
    if niit:
        text += (
            " NIIT is figured on the whole year's investment income (less any deposit interest recorded as received "
            "before the residency starting date), but " + _DUAL_STATUS_NIIT
            + " — so the NIIT here may be OVERSTATED."
        )
    joint_cond = {
        "unanswered": "IF you are married at the end of the year (household.marital_status is not answered)",
        "death_year": (
            "IF the choice is open in the year of your spouse's death (Pub 501: \"If your spouse died during the "
            "year, you are considered married for the whole year for filing status purposes\" — this estimate does "
            "not decide it)"
        ),
    }.get(routes.married or "", "you are married at the end of the year")
    joint_route = None if joint_candidate is None else (
        f"(ii) {joint_cond} and you and your spouse choose the §6013(g)/(h) election to be "
        "treated as U.S. residents for the whole year — a JOINT return that makes worldwide income taxable (Pub 519 "
        "ch. 6: \"If you are married and choose to be a nonresident spouse treated as a resident, as explained in "
        "chapter 1, the rules of this chapter do not apply to you for that year.\"): that is the married-filing-"
        f"jointly CANDIDATE, the election's joint figure ({_signed_dollars(joint_candidate)}, + refund / - owed — "
        "the §6013(g)/(h) candidate caveat gives its terms)"
    )
    if resident_reading is not None:
        opened: list[str] = []
        if routes.prior_year:
            recorded = routes.prior_form in ("1040", "dual_status")
            unsettling = {
                "not_filed": "not filing says nothing about residency",
                "1040_with_6013_election": "a joint return under the election is not read as residency",
            }.get(routes.prior_form or "")
            lead = (
                f"(i) your {year - 1} return is recorded as '{routes.prior_form}' (a U.S. resident then)"
                if recorded else
                f"(i) your {year - 1} return is recorded as '{routes.prior_form}', which does not settle {year - 1}'s "
                f"residency ({unsettling}) — if you were in fact a U.S. resident during {year - 1}"
                if unsettling else f"(i) you were a U.S. resident during {year - 1}"
            )
            opened.append(
                f"{lead}: you are then a resident from January 1 of {year} and the year is not dual-status (Pub 519 "
                "ch. 1: \"If you were a U.S. resident during any part of the preceding calendar year and you are a "
                "U.S. resident for any part of the current year, you will be considered a U.S. resident at the "
                "beginning of the current year.\")"
                + ("" if recorded else (
                    f" — record the visa timeline and days in the U.S. for {year - 1} to settle it" if unsettling
                    else f" — record the return you filed for {year - 1} in prior_filings.return_forms"))
            )
        if routes.married is not None and joint_route is None:
            cond = {
                "married": "you are married at the end of the year",
                "unanswered": "IF you are married at the end of the year (household.marital_status is not answered)",
                "death_year": (
                    "IF the choice is open in the year of your spouse's death (Pub 501: \"If your spouse died during "
                    "the year, you are considered married for the whole year for filing status purposes\" — this "
                    "estimate does not decide it)"
                ),
            }[routes.married]
            opened.append(
                f"(ii) {cond} and you and your spouse choose the §6013(g)/(h) election to be treated as U.S. "
                "residents for the whole year — a JOINT return that makes worldwide income taxable (Pub 519 ch. 6: "
                "\"If you are married and choose to be a nonresident spouse treated as a resident, as explained in "
                "chapter 1, the rules of this chapter do not apply to you for that year.\"); this end of the range is "
                "the same status under resident rules, not the joint figure — record "
                "residency_facts.section_6013_election to price the election"
            )
        text += (
            " The range ALSO prices the full-year-resident figure — the same inputs under resident rules for the "
            f"whole year, with the standard deduction and the credits ({primary}: {_signed_dollars(resident_reading)}, "
            "+ refund / - owed). It is lawful only by one of these routes: " + "; ".join(opened)
            + "; or (iii) the dates on the visa timeline are wrong (the dual-status flag rests on them — a labeled "
            "judgment)."
            + (" That end prices the same statuses as the point: head of household, which a full-year resident with "
               "a qualifying person may use, is not priced here." if hoh_not_priced else "")
            + (f" The other route is priced as its own figure: {joint_route}." if joint_route is not None else "")
        )
    elif joint_route is not None:
        text += (
            " No route to the standard deduction on THIS return is open on these facts: your "
            f"{year - 1} return is recorded as '{routes.prior_form}' (prior_filings.return_forms — read as not a U.S. "
            f"resident in {year - 1}, so residency starts partway through {year}) — unless the dates on the visa "
            f"timeline are wrong. The one route to resident rules is {joint_route}, which the range includes."
        )
    else:
        why = (
            "the §6013(g)/(h) election is recorded as DECLINED"
            if routes.declined
            else "you are not married at the end of the year on these facts, so no joint-return choice opens resident "
            "rules (Pub 519 ch. 1: \"If you are single at the end of the year, you cannot make this choice.\")"
            if unmarried
            else "the §6013(g)/(h) election needs a spouse at the end of the year and none is on these facts (Pub 519 "
            "ch. 1: \"If you are single at the end of the year, you cannot make this choice.\")"
        )
        text += (
            " No route to the standard deduction is open on these facts, so the range "
            + ("adds no full-year-resident figure (it is bracketed only by the other readings named here)"
               if otherwise_bracketed else "is this figure alone")
            + ": your "
            f"{year - 1} return is recorded as '{routes.prior_form}' (prior_filings.return_forms — read as not a U.S. resident "
            f"in {year - 1}, so residency starts partway through {year}), and {why} — unless the dates on the visa "
            "timeline are wrong."
        )
    return text + " Confirm the split-year treatment before relying on these numbers."


def _dual_status_credits_note(
    income: "IncomeSnapshot", unrestricted: "BottomLineResult", *, in_range: bool, joint_candidate: bool = False,
) -> str | None:
    """The EITC and education-credit disclosures extended to a dual-status year (JF5b.2):
    what the dual-status point does not claim, and what the full-year-resident figure
    would — with its amounts (P-013 rule (d): name the dollars). ``joint_candidate`` (JF5b
    part 3b): the election's joint figure is priced as its own candidate, with its own credits."""
    effects = {line.slot: -line.amount for line in unrestricted.lines}
    eitc = effects.get("eitc", 0)
    edu = effects.get("education_credits_nonrefundable", 0) + effects.get("aotc_refundable", 0)
    if not (eitc or edu or income.aotc_qualified_expenses):
        return None
    parts: list[str] = []
    if income.aotc_qualified_expenses:
        parts.append(
            "Education expenses were provided but NO education credit was estimated on the dual-status figure: IRC "
            "25A(g)(7) — \"If the taxpayer is a nonresident alien individual for any portion of the taxable year, this "
            "section shall apply only if such individual is treated as a resident alien of the United States for "
            "purposes of this chapter by reason of an election under subsection (g) or (h) of section 6013.\""
        )
    if eitc:
        parts.append(
            "NO earned income credit on the dual-status figure: IRC 32(c)(1)(D) — the eligible individual \"shall not "
            "include any individual who is a nonresident alien individual for any portion of the taxable year\" "
            "unless treated as a resident by reason of the §6013(g)/(h) election."
        )
    claimed = [f"${amount:,} of {name}" for name, amount in (("earned income credit", eitc), ("education credits", edu))
               if amount]
    if claimed:
        where = (
            "The full-year-resident figure in the range claims "
            if in_range
            else "Under resident rules for the whole year on this return (computed for comparison only — no route to "
            "that figure is open on these facts; the election's route is the married-filing-jointly candidate, priced "
            "with the credits a joint return may claim) the same inputs would claim "
            if joint_candidate
            else "Under resident rules for the whole year (computed for comparison only — no route to that figure is "
            "open on these facts) the same inputs would claim "
        )
        parts.append(where + " and ".join(claimed) + " (Pub 519 ch. 6 Caution).")
    return " ".join(parts)


def _dual_deposit_note(
    snap: "IncomeSnapshot", *, whose: str, in_range: bool, joint_taxes: bool = False,
) -> str | None:
    """The deposit-interest disclosure for a dual-status payee's return (JF5b.3, P-013, P-018):
    the nonresident-period subset EXCLUDED and the rest taxed, or — with no split recorded —
    the amount taxed in full and what to record. ``whose`` is '' for your return or the
    spouse's lead-in; ``joint_taxes``: a joint-return candidate taxes it (election only)."""
    deposit, period = snap.bank_deposit_interest, snap.bank_deposit_interest_nonresident_period
    uncharacterized = snap.interest - deposit
    if deposit <= 0 and uncharacterized <= 0:
        return None
    field = "the spouse snapshot's bank_deposit_interest_nonresident_period" if whose else (
        "bank_deposit_interest_nonresident_period")
    law = (
        f"{_DUAL_STATUS_TWO_RULES}; for the nonresident part IRC 871(i)(1) imposes no tax on 871(i)(2)(A) \"interest "
        "on deposits, if such interest is not effectively connected with the conduct of a trade or business within "
        "the United States\" (Pub 519 ch. 6: U.S.-source income is taxable in either part \"unless specifically "
        "exempt under the Internal Revenue Code or a tax treaty provision\"), and for the resident part \"you are "
        "taxed on income from all sources\" (Pub 519 ch. 6)"
    )
    tail = ((" The full-year-resident figure in the range taxes all of it." if not whose else
             " The range's full-year-resident reading of the spouse's return taxes all of it.") if in_range else "") + (
        " The joint-return figure taxes it: a joint return with a spouse who is a nonresident alien for part of the "
        "year exists only under the §6013(g)/(h) election." if joint_taxes else "")
    sentences: list[str] = []
    if period > 0:
        rest = deposit - period
        sentences.append(
            f"{whose}US bank-deposit interest of ${period:,} received before the residency starting date was EXCLUDED "
            f"from income" + (f", and the other ${rest:,} of bank_deposit_interest was taxed as resident-period "
                              "interest" if rest else "")
            + f": {law}. The exclusion rests on the CHARACTER and the DATE you entered — the amount paid or credited "
            "before the residency starting date, from the account statements, never a proration. "
            + _DUAL_STATUS_ELECTION_ENDS + tail
        )
    elif deposit > 0:
        sentences.append(
            f"{whose}${deposit:,} of bank_deposit_interest was taxed IN FULL"
            + ("" if whose else " on the dual-status figure")
            + ": none of it is recorded as received before the residency starting date. In a dual-status year the "
            "part received before "
            "that date — the nonresident part — is excluded if it is deposit interest not effectively connected with "
            f"a U.S. trade or business, and the rest is taxed as resident-period interest: {law}. Record the amount "
            f"paid or credited before the residency starting date (from the account statements — never a proration) "
            f"in {field} and rerun. " + _DUAL_STATUS_ELECTION_ENDS + tail
        )
    if uncharacterized > 0:
        sentences.append(
            f"{whose}${uncharacterized:,} of interest was entered WITHOUT deposit character (interest minus "
            "bank_deposit_interest) and was taxed in full. If part of it is interest on a deposit with a US bank, "
            "savings institution or insurance company, not effectively connected with a US trade or business, and "
            "received before the residency starting date, 871(i)(2)(A) excludes that part — put the deposit portion "
            f"in bank_deposit_interest and the part received before that date in {field}, and rerun."
        )
    return " ".join(sentences)


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
        "the regular and preferential rates, NIIT evaluated (see the NIIT note for the Treas. Reg. "
        "1.1411-2(a)(2)(iii)/(iv) default where a spouse is a nonresident or arriving), and no IRC 871(i)(2)(A) deposit-interest "
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
    "and check the appropriate checkbox near the top of Form 8960, Part I\""
)
# The same instructions put "The election must be made for the first tax year in which the U.S.
# taxpayer is subject to NIIT." in a paragraph that covers BOTH elections, but the regulation
# attaches the first-year rule to 6013(g) only ((iii)(B)(2)); (iv)(B)(2) sets none for 6013(h).
# So the sentence rides the 6013(g) text and never a 6013(h) one (JF5b part 3a).
_SECTION_6013_NIIT_I8960_FIRST_YEAR = (
    "\"The election must be made for the first tax year in which the U.S. taxpayer is subject to NIIT.\""
)


def _section_6013_niit_i8960(kind: str) -> str:
    """The Form 8960 instructions' how-to, with the first-year sentence only where it governs."""
    if kind == "h":
        return _SECTION_6013_NIIT_I8960 + "."
    if kind == "g":
        return f"{_SECTION_6013_NIIT_I8960}, and {_SECTION_6013_NIIT_I8960_FIRST_YEAR}"
    return (
        f"{_SECTION_6013_NIIT_I8960}, and, for IRC 6013(g), {_SECTION_6013_NIIT_I8960_FIRST_YEAR} (the "
        "regulation sets no first-year condition for IRC 6013(h): (iv)(B)(2))."
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
# Treas. Reg. 1.1411-2(a)(2)(iii)(B)(2) and (B)(3), (a)(2)(ii) — eCFR, read 2026-09-27.
_SECTION_6013G_FIRST_YEAR = (
    "\"for the first taxable year beginning after December 31, 2013, in which the United States taxpayer is "
    "subject to tax under section 1411\""
)
_SECTION_6013G_WITHOUT_REGARD = (
    "\"The determination of whether the United States taxpayer is subject to tax under section 1411 is made "
    "without regard to the effect of the section 6013(g) election\""
)
_SECTION_6013G_CONTINUES = (
    "\"once made, the duration and termination of the section 6013(g) election for chapter 2A is governed by "
    "the rules of section 6013(g)(2) through (g)(6)\""
)
_SECTION_6013G_NO_EFFECT = "\"such original election will have no effect for that year and all future years\""
_SECTION_6013G_NRA_NOT_SUBJECT = "\"the nonresident alien spouse will not be subject to tax under section 1411\""
_SECTION_6013G_JOINT_ONLY = (
    "\"Married taxpayers who file a joint Federal income tax return pursuant to a section 6013(g) election\""
)
_SECTION_6013H_PORTION = (
    "\"only with respect to income received for the portion of the year for which he or she is treated as a "
    "United States resident\""
)
_DUAL_STATUS_NIIT_PORTION = (
    "Treas. Reg. 1.1411-2(a)(2)(ii): \"The only income the individual must take into account for purposes of "
    "section 1411 is the income he or she receives during the portion of the year for which he or she is "
    "treated as a resident of the United States\""
)

# The composition label of a joint figure whose NIIT is the default (JF5b part 3a).
_NIIT_DEFAULT_LABEL = (
    "Plus: Net investment income tax (Form 8960 — the §6013 default: married filing separately for NIIT, each "
    "spouse subject on their own figures against the $125,000 threshold, a nonresident spouse not subject)"
)


class _NiitOverride(NamedTuple):
    """A figure's NIIT priced by the caller, not from its own snapshot (JF5b part 3a, P-018)."""

    amount: int
    label: str = _NIIT_DEFAULT_LABEL
    citations: tuple[Citation, ...] = ()


_NIIT_ZERO = _NiitOverride(0)

# How "U.S." each spouse's no-election residency is (residency.section_6013_kind's inputs), to
# tell the U.S. citizen or resident spouse from the nonresident one, and the arriving spouse.
_US_RANK = {"us": 4, "resident": 3, None: 2, "dual_status_candidate": 1, "nonresident": 0}


class _NiitReading(NamedTuple):
    """One reading of the NIIT default under the election: Treas. Reg. 1.1411-2(a)(2)(iii)
    ('g', IRC 6013(g)) or (iv) ('h', IRC 6013(h)). Sides: 0 you, 1 your spouse."""

    paragraph: str             # 'g' or 'h'
    us: int | None             # 'g': the U.S. citizen or resident spouse
    arriving: tuple[int, ...]  # 'h': the spouse(s) who become residents during the year; 'g': the
    #                            nonresident spouse of a continuing election who arrives this year
    low: int                   # the default's low end (a resident-period split not recorded)
    high: int                  # the default's high end (each spouse's own full-year figure)
    available: bool            # the second (chapter-2A) election can be reached this year
    point: int                 # the NIIT this reading's joint figure uses
    reach: tuple[int, ...]     # every NIIT amount this reading's joint figure can take


def _niit_readings(
    kind: str, classes: tuple[str | None, str | None], own: tuple[int, int], elected: int,
) -> tuple[_NiitReading, ...]:
    """The NIIT default's readings under the §6013(g)/(h) election (JF5b part 3a, P-018).

    ``classes``: each spouse's residency WITHOUT the election ('us' for a declared U.S.
    person — residency.section_6013_kind's inputs). ``own``: each spouse's own NIIT, their
    own snapshot run under the married-filing-separately rules against the $125,000
    threshold. ``elected``: the joint figure's combined-income NIIT (the second election's).

    'g' — (iii)(A): the U.S. citizen or resident spouse's own NIIT, and $0 for the spouse
    who is a nonresident without the election ("the nonresident alien spouse will not be
    subject to tax under section 1411"); a U.S. spouse in a dual-status year counts only
    resident-period income ((a)(2)(ii), a reading — (iii)(A) does not mention it), which is
    not recorded, so their default runs from $0 to their full-year figure. The second
    election is reachable only when the U.S. spouse is subject on their own figures
    ((iii)(B)(2)); the reading's joint figure is the default. When the facts do not tell
    which spouse is the U.S. one (the same rank), both assignments are readings.
    'h' — (iv)(A): each spouse against $125,000, the arriving spouse "only with respect to
    income received for the portion of the year for which he or she is treated as a United
    States resident" — no period split is recorded, so the default runs from the other
    spouse's own NIIT (arriving: $0) to both full-year figures. (iv)(B)(2) sets no first-year
    condition, so the couple takes the lower: the joint figure is min(elected, high) —
    ``high`` not under the true default on income that is all positive — and min(elected, low)
    is reachable too. A side that is a U.S. person or a full-year resident on its own facts never
    takes the nonresident or the arriving role; when no reading remains, there is no default.
    'either' gives both paragraphs.
    """
    ranks = [_US_RANK.get(c, 2) for c in classes]
    readings: list[_NiitReading] = []
    # (iii)(A) reaches only "a United States citizen or resident who is married to a nonresident
    # alien individual", and (iv)(A) only a spouse "who is a nonresident alien individual at the
    # beginning of any taxable year" — so a side that is a U.S. person or a full-year resident on
    # its own facts never takes the nonresident or the arriving role. No reading, no default.
    both_nra = classes[0] == classes[1] == "nonresident"

    # A definite 'g' with no full-year nonresident in the couple is a CONTINUING 6013(g) election
    # (JF5b part 3b: a prior-year election return, residency.section_6013_kind) — its nonresident
    # spouse may be the one arriving this year.
    continuing_g = kind == "g" and "nonresident" not in classes

    def _can_be_nra(side: int) -> bool:
        return classes[side] in ("nonresident", None) or (
            classes[side] == "dual_status_candidate" and (kind == "either" or continuing_g))

    for paragraph in (["g"] if kind == "g" else ["h"] if kind == "h" else ["g", "h"]):
        if paragraph == "g":
            us_sides = [0, 1] if ranks[0] == ranks[1] else [0 if ranks[0] > ranks[1] else 1]
            us_sides = [u for u in us_sides if _can_be_nra(1 - u) and (classes[u] != "nonresident" or both_nra)]
            for u in us_sides:
                high = own[u]
                low = 0 if classes[u] == "dual_status_candidate" else high
                arriving_nra: tuple[int, ...] = ()
                if continuing_g and classes[1 - u] == "dual_status_candidate":
                    # The nonresident spouse becomes a resident this year: (iv)(A)'s facts ("married to
                    # an individual who is a nonresident alien individual at the beginning of any taxable
                    # year, but is a United States resident at the close of such taxable year") — subject
                    # on resident-period income only, not recorded: from $0 to their full-year figure.
                    arriving_nra = (1 - u,)
                    high += own[1 - u]
                available = own[u] > 0   # (iii)(B)(2): the U.S. spouse subject on their OWN figures
                reach = {high, low} | ({elected} if available else set())
                readings.append(_NiitReading("g", u, arriving_nra, low, high, available, high, tuple(sorted(reach))))
        else:
            arriving = tuple(i for i in (0, 1) if classes[i] == "dual_status_candidate")
            if not arriving:
                arriving = tuple(i for i in (0, 1) if classes[i] is None)
            if not arriving:
                continue
            high = own[0] + own[1]
            low = sum(own[i] for i in (0, 1) if i not in arriving)
            point = min(elected, high)
            readings.append(_NiitReading(
                "h", None, arriving, low, high, True, point, tuple(sorted({point, min(elected, low)})),
            ))
    return tuple(readings)


class _NiitPriced(NamedTuple):
    """The NIIT default as priced on the election figures (JF5b part 3a)."""

    classes: tuple[str | None, str | None]
    own: tuple[int, int]
    elected: int | None                # the joint figure's combined-income NIIT (None: no joint figure)
    readings: tuple[_NiitReading, ...]
    point: int | None                  # the NIIT the joint POINT uses
    reach: tuple[int, ...]             # every NIIT amount the joint RANGE prices (point included)
    separate_zero: tuple[int, ...]     # sides whose separate-return NIIT the POINT prices at $0
    separate_bracket: tuple[int, ...]  # sides whose $0 separate-return NIIT only the RANGE prices


def _price_niit(
    kind: str, classes: tuple[str | None, str | None], own: tuple[int, int], elected: int | None,
    *, separate: bool,
) -> _NiitPriced:
    """Which NIIT each election figure's point and range use (JF5b part 3a, P-018).

    One reading (a definite 'g' or 'h'): the joint point is that reading's figure. Several
    ('either', or a 'g' whose U.S. spouse the facts do not name): the point keeps the
    combined-income figure and the range covers every reading. ``separate``: the election
    leaves separate returns open — the spouse who is a nonresident without the election
    owes $0 there ((iii)(A); the chapter-2A election is open only on a joint return), at the
    point for a definite 'g' and in the range otherwise.
    """
    readings = _niit_readings(kind, classes, own, elected or 0)
    settled = len(readings) == 1
    point = reach = None
    if elected is not None:
        point = readings[0].point if settled else elected
        reach = tuple(sorted({point, *(x for r in readings for x in r.reach)}))
    nonresident_sides = tuple(sorted({1 - r.us for r in readings if r.paragraph == "g"}))
    # An arriving nonresident spouse of a continuing 6013(g) election (JF5b part 3b) owes NIIT on
    # resident-period income — not recorded — so its separate return keeps the resident-rules
    # figure at the point and $0 only in the range, as an unsettled reading does.
    arriving_sides = tuple(sorted({i for r in readings if r.paragraph == "g" for i in r.arriving}))
    full_nra_sides = tuple(i for i in nonresident_sides if i not in arriving_sides)
    separate_zero = full_nra_sides if separate and settled and readings[0].paragraph == "g" else ()
    separate_bracket = (
        nonresident_sides if separate and not settled
        else arriving_sides if separate else ()
    )
    return _NiitPriced(classes, own, elected, readings, point, reach or (), separate_zero, separate_bracket)


def _who(side: int) -> str:
    return ("you", "your spouse")[side]


def _owe(side: int) -> str:
    return ("owe", "owes")[side]


def _their(side: int) -> str:
    return ("your", "their")[side]


def _poss(side: int) -> str:
    return ("your", "your spouse's")[side]


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _niit_g_reading_text(r: _NiitReading, priced: _NiitPriced, *, full: bool) -> str:
    """One IRC 6013(g) reading of the default, in words."""
    u, n = r.us, 1 - r.us
    own = priced.own
    if full and r.arriving:
        # JF5b part 3b: a continuing 6013(g) election in the year its nonresident spouse arrives.
        return (
            f"{_cap(_who(u))} — the U.S. citizen or resident spouse — {_owe(u)} ${own[u]:,} on {_their(u)} own net "
            "investment income and modified AGI, figured under the married-filing-separately rules against the "
            f"$125,000 threshold; {_who(n)}, the spouse who was a nonresident alien at the start of the year and a "
            f"resident at its close, {'are' if n == 0 else 'is'} subject {_SECTION_6013H_PORTION} — Treas. Reg. "
            "1.1411-2(a)(2)(iv)(A), whose facts (\"married to an individual who is a nonresident alien individual at "
            "the beginning of any taxable year, but is a United States resident at the close of such taxable year\") "
            "fit this later year of a continuing 6013(g) election (a reading: (iii)(A)'s "
            f"{_SECTION_6013G_NRA_NOT_SUBJECT} speaks of a nonresident) — a split this estimate does not record, so "
            f"between $0 and {_their(n)} full-year ${own[n]:,}: {_niit_default_span(r)}; the point uses the full-year "
            f"${r.high:,} and the range ${r.low:,} too"
        )
    if full:
        text = (
            f"{_cap(_who(u))} — the U.S. citizen or resident spouse — {_owe(u)} ${own[u]:,} on {_their(u)} own net "
            "investment income and modified AGI, figured under the married-filing-separately rules against the "
            f"$125,000 threshold, and {_who(n)} $0 ({_SECTION_6013G_NRA_NOT_SUBJECT}): a default of ${r.high:,}"
        )
        if r.low != r.high:
            text += (
                f". {_cap(_who(u))} {'are' if u == 0 else 'is'} in a dual-status year, and only resident-period income "
                f"counts ({_DUAL_STATUS_NIIT_PORTION} — a reading here, since (iii)(A) does not mention it) — a split "
                f"this estimate does not record — so the default may be as low as ${r.low:,}; the point uses the "
                f"full-year ${r.high:,} and the range ${r.low:,} too"
            )
        return text
    text = (
        f"with {_who(u)} as the U.S. citizen or resident spouse, {_their(u)} own ${own[u]:,} against $125,000 and "
        + (f"{_who(n)} on resident-period income only (between $0 and ${own[n]:,}, not recorded): "
           f"{_niit_default_span(r)}" if r.arriving else
           f"$0 for {_who(n)}"
           + (f" (as low as ${r.low:,} on resident-period income only, not recorded)" if r.low != r.high else ""))
    )
    if priced.elected is not None:
        text += (
            f", the second election's ${priced.elected:,} reachable only if this is the first year the U.S. spouse "
            "is subject to NIIT ((iii)(B)(2)) — or if one was made in that earlier first year and continues "
            f"({_SECTION_6013G_CONTINUES})" if r.available
            else ", the second election cannot be MADE this year (on their own figures the U.S. spouse owes no NIIT, "
            "(iii)(B)(2)) unless one made in an earlier year continues (not recorded)"
        )
    return text


def _niit_default_span(r: _NiitReading) -> str:
    return f"a default of ${r.high:,}" if r.low == r.high else f"a default between ${r.low:,} and ${r.high:,}"


def _niit_h_reading_text(r: _NiitReading, priced: _NiitPriced, *, full: bool) -> str:
    """The IRC 6013(h) reading of the default, in words."""
    own = priced.own
    others = [i for i in (0, 1) if i not in r.arriving]
    if not full:
        who = "each of you" if len(r.arriving) == 2 else _who(r.arriving[0])
        text = (
            f"each spouse against $125,000 on their own figures, {who} on resident-period income only (not recorded "
            f"separately): {_niit_default_span(r)}"
        )
        if priced.elected is not None:
            text += (
                f", or the second election's ${priced.elected:,}, which has no first-year condition for 6013(h) "
                "((iv)(B)(2))"
            )
        return text
    parts = [
        f"{_who(i)} {_owe(i)} ${own[i]:,} on {_their(i)} own figures under the married-filing-separately rules"
        for i in others
    ]
    if len(r.arriving) == 2:
        parts.append(
            "each of you becomes a U.S. resident during the year and is subject " + _SECTION_6013H_PORTION
            + " — applied to each of you, a reading, since (iv)(A) speaks of one arriving spouse — a split this "
            f"estimate does not record (one snapshot for the year), so between $0 and your full-year ${own[0]:,} and "
            f"between $0 and your spouse's ${own[1]:,}"
        )
    else:
        a = r.arriving[0]
        parts.append(
            f"{_who(a)}, the spouse who becomes a U.S. resident during the year, {'are' if a == 0 else 'is'} subject "
            + _SECTION_6013H_PORTION + " — a split this estimate does not record (one snapshot for the year), so "
            + (f"between $0 and {_their(a)} full-year ${own[a]:,}" if own[a] else
               f"$0 (on {_their(a)} full-year figures too)")
        )
    return "; ".join(parts) + f": {_niit_default_span(r)}"


def _niit_settle_advice(kind: str, classes: tuple[str | None, str | None]) -> str:
    """What to record so a single reading of the NIIT default is left: for 'either', the
    prior-year return (an earlier 6013(g) election still in effect decides the paragraph)
    and any residency not on file; for a 6013(g) couple both classified nonresident, which
    spouse is the U.S. citizen or resident."""
    wanted = []
    if None in classes or classes == ("nonresident", "nonresident"):
        wanted.append("the visa timeline and days in the US (or the U.S.-person answer) of each spouse")
    if kind != "g":
        wanted.append(
            "the prior-year return (prior_filings.return_forms — a '1040_with_6013_election' entry shows a 6013(g) "
            "election made in an earlier year)"
        )
    return "Record " + " and ".join(wanted) + " to settle it."


def _section_6013_niit_note(
    *, joint: bool, separate: bool, kind: str = "either", priced: _NiitPriced | None = None,
    no_default: bool = False, spouse_split: bool = False, candidate: bool = False, continuing_from: int | None = None,
) -> str:
    """How NIIT was priced under the §6013(g)/(h) election, and what the default is (P-018).

    ``joint`` / ``separate``: which candidate figures carry the election (both when a
    recorded election leaves MFJ and MFS open). ``kind`` picks the 1.1411-2(a)(2)
    paragraph — (iii) for IRC 6013(g), (iv) for IRC 6013(h), both for 'either'.
    ``priced`` (JF5b part 3a): the default as priced from each spouse's own snapshot
    (:func:`_price_niit`); None when the income is one combined snapshot, so the default
    cannot be split — the note then names ``income.spouse`` as what would price it.
    ``candidate`` (JF5b part 3b): no election is recorded — the joint figure is the
    married-filing-jointly CANDIDATE, the figure IF the couple makes it.
    """
    regs = (
        _SECTION_6013G_NIIT if kind == "g"
        else _SECTION_6013H_NIIT if kind == "h"
        else f"{_SECTION_6013G_NIIT} {_SECTION_6013H_NIIT}"
    )
    parts = [
        (f"NIIT under the §6013(g)/(h) election — on the married-filing-jointly CANDIDATE, the figure IF the election "
         f"made for {continuing_from} is still in effect:" if continuing_from is not None else
         "NIIT under the §6013(g)/(h) election — on the married-filing-jointly CANDIDATE, the figure IF you make it "
         "(no election is recorded):") if candidate and joint else "NIIT under the §6013(g)/(h) election:"
    ]
    if no_default:
        return (
            "NIIT under the §6013(g)/(h) election: on their own facts both spouses are U.S. citizens or residents "
            "for this year, so neither default paragraph applies — Treas. Reg. 1.1411-2(a)(2)(iii)(A) reaches only "
            "\"a United States citizen or resident who is married to a nonresident alien individual\" and (iv)(A) "
            "only a spouse \"who is a nonresident alien individual at the beginning of any taxable year\" — so NIIT "
            "follows the ordinary joint or separate rules on these figures."
        )
    if joint and priced is None and spouse_split:
        parts.append(
            "each spouse's own figures and the couple's combined figure were priced from the spouse snapshot, and "
            "NIIT is $0 on every reading — the Treas. Reg. 1.1411-2(a)(2)(iii)/(iv) default and the second election "
            "alike — so the election's NIIT treatment does not change this estimate."
        )
        return " ".join(parts)
    if joint and priced is None:
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
            "here: the income is one combined snapshot, so each spouse's own net investment income and modified "
            "AGI are unknown — enter the spouse's own amounts in income.spouse to price it. When the second "
            f"election is available: {timing} " + _section_6013_niit_i8960(kind)
        )
    elif joint and priced is not None and priced.elected is not None:
        parts.append(_niit_joint_priced_text(kind, priced))
    if separate and (priced is None or not (priced.separate_zero or priced.separate_bracket)):
        parts.append(
            ("And each" if joint else "Each")
            + " separate return here evaluates the net investment income tax on that spouse's own income "
            "against the married-filing-separately threshold, as a resident's would — so if the spouse who is a "
            "nonresident without the election has investment income, their NIIT on a separate figure may be "
            "overstated (the defaults below)"
            + ("; enter the spouse's own amounts in income.spouse to price it." if priced is None else ".")
        )
    elif separate:
        parts.append(_niit_separate_priced_text(priced, joint=joint))
    parts.append(
        "The chapter-1 election does not by itself reach NIIT (chapter 2A). " + regs
    )
    return " ".join(parts)


def _niit_joint_priced_text(kind: str, priced: _NiitPriced) -> str:
    """The joint figure's priced NIIT default, in words (JF5b part 3a)."""
    elected = priced.elected
    combined = (
        f"the combined-income figure the second election gives (${elected:,}: the couple's combined net investment "
        "income and modified AGI against the $250,000 joint threshold)"
    )
    lead = (
        "the joint-return figure's NIIT is the DEFAULT unless the couple also makes the optional SECOND "
        "(chapter 2A) election. "
    )
    readings = priced.readings
    if len(readings) == 1 and readings[0].paragraph == "g":
        r = readings[0]
        u = r.us
        text = (
            lead + "Priced here for IRC 6013(g) (Treas. Reg. 1.1411-2(a)(2)(iii)(A): \"the spouses will be treated "
            "as married filing separately for purposes of section 1411\"): " + _niit_g_reading_text(r, priced, full=True)
            + ". "
        )
        if not r.available:
            text += (
                f"The joint figure uses it — NIIT ${r.high:,} — and the second election is NOT available this year: "
                f"(iii)(B)(2) requires it {_SECTION_6013G_FIRST_YEAR}, and {_SECTION_6013G_WITHOUT_REGARD} — "
                f"reading \"subject to tax under section 1411\" as owing NIIT on {_their(u)} own figures, {_who(u)} "
                f"{_owe(u)} none, so this is not that year, and an election made anyway fails ((iii)(B)(3): "
                f"{_SECTION_6013G_NO_EFFECT}). So the second election cannot be MADE this year; {combined} applies "
                f"only if a chapter-2A election made in an earlier year continues ({_SECTION_6013G_CONTINUES}) — a "
                "fact this profile does not record, so it is not in the range. "
            )
        else:
            text += (
                f"The joint figure uses the default (${r.high:,}), which applies unless a chapter-2A election is made "
                "this year or one made in an earlier year continues. The range also "
                f"prices {combined}, reachable only if this is the first taxable year the U.S. spouse is subject to "
                f"NIIT — (iii)(B)(2): {_SECTION_6013G_FIRST_YEAR}, and {_SECTION_6013G_WITHOUT_REGARD} — or if "
                f"the second election was made in that year and continues ({_SECTION_6013G_CONTINUES}); which "
                "earlier year was the first is a fact this profile does not record. "
            )
        return text + _section_6013_niit_i8960("g")
    if len(readings) == 1:
        r = readings[0]
        return (
            lead + "Priced here for IRC 6013(h) (Treas. Reg. 1.1411-2(a)(2)(iv)(A): \"each spouse will be treated "
            "as married filing separately for the entire year for purposes of section 1411\", each against the "
            "$125,000 threshold): " + _niit_h_reading_text(r, priced, full=True) + ". The second election has no "
            "first-year condition for 6013(h) — (iv)(B)(2): taxpayers making the chapter-1 election \"may elect "
            "to have their section 6013(h) election apply for purposes of chapter 2A\" — so the couple can take "
            f"the lower: the joint figure uses ${r.point:,}, the lower of {combined} and the default's high end "
            f"(${r.high:,}, on income that is all positive not below the true default), and the range also prices "
            f"${min(elected, r.low):,} (with "
            "the default's low end). " + _section_6013_niit_i8960("h")
        )
    lows, highs = min(priced.reach), max(priced.reach)
    g_texts = [_niit_g_reading_text(r, priced, full=False) for r in readings if r.paragraph == "g"]
    h_texts = [_niit_h_reading_text(r, priced, full=False) for r in readings if r.paragraph == "h"]
    if kind == "g":
        why = (
            "On the facts on file both of you classify as nonresident without the election, so which of you is the "
            "U.S. citizen or resident spouse (IRC 6013(g) needs one) is not settled, and it decides the figure. "
            "Under IRC 6013(g) ((iii)(A)): " + "; or, ".join(g_texts) + ". "
        )
    else:
        why = (
            "Which paragraph governs is not settled on these facts — IRC 6013(g) when a spouse is a nonresident "
            "alien at year end (or a 6013(g) election made in an earlier year is still in effect), IRC 6013(h) when "
            "a spouse becomes a resident during the year — and the kind decides which figure is lawful. Under IRC "
            "6013(g) ((iii)(A)): " + "; or, ".join(g_texts) + ". Under IRC 6013(h) ((iv)(A)): "
            + "; ".join(h_texts) + ". "
        )
    return (
        lead + why + f"The joint figure keeps {combined}; the range covers every reading (NIIT from ${lows:,} to "
        f"${highs:,}). " + _niit_settle_advice(kind, priced.classes) + " " + _section_6013_niit_i8960(kind)
    )


def _niit_separate_priced_text(priced: _NiitPriced, *, joint: bool) -> str:
    """The separate returns' NIIT under the election, in words (JF5b part 3a)."""
    lead = "And on" if joint else "On"
    own = priced.own
    if priced.separate_zero:
        n = priced.separate_zero[0]
        u = 1 - n
        text = (
            f"{lead} each separate return here, {_who(n)} — the spouse who is a nonresident without the election — "
            f"{_owe(n)} NIIT $0: (iii)(A) {_SECTION_6013G_NRA_NOT_SUBJECT}, and the chapter-2A election is open only "
            f"to {_SECTION_6013G_JOINT_ONLY}."
        )
        if own[n] > 0:
            text += (
                f" The range also prices that return under resident rules (NIIT ${own[n]:,} on {_their(n)} own "
                "figures against $125,000) — the reading in which a chapter-2A election made in an earlier joint "
                "year carries over; the texts read do not settle what a continuing election does in a year the "
                "couple files separately."
            )
        text += (
            f" {_cap(_poss(u))} separate return owes NIIT ${own[u]:,} on either "
            "reading."
        )
        return text
    sides = priced.separate_bracket
    arriving = [i for r in priced.readings if r.paragraph == "g" for i in r.arriving]
    if len(priced.readings) == 1 and arriving:
        # JF5b part 3b: a continuing 6013(g) election in the year its nonresident spouse arrives.
        a = arriving[0]
        return (
            f"{lead} each separate return here the net investment income tax is evaluated on each spouse's own "
            f"income against the $125,000 threshold under resident rules; {_poss(a)} return — the spouse who becomes "
            f"a resident during the year — is subject {_SECTION_6013H_PORTION} (Treas. Reg. 1.1411-2(a)(2)(iv)(A)'s "
            "facts, a reading), a split this estimate does not record, so the range also prices that return's NIIT "
            "at $0."
        )
    return (
        f"{lead} each separate return here the net investment income tax is evaluated on each spouse's own income "
        "against the $125,000 threshold under resident rules; the range also prices "
        + (_poss(sides[0]) if len(sides) == 1 else "each spouse's")
        + " separate-return NIIT at $0 — the (iii)(A) default for the spouse who is a nonresident without the "
        f"election ({_SECTION_6013G_NRA_NOT_SUBJECT}). Which spouse that is, and what a continuing chapter-2A "
        "election does in a year the couple files separately, are not settled on these facts and the texts read."
    )


# JF1b.10 (P-018): the rules a head of household on the nonresident-spouse route still meets as a
# MARRIED individual — IRC 2(b)(2)(B) makes the filer unmarried only "For purposes of this
# subsection" (26 U.S.C. 21, 25A, 36B, 86, 221, 1211, 3101, Treas. Reg. 1.1211-1, 1.1411-2 and the
# 2025 Form 8863 and 8962 instructions, read 2026-09-27). Keyed by the _bottom_line(married_7703=True)
# note that fired.
_MARRIED_7703_RULES = {
    "m7703_education": (
        "no education credit — IRC 25A(g)(6): \"If the taxpayer is a married individual (within the meaning of "
        "section 7703), this section shall apply only if the taxpayer and the taxpayer's spouse file a joint return "
        "for the taxable year.\" (the 2025 Form 8863 instructions, Who cannot claim a credit: \"You (or your "
        "spouse) were a nonresident alien for any part of 2025 and didn't elect to be treated as a resident alien "
        "for tax purposes.\")"
    ),
    "m7703_dependent_care": (
        "no child and dependent care credit — IRC 21(e)(2): \"If the taxpayer is married at the close of the "
        "taxable year, the credit shall be allowed under subsection (a) only if the taxpayer and his spouse file a "
        "joint return for the taxable year.\" (its living-apart exception, 21(e)(4), is the other route)"
    ),
    "m7703_sli": (
        "no student loan interest deduction — IRC 221(e)(2): \"If the taxpayer is married at the close of the "
        "taxable year, the deduction shall be allowed under subsection (a) only if the taxpayer and the taxpayer's "
        "spouse file a joint return for the taxable year.\" ((e)(3): \"Marital status shall be determined in "
        "accordance with section 7703.\")"
    ),
    "m7703_capital_loss": (
        "the capital-loss deduction is limited to $1,500 — IRC 1211(b)(1): \"$3,000 ($1,500 in the case of a "
        "married individual filing a separate return)\"; Treas. Reg. 1.1211-1(b)(7)(i): \"In the case of a husband "
        "or a wife who files a separate return\""
    ),
    "m7703_ptc": (
        "no premium tax credit, so the advance payments are repaid up to the repayment limitation — IRC "
        "36B(c)(1)(C): \"If the taxpayer is married (within the meaning of section 7703) at the close of the taxable "
        "year, the taxpayer shall be treated as an applicable taxpayer only if the taxpayer and the taxpayer's "
        "spouse file a joint return for the taxable year.\" The 2025 Form 8962 instructions' Exception 1 reaches "
        "only a separate return filed \"because you meet the requirements for Married persons who live apart "
        "under Head of Household in the Instructions for Form 1040\", and Exception 2 only married filing "
        "separately"
    ),
    "m7703_niit": (
        "the net investment income tax uses the $125,000 married-filing-separately threshold — Treas. Reg. "
        "1.1411-2(a)(2)(iii)(A): \"In the case of a United States citizen or resident who is married to a "
        "nonresident alien individual, the spouses will be treated as married filing separately for purposes of "
        "section 1411.\""
    ),
    "m7703_addmed": (
        "Additional Medicare Tax uses the $125,000 threshold — IRC 3101(b)(2)(B): \"in the case of a married "
        "taxpayer (as defined in section 7703) filing a separate return, ½ of the dollar amount determined under "
        "subparagraph (A)\""
    ),
    "m7703_social_security": (
        "the taxable-Social-Security worksheet uses a $0 base amount, assuming you and your spouse did not live "
        "apart at all times during the year, as the married-filing-separately candidate does — IRC 86(c)(1)(C): "
        "\"zero in the case of a taxpayer who— (i) is married as of the close of the taxable year (within the "
        "meaning of section 7703) but does not file a joint return for such year, and (ii) does not live apart from "
        "his spouse at all times during the taxable year\" (lived apart all year: the $25,000 of (A) — record "
        "household.spouses_lived_apart_all_year)"
    ),
}


# The refundable credits IRC 6654(f)(4) takes off the tax: the part IV credits other than section 31's
# (the excess social security credit is section 31(b), withholding — its own input).
_REFUNDABLE_CREDIT_SLOTS = (
    "actc_refundable", "ctc_refundable_2021", "dependent_care_credit_refundable_2021", "eitc", "aotc_refundable",
    "net_ptc",
)


def safe_harbor_inputs_from_estimate(estimate: "RefundEstimate") -> dict[str, int]:
    """The calc op estimated_tax_safe_harbor inputs one estimate's ledger already carries (JF4), read off
    the primary figure's slots: ``projected_tax`` (total tax), ``expected_withholding`` (the withholding
    row — the Additional Medicare Tax withholding is its own input), ``excess_ss_credit``,
    ``additional_medicare_withheld`` and ``refundable_credits``. The filing status, year and prior-year
    figures are the caller's."""
    by: dict[str, int] = {}
    for line in estimate.composition:
        by[line.slot] = by.get(line.slot, 0) + line.amount
    return {
        "projected_tax": by.get("total_tax", 0),
        "expected_withholding": -by.get("withholding", 0),
        "excess_ss_credit": -by.get("excess_ss_credit", 0),
        "additional_medicare_withheld": -by.get("additional_medicare_withholding", 0),
        "refundable_credits": -sum(by.get(s, 0) for s in _REFUNDABLE_CREDIT_SLOTS),
    }


def _addmed_box_note(
    income: IncomeSnapshot, year: int, knowledge_dir, statuses: list[str], *, form_8959: bool, withheld: bool,
) -> str | None:
    """The Form 8959 disclosure (JF3, pitfall P-019): what was priced, whether box 1 stood in for box 5,
    and the box-6 credit. It fires when a figure carries Form 8959, when box 6 was given, or when box 1
    stood in and box 1 plus the year's 402(g) deferral limit reaches the lowest threshold priced — a
    deferrer's box 5 can cross it while box 1 does not, and the loss would otherwise be silent."""
    people = [income, *([income.spouse] if income.spouse is not None else [])]
    standin = [p for p in people if p.medicare_wages is None and p.wages > 0]
    box6_given = any(p.medicare_tax_withheld for p in people)
    pack = load_knowledge("federal", year, base_dir=knowledge_dir)
    params = pack.tax.additional_medicare_tax
    if params is None:
        return None
    threshold = min(params.thresholds[s] for s in statuses if s in params.thresholds)
    limits = pack.contribution_limits
    limit = limits.elective_deferral_402g.limit if limits is not None else None
    box5 = sum(p.wages if p.medicare_wages is None else p.medicare_wages for p in people)
    reach = bool(standin) and limit is not None and box5 < threshold <= box5 + limit * len(standin)
    if not (form_8959 or box6_given or reach):
        return None
    text = (
        "Additional Medicare Tax (Form 8959): 0.9% of Medicare wages (W-2 box 5) and self-employment earnings "
        "over the status threshold" + (" is in this figure." if form_8959 else " is $0 on these amounts.")
    )
    if standin:
        who = "" if len(people) == 1 else (" for both spouses" if len(standin) == 2 else (
            " for you" if standin[0] is income else " for your spouse"))
        text += (
            f" Box 1 wages stood in for box 5{who}: box 5 keeps the 401(k)/403(b) deferrals box 1 leaves out, and "
            "an exempt F/J student's box 5 is $0, so enter medicare_wages (W-2 box 5)."
        )
        if reach:
            text += (
                f" Box 1 is under the ${threshold:,} threshold, but box 1 plus the year's ${limit:,} 402(g) "
                "deferral limit reaches it, so box 5 may cross it."
            )
    if withheld:
        text += (
            " The Additional Medicare Tax your employers withheld — W-2 box 6 above \"your regular Medicare tax "
            "withholding on Medicare wages\" (1.45% of box 5) — is credited with your federal withholding."
        )
    elif not box6_given and form_8959:
        text += (
            " If an employer withheld extra Medicare tax (W-2 box 6 above 1.45% of box 5), enter each employer's "
            "box 6 in medicare_tax_withheld — not in federal_withholding."
        )
    return text


def _married_7703_note(keys: set[str]) -> str:
    """The married-filing-separately rules a nonresident-spouse-route head-of-household figure met (JF1b.10)."""
    rules = [text for key, text in _MARRIED_7703_RULES.items() if key in keys]
    return (
        "Head of household on the nonresident-spouse route makes you unmarried ONLY for the filing status — IRC "
        "2(b)(2)(B) reads \"For purposes of this subsection— ... a taxpayer shall be considered as not married at "
        "the close of his taxable year if at any time during the taxable year his spouse is a nonresident alien\" — "
        "so the head-of-household rates and standard deduction apply, while the rules that ask whether a married "
        "individual files a joint return still read you as filing separately: " + "; ".join(rules) + "."
    )


def _hoh_pair_note(
    *, spouse_nra: bool, weighed: bool, unsettled: bool, alternative: int | None, snapshot: bool = True,
    taxpayer_nonresident: bool = False, eitc_child: bool = True, spouse_dual: bool = False,
    candidate: bool = False,
) -> str:
    """What a married filer's head-of-household figure is, by route (P-018; Pub 501 and Pub 519).
    ``spouse_dual`` (JF5b part 3b): the spouse's separate return inside it runs under Pub 519 ch. 6's
    dual-status restrictions on either route — the route changes only your return. ``candidate``
    (JF1b.10): the figure is a candidate with no §6013(g)/(h) election recorded, so it exists only
    without one."""
    if taxpayer_nonresident:
        return (
            "The head-of-household figure prices the confirmed status as given — the residency caveat explains why "
            "a nonresident alien cannot use it (Pub 519 ch. 5)."
            + (" The spouse's separate return inside it is priced on "
               + ("Pub 519 ch. 6's dual-status rules" if spouse_dual else "resident rules")
               + ", and the spouse's residency is not settled — record the spouse's visa timeline and days in the US."
               if unsettled and snapshot else "")
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
    spouse_rules = " on Pub 519 ch. 6's dual-status rules" if spouse_dual else None
    if spouse_nra:
        text += (
            ((spouse_rules or " on Form 1040-NR rules") if snapshot else "")
            + " — head of household here rests on your spouse being a nonresident alien (Pub 501, Considered "
            "Unmarried: \"You are considered unmarried for head of household purposes if your spouse was a "
            "nonresident alien at any time during the year and you don't choose to treat your nonresident spouse "
            f"as a resident alien.\"). No earned income credit is computed on it — {eitc_quote}"
        )
        if candidate:
            text += (
                " No §6013(g)/(h) election is recorded, so this figure exists only if you and your spouse do NOT make "
                "it — the married-filing-jointly figure is the one under the election."
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
            ((spouse_rules or " on resident rules") if snapshot else "")
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
        if snapshot and not spouse_dual:
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


def _prior_year_form(profile: Profile, year: int) -> str | None:
    """The TAXPAYER's return for ``year - 1`` (PriorFilings.return_forms), or None (JF5b)."""
    pf = profile.prior_filings
    return residency.prior_year_return_form(pf.return_forms if pf is not None else None, year)


def _prior_year_resident(profile: Profile, year: int) -> bool | None:
    """The TAXPAYER's prior-year residency fact, from PriorFilings.return_forms[year - 1] only
    (residency.prior_year_resident_from_return_forms) — never from filed_years (JF5b)."""
    pf = profile.prior_filings
    return residency.prior_year_resident_from_return_forms(pf.return_forms if pf is not None else None, year)


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

    The TAXPAYER's prior-year residency fact (:func:`_prior_year_resident`, JF5b) is
    passed to the classifier: a prior-year resident who meets the substantial presence
    test is a resident from January 1 (Treas. Reg. 301.7701(b)-4(e)(1)), and one who
    fails it gets a first-position CONTRADICTION reason. A prior-year joint Form 1040
    under the election is not read as residency; the result's reasons say so
    (residency.prior_year_election_reason).
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
        result = residency.classify(
            imm.visa_timeline, days_by_year, year, section_6013_election=elected,
            prior_year_resident=_prior_year_resident(profile, year),
        )
    except (ValueError, AssertionError):
        # An incomplete/contradictory timeline cannot be classified yet — fall back
        # to the us_person best-effort rather than guessing (the election still
        # decides residency when it is in effect; its no-election answer is unknown).
        return residency.classify([], {}, year, section_6013_election=True) if elected else None
    if _prior_year_form(profile, year) == "1040_with_6013_election":
        result = result.model_copy(update={"reasons": [*result.reasons, residency.prior_year_election_reason(year)]})
    return result


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


def _gate_classification(
    classification: str | None, imm, rf, year: int, *, prior_year_resident: bool | None = None,
) -> str | None:
    """``classification`` for the IRC 6013(g)(3) gate: 'nonresident' only when it is CERTAIN —
    a nonresident answer that real presence in a missing lookback year could flip is
    unknown (None), and so is one that contradicts a recorded prior-year residency
    (``prior_year_resident`` True — the taxpayer's PriorFilings.return_forms; the spouse
    has no such fact). The rule intake's gate shares (residency.certain_nonresident)."""
    if classification != "nonresident" or imm is None or not imm.visa_timeline or rf is None:
        return classification
    days = {y: a.value for y, a in rf.days_in_us.items() if a is not None and a.value is not None}
    certain = residency.certain_nonresident(imm.visa_timeline, days, year, prior_year_resident=prior_year_resident)
    return classification if certain else None


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
    taxpayer_6013: str | None = None  # section_6013_kind's inputs: 'us' for a declared U.S. person,
    spouse_6013: str | None = None    # else the no-election classification (JF5b part 3a's NIIT default)


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
        _gate_classification(
            taxpayer, profile.immigration, profile.residency_facts, year,
            prior_year_resident=_prior_year_resident(profile, year),
        ) == "nonresident"
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
        # A recorded answer on (h) facts may be an earlier 6013(g) election still in effect
        # ('either'); a joint status read as the election, or the election as a CANDIDATE with
        # no answer recorded (JF5b part 3b), is a new choice. A prior-year joint return under the
        # election makes it 6013(g), which continues (residency.section_6013_kind).
        kind=residency.section_6013_kind(
            taxpayer, spouse, recorded=_section_6013_recorded(profile),
            prior_year_election=_prior_year_form(profile, year) == "1040_with_6013_election",
        ),
        precondition_unmet=unmet,
        unavailable=unavailable,
        nonresident_in_couple=nonresident_in_couple,
        no_joint=no_joint,
        joint_blocked=no_joint and confirmed == _MFJ,
        taxpayer_6013=taxpayer,
        spouse_6013=spouse,
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


def _signed_dollars(value: int) -> str:
    return f"{'+' if value >= 0 else '-'}${abs(value):,}"


def _missing_lookback_text(imm, rf, year: int) -> str:
    """The lookback years a person's timeline covers but their day counts lack, as text."""
    if imm is None or not imm.visa_timeline or rf is None:
        return f"{year - 1} or {year - 2}"
    days = {y: a.value for y, a in rf.days_in_us.items() if a is not None and a.value is not None}
    years = residency.missing_lookback_years(imm.visa_timeline, days, year)
    return " and ".join(str(y) for y in years) if years else f"{year - 1} or {year - 2}"


def _unsettled_residency_notes(
    profile: Profile, year: int, *, primary: str, contradiction: str | None, flip_reason: str | None,
    resident_reading: int | None, election: bool, spouse_result, spouse_flip_reason: str | None,
    spouse_flip_alternative: int | None,
) -> list[str]:
    """The notes an unsettled nonresident answer puts FIRST in the estimate (JF5b, P-018).

    The taxpayer's CONTRADICTION with a recorded prior-year residency (residency's
    first-position reason, a labeled judgment) and classify's "may be WRONG" reason, each
    quoted as the classifier gives it, with the resident reading the range prices; then the
    spouse's own answer that may flip, with the spouse-resident reading of the two-return
    MFS pair.
    """
    notes: list[str] = []

    def bracket(reading: str) -> str:
        return (
            f" The point prices Form 1040-NR rules; the range ALSO prices the same inputs under RESIDENT rules for "
            f"the whole year ({primary}: {_signed_dollars(resident_reading)}, + refund / - owed) — {reading}."
        )

    under_election = (
        " The figures here run under the §6013(g)/(h) election and are a resident's either way; this answer still "
        "decides FICA (the withheld-in-error note) and the election's precondition."
    )
    if contradiction is not None:
        text = contradiction
        if resident_reading is not None:
            text += bracket(
                f"the reading in which the timeline is incomplete (reading (1) above) and {year} meets the "
                f"substantial presence test after all: as a prior-year resident you would then be a resident from "
                f"January 1 (Treas. Reg. 301.7701(b)-4(e)(1)), so this full-year figure is that reading; under "
                f"readings (2) and (3) the Form 1040-NR point stands"
            )
        elif election:
            text += under_election
        notes.append(text)
    if flip_reason is not None:
        text = flip_reason
        if resident_reading is not None and contradiction is None:
            years = _missing_lookback_text(profile.immigration, profile.residency_facts, year)
            start = (
                f"the first day of presence in {year}"
                if _prior_year_resident(profile, year) is False
                else f"the first day of presence in {year} (January 1 if you were also a U.S. resident during "
                f"{year - 1} — record the return you filed for {year - 1} in prior_filings.return_forms)"
            )
            text += bracket(
                f"if real presence in {years} meets the substantial presence test — residency would then start on "
                f"{start}, so this full-year figure is the favorable bound"
            )
        elif election and contradiction is None:
            text += under_election
        notes.append(text)
    if spouse_flip_reason is not None and spouse_result is not None:
        sp = profile.household.spouse if profile.household is not None else None
        years = _missing_lookback_text(sp.immigration if sp else None, sp.residency_facts if sp else None, year)
        text = (
            f"The SPOUSE's own nonresident classification may be WRONG: the spouse's days in the U.S. have no entry "
            f"for {years} although the spouse's visa timeline covers {'them' if ' and ' in years else 'it'} "
            f"(counted as 0 days), and with "
            f"{spouse_result.spt.days_current_year} day(s) present in {year} (at least 31) real presence in {years} "
            f"could bring the weighted 3-year total to 183 and FLIP the spouse to resident (IRS Pub. 519, "
            f"substantial presence test)."
        )
        if spouse_flip_alternative is not None:
            text += (
                f" The spouse's separate return was priced on Form 1040-NR rules for the point; the range ALSO prices "
                f"it under RESIDENT rules for the whole year — married filing separately would then total "
                f"{_signed_dollars(spouse_flip_alternative)} (+ refund / - owed) — if real presence in {years} meets "
                f"the substantial presence test, the spouse's residency would then start on the first day of "
                f"presence in {year} (January 1 if the spouse was also a U.S. resident during {year - 1}, which real "
                f"presence in {year - 1} can itself establish), so this full-year figure is the favorable bound."
            )
        text += f" Record the spouse's days in the U.S. for {years} (0 is a valid answer) and rerun."
        notes.append(text)
    return notes


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
                "married filers use married-filing-separately (single if unmarried — an inference, ch. 6 "
                "names the column only for a married filer) — no joint return "
                "and no head of household absent a §6013(g)/(h) election to be treated as a full-year "
                "resident (Pub 519 ch. 6, 'Restrictions for Dual-Status Taxpayers'); and NO earned income "
                "credit, education credits (AOTC/LLC) or credit for the elderly or the disabled without that "
                "election (Pub 519 ch. 6, Tax Credits and Payments: \"You cannot claim the education credits, "
                "EIC, or credit for the elderly or the disabled unless you are married and you choose to be "
                "treated as a resident\" for the whole year by filing jointly; IRC 32(c)(1)(D), 25A(g)(7), "
                "22(f)).",
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
# the CTC worksheet arithmetic lives here — deterministic and data-driven; the EITC is the EIC Table,
# calc.eic_table_credit).
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
    """EITC: the EIC Table's figure (calc.eic_table_credit) when the pack carries its eic_table; otherwise the
    ratio approximation — phase-in at max_credit/earned_income_amount, phase-out (on the GREATER of AGI or earned
    income) at max_credit/(complete-begin)."""
    key = "3+" if n_qc >= 3 else str(n_qc)
    row = cfg["by_qualifying_children"][key]
    if cfg.get("eic_table") is not None and "credit_rate" in row:
        from taxfill_core.calc import eic_table_credit  # noqa: PLC0415

        return eic_table_credit(Decimal(earned), Decimal(agi), row, status == _MFJ, cfg["eic_table"])[0]
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


def _schedule_1a_engaged(income: IncomeSnapshot, seniors: int) -> bool:
    return bool(income.qualified_tips or income.qualified_overtime_premium or income.car_loan_interest or seniors)


def _senior(dob_answer, tax_id_answer, year: int) -> bool | None:
    """Schedule 1-A Part V for one person: 65 or older at the end of ``year`` (born before January 2 of year - 64,
    IRC 151(d)(5)(C)(ii)'s "attained age 65 before the close of the taxable year" — the knowledge pack's
    senior_deduction.born_before, test-pinned to this rule) with a valid SSN. None when the date of birth
    is unknown."""
    dob = getattr(dob_answer, "value", None)
    if dob is None:
        return None
    if dob >= date(year - 64, 1, 2):
        return False
    tax_id = str(getattr(tax_id_answer, "value", "") or "").replace("-", "").strip()
    return bool(tax_id) and len(tax_id) == 9 and tax_id.isdigit() and not tax_id.startswith("9")   # an ITIN starts with 9


def _valid_ssn(tax_id_answer) -> bool | None:
    """A recorded tax ID read as the SSN the 2026 education-credit rule needs: True for an SSN, False for an ITIN
    (it starts with 9), None when none is recorded (JT1e). Whether an SSN is 'valid for employment' is not on the
    profile — disclosed."""
    tax_id = str(getattr(tax_id_answer, "value", "") or "").replace("-", "").strip()
    if not tax_id:
        return None
    return len(tax_id) == 9 and tax_id.isdigit() and not tax_id.startswith("9")


def _ssn_oks(snap: "IncomeSnapshot") -> list[bool | None]:
    """aotc_students_ssn_ok padded to one entry per student (JT1e)."""
    n = len(snap.aotc_qualified_expenses)
    return [*snap.aotc_students_ssn_ok, *[None] * n][:n]


def _with_education_ssn(profile: Profile, income: IncomeSnapshot) -> IncomeSnapshot:
    """JT1e: fill each snapshot's education SSN facts from the profile's tax IDs when the caller left them None."""
    ident = profile.identity
    spouse = profile.household.spouse if profile.household is not None else None
    tp = _valid_ssn(getattr(ident, "tax_id", None)) if ident is not None else None
    sp = _valid_ssn(getattr(spouse, "tax_id", None)) if spouse is not None else None
    update: dict[str, Any] = {}
    if income.education_ssn_taxpayer is None and tp is not None:
        update["education_ssn_taxpayer"] = tp
    if income.education_ssn_spouse is None and sp is not None:
        update["education_ssn_spouse"] = sp
    if income.spouse is not None and income.spouse.education_ssn_taxpayer is None and sp is not None:
        update["spouse"] = income.spouse.model_copy(update={"education_ssn_taxpayer": sp, "education_ssn_spouse": tp})
    return income.model_copy(update=update) if update else income


def _with_senior_flags(profile: Profile, year: int, income: IncomeSnapshot) -> IncomeSnapshot:
    """JF7: fill each snapshot's Schedule 1-A senior flags from the profile when the caller left them None."""
    ident = profile.identity
    spouse = profile.household.spouse if profile.household is not None else None
    tp = _senior(getattr(ident, "dob", None), getattr(ident, "tax_id", None), year) if ident is not None else None
    sp = _senior(getattr(spouse, "dob", None), getattr(spouse, "tax_id", None), year) if spouse is not None else None
    update: dict[str, Any] = {}
    if income.senior_taxpayer is None:
        update["senior_taxpayer"] = bool(tp)
    if income.senior_spouse is None:
        update["senior_spouse"] = bool(sp)
    if income.spouse is not None and income.spouse.senior_taxpayer is None:
        update["spouse"] = income.spouse.model_copy(update={"senior_taxpayer": bool(sp), "senior_spouse": bool(tp)})
    return income.model_copy(update=update) if update else income


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
    dual_status: bool = False,
    nonresident_period_deposit: bool = False,
    niit_override: _NiitOverride | None = None,
    married_7703: bool = False,
    married_separate: bool = False,
    spouses_apart_all_year: bool = False,
    se_ss_wages: list[int | None] | None = None,
    medicare_withheld_groups: list[tuple[list[int], int]] | None = None,
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

    ``dual_status`` (JF5b, P-018): THIS return is a dual-status year's (no §6013(g)/(h)
    election) and runs under Pub 519 ch. 6, Restrictions for Dual-Status Taxpayers —
    "You cannot use the standard deduction allowed on Form 1040 or 1040-SR. However, you
    can itemize any allowable deductions." (the deduction is the supplied itemized amount
    or $0, as on the nonresident path, including the 'standard' pair mode), and no EITC
    (IRC 32(c)(1)(D)) and no education credit (IRC 25A(g)(7)); the rates, the preferential
    worksheet and NIIT stay the resident ones (one snapshot for the whole year — the
    caller discloses the approximation). ``nonresident_period_deposit``: the PAYEE's own
    year is dual-status, so only ``income.bank_deposit_interest_nonresident_period`` is
    excluded — Treas. Reg. 1.871-13(a)(1) prices the nonresident part under the nonresident
    rules, where 871(i)(2)(A) applies, and the resident part under the resident rules —
    even when ``nonresident`` prices this return as a full-year nonresident's (the spouse's
    assumed reading, P-018). ``dual_status`` implies it. The excluded amount is also out of
    NIIT's investment income: it is not income at all, and Treas. Reg. 1.1411-2(a)(2)(ii)
    counts only "the income he or she receives during the portion of the year for which he
    or she is treated as a resident of the United States".

    ``niit_override`` (JF5b part 3a, P-018): THIS figure's NIIT is not the one its own
    snapshot gives — under the §6013(g)/(h) election the joint figure's NIIT is the
    Treas. Reg. 1.1411-2(a)(2)(iii)(A)/(iv)(A) default (each spouse's own figures under
    the married-filing-separately rules) unless the second, chapter-2A election is made,
    and a separate return of the spouse who is a nonresident without the election owes
    none under (iii)(A). The caller prices that amount from independent runs; NIIT adds to
    the total tax and nothing after it, so the rest of the return is unchanged.

    ``married_7703`` (JF1b.10, P-018): THIS is a head-of-household return on the
    nonresident-spouse route, and its filer is still MARRIED outside the filing-status
    subsection — IRC 2(b)(2)(B) reads "For purposes of this subsection— ... a taxpayer shall
    be considered as not married at the close of his taxable year if at any time during the
    taxable year his spouse is a nonresident alien". The head-of-household rates and standard
    deduction stay; every provision that asks whether a married individual files a joint or a
    separate return reads this one as filing separately: no education credit (IRC 25A(g)(6)),
    no dependent care credit (21(e)(2)), no student loan interest deduction (221(e)(2)-(3)),
    the $1,500 capital-loss limit (1211(b)(1); Treas. Reg. 1.1211-1(b)(7)(i)), no premium tax
    credit (36B(c)(1)(C)), the married-filing-separately NIIT threshold (Treas. Reg.
    1.1411-2(a)(2)(iii)(A) with (d)(1)(ii)) and Additional Medicare Tax threshold (IRC
    3101(b)(2)(B)), and a zero taxable-Social-Security base amount (IRC 86(c)(1)(C), on the
    married-filing-separately candidate's lived-together assumption). Each gate that changes
    the figure adds an ``m7703_*`` key to ``notes``. The lived-apart route never passes it: IRC
    7703(b) makes that filer unmarried for each provision that refers to section 7703.

    ``married_separate`` (JF2.5): THIS return is a married individual's separate return for IRC
    1211(b)(1) — "$1,500 in the case of a married individual filing a separate return" — which does
    not refer to section 7703, so a head of household through living apart is still married for it
    (Pub 501: "You may be considered unmarried for the purpose of using head of household status but
    not for other purposes"); ``married_7703`` and married filing separately imply it.
    ``spouses_apart_all_year`` (JF2.5): the spouses lived apart at ALL times during the year
    (household.spouses_lived_apart_all_year), so a separate return's taxable-Social-Security base
    amount is the $25,000 of IRC 86(c)(1)(A), not the $0 of 86(c)(1)(C).

    JF3 (pitfall P-019): Form 8959 prices ``income.medicare_wages`` (W-2 box 5; box 1 stands in when
    None); Schedule SE subtracts each person's ``ss_wages`` (boxes 3 + 7) from the wage base —
    ``se_ss_wages`` aligns with ``se_persons`` (None entries fall back to that person's box 1); and
    ``medicare_withheld_groups`` — one (box 6 list, box 5) per person who gave box 6, default this
    snapshot's own — prices the Additional Medicare Tax withholding credit (box 6 less 1.45% of box 5,
    the rate from the pack's employee_social_security block).
    """
    citations: list[Citation] = []
    comp: list[CompositionLine] = []
    pack = load_knowledge("federal", year, base_dir=knowledge_dir)
    pack_tax = pack.tax
    credits_block = pack.credits
    mfs = status == _MFS
    # JF1b.10: a married individual's SEPARATE return — married filing separately, or a
    # head of household still married under IRC 7703 (the nonresident-spouse route).
    separate = mfs or married_7703
    sep_status = _MFS if married_7703 else status  # the status each married-separately rule keys on

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
    # JF5b: a dual-status payee's year splits (Treas. Reg. 1.871-13(a)(1)), so only the
    # deposit interest received in the nonresident part is excluded — never the whole.
    deposit_excluded = 0
    period_only = dual_status or nonresident_period_deposit
    if status != _MFJ and (period_only or nonresident):
        deposit_excluded = (
            income.bank_deposit_interest_nonresident_period if period_only else income.bank_deposit_interest
        )
    if deposit_excluded > 0:
        base -= deposit_excluded
        comp.append(
            _line(
                "deposit_interest_exclusion",
                label=_DUAL_DEPOSIT_EXCLUSION_LABEL if period_only else _DEPOSIT_EXCLUSION_LABEL,
                amount=-deposit_excluded,
            )
        )

    half_se = 0
    se_amount = 0
    # Schedule SE is PER PERSON: the MFJ spouse-split path passes each spouse's own
    # (se_net, own_wages) so one spouse's W-2 wages never absorb the other spouse's
    # SE wage base; without a split the snapshot is one person's amounts.
    se_citation = None
    persons = se_persons if se_persons is not None else [(income.self_employment_net, income.wages)]
    ss_boxes = se_ss_wages if se_ss_wages is not None else [income.ss_wages]
    for (se_net, own_wages), own_ss in zip(persons, [*ss_boxes, *[None] * (len(persons) - len(ss_boxes))]):
        if se_net >= 400:
            # Schedule SE: the W-2 social security wages (boxes 3 + 7) consume the wage base first;
            # box 1 stands in only when the box is not given — disclosed (JF3, P-019).
            if own_ss is None and own_wages and notes is not None:
                notes.add("se_box1_standin")
            se = se_tax(se_net, year, knowledge_dir, w2_ss_wages=own_wages if own_ss is None else own_ss)
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
        loss_cap = 1500 if (separate or married_separate) else 3000
        capital = max(combined_gain, -loss_cap)
        if married_7703 and combined_gain < -loss_cap and notes is not None:
            notes.add("m7703_capital_loss")
        elif married_separate and not separate and combined_gain < -loss_cap and notes is not None:
            notes.add("hoh_capital_loss_1211")  # the lived-apart head of household (JF2.5)
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
            filing_status=sep_status,
            year=year,
            # A separate return assumes the spouses did not live apart all year unless recorded (JF2.5).
            mfs_lived_with_spouse=separate and not spouses_apart_all_year,
            knowledge_dir=knowledge_dir,
        )
        if married_7703 and not spouses_apart_all_year and notes is not None:
            notes.add("m7703_social_security")
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
            income.student_loan_interest_paid, magi_for_sli, sep_status, year, knowledge_dir
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
            notes.add("m7703_sli" if married_7703 else "sli_zero_mfs" if mfs else "sli_zero_phaseout")

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
    nonitemizer = 0   # JF9: IRC 170(p), set on the standard-deduction path below
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
    elif dual_status:
        # Pub 519 ch. 6, Restrictions for Dual-Status Taxpayers: "You cannot use the standard
        # deduction allowed on Form 1040 or 1040-SR. However, you can itemize any allowable
        # deductions." The Instructions for Form 1040-NR, Restrictions for Dual-Status Taxpayers:
        # "You can't take the standard deduction even for the part of the year you were a resident
        # alien."
        if deduction_mode == "standard":
            deduction = 0
            label = (
                "Less: itemized deductions (dual-status year — none claimed, so the spouse's separate return "
                "keeps the standard deduction: IRC 63(c)(6)(A))"
            )
        else:
            deduction = income.itemized_deductions or 0
            label = "Less: itemized deductions (dual-status year — no standard deduction: Pub 519 ch. 6)"
    else:
        sd = standard_deduction(status, year, knowledge_dir=knowledge_dir)
        citations.append(sd.citation)
        # JF9: IRC 170(p) rides with the standard deduction, so the method comparison is itemized vs
        # standard + the capped non-itemizer amount.
        cc = pack.charitable_contributions
        nonitemizer_cap = (min(income.charitable_cash_nonitemizer, cc.nonitemizer.cap.for_status(status))
                           if cc is not None and income.charitable_cash_nonitemizer else 0)
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
            nonitemizer = nonitemizer_cap
        elif income.itemized_deductions is not None:
            if income.itemized_deductions > sd.amount + nonitemizer_cap:
                deduction, label = income.itemized_deductions, "Less: itemized deductions"
            else:
                deduction, label = sd.amount, "Less: standard deduction"
                nonitemizer = nonitemizer_cap
        else:
            deduction, label = sd.amount, "Less: standard deduction"
            nonitemizer = nonitemizer_cap
        if notes is not None and income.charitable_cash_nonitemizer and cc is not None:
            notes.add("charitable_nonitemizer" if nonitemizer else "charitable_itemized_won")
    comp.append(_line("deduction", label=label, amount=-deduction))
    if nonitemizer:
        comp.append(_line(
            "nonitemizer_charitable_deduction", amount=-nonitemizer,
            label=f"Less: charitable contribution deduction for non-itemizers (Form 1040 line "
                  f"{form_line(year, 'f1040.charitable_nonitemizer', base_dir=knowledge_dir)}; IRC 170(p))"))

    # JF7: the Schedule 1-A deductions, below AGI and after the deduction (P.L. 119-21). MAGI is AGI: the
    # estimator models none of Schedule 1-A Part I's add-backs (Puerto Rico, Form 2555, Form 4563).
    sched1a_total = 0
    seniors = int(bool(income.senior_taxpayer)) + int(bool(income.senior_spouse) and status == "married_filing_jointly")
    if _schedule_1a_engaged(income, seniors) and pack_tax.obbba_schedule_1a is not None:
        s1a = schedule_1a_deductions(
            magi=agi, filing_status=status, year=year, qualified_tips=income.qualified_tips,
            qualified_overtime=income.qualified_overtime_premium, car_loan_interest=income.car_loan_interest,
            seniors_qualifying=seniors, knowledge_dir=knowledge_dir,
        )
        sched1a_total = s1a.total_deduction
        citations.append(s1a.citation)
        if notes is not None:
            notes.add("schedule_1a")
            if any(p.forfeited_reason for p in s1a.parts):
                notes.add("schedule_1a_forfeit")
        if sched1a_total:
            where = (f"Form 1040-NR line {form_line(year, 'f1040nr.sched_1a', base_dir=knowledge_dir)}" if nonresident
                     else f"Form 1040 line {form_line(year, 'f1040.sched_1a', base_dir=knowledge_dir)}")
            comp.append(_line("schedule_1a_deductions", label=f"Less: Schedule 1-A deductions ({where})",
                              amount=-sched1a_total))

    taxable = max(0, agi - deduction - sched1a_total - nonitemizer)
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
    # A dual-status year without the election is barred too — IRC 25A(g)(7): "If the taxpayer is a
    # nonresident alien individual for any portion of the taxable year, this section shall apply only
    # if such individual is treated as a resident alien ... by reason of an election under subsection
    # (g) or (h) of section 6013."
    aotc_refundable = 0
    edu_expenses = list(income.aotc_qualified_expenses)
    edu_rule = pack_tax.education_credits.ssn_requirement if pack_tax.education_credits is not None else None
    if edu_expenses and edu_rule is not None and not nonresident and not dual_status and status != _MFS:
        # JT1e (P-024): IRC 25A(g)(1) as amended — the filer's valid SSN (one spouse's on a joint return, the Form
        # 8863 instructions) and, for a dependent student, the student's. A student not known to meet it is left
        # out and NOT ESTIMATED; one known not to is left out.
        filer = income.education_ssn_taxpayer
        if status == _MFJ and edu_rule.one_spouse_suffices_on_joint_return:
            pair = (income.education_ssn_taxpayer, income.education_ssn_spouse)
            filer = True if True in pair else (None if None in pair else False)
        oks = _ssn_oks(income)
        if notes is not None:
            if filer is False:
                notes.add("edu_ssn_filer_missing")
            elif filer is None:
                notes.add("edu_ssn_filer_unknown")
            else:
                if False in oks:
                    notes.add("edu_ssn_student_missing")
                if None in oks:
                    notes.add("edu_ssn_student_unknown")
        edu_expenses = [e for e, ok in zip(edu_expenses, oks) if filer is True and ok is True]
    if (
        edu_expenses and not nonresident and not dual_status
        and pack_tax.education_credits is not None
    ):
        edu = education_credits(
            edu_expenses, 0, magi=agi, filing_status=sep_status, year=year,
            knowledge_dir=knowledge_dir,
        )
        if married_7703 and notes is not None:
            notes.add("m7703_education")
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
        if separate:
            if notes is not None:
                notes.add("m7703_dependent_care" if married_7703 else "dependent_care_mfs")
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
                employer_benefits=income.dependent_care_benefits,   # JT4a: W-2 box 10
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
    addmed_wage = 0   # JT1c: the wage part, Schedule 2 Section B (outside subtitle A) from 2026
    # JF3 (P-019): Form 8959 prices W-2 box 5, never box 1 when box 5 is known — an exempt F/J
    # student's box 5 is $0, and a 401(k) deferrer's box 5 is above box 1.
    medicare_wages = income.wages if income.medicare_wages is None else income.medicare_wages
    if (medicare_wages or income.self_employment_net) and pack_tax.additional_medicare_tax is not None:
        addmed = additional_medicare_tax(
            medicare_wages, sep_status, year, se_net_profit=income.self_employment_net, knowledge_dir=knowledge_dir
        )
        if addmed.additional_medicare_tax:
            if married_7703 and notes is not None:
                notes.add("m7703_addmed")
            addmed_amount = addmed.additional_medicare_tax
            addmed_wage = irs_round(addmed.wage_portion)
            citations.append(addmed.citation)
            comp.append(
                _line("additional_medicare_tax", 
                    label="Plus: Additional Medicare Tax (Form 8959, 0.9% over threshold)",
                    amount=addmed_amount,
                )
            )

    niit_amount = 0
    # The excluded deposit interest is not income, so it is not investment income either
    # (it is nonzero here only on a dual-status payee's return: a nonresident has no NIIT).
    investment_income = income.interest - deposit_excluded + income.dividends + capital
    # NRAs are generally not subject to NIIT (Form 8960 instructions).
    if niit_override is not None:
        niit_amount = niit_override.amount
        if niit_amount:
            citations.extend(niit_override.citations)
            comp.append(_line("niit", label=niit_override.label, amount=niit_amount))
    elif investment_income > 0 and not nonresident and pack_tax.niit is not None:
        niit_res = niit(investment_income, agi, sep_status, year, knowledge_dir=knowledge_dir)
        if niit_res.niit:
            if married_7703 and notes is not None:
                notes.add("m7703_niit")
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
            filing_status=sep_status,
            year=year,
            state="other",
            knowledge_dir=knowledge_dir,
        )
        if married_7703 and notes is not None:
            notes.add("m7703_ptc")
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

    # JR3c: Form 5329 -> Schedule 2 — the 72(t) additional tax and the 4973 excise.
    early_tax, early_keys = _early_distribution_tax(income.retirement_distributions)
    if notes is not None:
        notes.update(early_keys)
    if early_tax:
        comp.append(_line(
            "early_distribution_additional_tax", amount=early_tax,
            label=f"Plus: additional tax on early distributions (Form 5329 line "
                  f"{form_line(year, 'f5329.early_distribution_tax', base_dir=knowledge_dir)} -> Schedule 2 line "
                  f"{form_line(year, 'sched2.retirement_additional_tax', base_dir=knowledge_dir)})"))
    excise = (irs_round(_EXCESS_EXCISE_RATE * _capped_excess(income, "traditional"))
              + irs_round(_EXCESS_EXCISE_RATE * _capped_excess(income, "roth")))
    if excise:
        comp.append(_line(
            "ira_excess_contribution_excise", amount=excise,
            label=f"Plus: 6% excise on excess IRA contributions (Form 5329 lines "
                  f"{form_line(year, 'f5329.traditional_excess_tax', base_dir=knowledge_dir)}/"
                  f"{form_line(year, 'f5329.roth_excess_tax', base_dir=knowledge_dir)} -> Schedule 2 line "
                  f"{form_line(year, 'sched2.ira_excess_excise', base_dir=knowledge_dir)})"))
        if notes is not None and (
                (income.traditional_ira_excess and income.traditional_ira_dec31_value is None)
                or (income.roth_ira_excess and income.roth_ira_dec31_value is None)):
            notes.add("excise_uncapped")
    total_tax = (income_tax_after_credits + se_amount + addmed_amount + niit_amount + ptc_repayment
                 + early_tax + excise)
    comp.append(_line("total_tax", label="Total tax", amount=total_tax))

    # ── Payments and refundable credits ─────────────────────────────────────
    # Negative, like every other "Less:" composition line (they reduce what you owe).
    comp.append(_line("withholding", label="Less: federal tax withheld / payments", amount=-income.federal_withholding))
    payments = income.federal_withholding

    # JF3: Additional Medicare Tax withholding — box 6 less "your regular Medicare tax withholding on
    # Medicare wages" (1.45% of box 5); "If zero or less, enter -0-" (Form 8959, 2025). It goes with
    # federal income tax withholding on the 1040. Only the people who gave box 6 are in it.
    groups = medicare_withheld_groups if medicare_withheld_groups is not None else (
        [(list(income.medicare_tax_withheld), income.medicare_wages)]
        if income.medicare_tax_withheld and income.medicare_wages is not None else []
    )
    if groups:
        ess = pack_tax.employee_social_security
        rate = ess.medicare_rate if ess is not None else None
        if rate is None:
            if notes is not None:
                notes.add("addmed_withholding_not_priced")
        else:
            box6 = sum(sum(g[0]) for g in groups)
            box5 = sum(g[1] for g in groups)
            addmed_withheld = irs_round(max(Decimal(0), Decimal(box6) - Decimal(box5) * rate))
            if addmed_withheld:
                payments += addmed_withheld
                comp.append(_line(
                    "additional_medicare_withholding",
                    label=(
                        f"Less: Additional Medicare Tax withheld (Form 8959 Part "
                        f"{form_line(pack, 'f8959.withholding_part')}, with Form 1040 line "
                        f"{form_line(pack, 'f1040.additional_medicare_withholding')})"
                    ),
                    amount=-addmed_withheld,
                ))

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
    # A dual-status year without the election: IRC 32(c)(1)(D) — the eligible individual "shall
    # not include any individual who is a nonresident alien individual for any portion of the
    # taxable year" absent the §6013(g)/(h) election.
    eitc_cfg = getattr(credits_block, "earned_income_tax_credit", None) if credits_block is not None else None
    if eitc_cfg and not nonresident and not dual_status and not mfs and not married_for_eitc and earned > 0:
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
                        label=("Less: earned income tax credit (refundable, EIC Table)" if eitc_cfg.get("eic_table")
                               else "Less: earned income tax credit (refundable, formula approximation)"),
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

    # JT1c (P-023): Schedule 3-A (2026 draft) — the affected refundable credits over the total tax less
    # Schedule 2 Section B, the employment taxes outside subtitle A (here, the wage part of the Additional
    # Medicare Tax). Proposed Treas. Reg. 1.32-4(c)(2) sums the credits first, then takes the excess.
    fpb = 0
    fpb_cfg = pack.federal_public_benefit
    if fpb_cfg is not None:
        affected = -sum(ln.amount for ln in comp if ln.slot in fpb_cfg.affected_credits)
        fpb = max(0, affected - max(0, total_tax - addmed_wage))

    bottom = payments - total_tax
    comp.append(_line("bottom_line", label=_BOTTOM_LINE_LABEL, amount=bottom))
    _reconcile(bottom, comp)
    return BottomLineResult(bottom=bottom, lines=comp, citations=citations, federal_public_benefit=fpb)


# JT1c (P-023): the status answer, read off the profile. A recorded qualified_alien_status decides; otherwise
# us_person True (a citizen or green-card holder, its own definition) is a Yes, and the latest visa-timeline
# status is read against 8 U.S.C. 1641 — a T status is 1641(c)(4), any other nonimmigrant class is on neither list.
_PRWORA_QUALIFIED = frozenset({
    "us_citizen", "us_national", "lpr", "asylee", "refugee", "parolee_1yr", "deportation_withheld",
    "conditional_entrant", "cuban_haitian_entrant", "cofa_resident"})
_PRWORA_1641C = frozenset({"battered_alien", "t_nonimmigrant"})
_T_STATUS_RE = re.compile(r"^T-?[1-6]\b")
_NONIMMIGRANT_RE = re.compile(r"^(?:[A-SUV]-?\d|TN\b|TD\b)")
_LPR_STATUS_RE = re.compile(r"^(?:LPR\b|GREEN[ _-]?CARD|(?:LAWFUL[ _])?PERMANENT[ _]RESIDENT)")


class _Prwora(BaseModel):
    """One person's Schedule 3-A answer as the profile reads (JT1c). kind: qualified / c_only (a 1641(c)
    category) / not_listed (a status on neither list) / unknown."""

    kind: Literal["qualified", "c_only", "not_listed", "unknown"]
    why: str


def _prwora_person(answer, us_person, immigration, pos: str) -> _Prwora:
    """``pos`` is the possessive the disclosure uses ('your' / "your spouse's")."""
    if answer is not None and answer.value is not None:
        value = str(answer.value)
        if value in _PRWORA_QUALIFIED:
            return _Prwora(kind="qualified", why=f"{pos} qualified_alien_status is '{value}'")
        if value in _PRWORA_1641C:
            return _Prwora(kind="c_only", why=(
                f"{pos} qualified_alien_status is '{value}', an 8 U.S.C. 1641(c) category — the statute counts it "
                f"(\"For purposes of this chapter, the term 'qualified alien' includes\"), but the proposed rule's "
                f"definition cites 1641(b) only, and the Schedule 3-A instructions are not posted"))
        return _Prwora(kind="not_listed", why=f"{pos} qualified_alien_status is 'none_of_these'")
    if us_person is not None and us_person.value is True:
        return _Prwora(kind="qualified", why=f"{pos} us_person answer is True (a U.S. citizen or green-card holder)")
    periods = list(immigration.visa_timeline) if immigration is not None else []
    if periods:
        latest = max(periods, key=lambda p: p.start).status.strip().upper()
        if _LPR_STATUS_RE.match(latest):
            return _Prwora(kind="qualified", why=f"{pos} latest recorded status is '{latest}' (8 U.S.C. 1641(b)(1))")
        if _T_STATUS_RE.match(latest):
            return _Prwora(kind="c_only", why=(
                f"{pos} latest recorded status is '{latest}', T nonimmigrant status — 8 U.S.C. 1641(c)(4) counts it, "
                f"but the proposed rule's definition cites 1641(b) only"))
        if _NONIMMIGRANT_RE.match(latest):
            return _Prwora(kind="not_listed", why=(
                f"{pos} latest recorded status is '{latest}', a nonimmigrant status on neither 8 U.S.C. 1641(b) "
                f"nor (c) — unless it changes before you file"))
    return _Prwora(kind="unknown", why=f"{pos} status as a U.S. citizen, U.S. national or qualified alien is not recorded")


def _prwora_view(profile: Profile) -> tuple[_Prwora, _Prwora | None]:
    """(taxpayer, spouse) — the spouse only when the profile records one."""
    ident = profile.identity
    tp = _prwora_person(
        ident.qualified_alien_status if ident is not None else None,
        ident.us_person if ident is not None else None, profile.immigration, "your")
    spouse = profile.household.spouse if profile.household is not None else None
    sp = None if spouse is None else _prwora_person(
        spouse.qualified_alien_status, spouse.us_person, spouse.immigration, "your spouse's")
    return tp, sp


def _public_benefit_lost(status: str, result: BottomLineResult, tp: _Prwora, sp: _Prwora | None) -> tuple[int, str]:
    """(the Schedule 3-A amount this reading of the profile forfeits on one candidate, the answer it rests on)
    (JT1c). A joint return keeps it when EITHER spouse qualifies (proposed 1.32-4(b)(4)); a separate return is
    its own filer's; the two-return MFS pair adds the spouse's separate return with the spouse's own answer.
    The answer is 'unknown' when any forfeiting person is unrecorded, else 'c_only', else 'not_listed'."""
    if status == _MFJ:
        people = [p for p in (tp, sp) if p is not None]
        if any(p.kind == "qualified" for p in people):
            return 0, "qualified"
        forfeiting = [(result.federal_public_benefit, people)]
    else:
        forfeiting = [(result.federal_public_benefit, [tp])]
        if sp is not None:
            forfeiting.append((result.spouse_federal_public_benefit, [sp]))
    lost, kinds = 0, set()
    for amount, people in forfeiting:
        if amount and all(p.kind != "qualified" for p in people):
            lost += amount
            kinds.update(p.kind for p in people)
    kind = next((k for k in ("unknown", "c_only", "not_listed") if k in kinds), "qualified")
    return lost, kind


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
    married = _married_for_year(profile, year)   # the year of a spouse's death included (JF1b.9)
    state = _election_state(profile, year)
    residency_result = state.residency_result
    election_implied = state.implied
    own_classification = state.own_classification
    election = state.election
    classification = residency_result.classification if residency_result is not None else None
    nonresident = classification == "nonresident"
    # JF5b (P-018): a dual-status year with no §6013(g)/(h) election (under the election the
    # classification is 'resident') is priced under Pub 519 ch. 6's restrictions for the point.
    dual = classification == "dual_status_candidate"
    # The election reaches chapter 1 and chapter 24 only (IRC 6013(g)(1)), so the FICA
    # disclosure keeps following the day-count answer.
    fica_nonresident = (
        residency_result.classification_without_election if election else classification
    ) == "nonresident"

    # JF5b part 3b (P-018): the election as a CANDIDATE for a nonresident or dual-status
    # TAXPAYER — married, no status confirmed, no answer recorded, and the election not ruled
    # out (IRC 6013(g)(3)): the joint figure it opens is priced on RESIDENT rules for both
    # spouses behind the no-election married-filing-separately primary, as the reverse couple's.
    election_candidate = (
        married and _confirmed_status(profile) is None and not election and not state.declined
        and not state.unavailable and classification in ("nonresident", "dual_status_candidate")
    )
    # JF1b.10 (P-018): head of household as a CANDIDATE for a citizen or resident whose spouse is,
    # or may be, a nonresident alien — no election recorded, none declined (the decline is the
    # no-joint path): Pub 501, Considered Unmarried (_candidate_statuses). It exists only WITHOUT the
    # election and rests on the nonresident-spouse rule, so it is priced on that route (below).
    nra_hoh_candidate = (
        married and not election and not state.no_joint and _confirmed_status(profile) is None
        and classification not in ("nonresident", "dual_status_candidate")
        and _spouse_nra_direction(profile, year) is not None
    )
    statuses, status_assumed = _candidate_statuses(
        profile, classification, year, no_joint=state.no_joint, election_candidate=election_candidate,
        nra_spouse_hoh=nra_hoh_candidate,
    )
    if state.joint_blocked:
        # P-018: a confirmed joint status the facts rule out (a recorded decline with a
        # nonresident in the couple, or neither spouse a U.S. citizen or resident) is
        # never priced as a joint return under nonresident rules, nor under an election
        # the facts refuse — it is priced married-filing-separately, named FIRST below.
        statuses = [_MFS]
    deps = _dependent_infos(profile, year)
    income = _with_senior_flags(profile, year, income)   # JF7: Schedule 1-A Part V, from DOB and tax ID
    income = _with_education_ssn(profile, income)        # JT1e: the 2026 education-credit SSN rule
    # JR3b: each person's 2b-checked IRA items priced through Form 8606 Part I with THEIR OWN pool, before any
    # joint view can concatenate them.
    income = _resolve_ira_pool(income, year, knowledge_dir, "taxpayer")
    if income.spouse is not None:
        income = income.model_copy(update={"spouse": _resolve_ira_pool(income.spouse, year, knowledge_dir, "spouse")})
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
    # JF5b part 3b (P-018): the SPOUSE's own dual-status year (no election) prices the spouse's
    # separate return under Pub 519 ch. 6's restrictions at the point (_bottom_line(dual_status=True):
    # no standard deduction, no EITC or education credit, married-filing-separately rates), the
    # recorded decline's assumed reading included — a spouse who is a nonresident alien for part
    # of the year is the nonresident that reading rests on; the range prices the full-year resident
    # and the full-year nonresident readings of that return.
    spouse_dual_point = spouse_split and spouse_dual_status
    spouse_nonresident = spouse_split and spouse_nra_reading and not spouse_dual_point
    spouse_mfs_return = spouse_split and _MFS in statuses
    # JF5b (P-018, P-013 rule (e)): the SPOUSE's own dual-status year (no election — the
    # direction is None under it) splits the spouse's deposit interest on every separate
    # return priced for the spouse, the assumed nonresident reading included: only the
    # recorded nonresident-period subset is excluded (Treas. Reg. 1.871-13(a)(1)) — except the
    # full-year RESIDENT reading in the range, which has no nonresident part (JF5b part 3b).
    spouse_period_rule = spouse_split and spouse_dual_status
    # A married filer's head of household (Pub 501, Considered Unmarried) comes by one of two
    # routes. The NONRESIDENT-SPOUSE route (spouse_nra_reading) — the spouse's return on Form
    # 1040-NR rules, and the filer "may still be considered married for purposes of the earned
    # income credit (EIC)" (Pub 519 ch. 5; the separated-spouse rule is not modeled), so no
    # EITC, with or without a spouse snapshot, and the couple's one deduction method (the
    # literal IRC 63(c)(6)(A) reading). The LIVED-APART route ("Your spouse didn't live in your
    # home during the last 6 months of the tax year") — a resident spouse and a free deduction
    # method (Pub 501); for the EITC the separated-spouse rule needs a qualifying child, so a
    # lived-apart figure with none computes no EITC either.
    # The head-of-household CANDIDATE with no election recorded (JF1b.10) rests on the nonresident-spouse
    # rule, so a spouse of unknown residency is read as the nonresident it needs. On that route the
    # filer is still married outside the filing-status subsection (IRC 2(b)(2)(B): "For purposes of
    # this subsection"), so the return carries _bottom_line(married_7703=True).
    hoh_spouse_nra = spouse_nra_reading or nra_hoh_candidate
    eitc_qualifying_child = any(a is not None and 0 <= a < 19 and ssn is True for a, ssn in deps)
    # The separated-spouse rule (IRC 32(d)(2)) starts in TY2021; before it a lived-apart HOH was
    # unmarried for the EITC under IRC 7703(b), so the qualifying-child gate is year-bound.
    lived_apart_no_eitc = year >= 2021 and not eitc_qualifying_child
    # JF2.5: the spouses lived apart at ALL times (IRC 86(c)(1)(C)(ii)) — recorded, never assumed.
    apart_all_year = married and profile.household is not None and _confirmed_true(
        profile.household.spouses_lived_apart_all_year)
    notes: set[str] = set()  # disclosure keys accumulated across every candidate status
    mfs_method: dict[str, str | None] = {}  # the couple's deduction method on the two-return MFS pair

    def _mfs_pair(
        spouse_nra: bool, self_status: str = _MFS, *, lived_apart_hoh: bool = False, married_for_eitc: bool = False,
        self_nra: bool | None = None, self_dual: bool | None = None, niit_zero: tuple[int, ...] = (),
        spouse_dual: bool | None = None, spouse_period: bool | None = None, married_7703: bool = False,
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
        nonresident-spouse route, Pub 519 ch. 5), so no EITC on that return. ``married_7703``: the
        same route's other married-filing-separately rules on your return (JF1b.10, _bottom_line).
        ``self_nra``: the rules YOUR return runs under (None = your classification) —
        False prices the resident reading of a nonresident answer that may flip (JF5b).
        ``self_dual``: your return runs under the dual-status restrictions (None = your
        classification) — False prices the full-year-resident reading of a dual-status year.
        The spouse's return keeps its own deposit rule (``spouse_period_rule``) on every reading.
        ``niit_zero`` (JF5b part 3a): the returns (0 yours, 1 the spouse's) priced with NIIT $0 —
        the spouse who is a nonresident without the §6013 election, Treas. Reg.
        1.1411-2(a)(2)(iii)(A).
        ``spouse_dual`` (JF5b part 3b): the spouse's return runs under Pub 519 ch. 6's dual-status
        restrictions (None = the spouse's own dual-status year, ``spouse_dual_point``) — it wins
        over ``spouse_nra``, which then drives only the head-of-household route; False prices the
        full-year readings. ``spouse_period``: the spouse's nonresident-period deposit rule (None =
        ``spouse_period_rule``; False for the full-year RESIDENT reading, which has no such part).
        """
        self_income = income.model_copy(update={"spouse": None})
        self_nra = nonresident if self_nra is None else self_nra
        self_dual = dual if self_dual is None else self_dual
        spouse_dual = spouse_dual_point if spouse_dual is None else spouse_dual
        spouse_nra = spouse_nra and not spouse_dual
        spouse_period = spouse_period_rule if spouse_period is None else spouse_period

        def _run(self_mode: str | None, spouse_mode: str | None):
            local: set[str] = set()
            rs = _bottom_line(
                self_income, self_status, year, knowledge_dir, nonresident=self_nra, deps=deps, notes=local,
                deduction_mode=self_mode, married_for_eitc=married_for_eitc, dual_status=self_dual,
                niit_override=_NIIT_ZERO if 0 in niit_zero else None, married_7703=married_7703,
                married_separate=True, spouses_apart_all_year=apart_all_year,
            )
            rp = _bottom_line(
                income.spouse, _MFS, year, knowledge_dir, nonresident=spouse_nra, deps=[], notes=local,
                deduction_mode=spouse_mode, nonresident_period_deposit=spouse_period, dual_status=spouse_dual,
                niit_override=_NIIT_ZERO if 1 in niit_zero else None, spouses_apart_all_year=apart_all_year,
            )
            return rs, rp, local

        # Two returns with no standard deduction (a nonresident's, IRC 63(c)(6)(B), or a
        # dual-status year's, Pub 519 ch. 6) have none to lose, so the method is weighed only
        # when at least one return is a full-year resident's.
        if (not (self_nra or self_dual) or not (spouse_nra or spouse_dual)) and any(
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
        result = BottomLineResult(
            bottom=total, lines=comp, citations=[*res_self.citations, *res_spouse.citations],
            federal_public_benefit=res_self.federal_public_benefit,
            spouse_federal_public_benefit=res_spouse.federal_public_benefit,
        )
        return result, method, local

    def _outcome(
        status: str, *, self_nra: bool | None = None, self_dual: bool | None = None, record: bool = True,
        niit_override: _NiitOverride | None = None, niit_zero: tuple[int, ...] = (),
    ) -> BottomLineResult:
        """One candidate's figure. ``self_nra`` / ``self_dual`` override the rules YOUR return
        runs under (None = your classification); ``record`` False prices a bracketing reading
        with no side effects on the disclosure keys or the deduction method shown (JF5b).
        ``niit_override`` prices a JOINT figure's NIIT as given, ``niit_zero`` the named returns
        of a two-return MFS pair at NIIT $0 (JF5b part 3a: the §6013 NIIT default)."""
        self_nra = nonresident if self_nra is None else self_nra
        self_dual = dual if self_dual is None else self_dual
        if status == _MFJ and election_candidate:
            # JF5b part 3b: the joint candidate exists only under the §6013(g)/(h) election, which
            # treats both spouses as residents for the whole year — resident rules, never 1040-NR's.
            self_nra = self_dual = False
        sink = notes if record else None
        if spouse_split:
            if status == _MFS:
                result, method, local = _mfs_pair(
                    spouse_nonresident, self_nra=self_nra, self_dual=self_dual, niit_zero=niit_zero,
                )
                if record:
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
                    married_for_eitc=hoh_spouse_nra or lived_apart_no_eitc, self_nra=self_nra, self_dual=self_dual,
                    married_7703=hoh_spouse_nra,
                )
                if record:
                    notes.update(local)
                    mfs_method["hoh_method"] = method
                return result
            # Combined (joint) return: income is summed, but the per-PERSON pieces —
            # the excess-SS credit and Schedule SE — are computed per spouse. (A dual-status
            # year has no joint return without the election, so self_dual is False here.)
            return _bottom_line(
                income.combined_with_spouse(), status, year, knowledge_dir, nonresident=self_nra, deps=deps,
                dual_status=self_dual, niit_override=niit_override,
                ss_withheld_groups=[
                    list(income.ss_withheld_by_employer),
                    list(income.spouse.ss_withheld_by_employer),
                ],
                se_persons=[
                    (income.self_employment_net, income.wages),
                    (income.spouse.self_employment_net, income.spouse.wages),
                ],
                se_ss_wages=[income.ss_wages, income.spouse.ss_wages],
                medicare_withheld_groups=[
                    (list(p.medicare_tax_withheld), p.medicare_wages)
                    for p in (income, income.spouse) if p.medicare_tax_withheld and p.medicare_wages is not None
                ],
                notes=sink,
            )
        # A married head of household with no spouse snapshot: the same EITC rule (above).
        married_hoh = status == "head_of_household" and married and not election
        return _bottom_line(
            income, status, year, knowledge_dir, nonresident=self_nra, deps=deps, notes=sink,
            married_for_eitc=married_hoh and (hoh_spouse_nra or lived_apart_no_eitc), dual_status=self_dual,
            married_7703=married_hoh and hoh_spouse_nra, married_separate=married_hoh,
            spouses_apart_all_year=married and apart_all_year,
        )

    # The ELECTION posture: every figure under the election, or the joint candidate of a
    # couple whose spouse's own facts classify nonresident (that joint return, too,
    # exists only under the election) — or whose TAXPAYER's do (JF5b part 3b).
    election_figures = election or (_MFJ in statuses and (spouse_nonresident or election_candidate))
    # JF5b part 3a (P-018): the chapter-1 election does not reach NIIT (chapter 2A), so an
    # election figure's NIIT is the Treas. Reg. 1.1411-2(a)(2)(iii)(A) / (iv)(A) DEFAULT —
    # each spouse's own snapshot under the married-filing-separately rules against $125,000,
    # the spouse who is a nonresident without the election at $0 under (iii) — unless the
    # couple makes the second election (combined income against $250,000), which (iii)(B)(2)
    # opens only in the first year the U.S. spouse is subject on their own figures. Priced
    # only with a spouse snapshot: one combined snapshot cannot be split (the note names
    # income.spouse). _price_niit decides the point and the range per reading.
    niit_priced: _NiitPriced | None = None
    niit_citations: tuple[Citation, ...] = ()
    # A default exists only for a couple that can hold a nonresident or an arriving spouse (no
    # U.S.-person / full-year-resident pair), and the gate reads the PRICED amounts — a raw
    # income sum misses a capital loss capped on the return.
    possible_nra = any(c in ("nonresident", "dual_status_candidate", None)
                       for c in (state.taxpayer_6013, state.spouse_6013))
    if election_figures and spouse_split and possible_nra:
        own_niit = tuple(
            next((ln.amount for ln in _bottom_line(snap, _MFS, year, knowledge_dir).lines if ln.slot == "niit"), 0)
            for snap in (income.model_copy(update={"spouse": None}), income.spouse)
        )
        elected_niit = (
            next((ln.amount for ln in _outcome(_MFJ, record=False).lines if ln.slot == "niit"), 0)
            if _MFJ in statuses else None
        )
        if any(own_niit) or elected_niit:
            niit_priced = _price_niit(
                state.kind, (state.taxpayer_6013, state.spouse_6013), own_niit, elected_niit,
                separate=election and _MFS in statuses,
            )
            if not niit_priced.readings:
                niit_priced = None
        niit_params = load_knowledge("federal", year, base_dir=knowledge_dir).tax.niit
        niit_citations = (niit_params.citation,) if niit_params is not None else ()

    def _joint_niit(amount: int) -> _NiitOverride | None:
        """The joint figure priced with ``amount`` of NIIT (None: its own combined-income NIIT)."""
        if niit_priced is None or amount == niit_priced.elected:
            return None
        return _NiitOverride(amount, citations=niit_citations)

    outcomes = {
        s: _outcome(
            s,
            niit_override=_joint_niit(niit_priced.point) if s == _MFJ and niit_priced is not None else None,
            niit_zero=niit_priced.separate_zero if s == _MFS and niit_priced is not None else (),
        )
        for s in statuses
    }
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
    # JF5b part 3a: every other NIIT amount a reading of the §6013 default can reach bounds the
    # range — on the joint figure (the second election's combined-income figure, the default's
    # ends) and on the separate returns (the spouse who is a nonresident without the election at
    # $0, or at the resident-rules figure a continuing chapter-2A election might carry).
    niit_alternatives: list[tuple[str, int]] = []  # (status, bottom line)
    if niit_priced is not None:
        if _MFJ in priced:
            niit_alternatives.extend(
                (_MFJ, _outcome(_MFJ, niit_override=_joint_niit(x), record=False).bottom)
                for x in niit_priced.reach if x != niit_priced.point
            )
        if _MFS in priced and niit_priced.separate_zero:
            niit_alternatives.append((_MFS, _outcome(_MFS, record=False).bottom))
        if _MFS in priced:
            niit_alternatives.extend(
                (_MFS, _outcome(_MFS, niit_zero=(side,), record=False).bottom)
                for side in niit_priced.separate_bracket
            )
        values.extend(v for _, v in niit_alternatives)
    # A spouse whose residency is not settled (a declared non-US person with no facts
    # that classify them, or a dual-status year) has the separate return computed under
    # RESIDENT rules — never the taxpayer's borrowed flag — and the range brackets the
    # other reading: the same pair with the spouse on Form 1040-NR rules (P-018).
    spouse_nra_alternative: int | None = None
    spouse_resident_alternative: int | None = None   # JF5b part 3b: a dual-status spouse's full-year resident reading
    if spouse_mfs_return and spouse_direction == "conditional" and spouse_dual_point:
        # JF5b part 3b: the point is the spouse's dual-status return (Pub 519 ch. 6); the range prices the
        # full-year resident reading (a resident from January 1 — the spouse's prior year is not recorded) and
        # the full-year nonresident one (Form 1040-NR — the timeline's dates wrong).
        spouse_resident_alternative = _mfs_pair(False, spouse_dual=False, spouse_period=False)[0].bottom
        spouse_nra_alternative = _mfs_pair(True, spouse_dual=False)[0].bottom
        values.extend((spouse_resident_alternative, spouse_nra_alternative))
    elif spouse_mfs_return and spouse_direction == "conditional":
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
                married_for_eitc=alt_nra or lived_apart_no_eitc, married_7703=alt_nra,
            )[0].bottom
        else:
            hoh_alternative = _bottom_line(
                income, "head_of_household", year, knowledge_dir, nonresident=nonresident, deps=deps,
                married_for_eitc=alt_nra or lived_apart_no_eitc, married_7703=alt_nra, married_separate=True,
                spouses_apart_all_year=apart_all_year,
            ).bottom
        values.append(hoh_alternative)
    # JF5b (items 1 and 6): a nonresident answer that is not settled — one that rests on a
    # missing lookback year real presence could flip (classify's nonresident_may_flip, its
    # "may be WRONG" reason), or one that contradicts a recorded prior-year residency (the
    # CONTRADICTION reason) — is priced on Form 1040-NR rules for the point, and the range
    # ALSO prices the same inputs under RESIDENT rules for the whole year: the reading in
    # which it flips. The law does not say which way that moves the bottom line (worldwide
    # income, NIIT and the lost deposit exclusion against the standard deduction), so it is
    # a bracket, never assumed to be the high end.
    tp_contradiction = residency.prior_year_contradiction(residency_result) if residency_result is not None else None
    tp_flip_reason = residency.may_flip_reason(residency_result) if residency_result is not None else None
    resident_reading: int | None = None
    if nonresident and (tp_contradiction is not None or tp_flip_reason is not None):
        resident_reading = _outcome(primary, self_nra=False, record=False).bottom
        values.append(resident_reading)
    # The same for the SPOUSE's own nonresident answer that may flip (the spouse has no
    # prior-year fact): the two-return MFS pair also prices the spouse's separate return
    # under resident rules. A spouse whose residency is not settled at all is bracketed
    # above (spouse_nra_alternative, the 'conditional' direction) — never both.
    spouse_result = _spouse_own_result(profile, year) if spouse_direction is not None else None
    spouse_flip_reason = residency.may_flip_reason(spouse_result) if spouse_result is not None else None
    spouse_flip_alternative: int | None = None
    if spouse_flip_reason is not None and spouse_mfs_return and spouse_nonresident:
        spouse_flip_alternative = _mfs_pair(False)[0].bottom
        values.append(spouse_flip_alternative)
    # JF5b.2 (P-018): a dual-status year's point prices Pub 519 ch. 6's restrictions; the same
    # inputs under resident rules for the whole year (the standard deduction and the credits)
    # are the range's other end — only where a route could make that figure lawful
    # (_dual_status_routes): a prior-year residency not ruled out, or the election open to a
    # married filer. A recorded Form 1040-NR for the prior year and no spouse (or a recorded
    # decline) leave no route, and the range is the point alone.
    # JF5b part 3b: with the election's JOINT figure priced as its own candidate (election_candidate),
    # route (ii) points at that figure — the same status under resident rules then needs route (i).
    dual_routes = _dual_status_routes(profile, year, declined=state.declined) if dual else None
    dual_unrestricted = _outcome(primary, self_dual=False, record=False) if dual else None
    dual_resident_reading: int | None = None
    if dual_routes is not None and dual_routes.resident_figure_open(joint_candidate=election_candidate):
        dual_resident_reading = dual_unrestricted.bottom
        values.append(dual_resident_reading)
        # Every candidate status's full-year-resident figure bounds the range, not only the primary's.
        # ...except the MFJ election candidate: it is already priced on resident rules, with its
        # NIIT default (route (ii) is its own figure).
        values.extend(_outcome(s, self_dual=False, record=False).bottom for s in statuses
                      if s != primary and not (s == _MFJ and election_candidate))
    # JT1c (P-023): Schedule 3-A — the refunded portion a household that is not a U.S. citizen, U.S. national or
    # qualified alien may not receive bounds the LOW end: the rule is proposed, and the answer is the one on the
    # date the return is filed.
    prwora_tp, prwora_sp = _prwora_view(profile)
    public_benefit: dict[str, tuple[int, str]] = {}
    for s, res in priced.items():
        if res.federal_public_benefit or res.spouse_federal_public_benefit:
            public_benefit[s] = _public_benefit_lost(s, res, prwora_tp, prwora_sp)
    public_benefit_bracketed = any(lost for lost, _ in public_benefit.values())
    values.extend(priced[s].bottom - lost for s, (lost, _) in public_benefit.items() if lost)
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
    # JF5b: a residency reading (a flip, a CONTRADICTION, an unsettled spouse) keeps a range of its
    # own, so confirming the status alone does not collapse it.
    residency_bracketed = any(v is not None for v in (
        resident_reading, spouse_flip_alternative, spouse_nra_alternative, hoh_alternative, dual_resident_reading,
        spouse_resident_alternative))
    # JF5b part 3a: so does a reading of the §6013 NIIT default (its own note names it).
    niit_bracketed = any(v != outcomes[s].bottom for s, v in niit_alternatives)
    if status_assumed:
        kept = " and ".join(part for part, on in (
            ("the residency reading named in these notes", residency_bracketed),
            ("the NIIT default under the §6013 election (its note)", niit_bracketed),
            ("the Schedule 3-A federal public benefit (its note)", public_benefit_bracketed),
        ) if on)
        assumptions.append(
            f"Filing status not confirmed — showing the range across {', '.join(statuses)}. "
            + (f"Confirming your status narrows it; {kept} may keep a range of its own."
               if kept else "Confirm your status to get a single number.")
        )
    elif state.joint_blocked:
        assumptions.append(
            f"Filing status: {primary} — priced in place of the confirmed married_filing_jointly, which these "
            "facts rule out (see the first note)."
        )
    else:
        assumptions.append(f"Filing status: {primary}.")
    if income.itemized_deductions is None and not nonresident and not dual:
        # A dual-status point takes none (Pub 519 ch. 6 — the dual-status caveat says so).
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
            f"Nonresident aliens cannot take the standard deduction: Form 1040-NR line "
            f"{form_line(year, 'f1040nr.itemized', base_dir=knowledge_dir)} is "
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
            self_nonresident=nonresident, spouse_nonresident=spouse_nonresident, self_dual=dual,
            spouse_dual=spouse_dual_point,
        ))
    if "head_of_household" in outcomes and married and not election:
        assumptions.append(_hoh_pair_note(
            spouse_nra=hoh_spouse_nra, weighed=mfs_method.get("hoh_method") is not None,
            unsettled=spouse_direction == "conditional", alternative=hoh_alternative, snapshot=spouse_split,
            taxpayer_nonresident=classification in ("nonresident", "dual_status_candidate"),
            eitc_child=not lived_apart_no_eitc, spouse_dual=spouse_dual_point, candidate=nra_hoh_candidate,
        ))
    if spouse_mfs_return and (nonresident != spouse_nonresident or spouse_dual_point):
        # P-018: the spouse's separate return ran under the spouse's OWN rules — say which (a
        # dual-status spouse's: Pub 519 ch. 6 at the point, JF5b part 3b).
        assumptions.append(_spouse_separate_return_note(
            profile, year, spouse_nonresident=spouse_nonresident, income=income.spouse, deduction_method=method,
            assumed=spouse_nra_assumed, dual_status=spouse_dual_status, dual_point=spouse_dual_point,
        ))
    if spouse_resident_alternative is not None:
        # JF5b part 3b: the dual-status spouse's two full-year readings.
        assumptions.append(
            "The spouse's own facts show a DUAL-STATUS year, so the point prices the spouse's separate return under "
            "Pub 519 ch. 6's restrictions (see the spouse's separate-return note), and the range ALSO prices it for "
            "the whole year under RESIDENT rules (Form 1040: the standard deduction, the regular and preferential "
            f"rates, deposit interest taxed in full) — married-filing-separately would then total "
            f"{_signed_dollars(spouse_resident_alternative)} — and under NONRESIDENT rules (Form 1040-NR: no "
            "standard deduction, ordinary rates, the IRC 871(i)(2)(A) exclusion only for the deposit interest "
            "recorded as received before the residency starting date) — "
            f"{_signed_dollars(spouse_nra_alternative)} (+ refund / - owed). The resident reading is lawful if your "
            f"spouse was a U.S. resident during any part of {year - 1} (Pub 519 ch. 1: \"you will be considered a U.S. "
            "resident at the beginning of the current year\" — the spouse's prior-year return is not a recorded "
            "fact here), the nonresident one only if the dates on the spouse's visa timeline are wrong. Record the "
            "spouse's visa timeline and days in the US to settle it."
        )
    elif spouse_nra_alternative is not None:
        if spouse_nra_assumed:
            reading = (
                "NONRESIDENT rules (Form 1040-NR) for the point estimate — the reading the recorded decline rests "
                "on, since a joint return is ruled out only when a spouse is a nonresident alien — and the range "
                "ALSO prices it under RESIDENT rules (Form 1040: the standard deduction, the regular and "
                "preferential rates, deposit interest taxed"
                + (" except the part recorded as received before the residency starting date" if spouse_period_rule
                   else "") + ")"
            )
        else:
            reading = (
                "RESIDENT rules for the point estimate — never by borrowing your classification — and the range "
                "ALSO prices it under NONRESIDENT rules (Form 1040-NR: no standard deduction, ordinary rates, the "
                + ("IRC 871(i)(2)(A) exclusion only for the deposit interest recorded as received before the residency "
                   "starting date" if spouse_period_rule else "IRC 871(i)(2)(A) deposit-interest exclusion") + ")"
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
    spouse_hoh_nra_return = (
        spouse_split and "head_of_household" in statuses and hoh_spouse_nra and not election and not spouse_dual_point)
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
    # A dual-status spouse's separate return excludes only the nonresident-period subset, on
    # any reading (JF5b.3): its own note below (_dual_deposit_note), never this one.
    spouse_excludes = spouse_nra_return and not spouse_period_rule
    excluded_snapshots = ([income] if primary_excludes else []) + ([income.spouse] if spouse_excludes else [])
    deposit_total = sum(snap.bank_deposit_interest for snap in excluded_snapshots)
    uncharacterized_interest = sum(snap.interest - snap.bank_deposit_interest for snap in excluded_snapshots)
    # A JOINT return taxes BOTH spouses' interest whatever either one's residency, and so
    # does every return under the election; those disclosures name the household amounts.
    joint_snapshots = [income] + ([income.spouse] if spouse_split else [])
    joint_deposit = sum(snap.bank_deposit_interest for snap in joint_snapshots)
    joint_uncharacterized = sum(snap.interest - snap.bank_deposit_interest for snap in joint_snapshots)
    # (election_figures, above: the ELECTION posture.) Its figures tax the interest whatever
    # its character — and so does every joint figure of a nonresident: the MFJ gate taxes the interest there
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
            "decline rests on (the spouse's residency is not on file)"
        )
        assumptions.append(
            f"US bank-deposit interest of ${deposit_total:,} was EXCLUDED from income{where}: IRC 871(i)(1) "
            f"imposes no 30% tax on 871(i)(2)(A) 'interest on deposits, if such interest is not "
            f"effectively connected with the conduct of a trade or business within the United States' "
            f"('deposits' per 871(i)(3): deposits with persons carrying on the banking business, "
            f"deposits or withdrawable accounts with savings institutions, and amounts held by an "
            f"insurance company under an agreement to pay interest); Pub 519 ch. 3 (Exclusions From "
            f"Gross Income — Interest Income) excludes it from gross income, and the Instructions for "
            f"Form 1040-NR (Exception 3 under line "
            f"{form_line(year, 'f1040nr.taxable_interest', base_dir=knowledge_dir)}) say not to report it "
            f"there. The exclusion is "
            f"conditioned on the CHARACTER you entered — confirm the payer is a bank, savings "
            f"institution or insurance company and the account is not part of a US trade or business. "
            f"It ENDS if a §6013(g)/(h) election treats you as a resident (the election, not the "
            f"marriage, makes the interest taxable)."
        )
    spouse_deposit_taxed = (
        income.spouse.bank_deposit_interest
        if spouse_mfs_return and not spouse_nonresident and not election and not spouse_period_rule
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
    if not nonresident and not dual and declared_non_us_person and classification != "resident":
        # P-013 rule (b)'s "taxed and SAID to be" shape for the primary: a filer who
        # DECLARES they are not a US person but whose residency is not established (no
        # visa timeline/day counts that classify it) is taxed on a characterized amount,
        # and the note says why instead of leaving the field silently inert. A dual-status
        # year has its own note (JF5b.3, below — for us_person False or unanswered alike).
        # A resident (or a profile with no identity facts) keeps the resident control: the
        # field changes nothing and says nothing.
        # The spouse's separate return has its own note when it runs on its own rules.
        entered_deposit = income.bank_deposit_interest + (
            income.spouse.bank_deposit_interest
            if spouse_split and not (spouse_nra_return or spouse_period_rule) else 0
        )
        if entered_deposit > 0:
            assumptions.append(
                f"${entered_deposit:,} of bank_deposit_interest was taxed as ordinary interest: the IRC "
                f"871(i)(2)(A) deposit-interest exclusion applies to a NONRESIDENT alien (in a dual-status year, "
                f"to the part received before the residency starting date — bank_deposit_interest_nonresident_period), "
                f"and this profile's residency is not established (record the visa timeline and days in the US "
                f"to classify it)."
            )
    # JF5b.3 (P-013, P-018): a dual-status payee's deposit interest splits at the residency
    # starting date (Treas. Reg. 1.871-13(a)(1)) — the note names the dollars excluded and
    # taxed, or, with no split recorded, the amount taxed in full and what to record. It
    # fires for any dual-status filer, us_person False or unanswered, and for the spouse's
    # separate return when the SPOUSE's own year is dual-status.
    if dual:
        note = _dual_deposit_note(
            income.model_copy(update={"spouse": None}) if spouse_split else income, whose="",
            in_range=dual_resident_reading is not None,
        )
        if note is not None:
            assumptions.append(note)
    spouse_return_priced = spouse_split and (_MFS in statuses or "head_of_household" in statuses)
    if spouse_period_rule and spouse_return_priced:
        note = _dual_deposit_note(
            income.spouse, whose="On the spouse's separate return (the spouse's own facts show a dual-status year), ",
            in_range=spouse_resident_alternative is not None, joint_taxes=_MFJ in statuses,
        )
        if note is not None:
            assumptions.append(note)
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
            "deduction is excluded from the worksheet's modified AGI per Pub 915). "
            + ("The spouses lived apart at all times during the year (household.spouses_lived_apart_all_year), "
               "so a married-filing-separately figure uses the $25,000 base amount (IRC 86(c)(1)(A))."
               if apart_all_year else
               "A married-filing-separately candidate assumes the spouses did NOT live apart at all times "
               "during the year (IRC 86(c)(1)(C): both thresholds $0) — record "
               "household.spouses_lived_apart_all_year if you lived apart all year.")
        )
    # Disclose a surtax whenever ANY candidate status includes it (the MFS low end can
    # trigger Form 8959 while the MFJ headline does not).
    addmed_note = _addmed_box_note(income if spouse_split else income.model_copy(update={"spouse": None}),
                                   year, knowledge_dir, statuses, form_8959="Form 8959" in labels,
                                   withheld="additional_medicare_withholding" in {
                                       ln.slot for r in outcomes.values() for ln in r.lines})
    if addmed_note is not None:
        assumptions.append(addmed_note)
    if "addmed_withholding_not_priced" in notes:
        assumptions.append(
            f"NOT ESTIMATED — Additional Medicare Tax withholding: W-2 box 6 was supplied, but the {year} pack "
            "carries no employee Medicare rate (employee_social_security.medicare_rate), so the credit for box 6 "
            "above the regular 1.45% of box 5 is not in this figure. This bottom line likely UNDERSTATES your refund."
        )
    if "Form 8960" in labels:
        assumptions.append(
            "Net investment income tax (Form 8960) included: 3.8% of interest + dividends + net capital "
            "gain over the MAGI threshold, with MAGI approximated by AGI. Rents, royalties, and passive "
            "K-1 income are not captured by this snapshot and would increase it."
        )
    if "se_box1_standin" in notes:
        assumptions.append(
            "Self-employment tax: the W-2 social security wages (boxes 3 + 7) consume the Social Security wage "
            f"base before self-employment earnings do (Schedule SE line {form_line(year, 'sched_se.ss_wages', base_dir=knowledge_dir)}); "
            "box 1 wages stood in for them because ss_wages was not given — boxes 3 and 7 keep the 401(k) "
            "deferrals box 1 leaves out, so enter ss_wages (W-2 boxes 3 + 7)."
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
    if "earned income tax credit (refundable, formula approximation)" in labels:
        assumptions.append(
            "EITC approximated by the formula (this year's pack carries no EIC Table rule); the official EIC "
            "table uses $50 income bands, so the filed amount can differ by a few dollars."
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
            + (f"Employer-provided dependent care benefits (W-2 box 10, ${income.combined_with_spouse().dependent_care_benefits:,}) "
               f"reduce the expense limit (Form 2441 Part III). "
               if income.combined_with_spouse().dependent_care_benefits else
               "Employer-provided dependent care benefits (W-2 box 10) REDUCE the credit — none were given; pass "
               "dependent_care_benefits (or the W-2s) if box 10 is nonzero. ")
            + "The deemed $250/$500-per-month income rule for a full-time-student or disabled spouse is not applied."
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
    if "early_corrective" in notes:
        assumptions.append(
            "A corrective distribution (box 7 code 8 with J or 1) owes NO 10% additional tax on its earnings: IRC "
            "72(t)(2)(A)(ix) exempts a distribution \"attributable to withdrawal of net income attributable to a "
            "contribution which is distributed pursuant to section 408(d)(4)\" (Form 5329 exception 21).")
    if "early_exception" in notes:
        assumptions.append(
            "The early_exception_amount you entered was taken off the 10% base (Form 5329 line 2) — the exception "
            "and its number are your judgment; name them on the form.")
    if "excise_uncapped" in notes:
        assumptions.append(
            "The 6% excise on an IRA excess contribution was charged on the whole excess: IRC 4973(a) caps it at 6% of "
            "the account's value at year end — pass traditional_ira_dec31_value / roth_ira_dec31_value for the cap.")
    # JT1c (P-023): Schedule 3-A, disclosed on the headline status.
    if primary in public_benefit:
        lost, kind = public_benefit[primary]
        fpb_cfg = load_knowledge("federal", year, base_dir=knowledge_dir).federal_public_benefit
        figure = outcomes[primary].federal_public_benefit + outcomes[primary].spouse_federal_public_benefit
        rule = (
            f"Schedule 3-A (the draft {year} schedule) and proposed Treas. Reg. 1.32-4 (REG-119882-25): the refunded "
            f"portion of the EIC, the additional child tax credit and the refundable AOTC — the part over the "
            f"subtitle A tax, ${figure:,} here — is a \"Federal public benefit\" that an alien who is not a qualified "
            f"alien (8 U.S.C. 1641) may not receive. Status counts on the date the return is filed, and on a joint "
            f"return one spouse who is a U.S. citizen, U.S. national or qualified alien is enough. Tax residency is "
            f"not the test: a resident alien on a visa is not on 1641(b)'s list."
        )
        answers = "; ".join(p.why for p in (prwora_tp, prwora_sp) if p is not None)
        if not lost:
            assumptions.append(f"{rule} Nothing is held back here — {answers}.")
        else:
            assumptions.append(
                f"{rule} {answers[0].upper() + answers[1:]}. The LOW end of the range holds the ${lost:,} back; the "
                f"point keeps it because the rule is {fpb_cfg.rule_status if fpb_cfg is not None else 'proposed'}: "
                f"\"proposed to apply for taxable years ending on or after the date these regulations are "
                f"published as final regulations\"."
                + (" The adoption credit is not modeled." if fpb_cfg is not None
                   and "adoption_refundable" in fpb_cfg.affected_credits else ""))
    retirement_view = income.combined_with_spouse()
    for item in retirement_view.retirement_distributions:
        name = item.label or f"the 1099-R with box 7 {item.codes or '(blank)'}"
        _t, key = _retirement_taxable(item)
        if key == "prior_year":
            from taxfill_core.distribution_codes import codes_for  # noqa: PLC0415
            title = codes_for(year).get("P", {}).get("title", "taxable in a previous year")
            assumptions.append(
                f"{name}: code P, \"{title}\" (the year's Table 1 of the Instructions for Forms 1099-R and 5498), so "
                f"it is EXCLUDED here — report it on that year's return (amend it if it is filed).")
        elif key == "ira_gross":
            assumptions.append(
                f"{name}: box 2b 'Taxable amount not determined' on an IRA — box 2a is the GROSS amount, used here "
                f"as taxable; with nondeductible basis run calc op ira_pro_rata and pass its figure as "
                f"taxable_override.")
        elif key == "blank_2a":
            assumptions.append(f"{name}: box 2a is blank, so the gross {item.gross:,} is used as taxable — confirm "
                               f"the taxable part (the Simplified Method for a pension with after-tax basis).")
        elif item.label.endswith("'s Form 8606)"):
            assumptions.append(f"{name}: priced through Form 8606 Part I (calc op ira_pro_rata) with that person's own "
                               f"IRA pool — IRC 408(d)(2) pools only one person's IRAs, so a spouse's never mixes in.")
        elif key == "roth_j":
            assumptions.append(f"{name}: code J, an early Roth IRA distribution — its taxable part turns on your "
                               f"Roth contribution and conversion basis (Form 8606 Part III); box 2a is used.")
    charity_view = income.combined_with_spouse()
    if charity_view.charitable_cash_nonitemizer:
        cc_pack = load_knowledge("federal", year, base_dir=knowledge_dir)
        if cc_pack.charitable_contributions is None:
            if year >= 2026:
                missing_blocks.append(MissingBlock(
                    block="charitable_contributions",
                    item="the non-itemizer charitable deduction (IRC 170(p))",
                    direction="understates_refund",
                ))
                assumptions.append(
                    f"The non-itemizer charitable deduction is NOT ESTIMATED for {year}: the {year} knowledge pack "
                    f"has no charitable_contributions block yet — this estimate OVERSTATES the tax by up to its value."
                )
            else:
                assumptions.append(
                    f"charitable_cash_nonitemizer is ignored for {year}: IRC 170(p) applies to taxable years "
                    f"beginning after December 31, 2025 (P.L. 119-21 §70424). For {year} a charitable gift counts "
                    f"only on Schedule A."
                )
        elif "charitable_nonitemizer" in notes:
            assumptions.append(
                "IRC 170(p) was taken with the standard deduction: charitable_cash_nonitemizer, capped at $1,000 "
                "($2,000 on a joint return), is taken as your cash gifts to 170(b)(1)(A) organizations — not a "
                "509(a)(3) supporting organization (TEOS SO, SONFI, SOUNK) and not a donor advised fund. calc op "
                "charitable_deduction checks each gift and its substantiation."
            )
        elif "charitable_itemized_won" in notes:
            assumptions.append(
                "Itemizing won, so charitable_cash_nonitemizer is not used: IRC 170(p) applies only \"if the "
                "individual does not elect to itemize deductions\". Your itemized_deductions figure must already "
                "count only the gifts above 0.5% of AGI (IRC 170(b)(1)(I), 2026 onward)."
            )
        else:
            # Only the resident path prices it; a 1040-NR or dual-status return never reached it.
            assumptions.append(
                "The non-itemizer charitable deduction is NOT ESTIMATED on this return: the draft 2026 Form 1040-NR "
                "adds a \"Charitable contribution deduction for non-itemizers\" line, but who may take it on a "
                "nonresident or dual-status return awaits the 2026 instructions (IRC 873, a nonresident's "
                "deductions, not read) — this estimate may OVERSTATE the tax by up to its value."
            )
    s1a_view = income.combined_with_spouse()
    if _schedule_1a_engaged(s1a_view, int(bool(s1a_view.senior_taxpayer)) + int(bool(s1a_view.senior_spouse))):
        s1a_pack = load_knowledge("federal", year, base_dir=knowledge_dir)
        if s1a_pack.tax.obbba_schedule_1a is not None:
            assumptions.append(
                "Schedule 1-A deductions (P.L. 119-21) were priced below AGI, after the deduction, with calc op "
                "schedule_1a_deductions: MAGI is taken as AGI (the Puerto Rico / Form 2555 / Form 4563 add-backs "
                "are not modeled), and each part's eligibility — a tipped occupation, the FLSA overtime premium, a "
                "new US-assembled vehicle with its VIN, 65 by year end with a valid SSN — is the caller's judgment."
                + (" On married filing separately tips, overtime and the senior deduction are FORFEITED; car-loan "
                   "interest is not." if "schedule_1a_forfeit" in notes else "")
            )
        elif 2025 <= year <= 2028:
            missing_blocks.append(MissingBlock(
                block="tax.obbba_schedule_1a",
                item="Schedule 1-A deductions (tips, overtime, car-loan interest, senior)",
                direction="understates_refund",
            ))
            assumptions.append(
                f"Schedule 1-A amounts were provided but the deductions are NOT ESTIMATED for {year}: the {year} "
                f"knowledge pack has no obbba_schedule_1a block yet — this estimate OVERSTATES the tax by up to "
                f"their value."
            )
        else:
            assumptions.append(
                f"The Schedule 1-A deductions (tips, overtime, car-loan interest, senior) exist for taxable years "
                f"2025-2028 only (P.L. 119-21), so none is taken for {year}."
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
        # a dual-status point cannot claim it (IRC 25A(g)(7)); only its full-year-resident end can —
        # or the joint candidate under the election (JF5b part 3b)
        and (not dual or dual_resident_reading is not None or election_candidate)
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
            f"no Form 8863 parameters, so no AOTC/LLC was credited. "
            + ("The full-year-resident figure in the range likely UNDERSTATES your refund (the dual-status point "
               "cannot claim the credit)." if dual else "This bottom line likely UNDERSTATES your refund.")
        )
    # JT4a: what the W-2s say that the snapshot cannot price — each person's IRC 402(g) total, and code W.
    limits = load_knowledge("federal", year, base_dir=knowledge_dir).contribution_limits
    per_person = [("you", income)] + ([("your spouse", income.spouse)] if income.spouse is not None else [])
    for who, snap in per_person:
        if not snap.w2s:
            continue
        deferred = sum(w.coded(*_W2_402G_CODES) for w in snap.w2s)
        limit = getattr(getattr(limits, "elective_deferral_402g", None), "limit", None) if limits else None
        if limit is not None and deferred > int(limit):
            assumptions.append(
                f"EXCESS DEFERRAL: {who} deferred ${deferred:,} across the W-2s' box 12 codes "
                f"{', '.join(_W2_402G_CODES)} — over the {year} IRC 402(g) limit of ${int(limit):,} before any "
                f"catch-up. The limit is per PERSON across every employer; the excess is income for {year} and must "
                f"be distributed by April 15 of the next year (calc op elective_deferral_room names the room and the "
                f"catch-ups). Not priced here.")
        hsa_w = sum(w.coded("W") for w in snap.w2s)
        if hsa_w and snap.pre_agi_adjustments:
            assumptions.append(
                f"Check the HSA figure: {who} has W-2 box 12 code W (${hsa_w:,}) and pre_agi_adjustments were "
                f"given — code W is employer money AND cafeteria-plan deferrals, already out of box 1, so it is "
                f"NEVER also deducted (Form 8889: it goes on the employer-contributions line, which reduces the "
                f"room). Only direct contributions reach Schedule 1 (calc op hsa_deduction).")
    # JT2a: the 2026 overall limitation on itemized deductions (IRC 68), disclosed at the Schedule A screen.
    limitation = getattr(pack_for_gaps.tax, "itemized_limitation", None)
    if isinstance(limitation, dict) and income.itemized_deductions:
        slots = {ln.slot: ln.amount for ln in outcomes[primary].lines}
        screen_income = slots.get("agi", 0) - abs(slots.get("schedule_1a_deductions", 0))
        itemizing = any(ln.slot == "deduction" and ln.label.startswith("Less: itemized deductions")
                        for ln in outcomes[primary].lines)
        if itemizing and screen_income > int(limitation["schedule_a_screen_over"]):
            assumptions.append(
                f"Your itemized deductions may be LIMITED: from {year} IRC 68 reduces them \"by 2/37 of the lesser "
                f"of\" the deductions or the taxable income over the start of the 37% bracket, and Schedule A "
                f"(the draft {year} form) asks whether AGI less the Schedule 1-A and QBI deductions is \"more than "
                f"${int(limitation['schedule_a_screen_over']):,}\" (${screen_income:,} here). Its worksheet is not "
                f"posted, so this estimate takes the itemized deductions in full — it OVERSTATES them if the "
                f"reduction applies.")
    # JT1e (P-024): the 2026 SSN rule, disclosed from the candidates' notes.
    edu_rule = pack_for_gaps.tax.education_credits.ssn_requirement if pack_for_gaps.tax.education_credits else None
    if edu_rule is not None:
        rule = (f"from {year} IRC 25A(g)(1) (P.L. 119-21 §70606) allows the American opportunity and lifetime "
                f"learning credits only with a valid SSN — \"valid for employment\" and issued \"before the due date "
                f"of your {year} return (including extensions)\"; on a joint return one spouse's is enough, and a "
                f"dependent student needs one too (draft Instructions for Form 8863 ({year})). An ITIN is not one.")
        if "edu_ssn_filer_missing" in notes:
            assumptions.append(f"No education credit: {rule} The tax ID on file is an ITIN (on a joint return, "
                               f"both spouses').")
        if "edu_ssn_filer_unknown" in notes:
            assumptions.append(f"NOT ESTIMATED — education credits: {rule} No tax ID is recorded "
                               f"(identity.tax_id, and household.spouse.tax_id on a joint return), so the credit is "
                               f"left out; with a valid SSN it likely UNDERSTATES your refund.")
        if "edu_ssn_student_missing" in notes:
            assumptions.append(f"No education credit for a dependent student without a valid SSN: {rule}")
        if "edu_ssn_student_unknown" in notes:
            assumptions.append(f"NOT ESTIMATED — education credits for a student whose SSN status is not recorded: "
                               f"{rule} Pass aotc_students_ssn_ok (one entry per student: True for you, your spouse "
                               f"or a dependent with a valid SSN) — the credit is left out until then.")
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
    # JF5b.2: the education-credit and EITC disclosures, extended to a dual-status year.
    if dual and dual_unrestricted is not None:
        credits_note = _dual_status_credits_note(
            income.model_copy(update={"spouse": None}) if spouse_split else income, dual_unrestricted,
            in_range=dual_resident_reading is not None, joint_candidate=election_candidate,
        )
        if credits_note is not None:
            assumptions.append(credits_note)
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
    # JF1b.10 (P-018): a head-of-household figure on the nonresident-spouse route keeps every
    # married-filing-separately rule outside IRC 2(b) — one note names each that applied.
    married_7703_keys = {k for k in notes if k.startswith("m7703_")}
    if married_7703_keys:
        assumptions.append(_married_7703_note(married_7703_keys))
    if "hoh_capital_loss_1211" in notes:
        # JF2.5: the lived-apart head of household is still married for IRC 1211(b)(1).
        assumptions.append(
            "The head-of-household figure (through living apart) limits the net capital loss deducted to "
            "$1,500: IRC 1211(b)(1) reads \"$3,000 ($1,500 in the case of a married individual filing a "
            "separate return)\" and does not refer to section 7703, so the living-apart rule that makes you "
            "unmarried for head of household does not reach it — Pub 501: \"You may be considered unmarried "
            "for the purpose of using head of household status but not for other purposes\"; Treas. Reg. "
            "1.1211-1(b)(7)(i): \"In the case of a husband or a wife who files a separate return\". The "
            "Schedule D instructions word the limit \"($1,500 if married filing separately)\"; the $3,000 "
            "that reading would allow is not priced."
        )
    # FICA withheld in error on an exempt nonresident is recovered OFF-return.
    # The election does not reach FICA (IRC 6013(g)(1): chapters 1 and 24 only), so this
    # note follows the day-count answer, not the elected one (P-018).
    nra_fica_msg: str | None = None
    spouse_fica_msg: str | None = None

    def _exempt_category_in_year(imm) -> bool:
        # IRC 3121(b)(19) reaches only an F, J, M or Q nonimmigrant's service (JF1b.11).
        return imm is not None and any(
            residency.is_exempt_category_status(p.status)
            and p.start.year <= year and (p.end is None or p.end.year >= year)
            for p in imm.visa_timeline
        )

    if fica_nonresident and sum(income.ss_withheld_by_employer) > 0 and _exempt_category_in_year(profile.immigration):
        ss_total = sum(income.ss_withheld_by_employer)
        nra_fica_msg = (
            ("If the nonresident answer stands (see the first note): "
             if tp_contradiction is not None or tp_flip_reason is not None else "")
            + f"${ss_total:,} of Social Security tax (W-2 box 4) was "
            f"withheld, but exempt F/J students and scholars are generally FICA-EXEMPT (IRC "
            f"3121(b)(19)): Social Security/Medicare withheld in error is recovered from the "
            f"EMPLOYER first, otherwise with Form 843 + Form 8316 — a separate claim, NOT on the "
            + ("Form 1040" if election else
               "1040-NR, nor on the joint Form 1040 of the married-filing-jointly candidate if you make the "
               "§6013(g)/(h) election — it does not reach FICA" if election_candidate else "1040-NR")
            + ". This estimate does not include it. The claim "
            f"would recover AT LEAST the "
            f"${ss_total:,} of box-4 Social Security tax PLUS the box-6 Medicare tax withheld — "
            f"Medicare withholding is not tracked in this snapshot, so add box 4 + box 6 from each "
            f"W-2 for the actual claim amount."
            + (f" {residency.SECTION_6013_FICA}" if election else "")
        )
        assumptions.append(nra_fica_msg)
    # JF1b.11: the same note for an F/J/M/Q SPOUSE, from the spouse's own snapshot and the
    # spouse's own no-election classification (the election never reaches FICA).
    sp_fica = profile.household.spouse if profile.household is not None else None
    spouse_fica_class = _spouse_own_classification(profile, year) if sp_fica is not None else None
    if (
        spouse_split and sp_fica is not None and sum(income.spouse.ss_withheld_by_employer) > 0
        and spouse_fica_class in ("nonresident", "dual_status_candidate")
        and _exempt_category_in_year(sp_fica.immigration)
    ):
        spouse_ss = sum(income.spouse.ss_withheld_by_employer)
        spouse_fica_msg = (
            f"Your spouse's ${spouse_ss:,} of Social Security tax (W-2 box 4) was withheld, but a nonresident alien "
            "in F, J, M or Q status is generally FICA-EXEMPT (IRC 3121(b)(19))"
            + (" for the nonresident part of a dual-status year" if spouse_fica_class == "dual_status_candidate" else "")
            + ": Social Security/Medicare withheld in error is recovered from the spouse's EMPLOYER first, otherwise "
            "with the spouse's own Form 843 + Form 8316 — a separate claim, not on any return here. This estimate "
            "does not include it; the claim would recover AT LEAST that box-4 tax PLUS the box-6 Medicare tax "
            "withheld — add box 4 + box 6 from each of the spouse's W-2s."
            + (f" {residency.SECTION_6013_FICA}" if election or election_figures else "")
        )
        assumptions.append(spouse_fica_msg)
    niit_on_a_figure = any(ln.slot == "niit" and ln.amount for r in outcomes.values() for ln in r.lines)
    if election_figures and (niit_priced is not None or niit_on_a_figure or any(
        snap.interest + snap.dividends + snap.capital_gain_long + snap.capital_gain_short > 0
        for snap in joint_snapshots
    )):
        # P-018: the joint NIIT figure is a SECOND election's result (Treas. Reg.
        # 1.1411-2(a)(2)(iii)(B) for 6013(g), (iv)(B) for 6013(h)); the default is
        # married-filing-separately for NIIT. Every election figure carries it — the
        # recorded election's (joint AND separate), and the joint candidate of a couple
        # whose spouse's own facts classify nonresident.
        assumptions.append(_section_6013_niit_note(
            joint=_MFJ in statuses, separate=election and _MFS in statuses, kind=state.kind, priced=niit_priced,
            no_default=not possible_nra, spouse_split=spouse_split,
            candidate=not election and _confirmed_status(profile) != _MFJ,
            continuing_from=year - 1 if _prior_year_form(profile, year) == "1040_with_6013_election" else None,
        ))
    assumptions.append(
        "Not modeled in this estimate: AMT, LLC (available via the calc tool), itemized-deduction "
        "sub-limits, capital-loss carryovers, and "
        "the retirement-savers credit — each could change the number. (The dependent-care credit IS "
        "estimated when dependent_care_expenses/persons are supplied.)"
    )
    assumptions.append("Before unclaimed credits not captured by these inputs — see what could change it.")

    # §6013(g)/(h) caveat (H1): surfaced in BOTH assumptions and what-would-change-it.
    ident = profile.identity
    us_person_false = (
        ident is not None and ident.us_person is not None and ident.us_person.value is False
    )
    dual_caveat: str | None = None
    if dual and dual_routes is not None:
        # JF5b.2: the point (Pub 519 ch. 6's restrictions — the deduction the point used is read
        # off its own ledger), the approximation, and the range with its route (or none).
        point_deduction = next((line for line in composition if line.slot == "deduction"), None)
        dual_married = _married_for_year(profile, year) or (
            _marital(profile) is None and _confirmed_status(profile) in _MARRIED_STATUSES)
        dual_caveat = _dual_status_caveat(
            year, primary, itemized_used=-point_deduction.amount if point_deduction is not None else 0,
            routes=dual_routes, resident_reading=dual_resident_reading, niit="Form 8960" in labels,
            married=dual_married, confirmed=_confirmed_status(profile) == primary,
            otherwise_bracketed=dual_resident_reading is None and low != high,
            marital_unanswered=_marital(profile) is None and _confirmed_status(profile) is None,
            joint_candidate=outcomes[_MFJ].bottom if election_candidate else None,
            hoh_not_priced=(
                dual_resident_reading is not None and not dual_married and "head_of_household" not in statuses
                and (bool(profile.household and profile.household.dependents) or _confirmed_true(
                    profile.household.hoh_qualifying_person if profile.household else None))
            ),
        )
    # JF5b part 3b: the election as a CANDIDATE for a nonresident or dual-status taxpayer.
    candidate_caveat = _section_6013_candidate_caveat(
        own_classification=classification, kind=state.kind, joint=outcomes[_MFJ].bottom,
        spouse_class=state.spouse_6013,
        spouse_needs_itin=_spouse_nra_direction(profile, year) is not None and not _spouse_has_tin(profile),
        continuing_from=year - 1 if _prior_year_form(profile, year) == "1040_with_6013_election" else None,
    ) if election_candidate else None
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
        if dual_caveat is not None:
            residency_caveat += " " + dual_caveat
    elif dual_caveat is not None:
        # A dual-status year restricts statuses, the deduction and the credits; MFJ/HOH were
        # dropped and the point prices the restrictions — say so loudly, with the range.
        residency_caveat = dual_caveat + (f" {candidate_caveat}" if candidate_caveat is not None else "")
    elif candidate_caveat is not None:
        # JF5b part 3b: a married nonresident sees the election as a candidate, as the reverse couple does.
        residency_caveat = candidate_caveat
    elif classification == "nonresident" and married:
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
        # Visa holder whose residency is not yet determined — frame it conditionally. The
        # §6013(g)/(h) election is a married couple's choice (JF1b.2): only a household married
        # for the year, or one with a confirmed married status, reads about it; an unmarried
        # (or unanswered) filer gets the 1040-NR restrictions alone.
        residency_caveat = (
            _SECTION_6013_CONDITIONAL_CAVEAT
            if _married_for_year(profile, year) or _confirmed_status(profile) in _MARRIED_STATUSES
            else _NONRESIDENT_CONDITIONAL_CAVEAT
        )
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
        bar = (
            "A nonresident alien cannot file as head of household — Pub 519 ch. 5: \"You cannot file as head of "
            "household if you are a nonresident alien at any time during the tax year.\""
            if classification == "nonresident" else
            "A dual-status year bars head of household — Pub 519 ch. 6: \"You cannot use the head of household Tax "
            "Table column or Tax Computation Worksheet.\""
        )
        hoh_bar = (
            f"{bar} So this figure prices {statuses[0].replace('_', ' ')} instead of the confirmed head_of_household "
            "status — the status open to you (generally married filing separately for a married filer — Pub 519 "
            "ch. 5 lists exceptions — otherwise single or, if eligible, qualifying surviving spouse); change the "
            "confirmed status to it."
        )
        residency_caveat = hoh_bar if residency_caveat is None else f"{hoh_bar} {residency_caveat}"
    if residency_caveat is not None:
        # A joint status the facts rule out is the first thing the user reads (P-018).
        if state.joint_blocked:
            assumptions.insert(0, residency_caveat)
        else:
            assumptions.append(residency_caveat)
    # JF5b: what the recorded prior-year return did to the residency answer.
    prior_year_check_note: str | None = None
    prior_form = _prior_year_form(profile, year)
    if own_classification == "resident" and _prior_year_resident(profile, year) is True:
        base_result = residency_result
        departing = base_result is not None and any(
            r.startswith("Your last declared status period ends") for r in base_result.reasons)
        assumptions.append(
            f"Residency: a resident from January 1 of {year} — your {year - 1} return is recorded as "
            f"'{prior_form}' (prior_filings.return_forms), so you were a U.S. resident during {year - 1}, and the "
            f"substantial presence test is met for {year}; no residency starting date falls inside {year}, so no "
            f"arrival split. {residency.PRIOR_YEAR_RESIDENCY_LAW}"
            + (
                f" Your last declared status period ends before December 31 of {year}: the residency ending date is "
                f"still December 31, and it is the last day of physical presence in {year} only if IRC 7701(b)(2)(B) "
                f"and Treas. Reg. 301.7701(b)-4(b)(2) are met — for the rest of the year a tax home in a foreign "
                f"country and a closer connection to it, and no U.S. residency during any part of {year + 1} — and the "
                f"statement Pub 519 requires is filed (Pub 519, Residency Starting and Ending Dates)."
                if departing else ""
            )
        )
        check = residency.prior_year_check(base_result) if base_result is not None else None
        if check is not None:
            assumptions.insert(0, check)
            prior_year_check_note = check
            fj = profile.immigration is not None and any(
                p.status.strip().upper().startswith(("F", "J")) for p in profile.immigration.visa_timeline)
            if sum(income.ss_withheld_by_employer) > 0 and fj:
                assumptions.append(
                    "If the CHECK THE PRIOR-YEAR RETURN note's reading (b) holds (the prior-year return was on the "
                    f"wrong form), the F/J part of {year} is a nonresident period, and wages there as an F/J exempt "
                    "individual are generally FICA-EXEMPT (IRC 3121(b)(19)): Social Security/Medicare withheld in "
                    "error is recovered from the EMPLOYER first, otherwise with Form 843 + Form 8316 — a separate "
                    "claim, not on the return."
                )
    elif prior_form == "1040_with_6013_election" and own_classification is not None:
        assumptions.append(residency.prior_year_election_reason(year))
    # JF5b part 3b (P-018): the election a prior-year joint return rests on may CONTINUE (IRC
    # 6013(g)(3)) — never applied from that return alone; the fact for this year is asked for.
    rf_now = profile.residency_facts
    continuing_note: str | None = None
    if (
        prior_form == "1040_with_6013_election"
        and not (rf_now is not None and rf_now.section_6013_election is not None
                 and rf_now.section_6013_election.value is not None)
        and (_married_for_year(profile, year) or _marital(profile) is None)
        and not state.unavailable   # suspended this year (IRC 6013(g)(3)) — the residency caveat says so
    ):
        if election:
            # A confirmed joint status is read as the election (JF5a): say it continues, not "NOT applied".
            continuing_note = residency.prior_year_election_read_as_continuing(year)
        elif _confirmed_status(profile) == _MFJ and spouse_nonresident:
            continuing_note = residency.prior_year_election_read_as_continuing(year, confirmed_joint_candidate=True)
        else:
            continuing_note = residency.prior_year_election_continues(year)
        assumptions.append(continuing_note)
    # JF5b: an unsettled nonresident answer (a CONTRADICTION with the recorded prior year, or
    # classify's "may be WRONG") is read before anything else, the taxpayer's first.
    residency_front = _unsettled_residency_notes(
        profile, year, primary=primary, contradiction=tp_contradiction, flip_reason=tp_flip_reason,
        resident_reading=resident_reading, election=election, spouse_result=spouse_result,
        spouse_flip_reason=spouse_flip_reason, spouse_flip_alternative=spouse_flip_alternative,
    )
    assumptions[0:0] = residency_front

    changes: list[str] = [*residency_front, *([prior_year_check_note] if prior_year_check_note else [])]
    if residency_caveat is not None:
        changes.append(residency_caveat)
    if continuing_note is not None:
        changes.append(continuing_note)
    if ssn_demotion_msg is not None:
        changes.append(ssn_demotion_msg)
    if nra_fica_msg is not None:
        changes.append(nra_fica_msg)
    if spouse_fica_msg is not None:
        changes.append(spouse_fica_msg)
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
        changes.append(
            "Confirming your filing status narrows the range (the residency reading keeps a range of its own)."
            if residency_bracketed else
            "Confirming your filing status narrows the range (the Schedule 3-A reading keeps a range of its own)."
            if public_benefit_bracketed else "Confirming your filing status collapses the range to one number."
        )
    if public_benefit.get(primary, (0, ""))[1] == "unknown" and public_benefit[primary][0]:
        changes.append(
            f"Record identity.qualified_alien_status (and the spouse's): on the date you file, a U.S. citizen, U.S. "
            f"national or qualified alien keeps the ${public_benefit[primary][0]:,} Schedule 3-A would otherwise "
            f"hold back — the low end of this range assumes it is held back.")

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
