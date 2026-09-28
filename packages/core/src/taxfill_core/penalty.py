"""The IRC 6654 underpayment-of-estimated-tax penalty, regular method (Phase J JP5a).

``underpayment_penalty`` prices Form 2210 Part III, Section B, from the statute's own mechanics:

* 6654(b)(1): the underpayment of an installment is "the excess of- (A) the required installment, over (B)
  the amount (if any) of the installment paid on or before the due date for the installment";
* 6654(b)(2): it runs "from the due date for the installment to whichever of the following dates is the
  earlier- (A) the 15th day of the 4th month following the close of the taxable year, or (B) with respect to
  any portion of the underpayment, the date on which such portion is paid";
* 6654(b)(3): "a payment of estimated tax shall be credited against unpaid required installments in the
  order in which such installments are required to be paid" — a FIFO ledger, which is exactly how the Form
  2210 instructions apply payments ("Your payments are applied first to any underpayment balance on an
  earlier installment even if you designate a payment for a later period");
* 6654(g)(1): withholding is "deemed paid on each due date" in equal parts "unless the taxpayer establishes
  the dates on which all amounts were actually withheld";
* 6654(a) and 6621: each day is priced at the rate period's underpayment rate over the worksheet's 365.

The calendar (due dates, period end, rate periods) is read from the year's knowledge pack
(``tax.estimated_tax_penalty``). A rate the Secretary has not announced is None there and the op FAILS
CLOSED rather than borrowing a neighbouring quarter.

JP5b adds the annualized income installment method, IRC 6654(d)(2)(A): "if the individual establishes that
the annualized income installment is less than the amount determined under paragraph (1)- (i) the amount of
such required installment shall be the annualized income installment". Form 2210 Schedule AI's Parts I and II
are computed line by line from the year's printed constants (``estimated_tax_penalty.schedule_ai``), and both
methods are priced so the result shows what Schedule AI saves.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.knowledge import Citation, load_knowledge

_CENT = Decimal("0.01")
_COLUMNS = ("a", "b", "c", "d")


class PenaltyPiece(BaseModel):
    """One priced slice: part of one installment's underpayment, inside one rate period."""

    model_config = ConfigDict(extra="forbid")

    column: str = Field(description="Form 2210 column: a (April 15), b (June 15), c (September 15), d (January 15).")
    amount: int = Field(description="The underpaid dollars this slice prices.")
    start: date = Field(description="The day the slice starts counting from (the due date or the period's start).")
    end: date = Field(description="The day it stops (the payment date, the period's last day or the period end).")
    days: int = Field(description="Days in the slice — the worksheet's lines 3, 6, 9 and 12.")
    rate: Decimal
    penalty: Decimal = Field(description="amount x days / day_count x rate, to the cent (worksheet lines 4/7/10/13).")
    paid_on: date | None = Field(description="The payment that ended this portion; None if still unpaid at period end.")


class InstallmentRow(BaseModel):
    """One Form 2210 column after Part III, Section A."""

    model_config = ConfigDict(extra="forbid")

    column: str
    due_date: date
    required: int = Field(description="Line 10, the required installment.")
    paid_by_due_date: int = Field(description="What the FIFO ledger credited to this installment by its due date.")
    underpayment: int = Field(description="Line 17: required - paid by the due date (6654(b)(1)).")


class ScheduleAiColumn(BaseModel):
    """One Schedule AI column (JP5b): the lines that decide the installment."""

    model_config = ConfigDict(extra="forbid")

    column: str
    period_end: date
    line_3_annualized_income: int
    line_13_taxable: int
    line_14_tax: int
    line_15_se_tax: int
    line_19_net_tax: int
    line_21: int
    line_23: int
    line_26: int
    line_27_installment: int
    face_lines: dict[str, int] = Field(
        default_factory=dict,
        description="Every Schedule AI line this column fills, keyed by the printed line ('1' ... '36'; '9a'/'9b' on "
                    "the 2026 draft) — what form2210_lines hands verify's independent recompute (JP5c).")


class UnderpaymentPenaltyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    method: str = Field(description="regular, or annualized (Schedule AI supplied the line-10 installments).")
    installments: list[InstallmentRow]
    pieces: list[PenaltyPiece]
    penalty: Decimal = Field(description="Form 2210 line 19 to the cent (the sum of the worksheet lines).")
    penalty_whole_dollars: int = Field(description="The same, rounded half up to whole dollars.")
    exception: str | None = Field(
        default=None, description="An IRC 6654(e)/(h) exception that zeroed all or part of the penalty, quoted.")
    regular_method_penalty: Decimal | None = Field(
        default=None, description="With Schedule AI: the same payments priced against 25% installments, for comparison.")
    schedule_ai: list[ScheduleAiColumn] | None = None
    not_modeled: list[str]
    inputs: dict[str, Any]
    work: str
    citation: Citation


def _as_date(value: date | str, what: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{what} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


def _as_int(value: Any, what: str) -> int:
    try:
        d = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 — any unparsable input gets the same prescriptive error
        raise ValueError(f"{what} must be a whole-dollar amount, got {value!r}") from exc
    if d < 0 or d != d.to_integral_value():
        raise ValueError(f"{what} must be a non-negative whole-dollar amount, got {value!r}")
    return int(d)


def underpayment_penalty(
    required_installments: list[int | str] | None = None,
    payments: list[dict[str, Any]] | None = None,
    withholding: int | str = 0,
    year: int = 2025,
    *,
    required_annual_payment: int | str | None = None,
    withholding_dates: list[dict[str, Any]] | None = None,
    tax_after_withholding: int | str | None = None,
    return_filed: date | str | None = None,
    paid_in_full_with_return: bool = False,
    annualized: dict[str, Any] | None = None,
    knowledge_dir: str | Path | None = None,
) -> UnderpaymentPenaltyResult:
    """Form 2210's regular-method penalty for ``year`` (Part III), from the statute's FIFO ledger.

    Args:
        required_installments: the four Form 2210 line 10 amounts, or pass ``required_annual_payment`` for the
            regular method's "25 percent of the required annual payment" (6654(d)(1)(A)) each.
        payments: estimated-tax payments as ``[{date, amount}]`` — include an overpayment applied from last year
            (dated the first due date) and the balance paid with the return (dated when paid).
        withholding: the year's federal income tax withheld; deemed paid in four equal parts on the due dates
            (6654(g)(1)) unless ``withholding_dates`` lists every amount with its actual date.
        tax_after_withholding: optional — the tax shown on the return less withholding; under $1,000 is the
            6654(e)(1) exception.
        return_filed / paid_in_full_with_return: a return filed by January 31 of the following year and paid in
            full removes the 4th installment's penalty (6654(h)).
        annualized: Schedule AI (JP5b) — ``{filing_status, agi: [4 cumulative period figures], standard_deduction,
            itemized?: [4], qbi?: [4], additional_deductions?: [4] (Schedule 1-A), se_net_earnings?: [4] (line 28:
            net profit x 92.35%), ss_wages?: [4] (line 30), other_taxes?: [4], credits?: [4], period_tax?: [4]
            (line 14 when the Tax Table is not the right computation)}``. Needs ``required_annual_payment`` (line 24
            is 25% of it); the result prices both methods.
    """
    pack = load_knowledge("federal", year, base_dir=knowledge_dir)
    cal = pack.tax.estimated_tax_penalty if pack.tax is not None else None
    if cal is None:
        raise ValueError(
            f"knowledge/federal/{year}.yaml has no tax.estimated_tax_penalty block — the penalty calendar (due "
            f"dates and the IRC 6621 rate periods) is transcribed per year from the Form 2210 instructions and the "
            f"IRS quarterly-rate table (JP5a ships 2025 and 2026)"
        )
    dues = list(cal.installment_due_dates)
    if (required_installments is None) == (required_annual_payment is None):
        raise ValueError("pass exactly one of required_installments (four line-10 amounts) or required_annual_payment")
    if required_installments is not None:
        if len(required_installments) != 4:
            raise ValueError(f"required_installments needs four amounts (columns a-d), got {len(required_installments)}")
        required = [_as_int(v, f"required_installments[{i}]") for i, v in enumerate(required_installments)]
        req_note = "the four required installments given (Form 2210 line 10)"
        annual = sum(required)
    else:
        annual = _as_int(required_annual_payment, "required_annual_payment")
        base, rem = divmod(annual, 4)
        required = [base + (1 if i < rem else 0) for i in range(4)]
        req_note = (f"25 percent of the required annual payment {annual:,} per installment (IRC 6654(d)(1)(A))"
                    + (" — the odd dollars on the earliest installments" if rem else ""))

    ai_cols = None
    if annualized is not None:
        if required_annual_payment is None:
            raise ValueError("Schedule AI needs required_annual_payment — its line 24 is '25% (0.25) of line 9 on page "
                             "1 of Form 2210' (the regular installment)")
        if cal.schedule_ai is None:
            raise ValueError(f"knowledge/federal/{year}.yaml carries no estimated_tax_penalty.schedule_ai block")
        ai_cols = _schedule_ai(cal.schedule_ai, annualized, annual, year, knowledge_dir)
    regular_required = list(required)
    if ai_cols is not None:
        required = [c.line_27_installment for c in ai_cols]
        req_note = ("the Schedule AI line 27 installments (IRC 6654(d)(2)(A); \"If you use Schedule AI for any payment "
                    "due date, you must use it for all payment due dates\")")

    # ── the credits, in date order (6654(b)(3) + (g)(1)) ──
    credits: list[tuple[date, int, str]] = []
    for i, p in enumerate(payments or []):
        credits.append((_as_date(p.get("date"), f"payments[{i}].date"), _as_int(p.get("amount"), f"payments[{i}].amount"),
                        "estimated tax payment"))
    wh_total = _as_int(withholding, "withholding")
    if withholding_dates is not None:
        dated = [(_as_date(w.get("date"), f"withholding_dates[{i}].date"), _as_int(w.get("amount"), f"withholding_dates[{i}].amount"))
                 for i, w in enumerate(withholding_dates)]
        if wh_total and sum(a for _, a in dated) != wh_total:
            raise ValueError(f"withholding_dates add to {sum(a for _, a in dated):,}, not the withholding {wh_total:,} — "
                             f"6654(g)(1) takes actual dates only for ALL amounts withheld")
        credits += [(d, a, "withholding (actual date)") for d, a in dated]
        wh_note = "withholding on the dates actually withheld (the 6654(g)(1) election)"
    elif wh_total:
        base, rem = divmod(wh_total, 4)
        credits += [(dues[i], base + (1 if i < rem else 0), "withholding (deemed ratable)") for i in range(4)]
        wh_note = f"withholding {wh_total:,} deemed paid in equal parts on the four due dates (IRC 6654(g)(1))"
    else:
        wh_note = "no withholding"
    credits.sort(key=lambda c: c[0])

    def _price(req: list[int]) -> tuple[list[InstallmentRow], list[PenaltyPiece], str | None]:
        # ── the FIFO ledger: each credit pays the earliest installment still owed ──
        owed = list(req)
        paid_by_due = [0, 0, 0, 0]
        portions: list[list[tuple[int, date | None]]] = [[], [], [], []]  # per column: (late dollars, paid on)
        for when, amount, _kind in credits:
            left = amount
            for k in range(4):
                if left == 0:
                    break
                if owed[k] == 0:
                    continue
                take = min(owed[k], left)
                owed[k] -= take
                left -= take
                if when <= dues[k]:
                    paid_by_due[k] += take
                else:
                    portions[k].append((take, when))
        for k in range(4):
            if owed[k]:
                portions[k].append((owed[k], None))       # unpaid through the period end
        rows = [InstallmentRow(column=_COLUMNS[k], due_date=dues[k], required=req[k], paid_by_due_date=paid_by_due[k],
                               underpayment=req[k] - paid_by_due[k]) for k in range(4)]
        exception = None
        if tax_left is not None and tax_left < 1000:
            exception = ("IRC 6654(e)(1): \"No addition to tax shall be imposed under subsection (a) for any taxable year "
                         "if the tax shown on the return for such taxable year ... reduced by the credit allowable under "
                         f"section 31, is less than $1,000\" — {tax_left:,} after withholding.")
            portions = [[], [], [], []]
        if exception is None and filed is not None and filed <= date(year + 1, 1, 31) and paid_in_full_with_return:
            exception = ("IRC 6654(h): a return filed on or before January 31 with the amount payable paid in full — "
                         "\"no addition to tax shall be imposed under subsection (a) with respect to any underpayment of "
                         "the 4th required installment\".")
            portions[3] = []
        # ── price each late portion, split at the rate periods ──
        pieces: list[PenaltyPiece] = []
        for k in range(4):
            for dollars, paid_on in portions[k]:
                stop = cal.period_end if paid_on is None or paid_on > cal.period_end else paid_on
                for period in cal.rate_periods:
                    lo = max(dues[k], period.start - timedelta(days=1))
                    hi = min(stop, period.end)
                    days = (hi - lo).days
                    if days <= 0:
                        continue
                    if period.rate is None:
                        raise ValueError(
                            f"the {year} penalty reaches {period.start}-{period.end}, whose IRC 6621 underpayment rate is "
                            f"not announced yet ({period.source}) — refusing to borrow another quarter's rate. Re-run "
                            f"once knowledge/federal/{year}.yaml carries it, or price only payments made before "
                            f"{period.start}"
                        )
                    amt = (Decimal(dollars) * days / cal.day_count * period.rate).quantize(_CENT, ROUND_HALF_UP)
                    pieces.append(PenaltyPiece(column=_COLUMNS[k], amount=dollars, start=lo, end=hi, days=days,
                                               rate=period.rate, penalty=amt, paid_on=paid_on))
        return rows, pieces, exception

    tax_left = None if tax_after_withholding is None else _as_int(tax_after_withholding, "tax_after_withholding")
    filed = None if return_filed is None else _as_date(return_filed, "return_filed")
    rows, pieces, exception = _price(required)
    regular_total = None
    if ai_cols is not None:
        regular_total = sum((p.penalty for p in _price(regular_required)[1]), Decimal("0.00"))
    total = sum((p.penalty for p in pieces), Decimal("0.00"))
    whole = int(total.quantize(Decimal(1), ROUND_HALF_UP))

    lines = [
        f"Form 2210 ({year}), {'annualized income installment method' if ai_cols is not None else 'regular method'}: "
        f"{req_note}; {wh_note}.",
        "Section A (6654(b)(1)): " + "; ".join(
            f"({r.column}) {r.due_date:%m/%d/%y} required {r.required:,}, paid by the due date {r.paid_by_due_date:,}, "
            f"underpayment {r.underpayment:,}" for r in rows) + ".",
        "Payments are credited to the earliest unpaid installment (6654(b)(3)); each late portion runs to the day "
        f"it is paid or {cal.period_end:%B %d, %Y} (6654(b)(2)).",
    ]
    for p in pieces:
        paid = f"paid {p.paid_on:%m/%d/%y}" if p.paid_on else "unpaid"
        lines.append(f"  ({p.column}) {p.amount:,} x {p.days} days ({p.start:%m/%d/%y}-{p.end:%m/%d/%y}, {paid}) / "
                     f"{cal.day_count} x {p.rate} = {p.penalty}")
    lines.append(f"Penalty (line 19): {total} (whole dollars {whole:,})." + (f" {exception}" if exception else ""))
    if ai_cols is not None:
        ai = cal.schedule_ai
        lines.insert(1, "Schedule AI (" + ("DRAFT face, " if ai.source_status == "draft" else "") + "line 27 = the smaller of "
                     "line 23, the annualized installment, and line 26, the regular installment plus what earlier "
                     "columns saved): " + "; ".join(
                         f"({c.column}) to {c.period_end:%m/%d}: annualized income {c.line_3_annualized_income:,}, tax "
                         f"{c.line_14_tax:,} + SE {c.line_15_se_tax:,}, line 21 {c.line_21:,}, line 27 "
                         f"{c.line_27_installment:,}" for c in ai_cols) + ".")
        lines.append(f"The regular method (25% installments) on the same payments: {regular_total}; Schedule AI saves "
                     f"{regular_total - total}.")
    return UnderpaymentPenaltyResult(
        year=year, method="annualized" if ai_cols is not None else "regular", installments=rows, pieces=pieces,
        penalty=total, penalty_whole_dollars=whole, exception=exception, regular_method_penalty=regular_total,
        schedule_ai=ai_cols,
        not_modeled=[
            "the required installments themselves — compute the required annual payment with calc op "
            "estimated_tax_safe_harbor (6654(d)) and pass it or the four line-10 amounts",
            "Schedule AI's line 16 other taxes and line 18 credits are taken as given per period — annualize their "
            "inputs as the instructions say (\"annualize any item of income or deduction used to figure each credit\")",
            "IRC 6654(e)(2) (no tax liability for a 12-month preceding year as a citizen or resident all year) and the "
            "6654(e)(3) waivers (casualty, disaster, retirement after age 62 or disability) — the filer's facts; the "
            "IRS decides a waiver request",
            "a weekend or holiday due date: the columns keep the statutory dates the worksheet prints (06/15/25 was "
            "a Sunday) — a payment on the next business day is timely under IRC 7503; pass it on the due date",
            "farmers and fishermen (6654(i)) and the short method (Form 2210 line 15 method)",
        ],
        inputs={"required": required, "payments": [(d.isoformat(), a, k) for d, a, k in credits], "year": year},
        work="\n".join(lines),
        citation=cal.citation,
    )


def form2210_lines(result: UnderpaymentPenaltyResult) -> dict[str, int]:
    """Form 2210 Part III lines 10-19 and Schedule AI, recomputed from an underpayment_penalty result (Phase J JP5c).

    The independent recompute for a filled Form 2210 pack: pass it as ``verify_form(..., independent=...)``. Section
    A is worked the way the face prints it — line 11 holds each column's own payments ("Column (b)—payments made
    after April 15 ... through June 15"; withholding on the due dates unless the actual dates were elected), 12 is
    the previous column's 18, 14 the previous 16 + 17, 15 = max(0, 13 - 14) (column (a): line 11), and 17 / 18 the
    under- / overpayment against line 10 — and each column's line 17 is checked against the ledger's own
    underpayment, so the face arithmetic and the 6654(b)(3) FIFO ledger can never silently disagree. Line 19 is the
    penalty in whole dollars. With Schedule AI (the annualized method), its face lines are keyed ``ai.<line>.<col>``.
    Keys follow the pack: ``10.a``, ``ai.27.d``. Payments after the last due date price Section B only."""
    dues = [row.due_date for row in result.installments]
    credits = [(date.fromisoformat(when), amount) for when, amount, _kind in result.inputs["payments"]]
    out: dict[str, int] = {}
    prev16 = prev17 = prev18 = 0
    for k, (col, row) in enumerate(zip(_COLUMNS, result.installments)):
        low = dues[k - 1] if k else date.min
        l10, l11 = row.required, sum(amount for when, amount in credits if low < when <= dues[k])
        out |= {f"10.{col}": l10, f"11.{col}": l11}
        if k == 0:
            l13 = l14 = 0
            l15 = l11
        else:
            l13, l14 = l11 + prev18, prev16 + prev17
            l15 = max(0, l13 - l14)
            out |= {f"12.{col}": prev18, f"13.{col}": l13, f"14.{col}": l14}
        l16 = max(0, l14 - l13) if k else 0
        l17, l18 = max(0, l10 - l15), max(0, l15 - l10)
        if l17 != row.underpayment:
            raise ValueError(f"Form 2210 line 17({col}) works out to {l17:,} but the ledger's underpayment is "
                             f"{row.underpayment:,} — the payments and the installments disagree; re-run "
                             f"underpayment_penalty")
        out |= {f"15.{col}": l15, f"17.{col}": l17}
        if col in ("b", "c"):
            out[f"16.{col}"] = l16
        if col != "d":
            out[f"18.{col}"] = l18
        prev16, prev17, prev18 = l16, l17, l18
    out["19"] = result.penalty_whole_dollars
    for ai_col in result.schedule_ai or []:
        out |= {f"ai.{line}.{ai_col.column}": value for line, value in ai_col.face_lines.items()}
    return out


def _per_period(values: Any, what: str, default: int = 0) -> list[int]:
    if values is None:
        return [default] * 4
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        raise ValueError(f"annualized.{what} needs four period figures (columns a-d, each cumulative from January 1)")
    out = []
    for i, v in enumerate(values):
        d = Decimal(str(v))
        if d != d.to_integral_value():
            raise ValueError(f"annualized.{what}[{i}] must be whole dollars, got {v!r}")
        out.append(int(d))
    return out


def _schedule_ai(ai, a: dict[str, Any], annual: int, year: int, knowledge_dir) -> list[ScheduleAiColumn]:
    """Form 2210 Schedule AI, Parts I and II, column by column ("Complete lines 22-27 of one column before going to
    line 22 of the next column")."""
    from taxfill_core.calc import tax_from_taxable_income  # noqa: PLC0415

    allowed = {"filing_status", "agi", "standard_deduction", "itemized", "qbi", "additional_deductions",
               "se_net_earnings", "ss_wages", "other_taxes", "credits", "period_tax"}
    unknown = sorted(set(a) - allowed)
    if unknown:
        raise ValueError(f"annualized has unknown key(s) {unknown}; expected {sorted(allowed)}")
    if "agi" not in a or "filing_status" not in a:
        raise ValueError("annualized needs filing_status and agi (Schedule AI line 1, four cumulative periods)")
    agi = _per_period(a["agi"], "agi")
    itemized = _per_period(a.get("itemized"), "itemized")
    qbi = _per_period(a.get("qbi"), "qbi")
    addl = _per_period(a.get("additional_deductions"), "additional_deductions")
    se = _per_period(a.get("se_net_earnings"), "se_net_earnings")
    wages = _per_period(a.get("ss_wages"), "ss_wages")
    other = _per_period(a.get("other_taxes"), "other_taxes")
    credits = _per_period(a.get("credits"), "credits")
    override = a.get("period_tax")
    override = None if override is None else _per_period(override, "period_tax")
    std = _as_int(a.get("standard_deduction", 0), "annualized.standard_deduction")
    one = Decimal(1)

    def r(x: Decimal) -> int:
        return int(x.quantize(one, ROUND_HALF_UP))

    cols: list[ScheduleAiColumn] = []
    line24 = r(Decimal(annual) * Decimal("0.25"))
    prev27_total = 0
    prev26 = prev27 = 0
    for k in range(4):
        f = ai.annualization[k]
        l3 = r(agi[k] * f)
        l6 = r(itemized[k] * f)
        l8 = max(l6, std)
        l9b = addl[k] if ai.additional_deductions == "line_9b" else 0
        l10 = l8 + qbi[k] + l9b
        l13 = max(0, l3 - l10)
        base = l13 if ai.additional_deductions == "line_9b" else max(0, l13 - addl[k])
        l14 = override[k] if override is not None else tax_from_taxable_income(base, a["filing_status"], year,
                                                                                knowledge_dir=knowledge_dir).tax
        l31 = max(0, ai.se_ss_limits[k] - wages[k])
        # "If your self-employment income for the applicable periods is less than $400, enter zero in Part II, line
        # 28"; lines 33 and 35 are whole-dollar lines of their own, and 36 "Add lines 33 and 35".
        l28 = se[k] if se[k] >= 400 else 0
        l33 = r(ai.se_factors_ss[k] * min(l28, l31))
        l35 = r(l28 * ai.se_factors_medicare[k])
        l36 = l33 + l35
        l19 = max(0, l14 + l36 + other[k] - credits[k])
        l21 = r(l19 * ai.applicable_percentages[k])
        l23 = max(0, l21 - prev27_total)
        l25 = (prev26 - prev27) if k else 0
        l26 = line24 + l25
        l27 = min(l23, l26)
        qbi_line = "9a" if ai.additional_deductions == "line_9b" else "9"
        face = {"1": agi[k], "3": l3, "4": itemized[k], "6": l6, "7": std, "8": l8, qbi_line: qbi[k], "10": l10,
                "11": l3 - l10, "12": 0, "13": l13, "14": int(l14), "15": l36, "16": other[k],
                "17": int(l14) + l36 + other[k], "18": credits[k], "19": l19, "21": l21, "23": l23, "24": line24,
                "26": l26, "27": l27, "28": l28, "30": wages[k], "31": l31, "33": l33, "35": l35, "36": l36}
        if ai.additional_deductions == "line_9b":
            face["9b"] = l9b
        if k:
            face |= {"22": prev27_total, "25": l25}
        cols.append(ScheduleAiColumn(column=_COLUMNS[k], period_end=ai.period_ends[k], line_3_annualized_income=l3,
                                     line_13_taxable=l13, line_14_tax=int(l14), line_15_se_tax=l36, line_19_net_tax=l19,
                                     line_21=l21, line_23=l23, line_26=l26, line_27_installment=l27, face_lines=face))
        prev27_total += l27
        prev26, prev27 = l26, l27
    return cols
