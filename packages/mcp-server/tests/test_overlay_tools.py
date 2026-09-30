"""Phase J JS4a — the overlay path through the existing tools (no 24th tool) and `taxfill locate`."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import taxfill_mcp.server as server
from taxfill_core.schemas.handfill import HandFillPack
from taxfill_mcp.cli import main


def _blank(path: Path) -> Path:
    """A one-page flat blank printed in an embedded font (Vera), the way real print-only blanks are."""
    pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Vera", 9)
    c.drawString(72, 700, "5")
    c.drawString(90, 700, "Federal adjusted gross income")
    c.drawString(72, 680, "6")
    c.save()
    return path


def _pack() -> HandFillPack:
    box = {"page": 1, "x": 400, "w": 100}
    return HandFillPack.model_validate({
        "form": "CT-1040", "jurisdiction": "states/ct", "tax_year": 2023,
        "source_url": "https://portal.ct.gov/-/media/drs/forms/2023/income/ct-1040_1223.pdf", "pdf_sha256": "0" * 64,
        "lines": [
            {"line": "5", "label": "Line 5", "type": "money", "overlay": {**box, "y": 700}},
            {"line": "6", "label": "Line 6", "type": "money", "overlay": {**box, "y": 680}},
            {"line": "7", "label": "Line 7 (hand-written)", "type": "money"},
        ],
    })


@pytest.fixture
def overlay_pack(tmp_path, monkeypatch):
    blank = _blank(tmp_path / "blank.pdf")
    pack = _pack()
    monkeypatch.setattr(server, "_load_any_pack", lambda form, year, jurisdiction: pack)
    monkeypatch.setattr(server, "_fetch_pack_blank", lambda p: blank)
    return pack, blank


def test_the_overlay_rides_the_existing_tools_and_the_tool_count_stays_23():
    assert len(asyncio.run(server.mcp.list_tools())) == 23


def test_the_server_does_not_import_the_overlay_module_at_load():
    # server.py imports overlay lazily, inside the hand-fill branch of verify_form (and fill_form's dispatch).
    import subprocess

    probe = "import sys, taxfill_mcp.server; print('taxfill_core.overlay' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "False"


def test_fill_form_stamps_and_verify_form_gives_the_overlay_verdict(overlay_pack, tmp_path):
    values = {"5": 14000, "6": 250, "7": 9}
    filled = server.fill_form("ct1040", 2023, values, str(tmp_path / "out.pdf"), jurisdiction="states/ct")
    assert filled["render_mode"] == "hand_fill_overlay"
    assert [s["line"] for s in filled["stamped_lines"]] == ["5", "6"]
    assert [w["line"] for w in filled["hand_written_lines"]] == ["7"]
    good = server.verify_form("ct1040", 2023, filled["out_path"], expected=values, jurisdiction="states/ct")
    assert good["ok"] and good["verdict"] == "OVERLAY" and good["sections"]["overlay"]["failed"] == 0
    assert "not run" in good["sections"]["recompute"]["note"] and good["limits"]
    # PJ-01 through the tool: a stamped 14,000 must not verify as 4,000
    bad = server.verify_form("ct1040", 2023, filled["out_path"], expected={**values, "5": 4000},
                             jurisdiction="states/ct")
    assert not bad["ok"] and bad["sections"]["overlay"]["failed"] == 1
    with pytest.raises(ValueError, match="needs `expected`"):
        server.verify_form("ct1040", 2023, filled["out_path"], jurisdiction="states/ct")


def test_a_hand_fill_pack_without_coordinates_points_at_the_worksheet(tmp_path, monkeypatch):
    # Since JS4d every shipped print-only state manifest carries coordinates, so a new pack without any stands in.
    bare = _pack().model_copy(update={"lines": [ln.model_copy(update={"overlay": None}) for ln in _pack().lines]})
    monkeypatch.setattr(server, "_load_any_pack", lambda form, year, jurisdiction: bare)
    with pytest.raises(ValueError, match=r"no overlay coordinates.*hand_fill_worksheet"):
        server.fill_form("ct1040", 2023, {}, str(tmp_path / "o.pdf"), jurisdiction="states/ct")


def test_taxfill_locate_prints_label_boxes(tmp_path, capsys):
    blank = _blank(tmp_path / "blank.pdf")
    assert main(["locate", str(blank), "--page", "1", "5", "gross income", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    (five,) = payload["hits"]["5"]
    assert abs(five["x0"] - 72) <= 1 and abs(five["y0"] - 700) <= 1
    assert payload["page"]["pages"] == 1 and payload["hits"]["gross income"]
    assert main(["locate", str(blank), "--page", "1", "no such label"]) == 1
    assert "no needle matched" in capsys.readouterr().err
    assert main(["locate", str(blank), "--page", "2", "5"]) == 1
    assert "out of range" in capsys.readouterr().err


# ── Phase J JS4b ─────────────────────────────────────────────────────────────


@pytest.mark.network
def test_js4b_verify_filing_verifies_a_filing_with_a_stamped_print_only_form(tmp_path, monkeypatch):
    # A real f8843 (AcroForm, from the cached blank) filed together with a stamped CT-1040-shaped hand-fill form.
    try:
        server.fetch_blank("f8843", 2023)
    except Exception as exc:  # offline + cold cache
        pytest.skip(f"cannot fetch blank: {exc}")
    real_load, real_fetch = server._load_any_pack, server._fetch_pack_blank
    pack, blank = _pack(), _blank(tmp_path / "blank.pdf")
    monkeypatch.setattr(server, "_load_any_pack", lambda f, y, j: pack if f == "ct1040" else real_load(f, y, j))
    monkeypatch.setattr(server, "_fetch_pack_blank", lambda p: blank if p is pack else real_fetch(p))
    fm = server.get_form_map("f8843", 2023)
    text_lines = [ln["line"] for ln in fm["lines"] if ln["type"] == "text"][:2]
    fed_values = {ln: f"TEST {i}" for i, ln in enumerate(text_lines)}
    fed = server.fill_form("f8843", 2023, fed_values, str(tmp_path / "f8843.pdf"))
    ct_values = {"5": 14000, "6": 250}
    ct = server.fill_form("ct1040", 2023, ct_values, str(tmp_path / "ct.pdf"), jurisdiction="states/ct")
    items = [{"form": "f8843", "year": 2023, "pdf_path": fed["out_path"]},
             {"form": "ct1040", "year": 2023, "pdf_path": ct["out_path"], "jurisdiction": "states/ct",
              "expected": ct_values}]
    good = server.verify_filing(items)
    assert good["sections"]["overlay"] == {"checked": 2, "failed": 0, "failures": []}
    assert "ct1040" in good["form_keys"] and any("took no part in the cross-form" in lim for lim in good["limits"])
    assert good["ok"] == server.verify_filing(items[:1])["ok"]        # the stamped form adds no failure of its own
    bad = server.verify_filing([items[0], {**items[1], "expected": {**ct_values, "5": 4000}}])
    assert not bad["ok"] and bad["sections"]["overlay"]["failed"] == 1
    assert bad["sections"]["overlay"]["failures"][0].startswith("ct1040: line '5'")
    with pytest.raises(ValueError, match="add `expected`"):
        server.verify_filing([items[0], {k: v for k, v in items[1].items() if k != "expected"}])
    with pytest.raises(ValueError, match=r"unknown form_key\(s\) \['ct'\]"):
        server.verify_filing(items, independent={"ct": {"5": 1}})
    with pytest.raises(ValueError, match="at least one fillable"):
        server.verify_filing(items[1:])


@pytest.mark.parametrize("year", [2023, 2024, 2025, 2026])
def test_js4b_the_fbar_has_no_blank_to_fetch_or_stamp(year, tmp_path):
    with pytest.raises(ValueError, match="BSA E-Filing System"):
        server.fetch_blank("fincen114", year)
    with pytest.raises(ValueError, match="ELECTRONICALLY ONLY"):
        server.fill_form("fincen114", year, {}, str(tmp_path / "o.pdf"))
    worksheet = server.hand_fill_worksheet("fincen114", year, "federal")   # the value-gathering sheet still works
    assert "DO NOT PRINT AND MAIL" in worksheet["instructions"]


def test_js4b_efile_only_needs_instructions_and_no_coordinates():
    base = _pack().model_dump(exclude_none=True)
    with pytest.raises(ValueError, match="must set `instructions`"):
        HandFillPack.model_validate({**base, "efile_only": True})
    with pytest.raises(ValueError, match="nothing to stamp"):
        HandFillPack.model_validate({**base, "efile_only": True, "instructions": "File it in the BSA E-Filing System."})
    from taxfill_core.handfill import load_hand_fill_pack

    root = Path(__file__).resolve().parents[3] / "formpacks"
    assert all(load_hand_fill_pack(p).efile_only for p in root.glob("federal/*/fincen114/handfill.yaml"))
    assert not any(load_hand_fill_pack(p).efile_only for p in root.glob("states/*/*/*/handfill.yaml"))


@pytest.mark.network
def test_js4c_the_real_ct1040_stamps_and_verifies_through_the_tools(tmp_path):
    try:
        server.fetch_blank("ct1040", 2023, "states/ct")
    except Exception as exc:  # offline + cold cache
        pytest.skip(f"cannot fetch blank: {exc}")
    values = {"identifying_number": "123-45-6789", "name.first": "TESS", "name.last": "TAXPAYER",
              "filing_status.single": "yes", "1": 52000, "6": 1800, "15": 0, "18a.fein": "12-3456789",
              "18a.wages": 52000, "18a": 2100, "signature.date": "04012024"}
    filled = server.fill_form("ct1040", 2023, values, str(tmp_path / "ct.pdf"), jurisdiction="states/ct")
    assert filled["render_mode"] == "hand_fill_overlay" and not filled["warnings"] and not filled["hand_written_lines"]
    assert {s["page"] for s in filled["stamped_lines"] if s["line"] == "identifying_number"} == {1, 2, 3, 4}
    assert any("blue or black ink" in rule for rule in filled["printing_guidance"])
    report = server.verify_form("ct1040", 2023, filled["out_path"], expected=values, jurisdiction="states/ct")
    assert report["ok"] and report["sections"]["overlay"]["failed"] == 0
