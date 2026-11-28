"""The first walkthrough's Form 8995 through the tools as an agent calls them (Phase K-W JW2d, finding P1-01; P-039).

A fictitious single filer whose only QBI item is $40 of section 199A dividends (Form 1099-DIV box 5). Before JW2d
list_forms showed no Form 8995, calc had no QBI op and extract_document said only that box 5 is part of box 1a.
"""

from __future__ import annotations

from taxfill_mcp.server import calc, extract_document, list_forms


def test_list_forms_shows_the_2025_form_8995_pack():
    [pack] = [p for p in list_forms("federal", 2025) if p["form_key"] == "f8995"]
    assert (pack["form"], pack["num_fields"], pack["source_status"]) == ("8995", 33, "final")
    assert pack["has_relations"] and pack["has_cross_form"]
    assert not [p for p in list_forms("federal", 2024) if p["form_key"] == "f8995"]   # TY2025 only


def test_extract_then_calc_gives_the_deduction_and_the_lines_to_fill():
    doc = extract_document("documents/example-1099div.pdf", "1099-DIV",
                           {"payer_name": "Example Index Fund", "1a": "1,900.00", "1b": "1,860.00", "5": "40.00"},
                           tax_year=2025)
    [finding] = [f for f in doc["findings"] if f["rule_id"] == "V31"]
    assert "Form 8995 line 6" in finding["message"] and "45 days" in finding["message"]
    out = calc("qbi_deduction", {"taxable_income_before_qbi": 169907, "filing_status": "single", "year": 2025,
                                 "qualified_reit_dividends": 40, "qualified_dividends": 1900,
                                 "schedule_d_long_term": 2800, "schedule_d_net": 2800})
    assert out["deduction"] == 8 and out["lines"]["15"] == 8 and out["independent"]["6"] == 40
    assert out["confirm"] and "holding period" in out["confirm"][0]


def test_above_the_threshold_the_op_refuses_with_no_number():
    try:
        calc("qbi_deduction", {"taxable_income_before_qbi": 197301, "filing_status": "single", "year": 2025,
                               "qualified_reit_dividends": 40})
    except ValueError as err:
        assert "REFUSED" in str(err) and "Form 8995-A" in str(err)
    else:
        raise AssertionError("qbi_deduction above the threshold must refuse")


def test_describe_names_the_op():
    text = calc("describe", {"op": "qbi_deduction"})["text"]
    assert "taxable_income_before_qbi" in text and "REFUSES" in text and "8995-A" in text
