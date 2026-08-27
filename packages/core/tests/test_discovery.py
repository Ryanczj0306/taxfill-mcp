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
    # / Schedule NEC (2023, Tier 2) = 41, + Forms 2441/843/8316 (Phase G) = 44,
    # + the TY2025 set (f1040, scheds 1/1a/2/3/A/B/C, 8843, f1040nr,
    # scheds OI/NEC/A-NR — the OBBBA year, incl. the new Schedule 1-A) = 57,
    # + f1040nr/sched_oi 2024 (the ported pair, 2026-08-10) = 59,
    # + the 2024/2025 backfill of the 2023 set (2026-08 batch: 18 forms x 2024
    # incl. sched_a_nr/sched_nec, 16 forms x 2025) = 93,
    # + f8606 x 2023/2024/2025 (Phase I1, 2026-08-26 — the form that carries IRA
    # basis across years, landed with the ira_pro_rata/roth_conversion ops) = 96,
    # + f8889 x 2023/2024/2025 (Phase I2, 2026-08-26 — HSAs, landed with the
    # hsa_deduction op and the 1099-SA/5498-SA DocSpecs) = 99,
    # + f8949 x 2023/2024/2025 (Phase I3, 2026-08-26 — Schedule D's DETAIL form,
    # without which a filer with stock sales could not assemble a return) = 102,
    # + the Phase I4 visa-status set x 2023/2024/2025 (2026-08-27): f8833 (the
    # section 6114 treaty disclosure calc.treaty_benefit could not help a filer
    # file), f1116 (foreign tax credit) and f8938 (specified foreign financial
    # assets) = 111. FinCEN 114 ships alongside as a hand_fill worksheet, so it
    # adds 3 handfill.yaml and ZERO pack.yaml — that asymmetry is the point of the
    # worksheet form (FBAR is e-filed to FinCEN, not attached to the return),
    # plus the state packs, pinned separately below.
    assert len([s for s in allf if s.jurisdiction == "federal"]) == 111

    # State packs. 42 for TY2023 (the C1 resident sweep: 38 states/DC with an
    # AcroForm pack — CA ships 4 — while HI/CT/NM/SC are hand-fill worksheets
    # and so carry no pack.yaml at all), + NY IT-201/IT-203 x 2024 and x 2025 and
    # PA-40 2024 (the 2026-08-10 port) = 47, + the 2026-08-21 ten-pack tranche
    # (AR1000F 2024 AND 2025, D-400 / NJ-1040 / IT 1040 / RI-1040 / TC-40 /
    # Form 760 x 2024, OR-40 and PA-40 x 2025) = 57, + the 2026-08-25 near-port
    # tranche (IL-1040 / ND-1 / OR-40 / MO-1040 x 2024) = 61. So TY2023 42,
    # TY2024 14, TY2025 5 — state coverage is no longer TY2023-only, and any
    # claim that it is should be corrected wherever it survives.
    states = [s for s in allf if s.jurisdiction.startswith("states/")]
    assert len(states) == 61
    assert len({s.tax_year for s in states}) == 3
    assert len([s for s in states if s.tax_year == 2023]) == 42
    assert len([s for s in states if s.tax_year == 2024]) == 14
    assert len([s for s in states if s.tax_year == 2025]) == 5
    # Every discovered pack is one or the other, so the total is the sum. This
    # catches a pack landing under a third top-level jurisdiction unnoticed.
    assert len(allf) == 111 + 61 == 172


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
