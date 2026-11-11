"""P-036 through the MCP tools: a line the blank cannot take (two printed rows on one field).

Arizona's 2026-11-02 revision of the 2025 Form 140 names line 16 and line 27 with one field. The tools must tell
the agent before the fill, refuse the value, count the hand-written amount once it is declared, and SHOW every
declared amount — a declaration is taken on the caller's word, so it must never close a relation without a trace.
Demo values only.
"""
from __future__ import annotations

import pytest

import taxfill_mcp.server as server

AZ = {"form": "az140", "year": 2025, "jurisdiction": "states/az"}
IDENTITY = {"tp_first_name_and_initial": "T", "tp_last_name": "DEMO", "tp_ssn": "999887777",
            "7_filing_status::single": True}


def test_get_form_map_lists_the_unfillable_lines_with_their_reasons():
    unfillable = server.get_form_map(**AZ)["unfillable_lines"]
    assert {"16", "27"} <= set(unfillable) and len(unfillable) == 8
    assert all(isinstance(why, str) and "hand-write" in why for why in unfillable.values())
    assert server.get_form_map("f1040", 2025)["unfillable_lines"] == {}


def test_the_tool_docstrings_say_what_to_do_with_an_unfillable_line():
    for tool in (server.get_form_map, server.fill_form, server.verify_form, server.verify_filing):
        assert "unfillable_lines" in (tool.__doc__ or ""), tool.__name__


@pytest.mark.network
def test_a_hand_written_line_16_through_fill_verify_form_and_verify_filing(tmp_path):
    out = str(tmp_path / "az140.pdf")
    values = {**IDENTITY, "12": 100000, "14": 100000, "19": 105000}
    with pytest.raises(ValueError, match=r"line\(s\) \['16'\] cannot be written.*expected=\{'16': <amount>\}"):
        server.fill_form(values={**values, "16": 5000}, out_path=out, **AZ)
    filled = server.fill_form(values=values, out_path=out, **AZ)["out_path"]

    # verify_form: undeclared fails and says to declare; declared passes and shows the hand-written line
    undeclared = server.verify_form(pdf_path=filled, expected=values, **AZ)
    assert not undeclared["ok"]
    assert any("line(s) ['16'] cannot be written on this blank" in f for f in undeclared["sections"]["relations"]["failures"])
    declared = server.verify_form(pdf_path=filled, expected={**values, "16": 5000}, **AZ)
    assert not declared["sections"]["relations"]["failures"] and not declared["sections"]["assertions"]["failures"]
    assert any("hand-write 5000" in s and "counted 5000" in s for s in declared["sections"]["assertions"]["skipped"])

    # verify_filing: the item's `expected` reaches the relation, and the declared amount is listed
    item = {"form": "az140", "year": 2025, "jurisdiction": "states/az", "pdf_path": filled}
    bare = server.verify_filing([item])
    assert any("az140: relation '19 ==" in f and "cannot be written" in f for f in bare["sections"]["relations"]["failures"])
    with_amount = server.verify_filing([{**item, "expected": {"16": 5000}}])
    assert not with_amount["sections"]["relations"]["failures"]
    skipped = with_amount["sections"]["assertions"]["skipped"]
    assert any("hand-write 5000" in s and "19 == 14 + 15 + 16 + 17 + 18" in s for s in skipped), skipped
    # a line no relation reads: shown, and said to be unchecked
    row_27 = server.verify_filing([{**item, "expected": {"16": 5000, "27": 777}}])["sections"]["assertions"]["skipped"]
    assert any("hand-write 777" in s and "nothing checked the amount" in s for s in row_27)
    with pytest.raises(ValueError, match="verify_filing item 'az140': `expected` must be a dict"):
        server.verify_filing([{**item, "expected": [5000]}])
