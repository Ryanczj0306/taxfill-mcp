"""Phase J JS5 — the NM PIT-1 2024 overlay: page 1 carried box for box, page 2 re-measured below line 28, stamped end to end.

The 2024 blank keeps every page-1 printed word and path within 0.5 pt of 2023, so page 1 (and the page-2 header SSN and
lines 23-28, 25a, 25b) reuse the 2023 boxes. Line 29's caption now wraps to two lines: its money box doubled in height
with the "+ 29" label 5.67 pt lower, and every box from line 30 down sits exactly 11.33 pt lower (see the manifest's port
banner). The first test pins that census: a box may only differ from 2023 by the measured shift, and only on page 2.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

from test_pit1_overlay import FULL as FULL_2023
from test_pit1_overlay import GOLDEN as GOLDEN_2023
from test_pit1_overlay import NM as NM_2023

NM = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "nm" / "2024" / "pit1" / "handfill.yaml"

CARRIED_P2 = {"1b", "23", "24", "25", "25a", "25b", "26", "27", "28"}   # identical rules in both blanks
REMEASURED = {"29": 524.51}                                              # the doubled box, label baseline 524.77
SHIFT = -11.33                                                           # every box from line 30 down

# The 2023 demo returns with 2024 dates and figures (placeholder identifiers only); line 18 is the 2024 PIT-TRT
# lookup for $58,800 MFJ (row "more than 58,700 but not over 58,800" reads 2,471), not bracket arithmetic.
GOLDEN = {**GOLDEN_2023, "12": 29200, "18": 2471, "signature.date": "04/01/2025", "spouse.signature_date": "04/01/2025"}
FULL = {**FULL_2023, **{k: v for k, v in GOLDEN.items() if k.endswith("date") or k in ("12", "18")},
        "tax_year.begin": "04/01/2024", "tax_year.end": "03/31/2025", "4c": "05/05/2024", "6b": "10/15/2025",
        "preparer.date": "04/02/2025", "hca_share": "yes"}
del FULL["hsd_share"]                                                    # the face renamed the box HCA. 1


def test_js5_the_2024_manifest_carries_page_1_and_moves_page_2_by_the_measured_shift():
    old, new = load_hand_fill_pack(NM_2023), load_hand_fill_pack(NM)
    assert new.tax_year == 2024 and new.source_url.endswith("/55c7e522-196c-433c-8e4a-8629474a9df0/2024pit-1.pdf")
    rekey = {"hsd_share": "hca_share"}
    assert [rekey.get(ln.line, ln.line) for ln in old.lines] == [ln.line for ln in new.lines]
    old_boxes = {rekey.get(ln.line, ln.line): [b.model_dump() for b in ln.boxes] for ln in old.lines}
    census = {"carried": 0, "moved": 0, "re-measured": 0}
    for ln in new.lines:
        for before, box in zip(old_boxes[ln.line], ln.boxes, strict=True):
            after = box.model_dump()
            if after == before:
                assert box.page == 1 or ln.line in CARRIED_P2, ln.line
                census["carried"] += 1
                continue
            assert box.page == 2 and {k for k in after if after[k] != before[k]} == {"y"}, ln.line
            if ln.line in REMEASURED:
                assert after["y"] == REMEASURED[ln.line], ln.line
                census["re-measured"] += 1
            else:
                assert round(after["y"] - before["y"], 2) == SHIFT, (ln.line, before["y"], after["y"])
                census["moved"] += 1
    assert census == {"carried": 80, "moved": 37, "re-measured": 1}
    labels = {ln.line: ln.label for ln in new.lines}
    notes = {ln.line: ln.note for ln in new.lines if ln.note}
    assert "line 28" in labels["15"] and "2024 federal return" in labels["25a"] and "entity-level tax" in labels["29"]
    assert labels["30"].startswith("(+) 2024") and "2025 estimated tax" in labels["41"] and labels["hca_share"].startswith("HCA.1")
    assert "2024 NM Tax Rate Table" in notes["18"] and "4.9%" in notes["18"] and "enters Y" in notes["18a"]
    assert all("2024 PIT-1 Instructions" in rule.source and rule.url.endswith("/2024pit-1-ins.pdf") for rule in new.printing_guidance)


def test_js5_the_2024_computes_follow_the_face():
    ws = {ln.line: ln.value for ln in hand_fill_worksheet(load_hand_fill_pack(NM), GOLDEN).lines}
    assert (ws["17"], ws["22"], ws["23"], ws["32"]) == ("58,800", "2,471", "2,471", "2,500")
    assert (ws["33"], ws["38"], ws["39"], ws["42"]) == ("0", "0", "29", "29")


@pytest.mark.network
def test_js5_the_2024_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(NM)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)   # the pinned-only NM TRD host
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the 2024 PIT-1 blank: {exc}")
    for values in (GOLDEN, FULL):
        result = stamp_overlay(blank, pack, values, tmp_path / "pit1_2024.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
        assert len(report.checks) == 118
    loss = next(s for s in result.stamped_lines if s.line == "9")
    assert loss.value == "-4,500"                                       # NM: the minus sign left of the number
    wrong = verify_overlay(pack, result.out_path, {**FULL, "9": 4500, "29": 51, "hca_share": ""})
    assert {"9", "29", "hca_share"} <= {c.line for c in wrong.checks if c.status == "FAIL"}
    assert len(render_pdf(result.out_path, tmp_path / "png")) == 2
