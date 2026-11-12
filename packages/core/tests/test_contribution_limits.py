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
    # 2026 now records its due date (JT2b, the draft Form 4868).
    r26 = ira_contribution_eligibility(150_000, "married_filing_separately", 2026, ira_type="roth", contributed=7_500)
    assert "April 15, 2027 (the 2026 pack's due date), or October 15, 2027 if you extend" in r26.work


def test_jf1b4_a_pack_with_no_deadlines_block_says_so(planning_year, synthetic_provisional_pack):
    # JT0b: the block stripped from a scratch copy, whatever the planning pack ships.
    r = ira_contribution_eligibility(150_000, "married_filing_separately", planning_year, ira_type="roth",
                                     contributed=7_500, knowledge_dir=synthetic_provisional_pack(["deadlines"]))
    assert f"(the {planning_year} pack records no due date — confirm it)" in r.work


def test_jf1b4_the_traditional_path_quotes_its_own_subsection_and_no_roth_input():
    # $9,000 into a traditional IRA is $2,000 over the 2025 limit: THAT is the excess (JW1 — before, the fixture was
    # $7,000, a contribution within the limit, which is never an excess).
    r = ira_contribution_eligibility(
        200_000, "single", 2025, ira_type="traditional_deduction", covered_by_employer_plan=True, contributed=9_000,
    )
    assert (r.excess, r.excise_per_year) == (2_000, 120) and "$2,000 over the $7,000 contribution limit" in r.work
    assert "recharacterize it by the same deadline" not in r.work   # P-037: it cannot cure an over-the-limit excess
    assert "roth_ira_dec31_value" not in r.work and "4973(f)" not in r.work
    assert "IRC 4973(b)" in r.work and "individual retirement account or the individual retirement annuity" in r.work
    assert "April 15, 2026 (the 2025 pack's due date), or October 15, 2026 if you extend" in r.work


# ── JW1 / P-037 (2026-11-12, walkthrough P1): the deduction phase-out never creates an excess ──────


def test_jw1_a_nondeductible_traditional_contribution_within_the_limit_is_not_an_excess():
    """The backdoor-Roth fact pattern: an active participant above the IRC 219(g) range puts the full limit into a
    traditional IRA. The deduction is $0 and the whole amount is nondeductible basis (Form 8606 line 1); IRC 4973(b)
    computes the 219 deduction "without regard to section 219(g)", so there is no excess and no excise. Before
    2026-11-12 the op reported excess 7,000 and $420 a year, and told the filer to withdraw or recharacterize."""
    r = ira_contribution_eligibility(
        187_385, "single", 2025, ira_type="traditional_deduction", covered_by_employer_plan=True, contributed=7_000,
    )
    assert (r.allowed, r.deductible, r.nondeductible) == (0, 0, 7_000)
    assert (r.excess, r.excise_per_year) == (0, 0)
    assert not any(line.startswith("EXCESS:") for line in r.work.splitlines()) and "NOT AN EXCESS:" in r.work
    assert "Form 8606 line 1" in r.work
    assert "shall be computed without regard to section 219(g)" in r.work          # IRC 4973(b)
    assert "designated nondeductible contributions may be made" in r.work          # IRC 408(o)(1)
    assert "withdrawing the contribution" not in r.work and "recharacterize it by the same deadline" not in r.work


def test_jw1_the_phase_out_splits_a_contribution_and_only_the_part_over_the_limit_is_excess():
    kw = dict(filing_status="single", year=2025, ira_type="traditional_deduction", covered_by_employer_plan=True)
    # MAGI $84,000 is the middle of the 2025 single range ($79,000-$89,000): half of $7,000 is deductible.
    within = ira_contribution_eligibility(84_000, contributed=7_000, **kw)
    assert (within.allowed, within.deductible, within.nondeductible, within.excess) == (3_500, 3_500, 3_500, 0)
    # $8,000 contributed: the same split of the first $7,000, and $1,000 over the limit is the excess (6% = $60).
    over = ira_contribution_eligibility(84_000, contributed=8_000, **kw)
    assert (over.deductible, over.nondeductible, over.excess, over.excise_per_year) == (3_500, 3_500, 1_000, 60)
    assert "EXCESS: contributed $8,000 -> $1,000 over the $7,000 contribution limit" in over.work
    # Below the range everything is deductible; nothing is nondeductible and nothing is excess.
    below = ira_contribution_eligibility(60_000, contributed=7_000, **kw)
    assert (below.deductible, below.nondeductible, below.excess) == (7_000, 0, 0) and "NOT AN EXCESS" not in below.work
    # The compensation cap of IRC 219(b)(1) is outside the op's inputs, and the work says so.
    assert "compensation includible in the individual's gross income" in below.work


def test_jw1_the_split_follows_what_was_contributed():
    """P-037: `deductible` and `nondeductible` are parts of the amount actually contributed, not of the limit."""
    kw = dict(filing_status="single", year=2025, ira_type="traditional_deduction", covered_by_employer_plan=True)
    above = ira_contribution_eligibility(200_000, contributed=3_000, **kw)          # allowed 0
    assert (above.deductible, above.nondeductible, above.excess) == (0, 3_000, 0)
    within = ira_contribution_eligibility(84_000, contributed=3_000, **kw)          # allowed 3,500
    assert (within.allowed, within.deductible, within.nondeductible, within.excess) == (3_500, 3_000, 0, 0)
    no_plan = ira_contribution_eligibility(200_000, "single", 2025, ira_type="traditional_deduction",
                                           covered_by_employer_plan=False, contributed=3_000)
    assert (no_plan.deductible, no_plan.nondeductible, no_plan.excess) == (3_000, 0, 0)
    for r in (above, within):
        assert r.deductible + r.nondeductible + r.excess == 3_000
        # The year-end sentence speaks of deductibility on this path, never of an excess that "flips".
        assert "excess under today's status" not in r.work and "Deductibility is tested at YEAR END" in r.work


def test_jw1_an_excess_beside_a_nondeductible_part_is_worded_apart():
    """P-037 (the fix's review): with $8,000 contributed the first $7,000 is split and only the $1,000 over the limit
    is the excess; the line about the split must not say that nothing needs to be withdrawn."""
    r = ira_contribution_eligibility(84_000, "single", 2025, ira_type="traditional_deduction",
                                     covered_by_employer_plan=True, contributed=8_000)
    split = next(line for line in r.work.splitlines() if line.startswith("WITHIN THE LIMIT:"))
    assert "of the first $7,000 contributed (the limit), $3,500 is deductible and $3,500 is a NONDEDUCTIBLE" in split
    assert "the $1,000 over the limit is the excess" in split and "NOT AN EXCESS" not in r.work
    assert "does not need to be withdrawn or recharacterized" not in r.work
    # A traditional excess is over the one limit shared with Roth IRAs: moving it to a Roth IRA cures nothing.
    excess = next(line for line in r.work.splitlines() if line.startswith("EXCESS:"))
    assert "Recharacterizing does not cure it" in excess and "Or recharacterize it by the same deadline" not in excess
    roth = ira_contribution_eligibility(200_000, "single", 2025, ira_type="roth", contributed=7_000)
    assert "Or recharacterize it by the same deadline: calc op ira_recharacterization" in roth.work


def test_jw1_the_compensation_caveat_carries_the_joint_return_rule():
    r = ira_contribution_eligibility(100_000, "married_filing_jointly", 2025, ira_type="traditional_deduction",
                                     covered_by_employer_plan=True, contributed=7_000)
    assert "on a joint return the spouse with less compensation counts the couple's combined compensation" in r.work
    assert "IRC 219(c)" in r.work


def test_jw1_a_separate_filer_whose_spouse_is_covered_is_phased_out_from_zero():
    """IRC 219(g)(1) applies when "an individual or the individual's spouse is an active participant", and a married
    individual filing separately has an applicable dollar amount of zero ((g)(3)(B)(iii)); Pub. 590-A (2025) Table
    1-3: "married filing separately with a spouse who is covered by a plan at work: less than $10,000 a partial
    deduction; $10,000 or more no deduction". Before 2026-11-12 the op returned the full deduction and said neither
    spouse was covered."""
    kw = dict(filing_status="married_filing_separately", year=2025, ira_type="traditional_deduction",
              covered_by_employer_plan=False, contributed=7_000)
    with pytest.raises(ValueError, match="must pass spouse_covered_by_employer_plan"):
        ira_contribution_eligibility(50_000, **kw)
    covered_spouse = ira_contribution_eligibility(50_000, spouse_covered_by_employer_plan=True, **kw)
    assert covered_spouse.phaseout == {"start": 0, "end": 10_000}
    assert (covered_spouse.deductible, covered_spouse.nondeductible, covered_spouse.excess) == (0, 7_000, 0)
    assert "neither spouse" not in covered_spouse.work
    partial = ira_contribution_eligibility(5_000, spouse_covered_by_employer_plan=True, **kw)
    assert (partial.deductible, partial.nondeductible) == (3_500, 3_500)
    neither = ira_contribution_eligibility(50_000, spouse_covered_by_employer_plan=False, **kw)
    assert (neither.deductible, neither.nondeductible) == (7_000, 0) and "neither spouse" in neither.work


def test_jw1_separate_filers_who_lived_apart_all_year_take_the_single_rules():
    """IRC 219(g)(4): they "shall not be treated as married individuals for purposes of this subsection". Pub. 590-A
    (2025) Table 1-2 footnote 2 (the single range) and Table 1-3 footnote 2 (the full deduction whatever the spouse's
    plan). Before 2026-11-12 the deduction path ignored mfs_lived_apart_all_year."""
    kw = dict(filing_status="married_filing_separately", year=2025, ira_type="traditional_deduction",
              mfs_lived_apart_all_year=True, contributed=7_000)
    covered = ira_contribution_eligibility(50_000, covered_by_employer_plan=True, **kw)
    assert covered.phaseout == {"start": 79_000, "end": 89_000} and covered.deductible == 7_000
    assert "shall not be treated as married individuals for purposes of this subsection" in covered.work
    together = ira_contribution_eligibility(50_000, "married_filing_separately", 2025, ira_type="traditional_deduction",
                                            covered_by_employer_plan=True, contributed=7_000)
    assert together.phaseout == {"start": 0, "end": 10_000} and together.deductible == 0
    # Not covered, living apart: the spouse's plan does not count, and the op does not ask for it.
    apart = ira_contribution_eligibility(500_000, covered_by_employer_plan=False, **kw)
    assert (apart.deductible, apart.nondeductible) == (7_000, 0)
    assert "your spouse's plan does not count (IRC 219(g)(4))" in apart.work and "neither spouse" not in apart.work


def test_jw1_a_qualifying_surviving_spouse_is_not_asked_about_a_spouse():
    # Pub. 590-A (2025) Table 1-3: "single, head of household, or qualifying surviving spouse: any amount: a full
    # deduction"; Table 1-2 puts a covered one on the joint range.
    r = ira_contribution_eligibility(500_000, "qualifying_surviving_spouse", 2025, ira_type="traditional_deduction",
                                     covered_by_employer_plan=False, contributed=7_000)
    assert (r.deductible, r.nondeductible) == (7_000, 0) and "you are not an active participant" in r.work
    covered = ira_contribution_eligibility(130_000, "qualifying_surviving_spouse", 2025,
                                           ira_type="traditional_deduction", covered_by_employer_plan=True)
    assert covered.phaseout == {"start": 126_000, "end": 146_000} and covered.allowed == 5_600


def test_jw1_the_no_plan_path_and_the_roth_path_keep_their_meaning():
    none_covered = ira_contribution_eligibility(
        500_000, "married_filing_jointly", 2025, ira_type="traditional_deduction", contributed=9_000,
        covered_by_employer_plan=False, spouse_covered_by_employer_plan=False,
    )
    assert (none_covered.deductible, none_covered.nondeductible, none_covered.excess) == (7_000, 0, 2_000)
    # A Roth contribution over the MAGI-reduced amount IS an excess (IRC 4973(f)); the split does not apply to it.
    roth = ira_contribution_eligibility(200_000, "single", 2025, ira_type="roth", contributed=7_000)
    assert (roth.allowed, roth.excess, roth.excise_per_year) == (0, 7_000, 420)
    assert roth.deductible is None and roth.nondeductible is None and "EXCESS:" in roth.work


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


# ── JP2: the 402(g) room across every employer ──────────────────────────────


def test_jp2_the_room_left_after_a_job_change_counts_the_old_plan():
    from taxfill_core.calc import elective_deferral_room  # noqa: PLC0415
    old = [{"employer": "old job", "elective_deferrals": 11_000}, {"employer": "new job", "elective_deferrals": 0}]
    assert elective_deferral_room(old, year=2026, age=40).room == Decimal("13500.00")
    assert elective_deferral_room(old, year=2026, age=55).room == Decimal("21500.00")
    sixty = elective_deferral_room(old, year=2026, age=61)
    assert sixty.catch_up == 11_250 and sixty.room == Decimal("24750.00")   # 11,250, not 8,000
    assert elective_deferral_room(old, year=2026, age=64).catch_up == 8_000


def test_jp2_the_per_check_amount_and_percent_never_overshoot():
    from taxfill_core.calc import elective_deferral_room  # noqa: PLC0415
    r = elective_deferral_room([{"employer": "A", "elective_deferrals": 11_000}, {"employer": "B", "elective_deferrals": 0}],
                               year=2026, age=40, remaining_pay_dates=7, per_check_compensation=6_250,
                               plan_increment_percent=1)
    assert r.per_check_amount == Decimal("1928")                    # 13,500 / 7 = 1,928.57, rounded down
    assert r.per_check_percent == Decimal("30")                     # 1,928.57 / 6,250 = 30.86%, down to 30%
    assert r.per_check_percent / 100 * 6_250 * 7 <= r.room
    assert r.per_check_amount * 7 <= r.room


def test_jp2_an_excess_names_the_april_15_deadline_and_the_double_tax():
    from taxfill_core.calc import elective_deferral_room  # noqa: PLC0415
    r = elective_deferral_room([{"employer": "A", "elective_deferrals": 15_000}, {"employer": "B", "elective_deferrals": 12_000}],
                               year=2026, age=40)
    assert r.excess == Decimal("2500.00") and r.room == Decimal("0.00")
    assert r.excess_correction_deadline == "April 15, 2027"
    assert "not postponed by extending the filing" in r.work and "taxed twice" in r.work


def test_jp2_the_roth_catch_up_wage_test_and_the_415c_room_per_plan():
    from taxfill_core.calc import elective_deferral_room  # noqa: PLC0415
    rows = [{"employer": "A", "elective_deferrals": 20_000, "employer_contributions": 10_000, "after_tax_contributions": 30_000}]
    high = elective_deferral_room(rows, year=2026, age=52, prior_year_fica_wages=160_000)
    assert high.roth_catch_up_required is True and "designated Roth" in high.work
    low = elective_deferral_room(rows, year=2026, age=52, prior_year_fica_wages=140_000)
    assert low.roth_catch_up_required is False
    assert elective_deferral_room(rows, year=2026, age=40, prior_year_fica_wages=160_000).roth_catch_up_required is None   # no catch-up
    assert high.employers[0].annual_additions_room == Decimal("12000.00")    # 72,000 - 60,000
    assert "414(v)(3)(A)(i)" in high.work
