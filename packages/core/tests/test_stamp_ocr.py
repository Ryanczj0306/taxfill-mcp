"""KG5's stamp, read by OCR on every page (ADR-0002 Open question 5; Phase K JEe2, 2026-10-25).

stamp.stamp_check proves the stamp is in pdfium's text layer and that its glyphs stand out on a print-path render.
This module adds the read the ROADMAP asked for: every page of a pack-less draft (fill_unmapped, JK16's demo form)
and of a rehearsal fill (fill_form's REHEARSAL_STAMP) is rendered through pdfium's print path, annotations and form
fields drawn, at 300 dpi in greyscale, written as a PGM, and handed to the tesseract CLI. The stamp's words must come
back on every page; the same page with the stamp's text stripped from its content stream must not read as stamped.

tesseract is a CI tool, installed on the runner by .github/workflows/ci.yml (apt, tesseract-ocr) before the offline
tests. It is never a runtime dependency of taxfill-core and adds no Python dependency: the bitmap goes to the CLI as a
file. Where it is missing the test FAILS when the CI environment variable is set, and skips elsewhere, saying so.
Demo values only.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import test_stamp as stamp_tests
import test_unmapped_fill as unmapped_tests
from pdf_fixtures import make_acroform_pdf
from pypdf import PdfWriter
from pypdf.generic import RectangleObject

from taxfill_core.filler import REHEARSAL_STAMP, UNMAPPED_STAMP, fill_form
from taxfill_core.schemas.formpack import FormPack

DPI = 300  # the ROADMAP asks for at least 200; the stamp is set as small as 6 pt
_GAP = 2  # stray words tolerated inside the stamp's line, in all
table = unmapped_tests.table  # JK16's passing anchor table, as a fixture here too
ROOT = "topmostSubform[0]"


def _in_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no")


def _find_tesseract() -> str:
    """The tesseract CLI's path; a failure in CI when it is missing, a skip with the reason anywhere else."""
    exe = shutil.which("tesseract")
    if exe is None:
        if _in_ci():
            pytest.fail("the tesseract CLI is not on PATH on this CI runner, so KG5's stamp went unread: "
                        ".github/workflows/ci.yml must install tesseract-ocr (apt) before the offline tests")
        pytest.skip("the tesseract CLI is not installed here (a CI tool, never a taxfill-core dependency): the stamp "
                    "OCR read runs in CI; install tesseract-ocr locally to run it")
    return exe


def _ocr_pages(pdf: bytes | Path, exe: str, work: Path) -> list[str]:
    """Each page's text as tesseract reads a 300 dpi greyscale render of pdfium's print path (form fields drawn)."""
    import pypdfium2 as pdfium  # noqa: PLC0415

    doc = pdfium.PdfDocument(pdf if isinstance(pdf, bytes) else str(pdf))
    texts = []
    try:
        doc.init_forms()  # draw the form fields on the print path, as render_form and stamp_check do
        for index in range(len(doc)):
            bitmap = doc[index].render(scale=DPI / 72, grayscale=True, optimize_mode="print", draw_annots=True,
                                       may_draw_forms=True)
            width, height, stride, buf = bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer)
            image = work / f"page-{index + 1}.pgm"
            image.write_bytes(b"P5\n%d %d\n255\n" % (width, height)
                              + b"".join(buf[row * stride:row * stride + width] for row in range(height)))
            run = subprocess.run([exe, str(image), "stdout", "--dpi", str(DPI), "--psm", "11"],
                                 capture_output=True, text=True, timeout=120, check=False)
            assert run.returncode == 0, f"tesseract failed on page {index + 1}: {run.stderr.strip()}"
            texts.append(run.stdout)
    finally:
        doc.close()
    return texts


def _words(text: str) -> list[str]:
    """OCR noise tolerated: case, and the em dash (read as -, --, an en dash or nothing): words of letters only."""
    return re.findall(r"[A-Z]+", text.upper())


def _reads_as_stamped(text: str, stamp: str) -> bool:
    """The stamp's words, in order, with at most _GAP stray words between them in all (an OCR engine may read a mark
    or a neighbouring word into the line); FILING-GRADE may come back as one word or two."""
    words = _words(text)
    for want in (_words(stamp), _words(stamp.replace("-", ""))):
        for start, word in enumerate(words):
            if word != want[0]:
                continue
            at, gap = start, 0
            for need in want[1:]:
                nxt = next((j for j in range(at + 1, min(len(words), at + 2 + _GAP - gap)) if words[j] == need), None)
                if nxt is None:
                    break
                gap += nxt - at - 1
                at = nxt
            else:
                return True
    return False


def _stripped(pdf: Path, stamp: str) -> bytes:
    """The same PDF with the stamp's text removed from every page's content stream (the drawn text object kept)."""
    first = re.escape(stamp.split()[0].encode())
    writer = PdfWriter(clone_from=str(pdf))
    for page in writer.pages:
        content = page.get_contents()
        content.set_data(re.sub(rb"\(" + first + rb"[^)]*\) Tj", b"() Tj", content.get_data()))
        page.replace_contents(content)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _assert_read_on_every_page(pdf: Path, stamp: str, pages: int, exe: str, work: Path) -> None:
    texts = _ocr_pages(pdf, exe, work)
    assert len(texts) == pages
    unread = [i + 1 for i, text in enumerate(texts) if not _reads_as_stamped(text, stamp)]
    assert not unread, f"OCR did not read {stamp!r} on page(s) {unread}: {[texts[i - 1] for i in unread]}"
    # the negative control: the same pages, the stamp's text stripped, do not read as stamped (nor its first word)
    bare = _ocr_pages(_stripped(pdf, stamp), exe, work)
    stamped = [i + 1 for i, text in enumerate(bare)
               if _reads_as_stamped(text, stamp) or _words(stamp)[0] in _words(text)]
    assert not stamped, f"page(s) {stamped} read as stamped with the stamp stripped: {bare}"


def test_ocr_reads_the_unmapped_stamp_on_every_page_of_a_pack_less_draft(tmp_path, table):
    """JK16's two-page demo form, filled with no pack: every page reads UNMAPPED DRAFT, NOT FILING-GRADE."""
    tesseract = _find_tesseract()  # in the test body, so a CI runner without it FAILS the test (not an error)
    env = unmapped_tests.Env(tmp_path, unmapped_tests._demo2(tmp_path), 2, "DEMO-2")
    result = env.fill(table, {"credit": 300, "hdr_name": "Demo Filer"}, money_fields=["credit"],
                      confirmed_fields=["hdr_name"])
    assert result["stamp"]["pages"] == [1, 2]
    work = tmp_path / "ocr"
    work.mkdir()
    _assert_read_on_every_page(env.out, UNMAPPED_STAMP, 2, tesseract, work)


def test_ocr_reads_the_rehearsal_stamp_on_every_page_of_a_rehearsal_fill(tmp_path):
    """A two-page offline DRAFT pack in a planning-only year, filled in rehearsal mode (JT0a): every page reads
    REHEARSAL, DRAFT FORM, NOT FOR FILING."""
    tesseract = _find_tesseract()
    pack = FormPack.model_validate({
        "form": "TEST-HARNESS", "jurisdiction": "federal", "tax_year": 2026, "source_status": "draft",
        "draft_created": "8/19/26", "source_url": "https://www.irs.gov/pub/irs-dft/ftest--dft.pdf", "pdf_sha256": "...",
        "acroform_root": ROOT,
        "fields": [{"line": "name", "field": "Page1[0].f1_4[0]", "type": "text"},
                   {"line": "1a", "field": "Page1[0].f1_28[0]", "type": "money"},
                   {"line": "2a", "field": "Page2[0].f2_1[0]", "type": "money"}],
    })
    blank = make_acroform_pdf(tmp_path / "harness.pdf", [
        {"name": f"{ROOT}.Page1[0].f1_4[0]", "x": 72, "y": 600},
        {"name": f"{ROOT}.Page1[0].f1_28[0]", "x": 72, "y": 560},
        {"name": f"{ROOT}.Page2[0].f2_1[0]", "page": 2, "x": 72, "y": 600},
    ])
    filled = tmp_path / "rehearsal.pdf"
    result = fill_form(pack, {"name": "Demo Filer", "1a": 1200, "2a": 300}, blank, filled, rehearsal=True)
    assert result.rehearsal
    work = tmp_path / "ocr"
    work.mkdir()
    _assert_read_on_every_page(filled, REHEARSAL_STAMP, 2, tesseract, work)


def _cover(placed):
    """A black box drawn over page 1's stamp, after it (test_stamp's 'black' cover)."""
    return stamp_tests._over_stamp(placed, 1, lambda b: b"q 0 g %.2f %.2f %.2f %.2f re f Q\n" % (
        b["x"], b["y"], b["w"], b["h"]))


def _crop(placed):
    """Page 1's CropBox starts 70% of the way along the stamp, so its last words fall outside the visible box."""
    x0, _y0, x1, _y1 = placed[0]["rect"]

    def cut(writer):
        writer.pages[0].cropbox = RectangleObject([x0 + (x1 - x0) * 0.7, 0, 612, 792])

    return cut


@pytest.mark.parametrize("hide", [_cover, _crop], ids=["covered", "cropped"])
def test_ocr_does_not_read_a_stamp_that_is_covered_or_cut_by_the_cropbox(tmp_path, hide):
    """Phase K JEe2 (2026-10-25), negative controls beside the stripped one: the stamp is still in page 1's content
    stream and text layer, but a box drawn over it or a CropBox that cuts it leaves nothing to read on the printed
    page, so OCR must not read it there; page 2, untouched, still reads in the same run."""
    tesseract = _find_tesseract()
    data, placed = stamp_tests._stamped(stamp_tests._blank(tmp_path))
    hidden = tmp_path / "hidden.pdf"
    hidden.write_bytes(stamp_tests._edit(data, hide(placed)))
    work = tmp_path / "ocr"
    work.mkdir()
    texts = _ocr_pages(hidden, tesseract, work)
    assert len(texts) == 3
    assert not _reads_as_stamped(texts[0], UNMAPPED_STAMP), f"page 1 read as stamped: {texts[0]!r}"
    assert _reads_as_stamped(texts[1], UNMAPPED_STAMP), f"page 2 (untouched) did not read: {texts[1]!r}"


def test_the_ocr_read_tolerates_case_and_the_em_dash_only():
    assert _reads_as_stamped("unmapped draft - not filing-grade", UNMAPPED_STAMP)
    assert _reads_as_stamped("Form DEMO-2\nUNMAPPED DRAFT -- NOT FILING GRADE\n", UNMAPPED_STAMP)
    assert _reads_as_stamped("REHEARSAL – DRAFT FORM NOT FOR FILING", REHEARSAL_STAMP)
    assert not _reads_as_stamped("UNMAPPED DRAFT", UNMAPPED_STAMP)            # half a stamp is no stamp
    assert not _reads_as_stamped("DRAFT FORM NOT FOR FILING", REHEARSAL_STAMP)
    assert not _reads_as_stamped("NOT FILING-GRADE UNMAPPED DRAFT", UNMAPPED_STAMP)  # out of order
    assert _reads_as_stamped("UNMAPPED DRAFT I NOT FILING-GRADE", UNMAPPED_STAMP)  # a rule read as a letter
    assert not _reads_as_stamped("UNMAPPED DRAFT a b c NOT FILING GRADE", UNMAPPED_STAMP)  # no longer one line


def test_a_missing_tesseract_fails_in_ci_and_skips_elsewhere(monkeypatch):
    """The lookup's two branches, without tesseract: CI set fails (the runner must install it), unset skips with the
    reason. Neither is silent."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    for value, outcome in (("true", pytest.fail.Exception), ("", pytest.skip.Exception), ("false", pytest.skip.Exception)):
        monkeypatch.setenv("CI", value)
        with pytest.raises(outcome, match="tesseract"):
            _find_tesseract()
