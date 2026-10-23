"""Phase K JK28 — P-033: comb cells against the separators printed in the box.

A comb widget's cells are its /Rect split evenly: "the field shall be automatically divided into as many equally
spaced positions, or combs, as the value of MaxLen" (ISO 32000-1:2008, 12.7.4.3, Table 228). On the IRS Form 1040
and 1040-X SSN boxes (2023-2026) the dotted 3-2-4 separators follow a narrower grid than the widget, so in every
viewer that draws the comb the dots crossed the third and fifth digits (found by the JK5 release-candidate
walkthrough). fill_form now narrows such a widget to the grid its separators imply before any appearance is built
(filler.comb_cell_grid over filler.vertical_strokes). The stroke figures below were measured on the cached blanks
(Phase K JK28, 2026-10-16).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject

from taxfill_core.filler import _FF_COMB, comb_cell_grid, fill_form
from taxfill_core.schemas.formpack import FormPack
from taxfill_core.verify import verify_form

REPO_ROOT = Path(__file__).resolve().parents[3]
SCALE = 600 / 72  # 600 dpi: one pixel is 0.12 pt


# ---------------------------------------------------------------------------
# comb_cell_grid on the measured boxes (offline: the strokes are literals)
# ---------------------------------------------------------------------------

# (rect, MaxLen, /DA size, the blank's vertical strokes near the box as (x, bottom, top), expected extent)
IRS_BOXES = {
    # 2025 Form 1040 "Your social security number" (Page1 f1_16): left rule 468.0, dots at 500.7 / 522.4. The cells
    # start at the rule and narrow to 10.885 pt so the dots sit on the 3|4 and 5|6 boundaries.
    "f1040_2025_own_ssn": ((469.0, 684.0, 576.0, 698.001), 9, 8.0,
                           [(468.0, 659.749, 684.25), (468.0, 683.75, 708.376), (500.7, 684.0, 694.001),
                            (522.4, 684.0, 694.001)], (468.0, 565.968)),
    # 2025 Form 1040 line 26, former spouse's SSN (Page2 f2_22): no rules, dots at 265.0 / 283.0.
    "f1040_2025_former_spouse_ssn": ((237.6, 432.0, 324.0, 443.999), 9, 8.0,
                                     [(265.0, 432.0, 442.001), (283.0, 432.0, 442.001)], (237.6, 319.447)),
    # 2024 Form 1040 dependent 1 (Row1 f1_21): rules 266.4 / 352.8, dots at 293.159 / 311.562.
    "f1040_2024_dependent_ssn": ((266.4, 402.001, 352.8, 414.0), 9, 8.0,
                                 [(266.4, 401.751, 414.25), (293.159, 365.99, 414.0), (311.562, 365.99, 414.0),
                                  (352.8, 401.751, 414.25)], (266.4, 347.423)),
    # Form 1040-X (Rev. December 2025) "Your social security number" (Page1 f1_05): rule 446.4, dots 485.348 / 511.937.
    "f1040x_rev_2025_own_ssn": ((447.4, 677.967, 576.0, 691.968), 9, 8.0,
                                [(446.4, 677.717, 702.218), (485.348, 677.967, 687.968), (511.937, 677.967, 687.968)],
                                (446.4, 564.069)),
    # The 2026 draft Form 1040-X (Page1 f1_15): rule 446.4, dots 486.346 / 511.937 — the anchored fit misses the first
    # dot by 0.46 pt, so the free fit (cells from 447.96) wins.
    "f1040x_2026_draft_own_ssn": ((447.4, 654.466, 576.0, 667.967), 9, 9.0,
                                  [(446.4, 653.716, 678.217), (486.346, 653.966, 663.967),
                                   (511.937, 653.966, 663.967)], (447.96, 563.119)),
}


@pytest.mark.parametrize("box", sorted(IRS_BOXES))
def test_p033_grid_puts_the_irs_separators_between_the_digits(box: str):
    rect, max_len, size, strokes, expected = IRS_BOXES[box]
    grid = comb_cell_grid(rect, max_len, size, strokes)
    assert grid is not None, f"{box}: the separators cross the digits of the widget's own cells"
    assert grid == pytest.approx(expected, abs=0.01)
    # every dot sits within 0.5 pt of a cell boundary of the new grid: 0.278 em either side of each centre is ink-free
    width = (grid[1] - grid[0]) / max_len
    for x, bottom, top in strokes:
        if rect[0] + 1.2 <= x <= rect[2] - 1.2:
            steps = (x - grid[0]) / width
            assert abs(steps - round(steps)) * width < 0.5, (box, x)
    # never past the printed box: the left rule (or the widget's edge) and the widget's right edge
    rules = [x for x, _, _ in strokes if x < rect[0] + 1.2]
    assert grid[0] >= (max(rules) if rules else rect[0]) - 0.5 and grid[1] <= rect[2] + 0.5


def test_p033_grid_leaves_clear_and_unfixable_boxes_alone():
    # 2025 Form 1040 dependent 1 (f1_39): the dots at 180.3 / 204.6 already fall between the digits.
    assert comb_cell_grid((145.0, 447.004, 251.25, 459.003), 9, 8.0,
                          [(144.0, 446.754, 459.253), (180.3, 446.998, 456.999), (204.599, 446.998, 456.999),
                           (252.0, 446.754, 459.253)]) is None
    # AZ Form 140NR 2023 worksheet line 8C: five printed boxes, the last one 8.7 pt wide. The uniform grid through the
    # dividers ends at 557.1, past the box's right rule at 552.5: no uniform comb fits, so the widget is left alone.
    assert comb_cell_grid((490.92, 206.411, 552.098, 219.371), 5, 10.0,
                          [(490.895, 206.48, 222.28), (504.18, 206.48, 222.28), (517.465, 206.48, 222.28),
                           (530.75, 206.48, 222.28), (543.78, 206.48, 222.28), (552.49, 206.48, 222.28)]) is None
    # MO-1040 page 1 SSN_1: three printed boxes with the two dashes in the 7.7 pt gaps; the pack writes the dashes into
    # cells 4 and 7, which sit in those gaps by design. No uniform 11-cell grid puts the gaps on cell boundaries.
    assert comb_cell_grid((57.5868, 383.703, 266.413, 401.735), 11, 10.0,
                          [(57.91, 383.97, 401.47), (122.21, 383.97, 401.47), (129.91, 383.97, 401.47),
                           (172.61, 383.97, 401.47), (180.31, 383.97, 401.47), (266.21, 383.97, 401.47)]) is None
    own = IRS_BOXES["f1040_2025_own_ssn"]
    assert comb_cell_grid(own[0], 9, 8.0, []) is None                                   # nothing printed in the box
    assert comb_cell_grid(own[0], 9, 8.0, [(500.7, 684.0, 686.0), (522.4, 684.0, 686.0)]) is None  # ticks under 25%


# ---------------------------------------------------------------------------
# fill_form on a synthetic SSN box (offline)
# ---------------------------------------------------------------------------

NAVY = (0, 0, 0.502)
PACK = FormPack.model_validate({
    "form": "COMB-1", "jurisdiction": "federal", "tax_year": 2023,
    "source_url": "https://www.irs.gov/pub/irs-pdf/comb1.pdf", "pdf_sha256": "...", "acroform_root": "",
    "fields": [
        {"line": "ssn", "field": "ssn", "type": "text", "maxlen": 9, "comb": True, "format": "ssn_digits_only"},
        {"line": "dependent_ssn", "field": "dependent_ssn", "type": "text", "maxlen": 9, "comb": True,
         "format": "ssn_digits_only"},
        {"line": "bordered_ssn", "field": "bordered_ssn", "type": "text", "maxlen": 9, "comb": True},
        {"line": "pale_ssn", "field": "pale_ssn", "type": "text", "maxlen": 9, "comb": True},
        {"line": "unwritten_ssn", "field": "unwritten_ssn", "type": "text", "maxlen": 9, "comb": True},
        {"line": "text_bar_ssn", "field": "text_bar_ssn", "type": "text", "maxlen": 9, "comb": True},
        {"line": "name", "field": "name", "type": "text"},
        {"line": "plain_nine", "field": "plain_nine", "type": "text", "maxlen": 9},
    ],
})
VALUES = {"ssn": "999880507", "dependent_ssn": "999880502", "bordered_ssn": "999880503", "pale_ssn": "999880504",
          "text_bar_ssn": "999880505", "name": "Tess Taxpayer", "plain_nine": "999880506"}


def _ssn_box_blank(tmp_path: Path) -> Path:
    """The 2025 Form 1040 SSN geometry on a synthetic page, with one control box per rule the pass must respect."""
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    out = tmp_path / "ssn_boxes.pdf"
    page = canvas.Canvas(str(out), pagesize=(612, 792))

    def box(dy: float, left: float, dots: tuple[float, float], gray: float = 0.0, right: float | None = None) -> None:
        page.setStrokeColorRGB(gray, gray, gray)
        page.setDash()
        page.setLineWidth(0.5)
        page.line(left, 660 - dy, left, 712 - dy)               # the box's left rule
        if right is not None:
            page.line(right, 660 - dy, right, 712 - dy)
        page.line(left - 0.75, 684 - dy, 576.75, 684 - dy)      # its bottom rule
        page.setLineWidth(1.0)
        page.setDash([0.5, 1.0])                                # the IRS dots: one stroked segment under a dash
        for x in dots:
            page.line(x, 684 - dy, x, 694 - dy)

    def field(name: str, x0: float, x1: float, dy: float, comb: bool = True, maxlen: int | None = 9, **look) -> None:
        page.acroForm.textfield(name=name, x=x0, y=684 - dy, width=x1 - x0, height=14, maxlen=maxlen,
                                fieldFlags=_FF_COMB if comb else "", value="", fontName="Helvetica", fontSize=8,
                                textColor=Color(*NAVY), **look)

    plain = {"borderWidth": 0, "borderColor": None, "fillColor": None}   # the IRS widgets carry no /MK at all
    box(0, 468.0, (500.7, 522.4))
    field("ssn", 469.0, 576.0, 0, **plain)
    box(100, 144.0, (180.3, 204.6), right=252.0)                         # already clear: the 2025 dependents' box
    field("dependent_ssn", 145.0, 251.25, 100, **plain)
    box(200, 468.0, (500.7, 522.4))
    field("bordered_ssn", 469.0, 576.0, 200)                              # reportlab's default /MK /BC + /BG
    box(300, 468.0, (500.7, 522.4), gray=0.92)                            # a pale drop-out tint, not reader ink
    field("pale_ssn", 469.0, 576.0, 300, **plain)
    box(400, 468.0, (500.7, 522.4))
    field("unwritten_ssn", 469.0, 576.0, 400, **plain)
    box(500, 468.0, (500.7, 522.4))
    field("name", 469.0, 576.0, 500, comb=False, maxlen=None, **plain)    # crossing dots, but no comb and no /MaxLen
    box(0, 168.0, (200.7, 222.4))                                         # the SSN box again, 300 pt to the left ...
    field("plain_nine", 169.0, 276.0, 0, comb=False, **plain)             # ... under a /MaxLen 9 widget with no comb bit
    box(600, 468.0, ())
    page.setFont("Helvetica", 12)
    for x in (500.7, 522.4):                                              # separators printed as TEXT ("|"): never read
        page.drawCentredString(x, 686 - 600, "|")
    field("text_bar_ssn", 469.0, 576.0, 600, **plain)
    page.showPage()
    page.save()
    return out


def _rects(pdf: Path) -> dict[str, list[float]]:
    return {str(a.get_object()["/T"]): [float(v) for v in a.get_object()["/Rect"]]
            for page in PdfReader(str(pdf)).pages for a in page.get("/Annots", [])}


def _crop(pdf: Path, page_index: int, box: tuple[float, float, float, float], *, forms: bool):
    """Render ``box`` (x0, y0, x1, y1 in page points) of a page at 600 dpi; forms off draws the printed page only."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        if forms:
            doc.init_forms()
        page = doc[page_index]
        width, height = page.get_size()
        x0, y0, x1, y1 = box
        bitmap = page.render(scale=SCALE, crop=(x0, y0, width - x1, height - y1), draw_annots=forms,
                             may_draw_forms=forms)
        return bitmap.to_pil().convert("RGB")
    finally:
        doc.close()


def _glyphs_and_separators(blank: Path, filled: Path, page_index: int, rect: tuple[float, float, float, float],
                           band: tuple[float, float]) -> tuple[list[tuple[float, float]], list[float]]:
    """The x extents of the navy digits drawn in ``band`` (the widget's original x span, padded) and the x of every
    dark column printed inside ``rect`` on the blank (the separators), both in page points."""
    x0, y0, x1, y1 = rect
    left, right = band
    printed = _crop(blank, page_index, (left, y0, right, y1), forms=False).convert("L")
    drawn = _crop(filled, page_index, (left, y0, right, y1), forms=True)
    width, height = printed.size
    ink, paint = printed.load(), drawn.load()
    separators, run = [], []
    for col in range(width):
        x = left + (col + 0.5) / SCALE
        dark = sum(1 for row in range(height) if ink[col, row] < 128) / height
        if dark >= 0.12 and x0 + 1.2 <= x <= x1 - 1.2:
            run.append(x)
        elif run:
            separators.append(sum(run) / len(run))
            run = []

    def navy(col: int) -> bool:  # the IRS /DA ink, 0 0 0.502 rg: blue well above red and green
        return any(min(paint[col, row][2] - paint[col, row][0], paint[col, row][2] - paint[col, row][1]) > 40
                   for row in range(height))

    glyphs, start = [], None
    for col in range(width + 1):
        inked = col < width and navy(col)
        if inked and start is None:
            start = col
        elif not inked and start is not None:
            glyphs.append((left + start / SCALE, left + col / SCALE))
            start = None
    return glyphs, separators


def _assert_digits_between(glyphs: list[tuple[float, float]], separators: list[float], groups: list[int], label: str):
    assert len(glyphs) == sum(groups), f"{label}: {len(glyphs)} glyphs drawn, expected {sum(groups)}"
    assert len(separators) == len(groups) - 1, f"{label}: separators {separators}"
    crossed = [x for x in separators if any(a - 0.3 <= x <= b + 0.3 for a, b in glyphs)]
    assert not crossed, f"{label}: the separators at {crossed} cross a digit (glyphs {glyphs})"
    edges = [-1e9, *separators, 1e9]
    counts = [sum(1 for a, b in glyphs if edges[i] < a and b < edges[i + 1]) for i in range(len(groups))]
    assert counts == groups, f"{label}: digits per separator group {counts}, expected {groups}"


def test_p033_fill_narrows_a_crossing_comb_and_nothing_else(tmp_path: Path):
    blank = _ssn_box_blank(tmp_path)
    out = tmp_path / "filled.pdf"
    result = fill_form(PACK, VALUES, blank, out)
    # the render: the digits print 3 | 2 | 4 between the dots
    glyphs, separators = _glyphs_and_separators(blank, out, 0, (469.0, 684.0, 576.0, 698.0), (466.0, 579.0))
    _assert_digits_between(glyphs, separators, [3, 2, 4], "synthetic SSN box")
    # the IRS-shaped box is narrowed to the grid of its dots, from the box's left rule, at its own height
    before, after = _rects(blank), _rects(out)
    assert after["ssn"] == pytest.approx([468.0, 684.0, 565.968, 698.0], abs=0.01)
    assert result.combs_aligned == ["ssn (page 1): x 469.00-576.00 -> 468.00-565.97"]
    # the clear box, the bordered one, the pale-tint one, the unwritten one, the one whose bars are text and the two
    # non-comb ones keep their /Rect: "plain_nine" has the SSN box's geometry and /MaxLen 9, so only the comb flag
    # keeps it out (as a comb it would narrow to 168.00-265.97)
    for name in ("dependent_ssn", "bordered_ssn", "pale_ssn", "unwritten_ssn", "text_bar_ssn", "name", "plain_nine"):
        assert after[name] == before[name], name
    report = verify_form(PACK, out, expected=VALUES)  # every value still reads back from the reshaped widget
    assert {c.line: c.status for c in report.assertions} == dict.fromkeys(VALUES, "PASS")


def test_p033_a_comb_mirror_is_built_before_the_combs_are_aligned(tmp_path: Path):
    """Phase K JK28 (2026-10-23): fill_form builds the page-header mirrors before it aligns the written combs, so a
    mirror bound to a comb widget whose cells cross printed separators is narrowed like a value the caller passed."""
    pack = FormPack.model_validate({**PACK.model_dump(exclude_unset=True), "mirrors": {"unwritten_ssn": "{ssn}"}})
    blank = _ssn_box_blank(tmp_path)
    out = tmp_path / "mirrored.pdf"
    result = fill_form(pack, VALUES, blank, out)
    assert result.mirrored == ["unwritten_ssn"] and result.written["unwritten_ssn"] == "999880507"
    assert "unwritten_ssn (page 1): x 469.00-576.00 -> 468.00-565.97" in result.combs_aligned, result.combs_aligned
    assert _rects(out)["unwritten_ssn"] == pytest.approx([468.0, 284.0, 565.968, 298.0], abs=0.01)
    check = next(c for c in verify_form(pack, out).identity if c.field == "page-header mirror unwritten_ssn")
    assert check.status == "PASS", check.detail


def test_p033_fill_is_idempotent_on_its_own_output(tmp_path: Path):
    """A filled return re-used as the blank keeps the narrowed widget: its cells already clear the dots."""
    blank = _ssn_box_blank(tmp_path)
    first = fill_form(PACK, VALUES, blank, tmp_path / "first.pdf")
    second = fill_form(PACK, VALUES, tmp_path / "first.pdf", tmp_path / "second.pdf")
    assert first.combs_aligned and second.combs_aligned == []
    assert _rects(tmp_path / "second.pdf")["ssn"] == _rects(tmp_path / "first.pdf")["ssn"]


def test_p033_the_pass_never_blocks_a_fill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The pass is cosmetic: when pdfium cannot hand it a page (pypdf and pdfium read a malformed page tree apart) or
    the grid rule raises, the fill still completes and every widget keeps its /Rect."""
    import pypdfium2

    import taxfill_core.filler as filler

    blank = _ssn_box_blank(tmp_path)

    class NoPages(pypdfium2.PdfDocument):
        def __getitem__(self, index):
            raise IndexError(f"page {index} is not in pdfium's page tree")

    def broken_rule(*args, **kwargs):
        raise ZeroDivisionError("a bug in the grid rule")

    for label, target, attribute, stand_in in (("no page", pypdfium2, "PdfDocument", NoPages),
                                                ("grid raises", filler, "comb_cell_grid", broken_rule)):
        out = tmp_path / f"{attribute}.pdf"
        with monkeypatch.context() as patch:
            patch.setattr(target, attribute, stand_in)
            result = fill_form(PACK, VALUES, blank, out)
        assert result.combs_aligned == [], label
        assert _rects(out) == _rects(blank), label


def test_p033_a_rotated_widget_keeps_its_rect(tmp_path: Path):
    blank = _ssn_box_blank(tmp_path)
    writer = PdfWriter(clone_from=str(blank))
    for ref in writer.pages[0]["/Annots"]:
        annot = ref.get_object()
        if annot["/T"] == "ssn":
            annot[NameObject("/MK")] = DictionaryObject({NameObject("/R"): NumberObject(90)})
    rotated = tmp_path / "rotated.pdf"
    writer.write(rotated)
    result = fill_form(PACK, {"ssn": "999880507"}, rotated, tmp_path / "out.pdf")
    assert result.combs_aligned == []


# ---------------------------------------------------------------------------
# The real 2025 Form 1040 (network, or a warm cache)
# ---------------------------------------------------------------------------


def _blank(pack):
    from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank

    try:
        return fetch_pack_blank(pack)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cache empty and network unreachable: {exc}")


def _widgets(pdf: Path) -> dict[str, list[tuple[int, list[float], int]]]:
    from taxfill_core.filler import _inherited_attr, _qualified_name

    found: dict[str, list[tuple[int, list[float], int]]] = {}
    for index, page in enumerate(PdfReader(str(pdf)).pages):
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            if annot.get("/Subtype") == "/Widget":
                flags = int(_inherited_attr(annot, "/Ff") or 0)
                found.setdefault(_qualified_name(annot), []).append((index, [float(v) for v in annot["/Rect"]], flags))
    return found


def _printed_edges(blank: Path, page_index: int, rect: list[float]) -> tuple[float, float]:
    """The box a widget sits in, read off the blank: the dark rule within 3 pt outside (or 1.2 pt inside) each edge
    that spans at least half the widget's height, or the widget's own edge where none is printed."""
    x0, y0, x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])
    image = _crop(blank, page_index, (x0 - 3.0, y0, x1 + 3.0, y1), forms=False).convert("L")
    width, height = image.size
    ink = image.load()
    rules = [x0 - 3.0 + (col + 0.5) / SCALE for col in range(width)
             if sum(1 for row in range(height) if ink[col, row] < 128) >= 0.5 * height]
    left = [x for x in rules if x < x0 + 1.2]
    right = [x for x in rules if x > x1 - 1.2]
    return (max(left) if left else x0), (min(right) if right else x1)


@pytest.mark.network
def test_p033_2025_form_1040_ssn_digits_fall_between_the_printed_separators(tmp_path: Path):
    from taxfill_core.schemas.formpack import load_pack
    from test_formpacks_federal import _assert_section_clean, synthetic_values

    pack = load_pack(REPO_ROOT / "formpacks/federal/2025/f1040/pack.yaml")
    blank = Path(_blank(pack))
    values = synthetic_values(pack)  # every mapped line; the SSN combs get 999-88-xxxx digits
    out = tmp_path / "f1040_2025.pdf"
    result = fill_form(pack, values, blank, out)

    # 1. The render: every SSN comb on the return prints 3 | 2 | 4 digits between its two dotted separators.
    before, after = _widgets(blank), _widgets(out)
    root = pack.acroform_root
    ssn_lines = ["identifying_number", "spouse.identifying_number", "26.former_spouse_ssn",
                 "dependent_1.ssn", "dependent_2.ssn", "dependent_3.ssn", "dependent_4.ssn"]
    by_line = {pf.line: f"{root}.{pf.field}" for pf in pack.fields}
    for line in ssn_lines:
        ((page_index, rect, _),) = before[by_line[line]]
        x0, y0, x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])
        glyphs, separators = _glyphs_and_separators(blank, out, page_index, (x0, y0, x1, y1), (x0 - 3.0, x1 + 3.0))
        _assert_digits_between(glyphs, separators, [3, 2, 4], f"2025 Form 1040 {line}")

    # 2. Only the three boxes whose dots crossed a digit moved, each a comb, each inside its printed box, at its height.
    moved = sorted(entry.split(" (page")[0] for entry in result.combs_aligned)
    assert moved == sorted(by_line[line] for line in ("identifying_number", "spouse.identifying_number",
                                                      "26.former_spouse_ssn"))
    for name, placements in before.items():
        for (page_index, old, flags), (_, new, _) in zip(placements, after[name]):
            if name not in moved:
                assert new == old, f"{name}: /Rect changed from {old} to {new}"
                continue
            assert flags & _FF_COMB, f"{name} is not a comb widget"
            assert (new[1], new[3]) == (min(old[1], old[3]), max(old[1], old[3])), f"{name}: height changed"
            left, right = _printed_edges(blank, page_index, old)
            assert left - 0.5 <= new[0] < new[2] <= right + 0.5, f"{name}: {new} leaves the printed box {left}-{right}"

    # 3. verify_form reads every value back.
    report = verify_form(pack, out, expected=values)
    _assert_section_clean(report.assertions, "assertion diff")
    _assert_section_clean(report.clipping, "clipping scan")
