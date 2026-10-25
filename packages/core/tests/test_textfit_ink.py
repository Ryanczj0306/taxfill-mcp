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

import json
import string
import sys
import warnings
from pathlib import Path

import pytest
from pdf_fixtures import make_acroform_pdf

from taxfill_core.schemas.formpack import load_pack
from taxfill_core.textfit import (
    _LSB_COURIER,
    _LSB_HELVETICA,
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
    widget_inset,
)
from taxfill_core.verify import (
    FAIL,
    PASS,
    PENDING_CLIP_DECISIONS,
    ClippingCheck,
    TextWidget,
    _pending_clip_decisions,
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
    """Draw every tabled glyph at 200 pt with reportlab (no embedding: pdfium substitutes its own base-14 faces, as for
    a form's /DA font), render at 2 px/pt, and take advance less ink edge; the table keeps the smaller of the regular
    and bold face."""
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
    if sys.platform != "darwin":
        # The tables were measured on macOS, where pdfium draws a non-embedded base-14 face with the system's Helvetica
        # and Courier; other platforms substitute other faces. Report this platform's bearings, so they can be folded
        # into the tables (Phase K JEe follow-up), and do not hold the macOS figures against them.
        report = {face: {ch: [round(lr[0], 3), round(lr[1], 3)] for ch, lr in m.items()} for face, m in measured.items()}
        warnings.warn(f"JEe bearings on {sys.platform}: {json.dumps(report, sort_keys=True)}", stacklevel=1)
        pytest.xfail(f"the bearing tables are measured on macOS; {sys.platform} substitutes other faces")
    for lsb, rsb, faces in ((_LSB_HELVETICA, _RSB_HELVETICA, ("Helvetica", "Helvetica-Bold")),
                            (_LSB_COURIER, _RSB_COURIER, ("Courier", "Courier-Bold"))):
        glyphs = "".join(rsb)
        regular, bold = (measured[face] for face in faces)
        for side, table in ((0, lsb), (1, rsb)):
            off = {ch: (table[ch], round(min(regular[ch][side], bold[ch][side]), 3)) for ch in glyphs
                   if abs(table[ch] - min(regular[ch][side], bold[ch][side])) > 0.006}
            assert not off, f"{faces} {('left', 'right')[side]} bearings: tabled vs measured differ: {off}"
        assert set(lsb) == set(rsb)
    assert set(string.digits + string.ascii_uppercase) <= set(_RSB_HELVETICA) <= set(_RSB_COURIER)


def test_the_tolerance_stays_under_the_thinnest_flagged_cut():
    """0.58 pt (RI's date of birth) is the thinnest cut a reviewer has flagged on a render, and the arithmetic gives it
    0.64 pt: the tolerance stays under both, and above the 0.14 pt the IRS's own year boxes lose and the 0.26 pt a bold
    Courier capital's ink starts left of its origin."""
    assert 0.26 < CUT_TOLERANCE_PT < 0.58
    assert ink_overrun("01012020", RI_DOB._replace(bold=False)) > CUT_TOLERANCE_PT


# ── the pending decision ─────────────────────────────────────────────────────


RI_PACKS = sorted(FORMPACKS.glob("states/ri/*/ri1040/pack.yaml"))


@pytest.mark.parametrize("path", RI_PACKS, ids=lambda p: p.parent.parent.name)
def test_ri_dob_keeps_its_verdict_until_the_user_decides(path: Path):
    """KG9: RI-1040's edge-to-edge boxes are the user's call (a shorter date, a smaller font, or a documented clip):
    the dependent dates of birth, the centred middle initials, the suffixes and the signature and preparer dates.
    Until it is recorded, a width FAIL on those boxes passes with the measured facts attached; nothing else changes."""
    pack = load_pack(path)
    pattern, note = PENDING_CLIP_DECISIONS[(pack.jurisdiction, pack.form)]
    covered = {pf.line for pf in pack.fields if pattern.fullmatch(pf.line)}
    dobs = sorted(line for line in covered if line.endswith(".dob"))
    assert len(dobs) == 13, f"{path}: {len(dobs)} dependent date-of-birth lines, the face prints 13 rows"
    assert covered - set(dobs) == {"name.middle_initial", "spouse.name.middle_initial", "name.suffix",
                                   "spouse.name.suffix", "signature.taxpayer.date", "signature.spouse.date",
                                   "preparer.date"}, covered - set(dobs)
    dob = qualified_field_name(pack, next(pf for pf in pack.fields if pf.line == dobs[0]))
    other = qualified_field_name(pack, next(pf for pf in pack.fields if not pattern.fullmatch(pf.line)))
    width_fail = "estimated text width 57.6pt (len 8 x 0.6 x 12pt Courier metric) exceeds the 55.6pt inside ..."
    checks = [
        ClippingCheck(name=dob, status=FAIL, detail=f"field '{dob}': {width_fail}"),
        ClippingCheck(name=dob, status=FAIL, detail=f"field '{dob}': value is 9 characters but MaxLen is 8"),
        ClippingCheck(name=other, status=FAIL, detail=f"field '{other}': {width_fail}"),
    ]
    box = {"da": "/CourierNewPSMT 12 Tf 0 g", "rect_width": 57.6, "monospace": True}
    widgets = [TextWidget(name=dob, value="01012020", **box), TextWidget(name=other, value="01012020", **box)]
    out = _pending_clip_decisions(pack, checks, widgets)
    assert out[0].status == PASS and note in out[0].detail and "0.6pt of its last digit" in out[0].detail
    assert "M or W" in note and "III" in note
    assert out[1].status == FAIL  # a MaxLen overflow is not the pending decision
    assert out[2].status == FAIL  # another box is not covered
    # a value wider than the rect itself is no edge-to-edge cut: it FAILed before JEe and still does
    longer = [TextWidget(name=dob, value="01/01/2020", **box)]
    assert _pending_clip_decisions(pack, checks[:1], longer)[0].status == FAIL
    ma = load_pack(FORMPACKS / "states/ma/2025/form1/pack.yaml")
    assert _pending_clip_decisions(ma, checks[:1], widgets) == checks[:1]


@pytest.mark.network
@pytest.mark.parametrize(("year", "value", "status"), [
    ("2023", "01/01/2020", FAIL),        # no pack maxlen in 2023: a slashed date is written, and it is far too wide
    ("2023", "January 1, 2020", FAIL),
    ("2025", "01012020", PASS),          # edge to edge: the pending decision, its facts in the detail
])
def test_the_pending_decision_covers_only_the_edge_to_edge_cut(year: str, value: str, status: str, tmp_path):
    """The JEe verifier's blocker: the exception once passed ANY width FAIL on the DOB box. Every verify path is run on
    a real fill: verify_form from disk, verify_form with the caller's widget records, and verify_filing."""
    from taxfill_core.fetch import fetch_pack_blank  # noqa: PLC0415
    from taxfill_core.filler import fill_form  # noqa: PLC0415
    from taxfill_core.verify import FilingItem, verify_filing, verify_form  # noqa: PLC0415

    pack = load_pack(FORMPACKS / f"states/ri/{year}/ri1040/pack.yaml")
    out = tmp_path / "ri.pdf"
    fill_form(pack, {"schedule_e.dependent_1.dob": value}, fetch_pack_blank(pack), out)
    dob = qualified_field_name(pack, next(pf for pf in pack.fields if pf.line == "schedule_e.dependent_1.dob"))

    def width_checks(report) -> list[ClippingCheck]:
        return [c for c in report.clipping if c.name.endswith(dob) and "estimated text width" in c.detail]

    reports = [
        verify_form(pack, out),
        verify_form(pack, out, widgets=read_text_widgets(out)),
        verify_filing([FilingItem(form_key="ri", pack=pack, pdf_path=out)]),
    ]
    for report in reports:
        checks = width_checks(report)
        assert checks and {c.status for c in checks} == {status}, [c.detail for c in checks]
        assert ("PENDING the user's decision" in checks[0].detail) == (status == PASS)


def test_every_pending_decision_row_still_names_a_shipped_form():
    for (jurisdiction, form), (pattern, _note) in PENDING_CLIP_DECISIONS.items():
        packs = [load_pack(p) for p in FORMPACKS.glob(f"{jurisdiction}/*/*/pack.yaml")]
        hits = [p for p in packs if p.form == form and any(pattern.fullmatch(pf.line) for pf in p.fields)]
        assert hits, f"PENDING_CLIP_DECISIONS names {jurisdiction} {form}, which no pack carries — delete the row"


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
        ("states/ri/2025/ri1040/pack.yaml", "schedule_e.dependent_1.dob", "01012020", True),
        ("states/ri/2025/ri1040/pack.yaml", "schedule_e.dependent_1.dob", "0101202", False),
        ("states/ca/2025/form540/pack.yaml", "mailing_address.apt_no", "1234567890123", True),
        ("states/ca/2025/form540/pack.yaml", "mailing_address.apt_no", "123456789012", False),
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
    name = qualified_field_name(loaded, next(pf for pf in loaded.fields if pf.line == line))
    widget = next(w for w in read_text_widgets(fetch_pack_blank(loaded)) if w.name == name)
    verdict = clipping_scan([widget.model_copy(update={"value": value})])[0].status
    assert verdict == (FAIL if cut else PASS), f"{value!r}: the model says {verdict}"
    measured = _cut_pt(FORMPACKS / pack, line, value, tmp_path)
    if cut:
        assert measured > 0.3, f"{value!r}: the model says cut, the render lost only {measured:.2f} pt"
    else:
        assert measured < 0.1, f"{value!r}: the model says whole, the render lost {measured:.2f} pt"
