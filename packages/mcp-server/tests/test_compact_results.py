"""Guard (Phase K JK32): list_document_kinds and extract_document answer compactly by default.

Claude Code warns on a tool result over 10,000 tokens and saves a text result over 50,000 characters to a file.
Before JK32 a bare list_document_kinds() returned every layout (104,002 characters of JSON) and a 1095-C
extract_document with one box read echoed every layout box (66,746 characters). The full shapes stay one optional
argument away.
"""

from __future__ import annotations

import json

import pytest

from taxfill_core.extract import list_document_kinds as core_kinds
from taxfill_mcp.server import list_document_kinds


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
