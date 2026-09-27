"""Federal residency classification tests — IRS Pub. 519 rules.

All data is synthetic: no real people, SSNs, or travel records; dates and
day counts are constructed to hit the rule boundaries exactly. Offline by
design (the Pub 519 rules are cited in the module, not fetched at test time).
"""

from datetime import date

import pytest

from taxfill_core.residency import (
    classify,
    exempt_individual_years,
    section_6013_kind,
    section_6013_texts,
    substantial_presence_test,
)


def period(status, start, end=None):
    return {"status": status, "start": start, "end": end}


# ---------------------------------------------------------------------------
# substantial_presence_test
# ---------------------------------------------------------------------------


def test_pub519_worked_example_120_days_each_year():
    # Pub 519's own example: 120 + 120/3 + 120/6 = 180 -> NOT a resident.
    result = substantial_presence_test({2024: 120, 2023: 120, 2022: 120}, 2024)
    assert result.meets_spt is False
    assert result.meets_31_day_test is True
    assert result.meets_183_day_test is False
    assert result.weighted_days == 180.0
    assert result.weighted_days_exact == "180"
    assert "= 180 weighted days" in result.work
    assert "120/3 = 40" in result.work
    assert "120/6 = 20" in result.work
    assert result.citations and all("irs.gov" in c.url for c in result.citations)
    assert result.inputs["target_year"] == 2024  # results echo their inputs (dev plan section 8)
    assert result.inputs["days_by_year"] == {2024: 120, 2023: 120, 2022: 120}


def test_weighted_exactly_183_meets():
    # 120 + 189/3 = 120 + 63 = exactly 183 -> met (the threshold is inclusive).
    result = substantial_presence_test({2024: 120, 2023: 189}, 2024)
    assert result.weighted_days_exact == "183"
    assert result.meets_spt is True


def test_one_third_of_a_day_below_183_fails():
    # 120 + 188/3 = 182 2/3 -> NOT met; the fraction is kept, never rounded up.
    result = substantial_presence_test({2024: 120, 2023: 188}, 2024)
    assert result.weighted_days_exact == "182 2/3"
    assert result.meets_spt is False
    assert "182 2/3" in result.work


def test_fractions_never_rounded_per_term():
    # 182 + 1/3 + 1/6 = 182 1/2 -> NOT met. Rounding each term up (1 + 1)
    # would falsely give 184 and flip the answer.
    result = substantial_presence_test({2024: 182, 2023: 1, 2022: 1}, 2024)
    assert result.weighted_days_exact == "182 1/2"
    assert result.meets_spt is False


def test_31_day_boundary_met_exactly():
    # 31 + 360/3 + 360/6 = 31 + 120 + 60 = 211 -> both prongs met at the 31-day floor.
    result = substantial_presence_test({2024: 31, 2023: 360, 2022: 360}, 2024)
    assert result.meets_31_day_test is True
    assert result.meets_spt is True


def test_30_days_fails_even_with_weighted_over_183():
    # 30 + 120 + 60 = 210 weighted, but 30 < 31 -> the SPT is NOT met.
    result = substantial_presence_test({2024: 30, 2023: 360, 2022: 360}, 2024)
    assert result.meets_183_day_test is True
    assert result.meets_31_day_test is False
    assert result.meets_spt is False


def test_missing_years_count_as_zero_days():
    result = substantial_presence_test({2024: 200}, 2024)
    assert result.days_first_preceding_year == 0
    assert result.days_second_preceding_year == 0
    assert result.meets_spt is True


def test_missing_preceding_years_flagged_in_work_with_flip_warning():
    # A NOT-met result computed with missing preceding years is never silent:
    # the work says they were treated as 0 and that real counts could flip it.
    result = substantial_presence_test({2023: 150}, 2023)
    assert result.meets_spt is False
    assert "days for 2021, 2022 not provided — treated as 0" in result.work
    assert "may flip to met (resident)" in result.work
    assert "0 is a valid answer" in result.work


def test_missing_years_note_is_mild_when_spt_already_met():
    # Met is monotone-safe (more days cannot un-meet it) — noted, no flip warning.
    result = substantial_presence_test({2024: 200}, 2024)
    assert "not provided — treated as 0" in result.work
    assert "may flip" not in result.work


def test_no_missing_year_note_when_all_three_years_supplied():
    result = substantial_presence_test({2024: 120, 2023: 120, 2022: 120}, 2024)
    assert "not provided" not in result.work


def test_string_year_keys_accepted():
    # JSON round-trips turn int keys into strings; accept digit strings.
    result = substantial_presence_test({"2024": 200, "2023": 30}, 2024)
    assert result.days_current_year == 200
    assert result.days_first_preceding_year == 30


@pytest.mark.parametrize(
    "days",
    [
        {2024: -1},  # negative
        {2024: 367},  # more days than any year has
        {2023: 366},  # 2023 is not a leap year: 365 days max
        {2024: 12.5},  # fractional days: a partial day counts as a full day
        {2024: True},  # bool is not a day count
        {"20x4": 100},  # malformed year key
    ],
)
def test_invalid_days_rejected_prescriptively(days):
    with pytest.raises(ValueError, match="days_by_year"):
        substantial_presence_test(days, 2024)


def test_leap_year_day_cap_is_year_aware():
    # Regression: 366 was accepted for every year; 2023 has only 365 days.
    assert substantial_presence_test({2024: 366}, 2024).days_current_year == 366  # 2024 is a leap year
    with pytest.raises(ValueError, match="2023 has 365 days"):
        substantial_presence_test({2023: 366}, 2024)


def test_target_year_must_be_int():
    with pytest.raises(ValueError, match="target_year"):
        substantial_presence_test({2024: 120}, "2024")


# ---------------------------------------------------------------------------
# exempt_individual_years
# ---------------------------------------------------------------------------


def test_sample_f1_exempt_for_five_calendar_years():
    # The standard case shape: F-1 arrives year N -> exempt N..N+4, SPT from N+5.
    periods = [period("F-1", date(2018, 8, 24))]
    result = exempt_individual_years(periods, 2024)
    assert result.fully_exempt_years == [2018, 2019, 2020, 2021, 2022]
    assert result.partially_exempt_years == []
    by_year = {r.year: r for r in result.records}
    assert by_year[2018].exempt is True
    assert "#1" in by_year[2018].reason
    assert by_year[2023].exempt is False
    assert "5 calendar years" in by_year[2023].reason
    assert by_year[2024].exempt is False
    assert any("irs.gov" in c.url for c in result.citations)


def test_partial_arrival_year_consumes_a_whole_exempt_year():
    # Arriving December 28 still burns calendar year #1 of the lifetime 5.
    result = exempt_individual_years([period("F-1", date(2019, 12, 28))], 2025)
    assert result.fully_exempt_years == [2019, 2020, 2021, 2022, 2023]
    assert {r.year for r in result.records if not r.exempt} == {2024, 2025}


def test_j1_researcher_exempt_two_years_then_blocked_by_2_of_6_rule():
    periods = [period("J-1 researcher", date(2022, 9, 1))]
    result = exempt_individual_years(periods, 2025)
    assert result.fully_exempt_years == [2022, 2023]
    by_year = {r.year: r for r in result.records}
    assert by_year[2024].exempt is False
    assert "2 of the 6 preceding" in by_year[2024].reason
    assert by_year[2025].exempt is False


def test_j1_researcher_requalifies_after_six_year_gap():
    # Exempt 2015-2016; by 2023 the preceding 6 years (2017-2022) hold zero
    # exempt years, so the teacher/trainee exemption applies again.
    periods = [
        period("J-1 teacher", date(2015, 1, 1), date(2016, 12, 31)),
        period("J-1 researcher", date(2023, 6, 1)),
    ]
    result = exempt_individual_years(periods, 2024)
    assert result.fully_exempt_years == [2015, 2016, 2023, 2024]


def test_prior_student_years_block_the_researcher_exemption():
    # "teacher, trainee, OR STUDENT" years count in the 2-of-6 lookback.
    periods = [
        period("F-1", date(2020, 8, 1), date(2022, 5, 31)),
        period("J-1 researcher", date(2023, 1, 1)),
    ]
    result = exempt_individual_years(periods, 2024)
    assert result.fully_exempt_years == [2020, 2021, 2022]
    by_year = {r.year: r for r in result.records}
    assert by_year[2023].exempt is False
    assert by_year[2024].exempt is False
    assert "foreign-employer" in by_year[2023].reason  # exception exists, not modeled


def test_transition_year_inside_exempt_window_is_partial():
    # F-1 (exempt year #4) ends June 30; H-1B starts July 1 -> only part of
    # 2024 is exempt, and the record says which dates.
    periods = [
        period("F-1", date(2021, 8, 10), date(2024, 6, 30)),
        period("H-1B", date(2024, 7, 1)),
    ]
    result = exempt_individual_years(periods, 2024)
    assert result.fully_exempt_years == [2021, 2022, 2023]
    assert result.partially_exempt_years == [2024]
    record = {r.year: r for r in result.records}[2024]
    assert record.coverage == "partial_year"
    assert "2024-01-01..2024-06-30" in record.reason


def test_bare_j1_status_is_rejected_as_ambiguous():
    with pytest.raises(ValueError, match="J-1 student"):
        exempt_individual_years([period("J-1", date(2022, 9, 1))], 2024)


@pytest.mark.parametrize(
    "status", ["OPT", "STEM OPT", "cap-gap", "cap gap", "CPT", "Optional Practical Training"]
)
def test_bare_work_authorization_status_is_rejected_not_silently_counted(status):
    # Regression for a silent nonresident->resident flip: these strings are how a
    # filer describes their situation ('OPT'), but they name a WORK
    # AUTHORIZATION, not a visa status. Before the guard, they matched no
    # F/M/J/Q prefix, the days counted toward the SPT, and classify() returned
    # `resident` while the identical facts entered as 'F-1 OPT' returned
    # `nonresident` — a filing-grade wrong answer on a wording difference.
    days = {2021: 150, 2022: 330, 2023: 330, 2024: 330, 2025: 330}
    with pytest.raises(ValueError, match="WORK AUTHORIZATION"):
        classify([period(status, date(2021, 8, 1))], days, 2025)
    # The error is prescriptive: it says exactly what to resubmit.
    with pytest.raises(ValueError, match="F-1 OPT"):
        classify([period(status, date(2021, 8, 1))], days, 2025)


def test_status_with_visa_class_plus_work_authorization_still_classifies():
    # The fix must not regress the correctly-phrased inputs: 'F-1 OPT' names the
    # class, matches the F/M student rule, and stays nonresident (exempt years).
    days = {2021: 150, 2022: 330, 2023: 330, 2024: 330, 2025: 330}
    for status in ("F-1 OPT", "F-1 STEM OPT", "M-1 OPT"):
        result = classify([period(status, date(2021, 8, 1))], days, 2025)
        assert result.classification == "nonresident", status


def test_h1b_only_timeline_has_no_exempt_years():
    result = exempt_individual_years([period("H-1B", date(2022, 10, 1))], 2024)
    assert result.records == []
    assert result.fully_exempt_years == []
    assert "No F, J, M, or Q" in result.work


def test_zero_presence_year_does_not_consume_a_student_exempt_year():
    # Regression (blocker): exempt calendar years used to be consumed by mere
    # visa-period OVERLAP with the calendar year. Pub 519: an exempt
    # individual is someone temporarily IN the US on an F/J/M/Q visa — with
    # ZERO days of presence the person was never exempt for any part of that
    # year, so it cannot count toward the lifetime-5 student limit.
    periods = [period("F-1", date(2018, 8, 15))]
    days = {2018: 130, 2019: 365, 2020: 0, 2021: 0, 2022: 365, 2023: 365, 2024: 366}
    result = exempt_individual_years(periods, 2024, days_by_year=days)
    # 2020/2021 (e.g. COVID remote study from abroad) consume nothing, so
    # 2024 is exempt year #5 — not "past the limit".
    assert result.fully_exempt_years == [2018, 2019, 2022, 2023, 2024]
    by_year = {r.year: r for r in result.records}
    for skipped in (2020, 2021):
        assert by_year[skipped].exempt is False
        assert "0 days of US presence" in by_year[skipped].reason
        assert "counts toward neither" in by_year[skipped].reason


def test_zero_presence_year_not_counted_in_teacher_2_of_6_lookback():
    # Same root cause on the teacher/trainee side: a J-period year with zero
    # presence must not inflate the 2-of-6 preceding-years lookback.
    periods = [
        period("J-1 teacher", date(2022, 1, 1), date(2023, 12, 31)),
        period("J-1 researcher", date(2024, 1, 1)),
    ]
    days = {2022: 200, 2023: 0, 2024: 200}
    result = exempt_individual_years(periods, 2024, days_by_year=days)
    # Lookback for 2024 holds only 2022 (2023 had zero presence): 1 < 2 -> exempt.
    assert result.fully_exempt_years == [2022, 2024]
    by_year = {r.year: r for r in result.records}
    assert by_year[2023].exempt is False
    assert by_year[2024].exempt is True


def test_category_year_missing_from_days_is_rejected_prescriptively():
    # Presence UNKNOWN is never silently assumed: the caller is told to
    # supply that year's count, and that 0 is a valid answer.
    with pytest.raises(ValueError, match=r"no entry for 2018.*0 is a valid answer"):
        exempt_individual_years(
            [period("F-1", date(2018, 8, 24))], 2020, days_by_year={2019: 100, 2020: 100}
        )


def test_exempt_years_without_days_assumes_presence():
    # Documented standalone behavior: no days_by_year -> presence assumed for
    # every category-period year (classify always passes the counts).
    result = exempt_individual_years([period("F-1", date(2018, 8, 15))], 2024)
    assert result.fully_exempt_years == [2018, 2019, 2020, 2021, 2022]


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

SAMPLE_F1 = [period("F-1", date(2018, 8, 24))]


def test_sample_f1_exempt_years_classify_nonresident():
    # Years N..N+4 all exempt -> every counted day excluded -> nonresident.
    result = classify(
        SAMPLE_F1,
        {2018: 130, 2019: 330, 2020: 330, 2021: 330, 2022: 330},
        2022,
    )
    assert result.classification == "nonresident"
    assert result.spt.weighted_days == 0.0
    assert "excluded from the SPT" in result.work
    assert "SPT 2022" in result.work


def test_sample_f1_sixth_year_is_resident():
    # N+5: the student exemption is exhausted, F-1 days count, SPT met,
    # status unchanged all year -> plain resident (no dual-status flag).
    result = classify(
        SAMPLE_F1,
        {2018: 130, 2019: 330, 2020: 330, 2021: 330, 2022: 330, 2023: 330},
        2023,
    )
    assert result.classification == "resident"
    assert result.spt.meets_spt is True
    assert result.spt.days_current_year == 330  # 2021/2022 zeroed, 2023 counted
    assert result.spt.days_first_preceding_year == 0


def test_f1_to_h1b_after_exemption_exhausted_is_full_year_resident():
    # Regression (over-flagging): a year-6+ F-1 -> H-1B mid-year transition
    # used to be flagged dual_status_candidate even though the student
    # exemption was already exhausted, so the F-1 days counted from Jan 1 and
    # Pub 519 makes a continuously present person a full-year resident — the
    # status change alone cannot split the year.
    periods = [
        period("F-1", date(2018, 8, 24), date(2023, 9, 30)),
        period("H-1B", date(2023, 10, 1)),
    ]
    days = {2018: 130, 2019: 330, 2020: 330, 2021: 330, 2022: 330, 2023: 330}
    result = classify(periods, days, 2023)
    assert result.classification == "resident"
    note = next(r for r in result.reasons if "does not split the year" in r)
    assert "F-1" in note and "H-1B" in note
    assert "full-year resident" in note
    assert any("residency-starting-and-ending-dates" in c.url for c in result.citations)


def test_transition_within_exempt_window_flags_dual_status_and_recount():
    # 2024 is partially exempt (F-1 part still inside the 5-year window):
    # per-year totals cannot be split, so the maximum possible non-exempt-part
    # days count (the 184-day Jul-Dec span beats the 360 reported) and a
    # reason tells the caller exactly how to tighten the answer.
    periods = [
        period("F-1", date(2021, 8, 10), date(2024, 6, 30)),
        period("H-1B", date(2024, 7, 1)),
    ]
    result = classify(periods, {2021: 140, 2022: 340, 2023: 340, 2024: 360}, 2024)
    assert result.classification == "dual_status_candidate"
    assert any("cannot be split" in r for r in result.reasons)
    assert any("recount" in r.lower() for r in result.reasons)
    assert any("F-1 to H-1B" in r for r in result.reasons)  # the mid-year change is flagged
    assert any("you and your agent decide" in r.lower() for r in result.reasons)
    assert any("First-Year Choice" in r for r in result.reasons)
    assert result.spt.days_current_year == 184  # min(360 reported, Jul 1..Dec 31 = 184)


def test_partial_year_ceiling_below_183_is_definitively_nonresident():
    # Regression: F-1 (exempt year #4) ends Sep 30, H-1B from Oct 1. Even if
    # the taxpayer were present every remaining day, Oct 1..Dec 31 = 92 < 183
    # and the two preceding years are fully exempt, so the SPT CANNOT be met
    # — Pub 519 outcome is nonresident (1040-NR + 8843), not a conservative
    # dual_status_candidate flag, and no recount is needed.
    periods = [
        period("F-1", date(2021, 8, 10), date(2024, 9, 30)),
        period("H-1B", date(2024, 10, 1)),
    ]
    result = classify(periods, {2021: 140, 2022: 350, 2023: 360, 2024: 366}, 2024)
    assert result.classification == "nonresident"
    assert result.spt.days_current_year == 92  # min(366 reported, Oct 1..Dec 31 = 92)
    assert result.spt.meets_spt is False
    assert any("no recount can change it" in r for r in result.reasons)
    assert any("First-Year Choice" in r for r in result.reasons)  # the main way out, mentioned


def test_jf1b7_a_capped_count_near_183_is_definitive_with_no_recount_warning():
    """JF1b.7 acceptance: F-1 2022-08-18 -> 2025-07-14 then H-1B 2025-07-15, TY2025. The
    non-exempt span Jul 15..Dec 31 is 170 days and 2023/2024 are fully exempt, so the weighted
    total can never pass 170: nonresident, definitive — and no "recount" reason (the count is
    already at its maximum), though 170 is within the near-183 band."""
    periods = [
        period("F-1", date(2022, 8, 18), date(2025, 7, 14)),
        period("H-1B", date(2025, 7, 15)),
    ]
    result = classify(periods, {2022: 136, 2023: 365, 2024: 366, 2025: 365}, 2025)
    assert result.classification == "nonresident"
    assert result.spt.days_current_year == 170
    assert any("definitive" in r and "no recount can change it" in r for r in result.reasons)
    assert not any("close to the 183-day threshold" in r for r in result.reasons)
    assert not any("recount days present" in r for r in result.reasons)


def test_jf1b7_a_capped_year_with_an_open_lookback_year_is_not_definitive():
    # Hypothetical: H-1B until 2025-03-31, then F-1. 2025's non-exempt span (Jan-Mar, 90 days)
    # is at its maximum, but 2024 and 2023 are NOT exempt years: more days there could still
    # meet the SPT (at most 90 + 366/3 + 365/6), so no "definitive" — the recount is named.
    periods = [
        period("H-1B", date(2022, 1, 1), date(2025, 3, 31)),
        period("F-1", date(2025, 4, 1)),
    ]
    result = classify(periods, {2023: 150, 2024: 150, 2025: 365}, 2025)
    assert result.classification == "nonresident"
    assert not any("definitive" in r for r in result.reasons)
    open_reason = next(r for r in result.reasons if "could reach" in r)
    assert "272 5/6" in open_reason and "recount days present in 2024" in open_reason
    # 90 + 50 + 25 = 165: inside the near-183 band, and a recount CAN raise it — warned.
    assert any("close to the 183-day threshold" in r for r in result.reasons)


def test_jf1b7_a_current_year_span_under_31_days_is_definitive():
    # The 31-day prong: 2025's non-exempt span is Jan 1-14, so the SPT cannot be met whatever
    # the lookback years hold.
    periods = [
        period("H-1B", date(2022, 1, 1), date(2025, 1, 14)),
        period("F-1", date(2025, 1, 15)),
    ]
    result = classify(periods, {2023: 365, 2024: 366, 2025: 365}, 2025)
    assert result.classification == "nonresident"
    assert any("no recount can change it" in r for r in result.reasons)


def test_status_change_exactly_on_jan_1_is_not_dual_status():
    periods = [
        period("F-1", date(2018, 8, 24), date(2022, 12, 31)),
        period("H-1B", date(2023, 1, 1)),
    ]
    result = classify(periods, {2018: 130, 2019: 330, 2020: 330, 2021: 330, 2022: 330, 2023: 330}, 2023)
    assert result.classification == "resident"


def test_mid_year_first_arrival_flags_dual_status():
    result = classify([period("H-1B", date(2024, 3, 15))], {2024: 250}, 2024)
    assert result.classification == "dual_status_candidate"
    assert any("2024-03-15" in r for r in result.reasons)


def test_resident_under_183_actual_days_mentions_closer_connection():
    # SPT met on the weighted total (130 + 200/3 + 30/6 = 201 2/3) with only
    # 130 actual days -> resident, plus a closer-connection (Form 8840) note.
    result = classify(
        [period("H-1B", date(2022, 1, 1))],
        {2022: 30, 2023: 200, 2024: 130},
        2024,
    )
    assert result.classification == "resident"
    assert result.spt.weighted_days_exact == "201 2/3"
    assert any("Form 8840" in r for r in result.reasons)
    assert any("closer-connection-exception" in c.url for c in result.citations)


def test_closer_connection_screen_uses_countable_not_raw_days():
    # Regression: the fewer-than-183-days screen used RAW presence days, but
    # under IRC 7701(b)(5)/Pub 519 exempt-individual days are not 'days of
    # presence'. J-1 teacher exempt Jan-Oct: 366 raw days but only 61
    # countable (Nov 1..Dec 31 cap) -> the Form 8840 hint must fire.
    periods = [
        period("H-1B", date(2022, 1, 1), date(2023, 12, 31)),
        period("J-1 teacher", date(2024, 1, 1), date(2024, 10, 31)),
        period("H-1B", date(2024, 11, 1)),
    ]
    result = classify(periods, {2022: 365, 2023: 365, 2024: 366}, 2024)
    assert result.spt.days_current_year == 61  # min(366 reported, Nov 1..Dec 31 = 61)
    assert result.spt.meets_spt is True  # 61 + 365/3 + 365/6 = 243 1/2
    assert result.classification == "dual_status_candidate"  # partially exempt target year
    hint = next(r for r in result.reasons if "Form 8840" in r)
    assert "61 countable day(s)" in hint
    assert "exempt-individual days do not count" in hint


def test_closer_connection_note_includes_eligibility_conditions():
    # Regression: the Form 8840 note must carry the verified Pub 519
    # conditions — tax home for the ENTIRE year, and the disqualifier for
    # anyone who took steps toward a green card.
    result = classify(
        [period("H-1B", date(2022, 1, 1))],
        {2022: 30, 2023: 200, 2024: 130},
        2024,
    )
    note = next(r for r in result.reasons if "Form 8840" in r)
    assert "entire year" in note
    assert "green card" in note


def test_departure_year_mentions_residency_ending_rules():
    # Regression: a timeline ending mid-target-year (left the US) used to
    # classify plain resident with no mention of the Pub 519 residency
    # ending rules. Default stays December 31 (still resident); the
    # earlier-termination conditions are surfaced as a reason, not computed.
    result = classify(
        [period("H-1B", date(2022, 1, 1), date(2024, 6, 30))],
        {2022: 330, 2023: 330, 2024: 170},
        2024,
    )
    assert result.classification == "resident"
    assert any("residency ending date" in r for r in result.reasons)
    assert any("residency-starting-and-ending-dates" in c.url for c in result.citations)


def test_nonresident_near_183_mentions_closer_connection_and_recount():
    # 120/120/120 -> 180 weighted: close to the line, so the reasons say to
    # recount and that the closer-connection exception exists.
    result = classify(
        [period("H-1B", date(2022, 1, 1))],
        {2022: 120, 2023: 120, 2024: 120},
        2024,
    )
    assert result.classification == "nonresident"
    assert any("Form 8840" in r for r in result.reasons)
    assert any("recount" in r.lower() for r in result.reasons)


def test_nonresident_weighted_over_183_but_under_31_days():
    # 25 + 120 + 60 = 205 weighted, but 25 < 31 days -> nonresident; the
    # reason names the 31-day minimum and the exception.
    result = classify(
        [period("H-1B", date(2022, 1, 1))],
        {2022: 360, 2023: 360, 2024: 25},
        2024,
    )
    assert result.classification == "nonresident"
    assert result.spt.meets_183_day_test is True
    assert any("31-day minimum" in r for r in result.reasons)
    assert any("Form 8840" in r for r in result.reasons)


def test_missing_covered_prior_years_make_nonresident_caveat_prominent():
    # Finding repro: H-1B since Feb 2020, only 2023 days supplied. The SPT treats
    # the missing 2021/2022 as 0 and lands nonresident, but real counts for those
    # period-covered years could flip it to resident — the caveat must lead the
    # reasons, not hide in fine print.
    result = classify([period("H-1B", date(2020, 2, 1))], {2023: 150}, 2023)
    assert result.classification == "nonresident"
    top = result.reasons[0]
    assert top.startswith("IMPORTANT")
    assert "may be WRONG" in top
    assert "2021, 2022" in top
    assert "FLIP to resident" in top
    assert "0 is a valid answer" in top
    # The SPT work carries the treated-as-0 note too.
    assert "days for 2021, 2022 not provided — treated as 0" in result.spt.work


def test_supplying_the_missing_years_flips_the_same_person_to_resident():
    # Companion to the prominent caveat: the same H-1B with real counts is a
    # resident — proving the missing-years zero was silently load-bearing before.
    result = classify(
        [period("H-1B", date(2020, 2, 1))], {2021: 320, 2022: 330, 2023: 150}, 2023
    )
    assert result.classification == "resident"
    assert not any("may be WRONG" in r for r in result.reasons)


def test_missing_years_not_flagged_without_period_coverage():
    # First US status starts mid-target-year: no declared period covers 2022/2023,
    # so their absence is expected (timeline assumed complete) — no missing-years
    # reason fires and the dual-status flag is undisturbed.
    result = classify([period("H-1B", date(2024, 3, 15))], {2024: 250}, 2024)
    assert result.classification == "dual_status_candidate"
    assert not any("no entry for" in r for r in result.reasons)


def test_missing_years_note_not_prominent_below_31_days():
    # 20 days present: the 31-day prong fails no matter what the missing years
    # hold, so the nonresident answer cannot flip — plain note, standard lead reason.
    result = classify([period("H-1B", date(2020, 2, 1))], {2023: 20}, 2023)
    assert result.classification == "nonresident"
    assert result.reasons[0].startswith("Substantial presence test NOT met")
    note = next(r for r in result.reasons if "no entry for 2021, 2022" in r)
    assert "31-day minimum" in note
    assert "0 is a valid answer" in note


def test_green_card_overrides_spt():
    result = classify([], {}, 2024, is_lawful_permanent_resident=True)
    assert result.classification == "resident"
    assert "Green card test" in result.reasons[0]
    assert any("green-card-test" in c.url for c in result.citations)


def test_green_card_holder_abroad_flags_abandonment_and_tie_breaker():
    # A green-card holder with (near-)zero US days is still a resident — and the
    # reasons must say WHY that does not end by living abroad: LPR status persists
    # until formally abandoned (I-407), a treaty tie-breaker (Form 8833) is the
    # elective out, and worldwide income stays reportable meanwhile.
    result = classify([], {2023: 0}, 2023, is_lawful_permanent_resident=True)
    assert result.classification == "resident"
    note = next(r for r in result.reasons if "I-407" in r)
    assert "Form 8833" in note
    assert "worldwide income" in note
    assert "Form 8854" in note  # expatriation-tax side effect is named
    assert "Pub. 519" in note  # cited like the neighboring reasons
    assert any("green-card-test" in c.url for c in result.citations)


def test_green_card_holder_with_substantial_presence_gets_no_abroad_flag():
    # 300 days present: not the living-abroad pattern — no I-407/8833 noise.
    result = classify([], {2024: 300}, 2024, is_lawful_permanent_resident=True)
    assert result.classification == "resident"
    assert not any("I-407" in r for r in result.reasons)


def test_green_card_holder_is_not_blocked_on_incomplete_day_history():
    # The strict category-year day-count requirement must not fire for a
    # lawful permanent resident: the green card test classifies them resident
    # regardless of the SPT, and they have no I-94 homework to do first.
    periods = [period("F-1", date(2018, 8, 24), date(2023, 9, 30))]
    result = classify(periods, {2023: 200}, 2023, is_lawful_permanent_resident=True)
    assert result.classification == "resident"


def test_green_card_overrides_dual_status_flag():
    periods = [
        period("F-1", date(2018, 8, 24), date(2023, 9, 30)),
        period("H-1B", date(2023, 10, 1)),
    ]
    result = classify(
        periods, {2021: 330, 2022: 330, 2023: 330}, 2023, is_lawful_permanent_resident=True
    )
    assert result.classification == "resident"


def test_days_without_a_covering_period_rejected():
    with pytest.raises(ValueError, match="add the missing period"):
        classify([period("H-1B", date(2024, 1, 1))], {2022: 100, 2024: 50}, 2024)


def test_empty_timeline_with_presence_days_rejected():
    # Regression: an empty timeline used to skip the completeness check
    # entirely, silently classifying a forgotten-timeline F-1 as resident.
    with pytest.raises(ValueError, match="visa_periods is empty"):
        classify([], {2024: 200}, 2024)


def test_green_card_holder_needs_no_visa_timeline():
    # Regression: the timeline-completeness check used to fire for lawful
    # permanent residents, who have no visa timeline to declare — the green
    # card test classifies them resident regardless of the SPT.
    result = classify([], {2024: 300}, 2024, is_lawful_permanent_resident=True)
    assert result.classification == "resident"
    uncovered = classify(
        [period("H-1B", date(2024, 1, 1))],
        {2022: 100, 2024: 50},
        2024,
        is_lawful_permanent_resident=True,
    )
    assert uncovered.classification == "resident"


def test_empty_inputs_classify_nonresident():
    result = classify([], {}, 2024)
    assert result.classification == "nonresident"


def test_a_visa_periods_rejected_as_unsupported():
    with pytest.raises(ValueError, match="not supported in v1"):
        classify([period("A-1", date(2023, 1, 1))], {2023: 200}, 2024)


def test_end_before_start_rejected():
    with pytest.raises(ValueError, match="before start"):
        classify([period("F-1", date(2024, 5, 1), date(2024, 1, 1))], {}, 2024)


def test_iso_date_strings_accepted():
    result = classify(
        [{"status": "F-1", "start": "2018-08-24", "end": None}],
        {2018: 130, 2019: 330, 2020: 330, 2021: 330, 2022: 330},
        2022,
    )
    assert result.classification == "nonresident"


def test_profile_visa_period_objects_accepted():
    # Shape compatibility with schemas/profile.py: VisaPeriod objects (extra
    # fields like provenance, end=None while ongoing) classify identically.
    from taxfill_core.schemas.profile import Provenance, VisaPeriod

    visa_period = VisaPeriod(
        status="F-1",
        start=date(2018, 8, 24),
        end=None,
        provenance=Provenance.user_stated(),
    )
    result = classify(
        [visa_period], {2018: 130, 2019: 330, 2020: 330, 2021: 330, 2022: 330}, 2022
    )
    assert result.classification == "nonresident"
    assert result.exempt_years.fully_exempt_years == [2018, 2019, 2020, 2021, 2022]


def test_classify_rejects_unknown_presence_for_category_years():
    # Regression companion to the zero-presence fix: classify never assumes
    # presence for an exempt-category year — missing counts are rejected with
    # instructions (0 is a valid answer), because assuming presence can burn
    # exempt years the taxpayer never used and flip the classification.
    with pytest.raises(ValueError, match=r"no entry for 2018.*0 is a valid answer"):
        classify(SAMPLE_F1, {2022: 200}, 2022)


def test_classify_zero_presence_years_keep_late_exempt_years_alive():
    # End-to-end shape of the original blocker: student abroad full-time
    # 2020-2021 (e.g. COVID remote study). 2024 is exempt year #5, ALL 2024
    # days are excluded, SPT fails -> NONRESIDENT (files 1040-NR + 8843) —
    # previously misclassified as resident with 487 2/3 weighted days.
    result = classify(
        [period("F-1", date(2018, 8, 15))],
        {2018: 130, 2019: 365, 2020: 0, 2021: 0, 2022: 365, 2023: 365, 2024: 366},
        2024,
    )
    assert result.classification == "nonresident"
    assert result.exempt_years.fully_exempt_years == [2018, 2019, 2022, 2023, 2024]
    assert result.spt.days_current_year == 0
    assert result.spt.weighted_days == 0.0


def test_result_carries_work_inputs_and_citations():
    days = {2018: 130, 2019: 330, 2020: 330, 2021: 330, 2022: 330, 2023: 330}
    result = classify(SAMPLE_F1, days, 2023)
    assert "Exempt-individual analysis" in result.work
    assert "SPT 2023" in result.work
    assert result.citations
    # Citations are the same structured model calc results use (source + url).
    assert all("irs.gov" in c.url for c in result.citations)
    assert all(c.source.startswith("IRS Pub. 519") for c in result.citations)
    # Results echo their inputs (dev plan section 8 calc contract).
    assert result.inputs["days_by_year"] == days
    assert result.inputs["target_year"] == 2023
    assert result.inputs["is_lawful_permanent_resident"] is False
    assert result.inputs["visa_periods"] == [
        {"status": "F-1", "start": "2018-08-24", "end": None}
    ]
    # Result models serialize cleanly for the MCP layer.
    dumped = result.model_dump()
    assert dumped["classification"] == "resident"
    assert dumped["spt"]["weighted_days_exact"] == "330"
    assert dumped["citations"][0]["url"].startswith("https://www.irs.gov")


# ---------------------------------------------------------------------------
# P-018 (Phase J JF5a): the §6013(g)/(h) election is a residency FACT. Pub 519
# (2025) ch. 1, Nonresident Spouse Treated as a Resident: "If you make this
# choice, you and your spouse are treated for income tax purposes as residents
# for your entire tax year" — and "the special instructions and restrictions for
# dual-status taxpayers in chapter 6 do not apply to you". IRC 6013(g)(1) reaches
# "chapter 1 for all of such taxable year" and chapter 24 wage withholding only,
# so the day-count answer is kept (FICA and the precondition still follow it).
# ---------------------------------------------------------------------------

_SAMPLE_F1_DAYS = {2018: 130, 2019: 330, 2020: 330, 2021: 330, 2022: 330}


def test_p018_election_makes_an_exempt_f1_resident_and_keeps_the_day_count_answer():
    without = classify(SAMPLE_F1, _SAMPLE_F1_DAYS, 2022)
    assert without.classification == "nonresident"          # control: exempt year, SPT fails
    assert without.section_6013_election is False
    assert without.classification_without_election is None  # no election, nothing to keep
    result = classify(SAMPLE_F1, _SAMPLE_F1_DAYS, 2022, section_6013_election=True)
    assert result.classification == "resident"
    assert result.section_6013_election is True
    assert result.classification_without_election == "nonresident"
    # The day-count work still runs and is unchanged — the election never rewrites it.
    assert result.spt.weighted_days == 0.0
    assert result.spt.meets_spt is False
    assert result.work == without.work
    # The reasons lead with the election and its three quoted rules, then explain the
    # no-election answer (which still decides the precondition and FICA).
    lead = result.reasons[0]
    assert lead.startswith("§6013(g)/(h) election applied: RESIDENT for all of 2022")
    assert "treated for income tax purposes as residents for your entire tax year" in lead
    assert "one spouse is a U.S. citizen or a resident alien" in lead          # the precondition
    assert "chapter 24 (relating to wage withholding)" in lead and "3121(b)(19)" in lead  # FICA
    assert "classification_without_election" in result.reasons[1] and "'nonresident'" in result.reasons[1]
    assert without.reasons[0] in result.reasons                              # the SPT reasons are kept
    assert any("6013" in c.source and c.url.startswith("https://www.irs.gov") for c in result.citations)
    assert all(c.source.startswith("IRS Pub. 519") for c in result.citations)
    assert result.inputs["section_6013_election"] is True
    dumped = result.model_dump()
    assert dumped["classification"] == "resident"
    assert dumped["classification_without_election"] == "nonresident"


def test_p018_election_leaves_no_dual_status_flag():
    # A mid-year first arrival is a dual-status candidate without the election; under it
    # the couple are residents for the ENTIRE year — no split (Pub 519 ch. 1 Caution).
    without = classify([period("H-1B", date(2024, 3, 15))], {2024: 250}, 2024)
    assert without.classification == "dual_status_candidate"
    result = classify([period("H-1B", date(2024, 3, 15))], {2024: 250}, 2024, section_6013_election=True)
    assert result.classification == "resident"
    assert result.classification_without_election == "dual_status_candidate"
    assert "no dual-status split" in result.reasons[0]
    assert "dual-status taxpayers in chapter 6 do not apply to you" in result.reasons[0]


def test_p018_election_with_no_facts_is_resident_with_no_day_count_answer():
    result = classify([], {}, 2024, section_6013_election=True)
    assert result.classification == "resident"
    assert result.section_6013_election is True
    assert result.classification_without_election is None
    assert any("classification_without_election is None" in r for r in result.reasons)
    # Control: the same empty facts without the election are the usual nonresident default.
    assert classify([], {}, 2024).classification == "nonresident"


def test_p018_election_on_a_green_card_holder_keeps_resident_as_the_day_count_answer():
    result = classify([], {2024: 200}, 2024, is_lawful_permanent_resident=True, section_6013_election=True)
    assert result.classification == "resident"
    assert result.classification_without_election == "resident"


def test_p018_the_6013g_and_6013h_choices_are_two_texts():
    # Pub 519 (2025) ch. 1 has two choices: Nonresident Spouse Treated as a Resident
    # (IRC 6013(g) — a nonresident spouse at year end; "you and your spouse can file joint
    # or separate returns in later years") and Choosing Resident Alien Status (IRC 6013(h)
    # — the dual-status year; "Neither you nor your spouse can make this choice for any
    # later tax year"). Pub 501: "You can only make this choice for 1 year".
    assert section_6013_kind("nonresident", "us") == "g"
    assert section_6013_kind("resident", "nonresident") == "g"
    assert section_6013_kind("dual_status_candidate", "nonresident") == "g"   # RA at end + NRA spouse at end
    assert section_6013_kind("nonresident", "nonresident") == "g"             # (its precondition fails)
    assert section_6013_kind("dual_status_candidate", "us") == "h"
    assert section_6013_kind("us", "dual_status_candidate") == "h"
    assert section_6013_kind("dual_status_candidate", "dual_status_candidate") == "h"
    assert section_6013_kind("us", None) == "either"
    g_effect, g_pre, g_stmt = section_6013_texts("g")
    h_effect, h_pre, h_stmt = section_6013_texts("h")
    assert "can file joint or separate returns in later years" in g_effect
    assert "only make this choice for 1 year" in h_effect and "later years" not in h_effect
    assert "IRC 6013(g)(3)" in g_pre                               # the continuing election's own test
    assert "You were a nonresident alien at the beginning of the year." in h_pre
    assert "on the last day of your tax year" in g_stmt and "you both qualify to make the choice" in h_stmt
    either = " ".join(section_6013_texts("either"))
    assert "IRC 6013(g) choice" in either and "IRC 6013(h) choice instead" in either


def test_p018_the_residency_tool_quotes_the_choice_its_answer_points_to():
    # A full-year nonresident is the 6013(g) spouse; a dual-status arrival year could be
    # either (the spouse's facts decide), so both are quoted conditionally.
    full_year = classify(SAMPLE_F1, _SAMPLE_F1_DAYS, 2022, section_6013_election=True)
    assert "IRC 6013(g)" in full_year.reasons[0] and "IRC 6013(h) choice instead" not in full_year.reasons[0]
    arrival = classify([period("H-1B", "2025-06-02")], {2023: 0, 2024: 0, 2025: 213}, 2025,
                       section_6013_election=True)
    assert arrival.classification_without_election == "dual_status_candidate"
    assert "IRC 6013(h) choice instead" in arrival.reasons[0]


def test_p018_the_quoted_texts_carry_the_conditions_the_law_attaches():
    # Second verify round (2026-09-26), texts read this session:
    # IRC 3121(b)(19) excludes only service "performed to carry out the purpose specified in
    # subparagraph (F), (J), (M), or (Q)"; Pub 519's Note on the 6013(h) choice: "If you
    # previously made that choice and it is still in effect, you do not need to make the
    # choice explained here"; IRC 6013(g)(3) and Pub 519 Suspending the Choice, worded on
    # the recorded facts (the prior-year return is prior_filings.return_forms, JF5b).
    from taxfill_core import residency as r

    assert "which is performed to carry out the purpose specified in subparagraph (F), (J), (M), or (Q)" in (
        r.SECTION_6013_FICA)
    h_effect, _, h_stmt = section_6013_texts("h")
    for text in (h_effect, h_stmt):
        assert "If you previously made that choice and it is still in effect" in text
    assert section_6013_kind("dual_status_candidate", "us", recorded=True) == "either"
    assert section_6013_kind("nonresident", "us", recorded=True) == "g"
    assert ("any such election shall not apply for any taxable year if neither spouse is a citizen or resident of "
            "the United States at any time during such year") in r.SECTION_6013_SUSPENDED
    # JF5b: worded on the facts recorded, and it names where the prior-year return is recorded.
    assert "on facts not recorded here" in r.SECTION_6013_SUSPENDED
    assert "prior_filings.return_forms" in r.SECTION_6013_SUSPENDED
    assert "Generally, you cannot file as married filing jointly if either spouse" in r.SECTION_6013_NO_JOINT


# ---------------------------------------------------------------------------
# P-018 / JF5b part 1: the prior-year residency fact. Treas. Reg. 301.7701(b)-4(e)(1):
# "An alien individual who was a United States resident during any part of the preceding
# calendar year and who is a United States resident for any part of the current year will
# be considered to be taxable as a resident at the beginning of the current year." IRC
# 7701(b)(2)(A)(i) splits a year only for an alien who "was not a resident of the United
# States at any time during the preceding calendar year"; IRC 7701(b)(1)(A): a resident
# "if (and only if)" a test is met. Hypothetical timelines only.
# ---------------------------------------------------------------------------

# A TRUNCATED F-1 history: declared from 2021 (the real start could be earlier), H-1B from
# Oct 1 2025 — the timeline makes 2021-2024 exempt years and 2025 partly exempt.
_TRUNCATED_F1 = [period("F-1", "2021-08-20", "2025-09-30"), period("H-1B", "2025-10-01")]
_TRUNCATED_DAYS = {2025: 365, 2024: 365, 2023: 365, 2022: 365, 2021: 130}
# The same filer switching on Apr 1: the SPT is met on the non-exempt part of 2025.
_SWITCH_APRIL = [period("F-1", "2021-08-20", "2025-03-31"), period("H-1B", "2025-04-01")]


def test_p018_truncated_f1_with_a_prior_1040_is_a_contradiction_never_definitive():
    from taxfill_core.residency import CONTRADICTION_PREFIX, prior_year_contradiction

    today = classify(_TRUNCATED_F1, _TRUNCATED_DAYS, 2025)
    assert today.classification == "nonresident"
    assert any("This nonresident answer is definitive" in r for r in today.reasons)   # the defect's shape
    result = classify(_TRUNCATED_F1, _TRUNCATED_DAYS, 2025, prior_year_resident=True)
    assert result.classification == "nonresident"          # IRC 7701(b)(1)(A): "if (and only if)"
    first = result.reasons[0]
    assert first.startswith(CONTRADICTION_PREFIX) and prior_year_contradiction(result) == first
    assert "a judgment about whether the recorded facts are complete" in first and "NOT definitive" in first
    # The three readings and what to record.
    assert "(1) the visa timeline or day counts are incomplete" in first
    assert "For any calendar year after the 5th calendar year for which an individual was an exempt individual" in first
    assert "(2) the 2024 return was filed on the wrong form" in first
    assert "(3) you genuinely left the United States or became an exempt individual again" in first
    assert "the full visa timeline from your FIRST U.S. entry" in first and "prior_filings.return_forms" in first
    # The cross-check names the exact conflict: the timeline makes 2024 a fully exempt year.
    assert "makes 2024 itself a FULLY exempt-individual year" in first
    # No reason calls it definitive, and the First-Year Choice pointer is gone (7701(b)(4)(A)(ii)).
    assert not any("is definitive" in r for r in result.reasons)
    assert not any("An election still can" in r or "may still allow" in r for r in result.reasons)
    assert any("First-Year Choice is closed (IRC 7701(b)(4)(A)(ii)); under reading (2)" in r for r in result.reasons)
    assert result.prior_year_resident is True and result.inputs["prior_year_resident"] is True


def test_p018_a_prior_year_resident_meeting_the_spt_is_resident_from_january_1():
    split = classify(_SWITCH_APRIL, _TRUNCATED_DAYS, 2025)
    assert split.classification == "dual_status_candidate"
    result = classify(_SWITCH_APRIL, _TRUNCATED_DAYS, 2025, prior_year_resident=True)
    assert result.classification == "resident"
    carried = next(r for r in result.reasons if r.startswith("Resident from January 1 of 2025"))
    assert ("An alien individual who was a United States resident during any part of the preceding calendar year "
            "and who is a United States resident for any part of the current year will be considered to be taxable "
            "as a resident at the beginning of the current year.") in carried
    assert "you will be considered a U.S. resident at the beginning of the current year" in carried   # Pub 519
    assert "no arrival split in 2025" in carried and "no nonresident part" not in carried
    # The arrival triggers and the First-Year Choice pointer are suppressed.
    assert not any("is a nonresident period" in r for r in result.reasons)
    assert not any("may still allow electing residency" in r for r in result.reasons)
    assert "First-Year Choice is not open to a prior-year resident" in carried
    assert not any("split year" in r.lower() and "flag, not a determination" in r for r in result.reasons)


def test_p018_a_prior_year_resident_arriving_mid_year_is_not_dual_status():
    arrival = [period("H-1B", date(2024, 3, 15))]
    assert classify(arrival, {2024: 250}, 2024).classification == "dual_status_candidate"
    assert classify(arrival, {2024: 250}, 2024, prior_year_resident=True).classification == "resident"


def test_p018_false_and_unknown_keep_todays_answers():
    for periods, expected in ((_TRUNCATED_F1, "nonresident"), (_SWITCH_APRIL, "dual_status_candidate")):
        base = classify(periods, _TRUNCATED_DAYS, 2025)
        for fact in (None, False):
            result = classify(periods, _TRUNCATED_DAYS, 2025, prior_year_resident=fact)
            assert result.classification == base.classification == expected
            assert result.spt == base.spt and result.nonresident_may_flip == base.nonresident_may_flip
            assert not any(r.startswith("CONTRADICTION") for r in result.reasons)
    unknown = classify(_SWITCH_APRIL, _TRUNCATED_DAYS, 2025)
    assert unknown.reasons == classify(_SWITCH_APRIL, _TRUNCATED_DAYS, 2025, prior_year_resident=None).reasons
    assert unknown.prior_year_resident is None and unknown.inputs["prior_year_resident"] is None
    denied = classify(_SWITCH_APRIL, _TRUNCATED_DAYS, 2025, prior_year_resident=False)
    assert any("partial-year rule of IRC 7701(b)(2)(A)(i) applies" in r for r in denied.reasons)


def test_p018_a_prior_year_resident_keeps_the_departure_note():
    leaving = [period("H-1B", date(2022, 1, 1), date(2025, 8, 31))]
    result = classify(leaving, {2025: 243, 2024: 366, 2023: 365}, 2025, prior_year_resident=True)
    assert result.classification == "resident"
    assert any("Your last declared status period ends 2025-08-31" in r for r in result.reasons)


def test_p018_the_contradiction_goes_ahead_of_may_be_wrong():
    from taxfill_core.residency import MAY_FLIP_PREFIX, may_flip_reason

    periods = [period("H-1B", date(2023, 1, 1))]
    result = classify(periods, {2025: 120}, 2025, prior_year_resident=True)
    assert result.classification == "nonresident" and result.nonresident_may_flip is True
    assert result.reasons[0].startswith("CONTRADICTION") and result.reasons[1].startswith(MAY_FLIP_PREFIX)
    assert may_flip_reason(result) == result.reasons[1]
    assert may_flip_reason(classify(periods, {2025: 120, 2024: 0, 2023: 0}, 2025)) is None


def test_p018_the_contradiction_names_a_prior_year_the_facts_classify_nonresident():
    periods = [period("H-1B", date(2023, 6, 1))]
    result = classify(periods, {2025: 100, 2024: 20, 2023: 20}, 2025, prior_year_resident=True)
    assert "classify 2024 itself as a NONRESIDENT year" in result.reasons[0]


def test_p018_a_prior_year_resident_is_never_a_certain_nonresident():
    from taxfill_core.residency import certain_nonresident

    assert certain_nonresident(_TRUNCATED_F1, _TRUNCATED_DAYS, 2025) is True
    assert certain_nonresident(_TRUNCATED_F1, _TRUNCATED_DAYS, 2025, prior_year_resident=False) is True
    assert certain_nonresident(_TRUNCATED_F1, _TRUNCATED_DAYS, 2025, prior_year_resident=True) is False


def test_p018_the_return_forms_map_only_the_preceding_year():
    from taxfill_core.residency import PRIOR_RETURN_RESIDENT, prior_year_resident_from_return_forms as read
    from taxfill_core.schemas.profile import Answer, Provenance

    assert PRIOR_RETURN_RESIDENT == {
        "1040": True, "dual_status": True, "1040-NR": False, "not_filed": None, "1040_with_6013_election": None,
    }
    for form, expected in PRIOR_RETURN_RESIDENT.items():
        assert read({2024: form}, 2025) is expected
        assert read({2024: Answer(value=form, provenance=Provenance.user_stated())}, 2025) is expected
        assert read({"2024": form}, 2025) is expected                       # JSON string keys
    assert read({2023: "1040"}, 2025) is None                               # only target_year - 1
    assert read({2025: "1040"}, 2025) is None
    assert read({}, 2025) is None and read(None, 2025) is None


def test_p018_the_prior_year_fact_rejects_a_non_boolean():
    with pytest.raises(ValueError, match="prior_year_resident must be true, false or null"):
        classify(_TRUNCATED_F1, _TRUNCATED_DAYS, 2025, prior_year_resident="yes")


def test_p018_a_green_card_holder_who_was_a_prior_year_resident_has_no_dual_status_first_year():
    result = classify([], {2025: 200}, 2025, is_lawful_permanent_resident=True, prior_year_resident=True)
    assert result.classification == "resident"
    assert any("resident year from January 1 — no dual-status first year" in r for r in result.reasons)


def test_p018_the_election_keeps_the_prior_year_answer_as_its_day_count_answer():
    result = classify(_SWITCH_APRIL, _TRUNCATED_DAYS, 2025, section_6013_election=True, prior_year_resident=True)
    assert result.classification == "resident" and result.classification_without_election == "resident"
    contra = classify(_TRUNCATED_F1, _TRUNCATED_DAYS, 2025, section_6013_election=True, prior_year_resident=True)
    assert contra.classification_without_election == "nonresident"
    assert any(r.startswith("CONTRADICTION") for r in contra.reasons)


def test_p018_the_election_year_reason_is_a_labeled_judgment():
    from taxfill_core.residency import prior_year_election_reason

    text = prior_year_election_reason(2025)
    assert "It is NOT read here as residency in 2024 — a judgment" in text
    assert "for purposes of chapter 1 for all of such taxable year" in text
    assert "if (and only if)" in text
    assert "record the days in the U.S. for 2024, 2023 and 2022" in text


def test_p018_the_prior_year_check_fires_only_when_the_timeline_cannot_support_the_prior_1040():
    from taxfill_core.residency import prior_year_check  # noqa: PLC0415
    flagged = classify(_SWITCH_APRIL, _TRUNCATED_DAYS, 2025, prior_year_resident=True)
    assert flagged.classification == "resident"
    assert flagged.reasons[0].startswith("CHECK THE PRIOR-YEAR RETURN") and prior_year_check(flagged) == flagged.reasons[0]
    full = [period("F-1", "2019-08-20", "2025-03-31"), period("H-1B", "2025-04-01")]
    days = {**_TRUNCATED_DAYS, 2021: 365, 2020: 366, 2019: 130}
    assert prior_year_check(classify(full, days, 2025, prior_year_resident=True)) is None


def test_p018_a_recorded_1040nr_is_worded_as_the_recorded_fact():
    result = classify(_SWITCH_APRIL, _TRUNCATED_DAYS, 2025, prior_year_resident=False)
    text = " ".join(result.reasons)
    assert "Your 2024 return is recorded as Form 1040-NR" in text and "if 2024 was in fact not a resident year" in text


def test_p018_a_first_year_choice_prior_year_is_never_checked_as_a_conflict():
    # IRC 7701(b)(4): an F-1 student who became H-1B on 2024-10-01 could make the First-Year Choice
    # for 2024, so a dual-status 2024 return is lawful — no CHECK, and no false "NONRESIDENT year".
    from taxfill_core.residency import prior_year_check, prior_year_contradiction  # noqa: PLC0415
    periods = [period("F-1", "2021-08-20", "2024-09-30"), period("H-1B", "2024-10-01")]
    days = {2025: 365, 2024: 366, 2023: 365, 2022: 365, 2021: 130}
    result = classify(periods, days, 2025, prior_year_resident=True)
    assert result.classification == "resident"
    assert prior_year_check(result) is None and prior_year_contradiction(result) is None
    # No arrival split in the target year: the prior-year fact changes nothing, so no CHECK either.
    h1b = [period("H-1B", "2022-01-01")]
    plain = classify(h1b, {2025: 365}, 2025, prior_year_resident=True)
    assert prior_year_check(plain) is None
    # A missing year-1 count never produces a claimed "NONRESIDENT year" conflict.
    thin = classify(h1b, {2025: 100}, 2025, prior_year_resident=True)
    assert not any("classify 2024 itself as a NONRESIDENT year" in r for r in thin.reasons)


def test_p018_section_6013_kind_reads_a_prior_year_election_return():
    # JF5b part 3b: a prior-year joint Form 1040 under the election makes the choice IRC 6013(g) —
    # IRC 6013(g)(3): it applies "to all subsequent taxable years until terminated"; IRC 6013(h)(2):
    # "such 2 individuals shall be ineligible to make an election under this subsection for any
    # subsequent taxable year" — never a new 6013(h) and never 'either'.
    from taxfill_core.residency import prior_year_election_continues  # noqa: PLC0415

    assert section_6013_kind("dual_status_candidate", "us") == "h"
    assert section_6013_kind("dual_status_candidate", "us", recorded=True) == "either"
    for recorded in (True, False):
        assert section_6013_kind("dual_status_candidate", "us", recorded=recorded, prior_year_election=True) == "g"
        assert section_6013_kind("resident", "us", recorded=recorded, prior_year_election=True) == "g"
    assert section_6013_kind("nonresident", "us", prior_year_election=True) == "g"
    text = prior_year_election_continues(2025)
    assert text.startswith("Your 2024 return is recorded as a joint Form 1040 under the §6013(g)/(h) election")
    assert "no election is recorded for 2025 — so this is NOT applied here" in text
    assert "shall apply to the taxable year for which made and to all subsequent taxable years until terminated" in text
    assert "You can only make this choice for 1 year, and it doesn't apply to any future years." in text
