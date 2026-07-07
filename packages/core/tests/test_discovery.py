"""list_forms / get_form_map tests (dev plan section 8). Offline; reads formpacks/."""

import pytest

from taxfill_core.discovery import FormMap, FormSummary, get_form_map, list_forms


def test_list_all_packs():
    allf = list_forms()
    assert all(isinstance(s, FormSummary) for s in allf)
    assert all(s.source_url.startswith("https://") for s in allf)
    # 26 federal (the M2 set) + Schedule SE + Schedule D/E + Form 8863/2555 (2023)
    # = 31, + Form 4868 (2023) = 32, + Form 1040-ES (2023) = 33, + Form 1040-X
    # (2023, Rev. 2-2024) = 34, + Form W-7 (2023, Rev. 12-2024) = 35, + Forms
    # 8959/8960/8962 (2023, Phase F) = 38, + Schedule 8812 / Schedule A (1040-NR)
    # / Schedule NEC (2023, Tier 2) = 41, plus the growing state packs.
    assert len([s for s in allf if s.jurisdiction == "federal"]) == 41
    assert any(s.jurisdiction.startswith("states/") for s in allf)


def test_list_filters_by_jurisdiction_and_year():
    fed_2023 = list_forms("federal", 2023)
    keys = {s.form_key for s in fed_2023}
    assert {"f1040", "f1040nr", "sched_c", "sched_oi"} <= keys
    assert all(s.tax_year == 2023 and s.jurisdiction == "federal" for s in fed_2023)
    # f8843 ships for six years; filtering by year narrows it.
    f8843_years = {s.tax_year for s in list_forms() if s.form_key == "f8843"}
    assert {2019, 2020, 2021, 2022, 2023, 2024} <= f8843_years


def test_get_form_map_returns_lines_relations_crossform():
    fm = get_form_map("f1040", 2023)
    assert isinstance(fm, FormMap)
    assert fm.form == "1040" and fm.form_key == "f1040"
    assert len(fm.lines) > 100
    assert "11 == 9 - 10" in fm.relations
    assert "8 == sched_1.10" in fm.cross_form
    assert fm.identity_fields == ["identifying_number"]
    # Each line maps a printed line id to an AcroForm field.
    by_line = {ln.line: ln for ln in fm.lines}
    assert "1z" in by_line and by_line["1z"].type == "money"


def test_get_form_map_unknown_lists_available_keys():
    with pytest.raises(FileNotFoundError) as exc:
        get_form_map("does_not_exist", 2023)
    msg = str(exc.value)
    assert "Available form keys" in msg and "f1040" in msg


def test_get_form_map_unknown_year():
    with pytest.raises(FileNotFoundError):
        get_form_map("f1040", 1999)
