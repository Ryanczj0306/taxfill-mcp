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


class UnderpaymentPenaltyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    installments: list[InstallmentRow]
    pieces: list[PenaltyPiece]
    penalty: Decimal = Field(description="Form 2210 line 19 to the cent (the sum of the worksheet lines).")
    penalty_whole_dollars: int = Field(description="The same, rounded half up to whole dollars.")
    exception: str | None = Field(
        default=None, description="An IRC 6654(e)/(h) exception that zeroed all or part of the penalty, quoted.")
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
    else:
        annual = _as_int(required_annual_payment, "required_annual_payment")
        base, rem = divmod(annual, 4)
        required = [base + (1 if i < rem else 0) for i in range(4)]
        req_note = (f"25 percent of the required annual payment {annual:,} per installment (IRC 6654(d)(1)(A))"
                    + (" — the odd dollars on the earliest installments" if rem else ""))

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

    # ── the FIFO ledger: each credit pays the earliest installment still owed ──
    owed = list(required)
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

    rows = [InstallmentRow(column=_COLUMNS[k], due_date=dues[k], required=required[k], paid_by_due_date=paid_by_due[k],
                           underpayment=required[k] - paid_by_due[k]) for k in range(4)]

    exception = None
    tax_left = None if tax_after_withholding is None else _as_int(tax_after_withholding, "tax_after_withholding")
    if tax_left is not None and tax_left < 1000:
        exception = ("IRC 6654(e)(1): \"No addition to tax shall be imposed under subsection (a) for any taxable year if "
                     "the tax shown on the return for such taxable year ... reduced by the credit allowable under section "
                     f"31, is less than $1,000\" — {tax_left:,} after withholding.")
        portions = [[], [], [], []]
    filed = None if return_filed is None else _as_date(return_filed, "return_filed")
    jan31 = date(year + 1, 1, 31)
    if exception is None and filed is not None and filed <= jan31 and paid_in_full_with_return:
        exception = ("IRC 6654(h): a return filed on or before January 31 with the amount payable paid in full — \"no "
                     "addition to tax shall be imposed under subsection (a) with respect to any underpayment of the 4th "
                     "required installment\".")
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
                        f"not announced yet ({period.source}) — refusing to borrow another quarter's rate. Re-run once "
                        f"knowledge/federal/{year}.yaml carries it, or price only payments made before {period.start}"
                    )
                amt = (Decimal(dollars) * days / cal.day_count * period.rate).quantize(_CENT, ROUND_HALF_UP)
                pieces.append(PenaltyPiece(column=_COLUMNS[k], amount=dollars, start=lo, end=hi, days=days,
                                           rate=period.rate, penalty=amt, paid_on=paid_on))
    total = sum((p.penalty for p in pieces), Decimal("0.00"))
    whole = int(total.quantize(Decimal(1), ROUND_HALF_UP))

    lines = [
        f"Form 2210 ({year}), regular method: {req_note}; {wh_note}.",
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
    return UnderpaymentPenaltyResult(
        year=year, installments=rows, pieces=pieces, penalty=total, penalty_whole_dollars=whole, exception=exception,
        not_modeled=[
            "the required installments themselves — compute the required annual payment with calc op "
            "estimated_tax_safe_harbor (6654(d)) and pass it or the four line-10 amounts",
            "the annualized income installment method (Schedule AI, 6654(d)(2)) — JP5b",
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
