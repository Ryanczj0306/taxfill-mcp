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
    irs_round,
    niit,
    presence_days,
    presence_days_by_year,
    se_tax,
    standard_deduction,
    tax_from_taxable_income,
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
