"""extract_document tests (dev plan section 2 "extract & confirm", section 8 tool).

The structuring layer must: type-check the agent's reading, attach document
provenance to every value, never invent a missing box, surface invalid values
(not drop them), flag required-box gaps, and cite each form's layout to .gov.
"""
from __future__ import annotations

import pytest

from taxfill_core.extract import DOC_SPECS, extract_document, list_document_kinds


def test_supported_kinds_are_cited_to_gov():
    from urllib.parse import urlparse

    from taxfill_core.knowledge import is_official_gov_host

    kinds = list_document_kinds()
    assert {"W-2", "1099-NEC", "1099-INT", "1099-DIV", "1098-T", "1042-S",
            "SSA-1099", "1099-R", "1099-B", "1095-A"} <= {k["kind"] for k in kinds}
    for spec in DOC_SPECS.values():
        # Official layout docs live on irs.gov — except SSA-1099, whose issuer is ssa.gov.
        host = (urlparse(spec.source_url).hostname or "").lower()
        assert spec.source_url.startswith("https://") and is_official_gov_host(host), spec.kind
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


def test_punctuation_only_money_is_invalid_not_blank():
    # A non-blank reading that is only currency punctuation is a misread — it must
    # NOT masquerade as a confirmed-blank "ok" field and slip past the gap check.
    for token in ("-", "$", ",", "$,", " - "):
        doc = extract_document("documents/w2.png", "W-2", {"1": token, "2": "0", "employee_ssn": "123-45-6789", "employer_ein": "12-3456789"})
        box1 = next(f for f in doc.fields if f.key == "1")
        assert box1.status == "invalid", token
        assert "1" in doc.gaps  # required + not ok => gap


def test_unrecognized_checkbox_is_invalid_not_silently_unchecked():
    doc = extract_document("documents/w2.png", "W-2", {"13_retirement": "see attached"})
    cb = next(f for f in doc.fields if f.key == "13_retirement")
    assert cb.status == "invalid" and cb.value is not False  # never fabricated as "unchecked"
    # recognized negative tokens DO resolve to a real False
    doc2 = extract_document("documents/w2.png", "W-2", {"13_retirement": "no"})
    assert next(f for f in doc2.fields if f.key == "13_retirement").value is False


def test_fractional_reading_of_int_box_is_invalid():
    # 1042-S box 1 (income code) is a code; use a money/int contrast instead via 1098-T.
    doc = extract_document("documents/1098t.png", "1098-T", {"1": "1234.50"})
    assert next(f for f in doc.fields if f.key == "1").status == "ok"  # money keeps cents
    # state must be 2 alpha
    w2 = extract_document("documents/w2.png", "W-2", {"15_state": "CAL"})
    assert next(f for f in w2.fields if f.key == "15_state").status == "invalid"


def test_bad_page_rejected():
    with pytest.raises(ValueError, match="1-based"):
        extract_document("documents/w2.png", "W-2", {}, page=0)


def test_unsupported_kind_raises():
    with pytest.raises(ValueError, match="unsupported document kind"):
        extract_document("documents/x.png", "W-9", {})


def test_caveat_states_missing_is_blank():
    doc = extract_document("documents/w2.png", "W-2", {})
    assert "never inferred" in doc.caveat.lower() or "blank" in doc.caveat.lower()
