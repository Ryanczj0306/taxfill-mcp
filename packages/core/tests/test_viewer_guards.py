"""Phase J JEd — P-027: what the filler writes shows and prints; a DOR's viewer guards do not.

A blank built for Adobe Reader shows and hides widgets from its own JavaScript, which taxfill never runs.
OH IT 1040's MFS spouse SSN and every AL Form 40 data widget ship Hidden; AL 40 covers each page with a
yellow "PLEASE USE A DIFFERENT PDF VIEWER" pushbutton and a white NoView + Print "print lid", MO-1040 with a
white ReadOnly panel. fill_form's flag pass does the viewer's work; verify_form reads the flags back (P-027).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pdf_fixtures import make_acroform_pdf
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject

from taxfill_core.filler import F_HIDDEN, F_NOVIEW, F_PRINT, fill_form, is_viewer_guard, visible_box
from taxfill_core.schemas.formpack import FormPack, PackField
from taxfill_core.verify import verify_form, widget_flag_problems

PACK = FormPack.model_validate({
    "form": "GUARDED-1", "jurisdiction": "federal", "tax_year": 2023,
    "source_url": "https://www.irs.gov/pub/irs-pdf/guarded1.pdf", "pdf_sha256": "...", "acroform_root": "",
    "fields": [
        {"line": "spouse_ssn", "field": "spouse_ssn", "type": "text", "maxlen": 9, "comb": True, "format": "ssn_digits_only"},
        {"line": "name", "field": "name", "type": "text", "maxlen": 30},
        {"line": "amended", "field": "amended", "type": "checkbox", "on_state": "/Yes"},
        {"line": "statement", "field": "statement", "type": "text"},
    ],
})
VALUES = {"spouse_ssn": "123456780", "amended": "yes", "name": "Tess Taxpayer"}
PUSHBUTTON = 1 << 16
READONLY = 1


def _widget(doc, name: str) -> DictionaryObject:
    for page in doc.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            if annot.get("/T") == name:
                return annot
    raise AssertionError(f"widget {name!r} not found")


def _flags(pdf: Path) -> dict[str, int]:
    reader = PdfReader(str(pdf))
    return {str(a.get_object()["/T"]): int(a.get_object().get("/F", 0))
            for page in reader.pages for a in page.get("/Annots", []) if a.get_object().get("/T") is not None}


def _set_flag(pdf: Path, name: str, flags: int, out: Path) -> Path:
    writer = PdfWriter(clone_from=str(pdf))
    _widget(writer, name)[NameObject("/F")] = NumberObject(flags)
    writer.write(out)
    return out


@pytest.fixture
def guarded_blank(tmp_path: Path) -> Path:
    """A synthetic blank in the AL 40 / MO-1040 / OH IT 1040 shape: hidden data widgets and page-covering guards."""
    plain = make_acroform_pdf(tmp_path / "plain.pdf", [
        {"name": "spouse_ssn", "maxlen": 9, "comb": True},
        {"name": "name", "maxlen": 30},
        {"name": "amended", "kind": "checkbox", "on_value": "/Yes"},
        {"name": "statement", "width": 540, "height": 690},   # 78% of the page, a writable attachment box
    ])
    writer = PdfWriter(clone_from=str(plain))
    page = writer.pages[0]
    _widget(writer, "spouse_ssn")[NameObject("/F")] = NumberObject(F_HIDDEN | F_PRINT)   # OH IT 1040's SP_SSN_SEP shape
    _widget(writer, "amended")[NameObject("/F")] = NumberObject(F_HIDDEN | F_PRINT)
    width, height = float(page.mediabox.width), float(page.mediabox.height)

    def add(name: str, ft: str, ff: int, flags: int, rect: tuple[float, float, float, float]) -> None:
        annot = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject(ft), NameObject("/Ff"): NumberObject(ff), NameObject("/T"): TextStringObject(name),
            NameObject("/F"): NumberObject(flags), NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
            NameObject("/P"): page.indirect_reference,
        })
        ref = writer._add_object(annot)
        page["/Annots"].append(ref)
        writer._root_object["/AcroForm"]["/Fields"].append(ref)

    add("VERCTRL", "/Btn", PUSHBUTTON, F_PRINT, (1, 7, width, height))                  # AL 40: the yellow warning
    add("printlid.1", "/Btn", PUSHBUTTON, F_NOVIEW | F_PRINT, (2, 2, width - 11, height))  # AL 40: the white print lid
    add("PANEL", "/Tx", READONLY, F_NOVIEW | F_PRINT, (3, 5, width - 7, height))         # MO-1040: the ReadOnly panel
    add("GoToSchedule", "/Btn", PUSHBUTTON, F_PRINT, (300, 700, 400, 712))               # a navigation button: not a guard
    out = tmp_path / "guarded.pdf"
    writer.write(out)
    return out


def test_p027_fill_shows_every_written_widget_and_hides_every_guard(guarded_blank: Path, tmp_path: Path):
    before = _flags(guarded_blank)
    assert before["spouse_ssn"] & F_HIDDEN and before["printlid.1"] & F_NOVIEW and before["VERCTRL"] == F_PRINT
    result = fill_form(PACK, VALUES, guarded_blank, tmp_path / "filled.pdf")
    assert sorted(result.guards_hidden) == ["PANEL (page 1)", "VERCTRL (page 1)", "printlid.1 (page 1)"]
    after = _flags(tmp_path / "filled.pdf")
    for written in ("spouse_ssn", "amended", "name"):
        assert not after[written] & (F_HIDDEN | F_NOVIEW) and after[written] & F_PRINT, (written, after[written])
    for guard in ("VERCTRL", "printlid.1", "PANEL"):
        assert after[guard] == F_HIDDEN, (guard, after[guard])
    assert after["statement"] == before["statement"] and after["GoToSchedule"] == before["GoToSchedule"]
    report = verify_form(PACK, tmp_path / "filled.pdf", expected=VALUES)
    (p027,) = [c for c in report.pitfall_checks if c.id == "P-027"]
    assert p027.status == "PASS" and "3 written widget(s)" in p027.detail and report.ok


def test_p027_a_written_widget_left_hidden_fails_verify(guarded_blank: Path, tmp_path: Path):
    fill_form(PACK, VALUES, guarded_blank, tmp_path / "filled.pdf")
    bad = _set_flag(tmp_path / "filled.pdf", "spouse_ssn", F_HIDDEN | F_PRINT, tmp_path / "bad.pdf")
    report = verify_form(PACK, bad, expected=VALUES)
    (p027,) = [c for c in report.pitfall_checks if c.id == "P-027"]
    assert p027.status == "FAIL" and "'spouse_ssn' on page 1 holds a value but is Hidden" in p027.detail
    assert not report.ok
    # without `expected`, the widgets holding a value are the written ones
    assert "'spouse_ssn'" in verify_form(PACK, bad).pitfall_checks[-1].detail


def test_p027_a_guard_left_printable_fails_verify(guarded_blank: Path, tmp_path: Path):
    fill_form(PACK, VALUES, guarded_blank, tmp_path / "filled.pdf")
    bad = _set_flag(tmp_path / "filled.pdf", "printlid.1", F_NOVIEW | F_PRINT, tmp_path / "bad.pdf")
    problems, checked = widget_flag_problems(bad, ["spouse_ssn", "amended", "name"])
    assert checked == 3 and problems == ["viewer guard 'printlid.1' covers page 1 and is still viewable or printable"]
    assert not verify_form(PACK, bad, expected=VALUES).ok


def test_p027_the_guard_rule_is_page_coverage_plus_pushbutton_or_readonly_text(guarded_blank: Path):
    reader = PdfReader(str(guarded_blank))
    page = reader.pages[0]
    box = visible_box(page)
    verdicts = {str(a.get_object()["/T"]): is_viewer_guard(a.get_object(), box) for a in page.get("/Annots", [])}
    assert {k for k, v in verdicts.items() if v} == {"VERCTRL", "printlid.1", "PANEL"}
    assert not verdicts["statement"]        # 78% of the page, but a writable text box
    assert not verdicts["GoToSchedule"]     # a pushbutton, but a small one


def test_p027_a_guard_is_measured_against_the_visible_cropbox(tmp_path: Path):
    """AL Form 40's worksheet pages crop a short window out of a Letter MediaBox; the print lid covers the whole
    window but under a third of the MediaBox. Measured against the MediaBox it stayed printable and the worksheet
    printed blank — the rule measures the visible area (the CropBox) instead."""
    plain = make_acroform_pdf(tmp_path / "plain.pdf", [{"name": "worksheet_line", "maxlen": 12}])
    writer = PdfWriter(clone_from=str(plain))
    page = writer.pages[0]
    width = float(page.mediabox.width)
    window = (12.0, 537.0, width - 9.0, 792.0)          # AL 2023 page 40's CropBox shape
    page[NameObject("/CropBox")] = ArrayObject([FloatObject(v) for v in window])
    lid = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Btn"), NameObject("/Ff"): NumberObject(PUSHBUTTON),
        NameObject("/T"): TextStringObject("printlid.43"), NameObject("/F"): NumberObject(F_NOVIEW | F_PRINT),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (4.0, 530.0, width - 4.0, 792.0)]),
        NameObject("/P"): page.indirect_reference,
    })
    ref = writer._add_object(lid)
    page["/Annots"].append(ref)
    writer._root_object["/AcroForm"]["/Fields"].append(ref)
    blank = tmp_path / "cropped.pdf"
    writer.write(blank)
    page = PdfReader(str(blank)).pages[0]
    media_share = (width - 8.0) * 262.0 / (width * float(page.mediabox.height))
    assert media_share < 0.85, media_share               # the old MediaBox rule would have missed it
    lid_annot = next(a.get_object() for a in page["/Annots"] if a.get_object()["/T"] == "printlid.43")
    assert is_viewer_guard(lid_annot, visible_box(page))
    pack = FormPack(form="X", jurisdiction="states/xx", tax_year=2023, source_url="https://example.gov/x.pdf",
                    pdf_sha256="0" * 64, acroform_root="",
                    fields=[PackField(line="worksheet_line", field="worksheet_line", type="text", maxlen=12)])
    result = fill_form(pack, {"worksheet_line": "1250"}, blank, tmp_path / "filled.pdf")
    assert result.guards_hidden == ["printlid.43 (page 1)"]
    problems, _ = widget_flag_problems(tmp_path / "filled.pdf", ["worksheet_line"])
    assert not problems


def test_p027_is_reported_only_when_the_pdf_itself_is_read():
    report = verify_form(PACK, {"name": "Tess Taxpayer"})
    assert [c.id for c in report.pitfall_checks] == ["P-001", "P-003"]


# ---------------------------------------------------------------------------
# The real blanks the finding came from
# ---------------------------------------------------------------------------


def _blank(pack):
    from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank

    try:
        return fetch_pack_blank(pack)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cache empty and network unreachable: {exc}")


def _dark_share(png: Path) -> float:
    from PIL import Image

    hist = Image.open(png).convert("L").histogram()
    return sum(hist[:160]) / sum(hist)


@pytest.mark.network
def test_p027_al40_hides_its_41_guards_and_its_page_1_renders_the_return(tmp_path: Path):
    from taxfill_core.render import render_pdf
    from taxfill_core.schemas.formpack import load_pack
    from test_formpacks_federal import synthetic_values

    pack = load_pack(Path(__file__).resolve().parents[3] / "formpacks/states/al/2023/al40/pack.yaml")
    result = fill_form(pack, synthetic_values(pack), _blank(pack), tmp_path / "al40.pdf")
    # 42: page 40's lid covers its whole CropBox but a third of its MediaBox (measured against the CropBox since
    # the JS5 AL 2025 port's re-verify; the MediaBox rule hid 41 and left page 40 printing blank)
    assert len(result.guards_hidden) == 42
    assert any(g.endswith("(page 40)") for g in result.guards_hidden)
    assert {g.split(" ")[0].split(".")[0] for g in result.guards_hidden} == {"printlid", "VERCTRL"}
    # Before the pass, page 1 rendered as the yellow warning (dark share 0.046); the return itself is far busier.
    (page1,) = render_pdf(tmp_path / "al40.pdf", tmp_path / "png", dpi=60, pages=[1])
    assert _dark_share(page1.path) > 0.07
    report = verify_form(pack, tmp_path / "al40.pdf", expected=synthetic_values(pack))
    assert [c for c in report.pitfall_checks if c.id == "P-027"][0].status == "PASS"


@pytest.mark.network
def test_p027_mo1040_hides_its_print_lids_and_oh_prints_the_mfs_spouse_ssn(tmp_path: Path):
    from taxfill_core.schemas.formpack import load_pack
    from test_formpacks_federal import synthetic_values

    root = Path(__file__).resolve().parents[3] / "formpacks/states"
    mo = load_pack(root / "mo/2024/mo1040/pack.yaml")
    result = fill_form(mo, synthetic_values(mo), _blank(mo), tmp_path / "mo.pdf")
    assert len(result.guards_hidden) == 32 and all(g.startswith("printlid.") for g in result.guards_hidden)
    oh = load_pack(root / "oh/2024/it1040_oh/pack.yaml")
    line = next(pf.line for pf in oh.fields if pf.field == "SP_SSN_SEP")
    result = fill_form(oh, {line: "123456780"}, _blank(oh), tmp_path / "oh.pdf")
    assert result.guards_hidden == []
    flags = _flags(tmp_path / "oh.pdf")["SP_SSN_SEP"]
    assert not flags & (F_HIDDEN | F_NOVIEW) and flags & F_PRINT
    assert [c for c in verify_form(oh, tmp_path / "oh.pdf", expected={line: "123456780"}).pitfall_checks
            if c.id == "P-027"][0].status == "PASS"


# ---------------------------------------------------------------------------
# P-028: a selected group member clears its separate-field siblings
# ---------------------------------------------------------------------------

GROUP_PACK = FormPack.model_validate({
    "form": "GROUPED-1", "jurisdiction": "federal", "tax_year": 2023,
    "source_url": "https://www.irs.gov/pub/irs-pdf/grouped1.pdf", "pdf_sha256": "...", "acroform_root": "",
    "fields": [
        {"line": "medium.paper", "field": "Paper Return", "type": "checkbox", "on_state": "/1", "group": "medium"},
        {"line": "medium.efile", "field": "Electronically Filed", "type": "checkbox", "on_state": "/1", "group": "medium"},
        {"line": "amended", "field": "Amended", "type": "checkbox", "on_state": "/1"},
    ],
})


@pytest.fixture
def prechecked_blank(tmp_path: Path) -> Path:
    """GA 500's voucher shape: the blank ships 'Paper Return' already ticked."""
    plain = make_acroform_pdf(tmp_path / "plain.pdf", [
        {"name": "Paper Return", "kind": "checkbox", "on_value": "/1"},
        {"name": "Electronically Filed", "kind": "checkbox", "on_value": "/1"},
        {"name": "Amended", "kind": "checkbox", "on_value": "/1"},
    ])
    writer = PdfWriter(clone_from=str(plain))
    paper = _widget(writer, "Paper Return")
    paper[NameObject("/AS")] = NameObject("/1")
    paper[NameObject("/V")] = NameObject("/1")
    out = tmp_path / "prechecked.pdf"
    writer.write(out)
    return out


def _states(pdf: Path) -> dict[str, str]:
    reader = PdfReader(str(pdf))
    return {str(a.get_object()["/T"]): str(a.get_object().get("/AS", "")) for page in reader.pages
            for a in page.get("/Annots", []) if a.get_object().get("/T") is not None}


def test_p028_selecting_a_group_member_clears_a_prechecked_sibling(prechecked_blank: Path, tmp_path: Path):
    assert _states(prechecked_blank)["Paper Return"] == "/1"
    result = fill_form(GROUP_PACK, {"medium.efile": "yes"}, prechecked_blank, tmp_path / "filled.pdf")
    assert result.written == {"Electronically Filed": "/1", "Paper Return": "/Off"}
    states = _states(tmp_path / "filled.pdf")
    assert states["Electronically Filed"] == "/1" and states["Paper Return"] == "/Off"
    assert states["Amended"] == "/Off"                       # not in the group, not touched
    # verify reads one tick on the question
    report = verify_form(GROUP_PACK, tmp_path / "filled.pdf", expected={"medium.efile": "yes"})
    assert report.ok


def test_p028_an_unanswered_group_keeps_the_blank_as_shipped(prechecked_blank: Path, tmp_path: Path):
    # the filler never invents an answer: no member named, nothing written to the group
    result = fill_form(GROUP_PACK, {"amended": "yes"}, prechecked_blank, tmp_path / "filled.pdf")
    assert result.written == {"Amended": "/1"}
    assert _states(tmp_path / "filled.pdf")["Paper Return"] == "/1"
