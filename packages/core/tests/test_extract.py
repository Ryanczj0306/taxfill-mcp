"""extract_document tests (dev plan section 2 "extract & confirm", section 8 tool).

The structuring layer must: type-check the agent's reading, attach document
provenance to every value, never invent a missing box, surface invalid values
(not drop them), flag required-box gaps, and cite each form's layout to .gov.
"""
from __future__ import annotations

import pytest

from taxfill_core.extract import DOC_SPECS, extract_document, list_document_kinds


def test_supported_kinds_are_cited_to_gov():
    kinds = list_document_kinds()
    assert {"W-2", "1099-NEC", "1099-INT", "1099-DIV", "1098-T", "1042-S"} <= {k["kind"] for k in kinds}
    for spec in DOC_SPECS.values():
        assert spec.source_url.startswith("https://www.irs.gov/"), spec.kind
        assert spec.boxes


def test_w2_happy_path_types_and_provenance():
    doc = extract_document(
        "documents/w2_acme.png",
        "W-2",
        {"employee_ssn": "123-45-6789", "employer_ein": "12 3456789", "1": "$52,000.00", "2": "6,100", "15_state": "ca", "13_retirement": "X"},
        page=1,
    )
    by = {f.key: f for f in doc.fields}
    assert by["1"].value == "52000.00" and by["1"].status == "ok"
    assert by["2"].value == "6100" and by["2"].status == "ok"
    assert by["employee_ssn"].value == "123-45-6789"
    assert by["employer_ein"].value == "12-3456789"  # normalized
    assert by["15_state"].value == "CA"
    assert by["13_retirement"].value is True
    # every field carries document provenance pointing at the source file+page
    assert all(f.provenance.kind == "document" and f.provenance.file == "documents/w2_acme.png" and f.provenance.page == 1 for f in doc.fields)
    assert doc.citation["url"].startswith("https://www.irs.gov/")
    assert doc.gaps == []  # all required boxes read


def test_missing_box_is_none_never_guessed():
    # Only box 1 read; box 2 (required) and everything else must be None/missing.
    doc = extract_document("documents/w2.png", "W-2", {"1": "40000"})
    by = {f.key: f for f in doc.fields}
    assert by["1"].value == "40000" and by["1"].status == "ok"
    assert by["2"].value is None and by["2"].status == "missing"
    assert by["3"].value is None and by["3"].status == "missing"
    # required-but-unread boxes surface as gaps (here SSN, EIN, box 2)
    assert set(doc.gaps) == {"employee_ssn", "employer_ein", "2"}


def test_invalid_value_is_surfaced_not_dropped():
    doc = extract_document("documents/w2.png", "W-2", {"employee_ssn": "1", "employer_ein": "12-3456789", "1": "not-a-number", "2": "100"})
    by = {f.key: f for f in doc.fields}
    assert by["1"].status == "invalid" and by["1"].raw == "not-a-number"
    assert by["employee_ssn"].status == "invalid"  # too few digits
    assert "1" in doc.gaps and "employee_ssn" in doc.gaps  # invalid required boxes are gaps


def test_unexpected_keys_are_reported():
    doc = extract_document("documents/w2.png", "W-2", {"1": "10000", "2": "0", "employee_ssn": "123-45-6789", "employer_ein": "12-3456789", "box_99": "x"})
    assert "box_99" in doc.unexpected


def test_1042s_nra_required_boxes():
    # The NRA/treaty document: income code + gross income are required.
    doc = extract_document("documents/1042s.png", "1042-S", {"1": "20", "2": "15000", "7a": "0"})
    by = {f.key: f for f in doc.fields}
    assert by["1"].value == "20" and by["2"].value == "15000"
    assert by["7a"].value == "0"
    assert doc.gaps == []


def test_unsupported_kind_raises():
    with pytest.raises(ValueError, match="unsupported document kind"):
        extract_document("documents/x.png", "W-9", {})


def test_caveat_states_missing_is_blank():
    doc = extract_document("documents/w2.png", "W-2", {})
    assert "never inferred" in doc.caveat.lower() or "blank" in doc.caveat.lower()
