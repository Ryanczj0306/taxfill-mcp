"""Pack-authoring skeleton tests (M7 — mechanize form-pack creation)."""
from __future__ import annotations

from pathlib import Path

import yaml
from pdf_fixtures import make_acroform_pdf

from taxfill_core.packbuild import build_skeleton, detect_acroform_root, extract_fields
from taxfill_core.schemas.formpack import FormPack

ROOT = "topmostSubform[0]"


def _blank(tmp: Path) -> Path:
    return make_acroform_pdf(
        tmp / "blank.pdf",
        [
            {"name": f"{ROOT}.Page1[0].f1_7[0]", "maxlen": 9, "comb": True},
            {"name": f"{ROOT}.Page1[0].f1_4[0]", "maxlen": 30},
            {"name": f"{ROOT}.Page1[0].c1_1[0]", "kind": "checkbox", "on_value": "/1"},
            {"name": f"{ROOT}.Page2[0].f2_3[0]", "page": 2},
        ],
    )


def test_detect_acroform_root():
    assert detect_acroform_root([f"{ROOT}.Page1[0].f1_7[0]", f"{ROOT}.Page2[0].f2_3[0]"]) == ROOT
    assert detect_acroform_root(["1045", "1035 CB"]) == ""          # flat state AcroForm
    assert detect_acroform_root([f"{ROOT}.a", "loose"]) == ""        # mixed -> no shared root


def test_extract_fields_reads_widgets(tmp_path):
    fields = extract_fields(_blank(tmp_path))
    assert len(fields) == 4
    cb = [f for f in fields if f["type"] == "checkbox"]
    assert len(cb) == 1 and "/1" in cb[0]["on_states"]


def test_build_skeleton_validates_as_formpack(tmp_path):
    skel = build_skeleton(_blank(tmp_path), form="1040-X", jurisdiction="federal", tax_year=2023,
                          source_url="https://www.irs.gov/pub/irs-pdf/f1040x.pdf")
    todo = skel.pop("_todo")
    assert isinstance(todo, list)
    assert skel["acroform_root"] == ROOT
    assert len(skel["pdf_sha256"]) == 64
    by_field = {f["field"]: f for f in skel["fields"]}
    assert "Page1[0].f1_7[0]" in by_field and by_field["Page1[0].f1_7[0]"]["maxlen"] == 9
    cb = [f for f in skel["fields"] if f["type"] == "checkbox"]
    assert cb and cb[0]["on_state"] == "/1"
    # The whole skeleton is structurally valid as a FormPack.
    FormPack.model_validate(skel)


def test_extract_fields_qualifies_hierarchical_names(tmp_path):
    # Real IRS XFA shape: a parent/kid tree — the skeleton must carry the FULL
    # dotted name (what the filler addresses), not just the leaf /T.
    from pypdf import PdfReader
    pdf = make_acroform_pdf(tmp_path / "h.pdf", [
        {"name": f"{ROOT}.Page1[0].f1_7[0]", "maxlen": 9, "hierarchical": True},
    ])
    names = [f["name"] for f in extract_fields(pdf)]
    assert f"{ROOT}.Page1[0].f1_7[0]" in names
    # and the filler agrees on that name
    PdfReader(str(pdf))


def test_radio_group_options_are_enumerated(tmp_path):
    pdf = make_acroform_pdf(tmp_path / "r.pdf", [
        {"name": f"{ROOT}.Page1[0].fs[0]", "kind": "radio", "on_value": "/1"},
        {"name": f"{ROOT}.Page1[0].fs[0]", "kind": "radio", "on_value": "/2"},
    ])
    skel = build_skeleton(pdf, form="540", jurisdiction="states/ca", tax_year=2023,
                          source_url="https://www.ftb.ca.gov/forms/2023/2023-540.pdf")
    skel.pop("_todo")
    cb = [f for f in skel["fields"] if f["type"] == "checkbox"]
    on = {f["on_state"] for f in cb}
    assert {"/1", "/2"} <= on                          # both radio options enumerated
    assert len({f["field"] for f in cb}) == 1          # they share one AcroForm field
    assert len({f["line"] for f in cb}) == len(cb)     # unique line keys per option
    FormPack.model_validate(skel)


def test_sentinel_sweep_fills_each_field_with_its_name(tmp_path):
    from pypdf import PdfReader

    from taxfill_core.packbuild import sentinel_sweep
    pdf = _blank(tmp_path)
    out = sentinel_sweep(pdf, tmp_path / "sweep.pdf")
    reader = PdfReader(str(out))
    filled = {}
    for page in reader.pages:
        for ref in page.get("/Annots") or []:
            o = ref.get_object()
            node = o if o.get("/T") is not None else (o.get("/Parent").get_object() if o.get("/Parent") else o)
            if node.get("/T") is not None and node.get("/V") is not None:
                filled[str(node.get("/T"))] = str(node.get("/V"))
    # a text field's value is its own (leaf) name; at least one checkbox got an on-state
    assert any(v in k for k, v in filled.items())


def test_introspect_cli_writes_skeleton(tmp_path):
    # The `taxfill introspect` CLI ties build_skeleton + sweep together; taxfill_mcp
    # is installed in the workspace so it imports here.
    from taxfill_mcp.cli import main

    pdf = _blank(tmp_path)
    out = tmp_path / "pack_out"
    rc = main([
        "introspect", str(pdf), "--form", "1040-X", "--jurisdiction", "federal",
        "--year", "2023", "--source-url", "https://www.irs.gov/pub/irs-pdf/f1040x.pdf", "--out", str(out),
    ])
    assert rc == 0
    skel = yaml.safe_load((out / "pack.skeleton.yaml").read_text())
    FormPack.model_validate(skel)  # the written skeleton re-validates
    assert (out / "MAPPING_TODO.md").exists()
