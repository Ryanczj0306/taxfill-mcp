"""JW2c (walkthrough finding P1-04): a combined "first name and middle initial" box against separate boxes.

Form 1040 prints "Your first name and middle initial" as one box; Form 540 prints "Your first name" and "Initial".
Both packs key the first-name box ``name.first``, so the identity check compared 'Avery J.' (1040) with 'Avery'
(540) and failed a correct filing. The check now compares the combined box with first name + initial (periods dropped,
spaces collapsed, case-folded) whenever the filing mixes the two shapes. Fictitious names only.
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
    ("Avery J.", "Avery", ""),      # the initial on one form only
    ("Avery", "Avery", "J"),        # the initial on the other form only
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
