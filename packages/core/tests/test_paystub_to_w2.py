"""Phase J JP3b — calc op paystub_to_w2 (hypothetical demo figures only)."""
from __future__ import annotations

from datetime import date

import pytest

from taxfill_core.calc import annualize_ytd
from taxfill_core.estimate import IncomeSnapshot, W2Facts
from taxfill_core.paystub import paystub_to_w2

SEMI_STUB = {"pay_date": "2026-06-30", "gross_ytd": "48000", "pretax_401k_ytd": "4800", "section_125_ytd": "1200",
             "hsa_ytd": "600", "roth_401k_ytd": "600", "federal_withholding_ytd": "5040",
             "federal_withholding_current": "420"}
SEMI_JOB = {"employer": "Demo Widgets Inc", "pay_frequency": "semimonthly", "first_pay_date": "2026-01-15",
            "gross_per_period": "4000", "deductions_per_period": {"pretax_401k": "400", "section_125": "100",
                                                                  "hsa_cafeteria": "50", "roth_401k": "50"}}


def test_jp3b_a_midyear_stub_reproduces_the_known_w2():
    # 24 semimonthly checks of $4,000: 12 on the stub, 12 still to be paid (July 15 - December 31).
    r = paystub_to_w2(SEMI_STUB, SEMI_JOB, 2026)
    assert len(r.remaining_pay_dates) == 12 and r.remaining_pay_dates[-1] == date(2026, 12, 31)
    # box 1 = 96,000 - 9,600 (401(k)) - 3,600 (section 125 + HSA); boxes 3/5 exclude only the 3,600.
    assert r.w2 == {"employer": "Demo Widgets Inc", "box1": 82800, "box2": 10080, "box3": 92400, "box4": 5729,
                    "box5": 92400, "box6": 1340, "box10": 0,
                    "box12": [{"code": "D", "amount": 9600}, {"code": "AA", "amount": 1200},
                              {"code": "W", "amount": 1200}]}
    # The output feeds the estimator as a W-2 (JT4a).
    IncomeSnapshot(w2s=[W2Facts(**r.w2)])


def test_jp3b_an_ended_job_is_not_annualized():
    ended = {**SEMI_JOB, "end": "2026-06-30"}
    r = paystub_to_w2(SEMI_STUB, ended, 2026)
    assert r.remaining_pay_dates == [] and r.w2["box1"] == 48000 - 4800 - 1800
    assert "never annualized" in " ".join(r.assumptions)
    assert "NEVER annualize a job that has ENDED" in annualize_ytd(48000, "2026-06-30", 2026).work


def test_jp3b_a_january_1_check_lands_on_next_years_w2():
    # Biweekly from Friday January 2, 2026: the 27th check is Friday January 1, 2027.
    r = paystub_to_w2({"pay_date": "2026-06-26", "gross_ytd": "39000", "federal_withholding_ytd": "3900",
                       "federal_withholding_current": "300"},
                      {"employer": "Demo Biweekly", "pay_frequency": "biweekly", "first_pay_date": "2026-01-02",
                       "gross_per_period": "3000"}, 2026)
    assert r.next_year_pay_dates == [date(2027, 1, 1)] and date(2027, 1, 1) not in r.remaining_pay_dates
    assert r.w2["box1"] == 39000 + 3000 * len(r.remaining_pay_dates) == 78000   # 26 checks paid in 2026


def test_jp3b_box_3_stops_at_the_wage_base_and_box_6_adds_the_0_9_percent():
    r = paystub_to_w2({"pay_date": "2026-06-30", "gross_ytd": "240000", "federal_withholding_ytd": "60000",
                       "federal_withholding_current": "5000"},
                      {"employer": "Demo High Pay", "pay_frequency": "semimonthly", "first_pay_date": "2026-01-15",
                       "gross_per_period": "20000"}, 2026)
    assert r.w2["box3"] == 184500 and r.w2["box5"] == 480000
    assert r.w2["box6"] == round(480000 * 0.0145 + (480000 - 200000) * 0.009)


def test_jp3b_a_stub_from_another_year_refuses():
    with pytest.raises(ValueError, match="Calendar year basis"):
        paystub_to_w2({**SEMI_STUB, "pay_date": "2027-01-01"}, SEMI_JOB, 2026)
