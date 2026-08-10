"""Golden tests for the H8 quartet: contribution_limits, ira_contribution_eligibility,
marginal_dollar_savings, magi_ladder.

Every figure was transcribed with verbatim quotes from Notice 2024-80 /
Notice 2025-67 (as published in IRB 2025-49 — the irs-drop copy of that notice
is DEFECTIVE and repeats 2025 figures), Rev. Procs. 2024-25/2025-19 (HSA),
2024-40/2025-32 (FSA/commuter), and Pub 590-A (the worksheet mechanics) before
the packs were authored. The vectors pin the four findings of the one real
planning session:

  * N-10 — the SCOPING is the answer ("is the 401(k) limit one per person?"),
    and two self-only HSAs beat one family plan;
  * N-11 — the live ineligible-Roth-contribution error (single, MAGI $194,600)
    and its flip-to-compliant on a year-end MFJ status;
  * N-13 — the MAGI ladder ("why is my MAGI under $200,000 when I make
    $220,000?" — because Additional Medicare is a WAGE test and NIIT is not);
  * the marginal-dollar fact that above the wage base a payroll dollar saves
    2.35% of FICA, never 7.65%.

All data synthetic. Offline.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from taxfill_core.calc import (
    contribution_limits,
    ira_contribution_eligibility,
    magi_ladder,
    marginal_dollar_savings,
)


# ── contribution_limits: the scoping IS the answer ─────────────────────────────


def test_the_scoping_answers_the_motivating_question():
    r = contribution_limits(2026)
    assert "per PERSON across ALL employers" in r.scoping["elective_deferral_402g"]
    assert "share this one limit" in r.scoping["elective_deferral_402g"]
    assert "per EMPLOYER PLAN" in r.scoping["annual_additions_415c"]
    assert "mega-backdoor" in r.scoping["annual_additions_415c"]
    assert "COVERAGE TIER" in r.scoping["hsa"]


def test_two_self_only_hsas_beat_one_family_plan_both_years():
    # The counter-intuitive coverage-tier consequence, true in both shipped years.
    for year, self_only, family in ((2025, 4_300, 8_550), (2026, 4_400, 8_750)):
        r = contribution_limits(year)
        assert r.limits.hsa.self_only == self_only and r.limits.hsa.family == family
        assert 2 * self_only > family
        assert "MORE than" in r.scoping["hsa"]


def test_2026_figures_come_from_the_irb_not_the_defective_drop_copy():
    # The irs-drop n-25-67.pdf repeats the 2025 IRA figures; the pack cites the
    # IRB publication and carries the 2026 amounts.
    r = contribution_limits(2026)
    assert r.limits.elective_deferral_402g.limit == 24_500
    assert r.limits.ira.limit == 7_500 and r.limits.ira.catch_up_50 == 1_100
    assert r.limits.ira.roth_magi_phaseout.single_hoh.start == 153_000
    assert "irb" in r.limits.citation.url


def test_limits_fail_closed_for_years_without_the_block():
    with pytest.raises(ValueError, match="contribution_limits block"):
        contribution_limits(2023)


# ── ira_contribution_eligibility: the live error and the flip ──────────────────


def test_the_live_error_single_194600_roth():
    # The real session caught exactly this: a single filer contributing $7,500
    # to a Roth IRA with MAGI above the $153,000-$168,000 phase-out.
    r = ira_contribution_eligibility(194_600, "single", 2026, ira_type="roth", contributed=7_500)
    assert r.magi_position == "above" and r.allowed == 0
    assert r.excess == 7_500
    assert r.excise_per_year == 450  # 6% x 7,500, EVERY year until fixed
    assert "EVERY year" in r.work and "INCLUDING extensions" in r.work


def test_the_same_magi_flips_compliant_on_a_year_end_mfj_return():
    r = ira_contribution_eligibility(194_600, "married_filing_jointly", 2026, ira_type="roth", contributed=7_500)
    assert r.allowed == 7_500 and r.excess == 0
    assert r.phaseout == {"start": 242_000, "end": 252_000}


def test_the_pub_590a_worksheet_mechanics():
    # 7,500 x (168,000-160,000)/15,000 = 4,000 exactly.
    assert ira_contribution_eligibility(160_000, "single", 2026, ira_type="roth").allowed == 4_000
    # 7,500 x 7,999/15,000 = 3,999.5 -> rounds UP to the nearest $10.
    assert ira_contribution_eligibility(160_001, "single", 2026, ira_type="roth").allowed == 4_000
    # $50 raw -> the $200 minimum while partially phased.
    assert ira_contribution_eligibility(167_900, "single", 2026, ira_type="roth").allowed == 200


def test_mfs_is_phased_out_almost_immediately_unless_lived_apart():
    r = ira_contribution_eligibility(50_000, "married_filing_separately", 2026, ira_type="roth")
    assert r.allowed == 0 and r.phaseout == {"start": 0, "end": 10_000}
    lived_apart = ira_contribution_eligibility(
        50_000, "married_filing_separately", 2026, ira_type="roth", mfs_lived_apart_all_year=True
    )
    assert lived_apart.allowed == 7_500  # the single range applies


def test_deduction_path_requires_the_coverage_facts():
    with pytest.raises(ValueError, match="covered_by_employer_plan"):
        ira_contribution_eligibility(100_000, "single", 2026, ira_type="traditional_deduction")
    # No plan anywhere: fully deductible regardless of MAGI.
    r = ira_contribution_eligibility(
        500_000, "married_filing_jointly", 2026, ira_type="traditional_deduction",
        covered_by_employer_plan=False, spouse_covered_by_employer_plan=False,
    )
    assert r.allowed == 7_500
    # Contributor not covered, spouse covered: the HIGHER spousal range.
    r = ira_contribution_eligibility(
        245_000, "married_filing_jointly", 2026, ira_type="traditional_deduction",
        covered_by_employer_plan=False, spouse_covered_by_employer_plan=True,
    )
    assert r.phaseout == {"start": 242_000, "end": 252_000} and r.magi_position == "within"


def test_age_50_catch_up_raises_the_limit():
    r = ira_contribution_eligibility(100_000, "single", 2026, ira_type="roth", age_50_plus=True)
    assert r.full_limit == 7_500 + 1_100


# ── marginal_dollar_savings: payroll dollars vs 401(k) dollars ─────────────────


def test_above_the_wage_base_a_payroll_dollar_saves_235_percent_never_765():
    r = marginal_dollar_savings(150_000, 220_000, "single", 2026)
    assert r.marginal_rate == Decimal("0.24")
    payroll = next(x for x in r.rows if x.bucket == "hsa_payroll")
    assert payroll.fica_saving == Decimal("0.0145") + Decimal("0.009")  # 2.35%, wages > $200k
    k401 = next(x for x in r.rows if x.bucket == "401k_pretax")
    assert k401.fica_saving == 0  # a 401(k) dollar still pays FICA
    # Payroll buckets outrank the 401(k) on the next dollar.
    assert r.rows[0].bucket in ("hsa_payroll", "health_fsa", "commuter_132f")


def test_below_the_wage_base_the_full_765_percent_applies():
    r = marginal_dollar_savings(60_000, 80_000, "single", 2026)
    payroll = next(x for x in r.rows if x.bucket == "hsa_payroll")
    assert payroll.fica_saving == Decimal("0.062") + Decimal("0.0145")
    assert "BELOW" in r.fica_tier


def test_between_the_base_and_200k_only_medicare_is_saved():
    # 2026 base $184,500 < wages $190,000 < $200,000.
    r = marginal_dollar_savings(120_000, 190_000, "single", 2026)
    payroll = next(x for x in r.rows if x.bucket == "hsa_payroll")
    assert payroll.fica_saving == Decimal("0.0145")
    assert "never 7.65%" in r.fica_tier


# ── magi_ladder: six tests, six thresholds, one table ──────────────────────────


def test_the_220k_wages_but_magi_under_200k_ladder():
    # The real user's own question. AGI $195,000 with $220,000 wages: NIIT (an
    # AGI-side test) still has headroom; Additional Medicare (a WAGE test) is
    # already over; Roth eligibility is long gone.
    r = magi_ladder(195_000, "single", 2026, wages=220_000)
    by_test = {row.test: row for row in r.rows}
    niit = by_test["Net investment income tax (Form 8960, 3.8%)"]
    assert niit.position == "below" and niit.headroom == 5_000
    addl = by_test["Additional Medicare Tax (Form 8959, 0.9%)"]
    assert addl.position == "above" and addl.magi_used == 220_000
    assert "WAGE test" in addl.definition
    roth = by_test["Roth IRA contribution phase-out"]
    assert roth.position == "above"
    assert "gross pay -> W-2 box 1" in r.work  # the ladder story itself


def test_ladder_rows_come_only_from_shipped_blocks():
    # 2025 ships the Schedule 1-A block -> its rows appear; add-backs shift the MAGI.
    r = magi_ladder(140_000, "single", 2025, foreign_earned_income_exclusion=20_000)
    tests = {row.test for row in r.rows}
    assert any("Schedule 1-A" in t for t in tests)
    niit = next(row for row in r.rows if "8960" in row.test)
    assert niit.magi_used == 160_000  # AGI + FEIE — each test's MAGI is its own


def test_ladder_mfs_shows_the_sli_hard_bar():
    r = magi_ladder(60_000, "married_filing_separately", 2025)
    sli = next(row for row in r.rows if "221" in row.test)
    assert sli.position == "above" and "no MAGI can fix it" in sli.definition
