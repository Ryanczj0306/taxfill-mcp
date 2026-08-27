"""Deterministic calculation primitives (dev plan sections 3, 8 and 10).

The no-LLM-arithmetic rule: the model never does arithmetic that lands on a
return. Every number is produced here, from per-year knowledge packs
(``knowledge/<jurisdiction>/<year>.yaml``) that carry citations to the
official IRS documents. Every tax result returns its inputs, a
human-readable ``work`` derivation, and the data-pack citation, so the
verifier can independently recompute it and a human can re-confirm it.

Contents:

* ABA routing-number checksum (M0) — validates banking details at intake.
* ``irs_round`` — IRS whole-dollar rounding (50 cents rounds up).
* ``tax_from_taxable_income`` — Form 1040 line 16, ORDINARY computation
  only: the published Tax Table below $100,000 (reproduced via the
  row-midpoint rule), the Tax Computation Worksheet / rate schedules at or
  above it. Returns with preferential-rate income (qualified dividends /
  capital gains, Schedule D worksheets, Form 8615, the Foreign Earned
  Income Tax Worksheet) compute line 16 from a different worksheet even
  below $100,000 — out of scope here, per the booklet's line 16 caution.
* ``standard_deduction`` — base amount plus 65-or-older/blind additions.
* ``se_tax`` — Schedule SE Part I (92.35% factor, capped SS portion,
  uncapped Medicare portion, $400 threshold).
* ``presence_days`` / ``presence_days_by_year`` — I-94-style day counting
  (any partial day counts as a full day; overlaps merged) feeding the
  Substantial Presence Test in residency.py.
* Phase F worksheet ops: ``tax_with_preferential_rates`` (Qualified
  Dividends and Capital Gain Tax Worksheet), ``taxable_social_security``
  (Social Security Benefits Worksheet), ``excess_ss`` (Schedule 3
  excess-social-security credit), ``student_loan_interest_deduction``
  (section 221), ``education_credits`` (Form 8863 AOTC/LLC), and
  ``ptc_annual`` / ``ptc_monthly`` (Form 8962 Premium Tax Credit — the
  annual method and the lines 12-23 monthly grid for part-year coverage).
* Family credit ops: ``child_tax_credit`` (Schedule 8812 — nonrefundable
  CTC/ODC for Form 1040 line 19 plus the refundable ACTC for line 28,
  including the 2021 ARPA expanded fully-refundable rules) and ``eitc``
  (the earned income credit by the Rev. Proc. formula, with the
  investment-income and married-filing-separately gates).
* ``dependent_care_credit`` (Phase G) — the Form 2441 child & dependent
  care credit line flow (Schedule 3 line 2): expense caps by qualifying-
  person count, the employer-benefit (W-2 box 10) cap offset, the earned-
  income smallest-of limitation (spouse required for MFJ), the AGI-driven
  applicable-percentage slide (35%->20%; 2021 ARPA: 50%->20%->0% with the
  $438,000 zero point), the MFS generally-ineligible gate, and the 2021
  refundable-if-US-abode flag.
* ``treaty_benefit`` (Phase G) — validates/computes a treaty exemption
  (Schedule OI / Form 1040-NR line 1k) from the per-country
  ``knowledge/treaties/<country>.yaml`` packs (China, India, Korea, Canada,
  Mexico): student compensation limits, scholarship/abroad-payment
  exemptions, teacher-article year windows (with India's retroactive-loss
  clawback), and the Canada/Mexico employment de-minimis shapes. Final
  eligibility judgment stays with the agent.
* ``schedule_1a_deductions`` (Phase H, H6) — the four OBBBA Schedule 1-A
  deductions (tips / overtime / car-loan interest / senior; P.L. 119-21,
  TY2025-2028): per-status caps, the asymmetric per-$1,000 phase-out rounding
  (down for tips/overtime, UP for car loan), the 6%-per-person senior
  phase-out, and the MFS forfeiture on tips/overtime/senior. Line 38 flows to
  Form 1040 line 13b / 1040-NR line 13c. Eligibility requirements stay caller
  judgment, quoted in the work.
* ``employee_fica`` / ``estimated_tax_safe_harbor`` / ``annualize_ytd``
  (Phase H, H4) — the projection trio: employee-side FICA across visa-status
  segments (the F/J exemption is STATUS-based, not marital — §6013(g) does not
  start FICA), the IRC 6654(d) required annual payment (90% current vs
  100/110% prior, the $1,000 de minimis, the flat-22% supplemental-wage trap
  quoted), and YTD->full-year calendar-day proration (disclosed arithmetic,
  no citation — it is an assumption, and the work says when it breaks).
* ``contribution_limits`` / ``ira_contribution_eligibility`` /
  ``marginal_dollar_savings`` / ``magi_ladder`` (Phase H, H8) — the
  account-limit quartet: limits WITH machine-readable scoping, the Pub 590-A
  reduced-limit worksheet (the 6%/yr-excise guard and its year-end-status
  flip), the where-does-the-next-dollar-go ranking (payroll dollars beat
  401(k) dollars by the FICA saving), and the per-test MAGI table.
* ``ira_pro_rata`` / ``roth_conversion`` (Phase I, I1) — the conversion pair.
  Form 8606 Part I as IRC 408(d)(2) writes it: ALL traditional/SEP/SIMPLE IRAs
  are 1 CONTRACT and a year's distributions 1 DISTRIBUTION, so the taxable
  share of a conversion is the POOL's pretax/basis mix and the ratio's
  denominator (line 9 = 6+7+8) ADDS THE CONVERSION BACK. ``roth_conversion``
  then makes the caller name the path, because the two are taxed differently
  and get conflated: a DIRECT plan-to-Roth-IRA rollover (Notice 2008-30) is
  fully taxable on its pretax part but pro-rata NEVER reaches it — the only
  clean way to empty an old 401(k) — while a traditional-IRA conversion
  delegates to ``ira_pro_rata``. On top of the taxable amount it returns the
  bracket headroom (which dollars spill into the next rate) and the IRC 1411
  crossing (conversion income is never NII, but it raises the MAGI the
  threshold is measured against), and the work carries the withholding trap:
  withheld tax is not converted, so it is lost Roth space the 10% additional
  tax can still reach.
* ``hsa_deduction`` (Phase I, I2) — Form 8889 / IRC 223, the op that turns the
  HSA amounts ``contribution_limits`` already shipped into a filed line. Four
  traps it is built around: the limit is MONTHLY (223(b)(1)-(2), the Line 3
  Limitation Chart month by month, not the annual figure); the LAST-MONTH RULE
  (223(b)(8)) hands a December-1 holder the whole annual limit and starts a
  13-MONTH testing period whose failure pulls the extra back into income plus a
  10% additional tax; W-2 box 12 code W is employer money AND cafeteria-plan
  payroll deferrals, already out of box 1, so it REDUCES the deduction instead
  of adding to it (the double-count that overstates every payroll filer's
  Schedule 1 line 13); and a general-purpose health FSA — INCLUDING a spouse's
  (Rev. Rul. 2004-45) — is disqualifying coverage, while limited-purpose and
  post-deductible ones are not. Also models the 223(b)(7) Medicare zeroing, the
  223(b)(5) family-limit split, the age-55 catch-up's line 3 / line 7 routing,
  the IRC 4973 6% excise, Part II distributions with the 223(f)(4) 20% tax and
  Part III recapture — and, with ``wages``, the FICA half the direct-vs-payroll
  choice turns on.
* ``espp_disposition`` / ``capital_loss_limitation`` (Phase I, I3) — the
  equity-comp pair, for the population this repo actually serves. The first is
  IRC 421/423 on ONE lot of section 423 ESPP stock, and it exists because the
  two dispositions are taxed COMPLETELY differently and get conflated: a
  QUALIFYING one (more than 2 years past grant AND more than 1 year past
  purchase) recognises the LESSER of the GRANT-date discount and the actual
  gain — so a sale at a loss recognises NOTHING as ordinary income — while a
  DISQUALIFYING one recognises the FULL purchase-date spread REGARDLESS of the
  sale price, so selling below the purchase-date FMV still produces that income
  and a capital loss on top. Its highest-dollar output is the BASIS CORRECTION:
  the 1099-B reports the discounted purchase price only (Instructions for Form
  8949, compensatory options granted after 2013), the correct basis is that
  plus the ordinary income (IRC 423(c)'s last sentence), and a filer who trusts
  the broker pays tax on the discount TWICE — so the op returns the corrected
  basis, the adjustment and the Form 8949 code-B row that files it. Under a
  LOOKBACK the qualifying income is measured on Form 3922 BOX 8, not box 5, and
  a price that only a lookback could produce is refused without it. The second
  is IRC 1211(b)/1212(b) and Schedule D's Capital Loss Carryover Worksheet: net
  short and long SEPARATELY, deduct at most $3,000/$1,500, carry the rest
  forward INDEFINITELY WITH ITS CHARACTER PRESERVED, and — the part the printed
  cap hides — let TAXABLE INCOME limit how much of the loss the year actually
  consumes (worksheet line 4 = 1212(b)(2)(A)'s lesser-of), which makes a
  low-income year's carryover LARGER, not smaller. ``following_years`` rolls a
  multi-year chain and threads the carryovers itself.
* ``state_tax`` (Phase G, G4) — the STATE income-tax line for every
  jurisdiction whose pack ships a cited ``tax`` block: all 42 income-tax
  jurisdictions (41 states + DC) for 2023 and 2024, and 41 of 42 for 2025
  (RI pending). Flat-rate packs multiply; graduated packs apply the
  per-filing-status marginal schedule bracket by bracket. Which shape a
  state has is the PACK's business and it MOVES BY YEAR (GA converted to
  flat for 2024; IA and LA for 2025) — never hardcode a roster. In both
  shapes the base is the caller-supplied state taxable base minus the
  state's verified personal/dependent exemptions and standard deduction
  where the state ships one. County/city add-on taxes and state credits are
  NOT modeled — the work string discloses exactly what was and was not
  applied, including out-of-schedule surcharges and recapture worksheets.

These functions are pure: no logging, no side effects; the only I/O is
reading the versioned knowledge pack. They never echo the value being
validated (routing/account numbers are sensitive).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.knowledge import (
    FILING_STATUSES,
    Citation,
    DependentCareParams,
    FilingStatus,
    ForeignAccountReportingParams,
    KnowledgePack,
    MagiPhaseoutRange,
    ContributionLimitsParams,
    MagiRange,
    ObbbaSchedule1aParams,
    RateBracket,
    StateRateBracket,
    TaxTable,
    load_knowledge,
    load_state_knowledge,
    load_treaty,
)

# ABA position weights for the 9-digit routing transit number checksum.
_ABA_WEIGHTS = (3, 7, 1, 3, 7, 1, 3, 7, 1)

# First-two-digit prefixes currently assigned to ACH-eligible institutions:
# 01-12 (Federal Reserve districts) and 21-32 (thrift institutions).
_VALID_PREFIX_RANGES = ((1, 12), (21, 32))


def aba_checksum_ok(routing: str) -> bool:
    """Return True if ``routing`` passes the ABA 3-7-1 checksum.

    The checksum is defined for exactly nine ASCII digits ``d1..d9``:

        (3*d1 + 7*d2 + 1*d3 + 3*d4 + 7*d5 + 1*d6 + 3*d7 + 7*d8 + 1*d9) % 10 == 0

    This is the pure checksum only. It does not check prefix assignment
    ranges — use :func:`is_valid_routing_number` for full validation
    (e.g. the all-zeros string passes the checksum but is not a real
    routing number).
    """
    if not isinstance(routing, str):
        return False
    if len(routing) != 9 or not routing.isascii() or not routing.isdigit():
        return False
    return sum(w * int(d) for w, d in zip(_ABA_WEIGHTS, routing)) % 10 == 0


def is_valid_routing_number(routing: str) -> bool:
    """Validate a US bank routing transit number for direct deposit/debit.

    Checks, in order:

    1. exactly nine ASCII digits (no dashes, no spaces — callers must pass
       the raw digits exactly as printed on a check);
    2. the first two digits fall in an assigned ACH-eligible prefix range
       (01-12 or 21-32), which also rejects the degenerate all-zeros value;
    3. the ABA 3-7-1 checksum (:func:`aba_checksum_ok`).

    Pure predicate: returns a bool, raises nothing, logs nothing.
    """
    if not isinstance(routing, str):
        return False
    if len(routing) != 9 or not routing.isascii() or not routing.isdigit():
        return False
    prefix = int(routing[:2])
    if not any(low <= prefix <= high for low, high in _VALID_PREFIX_RANGES):
        return False
    return aba_checksum_ok(routing)


# ---------------------------------------------------------------------------
# Shared helpers: exact money handling and IRS rounding
# ---------------------------------------------------------------------------

# Filing statuses accepted as input. A qualifying surviving spouse uses the
# married-filing-jointly column (2023 Tax Table footnote: "* This column must
# also be used by a qualifying surviving spouse."), so it is an input alias,
# not a fifth schedule in the knowledge pack.
FilingStatusInput = Literal[
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
    "qualifying_surviving_spouse",
]

_QSS = "qualifying_surviving_spouse"
_CENT = Decimal("0.01")
_ONE = Decimal("1")


def _to_decimal(value: int | float | Decimal | str, name: str) -> Decimal:
    """Convert a money input to an exact Decimal, with prescriptive errors."""
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number, got a bool — pass the dollar amount itself")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        # str() round-trips the shortest repr, so 0.1 becomes Decimal('0.1'),
        # not the 0.1000000000000000055... binary artifact.
        result = Decimal(str(value))
    elif isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        try:
            result = Decimal(cleaned)
        except InvalidOperation:
            raise ValueError(
                f"{name} string {value!r} is not a number — pass digits with an optional decimal point, "
                f"e.g. '25300' or '25300.00'"
            ) from None
    else:
        raise TypeError(
            f"{name} must be an int, float, Decimal or numeric string, got {type(value).__name__}"
        )
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite number, got {result} — check the upstream computation")
    return result


def _cents(amount: Decimal) -> Decimal:
    """Quantize to whole cents, half a cent rounding up (form line entries)."""
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _money(amount: Decimal) -> str:
    """Format a Decimal as $1,234.56 for work strings."""
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _dollars(amount: int | Decimal) -> str:
    """Format a whole-dollar amount as $1,234 for work strings."""
    value = int(amount)
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,}"


def irs_round(amount: int | float | Decimal | str) -> int:
    """IRS whole-dollar rounding: 50 cents or more rounds up to the next dollar.

    Form 1040 instructions ("Rounding Off to Whole Dollars"): drop amounts
    under 50 cents; increase amounts from 50 to 99 cents to the next dollar.
    Ties round AWAY from zero (1.50 -> 2), never banker's rounding — and the
    same rule applies to the magnitude of negative amounts (-1.50 -> -2).

    Accepts int, float, Decimal, or a numeric string (commas and a leading
    '$' are tolerated). Returns a plain int of whole dollars.
    """
    value = _to_decimal(amount, "amount")
    return int(value.quantize(_ONE, rounding=ROUND_HALF_UP))


def _resolve_filing_status(filing_status: str) -> tuple[FilingStatus, str | None]:
    """Map an input filing status to the knowledge-pack column, plus an alias note."""
    if filing_status == _QSS:
        return (
            "married_filing_jointly",
            "qualifying surviving spouse uses the married-filing-jointly column",
        )
    if filing_status in FILING_STATUSES:
        return filing_status, None  # type: ignore[return-value]
    raise ValueError(
        f"unknown filing_status {filing_status!r} — use one of: single, married_filing_jointly, "
        f"married_filing_separately, head_of_household, qualifying_surviving_spouse"
    )


def _load_federal(year: int, knowledge_dir: str | Path | None) -> KnowledgePack:
    return load_knowledge("federal", year, base_dir=knowledge_dir)


# ---------------------------------------------------------------------------
# Tax from taxable income (Form 1040 line 16)
# ---------------------------------------------------------------------------


class TaxResult(BaseModel):
    """Result of :func:`tax_from_taxable_income`: the number plus its full audit trail."""

    model_config = ConfigDict(extra="forbid")

    tax: int = Field(description="Whole-dollar tax for Form 1040 line 16.")
    method: Literal["tax_table", "schedule"] = Field(
        description="'tax_table' below the cutoff (published table via the midpoint rule); 'schedule' at/above it."
    )
    exact_tax: Decimal = Field(description="The pre-rounding schedule value the tax was rounded from.")
    inputs: dict[str, Any] = Field(description="Echo of the inputs this number was computed from.")
    work: str = Field(description="Human-readable derivation showing the bracket math.")
    citation: Citation


def _schedule_tax(amount: Decimal, brackets: list[RateBracket]) -> tuple[Decimal, RateBracket, Decimal]:
    """Evaluate a rate schedule exactly. Returns (tax, bracket used, bracket base tax).

    Bracket semantics follow the published wording: a bracket covers income
    'over X but not over Y', so income exactly equal to Y is still in that
    bracket (the formulas agree at the boundary either way).
    """
    base = Decimal("0")
    for bracket in brackets:
        if bracket.but_not_over is None or amount <= bracket.but_not_over:
            return base + bracket.rate * (amount - bracket.over), bracket, base
        base += bracket.rate * (Decimal(bracket.but_not_over) - bracket.over)
    raise AssertionError("rate schedule has no top bracket — knowledge validation should have rejected this pack")


def _bracket_math_text(amount: Decimal, bracket: RateBracket, base: Decimal) -> str:
    pct = f"{bracket.rate * 100:.0f}%"
    if bracket.over == 0:
        return f"{pct} x {_money(amount)}"
    return f"{_money(base)} + {pct} x ({_money(amount)} - {_dollars(bracket.over)})"


def _table_row(amount: Decimal, table: TaxTable) -> tuple[int, int]:
    """Locate the published Tax Table row [at_least, but_less_than) containing ``amount``."""
    for band in table.row_bands:
        if band.at_least <= amount < band.below:
            offset = int((amount - band.at_least) // band.row_width)
            row_lo = band.at_least + offset * band.row_width
            return row_lo, row_lo + band.row_width
    raise AssertionError(
        "amount outside every tax_table row band — callers must check applies_below first"
    )


def tax_from_taxable_income(
    taxable_income: int | float | Decimal | str,
    filing_status: FilingStatusInput | str,
    year: int = 2023,
    knowledge_dir: str | Path | None = None,
) -> TaxResult:
    """Compute Form 1040 line 16 tax from line 15 taxable income — ORDINARY computation only.

    Scope caution (mirroring the booklet's own line 16 note, "See the
    instructions for line 16 to see if you must use the Tax Table below to
    figure your tax"): this is the ordinary tax computation. A return with
    qualified dividends or capital gains (the Qualified Dividends and
    Capital Gain Tax Worksheet / Schedule D Tax Worksheet), Form 8615
    (kiddie tax), or the Foreign Earned Income Tax Worksheet computes
    line 16 from its own worksheet EVEN BELOW $100,000 — those worksheets
    are out of scope for this function; do not apply it to
    preferential-rate income.

    Honors the IRS method split exactly:

    * **Below $100,000** (``tax_table`` method): the published Tax Table is
      mandatory for the ordinary computation. The table is reproduced
      deterministically — find the row ``[at_least, but_less_than)``
      containing the income, evaluate the rate schedule at the row
      MIDPOINT, and round to the nearest dollar with 50 cents rounding up.
      This matches every published row (golden-tested against the official
      2023 table).
    * **At or above $100,000** (``schedule`` method): the Tax Computation
      Worksheet, which is algebraically the rate schedule; bracket math is
      shown in ``work`` and the result is rounded to whole dollars.

    ``filing_status`` accepts the four statuses plus
    ``qualifying_surviving_spouse`` (which uses the married-filing-jointly
    column, per the published table's footnote).

    ``knowledge_dir`` overrides the default ``knowledge/`` directory of the
    source checkout (pass it when running from an installed wheel).
    """
    income = _to_decimal(taxable_income, "taxable_income")
    if income < 0:
        raise ValueError(
            f"taxable_income cannot be negative (got {income}) — Form 1040 line 15 cannot go below zero; "
            f"pass 0 for a zero-or-negative taxable income"
        )
    status, alias_note = _resolve_filing_status(str(filing_status))
    pack = _load_federal(year, knowledge_dir)
    tax_block = pack.tax
    brackets = tax_block.rate_schedules.schedules[status]
    status_label = str(filing_status) if alias_note is None else f"{filing_status} ({alias_note})"
    inputs: dict[str, Any] = {
        "taxable_income": str(income),
        "filing_status": str(filing_status),
        "year": year,
    }

    if income < tax_block.tax_table.applies_below:
        row_lo, row_hi = _table_row(income, tax_block.tax_table)
        midpoint = (Decimal(row_lo) + Decimal(row_hi)) / 2
        exact, bracket, base = _schedule_tax(midpoint, brackets)
        tax = irs_round(exact)
        inputs["table_row"] = {"at_least": row_lo, "but_less_than": row_hi}
        work = (
            f"{year} Tax Table ({status_label}): taxable income {_money(income)} falls in the row "
            f"'at least {_dollars(row_lo)} but less than {_dollars(row_hi)}'. Table tax = rate schedule at "
            f"the row midpoint {_money(midpoint)}: {_bracket_math_text(midpoint, bracket, base)} "
            f"= {_money(exact)}, rounded to the nearest dollar (50 cents rounds up) = {_dollars(tax)}."
        )
        return TaxResult(
            tax=tax,
            method="tax_table",
            exact_tax=exact,
            inputs=inputs,
            work=work,
            citation=tax_block.tax_table.citation,
        )

    exact, bracket, base = _schedule_tax(income, brackets)
    tax = irs_round(exact)
    work = (
        f"{year} rate schedule ({status_label}): taxable income {_money(income)} is "
        f"{_dollars(tax_block.tax_table.applies_below)} or more, so the Tax Table does not apply and the "
        f"Tax Computation Worksheet (rate schedule) is used: {_bracket_math_text(income, bracket, base)} "
        f"= {_money(exact)}, rounded to the nearest dollar (50 cents rounds up) = {_dollars(tax)}."
    )
    return TaxResult(
        tax=tax,
        method="schedule",
        exact_tax=exact,
        inputs=inputs,
        work=work,
        citation=tax_block.rate_schedules.citation,
    )


# ---------------------------------------------------------------------------
# Standard deduction
# ---------------------------------------------------------------------------


class StandardDeductionResult(BaseModel):
    """Result of :func:`standard_deduction`."""

    model_config = ConfigDict(extra="forbid")

    amount: int = Field(description="Whole-dollar standard deduction.")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def standard_deduction(
    filing_status: FilingStatusInput | str,
    year: int = 2023,
    age_65_plus: int = 0,
    blind: int = 0,
    knowledge_dir: str | Path | None = None,
) -> StandardDeductionResult:
    """Standard deduction: base amount plus 65-or-older / blind additions.

    ``age_65_plus`` and ``blind`` count the people on the return each
    condition applies to (the Form 1040 'Age/Blindness' checkboxes):
    at most 1 each for single / head_of_household /
    qualifying_surviving_spouse (a surviving spouse files without a spouse,
    so only the taxpayer's own boxes exist — the published chart caps QSS
    at 2 boxes total), at most 2 each for married_filing_jointly and
    married_filing_separately (the 2023 Form 1040 instructions line 12
    chart footnote: MFS spouse boxes apply only when the spouse had no
    income, isn't filing, and isn't claimable as a dependent — that
    eligibility judgment is the agent's, the cap is enforced here). One
    additional amount applies per condition per person; the additional
    amount is larger for unmarried, not-a-surviving-spouse taxpayers
    (2023: $1,850 vs $1,500 — Rev. Proc. 2022-38 section 3.15(3)).

    Out of scope here (handled at position/verify time): the reduced
    standard deduction for someone claimable as a dependent, and the rule
    that a married-filing-separately taxpayer whose spouse itemizes must
    itemize too.
    """
    status, alias_note = _resolve_filing_status(str(filing_status))
    # Married statuses (and a surviving spouse) get the smaller per-condition
    # addition; only unmarried, not-a-surviving-spouse taxpayers get the
    # larger one — so the alias maps to 'married' here too.
    unmarried = str(filing_status) in ("single", "head_of_household")
    # Spouse Age/Blindness boxes exist only on joint and separate returns;
    # a qualifying surviving spouse has no spouse on the return, so the
    # published chart allows at most 2 QSS boxes total (1 per condition) —
    # 2023 Form 1040 instructions, line 12 'Standard Deduction Chart for
    # People Who Were Born Before January 2, 1959, or Were Blind'.
    two_person_statuses = ("married_filing_jointly", "married_filing_separately")
    max_per_condition = 2 if str(filing_status) in two_person_statuses else 1
    for name, count in (("age_65_plus", age_65_plus), ("blind", blind)):
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError(f"{name} must be an int (number of people the condition applies to), got {count!r}")
        if not 0 <= count <= max_per_condition:
            raise ValueError(
                f"{name} must be between 0 and {max_per_condition} for filing status '{filing_status}' "
                f"(it counts people on the return who are 65 or older / blind; spouse Age/Blindness "
                f"boxes exist only on married-filing-jointly and married-filing-separately returns), "
                f"got {count}"
            )
    pack = _load_federal(year, knowledge_dir)
    spec = pack.tax.standard_deduction
    base = spec.amounts[status]
    per_condition = (
        spec.additional_aged_or_blind.unmarried if unmarried else spec.additional_aged_or_blind.married
    )
    boxes = age_65_plus + blind
    amount = base + boxes * per_condition
    status_label = str(filing_status) if alias_note is None else f"{filing_status} ({alias_note})"
    rate_label = "unmarried rate" if unmarried else "married/surviving-spouse rate"
    if boxes:
        work = (
            f"{year} standard deduction ({status_label}): base {_dollars(base)} + {boxes} "
            f"age-65-or-older/blind box(es) x {_dollars(per_condition)} ({rate_label}) = {_dollars(amount)}."
        )
    else:
        work = f"{year} standard deduction ({status_label}): base {_dollars(base)} (no age-65-or-older/blind boxes)."
    return StandardDeductionResult(
        amount=amount,
        inputs={
            "filing_status": str(filing_status),
            "year": year,
            "age_65_plus": age_65_plus,
            "blind": blind,
        },
        work=work,
        citation=spec.citation,
    )


# ---------------------------------------------------------------------------
# Self-employment tax (Schedule SE, Part I)
# ---------------------------------------------------------------------------


class SeTaxResult(BaseModel):
    """Result of :func:`se_tax`: Schedule SE Part I, lines 4a-13."""

    model_config = ConfigDict(extra="forbid")

    se_tax: int = Field(description="Line 12, rounded to whole dollars (goes on Schedule 2 line 4).")
    deduction_half: int = Field(description="Line 13, rounded to whole dollars (goes on Schedule 1 line 15).")
    net_earnings: Decimal = Field(description="Line 4a/4c net earnings from self-employment, in cents.")
    ss_portion: Decimal = Field(description="Line 10 social security portion, in cents (capped at the wage base).")
    medicare_portion: Decimal = Field(description="Line 11 Medicare portion, in cents (uncapped).")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def se_tax(
    net_profit: int | float | Decimal | str,
    year: int = 2023,
    knowledge_dir: str | Path | None = None,
    w2_ss_wages: int | float | Decimal | str = 0,
) -> SeTaxResult:
    """Self-employment tax from Schedule C net profit (Schedule SE Part I).

    Line sequence, per the 2023 Schedule SE:

    * line 4a: net earnings = net profit x 92.35% when the profit is
      positive; otherwise the profit itself carries down unchanged.
    * line 4c: if net earnings are less than $400, stop — no SE tax (and no
      half-SE-tax deduction). The threshold is applied to the exact
      cents-level net earnings, not a rounded value.
    * lines 8a-9: ``w2_ss_wages`` (W-2 box 3 social security wages + box 7
      tips, all employers) reduces the wage base available to SE earnings —
      line 9 = max(0, wage base - line 8a). A filer whose W-2 wages already
      reach the base owes NO social security portion on the side gig.
    * line 10: social security portion = 12.4% of net earnings capped at the
      REMAINING wage base (line 9).
    * line 11: Medicare portion = 2.9% of net earnings, uncapped.
    * line 12/13: SE tax and the one-half deduction.

    Rounding sequence: cents are kept through every intermediate line
    (Form 1040 instructions: "include cents when adding the amounts and
    round off only the total"); only the final line 12 and line 13 entries
    are rounded to whole dollars.
    """
    profit = _to_decimal(net_profit, "net_profit")
    w2_ss = _to_decimal(w2_ss_wages, "w2_ss_wages")
    if w2_ss < 0:
        raise ValueError(f"w2_ss_wages must be >= 0, got {w2_ss}")
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.se_tax
    citation = params.citation
    inputs: dict[str, Any] = {"net_profit": str(profit), "year": year}
    if w2_ss > 0:
        inputs["w2_ss_wages"] = str(w2_ss)

    # Line 4a: "If line 3 is more than zero, multiply line 3 by 92.35%.
    # Otherwise, enter amount from line 3."
    net_earnings = _cents(profit * params.net_earnings_factor) if profit > 0 else profit

    if net_earnings < params.minimum_net_earnings:
        work = (
            f"Schedule SE ({year}) Part I: line 3 net profit {_money(profit)}; line 4a net earnings = "
            + (
                f"{_money(profit)} x {params.net_earnings_factor} = {_money(net_earnings)}"
                if profit > 0
                else f"{_money(net_earnings)} (zero or negative profit carries down unchanged)"
            )
            + f"; line 4c is less than {_dollars(params.minimum_net_earnings)}, so no self-employment tax "
            f"is owed and there is no one-half-of-SE-tax deduction."
        )
        return SeTaxResult(
            se_tax=0,
            deduction_half=0,
            net_earnings=net_earnings,
            ss_portion=Decimal("0.00"),
            medicare_portion=Decimal("0.00"),
            inputs=inputs,
            work=work,
            citation=citation,
        )

    # Lines 8a-9: W-2 social security wages consume the wage base first.
    remaining_base = max(Decimal(0), Decimal(params.ss_wage_base) - min(w2_ss, Decimal(params.ss_wage_base)))
    ss_taxable = min(net_earnings, remaining_base)
    ss_portion = _cents(ss_taxable * params.ss_rate)
    medicare_portion = _cents(net_earnings * params.medicare_rate)
    line_12 = ss_portion + medicare_portion
    se_tax_amount = irs_round(line_12)
    # Line 13 = 50% of the WHOLE-DOLLAR line 12 that's actually entered on the form (a filer
    # works it line-by-line), NOT 50% of the cents-level sum — the two diverge by $1 when
    # rounding line 12 flips whether x0.5 crosses a half-dollar. This also matches the
    # sched_se relation "13 == 12 * 0.5" the verifier checks against the filled whole dollars.
    deduction_half = irs_round(Decimal(se_tax_amount) * Decimal("0.5"))

    capped = net_earnings > remaining_base
    base_text = (
        f"the {_dollars(params.ss_wage_base)} wage base"
        if w2_ss == 0
        else (
            f"the remaining wage base {_money(remaining_base)} "
            f"(lines 8a-9: {_dollars(params.ss_wage_base)} base - W-2 social security wages {_money(w2_ss)})"
        )
    )
    ss_text = (
        f"line 10 social security portion = {params.ss_rate * 100:.1f}% x {_money(ss_taxable)}"
        + (f" (net earnings capped at {base_text})" if capped else (f" ({base_text} applies)" if w2_ss > 0 else ""))
        + f" = {_money(ss_portion)}"
    )
    work = (
        f"Schedule SE ({year}) Part I: line 3 net profit {_money(profit)}; "
        f"line 4a net earnings = {_money(profit)} x {params.net_earnings_factor} = {_money(net_earnings)} "
        f"(at least {_dollars(params.minimum_net_earnings)}, so SE tax applies); "
        f"{ss_text}; "
        f"line 11 Medicare portion = {params.medicare_rate * 100:.1f}% x {_money(net_earnings)} "
        f"= {_money(medicare_portion)} (no cap); "
        f"line 12 SE tax = {_money(line_12)}, rounded = {_dollars(se_tax_amount)}; "
        f"line 13 deduction for one-half of SE tax = 50% x {_dollars(se_tax_amount)} "
        f"(the whole-dollar line 12) = {_dollars(deduction_half)}. "
        f"Cents kept through intermediate lines; only final entries rounded."
    )
    return SeTaxResult(
        se_tax=se_tax_amount,
        deduction_half=deduction_half,
        net_earnings=net_earnings,
        ss_portion=ss_portion,
        medicare_portion=medicare_portion,
        inputs=inputs,
        work=work,
        citation=citation,
    )


# ---------------------------------------------------------------------------
# Additional Medicare Tax (Form 8959 -> Schedule 2 line 11)
# ---------------------------------------------------------------------------


def _surtax_threshold(thresholds: dict[str, int], filing_status: str, where: str) -> int:
    """Resolve a Form 8959/8960 threshold. All five statuses are explicit in the data
    (QSS buckets differently on the two forms), so no MFJ aliasing happens here."""
    if filing_status not in thresholds:
        raise ValueError(
            f"unknown filing_status {filing_status!r} for {where} — use one of: "
            f"{', '.join(sorted(thresholds))}"
        )
    return thresholds[filing_status]


class AdditionalMedicareTaxResult(BaseModel):
    """Result of :func:`additional_medicare_tax`: Form 8959 Parts I-II."""

    model_config = ConfigDict(extra="forbid")

    additional_medicare_tax: int = Field(
        description="Form 8959 line 18, rounded to whole dollars (goes on Schedule 2 line 11)."
    )
    wage_portion: Decimal = Field(description="Part I tax on Medicare wages above the threshold, in cents.")
    se_portion: Decimal = Field(description="Part II tax on SE earnings above the wage-reduced threshold, in cents.")
    threshold: int = Field(description="The filing-status threshold applied (statutory, not indexed).")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def additional_medicare_tax(
    medicare_wages: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2023,
    se_net_profit: int | float | Decimal | str = 0,
    knowledge_dir: str | Path | None = None,
) -> AdditionalMedicareTaxResult:
    """Additional Medicare Tax (Form 8959): 0.9% of Medicare wages and SE earnings
    above the filing-status threshold.

    Mechanics per Form 8959:

    * Part I (wages): 0.9% x max(0, Medicare wages - threshold).
    * Part II (self-employment): the threshold is first REDUCED by Medicare wages
      (floor 0), then 0.9% applies to SE net earnings (Schedule SE line 6 =
      net profit x 92.35%) above the reduced threshold. Below the $400 Schedule SE
      minimum no SE component applies (no Schedule SE is filed).
    * Thresholds are statutory (unchanged since 2013): $250,000 MFJ, $125,000 MFS,
      $200,000 single / head of household / qualifying surviving spouse. NOTE the
      QSS bucket differs from NIIT's — the data carries all five explicitly.
    * RRTA compensation (Part III, railroad) is out of scope.

    Any Additional Medicare Tax an employer already withheld (W-2 box 6 above
    1.45% of box 5) is credited as federal income tax withholding via Part IV —
    it offsets this liability on the return but is not modeled here.
    """
    wages = _to_decimal(medicare_wages, "medicare_wages")
    profit = _to_decimal(se_net_profit, "se_net_profit")
    if wages < 0:
        raise ValueError(f"medicare_wages must be >= 0, got {wages}")
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.additional_medicare_tax
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.additional_medicare_tax block — "
            f"add it (rate 0.009 + the five statutory thresholds) with a citation"
        )
    threshold = _surtax_threshold(params.thresholds, filing_status, "additional_medicare_tax")
    inputs: dict[str, Any] = {
        "medicare_wages": str(wages),
        "se_net_profit": str(profit),
        "filing_status": filing_status,
        "year": year,
    }

    wage_excess = max(Decimal(0), wages - threshold)
    wage_portion = _cents(wage_excess * params.rate)

    # Part II: SE net earnings above the wage-reduced threshold. Reuse the Schedule SE
    # parameters so the 92.35% factor and the $400 minimum stay single-sourced.
    se_params = pack.tax.se_tax
    net_earnings = _cents(profit * se_params.net_earnings_factor) if profit > 0 else Decimal(0)
    se_portion = Decimal("0.00")
    reduced_threshold = max(Decimal(0), Decimal(threshold) - wages)
    if net_earnings >= se_params.minimum_net_earnings:
        se_excess = max(Decimal(0), net_earnings - reduced_threshold)
        se_portion = _cents(se_excess * params.rate)

    # The form rounds line 7 (wages) and line 13 (SE) SEPARATELY, then sums on line 18 —
    # rounding the cents-sum once diverges by $1 when the two fractions straddle .50.
    total = irs_round(wage_portion) + irs_round(se_portion)
    rate_pct = f"{params.rate * 100:.1f}%"
    work = (
        f"Form 8959 ({year}), {filing_status} threshold {_dollars(threshold)}: "
        f"Part I wages {_money(wages)} - threshold = {_money(wage_excess)} excess, "
        f"x {rate_pct} = {_money(wage_portion)}"
        + (
            f"; Part II SE net earnings {_money(net_earnings)} vs threshold reduced by wages "
            f"to {_money(reduced_threshold)} = {_money(max(Decimal(0), net_earnings - reduced_threshold))} "
            f"excess, x {rate_pct} = {_money(se_portion)}"
            if net_earnings >= se_params.minimum_net_earnings
            else "; Part II: no SE component (below the $400 Schedule SE minimum)"
        )
        + f"; total Additional Medicare Tax = {_dollars(total)} (Schedule 2 line 11). "
        f"Employer box-6 excess withholding credits against this via Part IV."
    )
    return AdditionalMedicareTaxResult(
        additional_medicare_tax=total,
        wage_portion=wage_portion,
        se_portion=se_portion,
        threshold=threshold,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Net Investment Income Tax (Form 8960 -> Schedule 2 line 12)
# ---------------------------------------------------------------------------


class NiitResult(BaseModel):
    """Result of :func:`niit`: Form 8960 lines 8/13-17 (simplified: no investment-expense
    allocations; net investment income is passed in already netted)."""

    model_config = ConfigDict(extra="forbid")

    niit: int = Field(description="Form 8960 line 17, rounded to whole dollars (goes on Schedule 2 line 12).")
    base: Decimal = Field(description="The lesser of net investment income or the MAGI excess, in cents.")
    magi_excess: Decimal = Field(description="max(0, MAGI - threshold), in cents.")
    threshold: int = Field(description="The filing-status MAGI threshold applied (statutory, not indexed).")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def niit(
    net_investment_income: int | float | Decimal | str,
    magi: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2023,
    knowledge_dir: str | Path | None = None,
) -> NiitResult:
    """Net Investment Income Tax (Form 8960): 3.8% of the LESSER of net investment
    income or MAGI above the filing-status threshold.

    * Investment income = interest, dividends, capital gains, rental/royalty and
      passive income — NOT wages or self-employment income. Pass it already netted
      of allocable investment expenses (this helper does no expense allocation).
    * Thresholds are statutory: $250,000 MFJ AND qualifying surviving spouse,
      $125,000 MFS, $200,000 single / head of household. NOTE the QSS bucket
      differs from Form 8959's — the data carries all five explicitly.
    * Nonresident aliens are generally NOT subject to NIIT (Form 8960 instructions);
      callers handling NRA filers should skip this computation.
    """
    nii = _to_decimal(net_investment_income, "net_investment_income")
    magi_d = _to_decimal(magi, "magi")
    if nii < 0:
        nii = Decimal(0)  # a net investment LOSS just means no NIIT base
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.niit
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.niit block — "
            f"add it (rate 0.038 + the five statutory MAGI thresholds) with a citation"
        )
    threshold = _surtax_threshold(params.thresholds, filing_status, "niit")
    inputs: dict[str, Any] = {
        "net_investment_income": str(nii),
        "magi": str(magi_d),
        "filing_status": filing_status,
        "year": year,
    }

    magi_excess = _cents(max(Decimal(0), magi_d - threshold))
    base = min(_cents(nii), magi_excess)
    amount = irs_round(base * params.rate)
    work = (
        f"Form 8960 ({year}), {filing_status} MAGI threshold {_dollars(threshold)}: "
        f"MAGI {_money(magi_d)} - threshold = {_money(magi_excess)} excess; "
        f"net investment income {_money(_cents(nii))}; base = lesser = {_money(base)}; "
        f"x {params.rate * 100:.1f}% = NIIT {_dollars(amount)} (Schedule 2 line 12)."
    )
    return NiitResult(
        niit=amount,
        base=base,
        magi_excess=magi_excess,
        threshold=threshold,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Tax with preferential rates (Qualified Dividends and Capital Gain Tax
# Worksheet -> Form 1040 line 16)
# ---------------------------------------------------------------------------


class PreferentialRatesTaxResult(BaseModel):
    """Result of :func:`tax_with_preferential_rates`: the Qualified Dividends and
    Capital Gain Tax Worksheet (2023 line numbering; the 2019 edition computed
    Form 1040 line 12a — same arithmetic)."""

    model_config = ConfigDict(extra="forbid")

    tax: int = Field(
        description="Worksheet line 25 — the SMALLER of the worksheet tax and the all-ordinary tax — for Form 1040 line 16."
    )
    preferential_income: Decimal = Field(
        description="Line 4 clamped to taxable income (line 10): qualified dividends + net capital gain, in cents."
    )
    ordinary_part: Decimal = Field(
        description="Line 5: taxable income minus preferential income (floor 0), in cents — stacked BELOW the preferential income."
    )
    amount_at_0pct: Decimal = Field(description="Line 9: preferential income absorbed by the 0% bracket, in cents.")
    amount_at_15pct: Decimal = Field(description="Line 17: preferential income taxed at 15%, in cents.")
    amount_at_20pct: Decimal = Field(description="Line 20: preferential income taxed at 20%, in cents.")
    tax_on_ordinary_part: int = Field(
        description="Line 22: ordinary tax on line 5 (Tax Table below $100,000, rate schedule at/above)."
    )
    all_ordinary_tax: int = Field(
        description="Line 24: ordinary tax on the whole taxable income — the line-25 comparison value."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def tax_with_preferential_rates(
    taxable_income: int | float | Decimal | str,
    qualified_dividends: int | float | Decimal | str,
    net_long_term_gain: int | float | Decimal | str = 0,
    net_short_term_gain: int | float | Decimal | str = 0,
    filing_status: str = "single",
    year: int = 2023,
    knowledge_dir: str | Path | None = None,
) -> PreferentialRatesTaxResult:
    """Form 1040 line 16 tax WITH qualified dividends / net capital gain — the
    Qualified Dividends and Capital Gain Tax Worksheet.

    This is the worksheet :func:`tax_from_taxable_income` explicitly scopes
    out: any return with qualified dividends or a net capital gain computes
    line 16 here EVEN BELOW $100,000. Line sequence (2023 numbering):

    * lines 1-4: preferential income = qualified dividends + net capital
      gain. Net capital gain is Schedule D's "smaller of line 15 or line 16,
      but not less than zero", i.e. max(0, net_LT + min(net_ST, 0)): a
      short-term LOSS offsets the long-term gain, a short-term GAIN is
      ordinary income (never preferential), and a long-term loss leaves
      qualified dividends only.
    * line 5: ordinary part = taxable income - preferential (floor 0). The
      worksheet stacks ordinary income BELOW preferential income, so the
      ordinary part fills the rate brackets first.
    * lines 6-9: whatever room the zero-rate breakpoint (line 6, from the
      knowledge pack's ``capital_gains_brackets.max_zero_rate_amount``)
      leaves above the ordinary part is taxed at 0%.
    * lines 13-18: the slice up to the 15% breakpoint (line 13,
      ``max_15_percent_rate_amount``) is taxed at 15%.
    * lines 19-21: any remainder is taxed at 20%.
    * lines 22/24: ordinary tax on line 5 / line 1 via
      :func:`tax_from_taxable_income` (the worksheet's own rule — Tax Table
      below $100,000, Tax Computation Worksheet at or above — is exactly
      that function's switch).
    * line 25: the SMALLER of line 23 (worksheet total) and line 24
      (all-ordinary tax).

    Rounding: like a filer working the printed worksheet, each tax COMPONENT
    is rounded to whole dollars where the form computes it — line 18
    (x 0.15) and line 21 (x 0.20) individually, lines 22/24 already
    whole-dollar — and line 23 sums the whole-dollar entries. Income amounts
    keep cents through lines 1-20.

    Out of scope: the Schedule D Tax Worksheet's 25%/28% components
    (unrecaptured section 1250 gain, collectibles) — a return with either
    must use that worksheet instead.
    """
    income = _to_decimal(taxable_income, "taxable_income")
    qd = _to_decimal(qualified_dividends, "qualified_dividends")
    lt = _to_decimal(net_long_term_gain, "net_long_term_gain")
    st = _to_decimal(net_short_term_gain, "net_short_term_gain")
    if income < 0:
        raise ValueError(
            f"taxable_income cannot be negative (got {income}) — Form 1040 line 15 cannot go below zero; "
            f"pass 0 for a zero-or-negative taxable income"
        )
    if qd < 0:
        raise ValueError(
            f"qualified_dividends must be >= 0 (got {qd}) — Form 1040 line 3a is never negative; "
            f"capital LOSSES belong in net_long_term_gain/net_short_term_gain"
        )
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.capital_gains_brackets
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.capital_gains_brackets block — add it "
            f"(the Rev. Proc. section 3.03 maximum zero-rate and 15%-rate taxable-income ceilings, "
            f"all five statuses explicit) with a citation"
        )
    status = str(filing_status)
    zero_ceiling = _surtax_threshold(params.max_zero_rate_amount, status, "capital_gains_brackets")
    fifteen_ceiling = _surtax_threshold(params.max_15_percent_rate_amount, status, "capital_gains_brackets")
    inputs: dict[str, Any] = {
        "taxable_income": str(income),
        "qualified_dividends": str(qd),
        "net_long_term_gain": str(lt),
        "net_short_term_gain": str(st),
        "filing_status": status,
        "year": year,
    }

    zero = Decimal(0)
    net_capital_gain = max(zero, lt + min(st, zero))  # line 3 (Sch D smaller of 15/16, floor 0)
    line4 = _cents(qd + net_capital_gain)  # total preferential income
    line5 = max(zero, income - line4)  # ordinary part
    line7 = min(income, Decimal(zero_ceiling))
    line8 = min(line5, line7)
    line9 = line7 - line8  # taxed at 0%
    line10 = min(income, line4)  # preferential income, clamped to taxable income
    line12 = line10 - line9
    line14 = min(income, Decimal(fifteen_ceiling))
    line15 = line5 + line9
    line16 = max(zero, line14 - line15)
    line17 = min(line12, line16)  # taxed at 15%
    line18 = irs_round(_cents(line17 * Decimal("0.15")))
    line20 = line10 - (line9 + line17)  # taxed at 20%
    line21 = irs_round(_cents(line20 * Decimal("0.20")))
    line22 = tax_from_taxable_income(line5, filing_status, year, knowledge_dir).tax
    line23 = line18 + line21 + line22
    line24 = tax_from_taxable_income(income, filing_status, year, knowledge_dir).tax
    tax = min(line23, line24)

    gain_text = (
        f"net capital gain = max(0, LT {_money(lt)} + min(ST {_money(st)}, 0)) = {_money(net_capital_gain)}"
    )
    work = (
        f"Qualified Dividends and Capital Gain Tax Worksheet ({year}, {status}): taxable income "
        f"{_money(income)}; {gain_text}; preferential income = qualified dividends {_money(qd)} + "
        f"{_money(net_capital_gain)} = {_money(line4)} (line 10 clamps it to {_money(line10)}); "
        f"line 5 ordinary part = {_money(line5)} (stacked below the preferential income). "
        f"0% bracket to {_dollars(zero_ceiling)}: {_money(line9)} taxed at 0%; "
        f"15% bracket to {_dollars(fifteen_ceiling)}: {_money(line17)} x 15% = {_dollars(line18)}; "
        f"20% above: {_money(line20)} x 20% = {_dollars(line21)}; "
        f"line 22 ordinary tax on {_money(line5)} = {_dollars(line22)}; "
        f"line 23 worksheet tax = {_dollars(line23)}; line 24 all-ordinary tax on {_money(income)} = "
        f"{_dollars(line24)}; line 25 tax = smaller = {_dollars(tax)} (Form 1040 line 16). "
        f"Each tax component rounded to whole dollars where the worksheet computes it."
    )
    return PreferentialRatesTaxResult(
        tax=tax,
        preferential_income=_cents(line10),
        ordinary_part=_cents(line5),
        amount_at_0pct=_cents(line9),
        amount_at_15pct=_cents(line17),
        amount_at_20pct=_cents(line20),
        tax_on_ordinary_part=line22,
        all_ordinary_tax=line24,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Taxable Social Security benefits (SS Benefits Worksheet -> Form 1040 line 6b)
# ---------------------------------------------------------------------------


class TaxableSocialSecurityResult(BaseModel):
    """Result of :func:`taxable_social_security`: the Social Security Benefits
    Worksheet (Form 1040 line 6b; line 5b in 2019)."""

    model_config = ConfigDict(extra="forbid")

    taxable_benefits: int = Field(
        description="Worksheet line 18, rounded to whole dollars (goes on Form 1040 line 6b)."
    )
    provisional_income: Decimal = Field(
        description="Worksheet line 7: other income + tax-exempt interest + 50% of benefits, in cents."
    )
    base_amount: int = Field(description="First-tier threshold applied (line 8); 0 for MFS who lived with the spouse.")
    adjusted_base_amount: int = Field(
        description="Second-tier threshold applied (IRC 86(c)(2)); 0 for MFS who lived with the spouse."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def taxable_social_security(
    benefits: int | float | Decimal | str,
    other_income: int | float | Decimal | str,
    tax_exempt_interest: int | float | Decimal | str = 0,
    filing_status: str = "single",
    year: int = 2023,
    mfs_lived_with_spouse: bool = False,
    knowledge_dir: str | Path | None = None,
) -> TaxableSocialSecurityResult:
    """Taxable Social Security benefits — the Social Security Benefits Worksheet
    (Form 1040 line 6b; line 5b in 2019). Thresholds are statutory (IRC 86(c),
    never indexed), identical in every supported year.

    ``other_income`` is total income WITHOUT Social Security (the worksheet's
    line 3 concept — 1040 lines 1z, 2b, 3b, 4b, 5b, 7, 8 for 2023), already
    net of the line-6 adjustments EXCLUDING the student-loan-interest
    deduction (IRC 86(b)(2) figures modified AGI without section 221).

    Line sequence, per the 2023 worksheet:

    * line 2: 50% of benefits; line 7 provisional income = other income +
      tax-exempt interest + line 2.
    * MFS who lived WITH the spouse at ANY time during the year (a RULE, not
      a threshold column): skip lines 8-15 — taxable =
      min(0.85 x provisional income, 0.85 x benefits).
    * line 8: base amount (25,000 / 32,000 MFJ; MFS who lived apart ALL year
      uses the single amounts and writes "D" next to the benefits line). At
      or below it, nothing is taxable.
    * lines 9-14 (50% tier): the excess over the base, capped at the line-10
      gap (adjusted base - base: 9,000 / 12,000 MFJ), is halved and capped
      at line 2.
    * line 15 (85% tier): 85% of the excess over the ADJUSTED base amount.
    * lines 16-18: taxable = min(tier sum, 0.85 x benefits).

    Cents are kept through every intermediate line; only the final line-18
    entry is rounded to whole dollars.

    Out of scope (Pub 915 worksheets required): savings-bond interest,
    employer adoption benefits, foreign earned income / territory exclusions,
    and the covered-by-workplace-plan IRA-deduction interaction.
    """
    b = _to_decimal(benefits, "benefits")
    other = _to_decimal(other_income, "other_income")
    tei = _to_decimal(tax_exempt_interest, "tax_exempt_interest")
    if b < 0:
        raise ValueError(f"benefits must be >= 0, got {b} — pass the SSA-1099 box 5 total")
    if tei < 0:
        raise ValueError(f"tax_exempt_interest must be >= 0, got {tei}")
    status = str(filing_status)
    if mfs_lived_with_spouse and status != "married_filing_separately":
        raise ValueError(
            f"mfs_lived_with_spouse=True only applies to filing_status 'married_filing_separately' "
            f"(got {status!r}) — the lived-with-spouse rule is an MFS behavior split"
        )
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.taxable_social_security
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.taxable_social_security block — add it "
            f"(the IRC 86(c) base/adjusted-base amounts and 0.50/0.85 rates) with a citation"
        )
    inputs: dict[str, Any] = {
        "benefits": str(b),
        "other_income": str(other),
        "tax_exempt_interest": str(tei),
        "filing_status": status,
        "year": year,
    }
    if status == "married_filing_separately":
        inputs["mfs_lived_with_spouse"] = mfs_lived_with_spouse

    line2 = _cents(b * params.inclusion_rate_tier1)
    provisional = _cents(line2 + other + tei)  # line 7

    if status == "married_filing_separately" and mfs_lived_with_spouse:
        line16 = _cents(max(Decimal(0), provisional) * params.inclusion_rate_tier2)
        line17 = _cents(b * params.max_taxable_share_of_benefits)
        taxable = irs_round(min(line16, line17))
        base = adjusted = params.mfs_living_with_spouse_base
        work = (
            f"Social Security Benefits Worksheet ({year}), married filing separately having lived WITH "
            f"the spouse during the year: both thresholds are $0 by rule (IRC 86(c)), so lines 8-15 are "
            f"skipped. Provisional income = other income {_money(other)} + tax-exempt interest "
            f"{_money(tei)} + 50% x benefits {_money(b)} = {_money(provisional)}; taxable = "
            f"min(85% x provisional = {_money(line16)}, 85% x benefits = {_money(line17)}) "
            f"= {_dollars(taxable)} (Form 1040 line 6b)."
        )
        return TaxableSocialSecurityResult(
            taxable_benefits=taxable,
            provisional_income=provisional,
            base_amount=base,
            adjusted_base_amount=adjusted,
            inputs=inputs,
            work=work,
            citation=params.citation,
        )

    key = "married_filing_separately_lived_apart_all_year" if status == "married_filing_separately" else status
    if key not in params.base_amount:
        raise ValueError(
            f"unknown filing_status {status!r} for taxable_social_security — use one of: single, "
            f"married_filing_jointly, married_filing_separately, head_of_household, "
            f"qualifying_surviving_spouse (for married_filing_separately, set mfs_lived_with_spouse)"
        )
    base = params.base_amount[key]
    adjusted = params.adjusted_base_amount[key]
    status_label = status if key == status else f"{status} (lived apart from the spouse all year)"
    prefix = (
        f"Social Security Benefits Worksheet ({year}, {status_label}): provisional income = other income "
        f"{_money(other)} + tax-exempt interest {_money(tei)} + 50% x benefits {_money(b)} "
        f"= {_money(provisional)}"
    )

    if provisional <= base:
        work = (
            f"{prefix}; at or below the {_dollars(base)} base amount (line 8), so NO benefits are "
            f"taxable — Form 1040 line 6b is 0."
        )
        return TaxableSocialSecurityResult(
            taxable_benefits=0,
            provisional_income=provisional,
            base_amount=base,
            adjusted_base_amount=adjusted,
            inputs=inputs,
            work=work,
            citation=params.citation,
        )

    line9 = provisional - base
    line10 = Decimal(adjusted - base)  # the printed line-10 gap (9,000 / 12,000 MFJ)
    line11 = max(Decimal(0), line9 - line10)
    line12 = min(line9, line10)
    line13 = _cents(line12 / 2)
    line14 = min(line2, line13)
    line15 = _cents(line11 * params.inclusion_rate_tier2)
    line16 = line14 + line15
    line17 = _cents(b * params.max_taxable_share_of_benefits)
    taxable = irs_round(min(line16, line17))
    work = (
        f"{prefix}; excess over the {_dollars(base)} base = {_money(line9)}; 50% tier = "
        f"min(half of min(excess, {_dollars(line10)} gap) = {_money(line13)}, half of benefits "
        f"{_money(line2)}) = {_money(line14)}; 85% tier = 85% x {_money(line11)} excess over the "
        f"{_dollars(adjusted)} adjusted base = {_money(line15)}; sum {_money(line16)} capped at "
        f"85% x benefits = {_money(line17)}; taxable = {_dollars(taxable)} (Form 1040 line 6b). "
        f"Cents kept through intermediate lines; only the final entry rounded."
    )
    return TaxableSocialSecurityResult(
        taxable_benefits=taxable,
        provisional_income=provisional,
        base_amount=base,
        adjusted_base_amount=adjusted,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Excess social security withholding credit (Schedule 3 line 11; line 10 in 2020)
# ---------------------------------------------------------------------------


class ExcessSsResult(BaseModel):
    """Result of :func:`excess_ss`: the excess-social-security / tier 1 RRTA
    withholding credit (Schedule 3, Part II)."""

    model_config = ConfigDict(extra="forbid")

    credit: int = Field(
        description="The claimable credit, rounded to whole dollars (Schedule 3 line 11; line 10 on the 2020 schedule)."
    )
    max_withholding: Decimal = Field(description="The year's per-person maximum withholding (rate x wage base).")
    counted_total: Decimal = Field(
        description="Sum of per-employer withholding with each employer capped at the maximum, in cents."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def excess_ss(
    withheld_by_employer: list,
    year: int = 2023,
    knowledge_dir: str | Path | None = None,
) -> ExcessSsResult:
    """Excess social security withholding credit (Schedule 3, Part II).

    ``withheld_by_employer`` is ONE PERSON's W-2 box 4 amounts, one entry per
    employer. The cap is PER PERSON: on a joint return compute each spouse
    separately, never combined.

    Rules per the Form 1040 instructions (Schedule 3) and Topic 608:

    * The credit exists only with MULTIPLE employers: with fewer than two
      entries the credit is 0 — a single employer's over-withholding must be
      recovered FROM THE EMPLOYER (it adjusts the error; file Form 843 if it
      refuses), never claimed on the return.
    * With two or more employers, any single employer's withholding ABOVE the
      per-person maximum is likewise an employer error — it is excluded from
      the credit (clipped to the maximum) and flagged in ``work``.
    * credit = max(0, sum of the capped per-employer amounts - the per-person
      maximum), rounded to whole dollars at the end (cents kept until then).

    Tier 1 RRTA follows the same rate/cap; excess TIER 2 RRTA is never
    claimable on Form 1040 (Form 843 only) and is out of scope here.
    """
    if isinstance(withheld_by_employer, (str, bytes)) or not isinstance(withheld_by_employer, (list, tuple)):
        raise TypeError(
            f"withheld_by_employer must be a list of per-employer W-2 box 4 amounts "
            f"(one entry per employer, one person's W-2s only), got {type(withheld_by_employer).__name__}"
        )
    amounts = [_to_decimal(v, f"withheld_by_employer[{i}]") for i, v in enumerate(withheld_by_employer)]
    for i, amount in enumerate(amounts):
        if amount < 0:
            raise ValueError(f"withheld_by_employer[{i}] must be >= 0, got {amount}")
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.employee_social_security
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.employee_social_security block — add it "
            f"(the 6.2% employee rate, wage base, and per-person maximum withholding) with a citation"
        )
    max_wh = params.max_withholding
    inputs: dict[str, Any] = {
        "withheld_by_employer": [str(a) for a in amounts],
        "year": year,
    }
    capped = [min(a, max_wh) for a in amounts]
    counted_total = _cents(sum(capped, Decimal(0)))

    if len(amounts) < 2:
        if not amounts:
            detail = "no employers were given, so there is no withholding and no credit."
        elif amounts[0] > max_wh:
            detail = (
                f"the single employer withheld {_money(amounts[0])}, {_money(amounts[0] - max_wh)} OVER the "
                f"{_money(max_wh)} per-person maximum — that excess is an employer error and can NEVER be "
                f"claimed on the return: the employer must adjust/refund it; if it refuses, file Form 843."
            )
        else:
            detail = (
                f"the single employer withheld {_money(amounts[0])}, within the {_money(max_wh)} per-person "
                f"maximum — nothing was over-withheld."
            )
        work = (
            f"Excess social security withholding ({year}): the credit exists only when MULTIPLE employers "
            f"together withheld more than {_money(max_wh)} (6.2% x the {_dollars(params.ss_wage_base)} wage "
            f"base); {detail} Credit = $0."
        )
        return ExcessSsResult(
            credit=0,
            max_withholding=max_wh,
            counted_total=counted_total,
            inputs=inputs,
            work=work,
            citation=params.citation,
        )

    clipped = [i for i, a in enumerate(amounts) if a > max_wh]
    credit_exact = max(Decimal(0), counted_total - max_wh)
    credit = irs_round(credit_exact)
    clip_text = (
        " Employer(s) "
        + ", ".join(
            f"#{i + 1} ({_money(amounts[i])}, counted as {_money(max_wh)})" for i in clipped
        )
        + " withheld more than the per-person maximum — that excess is an employer error, excluded from "
        "the credit (recover it from the employer; Form 843 if it refuses)."
        if clipped
        else ""
    )
    work = (
        f"Excess social security withholding ({year}), {len(amounts)} employers: per-person maximum = "
        f"{_money(max_wh)} (6.2% x {_dollars(params.ss_wage_base)} wage base); counted withholding = "
        f"{' + '.join(_money(c) for c in capped)} = {_money(counted_total)}; credit = "
        f"{_money(counted_total)} - {_money(max_wh)} = {_money(credit_exact)}, rounded = {_dollars(credit)} "
        f"(Schedule 3{', line 10 in 2020' if year == 2020 else ' line 11'}). Computed per person — "
        f"never combine spouses' withholding.{clip_text}"
    )
    return ExcessSsResult(
        credit=credit,
        max_withholding=max_wh,
        counted_total=counted_total,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Student loan interest deduction (section 221 -> Schedule 1)
# ---------------------------------------------------------------------------


class StudentLoanInterestResult(BaseModel):
    """Result of :func:`student_loan_interest_deduction` (Schedule 1 line 21 in 2023)."""

    model_config = ConfigDict(extra="forbid")

    deduction: int = Field(description="The allowed deduction, rounded to whole dollars (Schedule 1).")
    tentative: Decimal = Field(
        description="min(interest paid, the statutory cap), in cents — what the phase-out ratio applies to."
    )
    reduction: Decimal = Field(description="Phase-out reduction subtracted from the tentative deduction, in cents.")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def student_loan_interest_deduction(
    interest_paid: int | float | Decimal | str,
    magi: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2023,
    knowledge_dir: str | Path | None = None,
) -> StudentLoanInterestResult:
    """Student loan interest deduction (IRC section 221; the Pub 970 / Schedule 1
    worksheet).

    * Tentative deduction = min(interest paid, the statutory $2,500 cap).
    * MFS: married filing separately may not take the deduction AT ALL
      (IRC 221(e)(2)) — the result is $0 by rule (not an error), regardless
      of MAGI or interest paid.
    * Phase-out (per the Pub 970 worksheet): reduction = tentative x
      (MAGI - start) / (end - start) — the ratio applies to the TENTATIVE
      deduction, not to a flat $2,500; fully eliminated at MAGI >= end.
    * Rounding: the reduction is computed exactly (cents) and the final
      deduction is rounded to whole dollars with :func:`irs_round` at the
      end. (The printed worksheet rounds the ratio to at least three decimal
      places, which can differ by up to a dollar; exact-then-round is used
      here so the derivation is reproducible.)

    Out of scope (caller judgment): the taxpayer being claimable as a
    dependent (deduction disallowed), and the section 221 MAGI definition
    (AGI before this deduction and before the foreign income exclusions).
    """
    paid = _to_decimal(interest_paid, "interest_paid")
    magi_d = _to_decimal(magi, "magi")
    if paid < 0:
        raise ValueError(f"interest_paid must be >= 0, got {paid}")
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.student_loan_interest
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.student_loan_interest block — add it "
            f"(the $2,500 cap and per-status MAGI phase-out ranges, no MFS key) with a citation"
        )
    status = str(filing_status)
    inputs: dict[str, Any] = {
        "interest_paid": str(paid),
        "magi": str(magi_d),
        "filing_status": status,
        "year": year,
    }

    if status == "married_filing_separately":
        work = (
            f"Student loan interest deduction ({year}): married filing separately may not take the "
            f"deduction at all (IRC 221(e)(2)) — $0 regardless of MAGI or interest paid. This is a rule, "
            f"not a phase-out."
        )
        return StudentLoanInterestResult(
            deduction=0,
            tentative=Decimal("0.00"),
            reduction=Decimal("0.00"),
            inputs=inputs,
            work=work,
            citation=params.citation,
        )
    if status not in params.phaseout:
        raise ValueError(
            f"unknown filing_status {status!r} for student_loan_interest_deduction — use one of: "
            f"{', '.join(sorted(params.phaseout))}, married_filing_separately (which gets $0 by rule)"
        )
    rng = params.phaseout[status]
    tentative = _cents(min(paid, Decimal(params.max_deduction)))
    if magi_d >= rng.end:
        reduction = tentative
        deduction = 0
        phase_text = (
            f"MAGI {_money(magi_d)} is at or above the {_dollars(rng.end)} phase-out end, so the "
            f"deduction is fully eliminated"
        )
    elif magi_d <= rng.start:
        reduction = Decimal("0.00")
        deduction = irs_round(tentative)
        phase_text = f"MAGI {_money(magi_d)} is at or below the {_dollars(rng.start)} phase-out start (no reduction)"
    else:
        reduction = _cents(tentative * (magi_d - rng.start) / Decimal(rng.end - rng.start))
        deduction = irs_round(tentative - reduction)
        phase_text = (
            f"phase-out: {_money(tentative)} x (MAGI {_money(magi_d)} - {_dollars(rng.start)}) / "
            f"{_dollars(rng.end - rng.start)} = {_money(reduction)} reduction"
        )
    work = (
        f"Student loan interest deduction ({year}, {status}): tentative = min(interest paid {_money(paid)}, "
        f"{_dollars(params.max_deduction)} cap) = {_money(tentative)}; {phase_text}; deduction = "
        f"{_dollars(deduction)} (rounded to whole dollars at the end)."
    )
    return StudentLoanInterestResult(
        deduction=deduction,
        tentative=tentative,
        reduction=reduction,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Education credits (Form 8863: AOTC + LLC)
# ---------------------------------------------------------------------------


def _phaseout_multiplier(magi: Decimal, rng: MagiPhaseoutRange) -> Decimal:
    """Form 8863-style linear phase-out multiplier: (end - MAGI) / (end - start), clamped to [0, 1]."""
    if magi <= rng.start:
        return Decimal(1)
    if magi >= rng.end:
        return Decimal(0)
    return (Decimal(rng.end) - magi) / Decimal(rng.end - rng.start)


class EducationCreditsResult(BaseModel):
    """Result of :func:`education_credits`: Form 8863 (AOTC per student + LLC per return)."""

    model_config = ConfigDict(extra="forbid")

    total_credit: int = Field(description="AOTC + LLC after phase-out, whole dollars.")
    aotc_total: int = Field(description="American opportunity credit after phase-out, whole dollars.")
    aotc_refundable: int = Field(
        description="Refundable part of the AOTC (40% of the post-phase-out credit, Form 8863 line 8)."
    )
    llc_amount: int = Field(description="Lifetime learning credit after phase-out, whole dollars (nonrefundable).")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def education_credits(
    aotc_expenses_per_student: list,
    llc_expenses: int | float | Decimal | str = 0,
    magi: int | float | Decimal | str = 0,
    filing_status: str = "single",
    year: int = 2023,
    knowledge_dir: str | Path | None = None,
) -> EducationCreditsResult:
    """Education credits (Form 8863): American opportunity credit + lifetime
    learning credit.

    * AOTC, PER STUDENT: 100% of the first $2,000 of qualified expenses plus
      25% of the next $2,000 — at most $2,500 per student; sum over
      ``aotc_expenses_per_student``.
    * LLC, PER RETURN: 20% of at most $10,000 of qualified expenses
      regardless of student count. The same student's expenses can never
      feed both credits in one year (caller responsibility).
    * Each credit is phased out linearly by its OWN MAGI range (Form 8863
      lines 2-7 / 13-18): tentative x (end - MAGI) / (end - start), where
      the range depends only on joint-vs-other (single, head of household,
      and a qualifying surviving spouse share the lower range).
    * MFS: married filing separately may claim NEITHER credit — both are $0
      by rule (not an error), regardless of MAGI.
    * ``aotc_refundable`` = 40% of the post-phase-out AOTC (Form 8863
      line 8). The line-7 under-age-24 exception (which makes the whole AOTC
      nonrefundable) is caller judgment — flagged in ``work``.
    * Rounding: each credit is computed exactly and rounded to whole dollars
      individually (AOTC, then 40% of that whole-dollar AOTC, then LLC), the
      way the form's line entries are made.
    """
    if isinstance(aotc_expenses_per_student, (str, bytes)) or not isinstance(aotc_expenses_per_student, (list, tuple)):
        raise TypeError(
            f"aotc_expenses_per_student must be a list of per-student qualified-expense amounts "
            f"(one entry per eligible student; [] for none), got {type(aotc_expenses_per_student).__name__}"
        )
    expenses = [_to_decimal(v, f"aotc_expenses_per_student[{i}]") for i, v in enumerate(aotc_expenses_per_student)]
    for i, amount in enumerate(expenses):
        if amount < 0:
            raise ValueError(f"aotc_expenses_per_student[{i}] must be >= 0, got {amount}")
    llc_exp = _to_decimal(llc_expenses, "llc_expenses")
    if llc_exp < 0:
        raise ValueError(f"llc_expenses must be >= 0, got {llc_exp}")
    magi_d = _to_decimal(magi, "magi")
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.education_credits
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.education_credits block — add it "
            f"(Form 8863 AOTC/LLC parameters and MAGI phase-outs) with a citation"
        )
    status = str(filing_status)
    inputs: dict[str, Any] = {
        "aotc_expenses_per_student": [str(e) for e in expenses],
        "llc_expenses": str(llc_exp),
        "magi": str(magi_d),
        "filing_status": status,
        "year": year,
    }

    if status == "married_filing_separately":
        work = (
            f"Education credits ({year}): married filing separately may claim NEITHER the American "
            f"opportunity credit nor the lifetime learning credit (Form 8863 rule) — both are $0 "
            f"regardless of MAGI. This is a rule, not a phase-out."
        )
        return EducationCreditsResult(
            total_credit=0,
            aotc_total=0,
            aotc_refundable=0,
            llc_amount=0,
            inputs=inputs,
            work=work,
            citation=params.citation,
        )
    if status == "married_filing_jointly":
        aotc_rng = params.aotc.phaseout.married_filing_jointly
        llc_rng = params.llc.phaseout.married_filing_jointly
    elif status in ("single", "head_of_household", "qualifying_surviving_spouse"):
        aotc_rng = params.aotc.phaseout.other
        llc_rng = params.llc.phaseout.other
    else:
        raise ValueError(
            f"unknown filing_status {status!r} for education_credits — use one of: single, "
            f"married_filing_jointly, married_filing_separately (which gets $0 by rule), "
            f"head_of_household, qualifying_surviving_spouse"
        )

    aotc = params.aotc
    first_cap = Decimal(aotc.first_dollar_cap)
    per_student: list[str] = []
    aotc_tentative = Decimal(0)
    for i, exp in enumerate(expenses):
        tier1 = min(exp, first_cap)
        tier2_base = min(max(Decimal(0), exp - first_cap), first_cap)
        tier2 = _cents(tier2_base * aotc.second_rate)
        credit_i = min(_cents(tier1 + tier2), Decimal(aotc.per_student_cap))
        aotc_tentative += credit_i
        per_student.append(
            f"student {i + 1} (expenses {_money(exp)}): 100% x {_money(tier1)}"
            + (f" + 25% x {_money(tier2_base)} = {_money(credit_i)}" if tier2_base > 0 else f" = {_money(credit_i)}")
        )
    aotc_mult = _phaseout_multiplier(magi_d, aotc_rng)
    aotc_total = irs_round(_cents(aotc_tentative * aotc_mult))
    aotc_refundable = irs_round(Decimal(aotc_total) * aotc.refundable_fraction)

    llc = params.llc
    llc_counted = min(llc_exp, Decimal(llc.per_return_expense_cap))
    llc_tentative = _cents(llc_counted * llc.rate)
    llc_mult = _phaseout_multiplier(magi_d, llc_rng)
    llc_amount = irs_round(_cents(llc_tentative * llc_mult))
    total = aotc_total + llc_amount

    def _mult_text(mult: Decimal, rng: MagiPhaseoutRange) -> str:
        if mult == 1:
            return f"no phase-out (MAGI at or below {_dollars(rng.start)})"
        if mult == 0:
            return f"fully phased out (MAGI at or above {_dollars(rng.end)})"
        return (
            f"phase-out x ({_dollars(rng.end)} - {_money(magi_d)}) / {_dollars(rng.end - rng.start)}"
        )

    aotc_text = (
        "AOTC: no eligible students"
        if not expenses
        else "AOTC per student: " + "; ".join(per_student) + f"; tentative total {_money(aotc_tentative)}, "
        f"{_mult_text(aotc_mult, aotc_rng)} -> {_dollars(aotc_total)}, refundable 40% = "
        f"{_dollars(aotc_refundable)} (Form 8863 line 8; $0 instead if the line-7 under-age-24 "
        f"exception applies)"
    )
    llc_text = (
        "LLC: no expenses"
        if llc_exp == 0
        else f"LLC: 20% x min(expenses {_money(llc_exp)}, {_dollars(llc.per_return_expense_cap)} per return) "
        f"= {_money(llc_tentative)}, {_mult_text(llc_mult, llc_rng)} -> {_dollars(llc_amount)} (nonrefundable)"
    )
    work = (
        f"Education credits ({year}, {status}, MAGI {_money(magi_d)}): {aotc_text}. {llc_text}. "
        f"Total = {_dollars(total)}. Each credit rounded to whole dollars individually."
    )
    return EducationCreditsResult(
        total_credit=total,
        aotc_total=aotc_total,
        aotc_refundable=aotc_refundable,
        llc_amount=llc_amount,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Premium Tax Credit (Form 8962: annual method + lines 12-23 monthly method)
# ---------------------------------------------------------------------------

_PTC_STATES = ("other", "alaska", "hawaii")

_PTC_STATE_LABELS = {"other": "48 contiguous states/DC", "alaska": "Alaska", "hawaii": "Hawaii"}


def _ptc_validate_common(
    income: Decimal, household_size: int, status: str, state: str, mfs_relief_exception: bool
) -> None:
    """Input gates shared by :func:`ptc_annual` and :func:`ptc_monthly` (identical messages)."""
    if income < 0:
        raise ValueError(f"household_income must be >= 0, got {income} — pass 0 for a negative household income")
    if isinstance(household_size, bool) or not isinstance(household_size, int) or household_size < 1:
        raise ValueError(
            f"household_size must be an int >= 1 (the Form 8962 line 1 tax family size), got {household_size!r}"
        )
    _resolve_filing_status(status)  # validates the five statuses
    if mfs_relief_exception and status != "married_filing_separately":
        raise ValueError(
            f"mfs_relief_exception=True only applies to filing_status 'married_filing_separately' "
            f"(got {status!r}) — the domestic-abuse/spousal-abandonment relief is an MFS behavior split"
        )
    if state not in _PTC_STATES:
        raise ValueError(
            f"state must be one of 'other' (the 48 contiguous states and DC), 'alaska', 'hawaii' — "
            f"got {state!r}. A household that lived in both AK/HI and elsewhere uses the table with "
            f"the HIGHER amounts."
        )


def _ptc_params(year: int, knowledge_dir: str | Path | None):
    """The pack's ``tax.ptc`` block, with the prescriptive unshipped-year error."""
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.ptc
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.ptc block — the Premium Tax Credit ships only "
            f"for tax years 2023-2025 (the ARPA applicable-percentage table as extended to 2023-2025 "
            f"by IRA section 12001(a); pre-2023 years use different indexed tables and post-2025 the "
            f"regime expires). Use 2023 or 2024, or author the year's block from its Form 8962 "
            f"instructions with citations."
        )
    return params


def _ptc_lines_4_to_8a(
    income: Decimal, household_size: int, state: str, params
) -> tuple[int, int, str, Decimal, str, int]:
    """Form 8962 lines 4-8a, shared by both methods.

    Returns ``(fpl, fpl_pct, pct_text, figure, figure_text, contribution)`` —
    the line 4 federal poverty line, the line 5 integer percentage (with the
    literal-401 rule applied) and its work fragment, the line 7 Table 2 figure
    and its work fragment, and the line 8a annual contribution amount.
    """
    fpl_table = {
        "other": params.federal_poverty_line.contiguous_48_and_dc,
        "alaska": params.federal_poverty_line.alaska,
        "hawaii": params.federal_poverty_line.hawaii,
    }[state]
    if household_size <= 8:
        fpl = fpl_table.household_size[household_size]
    else:
        fpl = fpl_table.household_size[8] + (household_size - 8) * fpl_table.per_additional_person

    ratio_pct = income * 100 / Decimal(fpl)
    fpl_pct = int(ratio_pct)  # Worksheet 2: TRUNCATE — drop the decimals, never round
    entered_401 = fpl_pct > 400
    if entered_401:
        fpl_pct = 401
    pct_text = (
        f"{fpl_pct} (over 400% — enter literally 401)"
        if entered_401
        else f"{fpl_pct} (TRUNCATED from {ratio_pct:.2f} — decimals dropped, never rounded)"
    )

    band = next(
        b
        for b in params.applicable_percentage_table
        if b.fpl_pct_at_least <= fpl_pct and (b.fpl_pct_less_than is None or fpl_pct < b.fpl_pct_less_than)
    )
    if band.fpl_pct_less_than is None or band.final == band.initial:
        figure = band.initial.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        figure_text = f"Table 2 figure for {fpl_pct} = {figure}"
    else:
        span = band.fpl_pct_less_than - band.fpl_pct_at_least
        figure = (
            band.initial + (band.final - band.initial) * (fpl_pct - band.fpl_pct_at_least) / Decimal(span)
        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        figure_text = (
            f"Table 2 figure for {fpl_pct} (band {band.fpl_pct_at_least}-{band.fpl_pct_less_than}: "
            f"{band.initial}-{band.final}, interpolated on the integer % and rounded half up to "
            f"4 decimals) = {figure}"
        )

    contribution = irs_round(income * figure)
    return fpl, fpl_pct, pct_text, figure, figure_text, contribution


def _ptc_settle(
    params,
    status: str,
    mfs_relief_exception: bool,
    fpl_pct: int,
    computed_ptc: int,
    aptc_whole: int,
    computed_text: str,
    ptc_label: str,
) -> tuple[int, int, int, str, str]:
    """Form 8962 lines 24-29 tail shared by both methods: the applicable-taxpayer
    gates (IRC 36B(c)(1) — the MFS rule and the below-100%-FPL floor), then the
    APTC reconciliation with the Table 5 repayment limitation.

    ``computed_text`` is the method's line 24 derivation fragment; ``ptc_label``
    names the line 24 entry ('annual PTC' / 'total PTC (monthly method)').
    Returns ``(ptc_amount, net_ptc, repayment, line24_text, settle_text)``.
    """
    mfs_denied = status == "married_filing_separately" and not mfs_relief_exception
    below_100 = fpl_pct < 100
    if mfs_denied:
        ptc_amount = 0
        line24_text = (
            f"line 24 {ptc_label} = $0 — a married-filing-separately filer is NOT an applicable "
            f"taxpayer (IRC 36B(c)(1)(C)), so the computed {computed_text} is disallowed and the "
            f"full APTC is excess. The only exception is the domestic-abuse/spousal-abandonment "
            f"relief (the Form 8962 'relief' checkbox) — pass mfs_relief_exception=True to compute "
            f"with it"
        )
    elif below_100 and aptc_whole == 0:
        ptc_amount = 0
        line24_text = (
            f"line 24 {ptc_label} = $0 — household income is below 100% of the federal poverty line "
            f"({fpl_pct}%), so the filer is not an applicable taxpayer (IRC 36B(c)(1)(A)); with NO "
            f"advance PTC paid the estimated-income safe harbor cannot apply (it requires APTC), and "
            f"the lawfully-present-immigrant exception is not modeled here, so the computed "
            f"{computed_text} is disallowed"
        )
    else:
        ptc_amount = computed_ptc
        line24_text = f"line 24 {ptc_label} = {computed_text}"
        if status == "married_filing_separately" and mfs_relief_exception:
            line24_text += (
                " (married filing separately WITH the domestic-abuse/spousal-abandonment relief "
                "exception claimed — the IRC 36B(c)(1)(C) bar does not apply; check the Form 8962 "
                "'relief' box)"
            )
        if below_100:
            line24_text += (
                f". CAVEAT: household income is below 100% of the federal poverty line ({fpl_pct}%), "
                f"where eligibility requires an exception — the estimated-income safe harbor (APTC was "
                f"paid based on a projected income of 100-400% FPL) or the lawfully-present-immigrant "
                f"rule; if neither applies, line 24 PTC is $0 and the full APTC is excess"
            )

    diff = ptc_amount - aptc_whole
    if diff >= 0:
        net_ptc, repayment = diff, 0
        settle_text = (
            f"PTC {_dollars(ptc_amount)} - APTC {_dollars(aptc_whole)} = net premium tax credit "
            f"{_dollars(net_ptc)} (Schedule 3)."
        )
    else:
        excess = -diff
        row = next(r for r in params.repayment_limitation if r.fpl_band_lt is None or fpl_pct < r.fpl_band_lt)
        cap = row.single if status == "single" else row.other
        net_ptc = 0
        if cap is None:
            repayment = excess
            settle_text = (
                f"APTC {_dollars(aptc_whole)} exceeds PTC {_dollars(ptc_amount)} by {_dollars(excess)}; at "
                f"400% FPL or more there is NO repayment limitation (Table 5) — repay the full "
                f"{_dollars(repayment)} (Schedule 2)."
            )
        else:
            repayment = min(excess, cap)
            settle_text = (
                f"APTC {_dollars(aptc_whole)} exceeds PTC {_dollars(ptc_amount)} by {_dollars(excess)}; "
                f"Table 5 limitation for FPL% {fpl_pct} "
                f"({'single' if status == 'single' else 'any other filing status'} column) = "
                f"{_dollars(cap)}; repayment = {_dollars(repayment)} (Schedule 2)."
            )
    return ptc_amount, net_ptc, repayment, line24_text, settle_text


class PtcAnnualResult(BaseModel):
    """Result of :func:`ptc_annual`: Form 8962 lines 1-29, ANNUAL method (no
    monthly allocation, no shared-policy or marriage-year alternatives)."""

    model_config = ConfigDict(extra="forbid")

    fpl_amount: int = Field(description="Line 4: the federal poverty line for the household size and state table.")
    fpl_pct: int = Field(
        description="Line 5: household income as % of the FPL, TRUNCATED to an integer (literally 401 when over 400%)."
    )
    applicable_figure: Decimal = Field(description="Line 7: the Table 2 applicable figure (4 decimals).")
    contribution: int = Field(description="Line 8a: annual contribution amount = income x figure, whole dollars.")
    ptc: int = Field(description="Line 24: annual premium tax credit = min(premiums, SLCSP - contribution), floor 0.")
    net_ptc: int = Field(description="Line 26: PTC in excess of APTC (0 when APTC exceeds PTC).")
    repayment: int = Field(
        description="Line 29: excess APTC repayment after the Table 5 limitation (0 when PTC covers APTC)."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def ptc_annual(
    household_income: int | float | Decimal | str,
    household_size: int,
    annual_premiums: int | float | Decimal | str,
    annual_slcsp: int | float | Decimal | str,
    annual_aptc: int | float | Decimal | str = 0,
    filing_status: str = "single",
    year: int = 2023,
    state: str = "other",
    mfs_relief_exception: bool = False,
    knowledge_dir: str | Path | None = None,
) -> PtcAnnualResult:
    """Premium Tax Credit (Form 8962), ANNUAL method — lines 1-29 with a single
    full-year policy (no monthly allocation, shared policy, or alternative
    marriage-year computation).

    Line sequence, per the Form 8962 instructions:

    * line 4: the federal poverty line — Tables 1-1/1-2/1-3 by ``state``
      ('other' = the 48 contiguous states and DC, 'alaska', 'hawaii'), for
      the household size (sizes above 8 add the per-person increment). A tax
      year uses the PRIOR year's HHS guidelines (already encoded in the pack).
    * line 5 (Worksheet 2): household income / FPL x 100, TRUNCATED to an
      integer — drop the decimals, never round (3.997 -> 399); enter
      literally 401 when over 400%.
    * line 7 (Table 2): the applicable figure for the INTEGER percentage —
      linear interpolation within its band, rounded HALF UP to 4 decimals
      (349 -> 0.0723, 399 -> 0.0848; 0.0850 flat at 400 or more — there is
      NO eligibility cliff). Below-150 rows are 0.0000 per the table.
    * line 8a: contribution = household income x figure, whole dollars.
    * line 24: annual PTC = min(premiums, SLCSP - contribution), floor 0.
    * lines 25-29: against APTC — a surplus is ``net_ptc`` (Schedule 3);
      a shortfall is repaid, capped by the Table 5 limitation for the FPL
      band ('single' vs any other filing status), UNCAPPED at 400% FPL or
      more (Schedule 2). The 400% figure cap and the vanishing repayment
      limitation are different rules — do not conflate them.

    Applicable-taxpayer gates (IRC 36B(c)(1)):

    * MARRIED FILING SEPARATELY is not an applicable taxpayer
      (IRC 36B(c)(1)(C)): by default line 24 PTC = 0, net_ptc = 0, and the
      FULL APTC is excess subject to the Table 5 'other'-column limitation
      (unlimited at 400% FPL or more). ``mfs_relief_exception=True`` claims
      the domestic-abuse/spousal-abandonment relief (the Form 8962 'relief'
      checkbox) and computes the credit normally; it is rejected for any
      other filing status.
    * BELOW 100% FPL (IRC 36B(c)(1)(A)): with NO APTC paid the
      estimated-income safe harbor cannot apply, so line 24 PTC = 0 (the
      lawfully-present-immigrant exception is not modeled). With APTC paid
      the credit is computed normally (the safe harbor commonly applies) and
      the eligibility caveat is spelled out in ``work``.
    """
    income = _to_decimal(household_income, "household_income")
    premiums = _to_decimal(annual_premiums, "annual_premiums")
    slcsp = _to_decimal(annual_slcsp, "annual_slcsp")
    aptc = _to_decimal(annual_aptc, "annual_aptc")
    for name, value in (("annual_premiums", premiums), ("annual_slcsp", slcsp), ("annual_aptc", aptc)):
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")
    status = str(filing_status)
    _ptc_validate_common(income, household_size, status, state, mfs_relief_exception)
    params = _ptc_params(year, knowledge_dir)
    inputs: dict[str, Any] = {
        "household_income": str(income),
        "household_size": household_size,
        "annual_premiums": str(premiums),
        "annual_slcsp": str(slcsp),
        "annual_aptc": str(aptc),
        "filing_status": status,
        "state": state,
        "year": year,
    }
    if status == "married_filing_separately":
        inputs["mfs_relief_exception"] = mfs_relief_exception

    fpl, fpl_pct, pct_text, figure, figure_text, contribution = _ptc_lines_4_to_8a(
        income, household_size, state, params
    )
    computed_ptc = irs_round(min(premiums, max(Decimal(0), slcsp - contribution)))
    aptc_whole = irs_round(aptc)

    # Applicable-taxpayer gates (IRC 36B(c)(1)) — line 24 becomes $0 by RULE —
    # then the APTC reconciliation (Table 5), via the tail shared with ptc_monthly.
    computed_text = (
        f"min(premiums {_money(premiums)}, SLCSP {_money(slcsp)} - contribution = "
        f"{_money(slcsp - contribution)}, floor 0) = {_dollars(computed_ptc)}"
    )
    ptc_amount, net_ptc, repayment, line24_text, settle_text = _ptc_settle(
        params, status, mfs_relief_exception, fpl_pct, computed_ptc, aptc_whole, computed_text, "annual PTC"
    )

    state_label = _PTC_STATE_LABELS[state]
    work = (
        f"Form 8962 ({year}, annual method): line 4 FPL ({state_label} table, household of "
        f"{household_size}) = {_dollars(fpl)}; line 5 = household income {_money(income)} / FPL x 100 = "
        f"{pct_text}; {figure_text}; line 8a contribution = {_money(income)} x {figure} = "
        f"{_dollars(contribution)}; {line24_text}. {settle_text}"
    )
    return PtcAnnualResult(
        fpl_amount=fpl,
        fpl_pct=fpl_pct,
        applicable_figure=figure,
        contribution=contribution,
        ptc=ptc_amount,
        net_ptc=net_ptc,
        repayment=repayment,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


_MONTHS = ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December")
_PTC_MONTH_KEYS = ("premium", "slcsp", "aptc")


class PtcMonthlyResult(BaseModel):
    """Result of :func:`ptc_monthly`: Form 8962 lines 1-29, MONTHLY method (the
    lines 12-23 grid; no shared-policy allocation or marriage-year alternatives)."""

    model_config = ConfigDict(extra="forbid")

    fpl_amount: int = Field(description="Line 4: the federal poverty line for the household size and state table.")
    fpl_pct: int = Field(
        description="Line 5: household income as % of the FPL, TRUNCATED to an integer (literally 401 when over 400%)."
    )
    applicable_figure: Decimal = Field(description="Line 7: the Table 2 applicable figure (4 decimals).")
    contribution: int = Field(description="Line 8a: annual contribution amount = income x figure, whole dollars.")
    monthly_contribution: int = Field(
        description="Line 8b: line 8a / 12, rounded to whole dollars — column (c) of every monthly row (lines 12c-23c)."
    )
    months_covered: int = Field(description="Months with coverage (a premium or SLCSP entry) among the 12 rows.")
    ptc: int = Field(
        description="Line 24: total premium tax credit = the sum of the monthly PTC column (lines 12e-23e), floor 0 per month."
    )
    net_ptc: int = Field(description="Line 26: PTC in excess of APTC (0 when APTC exceeds PTC).")
    repayment: int = Field(
        description="Line 29: excess APTC repayment after the Table 5 limitation (0 when PTC covers APTC)."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def ptc_monthly(
    household_income: int | float | Decimal | str,
    household_size: int,
    monthly: list[dict],
    filing_status: str = "single",
    year: int = 2023,
    state: str = "other",
    annual_aptc: int | float | Decimal | str | None = None,
    mfs_relief_exception: bool = False,
    knowledge_dir: str | Path | None = None,
) -> PtcMonthlyResult:
    """Premium Tax Credit (Form 8962), MONTHLY method — the lines 12-23 grid for
    part-year or month-varying coverage (no shared-policy allocation or
    alternative marriage-year computation).

    ``monthly`` is EXACTLY 12 rows, January..December, each
    ``{premium, slcsp, aptc}`` from the Form 1095-A monthly lines 21-32
    (columns A/B/C; omitted keys default to 0). A month WITHOUT coverage is
    all zeros — never dropped from the list.

    Line sequence, per the Form 8962 instructions:

    * lines 4-8a: identical to :func:`ptc_annual` (FPL table by ``state``,
      Worksheet 2 truncation, the Table 2 figure, contribution = income x
      figure).
    * line 8b: monthly contribution amount = line 8a / 12, rounded to whole
      dollars — column (c) of every monthly row.
    * lines 12-23, per month: column (d) = SLCSP - line 8b, floor 0; column
      (e) monthly PTC = the smaller of the premium and (d). Each row uses the
      row's own whole-dollar 1095-A entries.
    * line 24: the sum of the monthly PTC column; line 25: the sum of the
      monthly APTC column. ``annual_aptc`` (Form 1095-A line 33C) is an
      optional cross-check — it must equal the monthly APTC sum; when the
      rows carry NO monthly APTC breakdown it is used as line 25 directly.
    * lines 26-29: the SAME applicable-taxpayer gates and Table 5 repayment
      limitation as :func:`ptc_annual` (MFS denial unless
      ``mfs_relief_exception``, the below-100%-FPL floor, the vanishing
      limitation at 400% FPL or more).
    """
    income = _to_decimal(household_income, "household_income")
    if isinstance(monthly, (str, bytes, dict)) or not isinstance(monthly, (list, tuple)):
        raise TypeError(
            f"monthly must be a list of 12 {{premium, slcsp, aptc}} rows (January..December, from the "
            f"Form 1095-A monthly lines 21-32), got {type(monthly).__name__}"
        )
    if len(monthly) != 12:
        raise ValueError(
            f"monthly must have EXACTLY 12 entries (January..December — a month without coverage is "
            f"all zeros, never dropped), got {len(monthly)}"
        )
    rows: list[dict[str, Decimal]] = []
    for i, raw in enumerate(monthly):
        if not isinstance(raw, dict):
            raise TypeError(
                f"monthly[{i}] ({_MONTHS[i]}) must be a dict {{premium, slcsp, aptc}}, got {type(raw).__name__}"
            )
        unknown = sorted(set(raw) - set(_PTC_MONTH_KEYS))
        if unknown:
            raise ValueError(
                f"monthly[{i}] ({_MONTHS[i]}) has unknown key(s) {unknown} — each row carries only "
                f"premium (1095-A column A), slcsp (column B), aptc (column C); omitted keys default to 0"
            )
        row: dict[str, Decimal] = {}
        for key in _PTC_MONTH_KEYS:
            value = _to_decimal(raw.get(key, 0), f"monthly[{i}].{key}")
            if value < 0:
                raise ValueError(f"monthly[{i}].{key} must be >= 0, got {value}")
            row[key] = value
        rows.append(row)
    status = str(filing_status)
    _ptc_validate_common(income, household_size, status, state, mfs_relief_exception)
    aptc_total_given = None if annual_aptc is None else _to_decimal(annual_aptc, "annual_aptc")
    if aptc_total_given is not None and aptc_total_given < 0:
        raise ValueError(f"annual_aptc must be >= 0, got {aptc_total_given}")
    params = _ptc_params(year, knowledge_dir)

    inputs: dict[str, Any] = {
        "household_income": str(income),
        "household_size": household_size,
        "monthly": [{k: str(r[k]) for k in _PTC_MONTH_KEYS} for r in rows],
        "filing_status": status,
        "state": state,
        "year": year,
    }
    if aptc_total_given is not None:
        inputs["annual_aptc"] = str(aptc_total_given)
    if status == "married_filing_separately":
        inputs["mfs_relief_exception"] = mfs_relief_exception

    fpl, fpl_pct, pct_text, figure, figure_text, contribution = _ptc_lines_4_to_8a(
        income, household_size, state, params
    )
    line_8b = irs_round(Decimal(contribution) / 12)

    # Lines 12-23: each row from its own whole-dollar 1095-A entries. An uncovered
    # month is all zeros, so its row math reduces to 0 exactly like a blank row.
    month_lines: list[str] = []
    months_covered = 0
    computed_ptc = 0
    monthly_aptc_sum = 0
    for i, row in enumerate(rows):
        prem = irs_round(row["premium"])
        slcsp = irs_round(row["slcsp"])
        monthly_aptc_sum += irs_round(row["aptc"])
        if prem == 0 and slcsp == 0:
            continue
        months_covered += 1
        max_assistance = max(0, slcsp - line_8b)  # column (d)
        month_ptc = min(prem, max_assistance)  # column (e)
        computed_ptc += month_ptc
        month_lines.append(
            f"{_MONTHS[i][:3]} min({_dollars(prem)}, max(0, {_dollars(slcsp)} - {_dollars(line_8b)}) = "
            f"{_dollars(max_assistance)}) = {_dollars(month_ptc)}"
        )

    # Line 25. annual_aptc is a cross-check against the monthly column-C sum; with
    # no monthly breakdown at all it stands in as the total (the tail only needs it).
    aptc_note = ""
    if aptc_total_given is None:
        aptc_whole = monthly_aptc_sum
    elif monthly_aptc_sum == 0:
        aptc_whole = irs_round(aptc_total_given)
        if aptc_whole:
            aptc_note = " (annual_aptc supplied without a monthly APTC breakdown — used as the line 25 total)"
    elif irs_round(aptc_total_given) != monthly_aptc_sum:
        raise ValueError(
            f"annual_aptc ({_dollars(irs_round(aptc_total_given))}) does not equal the sum of the monthly "
            f"aptc entries ({_dollars(monthly_aptc_sum)}) — Form 1095-A line 33C is the sum of lines 21-32 "
            f"column C; fix the inputs, or omit annual_aptc and let the monthly rows carry the APTC"
        )
    else:
        aptc_whole = monthly_aptc_sum

    computed_text = (
        f"sum of the monthly PTC column (lines 12e-23e, {months_covered} covered month(s)) = "
        f"{_dollars(computed_ptc)}"
    )
    ptc_amount, net_ptc, repayment, line24_text, settle_text = _ptc_settle(
        params, status, mfs_relief_exception, fpl_pct, computed_ptc, aptc_whole, computed_text,
        "total PTC (monthly method)",
    )

    state_label = _PTC_STATE_LABELS[state]
    grid_text = "; ".join(month_lines) if month_lines else "no covered months (every row zero)"
    work = (
        f"Form 8962 ({year}, monthly method): line 4 FPL ({state_label} table, household of "
        f"{household_size}) = {_dollars(fpl)}; line 5 = household income {_money(income)} / FPL x 100 = "
        f"{pct_text}; {figure_text}; line 8a contribution = {_money(income)} x {figure} = "
        f"{_dollars(contribution)}; line 8b monthly contribution = round({_dollars(contribution)} / 12) = "
        f"{_dollars(line_8b)}. Lines 12-23 (per month: (d) = max(0, SLCSP - {_dollars(line_8b)}), "
        f"(e) = min(premium, (d))): {grid_text}; {line24_text}; "
        f"line 25 total APTC = {_dollars(aptc_whole)}{aptc_note}. {settle_text}"
    )
    return PtcMonthlyResult(
        fpl_amount=fpl,
        fpl_pct=fpl_pct,
        applicable_figure=figure,
        contribution=contribution,
        monthly_contribution=line_8b,
        months_covered=months_covered,
        ptc=ptc_amount,
        net_ptc=net_ptc,
        repayment=repayment,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Child tax credit / credit for other dependents / additional CTC
# (Schedule 8812 -> Form 1040 lines 19 and 28)
# ---------------------------------------------------------------------------

# Schedule 8812 Part II-A lines 19-20: the refundable ACTC is 15% of earned
# income over $2,500. Both figures are statutory (IRC 24(d)(1)(A) as amended
# by TCJA), NOT indexed — identical in every supported non-ARPA year.
_ACTC_EARNED_INCOME_FLOOR = 2500
_ACTC_EARNED_INCOME_RATE = Decimal("0.15")


def _credits_config(pack: KnowledgePack, year: int, name: str, contents: str) -> dict:
    """Fetch ``credits.<name>`` from the pack as a dict, with a prescriptive error."""
    block = getattr(pack.credits, name, None) if pack.credits is not None else None
    if not isinstance(block, dict) or "citation" not in block:
        raise ValueError(
            f"knowledge pack for federal {year} has no credits.{name} block — add it ({contents}) with a citation"
        )
    return block


def _count_arg(value: Any, name: str, what: str) -> int:
    """Validate a people-count argument: a non-negative int, never a bool."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int ({what}), got {value!r}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0 ({what}), got {value}")
    return value


def _status_amount(table: dict, filing_status: str, where: str) -> int:
    """Resolve a per-status amount from a credits table (all five statuses explicit)."""
    if filing_status not in table:
        raise ValueError(
            f"unknown filing_status {filing_status!r} for {where} — use one of: {', '.join(sorted(table))}"
        )
    return int(table[filing_status])


def _ctc_phaseout_step(magi: Decimal, threshold: int) -> int:
    """Schedule 8812 phase-out arithmetic: $50 per $1,000 OR FRACTION of MAGI above
    the threshold — the excess is rounded UP to the next whole $1,000 FIRST (line 10:
    'if not a multiple of $1,000, increase it to the next multiple of $1,000')."""
    excess = magi - threshold
    if excess <= 0:
        return 0
    thousands = int((excess / Decimal(1000)).to_integral_value(rounding=ROUND_CEILING))
    return 50 * thousands


class CtcResult(BaseModel):
    """Result of :func:`child_tax_credit`: Schedule 8812 (CTC / ODC / ACTC)."""

    model_config = ConfigDict(extra="forbid")

    ctc_odc_total: int = Field(
        description="Line 8-style pre-phase-out, pre-limit total: per-child credit x qualifying children "
        "+ $500 x other dependents (2021: the ARPA $3,600/$3,000 expanded per-child amounts)."
    )
    phaseout_reduction: int = Field(
        description="Total MAGI phase-out reduction actually applied ($50 per $1,000 or fraction over the "
        "threshold, capped at the available credit; 2021 applies its two tiers)."
    )
    credit_after_phaseout: int = Field(
        description="Line 12: ctc_odc_total - phaseout_reduction (floor 0) — the credit before the "
        "tax-liability limit."
    )
    nonrefundable_used: int = Field(
        description="Line 14: the nonrefundable CTC/ODC usable against income_tax_before_credits "
        "(goes on Form 1040 line 19). 2021: only the ODC part is nonrefundable."
    )
    actc_refundable: int = Field(
        description="Line 27 additional child tax credit (goes on Form 1040 line 28). "
        "2021: the fully refundable ARPA child tax credit remainder."
    )
    actc_cap_per_child: int = Field(
        description="The year's refundable ACTC cap per qualifying child that was applied on line 16b "
        "(e.g. $1,600 for 2023; for 2021 the ARPA credit is fully refundable, so no dollar cap binds)."
    )
    fully_refundable: bool = Field(
        description="True only for 2021 (ARPA): the whole child tax credit refunds for a taxpayer with a "
        "principal place of abode in the US for more than half the year (assumed — see work)."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def child_tax_credit(
    qualifying_children_ssn: int,
    other_dependents: int,
    magi: int | float | Decimal | str,
    income_tax_before_credits: int | float | Decimal | str,
    earned_income: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2023,
    children_under_6: int = 0,
    knowledge_dir: str | Path | None = None,
) -> CtcResult:
    """Child tax credit / credit for other dependents / additional child tax credit
    (Schedule 8812) — the numbers for Form 1040 lines 19 and 28.

    Inputs (eligibility itself is caller judgment — this op does the worksheet math):

    * ``qualifying_children_ssn``: dependents who meet the year's qualifying-child
      age test (under 17 at year end; under 18 for 2021) AND have the required
      work-eligible SSN. A child with an ITIN/ATIN belongs in ``other_dependents``.
    * ``other_dependents``: every other claimed dependent ($500 ODC each; an SSN
      is not required, but the dependent needs an ITIN/ATIN/SSN by the due date).
    * ``magi``: Schedule 8812 line 3 (Form 1040 line 11 AGI plus the Puerto Rico /
      Form 2555 / Form 4563 exclusions — line 1 = line 3 for most filers).
    * ``income_tax_before_credits``: the Credit Limit Worksheet amount — Form 1040
      line 18 tax MINUS the credits taken before this one (Schedule 3 lines 1-4,
      5b, 6c, 6g, 6h — e.g. foreign tax and education credits), per the Schedule
      8812 instructions. Pass the tax itself when no earlier credits apply.
    * ``earned_income``: line 18a per the instructions' Earned Income Worksheet
      (wages + SE net earnings - 1/2 SE tax, etc.); drives the refundable ACTC.
    * ``children_under_6``: how many of the qualifying children had not turned 6
      by year end — only changes the result for 2021 (the ARPA $3,600 tier).

    Non-ARPA years (2019-2020, 2022+), following the 2023 Schedule 8812 line flow:

    * line 5 = qualifying children x the per-child credit ($2,000); line 7 = other
      dependents x $500; line 8 = their sum (``ctc_odc_total``).
    * lines 9-11: the phase-out — $50 per $1,000 OR FRACTION (excess rounded UP to
      the next $1,000) of MAGI over $400,000 MFJ / $200,000 otherwise; line 12 =
      line 8 minus the reduction (if not above zero, the form says stop — no CTC,
      ODC, or ACTC).
    * lines 13-14: the nonrefundable credit = min(line 12, the credit limit)
      (Form 1040 line 19).
    * Part II-A (ACTC): line 16a leftover = line 12 - line 14; line 16b = the
      year's refundable cap x qualifying children ($1,600 for 2023); line 20 = 15%
      of earned income over $2,500; line 27 ACTC = the smallest of the three
      (Form 1040 line 28). No qualifying children -> no ACTC (the ODC never
      refunds). Part II-B (3+ children: the larger-of social-security-taxes
      alternative) is NOT modeled — when it could apply, ``work`` says so (it can
      only increase the ACTC).

    2021 (ARPA, per the pack's ``arpa_expanded`` keys — Schedule 8812 (2021) and
    its Line 5 Worksheet): $3,600 per child under 6 / $3,000 otherwise; the FIRST
    phase-out trims only the increase over the $2,000 base ($50 per $1,000 or
    fraction of MAGI over $75,000/$112,500/$150,000, capped by the Line 5
    Worksheet's per-status cap); the SECOND trims the remainder at the regular
    $400,000/$200,000 thresholds. The ODC part stays nonrefundable (line 14a);
    the child-tax-credit remainder is FULLY refundable (no 15%-of-earned-income
    rule) — assuming the line 13A US-principal-abode residency box applies, which
    is a caller judgment disclosed in ``work``.
    """
    n_qc = _count_arg(qualifying_children_ssn, "qualifying_children_ssn",
                      "qualifying children with the required SSN")
    n_odc = _count_arg(other_dependents, "other_dependents", "other dependents eligible for the $500 ODC")
    n_u6 = _count_arg(children_under_6, "children_under_6", "qualifying children under age 6 at year end")
    if n_u6 > n_qc:
        raise ValueError(
            f"children_under_6 ({n_u6}) cannot exceed qualifying_children_ssn ({n_qc}) — it counts the "
            f"subset of the qualifying children who had not turned 6 by year end"
        )
    magi_d = _to_decimal(magi, "magi")
    limit_d = _to_decimal(income_tax_before_credits, "income_tax_before_credits")
    if limit_d < 0:
        raise ValueError(
            f"income_tax_before_credits must be >= 0, got {limit_d} — pass 0 when no tax remains after "
            f"the credits taken before this one"
        )
    earned = _to_decimal(earned_income, "earned_income")
    if earned < 0:
        raise ValueError(
            f"earned_income cannot be negative (got {earned}) — the Schedule 8812 earned-income worksheet "
            f"floors it at zero; pass 0"
        )
    status = str(filing_status)
    pack = _load_federal(year, knowledge_dir)
    cfg = _credits_config(
        pack, year, "child_tax_credit",
        "per-child amount, ODC amount, the refundable ACTC cap, and the MAGI phase-out thresholds",
    )
    citation = Citation(**cfg["citation"])
    limit_whole = irs_round(limit_d)
    inputs: dict[str, Any] = {
        "qualifying_children_ssn": n_qc,
        "other_dependents": n_odc,
        "children_under_6": n_u6,
        "magi": str(magi_d),
        "income_tax_before_credits": str(limit_d),
        "earned_income": str(earned),
        "filing_status": status,
        "year": year,
    }
    odc_amount = int(cfg["credit_for_other_dependents"])
    odc_total = odc_amount * n_odc
    cap_per_child = int(cfg["additional_ctc_refundable_cap_per_child"])
    age_test = str(cfg.get("qualifying_child_age_test", "the qualifying-child age test"))

    if cfg.get("arpa_expanded"):
        # 2021 only — mirror the Schedule 8812 (2021) Line 5 Worksheet + lines 9-14.
        per_child = int(cfg["per_qualifying_child"])  # 3,000 (age 6-17)
        per_under_6 = int(cfg["per_qualifying_child_under_6"])  # 3,600
        base_per_child = int(cfg["pre_arpa_base_per_child"])  # 2,000
        expanded = per_under_6 * n_u6 + per_child * (n_qc - n_u6)
        base_credit = base_per_child * n_qc
        increase = expanded - base_credit
        tier1_threshold = _status_amount(cfg["increased_amount_phaseout_threshold"], status, "child_tax_credit")
        tier1_cap = _status_amount(cfg["increased_amount_phaseout_cap"], status, "child_tax_credit")
        tier1_raw = _ctc_phaseout_step(magi_d, tier1_threshold)
        tier1_reduction = min(tier1_raw, tier1_cap, increase)
        line8 = expanded - tier1_reduction + odc_total
        tier2_threshold = _status_amount(cfg["base_credit_phaseout_threshold"], status, "child_tax_credit")
        tier2_raw = _ctc_phaseout_step(magi_d, tier2_threshold)
        line12 = max(0, line8 - tier2_raw)
        tier2_reduction = line8 - line12
        total = expanded + odc_total
        reduction = tier1_reduction + tier2_reduction
        # The 2021 Schedule 8812 preserves the ODC first (line 14a); the child-tax-credit
        # remainder is the fully refundable RCTC (Form 1040 line 28).
        odc_part = min(odc_total, line12)
        rctc = line12 - odc_part
        used = min(odc_part, limit_whole)
        work = (
            f"Schedule 8812 (2021, ARPA, {status}): {n_qc} qualifying children ({age_test}, each with the "
            f"required SSN) -> expanded credit = {n_u6} x {_dollars(per_under_6)} (under 6) + "
            f"{n_qc - n_u6} x {_dollars(per_child)} = {_dollars(expanded)} "
            f"(pre-ARPA base {_dollars(base_credit)}, increase {_dollars(increase)}). "
            f"Line 5 Worksheet first-tier phase-out trims ONLY the increase: min($50 per $1,000 or fraction "
            f"of MAGI {_money(magi_d)} over {_dollars(tier1_threshold)} = {_dollars(tier1_raw)}, the "
            f"{_dollars(tier1_cap)} worksheet cap, the increase) = {_dollars(tier1_reduction)}; "
            f"line 7 ODC = {n_odc} x {_dollars(odc_amount)} = {_dollars(odc_total)}; line 8 = {_dollars(line8)}. "
            f"Second-tier phase-out over the {_dollars(tier2_threshold)} threshold = {_dollars(tier2_raw)} "
            f"-> line 12 = {_dollars(line12)}. The ODC part {_dollars(odc_part)} stays nonrefundable: "
            f"{_dollars(used)} usable against the {_dollars(limit_whole)} credit limit (Form 1040 line 19); "
            f"the remaining {_dollars(rctc)} child tax credit is FULLY REFUNDABLE for 2021 (Form 1040 "
            f"line 28) — this assumes a principal place of abode in the US for more than half of 2021 "
            f"(Schedule 8812 box 13A, caller judgment); without it the pre-ARPA $1,400-cap ACTC rules "
            f"apply instead."
        )
        return CtcResult(
            ctc_odc_total=total,
            phaseout_reduction=reduction,
            credit_after_phaseout=line12,
            nonrefundable_used=used,
            actc_refundable=rctc,
            actc_cap_per_child=cap_per_child,
            fully_refundable=True,
            inputs=inputs,
            work=work,
            citation=citation,
        )

    # Non-ARPA years: the 2023 Schedule 8812 line flow (2019/2020 print the same
    # math in Pub 972's worksheet + Schedule 8812; line names follow the 2023 form).
    per_child = int(cfg["per_qualifying_child"])
    line5 = per_child * n_qc
    line8 = line5 + odc_total
    threshold = _status_amount(cfg["magi_phaseout_threshold"], status, "child_tax_credit")
    line11 = _ctc_phaseout_step(magi_d, threshold)
    line12 = max(0, line8 - line11)
    reduction = line8 - line12
    line14 = min(line12, limit_whole)
    leftover = line12 - line14  # line 16a
    line16b = cap_per_child * n_qc
    line20 = irs_round(max(Decimal(0), _ACTC_EARNED_INCOME_RATE * (earned - _ACTC_EARNED_INCOME_FLOOR)))
    actc = min(leftover, line16b, line20) if n_qc else 0

    if n_qc == 0:
        actc_text = "no qualifying children -> no additional child tax credit (the ODC never refunds)"
    elif line12 == 0:
        actc_text = "line 12 is $0, so the form stops — no CTC, ODC, or ACTC"
    else:
        actc_text = (
            f"Part II-A: line 16a leftover = {_dollars(leftover)}; line 16b = {n_qc} x "
            f"{_dollars(cap_per_child)} = {_dollars(line16b)}; line 18a earned income {_money(earned)} -> "
            f"line 20 = 15% x max(0, earned - {_dollars(_ACTC_EARNED_INCOME_FLOOR)}) = {_dollars(line20)}; "
            f"line 27 additional child tax credit = smallest = {_dollars(actc)} (Form 1040 line 28)"
        )
        if n_qc >= 3 and line20 < min(leftover, line16b):
            actc_text += (
                ". NOTE: with 3 or more qualifying children and line 20 below line 17, Part II-B (the "
                "larger-of social-security-taxes alternative, lines 21-26) can only INCREASE the ACTC — "
                "it is not modeled here; work it from the printed schedule"
            )
    work = (
        f"Schedule 8812 ({year}, {status}): line 5 = {n_qc} qualifying children ({age_test}, each with the "
        f"required SSN) x {_dollars(per_child)} = {_dollars(line5)}; line 7 = {n_odc} other dependents x "
        f"{_dollars(odc_amount)} = {_dollars(odc_total)}; line 8 = {_dollars(line8)}. Line 3 MAGI "
        f"{_money(magi_d)} vs the {_dollars(threshold)} line 9 threshold: lines 10-11 phase-out = "
        f"{_dollars(line11)} ($50 per $1,000 or fraction over, excess rounded UP to the next $1,000) -> "
        f"line 12 = {_dollars(line12)}. Line 13 credit limit (income tax minus earlier credits) = "
        f"{_dollars(limit_whole)} -> line 14 nonrefundable child tax credit / credit for other dependents = "
        f"{_dollars(line14)} (Form 1040 line 19). {actc_text}."
    )
    return CtcResult(
        ctc_odc_total=line8,
        phaseout_reduction=reduction,
        credit_after_phaseout=line12,
        nonrefundable_used=line14,
        actc_refundable=actc,
        actc_cap_per_child=cap_per_child,
        fully_refundable=False,
        inputs=inputs,
        work=work,
        citation=citation,
    )


# ---------------------------------------------------------------------------
# Earned income tax credit (Rev. Proc. formula -> Form 1040 line 27)
# ---------------------------------------------------------------------------


class EitcResult(BaseModel):
    """Result of :func:`eitc`: the earned income credit by the Rev. Proc. formula."""

    model_config = ConfigDict(extra="forbid")

    eitc: int = Field(
        description="The earned income credit, whole dollars (Form 1040 line 27); 0 when disqualified."
    )
    phase: Literal["in", "plateau", "out"] | None = Field(
        description="Which region bound the credit: 'in' (phase-in rate x earned income), 'plateau' "
        "(the maximum credit), 'out' (phasing out on the GREATER of AGI or earned income); "
        "None when disqualified by a gate."
    )
    disqualified_reason: str | None = Field(
        description="Why the credit is $0 by rule (investment income over the limit, married filing "
        "separately, or no positive earned income); None when the credit was computed."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def eitc(
    earned_income: int | float | Decimal | str,
    agi: int | float | Decimal | str,
    qualifying_children: int,
    filing_status: str = "single",
    year: int = 2023,
    investment_income: int | float | Decimal | str = 0,
    knowledge_dir: str | Path | None = None,
) -> EitcResult:
    """Earned income tax credit (Form 1040 line 27) by the Rev. Proc. formula.

    ``qualifying_children`` counts the EITC qualifying children (relationship /
    age / residency / joint-return tests met, each with a valid SSN) — those
    tests, and the taxpayer-level rules not modeled here (valid SSNs for the
    filer and spouse, not being another person's qualifying child, the childless
    age band, no Form 2555), are caller judgment. Three or more children share
    the '3+' parameter column.

    Mechanics (parameters from the year's cited Rev. Proc. table):

    * gates, checked first: investment income over the year's limit denies the
      credit entirely (Pub 596 Rule 6 — interest incl. tax-exempt, dividends,
      net capital gain, and net passive/rental income); married filing
      separately is denied by rule (see below); and the credit needs positive
      earned income.
    * phase-in: max_credit / earned_income_amount x earned income, capped at
      the maximum credit (the plateau).
    * phase-out: on the GREATER of AGI or earned income above the phase-out
      threshold (the MFJ column's thresholds are higher than every other
      status's — a qualifying surviving spouse uses the OTHER column, unlike
      most MFJ aliasing), at max_credit / (complete - begin) per dollar, to
      zero at the completion point. Floor 0, then IRS-rounded.

    MFS: generally NOT eligible (IRC 32(d)). Since 2021 (ARPA section 9622)
    there is a NARROW exception — an MFS filer who lived with their qualifying
    child for more than half the year AND either did not live with the spouse
    during the last 6 months or has a separation decree/agreement and lived
    apart at year end. This op conservatively returns $0 for MFS and spells the
    exception out in ``work``; a filer meeting it should be worked from Pub 596.

    Approximation, same disclosure as the estimator: the official EIC table
    uses $50 income bands (the formula evaluated at each band's midpoint), so a
    printed-table lookup can differ from this exact-formula value by roughly
    +/-$27 — re-derive from the printed table at filing time.
    """
    earned = _to_decimal(earned_income, "earned_income")
    agi_d = _to_decimal(agi, "agi")
    inv = _to_decimal(investment_income, "investment_income")
    if inv < 0:
        raise ValueError(f"investment_income must be >= 0, got {inv} — pass the Pub 596 Rule 6 total")
    n_qc = _count_arg(qualifying_children, "qualifying_children", "EITC qualifying children")
    status = str(filing_status)
    _resolve_filing_status(status)  # validates the five statuses (the alias is NOT used: QSS is not MFJ here)
    pack = _load_federal(year, knowledge_dir)
    cfg = _credits_config(
        pack, year, "earned_income_tax_credit",
        "the investment-income limit and the by_qualifying_children parameter table",
    )
    citation = Citation(**cfg["citation"])
    inv_limit = int(cfg["investment_income_limit"])
    key = "3+" if n_qc >= 3 else str(n_qc)
    inputs: dict[str, Any] = {
        "earned_income": str(earned),
        "agi": str(agi_d),
        "qualifying_children": n_qc,
        "investment_income": str(inv),
        "filing_status": status,
        "year": year,
    }

    def _denied(reason: str, detail: str) -> EitcResult:
        return EitcResult(
            eitc=0, phase=None, disqualified_reason=reason, inputs=inputs,
            work=f"EITC ({year}, {status}): $0 — {detail}", citation=citation,
        )

    if status == "married_filing_separately":
        return _denied(
            "married filing separately is not eligible for the EITC (IRC 32(d))",
            f"married filing separately is denied the credit by rule (IRC 32(d)). The only exception "
            f"(post-2021, ARPA section 9622): the filer lived with their qualifying child for more than "
            f"half of {year} AND either did not live with the spouse during the last 6 months of {year} "
            f"or has a separation decree/agreement and lived apart at year end — if that applies, work "
            f"the credit from Pub 596 (this op conservatively returns $0 for MFS).",
        )
    if inv > inv_limit:
        return _denied(
            f"investment income exceeds the {_dollars(inv_limit)} limit",
            f"investment income {_money(inv)} exceeds the {_dollars(inv_limit)} limit for {year}, which "
            f"denies the credit ENTIRELY (Pub 596 Rule 6 — count interest including tax-exempt, dividends, "
            f"net capital gain, and net passive/rental income); no phase-out applies, the credit is simply $0.",
        )
    if earned <= 0:
        return _denied(
            "the EITC requires positive earned income",
            f"earned income is {_money(earned)} — the credit phases in from earned income, so with none "
            f"there is no credit (investment or unearned income alone never qualifies).",
        )

    row = cfg["by_qualifying_children"][key]
    max_credit = Decimal(row["max_credit"])
    ei_amount = Decimal(row["earned_income_amount"])
    phase_in_amount = min(max_credit, max_credit / ei_amount * earned)
    mfj = status == "married_filing_jointly"
    begin = Decimal(row["phaseout_begins_mfj" if mfj else "phaseout_begins_other"])
    complete = Decimal(row["phaseout_complete_mfj" if mfj else "phaseout_complete_other"])
    phase_base = max(agi_d, earned)
    column = "married-filing-jointly" if mfj else "single/HoH/QSS"
    if phase_base > begin:
        rate_out = max_credit / (complete - begin)
        phase_out_amount = max_credit - rate_out * (phase_base - begin)
        credit_exact = min(phase_in_amount, phase_out_amount)
        phase: Literal["in", "plateau", "out"] = "out" if phase_out_amount <= phase_in_amount else "in"
        phase_text = (
            f"phase-out on the GREATER of AGI {_money(agi_d)} or earned income = {_money(phase_base)}, "
            f"{_money(phase_base - begin)} over the {_dollars(begin)} {column} threshold, at "
            f"{_dollars(max_credit)}/{_dollars(complete - begin)} per dollar -> {_money(max(Decimal(0), phase_out_amount))} "
            f"(zero at {_dollars(complete)})"
        )
    else:
        credit_exact = phase_in_amount
        phase = "plateau" if earned >= ei_amount else "in"
        phase_text = (
            f"the greater of AGI {_money(agi_d)} or earned income is at or below the {_dollars(begin)} "
            f"{column} phase-out threshold (no reduction)"
        )
    credit = irs_round(max(Decimal(0), credit_exact))
    work = (
        f"EITC ({year}, {status}, {key} qualifying children): investment income {_money(inv)} is within the "
        f"{_dollars(inv_limit)} limit. Phase-in = min(max credit {_dollars(max_credit)}, "
        f"{_dollars(max_credit)}/{_dollars(ei_amount)} x earned income {_money(earned)}) = "
        f"{_money(phase_in_amount)}; {phase_text}; credit = {_dollars(credit)} (Form 1040 line 27), "
        f"'{phase}' region. The official EIC table uses $50 income bands, so a printed-table lookup can "
        f"differ from this exact formula by roughly +/-$27 — re-derive from the table at filing time. "
        f"Qualifying-child and taxpayer-level eligibility tests are caller judgment."
    )
    return EitcResult(
        eitc=credit,
        phase=phase,
        disqualified_reason=None,
        inputs=inputs,
        work=work,
        citation=citation,
    )


# ---------------------------------------------------------------------------
# Child & dependent care credit (Form 2441 -> Schedule 3 line 2) — Phase G, G2
# ---------------------------------------------------------------------------


def _dependent_care_percentage(agi: Decimal, params: DependentCareParams) -> Decimal:
    """The Form 2441 line 8 applicable percentage for an AGI, from the pack's slide.

    Each leg reduces its ``from_rate`` by ``points_per_step`` per ``per_agi_step``
    dollars OR FRACTION THEREOF of AGI above ``starts_above_agi`` (the excess is
    rounded UP to the next step FIRST — IRC 21(a)(2)/(g)(4)), floored at
    ``to_rate``. AGI exactly at a published boundary keeps the HIGHER rate
    (exactly $15,000 -> 0.35; exactly $43,000 -> 0.21; 2021: exactly $438,000 ->
    0.01, over it -> 0.00 — the zero point follows from the fraction rule).
    """
    rate = params.phase_downs[0].from_rate
    for leg in params.phase_downs:
        if agi > leg.starts_above_agi:
            steps = int(
                ((agi - leg.starts_above_agi) / leg.per_agi_step).to_integral_value(rounding=ROUND_CEILING)
            )
            rate = max(leg.to_rate, leg.from_rate - leg.points_per_step * steps)
    return rate


class DependentCareResult(BaseModel):
    """Result of :func:`dependent_care_credit`: Form 2441 Part II (+ the Part III cap offset)."""

    model_config = ConfigDict(extra="forbid")

    allowed_expenses: int = Field(
        description="Form 2441 line 6: the smallest of the capped (benefit-reduced) expenses and the "
        "earned-income figures — the credit base."
    )
    applicable_percentage: Decimal = Field(
        description="Form 2441 line 8 decimal from the AGI slide (0.20-0.35; 2021: 0.00-0.50)."
    )
    credit: int = Field(
        description="Line 9a-style credit = percentage x allowed expenses, whole dollars — BEFORE the "
        "tax-liability limit (line 10 Credit Limit Worksheet) when nonrefundable."
    )
    refundable: bool = Field(
        description="True only for 2021 (ARPA, IRC 21(g)(1)) — and only IF the US-principal-abode test "
        "is met (caller judgment, see work); every other year is nonrefundable."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def dependent_care_credit(
    expenses: int | float | Decimal | str,
    qualifying_persons: int,
    earned_income: int | float | Decimal | str,
    spouse_earned_income: int | float | Decimal | str | None = None,
    agi: int | float | Decimal | str = 0,
    filing_status: str = "single",
    year: int = 2023,
    employer_benefits: int | float | Decimal | str = 0,
    knowledge_dir: str | Path | None = None,
) -> DependentCareResult:
    """Child and dependent care credit (Form 2441 -> Schedule 3 line 2), from the
    pack's cited ``tax.dependent_care`` parameters.

    Inputs (who counts as a qualifying person — under 13, or a spouse/dependent
    incapable of self-care — and whether the care let you work are caller
    judgment; this op does the form math):

    * ``expenses``: total qualified care expenses paid for the year (Form 2441
      line 2 column (d) total BEFORE the caps), including any paid through an
      employer plan.
    * ``qualifying_persons``: 1 vs 2-or-more selects the expense cap
      ($3,000/$6,000; 2021: $8,000/$16,000).
    * ``earned_income`` / ``spouse_earned_income``: Form 2441 lines 4/5. The
      spouse figure is REQUIRED for married_filing_jointly (line 5; all other
      statuses enter the line 4 amount, so it is ignored). The deemed
      $250/$500-per-month rule for a full-time-student or disabled spouse is
      the AGENT'S judgment — include any deemed amount in the figure you pass
      (the work string quotes the rule).
    * ``employer_benefits``: dependent care benefits (W-2 box 10). They reduce
      BOTH the cap (line 27 - line 28 -> line 29) and the countable expenses
      (line 30 excludes them); formally the offset is the amount actually
      deducted + excluded (lines 24+25) — box 10 stands in for it when the
      benefits were all excluded, which the work discloses.
    * ``agi``: Form 1040/1040-NR line 11 — drives the line 8 percentage slide
      (35% down to 20% above $15,000; 2021: 50% -> 20% above $125,000, then
      20% -> 0% above $400,000, zero for AGI over $438,000).

    Line flow: line 3 = min(cap - benefits, expenses - benefits); line 6 =
    smallest of line 3 and the earned-income figures; credit = line 8
    percentage x line 6 (IRS-rounded). Nonrefundable — limited by tax via the
    line 10 Credit Limit Worksheet, which is applied DOWNSTREAM, not here —
    except 2021 (ARPA): refundable when the US-principal-abode test is met
    (Form 2441 line B — caller judgment, flagged in the work).

    married_filing_separately: generally INELIGIBLE by rule — the op returns $0
    and quotes the three treated-as-unmarried conditions (a filer meeting ALL
    three claims the credit as if unmarried: rerun with their actual unmarried
    status and check the form's MFS checkbox).
    """
    exp = _to_decimal(expenses, "expenses")
    if exp < 0:
        raise ValueError(f"expenses must be >= 0, got {exp} — pass the qualified care expenses paid")
    n_persons = _count_arg(qualifying_persons, "qualifying_persons", "qualifying persons the care was for")
    if n_persons < 1:
        raise ValueError(
            "qualifying_persons must be >= 1 — the credit requires at least one qualifying person "
            "(a child under 13, or a spouse/dependent incapable of self-care); with none there is "
            "no credit to compute"
        )
    earned = _to_decimal(earned_income, "earned_income")
    if earned < 0:
        raise ValueError(
            f"earned_income must be >= 0, got {earned} — Form 2441 line 4 is earned income "
            f"(include any deemed $250/$500 student/disabled amount you have decided applies)"
        )
    agi_d = _to_decimal(agi, "agi")
    if agi_d < 0:
        raise ValueError(f"agi must be >= 0, got {agi_d} — pass the Form 1040 line 11 amount")
    benefits = _to_decimal(employer_benefits, "employer_benefits")
    if benefits < 0:
        raise ValueError(f"employer_benefits must be >= 0, got {benefits} — pass the W-2 box 10 total")
    status = str(filing_status)
    _resolve_filing_status(status)  # validates the five statuses; no aliasing is used here
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.dependent_care
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.dependent_care block — add it (Form 2441 "
            f"expense caps, the line-8 percentage slide, the deemed-income and MFS rules) with a "
            f"citation to the year's Instructions for Form 2441 (see knowledge/federal/2023.yaml)"
        )
    inputs: dict[str, Any] = {
        "expenses": str(exp),
        "qualifying_persons": n_persons,
        "earned_income": str(earned),
        "agi": str(agi_d),
        "filing_status": status,
        "year": year,
        "employer_benefits": str(benefits),
    }
    if spouse_earned_income is not None:
        inputs["spouse_earned_income"] = str(_to_decimal(spouse_earned_income, "spouse_earned_income"))

    if status == "married_filing_separately":
        work = (
            f"Child and dependent care credit ({year}): $0 by RULE for married filing separately — "
            f"{params.married_filing_separately_note} A filer meeting ALL of those conditions is "
            f"treated as unmarried: rerun this op with the status the treated-as-unmarried rules give "
            f"them and check the Form 2441 married-filing-separately checkbox on the form."
        )
        return DependentCareResult(
            allowed_expenses=0,
            applicable_percentage=Decimal("0"),
            credit=0,
            refundable=False,
            inputs=inputs,
            work=work,
            citation=params.citation,
        )

    cap = (
        params.expense_cap.one_qualifying_person
        if n_persons == 1
        else params.expense_cap.two_or_more_qualifying_persons
    )
    line29 = max(Decimal(0), Decimal(cap) - benefits)  # cap reduced by employer benefits
    line30 = max(Decimal(0), exp - benefits)  # countable expenses exclude benefit-paid amounts
    line3 = min(line29, line30)
    candidates = [line3, earned]
    if status == "married_filing_jointly":
        if spouse_earned_income is None:
            raise ValueError(
                "married_filing_jointly requires spouse_earned_income (Form 2441 line 5) — the credit "
                "is limited by the LOWER-earning spouse's earned income. If the spouse was a full-time "
                "student or incapable of self-care, the deemed $250/$500-per-month rule may supply the "
                "figure — that is YOUR judgment: " + params.student_spouse_rule
            )
        spouse_earned = _to_decimal(spouse_earned_income, "spouse_earned_income")
        if spouse_earned < 0:
            raise ValueError(f"spouse_earned_income must be >= 0, got {spouse_earned}")
        candidates.append(spouse_earned)
        earned_text = (
            f"line 4 earned income {_money(earned)}, line 5 spouse's earned income {_money(spouse_earned)}"
        )
    else:
        earned_text = f"line 4 earned income {_money(earned)} (line 5 = line 4 for non-MFJ statuses)"
    line6 = max(Decimal(0), min(candidates))
    allowed = irs_round(line6)
    pct = _dependent_care_percentage(agi_d, params)
    credit = irs_round(pct * allowed)
    refundable = bool(params.refundable_if_us_abode and credit)

    benefit_text = (
        f" Employer dependent care benefits {_money(benefits)} (W-2 box 10) reduce both the cap "
        f"(line 29 = {_dollars(cap)} - benefits = {_money(line29)}) and the countable expenses "
        f"(line 30 = {_money(line30)}); the formal offset is the amount actually deducted + excluded "
        f"(Form 2441 lines 24+25) — box 10 stands in for it here, which assumes the benefits were all "
        f"excluded (complete Part III on the form to settle it)."
        if benefits > 0
        else ""
    )
    if refundable:
        limit_text = (
            f" REFUNDABLE for {year} (IRC 21(g)(1)) — but ONLY IF the abode test is met, which is YOUR "
            f"judgment: {params.refundable_condition}"
        )
    else:
        limit_text = (
            " Nonrefundable: the credit is limited by tax via the Form 2441 line 10 Credit Limit "
            "Worksheet (not applied here — apply it against the remaining income tax)."
        )
    work = (
        f"Form 2441 ({year}, {status}): {n_persons} qualifying person(s) -> {_dollars(cap)} expense cap; "
        f"line 3 = min(cap{' - benefits' if benefits > 0 else ''} {_money(line29)}, qualified expenses"
        f"{' - benefits' if benefits > 0 else ''} {_money(line30)}) = {_money(line3)}; {earned_text}; "
        f"line 6 = smallest = {_dollars(allowed)}. Line 8 applicable percentage for AGI {_money(agi_d)} "
        f"= {pct} (1 point per $2,000 OR FRACTION of AGI over the slide start — AGI exactly at a "
        f"boundary keeps the higher rate); line 9a credit = {pct} x {_dollars(allowed)} = "
        f"{_dollars(credit)} (Schedule 3 line 2).{benefit_text}{limit_text} Deemed-income rule (agent "
        f"judgment, include it in the earned income you pass): {params.student_spouse_rule} Form 2441 "
        f"Part I requires each provider's name, address, and TIN — the credit can be denied without them."
    )
    return DependentCareResult(
        allowed_expenses=allowed,
        applicable_percentage=pct,
        credit=credit,
        refundable=refundable,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# OBBBA Schedule 1-A additional deductions (Phase H, H6)
# ---------------------------------------------------------------------------


class Schedule1APart(BaseModel):
    """One Schedule 1-A part's outcome (Parts II-V)."""

    model_config = ConfigDict(extra="forbid")

    part: str = Field(description="Form part: 'II' tips, 'III' overtime, 'IV' car-loan interest, 'V' senior.")
    form_line: str = Field(
        description="The Schedule 1-A line this part's deduction lands on (13 / 21 / 30 / 37) — key "
        "verify_form's `independent` by it; line 38 is the sum of the four."
    )
    name: str
    input_amount: int = Field(
        description="Dollars entered for this part BEFORE the cap (Part V: qualifying count x the per-person amount)."
    )
    cap_applied: int = Field(description="The per-return cap for this filing status (Part V: count x per-person).")
    tentative: int = Field(description="min(input, cap) — the amount the MAGI reduction then applies to.")
    magi_threshold: int = Field(description="The phase-out threshold used (joint-return column only on MFJ).")
    magi_excess: int = Field(description="max(0, MAGI - threshold), whole dollars.")
    reduction: int = Field(description="The MAGI-driven reduction actually applied (never more than tentative).")
    deduction: int = Field(description="This part's deduction after cap, reduction, and any MFS forfeiture.")
    forfeited_reason: str | None = Field(
        default=None,
        description="Set when the part is FORFEITED outright (married filing separately on tips/overtime/senior).",
    )


class Schedule1AResult(BaseModel):
    """Result of :func:`schedule_1a_deductions`: Schedule 1-A Parts II-V and the line 38 total."""

    model_config = ConfigDict(extra="forbid")

    total_deduction: int = Field(
        description="Schedule 1-A line 38 -> Form 1040/1040-SR line 13b (Form 1040-NR line 13c). Reduces "
        "taxable income whether the filer itemizes or takes the standard deduction."
    )
    parts: list[Schedule1APart] = Field(
        description="Only the parts an input engaged; a forfeited part still appears with its reason."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def _sched1a_step_units(excess: Decimal, rounding: str) -> int:
    """excess/$1,000 as a whole number, rounded per the form line's own direction.

    Lines 11 and 19 say "decrease to the next LOWER whole number" (floor); line 28
    says "increase to the next HIGHER whole number" (ceil). The direction comes
    from pack data — this helper never chooses it.
    """
    whole, remainder = divmod(excess, Decimal(1000))
    units = int(whole)
    if rounding == "up" and remainder > 0:
        units += 1
    return units


def schedule_1a_deductions(
    magi: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2025,
    qualified_tips: int | float | Decimal | str = 0,
    qualified_overtime: int | float | Decimal | str = 0,
    car_loan_interest: int | float | Decimal | str = 0,
    seniors_qualifying: int = 0,
    knowledge_dir: str | Path | None = None,
) -> Schedule1AResult:
    """The four OBBBA Schedule 1-A deductions (P.L. 119-21, TY2025-2028), from the
    pack's cited ``tax.obbba_schedule_1a`` block.

    Eligibility stays CALLER judgment — quoted in the work, never silently assumed:
    qualified tips must be from an occupation on the IRS tipped-occupation list
    (voluntary tips only; SSTB tips excluded; valid SSN required); qualified
    overtime is the FLSA-required PREMIUM HALF of time-and-a-half, not the whole
    overtime wage; car-loan interest requires a personal-use NEW vehicle,
    US final assembly, a post-2024-12-31 loan secured by the vehicle, and the VIN
    on the return, net of amounts deducted on Schedule C/E/F; a senior qualifies
    when born before January 2, 1961 with a valid SSN.

    What the op DOES enforce, because they are form math, not judgment:

    * ``magi``: Schedule 1-A Part I — AGI + excluded Puerto Rico income + Form
      2555 lines 45/50 + Form 4563 line 15. One MAGI feeds all four parts.
    * Per-status caps ($25,000 tips PER RETURN — a joint return does NOT double
      it; $12,500/$25,000-MFJ overtime; $10,000 car loan; $6,000 per qualifying
      senior).
    * The phase-outs with their ASYMMETRIC rounding: tips/overtime reduce $100
      per $1,000 of excess rounded DOWN (lines 11/19); car loan reduces $200 per
      $1,000 rounded UP (line 28); the senior amount reduces by 6% of the excess
      per person (line 34).
    * The MFS forfeiture: tips, overtime and the senior deduction are FORFEITED
      by a married taxpayer who does not file jointly. Car-loan interest is NOT
      — the statute has no joint-filing rule for it.
    * A qualifying surviving spouse files a NON-joint return, so QSS takes the
      ``other`` thresholds and caps here (UNLIKE the rate schedules, where QSS
      maps to the MFJ column).

    ``seniors_qualifying`` is the COUNT of qualifying individuals (0-2; two only
    on a joint return where both spouses qualify).

    Raises a prescriptive ValueError for a year without the block: the deduction
    family exists for 2025-2028 only, and the 2026 planning pack declares it
    deliberately absent until the 2026 Schedule 1-A publishes.
    """
    if filing_status not in FILING_STATUSES and filing_status != _QSS:
        raise ValueError(
            f"unknown filing_status {filing_status!r} — use one of: single, married_filing_jointly, "
            f"married_filing_separately, head_of_household, qualifying_surviving_spouse"
        )
    magi_d = _to_decimal(magi, "magi")
    tips_d = _to_decimal(qualified_tips, "qualified_tips")
    overtime_d = _to_decimal(qualified_overtime, "qualified_overtime")
    car_d = _to_decimal(car_loan_interest, "car_loan_interest")
    for name, val in (("qualified_tips", tips_d), ("qualified_overtime", overtime_d), ("car_loan_interest", car_d)):
        if val < 0:
            raise ValueError(f"{name} must be >= 0 — pass the qualified dollar amount, got {val}")
    if not isinstance(seniors_qualifying, int) or isinstance(seniors_qualifying, bool) or seniors_qualifying < 0:
        raise ValueError("seniors_qualifying must be a whole count >= 0 (people born before January 2, 1961)")
    if seniors_qualifying > 2:
        raise ValueError("seniors_qualifying cannot exceed 2 — only the taxpayer and a spouse can qualify")
    if seniors_qualifying == 2 and filing_status != "married_filing_jointly":
        raise ValueError(
            f"seniors_qualifying=2 requires married_filing_jointly (the taxpayer AND the spouse) — a "
            f"{filing_status} return has one taxpayer, so at most 1 qualifying individual"
        )

    pack = _load_federal(year, knowledge_dir)
    params: ObbbaSchedule1aParams | None = pack.tax.obbba_schedule_1a
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.obbba_schedule_1a block. The Schedule 1-A "
            f"deductions (tips / overtime / car-loan interest / senior) exist for tax years 2025-2028 "
            f"only (P.L. 119-21) — for an earlier year there is nothing to compute; for 2026+ the block "
            f"ships once that year's Schedule 1-A publishes and is two-pass verified (the 2026 planning "
            f"pack declares it deliberately absent rather than carrying forward unverified figures)."
        )

    mfs = filing_status == "married_filing_separately"
    magi_whole = irs_round(magi_d)
    parts: list[Schedule1APart] = []
    work_lines = [
        f"Schedule 1-A ({year}) — MAGI (Part I) = ${magi_whole:,}; filing status {filing_status}.",
    ]
    if filing_status == _QSS:
        work_lines.append(
            "Qualifying surviving spouse files a NON-joint return: the `other` thresholds and caps "
            "apply here (each statute keys on 'a joint return'), UNLIKE the rate schedules where QSS "
            "uses the married-filing-jointly column."
        )

    _MFS_FORFEIT = (
        "forfeited on married filing separately — the instructions require a married taxpayer to "
        "file JOINTLY to claim this deduction"
    )

    def _step_part(
        part_id: str,
        form_line: str,
        name: str,
        amount: Decimal,
        cap: int,
        phaseout,
        *,
        forfeit_on_mfs: bool,
        lines_note: str,
        cap_note: str = "",
    ) -> None:
        input_whole = irs_round(amount)
        threshold = phaseout.magi_threshold.for_status(filing_status)
        if forfeit_on_mfs and mfs:
            parts.append(Schedule1APart(
                part=part_id, form_line=form_line, name=name, input_amount=input_whole, cap_applied=cap,
                tentative=0, magi_threshold=threshold, magi_excess=0, reduction=0, deduction=0,
                forfeited_reason=_MFS_FORFEIT,
            ))
            work_lines.append(f"Part {part_id} ({name}): ${input_whole:,} entered but {_MFS_FORFEIT}. Deduction $0.")
            return
        tentative = min(input_whole, cap)
        excess = max(Decimal(0), magi_d - threshold)
        units = _sched1a_step_units(excess, phaseout.excess_rounding)
        reduction = min(units * phaseout.reduction_per_1000_of_excess, tentative)
        deduction = tentative - reduction
        parts.append(Schedule1APart(
            part=part_id, form_line=form_line, name=name, input_amount=input_whole, cap_applied=cap,
            tentative=tentative, magi_threshold=threshold, magi_excess=irs_round(excess),
            reduction=reduction, deduction=deduction,
        ))
        rounding_word = "DOWN to the next lower" if phaseout.excess_rounding == "down" else "UP to the next higher"
        work_lines.append(
            f"Part {part_id} ({name}, {lines_note}): min(${input_whole:,}, ${cap:,} cap{cap_note}) = "
            f"${tentative:,}; MAGI excess over ${threshold:,} = ${irs_round(excess):,} -> "
            f"{units:,} whole $1,000 unit(s) (quotient rounded {rounding_word} whole number) x "
            f"${phaseout.reduction_per_1000_of_excess} = ${units * phaseout.reduction_per_1000_of_excess:,} "
            f"reduction -> deduction ${deduction:,}."
        )

    if tips_d > 0:
        cap_note = " — per RETURN; a joint return does NOT double it" if params.tips.cap_is_per_return else ""
        _step_part("II", "13", "No Tax on Tips", tips_d, params.tips.deduction_cap, params.tips.phaseout,
                   forfeit_on_mfs=not params.tips.mfs_allowed, lines_note="lines 4-13", cap_note=cap_note)
    if overtime_d > 0:
        _step_part("III", "21", "No Tax on Overtime", overtime_d,
                   params.overtime.deduction_cap.for_status(filing_status), params.overtime.phaseout,
                   forfeit_on_mfs=not params.overtime.mfs_allowed, lines_note="lines 14-21")
        # N-14 push-back: the marketing name produced a wrong conclusion in a real
        # session ("no tax on overtime ⇒ overtime is untaxed") — state the
        # distinction unprompted, in the work the user actually reads.
        work_lines.append(
            "Push-back on the name 'No Tax on Overtime': (1) only the FLSA-required PREMIUM HALF of "
            "time-and-a-half qualifies — the whole overtime wage is still taxable wages; (2) this is a "
            "BELOW-the-AGI-line deduction, so the overtime still raises AGI and every MAGI-tested item "
            "above it (IRA phase-outs, NIIT, this schedule's own phase-outs)."
        )
    if car_d > 0:
        _step_part("IV", "30", "Qualified passenger vehicle loan interest", car_d,
                   params.car_loan_interest.deduction_cap, params.car_loan_interest.phaseout,
                   forfeit_on_mfs=False, lines_note="lines 22-30")
    if seniors_qualifying > 0:
        sd = params.senior_deduction
        per_person = sd.amount_per_qualifying_individual
        threshold = sd.phaseout.magi_threshold.for_status(filing_status)
        total_base = per_person * seniors_qualifying
        if mfs and not sd.mfs_allowed:
            parts.append(Schedule1APart(
                part="V", form_line="37", name="Senior deduction", input_amount=total_base,
                cap_applied=total_base, tentative=0, magi_threshold=threshold, magi_excess=0,
                reduction=0, deduction=0, forfeited_reason=_MFS_FORFEIT,
            ))
            work_lines.append(f"Part V (Senior deduction): {seniors_qualifying} qualifying but {_MFS_FORFEIT}. Deduction $0.")
        else:
            excess = max(Decimal(0), magi_d - threshold)
            reduction_pp = min(irs_round(sd.phaseout.rate * excess), per_person)
            per_person_ded = per_person - reduction_pp
            deduction = per_person_ded * seniors_qualifying
            parts.append(Schedule1APart(
                part="V", form_line="37", name="Senior deduction", input_amount=total_base,
                cap_applied=total_base, tentative=total_base, magi_threshold=threshold,
                magi_excess=irs_round(excess), reduction=reduction_pp * seniors_qualifying,
                deduction=deduction,
            ))
            work_lines.append(
                f"Part V (Senior deduction, lines 31-37): {seniors_qualifying} qualifying individual(s) "
                f"({sd.birth_date_requirement}, valid SSN) x ${per_person:,}; MAGI excess over "
                f"${threshold:,} = ${irs_round(excess):,} x {sd.phaseout.rate} = ${reduction_pp:,} "
                f"reduction PER PERSON -> ${per_person_ded:,} each -> deduction ${deduction:,}."
            )

    total = sum(p.deduction for p in parts)
    work_lines.append(
        f"Line 38 total = ${total:,} -> Form 1040/1040-SR line 13b (Form 1040-NR line 13c); reduces "
        f"taxable income whether itemizing or taking the standard deduction."
    )
    work_lines.append(
        "Caller-judgment requirements NOT verified here: tipped-occupation list (IRS.gov/TippedOccupations, "
        "voluntary tips only, no SSTB tips); overtime = the FLSA premium HALF only; car loan = personal-use "
        "NEW vehicle, US final assembly, loan after 2024-12-31 secured by the vehicle, VIN on line 22, net "
        "of Schedule C/E/F amounts; valid SSNs where required."
    )

    return Schedule1AResult(
        total_deduction=total,
        parts=parts,
        inputs={
            "magi": magi_whole,
            "filing_status": filing_status,
            "year": year,
            "qualified_tips": irs_round(tips_d),
            "qualified_overtime": irs_round(overtime_d),
            "car_loan_interest": irs_round(car_d),
            "seniors_qualifying": seniors_qualifying,
        },
        work="\n".join(work_lines),
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Projection-mode ops (Phase H, H4): employee FICA by status period, the
# IRC 6654 estimated-tax safe harbor, and YTD annualization
# ---------------------------------------------------------------------------


class FicaSegment(BaseModel):
    """One wage segment's FICA outcome (a visa-status period, an employer, a scenario leg)."""

    model_config = ConfigDict(extra="forbid")

    label: str
    wages: int
    fica_exempt: bool
    social_security: Decimal = Field(description="6.2% of this segment's wages within the remaining wage base.")
    medicare: Decimal = Field(description="1.45% of this segment's wages — Medicare has NO wage base.")
    additional_medicare: Decimal = Field(
        description="0.9% withholding on this segment's share of wages over the $200,000 trigger."
    )
    total: Decimal
    exempt_reason: str | None = Field(
        default=None, description="Set on exempt segments: why no FICA was withheld (caller-confirmed status)."
    )


class EmployeeFicaResult(BaseModel):
    """Result of :func:`employee_fica`: the employee-side payroll tax projection."""

    model_config = ConfigDict(extra="forbid")

    total_fica: Decimal = Field(description="Sum of every segment's SS + Medicare + Additional Medicare.")
    social_security: Decimal
    medicare: Decimal
    additional_medicare: Decimal
    segments: list[FicaSegment]
    inputs: dict[str, Any]
    work: str
    citation: Citation


def employee_fica(
    wage_segments: Sequence[Mapping[str, Any]],
    year: int = 2025,
    knowledge_dir: str | Path | None = None,
) -> EmployeeFicaResult:
    """Employee-side FICA (social security + Medicare withholding) across wage
    segments — the projection op for a year whose FICA status CHANGES mid-year.

    Each segment is ``{wages, fica_exempt, label?}``, in chronological order.
    Whether a segment is exempt is CALLER judgment (quoted in the work), and the
    biggest trap is N-7b: **the F/J student FICA exemption is STATUS-based, not
    marital** — an exempt-individual nonresident on F-1/OPT/STEM OPT pays no
    FICA (IRC 3121(b)(19), Pub 519), and a §6013(g) election that makes the
    couple file jointly does NOT start FICA on the OPT spouse's wages. FICA
    switches on at the STATUS boundary (e.g. the H-1B start date), which is why
    the op takes segments rather than one annual wage figure.

    Mechanics enforced here, per Pub 15 section 9:

    * social security 6.2% up to the year's wage base, applied across the
      non-exempt segments in order (the base is one annual pool per person);
    * Medicare 1.45% on every non-exempt dollar — no wage base;
    * Additional Medicare Tax withholding 0.9% on non-exempt wages over
      $200,000, attributed to the segments that cross the trigger.

    Two per-employer nuances are disclosed, not modeled: an EMPLOYER applies the
    wage base and the $200,000 trigger to its own wages only, so a multi-employer
    year can over-withhold social security (recovered via the Schedule 3
    excess-SS credit — calc op ``excess_ss``) and mis-withhold the 0.9%
    (reconciled on Form 8959). This op computes the PERSON-level projection.
    """
    if not wage_segments:
        raise ValueError(
            "wage_segments must be a non-empty list of {wages, fica_exempt, label?} — one segment per "
            "FICA-status period (e.g. the OPT months and the H-1B months are two segments)"
        )
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.employee_social_security
    if params is None or params.medicare_rate is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no employee-side FICA parameters "
            f"(employee_social_security with medicare_rate / additional_medicare_withholding_*) — add "
            f"them with a citation to that year's Pub 15 section 9 (see knowledge/federal/2025.yaml)"
        )

    segments: list[FicaSegment] = []
    remaining_base = Decimal(params.ss_wage_base)
    cumulative_medicare_wages = Decimal(0)
    threshold = Decimal(params.additional_medicare_withholding_threshold)
    work_lines = [
        f"Employee FICA projection ({year}) — Pub 15 section 9: social security "
        f"{params.rate:%} up to the ${params.ss_wage_base:,} wage base; Medicare {params.medicare_rate:%} "
        f"with no wage base; Additional Medicare Tax withholding "
        f"{params.additional_medicare_withholding_rate:%} on wages over ${params.additional_medicare_withholding_threshold:,}.",
    ]
    exempt_note = (
        "fica_exempt per your confirmed status: an exempt-individual nonresident on F-1 (incl. OPT / "
        "STEM OPT / cap-gap) owes no FICA (IRC 3121(b)(19); Pub 519). The exemption is STATUS-based, "
        "not marital — a §6013(g)/(h) election does NOT start FICA on the exempt spouse's wages."
    )

    for i, raw in enumerate(wage_segments):
        if not isinstance(raw, Mapping):
            raise ValueError(f"wage_segments[{i}] must be a mapping {{wages, fica_exempt, label?}}")
        if "fica_exempt" not in raw or isinstance(raw.get("fica_exempt"), (int, float)) and not isinstance(raw.get("fica_exempt"), bool):
            raise ValueError(
                f"wage_segments[{i}] needs an explicit boolean fica_exempt — the status judgment is yours "
                f"(F/J exempt individual: True; H-1B and other statuses: False); never omit it"
            )
        exempt = bool(raw["fica_exempt"])
        wages = irs_round(_to_decimal(raw.get("wages", 0), f"wage_segments[{i}].wages"))
        if wages < 0:
            raise ValueError(f"wage_segments[{i}].wages must be >= 0, got {wages}")
        label = str(raw.get("label") or f"segment {i + 1}")
        if exempt:
            segments.append(FicaSegment(
                label=label, wages=wages, fica_exempt=True,
                social_security=Decimal("0.00"), medicare=Decimal("0.00"),
                additional_medicare=Decimal("0.00"), total=Decimal("0.00"),
                exempt_reason=exempt_note,
            ))
            work_lines.append(f"{label}: ${wages:,} wages, FICA-EXEMPT -> $0.00 ({exempt_note})")
            continue
        wages_d = Decimal(wages)
        ss_taxable = min(wages_d, remaining_base)
        remaining_base -= ss_taxable
        ss = (params.rate * ss_taxable).quantize(_CENT, rounding=ROUND_HALF_UP)
        medicare = (params.medicare_rate * wages_d).quantize(_CENT, rounding=ROUND_HALF_UP)
        before = max(Decimal(0), cumulative_medicare_wages - threshold)
        cumulative_medicare_wages += wages_d
        after = max(Decimal(0), cumulative_medicare_wages - threshold)
        addl = (params.additional_medicare_withholding_rate * (after - before)).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
        total = ss + medicare + addl
        segments.append(FicaSegment(
            label=label, wages=wages, fica_exempt=False,
            social_security=ss, medicare=medicare, additional_medicare=addl, total=total,
        ))
        capped = " (wage base reached)" if remaining_base == 0 and ss_taxable < wages_d else ""
        work_lines.append(
            f"{label}: ${wages:,} wages -> SS {params.rate:%} x ${ss_taxable:,.0f}{capped} = ${ss:,}; "
            f"Medicare {params.medicare_rate:%} = ${medicare:,}; Additional Medicare on "
            f"${(after - before):,.0f} over the trigger = ${addl:,}; segment total ${total:,}."
        )

    ss_total = sum((s.social_security for s in segments), Decimal("0.00"))
    med_total = sum((s.medicare for s in segments), Decimal("0.00"))
    addl_total = sum((s.additional_medicare for s in segments), Decimal("0.00"))
    grand = ss_total + med_total + addl_total
    work_lines.append(
        f"Totals: social security ${ss_total:,} + Medicare ${med_total:,} + Additional Medicare "
        f"${addl_total:,} = ${grand:,} employee FICA for the year."
    )
    work_lines.append(
        "Per-employer nuances NOT modeled (disclosed): each employer applies the wage base and the "
        "$200,000 trigger to its own wages only — a multi-employer year can over-withhold social "
        "security (recover via the Schedule 3 excess-SS credit, calc op excess_ss) and the 0.9% "
        "withholding reconciles against the status-based thresholds on Form 8959."
    )
    return EmployeeFicaResult(
        total_fica=grand,
        social_security=ss_total,
        medicare=med_total,
        additional_medicare=addl_total,
        segments=segments,
        inputs={"wage_segments": [dict(s) for s in wage_segments], "year": year},
        work="\n".join(work_lines),
        citation=params.citation,
    )


class SafeHarborResult(BaseModel):
    """Result of :func:`estimated_tax_safe_harbor`: the IRC 6654(d) required annual payment."""

    model_config = ConfigDict(extra="forbid")

    required_annual_payment: int = Field(
        description="min(current-year prong, prior-year prong) — withholding at or above this is SAFE."
    )
    current_year_prong: int = Field(description="90% of the projected current-year tax.")
    prior_year_prong: int | None = Field(
        description="100%/110% of the prior year's tax; None when the prior figures were not supplied."
    )
    prior_pct_applied: Decimal | None = Field(
        description="The prior-year percentage used (1.00 or 1.10); None without prior figures."
    )
    estimated_payments_required: bool = Field(
        description="True when the expected balance is at least the $1,000 de minimis AND withholding "
        "falls short of the required annual payment."
    )
    shortfall: int = Field(description="required_annual_payment - expected withholding, floored at 0.")
    quarterly_payment: int = Field(description="The shortfall spread over four installments (rounded).")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def estimated_tax_safe_harbor(
    projected_tax: int | float | Decimal | str,
    expected_withholding: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2025,
    prior_year_agi: int | None = None,
    prior_year_total_tax: int | None = None,
    knowledge_dir: str | Path | None = None,
) -> SafeHarborResult:
    """The IRC 6654(d) estimated-tax safe harbor (Form 1040-ES, 'General Rule'):
    will the year's withholding be enough to avoid an underpayment penalty?

    ``projected_tax`` is the CURRENT year's expected total tax (the Form 1040
    line 24 equivalent — for a planning year, project it with the calc/estimate
    surface first). ``prior_year_agi`` / ``prior_year_total_tax`` come off the
    PRIOR year's filed return (lines 11 and 24; intake stores them on
    PriorFilings) — supply BOTH or NEITHER. The prior-year prong exists only
    when the prior return covered all 12 months (caller judgment, disclosed).

    Rules enforced exactly as printed: required annual payment = the smaller of
    90% of the current year's tax and 100% of the prior year's — 110% when the
    PRIOR year's AGI exceeded $150,000 ($75,000 when the CURRENT year's status
    is married filing separately: the AGI is last year's, the status test is
    this year's). No estimated payments are due at all when the expected
    balance after withholding is under the $1,000 de minimis. Farmers/fishermen
    substitution (66 2/3%) is quoted, never computed.

    The work also quotes the N-12 withholding-realism trap: supplemental wages
    (bonuses) are withheld at the FLAT 22% no matter your marginal rate, so a
    higher-bracket filer under-withholds on every bonus — project
    ``expected_withholding`` accordingly (bonus withholding = 22% x bonus).
    """
    if filing_status not in FILING_STATUSES and filing_status != _QSS:
        raise ValueError(
            f"unknown filing_status {filing_status!r} — use one of: single, married_filing_jointly, "
            f"married_filing_separately, head_of_household, qualifying_surviving_spouse"
        )
    tax_d = _to_decimal(projected_tax, "projected_tax")
    wh_d = _to_decimal(expected_withholding, "expected_withholding")
    if tax_d < 0 or wh_d < 0:
        raise ValueError("projected_tax and expected_withholding must be >= 0")
    if (prior_year_agi is None) != (prior_year_total_tax is None):
        raise ValueError(
            "supply BOTH prior_year_agi and prior_year_total_tax (prior return lines 11 and 24) or "
            "NEITHER — the 110%-vs-100% tier needs the AGI, and the prong needs the tax; one without "
            "the other cannot be evaluated"
        )
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.estimated_tax_safe_harbor
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no estimated_tax_safe_harbor block — add it with a "
            f"citation to that year's Form 1040-ES 'General Rule' (see knowledge/federal/2025.yaml)"
        )

    current_prong = irs_round(params.current_year_pct * tax_d)
    threshold = (
        params.high_income_agi_threshold_mfs
        if filing_status == "married_filing_separately"
        else params.high_income_agi_threshold
    )
    prior_prong: int | None = None
    prior_pct: Decimal | None = None
    if prior_year_total_tax is not None:
        assert prior_year_agi is not None
        if prior_year_agi < 0 or prior_year_total_tax < 0:
            raise ValueError("prior_year_agi and prior_year_total_tax must be >= 0")
        prior_pct = (
            params.high_income_prior_year_pct if prior_year_agi > threshold else params.prior_year_pct
        )
        prior_prong = irs_round(prior_pct * Decimal(prior_year_total_tax))
    required = current_prong if prior_prong is None else min(current_prong, prior_prong)
    balance = irs_round(tax_d - wh_d)
    payments_required = balance >= params.underpayment_de_minimis and irs_round(wh_d) < required
    shortfall = max(0, required - irs_round(wh_d)) if payments_required else 0
    quarterly = irs_round(Decimal(shortfall) / 4) if shortfall else 0

    work_lines = [
        f"IRC 6654(d) safe harbor ({year}), filing status {filing_status}:",
        f"Current-year prong: {params.current_year_pct:%} x ${irs_round(tax_d):,} projected tax = ${current_prong:,}.",
    ]
    if prior_prong is not None:
        tier = (
            f"prior-year AGI ${prior_year_agi:,} > ${threshold:,} -> {params.high_income_prior_year_pct:%}"
            if prior_pct == params.high_income_prior_year_pct
            else f"prior-year AGI ${prior_year_agi:,} <= ${threshold:,} -> {params.prior_year_pct:%}"
        )
        work_lines.append(
            f"Prior-year prong: {tier} x ${prior_year_total_tax:,} prior tax = ${prior_prong:,} "
            f"(valid only if the prior return covered all 12 months — your judgment; the MFS "
            f"${params.high_income_agi_threshold_mfs:,} threshold keys on the CURRENT year's status)."
        )
    else:
        work_lines.append(
            "Prior-year prong NOT evaluated (prior_year_agi / prior_year_total_tax not supplied) — the "
            "required payment shown uses the 90% prong alone; the prior-year prong is often SMALLER, so "
            "supplying the prior return's lines 11 and 24 can only help."
        )
    work_lines.append(
        f"Required annual payment = ${required:,}; expected withholding ${irs_round(wh_d):,}; expected "
        f"balance ${balance:,} vs the ${params.underpayment_de_minimis:,} de minimis -> estimated "
        f"payments {'REQUIRED' if payments_required else 'not required'}"
        + (f"; shortfall ${shortfall:,} (${quarterly:,}/quarter over four installments)." if shortfall else ".")
    )
    work_lines.append(params.farmers_fishermen_note)
    sw = pack.tax.supplemental_withholding
    if sw is not None:
        work_lines.append(
            f"Withholding realism (Pub 15 section 7): supplemental wages (bonuses) are withheld at the "
            f"FLAT {sw.flat_rate:%} regardless of your marginal rate ({sw.high_rate:%} only on the "
            f"excess over ${sw.high_threshold:,}) — a filer in a higher bracket under-withholds on "
            f"every bonus, and the gap lands in this shortfall. Project expected_withholding as "
            f"{sw.flat_rate:%} x bonus for supplemental pay."
        )

    return SafeHarborResult(
        required_annual_payment=required,
        current_year_prong=current_prong,
        prior_year_prong=prior_prong,
        prior_pct_applied=prior_pct,
        estimated_payments_required=payments_required,
        shortfall=shortfall,
        quarterly_payment=quarterly,
        inputs={
            "projected_tax": irs_round(tax_d),
            "expected_withholding": irs_round(wh_d),
            "filing_status": filing_status,
            "year": year,
            "prior_year_agi": prior_year_agi,
            "prior_year_total_tax": prior_year_total_tax,
        },
        work="\n".join(work_lines),
        citation=params.citation,
    )


class AnnualizeResult(BaseModel):
    """Result of :func:`annualize_ytd`. No citation: this is disclosed arithmetic, not tax law."""

    model_config = ConfigDict(extra="forbid")

    annualized: int
    ytd_amount: int
    days_elapsed: int
    days_in_year: int
    inputs: dict[str, Any]
    work: str


def annualize_ytd(
    ytd_amount: int | float | Decimal | str,
    through: date | datetime | str,
    year: int,
) -> AnnualizeResult:
    """Project a year-to-date paystub figure to a full-year amount by calendar-day
    proration: ``ytd x days_in_year / days_elapsed``.

    Deterministic home for the one arithmetic step every projection needs (hard
    rule #1: the agent never does the math itself). Carries NO citation — there
    is no authority for straight-line proration; it is an ASSUMPTION, and the
    work says exactly when it breaks: level pay only. A raise, a bonus, or a
    mid-year FICA-status change breaks linearity — annualize each segment
    separately (and bonuses are not annualized at all; they are one-time).
    """
    amount = _to_decimal(ytd_amount, "ytd_amount")
    if amount < 0:
        raise ValueError("ytd_amount must be >= 0 — annualize income and withholding separately")
    through_d = _as_date(through, "through")
    if through_d.year != year:
        raise ValueError(
            f"through date {through_d.isoformat()} is not in year {year} — pass the paystub's "
            f"period-end date for the year being projected"
        )
    days_elapsed = (through_d - date(year, 1, 1)).days + 1
    days_in_year = (date(year, 12, 31) - date(year, 1, 1)).days + 1
    annualized = irs_round(amount * days_in_year / days_elapsed)
    work = (
        f"Annualize ({year}): ${irs_round(amount):,} through {through_d.isoformat()} "
        f"({days_elapsed} of {days_in_year} days) x {days_in_year}/{days_elapsed} = ${annualized:,}. "
        f"ASSUMES LEVEL PAY: a raise, a bonus, or a mid-year FICA-status change breaks straight-line "
        f"proration — annualize each segment separately, and never annualize one-time amounts "
        f"(bonuses, RSU vests); add those at face value."
    )
    return AnnualizeResult(
        annualized=annualized,
        ytd_amount=irs_round(amount),
        days_elapsed=days_elapsed,
        days_in_year=days_in_year,
        inputs={"ytd_amount": irs_round(amount), "through": through_d.isoformat(), "year": year},
        work=work,
    )


# ---------------------------------------------------------------------------
# Tax-advantaged account ops (Phase H, H8): the limits lookup, the IRA
# eligibility guard, the marginal-dollar ranking, and the MAGI ladder
# ---------------------------------------------------------------------------


def _require_contribution_limits(pack: KnowledgePack, year: int) -> ContributionLimitsParams:
    params = pack.contribution_limits
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no contribution_limits block — add it with citations "
            f"to that year's COLA notice (retirement), HSA revenue procedure, and inflation-adjustment "
            f"revenue procedure (see knowledge/federal/2025.yaml)"
        )
    return params


class ContributionLimitsResult(BaseModel):
    """Result of :func:`contribution_limits`: every bucket with its SCOPING spelled out."""

    model_config = ConfigDict(extra="forbid")

    limits: ContributionLimitsParams
    scoping: dict[str, str] = Field(description="Bucket -> one-sentence scoping answer, quotable to the user.")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def contribution_limits(
    year: int = 2025,
    knowledge_dir: str | Path | None = None,
) -> ContributionLimitsResult:
    """The year's tax-advantaged account limits WITH their scoping — because the
    real question is never just the amount.

    The motivating session's question was "is the 401(k) limit one per person?",
    and the useful answer is that the big limits are scoped four different ways:

    * 402(g) elective deferral — per PERSON across every employer, and
      traditional + Roth deferrals share the one limit (a split moves AGI,
      never the cap);
    * 415(c) annual additions — per EMPLOYER PLAN (employee + employer +
      after-tax), which is what makes a mega-backdoor possible;
    * IRA — per person across traditional + Roth combined;
    * HSA — per COVERAGE TIER, so two unmarried self-only HDHP holders can
      contribute more together than one family plan allows;
    * 125(i) health FSA — per employee per employer;
    * 132(f) commuter — per month, transit and parking separately.

    Payroll HSA/FSA/commuter dollars also avoid FICA where 401(k) dollars do not,
    but "FICA" is not one rate: the full 7.65% applies only BELOW the social
    security wage base, and above it the saving is Medicare alone (1.45%, or
    2.35% once the 0.9% Additional Medicare withholding threshold is passed) —
    exactly the population that maxes these buckets.
    :func:`marginal_dollar_savings` picks the tier and turns it into a ranking,
    and :func:`hsa_deduction` turns the HSA ceiling above into the Form 8889
    line that is actually deductible.
    """
    pack = _load_federal(year, knowledge_dir)
    params = _require_contribution_limits(pack, year)
    d = params.elective_deferral_402g
    scoping = {
        "elective_deferral_402g": (
            f"${d.limit:,} per PERSON across ALL employers for {year}; traditional and Roth deferrals "
            f"share this one limit"
            + (f"; age-50 catch-up ${d.catch_up_50:,}" if d.catch_up_50 else "")
            + (f"; age-60-63 higher catch-up ${d.catch_up_60_63:,}" if d.catch_up_60_63 else "")
            + ". A 401(k) dollar still pays FICA."
        ),
        "annual_additions_415c": (
            f"${params.annual_additions_415c.limit:,} per EMPLOYER PLAN (employee + employer + "
            f"after-tax contributions combined) — separate employers get separate {year} limits, which "
            f"is what makes after-tax 'mega-backdoor' room possible."
        ),
        "ira": (
            f"${params.ira.limit:,} per person across traditional + Roth IRAs combined for {year}"
            + (f" (+${params.ira.catch_up_50:,} at 50+)" if params.ira.catch_up_50 else "")
            + "; Roth eligibility and the traditional DEDUCTION phase out on MAGI — check "
            + "ira_contribution_eligibility before contributing."
        ),
        "hsa": (
            f"${params.hsa.self_only:,} self-only / ${params.hsa.family:,} family for {year} — the limit "
            f"follows the HDHP COVERAGE TIER, not the household: two unmarried people with self-only "
            f"coverage get ${2 * params.hsa.self_only:,} together, "
            f"{'MORE than' if 2 * params.hsa.self_only > params.hsa.family else 'vs'} the family "
            f"${params.hsa.family:,}"
            + (f" (+${params.hsa.catch_up_55:,} per PERSON at 55+, so a couple needs TWO HSAs to take it "
               f"twice)" if params.hsa.catch_up_55 else "")
            + ". This annual figure is a CEILING, not the amount: IRC 223(b)(1)-(2) tests eligibility "
            "on the FIRST DAY of each month and allows 1/12 per eligible month, and a general-purpose "
            "health FSA — including a SPOUSE's (Rev. Rul. 2004-45) — makes those months ineligible "
            "outright. Run hsa_deduction before recording any HSA contribution: it prorates, applies "
            "the 223(b)(8) last-month rule with its 13-month testing period, and keeps W-2 box 12 code "
            "W out of the deduction (that money is already excluded from box 1, so deducting it again "
            "is the classic HSA error). Payroll HSA dollars also avoid FICA — but only the FULL 7.65% "
            "BELOW the social security wage base; above it the saving is Medicare 1.45%, or 2.35% once "
            "the 0.9% Additional Medicare withholding threshold is passed, and that is exactly the "
            "population that maxes an HSA. marginal_dollar_savings picks the tier."
        ),
        "health_fsa_125i": (
            f"${params.health_fsa_125i.limit:,} per EMPLOYEE per EMPLOYER for {year}"
            + (f" (carryover up to ${params.health_fsa_125i.carryover:,})" if params.health_fsa_125i.carryover else "")
            + "; payroll FSA dollars also avoid FICA — the full 7.65% only BELOW the social security "
              "wage base, 1.45% above it and 2.35% past the 0.9% Additional Medicare threshold. A "
              "GENERAL-PURPOSE health FSA also destroys HSA eligibility for every month it covers you, "
              "a spouse's included (Rev. Rul. 2004-45); a limited-purpose (dental/vision) or "
              "post-deductible one does not."
        ),
        # The caps are only half the answer: pitfall P-006 is a real session that
        # had the limits and still had to research WHAT QUALIFIES. The eligibility
        # rules are year-invariant, so they ride the scoping string rather than the
        # per-year pack.
        "commuter_132f": (
            f"${params.commuter_132f.transit_monthly:,}/month transit and "
            f"${params.commuter_132f.parking_monthly:,}/month parking for {year}, separately; "
            f"payroll commuter dollars also avoid FICA — the full 7.65% only BELOW the social "
            f"security wage base, 1.45% above it and 2.35% past the 0.9% Additional Medicare "
            f"threshold. ELIGIBILITY (P-006, year-invariant): "
            f"qualified transportation benefits are an EXHAUSTIVE list of three — a ride in a "
            f"commuter highway vehicle (6+ adults excluding the driver, 80% of mileage "
            f"commuting), a transit pass, and qualified parking. Vehicle ENERGY is never among "
            f"them: fuel and EV charging are as ineligible as tolls and mileage. Qualified "
            f"parking is parking on or near the EMPLOYER's premises, or near where the employee "
            f"catches transit/vanpool/carpool — parking at or near the employee's HOME is "
            f"expressly excluded, and employer-provided free parking leaves nothing to shelter. "
            f"Reimbursement requires the employee to INCUR AND SUBSTANTIATE the expense BEFORE "
            f"payment, and cash reimbursement for transit passes is barred wherever a "
            f"transit-only voucher is readily available; amounts failing these tests are WAGES, "
            f"not an exclusion (and cash can never fall back on the de minimis rule). "
            f"Authority: get_sources('commuter benefits')."
        ),
    }
    work = f"Contribution limits and SCOPING for {year}:\n" + "\n".join(f"* {k}: {v}" for k, v in scoping.items())
    return ContributionLimitsResult(
        limits=params, scoping=scoping, inputs={"year": year}, work=work, citation=params.citation
    )


class IraEligibilityResult(BaseModel):
    """Result of :func:`ira_contribution_eligibility`: the reduced limit + any excess."""

    model_config = ConfigDict(extra="forbid")

    allowed: int = Field(description="The MAGI-reduced contribution (Roth) or deduction (traditional) limit.")
    full_limit: int = Field(description="The unreduced limit used (incl. the age-50 catch-up when claimed).")
    phaseout: dict[str, int] = Field(description="{start, end} of the range applied.")
    magi_position: Literal["below", "within", "above"]
    excess: int = Field(description="max(0, contributed - allowed) — the amount the 6% excise bites.")
    excise_per_year: int = Field(description="IRC 4973: 6% of the excess, charged EVERY year until fixed.")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def ira_contribution_eligibility(
    magi: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2025,
    ira_type: str = "roth",
    contributed: int | float | Decimal | str = 0,
    age_50_plus: bool = False,
    covered_by_employer_plan: bool | None = None,
    spouse_covered_by_employer_plan: bool | None = None,
    mfs_lived_apart_all_year: bool = False,
    knowledge_dir: str | Path | None = None,
) -> IraEligibilityResult:
    """The Pub 590-A reduced-limit worksheet: how much Roth IRA contribution (or
    traditional-IRA DEDUCTION) the MAGI actually allows — and the 6%-per-year
    excise on any excess already contributed.

    This op exists because the one real planning session caught a LIVE error of
    exactly this shape: a single filer contributing to a Roth IRA with MAGI
    above the phase-out — a 6%-per-year excise (IRC 4973) that nobody notices
    until it has compounded. Two facts the work always states:

    * eligibility is tested on the YEAR-END filing status and full-year MAGI —
      an ineligible contribution can FLIP TO COMPLIANT by marrying and filing
      jointly, because the MFJ range is far higher (and vice versa: MFS is
      phased out almost immediately unless the spouses lived apart ALL year,
      in which case the single range applies — set mfs_lived_apart_all_year);
    * an excess is fixable without the excise by withdrawing the contribution
      plus earnings before the filing deadline, or recharacterizing.

    ``ira_type``: 'roth' (contribution eligibility) or 'traditional_deduction'
    (the deduction phase-out — a NONDEDUCTIBLE traditional contribution is
    always allowed up to the limit regardless of MAGI). The deduction path
    needs ``covered_by_employer_plan`` (and, on a joint return,
    ``spouse_covered_by_employer_plan``): no coverage anywhere means NO
    phase-out at all.

    Worksheet mechanics from the pack (Pub 590-A): the reduced limit rounds UP
    to the nearest $10, and a partial phase-out never drops below $200.
    """
    if filing_status not in FILING_STATUSES and filing_status != _QSS:
        raise ValueError(
            f"unknown filing_status {filing_status!r} — use one of: single, married_filing_jointly, "
            f"married_filing_separately, head_of_household, qualifying_surviving_spouse"
        )
    if ira_type not in ("roth", "traditional_deduction"):
        raise ValueError(
            f"ira_type must be 'roth' or 'traditional_deduction', got {ira_type!r} — a nondeductible "
            f"traditional contribution needs no eligibility check (always allowed up to the limit)"
        )
    magi_d = _to_decimal(magi, "magi")
    contributed_i = irs_round(_to_decimal(contributed, "contributed"))
    if contributed_i < 0:
        raise ValueError("contributed must be >= 0")
    pack = _load_federal(year, knowledge_dir)
    params = _require_contribution_limits(pack, year)
    ira = params.ira
    full_limit = ira.limit + (ira.catch_up_50 or 0 if age_50_plus else 0)

    mfj_like = filing_status in ("married_filing_jointly", _QSS)
    mfs = filing_status == "married_filing_separately"
    notes: list[str] = []
    if ira_type == "roth":
        if mfs and mfs_lived_apart_all_year:
            rng = ira.roth_magi_phaseout.single_hoh
            notes.append(
                "MFS but lived apart from the spouse ALL year: Pub 590-A treats this as the single "
                "range (your judgment — the default MFS range is $0-$10,000)."
            )
        elif mfs:
            rng = ira.roth_magi_phaseout.married_filing_separately
        elif mfj_like:
            rng = ira.roth_magi_phaseout.married_filing_jointly
        else:
            rng = ira.roth_magi_phaseout.single_hoh
    else:
        if covered_by_employer_plan is None:
            raise ValueError(
                "traditional_deduction needs covered_by_employer_plan (True/False) — the phase-out "
                "exists ONLY for active participants; with no coverage anywhere the deduction is "
                "unlimited by MAGI (on a joint return also pass spouse_covered_by_employer_plan)"
            )
        if not covered_by_employer_plan:
            if mfj_like and spouse_covered_by_employer_plan is None:
                raise ValueError(
                    "on a joint return with covered_by_employer_plan=False, pass "
                    "spouse_covered_by_employer_plan (True/False) — a covered SPOUSE triggers the "
                    "higher spousal phase-out range"
                )
            if mfj_like and spouse_covered_by_employer_plan:
                rng = ira.deduction_magi_phaseout_active.married_filing_jointly_spouse_covered
                notes.append("Not covered yourself, but the spouse is: the higher spousal range applies.")
            else:
                # No employer plan anywhere: fully deductible regardless of MAGI.
                work = (
                    f"Traditional-IRA deduction {year}: neither spouse is an active participant in an "
                    f"employer plan, so NO MAGI phase-out applies — deductible up to the "
                    f"${full_limit:,} limit (IRC 219; Pub 590-A). Contributed ${contributed_i:,} -> "
                    f"excess ${max(0, contributed_i - full_limit):,}."
                )
                excess = max(0, contributed_i - full_limit)
                return IraEligibilityResult(
                    allowed=full_limit, full_limit=full_limit,
                    phaseout={"start": 0, "end": 0}, magi_position="below",
                    excess=excess, excise_per_year=irs_round(ira.excess_excise_rate * excess),
                    inputs={"magi": irs_round(magi_d), "filing_status": filing_status, "year": year,
                            "ira_type": ira_type, "contributed": contributed_i},
                    work=work, citation=ira.citation,
                )
        else:
            if mfs:
                rng = ira.deduction_magi_phaseout_active.married_filing_separately
            elif mfj_like:
                rng = ira.deduction_magi_phaseout_active.married_filing_jointly_covered
            else:
                rng = ira.deduction_magi_phaseout_active.single_hoh

    if magi_d <= rng.start:
        allowed, position = full_limit, "below"
    elif magi_d >= rng.end:
        allowed, position = 0, "above"
    else:
        position = "within"
        span = Decimal(rng.end - rng.start)
        raw = Decimal(full_limit) * (Decimal(rng.end) - magi_d) / span
        # Pub 590-A: round UP to the nearest $10; a partial phase-out never goes below $200.
        step = Decimal(ira.worksheet.round_up_to)
        allowed_d = (raw / step).to_integral_value(rounding="ROUND_CEILING") * step
        allowed = int(allowed_d)
        if 0 < allowed < ira.worksheet.minimum_if_partial:
            allowed = ira.worksheet.minimum_if_partial

    excess = max(0, contributed_i - allowed)
    excise = irs_round(ira.excess_excise_rate * excess)
    kind = "Roth IRA contribution" if ira_type == "roth" else "traditional-IRA deduction"
    work_lines = [
        f"{kind} eligibility ({year}, {filing_status}): MAGI ${irs_round(magi_d):,} vs the "
        f"${rng.start:,}-${rng.end:,} phase-out -> {position}; limit ${full_limit:,}"
        + (f" (incl. ${ira.catch_up_50:,} age-50 catch-up)" if age_50_plus and ira.catch_up_50 else "")
        + f" -> allowed ${allowed:,}"
        + (
            f" (worksheet: limit x (range end - MAGI)/range span, rounded UP to the nearest "
            f"${ira.worksheet.round_up_to}, minimum ${ira.worksheet.minimum_if_partial} while partially "
            f"phased)" if position == "within" else ""
        )
        + ".",
    ]
    work_lines.extend(notes)
    if excess:
        work_lines.append(
            f"EXCESS: contributed ${contributed_i:,} -> ${excess:,} over the allowed amount. IRC 4973 "
            f"charges {ira.excess_excise_rate:%} of the excess (${excise:,}) EVERY year until it is "
            f"withdrawn or absorbed — fixable WITHOUT the excise by withdrawing the contribution plus "
            f"earnings before the filing deadline, or recharacterizing."
        )
    work_lines.append(
        f"Eligibility is tested at YEAR END: {ira.eligibility_tested_at} A contribution that is excess "
        f"under today's status can flip to compliant on a year-end married-filing-jointly return "
        f"(the MFJ range is far higher) — and the reverse."
    )
    return IraEligibilityResult(
        allowed=allowed, full_limit=full_limit,
        phaseout={"start": rng.start, "end": rng.end}, magi_position=position,
        excess=excess, excise_per_year=excise,
        inputs={"magi": irs_round(magi_d), "filing_status": filing_status, "year": year,
                "ira_type": ira_type, "contributed": contributed_i, "age_50_plus": age_50_plus},
        work="\n".join(work_lines), citation=ira.citation,
    )


class MarginalDollarRow(BaseModel):
    """One bucket's saving on the NEXT pre-tax dollar."""

    model_config = ConfigDict(extra="forbid")

    bucket: str
    income_tax_saving: Decimal = Field(description="The federal marginal rate applied to $1.")
    fica_saving: Decimal = Field(description="The payroll FICA avoided on $1 (0 where the dollar still pays FICA).")
    total_per_dollar: Decimal
    note: str


class MarginalDollarResult(BaseModel):
    """Result of :func:`marginal_dollar_savings`: the buckets ranked by savings per dollar."""

    model_config = ConfigDict(extra="forbid")

    marginal_rate: Decimal
    fica_tier: str = Field(description="Which FICA tier the next wage dollar sits in, and why.")
    rows: list[MarginalDollarRow] = Field(description="Largest saving first.")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def marginal_dollar_savings(
    taxable_income: int | float | Decimal | str,
    wages: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2025,
    knowledge_dir: str | Path | None = None,
) -> MarginalDollarResult:
    """"Where does one more pre-tax dollar save the most?" — the ranking the one
    real planning session built by hand.

    The two facts the ranking turns on, both from pack data:

    * a payroll HSA/FSA/commuter dollar (cafeteria plan) avoids FICA as well as
      income tax; a 401(k) or deductible-IRA dollar avoids income tax only;
    * ABOVE the social security wage base the FICA saving is only Medicare
      (1.45%, plus 0.9% over $200,000) — never the full 7.65%.

    Federal income tax only (state marginal rates stack on top — disclosed);
    Roth dollars save $0 today by design, so they are not rows here — the
    now-vs-retirement trade is judgment, not arithmetic.
    """
    if filing_status not in FILING_STATUSES and filing_status != _QSS:
        raise ValueError(
            f"unknown filing_status {filing_status!r} — use one of: single, married_filing_jointly, "
            f"married_filing_separately, head_of_household, qualifying_surviving_spouse"
        )
    taxable_d = _to_decimal(taxable_income, "taxable_income")
    wages_d = _to_decimal(wages, "wages")
    if taxable_d < 0 or wages_d < 0:
        raise ValueError("taxable_income and wages must be >= 0")
    pack = _load_federal(year, knowledge_dir)
    _require_contribution_limits(pack, year)  # the buckets must exist for the year
    ess = pack.tax.employee_social_security
    if ess is None or ess.medicare_rate is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no employee-side FICA parameters — add the "
            f"medicare fields to employee_social_security (see knowledge/federal/2025.yaml)"
        )
    status_key, alias_note = _resolve_filing_status(filing_status)
    schedule = pack.tax.rate_schedules.schedules[status_key]
    marginal = schedule[0].rate
    for bracket in schedule:
        if taxable_d > bracket.over:
            marginal = bracket.rate

    # The 0.9% tier keys on the Form 8959 TAX threshold, which is FILING-STATUS
    # specific ($250,000 MFJ / $125,000 MFS / $200,000 otherwise, IRC 3101(b)(2)),
    # NOT on the employer's status-blind $200,000 WITHHOLDING threshold. The
    # difference is a real wrong answer, found 2026-08-26: an MFJ filer with
    # $210,000 of wages has 0.9% WITHHELD, but owes none of it — combined wages are
    # under $250,000, so it comes back as a credit on the return and the marginal
    # payroll dollar saves Medicare only. Withholding is trued up; the tax is what
    # a planning answer must price.
    amt = pack.tax.additional_medicare_tax
    if amt is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.additional_medicare_tax block — add it "
            f"(rate 0.009 + the five statutory thresholds) with a citation, or this op cannot say "
            f"whether the 0.9% tier applies"
        )
    threshold = Decimal(_surtax_threshold(amt.thresholds, filing_status, "additional_medicare_tax"))
    withholding_threshold = Decimal(ess.additional_medicare_withholding_threshold)
    if wages_d < ess.ss_wage_base:
        fica = ess.rate + ess.medicare_rate
        tier = (
            f"wages ${irs_round(wages_d):,} are BELOW the ${ess.ss_wage_base:,} wage base -> a payroll "
            f"dollar avoids the full {fica:%} (SS {ess.rate:%} + Medicare {ess.medicare_rate:%})"
        )
    elif wages_d <= threshold:
        fica = ess.medicare_rate
        withheld_note = (
            f" (your employer still WITHHOLDS the extra {amt.rate:%} above "
            f"${irs_round(withholding_threshold):,} — that is status-blind — but Form 8959 measures the "
            f"TAX against your {filing_status} threshold of ${irs_round(threshold):,}, so the "
            f"over-withholding comes back as a credit and the marginal dollar does not save it)"
            if wages_d > withholding_threshold else ""
        )
        tier = (
            f"wages ${irs_round(wages_d):,} are ABOVE the ${ess.ss_wage_base:,} wage base -> SS is "
            f"already capped; a payroll dollar avoids only Medicare {fica:%}, never 7.65%{withheld_note}"
        )
    else:
        fica = ess.medicare_rate + amt.rate
        tier = (
            f"wages ${irs_round(wages_d):,} exceed the {filing_status} Form 8959 threshold of "
            f"${irs_round(threshold):,} -> a payroll dollar avoids Medicare {ess.medicare_rate:%} + "
            f"Additional Medicare {amt.rate:%} = {fica:%} (SS already capped)"
        )

    zero = Decimal("0")
    rows = [
        MarginalDollarRow(
            bucket="hsa_payroll", income_tax_saving=marginal, fica_saving=fica,
            total_per_dollar=marginal + fica,
            note="Cafeteria-plan HSA: income tax AND FICA avoided; triple-advantaged on the way out too.",
        ),
        MarginalDollarRow(
            bucket="health_fsa", income_tax_saving=marginal, fica_saving=fica,
            total_per_dollar=marginal + fica,
            note="FSA: same payroll savings as HSA, but use-it-or-lose-it beyond the carryover.",
        ),
        MarginalDollarRow(
            bucket="commuter_132f", income_tax_saving=marginal, fica_saving=fica,
            total_per_dollar=marginal + fica,
            note="Commuter: same payroll savings, capped monthly, only against actual transit/parking spend.",
        ),
        MarginalDollarRow(
            bucket="401k_pretax", income_tax_saving=marginal, fica_saving=zero,
            total_per_dollar=marginal,
            note="Pre-tax 401(k): income tax deferred, but the dollar still pays FICA.",
        ),
        MarginalDollarRow(
            bucket="traditional_ira_deductible", income_tax_saving=marginal, fica_saving=zero,
            total_per_dollar=marginal,
            note="Deductible IRA: income tax only (post-payroll money) — and the deduction itself phases "
                 "out for active participants; check ira_contribution_eligibility first.",
        ),
    ]
    rows.sort(key=lambda r: (-r.total_per_dollar, r.bucket))
    work_lines = [
        f"Marginal-dollar savings ({year}, {filing_status}): federal marginal rate {marginal:%} at "
        f"taxable income ${irs_round(taxable_d):,}." + (f" ({alias_note}.)" if alias_note else ""),
        tier,
        *(f"* {r.bucket}: {r.income_tax_saving:%} income tax + {r.fica_saving:%} FICA = "
          f"{r.total_per_dollar:%} per $1 — {r.note}" for r in rows),
        "Federal only: a state marginal rate stacks on the income-tax side (calc op state_tax's "
        "jurisdiction rules). Roth dollars save $0 TODAY by design — the now-vs-retirement trade is "
        "judgment, not arithmetic. Employer match is free money ahead of everything here.",
    ]
    return MarginalDollarResult(
        marginal_rate=marginal, fica_tier=tier, rows=rows,
        inputs={"taxable_income": irs_round(taxable_d), "wages": irs_round(wages_d),
                "filing_status": filing_status, "year": year},
        work="\n".join(work_lines), citation=pack.tax.rate_schedules.citation,
    )


class MagiLadderRow(BaseModel):
    """One MAGI test: its own definition, its own threshold, this filer's position."""

    model_config = ConfigDict(extra="forbid")

    test: str
    magi_used: int = Field(description="The MAGI (or wage figure) THIS test measures — they differ by test.")
    threshold: str = Field(description="The trigger: a single threshold or a phase-out range, as printed.")
    position: Literal["below", "within", "above"]
    headroom: int = Field(description="Dollars until the test starts to bite (0 when already within/above).")
    definition: str = Field(description="What this test adds back on top of AGI (why its MAGI is its own).")


class MagiLadderResult(BaseModel):
    """Result of :func:`magi_ladder`: every MAGI test the year's packs carry, one table."""

    model_config = ConfigDict(extra="forbid")

    agi: int
    rows: list[MagiLadderRow]
    inputs: dict[str, Any]
    work: str
    citation: Citation


def magi_ladder(
    agi: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2025,
    wages: int | float | Decimal | str = 0,
    foreign_earned_income_exclusion: int | float | Decimal | str = 0,
    excluded_puerto_rico_income: int | float | Decimal | str = 0,
    knowledge_dir: str | Path | None = None,
) -> MagiLadderResult:
    """Every MAGI test the year's packs carry, in ONE table — because "MAGI" is
    not one number.

    The one real planning session fired at least six different MAGI tests with
    six different thresholds, and the user's own question — "why is my MAGI
    under $200,000 when I make $220,000?" — is the UX signal: the answer is a
    LADDER. Gross pay is not box 1 (pre-tax 401(k)/HSA/FSA/commuter come out
    first); box 1 is not AGI (above-the-line adjustments); and AGI is not any
    test's MAGI (each test defines its own add-backs). This op renders the
    per-test half of the ladder from AGI down; the gross-to-box-1 half is
    payroll arithmetic the work explains.

    Rows come from the blocks the year's pack actually ships (NIIT, Additional
    Medicare — a WAGE test, not an AGI test — student-loan interest, the
    Schedule 1-A parts for OBBBA years, Roth IRA and deductible IRA); a block
    the pack lacks is simply not a row, never guessed.
    """
    if filing_status not in FILING_STATUSES and filing_status != _QSS:
        raise ValueError(
            f"unknown filing_status {filing_status!r} — use one of: single, married_filing_jointly, "
            f"married_filing_separately, head_of_household, qualifying_surviving_spouse"
        )
    agi_i = irs_round(_to_decimal(agi, "agi"))
    wages_i = irs_round(_to_decimal(wages, "wages"))
    feie_i = irs_round(_to_decimal(foreign_earned_income_exclusion, "foreign_earned_income_exclusion"))
    pr_i = irs_round(_to_decimal(excluded_puerto_rico_income, "excluded_puerto_rico_income"))
    pack = _load_federal(year, knowledge_dir)
    status_key, _ = _resolve_filing_status(filing_status)
    mfs = filing_status == "married_filing_separately"
    mfj_like = filing_status in ("married_filing_jointly", _QSS)
    rows: list[MagiLadderRow] = []

    def _threshold_row(test, magi_used, threshold_amount, definition):
        position = "above" if magi_used > threshold_amount else "below"
        rows.append(MagiLadderRow(
            test=test, magi_used=magi_used, threshold=f"${threshold_amount:,}",
            position=position, headroom=max(0, threshold_amount - magi_used), definition=definition,
        ))

    def _range_row(test, magi_used, rng: MagiRange, definition):
        if magi_used < rng.start:
            position, headroom = "below", rng.start - magi_used
        elif magi_used >= rng.end:
            position, headroom = "above", 0
        else:
            position, headroom = "within", 0
        rows.append(MagiLadderRow(
            test=test, magi_used=magi_used, threshold=f"${rng.start:,}-${rng.end:,}",
            position=position, headroom=headroom, definition=definition,
        ))

    if pack.tax.niit is not None:
        _threshold_row(
            "Net investment income tax (Form 8960, 3.8%)",
            agi_i + feie_i,
            int(pack.tax.niit.thresholds[status_key]),
            "MAGI = AGI + the foreign earned income exclusion (IRC 1411(d)); investment income above "
            "the threshold pays 3.8%.",
        )
    if pack.tax.additional_medicare_tax is not None:
        _threshold_row(
            "Additional Medicare Tax (Form 8959, 0.9%)",
            wages_i,
            int(pack.tax.additional_medicare_tax.thresholds[status_key]),
            "A WAGE test, not an AGI test: Medicare wages (plus SE income) over the threshold — moving "
            "AGI does not move this one.",
        )
    sli = pack.tax.student_loan_interest
    if sli is not None:
        sli_rng = getattr(sli, "phaseouts", None)
        rng = sli_rng.get(status_key) if isinstance(sli_rng, dict) else None
        if rng is not None:
            _range_row(
                "Student-loan interest deduction (IRC 221)",
                agi_i + feie_i + pr_i,
                MagiRange(start=int(rng.start), end=int(rng.end)),
                "MAGI = AGI without this deduction itself, + foreign/PR exclusions; MFS is not allowed "
                "the deduction at all.",
            )
        elif mfs:
            rows.append(MagiLadderRow(
                test="Student-loan interest deduction (IRC 221)", magi_used=agi_i,
                threshold="not allowed on MFS", position="above", headroom=0,
                definition="IRC 221(e)(2): married filing separately may not take the deduction — no MAGI can fix it.",
            ))
    s1a = pack.tax.obbba_schedule_1a
    if s1a is not None:
        s1a_magi = agi_i + pr_i + feie_i
        for name, part in (
            ("Schedule 1-A tips/overtime", s1a.tips), ("Schedule 1-A car-loan interest", s1a.car_loan_interest),
            ("Schedule 1-A senior deduction", s1a.senior_deduction),
        ):
            _threshold_row(
                f"{name} phase-out start",
                s1a_magi,
                part.phaseout.magi_threshold.for_status(filing_status),
                "MAGI = AGI + excluded Puerto Rico income + Form 2555 amounts (Schedule 1-A Part I) — "
                "one MAGI feeds all four parts.",
            )
    cl = pack.contribution_limits
    if cl is not None:
        roth = cl.ira.roth_magi_phaseout
        rng = (
            roth.married_filing_separately if mfs
            else roth.married_filing_jointly if mfj_like
            else roth.single_hoh
        )
        _range_row(
            "Roth IRA contribution phase-out",
            agi_i + feie_i,
            rng,
            "Pub 590-A MAGI: AGI + foreign exclusions, MINUS Roth conversion income (conversions never "
            "phase you out of contributing).",
        )
        ded = cl.ira.deduction_magi_phaseout_active
        drng = (
            ded.married_filing_separately if mfs
            else ded.married_filing_jointly_covered if mfj_like
            else ded.single_hoh
        )
        _range_row(
            "Traditional-IRA deduction phase-out (active participant)",
            agi_i + feie_i,
            drng,
            "Applies ONLY when covered by an employer plan (the spousal-coverage range is higher; no "
            "coverage anywhere = no phase-out).",
        )

    rows.sort(key=lambda r: (0 if r.position == "within" else 1, r.headroom))
    work_lines = [
        f"MAGI ladder ({year}, {filing_status}), AGI ${agi_i:,}"
        + (f", wages ${wages_i:,}" if wages_i else "") + ":",
        "THE LADDER: gross pay -> W-2 box 1 (pre-tax 401(k)/HSA/FSA/commuter come OUT — a Roth 401(k) "
        "split does NOT reduce box 1) -> AGI (above-the-line adjustments) -> each test's OWN MAGI "
        "(each adds back different items). Every planning lever works by moving a number up or down "
        "this ladder; the rows below show where each test bites.",
        *(f"* {r.test}: MAGI ${r.magi_used:,} vs {r.threshold} -> {r.position.upper()}"
          + (f" (headroom ${r.headroom:,})" if r.position == "below" else "")
          + f" — {r.definition}" for r in rows),
        "Rows come only from blocks this year's pack ships; a missing block is a missing row, never a "
        "guess. Roth-conversion income and rental/passive add-backs are not modeled — supply the "
        "adjusted figures where a test needs them.",
    ]
    return MagiLadderResult(
        agi=agi_i, rows=rows,
        inputs={"agi": agi_i, "filing_status": filing_status, "year": year, "wages": wages_i,
                "foreign_earned_income_exclusion": feie_i, "excluded_puerto_rico_income": pr_i},
        work="\n".join(work_lines),
        citation=(cl.citation if cl is not None else pack.tax.rate_schedules.citation),
    )


# ---------------------------------------------------------------------------
# IRA pro-rata + Roth conversion (Phase I, I1): IRC 408(d)(2) / Form 8606
# Part I, and the two conversion paths that get conflated
# ---------------------------------------------------------------------------

# Both rules below are YEAR-INVARIANT, so — following the P-005/P-006 discipline
# that only FIGURES belong in a year pack — the authorities live here beside the
# ops rather than as a figure-less typed block cloned into eight year files.
#
# The Form 8606 line numbering these ops reproduce was read off EVERY revision
# the repo's shipped years cover (f8606--2019.pdf .. f8606--2025.pdf, all
# fetched): Part I lines 1-14 and Part II lines 16-18 are IDENTICAL in all
# seven. Only the wording moved — the 2025 revision hoisted "'traditional IRA'
# includes traditional SEP IRAs and traditional SIMPLE IRAs" into a Note at the
# top of the form instead of repeating it inside lines 6 and 8. Earlier
# revisions renumber: the instructions' own Total Basis Chart routes a
# pre-2001 Form 8606's basis to LINE 12, a 1989-1992 form's to line 14, 1988's to
# lines 7+16 and 1987's to lines 4+13 — which is why 2019 is the floor these ops
# accept.
_F8606_VERIFIED_REVISIONS: tuple[int, ...] = tuple(range(2019, 2026))
_F8606_NEWEST_VERIFIED = max(_F8606_VERIFIED_REVISIONS)

_IRC_408D2_CITATION = Citation(
    source=(
        "IRC 408(d)(2) (26 U.S.C. 408(d)(2)), 'Special rules for applying section 72': "
        "'(A) all individual retirement plans shall be treated as 1 contract, (B) all "
        "distributions during any taxable year shall be treated as 1 distribution, and "
        "(C) the value of the contract, income on the contract, and investment in the "
        "contract shall be computed as of the close of the calendar year in which the "
        "taxable year begins.' followed by 'For purposes of subparagraph (C), the value of "
        "the contract shall be increased by the amount of any distributions during the "
        "calendar year.' — the one-pool rule (A) AND the statutory basis for Form 8606 "
        "line 9 adding the year's distributions and conversions back to the Dec-31 value"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section408&num=0&edition=prelim",
)

_F8606_INSTRUCTIONS_CITATION = Citation(
    source=(
        "Instructions for Form 8606 (2025), Dec 10 2025 revision: Line 4 ('Although the "
        "contributions to traditional IRAs for 2025 that you made from January 1, 2026, "
        "through April 15, [2026], can be treated as nondeductible, they aren't included in "
        "figuring the nontaxable part of any distributions you received in 2025'), Line 6 "
        "(Dec-31 value plus outstanding rollovers), Line 7 (what is NOT a distribution — "
        "conversions, rollovers, QCDs, recharacterizations), Line 8 (the net amount "
        "converted), Line 14 (line 3 reduced by line 13), and the Total Basis Chart for "
        "line 2. 'Purpose of Form' lists what Form 8606 reports and does NOT list a "
        "rollover from a qualified retirement plan to a Roth IRA; the Part III line 24 "
        "instructions and footnote 3 of the Basis in Roth IRA Conversions chart place those "
        "on Form 1040 line 5a/5b instead"
    ),
    url="https://www.irs.gov/pub/irs-prior/i8606--2025.pdf",
)

_PUB590B_BASIS_CITATION = Citation(
    source=(
        "Publication 590-B (2025), ch. 1, 'Distributions Fully or Partly Taxable': 'If only "
        "deductible contributions were made to your traditional IRA (or IRAs, if you have "
        "more than one), you have no basis in your IRA' ... 'Until all of your basis has "
        "been distributed, each distribution is partly nontaxable and partly taxable.' Same "
        "chapter, 'Withholding': 'Federal income tax is withheld from distributions from "
        "traditional IRAs unless you choose not to have tax withheld' and 'Generally, tax "
        "will be withheld at a 10% rate on nonperiodic payments.'"
    ),
    url="https://www.irs.gov/pub/irs-pdf/p590b.pdf",
)

_NOTICE_2008_30_CITATION = Citation(
    source=(
        "Notice 2008-30 (PPA '06 section 824), Q&A-1 through Q&A-6: A-1 a section 401(a) "
        "plan distribution may go to a Roth IRA 'through a direct rollover from the plan to "
        "the Roth IRA' and 'there is included in gross income any amount that would be "
        "includible if the distribution were not rolled over'; A-2 extends this to 403(a), "
        "403(b) and governmental 457(b) plans; A-3 'the additional tax under section 72(t) "
        "does not apply to rollovers from an eligible retirement plan other than a Roth "
        "IRA' but a taxable amount so rolled in and then distributed within 5 years is "
        "hit by 72(t) 'as if it were includible in gross income' (section 408A(d)(3)(F)); "
        "A-6 a DIRECT rollover to a Roth IRA is not subject to the section 3405(c) 20% "
        "mandatory withholding 'even if the distribution is includible in gross income', "
        "though a voluntary withholding agreement is permitted"
    ),
    url="https://www.irs.gov/pub/irs-drop/n-08-30.pdf",
)

_NOTICE_2014_54_CITATION = Citation(
    source=(
        "Notice 2014-54, sections II-III: under section 72(e)(8) each distribution from a "
        "plan account holding both after-tax and pretax amounts 'will include a pro rata "
        "share of both', while section 402(c)(2) provides 'the amount transferred shall be "
        "treated as consisting first of the portion of such distribution that is includible "
        "in gross income'; section III aggregates simultaneous disbursements into one "
        "distribution and assigns the pretax amount to the direct rollovers first, so a "
        "split rollover's pretax/after-tax allocation is the PLAN's determination (reported "
        "per section IV on Form 1099-R), not the IRA pro-rata ratio"
    ),
    url="https://www.irs.gov/pub/irs-drop/n-14-54.pdf",
)

_PUB590A_CONVERSION_CITATION = Citation(
    source=(
        "Publication 590-A (2025): ch. 1, Table 1-5 'Comparison of Payment to You Versus "
        "Direct Rollover' — payment to you: 'The payer must withhold 20% of the taxable "
        "part' and 'If you are under age 59 1/2, a 10% additional tax may apply to the "
        "taxable part (including an amount equal to the tax withheld) that isn't rolled "
        "over'; direct rollover: 'There is no withholding' and 'There is no 10% additional "
        "tax'. Same chapter: 'The amount withheld is part of the distribution ... you can "
        "make up the amount withheld with funds from other sources.' ch. 2, 'Converting "
        "From Any Traditional IRA Into a Roth IRA' — 'If properly (and timely) rolled over, "
        "the 10% additional tax on early distributions won't apply', 'The amount you keep "
        "will generally be taxable ... and may be subject to the 10% additional tax', "
        "'You can't convert amounts that must be distributed ... under the required "
        "distribution rules', and 'No recharacterizations of conversions made in 2018 or "
        "later'"
    ),
    url="https://www.irs.gov/pub/irs-pdf/p590a.pdf",
)

_IRC_1411_C5_CITATION = Citation(
    source=(
        "IRC 1411(c)(5) (26 U.S.C. 1411(c)(5)), 'Exception for distributions from qualified "
        "plans': 'The term \"net investment income\" shall not include any distribution "
        "from a plan or arrangement described in section 401(a), 403(a), 403(b), 408, 408A, "
        "or 457(b).' IRC 1411(d) defines the threshold's modified adjusted gross income as "
        "AGI increased only by the section 911(a)(1) exclusion — so conversion income is "
        "never itself net investment income, yet it sits in AGI and therefore RAISES the "
        "MAGI the 1411 threshold is measured against"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section1411&num=0&edition=prelim",
)


def _f8606_citation(year: int) -> Citation:
    """Cite the year's own Form 8606 revision; a year whose form has not published
    yet cites the newest revision actually READ and says so in the source text."""
    if year in _F8606_VERIFIED_REVISIONS:
        return Citation(
            source=(
                f"Form 8606 ({year}), Part I lines 1-14 (line 1 this year's nondeductible "
                f"contributions, line 2 prior basis, line 4 the after-year-end slice, line 6 the "
                f"Dec-31 value of all traditional/SEP/SIMPLE IRAs plus outstanding rollovers, line 7 "
                f"other distributions, line 8 the net amount converted, line 9 = 6+7+8, line 10 the "
                f"ratio 'rounded to at least 3 places ... If the result is 1.000 or more, enter "
                f"\"1.000\"', lines 11-13 the nontaxable portions, line 14 the basis carryforward) "
                f"and Part II lines 16-18 (the conversion's taxable amount -> Form 1040 line 4b) — "
                f"line numbering read off this revision's own blank"
            ),
            url=f"https://www.irs.gov/pub/irs-prior/f8606--{year}.pdf",
        )
    return Citation(
        source=(
            f"Form 8606 ({_F8606_NEWEST_VERIFIED}) — quoted for {year} because the {year} revision "
            f"had not published when this op was written. Part I lines 1-14 / Part II lines 16-18 are "
            f"identical on every revision actually read ({_F8606_VERIFIED_REVISIONS[0]}-"
            f"{_F8606_NEWEST_VERIFIED}), but RE-VERIFY the line numbering against the {year} form "
            f"before anything is filed"
        ),
        url=f"https://www.irs.gov/pub/irs-prior/f8606--{_F8606_NEWEST_VERIFIED}.pdf",
    )


class IraProRataResult(BaseModel):
    """Result of :func:`ira_pro_rata`: Form 8606 Part I lines 5-14 plus Part II line 18."""

    model_config = ConfigDict(extra="forbid")

    taxable_conversion: int = Field(
        description="Form 8606 line 18 (line 16 - line 17): the converted amount's TAXABLE part -> Form 1040 line 4b."
    )
    nontaxable_conversion: int = Field(description="Form 8606 line 11 (= line 8 x line 10): basis applied to the conversion.")
    taxable_other_distributions: int = Field(
        description="Form 8606 line 15a/15c (line 7 - line 12): the taxable part of distributions NOT converted."
    )
    nontaxable_other_distributions: int = Field(description="Form 8606 line 12 (= line 7 x line 10).")
    taxable_total: int = Field(description="line 18 + line 15c: everything from this pool that lands on Form 1040 line 4b.")
    basis_applied: int = Field(description="Form 8606 line 13 (= line 11 + line 12): basis consumed this year.")
    basis_carryforward: int = Field(description="Form 8606 line 14 (= line 3 - line 13): next year's line 2.")
    nontaxable_ratio: Decimal = Field(
        description="Form 8606 line 10 computed EXACTLY as line 5 / line 9 (capped at 1), before the form's 3-place rounding."
    )
    ratio_as_filed: Decimal = Field(
        description="line 10 as the form asks it to be entered: rounded to 3 places, 1.000 or more entered as 1.000."
    )
    numerator: int = Field(description="Form 8606 line 5 (= line 3 - line 4): the basis available to this year's ratio.")
    denominator: int = Field(description="Form 8606 line 9 (= line 6 + line 7 + line 8) — it INCLUDES the amount converted.")
    form_8606_lines: dict[str, str] = Field(
        description="Every Part I / Part II line this op computes, keyed by the form's printed line label."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation
    citations: list[Citation] = Field(description="Every authority behind the number, primary first.")


def ira_pro_rata(
    dec31_total_value: int | float | Decimal | str,
    amount_converted: int | float | Decimal | str = 0,
    other_distributions: int | float | Decimal | str = 0,
    nondeductible_basis_carryforward: int | float | Decimal | str = 0,
    nondeductible_contributions_this_year: int | float | Decimal | str = 0,
    contributions_made_after_year_end: int | float | Decimal | str = 0,
    year: int = 2026,
    knowledge_dir: str | Path | None = None,
) -> IraProRataResult:
    """The IRC 408(d)(2) pro-rata rule as Form 8606 Part I computes it: how much of a
    conversion (or any traditional-IRA distribution) is taxable when the pool holds
    both pretax money and nondeductible basis.

    This op exists because nothing in the engine modeled 408(d)(2), so the one
    question a backdoor-Roth filer actually has — "where can I put my old
    401(k)?" — had no deterministic answer. The statute is the whole answer:
    ALL individual retirement plans are treated as 1 CONTRACT and all of a
    year's distributions as 1 DISTRIBUTION, so which dollars physically moved is
    irrelevant. Rolling an old 401(k) into a TRADITIONAL IRA lands it on line 6
    and makes every future backdoor conversion mostly taxable; rolling it
    straight to a Roth IRA (calc op ``roth_conversion`` with
    ``source='plan_to_roth_ira'``) or into a new employer's 401(k) keeps the pool
    clean, because neither ever enters line 6.

    Inputs map one-to-one onto the printed lines:

    * ``dec31_total_value`` = line 6, the value of ALL your traditional, SEP and
      SIMPLE IRAs on December 31 plus any outstanding rollovers. It is measured
      AFTER the conversion left the account, and the timing is the trap: an
      amount rolled INTO a traditional IRA in December still sits in line 6 for a
      conversion done the previous January.
    * ``amount_converted`` = line 8 (also line 16), the net amount converted to
      Roth IRAs during the year.
    * ``other_distributions`` = line 7, distributions you did NOT convert.
      Rollovers, QCDs, recharacterizations and returned contributions are
      excluded by the instructions — do not pass them.
    * ``nondeductible_basis_carryforward`` = line 2, from the last Form 8606's
      line 14.
    * ``nondeductible_contributions_this_year`` = line 1.
    * ``contributions_made_after_year_end`` = line 4, the part of line 1 made
      between January 1 and April 15 of the FOLLOWING year. The instructions keep
      it out of the ratio's numerator while line 14 still carries it forward, so a
      January-for-last-year contribution is basis you cannot use yet.

    THE DENOMINATOR INCLUDES THE CONVERSION. Line 9 = line 6 + line 7 + line 8,
    which is 408(d)(2)(C)'s "the value of the contract shall be increased by the
    amount of any distributions during the calendar year" — converting a bigger
    slice does not shrink the denominator, it only moves dollars from line 6 to
    line 8. Basis is per PERSON, never per couple: the form is filed separately
    for each spouse, so a spouse's traditional IRA never enters your ratio.

    ``year`` selects which Form 8606 revision the work string and citation quote.
    Revisions 2019-2025 were read directly; the numbering is identical in all of
    them, and pre-2019 revisions renumber (the instructions' Total Basis Chart
    routes a pre-2001 form's basis to line 12), so earlier years are refused. A
    year whose form has not published yet quotes the newest revision read and
    says so in both the work and the citation.

    ``knowledge_dir`` is accepted for signature parity with its neighbours (and
    so :func:`roth_conversion` can forward it) but is deliberately unused: the
    pro-rata rule carries NO per-year figures, so this op reads no knowledge
    pack and its authorities are module constants, per the P-005/P-006
    discipline that only figures belong in a year pack.
    """
    del knowledge_dir  # see the docstring: no per-year figures, so no pack read
    if year < _F8606_VERIFIED_REVISIONS[0]:
        raise ValueError(
            f"ira_pro_rata does not support {year}: Form 8606 revisions before "
            f"{_F8606_VERIFIED_REVISIONS[0]} renumber the lines this op reproduces (the Form 8606 "
            f"instructions' Total Basis Chart takes basis from line 12 of a pre-2001 form, line 14 "
            f"of a 1989-1992 form, lines 7+16 of the 1988 form and lines 4+13 of the 1987 form). Read that year's own blank and "
            f"compute it by hand, or pass a year from {_F8606_VERIFIED_REVISIONS[0]} onward"
        )
    line6 = irs_round(_to_decimal(dec31_total_value, "dec31_total_value"))
    line8 = irs_round(_to_decimal(amount_converted, "amount_converted"))
    line7 = irs_round(_to_decimal(other_distributions, "other_distributions"))
    line2 = irs_round(_to_decimal(nondeductible_basis_carryforward, "nondeductible_basis_carryforward"))
    line1 = irs_round(_to_decimal(nondeductible_contributions_this_year, "nondeductible_contributions_this_year"))
    line4 = irs_round(_to_decimal(contributions_made_after_year_end, "contributions_made_after_year_end"))
    for name, value in (
        ("dec31_total_value", line6), ("amount_converted", line8), ("other_distributions", line7),
        ("nondeductible_basis_carryforward", line2),
        ("nondeductible_contributions_this_year", line1), ("contributions_made_after_year_end", line4),
    ):
        if value < 0:
            raise ValueError(
                f"{name} must be >= 0, got {value} — Form 8606 takes no negative entries; a basis "
                f"adjustment (divorce transfer, returned excess contribution) is folded into line 2 "
                f"per the instructions' Line 2 bullets, not passed as a negative"
            )
    if line4 > line1:
        raise ValueError(
            f"contributions_made_after_year_end ({line4}) cannot exceed "
            f"nondeductible_contributions_this_year ({line1}) — Form 8606 line 4 is 'those "
            f"contributions INCLUDED ON LINE 1 that were made from January 1 through April 15' of the "
            f"following year, a subset of line 1"
        )
    if line8 == 0 and line7 == 0:
        raise ValueError(
            f"nothing left the pool: with amount_converted and other_distributions both 0 there is no "
            f"pro-rata computation to do. Form 8606 answers 'In {year}, did you take a distribution "
            f"from a traditional IRA, or make a Roth IRA conversion?' with 'No -> Enter the amount "
            f"from line 3 on line 14. Do not complete the rest of Part I', so the whole "
            f"${line1 + line2:,} of basis simply carries forward. Pass amount_converted (line 8) "
            f"and/or other_distributions (line 7)"
        )

    line3 = line1 + line2
    line5 = line3 - line4
    line9 = line6 + line7 + line8
    # line9 >= line8 + line7 > 0 is guaranteed by the guard above.
    exact = Decimal(line5) / Decimal(line9)
    capped = min(exact, _ONE)  # the form: "If the result is 1.000 or more, enter '1.000'"
    as_filed = min(exact.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), _ONE)
    line11 = irs_round(Decimal(line8) * capped)
    line12 = irs_round(Decimal(line7) * capped)
    line13 = line11 + line12
    line14 = line3 - line13
    line18 = line8 - line11
    line15 = line7 - line12
    # Belt and braces: the form can never make a distribution more than fully
    # nontaxable, and the ratio cap is what guarantees it.
    line18, line15 = max(0, line18), max(0, line15)

    lines = {
        "1": _dollars(line1), "2": _dollars(line2), "3": _dollars(line3), "4": _dollars(line4),
        "5": _dollars(line5), "6": _dollars(line6), "7": _dollars(line7), "8": _dollars(line8),
        "9": _dollars(line9), "10": f"{as_filed:.3f}", "11": _dollars(line11), "12": _dollars(line12),
        "13": _dollars(line13), "14": _dollars(line14), "15a": _dollars(line15),
        # 15c == 15a ONLY because this op models neither line 15b nor the Line 15c
        # Worksheet — see the LINE 15b / 15c SCOPE note in the work string below.
        "15c": _dollars(line15), "16": _dollars(line8), "17": _dollars(line11), "18": _dollars(line18),
    }
    scope_15 = (
        "LINE 15b / 15c SCOPE, disclosed because this op reports 15a and 15c as the SAME number: "
        "line 15c's printed row is 'Subtract line 15b from line 15a' and, on the 2024 and later "
        "revisions, 'Reduce that amount by certain <year> retirement plan distribution repayments "
        "... treated as rollovers'. This op models NEITHER term — it assumes line 15b (Form 8915-F "
        "qualified disaster distributions) is zero and that there are no repayments treated as "
        "rollovers, so 15a == 15c and NO Line 15c Worksheet basis adjustment is carried into the "
        "next year's line 14 / line 2. A filer with Form 8915-F amounts, or with a repaid qualified "
        "birth-or-adoption / emergency-personal-expense / domestic-abuse / terminal-illness "
        "distribution, must compute 15b and the worksheet by hand off the year's own instructions "
        "and treat this op's 15c as line 15a only."
    )
    ratio_note = (
        f"line 10 = line 5 / line 9 = {_dollars(line5)} / {_dollars(line9)} = {capped:.6f}"
        + ("..." if capped != capped.quantize(Decimal('0.000001')) else "")
        + f" (the form asks for 'a decimal rounded to at least 3 places' and caps it: 'If the result is "
        f"1.000 or more, enter \"1.000\"' — as filed {as_filed:.3f}; this op divides EXACTLY, which "
        f"'at least 3 places' permits)"
    )
    three_place_11 = irs_round(Decimal(line8) * as_filed)
    if line8 and abs(three_place_11 - line11) >= 1:
        ratio_note += (
            f". Entering exactly 3 places instead would make line 11 {_dollars(three_place_11)} and "
            f"line 18 {_dollars(line8 - three_place_11)} — a ${abs(three_place_11 - line11):,} "
            f"difference; carry more places on the filed form to match this result"
        )
    work_lines = [
        f"Form 8606 ({year}) Part I, IRC 408(d)(2) pro-rata:",
        f"line 1 nondeductible contributions for {year} {_dollars(line1)} + line 2 prior-year basis "
        f"{_dollars(line2)} = line 3 {_dollars(line3)}; line 4 (the part of line 1 made Jan 1-Apr 15 "
        f"{year + 1}) {_dollars(line4)}; line 5 = 3 - 4 = {_dollars(line5)} = the NUMERATOR. The "
        f"instructions keep line 4 out of the ratio — those contributions 'aren't included in "
        f"figuring the nontaxable part of any distributions you received in {year}' — while line 14 "
        f"still carries them forward.",
        f"line 6 Dec 31 {year} value of ALL traditional/SEP/SIMPLE IRAs + outstanding rollovers "
        f"{_dollars(line6)} + line 7 distributions not converted {_dollars(line7)} + line 8 net "
        f"amount converted {_dollars(line8)} = line 9 {_dollars(line9)} = the DENOMINATOR. Line 9 "
        f"ADDS THE CONVERSION BACK, which is 408(d)(2)(C)'s 'the value of the contract shall be "
        f"increased by the amount of any distributions during the calendar year' — converting a "
        f"bigger slice moves dollars from line 6 to line 8 and leaves line 9 unchanged.",
        ratio_note + ".",
        f"line 11 = line 8 x line 10 = {_dollars(line11)} nontaxable share of the conversion; "
        f"line 12 = line 7 x line 10 = {_dollars(line12)} nontaxable share of the other "
        f"distributions; line 13 = 11 + 12 = {_dollars(line13)} of basis applied; line 14 = line 3 - "
        f"line 13 = {_dollars(line14)} carries to next year's line 2.",
        f"Part II: line 16 = line 8 = {_dollars(line8)}; line 17 = line 11 = {_dollars(line11)}; "
        f"line 18 = 16 - 17 = {_dollars(line18)} TAXABLE on Form 1040 line 4b."
        + (
            f" Lines 15a/15c: {_dollars(line7)} - {_dollars(line12)} = {_dollars(line15)} of the "
            f"unconverted distribution is taxable too, and the form's own Note warns 'You may be "
            f"subject to an additional 10% tax on the amount on line 15c if you were under age "
            f"59 1/2 at the time of the distribution.'" if line7 else ""
        ),
        "WHY THE POOL AND NOT THE DOLLARS YOU MOVED: IRC 408(d)(2) treats ALL individual retirement "
        "plans as 1 contract and all of a year's distributions as 1 distribution, so earmarking the "
        "nondeductible dollars for the conversion is impossible — Pub 590-B: 'Until all of your basis "
        "has been distributed, each distribution is partly nontaxable and partly taxable.'",
        "ONE POOL, ONE PERSON: the pool is traditional + SEP + SIMPLE IRAs, and it is PER FILER — "
        "Form 8606's own header is 'If married, file a separate form for each spouse required to "
        "file', so a spouse's traditional IRA never enters your ratio. A Roth IRA, a 401(k)/403(b), "
        "and an inherited IRA are all OUTSIDE the pool.",
        "WHERE AN OLD 401(k) MAY GO: not into a traditional IRA in any year you intend a backdoor "
        "Roth — it lands on line 6 whenever in the year it arrives and poisons the ratio. A DIRECT "
        "rollover to a Roth IRA (calc op roth_conversion, source='plan_to_roth_ira') is fully taxable "
        "now but never touches line 6; a rollover into a new employer's 401(k) is not taxable and "
        "never touches line 6 either.",
        scope_15,
    ]
    inputs: dict[str, Any] = {
        "dec31_total_value": line6, "amount_converted": line8, "other_distributions": line7,
        "nondeductible_basis_carryforward": line2, "nondeductible_contributions_this_year": line1,
        "contributions_made_after_year_end": line4, "year": year,
    }
    if year not in _F8606_VERIFIED_REVISIONS:
        work_lines.append(
            f"YEAR NOTE: the {year} Form 8606 had not published when this op was written, so the line "
            f"numbering above is the {_F8606_NEWEST_VERIFIED} revision's (identical on every revision "
            f"read, {_F8606_VERIFIED_REVISIONS[0]}-{_F8606_NEWEST_VERIFIED}). Re-verify against the "
            f"{year} form before anything is filed."
        )
    form_citation = _f8606_citation(year)
    return IraProRataResult(
        taxable_conversion=line18,
        nontaxable_conversion=line11,
        taxable_other_distributions=line15,
        nontaxable_other_distributions=line12,
        taxable_total=line18 + line15,
        basis_applied=line13,
        basis_carryforward=line14,
        nontaxable_ratio=capped,
        ratio_as_filed=as_filed,
        numerator=line5,
        denominator=line9,
        form_8606_lines=lines,
        inputs=inputs,
        work="\n".join(w for w in work_lines if w),
        citation=_IRC_408D2_CITATION,
        citations=[_IRC_408D2_CITATION, form_citation, _F8606_INSTRUCTIONS_CITATION, _PUB590B_BASIS_CITATION],
    )


_ROTH_CONVERSION_SOURCES = ("plan_to_roth_ira", "traditional_ira_to_roth")


class BracketSlice(BaseModel):
    """One rate bracket's share of the conversion's taxable income."""

    model_config = ConfigDict(extra="forbid")

    rate: Decimal = Field(description="The bracket's marginal rate.")
    amount: int = Field(description="Dollars of the taxable conversion that land in this bracket.")
    tax: Decimal = Field(description="rate x amount, in cents.")


class RothConversionResult(BaseModel):
    """Result of :func:`roth_conversion`: the taxable amount plus the three things a
    filer cannot compute by hand — bracket headroom, the NIIT crossing, and the
    withholding trap (in the work)."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["plan_to_roth_ira", "traditional_ira_to_roth"] = Field(
        description="Which path the money took — the two are taxed differently and the caller must choose."
    )
    amount_converted: int = Field(description="The gross amount converted or rolled over to the Roth IRA.")
    taxable_amount: int = Field(description="The conversion income: Form 1040 line 5b (plan path) or line 4b (IRA path).")
    nontaxable_amount: int = Field(description="The basis-recovery part: plan after-tax basis, or Form 8606 line 11.")
    pro_rata: IraProRataResult | None = Field(
        description="The delegated Form 8606 Part I computation — None on the plan path, where pro-rata never applies."
    )
    marginal_rate_before: Decimal = Field(description="The bracket rate the pre-conversion taxable income sits in.")
    marginal_rate_after: Decimal = Field(description="The bracket rate the post-conversion taxable income sits in.")
    bracket_top_before: int | None = Field(description="Top of the bracket the filer starts in (None in the top bracket).")
    headroom_before: int | None = Field(description="Dollars of room below that top before the conversion (None if top).")
    headroom_after: int | None = Field(description="Room left below the post-conversion bracket's top (None if top).")
    spill_into_higher_brackets: int = Field(description="Taxable conversion dollars taxed above marginal_rate_before.")
    bracket_slices: list[BracketSlice] = Field(description="The taxable conversion split bracket by bracket, lowest first.")
    incremental_income_tax: int = Field(description="Rate-schedule tax on the conversion (tax after - tax before).")
    magi_before: int = Field(description="Pre-conversion MAGI for IRC 1411 (AGI + the section 911 exclusion).")
    magi_after: int = Field(description="magi_before + taxable_amount — only the TAXABLE part enters AGI.")
    niit_threshold: int = Field(description="The filing-status IRC 1411 MAGI threshold (statutory, not indexed).")
    niit_before: int = Field(description="Form 8960 line 17 at magi_before.")
    niit_after: int = Field(description="Form 8960 line 17 at magi_after.")
    niit_from_conversion: int = Field(description="niit_after - niit_before: the 3.8% the conversion itself causes.")
    crosses_niit_threshold: bool = Field(description="True when the conversion carries MAGI from at-or-below to above.")
    total_incremental_tax: int = Field(description="incremental_income_tax + niit_from_conversion (federal only).")
    inputs: dict[str, Any]
    work: str
    citation: Citation
    citations: list[Citation] = Field(description="Every authority behind the number, primary first.")


def roth_conversion(
    source: str,
    amount: int | float | Decimal | str,
    taxable_income_before: int | float | Decimal | str,
    magi_before: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2026,
    net_investment_income: int | float | Decimal | str = 0,
    plan_after_tax_basis: int | float | Decimal | str = 0,
    dec31_total_value: int | float | Decimal | str | None = None,
    nondeductible_basis_carryforward: int | float | Decimal | str = 0,
    nondeductible_contributions_this_year: int | float | Decimal | str = 0,
    other_distributions: int | float | Decimal | str = 0,
    contributions_made_after_year_end: int | float | Decimal | str = 0,
    knowledge_dir: str | Path | None = None,
) -> RothConversionResult:
    """Price a Roth conversion on the ONE path the money actually takes — the two
    paths behave differently and are routinely conflated.

    ``source='plan_to_roth_ira'`` — a DIRECT rollover from a 401(k)/403(b)/
    governmental 457(b) to a Roth IRA (Notice 2008-30 A-1/A-2). Taxable is the
    pretax portion of the distribution: "there is included in gross income any
    amount that would be includible if the distribution were not rolled over".
    IRC 408(d)(2) PRO-RATA DOES NOT APPLY — no individual retirement plan is
    involved, the Form 8606 pool is untouched, and the rollover is reported on
    Form 1040 line 5a/5b, not on Form 8606 (its 'Purpose of Form' does not list
    it; the Part III line 24 instructions point at line 5a). This is the path
    that empties an old plan WITHOUT poisoning future backdoor Roths. Pass
    ``plan_after_tax_basis`` = the 1099-R box 5 after-tax amount allocated to
    this rollover; how a plan splits after-tax dollars across destinations is the
    PLAN's determination under section 72(e)(8), 402(c)(2) and Notice 2014-54,
    never this op's guess.

    ``source='traditional_ira_to_roth'`` — pro-rata applies, and the computation
    is delegated whole to :func:`ira_pro_rata`, which needs
    ``dec31_total_value`` (Form 8606 line 6) at minimum.

    Beyond the taxable amount the op surfaces three things a filer cannot do by
    hand:

    * BRACKET HEADROOM — the room left below the top of the current bracket, and
      exactly how many conversion dollars spill into higher rates (from the
      year's own ``rate_schedules``, bracket by bracket).
    * THE NIIT CROSSING — IRC 1411(c)(5) says a distribution from a 401(a),
      403(a), 403(b), 408, 408A or 457(b) plan is NEVER net investment income,
      so the conversion pays no 3.8% itself; but 1411(d)'s MAGI is AGI (plus the
      section 911 exclusion), so the conversion RAISES MAGI and can drag OTHER
      investment income over the threshold. Both halves are computed by reusing
      the ``niit`` op and its pack block.
    * THE WITHHOLDING TRAP, in the work: tax withheld from the conversion is not
      converted. It is lost Roth space, and Pub 590-A's Table 1-5 says the 10%
      additional tax applies to the taxable part "including an amount equal to
      the tax withheld" that isn't rolled over. Pay the tax from OUTSIDE funds.

    Federal only, and the incremental tax is computed on the RATE SCHEDULE:
    below $100,000 of taxable income the filed Form 1040 line 16 comes from the
    published Tax Table instead, and preferential-rate income needs
    :func:`tax_with_preferential_rates` — both disclosed in the work.
    """
    if source not in _ROTH_CONVERSION_SOURCES:
        raise ValueError(
            f"unknown source {source!r} — use 'plan_to_roth_ira' for a DIRECT rollover from a "
            f"401(k)/403(b)/governmental 457(b) to a Roth IRA (Notice 2008-30; IRC 408(d)(2) pro-rata "
            f"does NOT apply, so it never touches the traditional-IRA pool) or "
            f"'traditional_ira_to_roth' for a conversion out of a traditional/SEP/SIMPLE IRA "
            f"(pro-rata DOES apply, via Form 8606 Part I). The two are taxed differently and the "
            f"choice is the whole point of this op"
        )
    if filing_status not in FILING_STATUSES and filing_status != _QSS:
        raise ValueError(
            f"unknown filing_status {filing_status!r} — use one of: single, married_filing_jointly, "
            f"married_filing_separately, head_of_household, qualifying_surviving_spouse"
        )
    gross = irs_round(_to_decimal(amount, "amount"))
    if gross <= 0:
        raise ValueError(f"amount must be > 0, got {gross} — pass the gross amount converted or rolled over")
    taxable_before_d = _to_decimal(taxable_income_before, "taxable_income_before")
    magi_before_i = irs_round(_to_decimal(magi_before, "magi_before"))
    nii_i = irs_round(_to_decimal(net_investment_income, "net_investment_income"))
    if taxable_before_d < 0 or magi_before_i < 0:
        raise ValueError("taxable_income_before and magi_before must be >= 0 (pre-conversion figures)")
    taxable_before_i = irs_round(taxable_before_d)

    pack = _load_federal(year, knowledge_dir)
    ira_args = {
        "dec31_total_value": dec31_total_value,
        "nondeductible_basis_carryforward": nondeductible_basis_carryforward,
        "nondeductible_contributions_this_year": nondeductible_contributions_this_year,
        "other_distributions": other_distributions,
        "contributions_made_after_year_end": contributions_made_after_year_end,
    }
    pro_rata: IraProRataResult | None = None
    if source == "plan_to_roth_ira":
        supplied = sorted(
            name for name, value in ira_args.items()
            if value is not None and irs_round(_to_decimal(value, name)) != 0
        )
        if supplied:
            raise ValueError(
                f"plan_to_roth_ira was given traditional-IRA arguments {supplied}, and that is the "
                f"exact conflation this op exists to prevent: a DIRECT rollover from a plan to a Roth "
                f"IRA is not a Form 8606 Part I conversion — no individual retirement plan is "
                f"involved, so IRC 408(d)(2) pro-rata never applies and the traditional-IRA pool is "
                f"irrelevant to it (Notice 2008-30 A-1). Drop those arguments, or use "
                f"source='traditional_ira_to_roth' if the money really is leaving a traditional IRA"
            )
        basis = irs_round(_to_decimal(plan_after_tax_basis, "plan_after_tax_basis"))
        if basis < 0:
            raise ValueError("plan_after_tax_basis must be >= 0 (Form 1099-R box 5)")
        if basis > gross:
            raise ValueError(
                f"plan_after_tax_basis ({basis}) exceeds the amount rolled over ({gross}) — box 5 of "
                f"the Form 1099-R for THIS rollover is the after-tax slice allocated to it under "
                f"Notice 2014-54 section III, so it can never be larger than box 1"
            )
        taxable_i, nontaxable_i = gross - basis, basis
    else:
        if dec31_total_value is None:
            raise ValueError(
                "traditional_ira_to_roth needs dec31_total_value — Form 8606 line 6, the value of ALL "
                "your traditional, SEP and SIMPLE IRAs on December 31 (measured AFTER the conversion "
                "left them) plus any outstanding rollovers. Pass 0 only if every traditional IRA was "
                "emptied, and note that 0 is what makes a backdoor Roth non-taxable. For a DIRECT "
                "rollover out of a 401(k)/403(b) use source='plan_to_roth_ira' instead: no "
                "traditional IRA is involved there and pro-rata never applies"
            )
        if irs_round(_to_decimal(plan_after_tax_basis, "plan_after_tax_basis")) != 0:
            raise ValueError(
                "plan_after_tax_basis applies only to source='plan_to_roth_ira' — a traditional-IRA "
                "conversion recovers basis through Form 8606 lines 2 and 1 "
                "(nondeductible_basis_carryforward / nondeductible_contributions_this_year), never "
                "through a 1099-R box 5 plan figure"
            )
        if irs_round(_to_decimal(other_distributions, "other_distributions")) != 0:
            # Found 2026-08-26 by the Phase-I1 adversarial review: this op accepted
            # line 7 into the pro-rata denominator and then dropped the resulting
            # taxable line-15a income from taxable_amount, magi_after,
            # incremental_income_tax and the NIIT crossing — silently, in the
            # direction that UNDERSTATES both the bracket and the threshold test.
            # Refusing is the honest fix: the ratio needs line 7, but this op's
            # outputs are all named for the CONVERSION, and the two amounts are not
            # even taxed alike.
            raise ValueError(
                "other_distributions (Form 8606 line 7 — money that LEFT the pool without being "
                "converted) belongs to ira_pro_rata, not here: it correctly enters the pro-rata "
                "DENOMINATOR (line 9 = 6 + 7 + 8) but it also carries its own taxable line-15a "
                "income, which every headline number of this op is named for the conversion and "
                "does NOT price — so taxable_amount, magi_after, incremental_income_tax and the "
                "NIIT crossing would all silently omit it. The two amounts are not taxed alike "
                "either: a non-converted distribution can draw the section 72(t) 10% additional "
                "tax, which a conversion to a Roth IRA does not. Call ira_pro_rata directly for "
                "the full-year Form 8606 picture — it returns taxable_conversion and "
                "taxable_other_distributions SEPARATELY — then price the bracket and NIIT effect "
                "on their sum"
            )
        pro_rata = ira_pro_rata(
            dec31_total_value=dec31_total_value,
            amount_converted=gross,
            other_distributions=other_distributions,
            nondeductible_basis_carryforward=nondeductible_basis_carryforward,
            nondeductible_contributions_this_year=nondeductible_contributions_this_year,
            contributions_made_after_year_end=contributions_made_after_year_end,
            year=year,
            knowledge_dir=knowledge_dir,
        )
        taxable_i, nontaxable_i = pro_rata.taxable_conversion, pro_rata.nontaxable_conversion

    # ── Bracket headroom, from the year's own rate schedule ────────────────────
    status_key, alias_note = _resolve_filing_status(filing_status)
    schedule = pack.tax.rate_schedules.schedules[status_key]
    taxable_after_i = taxable_before_i + taxable_i

    def _bracket_for(amount_i: int) -> RateBracket:
        for bracket in schedule:
            if bracket.but_not_over is None or amount_i <= bracket.but_not_over:
                return bracket
        raise AssertionError("rate schedule has no top bracket — knowledge validation should have rejected this pack")

    b_before, b_after = _bracket_for(taxable_before_i), _bracket_for(taxable_after_i)
    top_before = b_before.but_not_over
    headroom_before = None if top_before is None else max(0, top_before - taxable_before_i)
    headroom_after = None if b_after.but_not_over is None else max(0, b_after.but_not_over - taxable_after_i)
    spill = 0 if top_before is None else max(0, taxable_after_i - top_before)

    slices: list[BracketSlice] = []
    for bracket in schedule:
        lo = max(taxable_before_i, bracket.over)
        hi = taxable_after_i if bracket.but_not_over is None else min(taxable_after_i, bracket.but_not_over)
        if hi > lo:
            slices.append(BracketSlice(rate=bracket.rate, amount=hi - lo, tax=_cents(bracket.rate * (hi - lo))))
    tax_before, _, _ = _schedule_tax(Decimal(taxable_before_i), schedule)
    tax_after, _, _ = _schedule_tax(Decimal(taxable_after_i), schedule)
    incremental = irs_round(tax_after - tax_before)

    # ── The NIIT crossing: reuse the niit op and its pack block, never re-derive ─
    magi_after_i = magi_before_i + taxable_i
    niit_before_r = niit(nii_i, magi_before_i, filing_status, year, knowledge_dir=knowledge_dir)
    niit_after_r = niit(nii_i, magi_after_i, filing_status, year, knowledge_dir=knowledge_dir)
    threshold = niit_after_r.threshold
    crosses = magi_before_i <= threshold < magi_after_i

    path_line = (
        f"PATH: a DIRECT rollover from a 401(k)/403(b)/governmental 457(b) to a Roth IRA. Notice "
        f"2008-30 A-1: 'there is included in gross income any amount that would be includible if the "
        f"distribution were not rolled over' -> taxable {_dollars(taxable_i)} of the "
        f"{_dollars(gross)} rolled over, with {_dollars(nontaxable_i)} of after-tax basis (1099-R box "
        f"5) recovered tax-free. IRC 408(d)(2) PRO-RATA DOES NOT APPLY: no individual retirement plan "
        f"is involved, so the traditional-IRA pool is irrelevant and Form 8606 Part I is not filed — "
        f"the rollover is reported on Form 1040 line 5a/5b. That is what makes this the path that "
        f"clears an old plan WITHOUT poisoning future backdoor Roth conversions. How a plan splits "
        f"after-tax dollars across destinations is the plan's call under section 72(e)(8), 402(c)(2) "
        f"and Notice 2014-54 section III (pretax assigned to the direct rollovers first) — take box 5 "
        f"from the 1099-R, never estimate it."
        if source == "plan_to_roth_ira" else
        f"PATH: a conversion out of a traditional/SEP/SIMPLE IRA, so IRC 408(d)(2) pro-rata applies "
        f"and Form 8606 Part I decides the split: {_dollars(taxable_i)} of the {_dollars(gross)} "
        f"converted is taxable (line 18) and {_dollars(nontaxable_i)} is basis (line 11). The full "
        f"line-by-line derivation is in this result's pro_rata.work."
    )
    bracket_line = (
        f"BRACKET HEADROOM ({year}, {filing_status}): taxable income {_dollars(taxable_before_i)} sits "
        f"in the {b_before.rate:.0%} bracket"
        + (
            f", whose top is {_dollars(top_before)} -> {_dollars(headroom_before)} of headroom before "
            f"the conversion" if top_before is not None else " (the TOP bracket — no headroom to run out of)"
        )
        + f". Adding {_dollars(taxable_i)} of conversion income takes taxable income to "
        f"{_dollars(taxable_after_i)}, in the {b_after.rate:.0%} bracket"
        + (f" with {_dollars(headroom_after)} of headroom left" if headroom_after is not None else "")
        + (
            f"; {_dollars(spill)} SPILLS above {_dollars(top_before)} into the higher rate(s)"
            if spill else "; nothing spills into a higher bracket"
        )
        + "."
    )
    if slices:
        slice_line = (
            "The conversion's taxable income bracket by bracket: "
            + "; ".join(f"{s.rate:.0%} x {_dollars(s.amount)} = {_money(s.tax)}" for s in slices)
            + f" -> {_dollars(incremental)} of federal income tax on the conversion."
        )
    else:
        slice_line = "No taxable conversion income, so no incremental federal income tax."
    niit_line = (
        f"NIIT (Form 8960, {filing_status} threshold {_dollars(threshold)}): MAGI "
        f"{_dollars(magi_before_i)} -> {_dollars(magi_after_i)} (only the TAXABLE part of the "
        f"conversion enters AGI). "
        + (
            f"THIS CONVERSION CROSSES THE 1411 THRESHOLD: NIIT goes {_dollars(niit_before_r.niit)} -> "
            f"{_dollars(niit_after_r.niit)}, i.e. {_dollars(niit_after_r.niit - niit_before_r.niit)} "
            f"caused by the conversion. " if crosses else
            f"NIIT {_dollars(niit_before_r.niit)} -> {_dollars(niit_after_r.niit)} "
            f"({_dollars(niit_after_r.niit - niit_before_r.niit)} from the conversion). "
        )
        + "THE TRAP: IRC 1411(c)(5) excludes any distribution from a 401(a), 403(a), 403(b), 408, "
        "408A or 457(b) plan from net investment income, so the conversion NEVER pays 3.8% itself — "
        "but 1411(d)'s MAGI is AGI (plus the section 911 exclusion), so the conversion raises MAGI "
        f"and drags the OTHER {_dollars(nii_i)} of net investment income over the line. The 3.8% is "
        "charged on the LESSER of net investment income and the MAGI excess."
    )
    withholding_line = (
        "WITHHOLDING — PAY FROM OUTSIDE FUNDS. Tax withheld from the conversion is NOT converted: it "
        "is Roth space you never get back (this year's conversion cannot be redone, and no "
        "contribution limit lets you replace it), and Pub 590-A's Table 1-5 says the 10% additional "
        "tax applies to the taxable part 'including an amount equal to the tax withheld' that isn't "
        "rolled over, for a filer under 59 1/2. "
        + (
            "On this path the good news is structural: Notice 2008-30 A-6 exempts a DIRECT rollover to "
            "a Roth IRA from the section 3405(c) 20% mandatory withholding 'even if the distribution "
            "is includible in gross income' — so decline the voluntary withholding agreement A-6 "
            "permits, and never take the money as a 60-day (indirect) rollover, where the 20% IS "
            "mandatory and only outside funds can make it whole within 60 days."
            if source == "plan_to_roth_ira" else
            "On this path an IRA distribution defaults to 10% federal withholding unless you elect out "
            "(Pub 590-B, 'Withholding': 'Generally, tax will be withheld at a 10% rate on nonperiodic "
            "payments'), and any withheld dollars land on Form 8606 LINE 7 (a distribution you did not "
            "convert), not line 8 — so they are taxed pro-rata AND exposed to the line 15c Note's 10% "
            "additional tax under 59 1/2. Elect 0% withholding and pay with estimated tax instead."
        )
        + " Cover the liability with an estimated payment or extra wage withholding — calc op "
        "estimated_tax_safe_harbor sizes it (IRC 6654(d))."
    )
    judgment_line = (
        "IRREVERSIBLE AND NOT MODELED HERE. Pub 590-A: 'No recharacterizations of conversions made in "
        "2018 or later' — a conversion of a traditional IRA to a Roth IRA AND a rollover from any "
        "other eligible retirement plan to a Roth IRA can no longer be undone, so the bracket call has "
        "to be right the first time. Also from Pub 590-A ch. 2: an amount that must be distributed "
        "under the required-distribution rules cannot be converted. Notice 2008-30 A-3: section 72(t) "
        "does not apply to the rollover itself, but a taxable amount rolled into a Roth IRA and then "
        "distributed within 5 years is hit by 72(t) 'as if it were includible in gross income' "
        "(section 408A(d)(3)(F)) — each conversion starts its own 5-year clock. One thing the "
        "conversion does NOT do: it cannot phase you out of CONTRIBUTING to a Roth IRA, because the "
        "Form 8606 instructions' 'Modified AGI for Roth IRA purposes' SUBTRACTS Roth conversions "
        "(1040 line 4b) and plan-to-Roth-IRA rollovers (1040 line 5b) back out."
    )
    disclosure_line = (
        f"SCOPE: federal only, {_dollars(incremental)} income tax + {_dollars(niit_after_r.niit - niit_before_r.niit)} "
        f"NIIT = {_dollars(incremental + niit_after_r.niit - niit_before_r.niit)} of incremental "
        f"federal tax. Computed on the {year} RATE SCHEDULE: below $100,000 of taxable income the "
        f"filed Form 1040 line 16 comes from the published Tax Table and can differ by a few dollars "
        f"within a $50 band, and a return with qualified dividends or capital gains computes line 16 "
        f"from the Qualified Dividends and Capital Gain Tax Worksheet — ordinary conversion income "
        f"stacks UNDER that income and can push it into a higher preferential rate, which calc op "
        f"tax_with_preferential_rates prices and this op does not. A state income tax stacks on top "
        f"(calc op state_tax). Credit and premium phase-outs the packs do not carry — IRMAA two years "
        f"later, ACA premium-credit repayment, education and family credits — are NOT modeled; run "
        f"calc op magi_ladder on the post-conversion AGI to see which tests move."
        + (f" ({alias_note}.)" if alias_note else "")
    )

    work_lines = [
        f"Roth conversion ({year}, {filing_status}), {_dollars(gross)} via {source}:",
        path_line, bracket_line, slice_line, niit_line, withholding_line, judgment_line, disclosure_line,
    ]
    inputs: dict[str, Any] = {
        "source": source, "amount": gross, "year": year, "filing_status": filing_status,
        "taxable_income_before": taxable_before_i, "magi_before": magi_before_i,
        "net_investment_income": nii_i,
    }
    if source == "plan_to_roth_ira":
        inputs["plan_after_tax_basis"] = nontaxable_i
    else:
        assert pro_rata is not None
        inputs.update({k: v for k, v in pro_rata.inputs.items() if k != "year"})
    citations = [_NOTICE_2008_30_CITATION, _NOTICE_2014_54_CITATION] if source == "plan_to_roth_ira" else [
        _IRC_408D2_CITATION, _f8606_citation(year), _F8606_INSTRUCTIONS_CITATION, _PUB590B_BASIS_CITATION
    ]
    citations += [_IRC_1411_C5_CITATION, niit_after_r.citation, pack.tax.rate_schedules.citation,
                  _PUB590A_CONVERSION_CITATION]
    return RothConversionResult(
        source=source,  # type: ignore[arg-type]
        amount_converted=gross,
        taxable_amount=taxable_i,
        nontaxable_amount=nontaxable_i,
        pro_rata=pro_rata,
        marginal_rate_before=b_before.rate,
        marginal_rate_after=b_after.rate,
        bracket_top_before=top_before,
        headroom_before=headroom_before,
        headroom_after=headroom_after,
        spill_into_higher_brackets=spill,
        bracket_slices=slices,
        incremental_income_tax=incremental,
        magi_before=magi_before_i,
        magi_after=magi_after_i,
        niit_threshold=threshold,
        niit_before=niit_before_r.niit,
        niit_after=niit_after_r.niit,
        niit_from_conversion=niit_after_r.niit - niit_before_r.niit,
        crosses_niit_threshold=crosses,
        total_incremental_tax=incremental + (niit_after_r.niit - niit_before_r.niit),
        inputs=inputs,
        work="\n".join(work_lines),
        citation=citations[0],
        citations=citations,
    )


# ---------------------------------------------------------------------------
# HSA deduction (Phase I, I2): Form 8889 / IRC 223 — the monthly limitation,
# the last-month rule and its 13-month testing period, and the employer-money
# offset that double-counts when it is got backwards
# ---------------------------------------------------------------------------

# Everything in this section is YEAR-INVARIANT law, so — following the
# P-005/P-006 discipline that only FIGURES belong in a year pack — the
# authorities live here beside the op. The year's dollar limits come from
# ``contribution_limits.hsa`` in knowledge/federal/<year>.yaml, which is why
# this op reads a pack at all.
#
# Form 8889's line numbering was read off EVERY revision the repo's shipped
# years could reach (f8889--2019.pdf .. f8889--2025.pdf, all fetched): Part I
# lines 1-13, Part II lines 14a-17b and Part III lines 18-21 are IDENTICAL in
# all seven. One thing DID move, and it is a wording change, not a renumber:
# through the 2023 revision line 13 printed its own destination ("HSA
# deduction. Enter the smaller of line 2 or line 12 here and on Schedule 1
# (Form 1040), Part II, line 13"); the 2024 and 2025 revisions print "HSA
# deduction (see instructions)" and the destination moved into the
# instructions' Line 13 paragraph, which names the same Schedule 1 Part II
# line 13.
# NARROWED to 2021-2025 on 2026-08-26: the citation body quotes the Schedule 1 /
# Schedule 2 DESTINATIONS ('Schedule 1 (Form 1040), Part I, line 8f' etc.), and the
# 2019 and 2020 revisions print materially different ones ('Schedule 1 (Form 1040 or
# 1040-SR), line 8, or Form 1040-NR, line 21'). Claiming those were read off the
# revision's own blank would be false. The 2019/2020 blanks WERE downloaded and their
# Part I/II/III line NUMBERING confirmed identical; it is only the destinations that
# moved, so widening this range again means making the destination clause year-aware.
_F8889_VERIFIED_REVISIONS: tuple[int, ...] = tuple(range(2021, 2026))
_F8889_NEWEST_VERIFIED = max(_F8889_VERIFIED_REVISIONS)

_HSA_TIERS = ("self_only", "family", "none")
_HSA_FSA_KINDS = ("none", "limited_purpose", "post_deductible", "general_purpose")

# IRC 4973(a): 6%, statutory and not indexed. Held here rather than in a year
# pack because it is not a year-varying figure (the IRA block carries its own
# copy for the same rate because that block predates this discipline).
_HSA_EXCISE_RATE = Decimal("0.06")
# IRC 223(b)(8)(B)(i)(II) / Form 8889 line 21.
_HSA_TESTING_PERIOD_TAX_RATE = Decimal("0.10")
# IRC 223(f)(4)(A) / Form 8889 line 17b.
_HSA_NONQUALIFIED_DISTRIBUTION_RATE = Decimal("0.20")

_IRC_223_LIMIT_CITATION = Citation(
    source=(
        "IRC 223 (26 U.S.C. 223): (a) the deduction is 'the aggregate amount paid in cash "
        "during such taxable year by or on behalf of such individual to a health savings "
        "account'; (b)(1) it 'shall not exceed the sum of the monthly limitations for months "
        "during such taxable year that the individual is an eligible individual'; (b)(2) 'The "
        "monthly limitation for any month is 1/12 of' the self-only or family amount, keyed to "
        "the coverage the individual has 'as of the first day of such month' — the statutory "
        "basis for month-by-month proration; (b)(3) the age-55 additional contribution amount "
        "is '$1,000' for '2009 and thereafter' for an individual 'who has attained age 55 "
        "before the close of the taxable year'; (b)(4) the limit is reduced by Archer MSA "
        "contributions, by amounts 'excludable from the taxpayer's gross income for such "
        "taxable year under section 106(d)' (employer/cafeteria-plan money, '(and such amount "
        "shall not be allowed as a deduction under subsection (a))') and by section 408(d)(9) "
        "qualified HSA funding distributions; (b)(5) if either spouse has family coverage "
        "'both spouses shall be treated as having only such family coverage' and the limit, "
        "'without regard to any additional contribution amount under paragraph (3)', 'shall be "
        "divided equally between them unless they agree on a different division'; (b)(6) no "
        "deduction to an individual another taxpayer may claim as a dependent; (b)(7) 'The "
        "limitation under this subsection for any month ... shall be zero for the first month "
        "such individual is entitled to benefits under title XVIII of the Social Security Act "
        "and for each month thereafter'"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section223&num=0&edition=prelim",
)

_IRC_223_B8_CITATION = Citation(
    source=(
        "IRC 223(b)(8) (26 U.S.C. 223(b)(8)), 'Increase in limit for individuals becoming "
        "eligible individuals after the beginning of the year': (A) 'an individual who is an "
        "eligible individual during the last month of such taxable year shall be treated (i) "
        "as having been an eligible individual during each of the months in such taxable year, "
        "and (ii) as having been enrolled, during each of the months such individual is "
        "treated as an eligible individual solely by reason of clause (i), in the same high "
        "deductible health plan in which the individual was enrolled for the last month'; "
        "(B)(i) 'If, at any time during the testing period, the individual is not an eligible "
        "individual', gross income for the year of the first failing month 'is increased by "
        "the aggregate amount of all contributions to the health savings account of the "
        "individual which could not have been made but for subparagraph (A)' AND 'the tax "
        "imposed by this chapter ... shall be increased by 10 percent of the amount of such "
        "increase'; (B)(ii) the exception for death or becoming disabled 'within the meaning "
        "of section 72(m)(7)'; (B)(iii) 'The term \"testing period\" means the period "
        "beginning with the last month of the taxable year referred to in subparagraph (A) and "
        "ending on the last day of the 12th month following such month' — 13 months"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section223&num=0&edition=prelim",
)

_IRC_223_C1_CITATION = Citation(
    source=(
        "IRC 223(c)(1) (26 U.S.C. 223(c)(1)), 'Eligible individual': '(A) ... with respect to "
        "any month, any individual if (i) such individual is covered under a high deductible "
        "health plan as of the 1st day of such month, and (ii) such individual is not, while "
        "covered under a high deductible health plan, covered under any health plan (I) which "
        "is not a high deductible health plan, and (II) which provides coverage for any "
        "benefit which is covered under the high deductible health plan.' (B) disregards "
        "permitted insurance, 'coverage (whether through insurance or otherwise) for "
        "accidents, disability, dental care, vision care, long-term care, or telehealth and "
        "other remote care', and (B)(iii) health-FSA coverage during a plan year's grace "
        "period only if 'the balance in such arrangement at the end of such plan year is "
        "zero' or the individual makes a section 106(e) qualified HSA distribution of it. "
        "(C)/(D) preserve eligibility for service-connected VA care and surprise-billing "
        "benefits; (E) excludes a qualifying direct primary care service arrangement from "
        "being a health plan at all"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section223&num=0&edition=prelim",
)

_IRC_223_F4_CITATION = Citation(
    source=(
        "IRC 223(f)(4)(A) (26 U.S.C. 223(f)(4)): a distribution includible in gross income "
        "under 223(f)(2) increases the tax 'by 20 percent of the amount which is so "
        "includible' — raised from 10 percent by P.L. 111-148 section 9004(a). 223(f)(4)(B) "
        "excepts distributions made after the account beneficiary's death, disability, or "
        "attaining the age for Medicare eligibility"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section223&num=0&edition=prelim",
)

_IRC_4973_HSA_CITATION = Citation(
    source=(
        "IRC 4973 (26 U.S.C. 4973): subsection (a) imposes, for a health savings account "
        "'(within the meaning of section 223(d))', 'for each taxable year a tax in an amount "
        "equal to 6 percent of the amount of the excess contributions to such individual's "
        "accounts ... (determined as of the close of the taxable year)', and 'The amount of "
        "such tax for any taxable year shall not exceed 6 percent of the value of the account "
        "... determined as of the close of the taxable year'. Subsection (g) defines the HSA "
        "excess as the amount contributed 'which is neither excludable from gross income "
        "under section 106(d) nor allowable as a deduction under section 223 for such year', "
        "plus the prior year's excess reduced by taxable distributions and by any unused "
        "limit; a contribution 'distributed out of the health savings account in a "
        "distribution to which section 223(f)(3) applies shall be treated as an amount not "
        "contributed'"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section4973&num=0&edition=prelim",
)

_REV_RUL_2004_45_CITATION = Citation(
    source=(
        "Rev. Rul. 2004-45 (section 223 — interaction with other health arrangements): 'A "
        "health FSA and an HRA are health plans and constitute other coverage under section "
        "223(c)(1)(A)(ii). Consequently, an individual who is covered by an HDHP and a health "
        "FSA or HRA that pays or reimburses section 213(d) medical expenses is generally not "
        "an eligible individual for the purpose of making contributions to an HSA.' Holding, "
        "Situation 1: 'This result is the same if the individual is covered by a health FSA or "
        "HRA sponsored by the employer of the individual's SPOUSE.' Situations 2-5 are the "
        "arrangements that do NOT disqualify: a LIMITED-PURPOSE health FSA/HRA paying only "
        "permitted coverage (dental, vision) and preventive care; a POST-DEDUCTIBLE health "
        "FSA/HRA that 'does not pay or reimburse any medical expense incurred before the "
        "minimum annual deductible under section 223(c)(2)(A)(i) is satisfied' (and 'Where the "
        "HDHP and the other coverage do not have identical deductibles, contributions to the "
        "HSA are limited to the lower of the deductibles'); a SUSPENDED HRA elected before the "
        "coverage period begins; and a RETIREMENT HRA, which disqualifies only after "
        "retirement"
    ),
    url="https://www.irs.gov/pub/irs-drop/rr-04-45.pdf",
)

_I8889_CITATION = Citation(
    source=(
        "Instructions for Form 8889 (2025), Nov 25 2025 revision. Last-month rule: 'You may "
        "consider yourself an \"eligible individual\" for the entire year if you are an "
        "eligible individual on the 1st day of the last month of the tax year (December 1, for "
        "most individuals). You are then subject to a \"testing period\".' Testing period: "
        "'begins with the last month of your tax year and ends on the last day of the 12th "
        "month following that month (for example, December 1, 2025 - December 31, 2026)'. "
        "Line 2: 'Do not include employer contributions (see line 9) ... Payroll contributions "
        "through a salary reduction agreement elected by an employee (a cafeteria plan) are "
        "treated as employer contributions and are not included on line 2.' Line 3 rules "
        "1-6 and the LINE 3 LIMITATION CHART AND WORKSHEET (per month: -0- for a Medicare "
        "month or a month not eligible on the first day, otherwise the self-only or family "
        "amount, with the age-55 amount folded in; 'Total for all months' divided by 12), plus "
        "the greater-of test against 'The maximum amount that can be contributed based on the "
        "type of HDHP coverage you had on the first day of the last month of your tax year'. "
        "Line 6 spouse allocation and the Line 7 ADDITIONAL CONTRIBUTION AMOUNT WORKSHEET "
        "('$1,000 x number of months eligible', divided by 12) with the Line 3 note that a "
        "married filer who 'had family coverage at any time during the year' figures the "
        "additional amount on line 7 and NOT on line 3. Line 9: 'Employer contributions "
        "(including employee payroll contributions through a cafeteria plan) ... should be "
        "shown on Form W-2, box 12, code W.' Line 13: 'Generally, enter the smaller of line 2 "
        "or line 12 on line 13 and on Schedule 1 (Form 1040), Part II, line 13.' Excess "
        "Contributions You Make / Excess Employer Contributions (the excess is over the line 8 "
        "limitation, reduced first by any line 10 funding distribution) and the withdrawal "
        "cure by the due date INCLUDING extensions, with the further 'no later than 6 months "
        "after the due date' amended-return path 'Filed pursuant to section 301.9100-2'. "
        "Part III Line 18: 'Enter on line 18 the excess of the amount contributed over the "
        "redetermined amount'"
    ),
    url="https://www.irs.gov/pub/irs-prior/i8889--2025.pdf",
)

_PUB969_CITATION = Citation(
    source=(
        "Publication 969 (2025), 'Health Savings Accounts (HSAs)'. Limit on Contributions: "
        "'if you weren't an eligible individual for the entire year or changed your coverage "
        "during the year, your contribution limit is the greater of: 1. The limitation shown "
        "on the Line 3 Limitation Chart and Worksheet in the Instructions for Form 8889 ...; "
        "or 2. The maximum annual HSA contribution based on your HDHP coverage (self-only or "
        "family) on the first day of the last month of your tax year.' Worked last-month-rule "
        "examples: Example 1 (family coverage from December 1, 2025, $8,550 contributed, "
        "eligibility lost June 2026) -> worksheet limitation $712.50 and 'You would include "
        "$7,837.50 ($8,550.00 - $712.50) in your gross income on your 2026 tax return. Also, a "
        "10% additional tax applies'; Example 2 (self-only from January 1, family from "
        "November 1, $8,550 contributed, eligibility lost March 2026) -> total for all months "
        "$60,100.00, limitation $5,008.33, include $3,541.67. Medicare example: 'You turned "
        "age 65 in July 2025 and enrolled in Medicare ... Your contribution limit is $2,650 "
        "($5,300 x 6 / 12).' Other employee health plans: 'An employee covered by an HDHP and "
        "a health FSA or an HRA that pays or reimburses qualified medical expenses can't "
        "generally make contributions to an HSA.' Other health coverage: 'you can still be an "
        "eligible individual even if your spouse has non-HDHP coverage, provided you aren't "
        "covered by that plan.' Employer contributions: 'You must reduce the amount you or any "
        "other person can contribute to your HSA by the amount of any contributions made by "
        "your employer that are excludable from your income. This includes amounts contributed "
        "to your account by your employer through a cafeteria plan.' Rules for married people: "
        "'If both spouses meet the age requirement, the total contributions under family "
        "coverage can't be more than $10,550. Each spouse must make the additional "
        "contribution to their own HSA.' And 'Each spouse who is an eligible individual who "
        "wants an HSA must open a separate HSA. You can't have a joint HSA.'"
    ),
    url="https://www.irs.gov/pub/irs-pdf/p969.pdf",
)


def _f8889_citation(year: int) -> Citation:
    """Cite the year's own Form 8889 revision; a year whose form has not published
    yet cites the newest revision actually READ and says so in the source text."""
    body = (
        "Part I lines 1-13 (line 1 the self-only/family coverage box, line 2 'HSA "
        "contributions you made ... Do not include employer contributions, contributions "
        "through a cafeteria plan, or rollovers', line 3 the limitation, line 4 Archer MSA "
        "contributions from Form 8853, line 5 = 3 - 4, line 6 line 5 or the spouse's share, "
        "line 7 the age-55 additional contribution amount, line 8 = 6 + 7, line 9 employer "
        "contributions, line 10 qualified HSA funding distributions, line 11 = 9 + 10, "
        "line 12 = 8 - 11 floored at zero, line 13 the HSA deduction), Part II lines 14a-17b "
        "(14c = 14a - 14b, line 16 = 14c - 15 floored at zero -> 'Schedule 1 (Form 1040), "
        "Part I, line 8f', 17a the exceptions checkbox, 17b '20% (0.20) of the distributions "
        "included on line 16 that are subject to the additional 20% tax' -> 'Schedule 2 (Form "
        "1040), Part II, line 17c') and Part III lines 18-21 ('Income and Additional Tax for "
        "Failure To Maintain HDHP Coverage': line 18 last-month rule, line 19 qualified HSA "
        "funding distribution, line 20 = 18 + 19 -> Schedule 1 Part I line 8f, line 21 = 10% "
        "of line 20 -> Schedule 2 Part II line 17d) — line numbering read off this revision's "
        "own blank"
    )
    if year in _F8889_VERIFIED_REVISIONS:
        return Citation(source=f"Form 8889 ({year}), {body}", url=f"https://www.irs.gov/pub/irs-prior/f8889--{year}.pdf")
    return Citation(
        source=(
            f"Form 8889 ({_F8889_NEWEST_VERIFIED}) — quoted for {year} because the {year} revision had "
            f"not published when this op was written. {body}. Part I/II/III numbering is identical on "
            f"every revision actually read ({_F8889_VERIFIED_REVISIONS[0]}-{_F8889_NEWEST_VERIFIED}), "
            f"but RE-VERIFY against the {year} form before anything is filed"
        ),
        url=f"https://www.irs.gov/pub/irs-prior/f8889--{_F8889_NEWEST_VERIFIED}.pdf",
    )


class HsaDeductionResult(BaseModel):
    """Result of :func:`hsa_deduction`: Form 8889 Parts I-III, line by line."""

    model_config = ConfigDict(extra="forbid")

    deduction: int = Field(
        description="Form 8889 line 13 = min(line 2, line 12) -> Schedule 1 (Form 1040), Part II, line 13."
    )
    deduction_exact: Decimal = Field(description="Line 13 before whole-dollar rounding (the limit carries cents).")
    annual_limit: int = Field(description="Form 8889 line 3 as filed: the greater of the monthly chart and the last-month-rule amount.")
    annual_limit_exact: Decimal = Field(description="Line 3 before rounding — the chart divides by 12, so cents are normal here.")
    prorated_limit: Decimal = Field(description="The Line 3 Limitation Chart total / 12: what IRC 223(b)(1)-(2) allows month by month.")
    limit_basis: Literal["full_year", "monthly_proration", "last_month_rule"]
    monthly_limits: list[str] = Field(description="The Line 3 Limitation Chart, January first — one entry per month.")
    months_eligible: int = Field(description="Months with a non-zero chart amount (first-day-of-month test, Medicare months excluded).")
    last_month_rule_applied: bool = Field(
        description="True when IRC 223(b)(8)(A) bought room the monthly proration would not allow — this is what starts the testing period."
    )
    testing_period: dict[str, str] | None = Field(
        default=None, description="The IRC 223(b)(8)(B)(iii) 13-month window, spelled out, when the last-month rule applies."
    )
    at_risk_if_testing_period_fails: int = Field(
        description="Form 8889 line 18 if eligibility lapses in the testing period: the contributions that could not have been made but for 223(b)(8)(A)."
    )
    input_assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Assumptions this op made about the INPUTS, promoted out of `work` so a caller "
            "reading only `deduction` cannot miss them. Today the only entry is the "
            "months_eligible expansion: the shorthand places the eligible months at the END of "
            "the year, which is not neutral — it is what triggers the last-month rule and can "
            "double the deduction relative to the same count of months earlier in the year."
        ),
    )
    catch_up_amount: int = Field(description="The age-55 additional contribution actually allowed (line 3 or line 7 — never both).")
    catch_up_on_line: Literal["3", "7", "none"] = Field(
        description="Where the $1,000 rides: line 7 for a married filer with ANY family coverage in the year, otherwise inside line 3."
    )
    employer_contributions_excluded: int = Field(
        description="Form 8889 line 9 — W-2 box 12 code W, employer money AND cafeteria-plan payroll deferrals. Already out of box 1: NOT deductible again."
    )
    excess_personal_contributions: int = Field(description="Line 2 - line 13: your own excess (Form 5329 Part VII).")
    excess_employer_contributions: int = Field(description="Line 9 over the line 8 limitation (reduced first by line 10).")
    excise_per_year: int = Field(description="IRC 4973(a): 6% of the total excess, charged EVERY year it stays in the account.")
    taxable_distributions: int = Field(description="Form 8889 line 16 -> Schedule 1 Part I line 8f.")
    distributions_additional_tax: int = Field(description="Form 8889 line 17b: 20% of the non-excepted part of line 16 -> Schedule 2 Part II line 17c.")
    recapture_income: int = Field(description="Form 8889 line 20 (= 18 + 19) -> Schedule 1 Part I line 8f.")
    recapture_additional_tax: int = Field(description="Form 8889 line 21 = 10% of line 20 -> Schedule 2 Part II line 17d.")
    fica_saving_forgone: Decimal | None = Field(
        default=None,
        description="Payroll FICA the DIRECT (line 2) contributions did not avoid, at this wage level's real tier — None unless wages were passed.",
    )
    fica_tier: str | None = Field(default=None, description="Which FICA tier the next wage dollar sits in, and why.")
    form_8889_lines: dict[str, str] = Field(description="Every Part I/II/III line this op computes, keyed by the form's printed line label.")
    inputs: dict[str, Any]
    work: str
    citation: Citation
    citations: list[Citation] = Field(description="Every authority behind the number, statute first.")


def hsa_deduction(
    coverage: str | None = None,
    year: int = 2026,
    months_eligible: int | None = None,
    monthly_coverage: Sequence[str] | None = None,
    age_55_plus: bool = False,
    married: bool = False,
    spouse_has_separate_hsa: bool = False,
    your_share_of_family_limit: int | float | Decimal | str | None = None,
    personal_contributions: int | float | Decimal | str = 0,
    employer_contributions: int | float | Decimal | str = 0,
    qualified_hsa_funding_distribution: int | float | Decimal | str = 0,
    archer_msa_contributions: int | float | Decimal | str = 0,
    medicare_start_month: int | None = None,
    health_fsa: str = "none",
    claimed_as_dependent_by_another: bool = False,
    testing_period_failed: bool = False,
    funding_distribution_testing_period_failed: bool = False,
    distributions_total: int | float | Decimal | str = 0,
    distributions_rolled_over: int | float | Decimal | str = 0,
    qualified_medical_expenses: int | float | Decimal | str = 0,
    distributions_excepted_from_20_percent: int | float | Decimal | str = 0,
    wages: int | float | Decimal | str | None = None,
    knowledge_dir: str | Path | None = None,
) -> HsaDeductionResult:
    """Form 8889 as IRC 223 writes it: how much of an HSA contribution is actually
    DEDUCTIBLE, what the last-month rule buys and what it puts at risk.

    This op exists because ``contribution_limits`` already shipped the year's HSA
    amounts while nothing could turn them into a return line — an HSA
    contribution could be planned and never filed. Five traps it is built
    around, each one a real filing error:

    1. **The limit is MONTHLY, not annual.** IRC 223(b)(1)-(2): the deduction is
       "the sum of the monthly limitations for months ... that the individual is
       an eligible individual", and each monthly limitation is 1/12 of the tier
       amount for the coverage held "as of the first day of such month". A
       July-start HDHP holder gets 6/12 of the limit, not the whole thing. Pass
       ``months_eligible`` (the shorthand) or ``monthly_coverage`` (the Line 3
       Limitation Chart itself, 12 entries, January first).
    2. **The last-month rule and its 13-month testing period.** IRC 223(b)(8)(A)
       treats someone eligible on December 1 as eligible all year, so line 3
       becomes the GREATER of the monthly chart and the full annual limit for
       December's coverage tier. It is not an election and it is not free:
       223(b)(8)(B) runs a testing period from December 1 through December 31 of
       the FOLLOWING year, and losing eligibility inside it pulls the extra
       contributions back into income PLUS a 10% additional tax. This op always
       reports ``at_risk_if_testing_period_fails``, whether or not it failed.
    3. **Employer money reduces the DEDUCTION, it is not a second deduction.**
       W-2 box 12 code W is employer contributions AND the employee's own
       cafeteria-plan payroll deferrals (i8889, line 9), and every dollar of it
       is already out of box 1 under section 106(d). It belongs on line 9, where
       it SUBTRACTS from the room on line 12 — only DIRECT contributions (line 2)
       reach Schedule 1. Deducting box 12 code W again is the most common HSA
       filing error, and it is why ``personal_contributions`` and
       ``employer_contributions`` are separate arguments.
    4. **A general-purpose health FSA — including a SPOUSE's — is
       disqualifying coverage.** Rev. Rul. 2004-45 holds a health FSA or HRA that
       reimburses section 213(d) expenses is "other coverage" under
       223(c)(1)(A)(ii), and says in terms that "This result is the same if the
       individual is covered by a health FSA or HRA sponsored by the employer of
       the individual's spouse." ``health_fsa='general_purpose'`` is REFUSED with
       the fix. Limited-purpose (dental/vision) and post-deductible arrangements
       are fine and are accepted.
    5. **Excess contributions.** IRC 4973(a) charges 6% of the excess EVERY year
       it stays in the account. The cure is a withdrawal of the excess plus its
       earnings by the return's due date INCLUDING extensions, with a further
       six-month amended-return window under section 301.9100-2.

    ``wages`` is optional and adds the payroll half: cafeteria-plan HSA dollars
    avoid income tax AND FICA, so a DIRECT contribution of the same size saves
    the same income tax and loses the FICA. Above the social security wage base
    that FICA saving is Medicare only — 1.45%, or 2.35% once the 0.9% Additional
    Medicare withholding threshold is passed — never 7.65%, and the filers who
    max an HSA are exactly the ones above the base.

    ``year`` selects the pack the dollar limits come from, and the Form 8889
    revision the work string quotes. A year with no ``contribution_limits.hsa``
    block is refused rather than estimated.
    """
    # ── argument validation, before any arithmetic ────────────────────────────
    if health_fsa not in _HSA_FSA_KINDS:
        raise ValueError(
            f"health_fsa must be one of {list(_HSA_FSA_KINDS)}, got {health_fsa!r} — the distinction is "
            f"the whole point: Rev. Rul. 2004-45 disqualifies a GENERAL-PURPOSE health FSA or HRA and "
            f"expressly allows a LIMITED-PURPOSE (dental/vision/preventive) or POST-DEDUCTIBLE one"
        )
    if health_fsa == "general_purpose":
        raise ValueError(
            "health_fsa='general_purpose' means there is no HSA contribution room for those months: "
            "Rev. Rul. 2004-45 holds that 'an individual who is covered by an HDHP and a health FSA or "
            "HRA that pays or reimburses section 213(d) medical expenses is generally not an eligible "
            "individual', and its Situation 1 holding adds 'This result is the same if the individual is "
            "covered by a health FSA or HRA sponsored by the employer of the individual's SPOUSE' — so a "
            "spouse's general-purpose FSA disqualifies you even though you never enrolled in it. FIX: "
            "drop the FSA-covered months out of monthly_coverage (or reduce months_eligible) and call "
            "again with health_fsa='none'; a mid-year switch to a LIMITED-PURPOSE or POST-DEDUCTIBLE FSA "
            "restores eligibility from the first day of the first month it applies, and a general-purpose "
            "FSA's GRACE PERIOD is disregarded under IRC 223(c)(1)(B)(iii) only if its year-end balance "
            "was zero (or the balance was moved by a section 106(e) qualified HSA distribution)"
        )
    if (coverage is None) == (monthly_coverage is None):
        raise ValueError(
            "pass EITHER coverage ('self_only' or 'family', optionally with months_eligible) OR "
            "monthly_coverage (12 entries, January first, each 'self_only'/'family'/'none') — never both "
            "and never neither. monthly_coverage IS the Line 3 Limitation Chart and is the only way to "
            "describe a year whose coverage tier changed mid-year"
        )
    if monthly_coverage is not None:
        if months_eligible is not None:
            raise ValueError(
                "months_eligible and monthly_coverage are two spellings of the same input — pass "
                "monthly_coverage alone (it already says which months, and which tier each one had)"
            )
        rows = list(monthly_coverage)
        if len(rows) != 12:
            raise ValueError(
                f"monthly_coverage needs EXACTLY 12 entries (January first), got {len(rows)} — the Line 3 "
                f"Limitation Chart has a row for every month of the year and an ineligible month is the "
                f"string 'none', never an omitted entry"
            )
        for i, tier in enumerate(rows):
            if tier not in _HSA_TIERS:
                raise ValueError(
                    f"monthly_coverage[{i}] ({_MONTHS[i]}) is {tier!r} — each entry must be one of "
                    f"{list(_HSA_TIERS)}: the coverage held on the FIRST DAY of that month, or 'none'"
                )
        declared = rows
        months_note = (
            "monthly_coverage was supplied, so the chart is exactly the caller's month-by-month reading."
        )
    else:
        if coverage not in ("self_only", "family"):
            raise ValueError(
                f"coverage must be 'self_only' or 'family', got {coverage!r} — a filer with no HDHP "
                f"coverage in ANY month has no contribution room at all; use monthly_coverage to describe "
                f"a year that mixes covered and uncovered months"
            )
        m = 12 if months_eligible is None else months_eligible
        if not isinstance(m, int) or isinstance(m, bool) or not 0 <= m <= 12:
            raise ValueError(f"months_eligible must be an int from 0 to 12, got {months_eligible!r}")
        declared = ["none"] * (12 - m) + [coverage] * m
        months_note = (
            f"months_eligible={m} was expanded to the LAST {m} month(s) of {year} "
            f"({'none' if m == 0 else _MONTHS[12 - m] + '-December'}), a DISCLOSED assumption and not a "
            f"rule — the sum on the chart does not care which months they are, but the last-month rule "
            f"and the line 7 month count both key on DECEMBER, so pass monthly_coverage whenever the "
            f"eligible months are not the closing ones"
        )
    if medicare_start_month is not None:
        if isinstance(medicare_start_month, bool) or not isinstance(medicare_start_month, int) or not 1 <= medicare_start_month <= 12:
            raise ValueError(
                f"medicare_start_month must be a month number 1-12 (the FIRST month entitled to Medicare "
                f"benefits) or None, got {medicare_start_month!r}"
            )
    money = {
        "personal_contributions": personal_contributions,
        "employer_contributions": employer_contributions,
        "qualified_hsa_funding_distribution": qualified_hsa_funding_distribution,
        "archer_msa_contributions": archer_msa_contributions,
        "distributions_total": distributions_total,
        "distributions_rolled_over": distributions_rolled_over,
        "qualified_medical_expenses": qualified_medical_expenses,
        "distributions_excepted_from_20_percent": distributions_excepted_from_20_percent,
    }
    amounts: dict[str, Decimal] = {}
    for name, raw in money.items():
        value = _cents(_to_decimal(raw, name))
        if value < 0:
            raise ValueError(
                f"{name} must be >= 0, got {value} — Form 8889 takes no negative entries; a returned or "
                f"withdrawn contribution is handled by the excess rules (line 14b / Form 5329), not by a "
                f"negative contribution"
            )
        amounts[name] = value

    pack = _load_federal(year, knowledge_dir)
    params = _require_contribution_limits(pack, year)
    hsa = params.hsa
    tier_amounts = {"self_only": Decimal(hsa.self_only), "family": Decimal(hsa.family), "none": Decimal(0)}
    catch_up_full = Decimal(hsa.catch_up_55 or 0) if age_55_plus else Decimal(0)

    # ── the Line 3 Limitation Chart, month by month ───────────────────────────
    # IRC 223(b)(7): from the FIRST month entitled to Medicare the monthly
    # limitation is zero "and for each month thereafter" — so Medicare wipes the
    # tail of the year regardless of what plan is still in force.
    effective = [
        "none" if (medicare_start_month is not None and i + 1 >= medicare_start_month) else tier
        for i, tier in enumerate(declared)
    ]
    had_family_any = any(tier == "family" for tier in declared)
    # i8889 Line 3 note: a MARRIED filer with family coverage at any time in the
    # year figures the additional contribution amount on line 7 and NOT on
    # line 3 — because 223(b)(5)(B) splits the family limit between the spouses
    # "without regard to any additional contribution amount under paragraph (3)".
    catch_up_on_line_7 = bool(catch_up_full) and married and had_family_any
    catch_up_on_line_3 = bool(catch_up_full) and not catch_up_on_line_7
    per_month = [
        tier_amounts[tier] + (catch_up_full if (catch_up_on_line_3 and tier != "none") else Decimal(0))
        for tier in effective
    ]
    chart_total = sum(per_month, Decimal(0))
    chart_limit = _cents(chart_total / 12)
    eligible_months = sum(1 for tier in effective if tier != "none")

    # ── the last-month rule: IRC 223(b)(8)(A) ─────────────────────────────────
    december_tier = effective[11]
    if december_tier == "none":
        lmr_limit = Decimal(0)
    else:
        lmr_limit = tier_amounts[december_tier] + (catch_up_full if catch_up_on_line_3 else Decimal(0))
    line3 = max(chart_limit, lmr_limit)
    last_month_rule_applied = lmr_limit > chart_limit
    if eligible_months == 12 and len(set(effective)) == 1:
        limit_basis: Literal["full_year", "monthly_proration", "last_month_rule"] = "full_year"
    elif last_month_rule_applied:
        limit_basis = "last_month_rule"
    else:
        limit_basis = "monthly_proration"

    # ── line 7: the age-55 additional contribution amount ─────────────────────
    # i8889 Line 7: count the months in which you (or your spouse) had FAMILY
    # coverage under an HDHP, were (or were considered) an eligible individual on
    # the first day of the month, and were NOT enrolled in Medicare.
    eligible_family_months = sum(1 for tier in effective if tier == "family")
    line7_months = eligible_family_months
    if last_month_rule_applied and december_tier == "family":
        # 223(b)(8)(A)(ii): the imputed months are treated as enrolled in
        # DECEMBER's plan, which here is the family plan — so all 12 count.
        line7_months = 12

    # The catch-up actually allowed: the full $1,000 when the last-month rule
    # imputes all 12 months, otherwise 1/12 per eligible month exactly as the
    # chart (line 3) or the Additional Contribution Amount Worksheet (line 7)
    # computes it.
    if catch_up_on_line_7:
        catch_up_allowed = _cents(catch_up_full * Decimal(line7_months) / 12)
    elif catch_up_on_line_3:
        catch_up_allowed = catch_up_full if last_month_rule_applied else _cents(
            catch_up_full * Decimal(eligible_months) / 12
        )
    else:
        catch_up_allowed = Decimal(0)

    # ── lines 4-8 ─────────────────────────────────────────────────────────────
    line4 = amounts["archer_msa_contributions"]
    two_hsa_family_split = bool(married and had_family_any and spouse_has_separate_hsa)
    share: Decimal | None = None
    if your_share_of_family_limit is not None:
        if not two_hsa_family_split:
            raise ValueError(
                "your_share_of_family_limit only has meaning when married=True, the year has family "
                "coverage, and spouse_has_separate_hsa=True — IRC 223(b)(5) divides ONE family limit "
                "between two spouses' HSAs. With no second HSA the whole family limit may go into yours"
            )
        share = _cents(_to_decimal(your_share_of_family_limit, "your_share_of_family_limit"))
        ceiling = max(Decimal(0), line3 - line4)
        if share < 0 or share > ceiling:
            raise ValueError(
                f"your_share_of_family_limit must be between 0 and the line 5 limit {_money(ceiling)}, "
                f"got {_money(share)} — the two spouses' shares divide that one limit "
                f"(223(b)(5)(B)(ii): 'divided equally between them unless they agree on a different division')"
            )

    def _limit_chain(line3_value: Decimal, family_months_for_line_7: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """Form 8889 lines 5-8 from a given line 3 — run twice, once on the filed
        line 3 and once on the chart-only line 3, because Part III's "redetermined
        amount" is the limit you could have contributed WITHOUT 223(b)(8)(A), and
        the Archer offset, the spouse split and the line 7 catch-up all sit
        between line 3 and that limit."""
        l5 = max(Decimal(0), line3_value - line4)
        if share is not None:
            l6 = min(share, l5)
        elif two_hsa_family_split:
            l6 = _cents(l5 / 2)
        else:
            l6 = l5
        l7 = _cents(catch_up_full * Decimal(family_months_for_line_7) / 12) if catch_up_on_line_7 else Decimal(0)
        return l5, l6, l7, l6 + l7

    line5, line6, line7, line8 = _limit_chain(line3, line7_months)
    split_note = ""
    if share is not None:
        split_note = (
            f"line 6: the {_money(line5)} family limit is split by agreement, {_money(line6)} to you "
            f"(223(b)(5)(B)(ii) allows any division, including allocating nothing to one spouse)."
        )
    elif two_hsa_family_split:
        split_note = (
            f"line 6: two spouses, one family limit — 223(b)(5)(B)(ii) divides it EQUALLY by default, so "
            f"{_money(line5)} / 2 = {_money(line6)} is yours. Pass your_share_of_family_limit to record a "
            f"different agreed division (the instructions' example is 'allocating nothing to one spouse')."
        )
    elif married and had_family_any:
        split_note = (
            "line 6 = line 5: the spouse has no separate HSA (spouse_has_separate_hsa=False), so the "
            "whole family limit can be contributed to yours — the 223(b)(5)(B)(ii) division allows "
            "allocating nothing to one spouse, and Pub 969 is explicit that 'Each spouse who is an "
            "eligible individual who wants an HSA must open a separate HSA. You can't have a joint HSA.'"
        )

    # ── lines 9-13: the employer offset, and what is left to deduct ───────────
    line2 = amounts["personal_contributions"]
    line9 = amounts["employer_contributions"]
    line10 = amounts["qualified_hsa_funding_distribution"]
    line11 = line9 + line10
    line12 = max(Decimal(0), line8 - line11)
    line13 = min(line2, line12)
    dependent_note = ""
    if claimed_as_dependent_by_another:
        line13 = Decimal(0)
        dependent_note = (
            f"DEPENDENT: IRC 223(b)(6) denies the deduction outright to an individual another taxpayer "
            f"may claim as a dependent, so line 13 is $0 even though line 12 leaves {_money(line12)} of "
            f"room. Pub 969: 'This is true even if the other person doesn't receive an exemption "
            f"deduction for you because the exemption amount is zero.' The whole {_money(line2)} is an "
            f"EXCESS contribution under IRC 4973(g)(1) — neither excludable nor deductible."
        )

    # ── excess contributions: IRC 4973 ────────────────────────────────────────
    excess_personal = max(Decimal(0), line2 - line13)
    # i8889, Excess Employer Contributions: the excess over the LINE 8 limitation,
    # and line 8 is reduced by any line 10 funding distribution FIRST.
    employer_room = max(Decimal(0), line8 - line10)
    excess_employer = max(Decimal(0), line9 - employer_room)
    excess_total = excess_personal + excess_employer
    excise = _cents(_HSA_EXCISE_RATE * excess_total)

    # ── Part II: distributions ────────────────────────────────────────────────
    line14a = amounts["distributions_total"]
    line14b = amounts["distributions_rolled_over"]
    if line14b > line14a:
        raise ValueError(
            f"distributions_rolled_over ({_money(line14b)}) cannot exceed distributions_total "
            f"({_money(line14a)}) — Form 8889 line 14b is 'Distributions included on line 14a that you "
            f"rolled over', a subset of line 14a (1099-SA box 1 is the line 14a figure)"
        )
    line14c = line14a - line14b
    line15 = amounts["qualified_medical_expenses"]
    line16 = max(Decimal(0), line14c - line15)
    excepted = amounts["distributions_excepted_from_20_percent"]
    if excepted > line16:
        raise ValueError(
            f"distributions_excepted_from_20_percent ({_money(excepted)}) exceeds line 16 "
            f"({_money(line16)}) — line 17b is '20% (0.20) of the distributions INCLUDED ON LINE 16 that "
            f"are subject to the additional 20% tax', so the excepted amount is a slice of line 16, "
            f"never more. The exceptions (IRC 223(f)(4)(B)) are death, disability and turning 65"
        )
    line17b = _cents(_HSA_NONQUALIFIED_DISTRIBUTION_RATE * (line16 - excepted))

    # ── Part III: the testing-period recapture ────────────────────────────────
    # 223(b)(8)(B)(i)(I) recaptures "all contributions ... which could not have
    # been made but for subparagraph (A)" — i8889 line 18: "the excess of the
    # amount contributed over the redetermined amount", the redetermined amount
    # being the Line 3 chart limit without the last-month rule.
    # The redetermined limit is the WHOLE chain re-run on the chart-only line 3:
    # the Archer offset, any spouse split and the line 7 catch-up (whose month
    # count drops back to the real family months) all move with it.
    _, _, _, redetermined_line8 = _limit_chain(chart_limit, eligible_family_months)
    redetermined_room = max(Decimal(0), redetermined_line8 - line10)
    lmr_benefit = max(Decimal(0), line8 - redetermined_line8)
    contributed_for_recapture = line2 + line9
    at_risk = min(max(Decimal(0), contributed_for_recapture - redetermined_room), lmr_benefit)
    line18 = at_risk if testing_period_failed else Decimal(0)
    if funding_distribution_testing_period_failed and not line10:
        raise ValueError(
            "funding_distribution_testing_period_failed=True with qualified_hsa_funding_distribution=0 "
            "has nothing to recapture — Form 8889 line 19 is 'the total of any qualified HSA funding "
            "distribution' (line 10). The last-month rule's own testing period is the "
            "testing_period_failed flag, and the two run on different clocks"
        )
    line19 = line10 if funding_distribution_testing_period_failed else Decimal(0)
    line20 = line18 + line19
    line21 = _cents(_HSA_TESTING_PERIOD_TAX_RATE * line20)
    testing_period = None
    if last_month_rule_applied:
        testing_period = {
            "begins": f"December 1, {year}",
            "ends": f"December 31, {year + 1}",
            "length_months": "13",
            "authority": "IRC 223(b)(8)(B)(iii)",
            "failure_cost": (
                f"{_money(at_risk)} back into {year + 1} income (Form 8889 line 18 -> line 20 -> "
                f"Schedule 1 Part I line 8f) plus a 10% additional tax of "
                f"{_money(_cents(_HSA_TESTING_PERIOD_TAX_RATE * at_risk))} (line 21 -> Schedule 2 Part II "
                f"line 17d), unless the lapse was death or disability under 223(b)(8)(B)(ii)"
            ),
        }

    # ── the FICA half, optional ───────────────────────────────────────────────
    fica_saving: Decimal | None = None
    fica_tier: str | None = None
    if wages is not None:
        wages_d = _to_decimal(wages, "wages")
        if wages_d < 0:
            raise ValueError("wages must be >= 0")
        ess = pack.tax.employee_social_security
        if ess is None or ess.medicare_rate is None:
            raise ValueError(
                f"knowledge pack for federal {year} has no employee-side FICA parameters — add the "
                f"medicare fields to employee_social_security (see knowledge/federal/2025.yaml), or call "
                f"hsa_deduction without wages to skip the payroll comparison"
            )
        threshold = Decimal(ess.additional_medicare_withholding_threshold)
        if wages_d < ess.ss_wage_base:
            rate = ess.rate + ess.medicare_rate
            fica_tier = (
                f"wages {_money(wages_d)} are BELOW the ${ess.ss_wage_base:,} social security wage base, "
                f"so a cafeteria-plan dollar avoids the full {rate:%} (SS {ess.rate:%} + Medicare "
                f"{ess.medicare_rate:%})"
            )
        elif wages_d <= threshold:
            # `<=`, not `<`: Pub 15 withholds Additional Medicare on wages "in excess
            # of" the threshold, so wages of exactly $200,000 are still in the
            # Medicare-only tier (off-by-one found 2026-08-26 by the adversarial review).
            rate = ess.medicare_rate
            fica_tier = (
                f"wages {_money(wages_d)} are ABOVE the ${ess.ss_wage_base:,} social security wage base, "
                f"so SS is already capped and a cafeteria-plan dollar avoids only Medicare {rate:%} — "
                f"NOT 7.65%"
            )
        else:
            rate = ess.medicare_rate + ess.additional_medicare_withholding_rate
            fica_tier = (
                f"wages {_money(wages_d)} exceed both the ${ess.ss_wage_base:,} social security wage base "
                f"and the ${irs_round(threshold):,} Additional Medicare withholding threshold, so a "
                f"cafeteria-plan dollar avoids Medicare {ess.medicare_rate:%} + Additional Medicare "
                f"{ess.additional_medicare_withholding_rate:%} = {rate:%} — NOT 7.65%. This is the tier "
                f"the filers who max an HSA are actually in. TWO CAVEATS, both of which make this an "
                f"UPPER BOUND. (1) ${irs_round(threshold):,} is the employer's status-blind WITHHOLDING "
                f"threshold; the Form 8959 TAX is measured against a FILING-STATUS threshold "
                f"($250,000 MFJ / $125,000 MFS / $200,000 otherwise, IRC 3101(b)(2)), so an MFJ filer "
                f"between the two gets the withheld 0.9% back as a credit and does NOT save it — call "
                f"marginal_dollar_savings with your filing_status for that answer. (2) This is the "
                f"MARGINAL rate at the top of these wages applied to the whole line-13 amount; a "
                f"contribution straddling the threshold saves {ess.medicare_rate:%} on the part below it"
            )
        fica_saving = _cents(rate * line13)

    # ── the printed lines ─────────────────────────────────────────────────────
    # i8889 Line 1: "check the box for the plan that was in effect for a longer
    # period", overridden by "If, on the first day of the last month of your tax
    # year ... you had family coverage, check the 'family' box"; simultaneous
    # self-only and family coverage "you are treated as having family coverage".
    self_only_months = sum(1 for tier in declared if tier == "self_only")
    declared_family_months = sum(1 for tier in declared if tier == "family")
    if december_tier == "family":
        # The printed override runs ONE WAY only. i8889 Line 1: "check the box for
        # the plan that was in effect for a longer period", then "If, on the first
        # day of the last month of your tax year ... you had family coverage, check
        # the 'family' box." There is no matching sentence for a self-only December,
        # so a December self-only month does NOT override a majority-family year
        # (found 2026-08-26 by the Phase-I2 adversarial review, which reproduced
        # 10 family months + 2 self-only printing "Self-only").
        coverage_box = "Family"
    elif declared_family_months == 0 and self_only_months == 0:
        coverage_box = "(neither — no HDHP coverage on the first day of any month)"
    else:
        coverage_box = "Family" if declared_family_months >= self_only_months else "Self-only"
    lines = {
        "1": coverage_box,
        "2": _money(line2), "3": _money(line3), "4": _money(line4), "5": _money(line5),
        "6": _money(line6), "7": _money(line7), "8": _money(line8), "9": _money(line9),
        "10": _money(line10), "11": _money(line11), "12": _money(line12), "13": _money(line13),
        "14a": _money(line14a), "14b": _money(line14b), "14c": _money(line14c), "15": _money(line15),
        "16": _money(line16), "17b": _money(line17b),
        "18": _money(line18), "19": _money(line19), "20": _money(line20), "21": _money(line21),
    }

    chart_rows = ", ".join(f"{_MONTHS[i][:3]} {_money(per_month[i])}" for i in range(12))
    work_lines = [
        f"Form 8889 ({year}) Part I, IRC 223 — HSA contributions and deduction:",
        f"line 1 coverage box: {lines['1']}. Eligibility is tested on the FIRST DAY OF EACH MONTH "
        f"(223(c)(1)(A)(i)), and the deduction is 'the sum of the monthly limitations for months during "
        f"such taxable year that the individual is an eligible individual' (223(b)(1)), each 1/12 of the "
        f"tier amount (223(b)(2)) — {eligible_months} of 12 months qualify here. {months_note}",
        f"LINE 3 LIMITATION CHART ({year} amounts from the pack: self-only ${hsa.self_only:,}, family "
        f"${hsa.family:,}"
        + (f", age-55 additional ${hsa.catch_up_55:,}" if hsa.catch_up_55 else "")
        + f"): {chart_rows}. Total for all months {_money(chart_total)} / 12 = {_money(chart_limit)}.",
    ]
    if last_month_rule_applied:
        work_lines.append(
            f"LAST-MONTH RULE APPLIES. Eligible on December 1 with {december_tier.replace('_', '-')} "
            f"coverage, so 223(b)(8)(A) treats you as 'having been an eligible individual during each of "
            f"the months in such taxable year' and 'as having been enrolled ... in the same high "
            f"deductible health plan in which the individual was enrolled for the last month'. Line 3 is "
            f"the GREATER of the chart {_money(chart_limit)} and the full-year December-tier amount "
            f"{_money(lmr_limit)} -> {_money(line3)}, which is {_money(lmr_benefit)} more room than the "
            f"months alone allow."
        )
        work_lines.append(
            f"TESTING PERIOD: December 1, {year} through December 31, {year + 1} — 13 months "
            f"(223(b)(8)(B)(iii): 'beginning with the last month of the taxable year ... and ending on "
            f"the last day of the 12th month following such month'). If you are not an eligible "
            f"individual at ANY time in that window, {_money(at_risk)} goes into {year + 1} gross income "
            f"(the contributions 'which could not have been made but for subparagraph (A)') AND the tax "
            f"is 'increased by 10 percent of the amount of such increase' = "
            f"{_money(_cents(_HSA_TESTING_PERIOD_TAX_RATE * at_risk))}. Only death or disability under "
            f"223(b)(8)(B)(ii) excuses it — changing jobs, taking a spouse's non-HDHP plan, or enrolling "
            f"in Medicare does not. Contributing no more than {_money(redetermined_room)} keeps the full "
            f"deduction the months themselves earn, with ZERO testing-period exposure."
        )
    elif limit_basis == "monthly_proration":
        december = "you were not an eligible individual on December 1" if december_tier == "none" else (
            "December's own tier already gives the larger figure"
        )
        work_lines.append(
            f"No last-month-rule benefit: {december}, so line 3 is the chart's {_money(line3)} and there "
            f"is NO 223(b)(8) testing period to fail. (Pub 969 states the test as the greater of the "
            f"chart and 'The maximum annual HSA contribution based on your HDHP coverage (self-only or "
            f"family) on the first day of the last month of your tax year'.)"
        )
    else:
        work_lines.append(
            f"Eligible all 12 months with unchanged coverage, so the chart equals the annual limit and "
            f"line 3 = {_money(line3)}; 223(b)(8)(A) confers nothing extra and no testing period runs."
        )
    if medicare_start_month is not None:
        work_lines.append(
            f"MEDICARE: entitlement begins {_MONTHS[medicare_start_month - 1]} {year}, and 223(b)(7) sets "
            f"the monthly limitation to zero 'for the first month such individual is entitled to benefits "
            f"under title XVIII of the Social Security Act and for each month thereafter' — "
            f"{13 - medicare_start_month} month(s) zeroed, whatever plan is still in force. Pub 969 warns "
            f"'This rule applies to periods of RETROACTIVE Medicare coverage', so a backdated enrollment "
            f"turns already-made contributions into excess."
        )
    work_lines.append(
        f"line 4 Archer MSA contributions {_money(line4)} (223(b)(4)(A), from Form 8853 lines 1-2); "
        f"line 5 = 3 - 4 = {_money(line5)}."
    )
    if split_note:
        work_lines.append(split_note)
    if catch_up_on_line_7:
        work_lines.append(
            f"line 7 = ${hsa.catch_up_55:,} x {line7_months}/12 = {_money(line7)}. You are 55 or older "
            f"AND married with family coverage in the year, so the additional contribution amount rides "
            f"LINE 7, not line 3 (i8889 Line 3 note) — because 223(b)(5)(B) splits the family limit "
            f"'without regard to any additional contribution amount under paragraph (3)'."
            + (
                f" NOTE the consequence, read straight off the instructions and worth a second look "
                f"before filing: line 7's worksheet counts only the months you (or your spouse) had "
                f"FAMILY coverage and were an eligible individual, so the "
                f"{eligible_months - line7_months} SELF-ONLY eligible month(s) here contribute nothing "
                f"to the catch-up even though the line 3 chart would have carried "
                f"${hsa.catch_up_55:,}/12 for each of them had you been unmarried."
                if line7_months < eligible_months else ""
            )
        )
    elif catch_up_on_line_3:
        work_lines.append(
            f"line 7 = $0: the ${hsa.catch_up_55:,} age-55 additional contribution amount is already "
            f"inside each eligible month's line 3 chart entry (i8889: 'the additional contribution amount "
            f"is included for each month you are an eligible individual')."
        )
    work_lines.append(f"line 8 = 6 + 7 = {_money(line8)} — the full contribution limit from every source.")
    work_lines.append(
        f"line 9 EMPLOYER CONTRIBUTIONS {_money(line9)} + line 10 qualified HSA funding distributions "
        f"{_money(line10)} = line 11 {_money(line11)}; line 12 = 8 - 11 = {_money(line12)}; line 13 = "
        f"min(line 2 {_money(line2)}, line 12) = {_money(line13)} -> Schedule 1 (Form 1040), Part II, "
        f"line 13."
    )
    work_lines.append(
        "THE DOUBLE-COUNT TRAP: W-2 box 12 code W is NOT a deduction. i8889 line 9 defines employer "
        "contributions as 'including employee payroll contributions through a cafeteria plan', and line 2 "
        "says 'Payroll contributions through a salary reduction agreement elected by an employee (a "
        "cafeteria plan) are treated as employer contributions and are not included on line 2'. That "
        "whole amount is already excluded from box 1 wages under section 106(d) — 223(b)(4)(B) reduces "
        "the limit by it '(and such amount shall not be allowed as a deduction under subsection (a))'. "
        "So box 12 code W belongs on line 9, where it SUBTRACTS room; only DIRECT contributions (line 2, "
        "from 5498-SA box 2 less the code-W amount) reach Schedule 1. Deducting code W as well is the "
        "most common HSA filing error and it overstates the deduction by the whole payroll amount."
    )
    if dependent_note:
        work_lines.append(dependent_note)
    if excess_total:
        parts = []
        if excess_personal:
            parts.append(f"your own {_money(excess_personal)} (line 2 - line 13)")
        if excess_employer:
            parts.append(
                f"employer {_money(excess_employer)} (line 9 over the line 8 limitation reduced first by "
                f"the line 10 funding distribution, i.e. over {_money(employer_room)}) — 'If the excess "
                f"was not included in income on Form W-2, you must report it as \"Other income\"'"
            )
        work_lines.append(
            f"EXCESS CONTRIBUTIONS {_money(excess_total)}: " + "; ".join(parts) + f". IRC 4973(a) charges "
            f"{_HSA_EXCISE_RATE:%} of the excess ({_money(excise)}) for EACH taxable year it is still in "
            f"the account at year end, capped at 6% of the account's year-end value (5498-SA box 5 — this "
            f"op does not apply that cap, it has no account value). CURE: withdraw the excess plus the "
            f"income earned on it by the due date INCLUDING extensions, do not claim the deduction/"
            f"exclusion for it, and report the earnings as 'Other income'; miss that and there is still a "
            f"window 'no later than 6 months after the due date of your tax return, excluding "
            f"extensions' via an amended return marked 'Filed pursuant to section 301.9100-2'. Figure "
            f"the tax itself on Form 5329 Part VII."
        )
    fsa_line = (
        "OTHER-COVERAGE GATE (the silent disqualifier): 223(c)(1)(A)(ii) makes you ineligible for any "
        "month you are 'covered under any health plan (I) which is not a high deductible health plan, and "
        "(II) which provides coverage for any benefit which is covered under the high deductible health "
        "plan'. Rev. Rul. 2004-45: a general-purpose health FSA or HRA IS such a plan, and its Situation 1 "
        "holding adds 'This result is the same if the individual is covered by a health FSA or HRA "
        "sponsored by the employer of the individual's SPOUSE' — the trap, because nobody thinks of a "
        "spouse's FSA as their own coverage. Safe: LIMITED-PURPOSE (dental/vision/preventive only), "
        "POST-DEDUCTIBLE (nothing paid before the HDHP minimum annual deductible is met; where the two "
        "deductibles differ, 'contributions to the HSA are limited to the lower of the deductibles'), a "
        "SUSPENDED HRA elected before the coverage period, and a RETIREMENT HRA until you retire. Also "
        "disregarded by 223(c)(1)(B): permitted insurance, and coverage for accidents, disability, dental "
        "care, vision care, long-term care, or telehealth and other remote care. A general-purpose FSA's "
        "GRACE PERIOD counts against you unless its year-end balance was zero (223(c)(1)(B)(iii))."
    )
    if health_fsa in ("limited_purpose", "post_deductible"):
        fsa_line += (
            f" Caller declared health_fsa='{health_fsa}', which Rev. Rul. 2004-45 "
            f"{'Situation 2' if health_fsa == 'limited_purpose' else 'Situation 4'} holds does NOT "
            f"disqualify — the months above stand."
        )
    work_lines.append(fsa_line)
    work_lines.append(
        f"AGE-55 CATCH-UP: ${hsa.catch_up_55 or 0:,} is statutory under 223(b)(3)(B) ('2009 and "
        f"thereafter'), never inflation-adjusted, and is allowed to anyone who 'has attained age 55 "
        f"before the close of the taxable year'. It is PER PERSON, not per return, and it is not "
        f"allocable: Pub 969 — 'If both spouses meet the age requirement, the total contributions under "
        f"family coverage can't be more than ${hsa.family + 2 * (hsa.catch_up_55 or 0):,}. Each spouse "
        f"must make the additional contribution to their OWN HSA.' So a couple who both turn 55 needs TWO "
        f"HSAs to take two catch-ups; one joint account cannot exist at all ('You can't have a joint HSA')."
    )
    if fica_tier:
        work_lines.append(
            f"PAYROLL vs DIRECT: {fica_tier}. The {_money(line13)} on line 13 is a DIRECT contribution — "
            f"it saves income tax on Schedule 1 but it already paid FICA, so routing the same dollars "
            f"through the employer's cafeteria plan instead would have saved a further "
            f"{_money(fica_saving or Decimal(0))} of FICA (the income-tax saving is identical either way; "
            f"only the FICA differs, and payroll dollars land on line 9 rather than line 2). Employee "
            f"share only, federal only. On a JOINT return the 0.9% half of a 2.35% tier is provisional: "
            f"employers withhold it on wages over $200,000 with no filing-status test, while the Form "
            f"8959 TAX is measured on the couple's combined wages against $250,000 ($125,000 MFS), so "
            f"withholding above $200,000 that the joint threshold does not reach comes back as a credit "
            f"— for that filer the real saving is Medicare alone."
        )
    if line14a:
        work_lines.append(
            f"Part II DISTRIBUTIONS: line 14a {_money(line14a)} (1099-SA box 1, ALL HSAs) - line 14b "
            f"{_money(line14b)} rolled over or excess-plus-earnings withdrawn by the due date = line 14c "
            f"{_money(line14c)}; line 15 qualified medical expenses {_money(line15)}; line 16 = 14c - 15 "
            f"= {_money(line16)} TAXABLE -> Schedule 1 Part I line 8f. line 17b = "
            f"{_HSA_NONQUALIFIED_DISTRIBUTION_RATE:%} x {_money(line16 - excepted)} = {_money(line17b)} "
            f"-> Schedule 2 Part II line 17c (223(f)(4)(A) — 20%, raised from 10% by P.L. 111-148 "
            f"section 9004(a)). The only exceptions are distributions made after the account beneficiary "
            f"dies, becomes disabled, or turns 65; expenses incurred BEFORE the HSA was established are "
            f"never qualified, and an amount reimbursed by insurance or claimed on Schedule A cannot also "
            f"be line 15."
        )
    else:
        work_lines.append(
            "Part II DISTRIBUTIONS: nothing passed, so lines 14a-17b are zero. If any HSA paid out this "
            "year you MUST file Form 8889 — i8889: 'If you (or your spouse, if filing jointly) received "
            "HSA distributions ... you must file Form 8889 ... even if you have no taxable income or any "
            "other reason for filing' — so pass distributions_total (1099-SA box 1), "
            "distributions_rolled_over and qualified_medical_expenses even when the whole distribution "
            "was spent on qualified care."
        )
    if testing_period_failed and not last_month_rule_applied:
        work_lines.append(
            "TESTING-PERIOD FLAG WITH NOTHING AT RISK: testing_period_failed=True, but the last-month "
            "rule bought no extra room this year (line 3 is the monthly chart), so 223(b)(8)(B)(i) "
            "recaptures nothing — 'the aggregate amount of all contributions ... which could not have "
            "been made but for subparagraph (A)' is $0. Line 18 stays $0."
        )
    if line20:
        work_lines.append(
            f"Part III RECAPTURE: line 18 {_money(line18)} (last-month rule) + line 19 {_money(line19)} "
            f"(qualified HSA funding distribution) = line 20 {_money(line20)} into gross income on "
            f"Schedule 1 Part I line 8f, plus line 21 = 10% = {_money(line21)} on Schedule 2 Part II "
            f"line 17d. Include it in the year the failure happens, not the year of the contribution."
        )
    work_lines.append(
        "SCOPE — modelled here: Part I lines 1-13, Part II lines 14a-17b, Part III lines 18-21, the "
        "IRC 4973 excise on both kinds of excess, and the 223(b)(7) Medicare zeroing. NOT modelled, and "
        "not assumed away silently: (a) whether the plan IS an HDHP — the year's minimum annual "
        "deductible and maximum out-of-pocket limits are not in this op, so confirm the plan against that "
        "year's HSA revenue procedure; (b) Form 8853 itself, so line 4 is taken as given; (c) the "
        "instructions' Line 6 Step 1-4 REFIGURING for two spouses with separate HSAs whose family "
        "coverage did not run the whole year — with a mid-year tier change and spouse_has_separate_hsa "
        "this op splits line 5 rather than re-running the worksheet on the family months alone, so "
        "compute line 6 by hand there; (d) Form 5329 Part VII, including the absorption of a PRIOR year's "
        "excess into this year's unused limit and the 4973(a) cap at 6% of the account's year-end value; "
        "(e) deemed distributions (a section 4975 prohibited transaction, or pledging the account as "
        "security for a loan), which are taxable in full and generally carry the 20% tax; (f) the "
        "death-of-account-beneficiary path and the 'statement' + controlling Form 8889 aggregation when "
        "one person holds or inherits more than one HSA; (g) whether a given expense is a qualified "
        "medical expense; and (h) the second testing period a qualified HSA funding distribution starts "
        "(it runs from the MONTH of the transfer through the last day of the 12th month following, e.g. "
        "June 17 -> June 30 of the next year, and it is once per lifetime), so line 19 is driven by the "
        "caller's own flag."
    )
    if year not in _F8889_VERIFIED_REVISIONS:
        work_lines.append(
            f"YEAR NOTE: the {year} Form 8889 had not published when this op was written, so the line "
            f"numbering above is the {_F8889_NEWEST_VERIFIED} revision's (identical on every revision "
            f"read, {_F8889_VERIFIED_REVISIONS[0]}-{_F8889_NEWEST_VERIFIED}). Re-verify against the "
            f"{year} form before anything is filed."
        )

    inputs: dict[str, Any] = {
        "coverage": coverage,
        "year": year,
        "months_eligible": None if monthly_coverage is not None else (12 if months_eligible is None else months_eligible),
        "monthly_coverage": list(declared),
        "age_55_plus": age_55_plus,
        "married": married,
        "spouse_has_separate_hsa": spouse_has_separate_hsa,
        "personal_contributions": _money(line2),
        "employer_contributions": _money(line9),
        "qualified_hsa_funding_distribution": _money(line10),
        "archer_msa_contributions": _money(line4),
        "medicare_start_month": medicare_start_month,
        "health_fsa": health_fsa,
        "claimed_as_dependent_by_another": claimed_as_dependent_by_another,
        "testing_period_failed": testing_period_failed,
        "funding_distribution_testing_period_failed": funding_distribution_testing_period_failed,
        "distributions_total": _money(line14a),
        "distributions_rolled_over": _money(line14b),
        "qualified_medical_expenses": _money(line15),
        "distributions_excepted_from_20_percent": _money(excepted),
        "wages": None if wages is None else _money(_to_decimal(wages, "wages")),
    }
    citations = [
        _IRC_223_LIMIT_CITATION, _IRC_223_B8_CITATION, _IRC_223_C1_CITATION, _IRC_223_F4_CITATION,
        _IRC_4973_HSA_CITATION, _REV_RUL_2004_45_CITATION, _f8889_citation(year), _I8889_CITATION,
        _PUB969_CITATION, hsa.citation,
    ]
    input_assumptions = [months_note] if months_note else []
    return HsaDeductionResult(
        input_assumptions=input_assumptions,
        deduction=irs_round(line13),
        deduction_exact=line13,
        annual_limit=irs_round(line3),
        annual_limit_exact=line3,
        prorated_limit=chart_limit,
        limit_basis=limit_basis,
        monthly_limits=[_money(v) for v in per_month],
        months_eligible=eligible_months,
        last_month_rule_applied=last_month_rule_applied,
        testing_period=testing_period,
        at_risk_if_testing_period_fails=irs_round(at_risk),
        catch_up_amount=irs_round(catch_up_allowed),
        catch_up_on_line="7" if catch_up_on_line_7 else ("3" if catch_up_on_line_3 else "none"),
        employer_contributions_excluded=irs_round(line9),
        excess_personal_contributions=irs_round(excess_personal),
        excess_employer_contributions=irs_round(excess_employer),
        excise_per_year=irs_round(excise),
        taxable_distributions=irs_round(line16),
        distributions_additional_tax=irs_round(line17b),
        recapture_income=irs_round(line20),
        recapture_additional_tax=irs_round(line21),
        fica_saving_forgone=fica_saving,
        fica_tier=fica_tier,
        form_8889_lines=lines,
        inputs=inputs,
        work="\n".join(work_lines),
        citation=hsa.citation,
        citations=citations,
    )


# ---------------------------------------------------------------------------
# Presence-day counting (I-94 history -> Substantial Presence Test inputs)
# ---------------------------------------------------------------------------

_DateLike = date | datetime | str


def _as_date(value: _DateLike, where: str) -> date:
    """Normalize a period endpoint to datetime.date, with prescriptive errors."""
    if isinstance(value, datetime):
        # A timestamped arrival/departure still counts as presence on that day.
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"{where}: cannot parse date string {value!r} — use ISO format 'YYYY-MM-DD' "
                f"(e.g. '2023-06-15') or pass a datetime.date"
            ) from None
    raise TypeError(
        f"{where}: dates must be datetime.date, datetime.datetime or ISO 'YYYY-MM-DD' strings, "
        f"got {type(value).__name__}"
    )


def _merged_day_intervals(periods: list[tuple[_DateLike, _DateLike]]) -> list[tuple[int, int]]:
    """Validate and merge presence periods into disjoint inclusive ordinal-day intervals."""
    intervals: list[tuple[int, int]] = []
    for i, period in enumerate(periods):
        try:
            start_raw, end_raw = period
        except (TypeError, ValueError):
            raise ValueError(
                f"presence period {i} must be a (start_date, end_date) pair, got {period!r} — "
                f"each I-94 row is one (arrival, departure) range"
            ) from None
        start = _as_date(start_raw, f"presence period {i} start")
        end = _as_date(end_raw, f"presence period {i} end")
        if start > end:
            raise ValueError(
                f"presence period {i}: start {start.isoformat()} is after end {end.isoformat()} — "
                f"swap them (each period is arrival date first, departure date second)"
            )
        intervals.append((start.toordinal(), end.toordinal()))
    intervals.sort()
    merged: list[tuple[int, int]] = []
    for start_ord, end_ord in intervals:
        # Merge overlapping AND adjacent intervals; for day counting the
        # union is identical and duplicates from re-submitted I-94 rows
        # collapse into one stay.
        if merged and start_ord <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_ord))
        else:
            merged.append((start_ord, end_ord))
    return merged


def presence_days(periods: list[tuple[_DateLike, _DateLike]]) -> int:
    """Count distinct days physically present in the US from I-94-style ranges.

    Rules (Pub 519, Substantial Presence Test day counting):

    * endpoints are INCLUSIVE — any partial day in the US counts as a full
      day, so both the arrival day and the departure day count;
    * a same-day arrival and departure counts as 1 day;
    * overlapping or duplicate ranges are merged — each calendar day counts
      at most once.

    Accepts ``datetime.date`` objects, datetimes (time of day ignored), or
    ISO 'YYYY-MM-DD' strings. Exempt-individual rules and the SPT formula
    itself live in residency.py; this is the raw day count.

    Returns a bare int by design (a counting primitive, not a tax result):
    the MCP-layer ``calc(op='presence_days')`` wrapper (M4) adds the
    inputs/work/citation envelope required by dev plan section 8, and
    residency.py results carry the full day-count work trail.
    """
    return sum(end_ord - start_ord + 1 for start_ord, end_ord in _merged_day_intervals(periods))


def presence_days_by_year(periods: list[tuple[_DateLike, _DateLike]]) -> dict[int, int]:
    """Split :func:`presence_days` by calendar year: ``{year: days present}``.

    The Substantial Presence Test weighs the current year, 1st preceding
    year, and 2nd preceding year differently, so the per-year split is the
    shape residency.py consumes. Years with zero presence are omitted.
    Same merging/inclusive-endpoint semantics as :func:`presence_days`;
    the per-year values always sum to the total. Returns a bare dict by
    design — see the :func:`presence_days` note on the MCP-layer wrapper
    adding the work trail.
    """
    days: dict[int, int] = {}
    for start_ord, end_ord in _merged_day_intervals(periods):
        start, end = date.fromordinal(start_ord), date.fromordinal(end_ord)
        for year in range(start.year, end.year + 1):
            year_start = max(start_ord, date(year, 1, 1).toordinal())
            year_end = min(end_ord, date(year, 12, 31).toordinal())
            days[year] = days.get(year, 0) + (year_end - year_start + 1)
    return days


# ---------------------------------------------------------------------------
# Equity compensation and the capital-loss limitation (Phase I, I3): IRC 421 /
# 422 / 423 (the ESPP disposition, and the 1099-B basis correction brokers get
# systematically wrong) and IRC 1211(b) / 1212(b) (the $3,000 cap and the
# CHARACTER-PRESERVING carryover Schedule D's own worksheet computes)
# ---------------------------------------------------------------------------

# Everything in this section is YEAR-INVARIANT law, so — following the
# P-005/P-006 discipline that only FIGURES belong in a year pack — the
# authorities live here beside the ops. Neither op reads a knowledge pack: the
# $3,000/$1,500 limitation is statutory and NOT indexed (IRC 1211(b), unchanged
# since P.L. 99-514 rewrote the subsection for tax years beginning after
# December 31, 1986), and IRC 423(c) carries no dollar figures at all.
#
# The Capital Loss Carryover Worksheet's line numbering (lines 1-13, "Capital
# Loss Carryover Worksheet-Lines 6 and 14") was read off four consecutive
# Schedule D instruction revisions: i1040sd--2022.pdf, i1040sd--2023.pdf,
# i1040sd--2024.pdf and i1040sd--2025.pdf, all fetched 2026-08-26. Lines 1-13 are
# IDENTICAL in all four. Pre-2022 revisions were NOT read, so 2022 is the floor.
#
# MIND THE DIRECTION: the worksheet printed in year Y's instructions carries
# year Y-1's loss INTO year Y. This op runs the worksheet for the year the loss
# arose, so a call for year Y reproduces the worksheet printed in the Y+1
# instructions — read for Y = 2021..2024. For Y = 2025 the 2026 instructions had
# not published when this was written; the four revisions read agree line for
# line, so the structure is quoted from them, and `_schedule_d_citation` says so.
#
# ONE thing DID move inside that window and it is not the worksheet: Schedule D
# line 21's destination. The 2022, 2023 and 2024 faces all print "enter here and
# on Form 1040, 1040-SR, or 1040-NR, line 7"; the 2025 face prints "line 7a",
# because TY2025 split Form 1040 line 7 into 7a/7b. All four faces were read
# (f1040sd--2022/2023/2024/2025.pdf). Form 1040 line 15 is still "Subtract line
# 14 from line 11b. If zero or less, enter -0-. This is your taxable income" on
# the 2025 face, so the worksheet's line 1 reference is unchanged.
_CAPITAL_LOSS_VERIFIED_REVISIONS: tuple[int, ...] = tuple(range(2022, 2026))
_CAPITAL_LOSS_NEWEST_VERIFIED = max(_CAPITAL_LOSS_VERIFIED_REVISIONS)

# IRC 1211(b)(1): "$3,000 ($1,500 in the case of a married individual filing a
# separate return)". Statutory, not indexed — hence a module constant, not a
# year-pack figure.
_CAPITAL_LOSS_CAP = 3_000
_CAPITAL_LOSS_CAP_MFS = 1_500

# IRC 423(b)(6): the plan's option price may be no less than the LESSER of 85%
# of the grant-date FMV and 85% of the exercise-date FMV.
_ESPP_STATUTORY_MIN_PRICE_RATE = Decimal("0.85")
# Plans price to the cent, and 85% of an odd share price rarely lands on one, so
# both 423(b)(6) tests allow a one-cent rounding slack before they refuse.
_ESPP_PRICE_TOLERANCE = Decimal("0.01")

_IRC_423_CITATION = Citation(
    source=(
        "IRC 423 (26 U.S.C. 423), 'Employee stock purchase plans': (a) section 421(a) applies to a "
        "share transferred under an ESPP if '(1) no disposition of such share is made by him within 2 "
        "years after the date of the granting of the option nor within 1 year after the transfer of "
        "such share to him; and (2) at all times during the period beginning with the date of the "
        "granting of the option and ending on the day 3 months before the date of such exercise, he is "
        "an employee of the corporation granting such option' or a parent/subsidiary. (b)(6) the plan's "
        "option price must be 'not less than the lesser of- (A) an amount equal to 85 percent of the "
        "fair market value of the stock at the time such option is granted, or (B) an amount which "
        "under the terms of the option may not be less than 85 percent of the fair market value of the "
        "stock at the time such option is exercised'. (c) 'Special rule where option price is between "
        "85 percent and 100 percent of value of stock': on a disposition 'which meets the holding "
        "period requirements of subsection (a)', there is included as COMPENSATION 'and not as gain "
        "upon the sale or exchange of a capital asset' an amount equal to the LESSER of '(1) the "
        "excess of the fair market value of the share at the time of such disposition or death over "
        "the amount paid for the share under the option, or (2) the excess of the fair market value of "
        "the share at the time the option was granted over the option price.' Then, in the same "
        "subsection: 'If the option price is not fixed or determinable at the time the option is "
        "granted, then for purposes of this subsection, the option price shall be determined as if the "
        "option were exercised at such time' (the LOOKBACK rule, which is what Form 3922 box 8 "
        "reports); 'the basis of the share in his hands at the time of such disposition shall be "
        "increased by an amount equal to the amount so includible in his gross income'; and 'No amount "
        "shall be required to be deducted and withheld under chapter 24 with respect to any amount "
        "treated as compensation under this subsection.'"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section423&num=0&edition=prelim",
)

_IRC_421_CITATION = Citation(
    source=(
        "IRC 421 (26 U.S.C. 421), 'General rules': (a) where the requirements of section 422(a) or "
        "423(a) are met, '(1) no income shall result at the time of the transfer of such share to the "
        "individual upon his exercise of the option'. (b) 'Effect of disqualifying disposition': where "
        "the transfer 'would otherwise meet the requirements of section 422(a) or 423(a) except that "
        "there is a failure to meet any of the holding period requirements of section 422(a)(1) or "
        "423(a)(1), then any increase in the income of such individual ... for the taxable year in "
        "which such exercise occurred attributable to such disposition, shall be treated as an "
        "increase in income ... in the taxable year of such individual ... in which such disposition "
        "occurred. No amount shall be required to be deducted and withheld under chapter 24 with "
        "respect to any increase in income attributable to a disposition described in the preceding "
        "sentence.' (d) a disposition made pursuant to a certificate of divestiture under section "
        "1043(b)(2) 'shall be treated as meeting the requirements of section 422(a)(1) or 423(a)(1)'"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section421&num=0&edition=prelim",
)

_IRC_422_CITATION = Citation(
    source=(
        "IRC 422 (26 U.S.C. 422), 'Incentive stock options': (a)(1) the same two-part holding period "
        "as an ESPP — 'no disposition of such share is made by him within 2 years from the date of the "
        "granting of the option nor within 1 year after the transfer of such share to him'; (b)(4) 'the "
        "option price is not less than the fair market value of the stock at the time such option is "
        "granted' (so an ISO has NO built-in discount, which is why the ISO and ESPP dispositions do "
        "not share a formula); (c)(2) on a disqualifying disposition that is a sale or exchange 'with "
        "respect to which a loss (if sustained) would be recognized', the compensation income 'shall "
        "not exceed the excess (if any) of the amount realized on such sale or exchange over the "
        "adjusted basis of such share' — the ISO-only cap that has NO section 423 counterpart"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section422&num=0&edition=prelim",
)

_IRC_83_E1_CITATION = Citation(
    source=(
        "IRC 83(e) (26 U.S.C. 83), 'Applicability of section': 'This section shall not apply to- (1) a "
        "transaction to which section 421 applies'. Section 421(a) is what applies to a share "
        "transferred under a qualifying section 423 exercise, so section 83 — and with it the section "
        "83(b) election — never reaches an ESPP purchase"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section83&num=0&edition=prelim",
)

_IRC_3121_A22_CITATION = Citation(
    source=(
        "IRC 3121(a)(22) (26 U.S.C. 3121(a)): the term 'wages' for FICA does not include "
        "'remuneration on account of- (A) a transfer of a share of stock to any individual pursuant to "
        "an exercise of an incentive stock option (as defined in section 422(b)) or under an employee "
        "stock purchase plan (as defined in section 423(b)), or (B) any disposition by the individual "
        "of such stock'"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section3121&num=0&edition=prelim",
)

_PUB525_ESPP_CITATION = Citation(
    source=(
        "Publication 525 (2025), 'Statutory Stock Options' -> 'Employee stock purchase plan'. Holding "
        "period requirement: 'You satisfy the holding period requirement if you don't sell the stock "
        "until the end of the later of the 1-year period after the stock was transferred to you or the "
        "2-year period after the option was granted', and 'Your holding period for the property you "
        "acquire when you exercise an option begins on the day after you exercise the option.' "
        "SATISFIED, 'Option granted at a discount': 'If, at the time the option was granted, the "
        "option price per share was less than 100% (but not less than 85%) of the FMV of the share, "
        "and you dispose of the share after meeting the holding period requirement ... you must "
        "include in your income as compensation the lesser of: The excess of the FMV of the share at "
        "the time the option was granted over the option price, or The excess of the FMV of the share "
        "at the time of the disposition or death over the amount paid for the share under the option.' "
        "'For this purpose, if the option price wasn't fixed or determinable at the time the option was "
        "granted, the option price is figured as if the option had been exercised at the time it was "
        "granted.' 'Any excess gain is capital gain. If you have a loss from the sale, it's a capital "
        "loss, and you don't have any ordinary income.' NOT SATISFIED: 'your ordinary income is the "
        "amount by which the stock's FMV when you exercised the option exceeded the option price. This "
        "ordinary income isn't limited to your gain from the sale of the stock. Increase your basis in "
        "the stock by the amount of this ordinary income. The difference between your increased basis "
        "and the selling price of the stock is a capital gain or loss.' Worked examples reproduced by "
        "this op to the dollar: Example 10 (grant $20 option price when the stock was worth $22, "
        "exercised 18 months later at $23, sold 14 months after that at $30, 100 shares -> $200 wages "
        "and $800 capital gain) and Example 11 (identical facts but sold 6 months after exercise -> "
        "$300 wages and $700 capital gain). Also, Example 9: 'Adrian's holding period for all 12 shares "
        "begins the day after the option is exercised, even though the money used to purchase the "
        "shares was deducted from Adrian's pay on 48 separate days' and 'The timing and amount of pay "
        "period deductions don't affect your basis.' Reporting: 'Your employer or former employer "
        "should report the ordinary income to you as wages in box 1 of Form W-2 ... If your employer or "
        "former employer doesn't provide you with a Form W-2, or if the Form W-2 doesn't include the "
        "ordinary income in box 1, you must report the ordinary income as wages on Schedule 1 (Form "
        "1040), line 8k, for the year of the sale or other disposition of the stock.' And the caution "
        "this op exists to act on: 'It's your responsibility to make any appropriate adjustments to the "
        "basis information reported on Form 1099-B by completing Form 8949.'"
    ),
    url="https://www.irs.gov/pub/irs-pdf/p525.pdf",
)

_I8949_BASIS_CITATION = Citation(
    source=(
        "Instructions for Form 8949 (2025). 'Column (e)-Cost or Other Basis': 'For compensatory "
        "options granted after 2013, the basis information reported to you on Form 1099-B or Form "
        "1099-DA (or substitute statement) won't reflect any amount you included in income upon grant "
        "or exercise of the option. Increase your basis by any amount you included in income upon "
        "grant or exercise of the option. For compensatory options granted before 2014, any basis "
        "information reported to you ... may or may not reflect any amount you included in income'. "
        "'How To Complete Form 8949, Columns (f) and (g)' table, code B row: IF 'You received a Form "
        "1099-B or Form 1099-DA (or substitute statement) and the basis shown in box 1e on Form 1099-B "
        "or box 1g on Form 1099-DA is incorrect' THEN enter code 'B' in column (f), AND '- If this "
        "transaction is reported on Part I with box B or box H checked at the top or if this "
        "transaction is reported on Part II with box E or box K checked at the top, enter the correct "
        "basis in column (e), and enter -0- in column (g). - If this transaction is reported on Part I "
        "with box A or box G checked at the top or if this transaction is reported on Part II with box "
        "D or box J checked at the top, enter the basis shown on Form 1099-B or Form 1099-DA (or "
        "substitute statement) in column (e), even though that basis is incorrect. Correct the error by "
        "entering an adjustment in column (g).' Code O row: 'You have an adjustment not explained "
        "earlier in this column' -> 'Enter the appropriate adjustment amount in column (g).' "
        "'Worksheet for Basis Adjustments in Column (g)': line 1 the basis shown on the 1099-B, line 2 "
        "'the correct cost or other basis', line 3 'If line 2 is larger than line 1, subtract line 1 "
        "from line 2. Enter the result here and in column (g) as a negative number (in parentheses)', "
        "line 4 the mirror positive. 'Column (h)-Gain (or Loss)': 'First, subtract the cost or other "
        "basis in column (e) from the proceeds (sales price) in column (d). Then take into account any "
        "adjustments in column (g).'"
    ),
    url="https://www.irs.gov/pub/irs-pdf/i8949.pdf",
)

_F8949_CITATION = Citation(
    source=(
        "Form 8949 (2025), 'Sales and Other Dispositions of Capital Assets'. Part I box legend: '(A) "
        "Short-term transactions reported on Form(s) 1099-B showing basis was reported to the IRS'; "
        "'(B) Short-term transactions reported on Form(s) 1099-B showing basis was not reported to the "
        "IRS'; '(C) Short-term transactions, other than digital asset transactions, not reported to "
        "you on Form 1099-B or Form 1099-DA'. Part II: the same three as '(D)', '(E)', '(F)' for "
        "long-term. Columns: (a) Description of property '(Example: 100 sh. XYZ Co.)', (b) Date "
        "acquired, (c) Date sold or disposed of, (d) Proceeds (sales price), (e) Cost or other basis, "
        "(f) Code(s) from instructions, (g) Amount of adjustment, (h) 'Subtract column (e) from column "
        "(d) and combine the result with column (g)'. The face's own Note under Part I: 'If you checked "
        "Box A or Box G above but the basis reported to the IRS was incorrect, enter in column (e) the "
        "basis as reported to the IRS, and [enter the correction in column (g)]'. Line 2 totals flow to "
        "'Schedule D, line 1b (if Box A or Box G above is checked), line 2 (if Box B or Box H above is "
        "checked), or line 3 (if Box C or Box I above is checked)'"
    ),
    url="https://www.irs.gov/pub/irs-pdf/f8949.pdf",
)

_F3922_CITATION = Citation(
    source=(
        "Form 3922 (Rev. April 2025), 'Transfer of Stock Acquired Through an Employee Stock Purchase "
        "Plan Under Section 423(c)'. Boxes: 1 Date option granted; 2 Date option exercised; 3 Fair "
        "market value per share on grant date; 4 Fair market value per share on exercise date; 5 "
        "Exercise price paid per share; 6 No. of shares transferred; 7 Date legal title transferred; 8 "
        "'Exercise price per share determined as if the option was exercised on the date shown in box "
        "1'. Instructions for Employee: 'You have received this form because (1) your employer (or its "
        "transfer agent) has recorded a first transfer of legal title of stock you acquired pursuant to "
        "your exercise of an option granted under an employee stock purchase plan, and (2) the exercise "
        "price was less than 100% of the value of the stock on the date shown in box 1 or was not fixed "
        "or determinable on that date.' 'No income is recognized when you exercise an option under an "
        "employee stock purchase plan.' Box 8: 'If the exercise price per share was not fixed or "
        "determinable on the date entered in box 1, box 8 shows the exercise price per share determined "
        "as if the option was exercised on the date in box 1. If the exercise price per share was fixed "
        "or determinable on the date shown in box 1, then box 8 will be blank.'"
    ),
    url="https://www.irs.gov/pub/irs-pdf/f3922.pdf",
)

_F3921_CITATION = Citation(
    source=(
        "Form 3921 (Rev. April 2025), 'Exercise of an Incentive Stock Option Under Section 422(b)'. "
        "Boxes: 1 Date option granted; 2 Date option exercised; 3 Exercise price per share; 4 Fair "
        "market value per share on exercise date; 5 No. of shares transferred; 6 'If other than "
        "TRANSFEROR, name, address, and TIN of corporation whose stock is being transferred'. "
        "Instructions for Employee: 'When you exercise an ISO, you may have to include in alternative "
        "minimum taxable income a portion of the fair market value of the stock acquired through the "
        "exercise of the option. For more information, see Form 6251'"
    ),
    url="https://www.irs.gov/pub/irs-pdf/f3921.pdf",
)

_IRC_1211_B_CITATION = Citation(
    source=(
        "IRC 1211(b) (26 U.S.C. 1211), 'Limitation on capital losses' - 'Other taxpayers': 'In the "
        "case of a taxpayer other than a corporation, losses from sales or exchanges of capital assets "
        "shall be allowed only to the extent of the gains from such sales or exchanges, plus (if such "
        "losses exceed such gains) the lower of- (1) $3,000 ($1,500 in the case of a married individual "
        "filing a separate return), or (2) the excess of such losses over such gains.' The present text "
        "was substituted by P.L. 99-514 title III section 301(b)(10), applicable to taxable years "
        "beginning after December 31, 1986; the figures are STATUTORY and carry no inflation "
        "adjustment, which is why they are not in a year pack"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section1211&num=0&edition=prelim",
)

_IRC_1212_B_CITATION = Citation(
    source=(
        "IRC 1212(b) (26 U.S.C. 1212), 'Capital loss carrybacks and carryovers' - 'Other taxpayers': "
        "(1) 'If a taxpayer other than a corporation has a net capital loss for any taxable year- (A) "
        "the excess of the net short-term capital loss over the net long-term capital gain for such "
        "year shall be a short-term capital loss in the succeeding taxable year, and (B) the excess of "
        "the net long-term capital loss over the net short-term capital gain for such year shall be a "
        "long-term capital loss in the succeeding taxable year' — the statute that PRESERVES CHARACTER. "
        "(2)(A) 'For purposes of determining the excess referred to in subparagraph (A) or (B) of "
        "paragraph (1), there shall be treated as a short-term capital gain in the taxable year an "
        "amount equal to the lesser of- (i) the amount allowed for the taxable year under paragraph (1) "
        "or (2) of section 1211(b), or (ii) the adjusted taxable income for such taxable year.' (2)(B) "
        "'the term \"adjusted taxable income\" means taxable income increased by the sum of- (i) the "
        "amount allowed for the taxable year under paragraph (1) or (2) of section 1211(b), and (ii) "
        "the deduction allowed for such year under section 151 or any deduction in lieu thereof. For "
        "purposes of the preceding sentence, any excess of the deductions allowed for the taxable year "
        "over the gross income for such year shall be taken into account as negative taxable income.' "
        "This (2)(A) lesser-of is what the Capital Loss Carryover Worksheet's lines 1-4 compute, and it "
        "is why a low-taxable-income year consumes LESS of the loss than it deducts"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section1212&num=0&edition=prelim",
)

_IRC_1222_CITATION = Citation(
    source=(
        "IRC 1222 (26 U.S.C. 1222), 'Other terms relating to capital gains and losses': (6) 'net "
        "short-term capital loss' is 'the excess of short-term capital losses for the taxable year over "
        "the short-term capital gains for such year'; (8) 'net long-term capital loss' the long-term "
        "mirror; (10) 'net capital loss' is 'the excess of the losses from sales or exchanges of "
        "capital assets over the sum allowed under section 1211'; (11) 'net capital gain' is 'the "
        "excess of the net long-term capital gain for the taxable year over the net short-term capital "
        "loss for such year'. Short and long are netted SEPARATELY first (Schedule D lines 7 and 15) "
        "and only then against each other (line 16)"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section1222&num=0&edition=prelim",
)

_IRC_151_D5_CITATION = Citation(
    source=(
        "IRC 151(d)(5) (26 U.S.C. 151), 'Special rules for taxable years beginning after 2017': 'In the "
        "case of a taxable year beginning after December 31, 2017- (A) Exemption amount. The term "
        "\"exemption amount\" means zero.' This is why the Capital Loss Carryover Worksheet's line 1 "
        "takes Form 1040 line 15 (taxable income) with NO add-back for the section 151 deduction that "
        "IRC 1212(b)(2)(B)(ii) names. (C), added by P.L. 119-21, allows 'a deduction in an amount equal "
        "to $6,000 for each qualified individual' for taxable years beginning before January 1, 2029 — "
        "a deduction allowed UNDER SECTION 151 that the printed worksheet does not add back"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section151&num=0&edition=prelim",
)

_PUB550_CARRYOVER_CITATION = Citation(
    source=(
        "Publication 550 (2025), chapter 4, 'Capital Losses'. Limit on deduction: 'Your allowable "
        "capital loss deduction, figured on Schedule D (Form 1040), is the lesser of: $3,000 ($1,500 if "
        "you are married and file a separate return), or Your total net loss as shown on line 16 of "
        "Schedule D (Form 1040).' Capital loss carryover: 'you can carry over the unused part to the "
        "next year and treat it as if you had incurred it in that next year. If part of the loss is "
        "still unused, you can carry it over to later years until it is completely used up.' 'When you "
        "figure the amount of any capital loss carryover to the next year, you must take the current "
        "year's allowable deduction into account, WHETHER OR NOT you claimed it and whether or not you "
        "filed a return for the current year.' 'When you carry over a loss, it remains long-term or "
        "short-term. A long-term capital loss you carry over to the next tax year will reduce that "
        "year's long-term capital gains before it reduces that year's short-term capital gains.' "
        "Figuring your carryover: 'The amount of your capital loss carryover is the amount of your "
        "total net loss that is more than the lesser of: 1. Your allowable capital loss deduction for "
        "the year, or 2. Your taxable income increased by your allowable capital loss deduction for the "
        "year.' 'If your deductions are more than your gross income for the tax year, use your negative "
        "taxable income in figuring the amount in (2) above.' 'Use short-term losses first. When you "
        "figure your capital loss carryover, use your short-term capital losses first, even if you "
        "incurred them after a long-term capital loss.' Joint and separate returns: 'if you and your "
        "spouse once filed a joint return and are now filing separate returns, any capital loss "
        "carryover from the joint return can be deducted only on the return of the spouse who actually "
        "had the loss.' Decedent's capital loss: it 'can be deducted only on the final income tax "
        "return filed for the decedent. ... The decedent's estate cannot deduct any of the loss or "
        "carry it over to following years.' Worksheet 4-1 is the same Capital Loss Carryover Worksheet "
        "printed in the Schedule D instructions"
    ),
    url="https://www.irs.gov/pub/irs-pdf/p550.pdf",
)


def _capital_loss_1040_line(year: int) -> str:
    """Which Form 1040 line Schedule D line 21 lands on for ``year``.

    Read off the faces, not remembered: f1040sd--2023.pdf and f1040sd--2024.pdf
    both print "enter here and on Form 1040, 1040-SR, or 1040-NR, line 7"; the
    2025 face prints "line 7a", because TY2025 split line 7 into 7a/7b.
    """
    return "7a" if year >= 2025 else "7"


def _schedule_d_citation(year: int) -> Citation:
    """Cite the year's own Schedule D + the FOLLOWING year's Capital Loss Carryover
    Worksheet (the worksheet that carries year Y's loss into Y+1 is printed in the
    Y+1 instructions). A year whose forms have not published yet cites the newest
    revision actually READ and says so."""
    body = (
        f"Schedule D (Form 1040) line 7 'Net short-term capital gain or (loss). Combine lines 1a "
        f"through 6 in column (h)', line 15 'Net long-term capital gain or (loss). Combine lines 8a "
        f"through 14', line 16 'Combine lines 7 and 15', line 21 'If line 16 is a loss, enter here and "
        f"on Form 1040, 1040-SR, or 1040-NR, line {_capital_loss_1040_line(year)}, the smaller of: The "
        f"loss on line 16; or ($3,000), or if married filing separately, ($1,500)' with the printed "
        f"Note 'When figuring which amount is smaller, treat both amounts as positive numbers'; line 6 "
        f"'Short-term capital loss carryover. Enter the amount, if any, from line 8 of your Capital "
        f"Loss Carryover Worksheet in the instructions' and line 14 the long-term mirror from "
        f"worksheet line 13. Instructions for Schedule D (Form 1040), 'Capital Loss Carryover "
        f"Worksheet-Lines 6 and 14': line 1 the prior year's Form 1040 line 15 ('If the amount would "
        f"have been a loss if you could enter a negative number on that line, enclose the amount in "
        f"parentheses'), line 2 the prior Schedule D line 21 loss as a positive amount, line 3 "
        f"'Combine lines 1 and 2. If zero or less, enter -0-', line 4 'Enter the smaller of line 2 or "
        f"line 3', line 5 the prior Schedule D line 7 loss as a positive amount, line 6 'Enter any gain "
        f"from your ... Schedule D, line 15. If a loss, enter -0-', line 7 'Add lines 4 and 6', line 8 "
        f"the SHORT-TERM carryover 'Subtract line 7 from line 5. If zero or less, enter -0-', line 9 "
        f"the prior Schedule D line 15 loss as a positive amount, line 10 'Enter any gain from your ... "
        f"Schedule D, line 7. If a loss, enter -0-', line 11 'Subtract line 5 from line 4. If zero or "
        f"less, enter -0-', line 12 'Add lines 10 and 11', line 13 the LONG-TERM carryover 'Subtract "
        f"line 12 from line 9. If zero or less, enter -0-'"
    )
    if year in _CAPITAL_LOSS_VERIFIED_REVISIONS:
        worksheet_note = (
            f"The face above was read off the {year} blank. The worksheet that carries a {year} loss "
            f"forward is the one printed in the {year + 1} instructions"
            + (
                f", read directly (i1040sd--{year + 1}.pdf)."
                if year + 1 in _CAPITAL_LOSS_VERIFIED_REVISIONS else
                f", which had not published when this op was written — its lines 1-13 are quoted from the "
                f"four consecutive revisions that were read (i1040sd--"
                f"{_CAPITAL_LOSS_VERIFIED_REVISIONS[0]}.pdf .. i1040sd--{_CAPITAL_LOSS_NEWEST_VERIFIED}.pdf), "
                f"which agree line for line. RE-VERIFY against the {year + 1} instructions before filing."
            )
        )
        return Citation(source=f"Schedule D (Form 1040) ({year}): {body}. {worksheet_note}",
                        url=f"https://www.irs.gov/pub/irs-prior/f1040sd--{year}.pdf")
    return Citation(
        source=(
            f"Schedule D (Form 1040) ({_CAPITAL_LOSS_NEWEST_VERIFIED}) — quoted for {year} because the "
            f"{year} revision had not published when this op was written. {body}. Worksheet lines 1-13 "
            f"are identical on every revision actually read ({_CAPITAL_LOSS_VERIFIED_REVISIONS[0]}-"
            f"{_CAPITAL_LOSS_NEWEST_VERIFIED}), but line 21's DESTINATION did move inside that window "
            f"(line 7 through 2024, line 7a from 2025) — RE-VERIFY against the {year} form before "
            f"anything is filed"
        ),
        url="https://www.irs.gov/pub/irs-pdf/f1040sd.pdf",
    )


def _add_years(start: date, years: int) -> date:
    """The same calendar day ``years`` later; a February 29 start lands on
    February 28 when the target year is not a leap year."""
    try:
        return start.replace(year=start.year + years)
    except ValueError:
        return date(start.year + years, 2, 28)


class EsppDispositionResult(BaseModel):
    """Result of :func:`espp_disposition`: the IRC 423 split between compensation
    and capital gain, plus the Form 8949 row that actually files it."""

    model_config = ConfigDict(extra="forbid")

    disposition_type: Literal["qualifying", "disqualifying"] = Field(
        description="IRC 423(a)(1): 'qualifying' only when the sale is MORE than 2 years after grant AND more than 1 year after purchase."
    )
    ordinary_income: int = Field(
        description="Compensation income -> W-2 box 1 (Form 1040 line 1a); Schedule 1 line 8k 'Stock options' if the employer left it off."
    )
    ordinary_income_per_share: Decimal = Field(description="The per-share compensation before rounding — this is where the cents live.")
    capital_gain_or_loss: int = Field(description="Form 8949 column (h) = column (d) - column (e) + column (g).")
    capital_gain_character: Literal["short_term", "long_term"] = Field(
        description="Measured from the PURCHASE date (Pub 525: the holding period 'begins on the day after you exercise the option')."
    )
    proceeds: int = Field(description="Form 8949 column (d): shares x sale price, less selling expenses when they were passed.")
    amount_paid: int = Field(description="What actually left your pocket: shares x Form 3922 box 5.")
    corrected_basis: int = Field(description="IRC 423(c) last sentence / Pub 525: amount paid PLUS the ordinary income recognised.")
    corrected_basis_per_share: Decimal = Field(description="The per-share adjusted basis, cents intact.")
    broker_reported_basis: int = Field(description="Form 1099-B box 1e as the broker reported it (defaulted to the amount paid when not supplied).")
    basis_adjustment: int = Field(
        description="corrected_basis - broker_reported_basis. POSITIVE means the broker UNDERSTATED your basis and you are about to be taxed twice."
    )
    double_taxed_if_uncorrected: int = Field(
        description="The dollars that would be taxed as compensation AND again as capital gain if the 1099-B is filed unadjusted — the whole point of the op."
    )
    form_8949: dict[str, str] = Field(description="The Form 8949 row: part, box, and columns (a)-(h) as they should be typed.")
    holding_periods: dict[str, str] = Field(description="Both IRC 423(a)(1) tests and the capital-gain holding period, each with its date and verdict.")
    discount_percentage: Decimal = Field(description="1 - (price paid / the lower of the two FMVs): the discount the plan actually delivered.")
    lookback_applied: bool = Field(description="True when Form 3922 box 8 was supplied, i.e. the option price was not fixed or determinable at grant.")
    grant_date_option_price: Decimal = Field(
        description="The IRC 423(c)(2) option price: Form 3922 box 8 under a lookback, box 5 when the price was fixed at grant."
    )
    input_assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Assumptions this op made about the INPUTS, promoted out of `work` so a caller reading "
            "only `ordinary_income` cannot miss them — chiefly a defaulted 1099-B basis and a missing "
            "Form 3922 box 8, either of which moves the dollars."
        ),
    )
    not_modeled: list[str] = Field(description="What this op deliberately does NOT compute, named so nothing is silently assumed away.")
    form_3922_boxes: dict[str, str] = Field(description="The Form 3922 boxes this computation used, echoed back for confirmation against the paper form.")
    inputs: dict[str, Any]
    work: str
    citation: Citation
    citations: list[Citation] = Field(description="Every authority behind the number, statute first.")


def espp_disposition(
    shares: int | float | Decimal | str,
    grant_date: "_DateLike",
    purchase_date: "_DateLike",
    sale_date: "_DateLike",
    grant_date_fmv_per_share: int | float | Decimal | str,
    purchase_date_fmv_per_share: int | float | Decimal | str,
    purchase_price_per_share: int | float | Decimal | str,
    sale_price_per_share: int | float | Decimal | str,
    grant_date_exercise_price_per_share: int | float | Decimal | str | None = None,
    broker_reported_basis: int | float | Decimal | str | None = None,
    broker_reported_basis_to_irs: bool = True,
    selling_expenses: int | float | Decimal | str = 0,
    employed_through_exercise: bool = True,
    knowledge_dir: str | Path | None = None,
) -> EsppDispositionResult:
    """One lot of section 423 ESPP stock, sold: how much is compensation, how much
    is capital gain, and what the Form 8949 row has to say so the discount is not
    taxed twice.

    THE TWO DISPOSITIONS ARE NOT VARIANTS OF ONE FORMULA. Conflating them is
    the error this op exists to prevent, so it names the branch it took:

    * **Qualifying** — sold MORE than 2 years after the GRANT date and MORE than
      1 year after the PURCHASE date (IRC 423(a)(1)). Ordinary income is the
      **LESSER** of (a) the discount measured on the GRANT-date price
      (423(c)(2): grant-date FMV minus the option price) and (b) the actual gain
      (423(c)(1): disposition FMV minus what you paid). A sale at a LOSS
      therefore recognises **ZERO** ordinary income — Pub 525: "If you have a
      loss from the sale, it's a capital loss, and you don't have any ordinary
      income." The remainder is long-term capital gain, necessarily, because
      the qualifying test already requires more than a year past purchase.
    * **Disqualifying** — anything else, including a same-day sale. Ordinary
      income is the full spread at PURCHASE (purchase-date FMV minus the price
      paid) **regardless of the sale price**: Pub 525, "This ordinary income
      isn't limited to your gain from the sale of the stock." So a filer who
      sold below the purchase-date FMV still recognises that compensation AND
      takes a capital loss. The remainder is capital gain or loss, short- or
      long-term measured from the PURCHASE date.

    **THE BASIS CORRECTION IS THE HIGHEST-DOLLAR PART.** The broker's Form
    1099-B reports box 1e as the DISCOUNTED PURCHASE PRICE only — Instructions
    for Form 8949: "For compensatory options granted after 2013, the basis
    information reported to you on Form 1099-B ... won't reflect any amount you
    included in income upon grant or exercise of the option." The correct basis
    is the price paid PLUS the ordinary income recognised (IRC 423(c)'s last
    sentence for a qualifying disposition; Pub 525's "Increase your basis in the
    stock by the amount of this ordinary income" for a disqualifying one). A
    filer who trusts the 1099-B pays tax on the discount TWICE. This op returns
    the corrected basis, the adjustment, and the exact Form 8949 treatment:
    **code B** in column (f) whenever the broker reported an incorrect basis,
    with the reported basis left in column (e) and the correction in column (g)
    as a negative number when the basis WAS reported to the IRS (box A/D), or
    the correct basis in column (e) and -0- in column (g) when it was not (box
    B/E).

    **THE LOOKBACK.** Under a lookback the price you pay is the discount applied
    to the LOWER of the grant-date and purchase-date FMVs, but the QUALIFYING
    ordinary income is computed on the GRANT-date price — IRC 423(c): "If the
    option price is not fixed or determinable at the time the option is granted,
    then for purposes of this subsection, the option price shall be determined
    as if the option were exercised at such time." That price is **Form 3922 box
    8**, and it is a different number from box 5 whenever the stock fell between
    grant and purchase. Pass ``grant_date_exercise_price_per_share`` (box 8)
    whenever your form shows one; the Form 3922 Instructions for Employee say
    box 8 is blank ONLY when the price "was fixed or determinable on the date
    shown in box 1".

    Inputs map one-to-one onto Form 3922 and the 1099-B:

    * ``shares`` = box 6, ``grant_date`` = box 1, ``purchase_date`` = box 2,
      ``grant_date_fmv_per_share`` = box 3, ``purchase_date_fmv_per_share`` =
      box 4, ``purchase_price_per_share`` = box 5,
      ``grant_date_exercise_price_per_share`` = box 8 (omit when blank).
    * ``sale_date`` and ``sale_price_per_share`` come from the 1099-B
      (box 1c / box 1d divided by the shares), not from Form 3922 box 7, which
      records the first transfer of legal title rather than the sale.
    * ``broker_reported_basis`` is 1099-B **box 1e for this lot, as a TOTAL**.
      Left out, it defaults to shares x box 5 — the systematic broker behaviour
      — and that default is promoted into ``input_assumptions``.
    * ``broker_reported_basis_to_irs`` mirrors 1099-B box 12 and decides which
      Form 8949 box you check and therefore which half of the code-B rule
      applies. Stock acquired after 2011 is a covered security, so True is the
      normal case.

    Refused, prescriptively, rather than answered wrongly:
    ``employed_through_exercise=False`` (IRC 423(a)(2) fails, so section 421(a)
    never applied and the option was a NONSTATUTORY one taxed at exercise under
    section 83, not here), and a price below the section 423(b)(6) floor, or one
    below 85% of the grant-date FMV with no box 8 — which can only mean a
    lookback whose box 8 was not supplied.

    ``knowledge_dir`` is accepted for signature parity with its neighbours but
    is deliberately unused: IRC 423 carries no per-year figures, so this op
    reads no knowledge pack, per the P-005/P-006 discipline that only figures
    belong in a year pack.
    """
    del knowledge_dir  # see the docstring: no per-year figures, so no pack read
    if not employed_through_exercise:
        raise ValueError(
            "employed_through_exercise=False takes this out of section 423 entirely: 423(a)(2) requires "
            "employment 'at all times during the period beginning with the date of the granting of the "
            "option and ending on the day 3 months before the date of such exercise', and Pub 525 says "
            "'If you don't meet the employment requirements ... your option is a nonstatutory stock "
            "option.' A nonstatutory option is taxed at EXERCISE under section 83 (the spread is wages "
            "in the exercise year, withheld on, and the basis is the price paid plus that spread), not "
            "on disposition — so neither branch of this op applies. Compute the exercise-year wages "
            "from the Form W-2 and report the later sale as an ordinary capital transaction"
        )
    n = _to_decimal(shares, "shares")
    if n <= 0:
        raise ValueError(
            f"shares must be > 0, got {n} — pass Form 3922 box 6 ('No. of shares transferred'). "
            f"Fractional shares are fine: an ESPP buys them from whole payroll dollars"
        )
    grant = _as_date(grant_date, "grant_date")
    purchase = _as_date(purchase_date, "purchase_date")
    sale = _as_date(sale_date, "sale_date")
    if not (grant <= purchase <= sale):
        raise ValueError(
            f"dates must run grant_date <= purchase_date <= sale_date, got grant {grant.isoformat()}, "
            f"purchase {purchase.isoformat()}, sale {sale.isoformat()} — grant_date is Form 3922 box 1, "
            f"purchase_date is box 2 (the exercise date), and sale_date is the 1099-B box 1c date sold, "
            f"NOT Form 3922 box 7 (the first transfer of legal title)"
        )
    grant_fmv = _to_decimal(grant_date_fmv_per_share, "grant_date_fmv_per_share")
    purchase_fmv = _to_decimal(purchase_date_fmv_per_share, "purchase_date_fmv_per_share")
    paid = _to_decimal(purchase_price_per_share, "purchase_price_per_share")
    sale_price = _to_decimal(sale_price_per_share, "sale_price_per_share")
    expenses = _to_decimal(selling_expenses, "selling_expenses")
    for name, value in (
        ("grant_date_fmv_per_share", grant_fmv), ("purchase_date_fmv_per_share", purchase_fmv),
        ("purchase_price_per_share", paid),
    ):
        if value <= 0:
            raise ValueError(
                f"{name} must be > 0, got {value} — Form 3922 boxes 3, 4 and 5 are per-SHARE dollar "
                f"amounts, never totals and never zero"
            )
    if sale_price < 0:
        raise ValueError(f"sale_price_per_share must be >= 0, got {sale_price} (0 is a worthless disposition)")
    if expenses < 0:
        raise ValueError(f"selling_expenses must be >= 0, got {expenses} — pass the commission as a positive amount")

    lower_fmv = min(grant_fmv, purchase_fmv)
    statutory_floor = _cents(_ESPP_STATUTORY_MIN_PRICE_RATE * lower_fmv)
    if paid < statutory_floor - _ESPP_PRICE_TOLERANCE:
        raise ValueError(
            f"purchase_price_per_share {_money(paid)} is below the IRC 423(b)(6) floor {_money(statutory_floor)} "
            f"(85% of {_money(lower_fmv)}, the lower of the grant-date FMV {_money(grant_fmv)} and the "
            f"exercise-date FMV {_money(purchase_fmv)}). 423(b)(6) requires the plan's option price to be "
            f"'not less than the lesser of ... 85 percent of the fair market value of the stock at the time "
            f"such option is granted, or ... 85 percent of the fair market value of the stock at the time "
            f"such option is exercised', so a plan pricing below that is NOT a section 423 plan and none of "
            f"423(c)'s treatment applies — the spread would be ordinary compensation at purchase under "
            f"section 83. Re-read Form 3922 boxes 3, 4 and 5"
        )
    grant_floor = _cents(_ESPP_STATUTORY_MIN_PRICE_RATE * grant_fmv)
    box8_supplied = grant_date_exercise_price_per_share is not None
    if box8_supplied:
        box8 = _to_decimal(grant_date_exercise_price_per_share, "grant_date_exercise_price_per_share")
        if box8 <= 0:
            raise ValueError(
                f"grant_date_exercise_price_per_share must be > 0, got {box8} — Form 3922 box 8 is a "
                f"per-share price. Omit the argument entirely when box 8 is BLANK on your form (which the "
                f"Instructions for Employee say happens only when 'the exercise price per share was fixed "
                f"or determinable on the date shown in box 1')"
            )
    elif paid < grant_floor - _ESPP_PRICE_TOLERANCE:
        raise ValueError(
            f"purchase_price_per_share {_money(paid)} is below 85% of the GRANT-date FMV "
            f"({_money(grant_floor)}), which under IRC 423(b)(6) can only happen when the price was set "
            f"off the LOWER exercise-date FMV — i.e. this plan has a LOOKBACK, so the option price was "
            f"NOT fixed or determinable at grant. IRC 423(c)'s last sentence then requires the "
            f"qualifying-disposition ordinary income to be measured against the price 'determined as if "
            f"the option were exercised at such time', which is exactly what Form 3922 box 8 reports. "
            f"Pass grant_date_exercise_price_per_share (box 8). Using box 5 here instead would put the "
            f"423(c)(2) discount at {_money(grant_fmv - paid)} per share when the statute wants "
            f"{_money(grant_fmv)} minus box 8"
        )
    else:
        box8 = paid
    grant_option_price = box8

    two_year_mark = _add_years(grant, 2)
    one_year_mark = _add_years(purchase, 1)
    two_year_met = sale > two_year_mark
    one_year_met = sale > one_year_mark
    qualifying = two_year_met and one_year_met
    long_term = one_year_met  # Pub 525: the holding period begins the day AFTER the purchase

    # THE OTHER HALF OF THE BOX-8 GAP (found 2026-08-26 by the Phase-I3 adversarial
    # review), DISCLOSED rather than refused. The guard above catches a price BELOW
    # the grant floor — a lookback on a stock that FELL. The mirror case cannot be
    # caught: a plan priced at 85% of the EXERCISE-date FMV on a stock that ROSE pays
    # MORE than 85% of the grant FMV, so box 8 would be 85% x grant FMV rather than
    # box 5, and the 423(c)(2) discount is larger than this op computes.
    #
    # A REFUSAL WAS TRIED AND REVERTED: the condition that catches it
    # (purchase_fmv > grant_fmv and paid > grant_floor) also describes Publication
    # 525's own Example 10 — grant FMV $22, purchase FMV $23, paid $20 — which the
    # IRS resolves as a fixed-at-grant price with ordinary income ($22 - $20) x 100.
    # Nothing in boxes 3/4/5 separates that from an exercise-date-priced plan; Form
    # 3922 box 8 is the ONLY discriminator, which is why the form has the box. So the
    # honest behaviour is the IRS's own default plus a promoted, unmissable note.
    _box8_rise_note: str | None = None
    if not box8_supplied and purchase_fmv > grant_fmv and paid > grant_floor + _ESPP_PRICE_TOLERANCE:
        _box8_rise_note = (
            f"Form 3922 box 8 was not supplied, so the IRC 423(c)(2) option price is taken as box 5 "
            f"({_money(paid)}) — the Instructions for Employee say box 8 is blank ONLY when 'the "
            f"exercise price per share was fixed or determinable on the date shown in box 1', and that "
            f"is Publication 525 Example 10's own reading. BUT this share's numbers cannot confirm it: "
            f"the price paid is ABOVE 85% of the grant-date FMV ({_money(grant_floor)}) and the stock "
            f"ROSE between grant and purchase, which is exactly the shape a plan priced at 85% of the "
            f"EXERCISE-date FMV also produces. If that is your plan, box 8 is NOT blank — it reads "
            f"{_money(grant_floor)}, the 423(c)(2) discount is {_money(grant_fmv - grant_floor)} per "
            f"share instead of {_money(max(Decimal(0), grant_fmv - paid))}, and the ordinary income on "
            f"a qualifying disposition is larger. READ BOX 8 on your Form 3922 before filing."
        )

    zero = Decimal(0)
    if qualifying:
        stat_1 = max(zero, sale_price - paid)          # IRC 423(c)(1)
        stat_2 = max(zero, grant_fmv - grant_option_price)  # IRC 423(c)(2)
        ord_ps = min(stat_1, stat_2)
    else:
        stat_1 = stat_2 = zero
        ord_ps = max(zero, purchase_fmv - paid)        # IRC 421(b) / Pub 525

    amount_paid = irs_round(n * paid)
    ordinary_income = irs_round(n * ord_ps)
    # The form-level identity a filer types: basis = what you paid + what you were
    # taxed on as compensation. Both halves are whole dollars, so build the basis
    # from them rather than re-rounding the exact product.
    corrected_basis = amount_paid + ordinary_income
    proceeds = irs_round(n * sale_price - expenses)
    reported_basis = amount_paid if broker_reported_basis is None else irs_round(
        _to_decimal(broker_reported_basis, "broker_reported_basis")
    )
    if reported_basis < 0:
        raise ValueError(
            f"broker_reported_basis must be >= 0, got {reported_basis} — Form 1099-B box 1e is a cost, "
            f"never negative"
        )
    basis_adjustment = corrected_basis - reported_basis
    basis_is_wrong = basis_adjustment != 0

    part = "II" if long_term else "I"
    box = ("D" if long_term else "A") if broker_reported_basis_to_irs else ("E" if long_term else "B")
    if basis_is_wrong and broker_reported_basis_to_irs:
        col_e, col_g, col_f = reported_basis, -basis_adjustment, "B"
    elif basis_is_wrong:
        col_e, col_g, col_f = corrected_basis, 0, "B"
    else:
        col_e, col_g, col_f = corrected_basis, 0, ""
    capital = proceeds - col_e + col_g
    form_8949 = {
        "part": f"{part} — {'Long-term' if long_term else 'Short-term'}",
        "box": (
            f"{box} — {'Long' if long_term else 'Short'}-term transactions reported on Form(s) 1099-B "
            f"showing basis was {'' if broker_reported_basis_to_irs else 'not '}reported to the IRS"
        ),
        "(a) description of property": f"{n.normalize():f} sh. ESPP",
        "(b) date acquired": purchase.isoformat(),
        "(c) date sold": sale.isoformat(),
        "(d) proceeds": _dollars(proceeds),
        "(e) cost or other basis": _dollars(col_e),
        "(f) code": col_f or "(leave blank — no adjustment)",
        "(g) adjustment": (f"({_dollars(-col_g)})" if col_g < 0 else _dollars(col_g)),
        "(h) gain or (loss)": _dollars(capital),
    }
    holding_periods = {
        "2 years after grant (IRC 423(a)(1))": (
            f"grant {grant.isoformat()} + 2 years = {two_year_mark.isoformat()}; sold {sale.isoformat()} "
            f"— {'MET' if two_year_met else 'NOT met'}"
        ),
        "1 year after purchase (IRC 423(a)(1))": (
            f"purchase {purchase.isoformat()} + 1 year = {one_year_mark.isoformat()}; sold "
            f"{sale.isoformat()} — {'MET' if one_year_met else 'NOT met'}"
        ),
        "capital-gain holding period": (
            f"runs from the day after the purchase date (Pub 525), so the same {one_year_mark.isoformat()} "
            f"line decides it: {'LONG' if long_term else 'SHORT'}-term"
        ),
    }
    discount_pct = (_ONE - (paid / lower_fmv)) if lower_fmv else zero

    assumptions: list[str] = []
    if _box8_rise_note:
        assumptions.append(_box8_rise_note)
    if broker_reported_basis is None:
        assumptions.append(
            f"1099-B BOX 1e WAS NOT SUPPLIED, so it was DEFAULTED to the amount paid "
            f"({_dollars(amount_paid)} = {n.normalize():f} sh x {_money(paid)}) — the systematic broker "
            f"behaviour the Instructions for Form 8949 describe for compensatory options granted after "
            f"2013. The whole ${abs(basis_adjustment):,} adjustment below rests on that default: read box "
            f"1e off your actual 1099-B and re-run if it differs, because the adjustment is the "
            f"difference between the two numbers, not a fixed quantity."
        )
    if qualifying and not box8_supplied and purchase_fmv != grant_fmv:
        assumptions.append(
            f"FORM 3922 BOX 8 WAS NOT SUPPLIED and the two FMVs differ (grant {_money(grant_fmv)} vs "
            f"exercise {_money(purchase_fmv)}), so IRC 423(c)(2) was computed against the price actually "
            f"paid, box 5 {_money(paid)}. Box 8 is blank ONLY when 'the exercise price per share was fixed "
            f"or determinable on the date shown in box 1' (Form 3922 Instructions for Employee). If your "
            f"plan has a LOOKBACK, box 8 is filled in, it is a DIFFERENT number from box 5, and it — not "
            f"box 5 — is what 423(c)'s last sentence requires. Check the paper form before filing: on a "
            f"qualifying disposition this choice moves the ordinary income dollar for dollar."
        )
    if broker_reported_basis_to_irs and broker_reported_basis is None:
        assumptions.append(
            "broker_reported_basis_to_irs defaulted to True (Form 8949 box A/D, 1099-B box 12 checked), "
            "which is right for any share acquired after 2011 — a covered security. It decides WHICH HALF "
            "of the code-B rule you follow: basis reported to the IRS keeps the wrong basis in column (e) "
            "and puts the correction in column (g); basis NOT reported puts the correct basis straight "
            "into column (e) with -0- in column (g). The gain in column (h) is the same either way."
        )
    assumptions.append(
        f"IRC 423(c)(1) measures 'the fair market value of the share at the time of such disposition', "
        f"and this op used the SALE PRICE {_money(sale_price)} for it — correct for an arm's-length market "
        f"sale, which is the only disposition modelled here. A gift, a transfer to a trust, or any other "
        f"non-sale disposition is still a disposition under 423(a)(1): use that date's FMV instead, and "
        f"note there are then no proceeds to fund the tax."
    )

    not_modeled = [
        "ISO exercises and the AMT they create — IRC 422 has no built-in discount (422(b)(4): 'the option "
        "price is not less than the fair market value of the stock at the time such option is granted'), "
        "the exercise spread is an AMT preference on Form 6251 line 2i, and IRC 422(c)(2) caps a "
        "disqualifying disposition's compensation at the realised gain, which section 423 does NOT. Form "
        "3921 reports the ISO exercise; this op is section 423 only.",
        "Section 83(b) elections and restricted stock — section 83 does not reach this transaction at "
        "all: IRC 83(e)(1) says 'This section shall not apply to- (1) a transaction to which section "
        "421 applies', and 421(a)(1) is what applies here ('no income shall result at the time of the "
        "transfer of such share to the individual upon his exercise of the option'). There is "
        "therefore no 83(b) election to make on an ESPP purchase.",
        "RSU vesting — an RSU is not an option at all; it is section 83 wages at vest, with basis equal "
        "to the vest-date FMV already in W-2 box 1, and its 1099-B basis error has a different shape.",
        "Wash sales (IRC 1091) — selling ESPP stock at a loss while another purchase settles inside the "
        "61-day window disallows the loss, and an automatic ESPP or DRIP purchase is exactly the kind of "
        "acquisition that triggers it. Form 8949 code W, not modelled here.",
        "The IRC 423(b)(8) $25,000-per-calendar-year accrual limit, plan eligibility, the 3-month "
        "employment window's own edge cases, and section 421(c) death/estate treatment.",
        "State income tax, and the timing mismatch a mid-year move creates between the purchase-date and "
        "sale-date states.",
        "Multiple purchase lots — this is ONE lot (one Form 3922). Each lot has its own grant date, "
        "purchase date and price, so each gets its own call and its own Form 8949 row.",
    ]

    grant_year_note = (
        f"Your option was granted in {grant.year}, after 2013, so the Instructions for Form 8949 are "
        f"unconditional: the 1099-B basis 'won't reflect any amount you included in income upon grant or "
        f"exercise of the option'."
        if grant.year > 2013 else
        f"Your option was granted in {grant.year}, BEFORE 2014, so the Instructions for Form 8949 say the "
        f"reported basis 'may or may not reflect any amount you included in income' — check box 1e against "
        f"the corrected basis below rather than assuming either way."
    )
    if qualifying:
        income_para = (
            f"QUALIFYING disposition -> IRC 423(c), ordinary income is the LESSER of two per-share amounts: "
            f"(1) FMV at disposition {_money(sale_price)} - amount paid {_money(paid)} = {_money(stat_1)}; "
            f"(2) FMV at GRANT {_money(grant_fmv)} - the option price {_money(grant_option_price)}"
            + (" (Form 3922 box 8, the lookback price)" if box8_supplied else " (Form 3922 box 5 — box 8 blank, so the price was fixed at grant)")
            + f" = {_money(stat_2)}. Lesser = {_money(ord_ps)} per share x {n.normalize():f} sh = "
            f"{_dollars(ordinary_income)}."
            + (
                " The sale was at or below what you paid, so branch (1) is zero and there is NO ordinary "
                "income at all — Pub 525: 'If you have a loss from the sale, it's a capital loss, and you "
                "don't have any ordinary income.'" if stat_1 <= 0 else ""
            )
            + (
                f" There was no grant-date discount either ({_money(grant_option_price)} is not less than "
                f"the {_money(grant_fmv)} grant-date FMV), so branch (2) is zero as well. IRC 423(c) only "
                f"reaches an option priced at 'less than 100 percent of the fair market value of such share "
                f"at the time such option was granted', and Form 3922 is issued only when that or the "
                f"not-determinable condition holds — re-read boxes 3, 5 and 8 if you have one."
                if stat_2 <= 0 else ""
            )
        )
    else:
        failed = []
        if not two_year_met:
            failed.append(f"the 2-year-after-grant test (needed a sale after {two_year_mark.isoformat()})")
        if not one_year_met:
            failed.append(f"the 1-year-after-purchase test (needed a sale after {one_year_mark.isoformat()})")
        income_para = (
            f"DISQUALIFYING disposition — it fails {' and '.join(failed)}. IRC 421(b) switches off 421(a) "
            f"and moves the exercise-year income into the year of DISPOSITION, so ordinary income is the "
            f"full spread AT PURCHASE: exercise-date FMV {_money(purchase_fmv)} - price paid {_money(paid)} "
            f"= {_money(ord_ps)} per share x {n.normalize():f} sh = {_dollars(ordinary_income)}. The SALE "
            f"PRICE does not enter it — Pub 525: 'This ordinary income isn't limited to your gain from the "
            f"sale of the stock.' Sold below {_money(purchase_fmv)} you would still recognise every dollar "
            f"of it and take a capital LOSS on top."
            + (
                f" Here the spread is ZERO: the stock was worth {_money(purchase_fmv)} at exercise, no more "
                f"than the {_money(paid)} you paid, and Pub 525 measures only 'the amount by which the "
                f"stock's FMV when you exercised the option EXCEEDED the option price'. A fixed-price plan "
                f"on a stock that fell more than the discount does exactly this."
                if ord_ps <= 0 else ""
            )
        )

    if basis_is_wrong and broker_reported_basis_to_irs:
        f8949_para = (
            f"FORM 8949, Part {part}, box {box} (basis WAS reported to the IRS): the face's own Note and the "
            f"code-B rule both say to leave the WRONG basis in column (e) and correct it in column (g). "
            f"(d) proceeds {_dollars(proceeds)}; (e) {_dollars(reported_basis)} as reported; (f) code B; "
            f"(g) {form_8949['(g) adjustment']} (the Worksheet for Basis Adjustments in Column (g): line 1 "
            f"{_dollars(reported_basis)} reported, line 2 {_dollars(corrected_basis)} correct, line 2 larger "
            f"so line 3 enters {_dollars(abs(basis_adjustment))} in column (g) as a negative number); "
            f"(h) = (d) - (e) + (g) = {_dollars(capital)}."
        )
    elif basis_is_wrong:
        f8949_para = (
            f"FORM 8949, Part {part}, box {box} (basis was NOT reported to the IRS): the code-B rule's other "
            f"half — put the CORRECT basis straight into column (e) and enter -0- in column (g). "
            f"(d) proceeds {_dollars(proceeds)}; (e) {_dollars(corrected_basis)}; (f) code B; (g) $0; "
            f"(h) {_dollars(capital)}. No adjustment worksheet is needed on this path."
        )
    else:
        f8949_para = (
            f"FORM 8949, Part {part}, box {box}: the reported basis {_dollars(reported_basis)} already equals "
            f"the corrected basis, so columns (f) and (g) stay BLANK — the instructions' last table row, "
            f"'None of the other statements in this column apply because you have no adjustments'. "
            f"(d) {_dollars(proceeds)}; (e) {_dollars(col_e)}; (h) {_dollars(capital)}."
        )

    schedule_d_row = (
        f"Schedule D line {'8b' if long_term else '1b'}"
        if broker_reported_basis_to_irs else f"Schedule D line {'9' if long_term else '2'}"
    )
    if capital < 0:
        capital_para = (
            f"CAPITAL RESULT: {_dollars(-capital)} LOSS, {'LONG' if long_term else 'SHORT'}-term, carried "
            f"to {schedule_d_row} (Form 8949 box {box}). A net capital loss is deductible against ordinary "
            f"income only up to $3,000 a year ($1,500 MFS) under IRC 1211(b) — run calc op "
            f"capital_loss_limitation for the deductible part and the carryover, which keeps its "
            f"{'long' if long_term else 'short'}-term character under IRC 1212(b)(1)."
        )
    else:
        capital_para = (
            f"CAPITAL RESULT: {_dollars(capital)} gain, {'LONG' if long_term else 'SHORT'}-term, to "
            f"{schedule_d_row} (Form 8949 box {box}). A long-term gain reaches the preferential rates "
            f"(calc op tax_with_preferential_rates); a short-term gain is taxed at ordinary rates."
        )
    work_lines = [
        f"Section 423 ESPP disposition, {n.normalize():f} share(s): granted {grant.isoformat()}, purchased "
        f"{purchase.isoformat()} at {_money(paid)}/sh (a "
        f"{(discount_pct * 100).quantize(Decimal('0.01'))}% discount off {_money(lower_fmv)}, the lower of the "
        f"grant-date {_money(grant_fmv)} and exercise-date {_money(purchase_fmv)} FMVs), sold "
        f"{sale.isoformat()} at {_money(sale_price)}/sh.",
        f"HOLDING PERIODS (IRC 423(a)(1), both required): more than 2 years after grant -> after "
        f"{two_year_mark.isoformat()}, {'MET' if two_year_met else 'NOT MET'}; more than 1 year after the "
        f"transfer -> after {one_year_mark.isoformat()}, {'MET' if one_year_met else 'NOT MET'}.",
        income_para,
        "WHERE THE ORDINARY INCOME GOES: the employer should have it in Form W-2 box 1 (Form 1040 line 1a). "
        "Pub 525: if it is not there, 'you must report the ordinary income as wages on Schedule 1 (Form "
        "1040), line 8k, for the year of the sale' — line 8k is printed 'Stock options'. NOTHING IS "
        "WITHHELD ON IT: IRC 423(c)'s last sentence and IRC 421(b)'s both say 'No amount shall be required "
        "to be deducted and withheld under chapter 24', and IRC 3121(a)(22) keeps it out of FICA wages "
        "entirely. Plan the cash — this income arrives with zero tax prepaid.",
        f"BASIS (the part brokers get wrong): amount paid {_dollars(amount_paid)} + ordinary income "
        f"{_dollars(ordinary_income)} = corrected basis {_dollars(corrected_basis)}. IRC 423(c): 'the basis "
        f"of the share in his hands at the time of such disposition shall be increased by an amount equal "
        f"to the amount so includible in his gross income'; Pub 525 says the same for the disqualifying "
        f"branch. The 1099-B reports {_dollars(reported_basis)}. {grant_year_note}"
        + (
            f" Filing the 1099-B unadjusted would tax ${abs(basis_adjustment):,} TWICE — once as "
            f"compensation and again as capital gain."
            if basis_adjustment > 0 else
            (f" The broker OVERSTATED your basis by ${abs(basis_adjustment):,}; the same code-B row corrects "
             f"it in the other direction, as a POSITIVE column (g)." if basis_adjustment < 0 else
             " The two agree, so no adjustment is needed.")
        ),
        f8949_para,
        capital_para,
    ]
    inputs: dict[str, Any] = {
        "shares": str(n),
        "grant_date": grant.isoformat(),
        "purchase_date": purchase.isoformat(),
        "sale_date": sale.isoformat(),
        "grant_date_fmv_per_share": str(grant_fmv),
        "purchase_date_fmv_per_share": str(purchase_fmv),
        "purchase_price_per_share": str(paid),
        "sale_price_per_share": str(sale_price),
        "grant_date_exercise_price_per_share": str(box8) if box8_supplied else None,
        "broker_reported_basis": None if broker_reported_basis is None else reported_basis,
        "broker_reported_basis_to_irs": broker_reported_basis_to_irs,
        "selling_expenses": str(expenses),
        "employed_through_exercise": employed_through_exercise,
    }
    form_3922 = {
        "1 date option granted": grant.isoformat(),
        "2 date option exercised": purchase.isoformat(),
        "3 FMV per share on grant date": _money(grant_fmv),
        "4 FMV per share on exercise date": _money(purchase_fmv),
        "5 exercise price paid per share": _money(paid),
        "6 no. of shares transferred": f"{n.normalize():f}",
        "8 exercise price per share determined as if exercised on the box 1 date": (
            _money(box8) if box8_supplied else "(blank — the price was fixed or determinable at grant)"
        ),
    }
    return EsppDispositionResult(
        disposition_type="qualifying" if qualifying else "disqualifying",
        ordinary_income=ordinary_income,
        ordinary_income_per_share=_cents(ord_ps),
        capital_gain_or_loss=capital,
        capital_gain_character="long_term" if long_term else "short_term",
        proceeds=proceeds,
        amount_paid=amount_paid,
        corrected_basis=corrected_basis,
        corrected_basis_per_share=_cents(paid + ord_ps),
        broker_reported_basis=reported_basis,
        basis_adjustment=basis_adjustment,
        double_taxed_if_uncorrected=max(0, basis_adjustment),
        form_8949=form_8949,
        holding_periods=holding_periods,
        discount_percentage=discount_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        lookback_applied=box8_supplied,
        grant_date_option_price=_cents(grant_option_price),
        input_assumptions=assumptions,
        not_modeled=not_modeled,
        form_3922_boxes=form_3922,
        inputs=inputs,
        work="\n".join(work_lines),
        citation=_IRC_423_CITATION,
        citations=[
            _IRC_423_CITATION, _IRC_421_CITATION, _PUB525_ESPP_CITATION, _F3922_CITATION,
            _I8949_BASIS_CITATION, _F8949_CITATION, _IRC_3121_A22_CITATION, _IRC_422_CITATION,
            _IRC_83_E1_CITATION,
        ],
    )


_CAPITAL_LOSS_YEAR_KEYS = (
    "short_term", "long_term", "taxable_income_before_capital_loss", "filing_status", "year",
)


class CapitalLossYear(BaseModel):
    """One tax year of the IRC 1211(b)/1212(b) chain: Schedule D Part III plus the
    Capital Loss Carryover Worksheet that feeds the next year's lines 6 and 14."""

    model_config = ConfigDict(extra="forbid")

    year: int
    filing_status: str
    short_term_carryover_in: int = Field(description="Schedule D line 6, entered on the form as a positive number in parentheses.")
    long_term_carryover_in: int = Field(description="Schedule D line 14, likewise.")
    net_short_term: int = Field(description="Schedule D line 7: this year's short-term transactions minus the line 6 carryover.")
    net_long_term: int = Field(description="Schedule D line 15: this year's long-term transactions minus the line 14 carryover.")
    net_capital: int = Field(description="Schedule D line 16 = line 7 + line 15.")
    deduction: int = Field(description="Schedule D line 21 as a POSITIVE amount — what actually reduces income this year.")
    deduction_cap: int = Field(description="$3,000, or $1,500 for married filing separately (IRC 1211(b)(1)).")
    taxable_income_before_capital_loss: int = Field(description="The caller's taxable income with the line 21 deduction NOT yet subtracted.")
    taxable_income_after_deduction: int = Field(description="Worksheet line 1 = Form 1040 line 15 as filed; may be negative, and the worksheet wants it that way.")
    loss_absorbed: int = Field(
        description="Worksheet line 4 = min(line 2, line 3): how much of the LOSS POOL this year actually consumed. Below `deduction` whenever taxable income ran out."
    )
    deduction_not_absorbed: int = Field(
        description="deduction - loss_absorbed: dollars deducted on Schedule D that bought nothing, because taxable income was already gone. They stay in the carryover."
    )
    short_term_carryover_out: int = Field(description="Worksheet line 8 -> next year's Schedule D line 6.")
    long_term_carryover_out: int = Field(description="Worksheet line 13 -> next year's Schedule D line 14.")
    worksheet_lines: dict[str, str] = Field(description="The Capital Loss Carryover Worksheet, lines 1-13, keyed by printed line number.")
    schedule_d_lines: dict[str, str] = Field(description="Schedule D lines 6, 7, 14, 15, 16 and 21 as they should be entered.")


class CapitalLossLimitationResult(BaseModel):
    """Result of :func:`capital_loss_limitation`: year one in the headline fields,
    the whole rolled-forward chain in ``years``."""

    model_config = ConfigDict(extra="forbid")

    deduction: int = Field(description="Year one's Schedule D line 21, as a positive amount.")
    deduction_cap: int
    net_short_term: int
    net_long_term: int
    net_capital: int = Field(description="Year one's Schedule D line 16.")
    short_term_carryover: int = Field(description="Year one's worksheet line 8 — short-term stays SHORT-term (IRC 1212(b)(1)(A)).")
    long_term_carryover: int = Field(description="Year one's worksheet line 13 — long-term stays LONG-term (IRC 1212(b)(1)(B)).")
    total_carryover: int
    loss_absorbed: int = Field(description="Year one's worksheet line 4: the IRC 1212(b)(2)(A) lesser-of, which is what the pool actually loses.")
    deduction_not_absorbed: int
    years: list[CapitalLossYear] = Field(description="One row per modelled year, in order, each carrying its own worksheet.")
    final_short_term_carryover: int = Field(description="What is still short-term after the LAST modelled year.")
    final_long_term_carryover: int = Field(description="What is still long-term after the last modelled year.")
    years_modeled: int
    years_to_exhaust: int | None = Field(
        default=None,
        description="How many modelled years it took to use the loss up entirely; None when the chain ends with a carryover still alive.",
    )
    input_assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Assumptions about the INPUTS, promoted out of `work`: how worksheet line 1 was derived "
            "from taxable_income_before_capital_loss, what a chain year inherited, and where the "
            "printed worksheet and IRC 1212(b)(2)(B) diverge."
        ),
    )
    worksheet_lines: dict[str, str] = Field(description="Year one's Capital Loss Carryover Worksheet.")
    schedule_d_lines: dict[str, str] = Field(description="Year one's Schedule D lines.")
    inputs: dict[str, Any]
    work: str
    citation: Citation
    citations: list[Citation] = Field(description="Every authority behind the number, statute first.")


def _capital_loss_one_year(
    year: int,
    filing_status: str,
    short_term: int,
    long_term: int,
    taxable_income_before: int,
    st_carryover_in: int,
    lt_carryover_in: int,
) -> CapitalLossYear:
    """Schedule D Part III + the Capital Loss Carryover Worksheet for ONE year."""
    resolved, _ = _resolve_filing_status(filing_status)
    cap = _CAPITAL_LOSS_CAP_MFS if resolved == "married_filing_separately" else _CAPITAL_LOSS_CAP
    line6, line14 = st_carryover_in, lt_carryover_in
    line7 = short_term - line6      # Schedule D line 7 (IRC 1222(5)/(6), after the carryover)
    line15 = long_term - line14     # Schedule D line 15 (IRC 1222(7)/(8))
    line16 = line7 + line15
    line21 = min(-line16, cap) if line16 < 0 else 0

    # Capital Loss Carryover Worksheet, lines 1-13.
    w1 = taxable_income_before - line21   # Form 1040 line 15 as filed; may be negative
    w2 = line21
    w3 = max(0, w1 + w2)
    w4 = min(w2, w3)
    w5 = -line7 if line7 < 0 else 0
    w6 = max(0, line15) if line7 < 0 else 0
    w7 = (w4 + w6) if line7 < 0 else 0
    w8 = max(0, w5 - w7) if line7 < 0 else 0
    if line15 < 0:
        w9 = -line15
        w10 = max(0, line7)
        w11 = max(0, w4 - w5)
        w12 = w10 + w11
        w13 = max(0, w9 - w12)
    else:
        w9 = w10 = w11 = w12 = w13 = 0

    skip_note = "" if line7 < 0 else " (line 7 is not a loss: the worksheet enters -0- on line 5 and goes to line 9)"
    worksheet = {
        "1": f"{_dollars(w1)} (Form 1040 line 15 as filed{', a negative taxable income, which the worksheet keeps' if w1 < 0 else ''})",
        "2": _dollars(w2),
        "3": _dollars(w3),
        "4": _dollars(w4),
        "5": _dollars(w5) + skip_note,
        "6": _dollars(w6),
        "7": _dollars(w7),
        "8": f"{_dollars(w8)} SHORT-term carryover -> next year's Schedule D line 6",
        "9": _dollars(w9) + ("" if line15 < 0 else " (line 15 is not a loss: the worksheet skips lines 9 through 13)"),
        "10": _dollars(w10),
        "11": _dollars(w11),
        "12": _dollars(w12),
        "13": f"{_dollars(w13)} LONG-term carryover -> next year's Schedule D line 14",
    }
    schedule_d = {
        "6": f"({_dollars(line6)})" if line6 else "$0",
        "7": _dollars(line7),
        "14": f"({_dollars(line14)})" if line14 else "$0",
        "15": _dollars(line15),
        "16": _dollars(line16),
        "21": (f"({_dollars(line21)}) -> Form 1040 line {_capital_loss_1040_line(year)}" if line21 else "$0 (line 16 is not a loss)"),
    }
    return CapitalLossYear(
        year=year,
        filing_status=filing_status,
        short_term_carryover_in=line6,
        long_term_carryover_in=line14,
        net_short_term=line7,
        net_long_term=line15,
        net_capital=line16,
        deduction=line21,
        deduction_cap=cap,
        taxable_income_before_capital_loss=taxable_income_before,
        taxable_income_after_deduction=w1,
        loss_absorbed=w4,
        deduction_not_absorbed=w2 - w4,
        short_term_carryover_out=w8,
        long_term_carryover_out=w13,
        worksheet_lines=worksheet,
        schedule_d_lines=schedule_d,
    )


def capital_loss_limitation(
    short_term: int | float | Decimal | str,
    long_term: int | float | Decimal | str,
    taxable_income_before_capital_loss: int | float | Decimal | str,
    filing_status: str = "single",
    year: int = 2025,
    short_term_carryover_in: int | float | Decimal | str = 0,
    long_term_carryover_in: int | float | Decimal | str = 0,
    following_years: Sequence[Mapping[str, Any]] | None = None,
    knowledge_dir: str | Path | None = None,
) -> CapitalLossLimitationResult:
    """IRC 1211(b) and 1212(b): how much of a net capital loss is deductible this
    year, and what carries forward — with its CHARACTER preserved.

    Schedule D nets short and long SEPARATELY first (line 7 and line 15, the IRC
    1222(5)-(8) definitions) and only then against each other (line 16). If line
    16 is a loss, line 21 deducts the smaller of that loss and **$3,000 ($1,500
    married filing separately)** — IRC 1211(b)(1), statutory and never indexed.
    Everything left carries forward indefinitely and **keeps its character**:
    IRC 1212(b)(1)(A) makes the excess short-term loss "a short-term capital
    loss in the succeeding taxable year", (B) does the same for long-term. That
    matters, because next year a long-term carryover hits long-term gains first
    (Pub 550) and short-term losses are the ones that shelter ordinary-rate
    short-term gains.

    **THE SUBTLETY MOST CALLERS MISS — and it is not the one they expect.**
    The Schedule D line 21 deduction is *not* reduced by taxable income; it
    stays at $3,000 even when it drives taxable income below zero. What taxable
    income limits is how much of the loss POOL the year consumes. The Capital
    Loss Carryover Worksheet computes, at line 4, the lesser of (line 2) the
    deduction and (line 3) taxable income plus that deduction — which is IRC
    1212(b)(2)(A)'s "lesser of ... the amount allowed for the taxable year under
    paragraph (1) or (2) of section 1211(b), or ... the adjusted taxable income
    for such taxable year". A filer whose taxable income was $1,000 deducts
    $3,000 and still only burns $1,000 of loss, so the carryover is $2,000
    LARGER than the naive "loss minus $3,000". This op reports both numbers:
    ``deduction`` and ``loss_absorbed``, with the gap named
    ``deduction_not_absorbed``.

    Inputs:

    * ``short_term`` / ``long_term`` are this year's OWN net short- and
      long-term results BEFORE any carryover — Schedule D lines 1a-5 and 8a-13
      respectively, each as one signed number (a loss is negative). Any prior
      carryover goes in ``short_term_carryover_in`` /
      ``long_term_carryover_in`` as POSITIVE amounts, because that is how
      Schedule D lines 6 and 14 are printed.
    * ``taxable_income_before_capital_loss`` is taxable income with the
      Schedule D line 21 deduction NOT yet subtracted. The worksheet's line 1 is
      the filed Form 1040 line 15, so this op derives it as this figure minus
      the deduction and prints it — taking it this way round keeps the
      computation non-circular for a projection. Pass it NEGATIVE if deductions
      already exceeded income: the worksheet explicitly wants that ("If the
      amount would have been a loss if you could enter a negative number on
      that line, enclose the amount in parentheses"), and Pub 550 agrees ("If
      your deductions are more than your gross income for the tax year, use
      your negative taxable income").
    * ``following_years`` rolls the chain forward. Each entry is a mapping with
      ``short_term``, ``long_term`` and ``taxable_income_before_capital_loss``,
      optionally ``filing_status`` and ``year``; the carryovers are threaded in
      automatically, so a caller never re-enters them and cannot lose the
      character split. Years default to consecutive and must strictly increase.

    ``year`` selects which Schedule D revision the work and citation quote and
    therefore which Form 1040 line the deduction lands on (line 7 through 2024,
    line 7a from 2025). Revisions 2022-2025 were read directly; the worksheet's
    lines 1-13 are identical in all of them, so earlier years — whose numbering
    was not verified — are refused.

    ``knowledge_dir`` is accepted for signature parity with its neighbours but
    is deliberately unused: the $3,000/$1,500 limitation is statutory and not
    indexed, so this op reads no knowledge pack, per the P-005/P-006 discipline
    that only figures belong in a year pack.
    """
    del knowledge_dir  # see the docstring: statutory figures, so no pack read
    if year < _CAPITAL_LOSS_VERIFIED_REVISIONS[0]:
        raise ValueError(
            f"capital_loss_limitation does not support {year}: the Capital Loss Carryover Worksheet's "
            f"line numbering was verified only against the {_CAPITAL_LOSS_VERIFIED_REVISIONS[0]}-"
            f"{_CAPITAL_LOSS_NEWEST_VERIFIED} Schedule D instructions, and Schedule D line 21's "
            f"destination on Form 1040 has already moved once inside that window. IRC 1211(b)'s "
            f"$3,000/$1,500 has been the law for tax years beginning after December 31, 1986 (P.L. "
            f"99-514 section 301(b)(10)), so an earlier year is computable by hand off that year's own "
            f"instructions — pass a year from {_CAPITAL_LOSS_VERIFIED_REVISIONS[0]} onward"
        )
    st = irs_round(_to_decimal(short_term, "short_term"))
    lt = irs_round(_to_decimal(long_term, "long_term"))
    ti = irs_round(_to_decimal(taxable_income_before_capital_loss, "taxable_income_before_capital_loss"))
    st_in = irs_round(_to_decimal(short_term_carryover_in, "short_term_carryover_in"))
    lt_in = irs_round(_to_decimal(long_term_carryover_in, "long_term_carryover_in"))
    for name, value in (("short_term_carryover_in", st_in), ("long_term_carryover_in", lt_in)):
        if value < 0:
            raise ValueError(
                f"{name} must be >= 0, got {value} — Schedule D lines 6 and 14 print the carryover as a "
                f"POSITIVE number inside parentheses and the form subtracts it. A prior-year capital GAIN "
                f"does not carry forward at all; only losses do"
            )
    _resolve_filing_status(filing_status)  # validate early with the module's own message

    rows: list[CapitalLossYear] = []
    first = _capital_loss_one_year(year, filing_status, st, lt, ti, st_in, lt_in)
    rows.append(first)

    assumptions: list[str] = [
        f"WORKSHEET LINE 1 WAS DERIVED, NOT GIVEN: taxable_income_before_capital_loss "
        f"{_dollars(ti)} minus the Schedule D line 21 deduction {_dollars(first.deduction)} = "
        f"{_dollars(first.taxable_income_after_deduction)}, which is what your filed Form 1040 line 15 "
        f"should read. Tie the two together before relying on the carryover — if line 15 differs, the "
        f"taxable income passed here was the wrong one and every carryover below moves."
    ]

    chain = list(following_years or [])
    prev_year, prev_status = year, filing_status
    st_next, lt_next = first.short_term_carryover_out, first.long_term_carryover_out
    for i, entry in enumerate(chain):
        if not isinstance(entry, Mapping):
            raise ValueError(
                f"following_years[{i}] must be a mapping, got {type(entry).__name__} — each entry is one "
                f"later tax year: {{'short_term': ..., 'long_term': ..., "
                f"'taxable_income_before_capital_loss': ..., 'filing_status'?: ..., 'year'?: ...}}"
            )
        unknown = sorted(set(entry) - set(_CAPITAL_LOSS_YEAR_KEYS))
        if unknown:
            raise ValueError(
                f"following_years[{i}] has unknown key(s) {unknown} — allowed keys are "
                f"{list(_CAPITAL_LOSS_YEAR_KEYS)}. The carryovers are threaded in automatically and must "
                f"NOT be re-entered: passing them by hand is how the short/long character split gets lost"
            )
        missing = [k for k in ("short_term", "long_term", "taxable_income_before_capital_loss") if k not in entry]
        if missing:
            raise ValueError(
                f"following_years[{i}] is missing {missing} — a chain year needs its own capital results "
                f"and its own taxable income, or the worksheet's line 3 limit cannot be applied to it"
            )
        entry_year = entry.get("year", prev_year + 1)
        if not isinstance(entry_year, int) or isinstance(entry_year, bool):
            raise ValueError(f"following_years[{i}]['year'] must be an int, got {entry_year!r}")
        if entry_year <= prev_year:
            raise ValueError(
                f"following_years[{i}]['year'] = {entry_year} must be LATER than the previous year "
                f"{prev_year} — IRC 1212(b)(1) carries a loss to 'the succeeding taxable year', so the "
                f"chain only runs forward"
            )
        entry_status = entry.get("filing_status", prev_status)
        row = _capital_loss_one_year(
            entry_year,
            str(entry_status),
            irs_round(_to_decimal(entry["short_term"], f"following_years[{i}]['short_term']")),
            irs_round(_to_decimal(entry["long_term"], f"following_years[{i}]['long_term']")),
            irs_round(_to_decimal(
                entry["taxable_income_before_capital_loss"],
                f"following_years[{i}]['taxable_income_before_capital_loss']",
            )),
            st_next,
            lt_next,
        )
        rows.append(row)
        if entry_year != prev_year + 1:
            assumptions.append(
                f"The chain SKIPS from {prev_year} to {entry_year}. IRC 1212(b)(1) carries a loss to 'the "
                f"succeeding taxable year' and Pub 550 says the current year's allowable deduction counts "
                f"'WHETHER OR NOT you claimed it and whether or not you filed a return for the current "
                f"year' — so the skipped year(s) still consumed their share. Model every year, or treat "
                f"this carryover as an upper bound."
            )
        if str(entry_status) != str(prev_status):
            assumptions.append(
                f"Filing status changes from {prev_status} to {entry_status} at {entry_year}, which "
                f"changes the cap to {_dollars(row.deduction_cap)}. Pub 550: 'if you and your spouse once "
                f"filed a joint return and are now filing separate returns, any capital loss carryover "
                f"from the joint return can be deducted only on the return of the spouse who actually had "
                f"the loss.' This op cannot tell whose loss it was — SPLIT the carryover yourself before "
                f"a joint-to-separate year."
            )
        prev_year, prev_status = entry_year, str(entry_status)
        st_next, lt_next = row.short_term_carryover_out, row.long_term_carryover_out

    exhausted: int | None = None
    for i, row in enumerate(rows, start=1):
        if row.short_term_carryover_out == 0 and row.long_term_carryover_out == 0:
            exhausted = i
            break

    if first.deduction_not_absorbed:
        assumptions.append(
            f"TAXABLE INCOME CAPPED WHAT THE LOSS BOUGHT: {_dollars(first.deduction)} was deducted on "
            f"Schedule D line 21, but worksheet line 4 consumed only {_dollars(first.loss_absorbed)} of "
            f"the pool, so {_dollars(first.deduction_not_absorbed)} of that deduction bought nothing and "
            f"stays in the carryover. That is IRC 1212(b)(2)(A) working as written, not an error — but it "
            f"means the filed Form 1040 shows a $3,000-scale deduction while the loss barely shrank."
        )
    if exhausted is None and (rows[-1].short_term_carryover_out or rows[-1].long_term_carryover_out):
        assumptions.append(
            f"The chain ENDS with {_dollars(rows[-1].short_term_carryover_out)} short-term and "
            f"{_dollars(rows[-1].long_term_carryover_out)} long-term still unused after {rows[-1].year}. "
            f"The carryover is indefinite (Pub 550: 'you can carry it over to later years until it is "
            f"completely used up'), but it dies with the taxpayer — a decedent's loss 'can be deducted "
            f"only on the final income tax return filed for the decedent' and the estate cannot carry it "
            f"over."
        )
    assumptions.append(
        "SECTION 151 ADD-BACK, disclosed because the printed worksheet and the statute do not say the "
        "same thing. IRC 1212(b)(2)(B) defines adjusted taxable income as taxable income increased by "
        "BOTH the 1211(b) amount AND 'the deduction allowed for such year under section 151 or any "
        "deduction in lieu thereof'; the worksheet's line 3 adds back only the first, because IRC "
        "151(d)(5)(A) makes the exemption amount zero for tax years beginning after 2017. This op "
        "reproduces the WORKSHEET. One live divergence: P.L. 119-21 added IRC 151(d)(5)(C)'s $6,000 "
        "senior deduction for tax years beginning before 2029 — a deduction allowed under section 151 "
        "that the printed worksheet does NOT add back. It can only matter to a filer whose taxable "
        "income is near zero, and following the worksheet there gives the LARGER carryover."
    )

    net = first.net_capital
    if net >= 0:
        headline = (
            f"Schedule D line 16 is {_dollars(net)}, NOT a loss, so IRC 1211(b) never bites: there is no "
            f"line 21 deduction and nothing carries forward. "
            + (
                f"Line 7 {_dollars(first.net_short_term)} and line 15 {_dollars(first.net_long_term)} "
                f"still had to be netted separately first (IRC 1222) — that is what decides how much of "
                f"the gain reaches the preferential rates: net capital gain is the excess of the net "
                f"LONG-term gain over the net SHORT-term loss (IRC 1222(11))."
            )
        )
    else:
        headline = (
            f"Schedule D line 16 = line 7 {_dollars(first.net_short_term)} + line 15 "
            f"{_dollars(first.net_long_term)} = {_dollars(net)}, a net loss. IRC 1211(b) allows losses "
            f"'only to the extent of the gains ... plus (if such losses exceed such gains) the lower of- "
            f"(1) $3,000 ($1,500 in the case of a married individual filing a separate return), or (2) "
            f"the excess of such losses over such gains', so line 21 = the smaller of {_dollars(-net)} "
            f"and {_dollars(first.deduction_cap)} = {_dollars(first.deduction)}, entered in parentheses "
            f"and carried to Form 1040 line {_capital_loss_1040_line(year)}."
        )

    work_lines = [
        f"IRC 1211(b) / 1212(b), tax year {year} ({filing_status}):",
        f"NET SEPARATELY, THEN AGAINST EACH OTHER. Short-term: {_dollars(st)} this year - line 6 "
        f"carryover {_dollars(st_in)} = line 7 {_dollars(first.net_short_term)}. Long-term: "
        f"{_dollars(lt)} - line 14 carryover {_dollars(lt_in)} = line 15 "
        f"{_dollars(first.net_long_term)}.",
        headline,
    ]
    if net < 0:
        work_lines.append(
            f"CAPITAL LOSS CARRYOVER WORKSHEET (Schedule D instructions, 'Lines 6 and 14'): line 1 Form "
            f"1040 line 15 {_dollars(first.taxable_income_after_deduction)}; line 2 the line 21 loss as a "
            f"positive {_dollars(first.deduction)}; line 3 = 1 + 2 floored at zero = "
            f"{_dollars(max(0, ti))}; line 4 = smaller of 2 and 3 = {_dollars(first.loss_absorbed)}. Line "
            f"4 is IRC 1212(b)(2)(A)'s 'lesser of ... the amount allowed ... under section 1211(b), or "
            f"... the adjusted taxable income', and it is the ONLY place taxable income enters: it does "
            f"not shrink the deduction, it shrinks how much of the loss the deduction actually uses up."
            + (
                f" Here it bit: {_dollars(first.deduction)} was deducted but only "
                f"{_dollars(first.loss_absorbed)} of the pool was consumed."
                if first.deduction_not_absorbed else
                " Here taxable income was ample, so line 4 equals line 2 and the full deduction consumed "
                "an equal amount of loss."
            )
        )
        work_lines.append(
            f"SHORT-TERM FIRST, THEN LONG (Pub 550: 'Use short-term losses first ... even if you incurred "
            f"them after a long-term capital loss'): line 5 short-term loss "
            f"{_dollars(-first.net_short_term if first.net_short_term < 0 else 0)}"
            f", line 6 any long-term GAIN, line 7 = 4 + 6, line 8 SHORT-term carryover = "
            f"{_dollars(first.short_term_carryover_out)}. Then line 9 long-term loss, line 10 any "
            f"short-term gain, line 11 = 4 - 5 floored at zero (only the part of the deemed short-term "
            f"gain the short-term loss did not use), line 12 = 10 + 11, line 13 LONG-term carryover = "
            f"{_dollars(first.long_term_carryover_out)}."
        )
        work_lines.append(
            f"CHARACTER SURVIVES: IRC 1212(b)(1) makes the excess short-term loss 'a short-term capital "
            f"loss in the succeeding taxable year' and the excess long-term loss a long-term one, so "
            f"{_dollars(first.short_term_carryover_out)} goes on next year's Schedule D line 6 and "
            f"{_dollars(first.long_term_carryover_out)} on line 14 — never merged. Pub 550: 'A long-term "
            f"capital loss you carry over to the next tax year will reduce that year's long-term capital "
            f"gains before it reduces that year's short-term capital gains.'"
        )
    if len(rows) > 1:
        chain_bits = "; ".join(
            f"{r.year}: line 16 {_dollars(r.net_capital)}, deducted {_dollars(r.deduction)}, out "
            f"{_dollars(r.short_term_carryover_out)} ST / {_dollars(r.long_term_carryover_out)} LT"
            for r in rows
        )
        work_lines.append(f"CHAIN ({len(rows)} years): {chain_bits}.")
        work_lines.append(
            f"After {rows[-1].year}: {_dollars(rows[-1].short_term_carryover_out)} short-term and "
            f"{_dollars(rows[-1].long_term_carryover_out)} long-term remain."
            + (f" The loss was fully used up in modelled year {exhausted} ({rows[exhausted - 1].year})."
               if exhausted is not None else
               " Nothing in IRC 1212(b) expires it — it keeps rolling until it is used.")
        )
    work_lines.append(
        "NOT MODELED: section 1256 contracts and their 1212(c) three-year CARRYBACK (the one capital-loss "
        "carryback an individual can have); wash sales (IRC 1091), which can turn a realised loss into "
        "nothing at all before this computation ever starts; section 1244 small-business stock, which is "
        "ORDINARY loss up to its own limit and never reaches line 16; collectibles and unrecaptured "
        "section 1250 gain, which need the Schedule D Tax Worksheet rather than the Qualified Dividends "
        "and Capital Gain Tax Worksheet; and state capital-loss rules, several of which cap or disallow "
        "the federal carryover."
    )

    inputs: dict[str, Any] = {
        "short_term": st,
        "long_term": lt,
        "taxable_income_before_capital_loss": ti,
        "filing_status": filing_status,
        "year": year,
        "short_term_carryover_in": st_in,
        "long_term_carryover_in": lt_in,
        "following_years_count": len(chain),
    }
    form_citation = _schedule_d_citation(year)
    return CapitalLossLimitationResult(
        deduction=first.deduction,
        deduction_cap=first.deduction_cap,
        net_short_term=first.net_short_term,
        net_long_term=first.net_long_term,
        net_capital=first.net_capital,
        short_term_carryover=first.short_term_carryover_out,
        long_term_carryover=first.long_term_carryover_out,
        total_carryover=first.short_term_carryover_out + first.long_term_carryover_out,
        loss_absorbed=first.loss_absorbed,
        deduction_not_absorbed=first.deduction_not_absorbed,
        years=rows,
        final_short_term_carryover=rows[-1].short_term_carryover_out,
        final_long_term_carryover=rows[-1].long_term_carryover_out,
        years_modeled=len(rows),
        years_to_exhaust=exhausted,
        input_assumptions=assumptions,
        worksheet_lines=first.worksheet_lines,
        schedule_d_lines=first.schedule_d_lines,
        inputs=inputs,
        work="\n".join(work_lines),
        citation=_IRC_1211_B_CITATION,
        citations=[
            _IRC_1211_B_CITATION, _IRC_1212_B_CITATION, _IRC_1222_CITATION, form_citation,
            _PUB550_CARRYOVER_CITATION, _IRC_151_D5_CITATION,
        ],
    )


# ---------------------------------------------------------------------------
# Foreign tax credit — the IRC 904(j) de-minimis election (Phase I, item I4)
# ---------------------------------------------------------------------------

_IRC_904J_CITATION = Citation(
    source=(
        "IRC 904(j) 'Certain individuals exempt' (26 U.S.C. 904(j)), added by P.L. 105-34 "
        "(Taxpayer Relief Act of 1997, enacted 1997-08-05). 904(j)(1): for an individual to "
        "whom the subsection applies, '(A) the limitation of subsection (a) shall not apply, "
        "(B) no taxes paid or accrued by the individual during such taxable year may be deemed "
        "paid or accrued under subsection (c) in any other taxable year, and (C) no taxes paid "
        "or accrued by the individual during any other taxable year may be deemed paid or "
        "accrued under subsection (c) in such taxable year.' 904(j)(2): it applies if '(A) the "
        "entire amount of such individual's gross income for the taxable year from sources "
        "without the United States consists of qualified passive income, (B) the amount of the "
        "creditable foreign taxes paid or accrued by the individual during the taxable year "
        "does not exceed $300 ($600 in the case of a joint return), and (C) such individual "
        "elects to have this subsection apply for the taxable year.' 904(j)(3)(A) defines "
        "qualified passive income as passive income under 904(d)(2)(B) (without clause (iii)) "
        "that 'is shown on a payee statement furnished to the individual'; 904(j)(3)(B) defines "
        "creditable foreign taxes as taxes creditable under section 901 and likewise shown on a "
        "payee statement; 904(j)(3)(C) takes 'payee statement' from section 6724(d)(2); and "
        "904(j)(3)(D): 'This subsection shall not apply to any estate or trust.'"
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section904&num=0&edition=prelim",
)

_IRC_901_CITATION = Citation(
    source=(
        "IRC 901(a) (26 U.S.C. 901(a)): 'If the taxpayer chooses to have the benefits of this "
        "subpart, the tax imposed by this chapter shall, subject to the limitation of section "
        "904, be credited with the amounts provided in the applicable paragraph of subsection "
        "(b)...'; 901(b)(1) covers 'a citizen of the United States and ... a domestic "
        "corporation' for 'any income, war profits, and excess profits taxes paid or accrued "
        "during the taxable year to any foreign country or to any possession of the United "
        "States'. 901(k) imposes a minimum holding period for withholding tax on dividends. "
        "IRC 903 extends the creditable class to 'a tax paid in lieu of a tax on income, war "
        "profits, or excess profits otherwise generally imposed by any foreign country or by "
        "any possession of the United States'."
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section901&num=0&edition=prelim",
)

_IRC_904A_CITATION = Citation(
    source=(
        "IRC 904(a) 'Limitation' (26 U.S.C. 904(a)): 'The total amount of the credit taken "
        "under section 901(a) shall not exceed the same proportion of the tax against which "
        "such credit is taken which the taxpayer's taxable income from sources without the "
        "United States (but not in excess of the taxpayer's entire taxable income) bears to his "
        "entire taxable income for the same taxable year.' 904(c) 'Carryback and carryover of "
        "excess tax paid' is the 1-year-back / 10-year-forward relief the 904(j) election gives "
        "up."
    ),
    url="https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section904&num=0&edition=prelim",
)

# The entity kinds 904(j) speaks to. 904(j)(3)(D) excludes estates and trusts
# outright, so the op refuses to pretend the election exists for them.
FTC_ELECTION_ENTITIES: tuple[str, ...] = ("individual", "estate", "trust")

# Only a JOINT RETURN takes the $600 amount. This is deliberately NOT routed
# through _resolve_filing_status, which maps qualifying_surviving_spouse onto the
# married_filing_jointly RATE column: 904(j)(2)(B) says "in the case of a joint
# return", and a surviving spouse files as an unmarried individual that merely
# borrows the joint rate schedule (IRC 1(a)(2) via 2(a)) — it is not a joint
# return, so the limit is $300. Married filing separately is not one either.
_JOINT_RETURN_STATUSES: frozenset[str] = frozenset({"married_filing_jointly"})


class ForeignTaxCreditConditionCheck(BaseModel):
    """One IRC 904(j) condition, with the statutory pinpoint and how it was decided."""

    model_config = ConfigDict(extra="forbid")

    condition: str = Field(description="What the statute requires, in the statute's own terms.")
    statute: str = Field(description="Pinpoint cite, e.g. 'IRC 904(j)(2)(B)'.")
    met: bool
    detail: str = Field(description="The input that decided it, and the figure where there is one.")


class ForeignTaxCreditElectionResult(BaseModel):
    """Result of :func:`foreign_tax_credit_election`: Form 1116, or one line on Schedule 3."""

    model_config = ConfigDict(extra="forbid")

    form_1116_required: bool = Field(
        description="The headline answer. False only when every 904(j)(2) condition is met AND the caller elects."
    )
    election_available: bool = Field(
        description="True when every 904(j)(2)(A)/(B) condition and the 904(j)(3)(D) entity test are satisfied — before the caller's own election."
    )
    election_made: bool = Field(description="Whether the caller elected (904(j)(2)(C) is the taxpayer's own act, never inferred).")
    route: Literal["schedule_3_election", "form_1116"] = Field(
        description="Where the credit is claimed: one line on Schedule 3 under the election, or the full four-part Form 1116."
    )
    de_minimis_limit: int = Field(description="The 904(j)(2)(B) ceiling that applies to THIS return: $600 on a joint return, otherwise $300.")
    limit_basis: str = Field(description="Why that ceiling — the filing status, spelled out.")
    creditable_foreign_taxes: int = Field(description="The tested amount (whole dollars), after any 904(j)/line-12 reduction the caller passed.")
    headroom: int = Field(description="de_minimis_limit - creditable_foreign_taxes: how much more withholding the election survives (negative when already over).")
    conditions: list[ForeignTaxCreditConditionCheck] = Field(description="Every 904(j) condition, met or not, in statutory order.")
    failed_conditions: list[str] = Field(description="Pinpoint cites of the conditions that failed — empty when the election is available.")
    credit_on_schedule_3: int | None = Field(
        default=None,
        description=(
            "The election's own amount: 'the smaller of (a) your total foreign tax, or (b) your "
            "regular tax' (Instructions for Form 1116). None when not electing, or when "
            "regular_tax was not supplied."
        ),
    )
    schedule_3_line: str = Field(description="The printed line the credit lands on for this year's Schedule 3.")
    credit_lost_to_regular_tax_cap: int | None = Field(
        default=None,
        description=(
            "Foreign tax the election cannot use because regular tax is smaller — and under "
            "904(j)(1)(B) it can never be carried to another year, so it is lost permanently. "
            "None when regular_tax was not supplied."
        ),
    )
    election_costs: list[str] = Field(
        description=(
            "What the election gives up, ALWAYS populated (even on the electing path) so the "
            "answer is never presented as free: the 904(j)(1)(B)/(C) two-way carryover "
            "forfeiture, and the reductions the election does not waive."
        ),
    )
    form_1116_category_box: str | None = Field(
        default=None,
        description="On the Form 1116 route, which category box the passive-income facts point at — None when the facts do not settle it.",
    )
    form_1116_pack_key: str | None = Field(
        default=None,
        description=(
            "The form pack that files the credit the long way, for the year asked about — or None "
            "when that year ships no f1116 pack (2023-2025 only today), because naming a path that "
            "does not exist sends the caller into a FileNotFoundError."
        ),
    )
    not_modeled: list[str] = Field(description="What this op deliberately does not decide, so a caller cannot mistake silence for a clean bill.")
    input_assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions made about the INPUTS, promoted out of `work` so a caller reading only form_1116_required cannot miss them.",
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation
    citations: list[Citation] = Field(description="Every authority behind the answer, statute first.")


def _require_ftc_de_minimis(pack: KnowledgePack, year: int) -> dict:
    """The year pack's credits.foreign_tax_credit.de_minimis_election block, or a fix-it error."""
    credits = pack.credits
    block = (getattr(credits, "foreign_tax_credit", None) or {}) if credits is not None else {}
    election = block.get("de_minimis_election") if isinstance(block, dict) else None
    limits = (election or {}).get("creditable_foreign_taxes_limit")
    if not isinstance(limits, dict) or "joint_return" not in limits or "other" not in limits:
        raise ValueError(
            f"knowledge pack for federal {year} has no credits.foreign_tax_credit.de_minimis_election "
            f"block — add it with its citation before computing the IRC 904(j) election. The two "
            f"amounts are statutory and NOT inflation-indexed: 904(j)(2)(B) reads 'does not exceed "
            f"$300 ($600 in the case of a joint return)', unchanged since P.L. 105-34 added the "
            f"subsection in 1997, and the {year} Instructions for Form 1116 restate it under "
            f"'Election To Claim the Foreign Tax Credit Without Filing Form 1116'. Copy the block "
            f"from knowledge/federal/2023.yaml and re-point its citation url at "
            f"https://www.irs.gov/pub/irs-prior/i1116--{year}.pdf. The figure is never hardcoded in "
            f"calc.py — the citation has to travel with the number (dev plan section 7)."
        )
    return election


def foreign_tax_credit_election(
    creditable_foreign_taxes: int | float | Decimal | str,
    all_foreign_income_passive: bool | None = None,
    all_reported_on_payee_statement: bool | None = None,
    year: int = 2025,  # newest year whose pack ships the 904(j) block; 2026 is planning_only

    filing_status: FilingStatusInput | str = "single",
    elect: bool = True,
    entity: str = "individual",
    regular_tax: int | float | Decimal | str | None = None,
    reduction_in_foreign_taxes: int | float | Decimal | str = 0,
    excess_credit_if_form_1116: int | float | Decimal | str | None = None,
    knowledge_dir: str | Path | None = None,
) -> ForeignTaxCreditElectionResult:
    """Do I need Form 1116, or can I take the credit on Schedule 3 under IRC 904(j)?

    This is the branch that decides whether the four-part Form 1116 gets filled
    out at all, and for the population this repo serves it is usually answered
    "no": a holder of a total-international index fund has foreign tax withheld
    at source, it arrives on **Form 1099-DIV box 7**, and while it stays at or
    under **$300 ($600 on a joint return)** IRC 904(j) lets the whole thing be
    claimed as one number on Schedule 3 with no Form 1116, no three-country
    column grid, and no 904(a) limitation fraction.

    Three things this op refuses to guess, because guessing any of them silently
    decides the election:

    1. ``all_foreign_income_passive`` — 904(j)(2)(A) requires that "the ENTIRE
       amount of such individual's gross income for the taxable year from sources
       without the United States consists of qualified passive income". One dollar
       of foreign wages, foreign self-employment income or a foreign-branch item
       destroys the election for the whole year, no matter how small the withheld
       tax is. Passive here is 904(d)(2)(B) passive without clause (iii), and for
       this purpose the Instructions add that it "also includes (a) income subject
       to the special rule for high-taxed income ... and (b) certain export
       financing interest".
    2. ``all_reported_on_payee_statement`` — 904(j)(3)(A) and (B) both require the
       income AND the tax to be "shown on a payee statement furnished to the
       individual" (a term 904(j)(3)(C) takes from section 6724(d)(2)). The
       Instructions name the qualifying statements: "Form 1099-DIV, Form 1099-INT,
       Schedule K-1 (Form 1041), Schedule K-3 (Form 1065), Schedule K-3 (Form
       1120-S), or similar substitute statements". Foreign tax on a foreign bank
       account with no US information return is exactly what this condition
       excludes.
    3. ``elect`` — 904(j)(2)(C) makes the election the taxpayer's own act
       ("such individual ELECTS to have this subsection apply"). Availability and
       election are reported separately so a caller can see that a filer who
       QUALIFIES may still choose Form 1116 — which is the right choice whenever
       there is an excess credit worth carrying.

    THE ELECTION IS NOT FREE, and this op always says so. 904(j)(1)(B) and (C)
    forbid carrying foreign tax **out of** an election year and **into** one, so
    the 904(c) 1-year-back / 10-year-forward carryover is forfeited in both
    directions for that year. Two concrete consequences the op quantifies when it
    can: pass ``regular_tax`` (Form 1116 line 20 for individuals — Form 1040 line
    16 plus Schedule 2 line 2, less any tax from Form 4972) and it returns both
    the amount actually claimed, "the smaller of (a) your total foreign tax, or
    (b) your regular tax", and ``credit_lost_to_regular_tax_cap``, the difference
    — which under the election can never be recovered in another year. Pass
    ``excess_credit_if_form_1116`` (what Form 1116 line 14 would exceed line 23
    by) and the work names the carryover being given up.

    What the election does NOT waive: "You are still required to take into
    account the general rules for determining whether a tax is creditable" (IRC
    901/903 — and 901(k)'s minimum holding period on dividend withholding), and
    "You are still required to reduce the taxes available for credit by any amount
    you would have entered on line 12 of Form 1116." Pass
    ``reduction_in_foreign_taxes`` for that line-12 amount and it is subtracted
    BEFORE the $300/$600 test. **That ORDER is this op's reasoned reading, NOT
    something the Instructions state** — the sentence above appears under "If you
    make this election, the following rules apply", i.e. among the consequences of
    electing rather than as a step in the eligibility test (corrected 2026-08-27
    after an adversarial review found the claim overstated). The reading rests on
    the statute instead: 904(j)(2) tests "creditable foreign taxes", and a tax
    that line 12 removes was never creditable in the first place. It is
    nonetheless TAXPAYER-FAVOURABLE — it lets a filer whose gross taxes exceed the
    limit qualify — so both figures are returned and the assumption is promoted
    into ``input_assumptions``, with the gross-basis verdict stated whenever the
    two differ. A filer near the limit should have a preparer confirm the order.

    Args:
        creditable_foreign_taxes: foreign tax creditable under section 901/903 —
            for the common case, the total of Form 1099-DIV box 7 and Form
            1099-INT box 6 across every payer. Before any line-12 reduction.
        all_foreign_income_passive: caller's judgment on 904(j)(2)(A). Required.
        all_reported_on_payee_statement: caller's judgment on 904(j)(3)(A)/(B).
            Required.
        year: tax year; the $300/$600 amounts and the Schedule 3 line come from
            that year's knowledge pack.
        filing_status: only ``married_filing_jointly`` is "a joint return".
        elect: 904(j)(2)(C). Default True — the caller asking this question is
            normally asking whether they may take the shortcut.
        entity: ``individual`` | ``estate`` | ``trust``. 904(j)(3)(D) excludes the
            last two.
        regular_tax: Form 1116 line 20. Optional; unlocks the claimed amount and
            the permanently-lost excess.
        reduction_in_foreign_taxes: the Form 1116 line 12 reduction, which the
            election does not waive.
        excess_credit_if_form_1116: what would be carried under 904(c) if Form
            1116 were filed instead. Optional; makes the forfeiture concrete.
        knowledge_dir: override the knowledge base directory.

    Returns:
        :class:`ForeignTaxCreditElectionResult`.

    Raises:
        ValueError: a required judgment was not supplied, an unknown
            ``filing_status``/``entity``, a negative amount, or a year whose pack
            has no de-minimis block — every message says what to do next.
    """
    if all_foreign_income_passive is None:
        raise ValueError(
            "all_foreign_income_passive is required — IRC 904(j)(2)(A) needs 'the ENTIRE amount "
            "of such individual's gross income for the taxable year from sources without the "
            "United States' to consist of qualified passive income, and no engine can infer that "
            "from a tax figure. Pass True only after checking EVERY foreign-source item: interest "
            "and dividends normally qualify (904(d)(2)(B) passive income, plus high-taxed income "
            "and certain export financing interest per the Instructions for Form 1116), while any "
            "foreign wages, foreign self-employment income, foreign rental income, a foreign "
            "branch item or a section 951A inclusion makes it False for the WHOLE YEAR regardless "
            "of how small the withheld tax is. False means Form 1116 is required — run "
            "get_sources('foreign tax credit') and fill formpacks/federal/<year>/f1116."
        )
    if all_reported_on_payee_statement is None:
        raise ValueError(
            "all_reported_on_payee_statement is required — IRC 904(j)(3)(A) and (B) both require "
            "the income AND the foreign tax to be 'shown on a payee statement furnished to the "
            "individual' (section 6724(d)(2)). The Instructions for Form 1116 name the qualifying "
            "statements: Form 1099-DIV, Form 1099-INT, Schedule K-1 (Form 1041), Schedule K-3 "
            "(Form 1065), Schedule K-3 (Form 1120-S), or similar substitute statements. Foreign "
            "tax withheld on a foreign brokerage or bank account that sends no US information "
            "return is exactly what this condition excludes, so pass False for it — the "
            "$300/$600 test is then irrelevant and Form 1116 is required."
        )
    if entity not in FTC_ELECTION_ENTITIES:
        raise ValueError(
            f"unknown entity {entity!r} — use one of: {', '.join(FTC_ELECTION_ENTITIES)}. "
            f"IRC 904(j)(3)(D) is explicit: 'This subsection shall not apply to any estate or "
            f"trust', so the election exists for individuals only."
        )
    status = str(filing_status)
    if status not in set(FILING_STATUSES) | {_QSS}:
        raise ValueError(
            f"unknown filing_status {status!r} — use one of: single, married_filing_jointly, "
            f"married_filing_separately, head_of_household, qualifying_surviving_spouse"
        )

    gross_taxes = _to_decimal(creditable_foreign_taxes, "creditable_foreign_taxes")
    reduction = _to_decimal(reduction_in_foreign_taxes, "reduction_in_foreign_taxes")
    if gross_taxes < 0:
        raise ValueError(
            f"creditable_foreign_taxes must be zero or more, got {_money(gross_taxes)} — pass the "
            f"foreign tax actually withheld or accrued (Form 1099-DIV box 7 + Form 1099-INT box 6); "
            f"a refund of foreign tax is a foreign tax redetermination, which is Schedule C "
            f"(Form 1116) work, not a negative credit"
        )
    if reduction < 0:
        raise ValueError(
            f"reduction_in_foreign_taxes must be zero or more, got {_money(reduction)} — Form 1116 "
            f"line 12's box is printed inside parentheses and takes the POSITIVE reduction"
        )
    tested_exact = max(Decimal(0), gross_taxes - reduction)
    tested = irs_round(tested_exact)

    pack = _load_federal(year, knowledge_dir)
    election_block = _require_ftc_de_minimis(pack, year)
    limits = election_block["creditable_foreign_taxes_limit"]
    joint = status in _JOINT_RETURN_STATUSES
    limit = int(limits["joint_return"] if joint else limits["other"])
    if joint:
        limit_basis = (
            "married filing jointly — IRC 904(j)(2)(B)'s '$600 in the case of a joint return'"
        )
    elif status == _QSS:
        limit_basis = (
            "qualifying surviving spouse — $300, NOT $600: a surviving spouse borrows the joint "
            "RATE schedule (IRC 1(a)(2) via 2(a)) but does not file a joint return, and "
            "904(j)(2)(B) conditions the $600 on 'the case of a joint return'"
        )
    elif status == "married_filing_separately":
        limit_basis = (
            "married filing separately — $300: a separate return is not 'a joint return' under "
            "IRC 904(j)(2)(B), so each spouse tests their own taxes against $300"
        )
    else:
        limit_basis = f"{status.replace('_', ' ')} — $300 under IRC 904(j)(2)(B) (not a joint return)"

    is_individual = entity == "individual"
    within_limit = tested <= limit
    conditions = [
        ForeignTaxCreditConditionCheck(
            condition=(
                "the entire amount of gross income from sources without the United States "
                "consists of qualified passive income"
            ),
            statute="IRC 904(j)(2)(A) with 904(j)(3)(A)",
            met=bool(all_foreign_income_passive),
            detail=(
                "caller confirmed every foreign-source item is passive category income"
                if all_foreign_income_passive
                else "caller reported foreign-source income that is NOT all passive — one "
                "non-passive dollar ends the election for the whole year"
            ),
        ),
        ForeignTaxCreditConditionCheck(
            condition="the income and the foreign taxes on it are shown on a payee statement",
            statute="IRC 904(j)(3)(A) and (B), payee statement per 904(j)(3)(C)/6724(d)(2)",
            met=bool(all_reported_on_payee_statement),
            detail=(
                "caller confirmed a qualified payee statement (1099-DIV / 1099-INT / K-1 (1041) / "
                "K-3 (1065) / K-3 (1120-S) or substitute) covers all of it"
                if all_reported_on_payee_statement
                else "caller reported foreign income or tax NOT shown on a payee statement — "
                "904(j)(3)(A)/(B) exclude it from qualified passive income and creditable taxes"
            ),
        ),
        ForeignTaxCreditConditionCheck(
            condition="creditable foreign taxes do not exceed $300 ($600 in the case of a joint return)",
            statute="IRC 904(j)(2)(B)",
            met=within_limit,
            detail=(
                f"{_dollars(tested)} tested against the {_dollars(limit)} ceiling "
                f"({limit_basis}); "
                + (f"{_dollars(limit - tested)} of headroom" if within_limit else f"over by {_dollars(tested - limit)}")
            ),
        ),
        ForeignTaxCreditConditionCheck(
            condition="the filer is not an estate or trust",
            statute="IRC 904(j)(3)(D)",
            met=is_individual,
            detail=(
                "individual"
                if is_individual
                else f"entity is a {entity} — 'This subsection shall not apply to any estate or trust'"
            ),
        ),
    ]
    failed = [c.statute for c in conditions if not c.met]
    available = not failed
    election_made = bool(available and elect)
    conditions.append(
        ForeignTaxCreditConditionCheck(
            condition="the individual elects to have IRC 904(j) apply for the taxable year",
            statute="IRC 904(j)(2)(C)",
            met=election_made,
            detail=(
                "caller elected; the election is made by entering the credit directly on the "
                "return's foreign tax credit line, with no Form 1116 attached"
                if election_made
                else (
                    "caller chose Form 1116 even though the election was available — the right "
                    "call whenever there is an excess credit worth carrying under 904(c)"
                    if available
                    else "not reached: an earlier condition failed"
                )
            ),
        )
    )

    schedule_3_line = "Schedule 3 (Form 1040), Part I, line 1"
    claimed: int | None = None
    lost: int | None = None
    if regular_tax is not None:
        reg = _to_decimal(regular_tax, "regular_tax")
        if reg < 0:
            raise ValueError(
                f"regular_tax must be zero or more, got {_money(reg)} — it is Form 1116 line 20 "
                f"(individuals: Form 1040 line 16 plus Schedule 2 line 2, less any tax on line 16 "
                f"from Form 4972); if the amount is zero or less the Instructions say enter -0-"
            )
        reg_dollars = irs_round(reg)
        if election_made:
            claimed = min(tested, reg_dollars)
            lost = max(0, tested - reg_dollars)

    costs = [
        "IRC 904(j)(1)(B): no foreign tax paid or accrued in an election year may be carried to "
        "ANY other year — the 904(c) 1-year carryback and 10-year carryforward is forfeited for "
        "that year's taxes.",
        "IRC 904(j)(1)(C): and no foreign tax from any other year may be carried INTO an election "
        "year, so an existing carryforward cannot be used up in it (carryovers to and from other "
        "years are themselves unaffected).",
        "The election does NOT waive creditability: IRC 901/903 still decide whether a tax "
        "qualifies at all, including 901(k)'s minimum holding period for withholding tax on "
        "dividends — the trap for a fund position held briefly around a distribution.",
        "The election does NOT waive the Form 1116 line 12 reduction: 'You are still required to "
        "reduce the taxes available for credit by any amount you would have entered on line 12 of "
        "Form 1116.'",
        "IRC 904(j)(1)(A) turns the 904(a) limitation off, which is a simplification, not extra "
        "credit: the amount claimed is still capped at regular tax, and any excess above it is "
        "lost outright because (B) blocks the carryover.",
    ]
    if excess_credit_if_form_1116 is not None:
        excess = irs_round(_to_decimal(excess_credit_if_form_1116, "excess_credit_if_form_1116"))
        if excess > 0:
            costs.insert(
                0,
                f"CONCRETE COST HERE: {_dollars(excess)} of excess credit would be carried under "
                f"904(c) if Form 1116 were filed; electing 904(j) forfeits all of it.",
            )
    if lost:
        costs.insert(
            0,
            f"CONCRETE COST HERE: regular tax is smaller than the foreign tax, so {_dollars(lost)} "
            f"is not claimable this year and 904(j)(1)(B) makes it unrecoverable in any other year.",
        )

    category_box: str | None = None
    if all_foreign_income_passive:
        category_box = (
            "box c, Passive category income — the basket 1099-DIV box 7 / 1099-INT box 6 "
            "withholding belongs to (Form 1116 Part IV summarises it on line 27)"
        )

    assumptions = [
        f"creditable_foreign_taxes is taken as already limited to taxes creditable under IRC "
        f"901/903; this op tests the {_dollars(limit)} ceiling and does not re-decide "
        f"creditability.",
    ]
    if reduction > 0:
        gross_verdict = "PASSES" if gross_taxes <= limit else "FAILS"
        net_verdict = "PASSES" if tested_exact <= limit else "FAILS"
        assumptions.append(
            f"ORDERING — THIS OP'S READING, NOT A QUOTED RULE: the Form 1116 line 12 reduction of "
            f"{_money(reduction)} was subtracted BEFORE the {_dollars(limit)} test, so the tested "
            f"figure is {_money(tested_exact)} rather than the gross {_money(gross_taxes)}. The "
            f"Instructions sentence 'You are still required to reduce the taxes available for credit "
            f"by any amount you would have entered on line 12' sits under 'If you make this "
            f"election, the following rules apply' — among the CONSEQUENCES of electing, not as a "
            f"step in the eligibility test — so it does not set this order. The statutory basis is "
            f"904(j)(2)'s word 'creditable': a tax line 12 removes was never creditable. But the "
            f"reading is TAXPAYER-FAVOURABLE, and on these numbers it changes the answer: on the "
            f"NET basis the test {net_verdict}, on the GROSS basis it {gross_verdict}"
            + (
                ". THE TWO DISAGREE — have a preparer confirm the order before electing."
                if net_verdict != gross_verdict else
                ", so the order does not change the outcome here."
            )
        )
    if regular_tax is None and election_made:
        assumptions.append(
            "regular_tax was not supplied, so credit_on_schedule_3 is None: the election's amount "
            "is 'the smaller of (a) your total foreign tax, or (b) your regular tax' (Form 1116 "
            "line 20 = Form 1040 line 16 + Schedule 2 line 2, less Form 4972 tax). Pass it to get "
            "the number that goes on the return."
        )

    not_modeled = [
        "the 904(a) limitation fraction itself (Form 1116 lines 15-24) — that is the form's own "
        "math, and this op only decides whether the form is needed",
        "Schedule B (Form 1116) carryover reconciliation and Schedule C (Form 1116) foreign tax "
        "redeterminations",
        "the credit-versus-DEDUCTION choice (a foreign income tax may instead be an itemized "
        "deduction, all-or-nothing for the year — Pub 514)",
        "whether each foreign levy is a creditable income tax or an in-lieu-of tax (IRC 901/903, "
        "the 901(k) holding period, and Treas. Reg. 1.901-2)",
        "US Virgin Islands tax, which uses Form 8689 rather than Form 1116",
        "the nonresident-alien restriction of IRC 906 (a nonresident generally cannot take the "
        "credit at all)",
    ]

    lines = [
        f"IRC 904(j) de-minimis foreign tax credit election — tax year {year}, {status.replace('_', ' ')}, {entity}.",
        f"  Creditable foreign taxes as passed .......... {_money(gross_taxes)}",
    ]
    if reduction > 0:
        lines.append(f"  Less Form 1116 line 12 reduction ............ {_money(reduction)}")
        lines.append(f"  Tested amount ............................... {_money(tested_exact)} -> {_dollars(tested)} (IRS rounding)")
    else:
        lines.append(f"  Tested amount ............................... {_dollars(tested)} (IRS rounding)")
    lines.append(f"  IRC 904(j)(2)(B) ceiling .................... {_dollars(limit)}  [{limit_basis}]")
    lines.append("  Conditions (IRC 904(j)):")
    for check in conditions:
        lines.append(f"    [{'x' if check.met else ' '}] {check.statute}: {check.condition}")
        lines.append(f"        {check.detail}")
    if election_made:
        lines.append(
            "  => NO FORM 1116. Make the election by entering the credit directly on "
            f"{schedule_3_line}: 'To make the election, just enter on the foreign tax credit line "
            "of your tax return (for example, Schedule 3 (Form 1040), Part I, line 1) the smaller "
            "of (a) your total foreign tax, or (b) your regular tax.'"
        )
        if claimed is not None:
            lines.append(
                f"     smaller of foreign tax {_dollars(tested)} and regular tax "
                f"{_dollars(irs_round(_to_decimal(regular_tax, 'regular_tax')))} = {_dollars(claimed)}"
            )
            if lost:
                lines.append(
                    f"     {_dollars(lost)} of foreign tax exceeds regular tax and is LOST — "
                    f"904(j)(1)(B) blocks carrying it to any other year."
                )
    elif available:
        lines.append(
            "  => The election was AVAILABLE and you declined it, so Form 1116 is required. That "
            "is the right choice whenever the excess credit is worth carrying under 904(c)."
        )
    else:
        lines.append(
            "  => FORM 1116 IS REQUIRED. Failed: " + ", ".join(failed) + ". File Form 1116 for "
            "each category of income, checking exactly one box above Part I."
        )
        if category_box:
            lines.append(f"     For the passive basket that is {category_box}.")
    lines.append("  What the election costs:")
    lines.extend(f"    - {cost}" for cost in costs)

    return ForeignTaxCreditElectionResult(
        form_1116_required=not election_made,
        election_available=available,
        election_made=election_made,
        route="schedule_3_election" if election_made else "form_1116",
        de_minimis_limit=limit,
        limit_basis=limit_basis,
        creditable_foreign_taxes=tested,
        headroom=limit - tested,
        conditions=conditions,
        failed_conditions=failed,
        credit_on_schedule_3=claimed,
        schedule_3_line=schedule_3_line,
        credit_lost_to_regular_tax_cap=lost,
        election_costs=costs,
        form_1116_category_box=None if election_made else category_box,
        # None rather than a path that does not exist: f1116 ships for 2023-2025
        # only, and a caller following an invented key hits FileNotFoundError
        # (found 2026-08-27 by the adversarial review, which walked 2019-2022).
        form_1116_pack_key=(
            f"formpacks/federal/{year}/f1116"
            if (Path(__file__).resolve().parents[4] / "formpacks" / "federal" / str(year) / "f1116").is_dir()
            else None
        ),
        not_modeled=not_modeled,
        input_assumptions=assumptions,
        inputs={
            "creditable_foreign_taxes": str(gross_taxes),
            "reduction_in_foreign_taxes": str(reduction),
            "all_foreign_income_passive": bool(all_foreign_income_passive),
            "all_reported_on_payee_statement": bool(all_reported_on_payee_statement),
            "year": year,
            "filing_status": status,
            "elect": bool(elect),
            "entity": entity,
            "regular_tax": None if regular_tax is None else str(_to_decimal(regular_tax, "regular_tax")),
            "excess_credit_if_form_1116": (
                None if excess_credit_if_form_1116 is None
                else str(_to_decimal(excess_credit_if_form_1116, "excess_credit_if_form_1116"))
            ),
        },
        work="\n".join(lines),
        citation=_IRC_904J_CITATION,
        citations=[
            _IRC_904J_CITATION,
            _IRC_901_CITATION,
            _IRC_904A_CITATION,
            Citation(
                source=(
                    f"Instructions for Form 1116 ({year}), General Instructions, 'Election To Claim "
                    f"the Foreign Tax Credit Without Filing Form 1116' (every condition, the "
                    f"carryover forfeiture, the estates-and-trusts exclusion, the qualified payee "
                    f"statements, and how to make the election) and the Line 20 instructions (how "
                    f"to figure the 'regular tax' the election is capped at)."
                ),
                url=f"https://www.irs.gov/pub/irs-prior/i1116--{year}.pdf",
            ),
            Citation(
                source=(
                    f"Form 1116 ({year}), the form the election avoids: category boxes a-g above "
                    f"Part I ('Check only one box on each Form 1116'), Part I's three-country "
                    f"column grid, Part II's Paid/Accrued method election, Part III lines 15-23 "
                    f"(the 904(a) limitation the election turns off) and line 35 ('Enter here and "
                    f"on Schedule 3 (Form 1040), line 1')."
                ),
                url=f"https://www.irs.gov/pub/irs-prior/f1116--{year}.pdf",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Treaty benefit (Schedule OI item L / Form 1040-NR line 1k) — Phase G item G1
# ---------------------------------------------------------------------------

TREATY_INCOME_CLASSES: tuple[str, ...] = (
    "student_wages",
    "scholarship",
    "payments_from_abroad",
    "teacher_wages",
    "other_income",
)

# The eligibility facts this op does NOT decide — appended to every work string
# so the number is never mistaken for an eligibility ruling.
_TREATY_JUDGMENT_NOTE = (
    " This op VALIDATES the article and dollar limits only — final eligibility (visa category and "
    "the exact visa PERIOD the income was earned in, purpose of the visit, residence in the treaty "
    "country before US entry, and the saving-clause analysis) stays the AGENT'S judgment with the "
    "user; record the decided position with this citation."
)

# ── the DISCLOSURE half of a treaty position (Phase I4: the f8833 packs) ──────
#
# Every source below was opened, not recalled:
#   IRC 6114(a)/(b)          — uscode.house.gov, title 26 section 6114
#   IRC 6712(a)/(b)/(c)      — uscode.house.gov, title 26 section 6712
#   Treas. Reg. 301.6114-1   — ecfr.gov, 26 CFR 301.6114-1 (the (b) list, the
#                              (c) waivers, and (d)(1)'s "fully completed
#                              Form 8833")
#   Treas. Reg. 301.7701(b)-7(a)(1), (b), (c)(1)(i)  — ecfr.gov
#   Form 8833 (Rev. 12-2022) face + instructions pp. 3-4 — irs.gov/pub/irs-pdf/f8833.pdf
#
# Why this is on EVERY work string, and why it leads with the WAIVER: the form
# is not always required, and the failure mode in both directions is expensive.
# Telling a China Art. 20(c) student they must file Form 8833 is wrong law
# (301.6114-1(c)(1)(iv) and (c)(2) both waive it); saying nothing at all leaves
# a residency / dual-resident filer exposed to the 6712 penalty on a disclosure
# that has NO waiver. So the note states the requirement, the penalty, the
# waivers that cover this op's usual population, and the two positions that are
# genuinely reportable.
_TREATY_DISCLOSURE_NOTE = (
    " DISCLOSURE — the form, and whether you actually need it: a treaty-based return position is "
    "disclosed on Form 8833, 'Treaty-Based Return Position Disclosure Under Section 6114 or "
    "7701(b)' (current revision Rev. 12-2022; packs at formpacks/federal/{2023,2024,2025}/f8833), "
    "attached to the return — IRC 6114(a) requires the disclosure and Treas. Reg. 301.6114-1(d)(1) "
    "makes THIS form the vehicle ('a fully completed Form 8833'), one form per position (printed on "
    "the form's own face). An undisclosed position that needed disclosing costs $1,000 ($10,000 for "
    "a C corporation) per failure under IRC 6712(a), waivable only on reasonable cause AND good "
    "faith (6712(b)) and additive to any other penalty (6712(c)). BUT CHECK THE WAIVER FIRST — most "
    "of what this op computes is WAIVED and needs no Form 8833: Treas. Reg. 301.6114-1(c)(1)(iv) "
    "waives a position that a treaty reduces or modifies the taxation of income from dependent "
    "personal services or of 'income derived by artistes, athletes, students, trainees or "
    "teachers', which covers every student_wages / scholarship / payments_from_abroad / "
    "teacher_wages claim here (the Form 8833 instructions, Rev. 12-2022 p. 3, 'Exceptions from "
    "reporting', print the same waiver as a bullet, spelling it 'artists' — the quotation above "
    "is the REGULATION's wording), and 301.6114-1(c)(2) independently waives an "
    "individual whose otherwise-reportable items total $10,000 or less for the taxable year. A "
    "China Art. 20(c) $5,000 student-wage exemption is therefore waived twice over. WHAT IS NOT "
    "WAIVED, and is the real 8833 case in this lane: that your RESIDENCY is determined under the "
    "treaty and apart from the Code (301.6114-1(b)(8) — specifically required, and its (c)(2) "
    "threshold is $100,000, not $10,000), and the DUAL-RESIDENT TAXPAYER statement, which Treas. "
    "Reg. 301.7701(b)-7(b) and (c)(1)(i) require as 'a fully completed Form 8833' attached to Form "
    "1040-NR with no 301.6114-1(c) waiver reaching it at all. Filing the form when it is waived is "
    "permitted and harmless; skipping it when it is not is the penalty."
)

# other_income never grants relief in any shipped treaty (all five packs' Other
# Income articles leave US-arising items US-taxable), so nothing on that branch
# reduces US tax, no treaty-based return position is taken, and section 6114 is
# not triggered by it. Said before the general note, or the note reads as a duty
# that does not exist here.
_TREATY_DISCLOSURE_NO_POSITION = (
    " DISCLOSURE: because no article reduces the US tax on this item, NO treaty-based return "
    "position is taken on it and IRC 6114 is not triggered by this branch — there is nothing to "
    "disclose for it. If you take some OTHER treaty position on the same return, that one is "
    "disclosed as follows."
)


def _treaty_disclosure_note(income_class: str) -> str:
    """The Form 8833 pointer appended to every ``treaty_benefit`` work string.

    Changes no number: this is the disclosure half of the same position the op
    just priced.

    Only ``other_income`` gets the extra "no position taken" sentence. The
    tempting shortcut — key it on ``exempt_amount == 0`` — is WRONG, and India is
    the counterexample: ``india``/``student_wages`` exempts $0 and still rests on
    a treaty position, because Art. 21(2)'s deduction parity is a treaty
    provision overriding the Code's no-standard-deduction rule for a
    nonresident. A $0 exemption therefore does not mean no position was taken.
    """
    head = _TREATY_DISCLOSURE_NO_POSITION if income_class == "other_income" else ""
    return head + _TREATY_DISCLOSURE_NOTE


class TreatyBenefitResult(BaseModel):
    """Result of :func:`treaty_benefit`: the exempt/taxable split plus its audit trail."""

    model_config = ConfigDict(extra="forbid")

    exempt_amount: int = Field(description="Whole-dollar amount the treaty article supports as exempt.")
    taxable_remainder: int = Field(description="amount - exempt_amount: the part NO treaty article covers.")
    country: str = Field(description="Normalized treaty-pack country key (e.g. 'china').")
    income_class: str = Field(description="One of student_wages, scholarship, payments_from_abroad, teacher_wages.")
    article: str | None = Field(
        description="The treaty article relied on (None when the treaty has no article granting this benefit)."
    )
    limits_applied: list[str] = Field(description="Every limit/condition that shaped the number, spelled out.")
    inputs: dict[str, Any]
    work: str
    citation: Citation


def _treaty_saving_clause_text(saving_clause_exception: bool, text: str | None) -> str:
    if saving_clause_exception:
        detail = f" ({text})" if text else ""
        return f" Saving-clause exception applies{detail}."
    return " NO saving-clause exception — the benefit ends if the filer becomes a US resident."


def treaty_benefit(
    country: str,
    income_class: str,
    amount: int | float | Decimal | str,
    visa_periods: list[dict[str, Any]] | None = None,
    year: int = 2023,
    years_in_status: int | None = None,
    knowledge_dir: str | Path | None = None,
) -> TreatyBenefitResult:
    """Validate/compute a treaty exemption from the per-country treaty knowledge pack.

    Replaces the pure trust-the-agent semantics of ``treaty_exempt_income``:
    the dollar split comes from the versioned ``knowledge/treaties/<country>.yaml``
    (China, India, Korea, Canada, Mexico — treaty-fixed amounts, cited to the
    irs.gov treaty PDFs and Pub 901 (Rev. 9-2024)), never from model memory.
    The op computes and VALIDATES; the final eligibility judgment (visa
    category/period, purpose of visit, saving clause) stays with the agent —
    every ``work`` string says so, and each pack carries a ``disclaimer``.

    ``income_class`` semantics:

    * ``student_wages`` — US-source personal-services income during study/
      training. Exempt up to the treaty's compensation limit when one exists
      (China Art. 20(c) $5,000/yr; Korea Art. 21(1)(b)(iii) $2,000/yr).
      India has NO dollar exclusion: exempt $0, and the work explains the
      Art. 21(2) standard-deduction-parity rule instead (the estimate models
      it by setting itemized_deductions to the standard-deduction amount).
      Canada has NO student exclusion either — the Art. XV $10,000 employment
      de-minimis is applied instead (ALL-OR-NOTHING per calendar year, and it
      belongs to every Canadian-resident employee, not only students). Mexico
      has NO wage benefit and NO dollar de-minimis (verified) — only the
      three-part 183-day test, which is a facts question left to the agent.
    * ``scholarship`` — grant/fellowship amounts. Fully exempt where the
      treaty exempts grants as such (China Art. 20(b), Korea Art. 21(1)(b)(ii));
      $0 otherwise (India: Art. 21(2) parity instead; Canada/Mexico: only
      payments from outside the US — use ``payments_from_abroad``).
    * ``payments_from_abroad`` — maintenance/education payments arising
      outside the US. Fully exempt under every shipped treaty, subject to the
      source/purpose conditions quoted in the work.
    * ``teacher_wages`` — requires ``years_in_status`` (which year of the
      teacher-article window this is, counted on the treaty's basis). Fully
      exempt within the window; $0 beyond it — and for India the loss is
      RETROACTIVE (the WHOLE visit's exemption is lost, Pub 901 p. 25), which
      the work flags loudly. Canada/Mexico have no teacher article at all.
    * ``other_income`` — the bank-bonus / 1099-MISC box 3 corner (H9,
      pitfall P-005): validates against the treaty's Other Income article,
      transcribed verbatim into the pack. No dollar limit exists — the
      answer is an ARTICLE rule, and in all five shipped treaties US-arising
      other income of a treaty-country resident REMAINS US-taxable (China
      Art. 21(3) / India Art. 23(3) / Canada Art. XXII(1) carve it back to
      the source state; Mexico Art. 23 is source-state-only in form; Korea
      (1976) verifiably has NO other-income article, so Art. 4(1)'s source
      rule applies). Exempt is always $0; the work carries the law and the
      Schedule NEC 30% consequence.

    ``visa_periods`` (optional, ``[{status, start, end?}, ...]``) is echoed
    into the inputs and the work so the per-period eligibility analysis
    (pitfall P-004) is attached to the number — it is NOT evaluated here.
    ``year`` is contextual only: treaty dollar limits are treaty-fixed.
    """
    amt = _to_decimal(amount, "amount")
    if amt < 0:
        raise ValueError(f"amount must be >= 0, got {amt} — pass the income amount being tested")
    if income_class not in TREATY_INCOME_CLASSES:
        raise ValueError(
            f"unknown income_class {income_class!r} — use one of: {', '.join(TREATY_INCOME_CLASSES)}"
        )
    # Prescriptive FileNotFoundError (lists shipped countries) propagates as-is.
    pack = load_treaty(country, base_dir=knowledge_dir)
    amount_whole = irs_round(amt)
    label = pack.country.replace("_", " ").title()
    inputs: dict[str, Any] = {
        "country": pack.country,
        "income_class": income_class,
        "amount": str(amt),
        "year": year,
    }
    if years_in_status is not None:
        inputs["years_in_status"] = years_in_status
    if visa_periods:
        inputs["visa_periods"] = visa_periods
    limits: list[str] = []
    period_note = (
        " Visa periods were supplied for YOUR per-period eligibility analysis (P-004) — they were "
        "echoed, not evaluated."
        if visa_periods
        else ""
    )

    def _result(exempt: int, article: str | None, work: str, citation: Citation) -> TreatyBenefitResult:
        return TreatyBenefitResult(
            exempt_amount=exempt,
            taxable_remainder=amount_whole - exempt,
            country=pack.country,
            income_class=income_class,
            article=article,
            limits_applied=limits,
            inputs=inputs,
            work=(
                work
                + period_note
                + _TREATY_JUDGMENT_NOTE
                + _treaty_disclosure_note(income_class)
            ),
            citation=citation,
        )

    # H9/P-005: the Other Income article decides whether a US-arising item not
    # covered by any named article (bank bonus, 1099-MISC box 3) gets a treaty
    # rate. Handled before the student-block check — it needs no student data.
    if income_class == "other_income":
        oi = pack.other_income
        if oi is None:
            raise ValueError(
                f"treaty pack for {pack.country!r} has no other_income block — author it from the "
                f"treaty text with a verbatim citation (see knowledge/treaties/china.yaml); do NOT "
                f"assume either a shelter or its absence"
            )
        limits.append("no dollar exemption — the other-income analysis is an ARTICLE question, not a limit")
        if oi.article is None:
            opening = (
                f"{label} other income ({year}): the treaty has NO Other Income article (verified "
                f"absence). {oi.rule_text.strip()}"
            )
        else:
            opening = f"{label} other income ({year}): {oi.article}. {oi.rule_text.strip()}"
        consequence = (
            " Consequence: US-arising other income of a treaty-country resident REMAINS US-taxable — "
            "on Form 1040-NR it lands on Schedule NEC at the statutory 30% rate (IRC 871(a)) unless a "
            "DIFFERENT article covers the specific item; there is no other-income treaty reduction. "
            "Exempt $0 of the amount tested."
            if oi.us_source_other_income_taxable_by_us
            else " Consequence: see the article text — source-state taxation is limited; record the "
                 "position with the article citation."
        )
        work = opening + (f" {oi.notes.strip()}" if oi.notes.strip() else "") + consequence
        # No shipped treaty shelters US-arising other income, and a rate question
        # is not a dollar split — exempt stays 0 either way; the work carries the law.
        return _result(0, oi.article, work, oi.citation)

    student = pack.student
    if student is None:  # defensive: every shipped pack has a student block
        raise ValueError(
            f"treaty pack for {pack.country!r} has no student block — author it from the treaty text "
            f"and Pub 901 with a citation (see knowledge/treaties/china.yaml)"
        )

    if income_class == "student_wages":
        if student.compensation_limit is not None:
            limit = student.compensation_limit
            exempt = min(amount_whole, limit)
            limits.append(
                f"{student.compensation_limit_ref} compensation limit: {_dollars(limit)} per taxable year "
                f"(treaty-fixed, not indexed)"
            )
            limits.append(f"time limit: {student.time_limit_text}")
            work = (
                f"{label} student wages ({year}): {student.article} exempts US personal-services income up "
                f"to {_dollars(limit)} per taxable year ({student.compensation_limit_ref}) — exempt = "
                f"min({_dollars(amount_whole)}, {_dollars(limit)}) = {_dollars(exempt)}; taxable remainder "
                f"{_dollars(amount_whole - exempt)}. Scholarship grants and payments from abroad are "
                f"separately exempt WITHOUT this limit (use income_class 'scholarship' / "
                f"'payments_from_abroad'). Time limit: {student.time_limit_text}."
                + _treaty_saving_clause_text(student.saving_clause_exception, student.saving_clause_exception_text)
            )
            return _result(exempt, student.article, work, student.citation)
        if student.special_rule is not None:  # India Art. 21(2): parity, not an exclusion
            limits.append(f"no dollar exclusion for US-source wages under {student.article}")
            work = (
                f"{label} student wages ({year}): {student.article} provides NO dollar exclusion for "
                f"US-source wages — exempt $0 of {_dollars(amount_whole)}. Instead: {student.special_rule} "
                f"The engine models that parity rule on a Form 1040-NR estimate by setting "
                f"itemized_deductions to the standard-deduction amount (see estimate_refund's India note) — "
                f"do NOT enter the wages as treaty_exempt_income. Payments arising outside the US remain "
                f"separately exempt (income_class 'payments_from_abroad')."
                + _treaty_saving_clause_text(student.saving_clause_exception, student.saving_clause_exception_text)
            )
            return _result(0, student.article, work, student.citation)
        dm = pack.employment_de_minimis
        if dm is not None and dm.amount is not None:  # Canada Art. XV $10,000 all-or-nothing
            if amount_whole <= dm.amount:
                limits.append(
                    f"{dm.article}: {_dollars(dm.amount)} calendar-year de-minimis — ALL-OR-NOTHING "
                    f"(total US employment remuneration at or under the threshold is taxable only in the "
                    f"residence state; one dollar over loses it entirely)"
                )
                work = (
                    f"{label} student wages ({year}): {student.article} has NO student wage exclusion; the "
                    f"applicable relief is {dm.amount_text} — an employment rule for ANY {label}-resident "
                    f"employee, not a student benefit. {_dollars(amount_whole)} does not exceed "
                    f"{_dollars(dm.amount)}, so the WHOLE amount is exempt — PROVIDED this is the filer's "
                    f"TOTAL US employment remuneration for the calendar year (the threshold is "
                    f"all-or-nothing, never a per-dollar cap)."
                )
                return _result(amount_whole, dm.article, work, dm.citation)
            limits.append(
                f"{dm.article}: {_dollars(dm.amount)} de-minimis is ALL-OR-NOTHING and "
                f"{_dollars(amount_whole)} exceeds it — $0 exempt under the dollar rule"
            )
            work = (
                f"{label} student wages ({year}): {student.article} has NO student wage exclusion, and "
                f"{_dollars(amount_whole)} EXCEEDS the {dm.article} {_dollars(dm.amount)} all-or-nothing "
                f"calendar-year de-minimis, so the dollar rule exempts $0 (it is a cliff, not a cap). The "
                f"only remaining path is the alternative test — {dm.alternative_test} — a facts question "
                f"this op does not decide."
            )
            return _result(0, dm.article, work, dm.citation)
        if dm is not None:  # Mexico: no dollar de-minimis at all
            limits.append(f"no student wage exclusion ({student.article}) and no dollar de-minimis ({dm.article})")
            work = (
                f"{label} student wages ({year}): {student.article} has NO wage exclusion, and there is NO "
                f"dollar de-minimis for employment income — {dm.amount_text}. Exempt $0 of "
                f"{_dollars(amount_whole)}. The only possible exemption is the three-part test — "
                f"{dm.alternative_test} — a facts question this op does not decide. Payments arising from "
                f"or remitted from outside the US remain separately exempt (income_class "
                f"'payments_from_abroad')."
            )
            return _result(0, dm.article, work, dm.citation)
        limits.append(f"no student wage benefit under the US-{label} treaty")
        work = (
            f"{label} student wages ({year}): the treaty provides no US-source wage benefit — exempt $0 of "
            f"{_dollars(amount_whole)}."
        )
        return _result(0, student.article, work, student.citation)

    if income_class == "scholarship":
        if student.scholarship_exempt:
            limits.append(f"scholarship exemption: {student.scholarship_text or student.article}")
            limits.append(f"time limit: {student.time_limit_text}")
            work = (
                f"{label} scholarship/grant ({year}): {student.article} exempts qualifying grants in full — "
                f"{student.scholarship_text}. Exempt {_dollars(amount_whole)} of {_dollars(amount_whole)}. "
                f"Confirm the payor is a qualifying organization. Time limit: {student.time_limit_text}."
                + _treaty_saving_clause_text(student.saving_clause_exception, student.saving_clause_exception_text)
            )
            return _result(amount_whole, student.article, work, student.citation)
        limits.append(f"no scholarship exclusion as such under {student.article}")
        alternative = (
            f" Instead: {student.special_rule}"
            if student.special_rule
            else f" {student.scholarship_text}"
            if student.scholarship_text
            else ""
        )
        work = (
            f"{label} scholarship/grant ({year}): {student.article} does NOT exempt grants as such — "
            f"exempt $0 of {_dollars(amount_whole)}.{alternative} If the payments arise from or are "
            f"remitted from outside the US, test them as income_class 'payments_from_abroad' instead."
        )
        return _result(0, student.article, work, student.citation)

    if income_class == "payments_from_abroad":
        if student.payments_from_abroad_exempt:
            limits.append(f"source/purpose condition: {student.payments_from_abroad_text or student.article}")
            limits.append(f"time limit: {student.time_limit_text}")
            work = (
                f"{label} payments from abroad ({year}): {student.article} exempts them in full — "
                f"{student.payments_from_abroad_text}. Exempt {_dollars(amount_whole)} of "
                f"{_dollars(amount_whole)}, PROVIDED the quoted source/purpose conditions hold (payments "
                f"must actually arise/be remitted from outside the US). Time limit: {student.time_limit_text}."
                + _treaty_saving_clause_text(student.saving_clause_exception, student.saving_clause_exception_text)
            )
            return _result(amount_whole, student.article, work, student.citation)
        limits.append(f"no payments-from-abroad exemption under {student.article}")
        work = (
            f"{label} payments from abroad ({year}): {student.article} does not exempt them — exempt $0 of "
            f"{_dollars(amount_whole)}."
        )
        return _result(0, student.article, work, student.citation)

    # income_class == "teacher_wages"
    teacher = pack.teacher_researcher
    if teacher is None:
        limits.append(f"no teacher/professor article exists in the US-{label} treaty (verified)")
        work = (
            f"{label} teacher/researcher wages ({year}): the US-{label} treaty has NO teacher/professor "
            f"article (verified against the treaty text; Pub 901 (Rev. 9-2024) lists no {label} entry in "
            f"its Professors/Teachers section) — there is NO such benefit to claim: exempt $0 of "
            f"{_dollars(amount_whole)}. Do not put teacher wages on Schedule OI for this country."
        )
        return _result(0, None, work, pack.citation)
    if years_in_status is None:
        raise ValueError(
            f"teacher_wages for {pack.country!r} requires years_in_status — which year of the "
            f"{teacher.article} window this is, counted as: {teacher.years_basis}. The exemption runs "
            f"{teacher.years} years; pass years_in_status=1 for the first year."
        )
    if years_in_status < 1:
        raise ValueError(f"years_in_status must be >= 1 (the first exemption year is 1), got {years_in_status}")
    conditions_note = f" Conditions: {teacher.conditions}."
    if years_in_status <= teacher.years:
        limits.append(
            f"{teacher.years}-year window ({teacher.years_basis}): year {years_in_status} of "
            f"{teacher.years} — within the window"
        )
        warning = ""
        if teacher.retroactive_loss:
            warning = (
                f" WARNING — RETROACTIVE LOSS RISK: {teacher.retroactive_loss_text} If the visit ends up "
                f"exceeding {teacher.years} years, the WHOLE exemption (including this year's) is lost and "
                f"already-filed returns must be amended — confirm the expected visit length before claiming."
            )
            limits.append(
                f"retroactive-loss clause: exceeding the {teacher.years}-year visit forfeits the ENTIRE "
                f"exemption, not just the excess years"
            )
        work = (
            f"{label} teacher/researcher wages ({year}): {teacher.article} exempts them in full for "
            f"{teacher.years} years ({teacher.years_basis}); year {years_in_status} is within the window — "
            f"exempt {_dollars(amount_whole)} of {_dollars(amount_whole)}.{conditions_note}{warning}"
            + _treaty_saving_clause_text(teacher.saving_clause_exception, teacher.saving_clause_exception_text)
        )
        return _result(amount_whole, teacher.article, work, teacher.citation)
    # Beyond the window.
    if teacher.retroactive_loss:
        limits.append(
            f"{teacher.years}-year window exceeded (year {years_in_status}) with RETROACTIVE loss — the "
            f"WHOLE exemption is lost, including prior years"
        )
        work = (
            f"{label} teacher/researcher wages ({year}): year {years_in_status} EXCEEDS the "
            f"{teacher.article} {teacher.years}-year window ({teacher.years_basis}) — exempt $0 of "
            f"{_dollars(amount_whole)}. WARNING — RETROACTIVE LOSS: {teacher.retroactive_loss_text} The "
            f"WHOLE exemption is lost for the ENTIRE visit — not just this year: exemptions already claimed "
            f"for earlier years are forfeited too, and those returns must be AMENDED to add the income "
            f"back.{conditions_note}"
        )
        return _result(0, teacher.article, work, teacher.citation)
    limits.append(
        f"{teacher.years}-year window exceeded (year {years_in_status}) — loss is prospective only; "
        f"earlier years keep their exemption"
    )
    work = (
        f"{label} teacher/researcher wages ({year}): year {years_in_status} EXCEEDS the {teacher.article} "
        f"{teacher.years}-year window ({teacher.years_basis}) — exempt $0 of {_dollars(amount_whole)} for "
        f"this year. The loss is PROSPECTIVE only ({teacher.retroactive_loss_text}): earlier in-window "
        f"years keep their exemption.{conditions_note}"
    )
    return _result(0, teacher.article, work, teacher.citation)


# ---------------------------------------------------------------------------
# State income tax (Phase G item G4 — the state tax line, flat or graduated)
# ---------------------------------------------------------------------------

_STATE_TAX_BASE_LABELS = {
    "federal_agi": (
        "the state's own income base derived from federal AGI plus/minus the state's additions and "
        "subtractions (NOT raw federal AGI when modifications apply)"
    ),
    "federal_taxable_income": (
        "the state's own income base derived from federal TAXABLE income plus/minus the state's "
        "additions and subtractions (the federal standard/itemized deduction is already embedded)"
    ),
    "state_gross_income": (
        "the state's OWN gross-income computation (never federal AGI) — for PA, the sum of the eight "
        "separately-computed PA income classes, where a loss in one class never offsets another"
    ),
    "state_taxable_income": (
        "the state form's OWN taxable-income line, with the state's deductions/exemptions already "
        "computed on the form (this state's deduction is income-dependent or otherwise not a fixed "
        "amount the op could subtract)"
    ),
}


def _graduated_state_tax(
    brackets: list["StateRateBracket"], base_after: int
) -> tuple[Decimal, Decimal, list[str]]:
    """Marginal-bracket tax over ``base_after``: (exact total, marginal rate, per-bracket work lines)."""
    total = Decimal(0)
    lines: list[str] = []
    marginal = brackets[0].rate
    for bracket in brackets:
        if base_after <= bracket.over:
            break
        upper = base_after if bracket.but_not_over is None else min(base_after, bracket.but_not_over)
        portion = Decimal(upper) - Decimal(bracket.over)
        marginal = bracket.rate
        amount = portion * bracket.rate
        total += amount
        lines.append(
            f"{bracket.rate} x {_money(portion)} (the {_dollars(bracket.over)}"
            + (f"-{_dollars(bracket.but_not_over)}" if bracket.but_not_over is not None else "+")
            + f" bracket) = {_money(amount)}"
        )
    return total, marginal, lines


def _states_with_tax_block(year: int, base_dir: str | Path | None) -> list[str]:
    """The state codes whose ``knowledge/states/<st>/<year>.yaml`` ships a ``tax`` block."""
    from taxfill_core.datadir import knowledge_dir as _default_knowledge_dir

    base = Path(base_dir) if base_dir is not None else _default_knowledge_dir()
    states_dir = base / "states"
    if not states_dir.is_dir():
        return []
    shipped: list[str] = []
    for path in sorted(states_dir.glob(f"*/{year}.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(raw, dict) and isinstance(raw.get("tax"), dict):
            shipped.append(path.parent.name)
    return shipped


class StateTaxResult(BaseModel):
    """Result of :func:`state_tax`: the state's tax line plus its audit trail."""

    model_config = ConfigDict(extra="forbid")

    tax: int = Field(description="Whole-dollar state income tax for the state form's tax line.")
    rate: Decimal | None = Field(
        description="The state's flat rate as an exact decimal fraction (e.g. 0.0495); "
        "None for a graduated-bracket state (see marginal_rate and the work string)."
    )
    rate_structure: str = Field(description="'flat' or 'graduated' — which computation the state's pack ships.")
    marginal_rate: Decimal = Field(
        description="The marginal rate applied to the last dollar of the base: the flat rate for a "
        "flat state, the rate of the bracket the base lands in for a graduated state."
    )
    base_after_exemptions: int = Field(
        description="max(0, taxable_base - applied exemptions - standard deduction), whole dollars — "
        "the amount the rate/brackets were applied to."
    )
    state: str = Field(description="Two-letter lowercase state code the pack was loaded for.")
    base_kind: str = Field(
        description="Which figure the state's form starts from: federal_agi, federal_taxable_income, "
        "state_gross_income, or state_taxable_income."
    )
    inputs: dict[str, Any]
    work: str
    citation: Citation


def state_tax(
    state: str,
    taxable_base: int | float | Decimal | str,
    year: int = 2023,
    exemptions_count: int = 0,
    dependents_count: int = 0,
    filing_status: str = "single",
    knowledge_dir: str | Path | None = None,
) -> StateTaxResult:
    """The STATE income-tax line, from the state pack's cited ``tax`` block.

    Phase G item G4. First tranche: the eight flat-rate 2023 states — IL, PA,
    IN, MI, NC, CO, KY, AZ. Second tranche: the graduated-bracket states,
    whose packs ship per-filing-status marginal schedules instead of a flat
    rate. The op computes::

        base_after = max(0, taxable_base
                            - personal_exemption x exemptions_count
                            - dependent_exemption x dependents_count
                            - standard_deduction[filing_status])   # where the state ships one
        tax        = irs_round(base_after x flat_rate)             # flat-rate states
        tax        = irs_round(sum of marginal-bracket amounts)    # graduated states

    For a graduated state the schedule for ``filing_status`` is applied
    bracket by bracket (qualifying surviving spouse resolves to the
    married_filing_jointly schedule) and the work string shows every
    bracket's contribution. Pack ``notes`` — quoted in the work — carry the
    state's own caveats: tax-table mandates below an income threshold (the
    filed form must use the booklet table, which can differ from bracket math
    by a few dollars within a band), surcharges/recaptures OUTSIDE the
    schedule (e.g. CA's 1% Mental Health Services Tax over $1M; NY's
    worksheet recapture above $107,650 NY AGI, where plain bracket math is
    WRONG), and local add-on taxes (e.g. MD's mandatory county rate).

    ``taxable_base`` is the CALLER'S job and differs per state — supply the
    state's OWN base, already adjusted for the state's additions/subtractions:

    * IL — federal AGI +/- IL modifications (IL-1040 Line 9 base income);
      the op subtracts the Line 10 personal exemptions and multiplies by 4.95%.
    * IN — federal AGI +/- IN add-backs/deductions (IT-40 Line 5); the op
      subtracts the Schedule 3 personal/dependent exemptions ($1,000 each)
      and multiplies by 3.15%. Indiana COUNTY tax is NOT modeled.
    * MI — federal AGI +/- Schedule 1 modifications (MI-1040 Line 14); the op
      subtracts the $5,400 exemptions and multiplies by 4.05% (2023-only rate).
      Michigan CITY income taxes are NOT modeled.
    * NC — federal AGI +/- NC adjustments (D-400 Lines 6-9); the op subtracts
      the N.C. standard deduction by filing status and multiplies by 4.75%.
      The AGI-tiered child deduction (Line 10) and itemized deductions are NOT
      modeled — pass dependents_count=0 and see the pack notes.
    * KY — federal AGI +/- Schedule M modifications (Form 740 Line 9 Kentucky
      AGI); the op subtracts the single $2,980 standard deduction (ONE per
      return, even filing jointly) and multiplies by 4.5%.
    * AZ — federal AGI +/- AZ modifications through Form 140 line 37, MINUS
      any line 38-41 exemptions you compute on the form (age 65+ $2,100, blind
      $1,500, other $2,300, qualifying parent/grandparent $10,000 — the op
      does NOT apply them); the op subtracts the standard deduction (2023
      federal amounts) and multiplies by 2.5%. AZ has NO personal exemption;
      dependents are the Line 49 CREDIT, not a base reduction.
    * CO — federal TAXABLE income +/- CO modifications (DR 0104 Line 10);
      no exemptions or deduction (already embedded federally); 4.4%. The filed
      form uses the booklet tax table, which can differ from raw
      multiplication by a few dollars within its $100 bands.
    * PA — the PA-source gross by class (PA-40 Line 11 adjusted PA taxable
      income): the op multiplies the supplied base by 3.07% only — PA has no
      exemptions and no standard deduction, and a loss in one class never
      offsets another. Pass exemptions_count=0 and dependents_count=0.

    For the graduated second-tranche states the equivalent base guidance
    ships in the pack itself — each pack's ``tax_line`` and ``notes`` (quoted
    verbatim in the work string) name the exact form line to supply, and
    ``base_kind`` says which figure it derives from. ``state_taxable_income``
    packs take the form's OWN taxable-income line (the state's deduction is
    income-dependent, e.g. WI's sliding standard deduction, so the caller
    computes it on the form).

    ``exemptions_count`` counts the PERSONAL exemptions (taxpayer + spouse
    boxes) for states that ship a ``personal`` amount; ``dependents_count``
    counts dependents for states that ship a ``dependent`` amount. Passing a
    nonzero count to a state without that verified amount raises a
    prescriptive error (never a silent $0). Age-65/blind and the other
    verified exemption kinds in a pack are DISCLOSED in the work but not
    applied — compute those lines on the state form itself.

    County/city add-on taxes (Indiana counties, Michigan cities, PA/KY local
    earned-income taxes) and state credits are NEVER modeled here.

    Raises a prescriptive error for an unknown state or a state whose pack
    ships no ``tax`` block, listing the states that do.
    """
    code = str(state).strip().lower()
    supported_hint = None
    try:
        pack = load_state_knowledge(code, year, base_dir=knowledge_dir)
    except FileNotFoundError:
        supported_hint = _states_with_tax_block(year, knowledge_dir)
        pack = None
    if pack is None or pack.tax is None:
        shipped = supported_hint if supported_hint is not None else _states_with_tax_block(year, knowledge_dir)
        raise ValueError(
            f"no state tax computation block for state {state!r}, tax year {year} — state_tax covers the "
            f"states whose packs ship a cited tax block: "
            f"{', '.join(shipped) if shipped else '(none for this year)'}. For any other state, compute "
            f"the tax line on the state's own form/tables via get_sources (state DOR .gov only) and cite "
            f"it — never invent a state rate or amount."
        )
    params = pack.tax
    base = _to_decimal(taxable_base, "taxable_base")
    n_exemptions = _count_arg(exemptions_count, "exemptions_count", "personal exemptions (taxpayer + spouse)")
    n_dependents = _count_arg(dependents_count, "dependents_count", "dependents claimed")
    status, alias_note = _resolve_filing_status(str(filing_status))

    personal = params.exemptions.get("personal")
    dependent = params.exemptions.get("dependent")
    if n_exemptions and personal is None:
        raise ValueError(
            f"{code.upper()} {year}: exemptions_count was supplied but the pack ships no 'personal' "
            f"exemption amount — this state has no personal exemption for state_tax to apply "
            f"(verified exemption kinds shipped: {', '.join(sorted(params.exemptions)) or '(none)'}). "
            f"Pass exemptions_count=0 and see the pack's tax.notes for how the state handles it."
        )
    if n_dependents and dependent is None:
        raise ValueError(
            f"{code.upper()} {year}: dependents_count was supplied but the pack ships no 'dependent' "
            f"exemption amount — this state does not model dependents as a verified per-dependent base "
            f"exemption (verified exemption kinds shipped: "
            f"{', '.join(sorted(params.exemptions)) or '(none)'}). Pass dependents_count=0 and handle "
            f"dependents per the pack's tax.notes (e.g. AZ's Line 49 dependent CREDIT, NC's AGI-tiered "
            f"child deduction, IL's unverified Schedule IL-E/EIC amount)."
        )

    inputs: dict[str, Any] = {
        "state": code,
        "taxable_base": str(base),
        "year": year,
        "exemptions_count": n_exemptions,
        "dependents_count": n_dependents,
        "filing_status": str(filing_status),
    }

    parts: list[str] = []
    subtracted = Decimal(0)
    if personal is not None and n_exemptions:
        amount = Decimal(personal.amount) * n_exemptions
        subtracted += amount
        parts.append(f"{n_exemptions} personal exemption(s) x {_dollars(personal.amount)} = {_money(amount)}")
    if dependent is not None and n_dependents:
        amount = Decimal(dependent.amount) * n_dependents
        subtracted += amount
        parts.append(f"{n_dependents} dependent exemption(s) x {_dollars(dependent.amount)} = {_money(amount)}")
    std = 0
    if params.standard_deduction is not None:
        std = params.standard_deduction[status]
        subtracted += Decimal(std)
        alias_text = f" ({alias_note})" if alias_note else ""
        parts.append(f"standard deduction [{status}{alias_text}] = {_dollars(std)}")

    base_after_exact = base - subtracted
    clamped = base_after_exact < 0
    base_after = irs_round(max(Decimal(0), base_after_exact))
    if params.flat_rate is not None:
        rate_structure = "flat"
        marginal_rate = params.flat_rate
        tax = irs_round(Decimal(base_after) * params.flat_rate)
        computation_text = f"tax = {params.flat_rate} x {_dollars(base_after)} = {_dollars(tax)}"
    else:
        rate_structure = "graduated"
        assert params.brackets is not None  # the schema enforces exactly-one-of
        schedule = params.brackets[status]
        tax_exact, marginal_rate, bracket_lines = _graduated_state_tax(schedule, base_after)
        tax = irs_round(tax_exact)
        alias_text = f" ({alias_note})" if alias_note else ""
        computation_text = (
            f"graduated tax on {_dollars(base_after)} [{status}{alias_text} schedule]: "
            + ("; ".join(bracket_lines) if bracket_lines else "$0.00 (base does not exceed the first bracket)")
            + f"; total {_money(tax_exact)} -> {_dollars(tax)}"
        )

    unapplied = sorted(k for k in params.exemptions if k not in ("personal", "dependent"))
    unapplied_text = (
        " Verified exemption kinds shipped but NOT applied by this op (compute them on the form): "
        + "; ".join(f"{k} ({_dollars(params.exemptions[k].amount)} — {params.exemptions[k].note})" for k in unapplied)
        if unapplied
        else ""
    )
    subtraction_text = (
        f" minus {', '.join(parts)} = {_money(base_after_exact)}"
        + (" (clamped to $0 — exemptions/deduction exceed the base)" if clamped else "")
        if parts
        else " with no exemptions or standard deduction to subtract"
    )
    notes_text = (" Pack notes: " + " ".join(params.notes)) if params.notes else ""
    structure_label = "flat rate" if rate_structure == "flat" else "graduated brackets"
    scope_label = "flat-rate tax line" if rate_structure == "flat" else "rate-schedule tax line"
    work = (
        f"{code.upper()} state income tax ({year}, {structure_label}): taxable_base {_money(base)} — which must be "
        f"{_STATE_TAX_BASE_LABELS[params.base]} —{subtraction_text}; {computation_text}. "
        f"Tax line: {params.tax_line}{unapplied_text} This op "
        f"computes the state's {scope_label} ONLY — county/city add-on taxes, state credits, and any "
        f"amounts outside the rate schedule are NOT modeled.{notes_text}"
    )
    return StateTaxResult(
        tax=tax,
        rate=params.flat_rate,
        rate_structure=rate_structure,
        marginal_rate=marginal_rate,
        base_after_exemptions=base_after,
        state=code,
        base_kind=params.base,
        inputs=inputs,
        work=work,
        citation=params.citation,
    )


# ---------------------------------------------------------------------------
# Foreign-asset / foreign-account REPORTING — Form 8938 and the FBAR (I4)
#
# The op answers the one question a filer never volunteers: "I have an account
# back home — do I have to tell anyone?" It is deliberately NOT a tax
# calculation. Both duties exist even when the account produced no income and
# no tax is owed (Treas. Reg. 1.6038D-2(a)(8): the form "must be furnished ...
# EVEN IF none of the specified foreign financial assets that must be reported
# affect the specified person's tax liability"), which is exactly why nothing in
# a refund-shaped interview surfaces them.
#
# THE OP MAY NOT GUESS. Every path that cannot be decided from the inputs
# returns `required = None` with a `must_ask` entry naming the missing fact and
# the authority that makes it decisive — a silent "no" here is the most
# expensive wrong answer in this repo.
# ---------------------------------------------------------------------------


def _require_foreign_account_reporting(pack: KnowledgePack, year: int) -> ForeignAccountReportingParams:
    params = pack.foreign_account_reporting
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no foreign_account_reporting block — add it with "
            f"citations to Treas. Reg. 1.6038D-2 (the Form 8938 thresholds), 31 CFR 1010.306(c) / "
            f"FinCEN's FBAR instructions (the $10,000 aggregate maximum-value test) and 31 U.S.C. "
            f"5321(a)(5) (the FBAR penalties); see knowledge/federal/2025.yaml"
        )
    return params


class ForeignReportingDuty(BaseModel):
    """One of the two duties, decided (or explicitly undecided) for this filer."""

    model_config = ConfigDict(extra="forbid")

    form: str
    required: bool | None = Field(
        description="True/False when the inputs decide it; None when a needed fact is missing (see must_ask)."
    )
    threshold_year_end: int | None = Field(
        default=None, description="Form 8938 only: the last-day-of-year figure the filer must exceed."
    )
    threshold_any_time: int | None = Field(
        default=None,
        description="The maximum-value-during-the-period figure the filer must exceed (the FBAR's single $10,000 lands here).",
    )
    tripped_by: list[str] = Field(
        default_factory=list, description="Which test(s) the supplied values exceeded, e.g. ['any_time']."
    )
    filed_with: str
    due: str
    must_ask: list[str] = Field(
        default_factory=list, description="Facts that must be elicited before this duty can be decided."
    )
    penalty_exposure: str
    citation: Citation


class ForeignAssetReportingResult(BaseModel):
    """Result of :func:`foreign_asset_reporting`: both duties, never just one."""

    model_config = ConfigDict(extra="forbid")

    form_8938: ForeignReportingDuty
    fbar: ForeignReportingDuty
    any_duty_undecided: bool = Field(
        description="True when either duty came back None — the caller must elicit the must_ask facts."
    )
    must_ask: list[str] = Field(description="Union of both duties' must_ask, in the order they should be asked.")
    inputs: dict[str, Any]
    work: str
    citation: Citation


_ABROAD_ASK = (
    "Do you meet the IRC 911(d)(1) qualified-individual test for this year — either a bona fide "
    "resident of a foreign country for an uninterrupted period including an entire tax year, or "
    "present in a foreign country at least 330 full days in 12 consecutive months ending in this "
    "year — with a tax home in a foreign country? Treas. Reg. 1.6038D-2(a)(3) keys the 4x-higher "
    "Form 8938 thresholds to that test, not to where you feel you live, so living overseas without "
    "meeting it leaves you on the in-US thresholds."
)


def foreign_asset_reporting(
    year: int = 2025,
    filing_status: FilingStatusInput = "single",
    *,
    us_person: bool | None = None,
    lives_abroad: bool | None = None,
    specified_asset_value_year_end: float | int | Decimal | str | None = None,
    specified_asset_value_max: float | int | Decimal | str | None = None,
    foreign_account_value_max_aggregate: float | int | Decimal | str | None = None,
    has_foreign_account_signature_authority: bool = False,
    filer_type: str = "specified_individual",
    knowledge_dir: str | Path | None = None,
) -> ForeignAssetReportingResult:
    """Must this filer file Form 8938, the FBAR, both, or neither? (IRC 6038D / 31 U.S.C. 5314)

    BOTH duties are always answered, because the single most common error is
    answering one and calling it done: "The Form 8938 filing requirement does not
    replace or otherwise affect a taxpayer's obligation to file FinCEN Form 114"
    (IRS, Comparison of Form 8938 and FBAR requirements), and the two reach
    DIFFERENT assets in both directions — an account you only have signature
    authority over is FBAR-reportable and generally not 8938-reportable, while
    foreign stock held outside an account, a foreign partnership interest and a
    foreign hedge fund are 8938-reportable and not FBAR-reportable.

    Args:
        year: tax year; the thresholds come from that year's knowledge pack.
        filing_status: one of the five inputs. **Not** routed through
            ``_resolve_filing_status``, and that is the point: that helper maps
            ``qualifying_surviving_spouse`` onto the married-filing-jointly
            column because a QSS uses the joint RATE schedule, and applying it
            here would DOUBLE a QSS filer's Form 8938 threshold. Treas. Reg.
            1.6038D-2(a)(2)/(a)(4) are keyed to filers who "file a joint annual
            return"; a QSS does not, so it takes the (a)(1)/(a)(3) general-rule
            amounts. The pack stores all five statuses explicitly for exactly
            this reason.
        us_person: True for a US citizen or a resident alien; False for a
            nonresident alien. Required — passing ``None`` returns both duties
            undecided rather than assuming. See the notes below on why the two
            filings define the term differently.
        lives_abroad: True only for an IRC 911(d)(1) qualified individual. When
            ``None`` the op evaluates BOTH threshold ladders and still answers
            definitively if they agree; when they disagree it returns
            ``required=None`` with the 911(d)(1) question in ``must_ask``.
        specified_asset_value_year_end: aggregate value of all specified foreign
            financial assets on the LAST DAY of the taxable year.
        specified_asset_value_max: MAXIMUM aggregate value at ANY TIME during the
            taxable year. Either test alone triggers Form 8938 (the regulation
            joins them with "or"), so a filer who empties an account before
            December 31 still files.
        foreign_account_value_max_aggregate: the FBAR measure — the sum of the
            MAXIMUM values of every foreign financial account during the CALENDAR
            year. Not the year-end balance, and not per account.
        has_foreign_account_signature_authority: True when the filer has
            signature or other authority over a foreign account they have no
            financial interest in. That alone can require an FBAR (31 CFR
            1010.350(a)) even when the answer for Form 8938 is no.
        filer_type: ``specified_individual`` (default) or
            ``specified_domestic_entity``.

    What the op will NOT do, in each case with the authority:

    * **Guess "no" from silence.** Omitting a value leaves that duty ``None``,
      never False. ``any_duty_undecided`` and ``must_ask`` carry it out.
    * **Treat the FBAR threshold as year-end or per-account.** It is an
      AGGREGATE across every foreign financial account and a MAXIMUM-value test
      (31 CFR 1010.306(c); FinCEN's FBAR instructions: "If the maximum account
      value of a single account or aggregate of the maximum account values of
      multiple accounts exceeds $10,000, an FBAR must be filed"), and filing
      status does not move it.
    * **Assume "US person" means the same thing on both filings.** For Form 8938
      a specified individual includes a resident alien "for any part of the tax
      year" and a nonresident alien who elects joint-return resident treatment or
      is a bona fide resident of American Samoa or Puerto Rico (Instructions for
      Form 8938, "Specified Individual"). For the FBAR it is a citizen, a
      resident alien under 26 U.S.C. 7701(b) measured against 31 CFR
      1010.100(hhh)'s definition of "United States", or a US entity (31 CFR
      1010.350(b)) — which is why residents of US TERRITORIES file FBARs while
      the territories are NOT "the United States" for the Form 8938 threshold.
      The op takes one ``us_person`` flag and states the divergence rather than
      pretending to resolve it.
    * **Prorate a part-year specified individual.** Treas. Reg.
      1.6038D-2(a)(9) makes the reporting period the portion of the year the
      filer WAS a specified individual — the F-1-to-H-1B year in this repo's own
      user base. The op reports the values it is given; segmenting them is the
      caller's job, and the work string says so.
    """
    pack = _load_federal(year, knowledge_dir)
    params = _require_foreign_account_reporting(pack, year)
    f8938, fbar = params.form_8938, params.fbar

    if filing_status not in FilingStatusInput.__args__:  # type: ignore[attr-defined]
        raise ValueError(
            f"unknown filing_status {filing_status!r} — use one of: single, married_filing_jointly, "
            f"married_filing_separately, head_of_household, qualifying_surviving_spouse"
        )
    if filer_type not in ("specified_individual", "specified_domestic_entity"):
        raise ValueError(
            f"unknown filer_type {filer_type!r} — use 'specified_individual' (an individual: US "
            f"citizen, resident alien, or one of the two nonresident-alien cases in the Form 8938 "
            f"instructions) or 'specified_domestic_entity' (a closely held domestic corporation, "
            f"partnership or trust under Treas. Reg. 1.6038D-6)"
        )

    def _amt(value, name):
        return None if value is None else _to_decimal(value, name)

    ye = _amt(specified_asset_value_year_end, "specified_asset_value_year_end")
    mx = _amt(specified_asset_value_max, "specified_asset_value_max")
    acct = _amt(foreign_account_value_max_aggregate, "foreign_account_value_max_aggregate")
    for name, v in (("specified_asset_value_year_end", ye), ("specified_asset_value_max", mx),
                    ("foreign_account_value_max_aggregate", acct)):
        if v is not None and v < 0:
            raise ValueError(
                f"{name} is {v} — a reported VALUE cannot be negative. An asset with no positive "
                f"value is still reportable and its maximum value is determined under Treas. Reg. "
                f"1.6038D-5(b)(3); pass 0, not a negative number"
            )
    if mx is not None and ye is not None and mx < ye:
        raise ValueError(
            f"specified_asset_value_max ({mx}) is below specified_asset_value_year_end ({ye}) — the "
            f"maximum value AT ANY TIME during the year cannot be less than the value on the last "
            f"day of it; one of the two figures is measuring the wrong thing"
        )

    # ── Form 8938 ──────────────────────────────────────────────────────────
    ask_8938: list[str] = []
    tripped_8938: list[str] = []
    t_us = t_abroad = None
    if filer_type == "specified_domestic_entity":
        t_us = t_abroad = f8938.thresholds.specified_domestic_entity
    else:
        t_us = f8938.thresholds.in_us[filing_status]
        t_abroad = f8938.thresholds.abroad[filing_status]

    def _verdict(threshold) -> bool | None:
        """True/False/None against ONE bucket. None = the values cannot decide it."""
        hits = []
        if ye is not None and ye > threshold.year_end:
            hits.append("year_end")
        if mx is not None and mx > threshold.any_time:
            hits.append("any_time")
        if hits:
            return True
        # Neither supplied test tripped. That is only a NO if BOTH were supplied
        # — either one alone triggers the filing, so a missing figure leaves the
        # question open.
        if ye is not None and mx is not None:
            return False
        return None

    if us_person is False:
        req_8938: bool | None = False
        note_8938 = (
            "a nonresident alien is not a specified individual, so Form 8938 is not required — BUT "
            "the Form 8938 instructions make TWO nonresident aliens specified individuals anyway: "
            "one who elects to be treated as a resident alien in order to file a JOINT return "
            "(IRC 6013(g)/(h)), and one who is a bona fide resident of American Samoa or Puerto "
            "Rico. Confirm neither applies before relying on this."
        )
    elif us_person is None:
        req_8938 = None
        note_8938 = "us_person was not supplied"
        ask_8938.append(
            "Are you a US citizen, or a resident alien for any part of this tax year under the green "
            "card test or the substantial presence test? A resident alien for ANY PART of the year is "
            "a specified individual (Instructions for Form 8938, 'Specified Individual'), and a "
            "nonresident alien is one only if electing resident treatment on a joint return or a bona "
            "fide resident of American Samoa or Puerto Rico."
        )
    else:
        if filer_type == "specified_domestic_entity" or lives_abroad is not None:
            bucket = t_abroad if (filer_type != "specified_domestic_entity" and lives_abroad) else t_us
            req_8938 = _verdict(bucket)
            applied = bucket
            note_8938 = (
                f"{'specified domestic entity' if filer_type == 'specified_domestic_entity' else ('abroad (IRC 911(d)(1) qualified individual)' if lives_abroad else 'in the United States')} "
                f"thresholds applied"
            )
        else:
            v_us, v_abroad = _verdict(t_us), _verdict(t_abroad)
            if v_us is None and v_abroad is None:
                # NEITHER ladder can be decided, so lives_abroad is not the
                # missing fact and asking about it would MISDIRECT the interview:
                # a VALUE is missing, and no residence answer changes that. (The
                # first draft asked the 911(d)(1) question here; caught by
                # running it, not by reading it.) The value question is appended
                # by the `req_8938 is None and not ask_8938` block below.
                req_8938 = None
                applied = t_us
                note_8938 = (
                    "neither the in-US nor the abroad ladder can be decided from the values given, so "
                    "lives_abroad is not what is missing — a specified-asset value is"
                )
            elif v_us == v_abroad and v_us is not None:
                req_8938 = v_us
                applied = t_us if not v_us else t_abroad
                note_8938 = (
                    "lives_abroad was not supplied, but the in-US and abroad thresholds give the SAME "
                    "answer here, so it did not have to be asked"
                )
            else:
                req_8938 = None
                applied = t_us
                note_8938 = (
                    f"lives_abroad DECIDES this one and was not supplied: on the in-US ladder "
                    f"(more than ${t_us.year_end:,} / ${t_us.any_time:,}) the answer is "
                    f"{'REQUIRED' if v_us else ('not required' if v_us is False else 'still undecided')}, "
                    f"while as an IRC 911(d)(1) qualified individual (more than "
                    f"${t_abroad.year_end:,} / ${t_abroad.any_time:,}) it is "
                    f"{'REQUIRED' if v_abroad else ('not required' if v_abroad is False else 'still undecided')}"
                )
                # tripped_by is left EMPTY on purpose: naming a test as "tripped"
                # while the applicable ladder is still unknown reads as a verdict.
                ask_8938.append(
                    _ABROAD_ASK
                    + f" Concretely, for the values given: in-US -> "
                    f"{'REQUIRED' if v_us else ('not required' if v_us is False else 'undecided')}, "
                    f"911(d)(1) qualified individual -> "
                    f"{'REQUIRED' if v_abroad else ('not required' if v_abroad is False else 'undecided')}."
                )
        if req_8938 is None and not ask_8938:
            missing = [n for n, v in (("specified_asset_value_year_end", ye),
                                      ("specified_asset_value_max", mx)) if v is None]
            ask_8938.append(
                "What was the total value of ALL your specified foreign financial assets "
                + ("on the last day of the tax year" if "specified_asset_value_year_end" in missing else "")
                + (" and " if len(missing) == 2 else "")
                + ("at its highest point at any time during the tax year" if "specified_asset_value_max" in missing else "")
                + "? Treas. Reg. 1.6038D-2(a) joins the two tests with 'or', so EITHER one alone "
                  "triggers the filing and a missing figure cannot be read as a zero."
            )
        if req_8938 is not None:
            for label, value, limit in (("year_end", ye, applied.year_end), ("any_time", mx, applied.any_time)):
                if value is not None and value > limit:
                    tripped_8938.append(label)

    if us_person is not True:
        applied = t_us

    # ── FBAR ───────────────────────────────────────────────────────────────
    ask_fbar: list[str] = []
    tripped_fbar: list[str] = []
    if us_person is False:
        req_fbar: bool | None = False
        note_fbar = (
            "a nonresident alien is not a United States person under 31 CFR 1010.350(b), so no FBAR "
            "— note the definition uses 31 CFR 1010.100(hhh)'s 'United States', which INCLUDES the "
            "territories, so a resident of Puerto Rico, Guam, the USVI, American Samoa or the CNMI "
            "IS a US person for FBAR purposes even though the territories are not 'the United "
            "States' for the Form 8938 threshold ladder"
        )
    elif us_person is None:
        req_fbar = None
        note_fbar = "us_person was not supplied"
        ask_fbar.append(
            "Are you a United States person for FBAR purposes — a US citizen, a resident alien under "
            "26 U.S.C. 7701(b) (using 31 CFR 1010.100(hhh)'s definition of 'United States', which "
            "includes the US territories), or a US entity? 31 CFR 1010.350(b)."
        )
    elif acct is None:
        req_fbar = None
        note_fbar = "the aggregate maximum account value was not supplied"
        ask_fbar.append(
            f"Adding up the HIGHEST balance each foreign financial account reached at any point in "
            f"the calendar year, what is the total? The FBAR test is an AGGREGATE across every "
            f"account and a MAXIMUM-value test, not a year-end test and not per account: two "
            f"accounts whose combined balance touched ${fbar.aggregate_threshold + 1:,} for one day "
            f"are BOTH reportable even if each stayed under ${fbar.aggregate_threshold:,} alone and "
            f"both were empty on December 31 (31 CFR 1010.306(c); FinCEN's FBAR instructions)."
            + (" You have also indicated signature authority over an account you have no financial "
               "interest in, which is reportable in its own right (31 CFR 1010.350(a))."
               if has_foreign_account_signature_authority else "")
        )
    else:
        req_fbar = acct > fbar.aggregate_threshold
        if req_fbar:
            tripped_fbar.append("any_time_aggregate")
        note_fbar = (
            f"aggregate maximum account value {_money(acct)} vs the ${fbar.aggregate_threshold:,} "
            f"threshold, which filing status does not move"
        )
        if not req_fbar and has_foreign_account_signature_authority:
            req_fbar = None
            note_fbar += (
                "; the value test is not met, but you have signature or other authority over an "
                "account you have no financial interest in"
            )
            ask_fbar.append(
                "Is the aggregate maximum value figure you gave INCLUSIVE of every account you have "
                "signature or other authority over, not just the ones you own? 31 CFR 1010.350(a) "
                "requires the report from a US person with 'a financial interest in, or signature or "
                "other authority over' a foreign account, and the IRS comparison table confirms a "
                "signature-authority account is FBAR-reportable (subject to exceptions) while it is "
                "generally NOT a Form 8938 asset — so this is the case where the two answers differ."
            )

    p8 = f8938.penalties
    pf = fbar.penalties
    duty_8938 = ForeignReportingDuty(
        form=f8938.form,
        required=req_8938,
        threshold_year_end=applied.year_end,
        threshold_any_time=applied.any_time,
        tripped_by=tripped_8938,
        filed_with=f8938.filed_with,
        due="with the income tax return for the taxable year, including extensions",
        must_ask=ask_8938,
        penalty_exposure=(
            f"IRC 6038D(d): ${p8.failure_to_file:,} for failing to file a complete and correct Form "
            f"8938 by the due date including extensions, plus ${p8.continuing_failure_per_30_days:,} "
            f"for each 30-day period (or fraction) the failure continues more than "
            f"{p8.continuing_failure_grace_days_after_notice} days after IRS notice, that additional "
            f"penalty capped at ${p8.continuing_failure_additional_cap:,} — "
            f"${p8.maximum_per_year:,} maximum for the year. IRC 6662(j)(3) raises the "
            f"accuracy-related rate to {int(p8.accuracy_related_rate_undisclosed_foreign_asset * 100)}% "
            f"on any underpayment attributable to an undisclosed foreign financial asset, and "
            f"{int(p8.fraud_rate * 100)}% applies to an underpayment due to fraud. Reasonable cause "
            f"is a defence; a foreign jurisdiction's own disclosure penalty is NOT reasonable cause "
            f"(IRC 6038D(g)). {p8.statute_of_limitations_note}"
        ),
        citation=f8938.citation,
    )
    duty_fbar = ForeignReportingDuty(
        form=fbar.form,
        required=req_fbar,
        threshold_year_end=None,
        threshold_any_time=fbar.aggregate_threshold,
        tripped_by=tripped_fbar,
        filed_with=fbar.filed_with,
        due=fbar.due_date_rule,
        must_ask=ask_fbar,
        penalty_exposure=(
            f"31 U.S.C. 5321(a)(5): a NON-WILLFUL violation draws up to "
            f"${pf.non_willful_statutory_maximum:,} by statute, inflation-adjusted to "
            f"${pf.non_willful_adjusted_maximum:,} for {pf.adjusted_amounts_effective} (31 CFR "
            f"1010.821, Table 1) — and it accrues PER REPORT, not per account: Bittner v. United "
            f"States, 598 U.S. 85 (2023). A WILLFUL violation draws the GREATER of "
            f"${pf.willful_statutory_minimum_maximum:,} "
            f"(adjusted ${pf.willful_adjusted_minimum_maximum:,}) or "
            f"{int(pf.willful_alternative_share_of_balance * 100)}% of the account balance at the "
            f"time of the violation, which IS per account, and the reasonable-cause exception does "
            f"not apply to it. The adjusted maxima track the date the penalty is ASSESSED, not the "
            f"tax year. Criminal penalties may also apply."
        ),
        citation=fbar.citation,
    )

    must_ask = list(dict.fromkeys(ask_8938 + ask_fbar))
    def _say(v: bool | None) -> str:
        return "REQUIRED" if v is True else ("not required" if v is False else "UNDECIDED")

    work_lines = [
        f"Foreign-asset reporting for {year} ({filing_status}, {filer_type}) — two SEPARATE filings, "
        f"and neither substitutes for the other:",
        f"* Form 8938 (IRC 6038D): {_say(req_8938)}. Thresholds applied: more than "
        f"${applied.year_end:,} on the last day of the taxable year OR more than "
        f"${applied.any_time:,} at any time during it — {note_8938}."
        + (f" Tripped by: {', '.join(tripped_8938)}." if tripped_8938 else ""),
        f"* FBAR (FinCEN Form 114, 31 U.S.C. 5314): {_say(req_fbar)}. Threshold: aggregate maximum "
        f"value of ALL foreign financial accounts exceeding ${fbar.aggregate_threshold:,} at any "
        f"time in the CALENDAR year — {note_fbar}.",
        "The FBAR is filed with FinCEN, electronically through the BSA E-Filing System, and is NOT "
        "part of the tax return; a PRINTED FinCEN Form 114 is not accepted. Form 8938 attaches to "
        "the return. Filing one does not satisfy the other, and their asset scopes differ in BOTH "
        "directions (signature-authority accounts and a foreign BRANCH of a US bank: FBAR only; "
        "foreign stock outside an account, a foreign partnership interest, a foreign hedge fund: "
        "Form 8938 only).",
        "The two duties exist even if the accounts produced no income and no tax is owed (Treas. "
        "Reg. 1.6038D-2(a)(8)).",
        "ONE PRECONDITION THE OP DOES NOT TEST, and it can flip the Form 8938 answer to NO on any "
        "value: Treas. Reg. 1.6038D-2(a)(7)(i) — a specified person, INCLUDING a specified "
        "individual who is a bona fide resident of a US possession, \"is not required to file Form "
        "8938 with respect to a taxable year if the specified person is not required to file an "
        "annual return with the Internal Revenue Service with respect to such taxable year.\" So a "
        "filer below the IRC 6012 filing threshold files no Form 8938 however large the assets, "
        "while the FBAR is unaffected — it is not part of the income tax return and has its own "
        "duty. Confirm a return is required before acting on a REQUIRED verdict here.",
        "NOT MODELLED, and each would change the answer: the value-EXCEPTION rules (assets already "
        "reported on Forms 3520 / 3520-A / 5471 / 8621 / 8865 are excepted from Form 8938 DETAIL but "
        "still COUNT toward the threshold under Treas. Reg. 1.6038D-2(a)(6)(i)); the joint-ownership "
        "valuation rules; the FBAR's account exceptions (IRA-held, retirement-plan-held, US military "
        "banking facility, correspondent/nostro, governmental) and its 25-or-more-accounts short "
        "form; and PART-YEAR status — Treas. Reg. 1.6038D-2(a)(9) makes the Form 8938 reporting "
        "period only the portion of the year the filer was a specified individual, while the FBAR's "
        "period is always the calendar year, so an F-1-to-H-1B or dual-status year needs the values "
        "segmented by the caller before they are passed here.",
    ]
    if must_ask:
        work_lines.append(
            "UNDECIDED — ask, do not assume. A silent 'no' is the most expensive wrong answer here: "
            + " ".join(f"({i}) {q}" for i, q in enumerate(must_ask, start=1))
        )

    return ForeignAssetReportingResult(
        form_8938=duty_8938,
        fbar=duty_fbar,
        any_duty_undecided=(req_8938 is None or req_fbar is None),
        must_ask=must_ask,
        inputs={
            "year": year,
            "filing_status": filing_status,
            "filer_type": filer_type,
            "us_person": us_person,
            "lives_abroad": lives_abroad,
            "specified_asset_value_year_end": None if ye is None else int(ye),
            "specified_asset_value_max": None if mx is None else int(mx),
            "foreign_account_value_max_aggregate": None if acct is None else int(acct),
            "has_foreign_account_signature_authority": has_foreign_account_signature_authority,
        },
        work="\n".join(work_lines),
        citation=params.citation,
    )
