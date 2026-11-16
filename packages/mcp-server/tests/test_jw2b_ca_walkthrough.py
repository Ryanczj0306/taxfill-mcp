"""The first walkthrough's California filer, through the tools as an agent calls them (Phase K-W JW2b; P-038).

Findings P1-08 and P1-03. The filer is fictitious: single, a full-year California resident in tax year 2025, one W-2
whose box 12 carries code W (HSA contributions, 4,300), U.S. Treasury interest, capital gains; the federal return
attaches Schedule D, Form 8949, Form 8889 and others. With only the installed product an agent got the California
return right only by reading the FTB booklet itself: nothing said that the HSA contribution is added back on Schedule
CA (540) line 1h, column C, that Treasury interest is subtracted on line 2, column B, or that a copy of the federal
return goes with Form 540. The tools now say each, from the cited TY2025 California pack.
"""
from __future__ import annotations

import asyncio
import json

from mcp.shared.memory import create_connected_server_and_client_session as connect

from taxfill_mcp.server import mcp

YEAR = 2025
STATED = {"kind": "user_stated"}
PROFILE = {"state_footprint": {str(YEAR): {
    "lived": [{"state": "CA", "start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31", "provenance": STATED}],
    "worked": [{"state": "CA", "start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31", "provenance": STATED}],
}}}
FEDERAL_ATTACHED = ["Schedule 1", "Schedule 2", "Schedule A", "Schedule B", "Schedule D", "8949", "8889", "8606",
                    "8959"]
IF_YES = ("If Yes, attach a copy of your federal Form 1040 or 1040-SR return and all supporting federal forms and "
          "schedules to Form 540.")


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


def _manifest(*federal_attached: str) -> list[dict]:
    return [
        {"form": "1040", "tax_year": YEAR, "bottom_line": -1_200, "state": "CA",
         "attached_forms": list(federal_attached)},
        {"form": "540", "tax_year": YEAR, "jurisdiction": "states/ca", "bottom_line": 350},
    ]


def _ca_assemble(manifest: list[dict]) -> list[str]:
    returns = _data(_call("file_and_pay", {"manifest": manifest}))["returns"]
    return next(r for r in returns if r["jurisdiction"] == "states/ca")["assemble"]


def test_p038_state_scope_names_the_hsa_addition_and_the_treasury_subtraction():
    scope = _data(_call("state_scope", {"profile": PROFILE, "year": YEAR}))
    ca = next(s for s in scope["states"] if s["state"] == "CA")
    assert ca["filing_role"] == "resident" and ca["forms"] == ["540", "Schedule CA"]
    line = next(w for w in ca["warnings"] if w.startswith("CA adjustments (Schedule CA (540)"))
    assert "box 12, code W on line 1h, column C" in line and "line 1h, column C (raises CA AGI)" in line
    assert "U.S. Treasury bills, notes, and bonds" in line and "line 2, column B (lowers CA AGI)" in line


def test_p038_state_tax_says_what_california_agi_must_carry():
    result = _data(_call("calc", {"op": "state_tax", "args": {"state": "ca", "taxable_base": 178_000, "year": YEAR}}))
    work = result["work"]
    assert "CA AGI (Form 540 line 17) must already carry" in work
    assert "Employer HSA contribution (federal Form W-2, box 12, code W): Schedule CA (540), Part I, Section A, " \
           "line 1h, column C (raises CA AGI)" in work
    assert "line 2, column B (lowers CA AGI)" in work


def test_the_walkthrough_filers_california_checklist_carries_the_federal_copy():
    lines = _ca_assemble(_manifest(*FEDERAL_ATTACHED))
    copy = next(line for line in lines if line.startswith("Federal return copy:"))
    assert copy.startswith("Federal return copy: Yes.") and IF_YES in copy
    assert "Schedule D, Form 8949, Form 8889" in copy
    assert any("to the lower front of your tax return" in line for line in lines)
    assert any("send all six sides" in line for line in lines)
    assert any("Attach this schedule behind Form 540, Side 6" in line for line in lines)


def test_a_federal_return_with_only_schedules_a_and_b_gets_no_federal_copy():
    lines = _ca_assemble(_manifest("Schedule A", "Schedule B"))
    copy = next(line for line in lines if line.startswith("Federal return copy:"))
    assert copy.startswith("Federal return copy: No.") and IF_YES not in copy
    assert "do not attach a copy of your federal Form 1040 or 1040-SR return to Form 540" in copy
