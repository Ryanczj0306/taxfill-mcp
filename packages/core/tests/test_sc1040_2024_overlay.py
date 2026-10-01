"""Phase J JS5 — the SC1040 2024 overlay: the 2023 cells carried to the 2024 blank box for box, one box re-measured.

The 2024 blank (Rev. 7/8/24) keeps every ruled cell, checkbox square and SSN tick of the 2023 blank within 0.01 pt
(the manifest's port banner records the path census); the only entry area that moved is the combat-zone name, whose
printed underscore string the re-worded 2024 caption pushes 7.93 pt to the left (the 2025 blank draws a rule there
instead, so the 2024 box is measured from this blank's own underscore, not carried from 2025). The first test pins
exactly that: every other box is equal to its 2023 box, and the one re-measured box is the one the census says moved.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

from test_sc1040_overlay import FULL as FULL_2023
from test_sc1040_overlay import GOLDEN as GOLDEN_2023
from test_sc1040_overlay import SC as SC_2023

SC = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "sc" / "2024" / "sc1040" / "handfill.yaml"

# The 2023 demo returns with the 2024 figures ($4,790 dependent amounts, $16 subsistence days) and 2024-return dates
# (placeholder identifiers only).
GOLDEN = {**GOLDEN_2023, "w": 4790, "t": 4790, "signature.date": "04/01/2025"}
FULL = {**FULL_2023, "w": 4790, "t": 4790, "s": 160, "s.days": "10", "signature.date": "04/01/2025",
        "36.withdrawal_date": "04/15/2025", "preparer.date": "04/02/2025"}


def every_line(pack) -> dict:
    """The full return plus a synthetic value for every line it leaves blank: every box on the blank gets stamped
    (every checkbox X-ed, every money cell and text underscore filled), so a render reads each printed entry once."""
    values = dict(FULL)
    for i, ln in enumerate(pack.lines):
        if ln.line in values or ln.compute:
            continue
        if ln.type == "checkbox":
            values[ln.line] = "yes"
        elif ln.type == "money":
            values[ln.line] = 1000 + 111 * (i % 9)
        elif ln.line.endswith(".ssn") or ln.line.endswith("identifying_number") or ln.line.endswith("_ssn"):
            values[ln.line] = "999-88-0003"
        elif ln.line.endswith(".dob") or ln.line.endswith("date_of_birth"):
            values[ln.line] = "01/02/1950"
        else:
            values[ln.line] = "DEMO"
    return values


def test_js5_the_2024_manifest_keeps_every_2023_box_but_the_combat_zone_name():
    old, new = load_hand_fill_pack(SC_2023), load_hand_fill_pack(SC)
    assert new.tax_year == 2024 and new.source_url.endswith("/SC1040_2024.pdf")
    assert [ln.line for ln in new.lines] == [ln.line for ln in old.lines]
    old_boxes = {ln.line: [b.model_dump() for b in ln.boxes] for ln in old.lines}
    moved = [ln.line for ln in new.lines if [b.model_dump() for b in ln.boxes] != old_boxes[ln.line]]
    assert moved == ["combat_zone_name"]
    (box,) = next(ln for ln in new.lines if ln.line == "combat_zone_name").boxes
    assert (box.page, box.x, box.y, box.w) == (1, 164.89, 271.1, 179.7)     # the 2024 underscore runs 162.89 .. 346.59
    ssn = next(ln for ln in new.lines if ln.line == "identifying_number")
    assert [b.page for b in ssn.boxes] == [1, 2, 3]
    labels = {ln.line: ln.label for ln in new.lines}
    assert "$16" in labels["s"] and "2024" in labels["17"] and "2025" in labels["27"]
    assert "2024" in labels["dependents_count"] and "2025" in labels["tax_year.end"]
    notes = {ln.line: ln.note for ln in new.lines}
    assert "2024 SC1040TT" in notes["6"] and "6.2%" in notes["6"] and "$659" in notes["6"]
    assert "$4,790" in notes["w"] and "$4,790" in notes["t"]
    assert new.printing_guidance[0].url.endswith("/SC1040Instr_2024.pdf")


def test_js5_the_2024_computes_follow_the_face():
    ws = {ln.line: ln.value for ln in hand_fill_worksheet(load_hand_fill_pack(SC), FULL).lines}
    # line 4 adds f-w including the six p and two q sub-amounts; line 32 its two blanks (unchanged compute shape)
    assert (ws["2"], ws["3"], ws["4"], ws["5"]) == ("1,800", "74,300", "15,190", "59,110")
    assert (ws["10"], ws["14"], ws["15"], ws["23"]) == ("2,600", "150", "2,450", "2,900")
    assert (ws["24"], ws["25"], ws["29"], ws["30"], ws["31"]) == ("450", "0", "0", "450", "0")
    assert (ws["32"], ws["34"]) == ("15", "35")


@pytest.mark.network
def test_js5_the_2024_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(SC)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the 2024 SC1040 blank: {exc}")
    every = every_line(pack)
    assert {ln.line for ln in pack.lines if not ln.compute} <= set(every)
    for values in (GOLDEN, FULL, every):
        result = stamp_overlay(blank, pack, values, tmp_path / "sc1040_2024.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
    wrong = verify_overlay(pack, result.out_path, {**every, "1": 7250, "combat_zone_name": "", "s": 80})
    assert {"1", "combat_zone_name", "s"} <= {c.line for c in wrong.checks if c.status == "FAIL"}
    pages = render_pdf(result.out_path, tmp_path / "png")
    assert len(pages) == 3 and all(Path(p.path).stat().st_size > 1000 for p in pages)
