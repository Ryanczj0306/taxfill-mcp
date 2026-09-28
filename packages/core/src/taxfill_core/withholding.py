"""calc op ``withholding_projection`` — what each employer will withhold, check by check (Phase J JP1c).

Pub 15-T's percentage method for automated payroll (Worksheet 1A, the knowledge pack's ``payroll_withholding``
block), counted by PAY DATE; supplemental wages under Treas. Reg. 31.3402(g)-1 (the pack's
``tax.supplemental_withholding`` block, P-017): the optional flat rate only when its two conditions hold, the
aggregate procedure otherwise, both methods as a range when a fact is unknown or the reading is interpretive, and the
mandatory rate over $1,000,000; the two methods an employee may request in writing (Pub 15-T section 6, cumulative
wages and part-year employment), each behind its own gate; and the per-employer social security and Medicare
withholding. The result's ``w2s`` feed estimate_refund's ``IncomeSnapshot.w2s``.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taxfill_core.knowledge import Citation, load_knowledge

__all__ = ["WithholdingProjectionResult", "withholding_projection"]

Frequency = Literal["weekly", "biweekly", "semimonthly", "monthly", "quarterly", "semiannually", "annually", "daily"]
_STEP_DAYS = {"weekly": 7, "biweekly": 14}


class W4Facts(BaseModel):
    """The employee's Form W-4 as the employer holds it."""

    model_config = ConfigDict(extra="forbid")

    form: Literal["2020_or_later", "pre_2020"] = "2020_or_later"
    filing_status: Literal["single", "married_filing_separately", "married_filing_jointly", "head_of_household"] = (
        "single")
    step2_checkbox: bool = False
    step3_credits: Decimal = Decimal(0)
    step4a_other_income: Decimal = Decimal(0)
    step4b_deductions: Decimal = Decimal(0)
    step4c_extra_per_period: Decimal = Decimal(0)
    allowances: int = Field(default=0, ge=0, description="pre_2020 only: allowances claimed.")
    marital_pre_2020: Literal["single", "married"] = Field(default="single", description="pre_2020 line 3.")
    additional_pre_2020: Decimal = Field(default=Decimal(0), description="pre_2020 line 6.")
    exempt: bool = False


class SupplementalPayment(BaseModel):
    """One bonus / commission / other supplemental payment."""

    model_config = ConfigDict(extra="forbid")

    date: date
    amount: Decimal = Field(gt=0)
    concurrent_with_regular: bool | None = Field(
        default=None, description="Paid in the same payment as regular wages. None: read off the pay dates.")
    separately_stated: bool | None = Field(
        default=None, description="Separately stated on the employer's payroll records (31.3402(g)-1(a)(7)(i)(B)).")


class EmployerWithholding(BaseModel):
    """One employer's payroll facts."""

    model_config = ConfigDict(extra="forbid")

    label: str
    pay_frequency: Frequency
    wages_per_period: Decimal = Field(ge=0, description="Taxable wages per regular check (after pre-tax deferrals).")
    fica_wages_per_period: Decimal | None = Field(default=None, ge=0, description="W-2 box 3/5 basis; default wages.")
    pay_dates: list[date] = Field(default_factory=list, description="Explicit pay dates (counted by PAY date).")
    first_pay_date: date | None = None
    employment_end: date | None = Field(default=None, description="No regular check is paid after this date.")
    first_period_wages: Decimal | None = Field(
        default=None, ge=0, description="A partial first period's wages (withheld as a full payroll period).")
    w4: W4Facts = Field(default_factory=W4Facts)
    nonresident_alien: bool = Field(default=False, description="Pub 15-T's nonresident alien add-on applies.")
    first_paid_before_2020: bool = False
    withheld_prior_year: bool | None = Field(
        default=None, description="Income tax was withheld from this employee's regular wages last calendar year.")
    supplemental: list[SupplementalPayment] = Field(default_factory=list)
    fica_exempt: bool = Field(default=False, description="Your judgment (calc op employee_fica's rules).")
    method: Literal["percentage", "cumulative", "part_year"] = "percentage"
    written_request: bool = Field(default=False, description="The employee's written request (both section 6 methods).")
    same_period_since_january: bool | None = Field(default=None, description="cumulative: paid on this payroll period "
                                                                             "since the beginning of the year.")
    calendar_year_basis: bool | None = Field(default=None, description="part_year: the request's statement.")
    anticipated_days_employed: int | None = Field(
        default=None, ge=0, description="part_year: days in all terms of continuous employment this year (<= 245).")
    last_day_prior_employment: date | None = Field(
        default=None, description="part_year: the last day of employment with any prior employer this year.")
    employment_start: date | None = Field(default=None, description="part_year: the first day of this employment.")

    @model_validator(mode="after")
    def _dates(self) -> "EmployerWithholding":
        if not self.pay_dates and self.first_pay_date is None:
            raise ValueError(f"employer {self.label!r}: pass pay_dates or first_pay_date — withholding is counted by "
                             f"PAY DATE, so the checks must be known")
        return self


class CheckRow(BaseModel):
    date: date
    wages: Decimal
    withheld: int


class SupplementalRow(BaseModel):
    date: date
    amount: Decimal
    method: Literal["flat", "aggregate", "range", "interpretive"]
    flat: int | None
    aggregate: int
    mandatory_over_1m: int
    reason: str


class EmployerProjection(BaseModel):
    label: str
    checks: list[CheckRow]
    regular_total: int
    supplemental: list[SupplementalRow]
    box2_low: int
    box2_high: int
    box3: int
    box4: int
    box5: int
    box6: int
    notes: list[str]


class WithholdingProjectionResult(BaseModel):
    """Result of :func:`withholding_projection`."""

    model_config = ConfigDict(extra="forbid")

    year: int
    employers: list[EmployerProjection]
    federal_withholding_low: int
    federal_withholding_high: int
    w2s: list[dict[str, Any]] = Field(description="One dict per employer, ready for IncomeSnapshot.w2s (box 2 = low).")
    work: str
    citations: list[Citation]


def _round(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _last_day(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _schedule(e: EmployerWithholding, year: int) -> list[date]:
    end = min(e.employment_end or date(year, 12, 31), date(year, 12, 31))
    if e.pay_dates:
        return sorted(d for d in e.pay_dates if d.year == year and d <= end)
    d = e.first_pay_date
    out: list[date] = []
    if e.pay_frequency in _STEP_DAYS:
        while d <= end:
            if d.year == year:
                out.append(d)
            d += timedelta(days=_STEP_DAYS[e.pay_frequency])
    elif e.pay_frequency in ("semimonthly", "monthly"):
        for m in range(1, 13):
            days = [date(year, m, 15), _last_day(year, m)] if e.pay_frequency == "semimonthly" else [_last_day(year, m)]
            out.extend(x for x in days if d <= x <= end)
    else:
        raise ValueError(f"employer {e.label!r}: a {e.pay_frequency} schedule needs explicit pay_dates")
    return out


def _table(pw, w4: W4Facts):
    if w4.form == "pre_2020":
        return pw.standard, ("married_filing_jointly" if w4.marital_pre_2020 == "married" else "single_or_mfs")
    key = {"married_filing_jointly": "married_filing_jointly", "head_of_household": "head_of_household"}.get(
        w4.filing_status, "single_or_mfs")
    return (pw.step2_checkbox if w4.step2_checkbox else pw.standard), key


def _annual_tax(rows, amount: Decimal) -> Decimal:
    row = next(r for r in reversed(rows) if amount >= r.at_least)
    return row.tentative + row.rate * (amount - row.over)


def _per_period(pw, e: EmployerWithholding, wages: Decimal, periods: int, addon: Decimal) -> Decimal:
    """Worksheet 1A for one payroll period (exact, before rounding)."""
    w4 = e.w4
    if w4.exempt:
        return Decimal(0)
    annual = (wages + addon) * periods
    tables, key = _table(pw, w4)
    if w4.form == "2020_or_later":
        line_1g = 0 if w4.step2_checkbox else pw.worksheet_1a_line_1g[
            "married_filing_jointly" if w4.filing_status == "married_filing_jointly" else "other"]
        adjusted = max(Decimal(0), annual + w4.step4a_other_income - (w4.step4b_deductions + line_1g))
        tentative = _annual_tax(getattr(tables, key), adjusted) / periods
        return max(Decimal(0), tentative - w4.step3_credits / periods) + w4.step4c_extra_per_period
    adjusted = max(Decimal(0), annual - w4.allowances * pw.allowance_value)
    return _annual_tax(getattr(tables, key), adjusted) / periods + w4.additional_pre_2020


def withholding_projection(
    employers: list[dict[str, Any]],
    year: int = 2026,
    knowledge_dir: str | Path | None = None,
) -> WithholdingProjectionResult:
    """Project each employer's federal income tax, social security and Medicare withholding for ``year``.

    Per regular check (counted by PAY DATE, through ``employment_end``): Pub 15-T Worksheet 1A — annualize the
    period's wages (plus the nonresident alien add-on), subtract Step 4(b) and line 1g (0 with the Step 2 box),
    add Step 4(a), look up the STANDARD or Step 2 checkbox table, subtract Step 3, add Step 4(c); a pre-2020 W-4
    takes $4,300 per allowance and no head-of-household table. Rounded to the dollar per check (Pub 15-T's rounding
    option, used consistently). ``method`` 'cumulative' and 'part_year' are Pub 15-T section 6's employee-requested
    methods, refused unless their conditions are stated.

    Supplemental wages (Treas. Reg. 31.3402(g)-1): over $1,000,000 in the year from one employer, the excess at the
    mandatory rate. Otherwise the optional flat rate is open only when (a)(7)(i)(B) — not paid concurrently with
    regular wages, or separately stated — and (a)(7)(i)(C) — income tax withheld from regular wages this year or last
    — both hold: forced aggregate when either fails; both methods (the employer's option) as a RANGE when both hold
    or a fact is unknown; a bonus paid with the FIRST withheld regular check is labeled an interpretive reading of
    (C). The aggregate procedure withholds on (the concurrent or most recent regular wages + the supplemental) as one
    payment and subtracts the regular withholding.

    Social security 6.2% to the year's wage base and Medicare 1.45% plus 0.9% over $200,000 are PER EMPLOYER
    (each employer's own base and IRC 3102(f)(1) threshold) — calc op employee_fica reconciles the person's
    liability across employers.
    """
    pack = load_knowledge("federal", year, base_dir=knowledge_dir)
    pw = pack.payroll_withholding
    sup = pack.tax.supplemental_withholding
    ess = pack.tax.employee_social_security
    if pw is None or sup is None or ess is None:
        raise ValueError(f"the federal {year} knowledge pack lacks payroll_withholding / supplemental_withholding / "
                         f"employee_social_security — withholding_projection needs Pub 15-T and Pub 15 for {year}")
    flat_rate, high_rate, high_threshold = Decimal(str(sup.flat_rate)), Decimal(str(sup.high_rate)), Decimal(
        sup.high_threshold)
    out: list[EmployerProjection] = []
    for raw in employers:
        e = EmployerWithholding.model_validate(raw)
        periods = pw.pay_periods[e.pay_frequency]
        addon = Decimal(0)
        notes: list[str] = []
        if e.nonresident_alien:
            table_key = "pre_2020" if (e.w4.form == "pre_2020" and e.first_paid_before_2020) else "w4_2020_or_later"
            addon = pw.nonresident_alien_addon[table_key][e.pay_frequency]
            notes.append(f"nonresident alien add-on ${addon:,} per {e.pay_frequency} check (Pub 15-T, Table "
                         f"{'1' if table_key == 'pre_2020' else '2'}) — for the computation only, never on the W-2")
        dates = _schedule(e, year)
        wages_on = {d: (e.first_period_wages if i == 0 and e.first_period_wages is not None else e.wages_per_period)
                    for i, d in enumerate(dates)}
        if e.first_period_wages is not None and dates:
            notes.append(f"the first check ({dates[0].isoformat()}) is a partial period: its wages are withheld as a "
                         f"full {e.pay_frequency} payroll period's (the payroll period, not the days worked, sets the "
                         f"table)")
        checks: list[CheckRow] = []
        if e.method == "cumulative":
            if not e.written_request or e.same_period_since_january is not True:
                raise ValueError(
                    f"employer {e.label!r}: the cumulative wages method needs the employee's WRITTEN request and "
                    f"the same kind of payroll period since the beginning of the year (Pub 15-T section 6: \"An "
                    f"employee may ask you, in writing, to withhold tax on cumulative wages. If you agree to do so, "
                    f"and you've paid the employee for the same kind of payroll period ... since the beginning of the "
                    f"year\")")
            paid, withheld = Decimal(0), 0
            for k, d in enumerate(dates, start=1):
                paid += wages_on[d]
                total = _round(_per_period(pw, e, paid / k, periods, addon) * k)
                w = max(0, total - withheld)
                checks.append(CheckRow(date=d, wages=wages_on[d], withheld=w))
                withheld += w
            notes.append("cumulative wages method (Pub 15-T section 6), at the employee's written request")
        elif e.method == "part_year":
            if (not e.written_request or e.calendar_year_basis is not True or e.anticipated_days_employed is None
                    or e.employment_start is None):
                raise ValueError(
                    f"employer {e.label!r}: the part-year employment method needs the employee's written request "
                    f"under penalties of perjury stating the last day of prior employment, the calendar-year basis, "
                    f"and that they anticipate \"no more than 245 days in all terms of continuous employment\" — "
                    f"pass written_request, calendar_year_basis, anticipated_days_employed and employment_start")
            if e.anticipated_days_employed > 245:
                raise ValueError(
                    f"employer {e.label!r}: {e.anticipated_days_employed} days is over the part-year method's limit — "
                    f"the employee must reasonably anticipate \"no more than 245 days in all terms of continuous "
                    f"employment\" this year (Pub 15-T section 6; Treas. Reg. 31.3402(h)(4)-1(b))")
            period_days = {"weekly": 7, "biweekly": 14, "semimonthly": 15, "monthly": 30}.get(e.pay_frequency)
            if period_days is None:
                raise ValueError(f"employer {e.label!r}: the part-year method needs a weekly/biweekly/semimonthly/"
                                 f"monthly payroll period")
            prior_end = e.last_day_prior_employment or date(year - 1, 12, 31)
            gap_periods = Decimal((e.employment_start - prior_end).days) / period_days
            paid, withheld = Decimal(0), 0
            for k, d in enumerate(dates, start=1):
                paid += wages_on[d]
                total_periods = k + gap_periods
                total = _round(_per_period(pw, e, paid / total_periods, periods, addon) * total_periods)
                w = max(0, total - withheld)
                checks.append(CheckRow(date=d, wages=wages_on[d], withheld=w))
                withheld += w
            notes.append(f"part-year employment method (Pub 15-T section 6): {gap_periods:.2f} payroll periods "
                         f"between the last employment and this one count in the divisor")
        else:
            for d in dates:
                checks.append(CheckRow(date=d, wages=wages_on[d],
                                       withheld=_round(_per_period(pw, e, wages_on[d], periods, addon))))
        regular_total = sum(c.withheld for c in checks)

        rows: list[SupplementalRow] = []
        cumulative_sup = Decimal(0)
        low = high = 0
        for s in sorted(e.supplemental, key=lambda x: x.date):
            concurrent = s.concurrent_with_regular if s.concurrent_with_regular is not None else s.date in wages_on
            base_check = next((c for c in reversed(checks) if c.date <= s.date), None)
            before = [c for c in checks if c.date < s.date and c.withheld > 0]
            # the mandatory rate on the part of the year's supplemental wages over $1,000,000 (31.3402(g)-1(a)(2))
            over = max(Decimal(0), cumulative_sup + s.amount - max(cumulative_sup, high_threshold))
            cumulative_sup += s.amount
            mandatory = _round(over * high_rate)
            part = s.amount - over
            regular_wages = base_check.wages if base_check is not None else e.wages_per_period
            regular_wh = base_check.withheld if base_check is not None else 0
            aggregate = max(0, _round(_per_period(pw, e, regular_wages + part, periods, addon)) - regular_wh)
            flat = _round(part * flat_rate)
            cond_b = (not concurrent) or s.separately_stated
            if e.withheld_prior_year is True or before:
                cond_c: bool | None | str = True
            elif concurrent and base_check is not None and base_check.date == s.date and base_check.withheld > 0:
                cond_c = "interpretive"
            elif e.withheld_prior_year is None:
                cond_c = None
            else:
                cond_c = False
            if part == 0:
                method, reason = "flat", "the whole payment is over $1,000,000: the mandatory rate only"
                flat_value: int | None = 0
                aggregate = 0
            elif cond_b is False or cond_c is False:
                method, flat_value = "aggregate", None
                reason = ("the aggregate procedure is REQUIRED: "
                          + ("paid concurrently with regular wages and not separately stated (31.3402(g)-1(a)(7)(i)(B) "
                             "fails)" if cond_b is False else
                             "no income tax was withheld from regular wages this year or last (31.3402(g)-1(a)(7)(i)(C) "
                             "fails)"))
            elif cond_c == "interpretive":
                method, flat_value = "interpretive", flat
                reason = ("paid with the FIRST withheld regular check: whether income tax \"has been withheld from "
                          "regular wages ... during the calendar year of the payment\" when the only withholding is in "
                          "this same payment is an interpretive choice — both methods shown")
            elif cond_b is None or cond_c is None:
                method, flat_value = "range", flat
                reason = ("a fact is unknown (" + ("separately stated" if cond_b is None else "withholding last year")
                          + "): both methods are possible, shown as a range")
            else:
                method, flat_value = "range", flat
                reason = "both conditions hold: the flat rate is the employer's OPTION — both methods shown"
            rows.append(SupplementalRow(date=s.date, amount=s.amount, method=method, flat=flat_value,
                                        aggregate=aggregate, mandatory_over_1m=mandatory, reason=reason))
            options = [aggregate] + ([flat_value] if flat_value is not None and method != "aggregate" else [])
            low += min(options) + mandatory
            high += max(options) + mandatory
        fica_wages = [(e.fica_wages_per_period if e.fica_wages_per_period is not None else wages_on[c.date])
                      for c in checks]
        if e.first_period_wages is not None and checks and e.fica_wages_per_period is None:
            fica_wages[0] = e.first_period_wages
        fica_total = sum(fica_wages, Decimal(0)) + sum((s.amount for s in e.supplemental), Decimal(0))
        base = Decimal(ess.ss_wage_base)
        ss_rate, med_rate = Decimal(str(ess.rate)), Decimal(str(ess.medicare_rate or "0.0145"))
        addl_rate = Decimal(str(ess.additional_medicare_withholding_rate or "0.009"))
        if e.fica_exempt:
            box4 = box6 = 0
        else:
            box4 = _round(min(fica_total, base) * ss_rate)
            # IRC 3102(f)(1): the employer withholds the 0.9% on the wages IT pays over the threshold.
            threshold = Decimal(ess.additional_medicare_withholding_threshold or 200_000)
            box6 = _round(fica_total * med_rate + max(Decimal(0), fica_total - threshold) * addl_rate)
        out.append(EmployerProjection(
            label=e.label, checks=checks, regular_total=regular_total, supplemental=rows,
            box2_low=regular_total + low, box2_high=regular_total + high, box3=_round(min(fica_total, base)),
            box4=box4, box5=_round(fica_total), box6=box6, notes=notes))
    total_low = sum(p.box2_low for p in out)
    total_high = sum(p.box2_high for p in out)
    w2s = [{"employer": p.label, "box1": _round(sum((c.wages for c in p.checks), Decimal(0))
                                                + sum((r.amount for r in p.supplemental), Decimal(0))),
            "box2": p.box2_low, "box3": p.box3, "box4": p.box4, "box5": p.box5, "box6": p.box6} for p in out]
    work = (f"Withholding projection ({year}): " + "; ".join(
        f"{p.label}: {len(p.checks)} check(s) by pay date, regular ${p.regular_total:,}"
        + (f", supplemental {', '.join(r.method for r in p.supplemental)}" if p.supplemental else "")
        + f" -> box 2 ${p.box2_low:,}" + (f"-${p.box2_high:,}" if p.box2_high != p.box2_low else "")
        + f", box 4 ${p.box4:,}, box 6 ${p.box6:,}" for p in out)
        + ". Pub 15-T (2026) Worksheet 1A and the Annual Percentage Method tables; supplemental wages under Treas. "
          "Reg. 31.3402(g)-1(a)(6)-(7); social security and Medicare per employer.")
    return WithholdingProjectionResult(
        year=year, employers=out, federal_withholding_low=total_low, federal_withholding_high=total_high, w2s=w2s,
        work=work, citations=[pw.citation, sup.citation])
