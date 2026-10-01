"""Phase J JS5 — the NM PIT-1 2025 overlay: the return inside the PIT packet (source_pages 57-58), re-measured where it moved.

NM publishes no standalone 2025 PIT-1: the manifest pins the 136-page packet and names pages 57-58. Against 2024, the
page-1 header block was re-set (every box 1a-6a re-measured from its own rect or rule), line 16 became "Reserved for
Future Use" (16 and 16a dropped, line 17's compute no longer subtracts 16), lines 14/15/17/18 sit in re-drawn boxes and
18a-22 moved +0.50; page 2 moved -0.48 (23-29), -1.15 (31-34) and -2.59 (36 down), with 30 and 35 re-centred in taller
boxes (see the manifest's port banner). The first test pins that census box for box.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

from test_pit1_2024_overlay import FULL as FULL_2024
from test_pit1_2024_overlay import GOLDEN as GOLDEN_2024
from test_pit1_2024_overlay import NM as NM_2024

NM = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "nm" / "2025" / "pit1" / "handfill.yaml"

DROPPED = {"16", "16a"}                                                  # the face prints "16 DO NOT USE"
# page-1 boxes set from the 2025 blank's own rects and rules; a key not named keeps its 2024 value
REMEASURED = {
    "1a": {"y": 604.88}, "1b": {"y": 605.72}, "1c": {"y": 605.37}, "1d": {"y": 605.75, "w": 11.6},
    "1e": {"x": 459.54, "y": 605.33, "w": 13.72, "cells": [459.54], "cell_w": 13.72}, "1f": {"y": 604.99},
    "2a": {"y": 578.88}, "2b": {"y": 580.57}, "2c": {"y": 580.63}, "2d": {"y": 580.63, "w": 11.74},
    "2e": {"x": 459.54, "y": 580.57, "w": 13.72, "cells": [459.54], "cell_w": 13.72}, "2f": {"y": 580.72},
    "3a": {"x": 49.86, "y": 566.32, "w": 8.58}, "3b": {"y": 542.35},
    "3c": {"y": 518.26}, "3c.state": {"y": 518.26}, "3c.zip": {"y": 518.26},
    "3d": {"y": 495.5}, "3d.province": {"y": 495.5},
    "5": {"x": 45.49, "y": 464.64}, "6a": {"x": 43.49, "y": 436.55, "w": 14.69},
    "14": {"y": 229.67}, "15": {"y": 217.43}, "17": {"y": 165.97}, "18": {"y": 148.2},
}
# boxes moved by the shift their own bounding rules measured
SHIFT = {**{k: 0.5 for k in ("18a", "19", "20", "21", "22")},
         **{k: -0.48 for k in ("23", "24", "25", "25a", "25b", "26", "27", "28", "29")},
         "30": -0.81, **{k: -1.15 for k in ("31", "32", "33", "34")}, "35": -1.87}
SHIFT.update({k: -2.59 for k in (
    "36", "37", "38", "39", "40", "41", "42", "re.routing", "re.account", "re.checking", "re.savings",
    "re.foreign_yes", "re.foreign_no", "hca_share", "signature.date", "signature.dl_number", "signature.dl_state",
    "signature.dl_expiration", "spouse.signature_date", "spouse.dl_number", "spouse.dl_state",
    "spouse.dl_expiration", "phone", "email", "preparer.date", "preparer.firm", "preparer.nmbtin",
    "preparer.ptin", "preparer.fein", "preparer.phone", "preparer.rpd41338")})

# The 2024 demo returns with 2025 figures and 2026 dates (placeholder identifiers only): line 12 is the 2025 federal MFJ
# standard deduction, line 18 the 2025 PIT-TRT lookup for $56,500 MFJ (row "56,400 - 56,500" reads 2,042, packet page
# T-4), not bracket arithmetic; lines 16 / 16a no longer exist.
GOLDEN = {k: v for k, v in GOLDEN_2024.items() if k not in DROPPED}
GOLDEN.update({"12": 31500, "18": 2042, "signature.date": "04/01/2026", "spouse.signature_date": "04/01/2026"})
FULL = {k: v for k, v in FULL_2024.items() if k not in DROPPED}
FULL.update({**{k: v for k, v in GOLDEN.items() if k.endswith("date") or k in ("12", "18")},
             "tax_year.begin": "04/01/2025", "tax_year.end": "03/31/2026", "4c": "05/05/2025", "4d": "06/06/2025",
             "6b": "10/15/2026", "preparer.date": "04/02/2026",
             "dep3.first": "EMMA", "dep3.last": "TAXPAYER", "dep3.ssn": "999-88-0004", "dep3.dob": "08/08/2018",
             "dep4.first": "FINN", "dep4.last": "TAXPAYER", "dep4.ssn": "999-88-0005", "dep4.dob": "09/09/2019",
             "dep5.first": "GALE", "dep5.last": "TAXPAYER", "dep5.ssn": "999-88-0006", "dep5.dob": "10/10/2021"})
# The ten marks FULL never paints (FULL is married filing jointly, checking, no foreign account, neither spouse 65+ or
# blind, EIC qualified): a read exercise, not a coherent return — the four other filing-status ovals are painted at once.
MARKS = {"1a": GOLDEN["1a"], "1b": GOLDEN["1b"], "2a": GOLDEN["2a"], "2b": GOLDEN["2b"],
         "1d": "yes", "2c": "yes", "25b": "yes", "filing_status.single": "yes", "filing_status.mfs": "yes",
         "filing_status.hoh": "yes", "filing_status.qss": "yes", "re.savings": "yes", "re.foreign_yes": "yes"}


def test_js5_the_2025_manifest_names_the_packet_pages_and_pins_the_measured_census():
    old, new = load_hand_fill_pack(NM_2024), load_hand_fill_pack(NM)
    assert new.tax_year == 2025 and new.source_pages == [57, 58]
    assert new.source_url.endswith("/0558a902-6362-47ca-8e3b-7cca3bc69b9d/2025%20PIT%20Packet_Final.pdf")
    assert [ln.line for ln in old.lines if ln.line not in DROPPED] == [ln.line for ln in new.lines]
    old_boxes = {ln.line: [b.model_dump() for b in ln.boxes] for ln in old.lines}
    census = {"carried": 0, "moved": 0, "re-measured": 0}
    for ln in new.lines:
        for i, (before, box) in enumerate(zip(old_boxes[ln.line], ln.boxes, strict=True)):
            after = box.model_dump()
            if ln.line in REMEASURED and i == 0:
                assert after == {**before, **REMEASURED[ln.line]}, ln.line
                census["re-measured"] += 1
            elif ln.line in SHIFT:
                assert {k for k in after if after[k] != before[k]} == {"y"}, ln.line
                assert round(after["y"] - before["y"], 2) == SHIFT[ln.line], (ln.line, before["y"], after["y"])
                census["moved"] += 1
            else:
                assert after == before, ln.line
                census["carried"] += 1
    assert census == {"carried": 40, "moved": 51, "re-measured": 25}
    labels = {ln.line: ln.label for ln in new.lines}
    computes = {ln.line: ln.compute for ln in new.lines if ln.compute}
    notes = {ln.line: ln.note for ln in new.lines if ln.note}
    assert "state-issued driver's license" in labels["1a"]
    assert computes["17"] == "max(0, 9 + 10 + 11 - 12 - 13 - 14 - 15)" and "12,13,14,15 (" in labels["17"]
    assert "2025 federal return" in labels["25a"] and labels["30"].startswith("(+) 2025") and "2026 estimated tax" in labels["41"]
    assert "BeWell" in labels["hca_share"] and "NMHIE" not in labels["hca_share"]
    assert "2025 NM Tax Rate Table" in notes["18"] and "$4,087" in notes["18"] and notes["18a"].startswith("2025 Instructions")
    assert all("2025 PIT-1 Instructions" in rule.source and rule.url == new.source_url for rule in new.printing_guidance)


def test_js5_the_2025_computes_follow_the_face_and_the_worksheet_names_the_packet_pages():
    ws = hand_fill_worksheet(load_hand_fill_pack(NM), GOLDEN)
    values = {ln.line: ln.value for ln in ws.lines}
    assert (values["17"], values["18"], values["22"], values["23"], values["32"]) == ("56,500", "2,042", "2,042", "2,042", "2,500")
    assert (values["33"], values["38"], values["39"], values["42"]) == ("0", "0", "458", "458")
    assert "16" not in values and "16a" not in values
    assert ws.instructions.startswith("The form is page(s) 57, 58 of the PDF at print_url")


@pytest.mark.network
def test_js5_the_2025_demo_return_stamps_cleanly_and_verifies_on_the_real_packet(tmp_path):
    from pypdf import PdfReader

    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(NM)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)   # the pinned-only NM TRD host
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the 2025 PIT packet: {exc}")
    assert len(PdfReader(str(blank)).pages) == 136
    for values in (GOLDEN, MARKS, FULL):                                 # FULL last: the loss below reads it
        result = stamp_overlay(blank, pack, values, tmp_path / "pit1_2025.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
        assert len(report.checks) == 116
        if values is MARKS:
            assert {s.line for s in result.stamped_lines} >= set(MARKS)   # every one of the ten ovals painted
    assert len(PdfReader(str(result.out_path)).pages) == 2                # only packet pages 57-58 are written
    loss = next(s for s in result.stamped_lines if s.line == "9")
    assert loss.value == "-4,500"                                       # NM: the minus sign left of the number
    wrong = verify_overlay(pack, result.out_path, {**FULL, "9": 4500, "29": 51, "5": "04", "hca_share": ""})
    assert {"9", "29", "5", "hca_share"} <= {c.line for c in wrong.checks if c.status == "FAIL"}
    assert len(render_pdf(result.out_path, tmp_path / "png")) == 2
