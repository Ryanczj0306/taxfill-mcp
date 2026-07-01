"""Hand-fill worksheet engine tests (print-only forms — C3 fallback).

Print-only state forms (no AcroForm widgets, no XFA — e.g. HI N-11 2023) can't be
filled; instead the engine turns a line manifest + confirmed inputs into a
line->value worksheet the filer transcribes onto the printed blank. These tests pin
the compute engine (shared relation grammar), the entered/computed/blank sourcing,
and schema validation. Synthetic packs only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from taxfill_core.handfill import Worksheet, hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.schemas.handfill import HandFillPack
from taxfill_core.verify import evaluate_expression

REPO_ROOT = Path(__file__).resolve().parents[3]
HANDFILL_PACKS = sorted(REPO_ROOT.glob("formpacks/**/handfill.yaml"))
_LINE_ID_RE = re.compile(r"^(?:[0-9]+[a-z]?|[a-z][a-z0-9_]*)(?:\.(?:[0-9]+[a-z]?|[a-z][a-z0-9_]*))*$")


def _pack(lines: list[dict]) -> HandFillPack:
    return HandFillPack.model_validate(
        {
            "form": "TEST",
            "jurisdiction": "states/zz",
            "tax_year": 2023,
            "source_url": "https://example.gov/blank.pdf",
            "pdf_sha256": "a" * 64,
            "lines": lines,
        }
    )


def _by_line(ws: Worksheet) -> dict[str, tuple[str, str]]:
    return {ln.line: (ln.value, ln.source) for ln in ws.lines}


# ── the shared expression evaluator (also used by the verifier) ────────────


def test_evaluate_expression_arithmetic_and_blank_is_zero():
    v = {"1": 50000, "2": 1000, "3": 3000}
    assert evaluate_expression("1 + 2 - 3", v) == 48000
    assert evaluate_expression("max(0, 3 - 1)", v) == 0  # 3-1 = -47000 -> floored 0
    assert evaluate_expression("missing_line + 5", v) == 5  # blank ref counts as 0
    assert evaluate_expression("sum(1a..1c)", {"1a": 10, "1b": 20, "1c": 30}) == 60


def test_evaluate_expression_rejects_malformed():
    with pytest.raises(ValueError):
        evaluate_expression("1 + + 2", {"1": 1})
    with pytest.raises(ValueError):
        evaluate_expression("1 == 2", {"1": 1, "2": 2})  # a single expr, not a relation


# ── the worksheet builder ──────────────────────────────────────────────────


def test_worksheet_computes_chain_and_floors_at_zero():
    ws = hand_fill_worksheet(
        _pack(
            [
                {"line": "1", "label": "Federal AGI", "type": "money"},
                {"line": "2", "label": "Additions", "type": "money"},
                {"line": "3", "label": "Subtractions", "type": "money"},
                {"line": "4", "label": "State AGI", "type": "money", "compute": "1 + 2 - 3"},
                {"line": "5", "label": "Deduction", "type": "money"},
                {"line": "6", "label": "Taxable income", "type": "money", "compute": "max(0, 4 - 5)"},
            ]
        ),
        {"1": 50000, "2": 1000, "3": 3000, "5": 60000},
    )
    by = _by_line(ws)
    assert by["4"] == ("48,000", "computed")  # 50000 + 1000 - 3000
    assert by["6"] == ("0", "computed")  # max(0, 48000 - 60000)
    assert by["1"] == ("50,000", "entered")
    assert by["3"] == ("3,000", "entered")


def test_worksheet_blank_entered_text_and_checkbox():
    ws = hand_fill_worksheet(
        _pack(
            [
                {"line": "name", "label": "Your name", "type": "text"},
                {"line": "donate", "label": "Checkoff", "type": "checkbox"},
                {"line": "9", "label": "Unfilled money line", "type": "money"},
                {"line": "10", "label": "Reserved compute over blanks", "type": "money", "compute": "9 + 0"},
            ]
        ),
        {"name": "ALICE EXAMPLE", "donate": True},
    )
    by = _by_line(ws)
    assert by["name"] == ("ALICE EXAMPLE", "entered")
    assert by["donate"] == ("X", "entered")  # any truthy checkbox -> X
    assert by["9"] == ("", "blank")
    assert by["10"] == ("0", "computed")  # 9 is blank(0) -> computes 0


def test_worksheet_preserves_printed_order_and_metadata():
    pack = _pack([{"line": "1", "label": "L1", "type": "money"}, {"line": "2", "label": "L2", "type": "money"}])
    ws = hand_fill_worksheet(pack, {"1": 5})
    assert [ln.line for ln in ws.lines] == ["1", "2"]
    assert ws.form == "TEST" and ws.tax_year == 2023
    assert ws.print_url == "https://example.gov/blank.pdf"
    assert "no fillable fields" in ws.instructions.lower()


def test_worksheet_no_values_all_blank_or_zero():
    ws = hand_fill_worksheet(_pack([{"line": "1", "label": "L1", "type": "money"},
                                    {"line": "2", "label": "L2", "type": "money", "compute": "1 * 2"}]))
    by = _by_line(ws)
    assert by["1"] == ("", "blank")
    assert by["2"] == ("0", "computed")  # 1 is blank(0) -> 0*2 = 0


# ── schema validation ────────────────────────────────────────────────────────


def test_pack_requires_at_least_one_line():
    with pytest.raises(Exception):
        _pack([])


def test_pack_render_mode_is_hand_fill_and_roundtrips(tmp_path):
    pack = _pack([{"line": "1", "label": "L1", "type": "money"}])
    assert pack.render_mode == "hand_fill"
    p = tmp_path / "handfill.yaml"
    import yaml
    p.write_text(yaml.safe_dump(pack.model_dump()), encoding="utf-8")
    loaded = load_hand_fill_pack(p)
    assert loaded.form == "TEST" and loaded.lines[0].label == "L1"


# ── shipped print-only packs (e.g. HI N-11) ────────────────────────────────


@pytest.mark.parametrize(
    "path", HANDFILL_PACKS or [None], ids=lambda p: f"{p.parts[-4]}-{p.parts[-2]}" if p else "none"
)
def test_shipped_handfill_packs_validate_and_build(path):
    if path is None:
        pytest.skip("no shipped hand-fill packs")
    pack = load_hand_fill_pack(path)
    assert pack.render_mode == "hand_fill"
    assert pack.jurisdiction.startswith("states/")
    assert pack.pdf_sha256 != "..." and len(pack.pdf_sha256) == 64
    bad = [ln.line for ln in pack.lines if not _LINE_ID_RE.fullmatch(ln.line)]
    assert not bad, f"line ids violate the grammar: {bad}"
    # building the worksheet evaluates EVERY compute expression — a malformed one raises here
    ws = hand_fill_worksheet(pack, {})
    assert len(ws.lines) == len(pack.lines)


def test_hi_n11_income_chain_computes():
    """End-to-end on the shipped HI N-11 pack: the Hawaii-AGI chain derives correctly."""
    hi = [p for p in HANDFILL_PACKS if p.parts[-4] == "hi"]
    if not hi:
        pytest.skip("HI N-11 pack not present")
    pack = load_hand_fill_pack(hi[0])
    ws = hand_fill_worksheet(pack, {"7": 80000, "8": 2000, "13": 5000, "14": 3000})
    by = {ln.line: (ln.value, ln.source) for ln in ws.lines}
    assert by["11"] == ("2,000", "computed")   # 8 + 9 + 10 = 2000
    assert by["12"] == ("82,000", "computed")  # 7 + 11
    assert by["19"] == ("8,000", "computed")   # 13 + 14 + ... = 8000
    assert by["20"] == ("74,000", "computed")  # 12 - 19
