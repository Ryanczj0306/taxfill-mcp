"""Multi-year knowledge-pack tests (M3-KNOW-1): 2019-2022 and 2024.

The M2 form packs span 2019-2024 but only knowledge/federal/2023.yaml shipped
engine numbers, so calc/estimate hard-failed (FileNotFoundError) for every
other year. This module ships the missing five year packs and pins them.

Offline by design: every figure below is a PUBLISHED IRS value transcribed
from the official source (Rev. Proc., Schedule SE, the Tax Table booklet,
Pub 501, Schedule 8812). The GOLDEN assertions are LITERAL published integers,
NOT values recomputed by the engine — if the engine disagrees with a golden
figure, the engine (or the pack) is wrong, never the fixture (dev plan
section 10). Sources are cited per year in GOLDEN below.

Calc API usage mirrors packages/core/tests/test_tax_calc.py: every call passes
``year=`` and ``knowledge_dir=KNOWLEDGE_DIR``.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from taxfill_core.calc import se_tax, standard_deduction, tax_from_taxable_income
from taxfill_core.knowledge import load_knowledge

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"

# The five years this module ships (2023 already shipped and is tested in
# test_tax_calc.py / test_knowledge.py / test_knowledge_m3.py).
YEARS = (2019, 2020, 2021, 2022, 2024)


# ---------------------------------------------------------------------------
# Per-year GOLDEN fixtures — published IRS values, transcribed (not computed).
#
# std_single   : that year's single standard deduction (Rev. Proc. Section
#                3.15/3.16), independently cross-confirmed by Pub 501's
#                single under-65 filing threshold.
# ss_wage_base : Schedule SE line 7 social security wage base for the year.
# table_25300  : the published Tax Table row [25,300 - 25,350). The MFJ value
#                is the booklet's OWN printed worked example for $25,300
#                taxable income (so it is a doubly-published anchor).
# ctc          : (per_qualifying_child, additional_ctc_refundable_cap_per_child).
# rate_top_single : the dollar threshold where the 37% bracket begins for a
#                   single filer (Rev. Proc. Section 3.01, Table 3).
# ---------------------------------------------------------------------------
GOLDEN = {
    # Rev. Proc. 2018-57; Schedule SE 2019; 2019 Tax Table (i1040tt--2019);
    # Schedule 8812 2019. https://www.irs.gov/pub/irs-drop/rp-18-57.pdf
    2019: {
        "std_single": 12200,
        "std_mfj": 24400,
        "std_mfs": 12200,
        "std_hoh": 18350,
        "ss_wage_base": 132900,
        "table_25300": {"single": 2845, "mfj": 2651},
        "ctc": (2000, 1400),
        "rate_top_single": 510300,
    },
    # Rev. Proc. 2019-44; Schedule SE 2020; 2020 Tax Table (i1040tt--2020).
    # https://www.irs.gov/pub/irs-drop/rp-19-44.pdf
    2020: {
        "std_single": 12400,
        "std_mfj": 24800,
        "std_mfs": 12400,
        "std_hoh": 18650,
        "ss_wage_base": 137700,
        "table_25300": {"single": 2842, "mfj": 2644},
        "ctc": (2000, 1400),
        "rate_top_single": 518400,
    },
    # Rev. Proc. 2020-45; Schedule SE 2021; 2021 Tax Table (i1040tt--2021);
    # 2021 Schedule 8812 (ARPA-expanded, fully refundable).
    # https://www.irs.gov/pub/irs-drop/rp-20-45.pdf
    2021: {
        "std_single": 12550,
        "std_mfj": 25100,
        "std_mfs": 12550,
        "std_hoh": 18800,
        "ss_wage_base": 142800,
        "table_25300": {"single": 2840, "mfj": 2641},
        "ctc": (3000, 3600),  # ARPA: $3,000 (6-17) / $3,600 (under 6), fully refundable
        "rate_top_single": 523600,
    },
    # Rev. Proc. 2021-45; Schedule SE 2022; 2022 Tax Table (i1040tt--2022);
    # Schedule 8812 2022 (ACTC cap $1,500).
    # https://www.irs.gov/pub/irs-drop/rp-21-45.pdf
    2022: {
        "std_single": 12950,
        "std_mfj": 25900,
        "std_mfs": 12950,
        "std_hoh": 19400,
        "ss_wage_base": 147000,
        "table_25300": {"single": 2834, "mfj": 2628},
        "ctc": (2000, 1500),
        "rate_top_single": 539900,
    },
    # Rev. Proc. 2023-34; Schedule SE 2024; 2024 Tax Table (i1040tt--2024);
    # Schedule 8812 2024 (ACTC cap $1,700).
    # https://www.irs.gov/pub/irs-drop/rp-23-34.pdf
    2024: {
        "std_single": 14600,
        "std_mfj": 29200,
        "std_mfs": 14600,
        "std_hoh": 21900,
        "ss_wage_base": 168600,
        "table_25300": {"single": 2807, "mfj": 2575},
        "ctc": (2000, 1700),
        "rate_top_single": 609350,
    },
}


# ---------------------------------------------------------------------------
# The pack loads and validates for every year.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", YEARS)
def test_pack_loads_and_identifies_itself(year):
    pack = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR)
    assert pack.jurisdiction == "federal"
    assert pack.tax_year == year
    # Core tax block + the required filing_thresholds / credits blocks present.
    assert pack.tax is not None
    assert pack.filing_thresholds is not None
    assert pack.credits is not None


@pytest.mark.parametrize("year", YEARS)
def test_every_year_ships_filing_logistics_blocks(year):
    # All shipped years carry the M3 logistics blocks so estimate/file_and_pay
    # never silently degrade for a supported year.
    pack = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR)
    assert pack.payment_options is not None
    assert pack.payment_options.check.payee == "United States Treasury"
    assert pack.mailing_addresses is not None
    assert pack.mailing_addresses.f1040_for_state("California").no_payment  # resolves
    assert pack.deadlines is not None
    assert pack.deadlines.refund_statute_of_limitations.years_from_filing == 3
    for block in (pack.payment_options, pack.mailing_addresses, pack.deadlines):
        assert block.citation.url.startswith("https://www.irs.gov/")


@pytest.mark.parametrize("year", YEARS)
def test_rate_schedules_have_seven_brackets_each(year):
    schedules = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).tax.rate_schedules.schedules
    assert set(schedules) == {
        "single",
        "married_filing_jointly",
        "married_filing_separately",
        "head_of_household",
    }
    for status, brackets in schedules.items():
        assert len(brackets) == 7, f"{year} {status}: expected 7 brackets"
        assert brackets[0].over == 0
        assert brackets[-1].but_not_over is None


@pytest.mark.parametrize("year", YEARS)
def test_every_tax_block_cited_to_irs_gov(year):
    tax = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).tax
    for block in (
        tax.rate_schedules,
        tax.tax_table,
        tax.tax_computation_worksheet,
        tax.standard_deduction,
        tax.se_tax,
    ):
        assert block.citation.url.startswith("https://www.irs.gov/")
        assert block.citation.source.strip()


# ---------------------------------------------------------------------------
# GOLDEN: published single standard deduction (literal integer, transcribed).
# Cross-confirmed by Pub 501's single under-65 filing threshold == std ded.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", YEARS)
def test_golden_standard_deduction(year):
    g = GOLDEN[year]
    assert standard_deduction("single", year=year, knowledge_dir=KNOWLEDGE_DIR).amount == g["std_single"]
    assert standard_deduction("married_filing_jointly", year=year, knowledge_dir=KNOWLEDGE_DIR).amount == g["std_mfj"]
    assert standard_deduction("married_filing_separately", year=year, knowledge_dir=KNOWLEDGE_DIR).amount == g["std_mfs"]
    assert standard_deduction("head_of_household", year=year, knowledge_dir=KNOWLEDGE_DIR).amount == g["std_hoh"]
    # QSS uses the MFJ amount.
    qss = standard_deduction("qualifying_surviving_spouse", year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert qss.amount == g["std_mfj"]


@pytest.mark.parametrize("year", YEARS)
def test_standard_deduction_filing_threshold_reconcile(year):
    pack = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR)
    sd = pack.tax.standard_deduction.amounts
    ft = pack.filing_thresholds.amounts
    # Non-elderly gross-income threshold equals that status's standard deduction.
    assert ft["single"]["under_65"] == sd["single"]
    assert ft["married_filing_jointly"]["both_under_65"] == sd["married_filing_jointly"]
    assert ft["head_of_household"]["under_65"] == sd["head_of_household"]
    assert ft["married_filing_separately"]["any_age"] == 5


# ---------------------------------------------------------------------------
# GOLDEN: published Tax Table row [25,300 - 25,350). The MFJ figure is the
# booklet's own printed worked example for $25,300 taxable income.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", YEARS)
def test_golden_tax_table_row_25300(year):
    g = GOLDEN[year]["table_25300"]
    single = tax_from_taxable_income(25300, "single", year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert single.tax == g["single"]
    assert single.method == "tax_table"
    assert single.inputs["table_row"] == {"at_least": 25300, "but_less_than": 25350}
    mfj = tax_from_taxable_income(25300, "married_filing_jointly", year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert mfj.tax == g["mfj"]
    assert mfj.method == "tax_table"


@pytest.mark.parametrize("year", YEARS)
def test_golden_top_bracket_threshold_single(year):
    # The 37% bracket's lower bound for a single filer (Rev. Proc. Section
    # 3.01, Table 3) — a transcribed published threshold.
    schedules = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).tax.rate_schedules.schedules
    assert schedules["single"][-1].over == GOLDEN[year]["rate_top_single"]
    assert schedules["single"][-1].rate == Decimal("0.37")


# ---------------------------------------------------------------------------
# The calc functions work for every year (regression for the FileNotFoundError
# that M3-KNOW-1 fixed: tax_from_taxable_income(50000,'single',2022) used to
# raise).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", YEARS)
def test_tax_from_taxable_income_runs_below_and_above_cutoff(year):
    below = tax_from_taxable_income(50000, "single", year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert below.method == "tax_table"
    assert below.tax > 0
    assert below.inputs["year"] == year
    above = tax_from_taxable_income(150000, "single", year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert above.method == "schedule"
    assert above.tax > 0


def test_2022_single_50000_no_longer_raises():
    # The exact case named in M3-KNOW-1: this previously hard-failed with
    # FileNotFoundError because knowledge/federal/2022.yaml did not exist.
    result = tax_from_taxable_income(50000, "single", year=2022, knowledge_dir=KNOWLEDGE_DIR)
    assert result.method == "tax_table"
    assert result.tax > 0


# ---------------------------------------------------------------------------
# GOLDEN: SE tax — the year's social security wage base caps the SS portion.
# net earnings = 200,000 x 0.9235 = 184,700 (> every year's wage base), so the
# SS portion equals (wage_base x 0.124) rounded to cents, a published anchor.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", YEARS)
def test_golden_se_tax_caps_ss_at_wage_base(year):
    base = GOLDEN[year]["ss_wage_base"]
    result = se_tax(200000, year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert result.net_earnings == Decimal("184700.00")
    # SS portion is capped at wage_base x 12.4%, to the cent (half up).
    expected_ss = (Decimal(base) * Decimal("0.124")).quantize(Decimal("0.01"))
    assert result.ss_portion == expected_ss
    # Medicare is uncapped: 184,700 x 2.9% = 5,356.30 (same every year).
    assert result.medicare_portion == Decimal("5356.30")
    assert result.se_tax > 0
    assert f"${base:,}" in result.work  # the wage base is shown in the work (comma-formatted)


@pytest.mark.parametrize("year", YEARS)
def test_se_tax_below_threshold(year):
    # A $400 profit is below the threshold (400 x 0.9235 = 369.40 < 400).
    result = se_tax(400, year=year, knowledge_dir=KNOWLEDGE_DIR)
    assert result.se_tax == 0
    assert result.net_earnings == Decimal("369.40")


# ---------------------------------------------------------------------------
# GOLDEN: Child Tax Credit per-child amount and refundable ACTC cap per year.
# 2021 is the ARPA-expanded year ($3,000/$3,600, fully refundable).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", YEARS)
def test_golden_child_tax_credit(year):
    ctc = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).credits.child_tax_credit
    per_child, actc_cap = GOLDEN[year]["ctc"]
    assert ctc["per_qualifying_child"] == per_child
    assert ctc["additional_ctc_refundable_cap_per_child"] == actc_cap
    assert ctc["credit_for_other_dependents"] == 500


def test_2021_ctc_is_arpa_expanded_and_fully_refundable():
    ctc = load_knowledge("federal", 2021, base_dir=KNOWLEDGE_DIR).credits.child_tax_credit
    assert ctc["per_qualifying_child"] == 3000          # age 6-17
    assert ctc["per_qualifying_child_under_6"] == 3600  # under age 6
    assert ctc["fully_refundable"] is True
    # Two-tier phase-out: the ARPA increase phases out at the lower thresholds.
    assert ctc["increased_amount_phaseout_threshold"]["single"] == 75000
    assert ctc["increased_amount_phaseout_threshold"]["head_of_household"] == 112500
    assert ctc["increased_amount_phaseout_threshold"]["married_filing_jointly"] == 150000
    # The $2,000 base phases out at the regular thresholds.
    assert ctc["base_credit_phaseout_threshold"]["married_filing_jointly"] == 400000
    assert ctc["base_credit_phaseout_threshold"]["single"] == 200000


def test_2021_eitc_reflects_arpa_expansion():
    eitc = load_knowledge("federal", 2021, base_dir=KNOWLEDGE_DIR).credits.earned_income_tax_credit
    # ARPA raised the investment-income limit to $10,000 for 2021 and the
    # childless max credit to $1,502.
    assert eitc["investment_income_limit"] == 10000
    assert eitc["by_qualifying_children"]["0"]["max_credit"] == 1502
