"""Forms 8843, 8606 and 5329 carry their address boxes only when filed BY THEMSELVES (Phase K JK27).

Each face prints "Fill in your address(es) only if you are filing this form by itself and not with your (U.S.) tax
return", so attached to the return those boxes are correctly blank. Two verify_filing checks got that wrong:

* the cross-form identity check FAILed every correct Form 1040-NR + Form 8843 filing ("identity field
  'mailing_address' is blank on every form"): the 8843 pack DECLARES mailing_address, because a standalone 8843 must
  carry the current address (P-002), so the skip that saved Form 8606 in Phase I1 never reached it. The journey-2
  golden (packages/mcp-server/tests/test_journeys.py) found it;
* the confirmed-current-address check FAILed an attached Form 8606 or 5329 ("maps filer mailing-address lines but
  they are all BLANK") whenever the caller passed confirmed_current_address.

Packs now declare those lines in ``standalone_only_lines``; in a filing that holds a Form 1040, 1040-SR, 1040-NR or
1040-X a
blank there is correct, a filled one is still checked (against the confirmed current address, and against any form
that maps the same line), and a form verified alone still must carry its address. The shipped 2025 packs are used
with demo values (field dumps, no PDF).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from taxfill_core.schemas.formpack import FormPack, load_pack
from taxfill_core.verify import FilingItem, verify_filing

REPO = Path(__file__).resolve().parents[3]
FED = REPO / "formpacks" / "federal"
STREET, CITY, STATE, ZIP = "10 Sample Street", "Exampleville", "IL", "60000"
CURRENT = f"{STREET}, {CITY}, {STATE} {ZIP}"
PERSON = {"name.first": "Alex", "name.last": "Example", "identifying_number": "999880101"}


def _item(form_key: str, pack: FormPack, by_line: dict[str, str]) -> FilingItem:
    fields = {f.line: f for f in pack.fields}
    dump = {f"{pack.acroform_root}.{fields[line].field}": value for line, value in by_line.items()}
    return FilingItem(form_key=form_key, pack=pack, fields=dump)


def _return(form: str) -> FilingItem:
    pack = load_pack(FED / "2025" / form / "pack.yaml")
    return _item(form, pack, {**PERSON, "mailing_address.street": STREET, "mailing_address.city": CITY,
                              "mailing_address.state": STATE, "mailing_address.zip": ZIP})


def _f8843(mailing_address: str = "") -> FilingItem:
    pack = load_pack(FED / "2025" / "f8843" / "pack.yaml")
    return _item("f8843", pack, {**PERSON, "mailing_address": mailing_address, "home_country_address": ""})


def _single_name_form(form: str) -> FilingItem:
    pack = load_pack(FED / "2025" / form / "pack.yaml")
    blank_address = {f.line: "" for f in pack.fields if f.line.startswith("mailing_address")}
    return _item(form, pack, {"name": "Alex Example", "identifying_number": "999880101", **blank_address})


def _identity(report, field: str):
    return next(c for c in report.identity if c.field == field)


def test_an_attached_8843_may_leave_its_addresses_blank():
    report = verify_filing([_return("f1040nr"), _f8843()])
    assert [c.detail for c in report.identity if c.status == "FAIL"] == []
    check = _identity(report, "mailing_address")
    assert check.status == "SKIPPED" and "filed by themselves" in check.detail and "f1040nr" in check.detail
    assert next(p for p in report.pitfall_checks if p.id == "P-002").status == "PASS"


def test_a_filled_8843_address_is_still_compared():
    # The 8843 is the only form that maps a line named 'mailing_address', so the confirmed-address check is the one
    # that compares a filled 8843 address with where the filer receives mail today.
    report = verify_filing([_return("f1040nr"), _f8843("9 Old Apartment Road, Pastburg, NY 10000")],
                           confirmed_current_address=CURRENT)
    fails = [c for c in report.identity if c.status == "FAIL"]
    assert any("'f8843'" in c.detail and "Old Apartment" in c.detail for c in fails), [c.detail for c in fails]


def test_a_standalone_8843_must_still_carry_its_address():
    report = verify_filing([_f8843()])
    assert _identity(report, "mailing_address").status == "FAIL"
    assert next(p for p in report.pitfall_checks if p.id == "P-002").status == "FAIL"


@pytest.mark.parametrize("form", ["f8606", "f5329"])
def test_an_attached_form_with_blank_address_boxes_passes_the_confirmed_address_check(form):
    report = verify_filing([_return("f1040"), _single_name_form(form)], confirmed_current_address=CURRENT)
    fails = [c.detail for c in report.identity if c.status == "FAIL"]
    assert fails == [], fails
    assert next(p for p in report.pitfall_checks if p.id == "P-002").status == "PASS"


@pytest.mark.parametrize("form", ["f8606", "f5329"])
def test_the_same_form_filed_by_itself_still_needs_its_address(form):
    report = verify_filing([_single_name_form(form)], confirmed_current_address=CURRENT)
    assert any(c.status == "FAIL" and "all BLANK" in c.detail for c in report.identity)


def _shipped(form: str) -> list[Path]:
    return sorted(FED.glob(f"*/{form}/pack.yaml"))


@pytest.mark.parametrize("path", _shipped("f8843") + _shipped("f8606") + _shipped("f5329"),
                         ids=lambda p: f"{p.parts[-2]}-{p.parts[-3]}")
def test_every_shipped_by_itself_form_declares_its_address_lines(path):
    pack = load_pack(path)
    address = {f.line for f in pack.fields
               if re.match(r"(mailing_address|home_country_address)($|\.)", f.line)}
    assert address and set(pack.standalone_only_lines) == address


def test_standalone_only_lines_must_name_real_lines():
    raw = load_pack(FED / "2025" / "f8843" / "pack.yaml").model_dump()
    raw["standalone_only_lines"] = ["no_such_line"]
    with pytest.raises(ValidationError, match="standalone_only_lines"):
        FormPack.model_validate(raw)


# ── what counts as "your U.S. tax return" (JK27 final review) ──────────────────
# A blank address is correct only next to a Form 1040, 1040-SR or 1040-NR. The first cut counted every separately
# signed pack as a return, so a blank standalone 8843 passed beside a Form 843 claim or a Form W-7; and three
# mutations of the new verify logic left every test green. Each test below kills one.


def _filled(form: str, by_line: dict[str, str]) -> FilingItem:
    return _item(form, load_pack(FED / "2025" / form / "pack.yaml"), by_line)


@pytest.mark.parametrize("other", ["f843", "fw7"])
def test_a_claim_or_an_itin_application_is_not_the_return_an_8843_rides_with(other):
    if other == "f843":
        companion = _filled("f843", {"name": "Alex Example", "identifying_number": "999880101",
                                     "mailing_address.street": STREET, "mailing_address.city": CITY})
    else:
        companion = _filled("fw7", {"name.first": "Alex", "name.last": "Example"})
    report = verify_filing([companion, _f8843()])
    assert _identity(report, "mailing_address").status == "FAIL"
    assert next(p for p in report.pitfall_checks if p.id == "P-002").status == "FAIL"


def test_two_standalone_forms_do_not_excuse_each_others_blank_address():
    # Neither is a return: each is filed by itself, so each needs its address.
    report = verify_filing([_single_name_form("f8606"), _f8843()])
    assert _identity(report, "mailing_address").status == "FAIL"
    assert next(p for p in report.pitfall_checks if p.id == "P-002").status == "FAIL"


def test_only_the_standalone_lines_may_be_blank_on_an_attached_8843():
    pack = load_pack(FED / "2025" / "f8843" / "pack.yaml")
    blank_name = _item("f8843", pack, {**PERSON, "name.first": "", "mailing_address": "", "home_country_address": ""})
    report = verify_filing([_return("f1040nr"), blank_name])
    assert _identity(report, "name.first").status == "FAIL"


def test_a_second_return_never_excuses_a_returns_own_blank_address():
    pack = load_pack(FED / "2025" / "f1040" / "pack.yaml")
    blank = {f.line: "" for f in pack.fields if f.line.startswith("mailing_address")}
    f1040 = _item("f1040", pack, {**PERSON, **blank})
    report = verify_filing([f1040, _return("f1040nr")], confirmed_current_address=CURRENT)
    assert any(c.status == "FAIL" and "'f1040'" in c.detail and "all BLANK" in c.detail for c in report.identity)


def test_a_revised_8606_filed_with_a_1040x_may_leave_its_address_blank():
    # The Form 8606 instructions: "If necessary, complete a new Form 8606 showing the revised information and file it
    # with Form 1040-X." The 1040-X is the tax return it rides with.
    pack = load_pack(FED / "2025" / "f1040x" / "pack.yaml")
    lines = {f.line for f in pack.fields}
    by_line = {"name.first": "Alex", "name.last": "Example", "identifying_number": "999880101"}
    for key, value in (("mailing_address.street", STREET), ("mailing_address.city", CITY),
                       ("mailing_address.state", STATE), ("mailing_address.zip", ZIP)):
        if key in lines:
            by_line[key] = value
    f1040x = _item("f1040x", pack, by_line)
    report = verify_filing([f1040x, _single_name_form("f8606")], confirmed_current_address=CURRENT)
    assert [c.detail for c in report.identity if c.status == "FAIL"] == []
    assert next(p for p in report.pitfall_checks if p.id == "P-002").status == "PASS"
