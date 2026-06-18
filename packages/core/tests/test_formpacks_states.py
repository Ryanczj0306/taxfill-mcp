"""State form-pack tests (dev plan section 6) — mirrors test_formpacks_federal.

Auto-discovers every formpacks/states/<st>/<year>/<form>/pack.yaml and runs the
same guarantees as the federal packs: schema-valid, real sha256 (never the
authoring placeholder), relations parse in the verifier's evaluator, and a
network golden round-trip (fetch -> fill every line -> verify -> render every
page). State packs are flat AcroForms (empty acroform_root, top-level field
names), so this also exercises that engine path end to end.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.fetch import OfflineFetchError, fetch_blank
from taxfill_core.filler import fill_form
from taxfill_core.render import render_pdf
from taxfill_core.schemas.formpack import load_pack
from taxfill_core.verify import relations, verify_form

from test_formpacks_federal import _SHA256_PLACEHOLDER, _assert_section_clean, synthetic_values

REPO_ROOT = Path(__file__).resolve().parents[3]
STATE_PACK_PATHS = sorted((REPO_ROOT / "formpacks" / "states").glob("*/*/*/pack.yaml"))


def _pack_id(path: Path) -> str:
    # states/ca/2023/form540/pack.yaml -> ca_2023_form540
    parts = path.parts
    return f"{parts[-4]}_{parts[-3]}_{parts[-2]}"


if STATE_PACK_PATHS:

    @pytest.mark.parametrize("pack_path", STATE_PACK_PATHS, ids=_pack_id)
    def test_state_pack_parses_and_is_a_state_jurisdiction(pack_path: Path):
        pack = load_pack(pack_path)
        assert pack.jurisdiction.startswith("states/")
        # path layout matches the declared jurisdiction/year
        st = pack_path.parts[-4]
        assert pack.jurisdiction == f"states/{st}"
        assert int(pack_path.parts[-3]) == pack.tax_year

    @pytest.mark.parametrize("pack_path", STATE_PACK_PATHS, ids=_pack_id)
    def test_state_pack_sha256_is_real(pack_path: Path):
        assert load_pack(pack_path).pdf_sha256 != _SHA256_PLACEHOLDER

    @pytest.mark.parametrize("pack_path", STATE_PACK_PATHS, ids=_pack_id)
    def test_state_pack_relations_parse(pack_path: Path):
        pack = load_pack(pack_path)
        money = {pf.line: 1 for pf in pack.fields if pf.type == "money"}
        relations(pack, money)  # raises if a relation is malformed

    @pytest.mark.network
    @pytest.mark.parametrize("pack_path", STATE_PACK_PATHS, ids=_pack_id)
    def test_state_pack_golden_roundtrip(pack_path: Path, tmp_path: Path):
        pack = load_pack(pack_path)
        try:
            blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
        except OfflineFetchError as exc:
            pytest.skip(f"cache empty and network unreachable: {exc}")
        values = synthetic_values(pack)
        filled = tmp_path / f"{_pack_id(pack_path)}_filled.pdf"
        result = fill_form(pack, values, blank, filled)
        assert set(result.written), "the pack mapped no fillable lines"
        report = verify_form(pack, filled, expected=values)
        _assert_section_clean(report.assertions, "assertion diff")
        _assert_section_clean(report.clipping, "clipping scan")
        _assert_section_clean(report.checkboxes, "checkbox audit")
        pages = render_pdf(filled, tmp_path / "png")
        for page in pages:
            assert page.path.is_file() and page.path.stat().st_size > 1000
