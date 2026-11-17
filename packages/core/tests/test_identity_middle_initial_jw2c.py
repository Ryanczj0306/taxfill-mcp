"""JW2c (walkthrough finding P1-04): a combined "first name and middle initial" box against separate boxes.

Form 1040 prints "Your first name and middle initial" as one box; Form 540 prints "Your first name" and "Initial".
Both packs key the first-name box ``name.first``, so the identity check compared 'Avery J.' (1040) with 'Avery'
(540) and failed a correct filing. The check now compares the combined box with first name + initial (periods dropped,
spaces collapsed, case-folded) whenever the filing mixes the two shapes; an initial on one form only is no difference.
Fictitious names only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.schemas.formpack import FormPack, load_pack
from taxfill_core.verify import FilingItem, qualified_field_name, verify_filing

REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT = "topmostSubform[0]"


def _pack(form: str, lines: list[str], identity: list[str]) -> FormPack:
    return FormPack.model_validate({
        "form": form,
        "jurisdiction": "federal",
        "tax_year": 2023,
        "source_url": "https://www.irs.gov/pub/irs-prior/test.pdf",
        "pdf_sha256": "...",
        "acroform_root": ROOT,
        "fields": [{"line": line, "field": f"Page1[0].f_{line.replace('.', '_')}[0]", "type": "text"}
                   for line in lines],
        "identity_fields": identity,
    })


def _item(form_key: str, pack: FormPack, raw_by_line: dict[str, str]) -> FilingItem:
    by_line = {f.line: f for f in pack.fields}
    fields = {qualified_field_name(pack, by_line[line]): raw for line, raw in raw_by_line.items()}
    return FilingItem(form_key=form_key, pack=pack, fields=fields)


COMBINED = _pack("F-COMBINED", ["name.first", "name.last"], ["name.first", "name.last"])
SEPARATE = _pack("F-SEPARATE", ["name.first", "name.middle_initial", "name.last"], ["name.first", "name.last"])


def _first_name_check(items: list[FilingItem]):
    report = verify_filing(items)
    return next(check for check in report.identity if check.field == "name.first")


@pytest.mark.parametrize("combined_first", [True, False], ids=["combined-listed-first", "separate-listed-first"])
@pytest.mark.parametrize("combined, first, initial", [
    ("Avery J.", "Avery", "J"),
    ("Avery J", "Avery", "J."),
    ("Avery  J", "Avery ", "J"),        # extra spaces
    ("AVERY j.", "avery", "J"),
    ("Avery", "Avery", ""),             # no initial on either form
    ("Mary Ann K.", "Mary Ann", "K"),   # a two-word first name
    ("Avery J.", "Avery", ""),          # an initial on one form only is no difference
    ("Avery", "Avery", "J"),
])
def test_combined_box_matches_first_name_plus_initial(combined, first, initial, combined_first):
    items = [_item("f1040", COMBINED, {"name.first": combined, "name.last": "Example"}),
             _item("form540", SEPARATE, {"name.first": first, "name.middle_initial": initial, "name.last": "Example"})]
    check = _first_name_check(items if combined_first else items[::-1])
    assert check.status == "PASS", check.detail
    assert "first name + middle initial" in check.detail


@pytest.mark.parametrize("combined_first", [True, False], ids=["combined-listed-first", "separate-listed-first"])
@pytest.mark.parametrize("combined, first, initial", [
    ("Avery J.", "Avery", "K"),     # a different initial
    ("Avery", "Avory", ""),         # a different first name
    ("Avery J.", "Avory", "J"),     # a different first name, same initial
    ("Avery J.", "Avory", ""),      # a different first name, one initial
    ("Joe", "Jo", "E"),             # spaces are collapsed, not removed
])
def test_a_real_difference_still_fails(combined, first, initial, combined_first):
    items = [_item("f1040", COMBINED, {"name.first": combined, "name.last": "Example"}),
             _item("form540", SEPARATE, {"name.first": first, "name.middle_initial": initial, "name.last": "Example"})]
    check = _first_name_check(items if combined_first else items[::-1])
    assert check.status == "FAIL", check.detail
    assert "differs across the filing" in check.detail


def test_the_spouse_name_composes_the_same_way():
    combined = _pack("F-COMBINED", ["name.spouse_first"], ["name.spouse_first"])
    separate = _pack("F-SEPARATE", ["name.spouse_first", "name.spouse_middle_initial"], ["name.spouse_first"])
    good = verify_filing([
        _item("main", combined, {"name.spouse_first": "Jordan R."}),
        _item("state", separate, {"name.spouse_first": "Jordan", "name.spouse_middle_initial": "R"}),
    ])
    assert next(c for c in good.identity if c.field == "name.spouse_first").status == "PASS"
    bad = verify_filing([
        _item("main", combined, {"name.spouse_first": "Jordan R."}),
        _item("state", separate, {"name.spouse_first": "Jordan", "name.spouse_middle_initial": "S"}),
    ])
    assert next(c for c in bad.identity if c.field == "name.spouse_first").status == "FAIL"


def test_forms_of_one_shape_compare_as_before():
    # Two combined boxes: the strings are compared as before (case-folded).
    report = verify_filing([
        _item("a", COMBINED, {"name.first": "Avery J.", "name.last": "Example"}),
        _item("b", COMBINED, {"name.first": "avery j.", "name.last": "Example"}),
    ])
    check = next(c for c in report.identity if c.field == "name.first")
    assert check.status == "PASS" and "middle initial" not in check.detail
    # Two separate-box forms compare the first-name box only, as before.
    report = verify_filing([
        _item("a", SEPARATE, {"name.first": "Avery", "name.middle_initial": "J", "name.last": "Example"}),
        _item("b", SEPARATE, {"name.first": "Avery", "name.middle_initial": "J", "name.last": "Example"}),
    ])
    assert next(c for c in report.identity if c.field == "name.first").status == "PASS"


def _shipped_item(form_key: str, rel_pack: str, raw_by_line: dict[str, str]) -> FilingItem:
    pack = load_pack(REPO_ROOT / rel_pack)
    return _item(form_key, pack, raw_by_line)


@pytest.mark.parametrize("initial, status", [("J", "PASS"), ("K", "FAIL")])
def test_shipped_2025_form_1040_and_form_540_packs(initial, status):
    """The walkthrough's pair: Form 1040 2025 'Your first name and middle initial' against Form 540 2025."""
    f1040 = _shipped_item("f1040", "formpacks/federal/2025/f1040/pack.yaml",
                          {"name.first": "Avery J.", "name.last": "Example", "identifying_number": "999881234"})
    form540 = _shipped_item("form540", "formpacks/states/ca/2025/form540/pack.yaml",
                            {"name.first": "Avery", "name.middle_initial": initial, "name.last": "Example",
                             "identifying_number": "999-88-1234"})
    check = _first_name_check([f1040, form540])
    assert check.status == status, check.detail


def test_two_different_initials_across_three_forms_fail():
    check = _first_name_check([
        _item("f1040", COMBINED, {"name.first": "Avery", "name.last": "Example"}),
        _item("form540", SEPARATE, {"name.first": "Avery", "name.middle_initial": "J", "name.last": "Example"}),
        _item("d40", SEPARATE, {"name.first": "Avery", "name.middle_initial": "K", "name.last": "Example"}),
    ])
    assert check.status == "FAIL", check.detail


# Verifier round 1: the separate initial box is found under every key a shipped pack gives it. IA 1040 2025 prints
# "First Name MI" (key name.mi), OR-40 2025 "First name" and "Initial" (key name.initial), and Form W-7 "1a First name
# Middle name Last name" (key name.middle, a full middle name whose first letter is the initial).
F1040 = "formpacks/federal/2025/f1040/pack.yaml"
F1040_VALUES = {"name.first": "Avery J.", "name.last": "Example", "identifying_number": "999881234"}


@pytest.mark.parametrize("combined_first", [True, False], ids=["f1040-listed-first", "state-listed-first"])
@pytest.mark.parametrize("rel_pack, initial_key, initial, status", [
    ("formpacks/states/ia/2025/ia1040/pack.yaml", "name.mi", "J", "PASS"),
    ("formpacks/states/ia/2025/ia1040/pack.yaml", "name.mi", "K", "FAIL"),
    ("formpacks/federal/2025/fw7/pack.yaml", "name.middle", "Jordan", "PASS"),
    ("formpacks/federal/2025/fw7/pack.yaml", "name.middle", "Kendall", "FAIL"),
])
def test_shipped_2025_form_1040_against_other_initial_keys(rel_pack, initial_key, initial, status, combined_first):
    f1040 = _shipped_item("f1040", F1040, F1040_VALUES)
    other = _shipped_item("other", rel_pack, {"name.first": "Avery", initial_key: initial, "name.last": "Example"})
    check = _first_name_check([f1040, other] if combined_first else [other, f1040])
    assert check.status == status, check.detail
    assert "first name + middle initial" in check.detail


@pytest.mark.parametrize("initial, status", [("J", "PASS"), ("K", "FAIL")])
def test_shipped_2025_form_1040_nr_against_or_40(initial, status):
    # Form 1040-NR declares name.first; OR-40 prints "Initial" apart from "First name".
    f1040nr = _shipped_item("f1040nr", "formpacks/federal/2025/f1040nr/pack.yaml", F1040_VALUES)
    or40 = _shipped_item("or40", "formpacks/states/or/2025/or40/pack.yaml",
                         {"name.first": "Avery", "name.initial": initial})
    check = _first_name_check([f1040nr, or40])
    assert check.status == status, check.detail


@pytest.mark.parametrize("ia_initial, status", [("J", "PASS"), ("K", "FAIL")])
def test_the_result_does_not_depend_on_which_other_forms_are_present(ia_initial, status):
    f1040 = _shipped_item("f1040", F1040, F1040_VALUES)
    ia1040 = _shipped_item("ia1040", "formpacks/states/ia/2025/ia1040/pack.yaml",
                           {"name.first": "Avery", "name.mi": ia_initial, "name.last": "Example"})
    form540 = _shipped_item("form540", "formpacks/states/ca/2025/form540/pack.yaml",
                            {"name.first": "Avery", "name.middle_initial": "J", "name.last": "Example"})
    assert _first_name_check([f1040, ia1040]).status == status
    assert _first_name_check([f1040, ia1040, form540]).status == status


# Verifier round 1: Form 1040's "Home address (number and street)" and "Apt. no." boxes against a state that prints the
# apartment inside the street box (ME 1040ME "Current Mailing Address (P.O. Box, street, and apartment number)", KY 740
# "Mailing Address (Number and Street including Apartment Number or P.O. Box)").
ONE_BOX_STREET_PACKS = ["formpacks/states/me/2025/f1040me/pack.yaml", "formpacks/states/ky/2025/form740/pack.yaml"]


def _street_check(state_pack: str, state_street: str, f1040_street: str = "100 Main St", apt: str = "4B",
                  f1040_first: bool = True):
    f1040 = _shipped_item("f1040", F1040, {"mailing_address.street": f1040_street, "mailing_address.apt": apt})
    state = _shipped_item("state", state_pack, {"mailing_address.street": state_street})
    report = verify_filing([f1040, state] if f1040_first else [state, f1040])
    return next(check for check in report.identity if check.field == "mailing_address.street")


@pytest.mark.parametrize("f1040_first", [True, False], ids=["f1040-listed-first", "state-listed-first"])
@pytest.mark.parametrize("state_pack", ONE_BOX_STREET_PACKS)
@pytest.mark.parametrize("state_street", ["100 Main St Apt 4B", "100 Main St, Apt. 4B", "100 MAIN ST #4B",
                                          "100 Main St Unit 4B"])
def test_street_and_apartment_match_a_one_box_street(state_pack, state_street, f1040_first):
    check = _street_check(state_pack, state_street, f1040_first=f1040_first)
    assert check.status == "PASS", check.detail
    assert "street + unit" in check.detail


@pytest.mark.parametrize("state_pack", ONE_BOX_STREET_PACKS)
@pytest.mark.parametrize("state_street, f1040_street, apt", [
    ("100 Main St Apt 4C", "100 Main St", "4B"),     # a different unit
    ("102 Main St Apt 4B", "100 Main St", "4B"),     # a different street
    ("100 Main St Apt 4B", "100 Main St", ""),       # the 1040 leaves the unit off, the state names one
    ("100 Main St", "100 Elm St", "4B"),             # a different street, unit on the 1040 only
])
def test_a_real_street_difference_still_fails(state_pack, state_street, f1040_street, apt):
    check = _street_check(state_pack, state_street, f1040_street, apt)
    assert check.status == "FAIL", check.detail


def test_a_street_without_apartment_on_both_compares_as_before():
    check = _street_check(ONE_BOX_STREET_PACKS[0], "100 Main St", apt="")
    assert check.status == "PASS" and "street + unit" not in check.detail


@pytest.mark.parametrize("rel_pack, unit_values", [
    ("formpacks/states/la/2025/it540/pack.yaml",
     {"mailing_address.unit_type": "APT", "mailing_address.unit_number": "4B"}),
    ("formpacks/states/dc/2025/d40/pack.yaml", {"mailing_address.street2": "Apt 4B"}),
    ("formpacks/states/ca/2025/form540/pack.yaml", {"mailing_address.apt_no": "4B"}),
])
def test_other_separate_unit_keys_compose_against_a_one_box_street(rel_pack, unit_values):
    # A part-year filing: ME 1040ME (one box) beside a state that prints the unit apart.
    me = _shipped_item("f1040me", ONE_BOX_STREET_PACKS[0], {"mailing_address.street": "100 Main St Apt 4B"})
    other = _shipped_item("other", rel_pack, {"mailing_address.street": "100 Main St", **unit_values})
    check = next(c for c in verify_filing([me, other]).identity if c.field == "mailing_address.street")
    assert check.status == "PASS", check.detail


# Verifier round 1: Form 8606 prints "Name. If married, file a separate form for each spouse required to file 2025 Form
# 8606", and Form 5329 "Name of individual subject to additional tax. If married filing jointly, see instructions", so on
# a joint return each carries one spouse's name while the schedules carry "Name(s) shown on Form 1040". Form 8889's
# name stays per filing: it prints "Name(s) shown on Form 1040, 1040-SR, or 1040-NR".
JOINT = "Avery J. & Blake Example"


def _per_form(form: str, year: int = 2025) -> str:
    return f"formpacks/federal/{year}/{form}/pack.yaml"


def _name_check(items: list[FilingItem]):
    return next(check for check in verify_filing(items).identity if check.field == "name")


@pytest.mark.parametrize("year", [2023, 2024, 2025, 2026])
@pytest.mark.parametrize("form", ["f8606", "f5329"])
def test_every_year_declares_the_name_per_person(form, year):
    # TY2026 is planning-only (verify_filing refuses it), so its declaration is checked on the pack.
    assert load_pack(REPO_ROOT / _per_form(form, year)).identity_per_person == ["name", "identifying_number"]


@pytest.mark.parametrize("year", [2023, 2024, 2025])
@pytest.mark.parametrize("form", ["f8606", "f5329"])
def test_a_joint_return_with_each_spouses_form_is_no_name_difference(form, year):
    items = [
        _shipped_item("sched_b", _per_form("sched_b", 2025), {"name": JOINT, "identifying_number": "999881234"}),
        _shipped_item(f"{form}_you", _per_form(form, year), {"name": "Avery J. Example", "identifying_number": "999881234"}),
        _shipped_item(f"{form}_spouse", _per_form(form, year), {"name": "Blake Example", "identifying_number": "999885678"}),
    ]
    check = _name_check(items)
    assert check.status == "SKIPPED", check.detail


def test_a_schedule_name_typo_still_fails_beside_a_form_8606():
    items = [
        _shipped_item("sched_a", _per_form("sched_a"), {"name": "Avery J. Example", "identifying_number": "999881234"}),
        _shipped_item("sched_b", _per_form("sched_b"), {"name": "Avery J. Exmple", "identifying_number": "999881234"}),
        _shipped_item("f8606", _per_form("f8606"), {"name": "Avery J. Example", "identifying_number": "999881234"}),
    ]
    check = _name_check(items)
    assert check.status == "FAIL", check.detail


def test_the_form_8889_name_still_compares_with_the_return():
    items = [
        _shipped_item("sched_b", _per_form("sched_b"), {"name": JOINT, "identifying_number": "999881234"}),
        _shipped_item("f8889", _per_form("f8889"), {"name": "Avery J. Example", "identifying_number": "999881234"}),
    ]
    assert _name_check(items).status == "FAIL"
