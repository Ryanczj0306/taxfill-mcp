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

from taxfill_core.filler import F_HIDDEN, F_NOVIEW, F_PRINT, fill_form, is_viewer_guard
from taxfill_core.schemas.formpack import FormPack
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
    area = float(page.mediabox.width) * float(page.mediabox.height)
    verdicts = {str(a.get_object()["/T"]): is_viewer_guard(a.get_object(), area) for a in page.get("/Annots", [])}
    assert {k for k, v in verdicts.items() if v} == {"VERCTRL", "printlid.1", "PANEL"}
    assert not verdicts["statement"]        # 78% of the page, but a writable text box
    assert not verdicts["GoToSchedule"]     # a pushbutton, but a small one


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
    assert len(result.guards_hidden) == 41
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
