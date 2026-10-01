"""Phase J JS5 — the SC1040 2025 overlay: the 2023 cells carried to the 2025 blank box for box, one box re-measured.

The 2025 blank (Rev. 4/21/25) keeps every ruled cell, checkbox square and SSN tick of the 2023 blank within 0.01 pt
(the manifest's port banner records the path census); the only entry area that moved is the combat-zone name, which
the 2025 face rules with a drawn line 8 pt to the left of the 2023 underscore string. The first test pins exactly that:
every other box is equal to its 2023 box, and the one re-measured box is the one the census says moved.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

from test_sc1040_overlay import FULL as FULL_2023
from test_sc1040_overlay import GOLDEN as GOLDEN_2023
from test_sc1040_overlay import SC as SC_2023

SC = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "sc" / "2025" / "sc1040" / "handfill.yaml"

# The 2023 demo returns with 2025-return dates (placeholder identifiers only).
GOLDEN = {**GOLDEN_2023, "w": 4930, "t": 4930, "signature.date": "04/01/2026"}
FULL = {**FULL_2023, "w": 4930, "t": 4930, "s": 160, "s.days": "10", "signature.date": "04/01/2026",
        "36.withdrawal_date": "04/15/2026", "preparer.date": "04/02/2026"}


def test_js5_the_2025_manifest_keeps_every_2023_box_but_the_combat_zone_name():
    old, new = load_hand_fill_pack(SC_2023), load_hand_fill_pack(SC)
    assert new.tax_year == 2025 and new.source_url.endswith("/SC1040_2025.pdf")
    assert [ln.line for ln in new.lines] == [ln.line for ln in old.lines]
    old_boxes = {ln.line: [b.model_dump() for b in ln.boxes] for ln in old.lines}
    moved = [ln.line for ln in new.lines if [b.model_dump() for b in ln.boxes] != old_boxes[ln.line]]
    assert moved == ["combat_zone_name"]
    (box,) = next(ln for ln in new.lines if ln.line == "combat_zone_name").boxes
    assert (box.page, box.x, box.y, box.w) == (1, 163.85, 271.1, 179.7)     # the 2025 rule runs 161.85 .. 345.52
    ssn = next(ln for ln in new.lines if ln.line == "identifying_number")
    assert [b.page for b in ssn.boxes] == [1, 2, 3]
    labels = {ln.line: ln.label for ln in new.lines}
    assert "$16" in labels["s"] and "2025" in labels["17"] and "2026" in labels["27"]
    assert "2025" in labels["dependents_count"] and "2026" in labels["tax_year.end"]
    notes = {ln.line: ln.note for ln in new.lines}
    assert "2025 SC1040TT" in notes["6"] and "6%" in notes["6"] and "$4,930" in notes["w"]


def test_js5_the_2025_computes_follow_the_face():
    ws = {ln.line: ln.value for ln in hand_fill_worksheet(load_hand_fill_pack(SC), FULL).lines}
    # line 4 adds f-w including the six p and two q sub-amounts; line 32 its two blanks (unchanged compute shape)
    assert (ws["2"], ws["3"], ws["4"], ws["5"]) == ("1,800", "74,300", "15,470", "58,830")
    assert (ws["10"], ws["14"], ws["15"], ws["23"]) == ("2,600", "150", "2,450", "2,900")
    assert (ws["24"], ws["25"], ws["29"], ws["30"], ws["31"]) == ("450", "0", "0", "450", "0")
    assert (ws["32"], ws["34"]) == ("15", "35")


@pytest.mark.network
def test_js5_the_2025_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(SC)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the 2025 SC1040 blank: {exc}")
    for values in (GOLDEN, FULL):
        result = stamp_overlay(blank, pack, values, tmp_path / "sc1040_2025.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
    wrong = verify_overlay(pack, result.out_path, {**FULL, "1": 7250, "combat_zone_name": "", "s": 80})
    assert {"1", "combat_zone_name", "s"} <= {c.line for c in wrong.checks if c.status == "FAIL"}
    pages = render_pdf(result.out_path, tmp_path / "png")
    assert len(pages) == 3 and all(Path(p.path).stat().st_size > 1000 for p in pages)
