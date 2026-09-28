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


def test_a_hand_fill_pack_without_coordinates_points_at_the_worksheet(tmp_path):
    # The shipped CT-1040 2023 manifest has no overlay blocks yet (JS4c authors them).
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
