"""Phase J JR2c: the IRA custodian statement, the manifest's attached statements, and the rule reach of the
recharacterization op (P-021). Hypothetical demo figures; the i8606 Roth example for the round trip."""
from __future__ import annotations

from decimal import Decimal

from taxfill_core.calc import ira_contribution_eligibility, ira_pro_rata, ira_recharacterization, roth_conversion
from taxfill_core.extract import DOC_SPECS, dec31_total_value_from_statements, extract_document
from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay
from taxfill_core.intake import intake_checklist
from taxfill_core.schemas.profile import Answer, Profile, Provenance, RetirementContributionsYear

KIND = "IRA custodian statement"


def _year_end(path, account_type, fmv, as_of="2025-12-31"):
    return extract_document(path, KIND, {"statement_type": "year_end_fmv", "account_type": account_type,
                                         "custodian": "Demo Custodian", "fmv": fmv, "fmv_date": as_of}, page=1)


def test_p021_a_transfer_confirmation_round_trips_into_the_recharacterization():
    doc = extract_document("docs/confirmation.pdf", KIND, {
        "statement_type": "transfer_confirmation", "account_type": "roth", "transaction_type": "recharacterization",
        "transaction_date": "2025-12-30", "amount": "$4,200.00", "from_account": "Roth ...1234",
        "to_account": "Traditional ...5678", "contribution_year": 2025}, page=1)
    f = {x.key: x for x in doc.fields}
    assert not doc.gaps and not doc.findings and f["amount"].value == "4200.00"
    assert f["amount"].provenance == Provenance.document(file="docs/confirmation.pdf", page=1)
    r = ira_recharacterization(
        direction="roth_to_traditional", amount=4000, contribution_year=2025, contribution_date="2025-06-17",
        transfer_date=f["transaction_date"].value, contributions_during=4000, closing_fmv=4200, whole_account=True,
        magi=60_000, covered_by_employer_plan=True,
        readings=[{"form": "confirmation", "box": "amount", "amount": f["amount"].value}])
    assert r.reconciliation == [{"form": "CONFIRMATION", "box": "amount", "reported": Decimal("4200.00"),
                                 "expected": Decimal("4200.00"), "difference": Decimal("0.00"), "ok": True}]
    assert "attached_statements" in r.work
    missing = extract_document("docs/c.pdf", KIND, {"statement_type": "trade_confirmation", "account_type": "roth"})
    assert [x.rule_id for x in missing.findings] == ["V18"]


def test_p021_year_end_statements_feed_dec31_total_value_with_provenance():
    docs = [_year_end("docs/trad_a.pdf", "traditional", "12,000.50"), _year_end("docs/sep.pdf", "sep", 3000),
            _year_end("docs/roth.pdf", "roth", 9000), _year_end("docs/trad_b.pdf", "traditional", 500, "2025-11-30")]
    v = dec31_total_value_from_statements(docs, 2025)
    assert v.dec31_total_value == Decimal("15000.50")
    assert [a["file"] for a in v.accounts] == ["docs/trad_a.pdf", "docs/sep.pdf"]
    assert v.accounts[0]["provenance"] == {"kind": "document", "file": "docs/trad_a.pdf", "page": 1}
    assert [e["file"] for e in v.excluded] == ["docs/roth.pdf", "docs/trad_b.pdf"]
    assert docs[3].findings[0].rule_id == "V17"                    # not a December 31 value
    pr = ira_pro_rata(dec31_total_value=v.dec31_total_value, amount_converted=6000,
                      nondeductible_basis_carryforward=6000, year=2025)
    assert pr.taxable_conversion + pr.nontaxable_conversion == 6000 and 0 < pr.nontaxable_conversion < 6000


def test_p021_the_custodian_statement_notes_the_5498_timing():
    note = DOC_SPECS[KIND].status_note
    assert "with the IRS by May 31, 2027" in note and "each participant by February 1, 2027" in note


def test_p021_the_manifest_lists_the_recharacterization_statement():
    item = FilingManifestItem(form="1040", tax_year=2025, bottom_line=250,
                              attached_statements=["recharacterization statement"])
    ret = file_and_pay([item]).returns[0]
    assert any("ATTACH THE RECHARACTERIZATION STATEMENT" in a for a in ret.assemble)
    assert any("recharacterization statement is attached" in s and "do NOT sign" in s for s in ret.sign)


def test_p021_the_rule_reaches_its_use_sites():
    excess = ira_contribution_eligibility(magi=200_000, filing_status="single", year=2025, ira_type="roth",
                                          contributed=7000)
    assert "calc op ira_recharacterization" in excess.work
    assert "ira_recharacterization" in roth_conversion.__doc__ and "408A(d)(6)(B)(iii)" in roth_conversion.__doc__
    rc = RetirementContributionsYear(roth_ira=Answer(value=7000, provenance=Provenance.user_stated()))
    notes = intake_checklist(Profile(retirement_contributions={2026: rc}), tax_year=2026).notes
    assert any("calc op ira_recharacterization" in n for n in notes)
    assert "calc op ira_recharacterization: N when the transfer is in the contribution year" in \
        DOC_SPECS["1099-R"].status_note
