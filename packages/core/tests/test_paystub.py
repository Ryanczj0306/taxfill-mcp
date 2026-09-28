"""Phase J JP3a — Profile.employment and the paystub DocSpec (hypothetical demo figures only)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from taxfill_core.extract import DOC_SPECS, extract_document, list_document_kinds
from taxfill_core.schemas.profile import EmploymentRecord, PayrollDeductions, Profile, Provenance
from taxfill_core.workspace import Workspace

US = Provenance.user_stated()
STUB = {"employer_name": "Demo Widgets Inc", "pay_date": "2026-06-30", "period_start": "2026-06-16",
        "period_end": "2026-06-30", "gross_current": "4000.00", "gross_ytd": "48000.00",
        "federal_withholding_current": "420.00", "federal_withholding_ytd": "5040.00",
        "social_security_current": "248.00", "social_security_ytd": "2976.00", "medicare_current": "58.00",
        "medicare_ytd": "696.00", "pretax_401k_ytd": "4800.00", "section_125_ytd": "1200.00", "hsa_ytd": "600.00"}


def test_jp3a_a_synthetic_stub_extracts_with_its_caveat():
    doc = extract_document("demo-stub.pdf", "paystub", STUB, tax_year=2026)
    assert not [f for f in doc.findings if f.severity == "error"]
    assert Decimal({f.key: f for f in doc.fields}["gross_ytd"].value) == Decimal("48000.00")
    kinds = {k["kind"]: k for k in list_document_kinds()}
    assert kinds["paystub"]["source_url"].endswith("iw2w3.pdf")
    assert "Calendar year basis" in DOC_SPECS["paystub"].status_note
    assert "Calendar year basis" in doc.caveat              # the status note rides on every extraction


def test_jp3a_the_stub_validators():
    bad = extract_document("demo-stub.pdf", "paystub", {**STUB, "gross_ytd": "3000.00"}, tax_year=2026)
    assert any(f.rule_id == "V28" for f in bad.findings)
    late = extract_document("demo-stub.pdf", "paystub", {**STUB, "pay_date": "2027-01-02"}, tax_year=2026)
    assert any(f.rule_id == "V29" and f.severity == "warning" for f in late.findings)


def test_jp3a_employment_round_trips_through_the_workspace(tmp_path):
    job = EmploymentRecord(employer="Demo Widgets Inc", start=date(2026, 1, 5), end=date(2026, 8, 31),
                           pay_frequency="semimonthly", first_pay_date=date(2026, 1, 15),
                           gross_per_period=Decimal("4000"),
                           deductions_per_period=PayrollDeductions(pretax_401k=Decimal("400"), section_125=Decimal("100"),
                                                                   roth_401k=Decimal("50")),
                           provenance=US)
    profile = Profile(employment={2026: [job]})
    ws = Workspace.open(tmp_path, 2026, now="2026-09-28T00:00:00")
    ws.save_profile(profile, now="2026-09-28T00:00:00")
    back = Workspace.open(tmp_path, 2026, now="2026-09-28T00:00:01").load_profile()
    assert Profile.model_validate(back).employment[2026][0] == job


def test_jp3a_employment_dates_are_checked():
    with pytest.raises(ValueError, match="before start"):
        EmploymentRecord(employer="Demo", start=date(2026, 5, 1), end=date(2026, 4, 1), provenance=US)
