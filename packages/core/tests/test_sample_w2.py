"""The bundled demo-persona sample W-2 (Phase J JA1 item 3): docs/samples/w2_2025_synthetic.{pdf,png}.

The user guide's walkthrough, docs/dev/ACCEPTANCE.md and docs/dev/DEMO.md hand this file to a new user, so it has to
be what they say it is. extract_document does no OCR (the agent reads the document with its own vision), so the
"reading" here comes from the PDF's text layer, box by box, at the coordinates scripts/make_sample_w2.py printed
each value — then it goes through the same extract_document the MCP tool calls. The PNG is held to the PDF: it is
tagged with the PDF's sha256 and must match a fresh render of it, box by box. That comparison is only meaningful
because the PDF embeds every font it uses (a base-14 font name is drawn with whatever face the host has, so macOS and
Linux renders would differ by more than a one-digit edit), and a test holds the PDF to that.

The walkthrough's figures are the tools' answers on that reading (estimate_refund, calc tax, filing_summary,
file_and_pay, state_scope), and the docs must quote exactly those. All data synthetic: a demo persona (SSN
999-88-xxxx, never issued).
"""
from __future__ import annotations

import hashlib
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from taxfill_core.calc import irs_round, tax_from_taxable_income
from taxfill_core.estimate import IncomeSnapshot, W2Box12, W2Facts, estimate_refund
from taxfill_core.extract import DOC_SPECS, extract_document
from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay
from taxfill_core.filing_summary import filing_summary
from taxfill_core.knowledge import load_knowledge
from taxfill_core.schemas.profile import Profile
from taxfill_core.statescope import state_scope

pdfium = pytest.importorskip("pypdfium2")
Image = pytest.importorskip("PIL.Image")  # dev group (via reportlab)

REPO = Path(__file__).resolve().parents[3]
SAMPLES = REPO / "docs" / "samples"
PDF = SAMPLES / "w2_2025_synthetic.pdf"
PNG = SAMPLES / "w2_2025_synthetic.png"
SOURCE = "docs/samples/w2_2025_synthetic.pdf"
GUIDE = REPO / "docs" / "USER_GUIDE.md"
ACCEPTANCE = REPO / "docs" / "dev" / "ACCEPTANCE.md"
DEMO = REPO / "docs" / "dev" / "DEMO.md"


def _script():
    spec = importlib.util.spec_from_file_location("make_sample_w2", REPO / "scripts" / "make_sample_w2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MAKE = _script()


def _text(textpage, rect) -> str:
    left, bottom, right, top = rect
    return " ".join(textpage.get_text_bounded(left=left, bottom=bottom, right=right, top=top).split())


def _need(path: Path) -> None:
    if not path.is_file():
        pytest.fail(f"{path.relative_to(REPO)} is missing: run `uv run python scripts/make_sample_w2.py`")


def _read_pdf() -> dict[str, str]:
    """The sample's reading, box by box, from the PDF text layer (blank boxes absent)."""
    _need(PDF)
    doc = pdfium.PdfDocument(str(PDF))
    try:
        assert len(doc) == 1
        textpage = doc[0].get_textpage()
        reading = {}
        for key, rects in MAKE.value_areas().items():
            text = " ".join(t for t in (_text(textpage, r) for r in rects) if t)
            if text:
                reading[key] = text
        return reading
    finally:
        doc.close()


# Computed once per module in fixtures (never at import), so a missing sample fails a test with the regenerate hint
# instead of erroring the collection.
@pytest.fixture(scope="module")
def reading() -> dict[str, str]:
    return _read_pdf()


@pytest.fixture(scope="module")
def extracted(reading):
    return extract_document(SOURCE, "W-2", reading, page=1, tax_year=2025)


@pytest.fixture(scope="module")
def fields(extracted):
    return {f.key: f for f in extracted.fields}


def test_the_sample_files_are_committed_small_and_one_page():
    for path in (PDF, PNG):
        _need(path)
        assert path.stat().st_size < 300_000, f"{path.name} is {path.stat().st_size:,} bytes (keep it under 300 KB)"


def test_every_font_is_embedded():
    # A font the PDF only names (Helvetica, Courier, ...) is drawn with the host's face: the PNG check below would
    # then pass on the machine that made the PNG and fail elsewhere (CI runs Linux).
    raw = pytest.importorskip("pypdfium2.raw")
    if not hasattr(raw, "FPDFFont_GetIsEmbedded"):
        pytest.skip("this pypdfium2 has no FPDFFont_GetIsEmbedded")
    _need(PDF)
    doc = pdfium.PdfDocument(str(PDF))
    try:
        texts = list(doc[0].get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]))
        assert texts, "the sample has no text objects"
        bare = [i for i, obj in enumerate(texts) if not raw.FPDFFont_GetIsEmbedded(raw.FPDFTextObj_GetFont(obj.raw))]
        assert bare == [], f"{len(bare)} of {len(texts)} text objects use a font the PDF does not embed"
    finally:
        doc.close()


def test_every_printed_box_reads_back_to_the_scripts_figures(reading):
    # The PDF on disk carries exactly the boxes the script derives TODAY (from the knowledge pack and
    # employee_fica): a changed wage base or FICA rate fails here until the sample is regenerated.
    expected = MAKE.w2_boxes()
    assert reading == expected
    assert MAKE.PERSONA["employee_ssn"].startswith("999-88-")  # the demo range: never issued


def test_the_reading_extracts_with_document_provenance_and_no_gaps(extracted, fields):
    assert extracted.kind == "W-2" and extracted.gaps == [] and extracted.unexpected == []
    assert [f.severity for f in extracted.findings if f.severity != "info"] == []
    expected = {
        "employee_ssn": "999-88-0425", "employer_ein": "00-1234567",
        "employer_name": "Example Tech Corp 500 Demo Plaza Seattle, WA 98000", "employee_name": "Jordan Q. Taxpayer",
        "1": "168100.00", "2": "30487.00", "3": "176100.00", "4": "10918.20", "5": "191500.00", "6": "2776.75",
        "12a": "D 23400.00", "12b": "DD 8400.00", "13_retirement": True, "14a": "RSU 30000.00", "15_state": "WA",
    }
    ok = {k: f.value for k, f in fields.items() if f.status == "ok"}
    assert ok == expected
    # Every other box is blank on the sample and stays blank — never inferred.
    blank = {b.key for b in DOC_SPECS["W-2"].boxes} - set(expected)
    assert {k for k, f in fields.items() if f.status == "missing"} == blank
    for f in extracted.fields:
        assert (f.provenance.kind, f.provenance.file, f.provenance.page) == ("document", SOURCE, 1)


def test_the_boxes_are_internally_consistent(fields):
    pack = load_knowledge("federal", 2025)
    ess = pack.tax.employee_social_security
    box = {k: Decimal(fields[k].value) for k in ("1", "2", "3", "4", "5", "6")}
    deferral = Decimal(fields["12a"].value.split()[1])
    assert box["5"] > ess.ss_wage_base and box["3"] == ess.ss_wage_base  # the cap binds on this sample
    assert box["4"] == (box["3"] * Decimal(str(ess.rate))).quantize(Decimal("0.01"))
    assert box["6"] == (box["5"] * Decimal(str(ess.medicare_rate))).quantize(Decimal("0.01"))
    assert box["5"] < ess.additional_medicare_withholding_threshold  # no 0.9% withholding owed
    assert box["1"] == box["5"] - deferral  # the 401(k) deferral leaves box 1 only
    assert deferral <= pack.contribution_limits.elective_deferral_402g.limit


def test_the_png_is_the_pdf_rendered():
    from PIL import ImageChops, ImageStat

    _need(PDF)
    _need(PNG)
    png = Image.open(PNG)
    assert png.info["Source"] == f"{PDF.name} sha256 {hashlib.sha256(PDF.read_bytes()).hexdigest()}"
    doc = pdfium.PdfDocument(str(PDF))
    try:
        fresh = doc[0].render(scale=2).to_pil().convert("L")
    finally:
        doc.close()
    png = png.convert("L")
    assert png.size == fresh.size == (int(MAKE.PAGE_W * 2), int(MAKE.PAGE_H * 2))
    assert ImageStat.Stat(ImageChops.difference(fresh, png)).mean[0] < 2.0
    for key, rects in MAKE.value_areas().items():  # each value, box by box (a one-digit edit moves a box's mean > 3)
        for left, bottom, right, top in rects:
            area = (int(left * 2), int((MAKE.PAGE_H - top) * 2), int(right * 2), int((MAKE.PAGE_H - bottom) * 2))
            diff = ImageStat.Stat(ImageChops.difference(fresh.crop(area), png.crop(area))).mean[0]
            assert diff < 1.5, f"box {key}: the PNG differs from the PDF there ({diff:.2f})"


# ── The walkthrough (docs/USER_GUIDE.md "Your first return") quotes these tools' answers ──

_USER = {"kind": "user_stated"}
PROFILE = Profile.model_validate({
    "household": {"marital_status": {"value": "unmarried", "provenance": _USER},
                  "filing_status": {"value": "single", "provenance": _USER}},
    "identity": {"us_person": {"value": True, "provenance": _USER}},
    "state_footprint": {2025: {
        "lived": [{"state": "WA", "start": "2025-01-01", "end": "2025-12-31", "provenance": _USER}],
        "worked": [{"state": "WA", "start": "2025-01-01", "end": "2025-12-31", "provenance": _USER}]}},
})


def _w2_facts(fields) -> W2Facts:
    whole = {f"box{k}": irs_round(fields[k].value) for k in ("1", "2", "3", "4", "5", "6")}
    codes = [fields[k].value.split() for k in ("12a", "12b")]
    return W2Facts(employer="Example Tech Corp", **whole,
                   box12=[W2Box12(code=c, amount=irs_round(a)) for c, a in codes])


@pytest.fixture(scope="module")
def walkthrough(fields) -> dict[str, str]:
    est = estimate_refund(PROFILE, 2025, IncomeSnapshot(w2s=[_w2_facts(fields)]))
    assert est.label == "ESTIMATE" and est.low == est.high == est.point
    taxable = next(c.amount for c in est.composition if c.slot == "taxable_income")
    tax = tax_from_taxable_income(taxable, "single", 2025)
    assert next(c.amount for c in est.composition if c.slot == "income_tax") == tax.tax
    manifest = [FilingManifestItem(form="1040", tax_year=2025, jurisdiction="federal", bottom_line=est.point,
                                   state="WA", direct_deposit=True)]
    summary = filing_summary(manifest).items[0]
    mail = file_and_pay(manifest).returns[0]
    wa = state_scope(PROFILE, 2025).states
    assert [(s.state, s.must_file) for s in wa] == [("WA", False)]
    sol = summary.deadline_status.split("open until ~")[1][:10]
    return {
        "wages": f"wages ${irs_round(fields['1'].value):,}",
        "withheld": f"federal tax withheld ${irs_round(fields['2'].value):,}",
        "estimate": f"a refund of about ${est.point:,}",
        "taxable": f"${taxable:,}",
        "tax": f"${tax.tax:,}",
        "headline": summary.headline,
        "sol": sol,
        "address": mail.mailing_address.split("Service, ")[1],
    }


def _section(text: str, start: str, end: str) -> str:
    """The doc's text from heading `start` up to heading `end` (both must be there)."""
    assert start in text and end in text.split(start, 1)[1], f"the doc lost its {start!r} / {end!r} headings"
    return text.split(start, 1)[1].split(end, 1)[0]


def test_the_walkthrough_quotes_the_tools_answers(walkthrough):
    assert walkthrough["headline"] == "Federal 2025: refund $1,076 (direct deposit)"
    assert (walkthrough["sol"], walkthrough["address"]) == ("2029-04-15", "Ogden, UT 84201-0002")
    guide = GUIDE.read_text(encoding="utf-8")
    section = guide.split("## Your first return in ~15 minutes", 1)[1].split("\n## ", 1)[0]
    for name, text in walkthrough.items():
        assert text in section, f"the walkthrough does not quote the {name} figure {text!r}"
    assert "docs/samples/w2_2025_synthetic" in section or "samples/w2_2025_synthetic" in section
    assert "2023" not in section  # the walkthrough left TY2023 behind (Phase J JA1)


# The runbooks' step sections (a historical note elsewhere in the doc may mention 2023).
RUNBOOK_STEPS = {
    ACCEPTANCE: ("## Guided filing", "## Pass criteria"),
    DEMO: ("## Beats", "## Capture notes"),
}


@pytest.mark.parametrize("doc", list(RUNBOOK_STEPS), ids=lambda p: p.name)
def test_the_runbooks_use_the_sample_and_the_same_figures(doc, walkthrough):
    text = doc.read_text(encoding="utf-8")
    assert "samples/w2_2025_synthetic.png" in text
    steps = _section(text, *RUNBOOK_STEPS[doc])
    assert "2023" not in steps
    for name in ("wages", "withheld", "estimate"):
        assert walkthrough[name] in steps, f"{doc.name} does not quote the {name} figure {walkthrough[name]!r}"
