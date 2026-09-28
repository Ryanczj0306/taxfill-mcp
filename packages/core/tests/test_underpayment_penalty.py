"""Phase J JP5a — calc op underpayment_penalty (Form 2210 Part III, regular method).

Worked examples come from the Instructions for Form 2210 (2025): Example 2 (a $500 underpayment paid by a June
10 payment: "56 days"), Examples 3 and 4 (the line-1b allocation and "15"/"61" days), and Table 2, Chart of Total
Days. Demo figures only.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from taxfill_core.penalty import underpayment_penalty

EXAMPLE_3_PAYMENTS = [
    {"date": "2025-04-30", "amount": 2000},
    {"date": "2025-06-15", "amount": 3000},
    {"date": "2025-09-15", "amount": 4000},
    {"date": "2026-01-15", "amount": 4000},
]


def _days_by_column(result):
    out: dict[str, list[int]] = {}
    for p in result.pieces:
        out.setdefault(p.column, []).append(p.days)
    return out


def test_jp5a_instructions_example_3_and_4_allocate_and_count_days():
    r = underpayment_penalty([4000] * 4, EXAMPLE_3_PAYMENTS, year=2025)
    # "On line 1a, column (a) shows $4,000 and columns (b) through (d) show $3,000."
    assert [row.underpayment for row in r.installments] == [4000, 3000, 3000, 3000]
    col_a = [(p.amount, p.days, p.paid_on.isoformat()) for p in r.pieces if p.column == "a"]
    # Example 3: "04/30 $2,000" and "06/15 $2,000" on line 1b, column (a); Example 4: "15" and "61" days.
    assert col_a == [(2000, 15, "2025-04-30"), (2000, 61, "2025-06-15")]
    # "09/15 $3,000" pays column (b); "01/15 $3,000" pays column (c); nothing on line 1b, column (d).
    assert {p.paid_on.isoformat() for p in r.pieces if p.column == "b"} == {"2025-09-15"}
    assert {p.paid_on.isoformat() for p in r.pieces if p.column == "c"} == {"2026-01-15"}
    assert all(p.paid_on is None for p in r.pieces if p.column == "d")
    days = _days_by_column(r)
    assert (sum(days["b"]), sum(days["c"]), sum(days["d"])) == (92, 122, 90)
    # 0.07 / 365 x (2,000x15 + 2,000x61 + 3,000x92 + 3,000x122 + 3,000x90) = 74,480 / 365
    assert r.penalty == Decimal("204.05") and r.penalty_whole_dollars == 204


def test_jp5a_instructions_example_2_applies_the_june_payment_to_april_first():
    # "You had a $500 underpayment remaining after your April 15 payment. The June 15 installment required a
    # payment of $1,200. On June 10, you made a payment of $1,200 ... The penalty for the April 15 installment is
    # figured from April 15 to June 10 (56 days). The amount remaining to be applied to the June 15 installment
    # is $700."
    r = underpayment_penalty([1200] * 4, [{"date": "2025-04-15", "amount": 700}, {"date": "2025-06-10", "amount": 1200},
                                         {"date": "2025-09-15", "amount": 1200}, {"date": "2026-01-15", "amount": 1200}],
                             year=2025)
    a = [p for p in r.pieces if p.column == "a"]
    assert [(p.amount, p.days) for p in a] == [(500, 56)]
    assert r.installments[1].paid_by_due_date == 700 and r.installments[1].underpayment == 500


def test_jp5a_table_2_total_days_per_rate_period():
    # Table 2, Chart of Total Days: an underpayment unpaid for whole rate periods.
    r = underpayment_penalty([1000] * 4, [], year=2025)
    days = _days_by_column(r)
    assert days == {"a": [76, 92, 92, 105], "b": [15, 92, 92, 105], "c": [15, 92, 105], "d": [90]}


def test_jp5a_withholding_is_ratable_unless_actual_dates_are_elected():
    # 8,000 withheld against 12,000 required: 2,000 deemed on each due date (IRC 6654(g)(1)). The arrears
    # compound exactly as Form 2210 Section A shows them: column (b)'s 2,000 first pays column (a)'s 1,000
    # (line 14), so line 17 reads 1,000 / 2,000 / 3,000 / 3,000.
    ratable = underpayment_penalty(required_annual_payment=12000, withholding=8000, year=2025)
    assert [row.underpayment for row in ratable.installments] == [1000, 2000, 3000, 3000]
    # All 8,000 actually withheld in January 2025 (a demo bonus): it covers (a), (b) and 2,000 of (c) on time
    # (lines 18 and 12 carry the overpayment forward).
    actual = underpayment_penalty(required_annual_payment=12000, withholding=8000, year=2025,
                                  withholding_dates=[{"date": "2025-01-31", "amount": 8000}])
    assert [row.underpayment for row in actual.installments] == [0, 0, 1000, 3000]
    assert actual.penalty < ratable.penalty
    with pytest.raises(ValueError, match="ALL amounts withheld"):
        underpayment_penalty(required_annual_payment=12000, withholding=8000, year=2025,
                             withholding_dates=[{"date": "2025-01-31", "amount": 5000}])


def test_jp5a_the_statutory_exceptions():
    small = underpayment_penalty([1000] * 4, [], year=2025, tax_after_withholding=999)
    assert small.penalty == 0 and "6654(e)(1)" in small.exception
    early = underpayment_penalty([1000] * 4, [], year=2025, return_filed="2026-01-31", paid_in_full_with_return=True)
    assert "6654(h)" in early.exception and not [p for p in early.pieces if p.column == "d"]
    late = underpayment_penalty([1000] * 4, [], year=2025, return_filed="2026-02-01", paid_in_full_with_return=True)
    assert late.exception is None and [p for p in late.pieces if p.column == "d"]


def test_jp5a_2026_prices_the_6_percent_quarter_and_fails_closed_on_q1_2027():
    # April 15, 2026 underpayment paid June 15, 2026: 61 days, all in the 2nd quarter at 6%.
    r = underpayment_penalty([1000, 0, 0, 0], [{"date": "2026-06-15", "amount": 1000}], year=2026)
    assert [(p.days, p.rate) for p in r.pieces] == [(61, Decimal("0.06"))]
    assert r.penalty == (Decimal(1000) * 61 / 365 * Decimal("0.06")).quantize(Decimal("0.01"))
    # Anything unpaid into January 2027 needs the Q1 2027 rate, which is not announced: refuse.
    with pytest.raises(ValueError, match="not announced yet"):
        underpayment_penalty([1000] * 4, [], year=2026)


def test_jp5a_a_year_without_the_calendar_refuses():
    with pytest.raises(ValueError, match="no tax.estimated_tax_penalty block"):
        underpayment_penalty([1000] * 4, [], year=2024)


def test_jp5a_input_shape_errors_are_prescriptive():
    with pytest.raises(ValueError, match="exactly one of"):
        underpayment_penalty(year=2025)
    with pytest.raises(ValueError, match="four amounts"):
        underpayment_penalty([1000] * 3, year=2025)
    with pytest.raises(ValueError, match="ISO date"):
        underpayment_penalty([1000] * 4, [{"date": "April 30", "amount": 5}], year=2025)


def test_jp5a_the_rate_table_routes_to_the_penalty_topic():
    from taxfill_core.sources import get_sources  # noqa: PLC0415

    res = get_sources("quarterly interest rates", 2025)
    assert {s.topic for s in res.sources} == {"underpayment_penalty"}   # was a miss onto nonresident_fdap
    assert "https://www.irs.gov/payments/quarterly-interest-rates" in {s.url for s in res.sources}
