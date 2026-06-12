"""Knowledge pack loader tests (knowledge.py, M1).

Offline by design: tests load the real shipped pack
(knowledge/federal/2023.yaml) from disk and build broken variants in
memory / tmp_path. No real taxpayer data is involved — knowledge packs
contain only published IRS figures.
"""

import copy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.knowledge import KnowledgePack, load_knowledge

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
FEDERAL_2023 = KNOWLEDGE_DIR / "federal" / "2023.yaml"


@pytest.fixture(scope="module")
def pack_2023() -> KnowledgePack:
    return load_knowledge("federal", 2023, base_dir=KNOWLEDGE_DIR)


@pytest.fixture()
def raw_2023() -> dict:
    return yaml.safe_load(FEDERAL_2023.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Loading the real shipped pack
# ---------------------------------------------------------------------------


def test_real_pack_loads_and_identifies_itself(pack_2023):
    assert pack_2023.jurisdiction == "federal"
    assert pack_2023.tax_year == 2023


def test_default_base_dir_resolves_source_checkout():
    pack = load_knowledge("federal", 2023)
    assert pack.tax_year == 2023


def test_rate_schedules_match_rev_proc_2022_38(pack_2023):
    schedules = pack_2023.tax.rate_schedules.schedules
    assert set(schedules) == {
        "single",
        "married_filing_jointly",
        "married_filing_separately",
        "head_of_household",
    }
    for brackets in schedules.values():
        assert len(brackets) == 7  # seven rates: 10/12/22/24/32/35/37
        assert brackets[0].over == 0
        assert brackets[-1].but_not_over is None
    # Spot-check published boundaries (Rev. Proc. 2022-38, Section 3.01).
    single = schedules["single"]
    assert [b.but_not_over for b in single[:-1]] == [11000, 44725, 95375, 182100, 231250, 578125]
    assert single[2].rate == Decimal("0.22")
    mfj = schedules["married_filing_jointly"]
    assert [b.but_not_over for b in mfj[:-1]] == [22000, 89450, 190750, 364200, 462500, 693750]
    mfs = schedules["married_filing_separately"]
    assert mfs[-1].over == 346875
    hoh = schedules["head_of_household"]
    assert [b.but_not_over for b in hoh[:-1]] == [15700, 59850, 95350, 182100, 231250, 578100]


def test_rates_are_exact_decimals_not_float_artifacts(pack_2023):
    rates = [b.rate for b in pack_2023.tax.rate_schedules.schedules["single"]]
    assert rates == [
        Decimal("0.1"),
        Decimal("0.12"),
        Decimal("0.22"),
        Decimal("0.24"),
        Decimal("0.32"),
        Decimal("0.35"),
        Decimal("0.37"),
    ]


def test_tax_table_structure_matches_published_booklet(pack_2023):
    table = pack_2023.tax.tax_table
    assert table.applies_below == 100000
    assert table.rounding == "half_up"
    bands = [(b.at_least, b.below, b.row_width) for b in table.row_bands]
    # The published bottom rows: [0,5), [5,15), [15,25), then $25-wide rows
    # to 3,000, then $50-wide rows to 100,000.
    assert bands == [(0, 5, 5), (5, 25, 10), (25, 3000, 25), (3000, 100000, 50)]
    assert pack_2023.tax.tax_computation_worksheet.applies_at_or_above == 100000


def test_standard_deduction_matches_rev_proc(pack_2023):
    spec = pack_2023.tax.standard_deduction
    assert spec.amounts == {
        "single": 13850,
        "married_filing_jointly": 27700,
        "married_filing_separately": 13850,
        "head_of_household": 20800,
    }
    assert spec.additional_aged_or_blind.married == 1500
    assert spec.additional_aged_or_blind.unmarried == 1850


def test_se_tax_params_match_schedule_se(pack_2023):
    se = pack_2023.tax.se_tax
    assert se.net_earnings_factor == Decimal("0.9235")
    assert se.ss_rate == Decimal("0.124")
    assert se.medicare_rate == Decimal("0.029")
    assert se.ss_wage_base == 160200
    assert se.minimum_net_earnings == 400


def test_every_block_carries_an_official_citation(pack_2023):
    tax = pack_2023.tax
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
# Prescriptive loader errors
# ---------------------------------------------------------------------------


def test_missing_year_names_exact_path_and_freshness_protocol():
    with pytest.raises(FileNotFoundError) as excinfo:
        load_knowledge("federal", 2019, base_dir=KNOWLEDGE_DIR)
    message = str(excinfo.value)
    assert str(KNOWLEDGE_DIR / "federal" / "2019.yaml") in message
    assert "freshness protocol" in message
    assert "sources.yaml" in message


def test_bad_jurisdiction_rejected_prescriptively():
    for bad in ("Federal", "states/CA", "california", "states/cali"):
        with pytest.raises(ValueError, match="two-letter lowercase"):
            load_knowledge(bad, 2023, base_dir=KNOWLEDGE_DIR)


def test_missing_base_dir_tells_caller_what_to_pass(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"base_dir=<path"):
        load_knowledge("federal", 2023, base_dir=tmp_path / "does-not-exist")


def test_non_mapping_yaml_rejected(tmp_path):
    pack_dir = tmp_path / "federal"
    pack_dir.mkdir()
    (pack_dir / "2023.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="YAML mapping"):
        load_knowledge("federal", 2023, base_dir=tmp_path)


def test_year_mismatch_between_filename_and_content(tmp_path, raw_2023):
    pack_dir = tmp_path / "federal"
    pack_dir.mkdir()
    # The real 2023 content saved under the wrong filename must not load.
    (pack_dir / "2024.yaml").write_text(yaml.safe_dump(raw_2023), encoding="utf-8")
    with pytest.raises(ValueError, match=r"declares jurisdiction 'federal', tax_year 2023"):
        load_knowledge("federal", 2024, base_dir=tmp_path)


# ---------------------------------------------------------------------------
# Schema validation (broken in-memory variants of the real pack)
# ---------------------------------------------------------------------------


def test_bracket_gap_rejected(raw_2023):
    raw = copy.deepcopy(raw_2023)
    raw["tax"]["rate_schedules"]["schedules"]["single"][1]["over"] = 12000  # gap after 11,000
    with pytest.raises(ValidationError, match="contiguous"):
        KnowledgePack.model_validate(raw)


def test_missing_filing_status_rejected(raw_2023):
    raw = copy.deepcopy(raw_2023)
    del raw["tax"]["rate_schedules"]["schedules"]["head_of_household"]
    with pytest.raises(ValidationError, match="missing: head_of_household"):
        KnowledgePack.model_validate(raw)


def test_unbounded_middle_bracket_rejected(raw_2023):
    raw = copy.deepcopy(raw_2023)
    raw["tax"]["rate_schedules"]["schedules"]["single"][2]["but_not_over"] = None
    with pytest.raises(ValidationError, match="only the top bracket is unbounded"):
        KnowledgePack.model_validate(raw)


def test_row_band_not_tiling_rejected(raw_2023):
    raw = copy.deepcopy(raw_2023)
    raw["tax"]["tax_table"]["row_bands"][3]["row_width"] = 30  # 97,000 span not divisible
    with pytest.raises(ValidationError, match="multiple of row_width"):
        KnowledgePack.model_validate(raw)


def test_row_band_gap_rejected(raw_2023):
    raw = copy.deepcopy(raw_2023)
    raw["tax"]["tax_table"]["row_bands"][2]["at_least"] = 50  # gap after 25 (span stays divisible)
    with pytest.raises(ValidationError, match="no gaps"):
        KnowledgePack.model_validate(raw)


def test_table_worksheet_boundary_mismatch_rejected(raw_2023):
    raw = copy.deepcopy(raw_2023)
    raw["tax"]["tax_computation_worksheet"]["applies_at_or_above"] = 50000
    with pytest.raises(ValidationError, match="must equal tax_table.applies_below"):
        KnowledgePack.model_validate(raw)


def test_non_gov_citation_url_rejected(raw_2023):
    raw = copy.deepcopy(raw_2023)
    raw["tax"]["se_tax"]["citation"]["url"] = "somewhere/on/disk.pdf"
    with pytest.raises(ValidationError, match="https://"):
        KnowledgePack.model_validate(raw)


def test_extra_top_level_blocks_tolerated(raw_2023):
    # M3 adds filing thresholds / mailing addresses; older engines must not choke.
    raw = copy.deepcopy(raw_2023)
    raw["filing_thresholds"] = {"single": 13850}
    pack = KnowledgePack.model_validate(raw)
    assert pack.tax_year == 2023
