"""Page-header mirrors (Phase K JK28, 2026-10-16): a pack's ``mirrors`` and what fill_form and verify do with them.

Many forms repeat the filer's name and SSN at the top of later pages, and the packs map each repeat as its own line:
CA Form 540 / 540NR print "Your name:" and "Your SSN or ITIN:" across the top of Sides 2-6 (pack lines name.full and
identifying_number.page6, one AcroForm field each with a widget on every side). Nothing filled or checked them: the
JK5 release-candidate walkthrough's Form 540 printed blank headers on Sides 2-6 and verify_form passed.

A pack now declares ``mirrors`` (mirror line -> template over its other lines). This module pins the schema's
validators, the filler's derivation (slices, optional segments, a caller's override, the refuse-and-warn path, the
rehearsal path), the verify identity check (PASS / SKIPPED / FAIL, in verify_form and per verify_filing item), and
the CA pilot, on synthetic PDFs (packages/core/tests/pdf_fixtures.py) and, network-marked, on the real 2023-2025
CA blanks. Since the JK28 review (2026-10-16) it also pins ``mirror_abbreviations`` (a name too wide for its box may
shorten the placeholders a pack lists), the digits-alone comparison of a number written with or without dashes, and
the FAIL detail of a mirror whose box refuses the full value. Since the second review (2026-10-16) both sides MEASURE
a mirror against its box with one shared measure (``taxfill_core.textfit``: the advance at the widget's /DA font and
size against its width less 2 pt): fill_form writes the first value of ``mirror_ladder`` its box holds, or leaves
the header blank with a hand-write warning when none fits, and verify FAILs a header that is cut off or abbreviated
although the full value fits, and SKIPs one left blank because nothing fits. Before it, "ALEXANDRA Q WASHINGTON"
printed cut off on the real CA 540 with no warning and verify passed it. Since the sweep (2026-10-23) every pack
that declares mirrors (CA plus 40 federal and state packs) is filled, network-marked, with demo page-1 identity
values alone, and each declared mirror must be built and verify; the header follow-ups (2026-10-23) add GA 2023's
SSN header, AL 2023 Form 40NR's schedule headers, DE PIT-RES 2024-2025, IA 1040 2023-2025 and CO DR 0104 2023, 53
packs in all; the final review (2026-10-23) adds AL Form 40 2023-2025, 56. The defect is registered as P-034
(knowledge/pitfalls.yaml). Demo values only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from pdf_fixtures import make_acroform_pdf
from taxfill_core.discovery import get_form_map
from taxfill_core.filler import fill_form
from taxfill_core.overlay import text_width
from taxfill_core.schemas.formpack import (
    SSN_DASH_CELLS,
    FormPack,
    load_pack,
    mirror_digit_lines,
    mirror_ladder,
    mirror_order,
    mirror_sources,
    mirror_words,
    parse_mirror_template,
    render_mirror,
)
from taxfill_core.textfit import CUT_TOLERANCE_PT, WidgetBox, advance, fit, ink_overrun, is_courier, widget_box
from taxfill_core.verify import (
    FilingItem,
    TextWidget,
    _abbreviates,
    _da_is_monospace,
    mirror_checks,
    verify_filing,
    verify_form,
)

REPO = Path(__file__).resolve().parents[3]
CA_PACKS = sorted((REPO / "formpacks" / "states" / "ca").glob("*/form540*/pack.yaml"))

NAME_TEMPLATE = "{name.first} {name.middle_initial} {name.last}[ & {spouse.first} {spouse.last}]"
FIELDS = [
    {"line": "name.first", "field": "p1_first", "type": "text"},
    {"line": "name.middle_initial", "field": "p1_mi", "type": "text", "maxlen": 1},
    {"line": "name.last", "field": "p1_last", "type": "text"},
    {"line": "spouse.first", "field": "p1_sp_first", "type": "text"},
    {"line": "spouse.last", "field": "p1_sp_last", "type": "text"},
    {"line": "identifying_number", "field": "p1_ssn", "type": "text", "maxlen": 9, "comb": True,
     "format": "ssn_digits_only"},
    {"line": "1", "field": "p1_wages", "type": "money"},
    {"line": "filing_status.single", "field": "p1_single", "type": "checkbox", "on_state": "/1"},
    {"line": "page2.name", "field": "p2_name", "type": "text", "maxlen": 40},
    {"line": "page2.ssn_area", "field": "p2_ssn_a", "type": "text", "maxlen": 3, "comb": True},
    {"line": "page2.ssn_group", "field": "p2_ssn_g", "type": "text", "maxlen": 2, "comb": True},
    {"line": "page2.ssn_serial", "field": "p2_ssn_s", "type": "text", "maxlen": 4, "comb": True},
    {"line": "page3.name", "field": "p3_name", "type": "text", "maxlen": 40},
    {"line": "page3.last10", "field": "p3_last10", "type": "text", "maxlen": 10},
]
MIRRORS = {
    # a mirror of a mirror, declared FIRST: the order comes from the dependencies, not from the YAML
    "page3.name": "{page2.name}",
    "page2.name": NAME_TEMPLATE,
    "page2.ssn_area": "{identifying_number[0:3]}",
    "page2.ssn_group": "{identifying_number[3:5]}",
    "page2.ssn_serial": "{identifying_number[5:]}",
    "page3.last10": "{name.last[:10]}",  # "Last Name (First 10 Characters)"
}
PERSON = {"name.first": "Pat", "name.middle_initial": "Q", "name.last": "Example", "identifying_number": "999-88-0101"}


def _raw(root: str = "", **changes) -> dict:
    raw = {
        "form": "TEST-M", "jurisdiction": "states/ca", "tax_year": 2025,
        "source_url": "https://www.ftb.ca.gov/forms/2025/test-m.pdf", "pdf_sha256": "...", "acroform_root": root,
        "fields": [dict(f) for f in FIELDS], "mirrors": dict(MIRRORS),
    }
    raw.update(changes)
    return raw


def _pack(root: str = "", **changes) -> FormPack:
    return FormPack.model_validate(_raw(root, **changes))


def _qualified(pack: FormPack, line: str) -> str:
    field = next(f.field for f in pack.fields if f.line == line)
    return f"{pack.acroform_root}.{field}" if pack.acroform_root else field


def _blank(pack: FormPack, path: Path, widths: dict[str, float] | None = None) -> Path:
    """A synthetic blank: every text box /Helv 12, 144 pt wide unless ``widths`` (line -> pt) says otherwise."""
    pages = {"p1": 1, "p2": 2, "p3": 3}
    specs = []
    for f in pack.fields:
        spec = {"name": _qualified(pack, f.line), "page": pages[f.field[:2]]}
        if f.type == "checkbox":
            spec.update(kind="checkbox", on_value=f.on_state)
        else:
            spec.update({k: v for k, v in (("maxlen", f.maxlen), ("comb", f.comb)) if v})
            if widths and f.line in widths:
                spec["width"] = widths[f.line]
        specs.append(spec)
    return make_acroform_pdf(path, specs)


def _set_da(pdf: Path, name: str, da: str, font: tuple[str, str] | None = None) -> Path:
    """Rewrite the /DA of the widget named ``name`` (the synthetic blanks set every box in /Helv 12).

    ``font`` (resource name, /BaseFont) adds the /DA's font to the AcroForm /DR, as a real blank carries it: pypdf
    rewrites a /DA whose font /DR lacks to Helvetica when it fills the box.
    """
    from pypdf import PdfWriter  # noqa: PLC0415
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject  # noqa: PLC0415

    writer = PdfWriter(clone_from=str(pdf))
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            if ref.get_object().get("/T") == name:
                ref.get_object()[NameObject("/DA")] = TextStringObject(da)
    if font is not None:
        fonts = writer._root_object["/AcroForm"].get_object()["/DR"].get_object()["/Font"].get_object()
        fonts[NameObject(f"/{font[0]}")] = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject(f"/{font[1]}"),
        }))
    with pdf.open("wb") as fh:
        writer.write(fh)
    return pdf


def _widgets(pack: FormPack, header: str, width: float, da: str = "/Helv 12 Tf 0 g") -> list[TextWidget]:
    """The page2.name widget as verify reads it off a PDF: what it holds, its /DA and its width."""
    return [TextWidget(name=_qualified(pack, "page2.name"), value=header, da=da, rect_width=width, rect_height=18)]


def _on_disk(pack: FormPack, pdf: Path) -> dict[str, str]:
    fields = PdfReader(str(pdf)).get_fields() or {}
    return {f.line: str(fields[_qualified(pack, f.line)].get("/V") or "") for f in pack.fields if f.type != "checkbox"}


def _dump(pack: FormPack, by_line: dict[str, str]) -> dict[str, str]:
    """A field dump (what read_pdf_fields returns) holding ``by_line`` on the pack's own field names."""
    return {_qualified(pack, line): value for line, value in by_line.items()}


def _mirror_check(report, mirror: str):
    return next(c for c in report.identity if c.field.endswith(f"page-header mirror {mirror}"))


# --- the template language ------------------------------------------------------------------------------------------


def test_jk28_render_mirror_slices_segments_and_whitespace():
    values = {"a": "  Pat   Q ", "b": "", "ssn": "999880101", "n": "Exampleton-Sample", "m": 1234}
    assert render_mirror("{a}", values) == "Pat Q"                          # collapsed and stripped
    assert render_mirror("{a} [& {b}]", values) == "Pat Q"                  # an empty segment drops with its text
    assert render_mirror("{a} [& {a}]", values) == "Pat Q & Pat Q"
    assert render_mirror("{ssn[0:3]}-{ssn[3:5]}-{ssn[5:]}", values) == "999-88-0101"
    assert render_mirror("{n[:10]}", values) == "Exampleton"
    assert render_mirror("{n[-6:]}", values) == "Sample"                    # a negative bound counts from the end
    assert render_mirror("{a[:1]}{n[:1]}", values) == "PE"                  # sliced AFTER the strip
    assert render_mirror("{m}", values) == "1234"                           # a money line renders as written
    assert render_mirror("Name: {b} {missing}", values) == ""               # no value: no caption either
    assert mirror_sources("{a} [& {b} {a[:1]}]") == ("a", "b")
    assert mirror_order({"z": "{y}", "y": "{x}", "w": "{q}"}) == ["y", "z", "w"]


@pytest.mark.parametrize(("template", "message"), [
    ("", "names no line"),
    ("Your name", "names no line"),
    ("{name.first", "is never closed"),
    ("{name.first}}", "stray '}'"),
    ("{name.first}]", "stray ']'"),
    ("[{name.first}", "never closed with ']'"),
    ("[{name.first} [{name.last}]]", "do not nest"),
    ("{name.first}[ & ]", "holds no placeholder"),
    ("{}", "must be {line} or {line[a:b]}"),
    ("{name.last[3]}", r"is an index, not a slice; the one character it means is [3:4]"),
    ("{name.last[-1]}", "the one character it means is [-1:]"),
    ("{name.last[0:10:2]}", "there is no step"),
    ("{name.last[a:b]}", "malformed slice"),
    ("{name.last[5:2]}", "selects nothing"),
    # a stop of 0 ends before the first character whatever the start ([:0] and [-1:0] loaded until Phase K JK28,
    # 2026-10-16)
    ("{name.last[:0]}", "selects nothing — a stop bound of 0 ends the slice before its first character"),
    ("{name.last[-1:0]}", "selects nothing — a stop bound of 0"),
    ("{name.last[:-0]}", "selects nothing — a stop bound of 0"),
])
def test_jk28_malformed_templates_are_refused_at_load(template: str, message: str):
    with pytest.raises(ValueError, match=re.escape(message)):
        parse_mirror_template(template)
    with pytest.raises(ValidationError, match=re.escape("mirrors['page2.name']: ") + ".*" + re.escape(message)):
        _pack(mirrors={**MIRRORS, "page2.name": template})


# --- the fit measure and the abbreviation ladder (Phase K JK28, 2026-10-16) -----------------------------------------


def test_jk28_fit_measures_helvetica_capitals_by_their_afm_widths():
    """The round-2 major: CA's "Your name:" box is 125.9 pt wide at Helv 10, and 22 capitals overrun it."""
    box = widget_box(125.93, "/Helv 10 Tf 0 0 1 rg")
    assert box == WidgetBox(125.93, 10.0, "Helv", False, False, 1.0, 0, False) and box.room == pytest.approx(123.93)
    assert advance("ALEXANDRA Q WASHINGTON", 10, bold=False) == text_width("ALEXANDRA Q WASHINGTON", 10)  # overlay's AFM
    long = fit("ALEXANDRA Q WASHINGTON", [box])
    assert long == (False, "142.8 pt at Helv 10, wider than the 123.9 pt inside its box: 125.9 pt wide, less 1 pt on "
                           "each side")
    assert fit("CHRISTOPHER M RODRIGUEZ", [box]).fits is False  # 146.7 pt
    assert fit("A Q WASHINGTON", [box]).fits is True             # 88.9 pt
    assert len("ALEXANDRA Q WASHINGTON") * 0.5 * 10 < 125.93     # P-001's 0.5-em estimate (110 pt) passed it


# (box width pt, /DA size pt, capitals A-Z, digits) drawn whole by probe renders: the digit counts are the measured
# CA rows of test_pack_maxlen.py (JK27), the capitals and the IL ZIP box the JK28 budgets work's probe renders.
@pytest.mark.parametrize(("width", "size", "capitals", "digits"), [
    (72.5, 10.0, 11, 12),   # CA 540 / 540NR mailing "Apt. no/ste. no."
    (73.0, 10.0, 11, 12),   # CA 540 / 540NR "PMB/private mailbox"
    (70.7, 10.0, 10, 12),   # CA 540 principal-residence "Apt. no/ste. no."
    (79.56, 9.0, 13, 15),   # IL-1040 2025 ZIP or postal code (Arial 9, measured with Helvetica's widths)
])
def test_jk28_fit_holds_what_the_probe_renders_drew_whole(width: float, size: float, capitals: int, digits: int):
    box = WidgetBox(width, size, "Helv")
    caps = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    assert fit(caps[:capitals], [box]).fits and not fit(caps[:capitals + 1], [box]).fits
    assert fit("0" * digits, [box]).fits and not fit("0" * (digits + 1), [box]).fits


def test_jk28_fit_measures_courier_at_0_6_em_and_reads_the_face_as_verify_does():
    box = widget_box(98.6, "/Cour 12 Tf 0 g")  # AL Form 40's first-name box: 98.6 pt at Courier 12 fits 13
    assert box.courier and advance("W" * 13, 12, courier=True) == pytest.approx(93.6)
    assert fit("W" * 13, [box]).fits and not fit("I" * 14, [box]).fits  # every Courier glyph is 0.6 em
    for da, base_fonts, courier in [
        ("/Helv 10 Tf 0 g", {"Helv": "Helvetica"}, False),
        ("/Cour 10 Tf 0 g", {}, True),                        # Acrobat's alias, unresolved
        ("/CoBo 9 Tf 0 g", {}, True),
        ("/F1 10 Tf 0 g", {"F1": "CourierNewPSMT"}, True),    # resolved through the AcroForm /DR
        ("/Cour 10 Tf 0 g", {"Cour": "Helvetica"}, False),    # the /DR /BaseFont decides over the alias
        ("/CourierNew,Bold 8 Tf 0 g", {}, True),
        ("/Arial 9 Tf 0 g", {}, False),                       # Arial: Helvetica's widths
        ("/KozGoPr6N-Medium 10 Tf 0 g", {}, False),           # any other face with no /DR /Widths: Helvetica
    ]:
        assert widget_box(100, da, base_fonts=base_fonts).courier is courier, da
        assert _da_is_monospace(da, base_fonts) is courier, da  # the rule of verify's clipping scan
        assert is_courier(da.split()[0][1:], base_fonts) is courier, da


def test_jk28_fit_auto_size_always_fits_and_an_unmeasured_box_says_so():
    long = "ALEXANDRA Q WASHINGTON"
    assert fit(long, [widget_box(40, "/Helv 0 Tf 0 g")]) == (
        True, "an auto-size box (/DA 0 Tf): the viewer shrinks the text to fit")
    assert fit(long, [widget_box(40, "/Helv 0 Tf 0 g"), widget_box(125.93, "/Helv 10 Tf 0 g")]).fits is False
    unmeasured = "no single-line widget of the field with a width and a font size to measure"
    assert fit(long, []) == (None, unmeasured)
    assert fit(long, [WidgetBox(0.0, 10.0, "Helv")]) == (None, unmeasured)                   # no width
    assert fit(long, [WidgetBox(300.0, 10.0, "Helv", multiline=True)]) == (None, unmeasured)  # a box that wraps
    assert widget_box(125.93, None) == WidgetBox(125.93, 10.0, "", False, False)             # no /DA: 10 pt
    assert fit(long, [widget_box(125.93, None)]).detail.startswith("142.8 pt at Helvetica 10, wider than")
    assert fit("ABCDEFGHIJKLM", [], maxlen=12) == (False, "13 characters, and the box takes at most 12")
    assert fit("ABCDEFGHIJKLM", [WidgetBox(10.0, 10.0)], comb=True).fits is True  # a comb box: its own rules


def test_jk28_fit_binds_on_the_narrowest_widget_and_an_exact_fit_fits():
    sides = [widget_box(w, "/Helv 10 Tf 0 0 1 rg") for w in (127.0, 125.93, 127.0, 127.0, 127.0)]  # CA 540 Sides 2-6
    assert fit("ALEXANDRA Q WASHINGTON", sides).detail.endswith(
        "inside the narrowest of its 5 widgets: 125.9 pt wide, less 1 pt on each side")
    exact = WidgetBox(text_width("RILEY EXAMPLE", 10) + 2, 10.0, "Helv")  # the value's advance plus the two borders
    assert fit("RILEY EXAMPLE", [exact]).fits and not fit("RILEY EXAMPLES", [exact]).fits


CA_NAME = "{name.first} {name.middle_initial} {name.last} {name.suffix}"
CA_SHORT = ["name.first", "name.middle_initial"]


def test_jk28_mirror_ladder_cuts_the_listed_words_to_initials_then_keeps_the_first():
    alexandra = {"name.first": "ALEXANDRA", "name.middle_initial": "Q", "name.last": "WASHINGTON"}
    assert mirror_ladder(CA_NAME, alexandra, CA_SHORT) == ["ALEXANDRA Q WASHINGTON", "A Q WASHINGTON", "A WASHINGTON"]
    assert mirror_ladder(CA_NAME, {**alexandra, "name.suffix": "JR"}, CA_SHORT) == [
        "ALEXANDRA Q WASHINGTON JR", "A Q WASHINGTON JR", "A WASHINGTON JR"]  # the suffix stays whole
    assert mirror_ladder(CA_NAME, {**alexandra, "name.first": "MARY ANN"}, CA_SHORT) == [
        "MARY ANN Q WASHINGTON", "M A Q WASHINGTON", "M WASHINGTON"]          # every word of a listed line
    assert mirror_ladder(CA_NAME, {**alexandra, "name.first": "A"}, CA_SHORT) == ["A Q WASHINGTON", "A WASHINGTON"]
    assert mirror_ladder(CA_NAME, {"name.last": "WASHINGTON"}, CA_SHORT) == ["WASHINGTON"]  # nothing to shorten
    assert mirror_ladder(CA_NAME, alexandra) == ["ALEXANDRA Q WASHINGTON"]                # no mirror_abbreviations
    assert mirror_ladder(CA_NAME, {}, CA_SHORT) == []
    assert mirror_ladder("{name.first}{name.last}", alexandra, CA_SHORT) == ["ALEXANDRAWASHINGTON"]  # glued: whole
    # every rung is an abbreviation verify accepts: both read the one word list, mirror_words
    for values in (alexandra, {**alexandra, "name.suffix": "III"}, {**alexandra, "name.first": "MARY ANN"}):
        words = [(word.casefold(), short) for word, short in mirror_words(CA_NAME, values, CA_SHORT)]
        for rung in mirror_ladder(CA_NAME, values, CA_SHORT):
            assert _abbreviates(rung, words), rung


# --- the schema's validators ----------------------------------------------------------------------------------------


def test_jk28_a_valid_pack_loads_its_mirrors_in_dependency_order():
    pack = _pack()
    assert pack.mirrors == MIRRORS
    order = mirror_order(pack.mirrors)
    assert order.index("page2.name") < order.index("page3.name") and set(order) == set(MIRRORS)
    assert FormPack.model_validate({k: v for k, v in _raw().items() if k != "mirrors"}).mirrors == {}


@pytest.mark.parametrize(("mirrors", "message"), [
    ({"page2.nmae": "{name.last}"}, "mirrors: key 'page2.nmae' is not a line of this pack (did you mean 'page2.name'"),
    ({"1": "{name.last}"}, "mirrors: '1' is a money line"),
    ({"filing_status.single": "{name.last}"}, "mirrors: 'filing_status.single' is a checkbox line"),
    ({"page2.name": "{page2.name}"}, "reads 'page2.name' itself"),
    ({"page2.name": "{name.frist}"}, "placeholder {name.frist} names no line of this pack (did you mean 'name.first'"),
    ({"page2.name": "{filing_status.single}"}, "names a checkbox line"),
    ({"page2.name": "{page3.name}", "page3.name": "{page2.name}"},
     "mirrors read each other in a cycle (page2.name -> page3.name -> page2.name)"),
    ({"page2.name": "{page3.last10}", "page3.last10": "{page3.name}", "page3.name": "{page2.name}"},
     "mirrors read each other in a cycle (page2.name -> page3.last10 -> page3.name -> page2.name)"),
])
def test_jk28_each_mirror_validator_refuses_prescriptively(mirrors: dict, message: str):
    with pytest.raises(ValidationError, match=re.escape(message)):
        _pack(mirrors=mirrors)


ABBREVIABLE = {"page2.name": ["name.first", "name.middle_initial", "spouse.first"]}


@pytest.mark.parametrize(("abbreviations", "message"), [
    ({"page2.nmae": ["name.first"]},
     "mirror_abbreviations: 'page2.nmae' is not a mirror of this pack (did you mean 'page2.name'"),
    ({"page2.ssn_area": ["identifying_number"]},
     "mirror_abbreviations: 'page2.ssn_area' is a comb or ssn_digits_only line, which verify compares digit for digit"),
    ({"page2.name": []}, "mirror_abbreviations['page2.name'] lists no placeholder"),
    ({"page2.name": ["name.frist"]},
     "mirror_abbreviations['page2.name']: 'name.frist' is not a placeholder of its template"),
    ({"page2.name": ["1"]}, "'1' is not a placeholder of its template"),  # a line of the pack the template never reads
    ({"page2.name": ["name.first", "name.first"]}, "lists name.first more than once"),
    ({"page3.last10": ["name.last"]}, "lets the header abbreviate every placeholder of '{name.last[:10]}'"),
])
def test_jk28_each_mirror_abbreviations_validator_refuses_prescriptively(abbreviations: dict, message: str):
    with pytest.raises(ValidationError, match=re.escape(message)):
        _pack(mirror_abbreviations=abbreviations)


def test_jk28_mirror_abbreviations_needs_the_mirror_declared():
    with pytest.raises(ValidationError, match=re.escape("'page2.name' is not a mirror of this pack")):
        _pack(mirrors={}, mirror_abbreviations=ABBREVIABLE)
    assert _pack(mirror_abbreviations=ABBREVIABLE).mirror_abbreviations == ABBREVIABLE
    assert _pack().mirror_abbreviations == {}


def test_jk28_a_mirror_must_own_its_acroform_field():
    fields = [*FIELDS, {"line": "page2.name_copy", "field": "p2_name", "type": "text"}]
    with pytest.raises(ValidationError, match=re.escape("mirrors: 'page2.name' binds AcroForm field 'p2_name', "
                                                       "which ['page2.name_copy'] also bind(s)")):
        _pack(fields=fields)


def test_jk28_get_form_map_shows_the_mirrors():
    fm = get_form_map("form540", 2025, "states/ca")
    assert fm.mirrors == {"name.full": "{name.first} {name.middle_initial} {name.last} {name.suffix}",
                          "identifying_number.page6": "{identifying_number}"}
    assert fm.mirror_abbreviations == {"name.full": ["name.first", "name.middle_initial"]}
    assert get_form_map("f1040", 2025).mirrors == {} and get_form_map("f1040", 2025).mirror_abbreviations == {}


# --- fill_form ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("root", ["", "topmostSubform[0]"], ids=["flat", "rooted"])
def test_jk28_fill_form_builds_the_mirrors_the_caller_leaves_out(tmp_path: Path, root: str):
    pack = _pack(root)
    out = tmp_path / "filled.pdf"
    result = fill_form(pack, PERSON, _blank(pack, tmp_path / "blank.pdf"), out)
    disk = _on_disk(pack, out)
    assert disk["page2.name"] == "Pat Q Example"            # the spouse segment is absent: no spouse on Side 1
    assert disk["page3.name"] == "Pat Q Example"            # a mirror of the mirror, built after it
    assert (disk["page2.ssn_area"], disk["page2.ssn_group"], disk["page2.ssn_serial"]) == ("999", "88", "0101")
    assert disk["identifying_number"] == "999880101"        # the slices read the line AS RENDERED (digits only)
    assert disk["page3.last10"] == "Example"
    assert result.mirrored == ["page2.name", "page3.name", "page2.ssn_area", "page2.ssn_group", "page2.ssn_serial",
                               "page3.last10"]  # dependency order: page3.name is built from the page2.name just built
    assert result.warnings == []
    assert result.written[_qualified(pack, "page2.name")] == "Pat Q Example"


def test_jk28_the_optional_segment_prints_when_its_line_has_a_value(tmp_path: Path):
    pack = _pack()
    out = tmp_path / "joint.pdf"
    # 'Pat Q Exampleton-Sample & Sam Example' is 231.4 pt at Helv 12: a 320 pt header holds it whole
    fill_form(pack, {**PERSON, "spouse.first": "Sam", "spouse.last": "Example", "name.last": "Exampleton-Sample"},
              _blank(pack, tmp_path / "blank.pdf", {"page2.name": 320, "page3.name": 320}), out)
    disk = _on_disk(pack, out)
    assert disk["page2.name"] == "Pat Q Exampleton-Sample & Sam Example"
    assert disk["page3.last10"] == "Exampleton"             # "first 10 characters of your last name"


def test_jk28_a_caller_supplied_mirror_wins_and_a_blank_one_is_built(tmp_path: Path):
    pack = _pack()
    blank = _blank(pack, tmp_path / "blank.pdf")
    given = fill_form(pack, {**PERSON, "page2.name": "PAT EXAMPLE"}, blank, tmp_path / "given.pdf")
    disk = _on_disk(pack, tmp_path / "given.pdf")
    assert disk["page2.name"] == "PAT EXAMPLE"              # written as given ...
    assert disk["page3.name"] == "PAT EXAMPLE"              # ... and the mirror of it reads the caller's value
    assert "page2.name" not in given.mirrored and "page3.name" in given.mirrored
    built = fill_form(pack, {**PERSON, "page2.name": "  "}, blank, tmp_path / "built.pdf")
    assert _on_disk(pack, tmp_path / "built.pdf")["page2.name"] == "Pat Q Example"
    assert "page2.name" in built.mirrored


def test_jk28_nothing_to_mirror_writes_nothing(tmp_path: Path):
    pack = _pack()
    out = tmp_path / "wages.pdf"
    result = fill_form(pack, {"1": 100}, _blank(pack, tmp_path / "blank.pdf"), out)
    assert result.mirrored == [] and result.warnings == []
    assert {line: value for line, value in _on_disk(pack, out).items() if value} == {"1": "100"}


def test_jk28_a_built_value_over_its_maxlen_is_left_blank_to_hand_write(tmp_path: Path):
    # A plain box's maxlen is a question of room, like its width (Phase K JK28, 2026-10-16): with no abbreviation the
    # pack allows, the header is left blank for the filer to hand-write, and every other mirror is still written.
    fields = [dict(f, maxlen=12) if f["line"] == "page2.name" else f for f in FIELDS]
    pack = _pack(fields=fields)
    out = tmp_path / "long.pdf"
    result = fill_form(pack, PERSON, _blank(pack, tmp_path / "blank.pdf"), out)  # does not raise
    disk = _on_disk(pack, out)
    assert disk["page2.name"] == "" and disk["page3.name"] == ""  # its own mirror reads it as the blank it is
    assert disk["page2.ssn_area"] == "999"                        # every other mirror is still written
    assert "page2.name" not in result.mirrored and "page3.name" not in result.mirrored
    (warning,) = result.warnings
    assert warning == (
        "mirror line 'page2.name' left blank: its box cannot hold 'Pat Q Example' (13 characters, and the box takes at "
        "most 12), and the pack allows no shorter form of it — fill_form never writes a header its box would cut off, "
        "so hand-write it in the box after printing (verify_form does not fail a header left blank for this reason: "
        "its check is SKIPPED)"
    )

    # With the pack's abbreviations, the first one within the maxlen is written instead.
    pack = _pack(fields=fields, mirror_abbreviations=ABBREVIABLE)
    result = fill_form(pack, PERSON, _blank(pack, tmp_path / "blank2.pdf"), tmp_path / "short.pdf")
    assert _on_disk(pack, tmp_path / "short.pdf")["page2.name"] == "P Q Example"
    assert result.warnings[0].startswith(
        "mirror line 'page2.name': 'Pat Q Example' does not fit its box (13 characters, and the box takes at most 12), "
        "so fill_form wrote 'P Q Example'")


def test_jk28_a_comb_mirror_refuses_letters_and_nra_like_a_supplied_value(tmp_path: Path):
    fields = [*FIELDS, {"line": "spouse.tin_text", "field": "p1_sp_tin", "type": "text"},
              {"line": "page2.spouse_tin", "field": "p2_sp_tin", "type": "text", "maxlen": 9, "comb": True}]
    pack = _pack(fields=fields, mirrors={**MIRRORS, "page2.spouse_tin": "{spouse.tin_text}"})
    blank = _blank(pack, tmp_path / "blank.pdf")
    nra = fill_form(pack, {**PERSON, "spouse.tin_text": "NRA"}, blank, tmp_path / "nra.pdf")
    assert any("'page2.spouse_tin' left blank" in w and "'NRA' never goes in an identifying-number or comb box" in w
               for w in nra.warnings)
    letters = fill_form(pack, {**PERSON, "spouse.tin_text": "12A"}, blank, tmp_path / "letters.pdf")
    assert any("'page2.spouse_tin' left blank" in w and "comb fields take digits only" in w for w in letters.warnings)
    assert _on_disk(pack, tmp_path / "letters.pdf")["page2.spouse_tin"] == ""


def test_jk28_a_long_built_ssn_is_redacted_in_the_warning(tmp_path: Path):
    fields = [*FIELDS, {"line": "spouse.tin_text", "field": "p1_sp_tin", "type": "text"},
              {"line": "page2.spouse_tin", "field": "p2_sp_tin", "type": "text", "maxlen": 9}]
    pack = _pack(fields=fields, mirrors={**MIRRORS, "page2.spouse_tin": "{spouse.tin_text}"})
    result = fill_form(pack, {**PERSON, "spouse.tin_text": "999-88-0102"}, _blank(pack, tmp_path / "blank.pdf"),
                       tmp_path / "out.pdf")
    (warning,) = result.warnings
    assert "999-88-0102" not in warning and "[redacted-id]" in warning


def test_jk28_a_rehearsal_fill_builds_mirrors_too(tmp_path: Path):
    pack = _pack(jurisdiction="federal", tax_year=2026, source_url="https://www.irs.gov/pub/irs-dft/test-m--dft.pdf",
                 source_status="draft", draft_created="8/19/26")
    out = tmp_path / "rehearsal.pdf"
    result = fill_form(pack, PERSON, _blank(pack, tmp_path / "blank.pdf"), out, rehearsal=True)
    assert result.rehearsal and "page2.name" in result.mirrored
    assert _on_disk(pack, out)["page2.name"] == "Pat Q Example"
    report = verify_form(pack, out, rehearsal=True)
    assert _mirror_check(report, "page2.name").status == "PASS"


# --- verify ---------------------------------------------------------------------------------------------------------


def test_jk28_verify_passes_the_mirrors_fill_form_built(tmp_path: Path):
    pack = _pack()
    out = tmp_path / "filled.pdf"
    fill_form(pack, {**PERSON, "filing_status.single": True}, _blank(pack, tmp_path / "blank.pdf"), out)
    report = verify_form(pack, out)
    checks = {c.field: c for c in report.identity}
    assert set(checks) == {f"page-header mirror {m}" for m in MIRRORS}
    assert {c.status for c in checks.values()} == {"PASS"}
    assert checks["page-header mirror page2.name"].values == {"TEST-M": "Pat Q Example"}
    assert report.ok, [c.detail for c in report.identity if c.status == "FAIL"]


def test_jk28_verify_fails_the_blank_headers_a_mirrorless_fill_leaves(tmp_path: Path):
    # The JK5 walkthrough's shape: Side 1 filled, the header mirrors never written.
    pack = _pack()
    mirrorless = FormPack.model_validate({k: v for k, v in _raw().items() if k != "mirrors"})
    out = tmp_path / "pre_jk28.pdf"
    fill_form(mirrorless, {**PERSON, "filing_status.single": True}, _blank(pack, tmp_path / "blank.pdf"), out)
    assert verify_form(mirrorless, out).ok        # what the gate said before: nothing checked the headers
    report = verify_form(pack, out)
    assert not report.ok
    check = _mirror_check(report, "page2.name")
    assert check.status == "FAIL"
    assert "page-header mirror 'page2.name' is BLANK but must repeat 'Pat Q Example'" in check.detail
    assert "fill_form: it fills the mirrors you leave out" in check.detail
    statuses = {m: _mirror_check(report, m).status for m in MIRRORS}
    # page3.name repeats page2.name AS ON DISK, which is blank: nothing to mirror yet, and page2.name's FAIL holds ok
    assert statuses == {**{m: "FAIL" for m in MIRRORS}, "page3.name": "SKIPPED"}


def test_jk28_verify_fails_a_mirror_that_says_something_else(tmp_path: Path):
    pack = _pack()
    out = tmp_path / "wrong.pdf"
    fill_form(pack, {**PERSON, "filing_status.single": True, "page2.name": "Someone Else"},
              _blank(pack, tmp_path / "blank.pdf"), out)
    report = verify_form(pack, out)
    assert not report.ok
    wrong = _mirror_check(report, "page2.name")
    assert wrong.status == "FAIL" and wrong.values == {"TEST-M": "Someone Else"}
    assert "holds 'Someone Else' but its template" in wrong.detail and "builds 'Pat Q Example'" in wrong.detail
    assert "leaving 'page2.name' out (fill_form fills the mirrors you leave out)" in wrong.detail
    assert _mirror_check(report, "page3.name").status == "PASS"  # it repeats page2.name as written there


def test_jk28_verify_compares_case_and_whitespace_blind_and_ssn_digits_only():
    fields = [*FIELDS, {"line": "spouse.tin_text", "field": "p1_sp_tin", "type": "text"},
              {"line": "page2.spouse_tin", "field": "p2_sp_tin", "type": "text", "maxlen": 11,
               "format": "ssn_digits_only"}]
    pack = _pack(fields=fields, mirrors={"page2.name": NAME_TEMPLATE, "page2.spouse_tin": "{spouse.tin_text}"})
    dump = _dump(pack, {"name.first": "Pat", "name.last": "Example", "page2.name": "  PAT   example ",
                        "spouse.tin_text": "999880102", "page2.spouse_tin": "999-88-0102"})
    checks = {c.field: c.status for c in mirror_checks(pack, dump)}
    assert checks == {"page-header mirror page2.name": "PASS", "page-header mirror page2.spouse_tin": "PASS"}
    dump[_qualified(pack, "page2.spouse_tin")] = "999-88-0103"
    assert _mirror_check(verify_form(pack, dump), "page2.spouse_tin").status == "FAIL"


def test_jk28_verify_compares_a_number_by_its_digits_whatever_its_dashes():
    # CA's "Your SSN or ITIN:" header and its Side 1 source are plain text boxes (no comb, no format), so either side
    # may hold the SSN with or without dashes; a dash-style difference FAILed and flipped ok (Phase K JK28, 2026-10-16).
    fields = [{"line": "tin", "field": "p1_tin", "type": "text", "maxlen": 11},
              {"line": "page2.tin", "field": "p2_tin", "type": "text", "maxlen": 11}]
    pack = _pack(fields=fields, mirrors={"page2.tin": "{tin}"})
    for side1, header, status in [
        ("999880503", "999-88-0503", "PASS"),
        ("999-88-0503", "999880503", "PASS"),
        ("999 88 0503", "999-88-0503", "PASS"),
        ("999880503", "999-88-0504", "FAIL"),     # another number
        ("999-88-0503", "999-88-0503 X", "FAIL"),  # not a number alone: compared as text
        ("NRA", "999-88-0503", "FAIL"),
    ]:
        (check,) = mirror_checks(pack, _dump(pack, {"tin": side1, "page2.tin": header}))
        assert check.status == status, (side1, header, check.detail)


# --- Phase K JK28 (2026-10-23): a slice of an SSN-format line reads its digits ---------------------------------------

DASH_CELL_FIELDS = [
    {**field, "maxlen": 11, "format": SSN_DASH_CELLS} if field["line"] == "identifying_number" else field
    for field in FIELDS
]
SSN_SPLIT = ("page2.ssn_area", "page2.ssn_group", "page2.ssn_serial")


def test_jk28_a_slice_of_an_ssn_format_line_reads_its_digits():
    template = "{ssn[0:3]}|{ssn[3:5]}|{ssn[5:]}|{ssn[-4:]}"
    for written in ("999880101", "999-88-0101", "999 88 0101", " 999-880101 "):
        assert render_mirror(template, {"ssn": written}, digit_lines={"ssn"}) == "999|88|0101|0101", written
        assert mirror_ladder("{ssn[3:5]}", {"ssn": written}, digit_lines={"ssn"}) == ["88"], written
    # the whole line is not a slice: it renders as written (the mirror's own format then renders it for its box)
    assert render_mirror("{ssn}", {"ssn": "999-88-0101"}, digit_lines={"ssn"}) == "999-88-0101"
    # a line in no SSN format keeps its characters, and a value that is not a number is sliced as text
    assert render_mirror("{ssn[3:5]}", {"ssn": "999-88-0101"}) == "-8"
    assert render_mirror("{ssn[:3]}", {"ssn": "NRA"}, digit_lines={"ssn"}) == "NRA"
    pack = _pack(fields=DASH_CELL_FIELDS)
    assert mirror_digit_lines(pack.fields) == {"identifying_number"}
    assert mirror_digit_lines(_pack().fields) == {"identifying_number"}  # ssn_digits_only too


@pytest.mark.parametrize("given", ["999880101", "999-88-0101"])
def test_jk28_fill_form_splits_a_dash_cell_ssn_by_its_digits(tmp_path: Path, given: str):
    """The source writes 'ddd-dd-dddd' (ssn_dash_cells): the split boxes still get 999 / 88 / 0101, not '-8' / '8-0101'
    (each refused by its comb, so the boxes were left blank with a warning)."""
    pack = _pack(fields=DASH_CELL_FIELDS)
    out = tmp_path / "filled.pdf"
    result = fill_form(pack, {**PERSON, "identifying_number": given}, _blank(pack, tmp_path / "blank.pdf"), out)
    disk = _on_disk(pack, out)
    assert disk["identifying_number"] == "999-88-0101"
    assert tuple(disk[line] for line in SSN_SPLIT) == ("999", "88", "0101")
    assert result.warnings == []
    report = verify_form(pack, out)
    assert {_mirror_check(report, line).status for line in SSN_SPLIT} == {"PASS"}, [
        _mirror_check(report, line).detail for line in SSN_SPLIT]


@pytest.mark.parametrize("fields", [FIELDS, DASH_CELL_FIELDS], ids=["ssn_digits_only", "ssn_dash_cells"])
def test_jk28_verify_splits_an_ssn_source_by_its_digits_however_it_is_written(fields: list):
    pack = _pack(fields=fields)
    for source in ("999880101", "999-88-0101"):
        dump = _dump(pack, {"identifying_number": source, "page2.ssn_area": "999", "page2.ssn_group": "88",
                            "page2.ssn_serial": "0101"})
        checks = {c.field: c for c in mirror_checks(pack, dump)}
        statuses = {line: checks[f"page-header mirror {line}"].status for line in SSN_SPLIT}
        assert statuses == dict.fromkeys(SSN_SPLIT, "PASS"), (source, [c.detail for c in checks.values()])
        dump[_qualified(pack, "page2.ssn_group")] = "89"  # another number still fails
        (wrong,) = [c for c in mirror_checks(pack, dump) if c.field == "page-header mirror page2.ssn_group"]
        assert wrong.status == "FAIL", source


NARROW = 80.0  # pt at Helv 12, 78 pt inside: 'Pat Q Example' advances 80.7 pt, 'P Q Example' 70.7, 'P Example' 58.0
RULE = ("name.first, name.middle_initial and spouse.first shortened to an initial or left out, name.last and "
        "spouse.last whole")
TOO_WIDE = "80.7 pt at Helv 12, wider than the 78.0 pt inside its box: 80.0 pt wide, less 1 pt on each side"


@pytest.mark.parametrize(("header", "status"), [
    ("P Q Example", "PASS"),      # a first initial
    ("p. q. example", "PASS"),    # initials with periods, in any case
    ("P Example", "PASS"),        # the middle initial left out
    ("Pa Example", "PASS"),       # any leading part
    ("Pat Q Example", "FAIL"),    # the full value, which the box cuts off
    ("Pat Q Exampl", "FAIL"),     # name.last is not listed, so it stays whole
    ("Sam Q Example", "FAIL"),    # another first name
    ("Example Pat", "FAIL"),      # out of order
    ("P Q Example Sr", "FAIL"),   # a word the template does not build
    ("P Q", "FAIL"),              # the last name left out
    ("P. . Example", "FAIL"),     # a bare period abbreviates nothing
])
def test_jk28_a_header_may_abbreviate_only_what_mirror_abbreviations_lists(header: str, status: str):
    """Measured against a box 'Pat Q Example' does not fit: an abbreviation the pack allows that fits passes."""
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    report = verify_form(pack, _dump(pack, {**PERSON, "page2.name": header}), widgets=_widgets(pack, header, NARROW))
    check = _mirror_check(report, "page2.name")
    assert check.status == status, check.detail
    if status == "PASS":
        assert (f"abbreviates 'Pat Q Example' (its template '{NAME_TEMPLATE}') as {header!r}, which the pack's "
                f"mirror_abbreviations allow ({RULE}): 'Pat Q Example' does not fit its box ({TOO_WIDE})") in check.detail
    else:  # the detail names the value to write: the abbreviation fill_form would write
        assert f"write 'P Q Example', the abbreviation the pack's mirror_abbreviations allow ({RULE}) that fits" in \
            check.detail


@pytest.mark.parametrize("header", ["P Q Example", "P. Example", "Example"])
def test_jk28_an_abbreviated_header_fails_when_the_full_name_fits(header: str):
    """The round-2 minor: 'EXAMPLE' for 'RILEY EXAMPLE' passed whether or not the name fits. An abbreviation is
    allowed only when the full value does not fit its box."""
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    report = verify_form(pack, _dump(pack, {**PERSON, "page2.name": header}), widgets=_widgets(pack, header, 144))
    check = _mirror_check(report, "page2.name")
    assert check.status == "FAIL" and not report.ok
    assert f"holds {header!r}, an abbreviation of 'Pat Q Example'" in check.detail
    assert ("but 'Pat Q Example' fits its box (80.7 pt at Helv 12, within the 142.0 pt inside its box: 144.0 pt wide, "
            "less 1 pt on each side), so the header must repeat it whole — refill with fill_form, leaving "
            "'page2.name' out or passing exactly 'Pat Q Example', then re-verify") in check.detail


def test_jk28_a_joint_header_abbreviates_each_listed_part_in_place():
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    joint = {**PERSON, "spouse.first": "Sam", "spouse.last": "Example"}
    # a 160 pt box holds 158 pt: the full joint name is 170.1 pt, 'P Q Example & S Example' 143.4
    assert mirror_ladder(NAME_TEMPLATE, joint, ABBREVIABLE["page2.name"]) == [
        "Pat Q Example & Sam Example", "P Q Example & S Example", "P Example & Example"]
    for header, status in [
        ("Pat Q Example & Sam Example", "FAIL"),  # cut off
        ("P Q Example & S Example", "PASS"),
        ("P Example & S Example", "PASS"),
        ("P Example & Example", "PASS"),  # spouse.first is listed, so it may be left out
        ("P Example", "FAIL"),            # the printed segment's literal '&' and spouse.last stay whole
        ("P Example S Example", "FAIL"),  # the literal '&' dropped
    ]:
        report = verify_form(pack, _dump(pack, {**joint, "page2.name": header}), widgets=_widgets(pack, header, 160))
        check = _mirror_check(report, "page2.name")
        assert check.status == status, (header, check.detail)


def test_jk28_without_mirror_abbreviations_an_abbreviated_header_still_fails():
    pack = _pack()
    check = _mirror_check(verify_form(pack, _dump(pack, {**PERSON, "page2.name": "P Q Example"})), "page2.name")
    assert check.status == "FAIL" and "abbreviation" not in check.detail
    blank = _mirror_check(verify_form(pack, _dump(pack, PERSON)), "page2.name")
    assert blank.status == "FAIL" and "abbreviat" not in blank.detail


def test_jk28_a_caller_abbreviated_header_fills_and_verifies(tmp_path: Path):
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    out = tmp_path / "short.pdf"
    blank = _blank(pack, tmp_path / "blank.pdf", {"page2.name": NARROW})
    result = fill_form(pack, {**PERSON, "filing_status.single": True, "page2.name": "P. Example"}, blank, out)
    assert "page2.name" not in result.mirrored and "page3.name" in result.mirrored  # page3 repeats the caller's value
    assert result.warnings == []  # a value the caller passes is written as given; verify measures it
    report = verify_form(pack, out)
    assert report.ok, [c.detail for c in report.identity if c.status == "FAIL"]
    assert "abbreviates 'Pat Q Example'" in _mirror_check(report, "page2.name").detail
    assert _mirror_check(report, "page3.name").detail.startswith("page-header mirror 'page3.name' repeats 'P. Example'")
    blank_check = _mirror_check(verify_form(pack, _dump(pack, PERSON), widgets=_widgets(pack, "", NARROW)), "page2.name")
    assert blank_check.status == "FAIL"
    assert "is BLANK but must repeat 'P Q Example'" in blank_check.detail  # the value fill_form would write
    assert (f"'Pat Q Example' does not fit its box ({TOO_WIDE}), so write 'P Q Example', the abbreviation the pack's "
            f"mirror_abbreviations allow ({RULE}) that fits: refill with fill_form: it fills the mirrors you leave out "
            f"(or pass 'page2.name': 'P Q Example'), then re-verify") in blank_check.detail


def test_jk28_a_blank_mirror_its_box_cannot_hold_is_skipped_to_hand_write_not_sent_back(tmp_path: Path):
    # fill_form leaves a mirror blank when its box cannot hold the value (here its maxlen); verify must not send the
    # agent back to fill_form or to passing that same value, which would loop (Phase K JK28, 2026-10-16): the header
    # is SKIPPED with the hand-write instruction, and ok holds.
    fields = [dict(f, maxlen=12) if f["line"] == "page2.name" else f for f in FIELDS]
    pack = _pack(fields=fields)
    out = tmp_path / "long.pdf"
    result = fill_form(pack, {**PERSON, "filing_status.single": True}, _blank(pack, tmp_path / "blank.pdf"), out)
    assert any("mirror line 'page2.name' left blank" in w for w in result.warnings)
    report = verify_form(pack, out)
    check = _mirror_check(report, "page2.name")
    assert check.status == "SKIPPED"
    assert check.detail == (
        "page-header mirror 'page2.name' is blank: its box cannot hold 'Pat Q Example' (13 characters, and the box "
        "takes at most 12), so fill_form leaves it blank — hand-write it in the box after printing (this check cannot "
        "read handwriting)"
    )
    assert report.ok, [c.detail for c in report.identity if c.status == "FAIL"]

    # With the pack's abbreviation rule, fill_form writes the first abbreviation within the maxlen, and it verifies.
    pack = _pack(fields=fields, mirror_abbreviations=ABBREVIABLE)
    fixed = tmp_path / "fixed.pdf"
    fill_form(pack, {**PERSON, "filing_status.single": True}, _blank(pack, tmp_path / "blank2.pdf"), fixed)
    assert _on_disk(pack, fixed)["page2.name"] == "P Q Example"
    report = verify_form(pack, fixed)
    assert report.ok and _mirror_check(report, "page2.name").status == "PASS"


@pytest.mark.parametrize(("source", "reason"), [
    ("12A", "the box refuses that value (a comb box takes digits only)"),
    ("NRA", "the box refuses that value ('NRA' never goes in an identifying-number or comb box, P-026)"),
])
def test_jk28_a_comb_mirror_the_box_refuses_names_the_rule(source: str, reason: str):
    fields = [*FIELDS, {"line": "spouse.tin_text", "field": "p1_sp_tin", "type": "text"},
              {"line": "page2.spouse_tin", "field": "p2_sp_tin", "type": "text", "maxlen": 9, "comb": True}]
    pack = _pack(fields=fields, mirrors={"page2.spouse_tin": "{spouse.tin_text}"})
    (check,) = mirror_checks(pack, _dump(pack, {"spouse.tin_text": source}))
    assert check.status == "FAIL" and reason in check.detail
    assert "so fill_form cannot build it and leaves it blank" in check.detail


def test_jk28_verify_skips_a_mirror_with_nothing_to_mirror():
    pack = _pack()
    report = verify_form(pack, _dump(pack, {"page2.name": "Pat Example", "page3.name": "Pat Example"}))
    assert _mirror_check(report, "page3.name").status == "PASS"  # it repeats page2.name, which holds a value
    check = _mirror_check(report, "page2.name")
    assert check.status == "SKIPPED" and "nothing to mirror" in check.detail
    assert "the box holds 'Pat Example', which no line of this form backs" in check.detail
    assert report.ok  # SKIPPED is visible, never fatal


def test_jk28_verify_filing_checks_each_items_mirrors_under_its_form_key():
    pack = _pack()
    good = _dump(pack, {**PERSON, "identifying_number": "999880101", "page2.name": "Pat Q Example",
                        "page3.name": "Pat Q Example", "page2.ssn_area": "999", "page2.ssn_group": "88",
                        "page2.ssn_serial": "0101", "page3.last10": "Example"})
    ok = verify_filing([FilingItem(form_key="ca540", pack=pack, fields=good)])
    assert {c.status for c in ok.identity if "page-header mirror" in c.field} == {"PASS"}
    bad = verify_filing([FilingItem(form_key="ca540", pack=pack, fields={**good, _qualified(pack, "page2.name"): ""})])
    check = next(c for c in bad.identity if c.field == "ca540: page-header mirror page2.name")
    assert check.status == "FAIL" and "page-header mirror 'page2.name' on ca540 is BLANK" in check.detail
    assert not bad.ok


def test_jk28_p002_does_not_read_an_address_mirror_as_the_return_address():
    fields = [{"line": "name", "field": "p1_name", "type": "text"},
              {"line": "mailing_address.street", "field": "p1_street", "type": "text"},
              {"line": "mailing_address.page2", "field": "p2_street", "type": "text"}]
    pack = _pack(fields=fields, mirrors={"mailing_address.page2": "{mailing_address.street}"})
    report = verify_filing([FilingItem(form_key="m", pack=pack, fields=_dump(pack, {
        "name": "Pat Example", "mailing_address.street": "10 Sample Street", "mailing_address.page2": ""}))])
    assert _mirror_check(report, "mailing_address.page2").status == "FAIL" and not report.ok
    p002 = next(p for p in report.pitfall_checks if p.id == "P-002")
    assert p002.status == "PASS" and "no address identity field declared" in p002.detail


# --- a mirror measured against its box (Phase K JK28, 2026-10-16) --------------------------------------------------


@pytest.mark.parametrize(("width", "written"), [
    (144, "Pat Q Example"),   # 142 pt inside: the full value fits
    (NARROW, "P Q Example"),  # 78 pt inside: 'Pat Q Example' is 80.7 pt, its initials 70.7
    (66, "P Example"),        # 64 pt inside: the initials still overrun, the first initial alone is 58.0 pt
])
def test_jk28_fill_form_writes_the_first_value_its_box_holds(tmp_path: Path, width: float, written: str):
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    out = tmp_path / "filled.pdf"
    blank = _blank(pack, tmp_path / "blank.pdf", {"page2.name": width})
    result = fill_form(pack, {**PERSON, "filing_status.single": True}, blank, out)
    disk = _on_disk(pack, out)
    assert disk["page2.name"] == written and disk["page3.name"] == written  # its own mirror repeats what was written
    assert result.mirrored[:2] == ["page2.name", "page3.name"]
    if written == "Pat Q Example":
        assert result.warnings == []
    else:
        inside = f"the {width - 2:.1f} pt inside its box: {width:.1f} pt wide, less 1 pt on each side"
        assert result.warnings == [
            f"mirror line 'page2.name': 'Pat Q Example' does not fit its box (80.7 pt at Helv 12, wider than {inside}), "
            f"so fill_form wrote {written!r} ({text_width(written, 12):.1f} pt at Helv 12, within {inside}); the "
            f"pack's mirror_abbreviations let this header cut name.first, name.middle_initial and spouse.first to "
            f"initials or leave them out — informational: verify_form accepts it"]
    report = verify_form(pack, out)
    assert report.ok, [c.detail for c in report.identity if c.status == "FAIL"]
    assert _mirror_check(report, "page2.name").status == "PASS"


def test_jk28_a_name_no_allowed_value_fits_is_left_blank_to_hand_write(tmp_path: Path):
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    out = tmp_path / "narrow.pdf"
    result = fill_form(pack, {**PERSON, "filing_status.single": True},
                       _blank(pack, tmp_path / "blank.pdf", {"page2.name": 50}), out)
    disk = _on_disk(pack, out)
    assert disk["page2.name"] == "" and disk["page3.name"] == ""
    assert "page2.name" not in result.mirrored and "page3.name" not in result.mirrored
    inside = "the 48.0 pt inside its box: 50.0 pt wide, less 1 pt on each side"
    cannot = (f"its box cannot hold 'Pat Q Example' (80.7 pt at Helv 12, wider than {inside}), nor the shortest "
              f"abbreviation the pack's mirror_abbreviations allow, 'P Example' (58.0 pt at Helv 12, wider than {inside})")
    assert result.warnings == [
        f"mirror line 'page2.name' left blank: {cannot} — fill_form never writes a header its box would cut off, so "
        f"hand-write it in the box after printing (verify_form does not fail a header left blank for this reason: its "
        f"check is SKIPPED)"]
    report = verify_form(pack, out)
    check = _mirror_check(report, "page2.name")
    assert check.status == "SKIPPED"
    assert check.detail == (f"page-header mirror 'page2.name' is blank: {cannot}, so fill_form leaves it blank — "
                            f"hand-write it in the box after printing (this check cannot read handwriting)")
    assert _mirror_check(report, "page3.name").status == "SKIPPED"  # it repeats the blank header: nothing to mirror
    assert report.ok, [c.detail for c in report.identity if c.status == "FAIL"]

    # Without mirror_abbreviations the full name is the only value to try.
    pack = _pack()
    plain = tmp_path / "plain.pdf"
    result = fill_form(pack, PERSON, _blank(pack, tmp_path / "blank2.pdf", {"page2.name": NARROW}), plain)
    assert _on_disk(pack, plain)["page2.name"] == ""
    assert (f"its box cannot hold 'Pat Q Example' ({TOO_WIDE}), and the pack allows no shorter form of it — "
            in result.warnings[0])
    assert _mirror_check(verify_form(pack, plain), "page2.name").status == "SKIPPED"


def test_jk28_fill_form_measures_the_box_at_its_own_font(tmp_path: Path):
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    name = _qualified(pack, "page2.name")
    # Courier 10 is 0.6 em a glyph: 'Pat Q Example' is 78.0 pt, its ink past the 76 pt inside a 78 pt box, where
    # Helvetica 10 (67.2 pt) would fit.
    courier = _set_da(_blank(pack, tmp_path / "courier.pdf", {"page2.name": 78}), name, "/Cour 10 Tf 0 g",
                      ("Cour", "Courier"))
    result = fill_form(pack, PERSON, courier, tmp_path / "c.pdf")
    assert _on_disk(pack, tmp_path / "c.pdf")["page2.name"] == "P Q Example"
    assert "(78.0 pt at Cour 10, wider than the 76.0 pt inside its box: 78.0 pt wide" in result.warnings[0]
    assert _mirror_check(verify_form(pack, tmp_path / "c.pdf"), "page2.name").status == "PASS"
    # A /DA font the blank's /DR does not carry: pypdf draws it in Helvetica and writes /Helvetica into the /DA, so
    # fill_form measures Helvetica (67.2 pt fits) and verify, reading that /DA back, agrees.
    bare = _set_da(_blank(pack, tmp_path / "bare.pdf", {"page2.name": 78}), name, "/Cour 10 Tf 0 g")
    result = fill_form(pack, PERSON, bare, tmp_path / "b.pdf")
    assert _on_disk(pack, tmp_path / "b.pdf")["page2.name"] == "Pat Q Example" and result.warnings == []
    check = _mirror_check(verify_form(pack, tmp_path / "b.pdf"), "page2.name")
    assert check.status == "PASS" and "(67.2 pt at Helvetica 10, within the 76.0 pt inside its box" in check.detail
    # An auto-size box never cuts (the viewer shrinks the text): the full name, however narrow the box.
    auto = _set_da(_blank(pack, tmp_path / "auto.pdf", {"page2.name": 40}), name, "/Helv 0 Tf 0 g")
    result = fill_form(pack, PERSON, auto, tmp_path / "a.pdf")
    assert _on_disk(pack, tmp_path / "a.pdf")["page2.name"] == "Pat Q Example" and result.warnings == []
    check = _mirror_check(verify_form(pack, tmp_path / "a.pdf"), "page2.name")
    assert check.status == "PASS" and "(an auto-size box (/DA 0 Tf): the viewer shrinks the text to fit)" in check.detail


def test_jk28_a_comb_mirror_is_not_measured_by_its_width(tmp_path: Path):
    """A comb box prints one character a cell across its width: its maxlen and digits-only rules govern it, so a
    narrow comb mirror is still written whole and verifies (four Helv 12 digits advance 26.7 pt; this box is 20)."""
    pack = _pack()
    out = tmp_path / "comb.pdf"
    result = fill_form(pack, {**PERSON, "filing_status.single": True},
                       _blank(pack, tmp_path / "blank.pdf", {"page2.ssn_serial": 20}), out)
    assert _on_disk(pack, out)["page2.ssn_serial"] == "0101" and "page2.ssn_serial" in result.mirrored
    assert result.warnings == []
    check = _mirror_check(verify_form(pack, out), "page2.ssn_serial")
    assert check.status == "PASS" and check.detail == (
        "page-header mirror 'page2.ssn_serial' repeats '0101', as its template '{identifying_number[5:]}' builds it")


def test_jk28_verify_fails_a_caller_header_its_box_cuts_off(tmp_path: Path):
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    out = tmp_path / "cut.pdf"
    result = fill_form(pack, {**PERSON, "filing_status.single": True, "page2.name": "Pat Q Example"},
                       _blank(pack, tmp_path / "blank.pdf", {"page2.name": NARROW}), out)
    assert result.warnings == [] and "page2.name" not in result.mirrored  # written as given; verify measures it
    report = verify_form(pack, out)
    check = _mirror_check(report, "page2.name")
    assert check.status == "FAIL" and not report.ok
    assert check.detail == (
        f"page-header mirror 'page2.name' holds 'Pat Q Example', which its box cuts off ({TOO_WIDE}) — write "
        f"'P Q Example', the abbreviation the pack's mirror_abbreviations allow ({RULE}) that fits: refill with "
        f"fill_form, leaving 'page2.name' out (fill_form fills the mirrors you leave out) or passing exactly "
        f"'P Q Example', then re-verify")
    # In a filing, each item is measured against the widgets of its own PDF.
    filing = verify_filing([FilingItem(form_key="ca540", pack=pack, pdf_path=out)])
    check = next(c for c in filing.identity if c.field == "ca540: page-header mirror page2.name")
    assert check.status == "FAIL" and not filing.ok
    assert check.detail.startswith("page-header mirror 'page2.name' on ca540 holds 'Pat Q Example', which its box cuts")


def test_jk28_verify_fails_an_allowed_abbreviation_its_box_still_cuts_off(tmp_path: Path):
    """Phase K JK28 (2026-10-23): an abbreviation the pack allows, needed because the full name does not fit, still
    FAILs when its box cuts it off too: a cut-off header never passes verify, abbreviated or not."""
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    person = {**PERSON, "name.last": "Wolfeschlegelsteinhausen"}
    header = "P Wolfeschlegelsteinhausen"
    out = tmp_path / "cut.pdf"
    result = fill_form(pack, {**person, "filing_status.single": True, "page2.name": header},
                       _blank(pack, tmp_path / "blank.pdf", {"page2.name": NARROW, "page3.name": 400}), out)
    assert result.warnings == [] and "page2.name" not in result.mirrored  # written as given; verify measures it
    report = verify_form(pack, out)
    assert _mirror_check(report, "page3.name").status == "PASS"  # the wide page-3 box repeats it whole
    check = _mirror_check(report, "page2.name")
    assert check.status == "FAIL" and not report.ok, check.detail
    width = text_width(header, 12)
    assert check.detail.startswith(
        f"page-header mirror 'page2.name' holds {header!r}, an abbreviation of 'Pat Q Wolfeschlegelsteinhausen' "
        f"(its template '{NAME_TEMPLATE}') that the pack's mirror_abbreviations allow ({RULE}), which its box still "
        f"cuts off ({width:.1f} pt at Helv 12, wider than the 78.0 pt inside its box"), check.detail


def test_jk28_verify_without_widgets_cannot_measure_a_header():
    """A field dump carries no widget geometry: the full value passes and says so; an abbreviation is SKIPPED."""
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    unmeasured = "no single-line widget of the field with a width and a font size to measure"
    full = _mirror_check(verify_form(pack, _dump(pack, {**PERSON, "page2.name": "Pat Q Example"})), "page2.name")
    assert full.status == "PASS" and full.detail.endswith(f"(its width was not measured: {unmeasured})")
    short = _mirror_check(verify_form(pack, _dump(pack, {**PERSON, "page2.name": "P Q Example"})), "page2.name")
    assert short.status == "SKIPPED"
    assert (f"whether 'Pat Q Example' fits its box was not measured ({unmeasured}), so this check cannot tell whether "
            f"the abbreviation was needed") in short.detail
    filing = verify_filing([FilingItem(form_key="ca540", pack=pack,
                                       fields=_dump(pack, {**PERSON, "page2.name": "P Q Example"}))])
    assert next(c for c in filing.identity if c.field == "ca540: page-header mirror page2.name").status == "SKIPPED"


def test_jk28_fill_form_and_verify_agree_on_every_box_width(tmp_path: Path):
    """Whatever the box, verify expects exactly what fill_form wrote: PASS when it wrote a value, SKIPPED when it left
    the header blank, never FAIL. And fill_form wrote the longest rung that fits, by overlay's own widths: since Phase
    K JEe, a rung fits when its ink (its advance less the last glyph's right side bearing) ends within the box less
    1 pt a side, give or take textfit.CUT_TOLERANCE_PT."""
    pack = _pack(mirror_abbreviations=ABBREVIABLE)
    ladder = mirror_ladder(NAME_TEMPLATE, PERSON, ABBREVIABLE["page2.name"])
    assert ladder == ["Pat Q Example", "P Q Example", "P Example"]
    seen = set()
    for width in range(40, 100, 4):
        out = tmp_path / f"w{width}.pdf"
        fill_form(pack, {**PERSON, "filing_status.single": True},
                  _blank(pack, tmp_path / f"b{width}.pdf", {"page2.name": width}), out)
        written = _on_disk(pack, out)["page2.name"]
        box = WidgetBox(float(width), 12.0, "Helv", False, False, 1.0, 0, False)
        holds = [rung for rung in ladder if ink_overrun(rung, box) <= CUT_TOLERANCE_PT]
        assert written == (holds[0] if holds else ""), width
        assert _mirror_check(verify_form(pack, out), "page2.name").status == ("PASS" if written else "SKIPPED"), width
        seen.add(written)
    assert seen == {"", "P Example", "P Q Example", "Pat Q Example"}


# --- the CA pilot ---------------------------------------------------------------------------------------------------


def test_jk28_every_ca_540_pack_declares_its_sides_2_6_header_mirrors():
    assert len(CA_PACKS) == 6, CA_PACKS
    for path in CA_PACKS:
        pack = load_pack(path)
        assert pack.mirrors == {
            "name.full": "{name.first} {name.middle_initial} {name.last} {name.suffix}",  # "Your name:"
            "identifying_number.page6": "{identifying_number}",                         # "Your SSN or ITIN:"
        }, path
        # a name too wide for the box may shorten the first name and the middle initial (the booklets give no rule);
        # the last name and the suffix stay whole ("JR" has no initial; Phase K JK28, 2026-10-16)
        assert pack.mirror_abbreviations == {"name.full": ["name.first", "name.middle_initial"]}, path


def _header_values(pdf: Path, names: tuple[str, ...]) -> dict[int, dict[str, str]]:
    """Page number -> {field: value} for the widgets of ``names`` on each page (the value lives on the field)."""
    out: dict[int, dict[str, str]] = {}
    for number, page in enumerate(PdfReader(str(pdf)).pages, 1):
        for ref in page.get("/Annots") or []:
            node = widget = ref.get_object()
            parts, value = [], None
            while node is not None:
                if node.get("/T"):
                    parts.append(str(node["/T"]))
                if value is None and node.get("/V") is not None:
                    value = str(node["/V"])
                node = node["/Parent"].get_object() if node.get("/Parent") is not None else None
            name = ".".join(reversed(parts))
            if widget.get("/Subtype") == "/Widget" and name in names:
                out.setdefault(number, {})[name] = value or ""
    return out


@pytest.mark.network
@pytest.mark.parametrize("pack_path", CA_PACKS, ids=lambda p: f"{p.parts[-3]}_{p.parts[-2]}")
def test_jk28_a_ca_540_filled_with_a_name_and_ssn_only_carries_them_on_sides_2_6(pack_path: Path, tmp_path: Path):
    """The JK5 walkthrough's defect, on the real blanks: Side 1 alone now fills and verifies the Sides 2-6 headers."""
    from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank  # noqa: PLC0415

    pack = load_pack(pack_path)
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    side1 = next(f for f in pack.fields if f.line == "identifying_number")
    ssn = "999-88-0503" if side1.maxlen is None or side1.maxlen >= 11 else "999880503"  # 2024 540: /MaxLen 9
    out = tmp_path / f"{pack_path.parts[-3]}_{pack_path.parts[-2]}.pdf"
    result = fill_form(pack, {"name.first": "Riley", "name.last": "Example", "identifying_number": ssn}, blank, out)
    assert result.mirrored == ["name.full", "identifying_number.page6"] and result.warnings == []

    by_line = {f.line: f.field for f in pack.fields}
    name_field, ssn_field = by_line["name.full"], by_line["identifying_number.page6"]
    headers = _header_values(out, (name_field, ssn_field))
    assert sorted(headers) == [2, 3, 4, 5, 6], headers  # one widget of each field on every one of Sides 2-6
    assert all(page == {name_field: "Riley Example", ssn_field: ssn} for page in headers.values()), headers

    report = verify_form(pack, out)
    assert [(c.field, c.status) for c in report.identity] == [
        ("page-header mirror name.full", "PASS"), ("page-header mirror identifying_number.page6", "PASS")]
    assert not [c for c in report.clipping if c.status == "FAIL"]


LONG_NAME = {"name.first": "BARTHOLOMEW", "name.middle_initial": "Q", "name.last": "EXAMPLE-SAMPLE"}  # 183.9 pt


def _ca_blank(pack_path: Path) -> tuple[FormPack, Path]:
    from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank  # noqa: PLC0415

    pack = load_pack(pack_path)
    try:
        return pack, fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")


def _ca_ssn(pack: FormPack) -> str:
    side1 = next(f for f in pack.fields if f.line == "identifying_number")
    return "999-88-0503" if side1.maxlen is None or side1.maxlen >= 11 else "999880503"  # 2024 540: /MaxLen 9


@pytest.mark.network
@pytest.mark.parametrize("pack_path", CA_PACKS, ids=lambda p: f"{p.parts[-3]}_{p.parts[-2]}")
def test_jk28_a_long_ca_540_name_fills_abbreviated_and_verifies(pack_path: Path, tmp_path: Path):
    """A name too wide for the Sides 2-6 "Your name:" box, on every real blank (Phase K JK28, 2026-10-16).

    fill_form writes the abbreviation the pack allows, with an informational warning, and the fill verifies; a header
    that cuts the last name still FAILs, naming the value to write.
    """
    pack, blank = _ca_blank(pack_path)
    values = {**LONG_NAME, "identifying_number": _ca_ssn(pack), "filing_status.single": True}
    name_field = next(f.field for f in pack.fields if f.line == "name.full")

    built = tmp_path / "built.pdf"
    result = fill_form(pack, values, blank, built)
    assert result.mirrored == ["name.full", "identifying_number.page6"]
    (warning,) = result.warnings
    assert warning.startswith("mirror line 'name.full': 'BARTHOLOMEW Q EXAMPLE-SAMPLE' does not fit its box (183.9 pt "
                              "at Helv 10, wider than the ")
    assert "so fill_form wrote 'B Q EXAMPLE-SAMPLE' (111.2 pt at Helv 10, within the " in warning
    headers = _header_values(built, (name_field,))
    assert sorted(headers) == [2, 3, 4, 5, 6] and all(h == {name_field: "B Q EXAMPLE-SAMPLE"} for h in headers.values())
    report = verify_form(pack, built)
    assert report.ok, [c.detail for section in (report.identity, report.clipping) for c in section if c.status == "FAIL"]
    check = next(c for c in report.identity if c.field == "page-header mirror name.full")
    assert check.status == "PASS" and "as 'B Q EXAMPLE-SAMPLE'" in check.detail

    cut = tmp_path / "cut.pdf"
    fill_form(pack, {**values, "name.full": "BARTHOLOMEW Q EXAMPLE"}, blank, cut)
    check = next(c for c in verify_form(pack, cut).identity if c.field == "page-header mirror name.full")
    assert check.status == "FAIL" and "so write 'B Q EXAMPLE-SAMPLE'" in check.detail
    assert "name.last and name.suffix whole" in check.detail


CA_540_2025 = REPO / "formpacks" / "states" / "ca" / "2025" / "form540" / "pack.yaml"
NARROWEST_540 = "the 123.9 pt inside the narrowest of its 5 widgets: 125.9 pt wide, less 1 pt on each side"
CA_RULE = "name.first and name.middle_initial shortened to an initial or left out, name.last and name.suffix whole"


@pytest.mark.network
def test_jk28_a_ca_name_too_wide_for_the_header_is_abbreviated_on_sides_2_6(tmp_path: Path):
    """The round-2 major, on the real 2025 Form 540: 'ALEXANDRA Q WASHINGTON' printed cut off ('ALEXANDRA Q
    WASHINGT'), fill_form said nothing, and verify passed it (Phase K JK28, 2026-10-16)."""
    pack, blank = _ca_blank(CA_540_2025)
    out = tmp_path / "alexandra.pdf"
    result = fill_form(pack, {"name.first": "ALEXANDRA", "name.middle_initial": "Q", "name.last": "WASHINGTON",
                              "identifying_number": "999-88-0503", "filing_status.single": True}, blank, out)
    assert result.mirrored == ["name.full", "identifying_number.page6"]
    assert result.warnings == [
        f"mirror line 'name.full': 'ALEXANDRA Q WASHINGTON' does not fit its box (142.8 pt at Helv 10, wider than "
        f"{NARROWEST_540}), so fill_form wrote 'A Q WASHINGTON' (88.9 pt at Helv 10, within {NARROWEST_540}); the "
        f"pack's mirror_abbreviations let this header cut name.first and name.middle_initial to initials or leave "
        f"them out — informational: verify_form accepts it"]
    headers = _header_values(out, ("540_form_2001",))
    assert sorted(headers) == [2, 3, 4, 5, 6] and all(h == {"540_form_2001": "A Q WASHINGTON"} for h in headers.values())
    report = verify_form(pack, out)
    assert report.ok, [c.detail for section in (report.identity, report.clipping) for c in section if c.status == "FAIL"]
    check = next(c for c in report.identity if c.field == "page-header mirror name.full")
    assert check.status == "PASS"
    assert (f"as 'A Q WASHINGTON', which the pack's mirror_abbreviations allow ({CA_RULE}): 'ALEXANDRA Q WASHINGTON' "
            f"does not fit its box (142.8 pt at Helv 10, wider than {NARROWEST_540})") in check.detail


@pytest.mark.network
@pytest.mark.parametrize(("name", "header", "status", "says"), [
    (("RILEY", "", "EXAMPLE"), None, "PASS", "repeats 'RILEY EXAMPLE'"),
    (("RILEY", "", "EXAMPLE"), "R EXAMPLE", "FAIL", "but 'RILEY EXAMPLE' fits its box (78.9 pt at Helv 10, within"),
    (("RILEY", "", "EXAMPLE"), "EXAMPLE", "FAIL", "but 'RILEY EXAMPLE' fits its box (78.9 pt at Helv 10, within"),
    (("ALEXANDRA", "Q", "WASHINGTON"), "ALEXANDRA Q WASHINGTON", "FAIL",
     f"holds 'ALEXANDRA Q WASHINGTON', which its box cuts off (142.8 pt at Helv 10, wider than {NARROWEST_540}) — "
     f"write 'A Q WASHINGTON', the abbreviation the pack's mirror_abbreviations allow ({CA_RULE}) that fits"),
    (("ALEXANDRA", "Q", "WASHINGTON"), "A. WASHINGTON", "PASS", "as 'A. WASHINGTON'"),
    # Phase K JK28 (2026-10-23): an allowed abbreviation the box still cuts off fails like a cut-off full name
    (("PAT", "", "WOLFESCHLEGELSTEINHAUSEN"), "P WOLFESCHLEGELSTEINHAUSEN", "FAIL",
     f"an abbreviation of 'PAT WOLFESCHLEGELSTEINHAUSEN' (its template '{{name.first}} {{name.middle_initial}} "
     f"{{name.last}} {{name.suffix}}') that the pack's mirror_abbreviations allow ({CA_RULE}), which its box still "
     f"cuts off (169.5 pt at Helv 10, wider than {NARROWEST_540})"),
], ids=["short_name_stays_whole", "initial_although_it_fits", "surname_alone_although_it_fits",
        "caller_header_cut_off", "another_allowed_abbreviation_that_fits", "allowed_abbreviation_still_cut_off"])
def test_jk28_ca_540_header_verdicts_on_the_real_blank(name: tuple[str, str, str], header: str | None, status: str,
                                                       says: str, tmp_path: Path):
    pack, blank = _ca_blank(CA_540_2025)
    first, middle, last = name
    values = {"name.first": first, "name.last": last, "identifying_number": "999-88-0503", "filing_status.single": True}
    values.update({"name.middle_initial": middle} if middle else {})
    values.update({"name.full": header} if header is not None else {})
    out = tmp_path / "header.pdf"
    assert fill_form(pack, values, blank, out).warnings == []  # a name that fits, or a header the caller passed
    report = verify_form(pack, out)
    check = next(c for c in report.identity if c.field == "page-header mirror name.full")
    assert check.status == status and says in check.detail, check.detail
    assert report.ok is (status == "PASS"), [c.detail for c in report.identity if c.status == "FAIL"]


@pytest.mark.network
def test_jk28_a_surname_too_wide_for_the_header_on_its_own_is_left_to_hand_write(tmp_path: Path):
    """No allowed value fits: the Sides 2-6 header stays blank, the warning says to hand-write it, verify SKIPs it."""
    pack, blank = _ca_blank(CA_540_2025)
    out = tmp_path / "surname.pdf"
    result = fill_form(pack, {"name.first": "PAT", "name.last": "EXAMPLESON-SAMPLEWORTH",  # 150.6 pt alone
                              "identifying_number": "999-88-0503", "filing_status.single": True}, blank, out)
    assert result.mirrored == ["identifying_number.page6"]
    assert result.warnings == [
        f"mirror line 'name.full' left blank: its box cannot hold 'PAT EXAMPLESON-SAMPLEWORTH' (172.8 pt at Helv 10, "
        f"wider than {NARROWEST_540}), nor the shortest abbreviation the pack's mirror_abbreviations allow, "
        f"'P EXAMPLESON-SAMPLEWORTH' (160.0 pt at Helv 10, wider than {NARROWEST_540}) — fill_form never writes a "
        f"header its box would cut off, so hand-write it in the box after printing (verify_form does not fail a header "
        f"left blank for this reason: its check is SKIPPED)"]
    headers = _header_values(out, ("540_form_2001", "540_form_2002"))
    assert sorted(headers) == [2, 3, 4, 5, 6]
    assert all(h == {"540_form_2001": "", "540_form_2002": "999-88-0503"} for h in headers.values()), headers
    report = verify_form(pack, out)
    check = next(c for c in report.identity if c.field == "page-header mirror name.full")
    assert check.status == "SKIPPED" and check.detail.endswith(
        "so fill_form leaves it blank — hand-write it in the box after printing (this check cannot read handwriting)")
    assert report.ok, [c.detail for section in (report.identity, report.clipping) for c in section if c.status == "FAIL"]


@pytest.mark.network
@pytest.mark.parametrize(("pack_dir", "written"), [
    ("2025/form540", "M Q EXAMPLESON"),         # 123.9 pt inside its narrowest widget; the name is 127.3 pt
    ("2024/form540nr", "MORGAN Q EXAMPLESON"),  # 128.9 pt inside its 130.9 pt widgets: it fits whole
    ("2025/form540nr", "MORGAN Q EXAMPLESON"),  # 130.9-131.4 pt
])
def test_jk28_the_540nr_header_holds_a_name_the_540_header_cannot(pack_dir: str, written: str, tmp_path: Path):
    pack, blank = _ca_blank(REPO / "formpacks" / "states" / "ca" / pack_dir / "pack.yaml")
    out = tmp_path / "morgan.pdf"
    result = fill_form(pack, {"name.first": "MORGAN", "name.middle_initial": "Q", "name.last": "EXAMPLESON",
                              "identifying_number": _ca_ssn(pack), "filing_status.single": True}, blank, out)
    name_field = next(f.field for f in pack.fields if f.line == "name.full")
    assert {h[name_field] for h in _header_values(out, (name_field,)).values()} == {written}
    assert len(result.warnings) == (0 if written == "MORGAN Q EXAMPLESON" else 1), result.warnings
    report = verify_form(pack, out)
    assert report.ok, [c.detail for section in (report.identity, report.clipping) for c in section if c.status == "FAIL"]


# --- every pack that declares mirrors, on its real blank (Phase K JK28 sweep, 2026-10-23) --------------------------

MIRROR_PACKS = sorted(path for path in (REPO / "formpacks").glob("**/pack.yaml") if load_pack(path).mirrors)
DEMO_SSN = "999880507"


def _demo_identity(field) -> str | None:
    """A demo value for an identity source line, shaped as the line takes it (None: leave the line out).

    The SSN goes in as 999-88-0507 where the box takes dashes, as its nine digits on a comb, ssn_digits_only or
    9-character line, and digit by digit (or 3-2-4) across the cells a form splits it into; names are demo names.
    """
    line = field.line.lower()
    spouse = "spouse" in line
    if re.search(r"ssn|identifying_number", line):
        cell = re.search(r"_d0([1-9])$", line)  # NJ-1040's nine page-1 cells
        if cell:
            return DEMO_SSN[int(cell.group(1)) - 1]
        if field.maxlen in (2, 3, 4):  # a 3-2-4 split: f8863's area / group / serial, WI's first3 / mid2 / last4
            return {3: "999", 2: "88", 4: "0507"}[field.maxlen]
        if field.comb or field.format == "ssn_digits_only" or (field.maxlen is not None and field.maxlen < 11):
            return DEMO_SSN
        return "999-88-0507"
    if "suffix" in line:  # GA's Schedule 4 "SUFFIX" copy repeats tp_suffix alone, so a blank one would test nothing
        return "JR"
    if "middle" in line or re.search(r"(^|[._])mi$", line):
        return "M" if spouse else "Q"
    if "last_first_initial" in line:  # NJ-1040's one "Last Name, First Name, Initial" box
        return "EXAMPLE, PAT Q"
    if "first" in line:
        return "RILEY" if spouse else "PAT"
    if "last" in line:
        return "EXAMPLE"
    if line == "name" or line.endswith("name"):
        return "PAT Q EXAMPLE"
    raise AssertionError(f"no demo value for identity source line {field.line!r}: extend _demo_identity")


# Packs whose headers the JK28 follow-ups declared (Phase K JK28, 2026-10-23), each with the mirrors it must carry:
# the network test below fills them with page-1 identity alone and verifies them clean.
HEADER_FOLLOW_UP_MIRRORS = {
    "states/ga/2023/ga500": {"tp_ssn_page_header"},
    "states/al/2023/al40nr": {"NAME", "SSSNB", "SCHDSNAME", "SCHDSSSN", "SCHOCNAME", "SCHOCSSN", "SSSNB7A"},
    "states/de/2024/pit_res": {"header.name", "header.taxpayer_id"},
    "states/de/2025/pit_res": {"header.name", "header.taxpayer_id"},
    "states/ia/2023/ia1040": {"header.name"},
    "states/ia/2024/ia1040": {"header.name"},
    "states/ia/2025/ia1040": {"header.name"},
    "states/co/2023/dr0104": {"header_name"},
    # AL Form 40's schedule headers (Phase K JK28 final review, 2026-10-23), the boxes al40nr already declared.
    **{f"states/al/{year}/al40": {"SCHANAME", "SCHASSN", "SCHDSNAME", "SCHDSSSN", "SCHDSSPSSN", "SCHOCNAME",
                                  "SCHOCSSN", "SCHENAME", "4952ASSN"} for year in (2023, 2024, 2025)},
}


def test_jk28_the_header_follow_up_packs_are_in_the_network_fill():
    by_key = {"/".join(p.parts[-5:-1]): p for p in MIRROR_PACKS}
    for key, lines in HEADER_FOLLOW_UP_MIRRORS.items():
        assert key in by_key, f"{key} declares no mirrors, so the network fill below skips it"
        assert lines <= set(load_pack(by_key[key]).mirrors), (key, sorted(lines - set(load_pack(by_key[key]).mirrors)))
    assert "PG2NAME" not in load_pack(by_key["states/al/2023/al40nr"]).mirrors  # "Do not enter ... if shown on other side"
    for year in (2023, 2024, 2025):  # page 4 and Schedule HOF print the same "Do not enter ..." on Form 40
        declared = set(load_pack(by_key[f"states/al/{year}/al40"]).mirrors)
        assert not declared & {"NAME2A", "SSSNB2A", "SCHHOFNAME", "SCHHOFSSN", "SCHHOFSPSSN"}, year


@pytest.mark.network
@pytest.mark.parametrize("pack_path", MIRROR_PACKS, ids=lambda p: "-".join(p.parts[-4:-1]))
def test_jk28_every_declared_mirror_is_built_from_its_page_1_lines_and_verifies(pack_path: Path, tmp_path: Path):
    """Fill only the page-1 identity lines every mirror reads; each mirror is built (or left blank with a fit
    warning) and verify_form's identity section has no FAIL — on every pack that declares mirrors."""
    from taxfill_core.filler import rehearsal_only  # noqa: PLC0415

    pack, blank = _ca_blank(pack_path)  # loads the pack and its cached blank (skips when neither is reachable)
    by_line = {f.line: f for f in pack.fields}
    sources = {s for template in pack.mirrors.values() for s in mirror_sources(template)} - set(pack.mirrors)
    values = {line: value for line in sorted(sources) if (value := _demo_identity(by_line[line])) is not None}
    assert not set(values) & set(pack.mirrors)
    rehearsal = rehearsal_only(pack)  # a TY2026 draft pack fills and verifies only as a rehearsal
    out = tmp_path / "identity.pdf"
    result = fill_form(pack, values, blank, out, rehearsal=rehearsal)

    for mirror in pack.mirrors:
        assert mirror in result.mirrored or any(w.startswith(f"mirror line '{mirror}' left blank") for w in
                                                result.warnings), (mirror, result.mirrored, result.warnings)
    report = verify_form(pack, out, rehearsal=rehearsal)
    checks = {c.field: c for c in report.identity if c.field.startswith("page-header mirror ")}
    assert set(checks) == {f"page-header mirror {m}" for m in pack.mirrors}, sorted(checks)
    assert not [c for c in report.identity if c.status == "FAIL"], [
        c.detail for c in report.identity if c.status == "FAIL"]
