"""Golden tests for the deterministic tax-math engine (calc.py, M1).

All fixtures are synthetic or transcribed from PUBLISHED official IRS
documents; no real taxpayer data. Tests run fully offline: the documents
below were fetched and transcribed at development time, and the published
values are hardcoded here as golden fixtures.

Sources (verified against the official PDFs):

* 2023 Tax Table & Tax Computation Worksheet:
  https://www.irs.gov/pub/irs-prior/i1040tt--2023.pdf
  ("1040 and 1040-SR TAX AND EARNED INCOME CREDIT TABLES", Cat. No. 24327A)
* 2023 rate schedules & standard deduction: Rev. Proc. 2022-38,
  https://www.irs.gov/pub/irs-drop/rp-22-38.pdf (Sections 3.01 and 3.15)
* 2023 Schedule SE: https://www.irs.gov/pub/irs-prior/f1040sse--2023.pdf
* 2023 Schedule 8812 (CTC/ODC/ACTC) and its instructions:
  https://www.irs.gov/pub/irs-prior/f1040s8--2023.pdf; 2021 ARPA rules from
  the 2021 Schedule 8812 instructions (i1040s8--2021.pdf)
* EITC parameters: Rev. Proc. 2022-38 Section 3.06 (2023) and the per-year
  Rev. Procs. cited in knowledge/federal/<year>.yaml (2021 as amended by
  ARPA: Rev. Proc. 2021-23 Section 4)

Rule from docs/DEV_PLAN.md section 10: if the implementation disagrees with
ANY published row below, the implementation is wrong — fix it, never the
fixture.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from taxfill_core.calc import (
    additional_medicare_tax,
    child_tax_credit,
    dependent_care_credit,
    education_credits,
    eitc,
    excess_ss,
    irs_round,
    niit,
    presence_days,
    presence_days_by_year,
    ptc_annual,
    ptc_monthly,
    se_tax,
    standard_deduction,
    state_tax,
    student_loan_interest_deduction,
    tax_from_taxable_income,
    tax_with_preferential_rates,
    taxable_social_security,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"

TAX_TABLE_URL = "https://www.irs.gov/pub/irs-prior/i1040tt--2023.pdf"


# ---------------------------------------------------------------------------
# Tax Table golden rows (published values, all four statuses)
# ---------------------------------------------------------------------------

# Rows transcribed verbatim from the official 2023 Tax Table PDF
# (https://www.irs.gov/pub/irs-prior/i1040tt--2023.pdf). Tuple layout:
#   (at_least, but_less_than, single, mfj, mfs, hoh)
# i.e. "row: at least X but less than Y" with the four published
# 'Your tax is' columns. Comments give the booklet page the row appears on.
GOLDEN_ROWS = [
    # --- page 3: the published bottom-row structure ---
    (0, 5, 0, 0, 0, 0),
    (5, 15, 1, 1, 1, 1),
    (15, 25, 2, 2, 2, 2),
    (25, 50, 4, 4, 4, 4),  # first $25-wide row; midpoint 37.50 -> 3.75 -> 4
    (50, 75, 6, 6, 6, 6),  # midpoint 62.50 -> 6.25 -> 6 (nearest, NOT ceil)
    (975, 1000, 99, 99, 99, 99),
    (2975, 3000, 299, 299, 299, 299),  # last $25-wide row
    # --- page 4: $50-wide rows start at 3,000 ---
    (3000, 3050, 303, 303, 303, 303),  # midpoint 3,025 -> 302.50 -> 303 (half rounds UP)
    (11950, 12000, 1217, 1198, 1217, 1198),
    # --- page 5: HoH crosses 10% -> 12% at 15,700 ---
    (15700, 15750, 1667, 1573, 1667, 1573),
    # --- page 3 sample table: "find the $25,300-25,350 income line ...
    #     married filing jointly ... $2,599" (the booklet's worked example) ---
    (25300, 25350, 2819, 2599, 2819, 2725),
    # --- page 10 ---
    (57000, 57050, 7853, 6403, 7853, 6529),
    (60000, 60050, 8513, 6763, 8513, 6907),  # HoH: 6,868 + 22% x 175 = 6,906.50 -> 6,907
    # --- page 14: near the $100,000 table ceiling ---
    (95000, 95050, 16213, 11521, 16213, 14607),  # MFJ: 10,294 + 22% x 5,575 = 11,520.50 -> 11,521
    (97000, 97050, 16686, 11961, 16686, 15080),
    (99950, 100000, 17394, 12610, 17394, 15788),  # the table's last row
]

STATUS_COLUMN = {
    "single": 2,
    "married_filing_jointly": 3,
    "married_filing_separately": 4,
    "head_of_household": 5,
}


def _row_id(row):
    return f"{row[0]}-{row[1]}"


@pytest.mark.parametrize("status", list(STATUS_COLUMN))
@pytest.mark.parametrize("row", GOLDEN_ROWS, ids=_row_id)
def test_golden_tax_table_rows(row, status):
    expected = row[STATUS_COLUMN[status]]
    result = tax_from_taxable_income(row[0], status, year=2023, knowledge_dir=KNOWLEDGE_DIR)
    assert result.tax == expected
    assert result.method == "tax_table"
    assert result.citation.url == TAX_TABLE_URL
    assert result.inputs["table_row"] == {"at_least": row[0], "but_less_than": row[1]}


@pytest.mark.parametrize("status", list(STATUS_COLUMN))
@pytest.mark.parametrize("row", GOLDEN_ROWS, ids=_row_id)
def test_golden_rows_hold_across_the_whole_row(row, status):
    # The published tax applies to EVERY income in [at_least, but_less_than):
    # probe just below the row's exclusive upper bound.
    expected = row[STATUS_COLUMN[status]]
    just_below_upper = Decimal(row[1]) - Decimal("0.01")
    result = tax_from_taxable_income(just_below_upper, status, year=2023, knowledge_dir=KNOWLEDGE_DIR)
    assert result.tax == expected
    assert result.inputs["table_row"] == {"at_least": row[0], "but_less_than": row[1]}


def test_booklet_worked_example_verbatim():
    # Tax Table page 3: "Their taxable income on Form 1040, line 15, is
    # $25,300. First, they find the $25,300-25,350 taxable income line ...
    # married filing jointly ... $2,599."
    result = tax_from_taxable_income(25300, "married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert result.tax == 2599
    assert result.method == "tax_table"
    assert "25,300" in result.work and "25,350" in result.work


def test_qualifying_surviving_spouse_uses_mfj_column():
    # Footnote on the published MFJ column: "* This column must also be used
    # by a qualifying surviving spouse."
    qss = tax_from_taxable_income(25300, "qualifying_surviving_spouse", knowledge_dir=KNOWLEDGE_DIR)
    assert qss.tax == 2599
    assert "married-filing-jointly column" in qss.work


def test_work_shows_bracket_math_and_rounding():
    result = tax_from_taxable_income(60000, "head_of_household", knowledge_dir=KNOWLEDGE_DIR)
    # HoH row 60,000-60,050: schedule at midpoint 60,025 =
    # 6,868 + 22% x (60,025 - 59,850) = 6,906.50 -> 6,907.
    assert result.exact_tax == Decimal("6906.50")
    assert result.tax == 6907
    assert "$60,025.00" in result.work  # the midpoint
    assert "22% x" in result.work  # the bracket rate
    assert "$6,907" in result.work  # the rounded result


def test_tax_table_scope_caveat_is_documented():
    # Regression (scope overstatement): docs used to call the Tax Table
    # "mandatory below $100,000" without qualification. The booklet's own
    # line 16 caution ("See the instructions for line 16 to see if you must
    # use the Tax Table below to figure your tax") exists because qualified
    # dividends / capital gains, Schedule D worksheet, Form 8615, and FEIE
    # situations compute line 16 from a DIFFERENT worksheet even below
    # $100,000. Both the engine docstring and the knowledge pack must carry
    # the caveat so an agent never applies tax_from_taxable_income to
    # preferential-rate income.
    doc = (tax_from_taxable_income.__doc__ or "").lower()
    assert "qualified dividends" in doc
    assert "out of scope" in doc
    assert "even below $100,000" in doc
    pack_text = (KNOWLEDGE_DIR / "federal" / "2023.yaml").read_text(encoding="utf-8").lower()
    assert "qualified dividends" in pack_text
    assert "out of scope" in pack_text


# ---------------------------------------------------------------------------
# The $100,000 boundary and the schedule (Tax Computation Worksheet) region
# ---------------------------------------------------------------------------


def test_just_below_100k_uses_tax_table():
    result = tax_from_taxable_income(Decimal("99999.99"), "single", knowledge_dir=KNOWLEDGE_DIR)
    assert result.method == "tax_table"
    assert result.tax == 17394  # published row 99,950-100,000


def test_exactly_100k_uses_schedule():
    # Tax Table page 14: "$100,000 or over — use the Tax Computation
    # Worksheet". Single at exactly 100,000:
    #   16,290 + 24% x (100,000 - 95,375) = 16,290 + 1,110 = 17,400
    # Worksheet check: 0.24 x 100,000 - 6,600.00 = 17,400.
    result = tax_from_taxable_income(100000, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert result.method == "schedule"
    assert result.tax == 17400
    assert result.citation.url == "https://www.irs.gov/pub/irs-drop/rp-22-38.pdf"


@pytest.mark.parametrize(
    ("status", "income", "expected"),
    [
        # Hand-derived from Rev. Proc. 2022-38 Section 3.01 bracket math; each
        # cross-checked against the 2023 Tax Computation Worksheet (b)x-(d) form.
        # MFJ 100,000: 10,294 + 22% x (100,000 - 89,450) = 12,615
        #   (worksheet: 0.22 x 100,000 - 9,385.00 = 12,615)
        ("married_filing_jointly", 100000, 12615),
        # HoH 100,000: 14,678 + 24% x (100,000 - 95,350) = 15,794
        #   (worksheet: 0.24 x 100,000 - 8,206.00 = 15,794)
        ("head_of_household", 100000, 15794),
        # MFS 100,000: same schedule as single below 231,250 -> 17,400
        ("married_filing_separately", 100000, 17400),
        # Single 250,000: 52,832 + 35% x (250,000 - 231,250) = 59,394.50 -> 59,395
        #   (worksheet: 0.35 x 250,000 - 28,105.50 = 59,394.50; 50 cents rounds UP)
        ("single", 250000, 59395),
        # Single 600,000: 174,238.25 + 37% x (600,000 - 578,125) = 182,332.00
        ("single", 600000, 182332),
        # MFJ 1,000,000: 186,601.50 + 37% x (1,000,000 - 693,750) = 299,914.00
        ("married_filing_jointly", 1000000, 299914),
        # Published bracket bases from Rev. Proc. 2022-38 land exactly at the
        # bracket tops ("$B plus R% of the excess over $O" with zero excess
        # evaluated from the bracket BELOW the boundary):
        # MFJ 190,750 -> $32,580 (Table 1); 364,200 -> $74,208; 462,500 -> $105,664
        ("married_filing_jointly", 190750, 32580),
        ("married_filing_jointly", 364200, 74208),
        ("married_filing_jointly", 462500, 105664),
        # MFJ 693,750 -> $186,601.50 rounds to 186,602 (50 cents UP)
        ("married_filing_jointly", 693750, 186602),
        # Single 578,125 -> $174,238.25 rounds DOWN to 174,238 (under 50 cents)
        ("single", 578125, 174238),
        # MFS 346,875 -> $93,300.75 rounds UP to 93,301
        ("married_filing_separately", 346875, 93301),
        # HoH 578,100 -> $172,623.50 rounds UP to 172,624
        ("head_of_household", 578100, 172624),
    ],
)
def test_schedule_region_hand_derived(status, income, expected):
    result = tax_from_taxable_income(income, status, knowledge_dir=KNOWLEDGE_DIR)
    assert result.method == "schedule"
    assert result.tax == expected


def test_schedule_exact_tax_keeps_cents():
    result = tax_from_taxable_income(250000, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert result.exact_tax == Decimal("59394.50")
    assert "$59,394.50" in result.work


# ---------------------------------------------------------------------------
# tax_from_taxable_income input validation
# ---------------------------------------------------------------------------


def test_zero_income_is_the_zero_row():
    result = tax_from_taxable_income(0, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert result.tax == 0
    assert result.method == "tax_table"


def test_negative_income_rejected_prescriptively():
    with pytest.raises(ValueError, match=r"cannot be negative.*pass 0"):
        tax_from_taxable_income(-1, "single", knowledge_dir=KNOWLEDGE_DIR)


def test_unknown_filing_status_lists_the_valid_ones():
    with pytest.raises(ValueError, match=r"unknown filing_status.*qualifying_surviving_spouse"):
        tax_from_taxable_income(50000, "married", knowledge_dir=KNOWLEDGE_DIR)


def test_unshipped_year_names_path_and_protocol():
    with pytest.raises(FileNotFoundError, match=r"2099\.yaml.*freshness protocol"):
        tax_from_taxable_income(50000, "single", year=2099, knowledge_dir=KNOWLEDGE_DIR)


def test_string_and_float_money_inputs_accepted():
    assert tax_from_taxable_income("25,300", "single", knowledge_dir=KNOWLEDGE_DIR).tax == 2819
    assert tax_from_taxable_income(25300.0, "single", knowledge_dir=KNOWLEDGE_DIR).tax == 2819


def test_default_knowledge_dir_resolves_source_checkout():
    assert tax_from_taxable_income(25300, "single").tax == 2819


# ---------------------------------------------------------------------------
# irs_round
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, 0),
        (0.49, 0),  # under 50 cents drops
        (0.50, 1),  # exactly 50 cents rounds UP
        (1.49, 1),
        (1.50, 2),
        (2.50, 3),  # NOT banker's rounding (banker's would give 2)
        (Decimal("6.25"), 6),
        (Decimal("302.50"), 303),
        ("1,234.50", 1235),
        ("$2.50", 3),
        (17400, 17400),
        (-1.49, -1),
        (-1.50, -2),  # magnitude rounds up for negatives too
    ],
)
def test_irs_round(amount, expected):
    assert irs_round(amount) == expected


def test_irs_round_rejects_nan_and_garbage():
    with pytest.raises(ValueError, match="finite"):
        irs_round(float("nan"))
    with pytest.raises(ValueError, match="not a number"):
        irs_round("twelve dollars")
    with pytest.raises(TypeError):
        irs_round(None)


# ---------------------------------------------------------------------------
# Standard deduction (Rev. Proc. 2022-38, Section 3.15)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("single", 13850),
        ("married_filing_jointly", 27700),
        ("married_filing_separately", 13850),
        ("head_of_household", 20800),
        ("qualifying_surviving_spouse", 27700),  # uses the MFJ amount
    ],
)
def test_standard_deduction_base_amounts(status, expected):
    result = standard_deduction(status, knowledge_dir=KNOWLEDGE_DIR)
    assert result.amount == expected
    assert "2022-38" in result.citation.source


@pytest.mark.parametrize(
    ("status", "age_65_plus", "blind", "expected"),
    [
        # Unmarried, not a surviving spouse: $1,850 per condition.
        ("single", 1, 0, 13850 + 1850),
        ("single", 1, 1, 13850 + 2 * 1850),
        ("head_of_household", 0, 1, 20800 + 1850),
        # Married (and surviving spouse): $1,500 per condition per person.
        ("married_filing_jointly", 2, 1, 27700 + 3 * 1500),
        ("married_filing_jointly", 2, 2, 27700 + 4 * 1500),
        ("married_filing_separately", 1, 0, 13850 + 1500),
        ("qualifying_surviving_spouse", 1, 0, 27700 + 1500),
    ],
)
def test_standard_deduction_aged_blind_additions(status, age_65_plus, blind, expected):
    result = standard_deduction(status, age_65_plus=age_65_plus, blind=blind, knowledge_dir=KNOWLEDGE_DIR)
    assert result.amount == expected
    assert result.inputs["age_65_plus"] == age_65_plus
    assert result.work  # derivation present


def test_standard_deduction_count_validation():
    with pytest.raises(ValueError, match="between 0 and 1"):
        standard_deduction("single", age_65_plus=2, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="between 0 and 2"):
        standard_deduction("married_filing_jointly", blind=3, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="between 0 and"):
        standard_deduction("single", blind=-1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(TypeError, match="must be an int"):
        standard_deduction("single", age_65_plus=True, knowledge_dir=KNOWLEDGE_DIR)


def test_standard_deduction_qss_caps_at_one_box_per_condition():
    # Regression: a qualifying surviving spouse files WITHOUT a spouse, so
    # only the taxpayer's own Age/Blindness boxes exist. The published chart
    # (2023 Form 1040 instructions, line 12, 'Standard Deduction Chart for
    # People Who Were Born Before January 2, 1959, or Were Blind', page 34)
    # tops out at 2 boxes total for QSS ($30,700); spouse boxes are reserved
    # for married filing jointly / separately (chart footnote). The engine
    # previously accepted 2 per condition (up to 4 boxes = $33,700, an
    # amount the chart does not allow).
    with pytest.raises(ValueError, match="between 0 and 1"):
        standard_deduction("qualifying_surviving_spouse", age_65_plus=2, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="between 0 and 1"):
        standard_deduction("qualifying_surviving_spouse", blind=2, knowledge_dir=KNOWLEDGE_DIR)


@pytest.mark.parametrize(
    ("status", "age_65_plus", "blind", "chart_amount"),
    [
        # Every maximum-boxes row of the published chart (2023 Form 1040
        # instructions, line 12 chart, page 34) — the chart's printed totals
        # pin both the per-condition addition and the box caps.
        ("single", 1, 1, 17550),
        ("married_filing_jointly", 2, 2, 33700),
        ("qualifying_surviving_spouse", 1, 1, 30700),
        ("married_filing_separately", 2, 2, 19850),
        ("head_of_household", 1, 1, 24500),
    ],
)
def test_standard_deduction_matches_published_chart_maximums(status, age_65_plus, blind, chart_amount):
    result = standard_deduction(status, age_65_plus=age_65_plus, blind=blind, knowledge_dir=KNOWLEDGE_DIR)
    assert result.amount == chart_amount


# ---------------------------------------------------------------------------
# SE tax (2023 Schedule SE, Part I)
# ---------------------------------------------------------------------------

SE_URL = "https://www.irs.gov/pub/irs-prior/f1040sse--2023.pdf"


def test_se_tax_typical_profit():
    # Hand-derived per the Schedule SE line sequence:
    #   4a: 50,000 x 0.9235 = 46,175.00
    #   10: 46,175.00 x 0.124 = 5,725.70
    #   11: 46,175.00 x 0.029 = 1,339.075 -> 1,339.08 (cents, half up)
    #   12: 7,064.78 -> 7,065
    #   13: half of the WHOLE-DOLLAR line 12 (7,065 x 0.50 = 3,532.50) -> 3,533 (half up),
    #       NOT half of the cents-level line 12 — a filer works the form line-by-line.
    result = se_tax(50000, knowledge_dir=KNOWLEDGE_DIR)
    assert result.net_earnings == Decimal("46175.00")
    assert result.ss_portion == Decimal("5725.70")
    assert result.medicare_portion == Decimal("1339.08")
    assert result.se_tax == 7065
    assert result.deduction_half == 3533
    assert result.citation.url == SE_URL
    assert "92.35" in result.work or "0.9235" in result.work


def test_se_tax_above_wage_base_caps_ss_not_medicare():
    # 200,000 x 0.9235 = 184,700.00 net earnings (> 160,200 wage base)
    #   10: 160,200 x 0.124 = 19,864.80 (capped)
    #   11: 184,700 x 0.029 = 5,356.30 (uncapped)
    #   12: 25,221.10 -> 25,221    13: 12,610.55 -> 12,611
    result = se_tax(200000, knowledge_dir=KNOWLEDGE_DIR)
    assert result.net_earnings == Decimal("184700.00")
    assert result.ss_portion == Decimal("19864.80")
    assert result.medicare_portion == Decimal("5356.30")
    assert result.se_tax == 25221
    assert result.deduction_half == 12611
    assert "wage base" in result.work


def test_se_tax_below_threshold_after_factor():
    # The classic gotcha: a $400 profit is BELOW the threshold because the
    # threshold applies to line 4a (400 x 0.9235 = 369.40 < 400).
    result = se_tax(400, knowledge_dir=KNOWLEDGE_DIR)
    assert result.se_tax == 0
    assert result.deduction_half == 0
    assert result.net_earnings == Decimal("369.40")
    assert "$400" in result.work


def test_se_tax_threshold_boundary():
    # 433 x 0.9235 = 399.8755 -> 399.88 < 400: no SE tax.
    assert se_tax(433, knowledge_dir=KNOWLEDGE_DIR).se_tax == 0
    # 434 x 0.9235 = 400.799 -> 400.80 >= 400: SE tax due.
    #   10: 400.80 x 0.124 = 49.6992 -> 49.70
    #   11: 400.80 x 0.029 = 11.6232 -> 11.62
    #   12: 61.32 -> 61    13: 30.66 -> 31
    result = se_tax(434, knowledge_dir=KNOWLEDGE_DIR)
    assert result.net_earnings == Decimal("400.80")
    assert result.se_tax == 61
    assert result.deduction_half == 31


def test_se_tax_zero_and_negative_profit():
    # Line 4a: a zero-or-negative line 3 carries down unchanged (no factor).
    for profit in (0, -500):
        result = se_tax(profit, knowledge_dir=KNOWLEDGE_DIR)
        assert result.se_tax == 0
        assert result.deduction_half == 0
        assert result.net_earnings == Decimal(profit)


# ---------------------------------------------------------------------------
# Presence days (I-94-style ranges)
# ---------------------------------------------------------------------------


def test_presence_inclusive_endpoints():
    # Arrival Jan 1, departure Jan 10: both partial days count -> 10 days.
    assert presence_days([(date(2023, 1, 1), date(2023, 1, 10))]) == 10


def test_presence_same_day_counts_one():
    assert presence_days([(date(2023, 6, 15), date(2023, 6, 15))]) == 1


def test_presence_overlapping_ranges_merge():
    periods = [(date(2023, 1, 1), date(2023, 1, 10)), (date(2023, 1, 5), date(2023, 1, 15))]
    assert presence_days(periods) == 15


def test_presence_duplicate_ranges_count_once():
    periods = [(date(2023, 1, 1), date(2023, 1, 10))] * 3
    assert presence_days(periods) == 10


def test_presence_adjacent_ranges():
    periods = [(date(2023, 1, 1), date(2023, 1, 5)), (date(2023, 1, 6), date(2023, 1, 10))]
    assert presence_days(periods) == 10


def test_presence_accepts_iso_strings_and_datetimes():
    assert presence_days([("2023-01-01", "2023-01-10")]) == 10
    # A timestamped arrival still counts as presence on that day.
    assert presence_days([(datetime(2023, 1, 1, 23, 50), datetime(2023, 1, 2, 0, 10))]) == 2


def test_presence_empty_input():
    assert presence_days([]) == 0
    assert presence_days_by_year([]) == {}


def test_presence_by_year_splits_at_new_year():
    periods = [(date(2022, 12, 20), date(2023, 1, 10))]
    assert presence_days_by_year(periods) == {2022: 12, 2023: 10}
    assert presence_days(periods) == 22


def test_presence_leap_year_february():
    assert presence_days([(date(2024, 2, 1), date(2024, 2, 29))]) == 29


def test_presence_by_year_sums_to_total_with_messy_overlaps():
    periods = [
        ("2021-11-01", "2022-02-15"),
        ("2022-02-10", "2022-03-01"),  # overlaps the first
        ("2022-12-31", "2024-01-01"),  # spans two new years
        ("2023-06-01", "2023-06-01"),  # inside the previous range
    ]
    by_year = presence_days_by_year(periods)
    assert set(by_year) == {2021, 2022, 2023, 2024}
    assert by_year[2021] == 61  # Nov 1 - Dec 31, 2021
    assert by_year[2023] == 365  # all of 2023
    assert by_year[2024] == 1
    assert sum(by_year.values()) == presence_days(periods)


def test_presence_start_after_end_rejected():
    with pytest.raises(ValueError, match="swap"):
        presence_days([(date(2023, 1, 10), date(2023, 1, 1))])


def test_presence_malformed_period_rejected():
    with pytest.raises(ValueError, match=r"\(start_date, end_date\) pair"):
        presence_days([date(2023, 1, 1)])  # not a pair
    with pytest.raises(ValueError, match="ISO format"):
        presence_days([("01/05/2023", "01/10/2023")])  # not ISO
    with pytest.raises(TypeError, match="datetime.date"):
        presence_days([(20230101, 20230110)])


# ---------------------------------------------------------------------------
# Additional Medicare Tax (Form 8959) — thresholds statutory since 2013:
# $250,000 MFJ / $125,000 MFS / $200,000 single, HoH, AND qualifying surviving
# spouse (Topic 560). Hand-derived per the Form 8959 line sequence.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wages", "status", "expected"),
    [
        (300_000, "single", 900),                       # 0.9% x 100,000
        (300_000, "married_filing_jointly", 450),       # 0.9% x 50,000
        (130_000, "married_filing_separately", 45),     # 0.9% x 5,000
        (220_000, "head_of_household", 180),            # 0.9% x 20,000
        (200_000, "single", 0),                         # at the threshold -> no excess
        (50_000, "single", 0),
    ],
)
def test_additional_medicare_wages_only(wages, status, expected):
    result = additional_medicare_tax(wages, status, 2023, knowledge_dir=KNOWLEDGE_DIR)
    assert result.additional_medicare_tax == expected
    assert result.se_portion == Decimal("0.00")
    assert result.citation.url.startswith("https://www.irs.gov/")


def test_additional_medicare_qss_uses_the_200k_bucket_not_mfj():
    # Form 8959 groups qualifying surviving spouse with single/HoH at $200,000 —
    # NOT with MFJ at $250,000 (that grouping belongs to Form 8960). An MFJ alias
    # here would understate the tax by 0.9% x 50,000 = $450.
    qss = additional_medicare_tax(260_000, "qualifying_surviving_spouse", 2023, knowledge_dir=KNOWLEDGE_DIR)
    assert qss.threshold == 200_000
    assert qss.additional_medicare_tax == 540      # 0.9% x 60,000
    mfj = additional_medicare_tax(260_000, "married_filing_jointly", 2023, knowledge_dir=KNOWLEDGE_DIR)
    assert mfj.additional_medicare_tax == 90       # 0.9% x 10,000 — must differ


def test_additional_medicare_se_component_uses_wage_reduced_threshold():
    # Form 8959 Part II: wages 150,000 leave a reduced threshold of 50,000; SE net
    # earnings = 100,000 x 0.9235 = 92,350; excess 42,350 x 0.9% = 381.15 -> 381.
    result = additional_medicare_tax(150_000, "single", 2023, se_net_profit=100_000, knowledge_dir=KNOWLEDGE_DIR)
    assert result.wage_portion == Decimal("0.00")
    assert result.se_portion == Decimal("381.15")
    assert result.additional_medicare_tax == 381


def test_additional_medicare_wages_and_se_both_bite():
    # Wages 250,000 single: Part I = 0.9% x 50,000 = 450.00. Reduced threshold 0;
    # SE net earnings = 50,000 x 0.9235 = 46,175; Part II = 0.9% x 46,175 = 415.575
    # -> 415.58 cents; total 865.58 -> 866.
    result = additional_medicare_tax(250_000, "single", 2023, se_net_profit=50_000, knowledge_dir=KNOWLEDGE_DIR)
    assert result.wage_portion == Decimal("450.00")
    assert result.se_portion == Decimal("415.58")
    assert result.additional_medicare_tax == 866


def test_additional_medicare_se_below_schedule_se_minimum_has_no_se_component():
    # Net earnings 400 x 0.9235 = 369.40 < $400 -> no Schedule SE, no Part II.
    result = additional_medicare_tax(210_000, "single", 2023, se_net_profit=400, knowledge_dir=KNOWLEDGE_DIR)
    assert result.se_portion == Decimal("0.00")
    assert result.additional_medicare_tax == 90    # wages-only: 0.9% x 10,000


def test_additional_medicare_negative_wages_rejected():
    with pytest.raises(ValueError, match="medicare_wages"):
        additional_medicare_tax(-1, "single", 2023, knowledge_dir=KNOWLEDGE_DIR)


def test_additional_medicare_unknown_status_prescriptive():
    with pytest.raises(ValueError, match="unknown filing_status"):
        additional_medicare_tax(300_000, "widowed", 2023, knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Net Investment Income Tax (Form 8960) — 3.8% of the LESSER of net investment
# income or the MAGI excess. MAGI thresholds statutory: $250,000 MFJ AND QSS /
# $125,000 MFS / $200,000 single, HoH (Topic 559).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nii", "magi", "status", "expected"),
    [
        (50_000, 250_000, "single", 1_900),            # excess 50,000; base = min = 50,000
        (30_000, 260_000, "married_filing_jointly", 380),  # excess 10,000 binds
        (20_000, 130_000, "married_filing_separately", 190),  # excess 5,000 binds
        (10_000, 190_000, "single", 0),                # below the MAGI threshold
        (0, 400_000, "single", 0),                     # no investment income
    ],
)
def test_niit_lesser_of_rule(nii, magi, status, expected):
    result = niit(nii, magi, status, 2023, knowledge_dir=KNOWLEDGE_DIR)
    assert result.niit == expected
    assert result.citation.url.startswith("https://www.irs.gov/")


def test_niit_qss_uses_the_mfj_250k_bucket():
    # Form 8960 groups qualifying surviving spouse WITH MFJ at $250,000 — the
    # opposite bucketing from Form 8959. A single/$200,000 alias here would
    # overstate NIIT by 3.8% x 50,000 = $1,900.
    qss = niit(30_000, 260_000, "qualifying_surviving_spouse", 2023, knowledge_dir=KNOWLEDGE_DIR)
    assert qss.threshold == 250_000
    assert qss.niit == 380
    single = niit(30_000, 260_000, "single", 2023, knowledge_dir=KNOWLEDGE_DIR)
    assert single.niit == 1_140                        # excess 60,000 > NII -> base 30,000


def test_niit_investment_loss_is_floored_at_zero():
    assert niit(-5_000, 300_000, "single", 2023, knowledge_dir=KNOWLEDGE_DIR).niit == 0


@pytest.mark.parametrize("year", [2019, 2020, 2021, 2022, 2023, 2024])
def test_surtax_blocks_ship_for_every_supported_year(year):
    # The thresholds are statutory (not indexed) — identical for every year we ship.
    am = additional_medicare_tax(250_000, "single", year, knowledge_dir=KNOWLEDGE_DIR)
    assert am.additional_medicare_tax == 450
    ni = niit(10_000, 210_000, "single", year, knowledge_dir=KNOWLEDGE_DIR)
    assert ni.niit == 380


# ---------------------------------------------------------------------------
# Schedule SE lines 8a-9 — W-2 social security wages consume the wage base first
# ---------------------------------------------------------------------------


def test_se_tax_w2_wages_reduce_the_ss_base():
    # 2023 base $160,200. Wages $140,000 leave $20,200 of base; SE net earnings
    # 40,000 x 0.9235 = 36,940. Line 10 = 12.4% x 20,200 = 2,504.80;
    # line 11 = 2.9% x 36,940 = 1,071.26; line 12 = 3,576.06 -> 3,576;
    # line 13 = 50% x 3,576 = 1,788.
    r = se_tax(40_000, 2023, knowledge_dir=KNOWLEDGE_DIR, w2_ss_wages=140_000)
    assert r.ss_portion == Decimal("2504.80")
    assert r.medicare_portion == Decimal("1071.26")
    assert r.se_tax == 3576
    assert r.deduction_half == 1788
    assert "8a-9" in r.work


def test_se_tax_wages_at_or_over_the_base_zero_the_ss_portion_not_medicare():
    # Wages already at the 2023 base: NO social security portion on the side gig;
    # Medicare (uncapped) still applies. 30,000 x 0.9235 = 27,705;
    # line 11 = 2.9% x 27,705 = 803.445 -> 803.45 -> line 12 rounds to 803.
    r = se_tax(30_000, 2023, knowledge_dir=KNOWLEDGE_DIR, w2_ss_wages=160_200)
    assert r.ss_portion == Decimal("0.00")
    assert r.medicare_portion == Decimal("803.45")
    assert r.se_tax == 803


def test_se_tax_without_wages_unchanged():
    # Golden regression: the no-wages path must be identical to the pre-8a behavior.
    assert se_tax(50_000, knowledge_dir=KNOWLEDGE_DIR).se_tax == 7065
    assert se_tax(50_000, knowledge_dir=KNOWLEDGE_DIR, w2_ss_wages=0).se_tax == 7065


def test_se_tax_negative_w2_wages_rejected():
    with pytest.raises(ValueError, match="w2_ss_wages"):
        se_tax(50_000, knowledge_dir=KNOWLEDGE_DIR, w2_ss_wages=-1)


# ---------------------------------------------------------------------------
# Qualified Dividends and Capital Gain Tax Worksheet (Phase F) — hand-derived
# per the 2023 worksheet lines 1-25 and Rev. Proc. 2022-38 section 3.03
# breakpoints (single: 0% up to 44,625; 15% up to 492,300; 20% above).
# ---------------------------------------------------------------------------


def test_qdcgt_ordinary_income_fills_the_zero_band_first():
    # Single 2023, taxable 60,000 with 10,000 QD -> ordinary part 50,000.
    # The worksheet stacks ordinary income BELOW preferential income:
    #   line 7 = min(60,000, 44,625) = 44,625; line 8 = min(50,000, 44,625) = 44,625
    #   line 9 (0%) = 44,625 - 44,625 = 0  (the 0% band is fully consumed by ordinary income)
    #   line 17 (15%) = 10,000 -> line 18 = 1,500
    #   line 22 = tax(50,000) = table row 50,000-50,050, midpoint 50,025:
    #             5,147 + 22% x 5,300 = 6,313
    #   line 23 = 1,500 + 6,313 = 7,813; line 24 = tax(60,000) = 8,513 (published row)
    #   line 25 = min = 7,813
    r = tax_with_preferential_rates(60_000, 10_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.amount_at_0pct == Decimal("0.00")
    assert r.amount_at_15pct == Decimal("10000.00")
    assert r.amount_at_20pct == Decimal("0.00")
    assert r.tax_on_ordinary_part == 6313
    assert r.all_ordinary_tax == 8513
    assert r.tax == 7813
    assert r.citation.url == "https://www.irs.gov/pub/irs-drop/rp-22-38.pdf"


def test_qdcgt_zero_band_absorbs_all_preferential_income():
    # Single 2023, taxable 40,000 with 10,000 QD -> ordinary part 30,000.
    # Zero-band room above the ordinary part: min(40,000, 44,625) - 30,000 = 10,000 >= QD,
    # so ALL the preferential income is taxed at 0% and the total equals tax(30,000):
    #   tax(30,000) = row 30,000-30,050, midpoint 30,025: 1,100 + 12% x 19,025 = 3,383.
    r = tax_with_preferential_rates(40_000, 10_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.amount_at_0pct == Decimal("10000.00")
    assert r.amount_at_15pct == Decimal("0.00")
    assert r.tax == 3383
    assert r.tax == tax_from_taxable_income(30_000, "single", knowledge_dir=KNOWLEDGE_DIR).tax


def test_qdcgt_short_term_loss_offsets_long_term_gain():
    # Net capital gain = max(0, LT 10,000 + min(ST -4,000, 0)) = 6,000; + QD 2,000 = 8,000
    # preferential. Taxable 50,000 -> ordinary part 42,000.
    #   line 9 (0%) = 44,625 - 42,000 = 2,625
    #   line 17 (15%) = min(8,000 - 2,625, 50,000 - (42,000 + 2,625)) = 5,375 -> 806.25 -> 806
    #   line 22 = tax(42,000) = midpoint 42,025: 1,100 + 12% x 31,025 = 4,823
    #   line 23 = 806 + 4,823 = 5,629 < line 24 = tax(50,000) = 6,313
    r = tax_with_preferential_rates(50_000, 2_000, 10_000, -4_000, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.preferential_income == Decimal("8000.00")
    assert r.amount_at_0pct == Decimal("2625.00")
    assert r.amount_at_15pct == Decimal("5375.00")
    assert r.tax == 5629


def test_qdcgt_long_term_loss_leaves_qd_only():
    # A net LT LOSS offsets nothing preferential (Schedule D line 16 smaller-of, floor 0):
    # preferential = QD only, even with an ST gain (ST gain is ordinary income).
    r = tax_with_preferential_rates(50_000, 5_000, -5_000, 3_000, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.preferential_income == Decimal("5000.00")
    assert r.ordinary_part == Decimal("45000.00")


def test_qdcgt_20_percent_band():
    # Single 2023, taxable 600,000 with 200,000 QD -> ordinary part 400,000.
    #   0% band fully consumed (400,000 > 44,625) -> line 9 = 0
    #   15% band: line 14 = min(600,000, 492,300); line 16 = 492,300 - 400,000 = 92,300
    #     -> line 18 = 13,845
    #   20%: 200,000 - 92,300 = 107,700 -> line 21 = 21,540
    #   line 22 = tax(400,000) = 52,832 + 35% x 168,750 = 111,894.50 -> 111,895
    #   line 23 = 13,845 + 21,540 + 111,895 = 147,280 < line 24 = tax(600,000) = 182,332
    r = tax_with_preferential_rates(600_000, 200_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.amount_at_0pct == Decimal("0.00")
    assert r.amount_at_15pct == Decimal("92300.00")
    assert r.amount_at_20pct == Decimal("107700.00")
    assert r.tax_on_ordinary_part == 111895
    assert r.all_ordinary_tax == 182332
    assert r.tax == 147280


def test_qdcgt_clamps_preferential_to_taxable_income():
    # QD can exceed taxable income (deductions); line 10 clamps: preferential = 30,000,
    # ordinary part 0, all of it inside the 44,625 zero band -> tax 0.
    r = tax_with_preferential_rates(30_000, 50_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.preferential_income == Decimal("30000.00")
    assert r.ordinary_part == Decimal("0.00")
    assert r.tax == 0


@pytest.mark.parametrize(
    ("taxable", "qd", "lt", "st"),
    [
        (60_000, 10_000, 0, 0),
        (40_000, 10_000, 0, 0),
        (50_000, 2_000, 10_000, -4_000),
        (50_000, 5_000, -5_000, 3_000),   # LT loss + ST gain -> QD only
        (50_000, 0, -3_000, 8_000),       # LT loss + ST gain, no QD -> nothing preferential
        (100_000, 0, 20_000, 0),
        (600_000, 200_000, 0, 0),
        (25_000, 25_000, 0, 0),
        (0, 0, 0, 0),
    ],
)
def test_qdcgt_never_exceeds_the_all_ordinary_tax(taxable, qd, lt, st):
    # Worksheet line 25 is the SMALLER of the worksheet tax and the ordinary tax,
    # so the result can never exceed tax_from_taxable_income on the same income.
    r = tax_with_preferential_rates(taxable, qd, lt, st, "single", knowledge_dir=KNOWLEDGE_DIR)
    ordinary = tax_from_taxable_income(taxable, "single", knowledge_dir=KNOWLEDGE_DIR).tax
    assert r.all_ordinary_tax == ordinary
    assert r.tax <= ordinary


def test_qdcgt_qss_uses_the_explicit_qss_breakpoints():
    # capital_gains_brackets carries qualifying_surviving_spouse EXPLICITLY (grouped
    # with MFJ in every Rev. Proc. section 3.03): zero-band up to 89,250 for 2023.
    qss = tax_with_preferential_rates(
        80_000, 20_000, filing_status="qualifying_surviving_spouse", knowledge_dir=KNOWLEDGE_DIR
    )
    # ordinary part 60,000; zero-band room = min(80,000, 89,250) - 60,000 = 20,000 >= QD
    assert qss.amount_at_0pct == Decimal("20000.00")
    assert qss.tax == tax_from_taxable_income(60_000, "qualifying_surviving_spouse", knowledge_dir=KNOWLEDGE_DIR).tax


def test_qdcgt_rejects_negative_qd_and_negative_taxable_income():
    with pytest.raises(ValueError, match="qualified_dividends"):
        tax_with_preferential_rates(50_000, -1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="taxable_income"):
        tax_with_preferential_rates(-1, 0, knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Taxable Social Security benefits (Phase F) — hand-derived per the 2023
# Social Security Benefits Worksheet (statutory IRC 86(c) thresholds).
# ---------------------------------------------------------------------------


def test_taxable_ss_classic_50_85_mix():
    # Single, benefits 20,000, other income 30,000:
    #   line 2 = 10,000; provisional (line 7) = 40,000; base 25,000 -> line 9 = 15,000
    #   line 10 gap = 9,000 -> line 11 = 6,000; line 12 = 9,000; line 13 = 4,500
    #   line 14 = min(10,000, 4,500) = 4,500; line 15 = 85% x 6,000 = 5,100
    #   line 16 = 9,600 < line 17 = 17,000 -> taxable 9,600
    r = taxable_social_security(20_000, 30_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.provisional_income == Decimal("40000.00")
    assert r.base_amount == 25_000
    assert r.adjusted_base_amount == 34_000
    assert r.taxable_benefits == 9_600


def test_taxable_ss_below_the_base_amount_is_zero():
    # Single, benefits 10,000, other 10,000: provisional 15,000 < 25,000 -> nothing taxable.
    r = taxable_social_security(10_000, 10_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.taxable_benefits == 0
    assert "NO benefits are taxable" in r.work


def test_taxable_ss_85_percent_cap_binds_at_high_income():
    # Single, benefits 20,000, other 100,000: provisional 110,000; line 16 = 4,500 + 85% x 76,000
    # = 69,100, capped at line 17 = 85% x 20,000 = 17,000.
    r = taxable_social_security(20_000, 100_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.taxable_benefits == 17_000


def test_taxable_ss_mfj_mid_tier_50_percent_band():
    # MFJ, benefits 12,000, other 30,000: line 2 = 6,000; provisional 36,000; base 32,000
    #   line 9 = 4,000 (within the 12,000 gap) -> line 11 = 0; line 13 = 2,000
    #   line 14 = min(6,000, 2,000) = 2,000; line 16 = 2,000 < line 17 = 10,200 -> 2,000
    r = taxable_social_security(12_000, 30_000, filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert r.base_amount == 32_000
    assert r.taxable_benefits == 2_000


def test_taxable_ss_tax_exempt_interest_counts_in_provisional_income():
    # Same MFJ case but 4,000 tax-exempt interest pushes provisional to 40,000:
    #   line 9 = 8,000 -> line 13 = 4,000; line 14 = min(6,000, 4,000) = 4,000 -> taxable 4,000
    r = taxable_social_security(
        12_000, 30_000, tax_exempt_interest=4_000, filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR
    )
    assert r.provisional_income == Decimal("40000.00")
    assert r.taxable_benefits == 4_000


def test_taxable_ss_mfs_lived_with_spouse_85_percent_path():
    # MFS who lived WITH the spouse: both thresholds $0; taxable =
    # min(85% x provisional, 85% x benefits). Benefits 10,000, other 20,000:
    # provisional 25,000 -> min(21,250, 8,500) = 8,500 (benefits cap binds).
    r = taxable_social_security(
        10_000, 20_000, filing_status="married_filing_separately",
        mfs_lived_with_spouse=True, knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.base_amount == 0 and r.adjusted_base_amount == 0
    assert r.taxable_benefits == 8_500
    # Benefits 20,000, other 2,000: provisional 12,000 -> min(10,200, 17,000) = 10,200
    # (the provisional-income side binds).
    r2 = taxable_social_security(
        20_000, 2_000, filing_status="married_filing_separately",
        mfs_lived_with_spouse=True, knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r2.taxable_benefits == 10_200


def test_taxable_ss_mfs_lived_apart_all_year_uses_single_thresholds():
    r = taxable_social_security(
        20_000, 30_000, filing_status="married_filing_separately",
        mfs_lived_with_spouse=False, knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.base_amount == 25_000
    assert r.taxable_benefits == 9_600  # identical to the single case
    assert "lived apart" in r.work


def test_taxable_ss_mfs_flag_rejected_for_other_statuses():
    with pytest.raises(ValueError, match="mfs_lived_with_spouse"):
        taxable_social_security(10_000, 10_000, filing_status="single",
                                mfs_lived_with_spouse=True, knowledge_dir=KNOWLEDGE_DIR)


def test_taxable_ss_unknown_status_prescriptive():
    with pytest.raises(ValueError, match="unknown filing_status"):
        taxable_social_security(10_000, 10_000, filing_status="widowed", knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Excess social security withholding credit (Phase F) — 2023 per-person max
# 9,932.40 (6.2% x 160,200), multiple employers only.
# ---------------------------------------------------------------------------


def test_excess_ss_two_employers():
    # 6,000 + 6,000 = 12,000 counted vs the 9,932.40 max -> 2,067.60 -> 2,068.
    r = excess_ss([6_000, 6_000], knowledge_dir=KNOWLEDGE_DIR)
    assert r.max_withholding == Decimal("9932.40")
    assert r.counted_total == Decimal("12000.00")
    assert r.credit == 2068


def test_excess_ss_single_employer_gets_no_credit_even_when_over_withheld():
    # A single employer's over-withholding is recovered FROM THE EMPLOYER, never on the return.
    r = excess_ss([12_000], knowledge_dir=KNOWLEDGE_DIR)
    assert r.credit == 0
    assert "employer" in r.work and "Form 843" in r.work
    # A single employer under the max: still no credit, different explanation.
    r2 = excess_ss([5_000], knowledge_dir=KNOWLEDGE_DIR)
    assert r2.credit == 0
    assert "MULTIPLE employers" in r2.work


def test_excess_ss_entry_over_the_max_is_clipped_and_flagged():
    # Employer #1 withheld 10,000 > 9,932.40: only the max counts toward the credit
    # (the rest is an employer error); credit = 9,932.40 + 5,000 - 9,932.40 = 5,000.
    r = excess_ss([10_000, 5_000], knowledge_dir=KNOWLEDGE_DIR)
    assert r.counted_total == Decimal("14932.40")
    assert r.credit == 5000
    assert "employer error" in r.work and "#1" in r.work


def test_excess_ss_input_validation():
    with pytest.raises(TypeError, match="list"):
        excess_ss(6_000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match=r"withheld_by_employer\[1\]"):
        excess_ss([6_000, -1], knowledge_dir=KNOWLEDGE_DIR)
    assert excess_ss([], knowledge_dir=KNOWLEDGE_DIR).credit == 0


# ---------------------------------------------------------------------------
# Student loan interest deduction (Phase F) — 2023: cap 2,500; single phase-out
# 75,000-90,000 (Rev. Proc. 2022-38 section 3.30); MFS barred by rule.
# ---------------------------------------------------------------------------


def test_sli_below_phaseout_full_capped_deduction():
    r = student_loan_interest_deduction(3_000, 70_000, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.tentative == Decimal("2500.00")
    assert r.reduction == Decimal("0.00")
    assert r.deduction == 2500


def test_sli_midpoint_of_the_phaseout_halves():
    # MAGI 82,500 is the exact midpoint of 75,000-90,000: reduction = 2,500 x 7,500/15,000 = 1,250.
    r = student_loan_interest_deduction(3_000, 82_500, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.reduction == Decimal("1250.00")
    assert r.deduction == 1250


def test_sli_phaseout_applies_to_the_tentative_not_the_flat_cap():
    # Pub 970's own example shape: interest 1,000 (< cap) at the midpoint -> reduction 500.
    r = student_loan_interest_deduction(1_000, 82_500, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.tentative == Decimal("1000.00")
    assert r.deduction == 500


def test_sli_fully_phased_out_at_the_end():
    assert student_loan_interest_deduction(3_000, 90_000, "single", knowledge_dir=KNOWLEDGE_DIR).deduction == 0
    assert student_loan_interest_deduction(3_000, 200_000, "single", knowledge_dir=KNOWLEDGE_DIR).deduction == 0


def test_sli_mfs_is_zero_by_rule_not_an_error():
    r = student_loan_interest_deduction(3_000, 50_000, "married_filing_separately", knowledge_dir=KNOWLEDGE_DIR)
    assert r.deduction == 0
    assert "221(e)(2)" in r.work and "rule" in r.work


def test_sli_qss_uses_the_lower_range_and_unknown_status_rejected():
    # QSS phases out on the single/HoH range (75,000-90,000), NOT the MFJ range.
    r = student_loan_interest_deduction(3_000, 82_500, "qualifying_surviving_spouse", knowledge_dir=KNOWLEDGE_DIR)
    assert r.deduction == 1250
    with pytest.raises(ValueError, match="unknown filing_status"):
        student_loan_interest_deduction(3_000, 50_000, "married", knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Education credits (Phase F) — Form 8863: AOTC 100% of first 2,000 + 25% of
# next 2,000 per student (40% refundable); LLC 20% of up to 10,000 per return;
# 2023 phase-out 80,000-90,000 (160,000-180,000 MFJ); MFS barred.
# ---------------------------------------------------------------------------


def test_education_aotc_per_student_math():
    # Student 1 (4,000): 2,000 + 25% x 2,000 = 2,500; student 2 (1,000): 100% x 1,000 = 1,000.
    r = education_credits([4_000, 1_000], magi=50_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.aotc_total == 3500
    assert r.aotc_refundable == 1400  # 40% of the post-phase-out AOTC
    assert r.llc_amount == 0
    assert r.total_credit == 3500
    assert "student 1" in r.work and "student 2" in r.work


def test_education_aotc_expenses_above_4000_still_cap_at_2500():
    r = education_credits([10_000], magi=50_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.aotc_total == 2500


def test_education_llc_is_20_percent_per_return():
    r = education_credits([], llc_expenses=8_000, magi=50_000, filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.llc_amount == 1600
    assert r.aotc_total == 0 and r.aotc_refundable == 0
    assert r.total_credit == 1600
    # Per-return cap: 25,000 of expenses still yields 20% x 10,000 = 2,000.
    assert education_credits([], llc_expenses=25_000, magi=50_000, filing_status="single",
                             knowledge_dir=KNOWLEDGE_DIR).llc_amount == 2000


def test_education_phaseout_midpoint_halves_both_credits():
    # Single MAGI 85,000 = midpoint of 80,000-90,000 for BOTH credits in 2023:
    # AOTC 2,500 -> 1,250 (refundable 500); LLC 1,600 -> 800.
    r = education_credits([4_000], llc_expenses=8_000, magi=85_000, filing_status="single",
                          knowledge_dir=KNOWLEDGE_DIR)
    assert r.aotc_total == 1250
    assert r.aotc_refundable == 500
    assert r.llc_amount == 800
    assert r.total_credit == 2050


def test_education_fully_phased_out_and_mfj_range():
    assert education_credits([4_000], magi=90_000, filing_status="single",
                             knowledge_dir=KNOWLEDGE_DIR).total_credit == 0
    # MFJ uses 160,000-180,000: MAGI 90,000 is NOT phased out on a joint return.
    r = education_credits([4_000], magi=90_000, filing_status="married_filing_jointly",
                          knowledge_dir=KNOWLEDGE_DIR)
    assert r.aotc_total == 2500


def test_education_mfs_gets_neither_credit_by_rule():
    r = education_credits([4_000], llc_expenses=8_000, magi=50_000,
                          filing_status="married_filing_separately", knowledge_dir=KNOWLEDGE_DIR)
    assert r.total_credit == 0 and r.aotc_total == 0 and r.aotc_refundable == 0 and r.llc_amount == 0
    assert "NEITHER" in r.work and "rule" in r.work


def test_education_input_validation():
    with pytest.raises(TypeError, match="list"):
        education_credits(4_000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match=r"aotc_expenses_per_student\[0\]"):
        education_credits([-1], knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="unknown filing_status"):
        education_credits([4_000], filing_status="widowed", knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Premium Tax Credit, annual method (Phase F) — Form 8962 for 2023: FPL from
# the 2022 guidelines (13,590 for a household of 1, contiguous states), the
# ARPA/IRA applicable-figure table, Table 5 repayment limitation.
# ---------------------------------------------------------------------------


def test_ptc_200_percent_fpl_golden():
    # Income 27,180 = exactly 2 x 13,590 -> line 5 = 200 -> figure 0.0200
    #   contribution = 27,180 x 0.02 = 543.60 -> 544
    #   PTC = min(premiums 7,000, SLCSP 6,000 - 544 = 5,456) = 5,456; no APTC -> net PTC 5,456.
    r = ptc_annual(27_180, 1, 7_000, 6_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_amount == 13_590
    assert r.fpl_pct == 200
    assert r.applicable_figure == Decimal("0.0200")
    assert r.contribution == 544
    assert r.ptc == 5456
    assert r.net_ptc == 5456
    assert r.repayment == 0


def test_ptc_applicable_figure_interpolation_checkpoints():
    # IRS Table 2 checkpoints the interpolation must reproduce exactly (round HALF UP
    # to 4 decimals on the INTEGER percentage): 349 -> 0.0723, 399 -> 0.0848.
    r349 = ptc_annual(47_500, 1, 6_000, 6_000, knowledge_dir=KNOWLEDGE_DIR)  # 47,500/13,590 = 349.52 -> 349
    assert r349.fpl_pct == 349
    assert r349.applicable_figure == Decimal("0.0723")
    r399 = ptc_annual(54_300, 1, 6_000, 6_000, knowledge_dir=KNOWLEDGE_DIR)  # 54,300/13,590 = 399.55 -> 399
    assert r399.fpl_pct == 399
    assert r399.applicable_figure == Decimal("0.0848")


def test_ptc_line5_truncates_never_rounds():
    # 54,359/13,590 x 100 = 399.99...: Worksheet 2 says drop the decimals -> 399, not 400.
    r = ptc_annual(54_359, 1, 6_000, 6_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_pct == 399
    assert r.applicable_figure == Decimal("0.0848")
    # Exactly 400% stays 400 (the literal 401 entry is only for OVER 400%).
    assert ptc_annual(54_360, 1, 6_000, 6_000, knowledge_dir=KNOWLEDGE_DIR).fpl_pct == 400


def test_ptc_repayment_capped_below_200_percent_single():
    # Income 20,000 (147% FPL): figure 0.0000, contribution 0, PTC = min(2,000, 3,000) = 2,000.
    # APTC 5,000 -> excess 3,000, Table 5 single cap below 200% = 350 -> repayment 350.
    r = ptc_annual(20_000, 1, 2_000, 3_000, annual_aptc=5_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_pct == 147
    assert r.applicable_figure == Decimal("0.0000")
    assert r.ptc == 2000
    assert r.net_ptc == 0
    assert r.repayment == 350


def test_ptc_repayment_cap_other_statuses_column():
    # MFJ (any non-single status) uses the higher Table 5 column: 700 below 200% FPL.
    r = ptc_annual(25_000, 2, 2_000, 3_000, annual_aptc=5_000,
                   filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_pct == 136
    assert r.repayment == 700


def test_ptc_over_400_percent_enters_401_and_repays_in_full():
    # 60,000/13,590 = 441% -> line 5 is literally 401; figure 0.0850 (NO eligibility cliff);
    # contribution = 60,000 x 0.085 = 5,100 > SLCSP 4,000 -> PTC 0; but the repayment
    # LIMITATION vanishes at 400%+ -> the full 3,000 APTC is repaid.
    r = ptc_annual(60_000, 1, 7_000, 4_000, annual_aptc=3_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_pct == 401
    assert r.applicable_figure == Decimal("0.0850")
    assert r.contribution == 5100
    assert r.ptc == 0
    assert r.repayment == 3000


def test_ptc_mfs_denied_by_rule_full_aptc_excess_capped():
    # IRC 36B(c)(1)(C): a married-filing-separately filer without relief is NOT an
    # applicable taxpayer. Income 20,000 (147% FPL) would compute PTC 5,000; instead
    # line 24 = 0, net PTC = 0, and the FULL 4,000 APTC is excess — capped by the
    # Table 5 'other' column below 200% FPL = 700.
    r = ptc_annual(20_000, 1, 6_000, 5_000, annual_aptc=4_000,
                   filing_status="married_filing_separately", knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_pct == 147
    assert r.ptc == 0
    assert r.net_ptc == 0
    assert r.repayment == 700
    # The work trail explains the rule AND the relief exception.
    assert "36B(c)(1)(C)" in r.work
    assert "relief" in r.work
    assert r.inputs["mfs_relief_exception"] is False


def test_ptc_mfs_relief_exception_restores_the_computation():
    # The domestic-abuse/spousal-abandonment relief (Form 8962 'relief' checkbox):
    # figure 0.0000 -> contribution 0 -> PTC = min(6,000, 5,000) = 5,000; APTC 4,000
    # -> net PTC 1,000 — exactly the pre-gate computation, with the relief noted.
    r = ptc_annual(20_000, 1, 6_000, 5_000, annual_aptc=4_000,
                   filing_status="married_filing_separately", mfs_relief_exception=True,
                   knowledge_dir=KNOWLEDGE_DIR)
    assert r.ptc == 5_000
    assert r.net_ptc == 1_000
    assert r.repayment == 0
    assert "relief" in r.work
    assert r.inputs["mfs_relief_exception"] is True


def test_ptc_mfs_denied_repayment_uncapped_at_400_percent():
    # The MFS denial is still subject to Table 5, which VANISHES at 400%+ FPL:
    # the whole APTC is repaid (mirrors the over-400 rule for other statuses).
    r = ptc_annual(60_000, 1, 7_000, 4_000, annual_aptc=3_000,
                   filing_status="married_filing_separately", knowledge_dir=KNOWLEDGE_DIR)
    assert r.ptc == 0
    assert r.repayment == 3_000


def test_ptc_mfs_relief_flag_rejected_for_other_statuses():
    # Mirrors taxable_social_security's mfs_lived_with_spouse contract.
    with pytest.raises(ValueError, match="mfs_relief_exception"):
        ptc_annual(20_000, 1, 6_000, 5_000, filing_status="single",
                   mfs_relief_exception=True, knowledge_dir=KNOWLEDGE_DIR)


def test_ptc_below_100_fpl_without_aptc_is_zero():
    # 13,000 / 13,590 = 95% FPL with NO APTC: the estimated-income safe harbor cannot
    # apply (it requires APTC paid), so the filer is not an applicable taxpayer
    # (IRC 36B(c)(1)(A)) and line 24 is $0 — not the 5,000 the table would give.
    r = ptc_annual(13_000, 1, 6_000, 5_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_pct == 95
    assert r.ptc == 0
    assert r.net_ptc == 0
    assert r.repayment == 0
    assert "below 100%" in r.work
    assert "safe harbor" in r.work


def test_ptc_below_100_fpl_with_aptc_computes_with_caveat():
    # APTC was paid, so the estimated-income safe harbor can apply: keep the
    # computation (figure 0.0000 -> PTC = min(6,000, 5,000) = 5,000; net 2,000)
    # but spell out the eligibility caveat in the work trail.
    r = ptc_annual(13_000, 1, 6_000, 5_000, annual_aptc=3_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_pct == 95
    assert r.ptc == 5_000
    assert r.net_ptc == 2_000
    assert "CAVEAT" in r.work
    assert "safe harbor" in r.work


def test_ptc_alaska_table_and_large_household():
    # Alaska household of 1: FPL 16,990; income 33,980 = 200% -> contribution 680 (679.60 up).
    ak = ptc_annual(33_980, 1, 7_000, 6_000, state="alaska", knowledge_dir=KNOWLEDGE_DIR)
    assert ak.fpl_amount == 16_990
    assert ak.contribution == 680
    # Household of 10 (contiguous): 46,630 + 2 x 4,720 = 56,070.
    big = ptc_annual(56_070, 10, 7_000, 6_000, knowledge_dir=KNOWLEDGE_DIR)
    assert big.fpl_amount == 56_070
    assert big.fpl_pct == 100


def test_ptc_input_validation():
    with pytest.raises(ValueError, match="state"):
        ptc_annual(27_180, 1, 7_000, 6_000, state="guam", knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="household_size"):
        ptc_annual(27_180, 0, 7_000, 6_000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="unknown filing_status"):
        ptc_annual(27_180, 1, 7_000, 6_000, filing_status="widowed", knowledge_dir=KNOWLEDGE_DIR)


def test_ptc_unshipped_year_error_is_prescriptive():
    with pytest.raises(ValueError, match=r"no tax\.ptc block.*2023"):
        ptc_annual(27_180, 1, 7_000, 6_000, year=2019, knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Premium Tax Credit, MONTHLY method (Phase G3) — Form 8962 lines 12-23 grid:
# 8b = round(8a/12); per covered month (d) = max(0, SLCSP - 8b), (e) =
# min(premium, (d)); line 24 = sum of (e); the SAME IRC 36B(c)(1) gates and
# Table 5 limitation as the annual method.
# ---------------------------------------------------------------------------


def test_ptc_monthly_uniform_year_equals_annual_golden():
    # GOLDEN equivalence: with 12 uniform months and line 8a divisible by 12 the
    # monthly grid must reproduce the annual method exactly. MFJ household of 2,
    # income 36,620 = exactly 2 x 18,310 -> line 5 = 200 -> figure 0.0200;
    #   8a = 36,620 x 0.02 = 732.40 -> 732; 8b = 732/12 = 61 (no rounding drift).
    #   Per month: (d) = 500 - 61 = 439; (e) = min(600, 439) = 439; line 24 = 12 x 439 = 5,268.
    #   Line 25 = 12 x 300 = 3,600 -> net PTC 1,668.
    monthly = [{"premium": 600, "slcsp": 500, "aptc": 300}] * 12
    m = ptc_monthly(36_620, 2, monthly, filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    a = ptc_annual(36_620, 2, 7_200, 6_000, 3_600, filing_status="married_filing_jointly",
                   knowledge_dir=KNOWLEDGE_DIR)
    assert m.fpl_amount == a.fpl_amount == 18_310
    assert m.fpl_pct == a.fpl_pct == 200
    assert m.applicable_figure == a.applicable_figure == Decimal("0.0200")
    assert m.contribution == a.contribution == 732
    assert m.monthly_contribution == 61
    assert m.months_covered == 12
    assert m.ptc == a.ptc == 5_268
    assert m.net_ptc == a.net_ptc == 1_668
    assert m.repayment == a.repayment == 0
    assert "monthly method" in m.work and "line 8b" in m.work


def test_ptc_monthly_part_year_seven_months_hand_derived():
    # Hand-derived part-year case (the common 1095-A shape): coverage Jan-Jul only.
    # Income 27,180 (200% FPL): 8a = 543.60 -> 544; 8b = 544/12 = 45.33 -> 45.
    # Per covered month: (d) = 420 - 45 = 375; (e) = min(450, 375) = 375; line 24 = 7 x 375 = 2,625.
    # Line 25 = 7 x 380 = 2,660 -> excess 35, under the Table 5 single cap (900) -> repay 35.
    monthly = [{"premium": 450, "slcsp": 420, "aptc": 380}] * 7 + [{}] * 5
    r = ptc_monthly(27_180, 1, monthly, knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_pct == 200
    assert r.contribution == 544
    assert r.monthly_contribution == 45
    assert r.months_covered == 7
    assert r.ptc == 2_625
    assert r.net_ptc == 0
    assert r.repayment == 35
    # The work trail shows the grid month by month, only for covered months.
    assert "Jul" in r.work and "Aug" not in r.work


def test_ptc_monthly_part_year_repayment_capped():
    # 5 covered months at 147% FPL (figure 0.0000, 8b = 0): PTC = 5 x min(300, 280) = 1,400;
    # APTC = 5 x 700 = 3,500 -> excess 2,100, capped by Table 5 single below 200% = 350.
    monthly = [{"premium": 300, "slcsp": 280, "aptc": 700}] * 5 + [{}] * 7
    r = ptc_monthly(20_000, 1, monthly, knowledge_dir=KNOWLEDGE_DIR)
    assert r.fpl_pct == 147
    assert r.monthly_contribution == 0
    assert r.months_covered == 5
    assert r.ptc == 1_400
    assert r.net_ptc == 0
    assert r.repayment == 350


def test_ptc_monthly_inherits_mfs_gate_and_relief():
    # The IRC 36B(c)(1)(C) MFS denial applies to the monthly method identically:
    # PTC 0, full APTC (3,500) excess, capped by the Table 5 'other' column (700).
    monthly = [{"premium": 300, "slcsp": 280, "aptc": 700}] * 5 + [{}] * 7
    denied = ptc_monthly(20_000, 1, monthly, filing_status="married_filing_separately",
                         knowledge_dir=KNOWLEDGE_DIR)
    assert denied.ptc == 0
    assert denied.net_ptc == 0
    assert denied.repayment == 700
    assert "36B(c)(1)(C)" in denied.work and "relief" in denied.work
    assert denied.inputs["mfs_relief_exception"] is False
    # The relief exception restores the monthly computation: PTC 1,400, APTC 500 -> net 900.
    relief_rows = [{"premium": 300, "slcsp": 280, "aptc": 100}] * 5 + [{}] * 7
    relief = ptc_monthly(20_000, 1, relief_rows, filing_status="married_filing_separately",
                         mfs_relief_exception=True, knowledge_dir=KNOWLEDGE_DIR)
    assert relief.ptc == 1_400
    assert relief.net_ptc == 900
    assert relief.repayment == 0
    assert "relief" in relief.work


def test_ptc_monthly_inherits_below_100_fpl_gates():
    # 13,000 / 13,590 = 95% FPL. No APTC -> not an applicable taxpayer, PTC $0.
    no_aptc = ptc_monthly(13_000, 1, [{"premium": 500, "slcsp": 420}] * 12, knowledge_dir=KNOWLEDGE_DIR)
    assert no_aptc.fpl_pct == 95
    assert no_aptc.ptc == 0 and no_aptc.net_ptc == 0 and no_aptc.repayment == 0
    assert "below 100%" in no_aptc.work and "safe harbor" in no_aptc.work
    # With APTC the estimated-income safe harbor can apply: compute, with the caveat.
    with_aptc = ptc_monthly(13_000, 1, [{"premium": 500, "slcsp": 420, "aptc": 250}] * 12,
                            knowledge_dir=KNOWLEDGE_DIR)
    assert with_aptc.ptc == 5_040  # 12 x min(500, 420 - 0)
    assert with_aptc.net_ptc == 2_040
    assert "CAVEAT" in with_aptc.work and "safe harbor" in with_aptc.work


def test_ptc_monthly_annual_aptc_cross_check():
    monthly = [{"premium": 450, "slcsp": 420, "aptc": 380}] * 7 + [{}] * 5
    # Consistent 1095-A line 33C passes and changes nothing.
    ok = ptc_monthly(27_180, 1, monthly, annual_aptc=2_660, knowledge_dir=KNOWLEDGE_DIR)
    assert ok.repayment == 35
    # A mismatched total is rejected prescriptively (never silently preferred).
    with pytest.raises(ValueError, match=r"annual_aptc.*33C"):
        ptc_monthly(27_180, 1, monthly, annual_aptc=2_000, knowledge_dir=KNOWLEDGE_DIR)
    # With NO monthly APTC breakdown, the annual total stands in as line 25.
    no_breakdown = [{"premium": 450, "slcsp": 420}] * 7 + [{}] * 5
    used = ptc_monthly(27_180, 1, no_breakdown, annual_aptc=2_660, knowledge_dir=KNOWLEDGE_DIR)
    assert used.repayment == 35
    assert "used as the line 25 total" in used.work


def test_ptc_monthly_input_validation():
    row = {"premium": 450, "slcsp": 420, "aptc": 380}
    with pytest.raises(TypeError, match="list of 12"):
        ptc_monthly(27_180, 1, row, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="EXACTLY 12"):
        ptc_monthly(27_180, 1, [row] * 7, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(TypeError, match=r"monthly\[3\] \(April\)"):
        ptc_monthly(27_180, 1, [row] * 3 + [420] + [row] * 8, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match=r"unknown key.*premiums"):
        ptc_monthly(27_180, 1, [{"premiums": 450}] + [{}] * 11, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match=r"monthly\[0\]\.slcsp must be >= 0"):
        ptc_monthly(27_180, 1, [{"slcsp": -1}] + [{}] * 11, knowledge_dir=KNOWLEDGE_DIR)
    # The shared gates fire with the annual method's exact messages.
    with pytest.raises(ValueError, match="household_size"):
        ptc_monthly(27_180, 0, [row] * 12, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="state"):
        ptc_monthly(27_180, 1, [row] * 12, state="guam", knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="mfs_relief_exception"):
        ptc_monthly(27_180, 1, [row] * 12, filing_status="single",
                    mfs_relief_exception=True, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match=r"no tax\.ptc block"):
        ptc_monthly(27_180, 1, [row] * 12, year=2019, knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Phase F ops across every supported year: the five statutory/indexed ops ship
# for 2019-2024 (capital-gains breakpoints DIFFER per year — Rev. Procs
# 2018-57 .. 2023-34); the PTC block exists only for 2023-2024.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "expected_qdcgt", "expected_excess"),
    [
        # QDCGT spot: single, taxable 41,000 ALL qualified dividends. The slice above
        # that year's zero-rate breakpoint is taxed at 15% (ordinary part is 0):
        #   2019: breakpoint 39,375 -> 1,625 x 15% = 243.75 -> 244
        #   2020: 40,000 -> 1,000 x 15% = 150      2021: 40,400 -> 600 x 15% = 90
        #   2022: 41,675 / 2023: 44,625 / 2024: 47,025 -> all at 0% -> tax 0
        # excess_ss spot: [6,000, 6,000] vs that year's per-person max (6.2% x wage base):
        #   2019: 12,000 - 8,239.80 -> 3,760   2020: - 8,537.40 -> 3,463
        #   2021: - 8,853.60 -> 3,146          2022: - 9,114.00 -> 2,886
        #   2023: - 9,932.40 -> 2,068          2024: - 10,453.20 -> 1,547
        (2019, 244, 3760),
        (2020, 150, 3463),
        (2021, 90, 3146),
        (2022, 0, 2886),
        (2023, 0, 2068),
        (2024, 0, 1547),
    ],
)
def test_phase_f_ops_ship_for_every_supported_year(year, expected_qdcgt, expected_excess):
    qd = tax_with_preferential_rates(41_000, 41_000, filing_status="single", year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert qd.tax == expected_qdcgt
    assert excess_ss([6_000, 6_000], year=year, knowledge_dir=KNOWLEDGE_DIR).credit == expected_excess
    # Statutory IRC 86(c) thresholds: identical result in every year.
    assert taxable_social_security(20_000, 30_000, filing_status="single", year=year,
                                   knowledge_dir=KNOWLEDGE_DIR).taxable_benefits == 9_600
    # SLI: MAGI 0 is below every year's phase-out start -> the full 2,500 cap.
    assert student_loan_interest_deduction(3_000, 0, "single", year=year,
                                           knowledge_dir=KNOWLEDGE_DIR).deduction == 2500
    # AOTC: statutory formula, identical in every year at low MAGI.
    assert education_credits([4_000], magi=0, filing_status="single", year=year,
                             knowledge_dir=KNOWLEDGE_DIR).aotc_total == 2500
    # PTC ships only for 2023/2024 (ARPA table extended by IRA sec. 12001(a)).
    if year in (2023, 2024):
        assert ptc_annual(30_000, 1, 6_000, 5_000, year=year, knowledge_dir=KNOWLEDGE_DIR).ptc >= 0
    else:
        with pytest.raises(ValueError, match=r"no tax\.ptc block"):
            ptc_annual(30_000, 1, 6_000, 5_000, year=year, knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Child tax credit / ODC / ACTC (Schedule 8812) — 2023: $2,000 per qualifying
# child + $500 ODC, phase-out $50 per $1,000 (or fraction) of MAGI over
# 400,000 MFJ / 200,000 other, ACTC capped at $1,600/child and 15% of earned
# income over $2,500. 2021 uses the ARPA expanded two-tier fully-refundable
# rules. Parameters from the cited credits blocks; goldens hand-derived.
# ---------------------------------------------------------------------------


def test_ctc_mfj_two_kids_nonrefundable_path():
    # Wages 95,000 MFJ: taxable 67,300, table tax 7,639 comfortably exceeds the
    # 4,000 credit, so it is used in full nonrefundably and no ACTC remains.
    tax = tax_from_taxable_income(
        95_000 - standard_deduction("married_filing_jointly", 2023, knowledge_dir=KNOWLEDGE_DIR).amount,
        "married_filing_jointly", 2023, knowledge_dir=KNOWLEDGE_DIR,
    ).tax
    assert tax == 7_639
    r = child_tax_credit(2, 0, magi=95_000, income_tax_before_credits=tax, earned_income=95_000,
                         filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert r.ctc_odc_total == 4_000
    assert r.phaseout_reduction == 0
    assert r.credit_after_phaseout == 4_000
    assert r.nonrefundable_used == 4_000  # Form 1040 line 19
    assert r.actc_refundable == 0  # nothing left over for line 28
    assert r.fully_refundable is False
    assert "line 8" in r.work and "line 12" in r.work and "line 14" in r.work
    assert r.citation.url.startswith("https://www.irs.gov/")


def test_ctc_phaseout_rounds_the_excess_up_to_the_next_1000():
    # Line 10: MAGI excess over the threshold rounds UP to the next $1,000 FIRST.
    # MFJ threshold 400,000: excess 10,000 (exact multiple) -> 10 x $50 = $500;
    # excess 10,001 (a $1 fraction into the next band) -> 11 x $50 = $550.
    at = child_tax_credit(2, 0, magi=410_000, income_tax_before_credits=80_000, earned_income=410_000,
                          filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    over = child_tax_credit(2, 0, magi=410_001, income_tax_before_credits=80_000, earned_income=410_001,
                            filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert at.phaseout_reduction == 500
    assert at.credit_after_phaseout == 3_500
    assert over.phaseout_reduction == 550
    assert over.credit_after_phaseout == 3_450
    # At the threshold exactly there is no reduction at all.
    assert child_tax_credit(2, 0, magi=400_000, income_tax_before_credits=80_000, earned_income=400_000,
                            filing_status="married_filing_jointly",
                            knowledge_dir=KNOWLEDGE_DIR).phaseout_reduction == 0


def test_ctc_fully_phased_out_stops_the_form():
    # MFJ MAGI 480,000: reduction 80 x $50 = 4,000 wipes the whole line 8 -> the
    # form says stop; no CTC, ODC, or ACTC.
    r = child_tax_credit(2, 0, magi=480_000, income_tax_before_credits=100_000, earned_income=480_000,
                         filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert r.credit_after_phaseout == 0
    assert r.nonrefundable_used == 0 and r.actc_refundable == 0
    assert "stop" in r.work


def test_ctc_odc_only_never_refunds():
    # Two ITIN dependents: $1,000 of ODC offsets tax but can never become ACTC.
    r = child_tax_credit(0, 2, magi=50_000, income_tax_before_credits=5_000, earned_income=50_000,
                         filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.ctc_odc_total == 1_000
    assert r.nonrefundable_used == 1_000
    assert r.actc_refundable == 0
    assert "ODC never refunds" in r.work
    # With zero tax the ODC is simply lost — still no refund.
    lost = child_tax_credit(0, 2, magi=50_000, income_tax_before_credits=0, earned_income=50_000,
                            filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert lost.nonrefundable_used == 0 and lost.actc_refundable == 0


def test_ctc_actc_low_income_15_percent_rule_then_per_child_cap():
    # Tax 0, 2 qualifying children: leftover 4,000; per-child cap 2 x 1,600 = 3,200.
    # Earned 20,000 -> 15% x 17,500 = 2,625 binds (the 15% rule).
    r = child_tax_credit(2, 0, magi=20_000, income_tax_before_credits=0, earned_income=20_000,
                         filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.nonrefundable_used == 0
    assert r.actc_refundable == 2_625
    assert r.actc_cap_per_child == 1_600
    # Earned 30,000 -> 15% x 27,500 = 4,125, so the 3,200 per-child cap binds instead.
    capped = child_tax_credit(2, 0, magi=30_000, income_tax_before_credits=0, earned_income=30_000,
                              filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert capped.actc_refundable == 3_200


def test_ctc_partial_tax_absorption_leaves_the_rest_for_actc():
    # HOH wages 22,000: taxable 1,200 -> tax 121; line 14 = 121, leftover 3,879;
    # cap 3,200; 15% x 19,500 = 2,925 binds -> ACTC 2,925.
    tax = tax_from_taxable_income(
        22_000 - standard_deduction("head_of_household", 2023, knowledge_dir=KNOWLEDGE_DIR).amount,
        "head_of_household", 2023, knowledge_dir=KNOWLEDGE_DIR,
    ).tax
    assert tax == 121
    r = child_tax_credit(2, 0, magi=22_000, income_tax_before_credits=tax, earned_income=22_000,
                         filing_status="head_of_household", knowledge_dir=KNOWLEDGE_DIR)
    assert r.nonrefundable_used == 121
    assert r.actc_refundable == 2_925


def test_ctc_earned_income_at_or_below_2500_gives_no_actc():
    r = child_tax_credit(1, 0, magi=2_500, income_tax_before_credits=0, earned_income=2_500,
                         filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.actc_refundable == 0
    assert r.credit_after_phaseout == 2_000  # the credit exists, it just cannot refund


def test_ctc_three_plus_children_part_ii_b_caveat_is_flagged():
    # 3 QCs, tax 0, earned 10,000: line 20 = 1,125 < line 17 -> Part II-B (the
    # social-security-taxes alternative) could only INCREASE the ACTC; the op
    # must disclose that it is not modeled.
    r = child_tax_credit(3, 0, magi=10_000, income_tax_before_credits=0, earned_income=10_000,
                         filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.actc_refundable == 1_125
    assert "Part II-B" in r.work
    # With 2 children the caveat never appears (Part II-B needs 3+).
    two = child_tax_credit(2, 0, magi=10_000, income_tax_before_credits=0, earned_income=10_000,
                           filing_status="single", knowledge_dir=KNOWLEDGE_DIR)
    assert "Part II-B" not in two.work


def test_ctc_2021_arpa_under_6_two_tier_phaseout():
    # MFJ, 2 kids (1 under 6), MAGI 160,000: expanded 3,600 + 3,000 = 6,600
    # (base 4,000, increase 2,600); tier 1 trims min(50 x 10, cap 12,500, 2,600)
    # = 500; no tier 2 (below 400,000) -> 6,100, ALL of it refundable (no ODC).
    r = child_tax_credit(2, 0, magi=160_000, income_tax_before_credits=5_000, earned_income=160_000,
                         filing_status="married_filing_jointly", year=2021, children_under_6=1,
                         knowledge_dir=KNOWLEDGE_DIR)
    assert r.ctc_odc_total == 6_600
    assert r.phaseout_reduction == 500
    assert r.credit_after_phaseout == 6_100
    assert r.nonrefundable_used == 0  # no ODC part; the CTC itself never touches line 19
    assert r.actc_refundable == 6_100
    assert r.fully_refundable is True
    assert "FULLY REFUNDABLE" in r.work and "abode" in r.work


def test_ctc_2021_arpa_qss_tier1_cap_binds():
    # The 2021 Line 5 Worksheet caps the first-tier reduction per status; QSS's
    # cap is only 2,500 (its SECOND tier groups with 'all other' at 200,000).
    # QSS, 2 kids under 6, MAGI 220,000: raw tier 1 = 50 x 70 = 3,500, capped at
    # 2,500 (< the 3,200 increase); tier 2 over 200,000 = 50 x 20 = 1,000.
    r = child_tax_credit(2, 0, magi=220_000, income_tax_before_credits=30_000, earned_income=220_000,
                         filing_status="qualifying_surviving_spouse", year=2021, children_under_6=2,
                         knowledge_dir=KNOWLEDGE_DIR)
    assert r.ctc_odc_total == 7_200
    assert r.phaseout_reduction == 2_500 + 1_000
    assert r.credit_after_phaseout == 3_700
    assert r.actc_refundable == 3_700


def test_ctc_2021_arpa_odc_part_stays_nonrefundable():
    # Same ARPA family plus one ODC dependent: the 500 ODC is preserved FIRST
    # (line 14a) and offsets tax nonrefundably; the CTC remainder is the RCTC.
    r = child_tax_credit(2, 1, magi=160_000, income_tax_before_credits=5_000, earned_income=160_000,
                         filing_status="married_filing_jointly", year=2021, children_under_6=1,
                         knowledge_dir=KNOWLEDGE_DIR)
    assert r.credit_after_phaseout == 6_600
    assert r.nonrefundable_used == 500
    assert r.actc_refundable == 6_100
    # With zero tax the ODC part is lost, never refunded — even in 2021.
    zero_tax = child_tax_credit(2, 1, magi=160_000, income_tax_before_credits=0, earned_income=160_000,
                                filing_status="married_filing_jointly", year=2021, children_under_6=1,
                                knowledge_dir=KNOWLEDGE_DIR)
    assert zero_tax.nonrefundable_used == 0
    assert zero_tax.actc_refundable == 6_100


@pytest.mark.parametrize(
    ("year", "expected_actc", "expected_fully_refundable"),
    [
        # Single, 1 qualifying child (6+), earned = MAGI = 20,000, tax 0.
        # Non-ARPA years: ACTC = min(2,000 leftover, that year's per-child cap,
        # 15% x 17,500 = 2,625) — the cap binds: 1,400 / 1,400 / 1,500 / 1,600 / 1,700.
        # 2021 (ARPA): $3,000 credit, no phase-out at this income, FULLY refundable.
        (2019, 1_400, False),
        (2020, 1_400, False),
        (2021, 3_000, True),
        (2022, 1_500, False),
        (2023, 1_600, False),
        (2024, 1_700, False),
    ],
)
def test_ctc_ships_for_every_supported_year(year, expected_actc, expected_fully_refundable):
    r = child_tax_credit(1, 0, magi=20_000, income_tax_before_credits=0, earned_income=20_000,
                         filing_status="single", year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert r.nonrefundable_used == 0
    assert r.actc_refundable == expected_actc
    assert r.fully_refundable is expected_fully_refundable
    assert r.citation.url.startswith("https://www.irs.gov/")


def test_ctc_input_validation():
    with pytest.raises(TypeError, match="qualifying_children_ssn"):
        child_tax_credit(True, 0, 50_000, 5_000, 50_000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="other_dependents"):
        child_tax_credit(1, -1, 50_000, 5_000, 50_000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="children_under_6.*cannot exceed"):
        child_tax_credit(1, 0, 50_000, 5_000, 50_000, children_under_6=2, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="income_tax_before_credits"):
        child_tax_credit(1, 0, 50_000, -1, 50_000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="earned_income"):
        child_tax_credit(1, 0, 50_000, 5_000, -1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="unknown filing_status"):
        child_tax_credit(1, 0, 50_000, 5_000, 50_000, filing_status="married", knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Earned income tax credit — 2023 (Rev. Proc. 2022-38 section 3.06): 1 child
# max 3,995 over earned-income amount 11,750; phase-out (other) 21,560-46,560,
# (MFJ) 28,120-53,120; investment income limit 11,000; MFS barred by rule.
# Goldens hand-derived from the Rev. Proc. formula.
# ---------------------------------------------------------------------------


def test_eitc_one_child_phase_in_plateau_phase_out():
    # Phase-in: 3,995/11,750 = 0.34 exactly -> 0.34 x 6,000 = 2,040.
    lo = eitc(6_000, 6_000, 1, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert lo.eitc == 2_040 and lo.phase == "in" and lo.disqualified_reason is None
    # Plateau: earned past 11,750, AGI below the 21,560 phase-out start.
    mid = eitc(15_000, 15_000, 1, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert mid.eitc == 3_995 and mid.phase == "plateau"
    # Phase-out: 3,995 - 3,995/25,000 x (30,000 - 21,560) = 2,646.29 -> 2,646.
    hi = eitc(30_000, 30_000, 1, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert hi.eitc == 2_646 and hi.phase == "out"
    assert hi.citation.url.startswith("https://www.irs.gov/")


def test_eitc_phases_out_on_the_greater_of_agi_or_earned_income():
    # Same 2,646 whichever side is higher — the phase-out base is max(AGI, earned).
    assert eitc(15_000, 30_000, 1, "single", knowledge_dir=KNOWLEDGE_DIR).eitc == 2_646
    assert eitc(30_000, 15_000, 1, "single", knowledge_dir=KNOWLEDGE_DIR).eitc == 2_646
    assert eitc(15_000, 30_000, 1, "single", knowledge_dir=KNOWLEDGE_DIR).phase == "out"


def test_eitc_mfj_uses_the_higher_thresholds_and_qss_does_not():
    # MFJ phase-out starts at 28,120: 3,995 - 0.1598 x 1,880 = 3,694.58 -> 3,695.
    mfj = eitc(30_000, 30_000, 1, "married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert mfj.eitc == 3_695
    # A qualifying surviving spouse uses the OTHER column (the EIC table groups
    # single/HoH/QSS), NOT the MFJ column — no aliasing here.
    qss = eitc(30_000, 30_000, 1, "qualifying_surviving_spouse", knowledge_dir=KNOWLEDGE_DIR)
    assert qss.eitc == 2_646


def test_eitc_zero_children_and_three_plus_share_columns():
    # Childless plateau: max 600 at earned = the 7,840 earned-income amount.
    assert eitc(7_840, 7_840, 0, "single", knowledge_dir=KNOWLEDGE_DIR).eitc == 600
    # 4 and 5 children both use the '3+' column: plateau max 7,430.
    assert eitc(17_000, 17_000, 4, "single", knowledge_dir=KNOWLEDGE_DIR).eitc == 7_430
    assert eitc(17_000, 17_000, 5, "single", knowledge_dir=KNOWLEDGE_DIR).eitc == 7_430


def test_eitc_complete_phaseout_is_zero_but_not_disqualified():
    r = eitc(46_560, 46_560, 1, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.eitc == 0
    assert r.phase == "out"
    assert r.disqualified_reason is None


def test_eitc_investment_income_gate():
    # A dollar over the 11,000 limit denies the credit ENTIRELY (Pub 596 Rule 6).
    over = eitc(15_000, 15_000, 1, "single", investment_income=11_001, knowledge_dir=KNOWLEDGE_DIR)
    assert over.eitc == 0 and over.phase is None
    assert "11,000" in over.disqualified_reason
    assert "Rule 6" in over.work
    # AT the limit the credit still computes.
    assert eitc(15_000, 15_000, 1, "single", investment_income=11_000,
                knowledge_dir=KNOWLEDGE_DIR).eitc == 3_995


def test_eitc_mfs_gate_notes_the_narrow_post_2021_exception():
    r = eitc(15_000, 15_000, 1, "married_filing_separately", knowledge_dir=KNOWLEDGE_DIR)
    assert r.eitc == 0 and r.phase is None
    assert "married filing separately" in r.disqualified_reason
    # The work trail spells out the ARPA section 9622 separated-spouse exception.
    assert "exception" in r.work and "9622" in r.work and "last 6 months" in r.work


def test_eitc_requires_positive_earned_income():
    r = eitc(0, 15_000, 1, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert r.eitc == 0 and r.phase is None
    assert "earned income" in r.disqualified_reason


def test_eitc_work_discloses_the_50_dollar_band_approximation():
    r = eitc(30_000, 30_000, 1, "single", knowledge_dir=KNOWLEDGE_DIR)
    assert "$50 income bands" in r.work


@pytest.mark.parametrize(
    ("year", "expected_max"),
    [
        # 1-child plateau at earned = AGI = 15,000 (over every year's earned-income
        # amount, under every year's phase-out start): the Rev. Proc. maximums.
        (2019, 3_526),
        (2020, 3_584),
        (2021, 3_618),
        (2022, 3_733),
        (2023, 3_995),
        (2024, 4_213),
    ],
)
def test_eitc_ships_for_every_supported_year(year, expected_max):
    r = eitc(15_000, 15_000, 1, "single", year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert r.eitc == expected_max
    assert r.phase == "plateau"


def test_eitc_2021_arpa_childless_expansion():
    # ARPA (Rev. Proc. 2021-23 section 4) raised the 2021 childless maximum to
    # 1,502 (never 2020-45's 543) and the investment limit to 10,000.
    r = eitc(9_820, 9_820, 0, "single", year=2021, knowledge_dir=KNOWLEDGE_DIR)
    assert r.eitc == 1_502 and r.phase == "plateau"
    assert eitc(9_820, 9_820, 0, "single", year=2021, investment_income=10_001,
                knowledge_dir=KNOWLEDGE_DIR).eitc == 0


def test_eitc_input_validation():
    with pytest.raises(ValueError, match="qualifying_children"):
        eitc(15_000, 15_000, -1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(TypeError, match="qualifying_children"):
        eitc(15_000, 15_000, True, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="investment_income"):
        eitc(15_000, 15_000, 1, investment_income=-1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="unknown filing_status"):
        eitc(15_000, 15_000, 1, "widowed", knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Cross-checks against the estimator: the standalone ops must reproduce the
# adversarially-reviewed estimate_refund credit lines for identical inputs
# (estimate_refund imported read-only; its knowledge-pack math is the oracle).
# ---------------------------------------------------------------------------


def _family_profile(marital, status, dependents, hoh=False):
    from taxfill_core.schemas.profile import Answer, Dependent, Household, Profile, Provenance

    us = Provenance.user_stated()
    return Profile(household=Household(
        marital_status=Answer(value=marital, provenance=us),
        filing_status=Answer(value=status, provenance=us),
        hoh_qualifying_person=Answer(value=True, provenance=us) if hoh else None,
        dependents=[Dependent(name=n, relationship="child", dob=dob, has_ssn=True, provenance=us)
                    for n, dob in dependents],
    ))


def test_ctc_matches_estimate_refund_nonrefundable_family():
    from taxfill_core.estimate import IncomeSnapshot, estimate_refund

    profile = _family_profile("married", "married_filing_jointly",
                              [("Kid A", date(2016, 4, 1)), ("Kid B", date(2019, 9, 15))])
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=95_000, federal_withholding=10_000),
                          knowledge_dir=KNOWLEDGE_DIR)
    labels = {c.label: c.amount for c in est.composition}
    r = child_tax_credit(2, 0, magi=95_000, income_tax_before_credits=labels["Income tax"],
                         earned_income=95_000, filing_status="married_filing_jointly",
                         knowledge_dir=KNOWLEDGE_DIR)
    assert labels["Less: child tax credit / credit for other dependents (nonrefundable)"] == -r.nonrefundable_used
    assert r.nonrefundable_used == 4_000
    assert "Less: additional child tax credit (refundable)" not in labels


def test_ctc_and_eitc_match_estimate_refund_low_income_family():
    from taxfill_core.estimate import IncomeSnapshot, estimate_refund

    wages = 22_000
    profile = _family_profile("unmarried", "head_of_household",
                              [("Kid A", date(2016, 4, 1)), ("Kid B", date(2019, 9, 15))], hoh=True)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=wages, federal_withholding=500),
                          knowledge_dir=KNOWLEDGE_DIR)
    labels = {c.label: c.amount for c in est.composition}
    tax = labels["Income tax"]
    r = child_tax_credit(2, 0, magi=wages, income_tax_before_credits=tax, earned_income=wages,
                         filing_status="head_of_household", knowledge_dir=KNOWLEDGE_DIR)
    assert labels["Less: child tax credit / credit for other dependents (nonrefundable)"] == -r.nonrefundable_used
    assert labels["Less: additional child tax credit (refundable)"] == -r.actc_refundable
    e = eitc(wages, wages, 2, "head_of_household", knowledge_dir=KNOWLEDGE_DIR)
    assert labels["Less: earned income tax credit (refundable, formula approximation)"] == -e.eitc
    assert e.eitc == 6_511  # 6,604 - 6,604/31,358 x (22,000 - 21,560), rounded


def test_ctc_2021_arpa_matches_estimate_refund():
    from taxfill_core.estimate import IncomeSnapshot, estimate_refund

    # Ages at end of 2021: born 2016 -> 5 (under 6, $3,600); born 2013 -> 8 ($3,000).
    profile = _family_profile("married", "married_filing_jointly",
                              [("Kid A", date(2016, 4, 1)), ("Kid B", date(2013, 9, 15))])
    est = estimate_refund(profile, 2021, IncomeSnapshot(wages=160_000, federal_withholding=20_000),
                          knowledge_dir=KNOWLEDGE_DIR)
    labels = {c.label: c.amount for c in est.composition}
    r = child_tax_credit(2, 0, magi=160_000, income_tax_before_credits=labels["Income tax"],
                         earned_income=160_000, filing_status="married_filing_jointly", year=2021,
                         children_under_6=1, knowledge_dir=KNOWLEDGE_DIR)
    assert labels["Less: child tax credit (2021 — fully refundable)"] == -r.actc_refundable
    assert r.actc_refundable == 6_100


# ---------------------------------------------------------------------------
# Child & dependent care credit (Form 2441 -> Schedule 3 line 2) — Phase G, G2.
# Golden values from the researched/verified per-year table: the f2441 line 8
# decimal tables (i2441/f2441, 2019-2024; the 2021 i2441 Phaseout Schedule,
# p. 6) and IRC 21 — every bracket checkpoint below is a published table row.
# ---------------------------------------------------------------------------


def test_dependent_care_low_agi_35_percent():
    # 2023, AGI $0-15,000 bracket -> .35; one qualifying person caps expenses at $3,000.
    r = dependent_care_credit(3_600, 1, 30_000, agi=14_000, year=2023, knowledge_dir=KNOWLEDGE_DIR)
    assert r.allowed_expenses == 3_000
    assert r.applicable_percentage == Decimal("0.35")
    assert r.credit == 1_050
    assert r.refundable is False
    assert "Credit Limit Worksheet" in r.work           # nonrefundable-limited-by-tax disclosure
    assert "provider's name, address, and TIN" in r.work
    assert r.citation.url == "https://www.irs.gov/pub/irs-prior/i2441--2023.pdf"


def test_dependent_care_high_agi_20_percent_floor():
    # "43,000 — No limit = .20" (2023 form line 8 table); two-or-more cap $6,000.
    r = dependent_care_credit(9_000, 2, 80_000, agi=95_000, year=2023, knowledge_dir=KNOWLEDGE_DIR)
    assert r.allowed_expenses == 6_000
    assert r.applicable_percentage == Decimal("0.20")
    assert r.credit == 1_200


@pytest.mark.parametrize(
    ("agi", "pct"),
    [
        (15_000, "0.35"),   # boundary keeps the higher rate (over-X-but-not-over-Y)
        (15_001, "0.34"),   # one dollar over -> or-fraction-thereof rounds UP
        (29_000, "0.28"),   # published row 27,000-29,000 = .28
        (43_000, "0.21"),   # published row 41,000-43,000 = .21 (exactly 43,000 stays .21)
        (43_001, "0.20"),   # over 43,000 -> the .20 floor
    ],
)
def test_dependent_care_percentage_slide_published_rows(agi, pct):
    r = dependent_care_credit(3_000, 1, 50_000, agi=agi, year=2023, knowledge_dir=KNOWLEDGE_DIR)
    assert r.applicable_percentage == Decimal(pct)


def test_dependent_care_2021_arpa_50_percent_and_refundable():
    # 2021 ARPA: caps $8,000/$16,000, 50% at AGI <= $125,000, refundable (abode test).
    r = dependent_care_credit(
        20_000, 2, 60_000, spouse_earned_income=50_000, agi=120_000,
        filing_status="married_filing_jointly", year=2021, knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.allowed_expenses == 16_000
    assert r.applicable_percentage == Decimal("0.50")
    assert r.credit == 8_000
    assert r.refundable is True
    assert "principal place of abode" in r.work         # the line B test is caller judgment
    assert "line B" in r.work


@pytest.mark.parametrize(
    ("agi", "pct"),
    [
        (125_000, "0.50"),  # "$125,000 or less" keeps .50
        (150_000, "0.37"),  # 149,000-151,000 row of the 2021 Phaseout Schedule
        (183_000, "0.21"),  # 181,000-183,000 = .21 (boundary keeps the higher rate)
        (183_001, "0.20"),  # the .20 plateau begins
        (400_000, "0.20"),  # plateau holds through 400,000
        (410_000, "0.15"),  # second slide: 408,000-410,000 = .15
        (438_000, "0.01"),  # 436,000-438,000 = .01 — exactly 438,000 is 19 increments
        (438_001, "0.00"),  # "438,000 — No limit = .00" (the or-fraction rule's 20th step)
        (500_000, "0.00"),
    ],
)
def test_dependent_care_2021_dual_slide_published_rows(agi, pct):
    r = dependent_care_credit(8_000, 1, 999_999, agi=agi, year=2021, knowledge_dir=KNOWLEDGE_DIR)
    assert r.applicable_percentage == Decimal(pct)


def test_dependent_care_2021_zero_point_gives_no_credit_and_not_refundable():
    r = dependent_care_credit(8_000, 1, 999_999, agi=440_000, year=2021, knowledge_dir=KNOWLEDGE_DIR)
    assert r.credit == 0
    assert r.refundable is False  # a $0 credit is never flagged refundable


def test_dependent_care_employer_benefit_offset():
    # W-2 box 10 benefits reduce BOTH the cap (line 29) and the countable
    # expenses (line 30): $6,000 expenses, $5,000 benefits -> $1,000 base.
    r = dependent_care_credit(
        6_000, 2, 40_000, spouse_earned_income=40_000, agi=90_000,
        filing_status="married_filing_jointly", year=2023, employer_benefits=5_000,
        knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.allowed_expenses == 1_000
    assert r.credit == 200  # 20% x 1,000
    assert "box 10" in r.work and "lines 24+25" in r.work  # the offset approximation is disclosed


def test_dependent_care_mfj_spouse_earned_income_limitation():
    # Line 6 is the SMALLEST of line 3/4/5 — the low-earning spouse binds.
    r = dependent_care_credit(
        6_000, 2, 50_000, spouse_earned_income=2_500, agi=60_000,
        filing_status="married_filing_jointly", year=2023, knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.allowed_expenses == 2_500
    assert r.credit == 500  # 20% x 2,500


def test_dependent_care_mfj_requires_spouse_earned_income():
    with pytest.raises(ValueError) as exc:
        dependent_care_credit(
            6_000, 2, 50_000, agi=60_000, filing_status="married_filing_jointly",
            year=2023, knowledge_dir=KNOWLEDGE_DIR,
        )
    msg = str(exc.value)
    assert "spouse_earned_income" in msg
    # The deemed-income rule is named so a student/disabled-spouse case is not a dead end.
    assert "$250" in msg and "$500" in msg
    assert "judgment" in msg


def test_dependent_care_mfs_gate():
    r = dependent_care_credit(
        3_000, 1, 30_000, agi=20_000, filing_status="married_filing_separately",
        year=2023, knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.credit == 0 and r.allowed_expenses == 0
    assert "married persons must file a joint return" in r.work
    # All three treated-as-unmarried conditions are quoted.
    assert "last 6 months" in r.work
    assert "main home" in r.work
    assert "more than half the cost" in r.work


def test_dependent_care_earned_income_limitation_own_earnings():
    # A single filer's own earned income binds when below the capped expenses.
    r = dependent_care_credit(3_000, 1, 1_200, agi=1_200, year=2023, knowledge_dir=KNOWLEDGE_DIR)
    assert r.allowed_expenses == 1_200
    assert r.credit == 420  # 35% x 1,200
    # The deemed $250/$500 student/disabled rule is quoted as agent judgment.
    assert "$250 per month" in r.work and "judgment" in r.work


@pytest.mark.parametrize(
    ("year", "cap_one", "cap_two", "max_pct"),
    [
        (2019, 3_000, 6_000, "0.35"),
        (2020, 3_000, 6_000, "0.35"),
        (2021, 8_000, 16_000, "0.50"),
        (2022, 3_000, 6_000, "0.35"),
        (2023, 3_000, 6_000, "0.35"),
        (2024, 3_000, 6_000, "0.35"),
    ],
)
def test_dependent_care_ships_for_every_supported_year(year, cap_one, cap_two, max_pct):
    one = dependent_care_credit(99_999, 1, 99_999, agi=0, year=year, knowledge_dir=KNOWLEDGE_DIR)
    two = dependent_care_credit(99_999, 2, 99_999, agi=0, year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert one.allowed_expenses == cap_one
    assert two.allowed_expenses == cap_two
    assert one.applicable_percentage == Decimal(max_pct)
    assert one.citation.url == f"https://www.irs.gov/pub/irs-prior/i2441--{year}.pdf"


def test_dependent_care_missing_block_error_is_prescriptive(tmp_path):
    # A pack without tax.dependent_care must refuse with the exact fix.
    import yaml

    raw = yaml.safe_load((KNOWLEDGE_DIR / "federal" / "2023.yaml").read_text())
    del raw["tax"]["dependent_care"]
    fed = tmp_path / "federal"
    fed.mkdir()
    (fed / "2023.yaml").write_text(yaml.dump(raw, sort_keys=False))
    with pytest.raises(ValueError, match=r"tax\.dependent_care") as exc:
        dependent_care_credit(3_000, 1, 30_000, agi=20_000, year=2023, knowledge_dir=tmp_path)
    assert "Form 2441" in str(exc.value)


def test_dependent_care_input_validation():
    with pytest.raises(ValueError, match="qualifying_persons must be >= 1"):
        dependent_care_credit(3_000, 0, 30_000, agi=20_000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="expenses must be >= 0"):
        dependent_care_credit(-1, 1, 30_000, agi=20_000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="earned_income must be >= 0"):
        dependent_care_credit(3_000, 1, -5, agi=20_000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="employer_benefits must be >= 0"):
        dependent_care_credit(3_000, 1, 30_000, agi=20_000, employer_benefits=-1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="unknown filing_status"):
        dependent_care_credit(3_000, 1, 30_000, agi=20_000, filing_status="widowed", knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# state_tax (Phase G item G4 — the flat-rate state income-tax line)
# ---------------------------------------------------------------------------
# Goldens are HAND-DERIVED from the verified 2023 state DOR data (rates and
# exemption/deduction amounts quoted in each state pack's tax block):
#   tax = irs_round(max(0, base - exemptions - standard deduction) x flat rate)


def test_state_tax_il_golden_single_one_exemption():
    # (50,000 - 2,425) x 0.0495 = 47,575 x 0.0495 = 2,354.9625 -> 2,355.
    r = state_tax("il", 50_000, exemptions_count=1, knowledge_dir=KNOWLEDGE_DIR)
    assert r.tax == 2_355
    assert r.base_after_exemptions == 47_575
    assert r.rate == Decimal("0.0495")
    assert r.base_kind == "federal_agi"
    assert "IL-1040 Line 12" in r.work and "4.95%" in r.work
    assert "tax.illinois.gov" in r.citation.url
    # The base the CALLER must supply is documented in the work (fed AGI +/- IL mods).
    assert "federal AGI" in r.work


def test_state_tax_il_mfj_both_exemptions():
    # (80,000 - 2 x 2,425) x 0.0495 = 75,150 x 0.0495 = 3,719.925 -> 3,720.
    r = state_tax(
        "il", 80_000, exemptions_count=2, filing_status="married_filing_jointly",
        knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.tax == 3_720
    assert r.base_after_exemptions == 75_150


def test_state_tax_il_dependents_are_refused_as_unverified():
    # IL's per-dependent amount (Line 10d via Schedule IL-E/EIC) was NOT independently
    # verified, so the pack ships no 'dependent' amount — never a silent $0.
    with pytest.raises(ValueError) as exc:
        state_tax("il", 50_000, exemptions_count=1, dependents_count=1, knowledge_dir=KNOWLEDGE_DIR)
    msg = str(exc.value)
    assert "dependent" in msg and "IL 2023" in msg
    # The IL work string surfaces the unshipped-dependent disclosure from the pack notes.
    r = state_tax("il", 50_000, exemptions_count=1, knowledge_dir=KNOWLEDGE_DIR)
    assert "Schedule IL-E/EIC" in r.work and "not independently verified" in r.work


def test_state_tax_pa_no_exemption_flat_multiply():
    # PA: 61,000 x 0.0307 = 1,872.70 -> 1,873 — the op multiplies the supplied
    # eight-class PA base only (no exemptions, no standard deduction).
    r = state_tax("pa", 61_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.tax == 1_873
    assert r.base_after_exemptions == 61_000
    assert r.rate == Decimal("0.0307")
    assert r.base_kind == "state_gross_income"
    assert "eight" in r.work and "loss in one class" in r.work.lower()
    assert "no exemptions or standard deduction" in r.work
    assert "pa.gov" in r.citation.url


def test_state_tax_pa_rejects_exemption_counts():
    with pytest.raises(ValueError, match="no 'personal' exemption"):
        state_tax("pa", 61_000, exemptions_count=1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="no 'dependent' exemption"):
        state_tax("pa", 61_000, dependents_count=2, knowledge_dir=KNOWLEDGE_DIR)


def test_state_tax_in_golden_with_dependent():
    # (50,000 - 1,000 personal - 1,000 dependent) x 0.0315 = 48,000 x 0.0315 = 1,512.
    r = state_tax("in", 50_000, exemptions_count=1, dependents_count=1, knowledge_dir=KNOWLEDGE_DIR)
    assert r.tax == 1_512
    assert r.base_after_exemptions == 48_000
    assert r.rate == Decimal("0.0315")
    # County add-on taxes are disclosed as not modeled (prescriptive work note).
    assert "COUNTY" in r.work or "county" in r.work
    # The verifier's first-year $3,000 mechanics are quoted as a note, not encoded.
    assert "could have been claimed" in r.work
    assert "forms.in.gov" in r.citation.url


def test_state_tax_mi_golden_exemptions_apply_to_dependents_too():
    # MI: taxpayer, spouse, and dependents all take the same $5,400 (line 9a):
    # (60,000 - 3 x 5,400) x 0.0405 = 43,800 x 0.0405 = 1,773.90 -> 1,774.
    r = state_tax(
        "mi", 60_000, exemptions_count=2, dependents_count=1,
        filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.tax == 1_774
    assert r.base_after_exemptions == 43_800
    assert r.rate == Decimal("0.0405")
    # The one-year-only rate caveat ships in the pack notes and reaches the work.
    assert "ONE-YEAR" in r.work
    assert "michigan.gov" in r.citation.url


def test_state_tax_nc_standard_deduction_by_status():
    # Single: (50,000 - 12,750) x 0.0475 = 37,250 x 0.0475 = 1,769.375 -> 1,769.
    r = state_tax("nc", 50_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.tax == 1_769
    assert r.base_after_exemptions == 37_250
    # MFJ: (80,000 - 25,500) x 0.0475 = 54,500 x 0.0475 = 2,588.75 -> 2,589.
    mfj = state_tax("nc", 80_000, filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert mfj.tax == 2_589
    # HoH: (50,000 - 19,125) x 0.0475 = 30,875 x 0.0475 = 1,466.5625 -> 1,467.
    hoh = state_tax("nc", 50_000, filing_status="head_of_household", knowledge_dir=KNOWLEDGE_DIR)
    assert hoh.tax == 1_467
    # The AGI-tiered child deduction is NOT a per-dependent exemption here.
    with pytest.raises(ValueError, match="child deduction"):
        state_tax("nc", 50_000, dependents_count=2, knowledge_dir=KNOWLEDGE_DIR)
    assert "child deduction" in r.work.lower()
    assert "ncdor.gov" in r.citation.url


def test_state_tax_nc_qss_uses_the_mfj_column():
    qss = state_tax("nc", 80_000, filing_status="qualifying_surviving_spouse", knowledge_dir=KNOWLEDGE_DIR)
    mfj = state_tax("nc", 80_000, filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert qss.tax == mfj.tax == 2_589
    assert "married-filing-jointly column" in qss.work


def test_state_tax_co_matches_the_booklet_tax_table_row():
    # The 2023 CO booklet tax table row $30,700-$30,800 prints $1,353 — exactly
    # 4.4% of the $30,750 midpoint: 30,750 x 0.044 = 1,353.00 -> 1,353.
    r = state_tax("co", 30_750, knowledge_dir=KNOWLEDGE_DIR)
    assert r.tax == 1_353
    assert r.base_after_exemptions == 30_750
    assert r.rate == Decimal("0.044")
    assert r.base_kind == "federal_taxable_income"
    # The caller supplies federal TAXABLE income (not AGI) — documented in the work,
    # along with the booklet-table rounding caveat.
    assert "TAXABLE income" in r.work
    assert "tax table" in r.work
    assert "tax.colorado.gov" in r.citation.url


def test_state_tax_ky_one_standard_deduction_even_mfj():
    # KY: ONE $2,980 standard deduction per return, NOT doubled for a joint return:
    # (50,000 - 2,980) x 0.045 = 47,020 x 0.045 = 2,115.90 -> 2,116 for both statuses.
    single = state_tax("ky", 50_000, knowledge_dir=KNOWLEDGE_DIR)
    mfj = state_tax("ky", 50_000, filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert single.tax == mfj.tax == 2_116
    assert single.base_after_exemptions == 47_020
    assert single.rate == Decimal("0.045")
    assert "ONE $2,980" in single.work or "NOT doubled" in single.work
    # The unverified KY personal credits / family size credit are disclosed as not shipped.
    assert "Family Size Tax Credit" in single.work
    assert "revenue.ky.gov" in single.citation.url


def test_state_tax_az_standard_deduction_and_verifier_exemption_lines():
    # AZ single: (50,000 - 13,850) x 0.025 = 36,150 x 0.025 = 903.75 -> 904.
    r = state_tax("az", 50_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.tax == 904
    assert r.base_after_exemptions == 36_150
    assert r.rate == Decimal("0.025")
    # MFJ: (100,000 - 27,700) x 0.025 = 72,300 x 0.025 = 1,807.50 -> 1,808.
    mfj = state_tax("az", 100_000, filing_status="married_filing_jointly", knowledge_dir=KNOWLEDGE_DIR)
    assert mfj.tax == 1_808
    # The VERIFIER's corrected Form 140 line 38-41 exemptions ship as data and are
    # disclosed (not applied): age 65+ $2,100 / blind $1,500 / other $2,300 /
    # qualifying parent-grandparent $10,000.
    for needle in ("$2,100", "$1,500", "$2,300", "$10,000", "Line 38", "Line 41"):
        assert needle in r.work, needle
    # Dependents are the Line 49 CREDIT in AZ, never a base exemption.
    with pytest.raises(ValueError, match="no 'dependent' exemption"):
        state_tax("az", 50_000, dependents_count=1, knowledge_dir=KNOWLEDGE_DIR)
    # AZ has no personal exemption either.
    with pytest.raises(ValueError, match="no 'personal' exemption"):
        state_tax("az", 50_000, exemptions_count=1, knowledge_dir=KNOWLEDGE_DIR)
    assert "Dependent Tax Credit" in r.work
    assert "azdor.gov" in r.citation.url


def test_state_tax_base_never_goes_negative():
    # Exemptions + deduction above the base clamp to $0, never negative tax.
    r = state_tax("il", 2_000, exemptions_count=1, knowledge_dir=KNOWLEDGE_DIR)
    assert r.tax == 0 and r.base_after_exemptions == 0
    assert "clamped to $0" in r.work
    nc = state_tax("nc", 10_000, knowledge_dir=KNOWLEDGE_DIR)
    assert nc.tax == 0 and nc.base_after_exemptions == 0


def test_state_tax_unknown_state_lists_the_supported_ones():
    # TX has no income tax and no pack; the error must list the shipped flat states.
    with pytest.raises(ValueError) as exc:
        state_tax("tx", 50_000, knowledge_dir=KNOWLEDGE_DIR)
    msg = str(exc.value)
    for code in ("az", "co", "il", "in", "ky", "mi", "nc", "pa"):
        assert code in msg
    assert "get_sources" in msg


def test_state_tax_state_without_block_is_refused_prescriptively(tmp_path):
    # Every real 2023 pack now ships a block, so the refusal path is proven
    # with a synthetic pack that has none — same prescriptive error shape.
    d = tmp_path / "states" / "zx"
    d.mkdir(parents=True)
    (d / "2023.yaml").write_text(
        "jurisdiction: states/zx\ntax_year: 2023\nincome_tax: true\n"
        "conforms_to_federal_treaties: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc:
        state_tax("zx", 50_000, knowledge_dir=tmp_path)
    msg = str(exc.value)
    assert "'zx'" in msg
    assert "never invent" in msg


def test_state_tax_input_validation():
    with pytest.raises(ValueError, match="exemptions_count must be >= 0"):
        state_tax("il", 50_000, exemptions_count=-1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(TypeError, match="dependents_count"):
        state_tax("in", 50_000, dependents_count=True, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="unknown filing_status"):
        state_tax("nc", 50_000, filing_status="married", knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="not a number"):
        state_tax("pa", "lots", knowledge_dir=KNOWLEDGE_DIR)


def test_state_tax_accepts_string_and_float_money():
    assert state_tax("pa", "61,000", knowledge_dir=KNOWLEDGE_DIR).tax == 1_873
    assert state_tax("pa", 61_000.00, knowledge_dir=KNOWLEDGE_DIR).tax == 1_873
    assert state_tax("PA", 61_000, knowledge_dir=KNOWLEDGE_DIR).tax == 1_873  # case-insensitive


# ── G4 second tranche: the graduated-bracket engine (synthetic schedules) ──
# Real-state goldens live below the synthetic block; these prove the marginal
# math itself with a made-up two-letter state so no live data is involved.

SYNTHETIC_GRADUATED_YAML = """\
jurisdiction: states/zz
tax_year: 2023
income_tax: true
conforms_to_federal_treaties: true
tax:
  citation:
    source: "Synthetic engine fixture (not a real state)"
    url: https://www.irs.gov/
  base: federal_agi
  tax_line: "ZZ-1 Line 9 (synthetic)"
  brackets:
    single: &zz_single
      - {over: 0, but_not_over: 10000, rate: 0.02}
      - {over: 10000, but_not_over: 50000, rate: 0.04}
      - {over: 50000, but_not_over: null, rate: 0.06}
    married_filing_separately: *zz_single
    head_of_household:
      - {over: 0, but_not_over: 15000, rate: 0.02}
      - {over: 15000, but_not_over: 75000, rate: 0.04}
      - {over: 75000, but_not_over: null, rate: 0.06}
    married_filing_jointly:
      - {over: 0, but_not_over: 20000, rate: 0.02}
      - {over: 20000, but_not_over: 100000, rate: 0.04}
      - {over: 100000, but_not_over: null, rate: 0.06}
  exemptions:
    personal: {amount: 1000, note: "ZZ-1 Line 6 (synthetic)"}
    dependent: {amount: 500, note: "ZZ-1 Line 7 (synthetic)"}
  standard_deduction:
    single: 4000
    married_filing_jointly: 8000
    married_filing_separately: 4000
    head_of_household: 6000
  notes:
    - "Synthetic pack for engine tests only."
"""

SYNTHETIC_ZERO_FLOOR_YAML = """\
jurisdiction: states/zy
tax_year: 2023
income_tax: true
conforms_to_federal_treaties: true
tax:
  citation:
    source: "Synthetic zero-floor fixture (Ohio/Mississippi shape)"
    url: https://www.irs.gov/
  base: state_taxable_income
  tax_line: "ZY-1 Line 3 (synthetic)"
  brackets:
    single: &zy_all
      - {over: 0, but_not_over: 26050, rate: 0}
      - {over: 26050, but_not_over: null, rate: 0.0275}
    married_filing_jointly: *zy_all
    married_filing_separately: *zy_all
    head_of_household: *zy_all
"""


@pytest.fixture()
def synthetic_state_dir(tmp_path):
    for code, text in (("zz", SYNTHETIC_GRADUATED_YAML), ("zy", SYNTHETIC_ZERO_FLOOR_YAML)):
        d = tmp_path / "states" / code
        d.mkdir(parents=True)
        (d / "2023.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_state_tax_graduated_marginal_math(synthetic_state_dir):
    # single, 1 exemption: base_after = 60,000 - 1,000 - 4,000 std = 55,000;
    # tax = 2% x 10,000 + 4% x 40,000 + 6% x 5,000 = 200 + 1,600 + 300 = 2,100.
    r = state_tax("zz", 60_000, exemptions_count=1, knowledge_dir=synthetic_state_dir)
    assert r.tax == 2_100
    assert r.base_after_exemptions == 55_000
    assert r.rate is None
    assert r.rate_structure == "graduated"
    assert r.marginal_rate == Decimal("0.06")
    assert r.base_kind == "federal_agi"
    # Every bracket's contribution shows in the work, plus the schedule used.
    assert "[single schedule]" in r.work
    assert "$200.00" in r.work and "$1,600.00" in r.work and "$300.00" in r.work


def test_state_tax_graduated_uses_the_status_schedule(synthetic_state_dir):
    # MFJ same inputs: base_after = 60,000 - 2,000 - 8,000 = 50,000;
    # tax = 2% x 20,000 + 4% x 30,000 = 400 + 1,200 = 1,600 — a different schedule,
    # not a doubling of the single result.
    r = state_tax(
        "zz", 60_000, exemptions_count=2, filing_status="married_filing_jointly",
        knowledge_dir=synthetic_state_dir,
    )
    assert r.tax == 1_600
    assert r.base_after_exemptions == 50_000
    assert r.marginal_rate == Decimal("0.04")
    # Qualifying surviving spouse resolves to the MFJ schedule (same math).
    qss = state_tax(
        "zz", 60_000, exemptions_count=2, filing_status="qualifying_surviving_spouse",
        knowledge_dir=synthetic_state_dir,
    )
    assert qss.tax == 1_600
    assert "married_filing_jointly" in qss.work


def test_state_tax_graduated_rounds_half_up(synthetic_state_dir):
    # base_after = 10,011 (no exemptions/std? single std 4,000 applies):
    # pick base 14,011 -> base_after 10,011; tax = 200 + 4% x 11 = 200.44 -> 200;
    # base 14,014 -> base_after 10,014; tax = 200 + 0.56 = 200.56 -> 201.
    assert state_tax("zz", 14_011, knowledge_dir=synthetic_state_dir).tax == 200
    assert state_tax("zz", 14_014, knowledge_dir=synthetic_state_dir).tax == 201


def test_state_tax_graduated_zero_floor(synthetic_state_dir):
    # Ohio/Mississippi shape: 0% to $26,050 then 2.75%.
    # 30,000: (30,000 - 26,050) x 2.75% = 3,950 x 0.0275 = 108.625 -> 109.
    r = state_tax("zy", 30_000, knowledge_dir=synthetic_state_dir)
    assert r.tax == 109
    assert r.marginal_rate == Decimal("0.0275")
    assert r.base_kind == "state_taxable_income"
    # Below the floor: $0 tax, marginal rate is the floor's 0%.
    low = state_tax("zy", 20_000, knowledge_dir=synthetic_state_dir)
    assert low.tax == 0
    assert low.marginal_rate == Decimal("0")


def test_state_tax_graduated_dependent_exemptions_apply(synthetic_state_dir):
    # base_after = 30,000 - 1,000 - 2 x 500 - 4,000 = 24,000;
    # tax = 200 + 4% x 14,000 = 200 + 560 = 760.
    r = state_tax("zz", 30_000, exemptions_count=1, dependents_count=2, knowledge_dir=synthetic_state_dir)
    assert r.tax == 760
    assert r.base_after_exemptions == 24_000


def test_state_tax_flat_result_carries_the_new_structure_fields():
    # The flat path is unchanged math-wise but now reports structure + marginal rate.
    r = state_tax("il", 50_000, exemptions_count=1, knowledge_dir=KNOWLEDGE_DIR)
    assert r.rate_structure == "flat"
    assert r.marginal_rate == r.rate == Decimal("0.0495")


# ── G4 second tranche: real-state graduated goldens (two-pass verified data) ──
# One row per shipped test vector from the verified 2023 packs (verification
# pass 2026-07-24: every figure checked against the official state 2023
# instructions; every vector recomputed by hand AND through the engine by
# scripts/assemble_state_tax_blocks.py before the yaml was written). Rows tied
# to printed booklet tax-table rows / worked examples are noted in the packs.
GRADUATED_GOLDENS = [
    # (state, taxable_base, filing_status, exemptions_count, dependents_count,
    #  expected base_after_exemptions, expected tax)
    ('al', 2_000, 'single', 0, 0, 2_000, 70),
    ('al', 3_050, 'single', 0, 0, 3_050, 113),
    ('al', 23_350, 'married_filing_jointly', 0, 0, 23_350, 1_088),
    ('al', 50_000, 'head_of_household', 0, 0, 50_000, 2_460),
    ('al', 150_000, 'married_filing_separately', 0, 0, 150_000, 7_460),
    ('ar', 30_000, 'single', 0, 0, 27_660, 703),
    ('ar', 60_000, 'married_filing_jointly', 0, 0, 55_320, 2_003),
    ('ar', 12_000, 'single', 0, 0, 9_660, 87),
    ('ar', 20_000, 'head_of_household', 0, 0, 17_660, 328),
    ('ar', 91_940, 'married_filing_separately', 0, 0, 89_600, 3_614),
    ('ca', 150_000, 'single', 0, 0, 144_637, 10_104),
    ('ca', 800_000, 'married_filing_jointly', 0, 0, 789_274, 67_618),
    ('ca', 60_000, 'head_of_household', 0, 0, 49_274, 777),
    ('ca', 1_000_000, 'married_filing_separately', 0, 0, 994_637, 104_330),
    ('dc', 85_000, 'single', 0, 0, 71_150, 4_448),
    ('dc', 500_000, 'married_filing_jointly', 0, 0, 472_300, 40_213),
    ('dc', 60_000, 'married_filing_separately', 0, 0, 46_150, 2_600),
    ('dc', 45_000, 'head_of_household', 0, 0, 24_200, 1_252),
    ('dc', 1_200_000, 'single', 0, 0, 1_186_150, 111_536),
    ('de', 75_000, 'single', 0, 0, 71_750, 3_719),
    ('de', 130_000, 'married_filing_jointly', 0, 0, 123_500, 7_135),
    ('de', 30_000, 'married_filing_separately', 0, 0, 26_750, 1_098),
    ('de', 18_000, 'head_of_household', 0, 0, 14_750, 489),
    ('de', 4_000, 'single', 0, 0, 750, 0),
    ('ga', 13_225, 'single', 0, 0, 5_125, 138),
    ('ga', 92_378, 'married_filing_jointly', 0, 0, 77_878, 4_243),
    ('ga', 60_000, 'single', 0, 0, 51_900, 2_812),
    ('ga', 30_000, 'married_filing_separately', 0, 1, 19_750, 1_018),
    ('ga', 16_600, 'head_of_household', 0, 1, 5_500, 130),
    ('id', 60_000, 'single', 0, 0, 46_150, 2_416),
    ('id', 100_000, 'married_filing_jointly', 0, 0, 72_300, 3_673),
    ('id', 25_000, 'head_of_household', 0, 0, 4_200, 0),
    ('id', 18_589, 'single', 0, 0, 4_739, 15),
    ('id', 40_000, 'married_filing_separately', 0, 0, 26_150, 1_256),
    ('ks', 50_750, 'single', 1, 0, 45_000, 2_108),
    ('ks', 130_000, 'married_filing_jointly', 2, 2, 113_000, 5_526),
    ('ks', 40_000, 'head_of_household', 2, 1, 27_250, 1_108),
    ('ks', 20_000, 'married_filing_separately', 1, 0, 13_750, 426),
    ('ks', 10_000, 'married_filing_jointly', 2, 0, 0, 0),
    ('la', 16_125, 'single', 0, 0, 16_125, 275),
    ('la', 32_125, 'married_filing_jointly', 0, 0, 32_125, 545),
    ('la', 50_875, 'head_of_household', 0, 0, 50_875, 1_414),
    ('la', 11_125, 'single', 0, 2, 9_125, 86),
    ('la', 150_000, 'married_filing_jointly', 0, 2, 148_000, 4_961),
    ('md', 50_000, 'single', 0, 0, 50_000, 2_323),
    ('md', 140_000, 'single', 0, 0, 140_000, 6_735),
    ('md', 300_000, 'married_filing_separately', 0, 0, 300_000, 15_635),
    ('md', 200_000, 'married_filing_jointly', 0, 0, 200_000, 9_635),
    ('md', 350_000, 'head_of_household', 0, 0, 350_000, 17_948),
    ('me', 50_000, 'single', 1, 0, 31_450, 1_890),
    ('me', 160_000, 'married_filing_jointly', 2, 0, 122_900, 7_857),
    ('me', 30_000, 'head_of_household', 1, 0, 4_500, 261),
    ('me', 60_000, 'married_filing_separately', 1, 0, 41_450, 2_565),
    ('me', 30_800, 'single', 1, 0, 12_250, 711),
    ('mn', 150_000, 'single', 0, 0, 136_175, 9_217),
    ('mn', 130_000, 'married_filing_jointly', 0, 2, 92_750, 5_670),
    ('mn', 200_000, 'married_filing_separately', 0, 0, 186_175, 14_053),
    ('mn', 130_000, 'head_of_household', 0, 1, 104_400, 6_563),
    ('mo', 3_090, 'single', 0, 0, 3_090, 41),
    ('mo', 12_000, 'head_of_household', 0, 0, 12_000, 411),
    ('mo', 60_000, 'married_filing_jointly', 0, 0, 60_000, 2_787),
    ('mo', 1_000, 'married_filing_separately', 0, 0, 1_000, 0),
    ('ms', 50_000, 'single', 0, 0, 41_700, 1_585),
    ('ms', 100_000, 'married_filing_jointly', 0, 2, 80_400, 3_520),
    ('ms', 15_000, 'head_of_household', 0, 1, 2_100, 0),
    ('ms', 19_310, 'single', 0, 0, 11_010, 51),
    ('ms', 40_000, 'married_filing_separately', 0, 0, 31_700, 1_085),
    ('mt', 25_000, 'single', 0, 0, 25_000, 1_032),
    ('mt', 60_000, 'married_filing_jointly', 0, 0, 60_000, 3_394),
    ('mt', 12_000, 'head_of_household', 0, 0, 12_000, 284),
    ('mt', 15_500, 'married_filing_separately', 0, 0, 15_500, 449),
    ('mt', 3_000, 'single', 0, 0, 3_000, 30),
    ('nd', 30_000, 'single', 0, 0, 30_000, 0),
    ('nd', 90_375, 'married_filing_jointly', 0, 0, 90_375, 305),
    ('nd', 150_000, 'single', 0, 0, 150_000, 2_053),
    ('nd', 300_000, 'single', 0, 0, 300_000, 5_385),
    ('nd', 400_000, 'married_filing_jointly', 0, 0, 400_000, 7_029),
    ('nd', 275_000, 'head_of_household', 0, 0, 275_000, 4_328),
    ('nd', 200_000, 'married_filing_separately', 0, 0, 200_000, 3_515),
    ('ne', 60_000, 'single', 0, 0, 52_100, 2_506),
    ('ne', 120_000, 'married_filing_jointly', 0, 0, 104_200, 5_011),
    ('ne', 50_000, 'head_of_household', 0, 0, 38_400, 1_319),
    ('ne', 30_000, 'married_filing_separately', 0, 0, 22_100, 737),
    ('ne', 10_000, 'single', 0, 0, 2_100, 52),
    ('nj', 60_000, 'single', 1, 0, 59_000, 1_767),
    ('nj', 155_000, 'married_filing_jointly', 2, 2, 150_000, 5_513),
    ('nj', 77_500, 'head_of_household', 1, 1, 75_000, 1_470),
    ('nj', 40_000, 'married_filing_separately', 1, 0, 39_000, 683),
    ('nj', 1_200_000, 'single', 1, 0, 1_199_000, 95_966),
    ('ny', 50_000, 'single', 0, 0, 42_000, 2_145),
    ('ny', 100_000, 'married_filing_jointly', 0, 2, 81_950, 4_175),
    ('ny', 300_000, 'head_of_household', 0, 1, 287_800, 16_638),
    ('ny', 1_500_000, 'married_filing_separately', 0, 0, 1_492_000, 111_407),
    ('oh', 20_000, 'single', 0, 0, 20_000, 0),
    ('oh', 60_000, 'married_filing_jointly', 0, 0, 60_000, 934),
    ('oh', 110_000, 'single', 0, 0, 110_000, 2_402),
    ('oh', 200_000, 'head_of_household', 0, 0, 200_000, 5_774),
    ('ok', 50_000, 'single', 1, 0, 42_650, 1_837),
    ('ok', 10_000, 'married_filing_separately', 1, 0, 2_650, 16),
    ('ok', 20_000, 'head_of_household', 1, 1, 8_650, 103),
    ('ok', 130_000, 'married_filing_jointly', 2, 2, 113_300, 5_027),
    ('or', 80_710, 'married_filing_jointly', 0, 0, 75_500, 6_036),
    ('or', 152_605, 'single', 0, 0, 150_000, 13_128),
    ('or', 304_195, 'head_of_household', 0, 0, 300_000, 26_255),
    ('or', 10_605, 'married_filing_separately', 0, 0, 8_000, 459),
    ('ri', 60_000, 'single', 1, 0, 45_300, 1_699),
    ('ri', 95_000, 'married_filing_separately', 1, 0, 80_275, 3_079),
    ('ri', 150_000, 'married_filing_jointly', 2, 2, 111_150, 4_545),
    ('ri', 220_000, 'head_of_household', 1, 2, 190_850, 8_627),
    ('va', 60_000, 'single', 1, 0, 51_070, 2_679),
    ('va', 120_000, 'married_filing_jointly', 2, 2, 100_280, 5_509),
    ('va', 13_000, 'married_filing_separately', 1, 0, 4_070, 92),
    ('va', 40_000, 'head_of_household', 1, 1, 30_140, 1_476),
    ('va', 25_000, 'single', 1, 0, 16_070, 674),
    ('vt', 105_750, 'married_filing_jointly', 2, 0, 82_000, 2_947),
    ('vt', 261_850, 'single', 1, 0, 250_000, 16_659),
    ('vt', 125_100, 'head_of_household', 1, 2, 100_000, 4_622),
    ('vt', 131_850, 'married_filing_separately', 1, 0, 120_000, 6_970),
    ('vt', 41_850, 'single', 1, 0, 30_000, 1_005),
    ('wi', 150_000, 'single', 0, 0, 150_000, 7_577),
    ('wi', 500_000, 'married_filing_jointly', 0, 0, 500_000, 28_222),
    ('wi', 250_000, 'married_filing_separately', 0, 0, 250_000, 14_111),
    ('wi', 20_050, 'head_of_household', 0, 0, 20_050, 758),
    ('wv', 52_000, 'single', 1, 0, 50_000, 1_712),
    ('wv', 90_000, 'married_filing_jointly', 2, 2, 82_000, 3_310),
    ('wv', 35_000, 'married_filing_separately', 1, 1, 31_000, 1_143),
    ('wv', 20_000, 'head_of_household', 1, 1, 16_000, 425),
    ('wv', 11_000, 'single', 1, 0, 9_000, 212),]


@pytest.mark.parametrize(
    "code,base,status,n_ex,n_dep,expected_base_after,expected_tax",
    GRADUATED_GOLDENS,
    ids=[f"{r[0]}-{r[1]}-{r[2]}" for r in GRADUATED_GOLDENS],
)
def test_state_tax_graduated_golden(code, base, status, n_ex, n_dep, expected_base_after, expected_tax):
    r = state_tax(
        code, base, exemptions_count=n_ex, dependents_count=n_dep,
        filing_status=status, knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.base_after_exemptions == expected_base_after
    assert r.tax == expected_tax
    assert r.rate_structure == "graduated"
    assert r.rate is None


def test_state_tax_credit_exemption_states_refuse_counts():
    # OR/NE/CA-style states give per-person CREDITS, not income exemptions —
    # the packs ship no 'personal' key and the engine refuses nonzero counts
    # (never a silent $0). ME ships 'personal' but its dependents get a CREDIT.
    with pytest.raises(ValueError, match="no 'personal' exemption"):
        state_tax("or", 50_000, exemptions_count=1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="no 'personal' exemption"):
        state_tax("ne", 50_000, exemptions_count=1, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="no 'dependent' exemption"):
        state_tax("me", 50_000, exemptions_count=1, dependents_count=1, knowledge_dir=KNOWLEDGE_DIR)


def test_state_tax_oh_discloses_the_360_69_schedule_jump():
    # Ohio's published 2023 schedule is discontinuous ($360.69 at $26,050) —
    # marginal math can't reproduce it, so the pack's CRITICAL note (quoted in
    # the work) tells the caller exactly how the filed form differs.
    r = state_tax("oh", 60_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.tax == 934  # engine marginal math
    assert "360.69" in r.work and "BELOW the form's printed schedule" in r.work


def test_state_tax_ny_discloses_the_recapture_worksheet_mandate():
    # Above $107,650 NYAGI the filed form must use the benefit-recapture
    # worksheets — plain bracket math is WRONG there, and the work says so.
    r = state_tax("ny", 300_000, filing_status="head_of_household", dependents_count=1, knowledge_dir=KNOWLEDGE_DIR)
    assert "107,650" in r.work
    assert r.tax == 16_638


def test_state_tax_la_exemption_is_inside_the_zero_floor():
    # Louisiana's $4,500/$9,000 combined personal exemption-standard deduction
    # is BUILT INTO the zero-rate floor of the printed tables — exemptions_count
    # must be 0, and the head-of-household floor is the $9,000 one.
    r = state_tax("la", 16_125, knowledge_dir=KNOWLEDGE_DIR)
    assert r.base_after_exemptions == 16_125  # nothing subtracted off the top
    assert r.tax == 275
    hoh = state_tax("la", 50_875, filing_status="head_of_household", knowledge_dir=KNOWLEDGE_DIR)
    assert hoh.tax == 1_414
    with pytest.raises(ValueError, match="no 'personal' exemption"):
        state_tax("la", 16_125, exemptions_count=1, knowledge_dir=KNOWLEDGE_DIR)


# ── Cross-year state goldens (TY2024 / TY2025 cohorts) ──
# The 2023 GRADUATED_GOLDENS above cover the first cohort. These rows anchor the
# LATER years, and every one is auditable from the comment: flat-state rows are
# rate x base_after arithmetic (eight are exact .50 half-up ties), and the
# graduated rows are official worked examples or printed-table reproductions
# named in each pack's citation/notes. Rates move nearly every year — IN
# 3.15 -> 3.05 -> 3.00, MI's one-year 4.05 dip back to 4.25, KY 4.5 -> 4.0,
# GA 5.39 -> 5.19, LA/IA newly flat — so these rows are the year-to-year
# regression net for calc.state_tax's data-driven year lookup.
CROSS_YEAR_GOLDENS = [
    # (state, year, taxable_base, filing_status, exemptions_count, dependents_count,
    #  expected base_after_exemptions, expected tax)
    ('pa', 2024, 45_000, 'single', 0, 0, 45_000, 1_382),  # 45,000 x 3.07% = 1,381.50 -> 1,382 (.50 tie); PA has no SD/exemptions
    ('pa', 2025, 45_000, 'single', 0, 0, 45_000, 1_382),  # same rate 3.07% -> 1,382
    ('il', 2024, 51_000, 'single', 0, 0, 51_000, 2_525),  # 51,000 x 4.95% = 2,524.50 -> 2,525 (.50 tie)
    ('il', 2025, 51_000, 'single', 0, 0, 51_000, 2_525),  # rate held at 4.95% -> 2,525
    ('in', 2024, 50_000, 'single', 0, 0, 50_000, 1_525),  # 50,000 x 3.05% = 1,525 exactly
    ('in', 2025, 16_750, 'single', 0, 0, 16_750, 503),  # 16,750 x 3.00% = 502.50 -> 503 (.50 tie)
    ('mi', 2024, 72_600, 'single', 0, 0, 72_600, 3_086),  # 72,600 x 4.25% = 3,085.50 -> 3,086 (.50 tie)
    ('mi', 2025, 72_600, 'single', 0, 0, 72_600, 3_086),  # rate held 4.25% -> 3,086
    ('ky', 2024, 53_160, 'single', 0, 0, 50_000, 2_000),  # 53,160 - 3,160 one-per-return SD = 50,000 x 4% = 2,000
    ('az', 2024, 64_600, 'single', 0, 0, 50_000, 1_250),  # 64,600 - 14,600 federal-tracking SD = 50,000 x 2.5% = 1,250
    ('ut', 2023, 50_000, 'single', 0, 0, 50_000, 2_325),  # 50,000 x 4.65% = 2,325 (credit state: no SD/exemptions)
    ('ut', 2024, 50_000, 'single', 0, 0, 50_000, 2_275),  # 50,000 x 4.55% = 2,275
    ('ma', 2024, 54_400, 'single', 0, 0, 50_000, 2_500),  # 54,400 - 4,400 exemption = 50,000 x 5% = 2,500
    ('ga', 2024, 62_000, 'single', 0, 0, 50_000, 2_695),  # 62,000 - 12,000 SD = 50,000 x 5.39% = 2,695
    ('ga', 2025, 62_000, 'single', 0, 0, 50_000, 2_595),  # 62,000 - 12,000 SD = 50,000 x 5.19% = 2,595
    ('ia', 2025, 50_000, 'single', 0, 0, 50_000, 1_900),  # 50,000 x 3.8% flat (SF 2442) = 1,900
    ('la', 2025, 50_000, 'single', 0, 0, 37_500, 1_125),  # 50,000 - 12,500 SD = 37,500 x 3% = 1,125
    ('mt', 2024, 50_000, 'single', 0, 0, 50_000, 2_704),  # booklet's own worked example: 50,000 -> 2,704
    ('co', 2024, 30_850, 'single', 0, 0, 30_850, 1_311),  # reproduces the printed DR 0104 tax-table row
    ('nd', 2024, 100_000, 'single', 0, 0, 100_000, 1_031),  # 0%/1.95%/2.5% re-indexed schedule
    ('oh', 2024, 87_450, 'single', 0, 0, 87_450, 1_689),  # 0% floor to 26,050 then 2.75%: 1,688.50 -> 1,689 (.50 tie)
    ('wi', 2024, 29_380, 'single', 0, 0, 29_380, 1_171),  # re-indexed schedule: 1,170.50 -> 1,171 (.50 tie)
    ('vt', 2024, 96_850, 'married_filing_jointly', 0, 0, 82_000, 2_814),  # booklet example base 82,000 after 14,850 SD; exact math 2,813.625 -> 2,814 (printed 2,813, $1 constant divergence)
    ('ms', 2025, 50_000, 'single', 0, 0, 41_700, 1_395),  # 0% first 10,000 then 4.4% (HB 531 phase-in)
    ('nc', 2025, 53_350, 'married_filing_separately', 0, 0, 40_600, 1_726),  # 53,350 - 12,750 MFS SD = 40,600 x 4.25% = 1,725.50 -> 1,726 (.50 tie)
    ('az', 2025, 65_750, 'single', 0, 0, 50_000, 1_250),  # 65,750 - 15,750 OBBBA-tracking SD = 50,000 x 2.5% = 1,250
    ('co', 2025, 49_950, 'single', 0, 0, 49_950, 2_198),  # rate BACK to 4.4%: reproduces the printed 2025 table row $49,900-$50,000 -> $2,198
    ('ky', 2025, 103_270, 'married_filing_jointly', 0, 0, 100_000, 4_000),  # ONE $3,270 SD per return (never doubled) x 4% = 4,000
    ('ut', 2025, 45_100, 'single', 0, 0, 45_100, 2_030),  # HB 106 cut 4.55 -> 4.5%: 45,100 x 4.5% = 2,029.50 -> 2,030 (.50 tie); credit state, no SD
    ('ma', 2025, 60_000, 'head_of_household', 0, 2, 51_200, 2_560),  # 60,000 - 6,800 line 2a HoH exemption - 2 x 1,000 dependents = 51,200 x 5% = 2,560
]


@pytest.mark.parametrize(
    "code,year,base,status,n_ex,n_dep,expected_base_after,expected_tax",
    CROSS_YEAR_GOLDENS,
    ids=[f"{r[0]}-{r[1]}-{r[2]}" for r in CROSS_YEAR_GOLDENS],
)
def test_state_tax_cross_year_golden(
    code, year, base, status, n_ex, n_dep, expected_base_after, expected_tax
):
    r = state_tax(
        code, base, year=year, exemptions_count=n_ex, dependents_count=n_dep,
        filing_status=status, knowledge_dir=KNOWLEDGE_DIR,
    )
    assert r.base_after_exemptions == expected_base_after
    assert r.tax == expected_tax
    # The op must report the year's OWN citation, never a neighbouring year's.
    assert str(year) in r.citation.source or str(year) in r.citation.url


def test_state_tax_rate_progression_across_years():
    # The scheduled cuts are real data, not copy-forward: assert the engine sees a
    # DIFFERENT rate per year for the states that legislated changes.
    def rate(code, year):
        return state_tax(code, 10_000, year=year, knowledge_dir=KNOWLEDGE_DIR).rate

    assert rate("in", 2023) > rate("in", 2024) > rate("in", 2025)      # 3.15 -> 3.05 -> 3.00
    assert rate("mi", 2023) < rate("mi", 2024) == rate("mi", 2025)     # 4.05 was one-year only
    assert rate("ky", 2023) > rate("ky", 2024)                          # 4.5 -> 4.0
    assert rate("ga", 2024) > rate("ga", 2025)                          # 5.39 -> 5.19 (HB 111)
    assert rate("ut", 2023) > rate("ut", 2024)                          # 4.65 -> 4.55 (SB 69)
    assert rate("pa", 2023) == rate("pa", 2024) == rate("pa", 2025)     # 3.07 unmoved since 2004
