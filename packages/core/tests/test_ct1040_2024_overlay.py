"""Phase J JS5 — the CT-1040 2024 overlay: pages 1-2 re-measured on a re-flowed blank, pages 3-4 carried where unchanged.

The 2024 blank re-flows pages 1 and 2 against 2023 (the header block moved up 16 pt, Lines 1-16 down 4-5 pt, the
page-2 rows by -17 to +10 pt) and inserts Line 48d on page 3 — the same face the 2025 blank prints: a path census of
the two blanks finds every entry rectangle, stroke and square at the same numbers, the only differing square being the
health-coverage box. So every page-1/2 box and the page-3 rows 48a-50 were measured again from the 2024 blank's own
rectangles and underline strokes; the page-3/4 boxes whose anchors did not move are the 2023 boxes verbatim (the
manifest's port banner says which). This file pins all of it: the carried boxes equal the 2023 ones box for box, the
re-measured ones are the ones the 2024 geometry gives (and, where the TY2025 manifest is present, equal its boxes
except the health square), the face deltas are in the labels, and a demo return, a full return and a return with ink
in every one of the 187 boxes stamp with no warning and verify on all 187 placements on the real blank, and a wrong
value FAILs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

from test_ct1040_overlay import CT as CT_2023
from test_ct1040_overlay import FULL as FULL_2023
from test_ct1040_overlay import GOLDEN as GOLDEN_2023

CT = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "ct" / "2024" / "ct1040" / "handfill.yaml"
CT_2025 = CT.parents[2] / "2025" / "ct1040" / "handfill.yaml"

# The 2023 demo returns with 2024 dates; the 2023-only entries (email, CHET account number) dropped, the new ones added.
GOLDEN = {k: v for k, v in GOLDEN_2023.items() if k not in ("signature.email", "48.account")}
GOLDEN.update({"signature.date": "04012025", "spouse.signature_date": "04012025", "20d": 0,
               "60.date_1": "07-15-2024", "60.date_2": "01-15-2025", "61.date_1": "07-15-2024"})
FULL = {k: v for k, v in FULL_2023.items() if k not in ("signature.email", "48.account")}
FULL.update({**{k: v for k, v in GOLDEN.items() if k.endswith(("date", "date_1", "date_2"))},
             "tax_year.end": "03-31-2025", "preparer.date": "04022025",
             "62.date_1": "07-15-2024", "62.date_2": "01-15-2025",
             "health_coverage.interest": "yes", "20d": 75, "37.specify": "TREATY INCOME", "48d": 250,
             "49.specify": "TRIBAL INCOME",
             # every re-measured checkbox and the blank re-measured rows get a value too (a demo, not a plausible return)
             "deceased.taxpayer": "yes", "deceased.spouse": "yes", "25a.savings": "yes",
             "attach.ct2210": "yes", "attach.f1310": "yes", "attach.ct19it": "yes", "attach.ct1040crc": "yes",
             "attach.ct8379": "yes", "18d.fein": "98-7654321", "18d.wages": 600, "18d": 30, "18e.fein": "98-7654321",
             "18e.wages": 400, "18e": 20, "48a": 100, "48b": 200, "48c": 50})

# The 36 entries FULL still leaves blank (the four other filing-status squares, the MFS spouse name, the penalty and
# interest lines, every Schedule 1 addition/subtraction, 56b, Auto 1's second date, the 69/70 rows): a value in each,
# so the stamp test puts ink in every one of the 187 boxes (a coordinate exerciser — five filing statuses at once).
EVERY = {**FULL, "filing_status.single": "yes", "filing_status.mfs": "yes", "filing_status.hoh": "yes",
         "filing_status.qss": "yes", "filing_status.mfs_spouse_name": "SAM R TAXPAYER", "61.date_2": "01-15-2025",
         "18f": 180, "27": 270, "28": 280, "29": 290, "32": 3200, "33": 3300, "34": 3400, "35": 3500, "36": 3600,
         "36a": 3610, "40": 4000, "41": 4100, "43": 4300, "44": 4400, "45": 4500, "46": 4600, "47": 4700, "49": 4900,
         "56b": 560, "69a": 691, "69c": 693, "69d": 694, "70b": 702, "70c": 703, "70d": 704, "70e": 705, "70f": 706,
         "70g": 707, "70h": 708}

# Every page-3/4 box movebox called SAME on the 2024 blank (and the page 2-4 SSN headers): carried over verbatim.
CARRIED = ["31", "32", "33", "34", "35", "36", "36a", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46", "47",
           "48", "51", "52a", "52a.code", "52b", "52b.code", "53a", "53b", "54a", "54b", "55a", "55b", "56a", "56b",
           "57a", "57b", "58a", "58b", "59",
           "60.town", "60.description", "60.date_1", "60.date_2", "60.amount", "61.town", "61.description", "61.date_1",
           "61.date_2", "61.amount", "62.town", "62.description", "62.date_1", "62.date_2", "62.amount", "63", "65", "66",
           "67", "68", "69a", "69b", "69c", "69d", "69", "70a", "70b", "70c", "70d", "70e", "70f", "70g", "70h", "70"]
DROPPED = ["signature.email", "48.account"]
ADDED = ["health_coverage.interest", "20d", "37.specify", "48d", "49.specify"]


def _boxes(pack):
    return {ln.line: [b.model_dump() for b in ln.boxes] for ln in pack.lines}


def test_js5_the_2024_manifest_carries_the_unchanged_boxes_and_re_measures_the_rest():
    old, new = load_hand_fill_pack(CT_2023), load_hand_fill_pack(CT)
    assert new.tax_year == 2024 and new.source_url.endswith("/2024/income/ct-1040_1224.pdf")
    assert new.pdf_sha256 == "63ef57eba0b794985be947fa04971e02062e12d001c2879bce90f2ee5448dba0"
    old_ids, new_ids = [ln.line for ln in old.lines], [ln.line for ln in new.lines]
    assert [i for i in old_ids if i not in new_ids] == DROPPED and [i for i in new_ids if i not in old_ids] == ADDED
    assert [i for i in new_ids if i not in ADDED] == [i for i in old_ids if i not in DROPPED]  # the face order is kept
    ob, nb = _boxes(old), _boxes(new)
    assert all(nb[i] == ob[i] for i in CARRIED), [i for i in CARRIED if nb[i] != ob[i]]
    assert nb["identifying_number"][1:] == ob["identifying_number"][1:]      # the page 2-4 headers did not move
    assert nb["identifying_number"][0]["y"] == ob["identifying_number"][0]["y"] + 16  # page 1's header block moved up 16 pt
    assert all(b["page"] <= 2 for i in new_ids if i not in CARRIED and i not in ("identifying_number", *ADDED, "48a", "48b", "48c", "49", "50") for b in nb[i])
    moved = [i for i in new_ids if i not in CARRIED and i in ob and nb[i] != ob[i]]
    assert {"1", "16", "26", "30", "signature.date", "48a", "48b", "48c", "49", "filing_status.single"} <= set(moved)
    # re-measured on the 2024 geometry and found at the 2023 numbers (movebox had flagged 50 — the 48d insertion moved
    # its anchors, not its rectangle)
    assert [i for i in new_ids if i not in CARRIED and i in ob and nb[i] == ob[i]] == [
        "17", "18a.fein", "18a.wages", "18b.fein", "18b.wages", "18c.fein", "18c.wages", "18d.fein", "18d.wages", "50"]
    assert nb["25b"][0]["cells"] and nb["25c"][0]["cells"] and len(nb["25c"][0]["cells"]) == 18   # the uneven combs are cells now
    # the health-coverage square: the 8.55 x 7.96 pt filled path at x 144.00-152.55 on the 2024 face (2025 prints it elsewhere)
    health = nb["health_coverage.interest"]
    assert len(health) == 1 and (health[0]["page"], health[0]["x"], health[0]["y"], health[0]["w"]) == (1, 144.0, 402.1, 8.5)
    assert len(nb["48d"]) == 1 and nb["48d"][0]["page"] == 3
    assert sum(len(ln.boxes) for ln in new.lines) == 187 and [ln.line for ln in new.lines if not ln.boxes] == []


def test_js5_the_2024_boxes_are_the_2025_boxes_except_the_health_square():
    if not CT_2025.exists():
        pytest.skip("the TY2025 CT-1040 manifest is not in this tree")
    nb, sb = _boxes(load_hand_fill_pack(CT)), _boxes(load_hand_fill_pack(CT_2025))
    assert list(nb) == list(sb)
    assert [i for i in nb if nb[i] != sb[i]] == ["health_coverage.interest"]
    assert nb["health_coverage.interest"][0]["x"] == 144.0 and sb["health_coverage.interest"][0]["x"] != 144.0


def test_js5_the_2024_labels_and_computes_follow_the_face():
    pack = load_hand_fill_pack(CT)
    labels = {ln.line: ln.label for ln in pack.lines}
    computes = {ln.line: ln.compute for ln in pack.lines}
    assert labels["1"].endswith("Line 11") and "Line 10" in labels["13"] and labels["19"].startswith("All 2024")
    assert "2025 estimated" in labels["23"] and "made in 2024" in labels["48"] and labels["70g"] == "CHET Baby Scholars"
    assert labels["20d"].startswith("Historic Home Rehabilitation Credit") and labels["48d"].startswith("Achieving Better Life Experience")
    assert computes["21"].endswith("+ 20d") and "48d" in computes["50"]
    assert not any("2023" in (ln.label + (ln.note or "")) or "2025 Instructions" in (ln.label + (ln.note or "")) for ln in pack.lines)
    notes = {ln.line: ln.note for ln in pack.lines}
    assert "2024 Instructions, pages 19-23" in notes["6"] and "page 26" in notes["66"] and "$49,500" in notes["66"]
    assert pack.printing_guidance[0].source == "Form CT-1040 (Rev. 12/24), page 1"
    ws = {ln.line: ln.value for ln in hand_fill_worksheet(pack, GOLDEN).lines}
    assert (ws["3"], ws["5"], ws["8"], ws["14"], ws["16"], ws["17"]) == ("99,700", "96,300", "3,700", "3,400", "3,445", "3,445")
    assert (ws["18"], ws["21"], ws["22"], ws["25"], ws["26"], ws["30"]) == ("3,520", "4,020", "575", "570", "0", "0")
    assert (ws["38"], ws["50"], ws["55a"], ws["58a"], ws["59"], ws["68"]) == ("1,200", "3,400", "3,650", "190", "190", "300")
    full = {ln.line: ln.value for ln in hand_fill_worksheet(pack, FULL).lines}
    assert (full["18"], full["21"], full["50"]) == ("3,630", "4,205", "4,500")    # 18d/18e, 20d and 48a-48d flow into the totals
    every = {ln.line: ln.value for ln in hand_fill_worksheet(pack, EVERY).lines}
    assert [ln for ln, v in every.items() if not v] == []                        # EVERY leaves no line of the manifest blank
    assert (every["18"], every["30"], every["38"], every["50"], every["69"], every["70"]) == (
        "3,810", "840", "21,960", "40,000", "2,123", "4,940")                   # 18f, 27-29, 32-36a, 40-49, 69a-d, 70b-h flow


@pytest.mark.network
def test_js5_the_2024_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(CT)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the 2024 CT-1040 blank: {exc}")
    for values in (GOLDEN, FULL, EVERY):
        result = stamp_overlay(blank, pack, values, tmp_path / "ct1040_2024.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        assert sorted(s.page for s in result.stamped_lines if s.line == "identifying_number") == [1, 2, 3, 4]
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
        assert len(report.checks) == 187                      # blank lines' boxes are checked empty too
    assert len(result.stamped_lines) == 187                   # EVERY put ink in every box; none was checked as merely empty
    wrong = verify_overlay(pack, result.out_path, {**EVERY, "1": 8500, "health_coverage.interest": "", "48d": 0})
    assert not wrong.ok and {"1", "3", "5", "health_coverage.interest", "48d", "50"} <= {c.line for c in wrong.checks if c.status == "FAIL"}
    pages = render_pdf(result.out_path, tmp_path / "png")
    assert len(pages) == 4 and all(Path(p.path).stat().st_size > 1000 for p in pages)
