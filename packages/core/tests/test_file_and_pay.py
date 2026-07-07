"""file_and_pay tests (dev plan section 9). Offline; uses the shipped 2023 pack."""

import pytest

from taxfill_core.file_and_pay import FilingManifestItem, _plus_years, file_and_pay


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


def test_supported_state_uses_the_pack():
    r = file_and_pay([FilingManifestItem(
        form="540", tax_year=2023, jurisdiction="states/ca", bottom_line=-100, state="California")]).returns[0]
    assert "You owe $100" in r.bottom_line
    assert any('"Franchise Tax Board"' in p for p in r.payment)
    assert r.mailing_address and "Franchise Tax Board" in r.mailing_address and "94267" in r.mailing_address  # with-payment
    assert any("does not conform to federal tax treaties" in n.lower() for n in r.notes)
    assert any("ftb.ca.gov" in c.url for c in r.citations)


def test_unsupported_state_points_to_dor():
    r = file_and_pay([FilingManifestItem(form="IT-201", tax_year=2023, jurisdiction="states/ny", bottom_line=-100)]).returns[0]
    assert any("dor" in n.lower() for n in r.notes)


def test_no_income_tax_state_in_manifest_says_nothing_to_file():
    r = file_and_pay([FilingManifestItem(form="N/A", tax_year=2023, jurisdiction="states/tx", bottom_line=0)]).returns[0]
    assert any("no personal income tax" in n.lower() for n in r.notes)
    assert not any("knowledge pack" in n.lower() for n in r.notes)


def test_supported_state_refund_uses_no_payment_address():
    r = file_and_pay([FilingManifestItem(
        form="540", tax_year=2023, jurisdiction="states/ca", bottom_line=500, direct_deposit=True)]).returns[0]
    assert "94240" in r.mailing_address  # CA refund / no-payment PO box
    assert not any('"Franchise Tax Board"' in p for p in r.payment)  # no check payee for a refund


def test_supported_state_paid_online_does_not_enclose_check():
    r = file_and_pay([FilingManifestItem(
        form="540", tax_year=2023, jurisdiction="states/ca", bottom_line=-100, paid_online=True)]).returns[0]
    assert any("already paid" in p.lower() for p in r.payment)
    assert "94240" in r.mailing_address  # paid online -> no check enclosed -> no-payment address


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


# ── FIX 1: abroad automatic extension, Form 4868, 1040-NR nonwage due date ──


def test_abroad_extension_and_form_4868_surfaced():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-800, state="California")])
    # Abroad automatic 2-month extension date from the pack, with the interest caveat.
    # Jun 15 2024 is a Saturday, so IRC 7503 shifts the deadline to 2024-06-17.
    assert any("abroad" in d.lower() and "2024-06-17" in d for d in r.deadlines)
    assert any("interest still accrues" in d.lower() for d in r.deadlines)
    # Form 4868 names that it extends time to file, not to pay.
    assert any("4868" in d and "NOT the time to PAY" in d for d in r.deadlines)


def test_1040nr_nonwage_due_date_framed_conditionally():
    r = _only([FilingManifestItem(form="1040-NR", tax_year=2023, bottom_line=-200)])
    # 1040-NR with no US-withholding wages: 15th day of the 6th month, from the pack.
    assert any("no US-withholding wages" in d and "2024-06-17" in d for d in r.deadlines)


def test_1040_does_not_get_nonwage_1040nr_line():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=1000, state="Texas")])
    # The 1040-NR nonwage line must not appear on a plain 1040. (Key on the
    # nonwage phrasing, not the bare date: 2024-06-17 is now also the abroad
    # automatic-extension date after the IRC 7503 weekend shift, and that line
    # DOES legitimately appear on a 1040.)
    assert not any("no US-withholding wages" in d for d in r.deadlines)


# ── FIX 2: refund statute-of-limitations "later of" rule ──


def test_refund_sol_states_later_of_rule_and_note():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=1000, state="Texas")])
    sol_line = next(d for d in r.deadlines if "statute of limitations" in d.lower())
    # "later of 3 years from filing or 2 years from payment" — both numbers from the pack.
    assert "later of 3 years from filing or 2 years from payment" in sol_line
    # On-time-filing caveat is stated.
    assert "assumes on-time filing" in sol_line
    assert "treated as filed on the due date" in sol_line
    # The pack's note is surfaced.
    assert "Note:" in sol_line


def test_balanced_return_does_not_get_penalty_warning():
    # A balanced, on-time return should NOT trigger the over-broad late-penalty line.
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=0, state="Texas")])
    assert not any("penalt" in d.lower() for d in r.deadlines)


def test_balance_due_still_gets_penalty_warning():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-800, state="California")])
    assert any("penalt" in d.lower() for d in r.deadlines)


# ── FIX 3: degraded no-pack path and _plus_years Feb-29 boundary ──


def test_degraded_path_when_no_knowledge_pack(tmp_path):
    # Point load_knowledge at an empty dir so the pack is guaranteed absent
    # regardless of which year packs ship — forces the FileNotFoundError path.
    (tmp_path / "federal").mkdir()
    out = file_and_pay(
        [FilingManifestItem(form="1040", tax_year=2023, bottom_line=500, state="Texas", filing_jointly=True)],
        knowledge_dir=tmp_path,
    )
    r = out.returns[0]
    # Degraded note appears.
    assert any("no federal knowledge pack" in n.lower() for n in r.notes)
    # MFJ both-spouses-sign still fires (it's pack-independent).
    assert any("BOTH" in s for s in r.sign)
    # No pack -> no resolved mailing address.
    assert r.mailing_address is None


def test_partial_pack_warns_per_missing_block_not_silent_empty(tmp_path):
    # A loaded-but-PARTIAL pack (tax block present, but the payment/mailing/
    # deadlines logistics blocks absent) for a balance-due 1040 must produce
    # explicit warning notes for each missing block — never a silent empty
    # deliverable (mailing_address=None, payment=[], deadlines=[], notes=[]).
    # Synthesize a partial pack so this stays valid now that every shipped year
    # is complete: take the real 2023 pack and strip its three logistics blocks.
    import yaml
    from pathlib import Path

    real = Path(__file__).resolve().parents[3] / "knowledge" / "federal" / "2023.yaml"
    raw = yaml.safe_load(real.read_text())
    for block in ("payment_options", "mailing_addresses", "deadlines"):
        raw.pop(block, None)
    fed = tmp_path / "federal"
    fed.mkdir()
    (fed / "2023.yaml").write_text(yaml.dump(raw, sort_keys=False))

    r = file_and_pay(
        [FilingManifestItem(form="1040", tax_year=2023, bottom_line=-500, state="California")],
        knowledge_dir=str(tmp_path),
    ).returns[0]
    # Pack loaded -> the FileNotFoundError "no federal knowledge pack" note must NOT fire.
    assert not any("no federal knowledge pack" in n.lower() for n in r.notes)
    # Explicit per-block warnings instead of silent empties.
    assert any("where-to-file" in n.lower() and "2023" in n and "irs.gov" in n.lower() for n in r.notes)
    assert any("payment options" in n.lower() and "2023" in n and "irs.gov" in n.lower() for n in r.notes)
    assert any("statute-of-limitations" in n.lower() and "2023" in n and "irs.gov" in n.lower() for n in r.notes)
    # No invented data leaked through.
    assert r.mailing_address is None
    assert r.payment == []
    assert r.deadlines == []


def test_plus_years_feb_29_boundary():
    # Feb 29 in a leap year + 3 years lands on a non-leap year -> clamps to Feb 28.
    assert _plus_years("2024-02-29", 3) == "2027-02-28"


ALL_PACK_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)


# ── FIX: a return filed with Form W-7 goes to the Austin ITIN Operation ──


def test_w7_attached_overrides_mailing_address_to_itin_operation():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-1721, state="Texas",
                                  filing_jointly=True, attached_forms=["W-7"])])
    assert "ITIN Operation" in r.mailing_address
    assert "P.O. Box 149342" in r.mailing_address and "78714-9342" in r.mailing_address
    # NOT the normal Texas with-payment (Charlotte) address.
    assert "Charlotte" not in r.mailing_address
    # The override is explained (why it ignores state/payment) and cited to the W-7 instructions.
    assert any("ITIN Operation" in n and "regardless" in n for n in r.notes)
    assert any("instructions/iw7" in c.url for c in r.citations)
    # It's a PO box -> the USPS-only guidance fires.
    assert any("P.O. Box" in m for m in r.mail)


def test_w7_override_applies_without_payment_and_for_the_fw7_pack_key():
    # Refund case (no check enclosed) + the 'fw7' form-key spelling: still Austin ITIN.
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=900, state="California",
                                  direct_deposit=True, attached_forms=["fw7"])])
    assert "ITIN Operation" in r.mailing_address and "78714-9342" in r.mailing_address


def test_w7_as_its_own_manifest_item_also_goes_to_itin_operation():
    r = _only([FilingManifestItem(form="W-7", tax_year=2023, bottom_line=0)])
    assert r.mailing_address and "ITIN Operation" in r.mailing_address


@pytest.mark.parametrize("year", ALL_PACK_YEARS)
def test_w7_itin_address_ships_for_every_pack_year(year):
    r = _only([FilingManifestItem(form="1040", tax_year=year, bottom_line=-100, state="Texas",
                                  attached_forms=["W-7"])])
    assert r.mailing_address and "78714-9342" in r.mailing_address


# ── FIX: the W-7 applicant MUST sign the attached W-7 (unlike 8843-style attachments) ──


def test_attached_w7_sign_line_says_applicant_signs_it():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-100, state="Texas",
                                  attached_forms=["W-7", "8843"])])
    w7_lines = [s for s in r.sign if "W-7" in s]
    assert w7_lines, "expected a W-7 sign line"
    assert all("do NOT sign it separately" not in s for s in w7_lines)
    assert any("Sign Here" in s and "applicant" in s for s in w7_lines)
    # The 8843-style rule is unchanged: attached 8843 is NOT separately signed.
    assert any("8843" in s and "do NOT sign it separately" in s for s in r.sign)


# ── FIX: standalone 8843 (information return) last mile ──


def test_standalone_8843_gets_the_fixed_austin_address_and_no_return_boilerplate():
    r = _only([FilingManifestItem(form="8843", tax_year=2023, bottom_line=0)])
    assert r.mailing_address == "Department of the Treasury, Internal Revenue Service Center, Austin, TX 73301-0215"
    # No payment guidance, no W-2/1099/1040-V assembly boilerplate, no state demanded.
    assert r.payment == []
    assert not any("W-2" in a or "1099" in a or "1040-V" in a for a in r.assemble)
    assert not any("mailing address depends on your state" in n for n in r.notes)
    assert "information return" in r.bottom_line and "no tax due" in r.bottom_line
    # Signed standalone (page 2), unlike when attached to a 1040-NR.
    assert any("page 2" in s and "sign" in s.lower() for s in r.sign)
    # Cited to the Form 8843 instructions.
    assert any("about-form-8843" in c.url for c in r.citations)


def test_standalone_8843_deadlines_have_no_monetary_penalty_threat():
    r = _only([FilingManifestItem(form="8843", tax_year=2023, bottom_line=0)])
    # Due by the 1040-NR due date; the no-wage June date is surfaced from the pack.
    assert any("2024-06-17" in d for d in r.deadlines)
    # The stake is the exempt-individual day exclusion — never monetary penalties.
    assert any("exempt-individual" in d for d in r.deadlines)
    for d in r.deadlines:
        if "penalt" in d.lower():
            assert "no late-payment penalty" in d
    assert not any("4868" in d for d in r.deadlines)


def test_standalone_8843_ignores_state_for_the_address():
    r = _only([FilingManifestItem(form="8843", tax_year=2023, bottom_line=0, state="California")])
    assert "73301-0215" in r.mailing_address and "Ogden" not in r.mailing_address


# ── FIX: two-letter state codes resolve like full names ──


@pytest.mark.parametrize("state", ["CA", "ca", "California"])
def test_state_codes_and_full_names_both_resolve(state):
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-800, state=state)])
    assert "Cincinnati, OH 45280-2501" in r.mailing_address


def test_dc_code_resolves():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=500, state="DC")])
    assert "Kansas City, MO 64999-0002" in r.mailing_address


def test_unknown_state_note_is_prescriptive():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-800, state="Californai")])
    assert r.mailing_address is None
    note = next(n for n in r.notes if "where-to-file" in n)
    # The note tells the agent exactly what formats work.
    assert "two-letter USPS code" in note and "'California'" in note


# ── FIX: 1040-NR check memo and attachments are form-aware ──


@pytest.mark.parametrize("year", ALL_PACK_YEARS)
def test_1040nr_check_memo_names_1040nr_every_pack_year(year):
    r = _only([FilingManifestItem(form="1040-NR", tax_year=year, bottom_line=-465)])
    memo = next(p for p in r.payment if "payable" in p)
    assert f'"{year} Form 1040-NR"' in memo
    assert f'"{year} Form 1040" (or' not in memo and f'"{year} Form 1040" or' not in memo


def test_1040nr_assemble_names_1042s():
    r = _only([FilingManifestItem(form="1040-NR", tax_year=2023, bottom_line=-465)])
    assert any("1042-S" in a for a in r.assemble)


def test_plain_1040_memo_and_assemble_unchanged():
    r = _only([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-800, state="Texas")])
    memo = next(p for p in r.payment if "payable" in p)
    assert '"2023 Form 1040"' in memo and "1040-NR" not in memo
    assert not any("1042-S" in a for a in r.assemble)


# ── FIX: deadline citation follows the form family (1040 vs 1040-NR booklet) ──


@pytest.mark.parametrize("year", ALL_PACK_YEARS)
def test_plain_1040_never_cites_the_1040nr_booklet(year):
    r = _only([FilingManifestItem(form="1040", tax_year=year, bottom_line=-100, state="Texas")])
    assert r.citations
    assert not any("i1040nr" in c.url for c in r.citations)


@pytest.mark.parametrize("year", ALL_PACK_YEARS)
def test_1040nr_deadline_cites_the_nr_instructions(year):
    r = _only([FilingManifestItem(form="1040-NR", tax_year=year, bottom_line=-100)])
    assert any("i1040nr" in c.url for c in r.citations)
