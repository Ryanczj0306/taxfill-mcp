"""The first end-to-end walkthrough's filer, through the tools as an agent calls them (Phase K-W, JW2a).

Findings P1-07, P1-06, P1-10 and the estimate part of P1-18: with only the installed product, an agent handed
this filer the standard deduction and a single figure while the W-2 already showed otherwise. Every person here
is fictitious: single, California, tax year 2025, one W-2 (box 1 177,425; box 2 34,180; box 17 state income tax
14,250; box 14 state disability insurance 2,479.50), interest 2,450, ordinary dividends 2,400 of which 1,900
qualified, capital gains, an HSA, a backdoor Roth.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session as connect

from taxfill_mcp.server import mcp

REPO = Path(__file__).resolve().parents[3]
YEAR = 2025
STANDARD_DEDUCTION = 15_750     # knowledge/federal/2025.yaml, single
STATED = {"kind": "user_stated"}

W2 = {   # as printed: boxes 4 and 6 carry cents (main refused them)
    "employer": "Example Systems", "box1": 177_425, "box2": 34_180, "box3": 176_100, "box4": 10_918.20,
    "box5": 200_925, "box6": 2_921.74, "box17": 14_250,
    "box12": [{"code": "D", "amount": 23_500}, {"code": "W", "amount": 4_300}],
}
BOX14_SDI = 2_479.50
INCOME = {
    "w2s": [W2], "interest": 2_450, "dividends": 2_400, "qualified_dividends": 1_900,
    "capital_gain_long": 2_800, "capital_gain_short": 2_300,
    "retirement_distributions": [{
        "gross": 7_010, "taxable_amount": 7_010, "taxable_not_determined": True, "codes": "2",
        "ira_sep_simple": True, "converted_to_roth": True, "label": "backdoor Roth conversion",
    }],
    "ira_pool": {"basis_carryforward": 0, "nondeductible_contributions_this_year": 7_000, "dec31_total_value": 0},
}
DOCUMENTS = [
    ("W-2", "have"), ("1099-INT", "have"), ("1099-DIV", "have"), ("1099-B", "have"), ("1099-R", "have"),
    ("Form 5498", "have"), ("1095-A", "not_applicable"), ("foreign account statement", "not_applicable"),
]
EVERY_FILER = ["itemizable_items", "estimated_payments", "extension", "prior_year_overpayment_applied"]
FOLLOW_UPS = ["w2_box14", "hsa_coverage", "ira_basis", "employer_stock_sales", "dividend_boxes"]


def _call(name: str, args: dict):
    async def go():
        async with connect(mcp) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


def _data(result) -> dict:
    assert result.isError is not True, result.content[0].text
    if result.structuredContent is not None:
        return result.structuredContent.get("result", result.structuredContent)
    return json.loads(result.content[0].text)


def _answer(value):
    return {"value": value, "provenance": STATED}


def _profile(example: dict) -> dict:
    """The filer's profile, built in the shape the start state's example_profile shows."""
    profile = copy.deepcopy(example)
    profile["identity"]["dob"] = _answer("1990-04-02")
    profile["household"].update(hoh_qualifying_person=_answer(False), no_other_taxpayers=_answer(True))
    profile["income_documents"] = [{"kind": kind, "status": status, "provenance": STATED} for kind, status in DOCUMENTS]
    profile["deductions_and_payments"] = {}
    del profile["prior_filings"]            # not asked yet
    return profile


def _entry(estimate: dict, start: str) -> str | None:
    return next((f for f in estimate["roadmap"]["returns_and_forms"] if f.startswith(start)), None)


def test_the_walkthrough_filer_end_to_end():
    # 1. The start state hands over the profile's shape; the agent builds the filer's profile from it.
    start = _data(_call("intake_checklist", {"tax_year": YEAR}))
    assert start["ready_to_fill"] is False and start["example_profile"]["identity"]["name"]["provenance"] == STATED
    profile = _profile(start["example_profile"])

    # 2. Identity, a filing status and documents in hand are not enough: the deductions-and-payments questions
    #    hold readiness back, and the result names them.
    asked = _data(_call("intake_checklist", {"profile": profile, "tax_year": YEAR}))
    expected = [f"deductions_and_payments.{f}" for f in (*EVERY_FILER, *FOLLOW_UPS)]
    assert asked["ready_to_fill"] is False and asked["ready_to_fill_blockers"] == expected
    by_id = {q["id"]: q for q in asked["next_questions"]}
    assert by_id["deductions_and_payments.w2_box14"]["answers_into"] == "deductions_and_payments.2025.w2_box14"
    assert by_id["prior_filings.history"]["answers_into"].startswith("prior_filings.filed_years")
    assert {d["kind"]: d["status"] for d in asked["required_documents"]}["1095-A"] == "not_applicable"

    # 3. The estimate from the documents alone: the W-2's box 17 is close to the standard deduction, so the
    #    result says to compare itemizing and names what to collect — and invents no range.
    first = _data(_call("estimate_refund", {"profile": profile, "year": YEAR, "income": INCOME}))
    comparison = first["itemizing_comparison"]
    assert comparison["verdict"] == "close" and comparison["standard_deduction"] == STANDARD_DEDUCTION
    assert comparison["state_local_tax_paid"] == 14_250
    assert first["low"] == first["high"] == first["point"]
    assert any(a.startswith("Compare itemizing with the standard deduction") for a in first["assumptions"])
    collect = next(c for c in first["what_would_change_it"] if "collect the other Schedule A items" in c)
    for item in ("state disability", "vehicle licence", "real estate tax", "mortgage interest", "gifts to charity",
                 "medical"):
        assert item in collect, item
    assert _entry(first, "Compare: Schedule A") is not None

    # 4. With the box 14 state disability insurance the interview asks for, the state and local tax alone is over
    #    the standard deduction: the range contains the itemized outcome and the result says so.
    income = {**INCOME, "other_state_local_taxes": BOX14_SDI}
    second = _data(_call("estimate_refund", {"profile": profile, "year": YEAR, "income": income}))
    comparison = second["itemizing_comparison"]
    salt = comparison["deductible"]
    assert comparison["verdict"] == "exceeds_standard" and salt == 16_730 > STANDARD_DEDUCTION
    itemized = _data(_call("estimate_refund", {
        "profile": profile, "year": YEAR, "income": {**INCOME, "itemized_deductions": salt}}))
    assert itemized["low"] == itemized["high"] == itemized["point"] > first["point"]
    assert second["low"] <= itemized["point"] <= second["high"] and second["low"] < second["high"]
    assert comparison["itemized_bottom_line"] == itemized["point"] == second["high"]
    assert second["point"] == first["point"] == second["low"]      # the point waits for itemized_deductions
    note = next(a for a in second["assumptions"] if a.startswith("Compare itemizing with the standard deduction"))
    assert "the range includes it" in note and "MORE than the $15,750 standard deduction" in note
    assert any("collect the other Schedule A items" in c for c in second["what_would_change_it"])

    # The roadmap is built from the inputs, names the state return and says the figures are federal only.
    for start_of_entry in ("Form 1040", "Likely: Schedule A (Form 1040)", "Likely: Schedule B (Form 1040)",
                           "Likely: Schedule D (Form 1040)", "Likely: Form 8949", "Likely: Form 8889",
                           "Likely: Form 8606", "Likely: Form 8959", "State return: CA resident return"):
        assert _entry(second, start_of_entry) is not None, start_of_entry
    assert "540" in _entry(second, "State return: CA") and "not estimated" in _entry(second, "State return: CA")
    assert "NOT exhaustive" in second["roadmap"]["note"] and "FEDERAL return only" in second["roadmap"]["note"]

    # No document the profile records as not_applicable is called missing or unconfirmed.
    for estimate in (first, second):
        assert estimate["roadmap"]["missing_documents"] == []
        assert not any("unconfirmed or missing documents" in c for c in estimate["what_would_change_it"])
        said_missing = [line for line in (*estimate["assumptions"], *estimate["what_would_change_it"])
                        if "missing" in line.lower() or "unconfirmed" in line.lower()]
        assert not any("1095-A" in line or "foreign account" in line for line in said_missing)

    # 5. ready_to_fill stays false until every deductions-and-payments question is answered.
    answers = {f: _answer("none") for f in (*EVERY_FILER, *FOLLOW_UPS)}
    answers["w2_box14"] = _answer("CASDI 2,479.50")
    answers["extension"] = _answer("unknown")
    profile["prior_filings"] = {"filed_years": _answer([2024])}
    for held_back in FOLLOW_UPS[-1:] + EVERY_FILER[:1]:
        partial = {**profile, "deductions_and_payments": {str(YEAR): {k: v for k, v in answers.items() if k != held_back}}}
        result = _data(_call("intake_checklist", {"profile": partial, "tax_year": YEAR}))
        assert result["ready_to_fill"] is False
        assert result["ready_to_fill_blockers"] == [f"deductions_and_payments.{held_back}"]
    profile["deductions_and_payments"] = {str(YEAR): answers}
    done = _data(_call("intake_checklist", {"profile": profile, "tax_year": YEAR}))
    assert done["ready_to_fill"] is True and done["ready_to_fill_blockers"] == [] and done["next_questions"] == []


def test_the_example_profile_is_accepted_by_the_tools_that_take_a_profile():
    example = _data(_call("intake_checklist", {}))["example_profile"]
    year = int(next(iter(example["state_footprint"])))
    scope = _data(_call("state_scope", {"profile": example, "year": year}))
    assert [s["state"] for s in scope["states"] if s["must_file"]] == ["CA"]
    estimate = _data(_call("estimate_refund", {
        "profile": example, "year": year, "income": {"wages": 60_000, "federal_withholding": 7_000}}))
    assert estimate["roadmap"]["missing_documents"] == ["1099-INT"]   # 'missing' is; 'not_applicable' is not
    assert _entry(estimate, "State return: CA resident return") is not None


def test_a_wrong_shaped_profile_error_points_at_the_example_and_echoes_no_value():
    bad = {"identity": {"name": "Avery Example", "tax_id": "999-88-0001"}}      # bare values, not {value, provenance}
    result = _call("intake_checklist", {"profile": bad})
    assert result.isError is True
    text = result.content[0].text
    assert "identity.name" in text and "example_profile" in text and "answers_into" in text
    assert "Avery" not in text and "999-88-0001" not in text


def test_the_surfaces_name_the_new_inputs_and_result_fields():
    async def descriptions():
        return {t.name: t.description for t in await mcp.list_tools()}

    tools = asyncio.run(descriptions())
    for word in ("example_profile", "answers_into", "ready_to_fill_blockers", "deductions_and_payments"):
        assert word in tools["intake_checklist"], word
    for word in ("box17", "other_state_local_taxes", "foreign_tax_paid", "itemizing_comparison",
                 "returns_and_forms", "federal return only"):
        assert word in tools["estimate_refund"], word
    files = {name: (REPO / path).read_text(encoding="utf-8") for name, path in (
        ("claude", "skills/claude/SKILL.md"), ("codex", "skills/codex/AGENTS.md"),
        ("copilot", "skills/copilot/instructions.md"), ("tools", "docs/TOOLS.md"))}
    for name, text in files.items():
        for word in ("example_profile", "ready_to_fill_blockers", "itemizing_comparison", "other_state_local_taxes",
                     "box17", "returns_and_forms"):
            assert word in text, (name, word)
