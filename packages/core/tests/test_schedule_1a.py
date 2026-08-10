"""schedule_1a_deductions golden tests — the OBBBA Schedule 1-A op (Phase H, H6).

Every vector is hand-computed from the 2025 Schedule 1-A's own line math (the
pack block was two-pass verified against the published form before the op
existed). The traps these tests pin are the ones that swung the one real
planning session's answer:

  * tips/overtime/senior are FORFEITED on married-filing-separately — but
    car-loan interest is NOT (no joint-filing rule in its statute);
  * the tips $25,000 cap is PER RETURN (a joint return does not double it);
  * the phase-out rounding is ASYMMETRIC — lines 11/19 round the excess/$1,000
    quotient DOWN, line 28 rounds it UP;
  * a qualifying surviving spouse files a NON-joint return and takes the
    `other` thresholds (unlike the rate schedules' QSS→MFJ mapping).

All data is synthetic. Offline (the block is cited in the pack, not fetched).
"""

from __future__ import annotations

import pytest

from taxfill_core.calc import schedule_1a_deductions


def _part(result, part_id):
    return next(p for p in result.parts if p.part == part_id)


# ── Part II: tips ──────────────────────────────────────────────────────────────


def test_tips_phaseout_rounds_the_excess_down():
    # Excess $10,000 -> 10 whole units x $100 = $1,000 off.
    r = schedule_1a_deductions(160_000, "single", 2025, qualified_tips=5_000)
    assert r.total_deduction == 4_000
    # Excess $10,999 -> the quotient 10.999 rounds DOWN (line 11) -> still $1,000.
    r = schedule_1a_deductions(160_999, "single", 2025, qualified_tips=5_000)
    assert r.total_deduction == 4_000
    # Excess $999 -> 0 whole units -> no reduction at all.
    r = schedule_1a_deductions(150_999, "single", 2025, qualified_tips=5_000)
    assert r.total_deduction == 5_000


def test_tips_cap_is_per_return_and_mfj_does_not_double_it():
    r = schedule_1a_deductions(0, "married_filing_jointly", 2025, qualified_tips=30_000)
    assert r.total_deduction == 25_000
    part = _part(r, "II")
    assert part.cap_applied == 25_000 and part.tentative == 25_000
    assert "does NOT double" in r.work


def test_tips_fully_phase_out_for_high_magi():
    # Reduction reaches the full $25,000 cap at excess $250,000 (MAGI $400,000 single).
    r = schedule_1a_deductions(400_000, "single", 2025, qualified_tips=25_000)
    assert r.total_deduction == 0
    assert _part(r, "II").reduction == 25_000


# ── Part III: overtime ─────────────────────────────────────────────────────────


def test_overtime_cap_is_per_status():
    # Single cap $12,500 — the input is the FLSA premium half, already capped here.
    r = schedule_1a_deductions(100_000, "single", 2025, qualified_overtime=15_000)
    assert r.total_deduction == 12_500
    # MFJ cap $25,000, with the same round-DOWN phase-out as tips.
    r = schedule_1a_deductions(310_500, "married_filing_jointly", 2025, qualified_overtime=26_000)
    assert r.total_deduction == 24_000  # cap 25,000 - floor(10.5)=10 x $100


# ── Part IV: car-loan interest ─────────────────────────────────────────────────


def test_car_loan_phaseout_rounds_the_excess_UP():
    # ONE dollar of excess -> ceil(0.001) = 1 unit -> $200 off. The asymmetry trap.
    r = schedule_1a_deductions(100_001, "single", 2025, car_loan_interest=3_000)
    assert r.total_deduction == 2_800
    # At the threshold exactly: excess 0 -> no reduction.
    r = schedule_1a_deductions(100_000, "single", 2025, car_loan_interest=3_000)
    assert r.total_deduction == 3_000
    # Full elimination: the $10,000 cap is gone at excess $50,000 (MAGI $150,000).
    r = schedule_1a_deductions(150_000, "single", 2025, car_loan_interest=10_000)
    assert r.total_deduction == 0


def test_car_loan_is_NOT_forfeited_on_mfs():
    # The one Schedule 1-A deduction a married-filing-separately filer keeps.
    r = schedule_1a_deductions(100_001, "married_filing_separately", 2025, car_loan_interest=3_000)
    assert r.total_deduction == 2_800
    assert _part(r, "IV").forfeited_reason is None


# ── Part V: senior deduction ───────────────────────────────────────────────────


def test_senior_deduction_reduces_six_percent_per_person():
    # 6% x $25,000 excess = $1,500 off the per-person $6,000.
    r = schedule_1a_deductions(100_000, "single", 2025, seniors_qualifying=1)
    assert r.total_deduction == 4_500
    # Fully eliminated at MAGI $175,000 single (6,000 / 0.06 = 100,000 over 75,000).
    r = schedule_1a_deductions(175_000, "single", 2025, seniors_qualifying=1)
    assert r.total_deduction == 0
    # MFJ, both spouses qualify: each $6,000 reduced by 6% x $50,000 = $3,000 -> $3,000 x 2.
    r = schedule_1a_deductions(200_000, "married_filing_jointly", 2025, seniors_qualifying=2)
    assert r.total_deduction == 6_000
    # Both-spouse case eliminated at MAGI $250,000.
    r = schedule_1a_deductions(250_000, "married_filing_jointly", 2025, seniors_qualifying=2)
    assert r.total_deduction == 0


def test_senior_reduction_is_irs_rounded():
    # excess $5,001 x 6% = $300.06 -> $300 (whole dollars) -> $5,700.
    r = schedule_1a_deductions(80_001, "single", 2025, seniors_qualifying=1)
    assert r.total_deduction == 5_700


def test_two_qualifying_seniors_require_a_joint_return():
    with pytest.raises(ValueError, match="requires married_filing_jointly"):
        schedule_1a_deductions(100_000, "single", 2025, seniors_qualifying=2)


# ── The MFS forfeiture and the QSS threshold mapping ───────────────────────────


def test_tips_overtime_senior_are_forfeited_on_mfs():
    r = schedule_1a_deductions(
        100_001, "married_filing_separately", 2025,
        qualified_tips=5_000, qualified_overtime=4_000, seniors_qualifying=1,
    )
    assert r.total_deduction == 0
    for part_id in ("II", "III", "V"):
        part = _part(r, part_id)
        assert part.deduction == 0
        assert part.forfeited_reason is not None and "JOINTLY" in part.forfeited_reason
    assert "file JOINTLY" in r.work


def test_qss_takes_the_non_joint_thresholds():
    # Each statute keys on "a joint return"; QSS files a NON-joint return, so the
    # $150,000 (not $300,000) threshold applies — the opposite of the rate
    # schedules' QSS→MFJ mapping. At MAGI $200,000 the whole $5,000 phases away.
    r = schedule_1a_deductions(200_000, "qualifying_surviving_spouse", 2025, qualified_tips=5_000)
    assert r.total_deduction == 0
    assert _part(r, "II").magi_threshold == 150_000
    assert "NON-joint" in r.work


# ── Assembly, echo, and prescriptive errors ────────────────────────────────────


def test_all_four_parts_sum_to_line_38():
    r = schedule_1a_deductions(
        100_000, "married_filing_jointly", 2025,
        qualified_tips=4_000, qualified_overtime=3_000, car_loan_interest=2_000, seniors_qualifying=1,
    )
    # MAGI 100k MFJ: below every threshold except... tips/overtime 300k, car 200k,
    # senior 150k — all below. No reductions anywhere.
    assert [p.deduction for p in r.parts] == [4_000, 3_000, 2_000, 6_000]
    assert r.total_deduction == 15_000
    assert r.inputs["magi"] == 100_000 and r.inputs["seniors_qualifying"] == 1
    assert "Line 38 total = $15,000" in r.work
    assert "line 13b" in r.work and "13c" in r.work
    assert r.citation.url.startswith("https://www.irs.gov/")


def test_parts_without_inputs_are_omitted():
    r = schedule_1a_deductions(100_000, "single", 2025, qualified_tips=1_000)
    assert [p.part for p in r.parts] == ["II"]


def test_years_without_the_block_fail_closed_prescriptively():
    # Pre-OBBBA year: nothing to compute, and the error says so.
    with pytest.raises(ValueError, match="2025-2028"):
        schedule_1a_deductions(100_000, "single", 2023, qualified_tips=1_000)
    # 2026 planning pack: declared deliberately absent until the 2026 form publishes.
    with pytest.raises(ValueError, match="deliberately absent"):
        schedule_1a_deductions(100_000, "single", 2026, qualified_tips=1_000)


def test_negative_and_bogus_inputs_are_rejected():
    with pytest.raises(ValueError, match=">= 0"):
        schedule_1a_deductions(100_000, "single", 2025, qualified_tips=-5)
    with pytest.raises(ValueError, match="unknown filing_status"):
        schedule_1a_deductions(100_000, "married", 2025, qualified_tips=100)
    with pytest.raises(ValueError, match="whole count"):
        schedule_1a_deductions(100_000, "single", 2025, seniors_qualifying=-1)


def test_mcp_dispatch_reaches_the_op():
    # The server's calc tool must route the new op (and, for a filing-grade year,
    # add no provisional stamp).
    from taxfill_mcp.server import calc

    out = calc("schedule_1a_deductions", {
        "magi": 160_000, "filing_status": "single", "year": 2025, "qualified_tips": 5_000,
    })
    assert out["total_deduction"] == 4_000
    assert "provisional" not in out


def test_each_part_names_its_form_line_for_the_verify_flow():
    # The sched_1a form pack deliberately does NOT encode the phase-out worksheet
    # lines (its header says so) — the op fills that gap, so verify_form's
    # `independent` must be keyable straight off the result: parts land on lines
    # 13/21/30/37 and the pack's own relation sums them ("38 == 13 + 21 + 30 + 37").
    r = schedule_1a_deductions(
        100_000, "married_filing_jointly", 2025,
        qualified_tips=4_000, qualified_overtime=3_000, car_loan_interest=2_000, seniors_qualifying=1,
    )
    assert [(p.part, p.form_line) for p in r.parts] == [("II", "13"), ("III", "21"), ("IV", "30"), ("V", "37")]
    assert sum(p.deduction for p in r.parts) == r.total_deduction


def test_overtime_work_pushes_back_on_the_marketing_name():
    # N-14: "no tax on overtime" produced a real wrong conclusion ("overtime is
    # untaxed"). The work must state the two distinctions unprompted: only the
    # FLSA premium half qualifies, and the deduction sits BELOW the AGI line, so
    # the overtime still raises every MAGI test.
    r = schedule_1a_deductions(80_000, "single", 2025, qualified_overtime=4_000)
    assert "PREMIUM HALF" in r.work and "BELOW-the-AGI-line" in r.work
    assert "MAGI" in r.work
    # No overtime input -> no push-back noise.
    r2 = schedule_1a_deductions(80_000, "single", 2025, qualified_tips=1_000)
    assert "PREMIUM HALF" not in r2.work
