"""Phase J JS5 — the HI N-11 2024 overlay: the 2023 coordinates carried to the 2024 blank, stamped end to end.

The 2024 blank keeps every printed word within 0.5 pt of its 2023 position and differs from 2023 only where printed
text changed (see the manifest's port banner), so the 2024 manifest reuses every 2023 overlay box. The first test pins
that: a moved box in either year has to be re-measured, not silently carried.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

from test_n11_overlay import FULL as FULL_2023
from test_n11_overlay import GOLDEN as GOLDEN_2023
from test_n11_overlay import HI as HI_2023
from test_n11_overlay import MINUS_LINES

HI = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "hi" / "2024" / "n11" / "handfill.yaml"

# The 2023 demo returns with 2024 dates (placeholder identifiers only).
GOLDEN = {**GOLDEN_2023, "signature.date": "04/01/2025", "spouse.signature_date": "04/01/2025"}
FULL = {**FULL_2023, **{k: v for k, v in GOLDEN.items() if k.endswith("date")},
        "tax_year.begin": "04/01/24", "tax_year.end": "03/31/25",
        "deceased.taxpayer_date": "05/05/24", "deceased.spouse_date": "06/06/24", "preparer.date": "04/02/2025"}


def test_js5_the_2024_manifest_keeps_every_2023_box_and_every_line():
    old, new = load_hand_fill_pack(HI_2023), load_hand_fill_pack(HI)
    assert new.tax_year == 2024 and new.source_url.endswith("/2024/n11_i.pdf")
    assert [ln.line for ln in new.lines] == [ln.line for ln in old.lines]
    old_boxes = {ln.line: [b.model_dump() for b in ln.boxes] for ln in old.lines}
    moved = [ln.line for ln in new.lines if [b.model_dump() for b in ln.boxes] != old_boxes[ln.line]]
    assert moved == []
    assert sorted(ln.line for ln in new.lines if any(b.minus for b in ln.boxes)) == sorted(MINUS_LINES)
    labels = {ln.line: ln.label for ln in new.lines}
    assert "$8,082" in labels["15"] and "$4,400; 2/5: $8,800; 4: $6,424" in labels["23"]
    assert "N-325" in labels["27.other_forms"] and labels["38"].startswith("2024") and "2025" in labels["46"]


def test_js5_the_2024_computes_follow_the_face():
    ws = {ln.line: ln.value for ln in hand_fill_worksheet(load_hand_fill_pack(HI), GOLDEN).lines}
    assert (ws["6e"], ws["20"], ws["26"], ws["36"], ws["41"]) == ("3", "88,000", "80,168", "5,176", "5,800")
    assert (ws["42"], ws["45"], ws["47a"], ws["48"], ws["22"]) == ("624", "622", "622", "0", "")


@pytest.mark.network
def test_js5_the_2024_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(HI)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the 2024 N-11 blank: {exc}")
    for values in (GOLDEN, FULL):
        result = stamp_overlay(blank, pack, values, tmp_path / "n11_2024.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
        assert len(report.checks) == 177
    wrong = verify_overlay(pack, result.out_path, {**FULL, "7": 4500, "amended": ""})
    assert {"7", "amended"} <= {c.line for c in wrong.checks if c.status == "FAIL"}
    assert len(render_pdf(result.out_path, tmp_path / "png")) == 4
