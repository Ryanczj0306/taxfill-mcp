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
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.memory import create_connected_server_and_client_session as connect
from mcp.types import ImageContent

import taxfill_mcp
from taxfill_core.file_and_pay import DRAFT_NOTICE
from taxfill_mcp.server import mcp

EXPECTED_TOOLS = {
    "intake_checklist", "list_forms", "get_form_map", "fetch_blank", "fill_form",
    "verify_form", "verify_filing", "render_form", "calc", "residency",
    "estimate_refund",
    "compare_scenarios", "get_sources", "filing_summary", "file_and_pay", "state_scope",
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


def test_initialize_reports_this_packages_version_not_the_sdks():
    """serverInfo.version is taxfill-mcp's release (Phase K JK5: it read "1.30.0", the mcp SDK's)."""

    async def handshake():
        server = mcp._mcp_server
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with asyncio.TaskGroup() as tg:
                task = tg.create_task(server.run(*server_streams, server.create_initialization_options()))
                try:
                    async with ClientSession(*client_streams) as client:
                        result = await client.initialize()
                        await client.send_ping()  # the server has handled notifications/initialized: a clean stop
                        return result
                finally:
                    task.cancel()

    info = _run(handshake()).serverInfo
    assert (info.name, info.version) == ("taxfill", taxfill_mcp.__version__)


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
    # M2 (10) + SE + D/E + 8863/2555 + 4868 + 1040-ES + 1040-X + W-7 + 8959/8960/8962
    # + Tier 2: sched_8812 (CTC/ACTC), sched_a_nr, sched_nec
    # + Phase G: f2441, f843, f8316 — the pack set has settled, exact count restored.
    # + Phase J JR4b: the 2023 f5329.
    assert len(data) == 35
    assert any(f["form_key"] == "sched_8812" for f in data)  # the CTC is FILEABLE (persona-review fix)
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
    ptcm = _data(_run(_call("calc", {"op": "ptc_monthly", "args": {
        "household_income": 27180, "household_size": 1, "year": 2023,
        "monthly": [{"premium": 450, "slcsp": 420, "aptc": 380}] * 7 + [{}] * 5}})))
    assert ptcm["ptc"] == 2625 and ptcm["monthly_contribution"] == 45
    assert ptcm["months_covered"] == 7 and ptcm["repayment"] == 35


def test_calc_family_credit_ops_are_dispatched():
    # One golden per op (full derivations live in the core test suite): the family
    # credits the persona review found unfileable — Schedule 8812 CTC/ODC/ACTC and
    # the EITC — are reachable over MCP with work + citation.
    ctc = _data(_run(_call("calc", {"op": "child_tax_credit", "args": {
        "qualifying_children_ssn": 2, "other_dependents": 0, "magi": 95000,
        "income_tax_before_credits": 7639, "earned_income": 95000,
        "filing_status": "married_filing_jointly", "year": 2023}})))
    assert ctc["nonrefundable_used"] == 4000 and ctc["actc_refundable"] == 0
    assert "Schedule 8812" in ctc["work"] and ctc["citation"]["url"].startswith("https://www.irs.gov/")
    actc = _data(_run(_call("calc", {"op": "child_tax_credit", "args": {
        "qualifying_children_ssn": 2, "other_dependents": 0, "magi": 20000,
        "income_tax_before_credits": 0, "earned_income": 20000,
        "filing_status": "single", "year": 2023}})))
    assert actc["actc_refundable"] == 2625  # 15% x (20,000 - 2,500) binds
    ei = _data(_run(_call("calc", {"op": "eitc", "args": {
        "earned_income": 15000, "agi": 15000, "qualifying_children": 1,
        "filing_status": "single", "year": 2023}})))
    assert ei["eitc"] == 3995 and ei["phase"] == "plateau" and ei["disqualified_reason"] is None
    assert ei["citation"]["url"].startswith("https://www.irs.gov/")
    gated = _data(_run(_call("calc", {"op": "eitc", "args": {
        "earned_income": 15000, "agi": 15000, "qualifying_children": 1,
        "filing_status": "married_filing_separately", "year": 2023}})))
    assert gated["eitc"] == 0 and gated["disqualified_reason"]


def test_calc_dependent_care_credit_is_dispatched():
    # Phase G item G2: one golden per shape (full derivations live in the core
    # test suite, packages/core/tests/test_tax_calc.py).
    dc = _data(_run(_call("calc", {"op": "dependent_care_credit", "args": {
        "expenses": 3600, "qualifying_persons": 1, "earned_income": 30000,
        "agi": 14000, "filing_status": "single", "year": 2023}})))
    assert dc["allowed_expenses"] == 3000 and dc["credit"] == 1050
    assert dc["applicable_percentage"] == "0.35" and dc["refundable"] is False
    assert dc["citation"]["url"] == "https://www.irs.gov/pub/irs-prior/i2441--2023.pdf"
    arpa = _data(_run(_call("calc", {"op": "dependent_care_credit", "args": {
        "expenses": 20000, "qualifying_persons": 2, "earned_income": 60000,
        "spouse_earned_income": 50000, "agi": 120000,
        "filing_status": "married_filing_jointly", "year": 2021}})))
    assert arpa["credit"] == 8000 and arpa["refundable"] is True
    gated = _data(_run(_call("calc", {"op": "dependent_care_credit", "args": {
        "expenses": 3000, "qualifying_persons": 1, "earned_income": 30000,
        "agi": 20000, "filing_status": "married_filing_separately", "year": 2023}})))
    assert gated["credit"] == 0 and "joint return" in gated["work"]
    # The MFJ-needs-spouse-earned-income prescriptive error travels over MCP.
    err = _run(_call("calc", {"op": "dependent_care_credit", "args": {
        "expenses": 3000, "qualifying_persons": 1, "earned_income": 30000,
        "agi": 20000, "filing_status": "married_filing_jointly", "year": 2023}}))
    assert err.isError is True and "spouse_earned_income" in err.content[0].text
    # The unknown-op error lists the new op.
    unknown = _run(_call("calc", {"op": "nope", "args": {}}))
    assert "dependent_care_credit" in unknown.content[0].text


def test_file_and_pay_dispatches_the_fica_claim_path():
    # Phase G item G6: the 843+8316 FICA claim manifest shape works over MCP.
    fp = _data(_run(_call("file_and_pay", {"manifest": [
        {"form": "843", "tax_year": 2023, "bottom_line": 3060, "attached_forms": ["8316"]}]})))
    claim = fp["returns"][0]
    assert "Ogden, UT 84201-0038" in claim["mailing_address"]
    assert any("DO NOT attach this claim to your Form 1040-NR" in a for a in claim["assemble"])
    assert any("PAGE 2" in s for s in claim["sign"])  # f843 signature page per the pack


def test_calc_treaty_benefit_is_dispatched():
    # Phase G item G1: one golden per shape (full derivations live in the core
    # test suite, packages/core/tests/test_treaties.py).
    tb = _data(_run(_call("calc", {"op": "treaty_benefit", "args": {
        "country": "china", "income_class": "student_wages", "amount": 8000, "year": 2023}})))
    assert tb["exempt_amount"] == 5000 and tb["taxable_remainder"] == 3000
    assert tb["article"] == "Art. 20 (Students and Trainees)"
    assert tb["citation"]["url"] == "https://www.irs.gov/pub/irs-trty/china.pdf"
    assert "VALIDATES" in tb["work"]  # eligibility judgment stays with the agent
    teacher = _data(_run(_call("calc", {"op": "treaty_benefit", "args": {
        "country": "india", "income_class": "teacher_wages", "amount": 70000,
        "years_in_status": 3, "year": 2023}})))
    assert teacher["exempt_amount"] == 0 and "RETROACTIVE LOSS" in teacher["work"]
    # The unknown-op error lists the new op.
    unknown = _run(_call("calc", {"op": "nope", "args": {}}))
    assert unknown.isError is True
    assert "treaty_benefit" in unknown.content[0].text


def test_calc_state_tax_is_dispatched():
    # Phase G item G4: one golden per shape (full derivations live in the core
    # test suite, packages/core/tests/test_tax_calc.py).
    il = _data(_run(_call("calc", {"op": "state_tax", "args": {
        "state": "il", "taxable_base": 50000, "exemptions_count": 1, "year": 2023}})))
    assert il["tax"] == 2355 and il["base_after_exemptions"] == 47575
    assert il["rate"] == "0.0495" and il["base_kind"] == "federal_agi"
    assert il["citation"]["url"].startswith("https://tax.illinois.gov/")
    # PA: no exemptions, no deduction — the op multiplies the eight-class base only.
    pa = _data(_run(_call("calc", {"op": "state_tax", "args": {
        "state": "pa", "taxable_base": 61000, "year": 2023}})))
    assert pa["tax"] == 1873 and "no exemptions or standard deduction" in pa["work"]
    # CA (graduated second tranche): the bracket math and structure fields travel over MCP.
    ca = _data(_run(_call("calc", {"op": "state_tax", "args": {
        "state": "ca", "taxable_base": 60000, "filing_status": "head_of_household", "year": 2023}})))
    assert ca["tax"] == 777 and ca["rate_structure"] == "graduated"
    assert ca["rate"] is None and ca["marginal_rate"] == "0.02"
    # The unsupported-YEAR prescriptive error (listing the shipped states) travels
    # over MCP. Every jurisdiction now ships 2023/2024 blocks, so the refusal path
    # is exercised with a year no state pack covers.
    err = _run(_call("calc", {"op": "state_tax", "args": {
        "state": "il", "taxable_base": 50000, "year": 2019}}))
    assert err.isError is True
    assert "never invent" in err.content[0].text
    # The unknown-op error lists the new op.
    unknown = _run(_call("calc", {"op": "nope", "args": {}}))
    assert "state_tax" in unknown.content[0].text


def test_calc_state_tax_returns_ca_exemption_credits_over_mcp():
    # Phase K JK28 (2026-10-16): California's exemption credits travel as structured fields. MFJ, California AGI and
    # federal AGI $200,000, two dependents (2025): line 31 $10,416; line 7 2 x $153 + line 10 2 x $475 = line 11
    # $1,256 = line 32 (AGI not more than $504,411); line 33 $9,160 (worked in packages/core/tests/
    # test_state_exemption_credits.py).
    ca = _data(_run(_call("calc", {"op": "state_tax", "args": {
        "state": "ca", "taxable_base": 200000, "filing_status": "married_filing_jointly", "year": 2025,
        "exemption_credit_counts": {"personal": 2, "dependent": 2}, "federal_agi": 200000}})))
    assert ca["tax"] == 10416
    ec = ca["exemption_credits"]
    assert ec["applied"] is True and ec["form"] == "Form 540"
    assert ec["credits"]["personal"] == {"line": "7", "count": 2, "amount_each": 153, "credit": 306}
    assert ec["credits"]["dependent"] == {"line": "10", "count": 2, "amount_each": 475, "credit": 950}
    assert (ec["exemption_amount"], ec["limitation_reduction"], ec["total"], ec["tax_after_credits"]) == (1256, 0, 1256, 9160)
    assert ec["lines"] == {"exemption_amount": "11", "total": "32", "tax_after_credits": "33"}
    # Without counts the tax line is unchanged and the result says the credits were not applied.
    plain = _data(_run(_call("calc", {"op": "state_tax", "args": {
        "state": "ca", "taxable_base": 200000, "filing_status": "married_filing_jointly", "year": 2025}})))
    assert plain["tax"] == 10416 and plain["exemption_credits"]["applied"] is False
    assert "Exemption credits NOT applied" in plain["work"]
    # A state whose pack ships no credits keeps its old output shape, and refuses a nonzero credit count.
    il = _data(_run(_call("calc", {"op": "state_tax", "args": {
        "state": "il", "taxable_base": 50000, "exemptions_count": 1, "year": 2025}})))
    assert "exemption_credits" not in il
    err = _run(_call("calc", {"op": "state_tax", "args": {
        "state": "il", "taxable_base": 50000, "year": 2025, "exemption_credit_counts": {"personal": 1}}}))
    assert err.isError is True and "ships no exemption_credits block" in err.content[0].text
    # Phase K JK28 (2026-10-23): Oregon's AGI ceiling travels too. Single, line 15 and federal AGI $100,001, one
    # Regular box: "If your federal AGI is more than $100,000 and your filing status is single ... enter 0" (2025
    # OR-40 instructions p. 18), so line 25 is $0; agi_ceilings names the ceiling per kind.
    ore = _data(_run(_call("calc", {"op": "state_tax", "args": {
        "state": "or", "taxable_base": 100001, "year": 2025, "exemption_credit_counts": {"regular": 1},
        "federal_agi": 100001}})))
    oec = ore["exemption_credits"]
    assert (oec["exemption_amount"], oec["total"], oec["limitation_reduction"]) == (256, 0, 256)
    assert oec["agi_ceilings"]["regular"] == 100000 and oec["lines"]["total"] == "25"
    assert "agi_ceilings" not in ec  # California's limitation is not a ceiling; its output keeps its shape


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
    assert data["classification_without_election"] is None


def test_residency_tool_applies_the_6013_election():
    # P-018: the §6013(g)/(h) election makes the couple residents for the ENTIRE year
    # (Pub 519 ch. 1), whatever the SPT says; the day-count answer comes back as
    # classification_without_election — the one calc op employee_fica takes.
    data = _data(_run(_call("residency", {
        "visa_periods": [{"status": "F-1", "start": "2021-08-01", "end": None}],
        "days_by_year": {"2021": 150, "2022": 300, "2023": 300},
        "target_year": 2023,
        "section_6013_election": True,
    })))
    assert data["classification"] == "resident"
    assert data["section_6013_election"] is True
    assert data["classification_without_election"] == "nonresident"
    assert "entire tax year" in data["reasons"][0] and "chapter 24" in data["reasons"][0]


def test_p018_residency_tool_takes_the_prior_year_fact():
    # JF5b part 1: Treas. Reg. 301.7701(b)-4(e)(1) — a prior-year resident who meets the SPT
    # is a resident from January 1; one who fails it gets a FIRST CONTRADICTION reason.
    switch = [{"status": "F-1", "start": "2021-08-20", "end": "2025-03-31"},
              {"status": "H-1B", "start": "2025-04-01", "end": None}]
    days = {"2021": 130, "2022": 365, "2023": 365, "2024": 366, "2025": 365}
    base = {"visa_periods": switch, "days_by_year": days, "target_year": 2025}
    assert _data(_run(_call("residency", base)))["classification"] == "dual_status_candidate"
    carried = _data(_run(_call("residency", {**base, "prior_year_resident": True})))
    assert carried["classification"] == "resident" and carried["prior_year_resident"] is True
    assert carried["inputs"]["prior_year_resident"] is True
    truncated = [{"status": "F-1", "start": "2021-08-20", "end": "2025-09-30"},
                 {"status": "H-1B", "start": "2025-10-01", "end": None}]
    contra = _data(_run(_call("residency", {**base, "visa_periods": truncated, "prior_year_resident": True})))
    assert contra["classification"] == "nonresident" and contra["reasons"][0].startswith("CONTRADICTION")


def test_filing_summary_and_file_and_pay():
    manifest = [{"form": "1040", "tax_year": 2023, "bottom_line": -380, "state": "California"}]
    summ = _data(_run(_call("filing_summary", {"manifest": manifest})))
    assert "you owe $380" in summ["items"][0]["headline"].lower()
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


def test_verify_summary_lists_skipped_checks():
    """A SKIPPED check never flips ok, so the summary must say what went unchecked (Phase K JK28): a relation whose
    `unless` box is checked, a cross_form rule whose form is not in the filing. A section with nothing skipped keeps
    its old three keys."""
    from taxfill_core.verify import CrossFormCheck, RelationCheck, VerifyReport
    from taxfill_mcp.server import _report_summary

    report = VerifyReport(
        ok=True,
        relations=[
            RelationCheck(relation="12 == max(7 - 11, 0) unless alt_tax_method", status="SKIPPED",
                          detail="relation '12 == max(7 - 11, 0) unless alt_tax_method' not checked: box ..."),
            RelationCheck(relation="7 == 5 + 6", status="PASS", detail="456 == 456"),
        ],
        cross_form=[CrossFormCheck(form_key="ia1040", relation="1f == sched_1a.37", status="SKIPPED",
                                   detail="cross_form rule '1f == sched_1a.37' not checked: ...")],
    )
    sections = _report_summary(report)["sections"]
    assert sections["relations"] == {
        "checked": 2, "failed": 0, "failures": [],
        "skipped": ["relation '12 == max(7 - 11, 0) unless alt_tax_method' not checked: box ..."],
    }
    assert sections["cross_form"]["skipped"] == ["cross_form rule '1f == sched_1a.37' not checked: ..."]
    assert sections["assertions"] == {"checked": 0, "failed": 0, "failures": []}


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


def test_tool_surface_is_exactly_23_and_matches_manifest():
    """Exact tool-surface guard (the other test is a subset check, so it misses ADDED tools).

    Adding/removing/renaming a tool fails here until both EXPECTED_TOOLS and the shipped
    packages/mcp-server/bundle/manifest.json are updated — keeping the server, the tests, and the one-click
    .mcpb manifest in lock-step (the packaging job checks the built wheel's tools against EXPECTED_TOOLS and the
    count below: scripts/release_smoke.py).
    """
    from pathlib import Path

    names = {t.name for t in _run(mcp.list_tools())}
    assert names == EXPECTED_TOOLS, (
        f"server tool drift — unexpected: {names - EXPECTED_TOOLS}, missing: {EXPECTED_TOOLS - names}"
    )
    assert len(names) == 23

    manifest = json.loads((Path(__file__).parents[1] / "bundle" / "manifest.json").read_text())
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
            assert filled["notice"] == DRAFT_NOTICE  # review draft, not tax advice, paper filing only

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
def test_verify_form_over_mcp_skips_ia_line_12_while_the_step_5_box_is_checked(tmp_path):
    """IA 1040 2025 over MCP (Phase K JK28): a single filer on the Income Tax Reduction Worksheet (41-146) checks the
    Step 5 box and enters the worksheet's smaller amount on line 12. verify_form reports ok, and the summary lists the
    guarded relation under `skipped`; the same return with the box unchecked fails it. Demo figures only."""
    async def go():
        async with connect(mcp) as client:
            ia = {"form": "ia1040", "year": 2025, "jurisdiction": "states/ia"}
            try:
                _data(await client.call_tool("fetch_blank", ia))
            except Exception as exc:  # offline + cold cache
                pytest.skip(f"cannot fetch blank: {exc}")
            fm = _data(await client.call_tool("get_form_map", ia))
            guarded = "12 == max(7 - 11, 0) unless alt_tax_method"
            assert guarded in fm["relations"]
            values = {"filing_status.single": True, "a": 40, "d": 40, "2": 12000, "4": 12000, "5": 456, "7": 456,
                      "8": 40, "11": 40, "12": 300, "14": 300, "16": 300, "18": 300, "20": 300, "22": 300}
            for name, box, ok in (("checked.pdf", True, True), ("unchecked.pdf", False, False)):
                out = str(tmp_path / name)
                _data(await client.call_tool("fill_form", {**ia, "values": {**values, "alt_tax_method": box},
                                                           "out_path": out}))
                report = _data(await client.call_tool("verify_form", {**ia, "pdf_path": out}))
                rel = report["sections"]["relations"]
                assert report["ok"] is ok, rel
                if box:
                    assert rel["failed"] == 0
                    assert any(guarded in s and "box 'alt_tax_method' is checked" in s for s in rel["skipped"])
                else:
                    assert "skipped" not in rel
                    assert any(guarded in f for f in rel["failures"])

    _run(go())


@pytest.mark.network
def test_verify_filing_over_mcp_names_the_item_of_each_skipped_and_failed_relation(tmp_path):
    """Phase K JK28 final review (2026-10-23): two IA 1040 items carry the same guarded relation. The summary's
    `skipped` and `failures` entries are built from each check's detail, so each must name its form_key — before the
    fix the two items' skipped entries were identical strings and a failure named no item. Demo figures only."""
    async def go():
        async with connect(mcp) as client:
            ia = {"form": "ia1040", "year": 2025, "jurisdiction": "states/ia"}
            try:
                _data(await client.call_tool("fetch_blank", ia))
            except Exception as exc:  # offline + cold cache
                pytest.skip(f"cannot fetch blank: {exc}")
            values = {"filing_status.single": True, "a": 40, "d": 40, "2": 12000, "4": 12000, "5": 456, "7": 456,
                      "8": 40, "11": 40, "12": 300, "14": 300, "16": 300, "18": 300, "20": 300, "22": 300,
                      "alt_tax_method": True}
            items = []
            for key, extra in (("ia_a", {}), ("ia_b", {"7": 999})):  # ia_b's line 7 breaks "7 == 5 + 6"
                out = str(tmp_path / f"{key}.pdf")
                _data(await client.call_tool("fill_form", {**ia, "values": {**values, **extra}, "out_path": out}))
                items.append({**ia, "pdf_path": out, "form_key": key})
            report = _data(await client.call_tool("verify_filing", {"items": items}))
            rel = report["sections"]["relations"]
            guarded = "12 == max(7 - 11, 0) unless alt_tax_method"
            for key in ("ia_a", "ia_b"):
                assert any(s.startswith(f"{key}: ") and guarded in s for s in rel["skipped"]), rel["skipped"]
            assert len(set(rel["skipped"])) == len(rel["skipped"]), rel["skipped"]
            assert rel["failures"] and all(f.startswith("ia_b: ") for f in rel["failures"]), rel["failures"]

    _run(go())


@pytest.mark.network
def test_fill_form_over_mcp_names_the_combs_it_aligned(tmp_path):
    """Phase K JK28 (2026-10-23): the 2025 Form 1040 SSN box's dotted separators cross the widget's comb cells, so
    fill_form narrows it (P-033) and its MCP result names the widget under `combs_aligned`, as FillResult does."""
    async def go():
        async with connect(mcp) as client:
            where = {"form": "f1040", "year": 2025}
            try:
                _data(await client.call_tool("fetch_blank", where))
            except Exception as exc:  # offline + cold cache
                pytest.skip(f"cannot fetch blank: {exc}")
            filled = _data(await client.call_tool("fill_form", {**where, "values": {"identifying_number": "999880503"},
                                                                "out_path": str(tmp_path / "ssn.pdf")}))
            assert any("f1_16[0] (page 1): x 469.00-576.00 -> 468.00-" in c for c in filled["combs_aligned"]), filled
            plain = _data(await client.call_tool("fill_form", {**where, "values": {"name.first": "RILEY"},
                                                               "out_path": str(tmp_path / "name.pdf")}))
            assert plain["combs_aligned"] == []

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


# ── page-header mirrors (Phase K JK28) ─────────────────────────────────────────


def _mirror_blank(path, header_width=200):
    """A two-page blank: Side 1 first/last name, and a page-2 header box (Helv 12) that repeats the name."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    c.acroForm.textfield(name="p1_first", x=72, y=700, width=150, height=18)
    c.acroForm.textfield(name="p1_last", x=240, y=700, width=150, height=18)
    c.showPage()
    c.acroForm.textfield(name="p2_name", x=72, y=700, width=header_width, height=18)
    c.showPage()
    c.save()
    return path


def test_jk28_fill_form_returns_mirrored_and_verify_form_counts_a_wrong_header(tmp_path, monkeypatch):
    """fill_form's result names the header mirrors it built; verify_form's identity section fails a wrong one."""
    import taxfill_mcp.server as server
    from taxfill_core.schemas.formpack import FormPack

    pack = FormPack.model_validate({
        "form": "TEST-M", "jurisdiction": "states/ca", "tax_year": 2025,
        "source_url": "https://www.ftb.ca.gov/forms/2025/test-m.pdf", "pdf_sha256": "...", "acroform_root": "",
        "fields": [{"line": "name.first", "field": "p1_first", "type": "text"},
                   {"line": "name.last", "field": "p1_last", "type": "text"},
                   {"line": "name.full", "field": "p2_name", "type": "text"}],
        "mirrors": {"name.full": "{name.first} {name.last}"},
    })
    blank = _mirror_blank(tmp_path / "blank.pdf")
    monkeypatch.setattr(server, "_load_any_pack", lambda form, year, jurisdiction: pack)
    monkeypatch.setattr(server, "_fetch_pack_blank", lambda p: blank)
    where = {"form": "test_m", "year": 2025, "jurisdiction": "states/ca"}
    person = {"name.first": "Riley", "name.last": "Example"}

    out = str(tmp_path / "built.pdf")
    filled = _data(_run(_call("fill_form", {**where, "values": person, "out_path": out})))
    assert filled["mirrored"] == ["name.full"] and filled["warnings"] == []
    assert filled["written"]["p2_name"] == "Riley Example"
    good = _data(_run(_call("verify_form", {**where, "pdf_path": out})))
    assert good["ok"] is True
    assert good["sections"]["identity"] == {"checked": 1, "failed": 0, "failures": []}

    wrong = str(tmp_path / "wrong.pdf")
    filled = _data(_run(_call("fill_form", {**where, "values": {**person, "name.full": "Someone Else"},
                                            "out_path": wrong})))
    assert filled["mirrored"] == []  # a value the caller passes is written as given
    bad = _data(_run(_call("verify_form", {**where, "pdf_path": wrong})))
    assert bad["ok"] is False
    identity = bad["sections"]["identity"]
    assert (identity["checked"], identity["failed"]) == (1, 1)
    assert "holds 'Someone Else' but its template" in identity["failures"][0]
    assert "builds 'Riley Example'" in identity["failures"][0]


def _abbreviating_pack():
    from taxfill_core.schemas.formpack import FormPack

    return FormPack.model_validate({
        "form": "TEST-M", "jurisdiction": "states/ca", "tax_year": 2025,
        "source_url": "https://www.ftb.ca.gov/forms/2025/test-m.pdf", "pdf_sha256": "...", "acroform_root": "",
        "fields": [{"line": "name.first", "field": "p1_first", "type": "text"},
                   {"line": "name.last", "field": "p1_last", "type": "text"},
                   {"line": "name.full", "field": "p2_name", "type": "text"}],
        "mirrors": {"name.full": "{name.first} {name.last}"},
        "mirror_abbreviations": {"name.full": ["name.first"]},
    })


def test_jk28_get_form_map_shows_the_abbreviation_rule_and_verify_form_honours_it(tmp_path, monkeypatch):
    """A name too wide for its header box may be abbreviated as the pack's mirror_abbreviations allow: get_form_map
    shows the rule, and verify_form passes such a header only when the full name does not fit (Phase K JK28,
    2026-10-16)."""
    import taxfill_mcp.server as server

    fm = _data(_run(_call("get_form_map", {"form": "form540", "year": 2025, "jurisdiction": "states/ca"})))
    assert fm["mirror_abbreviations"] == {"name.full": ["name.first", "name.middle_initial"]}

    pack = _abbreviating_pack()
    monkeypatch.setattr(server, "_load_any_pack", lambda form, year, jurisdiction: pack)
    where = {"form": "test_m", "year": 2025, "jurisdiction": "states/ca"}
    person = {"name.first": "Riley", "name.last": "Example"}

    # 'Riley Example' is 76.7 pt at Helv 12: a 70 pt box holds 68 pt, a 200 pt box all of it
    for width, header, ok in ((70, "R. Example", True), (70, "Riley Exampl", False), (200, "R. Example", False)):
        blank = _mirror_blank(tmp_path / f"blank{width}.pdf", width)
        monkeypatch.setattr(server, "_fetch_pack_blank", lambda p, blank=blank: blank)
        out = str(tmp_path / f"{width}_{ok}.pdf")
        filled = _data(_run(_call("fill_form", {**where, "values": {**person, "name.full": header}, "out_path": out})))
        assert filled["mirrored"] == [] and filled["warnings"] == []  # a value the caller passes is written as given
        report = _data(_run(_call("verify_form", {**where, "pdf_path": out})))
        assert report["ok"] is ok, report["sections"]["identity"]
        assert report["sections"]["identity"]["failed"] == (0 if ok else 1)
        if width == 200:
            assert "but 'Riley Example' fits its box" in report["sections"]["identity"]["failures"][0]


def test_jk28_fill_form_abbreviates_or_leaves_blank_a_header_its_box_cannot_hold(tmp_path, monkeypatch):
    """fill_form measures a built header against its box: it writes the abbreviation the pack allows, with an
    informational warning, or leaves the box blank with a warning to hand-write it; verify_form agrees either way."""
    import taxfill_mcp.server as server

    pack = _abbreviating_pack()
    monkeypatch.setattr(server, "_load_any_pack", lambda form, year, jurisdiction: pack)
    where = {"form": "test_m", "year": 2025, "jurisdiction": "states/ca"}
    person = {"name.first": "Riley", "name.last": "Example"}

    for width, written in ((70, "R Example"), (40, None)):  # 'R Example' is 58.7 pt; a 40 pt box holds 38
        blank = _mirror_blank(tmp_path / f"blank{width}.pdf", width)
        monkeypatch.setattr(server, "_fetch_pack_blank", lambda p, blank=blank: blank)
        out = str(tmp_path / f"filled{width}.pdf")
        filled = _data(_run(_call("fill_form", {**where, "values": person, "out_path": out})))
        (warning,) = filled["warnings"]
        if written:
            assert filled["mirrored"] == ["name.full"] and filled["written"]["p2_name"] == written
            assert warning.startswith("mirror line 'name.full': 'Riley Example' does not fit its box (76.7 pt at Helv "
                                      "12, wider than the 68.0 pt inside its box")
            assert "informational: verify_form accepts it" in warning
        else:
            assert filled["mirrored"] == [] and "p2_name" not in filled["written"]
            assert warning.startswith("mirror line 'name.full' left blank: its box cannot hold 'Riley Example'")
            assert "hand-write it in the box after printing" in warning
        report = _data(_run(_call("verify_form", {**where, "pdf_path": out})))
        assert report["ok"] is True, report["sections"]["identity"]
        identity = report["sections"]["identity"]
        if written:
            assert identity == {"checked": 1, "failed": 0, "failures": []}
        else:  # Phase K JK28 (2026-10-23): the blank header is SKIPPED, and the summary lists it under `skipped`
            (skipped,) = identity.pop("skipped")
            assert identity == {"checked": 1, "failed": 0, "failures": []}
            assert skipped.startswith("page-header mirror 'name.full' is blank: its box cannot hold 'Riley Example'")
            assert "hand-write" in skipped
