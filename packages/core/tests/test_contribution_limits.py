"""Golden tests for the H8 quartet: contribution_limits, ira_contribution_eligibility,
marginal_dollar_savings, magi_ladder.

Every figure was transcribed with verbatim quotes from Notice 2024-80 /
Notice 2025-67 (as published in IRB 2025-49 — the irs-drop copy of that notice
is DEFECTIVE and repeats 2025 figures), Rev. Procs. 2024-25/2025-19 (HSA),
2024-40/2025-32 (FSA/commuter), and Pub 590-A (the worksheet mechanics) before
the packs were authored. The vectors pin four planning traps:

  * N-10 — the SCOPING is the answer ("is the 401(k) limit one per person?"),
    and two self-only HSAs beat one family plan;
  * N-11 — an over-the-phase-out Roth contribution (demo numbers: a married
    filer filing separately, whose range is $0-$10,000, contributing directly)
    and the joint-return range at the same MAGI;
  * N-13 — the MAGI ladder (wages over the Form 8959 threshold yet MAGI under
    the NIIT one, because Additional Medicare is a WAGE test and NIIT is not);
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


def test_the_scoping_answers_is_the_401k_limit_per_person():
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


# ── ira_contribution_eligibility: the excess and the flip ──────────────────────


def test_an_mfs_roth_is_excess():
    # A married filer filing separately who lived with the spouse (demo
    # numbers): MAGI $150,000, far above the $0-$10,000 MFS range, so a DIRECT
    # $6,000 Roth IRA contribution is excess in full.
    r = ira_contribution_eligibility(
        150_000, "married_filing_separately", 2026, ira_type="roth", contributed=6_000
    )
    assert r.magi_position == "above" and r.allowed == 0
    assert r.excess == 6_000
    assert r.excise_per_year == 360  # 6% x 6,000, EVERY year until fixed
    assert "EVERY year" in r.work and "INCLUDING extensions" in r.work


def test_the_same_magi_is_inside_the_joint_range():
    r = ira_contribution_eligibility(150_000, "married_filing_jointly", 2026, ira_type="roth", contributed=6_000)
    assert r.allowed == 7_500 and r.excess == 0  # the statutory full limit
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


# ── JF1b.4: the IRC 4973(a) cap and the correction deadline ────────────────────


def test_jf1b4_a_dec31_value_below_the_excess_caps_the_excise():
    # IRC 4973(a): "shall not exceed 6 percent of the value of the account or annuity
    # (determined as of the close of the taxable year)". Demo numbers: $7,000 excess, the
    # Roth IRAs worth $5,000 on Dec 31 -> 6% x 5,000.
    r = ira_contribution_eligibility(
        150_000, "married_filing_separately", 2025, ira_type="roth", contributed=7_000,
        roth_ira_dec31_value=5_000,
    )
    assert r.excess == 7_000
    assert r.excise_per_year == 300  # 6% x min(7,000, 5,000)
    assert r.inputs["roth_ira_dec31_value"] == 5_000
    assert "SMALLER of the excess ($7,000) and the Roth IRAs' Dec 31 value ($5,000)" in r.work
    assert "shall not exceed 6 percent of the value of the account" in r.work


def test_jf1b4_a_dec31_value_above_the_excess_leaves_the_excise_on_the_excess():
    r = ira_contribution_eligibility(
        150_000, "married_filing_separately", 2025, ira_type="roth", contributed=7_000,
        roth_ira_dec31_value=9_000,
    )
    assert r.excise_per_year == 420  # 6% x 7,000
    zero = ira_contribution_eligibility(
        150_000, "married_filing_separately", 2025, ira_type="roth", contributed=7_000,
        roth_ira_dec31_value=0,
    )
    assert zero.excise_per_year == 0


def test_jf1b4_without_the_value_the_work_names_the_cap_and_the_input():
    r = ira_contribution_eligibility(150_000, "married_filing_separately", 2025, ira_type="roth", contributed=7_000)
    assert r.excise_per_year == 420
    assert "roth_ira_dec31_value" in r.work and "4973(a)" in r.work
    assert "roth_ira_dec31_value" not in r.inputs


def test_jf1b4_the_value_is_refused_off_the_roth_path_and_when_negative():
    with pytest.raises(ValueError, match="omit it for ira_type='traditional_deduction'"):
        ira_contribution_eligibility(
            100_000, "single", 2025, ira_type="traditional_deduction", covered_by_employer_plan=True,
            contributed=7_000, roth_ira_dec31_value=5_000,
        )
    with pytest.raises(ValueError, match="roth_ira_dec31_value must be >= 0"):
        ira_contribution_eligibility(100_000, "single", 2025, contributed=7_000, roth_ira_dec31_value=-1)


def test_jf1b4_the_remedy_names_the_correction_deadlines():
    r = ira_contribution_eligibility(150_000, "married_filing_separately", 2025, ira_type="roth", contributed=7_000)
    # The year's due date from the pack, the extended date, and the 301.9100-2 window.
    assert "April 15, 2026 (the 2025 pack's due date), or October 15, 2026 if you extend" in r.work
    assert "automatic 6-month extension" in r.work and "Form 4868" in r.work
    assert "(including extensions of time)" in r.work  # IRC 408(d)(4)(A)
    assert "net income attributable to such contribution" in r.work  # IRC 408(d)(4)(C)
    assert "shall be treated as an amount not contributed" in r.work  # IRC 4973(f)
    assert "no later than 6 months after the due date of your tax return, excluding extensions" in r.work
    assert "Filed pursuant to section 301.9100-2" in r.work
    assert "provided the taxpayer timely filed its return" in r.work  # Treas. Reg. 301.9100-2(b)
    # A pack with no deadlines block says so instead of asserting a date.
    r26 = ira_contribution_eligibility(150_000, "married_filing_separately", 2026, ira_type="roth", contributed=7_500)
    assert "April 15, 2027 (the 2026 pack records no due date — confirm it)" in r26.work


def test_jf1b4_the_traditional_path_quotes_its_own_subsection_and_no_roth_input():
    r = ira_contribution_eligibility(
        200_000, "single", 2025, ira_type="traditional_deduction", covered_by_employer_plan=True, contributed=7_000,
    )
    assert "roth_ira_dec31_value" not in r.work and "4973(f)" not in r.work
    assert "IRC 4973(b)" in r.work and "individual retirement account or the individual retirement annuity" in r.work
    assert "April 15, 2026 (the 2025 pack's due date), or October 15, 2026 if you extend" in r.work


def test_jf1b4_an_october_15_on_a_weekend_names_irc_7503():
    from types import SimpleNamespace

    from taxfill_core.calc import _excess_correction_deadline

    # October 15, 2028 is a Sunday (a TY2027 deadline).
    stub = SimpleNamespace(deadlines=SimpleNamespace(filing_due_date="2028-04-17"))
    text = _excess_correction_deadline(stub, 2027)
    assert text.startswith("April 17, 2028 (the 2027 pack's due date), or October 15, 2028 — a Sunday: IRC 7503")
    assert "next succeeding day which is not a Saturday, Sunday, or a legal holiday" in text
    weekday = _excess_correction_deadline(stub, 2026)  # October 15, 2027 is a Friday
    assert "IRC 7503" not in weekday


def test_age_50_catch_up_raises_the_limit():
    r = ira_contribution_eligibility(100_000, "single", 2026, ira_type="roth", age_50_plus=True)
    assert r.full_limit == 7_500 + 1_100


# ── marginal_dollar_savings: payroll dollars vs 401(k) dollars ─────────────────


def test_above_the_wage_base_a_payroll_dollar_saves_235_percent_never_765():
    r = marginal_dollar_savings(150_000, 238_000, "single", 2026)
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


def test_wages_over_the_8959_threshold_but_magi_under_the_niit_one():
    # Demo numbers: a joint return with AGI $226,000 and $262,000 of combined
    # wages. NIIT (an AGI-side test) still has headroom under $250,000;
    # Additional Medicare (a WAGE test) is already over it; the joint Roth
    # phase-out ($242,000-$252,000) has not started.
    r = magi_ladder(226_000, "married_filing_jointly", 2026, wages=262_000)
    by_test = {row.test: row for row in r.rows}
    niit = by_test["Net investment income tax (Form 8960, 3.8%)"]
    assert niit.position == "below" and niit.headroom == 24_000
    addl = by_test["Additional Medicare Tax (Form 8959, 0.9%)"]
    assert addl.position == "above" and addl.magi_used == 262_000
    assert "WAGE test" in addl.definition
    roth = by_test["Roth IRA contribution phase-out"]
    assert roth.position == "below"
    assert "gross pay -> W-2 box 1" in r.work  # the ladder story itself


def test_jf1b1_qss_takes_form_8959s_200000_and_niits_joint_250000():
    """JF1b.1 acceptance: Form 8959: "Single, Head of household, or Qualifying surviving
    spouse . . . $200,000"; IRC 1411(b)(1): "a surviving spouse (as defined in section
    2(a)), $250,000". The QSS row never borrows the MFJ-aliased column."""
    r = magi_ladder(240_000, "qualifying_surviving_spouse", 2025, wages=240_000)
    by_test = {row.test: row for row in r.rows}
    addl = by_test["Additional Medicare Tax (Form 8959, 0.9%)"]
    assert addl.threshold == "$200,000" and addl.position == "above" and addl.headroom == 0
    assert "Qualifying surviving spouse . . . $200,000" in addl.definition
    niit = by_test["Net investment income tax (Form 8960, 3.8%)"]
    assert niit.threshold == "$250,000" and niit.position == "below" and niit.headroom == 10_000
    assert "surviving spouse (as defined in section 2(a)), $250,000" in niit.definition


@pytest.mark.parametrize("status", [
    "single", "married_filing_jointly", "married_filing_separately", "head_of_household",
    "qualifying_surviving_spouse",
])
@pytest.mark.parametrize("year", [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])
def test_jf1b1_every_surtax_row_reads_the_raw_status_from_the_pack(year: int, status: str):
    from taxfill_core.knowledge import load_knowledge

    tax = load_knowledge("federal", year).tax
    by_test = {row.test: row for row in magi_ladder(100_000, status, year, wages=100_000).rows}
    if tax.additional_medicare_tax is not None:
        expected = tax.additional_medicare_tax.thresholds[status]
        assert by_test["Additional Medicare Tax (Form 8959, 0.9%)"].threshold == f"${expected:,}"
    if tax.niit is not None:
        expected = tax.niit.thresholds[status]
        assert by_test["Net investment income tax (Form 8960, 3.8%)"].threshold == f"${expected:,}"


def test_jf1b1_the_non_qss_rows_carry_no_qss_sentence():
    r = magi_ladder(240_000, "married_filing_jointly", 2025, wages=240_000)
    assert not any("surviving spouse" in row.definition for row in r.rows if "89" in row.test)


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


def test_commuter_scoping_carries_the_eligibility_rules_not_just_the_caps():
    """P-006: the monthly caps alone do not say what qualifies. The scoping
    string is where an agent meets the limit, so the year-invariant eligibility
    rules ride along with it."""
    scoping = contribution_limits(year=2026).scoping["commuter_132f"]
    assert "EXHAUSTIVE list of three" in scoping
    assert "EV charging" in scoping and "fuel" in scoping          # the never-eligible trap
    assert "HOME is\nexpressly excluded" in scoping.replace(" ", " ") or "HOME" in scoping
    assert "INCUR AND SUBSTANTIATE" in scoping and "BEFORE" in scoping
    assert "WAGES" in scoping                                       # the failure consequence
    assert "get_sources('commuter benefits')" in scoping            # the authority pointer


def test_hsa_scoping_no_longer_overstates_the_fica_saving_or_the_ceiling():
    """Phase I2 correction. The hsa blurb said flatly "Payroll HSA dollars also
    avoid FICA", which is only true BELOW the social security wage base — and the
    filers who max an HSA are the ones above it, where the saving is 1.45% (or
    2.35% past the 0.9% Additional Medicare withholding threshold), never 7.65%.
    The same string is also where an agent meets the annual figure, so it now
    carries the two things that make that figure wrong on its own: the monthly
    proration and the FSA disqualification."""
    for year in (2025, 2026):
        scoping = contribution_limits(year).scoping["hsa"]
        assert "only the FULL 7.65% BELOW the social security wage base" in scoping
        assert "1.45%" in scoping and "2.35%" in scoping
        assert "CEILING, not the amount" in scoping                 # the monthly-proration warning
        assert "FIRST DAY of each month" in scoping and "1/12" in scoping
        assert "Rev. Rul. 2004-45" in scoping and "SPOUSE" in scoping
        assert "hsa_deduction" in scoping                            # the op that computes it
        assert "box 12 code W" in scoping                            # the double-count trap
    # The neighbouring payroll buckets carried the same overstatement.
    for bucket in ("health_fsa_125i", "commuter_132f"):
        scoping = contribution_limits(2026).scoping[bucket]
        assert "full 7.65% only BELOW the social security wage base" in scoping
