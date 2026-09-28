"""calc op withholding_projection (Phase J JP1c). All data synthetic; the worked figures are Pub 15 (2026)'s.

The tests are keyed on FACTS, never on hire status: whether a bonus may take the flat 22% turns on Treas. Reg.
31.3402(g)-1(a)(7)(i)(B) (not paid concurrently with regular wages, or separately stated) and (C) (income tax
withheld from regular wages this year or last).
"""
from __future__ import annotations

from datetime import date

import pytest

from taxfill_core.estimate import IncomeSnapshot, W2Facts
from taxfill_core.withholding import withholding_projection


def _one(**over):
    e = {"label": "Demo Co", "pay_frequency": "monthly", "wages_per_period": 2_000, "pay_dates": ["2026-05-01"],
         "withheld_prior_year": True}
    e.update(over)
    return withholding_projection([e]).employers[0]


def test_jp1c_pub15_examples_2_and_3():
    # Pub 15 (2026) Example 2: monthly, a 2026 W-4 single with Steps 2-4 blank; the wage bracket tables give $65 on
    # $2,000, $179 on $3,000 and $419 on $5,000 — the percentage method reproduces each within $1.
    for wages, printed in ((2_000, 65), (3_000, 179), (5_000, 419)):
        assert abs(_one(wages_per_period=wages).checks[0].withheld - printed) <= 1, wages
    # Example 3: "You withhold 22% of $1,000, or $220, from Sharon's bonus payment."
    e = _one(supplemental=[{"date": "2026-05-15", "amount": 1_000, "separately_stated": True}])
    s = e.supplemental[0]
    assert s.flat == 220 and s.method == "range"                 # (ii): the flat rate is the employer's OPTION
    assert abs(s.aggregate - (179 - 65)) <= 2                     # Example 2's aggregate: $179 - $65 = $114


def test_jp1c_i_a_bonus_before_any_withheld_regular_check_forces_the_aggregate():
    e = _one(pay_dates=["2026-06-30"], withheld_prior_year=False,
             supplemental=[{"date": "2026-06-15", "amount": 5_000, "separately_stated": True}])
    s = e.supplemental[0]
    assert s.method == "aggregate" and s.flat is None and "(a)(7)(i)(C) fails" in s.reason
    assert e.box2_low == e.box2_high


def test_jp1c_iii_concurrent_and_not_separately_stated_is_aggregate():
    e = _one(supplemental=[{"date": "2026-05-01", "amount": 1_000, "separately_stated": False}])
    s = e.supplemental[0]
    assert s.method == "aggregate" and "(a)(7)(i)(B) fails" in s.reason


def test_jp1c_iv_concurrent_with_the_first_regular_check_is_interpretive():
    e = _one(pay_dates=["2026-05-01", "2026-06-01"], withheld_prior_year=False,
             supplemental=[{"date": "2026-05-01", "amount": 1_000, "separately_stated": True}])
    s = e.supplemental[0]
    assert s.method == "interpretive" and s.flat == 220 and "interpretive choice" in s.reason
    assert e.box2_low < e.box2_high


def test_jp1c_an_unknown_fact_is_a_range():
    e = _one(pay_dates=["2026-05-01"], withheld_prior_year=None,
             supplemental=[{"date": "2026-04-20", "amount": 3_000, "separately_stated": True}])
    assert e.supplemental[0].method == "range" and "unknown" in e.supplemental[0].reason


def test_jp1c_the_mandatory_37_percent_over_1_million():
    e = _one(wages_per_period=50_000, supplemental=[{"date": "2026-05-15", "amount": 1_200_000,
                                                      "separately_stated": True}])
    s = e.supplemental[0]
    assert s.mandatory_over_1m == 74_000                        # 37% x $200,000
    assert s.flat == 220_000                                    # 22% x the first $1,000,000


def test_jp1c_the_nonresident_alien_addon_and_a_partial_first_period():
    base = {"label": "Demo Lab", "pay_frequency": "biweekly", "wages_per_period": 2_500, "first_pay_date": "2026-01-09"}
    plain = withholding_projection([base]).employers[0]
    nra = withholding_projection([{**base, "nonresident_alien": True}]).employers[0]
    assert len(plain.checks) == 26 and nra.checks[0].withheld > plain.checks[0].withheld
    assert any("619.20" in n for n in nra.notes)                 # Table 2, biweekly
    partial = withholding_projection([{**base, "first_period_wages": 900}]).employers[0]
    assert partial.checks[0].withheld < plain.checks[0].withheld == partial.checks[1].withheld
    ended = withholding_projection([{**base, "employment_end": "2026-06-30"}]).employers[0]
    assert len(ended.checks) == 13 and ended.checks[-1].date <= date(2026, 6, 30)


def test_jp1c_the_employee_requested_methods_and_their_gates():
    base = {"label": "Demo Seasonal", "pay_frequency": "biweekly", "wages_per_period": 3_000,
            "first_pay_date": "2026-06-05", "employment_end": "2026-09-30"}
    with pytest.raises(ValueError, match="no more than 245 days"):
        withholding_projection([{**base, "method": "part_year", "written_request": True, "calendar_year_basis": True,
                                 "anticipated_days_employed": 246, "employment_start": "2026-05-25"}])
    with pytest.raises(ValueError, match="written request under penalties of perjury"):
        withholding_projection([{**base, "method": "part_year", "anticipated_days_employed": 120}])
    part = withholding_projection([{**base, "method": "part_year", "written_request": True, "calendar_year_basis": True,
                                    "anticipated_days_employed": 128, "employment_start": "2026-05-25"}]).employers[0]
    normal = withholding_projection([base]).employers[0]
    assert part.regular_total < normal.regular_total              # the idle months spread the wages
    with pytest.raises(ValueError, match="WRITTEN request"):
        withholding_projection([{**base, "method": "cumulative"}])
    cumulative = withholding_projection([{**base, "first_pay_date": "2026-01-09", "method": "cumulative",
                                          "written_request": True, "same_period_since_january": True}]).employers[0]
    assert abs(cumulative.regular_total - withholding_projection([{**base, "first_pay_date": "2026-01-09"}])
               .employers[0].regular_total) <= len(cumulative.checks)   # level pay: the same tax, rounding aside


def test_jp1c_fica_is_per_employer_and_the_w2s_feed_the_estimate():
    r = withholding_projection([
        {"label": "Demo A", "pay_frequency": "monthly", "wages_per_period": 18_000, "first_pay_date": "2026-01-31"},
        {"label": "Demo B", "pay_frequency": "monthly", "wages_per_period": 2_000, "first_pay_date": "2026-01-31"}])
    a, b = r.employers
    assert a.box3 == 184_500 and a.box4 == round(184_500 * 0.062)   # A's own wage base
    assert a.box6 == round(216_000 * 0.0145 + 16_000 * 0.009)        # 0.9% over A's own $200,000
    assert b.box4 == round(24_000 * 0.062)
    snap = IncomeSnapshot(w2s=[W2Facts(**w) for w in r.w2s])
    assert snap.wages == 240_000 and snap.federal_withholding == r.federal_withholding_low
    assert "Pub 15-T (2026)" in r.work
