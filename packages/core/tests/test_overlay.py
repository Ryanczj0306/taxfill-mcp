"""Phase J JS4a — the overlay filler for print-only forms, on a synthetic flat blank.

The blank is drawn with reportlab in an EMBEDDED TrueType font (Vera), the way the CT / HI /
SC blanks embed theirs, so the only unembedded base-14 Helvetica on a stamped page is the
stamp. The PJ-01 negatives are the reason this file exists: before JS4a, verify_overlay
searched for the expected value inside that value's own footprint, so a stamped 14,000 /
10 / 1,200 verified as 4,000 / 0 / 200.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from taxfill_core.overlay import (
    MIN_FONT_SIZE,
    _HELVETICA_WIDTHS_COMPACT,
    _darkness,
    locate_labels,
    page_geometry,
    stamp_overlay,
    text_width,
    verify_overlay,
)
from taxfill_core.schemas.handfill import HandFillPack

# Rows of the synthetic blank (baselines, PDF points). Money boxes span x 400..500.
ROW = {"5": 700.0, "6": 680.0, "7": 660.0, "8": 640.0, "name": 620.0, "ssn": 600.0, "check": 580.0}
MONEY_X, MONEY_W = 400.0, 100.0


def _blank(path: Path, *, stray_helvetica: bool = False) -> Path:
    """Two pages; page 1 prints the line labels (embedded Vera) and a pre-printed '00' after each money box."""
    pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Vera", 9)
    for key, y in ROW.items():
        c.drawString(72, y, key)
        c.drawString(90, y, f"caption for line {key} (tax year 2023)")
    for key in ("5", "6", "7", "8"):
        c.drawString(MONEY_X + MONEY_W + 4, ROW[key], "00")
    c.drawString(72, 560, "15 is not 5")
    if stray_helvetica:  # a blank that prints its own unembedded Helvetica inside a declared box
        c.setFont("Helvetica", 9)
        c.drawString(MONEY_X + 60, ROW["8"], "00")
    c.showPage()
    c.setFont("Vera", 9)
    c.drawString(72, 700, "page two")
    c.save()
    return path


def _pack(**overrides) -> HandFillPack:
    money = {"page": 1, "x": MONEY_X, "w": MONEY_W}
    lines = [
        {"line": "5", "label": "Line 5", "type": "money", "overlay": {**money, "y": ROW["5"]}},
        {"line": "6", "label": "Line 6", "type": "money", "overlay": {**money, "y": ROW["6"]}},
        {"line": "7", "label": "Line 7", "type": "money", "overlay": {**money, "y": ROW["7"]}},
        {"line": "8", "label": "Line 8 = 5 + 6", "type": "money", "compute": "5 + 6", "overlay": {**money, "y": ROW["8"]}},
        {"line": "name", "label": "Name", "type": "text", "overlay": {"page": 1, "x": 200, "y": ROW["name"], "w": 150}},
        {"line": "ssn", "label": "SSN", "type": "text", "overlay": {"page": 1, "x": 300, "y": ROW["ssn"], "w": 90, "comb": 10}},
        {"line": "check", "label": "Box", "type": "checkbox", "overlay": {"page": 1, "x": 300, "y": ROW["check"], "w": 10}},
        {"line": "9", "label": "Line 9 (no coordinates)", "type": "money"},
    ]
    raw = {"form": "CT-1040", "jurisdiction": "states/ct", "tax_year": 2023,
           "source_url": "https://portal.ct.gov/-/media/drs/forms/2023/income/ct-1040_1223.pdf",
           "pdf_sha256": "0" * 64, "lines": lines}
    raw.update(overrides)
    return HandFillPack.model_validate(raw)


VALUES = {"5": 14000, "6": 10, "7": 1200, "name": "Tess Q", "ssn": "123-45-6789", "check": "yes", "9": 5}


@pytest.fixture
def stamped(tmp_path):
    blank = _blank(tmp_path / "blank.pdf")
    pack = _pack()
    result = stamp_overlay(blank, pack, VALUES, tmp_path / "out.pdf")
    return pack, result, Path(result.out_path)


def test_round_trip_verifies_and_every_alignment_lands_where_the_layout_says(stamped):
    pack, result, out = stamped
    report = verify_overlay(pack, out, VALUES)
    assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
    by = {s.line: s for s in result.stamped_lines}
    # money: right-aligned, ending at x + w
    for line in ("5", "6", "7", "8"):
        s = by[line]
        assert s.align == "right" and s.x + text_width(s.value, s.font_size) == pytest.approx(MONEY_X + MONEY_W, abs=1e-3)
    assert by["8"].value == "14,010"                                   # computed 5 + 6
    assert by["name"].align == "left" and by["name"].x == pytest.approx(200)
    assert by["check"].align == "center" and by["check"].value == "X"
    assert by["ssn"].align == "comb" and by["ssn"].value == "123456789"  # separators dropped: no cell for them
    # the comb's first digit is centred in cell 0 of pitch 10
    assert by["ssn"].x == pytest.approx(300 + (10 - text_width("1", by["ssn"].font_size)) / 2, abs=1e-3)
    assert [w.line for w in result.hand_written_lines] == ["9"]       # no coordinates -> hand-written
    assert [w.line for w in report.hand_written_lines] == ["9"]


def test_pj01_a_stamp_that_merely_contains_the_expected_value_fails(stamped):
    # The PJ-01 negatives: stamped 14,000 / 10 / 1,200 must NOT verify as 4,000 / 0 / 200.
    pack, _, out = stamped
    report = verify_overlay(pack, out, {**VALUES, "5": 4000, "6": 0, "7": 200})
    status = {c.line: c.status for c in report.checks}
    assert not report.ok
    assert status["5"] == status["6"] == status["7"] == "FAIL"
    assert status["8"] == "FAIL"                                     # 4,000 + 0 is not the stamped 14,010
    assert status["name"] == status["ssn"] == status["check"] == "PASS"
    detail = next(c.detail for c in report.checks if c.line == "5")
    assert "expected exactly '4,000'" in detail and "found stamped '14,000'" in detail


def test_a_blank_line_whose_box_holds_a_stamp_fails(stamped):
    pack, _, out = stamped
    values = {k: v for k, v in VALUES.items() if k != "7"}          # line 7 now blank, but its box was stamped
    report = verify_overlay(pack, out, values)
    check = next(c for c in report.checks if c.line == "7")
    assert check.status == "FAIL" and "is blank but its box" in check.detail and "1,200" in check.detail


def test_a_blank_line_with_an_empty_box_passes(tmp_path):
    blank = _blank(tmp_path / "blank.pdf")
    pack = _pack()
    values = {k: v for k, v in VALUES.items() if k != "7"}
    out = Path(stamp_overlay(blank, pack, values, tmp_path / "out.pdf").out_path)
    report = verify_overlay(pack, out, values)
    assert report.ok and next(c for c in report.checks if c.line == "7").status == "PASS"


def test_unknown_keys_are_refused_by_stamp_and_verify(stamped, tmp_path):
    pack, _, out = stamped
    with pytest.raises(ValueError, match=r"unknown line key\(s\) \['5a'\]"):
        stamp_overlay(_blank(tmp_path / "b2.pdf"), pack, {"5a": 1}, tmp_path / "x.pdf")
    with pytest.raises(ValueError, match=r"unknown line key\(s\) \['5a'\]"):
        verify_overlay(pack, out, {**VALUES, "5a": 1})


def test_wrong_coordinates_fail_and_say_the_value_is_elsewhere(stamped):
    pack, _, out = stamped
    moved = _pack(lines=[{**ln.model_dump(exclude_none=True), **(
        {"overlay": {**ln.overlay.model_dump(exclude_none=True), "y": ln.overlay.y - 30}} if ln.line == "5" else {})}
        for ln in pack.lines])
    check = next(c for c in verify_overlay(moved, out, VALUES).checks if c.line == "5")
    assert check.status == "FAIL" and "stamped elsewhere on the page" in check.detail


def test_a_page_beyond_the_blank_is_refused_at_stamp_time_and_fails_verification(stamped, tmp_path):
    pack, _, out = stamped
    far = _pack(lines=[{**ln.model_dump(exclude_none=True), **(
        {"overlay": {**ln.overlay.model_dump(exclude_none=True), "page": 3}} if ln.line == "5" else {})}
        for ln in pack.lines])
    with pytest.raises(ValueError, match="has 2 page"):
        stamp_overlay(_blank(tmp_path / "b3.pdf"), far, VALUES, tmp_path / "y.pdf")
    check = next(c for c in verify_overlay(far, out, VALUES).checks if c.line == "5")
    assert check.status == "FAIL" and "page 3" in check.detail


def test_a_pack_without_coordinates_is_refused(tmp_path):
    bare = _pack(lines=[{"line": "5", "label": "Line 5", "type": "money"}])
    with pytest.raises(ValueError, match="no overlay coordinates"):
        stamp_overlay(_blank(tmp_path / "b.pdf"), bare, {"5": 1}, tmp_path / "o.pdf")


def test_shrink_overflow_and_non_winansi_warnings(tmp_path):
    blank = _blank(tmp_path / "blank.pdf")
    pack = _pack(lines=[
        {"line": "a", "label": "shrinks", "type": "text", "overlay": {"page": 1, "x": 100, "y": 500, "w": 40}},
        {"line": "b", "label": "overflows", "type": "text", "overlay": {"page": 1, "x": 100, "y": 480, "w": 10}},
        {"line": "c", "label": "non-WinAnsi", "type": "text", "overlay": {"page": 1, "x": 100, "y": 460, "w": 200}},
        {"line": "d", "label": "comb overflow", "type": "text", "overlay": {"page": 1, "x": 100, "y": 440, "w": 30, "comb": 10}},
    ])
    result = stamp_overlay(blank, pack, {"a": "ABCDEFGHIJ", "b": "ABCDEFGHIJKLMNOP", "c": "Łódź", "d": "12345"},
                           tmp_path / "o.pdf")
    joined = "\n".join(result.warnings)
    assert "font shrunk to" in joined and "line 'a'" in joined
    assert "still overflows" in joined and f"{MIN_FONT_SIZE:g}pt floor" in joined
    assert "outside WinAnsi" in joined
    assert "comb value" in joined and "holds 3 cells" in joined
    by = {s.line: s for s in result.stamped_lines}
    assert MIN_FONT_SIZE <= by["a"].font_size < 9 and by["b"].font_size == MIN_FONT_SIZE


def test_the_font_filter_fails_safe_on_a_blank_that_prints_unembedded_helvetica_in_a_box(tmp_path):
    blank = _blank(tmp_path / "blank.pdf", stray_helvetica=True)
    pack = _pack()
    out = Path(stamp_overlay(blank, pack, VALUES, tmp_path / "o.pdf").out_path)
    check = next(c for c in verify_overlay(pack, out, VALUES).checks if c.line == "8")
    assert check.status == "FAIL"                                    # the blank's own '00' reads as stamped


def test_the_compact_widths_table_matches_pypdf_core14_metrics():
    try:
        from pypdf._codecs.core_font_metrics import CORE_FONT_METRICS
    except Exception:  # pragma: no cover - older/newer pypdf without the private module
        pytest.skip("this pypdf does not expose its Core-14 AFM table")
    widths = CORE_FONT_METRICS["Helvetica"].character_widths
    assert {ch: widths[ch] for ch in _HELVETICA_WIDTHS_COMPACT} == _HELVETICA_WIDTHS_COMPACT
    assert text_width("14,000", 10) == pytest.approx((556 * 5 + 278) / 100)


def test_locate_labels_finds_whole_words_within_a_point(tmp_path):
    blank = _blank(tmp_path / "blank.pdf")
    hits = locate_labels(blank, 1, ["5", "caption for line 7"])
    fives = hits["5"]
    # the printed '5' label at (72, 700), the '5' of its caption "caption for line 5", and the last word of
    # "15 is not 5" — never the '5' inside '15' (x about 77 on the y=560 row)
    assert any(abs(b.x0 - 72) <= 1 and abs(b.y0 - ROW["5"]) <= 1 for b in fives)
    assert not [b for b in fives if abs(b.y0 - 560) <= 1 and b.x0 < 100]
    assert len(fives) == 3
    # a caption's y0 is its descender ('p'), within 0.3 em below the baseline; a bare numeral's y0 IS the baseline
    (caption,) = hits["caption for line 7"]
    assert ROW["7"] - 0.3 * 9 <= caption.y0 <= ROW["7"] and caption.x0 == pytest.approx(90, abs=1)
    loose = locate_labels(blank, 1, ["5"], whole_word=False)["5"]
    assert len(loose) > len(fives)                                    # substring mode also finds the '5' of '15'
    geom = page_geometry(blank, 1)
    assert (geom["width"], geom["height"], geom["pages"]) == (612, 792, 2)
    with pytest.raises(ValueError, match="out of range"):
        locate_labels(blank, 3, ["5"])


# ── Phase J JS4b: the agencies' printing rules ───────────────────────────────


def test_js4b_the_stamp_result_carries_the_packs_printing_rules_and_honours_its_minimum_size(tmp_path):
    blank = _blank(tmp_path / "blank.pdf")
    rule = {"quote": "Complete return in blue or black ink only.", "source": "Form CT-1040 (Rev. 12/23), page 1",
            "url": "https://portal.ct.gov/-/media/drs/forms/2023/income/ct-1040_1223.pdf"}
    pack = _pack(printing_guidance=[rule], min_font_size=8,
                 lines=[{"line": "a", "label": "narrow", "type": "text", "overlay": {"page": 1, "x": 100, "y": 500, "w": 30}}])
    result = stamp_overlay(blank, pack, {"a": "ABCDEFGHIJ"}, tmp_path / "o.pdf")
    assert result.printing_guidance == ['Form CT-1040 (Rev. 12/23), page 1: "Complete return in blue or black ink only."']
    assert result.stamped_lines[0].font_size == 8                       # the agency floor, not the 6 pt default
    assert "at the 8pt floor" in "\n".join(result.warnings)


def _normalised_text(pdf: Path) -> str:
    import re

    import pypdf

    return re.sub(r"\s+", " ", "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages))


_STATE_HANDFILLS = sorted((Path(__file__).resolve().parents[3] / "formpacks" / "states").glob("*/*/*/handfill.yaml"))


@pytest.mark.network
@pytest.mark.parametrize("path", _STATE_HANDFILLS, ids=lambda p: f"{p.parts[-4]}_{p.parts[-3]}")
def test_js4b_every_recorded_printing_rule_is_verbatim_in_its_source(path):
    # Every year's manifest, not only 2023's: a port re-reads its year's face and Instructions (JS5).
    import re

    from taxfill_core.fetch import FetchError, fetch_blank
    from taxfill_core.handfill import load_hand_fill_pack

    state = path.parts[-4]
    pack = load_hand_fill_pack(path)
    assert pack.printing_guidance, f"{path}: record the agency's printing rules (or the finding that it has none)"
    assert pack.min_font_size is None                                  # none of the four publishes one (2023, 2024)
    texts: dict[str, str] = {}
    for rule in pack.printing_guidance:
        if rule.url not in texts:
            try:
                pdf = fetch_blank(rule.url, sha256=pack.pdf_sha256 if rule.url == pack.source_url else None)
            except (FetchError, ValueError) as exc:  # the official-host rule refuses with ValueError
                # NM TRD serves its library from an AWS API-gateway host, which fetch refuses as a blank host;
                # its quotes were read from that document on 2026-09-28 (see the manifest).
                if "official US government hosts" in str(exc) or "without a pinned sha256" in str(exc):
                    continue
                raise
            texts[rule.url] = _normalised_text(pdf)
        assert re.sub(r"\s+", " ", rule.quote) in texts[rule.url], (state, rule.quote)


# ── Phase J JS4c: uneven cells and repeated placements ───────────────────────


def test_js4c_cells_centre_each_character_in_its_own_uneven_cell_and_drop_separators(tmp_path):
    blank = _blank(tmp_path / "blank.pdf")
    # an SSN printed 3-2-4 around pre-printed dashes: 14 pt pitch inside a group, 24 pt across a dash
    lefts = [100, 114, 128, 152, 166, 190, 204, 218, 232]
    pack = _pack(lines=[{"line": "ssn", "label": "SSN", "type": "text",
                         "overlay": {"page": 1, "x": 98, "y": 500, "w": 148, "cells": lefts, "cell_w": 11}}])
    result = stamp_overlay(blank, pack, {"ssn": "123-45-6789"}, tmp_path / "o.pdf")
    (s,) = result.stamped_lines
    assert s.value == "123456789" and s.align == "cells" and not result.warnings
    assert s.x == pytest.approx(100 + (11 - text_width("1", 9)) / 2, abs=1e-3)
    assert verify_overlay(pack, Path(result.out_path), {"ssn": "123-45-6789"}).ok
    # a decimal around a pre-printed point: the point is the form's, only the digits are stamped
    dec = _pack(lines=[{"line": "d", "label": "decimal", "type": "text",
                        "overlay": {"page": 1, "x": 98, "y": 480, "w": 90, "cells": [100, 120, 135, 150, 165], "cell_w": 12}}])
    r2 = stamp_overlay(blank, dec, {"d": "0.4523"}, tmp_path / "d.pdf")
    assert r2.stamped_lines[0].value == "04523" and not r2.warnings
    r3 = stamp_overlay(blank, dec, {"d": "10.45235"}, tmp_path / "e.pdf")   # 7 characters for 5 cells
    assert "has 7 characters but the box has 5 cells" in "\n".join(r3.warnings)


def test_js4c_cells_are_validated(tmp_path):
    base = {"page": 1, "x": 98, "y": 500, "w": 148}
    for bad, msg in [({"cells": [100, 114]}, "needs cell_w"), ({"cell_w": 11}, "without cells"),
                     ({"cells": [100, 114], "cell_w": 11, "comb": 14}, "exclusive"),
                     ({"cells": [114, 100], "cell_w": 11}, "strictly increasing"),
                     ({"cells": [100, 240], "cell_w": 11}, "must lie inside")]:
        with pytest.raises(ValueError, match=msg):
            _pack(lines=[{"line": "ssn", "label": "SSN", "type": "text", "overlay": {**base, **bad}}])


def test_js4c_a_value_printed_in_several_places_is_stamped_and_verified_in_each(tmp_path):
    blank = _blank(tmp_path / "blank.pdf")
    boxes = [{"page": 1, "x": 200, "y": ROW["name"], "w": 150}, {"page": 2, "x": 300, "y": 740, "w": 150}]
    both = _pack(lines=[{"line": "name", "label": "Name", "type": "text", "overlay": boxes}])
    out = Path(stamp_overlay(blank, both, {"name": "Tess Q"}, tmp_path / "o.pdf").out_path)
    report = verify_overlay(both, out, {"name": "Tess Q"})
    assert report.ok and [c.page for c in report.checks] == [1, 2]
    # a PDF stamped from the first placement only: the page-2 header copy is missing, and that FAILS
    first = _pack(lines=[{"line": "name", "label": "Name", "type": "text", "overlay": boxes[0]}])
    partial = Path(stamp_overlay(blank, first, {"name": "Tess Q"}, tmp_path / "p.pdf").out_path)
    checks = verify_overlay(both, partial, {"name": "Tess Q"}).checks
    assert [(c.page, c.status) for c in checks] == [(1, "PASS"), (2, "FAIL")]
    with pytest.raises(ValueError, match="has 2 page"):
        stamp_overlay(blank, _pack(lines=[{"line": "name", "label": "Name", "type": "text",
                                           "overlay": [boxes[0], {**boxes[1], "page": 3}]}]), {"name": "x"}, tmp_path / "q.pdf")


# ── Phase J JS4d: machine-read forms (HI N-11) — painted ovals, digit cells, the minus box ──


def _hi_pack(**over):
    lines = [
        {"line": "yes", "label": "Oval", "type": "checkbox",
         "overlay": {"page": 1, "x": 300, "y": 500, "w": 16, "h": 8, "mark": "fill"}},
        {"line": "amt", "label": "Amount", "type": "money",
         "overlay": {"page": 1, "x": 300, "y": 470, "w": 115, "cells": [302, 315, 334, 347, 360, 379, 392, 402], "cell_w": 10,
                     "minus": {"x": 280, "y": 468, "w": 12, "h": 10}}},
    ]
    return _pack(lines=over.pop("lines", lines), **over)


def test_js4d_a_fill_mark_paints_the_oval_and_the_verdict_reads_the_paint(tmp_path):
    blank = _blank(tmp_path / "blank.pdf")
    pack = _hi_pack()
    out = Path(stamp_overlay(blank, pack, {"yes": "yes"}, tmp_path / "o.pdf").out_path)
    report = verify_overlay(pack, out, {"yes": "yes"})
    assert report.ok, [c.detail for c in report.checks]
    assert next(c for c in report.checks if c.line == "yes").detail.count("painted") == 1
    # the painted shape is the printed oval — straight sides, round ends — not an ellipse inscribed in the box
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(out))
    try:
        dark = _darkness(doc, 1, (300, 500, 16, 8), {}, inset=0)
    finally:
        doc.close()
    oval, ellipse = (64 + 3.14159 * 16) / 128, 3.14159 / 4
    assert abs(dark - oval) < 0.04 and dark - ellipse > 0.06
    empty = Path(stamp_overlay(blank, pack, {"amt": 5}, tmp_path / "e.pdf").out_path)
    bad = next(c for c in verify_overlay(pack, empty, {"yes": "yes", "amt": 5}).checks if c.line == "yes")
    assert bad.status == "FAIL" and "expected the oval" in bad.detail


def test_js4d_money_in_digit_cells_fills_from_the_right_and_a_loss_shades_the_minus_box(tmp_path):
    blank = _blank(tmp_path / "blank.pdf")
    pack = _hi_pack()
    gain = stamp_overlay(blank, pack, {"amt": 1234}, tmp_path / "g.pdf")
    (s,) = gain.stamped_lines
    assert s.value == "1234"                                      # the grouping is printed; no comma cell
    assert s.x == pytest.approx(360 + (10 - text_width("1", 9)) / 2, abs=1e-3)   # ones digit in the LAST cell
    assert verify_overlay(pack, Path(gain.out_path), {"amt": 1234}).ok
    loss = stamp_overlay(blank, pack, {"amt": -1234}, tmp_path / "l.pdf")
    assert loss.stamped_lines[0].value == "1234"                  # digits unsigned, the minus box shaded
    assert verify_overlay(pack, Path(loss.out_path), {"amt": -1234}).ok
    wrong = next(c for c in verify_overlay(pack, Path(loss.out_path), {"amt": 1234}).checks if c.line == "amt")
    assert wrong.status == "FAIL" and "minus box" in wrong.detail  # a shaded minus where no loss is expected
    no_minus = _pack(lines=[{"line": "amt", "label": "Amount", "type": "money",
                             "overlay": {"page": 1, "x": 300, "y": 470, "w": 110, "cells": [302, 315, 334], "cell_w": 10}}])
    with pytest.raises(ValueError, match="sign would silently vanish"):
        stamp_overlay(blank, no_minus, {"amt": -12}, tmp_path / "n.pdf")


def test_js4d_marks_are_validated():
    with pytest.raises(ValueError, match="needs h"):
        _pack(lines=[{"line": "c", "label": "c", "type": "checkbox", "overlay": {"page": 1, "x": 1, "y": 1, "w": 5, "mark": "fill"}}])
    with pytest.raises(ValueError, match="checkbox lines only"):
        _pack(lines=[{"line": "t", "label": "t", "type": "text", "overlay": {"page": 1, "x": 1, "y": 1, "w": 5, "h": 5, "mark": "fill"}}])
    with pytest.raises(ValueError, match="money lines only"):
        _pack(lines=[{"line": "t", "label": "t", "type": "text",
                      "overlay": {"page": 1, "x": 1, "y": 1, "w": 5, "minus": {"x": 0, "y": 0, "w": 3, "h": 3}}}])
