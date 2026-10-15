"""The field-tree walk fill_form and verify fall back to when pypdf cannot build ``get_fields()``.

pypdf 6's ``get_fields()`` raises ``KeyError('/AP')`` on a radio field one of whose kid widgets carries no /AP
dictionary at all — the shape of AZ Form 140NR 2023's "Filing Status" (four kids, no appearance, no on-state
name). Without the fallback every fill and every verify of that blank crashes, whatever lines are filled.
``filler._field_names`` and ``verify.pdf_field_dicts`` catch exactly that error and walk /AcroForm /Fields and
/Kids instead. These tests build the shape synthetically (no real blank is vendored). Synthetic data only.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from pdf_fixtures import make_acroform_pdf
from taxfill_core.filler import _field_names, fill_form
from taxfill_core.schemas.formpack import FormPack
from taxfill_core.verify import pdf_field_dicts, read_pdf_fields

SPECS = [
    {"name": "name", "maxlen": 30},
    {"name": "box", "kind": "checkbox", "on_value": "/Yes"},
    {"name": "fs", "kind": "radio", "on_value": "/1", "x": 72, "y": 600},
    {"name": "fs", "kind": "radio", "on_value": "/2", "x": 72, "y": 580},
]


def _pack() -> FormPack:
    return FormPack.model_validate(
        {
            "form": "TEST-APLESS",
            "jurisdiction": "federal",
            "tax_year": 2023,
            "source_url": "https://www.irs.gov/pub/irs-pdf/test1.pdf",
            "pdf_sha256": "...",
            "acroform_root": "",
            "fields": [
                {"line": "name", "field": "name", "type": "text", "maxlen": 30},
                {"line": "box", "field": "box", "type": "checkbox", "on_state": "/Yes"},
            ],
        }
    )


def _strip_radio_kid_appearances(src: Path, dst: Path) -> Path:
    """Copy ``src`` with every /AP removed from the "fs" radio's kid widgets (the AZ 140NR 2023 shape)."""
    writer = PdfWriter(clone_from=PdfReader(str(src)))
    stripped = 0
    for page in writer.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            parent = annot.get("/Parent")
            if parent is not None and parent.get_object().get("/T") == "fs" and "/AP" in annot:
                del annot[NameObject("/AP")]
                stripped += 1
    assert stripped == 2, stripped
    with dst.open("wb") as fh:
        writer.write(fh)
    return dst


@pytest.fixture
def blanks(tmp_path: Path) -> tuple[Path, Path]:
    whole = make_acroform_pdf(tmp_path / "whole.pdf", SPECS)
    return whole, _strip_radio_kid_appearances(whole, tmp_path / "apless.pdf")


def test_the_walk_names_what_get_fields_names(blanks: tuple[Path, Path]):
    # On a blank pypdf CAN read, the walk and get_fields() agree on the names and on /FT.
    whole, _ = blanks
    reader = PdfReader(str(whole))
    expected = reader.get_fields() or {}
    walked = pdf_field_dicts(reader)  # get_fields() path
    assert set(walked) == set(expected) == {"name", "box", "fs"}
    assert _field_names(PdfWriter(clone_from=reader)) == set(expected)


def test_apless_radio_kids_fall_back_to_the_walk(blanks: tuple[Path, Path]):
    _, apless = blanks
    reader = PdfReader(str(apless))
    try:
        reader.get_fields()
    except KeyError as exc:  # the pypdf behaviour the fallback exists for
        assert exc.args == ("/AP",)
    fields = pdf_field_dicts(reader)
    assert set(fields) == {"name", "box", "fs"}
    assert fields["fs"]["/FT"] == "/Btn"
    assert fields["name"]["/FT"] == "/Tx"
    assert _field_names(PdfWriter(clone_from=PdfReader(str(apless)))) == {"name", "box", "fs"}


def test_fill_and_read_back_succeed_on_an_apless_radio_blank(blanks: tuple[Path, Path], tmp_path: Path):
    # The other fields of such a blank still fill and read back; the /AP-less radio itself stays untouched.
    _, apless = blanks
    out = tmp_path / "filled.pdf"
    result = fill_form(_pack(), {"name": "ALEX DEMO", "box": True}, apless, out)
    assert result.written == {"name": "ALEX DEMO", "box": "/Yes"}
    dump = read_pdf_fields(out)
    assert dump["name"] == "ALEX DEMO"
    assert dump["box"] == "/Yes"
    assert dump["fs"] == ""
