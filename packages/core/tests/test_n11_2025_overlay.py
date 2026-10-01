"""Phase J JS5 — the HI N-11 2025 overlay: pages 1-3 carried from 2024, page 4 re-measured on the 2025 blank.

The 2025 blank keeps every page 1-3 entry path (digit cells, ovals, minus squares) within 0.3 pt of its 2024
position, so those boxes carry over box for box. Page 4 was rebuilt by the Department: the two AMENDED RETURN ONLY
lines (51, 52) are gone, the Schedule C/E/F block is renumbered 51-53 and sits exactly 48 pt higher together with
the designee, election-fund and signature rows, and the paid-preparer grid lost its "Check if self-employed" square
(see the manifest's port banner). The page 2-4 header captions were also re-set wider: the SSN digit cells stayed
put, but the "Name(s) as shown on return" underline now starts at x 311.83 (2024: 305.19), so name.as_shown is the
one page 1-3 box re-measured on the 2025 blank. The first test pins all of that: any other page 1-3 box that differs
from 2024, or a page-4 box that is neither carried, moved by exactly 48 pt nor one of the re-measured cells, fails.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

from test_n11_2024_overlay import HI as HI_2024
from test_n11_overlay import FULL as FULL_2023
from test_n11_overlay import GOLDEN as GOLDEN_2023

HI = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "hi" / "2025" / "n11" / "handfill.yaml"

# 2024's 53/54/55 (Schedule C / E / F) are 2025's 51/52/53; 2024's 51/52 (amended-return lines) and the preparer's
# self-employed square no longer exist on the face.
REKEYED = {"53": "51", "54": "52", "55": "53"}
DROPPED = {"51", "52", "preparer.self_employed"}
MOVED_UP_48 = {
    "51.yes", "51.no", "51", "51.activity", "51.product", "51.ge_id", "52.yes", "52.no", "52", "52.ge_id",
    "53.yes", "53.no", "53", "53.activity", "53.product", "53.ge_id",
    "designee.name", "designee.phone", "designee.id_number", "election_fund.yourself", "election_fund.spouse",
    "signature.date", "spouse.signature_date", "signature.occupation", "signature.daytime_phone",
    "spouse.occupation", "spouse.daytime_phone", "preparer.date", "preparer.name", "preparer.firm",
}
REMEASURED = {"preparer.ptin", "preparer.fein", "preparer.phone"}
# The name underline of the page 2-4 headers on the 2025 blank (underscore glyphs x 311.83-538.68; 2024: 305.19-532.03).
NAME_UNDERLINE = {"x": 311.83, "w": 226.85}
MINUS_LINES = ("7", "12", "20", "24", "34", "36")


def _port(values: dict) -> dict:
    out = {}
    for k, v in values.items():
        head, dot, rest = k.partition(".")
        if head in DROPPED or k in DROPPED:
            continue
        out[(REKEYED.get(head, head) + dot + rest) if head in REKEYED else k] = v
    return out


# The 2023 demo returns with 2025 dates and the 2025 line keys (placeholder identifiers only).
GOLDEN = {**_port(GOLDEN_2023), "signature.date": "04/01/2026", "spouse.signature_date": "04/01/2026"}
FULL = {**_port(FULL_2023), **{k: v for k, v in GOLDEN.items() if k.endswith("date")},
        "tax_year.begin": "04/01/25", "tax_year.end": "03/31/26",
        "deceased.taxpayer_date": "05/05/25", "deceased.spouse_date": "06/06/25", "preparer.date": "04/02/2026"}


def test_js5_the_2025_manifest_carries_pages_1_to_3_and_re_measures_page_4():
    old, new = load_hand_fill_pack(HI_2024), load_hand_fill_pack(HI)
    assert new.tax_year == 2025 and new.source_url.endswith("/2025/n11_i.pdf")
    old_lines = [ln.line for ln in old.lines]
    expected = [REKEYED.get(k.partition(".")[0], k.partition(".")[0]) + k[len(k.partition(".")[0]):]
                for k in old_lines if k not in DROPPED]
    assert [ln.line for ln in new.lines] == expected
    old_boxes = {ln.line: [b.model_dump() for b in ln.boxes] for ln in old.lines}
    back = {v: k for k, v in REKEYED.items()}
    for ln in new.lines:
        head, dot, rest = ln.line.partition(".")
        src = old_boxes[back.get(head, head) + dot + rest]
        boxes = [b.model_dump() for b in ln.boxes]
        if ln.line in MOVED_UP_48:
            assert len(boxes) == 1 and boxes[0]["page"] == 4
            assert boxes[0] == {**src[0], "y": pytest.approx(src[0]["y"] + 48.0), "minus": src[0]["minus"]}, ln.line
        elif ln.line in REMEASURED:
            assert len(boxes) == 1 and boxes[0]["page"] == 4 and boxes[0] != src[0], ln.line
        elif ln.line == "name.as_shown":                     # re-set caption: the box follows the 2025 underline
            assert [b["page"] for b in boxes] == [2, 3, 4]
            for b, s in zip(boxes, src):
                assert b == {**s, "x": pytest.approx(NAME_UNDERLINE["x"]), "w": pytest.approx(NAME_UNDERLINE["w"])}
        else:
            assert boxes == src, ln.line                     # pages 1-3, the page-4 SSN cells and lines 46-50
    assert sorted(ln.line for ln in new.lines if any(b.minus for b in ln.boxes)) == sorted(MINUS_LINES)
    marks = {ln.line: b.mark for ln in new.lines if ln.type == "checkbox" for b in ln.boxes}
    assert set(marks.values()) == {"fill"} and len(marks) == 41  # every oval painted; no self-employed square
    labels = {ln.line: ln.label for ln in new.lines}
    assert "$8,636" in labels["15"] and "$4,400; 2/5: $8,800; 4: $6,424" in labels["23"]
    assert labels["38"].startswith("2025") and labels["39"].endswith("2024 return") and "2026" in labels["46"]
    assert labels["51.yes"].startswith("51 Did you file a federal Schedule C?")
    assert labels["52"].startswith("Federal Schedule E") and labels["53"].startswith("Federal Schedule F")
    notes = {ln.line: ln.note for ln in new.lines}
    assert "Instructions page 20" in notes["22"] and "page 32" in notes["22"] and "page 22" in notes["42"]


def test_js5_the_2025_computes_follow_the_face():
    ws = {ln.line: ln.value for ln in hand_fill_worksheet(load_hand_fill_pack(HI), GOLDEN).lines}
    assert (ws["6e"], ws["20"], ws["26"], ws["36"], ws["41"]) == ("3", "88,000", "80,168", "5,176", "5,800")
    assert (ws["42"], ws["45"], ws["47a"], ws["48"], ws["22"]) == ("624", "622", "622", "0", "")
    loss = {ln.line: ln.value for ln in hand_fill_worksheet(load_hand_fill_pack(HI), FULL).lines}
    assert (loss["34"], loss["36"], loss["42"], loss["48"]) == ("-480", "-480", "6,280", "0")


@pytest.mark.network
def test_js5_the_2025_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(HI)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the 2025 N-11 blank: {exc}")
    for values in (GOLDEN, FULL):
        result = stamp_overlay(blank, pack, values, tmp_path / "n11_2025.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
        assert len(report.checks) == 174
    loss = next(s for s in result.stamped_lines if s.line == "7")
    assert loss.value == "4500"                                  # digits unsigned: the minus box carries the sign
    wrong = verify_overlay(pack, result.out_path, {**FULL, "7": 4500, "amended": "", "51": 50001, "53.yes": ""})
    assert {"7", "amended", "51", "53.yes"} <= {c.line for c in wrong.checks if c.status == "FAIL"}
    assert len(render_pdf(result.out_path, tmp_path / "png")) == 4
