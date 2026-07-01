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

    total = irs_round(wage_portion + se_portion)
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
