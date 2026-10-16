"""Amended returns in file_and_pay and filing_summary (Phase K JK27).

Before JK27 neither tool knew an amended return. A TY2024 Form 1040-X balance due for a Georgia resident got the Form
1040 checklist: the Form 1040 address, a "Form 1040" check memo, the Form 1040-V voucher and the original due date. A
Georgia Form 500X got the Form 500 payment address (PO Box 740399) and the original due date. The journey-5 golden
(packages/mcp-server/tests/test_journeys.py) found both.

Now a federal amended item follows the current Instructions for Form 1040-X (Rev. December 2025; a continuous-use form,
so the current instructions govern whatever year is amended), and a state amended item follows the state pack's
``amended_return`` block, or gets a pointer to the DOR with no address, voucher or due date at all.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from taxfill_core.file_and_pay import (
    _STATE_REVENUE_SITES,
    _F1040X_AUSTIN,
    _F1040X_AUSTIN_INTERNATIONAL,
    _F1040X_BY_STATE,
    _F1040X_KANSAS_CITY,
    _F1040X_OGDEN,
    _STATE_NAMES,
    FilingManifestItem,
    _is_amended,
    file_and_pay,
)
from taxfill_core.filing_summary import filing_summary


TODAY = date(2026, 10, 16)


def _one(**kw):
    return file_and_pay([FilingManifestItem(**kw)], today=TODAY).returns[0]


def _text(ret) -> str:
    return json.dumps(ret.model_dump())


# ── which items are amended ───────────────────────────────────────────────────


@pytest.mark.parametrize("form,amended,expected", [
    ("1040-X", None, True), ("1040X", None, True), ("f1040x", None, True), ("Form 1040-X", None, True),
    ("500X", None, True), ("IT-201-X", None, True), ("1040", None, False), ("1040-NR", None, False),
    ("843", None, False), ("Form 1", True, True), ("500X", False, False),
])
def test_an_amended_return_is_named_or_flagged(form, amended, expected):
    item = FilingManifestItem(form=form, tax_year=2024, bottom_line=0, amended=amended)
    assert _is_amended(item) is expected


# ── Form 1040-X ───────────────────────────────────────────────────────────────


def test_the_1040x_table_covers_every_state_and_dc_once():
    assert set(_F1040X_BY_STATE) == set(_STATE_NAMES.values())
    groups = {addr: sorted(st for st, a in _F1040X_BY_STATE.items() if a == addr) for addr in set(_F1040X_BY_STATE.values())}
    assert {addr: len(states) for addr, states in groups.items()} == {
        _F1040X_AUSTIN: 8, _F1040X_OGDEN: 20, _F1040X_KANSAS_CITY: 23}


@pytest.mark.parametrize("state,address", [
    ("GA", _F1040X_AUSTIN), ("Texas", _F1040X_AUSTIN), ("CA", _F1040X_OGDEN), ("IA", _F1040X_OGDEN),
    ("NY", _F1040X_KANSAS_CITY), ("DC", _F1040X_KANSAS_CITY), ("georgia", _F1040X_AUSTIN), (" ny ", _F1040X_KANSAS_CITY),
])
def test_a_1040x_goes_to_the_1040x_address_for_the_filers_state(state, address):
    ret = _one(form="1040-X", tax_year=2024, bottom_line=-264, state=state, attached_forms=["1040"])
    assert ret.mailing_address == address


def test_a_georgia_1040x_balance_due_is_not_a_form_1040_checklist():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=-264, state="GA", attached_forms=["1040"])
    text = _text(ret)
    assert ret.mailing_address == "Department of the Treasury, Internal Revenue Service, Austin, TX 73301-0052"
    assert '\\"U.S. Treasury\\"' in text and "2024 Form 1040-X" in text
    assert "Put Form 1040-V and the check on top" not in text and "name no payment voucher" in text
    assert "enclose (don't attach) your check or money order" in text
    # the corrected return behind it, the December 2025 revision's new requirement
    assert any("completed and updated Form 1040 for 2024" in a for a in ret.assemble)
    # interest from the original due date, never "Original due date ... file before then"
    assert not any(d.startswith("Original due date") for d in ret.deadlines)
    assert any("2025-04-15" in p for p in ret.payment)
    assert any(c.url == "https://www.irs.gov/pub/irs-pdf/i1040x.pdf" for c in ret.citations)


def test_a_1040x_amending_a_1040nr_goes_to_austin_0215_whatever_the_state():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=-50, state="NY", attached_forms=["1040-NR"])
    assert ret.mailing_address == _F1040X_AUSTIN_INTERNATIONAL


@pytest.mark.parametrize("extra", [{"dual_status": True}, {"attached_forms": ["1040", "2555"]}])
def test_dual_status_and_foreign_earned_income_filers_use_austin_0215(extra):
    ret = _one(**{"form": "1040-X", "tax_year": 2024, "bottom_line": -50, "state": "IL",
                  "attached_forms": ["1040"], **extra})
    assert ret.mailing_address == _F1040X_AUSTIN_INTERNATIONAL


def test_a_territory_or_foreign_state_gets_no_guess():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=-50, state="Puerto Rico", attached_forms=["1040"])
    assert ret.mailing_address is None
    assert any("Pub. 570" in n and "73301-0215" in n for n in ret.notes)


def test_a_1040x_refund_comes_by_check_within_the_claim_window():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=300, state="CA", attached_forms=["1040"], direct_deposit=True)
    assert any("can't be deposited directly" in p for p in ret.payment)
    assert any("2028-04-15" in d and "within 3 years" in d for d in ret.deadlines)
    assert any("cannot request it" in n for n in ret.notes)


def test_an_amended_1040_item_is_routed_to_the_1040x_checklist():
    ret = _one(form="1040", amended=True, tax_year=2024, bottom_line=-40, state="OH")
    assert ret.mailing_address == _F1040X_OGDEN
    assert any("amended on Form 1040-X" in n for n in ret.notes)


def test_a_1040x_without_the_corrected_return_says_it_is_needed():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=-40, state="OH")
    assert any("names no corrected return" in n for n in ret.notes)


# ── state amended returns ─────────────────────────────────────────────────────


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_a_georgia_500x_follows_the_500x_rules(year):
    ret = _one(form="500X", tax_year=year, jurisdiction="states/ga", bottom_line=-65)
    text = _text(ret)
    assert ret.mailing_address == "PROCESSING CENTER, GEORGIA DEPARTMENT OF REVENUE, PO BOX 740318, ATLANTA, GA 30374-0318"
    assert "740399" not in text and "740392" not in text  # the Form 500 boxes
    assert f"{year + 1}-04-15" not in json.dumps(ret.deadlines)  # the original return's due date
    assert any("Pay in full with this Return" in p for p in ret.payment)
    # the 525-TV is right for a 500X: its "Amended Return" box, mailed with the paper return
    assert any('"Amended Return" box checked' in p for p in ret.payment)
    assert any("three (3) years" in d for d in ret.deadlines) and any("180 days" in d for d in ret.deadlines)
    assert any(c.url.endswith(f"{year}-500x-amended-individual-income-tax-return-blank-form-printing/download")
               for c in ret.citations)


def test_a_state_without_amended_rules_gets_a_pointer_not_the_original_return():
    ret = _one(form="540X", tax_year=2024, jurisdiction="states/ca", bottom_line=-90)
    assert ret.mailing_address is None and ret.payment == [] and ret.deadlines == []
    assert any("carries no amended-return rules" in n for n in ret.notes)


def test_a_flagged_state_amendment_on_the_original_form_is_amended_too():
    ret = _one(form="Form 1", amended=True, tax_year=2024, jurisdiction="states/ma", bottom_line=-90)
    assert ret.mailing_address is None and any("amended MA return" in n for n in ret.notes)


# ── filing_summary ────────────────────────────────────────────────────────────


def test_filing_summary_reads_amended_items_as_amendments():
    items = [FilingManifestItem(form="1040-X", tax_year=2024, bottom_line=-264, state="GA", attached_forms=["1040"]),
             FilingManifestItem(form="500X", tax_year=2024, jurisdiction="states/ga", bottom_line=-65)]
    fed, ga = filing_summary(items, today=date(2026, 10, 16)).items
    assert "amended (Form 1040-X): you owe $264 more" in fed.headline
    assert "late-filing" not in fed.deadline_status and "2025-04-15" in fed.deadline_status
    assert "amended (500X)" in ga.headline
    assert "Due 2025-04-15" not in ga.deadline_status and "three (3) years" in ga.deadline_status


@pytest.mark.parametrize("form", ["Form M1, Individual Income Tax", "Form IT-201, Resident Income Tax Return",
                                  "Schedule X", "Tax", "1040-NR", "W-7", "8843", "Form 511-TX", "511-TX"])
def test_descriptive_words_never_make_a_return_amended(form):
    # "Form M1, Individual Income Tax" ends in an x: the first cut of the rule read every Minnesota return as amended
    # (caught by the JK21 golden mn_2025.json). Only the form-number token counts.
    assert _is_amended(FilingManifestItem(form=form, tax_year=2025, bottom_line=0)) is False


def test_no_shipped_state_form_name_reads_as_amended():
    from pathlib import Path

    import yaml

    names = []
    for path in sorted((Path(__file__).resolve().parents[3] / "knowledge" / "states").glob("*/[0-9][0-9][0-9][0-9].yaml")):
        forms = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("forms") or {}
        names += [(path.parent.name, path.stem, k, v) for k, v in forms.items() if isinstance(v, str)]
    assert names
    flagged = [n for n in names if _is_amended(FilingManifestItem(form=n[3], tax_year=int(n[1]), bottom_line=0))]
    # A pack may legitimately list its amended form under an 'amended' key; nothing else may read as amended.
    assert [n for n in flagged if "amend" not in n[2].lower()] == []


# ── what the Form 1040 checklist does carries over to the Form 1040-X (JK27 final review) ──────────────────────────


def test_a_1040x_with_a_w7_goes_to_the_itin_operation_and_the_w7_is_signed():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=100, state="TX", filing_jointly=True,
               attached_forms=["1040", "W-7"])
    assert "ITIN Operation" in ret.mailing_address
    assert any("W-7 IS signed separately" in s for s in ret.sign)
    assert not any("W-7 is attached to this amended return" in s for s in ret.sign)


def test_a_1040x_making_the_6013_choice_carries_the_statement_and_pub_519s_amended_steps():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=500, state="CA", filing_jointly=True,
               section_6013_election=True, attached_forms=["1040"])
    assert ret.assemble[0].startswith("ATTACH THE §6013(g)/(h) ELECTION STATEMENT")
    assert any("enter 'Amended' across the top of the corrected return" in a for a in ret.assemble)
    assert any("signed by BOTH spouses" in s for s in ret.sign)
    assert any("within 3 years from the date you filed your original" in d for d in ret.deadlines)
    assert any(c.url == "https://www.irs.gov/publications/p519" for c in ret.citations)


def test_a_dual_status_1040x_marks_the_updated_return():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=-50, state="IL", dual_status=True, attached_forms=["1040"])
    assert ret.mailing_address == _F1040X_AUSTIN_INTERNATIONAL
    assert any('"Dual-Status Return"' in a and "Form 1040-NR as the DUAL-STATUS STATEMENT" in a for a in ret.assemble)
    assert any("NO standard deduction" in a for a in ret.assemble)


@pytest.mark.parametrize("corrected", ["1040-NR", "1040-NR-EZ"])
def test_a_paper_1040x_amending_a_1040nr_follows_the_page_2_procedure(corrected):
    ret = _one(form="1040-X", tax_year=2024, bottom_line=-50, state="NY", attached_forms=[corrected])
    assert ret.mailing_address == _F1040X_AUSTIN_INTERNATIONAL
    lead = ret.assemble[0]
    assert "Don't enter any other information on page 1" in lead and "write 'Amended.'" in lead
    assert "completed \"in its entirety\"" in lead


def test_a_paid_online_1040x_does_not_ask_to_pay_again():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=-75, state="OH", paid_online=True, attached_forms=["1040"])
    assert not any("pay with the amended return or sooner" in p for p in ret.payment)
    assert any("until it was paid" in p for p in ret.payment)
    assert not any("loose in the envelope" in a for a in ret.assemble)


def test_a_zero_1040x_has_no_deadline_and_cites_no_due_date():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=0, state="OH", attached_forms=["1040"])
    assert ret.deadlines == [] and ret.payment == []
    assert not any("i1040gi" in c.url for c in ret.citations)


def test_the_refund_window_runs_from_april_15_even_when_a_weekend_moved_the_due_date():
    # TY2022's due date was 2023-04-18; an early or on-time original "is considered filed on the due date (generally
    # April 15)".
    ret = _one(form="1040-X", tax_year=2022, bottom_line=300, state="CA", attached_forms=["1040"])
    assert any("run to 2026-04-15" in d for d in ret.deadlines), ret.deadlines


@pytest.mark.parametrize("form", ["1040 X", "IRS 1040-X", "Federal Form 1040-X", "1040‑X", "U.S. 1040-X"])
def test_other_spellings_of_1040x_get_the_1040x_checklist(form):
    ret = _one(form=form, tax_year=2024, bottom_line=-264, state="GA", attached_forms=["1040"])
    assert ret.mailing_address == _F1040X_AUSTIN


def test_a_non_1040_federal_x_form_is_not_given_the_1040x_checklist():
    ret = _one(form="941-X", tax_year=2024, bottom_line=-10, state="GA")
    assert ret.mailing_address != _F1040X_AUSTIN and not ret.bottom_line.startswith("Amended")


@pytest.mark.parametrize("form,jurisdiction", [
    ("MI-1040X-12", "states/mi"), ("DR 0104X", "states/co"), ("IA 1040X", "states/ia"), ("IT 1040X", "states/oh"),
    ("1040XN", "states/ne"), ("RI-1040X-R", "states/ri"), ("RI-1040X-NR", "states/ri"),
])
def test_real_state_amended_form_names_are_read_as_amended(form, jurisdiction):
    ret = _one(form=form, tax_year=2024, jurisdiction=jurisdiction, bottom_line=-100)
    assert ret.mailing_address is None and ret.deadlines == []
    assert any("carries no amended-return rules" in n for n in ret.notes)
    summary = filing_summary([FilingManifestItem(form=form, tax_year=2024, jurisdiction=jurisdiction, bottom_line=-100)],
                             today=TODAY).items[0]
    assert "amended" in summary.headline and "Due 2025" not in summary.deadline_status
    code = jurisdiction.split("/")[1].upper()
    assert [c.url for c in summary.citations] == [c.url for c in ret.citations]
    assert _STATE_REVENUE_SITES[code] in summary.deadline_status


def test_a_state_without_amended_rules_points_to_its_revenue_site():
    ret = _one(form="IT 1040X", tax_year=2024, jurisdiction="states/oh", bottom_line=-90)
    assert [c.url for c in ret.citations] == [
        "https://tax.ohio.gov/", "https://www.irs.gov/businesses/small-businesses-self-employed/state-government-websites"]
    assert "https://tax.ohio.gov/" in ret.notes[0]


def test_every_income_tax_state_has_a_vetted_revenue_site():
    from pathlib import Path

    from taxfill_core.knowledge import Citation

    root = Path(__file__).resolve().parents[3] / "knowledge" / "states"
    codes = {d.name.upper() for d in root.iterdir() if d.is_dir() and any(p.stem.isdigit() for p in d.glob("*.yaml"))}
    assert codes == set(_STATE_REVENUE_SITES)
    for code, url in _STATE_REVENUE_SITES.items():
        Citation(source=code, url=url)  # a government host, or the model refuses it


def test_the_georgia_amended_checklist_does_not_recommend_certified_mail():
    ret = _one(form="500X", tax_year=2024, jurisdiction="states/ga", bottom_line=-90)
    assert not any("Certified Mail" in m for m in ret.mail) and any("certified mail" in m for m in ret.mail)


def test_every_shipped_pack_form_name_reads_as_amended_only_when_it_is_one():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[3]
    names = set()
    for pack in root.glob("formpacks/*/*/*/pack.yaml"):
        names.add(str(yaml.safe_load(pack.read_text(encoding="utf-8"))["form"]))
    for pack in root.glob("formpacks/*/*/*/*/pack.yaml"):
        names.add(str(yaml.safe_load(pack.read_text(encoding="utf-8"))["form"]))
    for pack in root.glob("formpacks/*/*/*/*/handfill.yaml"):
        names.add(str((yaml.safe_load(pack.read_text(encoding="utf-8")) or {}).get("form", "")))
    names.discard("")
    amended = sorted(n for n in names if _is_amended(FilingManifestItem(form=n, tax_year=2024, bottom_line=0)))
    assert amended == ["1040-X"], amended


def test_form_names_are_not_prefixed_twice():
    ret = _one(form="Form 540", amended=True, tax_year=2023, jurisdiction="states/ca", bottom_line=-100)
    assert ret.bottom_line == "Amended CA 2023 return (Form 540): you owe $100 more."


def test_a_postponed_due_date_moves_the_refund_window():
    # TY2020's due date was postponed to 2021-05-17 (the pack records the window moving with it); a weekend shift
    # (TY2022, 2023-04-18) does not move it.
    ret = _one(form="1040-X", tax_year=2020, bottom_line=300, state="CA", attached_forms=["1040"])
    assert any("run to 2024-05-17" in d for d in ret.deadlines), ret.deadlines


def test_an_old_year_is_amended_on_paper_and_says_its_window_has_passed():
    ret = _one(form="1040-X", tax_year=2021, bottom_line=300, state="CA", attached_forms=["1040"], direct_deposit=True)
    assert any("A 2021 amendment must be filed on paper" in n for n in ret.notes)
    assert not any(n.startswith("E-file alternative") for n in ret.notes)
    assert any("can no longer be filed electronically" in n for n in ret.notes)
    assert any("That date has passed" in d for d in ret.deadlines)
    recent = _one(form="1040-X", tax_year=2024, bottom_line=300, state="CA", attached_forms=["1040"])
    assert any(n.startswith("E-file alternative") for n in recent.notes)
    assert not any("That date has passed" in d for d in recent.deadlines)


def test_a_w7_package_goes_by_usps_not_a_private_delivery_service():
    ret = _one(form="1040-X", tax_year=2024, bottom_line=100, state="TX", attached_forms=["1040", "W-7"])
    assert not any("PDSStreetAddresses" in m for m in ret.mail)
    assert any("must go by USPS" in m for m in ret.mail)


def test_filing_summary_matches_the_checklist_for_paid_and_zero_amendments():
    paid, zero = filing_summary([
        FilingManifestItem(form="1040-X", tax_year=2024, bottom_line=-75, state="OH", paid_online=True),
        FilingManifestItem(form="1040-X", tax_year=2024, bottom_line=0, state="OH"),
    ], today=TODAY).items
    assert "until it was paid" in paid.deadline_status and "or sooner" not in paid.deadline_status
    assert not any("i1040gi" in c.url for c in zero.citations)
