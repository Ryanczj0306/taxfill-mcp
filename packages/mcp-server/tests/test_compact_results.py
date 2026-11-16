"""Guard (Phase K JK32): list_document_kinds and extract_document answer compactly by default.

Claude Code warns on a tool result over 10,000 tokens and saves a text result over 50,000 characters to a file.
Before JK32 a bare list_document_kinds() returned every layout (104,002 characters of JSON) and a 1095-C
extract_document with one box read echoed every layout box (66,746 characters). The full shapes stay one optional
argument away.
"""

from __future__ import annotations

import json

import pytest

from taxfill_core.extract import DOC_SPECS, dec31_total_value_from_statements
from taxfill_core.extract import extract_document as core_extract
from taxfill_core.extract import list_document_kinds as core_kinds
from taxfill_mcp.server import extract_document, list_document_kinds


def _size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False))


def test_the_bare_call_is_an_index_under_the_bound():
    index = list_document_kinds()
    full = core_kinds()
    assert [k["kind"] for k in index] == [k["kind"] for k in full]
    for entry, kind in zip(index, full, strict=True):
        assert entry == {
            "kind": kind["kind"], "title": kind["title"], "source_url": kind["source_url"],
            "box_count": len(kind["boxes"]), "required_box_count": sum(b["required"] for b in kind["boxes"]),
            "box_layout": f'list_document_kinds(kind="{kind["kind"]}")',
        }
    assert _size(index) < 10_000, _size(index)   # 7,124 at JK32 (104,002 before)


def test_kind_returns_the_full_entries_as_before():
    by_kind = {k["kind"]: k for k in core_kinds()}
    assert list_document_kinds(kind="W-2") == [by_kind["W-2"]]
    assert list_document_kinds(kind=["1099-INT", "W-2", "1099-INT"]) == [by_kind["1099-INT"], by_kind["W-2"]]
    with pytest.raises(ValueError, match=r"unknown document kind\(s\) \['W2'\]; supported: .*'W-2'"):
        list_document_kinds(kind="W2")


def test_a_one_box_1095c_extract_echoes_only_that_box_and_the_missing_required_ones():
    first = DOC_SPECS["1095-C"].boxes[0].key
    out = extract_document("docs/1095c.pdf", "1095-C", {first: "Pat Example"})
    required = [b.key for b in DOC_SPECS["1095-C"].boxes if b.required]
    assert [f["key"] for f in out["fields"]] == [first, *required] and out["gaps"] == required
    assert all(f["status"] == "missing" and f["value"] is None for f in out["fields"][1:])
    assert _size(out) < 8_000, _size(out)   # 4,836 at JK32 (67,837 before), 3,776 of it the caveat


def test_echo_all_is_the_former_full_shape():
    fields = {"1": "$50,000", "2": "5000", "employee_ssn": "123-45-6789"}
    full = extract_document("docs/w2.png", "W-2", fields, page=1, echo_all=True)
    assert full == core_extract("docs/w2.png", "W-2", fields, page=1).model_dump(mode="json")
    assert [f["key"] for f in full["fields"]] == [b.key for b in DOC_SPECS["W-2"].boxes]


def test_the_compact_echo_keeps_every_passed_box_and_leaves_the_reporting_unchanged():
    # A blank box, an invalid reading, a box read under its other-year alias and an unknown key.
    fields = {"1": "", "4": "not a number", "7a": "7", "bogus": "1"}
    compact = extract_document("docs/r.pdf", "1099-R", fields, tax_year=2025)
    full = extract_document("docs/r.pdf", "1099-R", fields, tax_year=2025, echo_all=True)
    for key in ("gaps", "unexpected", "findings", "interpretation", "caveat", "citation"):
        assert compact[key] == full[key], key
    by_key = {f["key"]: f for f in full["fields"]}
    passed = {b.key for b in DOC_SPECS["1099-R"].boxes if {b.key, *b.aliases} & set(fields)}
    assert [f["key"] for f in compact["fields"]] == [k for k in by_key if k in passed or k in full["gaps"]]
    assert all(f == by_key[f["key"]] for f in compact["fields"])
    assert {"1", "4", "7"} <= {f["key"] for f in compact["fields"]} and compact["unexpected"] == ["bogus"]
    assert {f["key"]: f["status"] for f in compact["fields"]}["4"] == "invalid"


def test_dec31_total_value_reads_a_compact_statement():
    doc = core_extract("docs/trad.pdf", "IRA custodian statement", {
        "statement_type": "year_end_fmv", "account_type": "traditional", "fmv": "1,000", "fmv_date": "2025-12-31"},
        echo_all=False)
    v = dec31_total_value_from_statements([doc], 2025)
    assert v.dec31_total_value == 1000 and v.accounts[0]["custodian"] is None
