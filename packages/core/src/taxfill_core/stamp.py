"""Page stamps drawn into the content stream, and the check that they print (Phase K JK16, 2026-10-25).

KG5 (docs/dev/ROADMAP.md, Phase K; ADR-0002): every page of every PDF the pack-less fallback writes carries
"UNMAPPED DRAFT — NOT FILING-GRADE", drawn into the page's content stream, inside the page's visible box, where it
prints. The rehearsal stamp (filler.REHEARSAL_STAMP, core-only rehearsal fills) is drawn the same way (ADR-0002 Open
question 6): until JK16 it was a pypdf FreeText annotation with no Print flag, placed from the MediaBox top, so it
did not print, any viewer could delete it, and on a page that crops a window out of its MediaBox it sat off the page.

Placement. Widget appearances paint ABOVE page content, so a stamp under a visible widget can be covered in print.
:func:`draw_stamp` therefore places the stamp where no annotation that a viewer or printer may draw lies (every
annotation but a Hidden one, a /Link or a /Popup), inside the visible box (``filler.visible_box``) and the MediaBox,
at least STAMP_EDGE_MARGIN from the visible edge (a printer's unprintable margin), choosing the spot with the least
printed ink on a render of the blank (the page's own text stays legible) — the topmost such spot at the largest size
in STAMP_SIZES. A page with no spot clear of every annotation is refused (:class:`StampRefused`), never stamped
under a widget, and so is a page whose least-inked spot is still shaded (more than _PLACE_MAX_INK of it inked), never
stamped small onto the art. The text is set in the base-14 Helvetica through the overlay's content-stream writer
(``overlay._text_op`` / ``overlay._overlay_page``, merged with ``merge_page``), in a dark red that prints dark on a
greyscale printer.

:func:`stamp_check` (reused by JK17's verify): per page, the stamp text is in pdfium's text layer, drawn visibly
(not render mode 3), whole inside the visible box at least STAMP_EDGE_MARGIN from its edge, AND it is legible on the
print path: on a pdfium render of the print path (``optimize_mode="print"``, annotations and form fields drawn, as
render_form draws them), the stamp's glyph pixels (where the stamp alone, every other object removed, draws ink) must
differ by at least a fixed contrast from the same render with the stamp's own text object removed. A page with the
stamp stripped fails (no text), and so do a stamp under a printing annotation, under content drawn over it (a black
or grey box, dense stripes), drawn on shaded art it does not stand out from, and a stamp a CropBox cuts. Phase K JK16
(2026-10-25): the check used to look for dark pixels only, so a blacked-out, low-contrast or cropped stamp passed.
It reads no OCR, and taxfill-core never will: the OCR read of every page is a CI test (ADR-0002 Open question 5,
answered in Phase K JEe2, 2026-10-25): packages/core/tests/test_stamp_ocr.py hands pdfium's print-path render of a
pack-less draft and a rehearsal fill to the tesseract CLI, which .github/workflows/ci.yml installs on the runner.
"""
from __future__ import annotations

import io
from collections.abc import Sequence
from itertools import accumulate
from pathlib import Path

__all__ = [
    "STAMP_EDGE_MARGIN",
    "STAMP_SIZES",
    "StampRefused",
    "draw_stamp",
    "stamp_check",
]

# Point sizes tried, largest first; the stamp keeps the largest that fits clear of every annotation.
STAMP_SIZES = (10.0, 9.0, 8.0, 7.0, 6.0)
# pt: the least distance from the visible box's edge (desktop printers leave about 1/8 in unprinted).
STAMP_EDGE_MARGIN = 9.0
# pt: clearance kept around the text box (and around every annotation it avoids).
_PAD = 2.0
# Helvetica's ascender and descender, 1/1000 em (the Core-14 AFM: 718 / -207).
_ASCENT, _DESCENT = 0.718, 0.207
# The stamp's colour: dark red (luminance about 61 of 255 on a greyscale render or printer).
_RGB = b"0.8 0 0 rg"
# Placement render: pixels per point, and the grey level below which a pixel is printed ink.
_PLACE_SCALE = 0.5
_PLACE_INK = 235
_STEP_X = 4.0  # pt between candidate positions across the page (down the page: one render pixel)
_BLOCKED = 1 << 30
# Placement (Phase K JK16, 2026-10-25): a page whose least-inked spot is still more than this share inked (shaded art
# everywhere) is refused rather than stamped small onto it.
_PLACE_MAX_INK = 0.2
# Check render: pixels per point; a glyph pixel is one the stamp alone draws darker than _CHECK_INK; the stamp alone
# must ink at least _CHECK_MIN_INK of its box, and at least _CHECK_LEGIBLE of its glyph pixels must differ by
# _CHECK_CONTRAST grey levels (of 255) between the print render and the same render without the stamp. Dark red on
# white differs by about 190; the stamp on a 0.12-grey page by about 30.
_CHECK_SCALE = 3.0
_CHECK_INK = 128
_CHECK_MIN_INK = 0.04
_CHECK_CONTRAST = 96
_CHECK_LEGIBLE = 0.9
_EDGE_TOLERANCE = 0.5  # pt: charboxes are measured, the placement is computed
_IGNORED_SUBTYPES = frozenset({"/Link", "/Popup"})
_F_HIDDEN = 2


class StampRefused(ValueError):
    """A page has no place for the stamp clear of every annotation; nothing was written."""


def _device_rect(box: tuple[float, float, float, float], rotation: int, scale: float,
                 rect: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """A user-space rect (x0, y0, x1, y1) as render pixels (c0, r0, c1, r1), for a page rendered from ``box``
    (left, bottom, right, top) with its /Rotate applied (pdfium renders the rotated page)."""
    left, bottom, right, top = box
    x0, y0, x1, y1 = rect
    if rotation == 90:
        cs, rs = ((y0 - bottom), (y1 - bottom)), ((x0 - left), (x1 - left))
    elif rotation == 180:
        cs, rs = ((right - x1), (right - x0)), ((y0 - bottom), (y1 - bottom))
    elif rotation == 270:
        cs, rs = ((top - y1), (top - y0)), ((right - x1), (right - x0))
    else:
        cs, rs = ((x0 - left), (x1 - left)), ((top - y1), (top - y0))
    return (int(cs[0] * scale), int(rs[0] * scale), int(cs[1] * scale + 0.999), int(rs[1] * scale + 0.999))


def _obstacles(page) -> list[tuple[float, float, float, float]]:
    """Every annotation a viewer or printer may draw on a pypdf page: all but Hidden ones, links and popups."""
    out = []
    for ref in page.get("/Annots") or []:
        annot = ref.get_object()
        if annot.get("/Subtype") in _IGNORED_SUBTYPES or int(annot.get("/F", 0)) & _F_HIDDEN:
            continue
        rect = annot.get("/Rect")
        if rect is None or len(rect) != 4:
            continue
        xs, ys = sorted((float(rect[0]), float(rect[2]))), sorted((float(rect[1]), float(rect[3])))
        out.append((xs[0], ys[0], xs[1], ys[1]))
    return out


def _cost_table(pdfium_page, obstacles, scale: float):
    """A summed-area table over the page render: 1 per inked pixel, _BLOCKED per pixel under an obstacle."""
    bitmap = pdfium_page.render(scale=scale, grayscale=True, draw_annots=False, may_draw_forms=False)
    buf, width, height, stride = bytes(bitmap.buffer), bitmap.width, bitmap.height, bitmap.stride
    rows = [[1 if b < _PLACE_INK else 0 for b in buf[r * stride:r * stride + width]] for r in range(height)]
    box = tuple(pdfium_page.get_bbox())
    rotation = pdfium_page.get_rotation() % 360
    for rect in obstacles:
        c0, r0, c1, r1 = _device_rect(box, rotation, scale, (rect[0] - _PAD, rect[1] - _PAD,
                                                             rect[2] + _PAD, rect[3] + _PAD))
        for r in range(max(0, r0), min(height, r1)):
            row = rows[r]
            for c in range(max(0, c0), min(width, c1)):
                row[c] = _BLOCKED
    table = [[0] * (width + 1)]
    for row in rows:
        prev = table[-1]
        table.append([0, *map(int.__add__, prev[1:], accumulate(row))])
    return table, width, height, box, rotation


def _cost(table, width: int, height: int, cell: tuple[int, int, int, int]) -> int:
    c0, r0, c1, r1 = max(0, cell[0]), max(0, cell[1]), min(width, cell[2]), min(height, cell[3])
    if c1 <= c0 or r1 <= r0:
        return _BLOCKED
    return table[r1][c1] - table[r0][c1] - table[r1][c0] + table[r0][c0]


def _place(pdfium_page, visible, obstacles, text: str, *, page_no: int, what: str) -> tuple[float, float, float]:
    """(x, baseline y, size) for the stamp on one page: clear of every obstacle, least ink, largest size, topmost."""
    from taxfill_core.overlay import text_width  # noqa: PLC0415 — the overlay's Helvetica metrics

    table, width, height, box, rotation = _cost_table(pdfium_page, obstacles, _PLACE_SCALE)
    left, bottom, right, top = visible
    best: tuple[int, float, float, float] | None = None  # (ink, x, y, size)
    best_share = 1.0
    for size in STAMP_SIZES:
        w = text_width(text, size)
        ascent, descent = _ASCENT * size, _DESCENT * size
        y = top - STAMP_EDGE_MARGIN - ascent
        step_y = 1.0 / _PLACE_SCALE
        while y - descent >= bottom + STAMP_EDGE_MARGIN:
            x = left + STAMP_EDGE_MARGIN
            while x + w <= right - STAMP_EDGE_MARGIN:
                cell = _device_rect(box, rotation, _PLACE_SCALE,
                                    (x - _PAD, y - descent - _PAD, x + w + _PAD, y + ascent + _PAD))
                ink = _cost(table, width, height, cell)
                if ink < _BLOCKED and (best is None or ink < best[0]):
                    best = (ink, x, y, size)
                    best_share = ink / max(1, (min(width, cell[2]) - max(0, cell[0]))
                                           * (min(height, cell[3]) - max(0, cell[1])))
                    if ink == 0:
                        return x, y, size
                x += _STEP_X
            y -= step_y
    if best is None:
        raise StampRefused(
            f"page {page_no} of {what} has no place for the stamp {text!r} clear of its fields and annotations, so "
            f"the page cannot carry the draft stamp where it prints — no PDF was written; this form cannot be "
            f"drafted here: print the blank from the agency's forms page and fill it by hand"
        )
    if best_share > _PLACE_MAX_INK:
        raise StampRefused(
            f"page {page_no} of {what} has no clear place for the stamp {text!r}: every spot clear of its fields is "
            f"printed over (shaded art), so the stamp would not stand out in print — no PDF was written; this form "
            f"cannot be drafted here: print the blank from the agency's forms page and fill it by hand"
        )
    return best[1], best[2], best[3]


def draw_stamp(writer, blank_pdf: str | Path, text: str, *,
               extra_obstacles: Sequence[Sequence[tuple[float, float, float, float]]] | None = None,
               what: str = "the form") -> list[dict]:
    """Draw ``text`` into every page's content stream of ``writer`` (pages aligned with ``blank_pdf``'s).

    The place is chosen per page on a render of ``blank_pdf`` (module doc), clear of the writer page's drawable
    annotations as they stand now (call it after the fill's flag pass, so a viewer guard the fill hid does not count)
    and of ``extra_obstacles[page_index]``. Returns ``[{"page", "rect", "size"}]`` (rect in user space). Raises
    :class:`StampRefused` when a page has no room; nothing is drawn then on any page.
    """
    import pypdfium2 as pdfium  # noqa: PLC0415

    from taxfill_core.filler import visible_box  # noqa: PLC0415
    from taxfill_core.overlay import _overlay_page, _text_op, text_width  # noqa: PLC0415

    doc = pdfium.PdfDocument(str(blank_pdf))
    placements = []
    try:
        if len(doc) != len(writer.pages):
            raise ValueError(f"{what}: the stamp's reference blank has {len(doc)} pages, the output "
                             f"{len(writer.pages)} — stamp the copy of the blank it was made from")
        for index, page in enumerate(writer.pages):
            vx0, vy0, vx1, vy1 = visible_box(page)
            mb = page.mediabox
            visible = (max(vx0, float(mb.left)), max(vy0, float(mb.bottom)),
                       min(vx1, float(mb.right)), min(vy1, float(mb.top)))
            obstacles = _obstacles(page) + list((extra_obstacles or [])[index] if extra_obstacles else [])
            placements.append(_place(doc[index], visible, obstacles, text, page_no=index + 1, what=what))
    finally:
        doc.close()
    out = []
    for index, (page, (x, y, size)) in enumerate(zip(writer.pages, placements)):
        op, warning = _text_op(x, y, size, text)
        if warning:  # the stamps are WinAnsi text; a caller passing anything else is a programming error
            raise ValueError(f"stamp text {text!r} is not WinAnsi: {warning}")
        page.merge_page(_overlay_page(page, b"q " + _RGB + b" " + op + b"Q\n"))
        w = text_width(text, size)
        out.append({"page": index + 1, "rect": [round(x, 2), round(y - _DESCENT * size, 2), round(x + w, 2),
                                                round(y + _ASCENT * size, 2)], "size": size})
    return out


def _grey(bitmap, box, rotation, rect) -> dict[int, int]:
    """Grey level per render pixel inside ``rect`` (user space), keyed by row * width + column."""
    buf, width, height, stride, channels = (bytes(bitmap.buffer), bitmap.width, bitmap.height, bitmap.stride,
                                            bitmap.n_channels)
    c0, r0, c1, r1 = _device_rect(box, rotation, _CHECK_SCALE, rect)
    c0, r0, c1, r1 = max(0, c0), max(0, r0), min(width, c1), min(height, r1)
    return {r * width + c: buf[r * stride + c * channels] for r in range(r0, r1) for c in range(c0, c1)}


def _address(handle) -> int:
    import ctypes  # noqa: PLC0415

    return ctypes.cast(handle, ctypes.c_void_p).value or 0


def _object_indexes(page, addresses: set[int]) -> set[int]:
    """The top-level object indexes of a pdfium page whose handles are ``addresses`` (an index names the same object
    in another copy of the same bytes; a handle does not)."""
    import pypdfium2.raw as pdfium_c  # noqa: PLC0415

    return {i for i in range(pdfium_c.FPDFPage_CountObjects(page.raw))
            if _address(pdfium_c.FPDFPage_GetObject(page.raw, i)) in addresses}


def _remove_objects(page, *, keep: set[int] | None = None, drop: set[int] | None = None) -> None:
    """Remove top-level page objects, by index, from a pdfium page in memory (renders then omit them): every object in
    ``drop``, or every object not in ``keep``."""
    import pypdfium2.raw as pdfium_c  # noqa: PLC0415

    handles = [pdfium_c.FPDFPage_GetObject(page.raw, i) for i in range(pdfium_c.FPDFPage_CountObjects(page.raw))]
    for i, handle in enumerate(handles):
        if (drop is not None and i in drop) or (keep is not None and i not in keep):
            if pdfium_c.FPDFPage_RemoveObject(page.raw, handle):
                pdfium_c.FPDFPageObj_Destroy(handle)


def _check_page(doc, alone_doc, index: int, text: str) -> dict:
    import pypdfium2.raw as pdfium_c  # noqa: PLC0415

    page = doc[index]
    result: dict = {"page": index + 1, "ok": False, "found": False, "box": None, "ink": 0.0, "legible": 0.0}
    textpage = page.get_textpage()
    try:
        searcher = textpage.search(text, match_case=True)
        hits = []
        while (hit := searcher.get_next()) is not None:
            start, count = hit
            chars = [i for i in range(start, start + count) if chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, i)).strip()]
            objects = {_address(pdfium_c.FPDFText_GetTextObject(textpage.raw, i)) for i in chars}
            visible = all(
                (obj := pdfium_c.FPDFText_GetTextObject(textpage.raw, i)) and
                pdfium_c.FPDFTextObj_GetTextRenderMode(obj) != pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE for i in chars)
            charboxes = [textpage.get_charbox(i) for i in range(start, start + count)]
            hits.append((visible, objects, (min(b[0] for b in charboxes), min(b[1] for b in charboxes),
                                            max(b[2] for b in charboxes), max(b[3] for b in charboxes))))
    finally:
        textpage.close()
    if not hits:
        result["problem"] = "the stamp text is not in the page's text layer (stripped)"
        return result
    result["found"] = True
    box, rotation = tuple(page.get_bbox()), page.get_rotation() % 360
    left, bottom, right, top = box
    margin = STAMP_EDGE_MARGIN - _EDGE_TOLERANCE
    printed = page.render(scale=_CHECK_SCALE, grayscale=True, optimize_mode="print", draw_annots=True,
                          may_draw_forms=True)
    alone_page = None
    for visible, objects, rect in hits:
        result["box"] = [round(v, 2) for v in rect]
        if not visible:
            result["problem"] = "the stamp text is drawn invisibly (render mode 3)"
            continue
        if not (rect[0] >= left + margin and rect[1] >= bottom + margin and rect[2] <= right - margin
                and rect[3] <= top - margin):
            result["problem"] = (f"the stamp is not whole inside the page's visible box, {STAMP_EDGE_MARGIN:g} pt from "
                                 f"its edge (a CropBox cuts it, or it sits in the unprintable margin)")
            continue
        indexes = _object_indexes(page, objects)
        if len(indexes) != len(objects):
            result["problem"] = "the stamp is not drawn as the page's own content (it sits inside another object)"
            continue
        if alone_page is None:  # the stamp's objects (every hit's) alone on the page, once
            alone_page = alone_doc[index]
            _remove_objects(alone_page, keep=_object_indexes(page, set().union(*(h[1] for h in hits))))
        alone = _grey(alone_page.render(scale=_CHECK_SCALE, grayscale=True, draw_annots=False, may_draw_forms=False),
                      box, rotation, rect)
        glyphs = [k for k, v in alone.items() if v < _CHECK_INK]
        with_stamp = _grey(printed, box, rotation, rect)
        _remove_objects(page, drop=indexes)
        without = _grey(page.render(scale=_CHECK_SCALE, grayscale=True, optimize_mode="print", draw_annots=True,
                                    may_draw_forms=True), box, rotation, rect)
        ink = len(glyphs) / max(1, len(alone))
        legible = (sum(1 for k in glyphs if abs(with_stamp[k] - without[k]) >= _CHECK_CONTRAST) / len(glyphs)
                   if glyphs else 0.0)
        result.update(ink=round(ink, 3), legible=round(legible, 3))
        if ink >= _CHECK_MIN_INK and legible >= _CHECK_LEGIBLE:
            result["ok"] = True
            result.pop("problem", None)
            return result
        result["problem"] = ("the stamp text leaves no ink on the page" if ink < _CHECK_MIN_INK else
                             "the stamp is not legible on the print path (an annotation, a field or content drawn "
                             "over it covers it, or it does not stand out from what is printed under it)")
    return result


def stamp_check(pdf: str | Path | bytes, text: str) -> dict:
    """Whether every page of ``pdf`` carries ``text`` as a stamp that prints (module doc).

    Returns ``{"ok", "text", "pages": [{"page", "ok", "found", "box", "ink", "legible", "problem"?}],
    "failed_pages"}``; ``ok`` only when every page passes. Reads the text layer and three pdfium renders per page
    (print path with and without the stamp, the stamp alone); no OCR. The PDF is never changed: the stamp is removed
    from in-memory copies only.
    """
    import pypdfium2 as pdfium  # noqa: PLC0415

    from taxfill_core.datadir import user_path  # noqa: PLC0415

    data = pdf if isinstance(pdf, bytes) else user_path(pdf).read_bytes()
    doc = pdfium.PdfDocument(io.BytesIO(data))
    alone_doc = pdfium.PdfDocument(io.BytesIO(data))  # a second copy, emptied but for each stamp in turn
    try:
        try:
            doc.init_forms()  # draw form fields on the print path, as render_form does
        except Exception:  # noqa: BLE001 — no form layer: page content and annotations still render
            pass
        pages = [_check_page(doc, alone_doc, i, text) for i in range(len(doc))]
    finally:
        alone_doc.close()
        doc.close()
    failed = [p["page"] for p in pages if not p["ok"]]
    return {"ok": bool(pages) and not failed, "text": text, "pages": pages, "failed_pages": failed}
