"""End-to-end MCP server tests over the SDK's in-memory client<->server transport.

These exercise the real MCP protocol path (tool listing, call_tool, content +
error handling), not just the wrapped core functions — so the MCP wiring itself
is regression-protected. Async bodies run via asyncio.run inside sync tests
(no pytest-asyncio dependency).
"""
from __future__ import annotations

import asyncio
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect
from mcp.types import ImageContent

from taxfill_mcp.server import mcp

EXPECTED_TOOLS = {
    "intake_checklist", "list_forms", "get_form_map", "fetch_blank", "fill_form",
    "verify_form", "verify_filing", "render_form", "calc", "residency",
    "estimate_refund", "get_sources", "filing_summary", "file_and_pay",
}


def _run(coro):
    return asyncio.run(coro)


def _data(result):
    """Robustly extract a tool's payload (structured when present, else JSON text)."""
    if result.structuredContent is not None:
        sc = result.structuredContent
        return sc.get("result", sc)  # list-returning tools wrap under "result"
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    return None


async def _call(name, args):
    async with connect(mcp) as client:
        return await client.call_tool(name, args)


# ── tool surface ───────────────────────────────────────────────────────────────


def test_all_expected_tools_are_listed_with_schemas():
    async def go():
        async with connect(mcp) as client:
            tools = (await client.list_tools()).tools
            names = {t.name for t in tools}
            assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"
            for t in tools:
                assert t.inputSchema and t.inputSchema.get("type") == "object"
                assert t.description  # every tool documents itself
    _run(go())


# ── offline tools ────────────────────────────────────────────────────────────


def test_list_forms_and_get_form_map():
    data = _data(_run(_call("list_forms", {"jurisdiction": "federal", "year": 2023})))
    assert len(data) == 10
    fm = _data(_run(_call("get_form_map", {"form": "f1040", "year": 2023})))
    assert fm["form"] == "1040"
    assert "8 == sched_1.10" in fm["cross_form"]


def test_intake_checklist_start():
    data = _data(_run(_call("intake_checklist", {})))
    ids = {q["id"] for q in data["next_questions"]}
    assert "identity.name" in ids and "identity.mailing_address" in ids


def test_calc_tax_matches_engine():
    data = _data(_run(_call("calc", {"op": "tax", "args": {"taxable_income": 75800, "filing_status": "head_of_household", "year": 2023}})))
    assert data["tax"] == 10383
    assert data["citation"]["url"].startswith("https://www.irs.gov/")


def test_estimate_refund_is_labeled_and_computed():
    profile = {"household": {"marital_status": {"value": "unmarried", "provenance": {"kind": "user_stated"}},
                             "filing_status": {"value": "single", "provenance": {"kind": "user_stated"}}}}
    data = _data(_run(_call("estimate_refund", {"profile": profile, "year": 2023, "income": {"wages": 50000, "federal_withholding": 6000}})))
    assert data["label"] == "ESTIMATE"
    assert data["low"] == data["high"] == data["point"]  # status known -> single number


def test_get_sources_freshness_registry():
    data = _data(_run(_call("get_sources", {"topic": "education", "year": 2023})))
    assert data["matched"] is True
    assert any("p970" in s["url"] for s in data["sources"])


def test_residency_substantial_presence():
    data = _data(_run(_call("residency", {
        "visa_periods": [{"status": "F-1", "start": "2021-08-01", "end": None}],
        "days_by_year": {"2021": 150, "2022": 300, "2023": 300},
        "target_year": 2023,
    })))
    # F-1 student is an exempt individual (5 calendar years), so still nonresident in 2023.
    assert data["classification"] == "nonresident"


def test_filing_summary_and_file_and_pay():
    manifest = [{"form": "1040", "tax_year": 2023, "bottom_line": -407, "state": "California"}]
    summ = _data(_run(_call("filing_summary", {"manifest": manifest})))
    assert "you owe $407" in summ["items"][0]["headline"].lower()
    fp = _data(_run(_call("file_and_pay", {"manifest": manifest})))
    assert any('"United States Treasury"' in p for p in fp["returns"][0]["payment"])


def test_unknown_form_is_a_clean_tool_error():
    async def go():
        async with connect(mcp) as client:
            r = await client.call_tool("get_form_map", {"form": "nope", "year": 2023})
            assert r.isError is True
            assert "Available form keys" in r.content[0].text
    _run(go())


# ── full chain on a real PDF (network or warm cache) ───────────────────────────


@pytest.mark.network
def test_full_chain_fetch_fill_verify_render(tmp_path):
    """fetch_blank -> fill_form -> verify_form -> render_form over MCP, on a real f8843."""
    async def go():
        async with connect(mcp) as client:
            try:
                fetched = _data(await client.call_tool("fetch_blank", {"form": "f8843", "year": 2023}))
            except Exception as exc:  # offline + cold cache
                pytest.skip(f"cannot fetch blank: {exc}")
            assert fetched["sha256"] and fetched["path"]

            # Pick two text lines from the map and fill them with sentinel values.
            fm = _data(await client.call_tool("get_form_map", {"form": "f8843", "year": 2023}))
            text_lines = [ln["line"] for ln in fm["lines"] if ln["type"] == "text"][:2]
            assert text_lines, "f8843 should have text lines"
            values = {ln: f"TEST {i}" for i, ln in enumerate(text_lines)}
            out = str(tmp_path / "f8843_filled.pdf")

            filled = _data(await client.call_tool("fill_form", {"form": "f8843", "year": 2023, "values": values, "out_path": out}))
            # written reports the AcroForm field names actually set (>= the lines we asked for).
            assert len(filled["written"]) >= len(values)

            report = _data(await client.call_tool("verify_form", {"form": "f8843", "year": 2023, "pdf_path": out, "expected": values}))
            # The values we set must read back cleanly (assertion diff has no failures).
            assert report["sections"]["assertions"]["failed"] == 0
            assert report["sections"]["clipping"]["failed"] == 0

            r = await client.call_tool("render_form", {"pdf_path": out, "pages": [1]})
            images = [c for c in r.content if isinstance(c, ImageContent)]
            assert images and images[0].mimeType == "image/png" and len(images[0].data) > 1000

    _run(go())
