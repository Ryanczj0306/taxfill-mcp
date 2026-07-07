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
    "estimate_refund", "get_sources", "filing_summary", "file_and_pay", "state_scope",
    "list_document_kinds", "extract_document",
    "workspace_save", "workspace_load", "workspace_record_position", "workspace_reconcile",
    "hand_fill_worksheet",
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
    assert len(data) == 22  # M2 (10) + SE + D/E + 8863/2555 + 4868 + 1040-ES + 1040-X + W-7 + 8959/8960/8962
    fm = _data(_run(_call("get_form_map", {"form": "f1040", "year": 2023})))
    assert fm["form"] == "1040"
    assert "8 == sched_1.10" in fm["cross_form"]


def test_list_document_kinds_and_extract():
    kinds = _data(_run(_call("list_document_kinds", {})))
    assert any(k["kind"] == "W-2" for k in kinds)
    out = _data(_run(_call("extract_document", {
        "path": "documents/w2.png", "kind": "W-2",
        "fields": {"employee_ssn": "123-45-6789", "employer_ein": "12-3456789", "1": "$50,000", "2": "5000"},
        "page": 1,
    })))
    by = {f["key"]: f for f in out["fields"]}
    assert by["1"]["value"] == "50000" and by["1"]["provenance"]["file"] == "documents/w2.png"
    assert out["gaps"] == [] and out["citation"]["url"].startswith("https://www.irs.gov/")


def test_workspace_persist_resume_reconcile(tmp_path):
    root = str(tmp_path / "ws")
    _run(_call("workspace_save", {"year": 2023, "profile": {"identity": {}}, "root": root}))
    loaded = _data(_run(_call("workspace_load", {"year": 2023, "root": root})))
    assert loaded["profile"] == {"identity": {}}
    _run(_call("workspace_record_position", {"year": 2023, "root": root, "position": {
        "topic": "std deduction", "value": "13850",
        "citation": {"source": "IRS Pub 17", "url": "https://www.irs.gov/publications/p17"},
    }}))
    rec = _data(_run(_call("workspace_reconcile", {"year": 2023, "root": root})))
    assert "p17" in rec["reconciliation_md"] and rec["status"]["positions"]["decided"] == 1


def test_intake_checklist_start():
    data = _data(_run(_call("intake_checklist", {})))
    ids = {q["id"] for q in data["next_questions"]}
    assert "identity.name" in ids and "identity.mailing_address" in ids


def test_calc_tax_matches_engine():
    data = _data(_run(_call("calc", {"op": "tax", "args": {"taxable_income": 75800, "filing_status": "head_of_household", "year": 2023}})))
    assert data["tax"] == 10383
    assert data["citation"]["url"].startswith("https://www.irs.gov/")


def test_calc_phase_f_ops_are_dispatched():
    # One golden per new op (full derivations live in the core test suite).
    qd = _data(_run(_call("calc", {"op": "tax_with_preferential_rates", "args": {
        "taxable_income": 60000, "qualified_dividends": 10000, "filing_status": "single", "year": 2023}})))
    assert qd["tax"] == 7813
    ss = _data(_run(_call("calc", {"op": "taxable_social_security", "args": {
        "benefits": 20000, "other_income": 30000, "filing_status": "single", "year": 2023}})))
    assert ss["taxable_benefits"] == 9600
    ex = _data(_run(_call("calc", {"op": "excess_ss", "args": {"withheld_by_employer": [6000, 6000], "year": 2023}})))
    assert ex["credit"] == 2068
    sli = _data(_run(_call("calc", {"op": "student_loan_interest_deduction", "args": {
        "interest_paid": 3000, "magi": 82500, "filing_status": "single", "year": 2023}})))
    assert sli["deduction"] == 1250
    edu = _data(_run(_call("calc", {"op": "education_credits", "args": {
        "aotc_expenses_per_student": [4000, 1000], "magi": 50000, "filing_status": "single", "year": 2023}})))
    assert edu["total_credit"] == 3500 and edu["aotc_refundable"] == 1400
    ptc = _data(_run(_call("calc", {"op": "ptc_annual", "args": {
        "household_income": 27180, "household_size": 1, "annual_premiums": 7000,
        "annual_slcsp": 6000, "year": 2023}})))
    assert ptc["ptc"] == 5456 and ptc["contribution"] == 544


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


def test_verify_tools_expose_independent_and_summary_flags_not_run():
    """The verify gate's independent recompute is reachable over MCP (tool schema has the
    `independent` parameter) and, when it is NOT supplied, the summary says the recompute
    did not run — checked:0 alone must never masquerade as a fully-verified pass."""
    async def go():
        async with connect(mcp) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert "independent" in tools["verify_form"].inputSchema["properties"]
            assert "independent" in tools["verify_filing"].inputSchema["properties"]
            assert "calc" in tools["verify_form"].description  # docstring says where the numbers come from
    _run(go())

    from taxfill_core.verify import VerifyReport
    from taxfill_mcp.server import _report_summary

    not_run = _report_summary(VerifyReport(ok=True), recompute_ran=False)
    rec = not_run["sections"]["recompute"]
    assert rec["checked"] == 0 and rec["failed"] == 0
    assert "not run" in rec["note"] and "independent" in rec["note"]
    ran = _report_summary(VerifyReport(ok=True), recompute_ran=True)
    assert "note" not in ran["sections"]["recompute"]


def test_estimate_refund_unknown_income_field_error_is_prescriptive():
    """A wrong-field guess (the 'capital_gains' repro) must name the bad field, list every
    valid IncomeSnapshot field, and never echo the supplied amounts (PII masking)."""
    async def go():
        async with connect(mcp) as client:
            r = await client.call_tool("estimate_refund", {
                "profile": {}, "year": 2023,
                "income": {"wages": 54321, "capital_gains": 1000},
            })
            assert r.isError is True
            text = r.content[0].text
            assert "capital_gains" in text  # names the offending field
            for field in ("capital_gain_long", "capital_gain_short", "social_security_benefits",
                          "aca_premiums", "spouse"):
                assert field in text  # full valid-field list
            assert "54321" not in text and "1000" not in text  # never echo input values
    _run(go())


def test_workspace_record_position_bad_shape_error_shows_expected_shape(tmp_path):
    """The natural first guess ({topic, decision, authority}) must come back with the
    canonical Position shape, not a raw pydantic dump."""
    async def go():
        async with connect(mcp) as client:
            r = await client.call_tool("workspace_record_position", {
                "year": 2023, "root": str(tmp_path / "ws"),
                "position": {"topic": "filing_status", "decision": "single", "authority": "IRC 1(c)"},
            })
            assert r.isError is True
            text = r.content[0].text
            assert "decision" in text and "value" in text  # names bad keys AND required ones
            assert '"citation": {"source"' in text  # shows the nested citation shape
            assert "e.g." in text  # carries a copyable example
            assert not (tmp_path / "ws").exists()  # invalid input creates no workspace
    _run(go())


def test_tool_surface_is_exactly_22_and_matches_manifest():
    """Exact tool-surface guard (the other test is a subset check, so it misses ADDED tools).

    Adding/removing/renaming a tool fails here until both EXPECTED_TOOLS and the shipped
    bundle/manifest.json are updated — keeping the server, the tests, and the one-click
    .mcpb manifest in lock-step (the packaging job also asserts 22 against the built wheel).
    """
    from pathlib import Path

    names = {t.name for t in _run(mcp.list_tools())}
    assert names == EXPECTED_TOOLS, (
        f"server tool drift — unexpected: {names - EXPECTED_TOOLS}, missing: {EXPECTED_TOOLS - names}"
    )
    assert len(names) == 22

    manifest = json.loads((Path(__file__).parents[3] / "bundle" / "manifest.json").read_text())
    manifest_names = {t["name"] for t in manifest["tools"]}
    assert manifest_names == names, (
        f"manifest/server drift — only in manifest: {manifest_names - names}, "
        f"only in server: {names - manifest_names}"
    )


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
            # No `independent` supplied -> the summary must say the recompute did not run.
            assert "not run" in report["sections"]["recompute"]["note"]

            r = await client.call_tool("render_form", {"pdf_path": out, "pages": [1]})
            images = [c for c in r.content if isinstance(c, ImageContent)]
            assert images and images[0].mimeType == "image/png" and len(images[0].data) > 1000

    _run(go())


@pytest.mark.network
def test_verify_form_independent_recompute_catches_wrong_tax_over_mcp(tmp_path):
    """The persona-review $6,036 repro, end-to-end over MCP: a 1040 whose line 16 carries a
    wrong tax-table number now FAILS verify_form when the calc result is passed as
    `independent` — the gate the whole safety story rests on actually checks the number."""
    async def go():
        async with connect(mcp) as client:
            try:
                _data(await client.call_tool("fetch_blank", {"form": "f1040", "year": 2023}))
            except Exception as exc:  # offline + cold cache
                pytest.skip(f"cannot fetch blank: {exc}")

            # Independent pass: the calc engine, not the agent, produces the tax number.
            tax = _data(await client.call_tool("calc", {"op": "tax", "args": {
                "taxable_income": 205150, "filing_status": "married_filing_jointly", "year": 2023}}))
            assert tax["tax"] == 36036

            # Fill line 16 with the understated 30000 (off by $6,036 from the tax table).
            out = str(tmp_path / "f1040_wrong_tax.pdf")
            _data(await client.call_tool("fill_form", {
                "form": "f1040", "year": 2023,
                "values": {"15": 205150, "16": 30000}, "out_path": out}))

            report = _data(await client.call_tool("verify_form", {
                "form": "f1040", "year": 2023, "pdf_path": out,
                "independent": {"16": tax["tax"]}}))
            assert report["ok"] is False
            rec = report["sections"]["recompute"]
            assert rec["checked"] == 1 and rec["failed"] == 1
            assert "note" not in rec  # the recompute RAN — no not-run disclaimer
            assert any("30000" in f and "36036" in f for f in rec["failures"])

            # Same wrong PDF through verify_filing with the per-form_key independent shape.
            filing = _data(await client.call_tool("verify_filing", {
                "items": [{"form": "f1040", "year": 2023, "pdf_path": out}],
                "independent": {"f1040": {"16": tax["tax"]}}}))
            assert filing["ok"] is False
            assert filing["sections"]["recompute"]["failed"] == 1
            assert "note" not in filing["sections"]["recompute"]

            # Without `independent`, the same PDF's summary must disclose the recompute gap.
            silent = _data(await client.call_tool("verify_form", {
                "form": "f1040", "year": 2023, "pdf_path": out}))
            assert silent["sections"]["recompute"]["checked"] == 0
            assert "not run" in silent["sections"]["recompute"]["note"]

    _run(go())
