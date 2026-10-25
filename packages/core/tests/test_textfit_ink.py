"""P-035 / Phase K JEe (2026-10-24): text width against the widget's inner padding.

verify's width check used to pass a value whose advance filled the widget rect exactly, and the render cut its last
glyph (RI-1040 2025's dependent date of birth). The measure now has three parts, each pinned here:

* the INSET: a viewer draws a text box's value inside its border, so the room is the width less the border width on
  each side (``textfit.widget_inset``: /BS /W, else /Border, else 1 pt; beveled and inset styles count twice);
* the INK: a glyph's advance includes blank space either side of its ink, and the clip cuts only ink, so a value fits
  when its ink stays inside the room, give or take ``CUT_TOLERANCE_PT``: laid out from the left inset, ending at
  the right one, or centred, by the box's /Q (``textfit.ink_overrun``);
* the bearings themselves, re-measured here the way they were made (reportlab draws, pdfium renders).

The network layer pins the arithmetic to real renders: on the cached RI-1040 and CA 540 blanks, the values the model
says are cut lose ink in pdfium's render, and the ones it says fit do not.
"""
from __future__ import annotations

import re
import string
import sys
from pathlib import Path

import pytest
from pdf_fixtures import make_acroform_pdf

from taxfill_core.schemas.formpack import load_pack
from taxfill_core.textfit import (
    _BEARINGS,
    _RSB_COURIER,
    _RSB_HELVETICA,
    BORDER_PT,
    CUT_TOLERANCE_PT,
    WidgetBox,
    advance,
    bearings,
    fit,
    ink_extent,
    ink_overrun,
    widget_box,
    widget_inset,
)
from taxfill_core.verify import (
    FAIL,
    PASS,
    ClippingCheck,
    TextWidget,
    clipping_scan,
    qualified_field_name,
    read_text_widgets,
)

FORMPACKS = Path(__file__).resolve().parents[3] / "formpacks"


# ── the inset ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("annot", "inset"),
    [
        ({}, 1.0),                                          # no /BS, no /Border: the 1 pt the renders show
        ({"/BS": {"/W": 1, "/S": "/S"}}, 1.0),
        ({"/BS": {"/S": "/U"}}, 1.0),                       # /W defaults to 1
        ({"/BS": {"/W": 2, "/S": "/S"}}, 2.0),              # AL Form 40's address box, PA-40 19b
        ({"/BS": {"/W": 3, "/S": "/S"}}, 3.0),              # KY 740 line 5a, PA-40 line 11
        ({"/BS": {"/W": 1, "/S": "/B"}}, 2.0),              # beveled: a second band inside the border
        ({"/BS": {"/W": 1, "/S": "/I"}}, 2.0),              # inset: likewise
        ({"/Border": [0, 0, 2]}, 2.0),                      # the legacy array's third number
        ({"/BS": {"/W": 0}}, 1.0),                          # never less than the measured 1 pt
        ({"/BS": {"/W": "junk"}}, 1.0),
    ],
)
def test_widget_inset_reads_the_border(annot: dict, inset: float):
    assert widget_inset(annot) == inset


def test_room_is_the_width_less_the_inset_on_each_side():
    assert WidgetBox(80.0, 9.0, "Cour", True).room == pytest.approx(80.0 - 2 * BORDER_PT)
    assert WidgetBox(80.17, 9.0, "Cour", True, False, 3.0).room == pytest.approx(74.17)


# ── the ink ──────────────────────────────────────────────────────────────────


def test_ink_extent_is_the_advance_less_the_last_glyphs_bearing():
    assert ink_extent("1", 10.0) == pytest.approx(advance("1", 10.0) - _RSB_HELVETICA["1"] * 10.0)
    assert ink_extent("12  ", 10.0) == ink_extent("12", 10.0)  # trailing spaces carry no ink
    assert ink_extent("   ", 10.0) == 0.0 and ink_extent("", 10.0) == 0.0
    assert ink_extent("x" * 11, 12.0, courier=True) == pytest.approx(79.2 - _RSB_COURIER["x"] * 12.0)


# Boxes whose cut JEe measured on pdfium renders (the network test below re-measures the first two).
RI_DOB = WidgetBox(57.6, 12.0, "CourierNewPSMT", True)  # RI-1040 dependent date of birth
CA_APT = WidgetBox(72.5, 10.0, "Helv", False)  # CA 540 mailing "Apt. no/ste. no."
IRS_YEAR = WidgetBox(21.6, 9.0, "HelveticaLTStd-Bold", False)  # draft 2026 Form 1040 deceased-year box


def test_the_measured_boxes():
    assert fit("01012020", [RI_DOB]).fits is False  # loses 0.58 pt of its last digit on the render
    assert fit("0101202", [RI_DOB]).fits is True
    assert fit("1234567890123", [CA_APT]).fits is False  # loses 1.33 pt
    assert fit("123456789012", [CA_APT]).fits is True
    for year in ("2024", "2025", "2026", "2027"):  # at most 0.14 pt: the IRS's own box holds its 4-digit year
        assert fit(year, [IRS_YEAR]).fits is True, year
        assert fit(year, [IRS_YEAR._replace(bold=True)]).fits is True, year


def test_alignment_decides_which_side_overruns():
    """RI-1040's middle-initial box is one Courier-12 glyph wide (7.2 pt) and centred: the 2 pt its border takes splits
    1 pt a side, and the glyph's own bearings (about 0.1 em each side in Courier) absorb it — the render shows the
    initial whole. Left-aligned, the same glyph would overrun the right side by its whole excess less its bearing."""
    centred = WidgetBox(7.2, 12.0, "CourierNewPSMT", True, False, 1.0, 1, False)
    left = centred._replace(quadding=0)
    right = centred._replace(quadding=2)
    regular = {ch: bearings(ch, courier=True, bold=False) for ch in "QIMW"}
    assert fit("Q", [centred]).fits is True and fit("I", [centred]).fits is True
    assert fit("M", [centred]).fits is False and fit("W", [centred]).fits is False  # wide: about 0.9 pt each side
    for initial in "QIMW":
        assert ink_overrun(initial, left) == pytest.approx(7.2 - regular[initial][1] * 12 - 5.2)
        assert ink_overrun(initial, right) == pytest.approx(7.2 - regular[initial][0] * 12 - 5.2)
    assert fit("Q", [left]).fits is False
    # right-aligned: the overrun is on the left, so the FIRST glyph's left bearing counts, not the last one's right
    box = WidgetBox(40.0, 10.0, "Helv", False, False, 1.0, 2)
    lsb_one = bearings("1", courier=False, bold=False)[0]
    assert ink_overrun("1000000", box) == pytest.approx(advance("1000000", 10.0, bold=False) - lsb_one * 10 - 38.0)
    assert ink_overrun("   ", box) == float("-inf")


def test_a_value_that_fills_the_box_edge_to_edge_fails_verify():
    """The JEe defect: 8 Courier-12 glyphs advance exactly the 57.6 pt box and passed; the render cuts the 8th."""
    widget = TextWidget(name="dob", value="01012020", da="/CourierNewPSMT 12 Tf 0 g", rect_width=57.6, monospace=True)
    check = clipping_scan([widget])[0]
    assert check.status == FAIL
    assert "the 55.6pt inside the 57.6pt widget (less 1pt on each side" in check.detail
    assert clipping_scan([widget.model_copy(update={"value": "0101202"})])[0].status == PASS


def test_md_502_2023_spouse_signature_date_holds_seven():
    """MD 502 2023's spouse signature-date box (48.2 pt at Courier New 10, no /MaxLen): 8 glyphs fill it edge to edge
    and the render cuts the last (0.58 pt measured), so the pack budget is 7 (Phase K JEe)."""
    box = {"da": "/CourierNewPSMT 10 Tf 0 g", "rect_width": 48.24, "monospace": True}
    assert clipping_scan([TextWidget(name="d", value="04152024", **box)])[0].status == FAIL
    assert clipping_scan([TextWidget(name="d", value="4152024", **box)])[0].status == PASS
    pack = load_pack(FORMPACKS / "states/md/2023/md502/pack.yaml")
    assert next(pf for pf in pack.fields if pf.line == "spouse_signature_date").maxlen == 7


def test_a_bold_box_is_measured_in_bold_widths():
    """A bold capital is up to a fifth wider than a regular one (the digits are the same): Form W-7 2025's 60.7 pt
    box at HelveticaLTStd-Bold 8 printed 'Taylor Fitzgerald' 4.9 pt cut while regular widths said it fit."""
    bold = TextWidget(name="w7", value="Taylor Fitzgerald", da="/HelveticaLTStd-Bold 8 Tf 0 g", rect_width=60.7)
    assert clipping_scan([bold])[0].status == FAIL  # measured in regular widths it passed, and printed cut
    assert advance("Taylor Fitzgerald", 8.0, bold=True) > advance("Taylor Fitzgerald", 8.0, bold=False)
    assert advance("123456", 8.0, bold=True) == advance("123456", 8.0, bold=False)
    assert clipping_scan([bold])[0].status == FAIL and "Helvetica-Bold metrics" in clipping_scan([bold])[0].detail
    assert clipping_scan([bold.model_copy(update={"da": "/Helv 8 Tf 0 g"})])[0].status == PASS
    # an unknown weight measures each glyph at the wider of the two
    assert advance("Taylor", 8.0) == advance("Taylor", 8.0, bold=True)


@pytest.mark.parametrize(("name", "bold"), [
    ("HelveticaNeueLTStd-Bd", True),     # Adobe's "Bd" (the draft 2026 Form 1116)
    ("Helvetica-Bold", True), ("Arial-BoldMT", True), ("Arial,Bold", True), ("OpenSans-Semibold", True),
    ("HelveticaNeueLTStd-Roman", False), ("Helvetica", False), ("ArialMT", False), ("CourierNewPSMT", False),
])
def test_is_bold_reads_the_weight_in_the_base_font_name(name: str, bold: bool):
    from taxfill_core.textfit import is_bold  # noqa: PLC0415

    assert is_bold("F1", {"F1": name}) is bold          # resolved through the /DR /BaseFont
    assert is_bold(name) is bold                        # or the /DA name itself when unresolved


def test_a_thick_border_takes_its_own_width():
    """KY 740's 3 pt borders: a value inside the width less 2 pt but past the width less 6 pt is cut."""
    widget = TextWidget(name="w", value="0" * 14, da="/Cour 9 Tf 0 g", rect_width=78.0, monospace=True, inset=3.0)
    assert ink_extent("0" * 14, 9.0, courier=True, bold=False) < 78.0 - 2  # would pass a 1 pt border
    check = clipping_scan([widget])[0]
    assert check.status == FAIL and "less 3pt on each side" in check.detail
    assert clipping_scan([widget.model_copy(update={"value": "0" * 13})])[0].status == PASS


def test_a_comb_box_with_a_maxlen_is_not_width_measured():
    comb = TextWidget(name="ssn", value="123456789", da="/Helv 14 Tf 0 g", rect_width=60.0, max_len=9, comb=True)
    assert clipping_scan([comb])[0].status == PASS
    # without a /MaxLen the comb flag means nothing to a viewer, so the width counts
    assert clipping_scan([comb.model_copy(update={"max_len": None})])[0].status == FAIL


def test_a_centred_box_measures_both_sides_in_verify():
    initial = TextWidget(name="mi", value="Q", da="/CourierNewPSMT 12 Tf 0 g", rect_width=7.2, monospace=True,
                         quadding=1)
    assert clipping_scan([initial])[0].status == PASS
    check = clipping_scan([initial.model_copy(update={"quadding": 0})])[0]
    assert check.status == FAIL and "overruns by" in check.detail and "on the right" in check.detail


def test_read_text_widgets_reads_the_border_and_the_comb_flag(tmp_path):
    from pypdf import PdfReader, PdfWriter  # noqa: PLC0415
    from pypdf.generic import DictionaryObject, FloatObject, NameObject, NumberObject  # noqa: PLC0415

    src = make_acroform_pdf(tmp_path / "blank.pdf", [
        {"name": "thick", "width": 80.0, "height": 18.0},
        {"name": "ssn", "width": 90.0, "height": 18.0, "maxlen": 9, "comb": True},
    ])
    writer = PdfWriter(clone_from=PdfReader(str(src)))
    for ref in writer.pages[0]["/Annots"]:
        annot = ref.get_object()
        if annot.get("/T") == "thick":
            annot[NameObject("/BS")] = DictionaryObject({NameObject("/W"): FloatObject(3), NameObject("/S"): NameObject("/S")})
            annot[NameObject("/Q")] = NumberObject(1)
    out = tmp_path / "bordered.pdf"
    writer.write(str(out))
    widgets = {w.name: w for w in read_text_widgets(out)}
    assert widgets["thick"].inset == 3.0 and not widgets["thick"].comb and widgets["thick"].quadding == 1
    assert widgets["ssn"].inset == 1.0 and widgets["ssn"].comb and widgets["ssn"].max_len == 9


# ── the bearings, re-measured ────────────────────────────────────────────────


def test_the_bearing_tables_match_a_fresh_measurement(tmp_path):
    """Draw every tabled glyph at 200 pt with reportlab (no embedding: pdfium substitutes a base-14 face, as for a
    form's /DA font), render at 2 px/pt, and take the blank space either side of its ink. The substitutes differ by
    platform (macOS draws the system's Helvetica and Courier, CI's Linux runner others), so the tables keep the
    thinner of the two, and on any platform no glyph may show less blank space than the table credits."""
    import pypdfium2 as pdfium  # noqa: PLC0415
    from reportlab.pdfbase.pdfmetrics import stringWidth  # noqa: PLC0415
    from reportlab.pdfgen import canvas  # noqa: PLC0415

    size, scale = 200.0, 2.0

    def bearings(face: str, glyphs: str) -> dict[str, tuple[float, float]]:
        pdf = tmp_path / f"{face}.pdf"
        c = canvas.Canvas(str(pdf), pagesize=(400, 400))
        for ch in glyphs:
            c.setFont(face, size)
            c.drawString(50, 100, ch)
            c.showPage()
        c.save()
        doc = pdfium.PdfDocument(str(pdf))
        try:
            out = {}
            for i, ch in enumerate(glyphs):
                bitmap = doc[i].render(scale=scale, grayscale=True).to_pil().point(lambda v: 255 if v < 128 else 0)
                box = bitmap.getbbox()
                out[ch] = ((box[0] / scale - 50) / size, (50 + stringWidth(ch, face, size) - box[2] / scale) / size)
            return out
        finally:
            doc.close()

    glyphs_of = {"Helvetica": "".join(_RSB_HELVETICA), "Courier": "".join(_RSB_COURIER)}
    measured = {face: bearings(face, glyphs_of[face.split("-")[0]])
                for face in ("Helvetica", "Helvetica-Bold", "Courier", "Courier-Bold")}
    # One-sided on every platform: the tables keep the thinner of the macOS and Linux measurements, so no renderer
    # may draw a glyph with LESS blank space than the table credits (pdfium substitutes different faces per
    # platform; a renderer with more blank space only makes the measure conservative there).
    over = {face: {ch: (table[ch], [round(v, 3) for v in measured[face][ch]])
                   for ch in table if any(t > m + 0.006 for t, m in zip(table[ch], measured[face][ch]))}
            for face, table in _BEARINGS.items()}
    over = {face: v for face, v in over.items() if v}
    assert not over, f"on {sys.platform} these glyphs have less blank space than the table credits: {over}"
    assert set(string.digits + string.ascii_uppercase) <= set(_RSB_HELVETICA) <= set(_RSB_COURIER)


def test_the_tolerance_stays_under_the_thinnest_flagged_cut():
    """0.58 pt (RI's date of birth) is the thinnest cut a reviewer has flagged on a render, and the arithmetic gives it
    0.64 pt: the tolerance stays under both, and above the 0.14 pt the IRS's own year boxes lose and the 0.26 pt a bold
    Courier capital's ink starts left of its origin."""
    assert 0.26 < CUT_TOLERANCE_PT < 0.58
    assert ink_overrun("01012020", RI_DOB._replace(bold=False)) > CUT_TOLERANCE_PT


# ── RI-1040's edge-to-edge boxes: a smaller font (Phase K JEe2) ─────────────


RI_PACKS = sorted(FORMPACKS.glob("states/ri/*/ri1040/pack.yaml"))
# Phase K JEe2 (2026-10-25): the user chose a smaller font for the four kinds of box RI-1040 sizes for its Courier New
# 12 glyphs edge to edge. kind -> (its lines, the box width pt and /Q, the widest values it takes, the pack font_size,
# a value too long for it). Each size is the largest on a 0.1 pt grid at which every widest value's ink stays inside
# the box (overrun <= 0, not merely the tolerance); the measurements are in the packs' comment.
RI_FONT_SIZES = {
    "date of birth": (r"schedule_e\.dependent_\d+\.dob", 57.6, 0,
                      [f"1231202{d}" for d in string.digits], 11.7, "12/31/2026"),
    "middle initial": (r"(?:spouse\.)?name\.middle_initial", 7.2, 1, list(string.ascii_uppercase), 8.5, "VW"),
    "suffix": (r"(?:spouse\.)?name\.suffix", 21.6, 0, ["III", "JR", "SR", "IV", "II"], 11.4, "VIII"),
    "signature date": (r"signature\.(?:taxpayer|spouse)\.date|preparer\.date", 72.0, 0,
                       [f"12/31/202{d}" for d in string.digits], 11.8, "Dec 31, 2026"),
}


# Phase K JEe2 (2026-10-25), verifier finding: values a box takes beyond its widest generational value, whose ink the
# pack size does NOT keep inside the box, kind -> [(value, side)]. They pass verify inside CUT_TOLERANCE_PT, the same
# tolerance as every other box, and the pack comment says so: ESQ ends past the suffix box's right inset, and V, VI and
# VII start just left of its left inset, at every size (so no smaller size would bring them in).
RI_WITHIN_TOLERANCE = {"suffix": [("ESQ", "right"), ("V", "left"), ("VI", "left"), ("VII", "left")]}


def _ri_box(kind: str, size: float) -> TextWidget:
    _pattern, width, quadding, *_ = RI_FONT_SIZES[kind]
    return TextWidget(name=kind, value="", da=f"/CourierNewPSMT {size:g} Tf 0 g", rect_width=width, monospace=True,
                      quadding=quadding)


# Measured font_size lines outside RI-1040: (pack, line) -> size. Phase K JEe3 (2026-10-25): MD 502 2023's 14.29 pt
# state-of-residence box in MinionPro-Regular 8 (/Widths) cannot hold WV, WY, WA, MO, MN, NM or MD at 8 pt.
OTHER_FONT_SIZES = {("states/md/2023/md502/pack.yaml", "other_state_of_residence"): 7.3}
STATE_CODES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
               "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()


def test_font_size_is_set_only_on_the_measured_ri_boxes():
    """Every pack line carrying a font_size is one of RI-1040's measured edge-to-edge boxes, at its measured size: 13
    dates of birth, two middle initials, two suffixes and three signature or preparer dates in each year (and the
    measured boxes of OTHER_FONT_SIZES)."""
    found = {(str(path.relative_to(FORMPACKS)), pf.line, pf.font_size)
             for path in sorted(FORMPACKS.glob("**/pack.yaml")) for pf in load_pack(path).fields if pf.font_size}
    expected = {(pack, line, size) for (pack, line), size in OTHER_FONT_SIZES.items()}
    for path in RI_PACKS:
        for pf in load_pack(path).fields:
            for pattern, _w, _q, _values, size, _long in RI_FONT_SIZES.values():
                if re.fullmatch(pattern, pf.line):
                    expected.add((str(path.relative_to(FORMPACKS)), pf.line, size))
    assert len(RI_PACKS) == 3 and len(expected) == 3 * 20 + len(OTHER_FONT_SIZES), sorted(expected)
    assert found == expected, (
        f"unmeasured font_size lines {sorted(found - expected)}, measured boxes without it {sorted(expected - found)}: "
        "a font_size is the LARGEST size at which the box's widest value prints whole (formpacks/CONVENTIONS.md); "
        "measure it and add the box here")


@pytest.mark.parametrize("kind", sorted(RI_FONT_SIZES))
def test_each_ri_box_prints_its_widest_value_whole_at_its_font_size(kind: str):
    """At the pack size every widest value's ink stays inside the box and verify PASSes it; 0.1 pt larger the widest
    one's ink overruns (the size is the largest on the grid); at the blank's own 12 pt verify FAILs it, which is
    why the size changed; and a value too long for the box still FAILs at the pack size."""
    _pattern, _width, _q, values, size, too_long = RI_FONT_SIZES[kind]
    box = _ri_box(kind, size)
    as_box = WidgetBox(box.rect_width, size, "CourierNewPSMT", True, False, 1.0, box.quadding, False)
    assert max(ink_overrun(v, as_box) for v in values) <= 0, kind
    assert {c.status for c in clipping_scan([box.model_copy(update={"value": v}) for v in values])} == {PASS}
    assert max(ink_overrun(v, as_box._replace(size=round(size + 0.1, 1))) for v in values) > 0, kind
    at_twelve = clipping_scan([_ri_box(kind, 12.0).model_copy(update={"value": v}) for v in values])
    assert FAIL in {c.status for c in at_twelve}, kind
    assert clipping_scan([box.model_copy(update={"value": too_long})])[0].status == FAIL, (kind, too_long)


@pytest.mark.parametrize("kind", sorted(RI_WITHIN_TOLERANCE))
def test_the_values_past_an_ri_box_at_its_font_size_pass_only_within_the_tolerance(kind: str):
    """Each listed value's ink crosses the box's inset at the pack size by more than 0 and less than CUT_TOLERANCE_PT,
    so verify PASSes it as it would on any box; at the blank's 12 pt ESQ was a FAIL. The left-side ones start with V,
    whose ink begins left of its origin (a negative left bearing)."""
    _pattern, width, quadding, _values, size, _long = RI_FONT_SIZES[kind]
    as_box = WidgetBox(width, size, "CourierNewPSMT", True, False, 1.0, quadding, False)
    for value, side in RI_WITHIN_TOLERANCE[kind]:
        assert 0 < ink_overrun(value, as_box) < CUT_TOLERANCE_PT, (value, ink_overrun(value, as_box))
        assert (bearings(value[0], courier=True)[0] < 0) == (side == "left"), value
        assert clipping_scan([_ri_box(kind, size).model_copy(update={"value": value})])[0].status == PASS, value
    assert clipping_scan([_ri_box(kind, 12.0).model_copy(update={"value": "ESQ"})])[0].status == FAIL


def _widest(kind: str) -> str:
    _pattern, width, quadding, values, size, _long = RI_FONT_SIZES[kind]
    box = WidgetBox(width, size, "CourierNewPSMT", True, False, 1.0, quadding, False)
    return max(values, key=lambda v: ink_overrun(v, box))


@pytest.mark.network
@pytest.mark.parametrize("path", RI_PACKS, ids=lambda p: p.parent.parent.name)
def test_a_real_ri_fill_writes_each_box_at_its_font_size_and_verify_passes_it(path: Path, tmp_path):
    """Fill every one of the 20 boxes with its widest value: each widget's /DA is written at the pack size, and every
    verify path (from disk, the caller's widget records, verify_filing) PASSes each box's width; a value too long for
    a box at its size (a slashed date of birth, a spelled-out signature date) still FAILs on every path."""
    from taxfill_core.fetch import fetch_pack_blank  # noqa: PLC0415
    from taxfill_core.filler import fill_form  # noqa: PLC0415
    from taxfill_core.verify import FilingItem, verify_filing, verify_form  # noqa: PLC0415

    pack = load_pack(path)
    kind_of = {pf.line: kind for pf in pack.fields for kind, row in RI_FONT_SIZES.items() if re.fullmatch(row[0], pf.line)}
    names = {qualified_field_name(pack, pf): kind_of[pf.line] for pf in pack.fields if pf.line in kind_of}
    blank = fetch_pack_blank(pack)

    def width_checks(values: dict[str, str]) -> list[list[ClippingCheck]]:
        out = tmp_path / f"ri-{len(values)}.pdf"
        fill_form(pack, values, blank, out)
        sizes = {w.name: w.da for w in read_text_widgets(out) if w.name in names and w.value}
        assert sizes == {n: f"/CourierNewPSMT {RI_FONT_SIZES[names[n]][4]:g} Tf 0 g" for n in sizes}, sizes
        reports = [verify_form(pack, out), verify_form(pack, out, widgets=read_text_widgets(out)),
                   verify_filing([FilingItem(form_key="ri", pack=pack, pdf_path=out)])]
        # the width checks only: a 2025 date of birth also gets the pack-maxlen check
        return [[c for c in r.clipping if any(c.name.endswith(n) for n in sizes) and "pt inside the" in c.detail]
                for r in reports]

    for checks in width_checks({line: _widest(kind) for line, kind in kind_of.items()}):
        assert len(checks) == 20 and {c.status for c in checks} == {PASS}, [c.detail for c in checks if c.status != PASS]
    dob = "schedule_e.dependent_1.dob"
    long_date = {"signature.taxpayer.date": "Dec 31, 2026"}
    if next(pf for pf in pack.fields if pf.line == dob).maxlen is None:  # 2023 and 2024 budget no date of birth
        long_date[dob] = "12/31/2026"
    for checks in width_checks(long_date):
        assert len(checks) == len(long_date) and {c.status for c in checks} == {FAIL}, [c.detail for c in checks]


@pytest.mark.network
@pytest.mark.parametrize("path", RI_PACKS, ids=lambda p: p.parent.parent.name)
@pytest.mark.parametrize(("kind", "line"), [("date of birth", "schedule_e.dependent_13.dob"),
                                            ("middle initial", "spouse.name.middle_initial"),
                                            ("suffix", "name.suffix"), ("signature date", "preparer.date")])
def test_the_render_draws_each_ri_box_whole_at_its_font_size(path: Path, kind: str, line: str, tmp_path):
    """pdfium's render agrees: the widest value, filled at the pack size, loses no ink to its box."""
    cut = _cut_pt(path, line, _widest(kind), tmp_path)
    assert cut < 0.1, f"{path.parent.parent.name} {line}: {_widest(kind)!r} lost {cut:.2f} pt at the pack font_size"


@pytest.mark.network
@pytest.mark.parametrize("path", RI_PACKS, ids=lambda p: p.parent.parent.name)
@pytest.mark.parametrize(("value", "side"), RI_WITHIN_TOLERANCE["suffix"])
def test_the_render_cuts_a_value_past_the_suffix_box_by_less_than_the_tolerance(path: Path, value: str, side: str,
                                                                                 tmp_path):
    """pdfium's render of the within-tolerance suffixes at the pack size: ESQ loses under CUT_TOLERANCE_PT of ink on
    the right, and V, VI and VII, which start left of the model's inset, render whole."""
    cut = _cut_pt(path, "name.suffix", value, tmp_path)
    limit = CUT_TOLERANCE_PT if side == "right" else 0.1
    assert cut < limit, f"{path.parent.parent.name} name.suffix: {value!r} lost {cut:.2f} pt at the pack font_size"


# ── the render ───────────────────────────────────────────────────────────────


def _cut_pt(pack_path: Path, line: str, value: str, work: Path) -> float:
    """Fill ``value`` with the real filler into the real box and into the same box widened 40 pt on the side(s) its
    /Q lets the text grow (right for left-aligned, left for right-aligned, both for centred), render both with pdfium's
    form layer, and return the larger amount of ink the real box cut off on either side (0 when nothing is cut). The
    probe lifts the pack's maxlen so an over-long value can be written at all."""
    import pypdfium2 as pdfium  # noqa: PLC0415
    from PIL import ImageChops  # noqa: PLC0415
    from pypdf import PdfReader, PdfWriter  # noqa: PLC0415
    from pypdf.generic import ArrayObject, FloatObject, NameObject  # noqa: PLC0415

    from taxfill_core.fetch import fetch_pack_blank  # noqa: PLC0415
    from taxfill_core.filler import fill_form  # noqa: PLC0415

    pack = load_pack(pack_path)
    blank = fetch_pack_blank(pack)
    pf = next(f for f in pack.fields if f.line == line)
    probe = pack.model_copy(update={"fields": [
        f.model_copy(update={"maxlen": None, "format": None}) if f.line == line else f for f in pack.fields]})
    name = qualified_field_name(pack, pf)
    quadding = next(w.quadding for w in read_text_widgets(blank) if w.name == name)
    grow_left, grow_right = {0: (0, 40), 1: (40, 40), 2: (40, 0)}[quadding]
    writer = PdfWriter(clone_from=PdfReader(str(blank)))
    page_no, rect = None, None
    for number, page in enumerate(writer.pages, 1):
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            parts, node = [], annot
            while node is not None:
                if "/T" in node:
                    parts.append(str(node["/T"]))
                node = node["/Parent"].get_object() if "/Parent" in node else None
            if ".".join(reversed(parts)) == name:
                rect = [float(v) for v in annot["/Rect"]]
                page_no = number
                annot[NameObject("/Rect")] = ArrayObject([FloatObject(rect[0] - grow_left), FloatObject(rect[1]),
                                                          FloatObject(rect[2] + grow_right), FloatObject(rect[3])])
                break
        if rect:
            break
    assert rect is not None, f"{name} not on the blank"
    wide_blank = work / "wide_blank.pdf"
    writer.write(str(wide_blank))
    real, wide = work / "real.pdf", work / "wide.pdf"
    entry = int(value) if pf.type == "money" else value  # a money line takes a number; it renders the same digits
    fill_form(probe, {line: entry}, blank, real)
    fill_form(probe, {line: entry}, wide_blank, wide)
    left_edge, right_edge = rect[0] - grow_left - 2, rect[2] + grow_right + 2

    def ink(filled: Path, empty: Path) -> tuple[float, float]:
        images = []
        for pdf in (filled, empty):
            doc = pdfium.PdfDocument(str(pdf))
            try:
                doc.init_forms()
                page = doc[page_no - 1]
                width, height = page.get_size()
                crop = (left_edge, rect[1], width - right_edge, height - rect[3])
                images.append(page.render(scale=12, crop=crop, may_draw_forms=True, grayscale=True).to_pil())
            finally:
                doc.close()
        box = ImageChops.difference(*images).point(lambda v: 255 if v > 60 else 0).getbbox()
        assert box is not None, f"{value!r} drew no ink in {name}"
        return left_edge + box[0] / 12, left_edge + box[2] / 12

    (real_l, real_r), (wide_l, wide_r) = ink(real, blank), ink(wide, wide_blank)
    return max(0.0, real_l - wide_l, wide_r - real_r)


@pytest.mark.network
@pytest.mark.parametrize(
    ("pack", "line", "value", "cut"),
    [
        # at the pack's font_size (11.7 pt, Phase K JEe2): 8 digits whole, a ninth far past the box
        ("states/ri/2025/ri1040/pack.yaml", "schedule_e.dependent_1.dob", "123120261", True),
        ("states/ri/2025/ri1040/pack.yaml", "schedule_e.dependent_1.dob", "12312026", False),
        ("states/ca/2025/form540/pack.yaml", "mailing_address.apt_no", "1234567890123", True),
        ("states/ca/2025/form540/pack.yaml", "mailing_address.apt_no", "123456789012", False),
        # a face measured by its /Widths (Phase K JEe3): ND-1's Verdana 8 cuts a 10-character date Helvetica's
        # widths passed, and IA 1040's narrower Calibri 10 prints the 15-digit budget Helvetica's widths said it cut
        ("states/nd/2023/nd1/pack.yaml", "signature.taxpayer_date", "01/10/2024", True),
        ("states/nd/2023/nd1/pack.yaml", "signature.taxpayer_date", "01/10/24", False),
        ("states/ia/2025/ia1040/pack.yaml", "36a", "999999999999999", False),
        # right-aligned (/Q 2): the overrun is on the LEFT, so it is the first glyph that is cut
        ("federal/2025/f1040/pack.yaml", "1a", "4000000000000001", True),
        ("federal/2025/f1040/pack.yaml", "1a", "85000", False),
        # centred (/Q 1): the overflow splits both sides and the glyphs' bearings absorb it (KY 740's ZIP+4)
        ("states/ky/2025/form740/pack.yaml", "mailing_address.zip", "40601-1234", False),
        # a bold face is measured in bold widths: Form W-7's HelveticaLTStd-Bold 8 box
        ("federal/2025/fw7/pack.yaml", "reason_de.us_person_name", "Taylor Fitzgerald", True),
        ("federal/2025/fw7/pack.yaml", "reason_de.us_person_name", "Pat Lee", False),
    ],
)
def test_the_render_cuts_what_the_model_says_and_nothing_else(pack: str, line: str, value: str, cut: bool, tmp_path):
    from taxfill_core.fetch import fetch_pack_blank  # noqa: PLC0415

    loaded = load_pack(FORMPACKS / pack)
    pf = next(pf for pf in loaded.fields if pf.line == line)
    name = qualified_field_name(loaded, pf)
    widget = next(w for w in read_text_widgets(fetch_pack_blank(loaded)) if w.name == name)
    if pf.font_size is not None:  # the fill writes the box at the pack's size (Phase K JEe2), so the model reads it
        widget = widget.model_copy(update={"da": re.sub(r"[\d.]+ Tf", f"{pf.font_size:g} Tf", widget.da)})
    verdict = clipping_scan([widget.model_copy(update={"value": value})])[0].status
    assert verdict == (FAIL if cut else PASS), f"{value!r}: the model says {verdict}"
    measured = _cut_pt(FORMPACKS / pack, line, value, tmp_path)
    if cut:
        assert measured > 0.3, f"{value!r}: the model says cut, the render lost only {measured:.2f} pt"
    else:
        assert measured < 0.1, f"{value!r}: the model says whole, the render lost {measured:.2f} pt"


# ── a face measured by its own /Widths (Phase K JEe3, 2026-10-25) ───────────
#
# A /DA font other than Helvetica, Arial, Courier or Times whose AcroForm /DR font carries /Widths (ND-1's Verdana,
# IA 1040's Calibri) is laid out by those widths in every viewer, whatever face it substitutes for the glyphs, so the
# advance is the /Widths sum and the ink is counted to the full advance (no bearing table for such a face). The
# synthetic face below gives every glyph 900/1000 em: "123456" at 10 pt advances 54.0 pt by it and 33.4 pt by
# Helvetica's AFM widths, in a 40 pt box whose room is 38 pt.

WIDE_EM = 900


def _wide_font(base: str = "DemoWide", *, first: int = 32, widths: list[float] | None = None,
               missing: float | None = None, encoding: object = "/WinAnsiEncoding", subtype: str = "/TrueType"):
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject  # noqa: PLC0415

    widths = widths if widths is not None else [WIDE_EM] * (127 - first)
    descriptor = DictionaryObject({NameObject("/Type"): NameObject("/FontDescriptor"),
                                   NameObject("/FontName"): NameObject(f"/{base}"), NameObject("/Flags"): NumberObject(32)})
    if missing is not None:
        descriptor[NameObject("/MissingWidth")] = FloatObject(missing)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject(subtype),
        NameObject("/BaseFont"): NameObject(f"/{base}"), NameObject("/FirstChar"): NumberObject(first),
        NameObject("/LastChar"): NumberObject(first + len(widths) - 1),
        NameObject("/Widths"): ArrayObject(FloatObject(w) for w in widths), NameObject("/FontDescriptor"): descriptor,
    })
    if encoding is not None:
        font[NameObject("/Encoding")] = encoding if not isinstance(encoding, str) else NameObject(encoding)
    return font


def _with_dr_font(pdf: Path, out: Path, font_name: str, font, das: dict[str, str]) -> Path:
    """``pdf`` with ``font`` added to its AcroForm /DR as ``font_name`` and the widgets ``das`` names set to their /DA."""
    from pypdf import PdfReader, PdfWriter  # noqa: PLC0415
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject  # noqa: PLC0415

    writer = PdfWriter(clone_from=PdfReader(str(pdf)))
    acroform = writer._root_object["/AcroForm"].get_object()
    if "/DR" not in acroform:
        acroform[NameObject("/DR")] = DictionaryObject({NameObject("/Font"): DictionaryObject()})
    fonts = acroform["/DR"].get_object()["/Font"].get_object()
    fonts[NameObject(f"/{font_name}")] = writer._add_object(font)
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            if annot.get("/T") in das:
                annot[NameObject("/DA")] = TextStringObject(das[annot["/T"]])
    writer.write(str(out))
    return out


def _wide_form(tmp_path: Path, font_name: str = "DemoWide", base: str = "DemoWide", value: str = "123456") -> Path:
    blank = make_acroform_pdf(tmp_path / "plain.pdf", [{"name": "amount", "width": 40.0, "height": 18.0, "value": value}])
    return _with_dr_font(blank, tmp_path / f"{base}.pdf", font_name, _wide_font(base),
                         {"amount": f"/{font_name} 10 Tf 0 g"})


def test_jee3_read_text_widgets_reads_the_dr_fonts_widths(tmp_path):
    widget = next(w for w in read_text_widgets(_wide_form(tmp_path)) if w.name == "amount")
    assert widget.font_widths is not None and widget.font_widths.name == "DemoWide"
    assert widget.font_widths.em("0") == pytest.approx(0.9)
    assert advance("123456", 10.0, widths=widget.font_widths) == pytest.approx(54.0)
    assert advance("123456", 10.0) == pytest.approx(33.36)  # Helvetica's AFM digits, 0.556 em
    assert bearings("6", widths=widget.font_widths) == (0.0, 0.0)  # no bearing table: ink to the full advance


def test_jee3_a_value_that_fits_helveticas_widths_fails_by_the_faces_own(tmp_path):
    """The JEe open item: Verdana's digits were measured as Helvetica's, so a value too wide for the box passed."""
    check = clipping_scan(_wide_form(tmp_path))[0]
    assert check.status == FAIL, check.detail
    assert "estimated text width 54.0pt (6 characters at 10pt, DemoWide's /Widths; its ink overruns by 16.0pt" in (
        check.detail)
    assert clipping_scan(_wide_form(tmp_path / "short", value="1234"))[0].status == PASS  # 36.0 pt in the 38 pt room


def test_jee3_the_fill_and_the_mirror_check_measure_by_the_widths(tmp_path):
    """fill_form's page-header mirror measure (filler._mirror_boxes) and verify's mirror check read the same widths."""
    from pypdf import PdfReader, PdfWriter  # noqa: PLC0415

    from taxfill_core.filler import _mirror_boxes  # noqa: PLC0415

    form = _wide_form(tmp_path)
    boxes = _mirror_boxes(PdfWriter(clone_from=PdfReader(str(form))), {"amount"})["amount"]
    assert boxes[0].widths is not None and boxes[0].widths.em("1") == pytest.approx(0.9)
    assert fit("123456", boxes).fits is False and fit("1234", boxes).fits is True
    widget = next(w for w in read_text_widgets(form) if w.name == "amount")
    from taxfill_core.textfit import widget_box  # noqa: PLC0415

    assert widget_box(widget.rect_width, widget.da, widths=widget.font_widths) == boxes[0]


def test_jee3_verify_fails_a_mirror_header_the_faces_widths_cut(tmp_path):
    from test_page_header_mirrors import PERSON, _pack, _qualified  # noqa: PLC0415

    from taxfill_core.textfit import font_widths  # noqa: PLC0415
    from taxfill_core.verify import mirror_checks  # noqa: PLC0415

    pack = _pack()
    fields = {_qualified(pack, line): value for line, value in PERSON.items()}
    fields[_qualified(pack, "page2.name")] = "Pat Q Example"  # 80.7 pt in Helvetica 12, 140.4 pt at 0.9 em
    widget = TextWidget(name=_qualified(pack, "page2.name"), value="Pat Q Example", da="/DemoWide 12 Tf 0 g",
                        rect_width=120.0, rect_height=18)
    helvetica = next(c for c in mirror_checks(pack, fields, widgets=[widget]) if c.field.endswith("page2.name"))
    assert helvetica.status == PASS, helvetica.detail
    wide = widget.model_copy(update={"font_widths": font_widths(_wide_font())})
    check = next(c for c in mirror_checks(pack, fields, widgets=[wide]) if c.field.endswith("page2.name"))
    assert check.status == FAIL and "its box cuts off" in check.detail, check.detail


@pytest.mark.parametrize("base", ["Helvetica", "ArialMT", "Arial,Bold", "HelveticaLTStd-Bold", "CourierNewPSMT",
                                  "Courier", "TimesNewRomanPSMT", "Times-Roman"])
def test_jee3_the_tabled_faces_keep_their_measure_whatever_widths_they_carry(base: str, tmp_path):
    """Helvetica, Arial, Courier and Times stay measured as before JEe3, byte for byte, even with a /Widths array."""
    from taxfill_core.textfit import font_widths  # noqa: PLC0415

    assert font_widths(_wide_font(base)) is None
    form = _wide_form(tmp_path, font_name="F1", base=base)
    widget = next(w for w in read_text_widgets(form) if w.name == "amount")
    assert widget.font_widths is None
    used = "36.0" if "Courier" in base else "33.4"  # Courier 0.6 em a glyph; Helvetica's digits in either weight
    assert clipping_scan([widget])[0].detail == (
        f"field 'amount': fits — estimated {used}pt within the 38.0pt inside the 40.0pt widget (less 1pt on each side, "
        "where the viewer draws the border)")


def test_jee3_helvetica_and_courier_verdicts_are_unchanged():
    """The pre-JEe3 verdicts and words, captured from main 13ccf78, for boxes that name no /Widths face."""
    widgets = [TextWidget(name="h2", value="1234567", da="/Helv 10 Tf 0 g", rect_width=40.0),
               TextWidget(name="b", value="Taylor", da="/HeBo 9 Tf 0 g", rect_width=30.0, quadding=2),
               TextWidget(name="v", value="123456", da="/Verdana 10 Tf 0 g", rect_width=40.0)]  # no /DR: Helvetica
    assert [(c.status, c.detail) for c in clipping_scan(widgets)] == [
        (FAIL, "field 'h2': estimated text width 38.9pt (7 characters at 10pt, Helvetica metrics; its ink overruns by "
               "0.6pt on the right) exceeds the 38.0pt inside the 40.0pt widget (less 1pt on each side, where the viewer "
               "draws the border) — text may be visually clipped (pitfall P-001); shorten this field's value or switch "
               "the field to auto-size, then re-render to confirm"),
        (PASS, "field 'b': fits — estimated 27.0pt within the 28.0pt inside the 30.0pt widget (less 1pt on each side, "
               "where the viewer draws the border)"),
        (PASS, "field 'v': fits — estimated 33.4pt within the 38.0pt inside the 40.0pt widget (less 1pt on each side, "
               "where the viewer draws the border)"),
    ]
    from taxfill_core.textfit import widget_box  # noqa: PLC0415

    assert tuple(fit("1234567", [widget_box(40.0, "/Helv 10 Tf 0 g")])) == (
        False, "38.9 pt at Helv 10, wider than the 38.0 pt inside its box: 40.0 pt wide, less 1 pt on each side")
    assert tuple(fit("ABCDEFG", [widget_box(40.0, "/Cour 10 Tf 0 g")])) == (
        False, "42.0 pt at Cour 10, wider than the 38.0 pt inside its box: 40.0 pt wide, less 1 pt on each side")


def test_jee3_a_glyph_outside_the_widths_takes_missing_width_else_helveticas():
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject  # noqa: PLC0415

    from taxfill_core.textfit import font_widths  # noqa: PLC0415

    digits_only = font_widths(_wide_font(first=48, widths=[WIDE_EM] * 10, missing=700))  # '0'..'9' only
    assert advance("12A", 10.0, widths=digits_only) == pytest.approx(9.0 + 9.0 + 7.0)
    no_missing = font_widths(_wide_font(first=48, widths=[WIDE_EM] * 10))
    assert advance("12A", 10.0, widths=no_missing) == pytest.approx(18.0 + advance("A", 10.0))
    zero = font_widths(_wide_font(first=48, widths=[0] * 10, missing=500))  # a 0 width is no width
    assert advance("1", 10.0, widths=zero) == pytest.approx(5.0)
    # IA 1040's Calibri: MacRoman with /Differences; a code /Differences renames reads the new glyph
    mac = DictionaryObject({NameObject("/Type"): NameObject("/Encoding"),
                            NameObject("/BaseEncoding"): NameObject("/MacRomanEncoding"),
                            NameObject("/Differences"): ArrayObject([NumberObject(65), NameObject("/Euro")])})
    widths = [WIDE_EM] * 95
    widths[65 - 32] = 450  # code 65 is now the Euro sign
    calibri = font_widths(_wide_font("Calibri", widths=widths, encoding=mac))
    assert calibri.em("€") == pytest.approx(0.45) and calibri.em("B") == pytest.approx(0.9)
    assert font_widths(_wide_font(subtype="/Type0")) is None and font_widths(_wide_font(subtype="/Type3")) is None


# ND-1 2023's page-2 signature-date boxes: centred, /Verdana 8 Tf, 43.6 pt (taxpayer, spouse) and 45.4 pt (preparer),
# no /MaxLen. Verdana's /Widths give a digit 636 and a slash 454, so MM/DD/YYYY advances 47.97 pt and its ink is cut
# (pdfium: 2.75 pt on the 43.6 pt box, 1.75 pt on the 45.4 pt one; the model: 3.18 and 2.28), where Helvetica's widths
# said 40.03 pt and passed it. MM/DD/YY (37.79 pt) prints whole, so the 2023 and 2024 packs budget 8, as 2025's did.
ND_DATE_LINES = ("signature.taxpayer_date", "signature.spouse_date", "preparer.date")


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_jee3_nd1_signature_dates_budget_mm_dd_yy(year: int):
    pack = load_pack(FORMPACKS / f"states/nd/{year}/nd1/pack.yaml")
    assert {pf.line: pf.maxlen for pf in pack.fields if pf.line in ND_DATE_LINES} == dict.fromkeys(ND_DATE_LINES, 8)


@pytest.mark.network
@pytest.mark.parametrize("year", [2023, 2024])
def test_jee3_nd1_measures_its_verdana_boxes_by_their_widths(year: int):
    from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank  # noqa: PLC0415

    pack = load_pack(FORMPACKS / f"states/nd/{year}/nd1/pack.yaml")
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    widgets = {w.name: w for w in read_text_widgets(blank)}
    for line in ND_DATE_LINES:
        widget = widgets[qualified_field_name(pack, next(pf for pf in pack.fields if pf.line == line))]
        assert widget.font_widths is not None and widget.font_widths.name == "Verdana", widget.da
        assert (widget.font_widths.em("0"), widget.font_widths.em("/")) == (0.636, 0.454)
        widest = "00/00/00"  # the budget-length value: every Verdana digit is 636
        assert advance(widest, 8.0, widths=widget.font_widths) == pytest.approx(37.792)
        assert clipping_scan([widget.model_copy(update={"value": widest})])[0].status == PASS
        full = clipping_scan([widget.model_copy(update={"value": "01/10/2024"})])[0]
        assert full.status == FAIL and "estimated text width 48.0pt" in full.detail, full.detail


@pytest.mark.network
def test_md502_2023_state_box_holds_every_state_code_at_its_font_size():
    """Phase K JEe3 (2026-10-25): measured by MinionPro's /Widths, MD 502 2023's state-of-residence box cuts seven state
    codes at the blank's 8 pt; at the pack's 7.3 pt every code's ink stays inside and verify PASSes the written box,
    and at 7.4 pt the widest (WV) overruns, so 7.3 is the largest size on the grid."""
    import re as _re

    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.verify import read_text_widgets

    path = FORMPACKS / "states/md/2023/md502/pack.yaml"
    pack = load_pack(path)
    pf = next(f for f in pack.fields if f.line == "other_state_of_residence")
    assert pf.font_size == 7.3
    w = next(x for x in read_text_widgets(fetch_pack_blank(pack)) if x.name == pf.field)

    def worst(size: float) -> tuple[float, str]:
        da = _re.sub(r"[\d.]+\s+Tf", f"{size:g} Tf", w.da)
        box = widget_box(w.rect_width, da, inset=w.inset, quadding=w.quadding, bold=w.bold, widths=w.font_widths)
        return max((ink_overrun(c, box), c) for c in STATE_CODES)

    assert worst(8.0)[0] > CUT_TOLERANCE_PT  # the blank's own size cuts a state code
    assert worst(7.3)[0] <= 0 < worst(7.4)[0]


def test_a_font_whose_widths_cover_no_encoded_character_is_not_measured_by_them():
    """The JEe3 review: /FirstChar past every encoded code (or every width 0) left an empty map, labelled a /Widths
    measure while every glyph fell back; font_widths now returns None, so the box keeps the standard measure."""
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject

    from taxfill_core.textfit import font_widths

    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/TrueType"),
                             NameObject("/BaseFont"): NameObject("/Verdana"), NameObject("/FirstChar"): NumberObject(300),
                             NameObject("/LastChar"): NumberObject(301),
                             NameObject("/Widths"): ArrayObject([NumberObject(600), NumberObject(600)]),
                             NameObject("/Encoding"): NameObject("/WinAnsiEncoding")})
    assert font_widths(font) is None
