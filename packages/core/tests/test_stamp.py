"""Content-stream stamps and the check that they print (Phase K JK16, 2026-10-25; KG5, ADR-0002 Open question 6).

The stamp is drawn into each page's content stream inside the visible box, clear of every annotation a viewer or
printer may draw, and :func:`taxfill_core.stamp.stamp_check` holds it to the print path: the text is in pdfium's text
layer and a print-mode render shows its ink there. A page whose stamp was stripped fails, and so does a page where a
printing annotation covers it. No OCR is read (ADR-0002 Open question 5 is the user's).
"""
from __future__ import annotations

import io
import re

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    RectangleObject,
)

from taxfill_core.filler import UNMAPPED_STAMP
from taxfill_core.stamp import StampRefused, draw_stamp, stamp_check

from pdf_fixtures import make_acroform_pdf

TEXTS = [(1, 60, 700, "1 Wages"), (2, 60, 700, "2 Interest"), (3, 60, 700, "3 Dividends")]


def _blank(tmp_path, *, fields=None, name="blank.pdf", **kwargs):
    fields = fields if fields is not None else [
        {"name": f"f{p}", "page": p, "x": 300, "y": 696, "width": 120, "height": 16} for p in (1, 2, 3)]
    return make_acroform_pdf(tmp_path / name, fields, texts=TEXTS, draw_labels=False, **kwargs)


def _stamped(blank) -> tuple[bytes, list[dict]]:
    writer = PdfWriter(clone_from=str(blank))
    placed = draw_stamp(writer, blank, UNMAPPED_STAMP)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), placed


def _edit(data: bytes, fn) -> bytes:
    writer = PdfWriter(clone_from=io.BytesIO(data))
    fn(writer)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_every_page_carries_the_stamp_in_its_content_stream_where_it_prints(tmp_path):
    data, placed = _stamped(_blank(tmp_path))
    reader = PdfReader(io.BytesIO(data))
    assert [p["page"] for p in placed] == [1, 2, 3]
    for page in reader.pages:
        assert UNMAPPED_STAMP in page.extract_text()  # page content, not an annotation
        assert all(a.get_object().get("/Subtype") == "/Widget" for a in page.get("/Annots") or [])
    check = stamp_check(data, UNMAPPED_STAMP)
    assert check["ok"] and check["failed_pages"] == [], check
    assert all(p["found"] and p["ink"] >= 0.04 and p["legible"] >= 0.9 for p in check["pages"])


def test_the_stamp_avoids_every_widget_and_stays_in_the_visible_box(tmp_path):
    # a field across the whole top band: the stamp must go below it, never under it
    fields = [{"name": "top", "page": 1, "x": 0, "y": 700, "width": 612, "height": 92}]
    blank = make_acroform_pdf(tmp_path / "b.pdf", fields, texts=[(1, 60, 600, "1 Wages")], draw_labels=False)
    data, placed = _stamped(blank)
    x0, y0, x1, y1 = placed[0]["rect"]
    assert y1 < 700 and x0 >= 9 and x1 <= 603
    # a cropped page: the stamp is placed inside the CropBox, not from the MediaBox top
    crop_pdf = tmp_path / "cropped.pdf"
    crop_pdf.write_bytes(_edit(_blank(tmp_path, name="c.pdf").read_bytes(),
                               lambda w: setattr(w.pages[0], "cropbox", RectangleObject([0, 300, 612, 500]))))
    data, placed = _stamped(crop_pdf)
    assert 300 <= placed[0]["rect"][1] and placed[0]["rect"][3] <= 500
    assert stamp_check(data, UNMAPPED_STAMP)["ok"]


def test_a_page_with_no_room_is_refused(tmp_path):
    fields = [{"name": "all", "page": 1, "x": 0, "y": 0, "width": 612, "height": 792}]
    blank = make_acroform_pdf(tmp_path / "full.pdf", fields, texts=[(1, 60, 600, "1 Wages")], draw_labels=False)
    with pytest.raises(StampRefused, match="no place for the stamp"):
        draw_stamp(PdfWriter(clone_from=str(blank)), blank, UNMAPPED_STAMP)


def test_stamp_check_fails_a_stripped_page(tmp_path):
    data, _ = _stamped(_blank(tmp_path))

    def strip(writer):
        page = writer.pages[1]
        content = page.get_contents()
        raw = content.get_data()
        stripped, n = re.subn(rb"\(UNMAPPED DRAFT[^)]*\) Tj", b"() Tj", raw)
        assert n == 1
        content.set_data(stripped)
        page.replace_contents(content)

    check = stamp_check(_edit(data, strip), UNMAPPED_STAMP)
    assert not check["ok"] and check["failed_pages"] == [2]
    assert "stripped" in check["pages"][1]["problem"]


def test_stamp_check_fails_a_page_where_a_printing_annotation_covers_the_stamp(tmp_path):
    data, placed = _stamped(_blank(tmp_path))
    x0, y0, x1, y1 = placed[2]["rect"]

    def cover(writer, flags=4):
        ap = DecodedStreamObject()
        ap.set_data(b"1 g 0 0 400 40 re f")
        ap.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                   NameObject("/BBox"): ArrayObject([FloatObject(v) for v in (0, 0, 400, 40)])})
        square = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Square"),
            NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (x0 - 5, y0 - 5, x0 + 395, y0 + 35)]),
            NameObject("/F"): NumberObject(flags),  # 4: Print
            NameObject("/AP"): DictionaryObject({NameObject("/N"): writer._add_object(ap)}),
        })
        writer.pages[2][NameObject("/Annots")] = ArrayObject(
            [*(writer.pages[2].get("/Annots") or []), writer._add_object(square)])

    check = stamp_check(_edit(data, cover), UNMAPPED_STAMP)
    assert not check["ok"] and check["failed_pages"] == [3], check
    assert "print path" in check["pages"][2]["problem"]
    # the same white box WITHOUT the Print flag is not drawn on the print path, so the page still passes there
    assert stamp_check(_edit(data, lambda w: cover(w, flags=0)), UNMAPPED_STAMP)["ok"]


def test_the_old_free_text_annotation_stamp_fails_the_check(tmp_path):
    # the pre-JK16 rehearsal stamp: a pypdf FreeText annotation, no Print flag — not in the text layer, never printed
    from pypdf.annotations import FreeText

    blank = _blank(tmp_path)
    writer = PdfWriter(clone_from=str(blank))
    for index in range(3):
        writer.add_annotation(page_number=index, annotation=FreeText(
            text=UNMAPPED_STAMP, rect=(36, 762, 420, 780), font="Helvetica", bold=True, font_size="11pt",
            font_color="cc0000", border_color=None, background_color=None))
    buf = io.BytesIO()
    writer.write(buf)
    assert stamp_check(buf.getvalue(), UNMAPPED_STAMP)["failed_pages"] == [1, 2, 3]


# ── a legible stamp, not just dark pixels (Phase K JK16 verifier fixes, 2026-10-25) ─────────────────────────────────


def _over_stamp(placed, page: int, content: bytes):
    """Draw ``content`` (with %(x)s-style box fields) into page ``page``'s content stream, after the stamp."""
    from taxfill_core.overlay import _overlay_page  # noqa: PLC0415

    x0, y0, x1, y1 = placed[page - 1]["rect"]
    box = {"x": x0 - 2, "y": y0 - 2, "w": x1 - x0 + 4, "h": y1 - y0 + 4, "x0": x0, "x1": x1, "y0": y0, "y1": y1}

    def edit(writer):
        target = writer.pages[page - 1]
        target.merge_page(_overlay_page(target, content(box)))

    return edit


@pytest.mark.parametrize("cover", [
    lambda b: b"q 0 g %.2f %.2f %.2f %.2f re f Q\n" % (b["x"], b["y"], b["w"], b["h"]),     # blacked out
    lambda b: b"q 0.3 g %.2f %.2f %.2f %.2f re f Q\n" % (b["x"], b["y"], b["w"], b["h"]),   # a dark grey box
    lambda b: b"q 0 g " + b"".join(b"%.2f %.2f 1.2 %.2f re " % (b["x0"] + i * 1.5, b["y"], b["h"])   # dense stripes
                                   for i in range(int((b["x1"] - b["x0"]) / 1.5))) + b"f Q\n",
], ids=["black", "grey", "stripes"])
def test_stamp_check_fails_a_stamp_that_content_drawn_over_it_hides(tmp_path, cover):
    data, placed = _stamped(_blank(tmp_path))
    check = stamp_check(_edit(data, _over_stamp(placed, 2, cover)), UNMAPPED_STAMP)
    assert check["failed_pages"] == [2], check
    assert "not legible" in check["pages"][1]["problem"] and check["pages"][1]["ink"] >= 0.04


@pytest.mark.parametrize("crop", ["half_height", "last_30_percent"])
def test_stamp_check_fails_a_stamp_a_cropbox_cuts(tmp_path, crop):
    data, placed = _stamped(_blank(tmp_path))
    x0, y0, x1, y1 = placed[0]["rect"]

    def cut(writer):
        page = writer.pages[0]
        if crop == "half_height":
            page.cropbox = RectangleObject([0, 0, 612, y0 + (y1 - y0) / 2])
        else:
            page.cropbox = RectangleObject([x0 + (x1 - x0) * 0.7, 0, 612, 792])

    check = stamp_check(_edit(data, cut), UNMAPPED_STAMP)
    assert check["failed_pages"] == [1] and "visible box" in check["pages"][0]["problem"], check


def _shade(data: bytes, grey: bytes = b"0.12") -> bytes:
    """Paint every page grey UNDER its existing content (shaded art: the page's own text stays on top)."""
    def under(writer):
        for page in writer.pages:
            content = page.get_contents()
            fresh = DecodedStreamObject()
            fresh.set_data(b"q " + grey + b" g 0 0 612 792 re f Q\n" + content.get_data())
            page[NameObject("/Contents")] = writer._add_object(fresh)

    return _edit(data, under)


def test_a_stamp_on_dark_shaded_art_fails_the_check_and_draw_stamp_refuses_such_a_page(tmp_path):
    data, _ = _stamped(_blank(tmp_path))
    check = stamp_check(_shade(data), UNMAPPED_STAMP)  # stamped first, then shaded under: present but barely visible
    assert check["failed_pages"] == [1, 2, 3] and "not legible" in check["pages"][0]["problem"], check
    shaded = tmp_path / "shaded.pdf"
    shaded.write_bytes(_shade(_blank(tmp_path, name="s.pdf").read_bytes()))
    with pytest.raises(StampRefused, match="no clear place"):  # never shrunk onto the art
        draw_stamp(PdfWriter(clone_from=str(shaded)), shaded, UNMAPPED_STAMP)
    light = tmp_path / "light.pdf"  # a light tint is not ink: the stamp is placed and legible there
    light.write_bytes(_shade(_blank(tmp_path, name="l.pdf").read_bytes(), b"0.95"))
    assert stamp_check(_stamped(light)[0], UNMAPPED_STAMP)["ok"]
