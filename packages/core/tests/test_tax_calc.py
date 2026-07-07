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
    education_credits,
    eitc,
    excess_ss,
    irs_round,
    niit,
    presence_days,
    presence_days_by_year,
    ptc_annual,
    se_tax,
    standard_deduction,
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
