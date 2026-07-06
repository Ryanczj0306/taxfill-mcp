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
  ``ptc_annual`` (Form 8962 Premium Tax Credit, annual method).

These functions are pure: no logging, no side effects; the only I/O is
reading the versioned knowledge pack. They never echo the value being
validated (routing/account numbers are sensitive).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.knowledge import (
    FILING_STATUSES,
    Citation,
    FilingStatus,
    KnowledgePack,
    MagiPhaseoutRange,
    RateBracket,
    TaxTable,
    load_knowledge,
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
# Premium Tax Credit (Form 8962, annual method)
# ---------------------------------------------------------------------------

_PTC_STATES = ("other", "alaska", "hawaii")


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
    """
    income = _to_decimal(household_income, "household_income")
    premiums = _to_decimal(annual_premiums, "annual_premiums")
    slcsp = _to_decimal(annual_slcsp, "annual_slcsp")
    aptc = _to_decimal(annual_aptc, "annual_aptc")
    if income < 0:
        raise ValueError(f"household_income must be >= 0, got {income} — pass 0 for a negative household income")
    for name, value in (("annual_premiums", premiums), ("annual_slcsp", slcsp), ("annual_aptc", aptc)):
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")
    if isinstance(household_size, bool) or not isinstance(household_size, int) or household_size < 1:
        raise ValueError(
            f"household_size must be an int >= 1 (the Form 8962 line 1 tax family size), got {household_size!r}"
        )
    _resolve_filing_status(str(filing_status))  # validates the five statuses
    if state not in _PTC_STATES:
        raise ValueError(
            f"state must be one of 'other' (the 48 contiguous states and DC), 'alaska', 'hawaii' — "
            f"got {state!r}. A household that lived in both AK/HI and elsewhere uses the table with "
            f"the HIGHER amounts."
        )
    pack = _load_federal(year, knowledge_dir)
    params = pack.tax.ptc
    if params is None:
        raise ValueError(
            f"knowledge pack for federal {year} has no tax.ptc block — the Premium Tax Credit ships only "
            f"for tax years 2023 and 2024 (the ARPA applicable-percentage table as extended to 2023-2025 "
            f"by IRA section 12001(a); pre-2023 years use different indexed tables and post-2025 the "
            f"regime expires). Use 2023 or 2024, or author the year's block from its Form 8962 "
            f"instructions with citations."
        )
    fpl_table = {
        "other": params.federal_poverty_line.contiguous_48_and_dc,
        "alaska": params.federal_poverty_line.alaska,
        "hawaii": params.federal_poverty_line.hawaii,
    }[state]
    if household_size <= 8:
        fpl = fpl_table.household_size[household_size]
    else:
        fpl = fpl_table.household_size[8] + (household_size - 8) * fpl_table.per_additional_person
    inputs: dict[str, Any] = {
        "household_income": str(income),
        "household_size": household_size,
        "annual_premiums": str(premiums),
        "annual_slcsp": str(slcsp),
        "annual_aptc": str(aptc),
        "filing_status": str(filing_status),
        "state": state,
        "year": year,
    }

    ratio_pct = income * 100 / Decimal(fpl)
    fpl_pct = int(ratio_pct)  # Worksheet 2: TRUNCATE — drop the decimals, never round
    entered_401 = fpl_pct > 400
    if entered_401:
        fpl_pct = 401

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
    ptc_amount = irs_round(min(premiums, max(Decimal(0), slcsp - contribution)))
    aptc_whole = irs_round(aptc)
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
        cap = row.single if str(filing_status) == "single" else row.other
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
                f"({'single' if str(filing_status) == 'single' else 'any other filing status'} column) = "
                f"{_dollars(cap)}; repayment = {_dollars(repayment)} (Schedule 2)."
            )

    state_label = {"other": "48 contiguous states/DC", "alaska": "Alaska", "hawaii": "Hawaii"}[state]
    pct_text = (
        f"{fpl_pct} (over 400% — enter literally 401)"
        if entered_401
        else f"{fpl_pct} (TRUNCATED from {ratio_pct:.2f} — decimals dropped, never rounded)"
    )
    work = (
        f"Form 8962 ({year}, annual method): line 4 FPL ({state_label} table, household of "
        f"{household_size}) = {_dollars(fpl)}; line 5 = household income {_money(income)} / FPL x 100 = "
        f"{pct_text}; {figure_text}; line 8a contribution = {_money(income)} x {figure} = "
        f"{_dollars(contribution)}; line 24 annual PTC = min(premiums {_money(premiums)}, SLCSP "
        f"{_money(slcsp)} - contribution = {_money(slcsp - contribution)}, floor 0) = "
        f"{_dollars(ptc_amount)}. {settle_text}"
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
