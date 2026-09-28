"""Paystub to projected W-2 (Phase J JP3b): the year-to-date actuals plus the checks still to be PAID.

The Instructions for Forms W-2 and W-3 (2026) set the rules this op follows:

* "Calendar year basis. The entries on Form W-2 must be based on wages paid during the calendar year" — so the
  projection adds only the checks whose PAY date falls on or before December 31, and a check for late-December
  work paid on January 1 goes on next year's W-2;
* "Box 1—Wages, tips, other compensation ... do not include elective deferrals (such as employee contributions
  to a section 401(k) or 403(b) plan)" — pre-tax 401(k) dollars come out of box 1 only;
* cafeteria-plan (IRC 125) premiums, HSA contributions through the plan (box 12 code W), health FSA, dependent
  care assistance (box 10, IRC 129) and qualified transportation fringes (IRC 132(f)) come out of boxes 1, 3 and 5;
* box 3 is capped at the year's social security wage base ("The total of boxes 3 and 7 cannot exceed" it), per
  employer — the same cap the employer's own payroll applies.

Nothing is annualized: an ended job adds no checks, and the stub's own YTD figures are taken as the actuals
through its pay date. Federal withholding for the remaining checks repeats the stub's current-period figure
(level pay); calc op withholding_projection computes it from the Form W-4 instead.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.knowledge import load_knowledge

_CENT = Decimal("0.01")
_DEDUCTIONS = ("pretax_401k", "section_125", "hsa_cafeteria", "health_fsa", "dependent_care_fsa", "commuter_132f",
               "roth_401k")
# stub YTD key for each per-period deduction
_STUB_YTD = {"pretax_401k": "pretax_401k_ytd", "section_125": "section_125_ytd", "hsa_cafeteria": "hsa_ytd",
             "health_fsa": "health_fsa_ytd", "dependent_care_fsa": "dependent_care_fsa_ytd",
             "commuter_132f": "commuter_ytd", "roth_401k": "roth_401k_ytd"}


class PaystubW2Result(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    employer: str
    stub_pay_date: date
    remaining_pay_dates: list[date] = Field(description="Checks still to be PAID in the year, after the stub's.")
    next_year_pay_dates: list[date] = Field(
        description="The first check paid after December 31 (or the final check of a job ending late in the year): "
                    "whatever December work it pays goes on next year's W-2 (Calendar year basis).")
    totals: dict[str, Decimal] = Field(description="Gross and each deduction for the year, to the cent.")
    w2: dict[str, Any] = Field(description="The projected W-2 as estimate_refund's IncomeSnapshot.w2s entry.")
    assumptions: list[str]
    work: str


def _dec(value: Any, what: str) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    try:
        d = Decimal(str(value).replace(",", "").replace("$", ""))
    except Exception as exc:  # noqa: BLE001 — every unparsable input gets the same prescriptive error
        raise ValueError(f"{what} must be an amount, got {value!r}") from exc
    if d < 0:
        raise ValueError(f"{what} must not be negative, got {value!r}")
    return d


def _date(value: Any, what: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{what} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


def _last_day(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


def _schedule_after(first: date, frequency: str, after: date, through: date) -> list[date]:
    """Pay dates strictly after ``after`` and on or before ``through`` (weekly/biweekly step from the first pay
    date; semimonthly pays the 15th and the last day; monthly the last day)."""
    out: list[date] = []
    if frequency in ("weekly", "biweekly"):
        step = timedelta(days=7 if frequency == "weekly" else 14)
        d = first
        while d <= through:
            if d > after:
                out.append(d)
            d += step
        return out
    if frequency in ("semimonthly", "monthly"):
        y, m = after.year, after.month
        while date(y, m, 1) <= through:
            days = [date(y, m, 15), _last_day(y, m)] if frequency == "semimonthly" else [_last_day(y, m)]
            out.extend(d for d in days if after < d <= through and d >= first)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out
    raise ValueError(f"pay_frequency {frequency!r} has no regular schedule — pass the remaining checks as "
                     f"remaining_pay_dates instead")


def paystub_to_w2(
    stub: dict[str, Any],
    employment: dict[str, Any],
    year: int,
    *,
    remaining_pay_dates: list[str] | None = None,
    knowledge_dir: str | Path | None = None,
) -> PaystubW2Result:
    """Project one job's Form W-2 for ``year`` from its latest stub plus the checks still to be paid.

    Args:
        stub: the extract_document('paystub') reading (pay_date, gross_ytd, the *_ytd deductions, the current-period
            federal withholding).
        employment: the Profile.employment record for this job (employer, end, pay_frequency, first_pay_date,
            gross_per_period, deductions_per_period).
        remaining_pay_dates: the actual remaining pay dates, when the schedule is irregular.
    """
    pack = load_knowledge("federal", year, base_dir=knowledge_dir)
    ss = pack.tax.employee_social_security if pack.tax is not None else None
    if ss is None or ss.medicare_rate is None:
        raise ValueError(f"knowledge/federal/{year}.yaml has no tax.employee_social_security block with the Medicare "
                         f"rates — the wage base and the FICA rates come from it")
    employer = str(employment.get("employer") or stub.get("employer_name") or "")
    paid = _date(stub.get("pay_date"), "stub.pay_date")
    if paid.year != year:
        raise ValueError(f"the stub is paid {paid.isoformat()}, not in {year}: its figures belong to the {paid.year} "
                         f"W-2 (Calendar year basis)")
    end = employment.get("end")
    end_d = _date(end, "employment.end") if end not in (None, "") else None
    dec31 = date(year, 12, 31)
    last_day_worked = min(end_d, dec31) if end_d else dec31
    per = employment.get("deductions_per_period") or {}
    unknown = sorted(set(per) - set(_DEDUCTIONS) - {"after_tax_401k", "plan_loan_repayment"})
    if unknown:
        raise ValueError(f"employment.deductions_per_period has unknown key(s) {unknown}")

    assumptions: list[str] = []
    if remaining_pay_dates is not None:
        dates = sorted(_date(d, "remaining_pay_dates[]") for d in remaining_pay_dates)
        remaining = [d for d in dates if paid < d <= dec31]
        next_year = [d for d in dates if d > dec31]
    elif end_d is not None and end_d <= paid:
        remaining, next_year = [], []
        assumptions.append(f"the job ended {end_d.isoformat()}, on or before the stub's pay date — no further checks "
                           f"(an ended job is never annualized)")
    else:
        freq = employment.get("pay_frequency")
        first = employment.get("first_pay_date")
        if not freq or not first:
            raise ValueError("employment needs pay_frequency and first_pay_date (or pass remaining_pay_dates) to "
                             "count the checks still to be paid")
        first_d = _date(first, "employment.first_pay_date")
        # the check for the last period worked may be PAID after it: look one period past the last day worked
        horizon = last_day_worked + timedelta(days=16)
        sched = _schedule_after(first_d, freq, paid, horizon)
        if end_d is None:
            sched = [d for d in sched if d <= dec31 or d - dec31 <= timedelta(days=16)]
        remaining = [d for d in sched if d <= dec31]
        next_year = [d for d in sched if d > dec31][:1]      # the first check after December 31 carries any
        if end_d is not None:                                  # late-December work onto next year's W-2
            # the final check covers the last period worked; nothing after it
            final = [d for d in sched if d >= end_d][:1]
            remaining = [d for d in sched if d < end_d] + [d for d in final if d <= dec31]
            next_year = [d for d in final if d > dec31]
        assumptions.append(f"{freq} checks counted by PAY date after {paid.isoformat()}"
                           + (f" through the job's end {end_d.isoformat()} — the final check is priced at a full "
                              f"period's gross; pass remaining_pay_dates and adjust if it is prorated"
                              if end_d else " through December 31"))
    n = len(remaining)
    gross_pp = _dec(employment.get("gross_per_period"), "employment.gross_per_period")
    if n and gross_pp == 0:
        raise ValueError("employment.gross_per_period is needed to project the remaining checks")
    totals: dict[str, Decimal] = {"gross": _dec(stub.get("gross_ytd"), "stub.gross_ytd") + gross_pp * n}
    for key in _DEDUCTIONS:
        totals[key] = _dec(stub.get(_STUB_YTD[key]), f"stub.{_STUB_YTD[key]}") + _dec(per.get(key), key) * n
    fed = _dec(stub.get("federal_withholding_ytd"), "stub.federal_withholding_ytd") + \
        _dec(stub.get("federal_withholding_current"), "stub.federal_withholding_current") * n
    if n:
        assumptions.append("federal withholding on the remaining checks repeats the stub's current-period figure "
                           "(level pay) — calc op withholding_projection prices it from the Form W-4")
    cafeteria = (totals["section_125"] + totals["hsa_cafeteria"] + totals["health_fsa"] + totals["dependent_care_fsa"]
                 + totals["commuter_132f"])
    box1 = totals["gross"] - totals["pretax_401k"] - cafeteria
    box5 = totals["gross"] - cafeteria
    box3 = min(box5, Decimal(ss.ss_wage_base))
    box4 = (box3 * ss.rate).quantize(_CENT, ROUND_HALF_UP)
    box6 = (box5 * ss.medicare_rate).quantize(_CENT, ROUND_HALF_UP)
    if ss.additional_medicare_withholding_threshold and box5 > ss.additional_medicare_withholding_threshold:
        box6 += ((box5 - ss.additional_medicare_withholding_threshold) * ss.additional_medicare_withholding_rate
                 ).quantize(_CENT, ROUND_HALF_UP)

    def whole(x: Decimal) -> int:
        return int(x.quantize(Decimal(1), ROUND_HALF_UP))

    box12 = [{"code": c, "amount": whole(totals[k])} for c, k in (("D", "pretax_401k"), ("AA", "roth_401k"),
                                                                   ("W", "hsa_cafeteria")) if totals[k] > 0]
    w2 = {"employer": employer, "box1": whole(box1), "box2": whole(fed), "box3": whole(box3), "box4": whole(box4),
          "box5": whole(box5), "box6": whole(box6), "box10": whole(totals["dependent_care_fsa"]), "box12": box12}
    dc = getattr(pack.tax, "dependent_care", None)
    work = (
        f"Projected W-2 ({year}) for {employer or 'the employer'}: the stub's YTD through {paid.isoformat()} plus "
        f"{n} check(s) still to be paid ({', '.join(d.isoformat() for d in remaining) or 'none'})"
        + (f"; paid after December 31, so on the {year + 1} W-2: {', '.join(d.isoformat() for d in next_year)}"
           if next_year else "")
        + f". Gross {totals['gross']:,}; box 1 = gross - pre-tax 401(k) {totals['pretax_401k']:,} - cafeteria-plan "
          f"reductions {cafeteria:,} = {box1:,}; boxes 3/5 exclude only the cafeteria-plan reductions (box 5 "
          f"{box5:,}; box 3 capped at the {ss.ss_wage_base:,} wage base = {box3:,}); box 4 = box 3 x {ss.rate}; box 6 "
          f"= box 5 x {ss.medicare_rate} (+ {ss.additional_medicare_withholding_rate} over "
          f"{ss.additional_medicare_withholding_threshold:,} at this employer); box 10 = dependent care FSA "
          f"{totals['dependent_care_fsa']:,}."
    )
    if dc is not None and totals["dependent_care_fsa"] > 0:
        work += (" Dependent care benefits over the year's exclusion limit are taxable wages — the estimator "
                 "applies the limit (tax.dependent_care).")
    return PaystubW2Result(year=year, employer=employer, stub_pay_date=paid, remaining_pay_dates=remaining,
                           next_year_pay_dates=next_year, totals=totals, w2=w2, assumptions=assumptions, work=work)
