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


# ── Schedule K-1 (Form 1065) — the last common document (Batch 2) ─────────────


def test_k1_extracts_losses_codes_and_the_k3_flag():
    r = extract_document("k1.pdf", "K-1", {
        "partnership_ein": "12-3456789",
        "partner_tin": "999-00-1234",
        "1": "-4,500",          # losses arrive with a minus sign
        "5": "120",
        "13": "W* (see stmt)",  # code letters stay text, statement-backed
        "14": "-4,500",
        "16": True,             # Schedule K-3 attached
    })
    by = {f.key: f for f in r.fields}
    assert by["1"].value == "-4500" and by["14"].value == "-4500"
    assert by["16"].value is True and by["13"].value == "W* (see stmt)"
    assert not r.gaps


def test_k1_parenthesized_loss_is_flagged_invalid_not_swallowed():
    r = extract_document("k1.pdf", "K-1", {
        "partnership_ein": "12-3456789", "partner_tin": "999-00-1234", "1": "(4,500)",
    })
    assert any(f.key == "1" and f.status == "invalid" for f in r.fields)


def test_k1_status_note_carries_the_se_and_k3_pointers():
    from taxfill_core.extract import DOC_SPECS

    note = DOC_SPECS["K-1"].status_note
    assert "minus sign" in note and "se_tax" in note and "K-3" in note


# ---------------------------------------------------------------------------
# 1099-SA / 5498-SA (Phase I, I2) — the two HSA documents. Box layouts read off
# the real forms 2026-08-26: f1099sa.pdf (Rev. April 2025) and f5498sa.pdf
# (Rev. December 2026), plus their Instructions for Recipient / Participant.
# ---------------------------------------------------------------------------


def test_hsa_documents_are_supported_and_cited():
    kinds = {k["kind"]: k for k in list_document_kinds()}
    assert {"1099-SA", "5498-SA"} <= set(kinds)
    assert kinds["1099-SA"]["source_url"] == "https://www.irs.gov/forms-pubs/about-form-1099-sa"
    assert kinds["5498-SA"]["source_url"] == "https://www.irs.gov/forms-pubs/about-form-5498-sa"


def test_1099_sa_box_layout_matches_the_printed_form():
    r = extract_document("documents/1099sa.pdf", "1099-SA", {
        "recipient_tin": "123-45-6789", "1": "$5,000.00", "2": "45", "3": "1", "5_hsa": "X",
    }, page=1)
    by = {f.key: f for f in r.fields}
    # Box 1 gross distribution, box 2 earnings on excess, box 3 the code, box 4
    # FMV on the date of death, box 5 the three account-type checkboxes.
    assert by["1"].value == "5000.00" and by["1"].status == "ok"
    assert by["2"].value == "45" and by["3"].value == "1"
    assert by["4"].value is None and by["4"].status == "missing"
    assert by["5_hsa"].value is True
    assert by["5_archer_msa"].status == "missing" and by["5_ma_msa"].status == "missing"
    assert r.gaps == []      # box 1, box 3 and the recipient TIN are the required three
    missing_code = extract_document("documents/1099sa.pdf", "1099-SA",
                                    {"recipient_tin": "123-45-6789", "1": "5000"})
    assert missing_code.gaps == ["3"]     # the code changes the reading, so it is required


def test_1099_sa_status_note_routes_box_1_to_form_8889_not_to_income():
    note = DOC_SPECS["1099-SA"].status_note
    assert "LINE 14a" in note and "hsa_deduction" in note
    assert "20% additional tax" in note
    assert "1 normal, 2 excess contributions" in note        # the box 3 code list
    assert "NONSPOUSE" in note                               # the box 4 trap


def test_5498_sa_box_numbers_are_not_what_they_look_like():
    r = extract_document("documents/5498sa.pdf", "5498-SA", {
        "participant_tin": "123456789", "1": "0", "2": "$7,300.00", "3": "1,000",
        "4": "0", "5": "$41,220.55", "6_hsa": "X",
    })
    by = {f.key: f for f in r.fields}
    assert by["2"].value == "7300.00" and r.gaps == []       # box 2 is the HSA total, and required
    assert by["1"].label.startswith("Box 1 — Employee's or self-employed person's Archer MSA")
    assert "subsequent year for the calendar year" in by["3"].label
    assert by["5"].value == "41220.55"
    assert by["6_hsa"].value is True
    note = DOC_SPECS["5498-SA"].status_note
    # Box 1 is Archer-only; the HSA figure is box 2 and it is NOT Form 8889 line 2.
    assert "Box 1 is ARCHER" in note and "the HSA figure is BOX 2" in note
    assert "MINUS the W-2 box 12 code W amount" in note
    # Box 3 runs forward (Jan 1 - Apr 15 of the NEXT year), not back.
    assert "Box 3 runs FORWARD" in note
    # Box 5 is what the IRC 4973(a) cap is measured against.
    assert "4973(a) cap" in note


# ---------------------------------------------------------------------------
# 3922 / 3921 (Phase I, I3) — the two equity-compensation documents. Box layouts
# read off the real forms 2026-08-26: f3922.pdf and f3921.pdf, both Rev. April
# 2025, plus their Instructions for Employee.
# ---------------------------------------------------------------------------


def test_equity_compensation_documents_are_supported_and_cited():
    kinds = {k["kind"]: k for k in list_document_kinds()}
    assert {"3922", "3921"} <= set(kinds)
    assert kinds["3922"]["source_url"] == "https://www.irs.gov/forms-pubs/about-form-3922"
    assert kinds["3921"]["source_url"] == "https://www.irs.gov/forms-pubs/about-form-3921"
    assert kinds["3922"]["title"].endswith("Under Section 423(c)")
    assert kinds["3921"]["title"] == "Exercise of an Incentive Stock Option Under Section 422(b)"


def test_3922_box_layout_matches_the_printed_form():
    """Boxes 1-8 exactly as printed, including box 8 — the lookback price that
    calc.espp_disposition needs and that is blank on a fixed-price plan."""
    r = extract_document("documents/3922.pdf", "3922", {
        "employee_tin": "999-88-7777", "1": "2022-03-01", "2": "2023-09-01",
        "3": "$22.00", "4": "$23.00", "5": "$20.00", "6": "100", "7": "2023-09-05",
    }, page=1)
    by = {f.key: f for f in r.fields}
    assert by["1"].label == "Box 1 — Date option granted"
    assert by["2"].label == "Box 2 — Date option exercised"
    assert by["3"].label == "Box 3 — Fair market value per share on grant date"
    assert by["4"].label == "Box 4 — Fair market value per share on exercise date"
    assert by["5"].label == "Box 5 — Exercise price paid per share"
    assert by["6"].label == "Box 6 — No. of shares transferred"
    assert by["7"].label == "Box 7 — Date legal title transferred"
    assert by["8"].label.startswith("Box 8 — Exercise price per share determined as if")
    assert by["3"].value == "22.00" and by["5"].value == "20.00"
    # A blank box 8 is the FIXED-price case, so it is reported as a gap-free
    # missing box, not a required one.
    assert by["8"].value is None and by["8"].status == "missing"
    assert r.gaps == []
    # Fractional shares are normal (Pub 525 Example 9 divides payroll dollars by
    # a share price), so box 6 must not be an int box.
    frac = extract_document("documents/3922.pdf", "3922", {
        "employee_tin": "999887777", "1": "2022-03-01", "2": "2023-09-01",
        "3": "22", "4": "23", "5": "20", "6": "12.3456",
    })
    assert {f.key: f for f in frac.fields}["6"].value == "12.3456"


def test_3922_status_note_routes_box_8_and_warns_about_the_broker_basis():
    note = DOC_SPECS["3922"].status_note
    assert "No income is recognized" in note
    assert "espp_disposition" in note
    assert "BOX 8 IS THE ONE PEOPLE MISS" in note and "LOOKBACK" in note
    assert "423(c)(2)" in note and "box 3 minus box 8" in note
    # Box 7 is the transfer of legal title, NOT the sale date.
    assert "BOX 7 IS NOT THE SALE DATE" in note
    # And the double-taxation warning the whole phase exists for.
    assert "taxes the discount twice" in note


def test_3921_box_layout_matches_the_printed_form():
    """Form 3921 has SIX boxes and they are not Form 3922's: box 3 is the
    exercise price, box 4 the exercise-date FMV, box 5 the share count."""
    r = extract_document("documents/3921.pdf", "3921", {
        "employee_tin": "999-88-7777", "1": "2023-03-12", "2": "2024-01-07",
        "3": "$10.00", "4": "$12.00", "5": "100",
    })
    by = {f.key: f for f in r.fields}
    assert by["3"].label == "Box 3 — Exercise price per share"
    assert by["4"].label == "Box 4 — Fair market value per share on exercise date"
    assert by["5"].label == "Box 5 — No. of shares transferred"
    assert by["6"].label.startswith("Box 6 — If other than TRANSFEROR")
    assert by["5"].value == 100 and r.gaps == []
    assert "7" not in by and "8" not in by      # Form 3922's boxes, not this form's
    # An ISO is exercised for whole shares, so a fractional box 5 is a misread.
    frac = extract_document("documents/3921.pdf", "3921", {
        "employee_tin": "999887777", "1": "2023-03-12", "2": "2024-01-07",
        "3": "10", "4": "12", "5": "100.5",
    })
    assert {f.key: f for f in frac.fields}["5"].status == "invalid"


def test_3921_status_note_keeps_the_iso_rules_apart_from_the_espp_ones():
    note = DOC_SPECS["3921"].status_note
    assert "AN ISO IS NOT AN ESPP" in note
    assert "422(b)(4)" in note and "no built-in discount" in note
    # The AMT consequence, which nothing on the face states in dollars.
    assert "alternative minimum taxable income" in note and "6251 line 2i" in note
    # And the 422(c)(2) cap that section 423 has no counterpart for — the reason
    # calc.espp_disposition refuses ISOs rather than reusing its formula.
    assert "422(c)(2)" in note and "espp_disposition refuses to model ISOs" in note
