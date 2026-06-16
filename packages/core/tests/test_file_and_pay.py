"""file_and_pay tests (dev plan section 9). Offline; uses the shipped 2023 pack."""

import pytest

from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay


def _only(manifest):
    return file_and_pay(manifest).returns[0]


def test_refund_with_direct_deposit_uses_no_payment_address():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=1600, state="California", direct_deposit=True)])
    assert "Refund of $1,600" in r.bottom_line
    assert "Ogden, UT 84201-0002" in r.mailing_address  # CA no-payment (refund)
    assert any("routing and account" in p for p in r.payment)
    assert any("statute of limitations" in d.lower() for d in r.deadlines)


def test_balance_due_by_check_resolves_payee_address_and_1040v():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-800, state="California")])
    assert "You owe $800" in r.bottom_line
    assert any('"United States Treasury"' in p for p in r.payment)
    assert "Cincinnati, OH 45280-2501" in r.mailing_address  # CA with-payment
    assert any("1040-V" in a for a in r.assemble)
    assert any("penalt" in d.lower() for d in r.deadlines)  # late-pay warning announced in advance


def test_paid_online_does_not_enclose_a_check():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-800, state="California", paid_online=True)])
    assert any("already paid" in p.lower() for p in r.payment)
    assert not any('"United States Treasury"' in p for p in r.payment)
    # Paid online -> mail to the no-payment (refund/no-check) address.
    assert "Ogden, UT 84201-0002" in r.mailing_address


def test_1040nr_uses_fixed_addresses_and_attached_form_not_signed():
    r = _only([FilingManifestItem(form="1040-NR", tax_year=2023, bottom_line=-200, attached_forms=["8843"])])
    assert "Charlotte, NC 28201-1303" in r.mailing_address  # NR with-payment
    assert any("8843" in s and "not" in s.lower() for s in r.sign)


def test_1040nr_refund_uses_austin_no_payment():
    r = _only([FilingManifestItem(form="1040-NR", tax_year=2023, bottom_line=300)])
    assert "Austin, TX 73301-0215" in r.mailing_address


def test_joint_return_requires_both_signatures():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=500, state="Texas", filing_jointly=True)])
    assert any("BOTH" in s for s in r.sign)


def test_refund_sol_expiry_is_three_years_after_due_date():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=1000, state="Texas")])
    # 2023 return due 2024-04-15 -> refund claim window closes ~2027-04-15.
    assert any("2027-04-15" in d for d in r.deadlines)


def test_citations_are_gov():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-800, state="California")])
    assert r.citations and all(c.url.startswith("https://") and ".gov" in c.url for c in r.citations)


def test_state_item_defers_to_m5():
    out = file_and_pay([FilingManifestItem(form="540", tax_year=2023, jurisdiction="states/ca", bottom_line=-100)])
    assert any("M5" in n for n in out.returns[0].notes)


def test_multiple_returns_get_separate_envelopes_note():
    out = file_and_pay([
        FilingManifestItem(form="1040", tax_year=2022, bottom_line=-100, state="Texas"),
        FilingManifestItem(form="1040", tax_year=2023, bottom_line=200, state="Texas"),
    ])
    assert len(out.returns) == 2
    assert any("own envelope" in n.lower() or "separate" in n.lower() for n in out.overall_notes)
    assert any("one envelope per return" in m.lower() for m in out.returns[0].mail)


def test_empty_manifest_rejected():
    with pytest.raises(ValueError, match="at least one"):
        file_and_pay([])
