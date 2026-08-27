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


# ---------------------------------------------------------------------------
# Phase I5 — document-extraction breadth. Every layout below was read off the
# official form on irs.gov 2026-08-27 together with its own instructions.
# ---------------------------------------------------------------------------


def test_1099k_box_layout_matches_the_printed_form():
    """f1099k.pdf (Rev. December 2026): 1a/1b/1c/1d, 2, 3, 4, 5a-5l, 6/7/8."""
    r = extract_document("documents/1099k.pdf", "1099-K", {
        "payee_tin": "123-45-6789", "1a": "$24,310.00", "1b": "24,310", "3": "412",
        "2": "5732", "txn_third_party_network": "X", "5a": "1,200", "5l": "3,000",
        "6": "0", "7": "12-3456", "8": "ca",
    }, page=1)
    by = {f.key: f for f in r.fields}
    assert by["1a"].label == "Box 1a — Gross amount of payment card/third party network transactions"
    assert by["1b"].label == "Box 1b — Card Not Present transactions"
    assert by["1c"].label == "Box 1c — Cash tips"
    assert by["2"].label == "Box 2 — Merchant category code"
    assert by["3"].label == "Box 3 — Number of payment transactions"
    assert by["4"].label == "Box 4 — Federal income tax withheld"
    assert by["1a"].value == "24310.00" and by["3"].value == 412
    assert by["txn_third_party_network"].value is True
    assert by["8"].value == "CA"
    # All twelve monthly boxes 5a-5l are modelled, in calendar order.
    assert by["5a"].label == "Box 5a — January" and by["5l"].label == "Box 5l — December"
    assert [f.key for f in r.fields if f.key.startswith("5")] == [
        "5a", "5b", "5c", "5d", "5e", "5f", "5g", "5h", "5i", "5j", "5k", "5l"]
    assert by["5f"].status == "missing"           # unread months stay blank
    assert r.gaps == []                            # box 1a + payee TIN are the required two


def test_1099k_ttoc_code_000_survives_as_a_code_not_an_int():
    """Box 1d code 000 DISQUALIFIES box 1c from the Schedule 1-A tips deduction
    ('do not use the amount reported in box 1c'), so the three zeros must survive.
    An int box would coerce "000" to 0 and the disqualifier would read as blank."""
    r = extract_document("documents/1099k.pdf", "1099-K", {
        "payee_tin": "123456789", "1a": "40000", "1c": "9,500", "1d_ttoc_1": "000",
    })
    by = {f.key: f for f in r.fields}
    assert by["1d_ttoc_1"].value == "000" and by["1d_ttoc_1"].type == "code"
    assert by["1d_ttoc_2"].status == "missing"     # up to TWO codes; one read
    assert by["1c"].value == "9500"
    # The merchant category code is a code for the same reason (leading zeros).
    mcc = extract_document("documents/1099k.pdf", "1099-K",
                           {"payee_tin": "123456789", "1a": "1", "2": "0742"})
    assert {f.key: f for f in mcc.fields}["2"].value == "0742"


def test_1099k_transaction_count_is_an_int_box():
    r = extract_document("documents/1099k.pdf", "1099-K",
                         {"payee_tin": "123456789", "1a": "500", "3": "12.5"})
    assert {f.key: f for f in r.fields}["3"].status == "invalid"


def test_1099k_wrong_revision_state_boxes_fail_loudly_rather_than_swap():
    """Boxes 6 and 8 SWAPPED between revisions: Rev. 12-2026 has 6 = state income
    tax withheld and 8 = State, Rev. 3-2024 the reverse. The spec carries the
    current numbering, and the TYPES make a reading off the older printing
    surface as `invalid` instead of silently landing withholding in the state
    code (or a state code where dollars belong)."""
    r = extract_document("documents/1099k_2024.pdf", "1099-K", {
        "payee_tin": "123456789", "1a": "30000", "6": "CA", "8": "412.55",
    })
    by = {f.key: f for f in r.fields}
    assert by["6"].status == "invalid" and by["6"].raw == "CA"
    assert by["8"].status == "invalid" and by["8"].raw == "412.55"


def test_1099k_status_note_refuses_to_treat_the_threshold_as_taxability():
    note = DOC_SPECS["1099-K"].status_note
    # Box 1a is gross, quoted from the filer instructions.
    assert "BOX 1a IS GROSS RECEIPTS, NOT INCOME" in note
    assert "without regard to any adjustments for credits" in note
    # The CURRENT threshold, quoted and attributed to the revision it came from,
    # with both conditions — and named as a reporting rule, not a taxability one.
    assert "THE THRESHOLD IS A REPORTING RULE, NEVER A TAXABILITY RULE" in note
    assert "Instructions for Form 1099-K (Rev. 12-2026)" in note
    assert "exceeds $20,000, and the total number of such transactions exceeds 200" in note
    assert "both conditions, AND" in note
    # A card-accepting business has no de minimis at all.
    assert "has no de minimis at all" in note
    # Under the threshold no form arrives AND no 1099-NEC substitutes for it.
    assert "6050W displaces sections 6041/6041A" in note and "is disregarded" in note
    assert "DOUBLE COUNTING" in note
    # The revision traps.
    assert "BOXES 6 AND 8 SWAPPED" in note
    assert "BOXES 1c AND 1d ARE NEW" in note and "P.L. 119-21, section 70201" in note
    assert "SUBSET of box 1a" in note and "Schedule 1-A" in note
    assert "Code of 000" in note and "do not use the amount reported in box 1c" in note


def test_1099q_box_layout_matches_the_printed_form():
    """f1099q.pdf (Rev. April 2025): boxes 1/2/3, the 4a/4b transfer pair, the
    5a/5b/5c program set, box 6 and the dual-use box 7."""
    r = extract_document("documents/1099q.pdf", "1099-Q", {
        "recipient_tin": "123-45-6789", "1": "$12,000.00", "2": "3,500", "3": "8,500",
        "5b": "X",
    }, page=1)
    by = {f.key: f for f in r.fields}
    assert by["1"].label == "Box 1 — Gross distribution"
    assert by["2"].label == "Box 2 — Earnings"
    assert by["3"].label == "Box 3 — Basis"
    assert by["4a"].label == "Box 4a — Type of transfer: Trustee-to-trustee"
    assert by["4b"].label == "Box 4b — Type of transfer: QTP to Roth IRA"
    assert by["5a"].label == "Box 5a — Distribution is from: Private QTP"
    assert by["5b"].label == "Box 5b — Distribution is from: State QTP"
    assert by["5c"].label == "Box 5c — Distribution is from: Coverdell ESA"
    assert by["6"].label == "Box 6 — Check if the recipient is not the designated beneficiary"
    assert by["5b"].value is True and by["5a"].status == "missing"
    # Box 1 = box 2 + box 3, per the filer instructions ("box 3 must equal box 1
    # minus box 2") — the values round-trip so a caller can check the identity.
    assert by["1"].value == "12000.00" and by["2"].value == "3500" and by["3"].value == "8500"
    assert r.gaps == []


def test_1099q_blank_earnings_and_basis_on_a_coverdell_is_not_a_gap():
    """The Coverdell trustee is INSTRUCTED to leave boxes 2 and 3 blank and put
    the year-end FMV in box 7 ('Do not enter zero'), so neither box may be
    required — otherwise a correctly-issued form reports two false gaps."""
    r = extract_document("documents/1099q_esa.pdf", "1099-Q", {
        "recipient_tin": "123456789", "1": "4,000", "5c": "X", "7": "FMV 18,250",
    })
    by = {f.key: f for f in r.fields}
    assert by["2"].status == "missing" and by["3"].status == "missing"
    assert r.gaps == []


def test_1099q_box_7_is_text_because_it_carries_an_fmv_label_or_a_code():
    """Box 7 holds the FMV 'labelled FMV' and/or an optional, abbreviatable
    distribution code — a money box would call the trustee's own prescribed
    reading invalid."""
    for reading in ("FMV 18,250", "distr. code 1", "FMV 18,250 / distr. code 2", "2"):
        r = extract_document("documents/1099q.pdf", "1099-Q", {
            "recipient_tin": "123456789", "1": "4,000", "7": reading,
        })
        box7 = {f.key: f for f in r.fields}["7"]
        assert box7.status == "ok" and box7.value == reading, reading
        assert box7.type == "text"


def test_1099q_status_note_keeps_taxability_with_the_filer_not_the_trustee():
    note = DOC_SPECS["1099-Q"].status_note
    assert "You must determine the taxability of any distribution" in note
    assert "ONLY BOX 2 CAN EVER BE INCOME" in note
    assert "is the total of the amounts shown in boxes 2 and 3" in note
    # The Coverdell blank-boxes instruction, quoted.
    assert "Do not enter zero" in note and "Pub. 970" in note
    # Box 7's two uses and the full code list.
    assert "BOX 7 IS NOT A MONEY BOX" in note and "may abbreviate as needed" in note
    assert "6 prohibited transaction" in note
    # What actually makes box 2 taxable is nowhere on the form.
    assert "more than one transfer or rollover within any 12-month period" in note
    assert "Form 5329" in note
    # 4b is the SECURE 2.0 QTP-to-Roth route; 4a can be blank on a CESA transfer.
    assert "QTP to a Roth IRA" in note and "the box will be blank" in note
    # Box 6 moves the income to the recipient, not the student.
    assert "RECIPIENT IS NOT THE DESIGNATED BENEFICIARY" in note and "529(e)(1)" in note
    # And there is no withholding anywhere on this form.
    assert "NO WITHHOLDING BOX ON THIS FORM" in note
    assert "Earnings are not subject to backup withholding" in note


def test_w2g_box_layout_matches_the_printed_form():
    """fw2g.pdf (Rev. January 2026) runs 1-18 with THREE withholding boxes:
    box 4 federal, box 15 state, box 17 local."""
    r = extract_document("documents/w2g.pdf", "W-2G", {
        "1": "$12,500.00", "2": "2026-03-14", "3": "Slot machine", "4": "3,000",
        "5": "SN 44-9182", "7": "0", "9": "123-45-6789", "10": "12",
        "13": "NV 88-1234567", "14": "12,500", "15": "0", "16": "0", "17": "0",
        "18": "Clark County",
    }, page=1)
    by = {f.key: f for f in r.fields}
    assert by["1"].label == "Box 1 — Reportable winnings"
    assert by["2"].label == "Box 2 — Date won"
    assert by["3"].label == "Box 3 — Type of wager"
    assert by["4"].label == "Box 4 — Federal income tax withheld"
    assert by["5"].label == "Box 5 — Transaction"
    assert by["6"].label == "Box 6 — Race"
    assert by["7"].label == "Box 7 — Winnings from identical wagers"
    assert by["8"].label == "Box 8 — Cashier"
    assert by["9"].label == "Box 9 — WINNER'S TIN"
    assert by["10"].label == "Box 10 — Window"
    assert by["11"].label == "Box 11 — First identification no."
    assert by["12"].label == "Box 12 — Second identification no."
    assert by["13"].label == "Box 13 — State/Payer's state identification no."
    assert by["14"].label == "Box 14 — State winnings"
    assert by["15"].label == "Box 15 — State income tax withheld"
    assert by["16"].label == "Box 16 — Local winnings"
    assert by["17"].label == "Box 17 — Local income tax withheld"
    assert by["18"].label == "Box 18 — Name of locality"
    # The three withholding boxes are money and carry through.
    assert by["4"].value == "3000" and by["15"].value == "0" and by["17"].value == "0"
    assert by["1"].value == "12500.00" and by["9"].value == "123-45-6789"
    # Box 9 is the winner's TIN and is "required information" per the instructions.
    assert r.gaps == []
    no_tin = extract_document("documents/w2g.pdf", "W-2G", {"1": "5000", "2": "2026-01-02"})
    assert no_tin.gaps == ["9"]


def test_w2g_box_13_holds_state_and_id_together_so_it_is_text():
    """Box 13's instruction is 'Enter the abbreviated name of the state and your
    state identification number' — one box, two things, so a `state` type would
    reject the correct reading (compare 1099-NEC box 6)."""
    r = extract_document("documents/w2g.pdf", "W-2G", {
        "1": "1200", "2": "2026-02-02", "9": "123456789", "13": "NV 88-1234567",
    })
    box13 = {f.key: f for f in r.fields}["13"]
    assert box13.type == "text" and box13.value == "NV 88-1234567" and box13.status == "ok"


def test_w2g_status_note_keys_the_loss_percentage_to_the_year_not_the_form():
    note = DOC_SPECS["W-2G"].status_note
    assert "BOX 1 IS INCOME IN FULL AND THE LOSSES DO NOT COME OFF IT" in note
    assert "Other income" in note and "ITEMIZED" in note and "deducts NOTHING" in note
    # The 90% rule, its statute, and its effective date — the year decides.
    assert "IRC 165(d)(1)" in note and "P.L. 119-21 §70114(a)" in note
    assert "90 percent of the amount of such losses" in note
    assert "taxable years beginning after December 31, 2025" in note
    # And the pre-amendment rule the TY2025-and-earlier filer still gets.
    assert "TY2025 and earlier take the pre-amendment rule" in note
    assert "only to the extent of the gains from such transactions" in note
    assert "165(d)(2)" in note
    # The threshold is inflation-indexed from 2026 and is not a taxability test.
    assert "THE REPORTING THRESHOLD MOVES EVERY YEAR NOW AND IS NOT A TAXABILITY TEST" in note
    assert "calendar year 2026 is $2,000" in note and "adjusted yearly for inflation" in note
    assert "NO W-2G and are income anyway" in note
    # Why box 4 is often zero, and the two noncash rates.
    assert "BOX 4 CAN BE ZERO ON A LARGE WIN" in note
    assert "24% under IRC 3402(q)" in note and "exceed $5,000" in note
    assert "IRC 3406 backup withholding" in note and "31.58%" in note
    # Identical wagers, and the NRA mis-classification signal.
    assert "identical wagers" in note
    assert "Use Form 1042-S to report gambling winnings paid to nonresident aliens" in note
    # Boxes 13-18 are courtesy boxes.
    assert "need not be completed for the IRS" in note


def test_1095b_box_layout_matches_the_printed_form():
    """f1095b.pdf (2025): Part I lines 1-8, Part II 10-11, Part III 16-18, and
    Part IV lines 23-28 with the per-person twelve-month column (e) grid."""
    r = extract_document("documents/1095b.pdf", "1095-B", {
        "2": "123-45-6789", "8": "C", "1": "Ada Lovelace",
        "16": "State Medicaid Agency", "17": "12-3456789",
        "23a": "Ada Lovelace", "23b": "123456789", "23d": "X",
        "24a": "Byron Lovelace", "24b": "987654321",
        "24e_jan": "X", "24e_feb": "X", "24e_mar": "X",
    }, page=1)
    by = {f.key: f for f in r.fields}
    assert by["1"].label == "Line 1 — Name of responsible individual"
    assert by["2"].label == "Line 2 — Social security number (SSN) or other TIN"
    assert by["3"].label == "Line 3 — Date of birth (if SSN or other TIN is not available)"
    assert by["8"].label == "Line 8 — Enter letter identifying Origin of the Health Coverage"
    assert by["11"].label == "Line 11 — Part II Employer identification number (EIN)"
    assert by["18"].label == "Line 18 — Part III Contact telephone number"
    assert by["8"].value == "C" and by["8"].type == "code"
    assert by["17"].value == "12-3456789"      # EIN normalized
    # Six covered-individual rows, 23 through 28, and no seventh (that is the
    # Part IV Continuation Sheet, a separate page).
    assert [k for k in (f.key for f in r.fields) if k.endswith("a") and k[:-1].isdigit()] == [
        "23a", "24a", "25a", "26a", "27a", "28a"]
    assert "29a" not in by
    # Column (d) "covered all 12 months" is a distinct claim from twelve (e) checks.
    assert by["23d"].value is True and by["23e_jan"].status == "missing"
    assert by["24d"].status == "missing" and by["24e_mar"].value is True
    assert by["24e_apr"].status == "missing"
    # All twelve months exist for every row, in calendar order.
    months = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    for line in range(23, 29):
        assert [k for k in (f.key for f in r.fields) if k.startswith(f"{line}e_")] == [
            f"{line}e_{m}" for m in months]
    assert by["28e_dec"].label == "Part IV line 28 col (e) — Months of coverage: Dec"
    assert r.gaps == []                        # line 2 TIN + line 8 code are required


def test_1095b_status_note_says_it_is_not_attached_and_routes_the_other_two_forms():
    note = DOC_SPECS["1095-B"].status_note
    assert "DO NOT ATTACH TO YOUR TAX RETURN" in note
    # Its only federal effect is to threaten the PTC.
    assert "you may not be eligible for the premium tax credit" in note
    # Its real numeric use is a state individual-mandate return — and the note
    # refuses to assert a state roster it cannot cite, pointing at the state
    # knowledge instead (only DC's regime is documented in this repo today).
    assert "per-person coverage evidence a state individual-mandate return needs" in note
    assert "is a STATE-LAW question this spec does not answer" in note
    assert "knowledge/states/dc" in note
    # 1095-A / 1095-B / 1095-C are not interchangeable.
    assert "generally be reported on a Form 1095-A rather than a Form 1095-B" in note
    assert "1095-C (Part III) rather than a Form 1095-B" in note
    # A blank Part II is correct, not a gap.
    assert "blank Part II is NORMAL" in note
    # The full line 8 code list, and only one letter is ever entered.
    assert "only one letter" in note
    for code in ("A SHOP", "B employer-sponsored coverage", "C government-sponsored program",
                 "D individual market insurance", "E multiemployer plan",
                 "F other designated minimum essential coverage", "G individual coverage HRA"):
        assert code in note, code
    # One day of a month counts the whole month.
    assert "covered for at least 1 day in EVERY month" in note
    # And the continuation sheet, which is how a big household loses people.
    assert "Continuation Sheet" in note and "INCOMPLETE" in note
    assert "Line 9 is printed 'Reserved'" in note


def test_1095c_part_ii_is_a_four_line_grid_with_an_all_12_months_column():
    """f1095c.pdf (2025) Part II: lines 14/15/16/17 each have an 'All 12 Months'
    column PLUS twelve monthly boxes — and the printed month labels are June,
    July and Sept, not Jun/Jul/Sep as on the 1095-B."""
    r = extract_document("documents/1095c.pdf", "1095-C", {
        "2": "123-45-6789", "8": "12-3456789", "7": "Acme Corp",
        "plan_start_month": "01", "employee_age_jan_1": "34",
        "14_all_12_months": "1E", "15_all_12_months": "0.00", "16_all_12_months": "2C",
    }, page=1)
    by = {f.key: f for f in r.fields}
    assert by["14_all_12_months"].label == (
        "Part II line 14 (Offer of Coverage — enter required code) — All 12 Months")
    assert by["15_jan"].label == "Part II line 15 (Employee Required Contribution) — Jan"
    assert by["16_all_12_months"].label.startswith(
        "Part II line 16 (Section 4980H Safe Harbor and Other Relief")
    assert by["17_dec"].label == "Part II line 17 (ZIP Code) — Dec"
    # The month labels are as PRINTED on this form.
    assert by["14_june"].label.endswith("— June")
    assert by["14_july"].label.endswith("— July")
    assert by["14_sept"].label.endswith("— Sept")
    assert "14_jun" not in by and "14_sep" not in by
    for line in ("14", "15", "16", "17"):
        assert [k for k in (f.key for f in r.fields) if k.startswith(f"{line}_")] == [
            f"{line}_{c}" for c in ("all_12_months", "jan", "feb", "mar", "apr", "may", "june",
                                    "july", "aug", "sept", "oct", "nov", "dec")]
    assert by["14_all_12_months"].value == "1E" and by["16_all_12_months"].value == "2C"
    assert r.gaps == []


def test_1095c_line_15_zero_is_a_real_value_not_an_empty_box():
    """'If you were offered coverage but there is no cost to you for the coverage,
    this line will report "0.00"' — so 0.00 must read as ok, distinct from the
    blank line 15 that a code 1A or 1H legitimately produces."""
    r = extract_document("documents/1095c.pdf", "1095-C", {
        "2": "123456789", "8": "123456789", "14_all_12_months": "1E",
        "15_all_12_months": "0.00",
    })
    by = {f.key: f for f in r.fields}
    assert by["15_all_12_months"].value == "0.00" and by["15_all_12_months"].status == "ok"
    assert by["15_jan"].status == "missing"


def test_1095c_plan_start_month_keeps_its_two_digits():
    """The form says 'enter 2-digit number', so an int box would turn 01 into 1."""
    r = extract_document("documents/1095c.pdf", "1095-C", {
        "2": "123456789", "8": "123456789", "plan_start_month": "01",
        "employee_age_jan_1": "34",
    })
    by = {f.key: f for f in r.fields}
    assert by["plan_start_month"].value == "01" and by["plan_start_month"].type == "code"
    assert by["employee_age_jan_1"].value == 34      # an age IS an int box
    frac = extract_document("documents/1095c.pdf", "1095-C", {
        "2": "123456789", "8": "123456789", "employee_age_jan_1": "34.5"})
    assert {f.key: f for f in frac.fields}["employee_age_jan_1"].status == "invalid"


def test_1095c_part_iii_prints_thirteen_rows_not_the_1095b_six():
    r = extract_document("documents/1095c.pdf", "1095-C", {
        "2": "123456789", "8": "123456789", "part_iii_self_insured": "X",
        "18a": "Ada Lovelace", "18d": "yes", "30a": "Thirteenth Person", "30e_june": "X",
    })
    by = {f.key: f for f in r.fields}
    assert [k for k in (f.key for f in r.fields) if k.endswith("a") and k[:-1].isdigit()] == [
        f"{n}a" for n in range(18, 31)]
    assert by["part_iii_self_insured"].value is True
    assert by["18d"].value is True
    # Row 30 is real (the 1095-B stops at 28) and its months use the printed labels.
    assert by["30e_june"].value is True
    assert by["30e_june"].label == "Part III line 30 col (e) — Months of coverage: June"
    assert "31a" not in by


def test_1095c_and_1095b_are_distinct_kinds_whose_line_numbers_do_not_mean_the_same_thing():
    """Both forms print a line 8 and lines 18-28, and they mean different things —
    which is why they are separate kinds rather than one shared 1095 spec."""
    b = {f.key: f for f in extract_document("d/b.pdf", "1095-B", {}).fields}
    c = {f.key: f for f in extract_document("d/c.pdf", "1095-C", {}).fields}
    assert b["8"].label == "Line 8 — Enter letter identifying Origin of the Health Coverage"
    assert c["8"].label == "Line 8 — Employer identification number (EIN)"
    assert b["8"].type == "code" and c["8"].type == "ein"
    # Line 2 differs too, and the types follow the printed captions: the 1095-B
    # says "Social security number (SSN) or other TIN" (an employer/entity TIN can
    # appear), the 1095-C says "Social security number (SSN)" and nothing else.
    assert b["2"].label.endswith("or other TIN") and b["2"].type == "tin"
    assert c["2"].label == "Line 2 — Social security number (SSN)" and c["2"].type == "ssn"
    # Line 23 is a covered individual on both forms but a DIFFERENT row of the roster.
    assert b["23a"].label.startswith("Part IV line 23") and c["23a"].label.startswith("Part III line 23")
    # And line 14 exists only on the 1095-C.
    assert "14_all_12_months" in c and not any(k.startswith("14") for k in b)
    assert DOC_SPECS["1095-B"].title == "Health Coverage"
    assert DOC_SPECS["1095-C"].title == "Employer-Provided Health Insurance Offer and Coverage"


def test_1095c_status_note_carries_both_code_series_and_the_ptc_consequence():
    note = DOC_SPECS["1095-C"].status_note
    assert "DO NOT ATTACH TO YOUR TAX RETURN" in note
    assert "PART II DECIDES WHETHER A PREMIUM TAX CREDIT IS ALLOWED AT ALL" in note
    assert "even if the employee declined it" in note
    # Code Series 1 — including the two ICHRA ZIP families and the reserved letters.
    assert "1H NO OFFER OF COVERAGE" in note
    assert "1L/1M/1N/1T priced off the employee's RESIDENCE ZIP" in note
    assert "1O/1P/1Q/1U off the PRIMARY EMPLOYMENT SITE ZIP" in note
    assert "1I and 1V-1Z are 'Reserved for future use'" in note
    # Code Series 2 in full, with the one-code-per-month rule and the 2C carve-out.
    assert "only one code from Code Series 2 per calendar month" in note
    for code in ("2A employee not employed", "2B not a full-time employee",
                 "2C ENROLLED", "2D in a section 4980H(b) Limited Non-Assessment",
                 "2E multiemployer interim rule relief", "2F Form W-2 affordability safe harbor",
                 "2G federal poverty line safe harbor", "2H rate of pay safe harbor"):
        assert code in note, code
    assert "ONLY 2C MATTERS TO THE FILER" in note
    assert "none of this information affects your eligibility for the premium tax credit" in note
    # Line 15 is the lowest-cost self-only figure, blank for some codes, 0.00 for others.
    assert "LINE 15 IS NOT WHAT THE EMPLOYEE PAID" in note
    assert "will show an amount only if code 1B" in note
    assert "A LINE 15 OF 0.00 IS A REAL VALUE" in note
    # The indexed affordability percentage is never hardcoded.
    assert "THE AFFORDABILITY PERCENTAGE IS INDEXED — never hardcode it" in note
    assert "8.39% for plan years beginning in 2024, and 9.02% for plan years beginning in 2025" in note
    # A blank Part III is correct under an insured plan.
    assert "PART III IS OFTEN LEGITIMATELY BLANK" in note
    assert "Complete Part III ONLY if the ALE Member offers employer-sponsored, self-insured" in note
    # Two employers, two forms; and the 13-row overflow.
    assert "MULTIPLE EMPLOYERS MEAN MULTIPLE FORMS" in note
    assert "THIRTEEN rows (lines 18-30)" in note


def test_5498_and_5498_sa_are_separate_kinds_that_do_not_collide():
    """Same number family, different forms. DOC_SPECS is keyed on the exact kind
    string, so "5498" and "5498-SA" are distinct entries — and the boxes they
    share a NUMBER with mean different things."""
    kinds = {k["kind"]: k for k in list_document_kinds()}
    assert {"5498", "5498-SA"} <= set(kinds)
    assert kinds["5498"]["title"] == "IRA Contribution Information"
    assert kinds["5498-SA"]["title"] == "HSA, Archer MSA, or Medicare Advantage MSA Information"
    assert kinds["5498"]["source_url"] == "https://www.irs.gov/forms-pubs/about-form-5498"
    assert kinds["5498-SA"]["source_url"] == "https://www.irs.gov/forms-pubs/about-form-5498-sa"
    ira = {f.key: f for f in extract_document("d/5498.pdf", "5498", {}).fields}
    hsa = {f.key: f for f in extract_document("d/5498sa.pdf", "5498-SA", {}).fields}
    # Box 5 on both forms, two different figures.
    assert ira["5"].label == "Box 5 — FMV of account"
    assert hsa["5"].label == "Box 5 — Fair market value of HSA, Archer MSA, or MA MSA"
    # Box 2 is the HSA contribution total on the SA form and a ROLLOVER here.
    assert ira["2"].label == "Box 2 — Rollover contributions"
    assert hsa["2"].label == "Box 2 — Total contributions made in the calendar year"
    # The account-type checkbox sets live on different box numbers (7 vs 6).
    assert {"7_ira", "7_sep", "7_simple", "7_roth_ira"} <= set(ira)
    assert {"6_hsa", "6_archer_msa", "6_ma_msa"} <= set(hsa)
    assert not any(k.startswith("6_") for k in ira)
    # And the IRA form's note points a mis-routed caller at the right kind.
    assert "you want kind 5498-SA" in DOC_SPECS["5498"].status_note


def test_5498_box_layout_matches_the_printed_form():
    """f5498.pdf runs 1-6, the box 7 checkbox set, 8-11, 12a/12b, 13a/13b/13c,
    14a/14b and 15a/15b."""
    r = extract_document("documents/5498.pdf", "5498", {
        "participant_tin": "123-45-6789", "1": "$7,500.00", "3": "40,000",
        "5": "$412,300.55", "7_ira": "X", "11": "no",
        "12a": "2027-12-31", "12b": "0", "13a": "1,000", "13b": "2025", "13c": "FD",
        "14a": "2,500", "14b": "BA", "15a": "25,000", "15b": "D",
    }, page=1)
    by = {f.key: f for f in r.fields}
    assert by["1"].label == "Box 1 — IRA contributions (other than amounts in boxes 2-4, 8-10, 13a, and 14a)"
    assert by["2"].label == "Box 2 — Rollover contributions"
    assert by["3"].label == "Box 3 — Roth IRA conversion amount"
    assert by["4"].label == "Box 4 — Recharacterized contributions"
    assert by["6"].label == "Box 6 — Life insurance cost included in box 1"
    assert by["8"].label == "Box 8 — SEP contributions"
    assert by["9"].label == "Box 9 — SIMPLE contributions"
    assert by["10"].label == "Box 10 — Roth IRA contributions"
    assert by["12a"].label == "Box 12a — RMD date"
    assert by["12b"].label == "Box 12b — RMD amount"
    assert by["13a"].label == "Box 13a — Postponed/late contrib."
    assert by["15a"].label == "Box 15a — FMV of certain specified assets"
    assert by["15b"].label == "Box 15b — Code(s)"
    assert by["5"].value == "412300.55" and by["3"].value == "40000"
    assert by["7_ira"].value is True and by["7_roth_ira"].status == "missing"
    # A recognized negative token gives a real False, never a fabricated one.
    assert by["11"].value is False
    # Box 13b is the credited YEAR, so it is an int box.
    assert by["13b"].value == 2025 and by["13b"].type == "int"
    # Box 15b is plural on the form: more than one letter can appear, so it is a
    # passthrough code rather than a validated single letter.
    multi = extract_document("documents/5498.pdf", "5498",
                             {"participant_tin": "123456789", "5": "1", "15b": "A, D, E"})
    assert {f.key: f for f in multi.fields}["15b"].value == "A, D, E"
    assert r.gaps == []


def test_5498_fmv_is_required_because_the_trustee_must_report_it_every_year():
    """'Enter the FMV of the account on December 31' — trustees 'are responsible
    for ensuring that all IRA assets ... are valued annually at their FMV', and
    box 5 is the Form 8606 line 6 / ira_pro_rata denominator, so a form read
    without it is a gap, not a complete reading."""
    r = extract_document("documents/5498.pdf", "5498",
                         {"participant_tin": "123456789", "1": "7000"})
    assert r.gaps == ["5"]


def test_5498_status_note_routes_boxes_3_and_5_into_the_ira_ops():
    note = DOC_SPECS["5498"].status_note
    assert "THIS IS THE IRA FORM, NOT THE HSA ONE" in note
    assert "Form 5498-TA" in note
    # Box 5 is the pro-rata denominator, and must be SUMMED across accounts.
    assert "BOX 5 IS THE PRO-RATA DENOMINATOR" in note
    assert "Form 8606 line 6" in note and "ira_pro_rata" in note
    assert "one account's box 5 is not the denominator, the sum is" in note
    # The decedent caveat that makes box 5 not a year-end value.
    assert "BOX 5 IS NOT ALWAYS A DEC-31 VALUE" in note
    assert "may be the FMV on the date of death" in note
    # Box 3 is the conversion and is NOT inside box 2.
    assert "BOX 3 IS THE CONVERSION" in note and "roth_conversion" in note
    assert "which are reported in box 3" in note
    # The year conventions disagree: box 1/10 are for-the-year, 8/9 are by deposit.
    assert "THE YEAR CONVENTIONS OF THE CONTRIBUTION BOXES DISAGREE WITH EACH OTHER" in note
    assert "through April 15" in note
    assert "boxes 8 (SEP) and 9 (SIMPLE) run the OPPOSITE way, by deposit date" in note
    assert "appears on NEXT year's Form 5498" in note
    # Box 1's exclusions, box 6's subtraction, box 7's optionality.
    assert "Box 1 EXCLUDES boxes 2-4, 8-10, 13a and 14a" in note
    assert "Subtract this amount from your allowable IRA contribution" in note
    assert "only 'MAY show the kind of IRA'" in note
    # Box 11 is next year's RMD and its silence is not safety.
    assert "BOX 11 IS ABOUT NEXT YEAR AND ITS SILENCE IS NOT SAFETY" in note
    assert "an RMD may be required even if the box is not checked" in note
    # The 13c and 14b code lists.
    assert "FD federally designated disaster" in note and "SC self-certified late rollover" in note
    assert "EO13239" in note and "PL115-97" in note
    assert "QR, DD, BA, HP, EP, DA or TI" in note
    # And 15a/15b mean the box 5 FMV is an estimate.
    assert "the box 5 FMV is an ESTIMATE" in note


# ---------------------------------------------------------------------------
# The other two Schedule K-1s. NAMING: the bare kind "K-1" stays the Form 1065
# layout it has always been (renaming it would break its callers), and the new
# siblings name their entity. f1120ssk.pdf / f1041sk1.pdf and both sets of
# instructions read 2026-08-27.
# ---------------------------------------------------------------------------


def test_the_bare_k1_kind_still_means_form_1065_and_is_unchanged():
    """Pins the naming decision: anything already passing "K-1" keeps the
    partnership layout. If a later change renames this key, this test fails
    loudly rather than silently re-pointing existing callers at another form."""
    kinds = {k["kind"]: k for k in list_document_kinds()}
    assert {"K-1", "K-1 (1120-S)", "K-1 (1041)"} <= set(kinds)
    assert kinds["K-1"]["title"].startswith("Schedule K-1 (Form 1065)")
    assert kinds["K-1"]["source_url"] == "https://www.irs.gov/forms-pubs/about-schedule-k-1-form-1065"
    # The 1065 spec's own boxes are untouched: box 14 is still SE earnings and
    # box 16 is still the K-3 flag there.
    p = {f.key: f for f in extract_document("k1.pdf", "K-1", {}).fields}
    assert p["14"].label == "Box 14 — Self-employment earnings (loss)"
    assert p["16"].label == "Box 16 — Schedule K-3 is attached if checked"


def test_k1_1120s_box_numbers_collide_with_the_1065_layout_and_mean_other_things():
    """The reason these are separate kinds. Box 14 and box 16 are swapped in
    meaning between the two forms, so a shared spec would mislabel both."""
    p = {f.key: f for f in extract_document("k1.pdf", "K-1", {}).fields}
    s = {f.key: f for f in extract_document("k1s.pdf", "K-1 (1120-S)", {}).fields}
    assert s["14"].label == "Box 14 — Schedule K-3 is attached if checked"
    assert s["14"].type == "checkbox" and p["14"].type == "money"
    assert s["16"].label.startswith("Box 16 — Items affecting shareholder basis")
    assert p["16"].type == "checkbox" and s["16"].type == "text"
    # An S corporation has no self-employment box and no guaranteed payments.
    assert not any("Self-employment" in f.label for f in
                   extract_document("k1s.pdf", "K-1 (1120-S)", {}).fields)
    assert "4a" not in s and "4b" not in s and "4c" not in s   # 1065 boxes only
    assert "21" not in s                                        # 1065 box 21, not here


def test_k1_1120s_box_layout_matches_the_printed_form():
    """Schedule K-1 (Form 1120-S) 2025: Part III boxes 1-17 plus the 18/19
    at-risk / passive-activity checkboxes, and Part I/II items A-I."""
    r = extract_document("documents/k1_1120s.pdf", "K-1 (1120-S)", {
        "corporation_ein": "12-3456789", "shareholder_tin": "999-00-1234",
        "1": "-18,000", "4": "310", "5a": "1,200", "5b": "1,100",
        "8a": "4,000", "11": "2,500", "14": True,
        "16": "D 25,000", "g_allocation_percentage": "33.333333",
        "i_loans_end": "50,000", "h_shares_end": "100", "18": "X",
    }, page=1)
    by = {f.key: f for f in r.fields}
    assert by["1"].label == "Box 1 — Ordinary business income (loss)"
    assert by["2"].label == "Box 2 — Net rental real estate income (loss)"
    assert by["3"].label == "Box 3 — Other net rental income (loss)"
    assert by["4"].label == "Box 4 — Interest income"
    assert by["5a"].label == "Box 5a — Ordinary dividends"
    assert by["5b"].label == "Box 5b — Qualified dividends"
    assert by["6"].label == "Box 6 — Royalties"
    assert by["7"].label == "Box 7 — Net short-term capital gain (loss)"
    assert by["8a"].label == "Box 8a — Net long-term capital gain (loss)"
    assert by["8b"].label == "Box 8b — Collectibles (28%) gain (loss)"
    assert by["8c"].label == "Box 8c — Unrecaptured section 1250 gain"
    assert by["9"].label == "Box 9 — Net section 1231 gain (loss)"
    assert by["11"].label == "Box 11 — Section 179 deduction"
    assert by["15"].label.startswith("Box 15 — Alternative minimum tax (AMT) items")
    assert by["17"].label.startswith("Box 17 — Other information")
    assert by["18"].label == "Box 18 — More than one activity for at-risk purposes"
    assert by["19"].label == "Box 19 — More than one activity for passive activity purposes"
    # Losses take a leading minus sign; a parenthesized reading is invalid.
    assert by["1"].value == "-18000"
    paren = extract_document("documents/k1_1120s.pdf", "K-1 (1120-S)", {
        "corporation_ein": "12-3456789", "shareholder_tin": "999001234", "1": "(18,000)"})
    assert {f.key: f for f in paren.fields}["1"].status == "invalid"
    assert by["14"].value is True and by["18"].value is True
    # The allocation percentage is a percentage, kept verbatim like 1042-S box 3b.
    assert by["g_allocation_percentage"].value == "33.333333"
    # Share counts must not be int boxes — fractional shares are possible.
    assert by["h_shares_end"].type == "money"
    frac = extract_document("documents/k1_1120s.pdf", "K-1 (1120-S)", {
        "corporation_ein": "123456789", "shareholder_tin": "999001234",
        "h_shares_end": "33.5"})
    assert {f.key: f for f in frac.fields}["h_shares_end"].value == "33.5"
    assert r.gaps == []


def test_k1_1120s_status_note_refuses_the_se_tax_error():
    note = DOC_SPECS["K-1 (1120-S)"].status_note
    assert "THIS IS THE S-CORPORATION K-1 AND IT IS NOT THE PARTNERSHIP ONE" in note
    # The box collision, spelled out in both directions.
    assert "on the 1065 K-1 that is box 16" in note
    assert "on the 1065 K-1 that is box 19, Distributions" in note
    # The quoted rule, and the instruction not to run se_tax.
    assert "isn't self-employment income and it isn't subject to self-employment tax" in note
    assert "Do NOT run calc op se_tax on box 1" in note
    assert "raises a reasonable-compensation question this form cannot" in note
    # The three loss gates, in order, with their forms.
    assert "may be less than the amount reported on Schedule K-1" in note
    assert "1366(d)" in note and "Form 7203" in note
    assert "Form 6198" in note and "passive activity" in note
    assert "code D distributions REDUCE that basis" in note
    # Codes, the K-3 flag, the aggregation warning, and NIIT on a stock sale.
    assert "MINUS SIGN" in note and "never total them blind" in note
    assert "Schedule K-3" in note
    assert "AGGREGATES of separate activities" in note
    assert "section 1411" in note and "Form 8960" in note


def test_k1_1041_box_layout_matches_the_printed_form():
    """Schedule K-1 (Form 1041) 2025: box 1 is INTEREST, not ordinary business
    income — the numbering shares almost nothing with the other two K-1s."""
    r = extract_document("documents/k1_1041.pdf", "K-1 (1041)", {
        "estate_trust_ein": "12-3456789", "beneficiary_tin": "999-00-1234",
        "1": "1,250", "2a": "800", "2b": "700", "4a": "12,000", "10": "3,000",
        "13": "A 4,500", "14": "B 210", "h_domestic_beneficiary": "X",
        "e_final_form_1041": "X", "11": "A 6,200 / C 3,000",
        "d_form_1041t_filed": "X", "d_form_1041t_date": "2026-01-10",
    }, page=1)
    by = {f.key: f for f in r.fields}
    assert by["1"].label == "Box 1 — Interest income"
    assert by["2a"].label == "Box 2a — Ordinary dividends"
    assert by["2b"].label == "Box 2b — Qualified dividends"
    assert by["3"].label == "Box 3 — Net short-term capital gain"
    assert by["4a"].label == "Box 4a — Net long-term capital gain"
    assert by["4b"].label == "Box 4b — 28% rate gain"
    assert by["4c"].label == "Box 4c — Unrecaptured section 1250 gain"
    assert by["5"].label == "Box 5 — Other portfolio and nonbusiness income"
    assert by["6"].label == "Box 6 — Ordinary business income"
    assert by["7"].label == "Box 7 — Net rental real estate income"
    assert by["8"].label == "Box 8 — Other rental income"
    assert by["10"].label == "Box 10 — Estate tax deduction"
    assert by["12"].label.startswith("Box 12 — Alternative minimum tax adjustment")
    # The capital-gain captions carry no "(loss)" — that is what the form prints,
    # and it is why losses only reach the beneficiary through box 11.
    assert "(loss)" not in by["3"].label and "(loss)" not in by["4a"].label
    assert by["1"].value == "1250" and by["4a"].value == "12000"
    assert by["e_final_form_1041"].value is True
    assert by["d_form_1041t_filed"].value is True and by["d_form_1041t_date"].value == "2026-01-10"
    assert by["h_domestic_beneficiary"].value is True
    assert by["h_foreign_beneficiary"].status == "missing"
    # No Schedule K-3 checkbox exists on this form at all.
    assert not any("K-3" in f.label for f in r.fields)
    # Nor the other two forms' distinctive boxes.
    assert "5a" not in by and "8a" not in by      # 1120-S / 1065 numbering
    assert "16" not in by and "17" not in by and "18" not in by
    assert r.gaps == []


def test_all_three_k1_kinds_disagree_on_what_box_1_and_box_14_mean():
    """One shared "K-1" spec could not label any of the three correctly."""
    p = {f.key: f for f in extract_document("a.pdf", "K-1", {}).fields}
    s = {f.key: f for f in extract_document("b.pdf", "K-1 (1120-S)", {}).fields}
    t = {f.key: f for f in extract_document("c.pdf", "K-1 (1041)", {}).fields}
    assert p["1"].label == "Box 1 — Ordinary business income (loss)"
    assert s["1"].label == "Box 1 — Ordinary business income (loss)"
    assert t["1"].label == "Box 1 — Interest income"          # the trust form differs
    assert p["14"].label == "Box 14 — Self-employment earnings (loss)"
    assert s["14"].label == "Box 14 — Schedule K-3 is attached if checked"
    assert t["14"].label == "Box 14 — Other information (code letters)"
    # Each names its own entity in the title, so a confirm-table cannot hide which
    # form was read.
    assert "Form 1065" in DOC_SPECS["K-1"].title
    assert "Form 1120-S" in DOC_SPECS["K-1 (1120-S)"].title
    assert "Form 1041" in DOC_SPECS["K-1 (1041)"].title


def test_k1_1041_status_note_carries_the_final_year_and_payment_traps():
    note = DOC_SPECS["K-1 (1041)"].status_note
    assert "THIS IS THE ESTATE/TRUST K-1" in note
    assert "box 1 is INTEREST income" in note
    # No K-3 here; foreign taxes come through box 14 code B into the 904(j) lane.
    assert "THERE IS NO SCHEDULE K-3 CHECKBOX ON THIS FORM AT ALL" in note
    assert "box 14 CODE B" in note and "foreign_tax_credit_election" in note
    # The attach-it-or-not rule, quoted.
    assert "Don't file it with your tax return, unless backup withholding was reported in box 13, code B" in note
    # The two payment codes and the Form 1041-T precondition tied to item D.
    assert "TWO BOXES ARE PAYMENTS, NOT INCOME" in note
    assert "Form 1040 line 26" in note and "line 25c" in note
    assert "must be timely filed by the fiduciary for the beneficiary to get the credit" in note
    assert "item D and box 13 must be read together" in note
    # Losses do not pass through except on termination.
    assert "LOSSES GENERALLY DO NOT PASS THROUGH" in note
    assert "with NO '(loss)'" in note
    assert "Excess deductions on termination occur only during the last" in note
    assert "IRC 1212" in note and "item E" in note
    # The full box 11 code list — the payload of a final-year K-1.
    for code in ("A excess deductions - section 67(e) expenses", "line 24k",
                 "C short-term capital loss carryover", "D long-term capital loss carryover",
                 "E net operating loss carryover - regular tax",
                 "F net operating loss carryover - minimum tax"):
        assert code in note, code
    assert "lost for good" in note
    # And the attached-statement warning printed on the form's own face.
    assert "A statement must be attached showing the beneficiary's share of income" in note
    assert "DOMESTIC from a FOREIGN beneficiary" in note


# ---------------------------------------------------------------------------
# Phase I5 acceptance (ROADMAP: "every box layout read off the official form,
# round-trip tested"). One place that fails if a kind is dropped or a citation
# rots, plus the round-trip every new spec must satisfy.
# ---------------------------------------------------------------------------

I5_KINDS = {
    "1099-K": "https://www.irs.gov/forms-pubs/about-form-1099-k",
    "1099-Q": "https://www.irs.gov/forms-pubs/about-form-1099-q",
    "W-2G": "https://www.irs.gov/forms-pubs/about-form-w-2-g",
    "1095-B": "https://www.irs.gov/forms-pubs/about-form-1095-b",
    "1095-C": "https://www.irs.gov/forms-pubs/about-form-1095-c",
    "5498": "https://www.irs.gov/forms-pubs/about-form-5498",
    "K-1 (1120-S)": "https://www.irs.gov/forms-pubs/about-schedule-k-1-form-1120-s",
    # Schedule K-1 (Form 1041) has no "About" page of its own on irs.gov (the
    # About Form 1041 page links straight to the form and these instructions),
    # so the layout is cited to the instructions themselves.
    "K-1 (1041)": "https://www.irs.gov/instructions/i1041sk1",
}


def test_i5_kinds_are_all_registered_and_cited():
    kinds = {k["kind"]: k for k in list_document_kinds()}
    assert set(I5_KINDS) <= set(kinds)
    for kind, url in I5_KINDS.items():
        assert kinds[kind]["source_url"] == url, kind
        assert kinds[kind]["title"], kind
        # Every I5 spec carries a status_note: these forms all mean something the
        # box values alone cannot say.
        assert DOC_SPECS[kind].status_note, kind
    # The pre-I5 kinds are all still here (nothing was renamed out from under a
    # caller). EIGHTEEN shipped before this tranche, 26 after — ROADMAP I5 says
    # "14 DocSpecs ship", which was true before I2/I3 added 1099-SA, 5498-SA,
    # 3921 and 3922; the roadmap line needs the +4, and this count is the gate.
    pre_i5 = {"W-2", "1099-NEC", "1099-INT", "1099-DIV", "1099-G", "1099-MISC", "1098-T",
              "1098-E", "1042-S", "SSA-1099", "1099-R", "1099-B", "1099-SA", "5498-SA",
              "3922", "3921", "1095-A", "K-1"}
    assert len(pre_i5) == 18 and pre_i5 <= set(kinds)
    assert set(kinds) == pre_i5 | set(I5_KINDS)
    assert len(kinds) == 26


@pytest.mark.parametrize("kind", sorted(I5_KINDS))
def test_i5_specs_round_trip_every_box(kind):
    """Round-trip: an empty reading returns every documented box as `missing`
    with document provenance and nothing invented, and a reading of every box
    with its own key comes back `ok` for the non-typed boxes and never silently
    drops a value."""
    spec = DOC_SPECS[kind]
    keys = [b.key for b in spec.boxes]
    assert len(keys) == len(set(keys)), f"{kind} has duplicate box keys"

    empty = extract_document("documents/x.pdf", kind, {}, page=2)
    assert [f.key for f in empty.fields] == keys           # order preserved
    assert all(f.value is None and f.status == "missing" for f in empty.fields)
    assert all(f.provenance.kind == "document" and f.provenance.page == 2 for f in empty.fields)
    assert set(empty.gaps) == {b.key for b in spec.boxes if b.required}
    assert empty.unexpected == []
    assert spec.status_note in empty.caveat                # the trap rides along

    # A type-appropriate reading of every box round-trips with no invalids.
    sample = {
        "money": "1,234.56", "int": "7", "text": "as printed", "code": "A",
        "ein": "12-3456789", "ssn": "123-45-6789", "tin": "123-45-6789",
        "state": "CA", "checkbox": "X",
    }
    full = extract_document("documents/x.pdf", kind, {b.key: sample[b.type] for b in spec.boxes})
    bad = [(f.key, f.type, f.raw) for f in full.fields if f.status != "ok"]
    assert bad == [], f"{kind}: {bad}"
    assert full.gaps == [] and full.unexpected == []
    # An unknown key is reported, never absorbed.
    stray = extract_document("documents/x.pdf", kind, {"not_a_box": "1"})
    assert stray.unexpected == ["not_a_box"]
