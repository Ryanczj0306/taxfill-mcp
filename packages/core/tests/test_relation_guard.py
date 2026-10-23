"""The relation guard: '<expr> == <expr> unless <checkbox line>' (Phase K JK28, 2026-10-16).

IA 1040 prints one box above line 5, "Check if using alternate tax (line 5), tax reduction calculation (line 12), or
low-income exemption". The 2025 Iowa Income Tax Reduction Worksheet (41-146) ends "Compare lines 3 and 4. Enter the
smaller number here and on IA 1040, line 12. Check the box on IA 1040, step 5 if the amount on line 3 is used", so the
floored "12 == max(7 - 11, 0)" FAILED that correct return. A relation may now end in " unless <line>": verify reports
it SKIPPED (visible, never failing ok) while that checkbox is checked in the filled PDF, and checks it as usual while
it is not. The pack load validates the clause and refuses it in cross_form rules.

Offline: the grammar, the schema, relations() over a dump, and a fill -> verify round trip on a synthetic AcroForm
(pdf_fixtures) whose box carries IA's recycled export name "/Spouse over 65". Network-marked: the real IA 1040 2025
pack on its cached blank. Demo figures only.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from taxfill_core.schemas.formpack import FormPack, load_pack, split_relation_guard
from taxfill_core.verify import FilingItem, read_pdf_fields, relations, verify_filing, verify_form

REPO = Path(__file__).resolve().parents[3]
IA_PACKS = {year: REPO / "formpacks" / "states" / "ia" / str(year) / "ia1040" / "pack.yaml" for year in (2023, 2024, 2025)}
GUARDED_12 = "12 == max(7 - 11, 0) unless alt_tax_method"
GUARDED_8 = "8 == d unless alt_tax_method"
ON_STATE = "/Spouse over 65"  # the IA box's export name, a DOR artifact copied from the blank's /AP /N


def _fields() -> list[dict]:
    return [
        {"line": "d", "field": "Step 3 d Total", "type": "money"},
        {"line": "5", "field": "5 Iowa tax", "type": "money"},
        {"line": "6", "field": "6 Lump-sum tax", "type": "money"},
        {"line": "7", "field": "7 Total tax", "type": "money"},
        {"line": "8", "field": "8 Exemption credits", "type": "money"},
        {"line": "11", "field": "11 Total credits", "type": "money"},
        {"line": "12", "field": "12 Balance", "type": "money"},
        {"line": "alt_tax_method", "field": "Check if using alternate tax", "type": "checkbox", "on_state": ON_STATE},
        {"line": "filing_status.single", "field": "Filing Status", "type": "checkbox", "on_state": "/Single",
         "group": "filing_status"},
        {"line": "filing_status.mfj", "field": "Filing Status", "type": "checkbox", "on_state": "/Married Joint",
         "group": "filing_status"},
    ]


def _pack(relations_: list[str], cross_form: list[str] | None = None) -> FormPack:
    return FormPack.model_validate({
        "form": "TEST-IA",
        "jurisdiction": "federal",
        "tax_year": 2023,
        "source_url": "https://www.irs.gov/pub/irs-prior/test.pdf",
        "pdf_sha256": "...",
        "acroform_root": "",  # flat, as the IA blank is
        "fields": _fields(),
        "relations": relations_,
        "cross_form": cross_form or [],
    })


# ---------------------------------------------------------------------------
# The clause grammar and the pack schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("relation", "expected"), [
    (GUARDED_12, ("12 == max(7 - 11, 0)", "alt_tax_method")),
    ("12 == max(7 - 11, 0)", ("12 == max(7 - 11, 0)", None)),
    ("  8 == d   unless   alt_tax_method  ", ("8 == d", "alt_tax_method")),
    ("19 == 17 - 18 unless 1_filing_status::single", ("19 == 17 - 18", "1_filing_status::single")),
])
def test_split_relation_guard_accepts(relation, expected):
    assert split_relation_guard(relation) == expected


@pytest.mark.parametrize(("relation", "message"), [
    ("12 == 7 - 11 unless", "exactly ONE line key"),
    ("12 == 7 - 11 unless a b", "exactly ONE line key"),
    ("unless alt_tax_method", "must follow a whole equation"),
    ("12 unless alt_tax_method", "must follow a whole equation"),
    ("12 == 7 unless a unless b", "at most one guard"),
    ("12 == max(7 - 11, 0)unless alt_tax_method", "must stand alone"),
    ("12 == 7 - 11 UNLESS alt_tax_method", "lowercase"),
])
def test_split_relation_guard_rejects_a_malformed_clause_prescriptively(relation, message):
    with pytest.raises(ValueError, match=message) as caught:
        split_relation_guard(relation)
    assert "unless <checkbox line>" in str(caught.value)  # every refusal shows how to write it


def test_pack_accepts_a_guard_naming_a_checkbox_line():
    pack = _pack([GUARDED_12, "12 == 7 unless filing_status.single"])
    assert pack.relations[0] == GUARDED_12


@pytest.mark.parametrize(("relation", "message"), [
    ("12 == max(7 - 11, 0) unless alt_tax_box", "no line key of this pack"),
    ("12 == max(7 - 11, 0) unless 11", "a money line"),
    ("12 == max(7 - 11, 0) unless", "exactly ONE line key"),
    ("12 == max(7 - 11, 0) unless alt_tax_method unless alt_tax_method", "at most one guard"),
])
def test_pack_load_refuses_a_bad_guard(relation, message):
    with pytest.raises(ValidationError, match=message):
        _pack([relation])


def test_pack_load_refuses_a_guard_in_cross_form():
    # _cross_form_check would read 'f1040.15 unless alt_tax_method' as one line key of f1040, find nothing and
    # compare against a silent 0 — so the schema refuses it instead.
    with pytest.raises(ValidationError, match="applies to `relations` only"):
        _pack([], cross_form=["7 == f1040.15 unless alt_tax_method"])


def test_a_handfill_compute_takes_no_guard():
    # A hand-fill line's `compute` is one expression in the same grammar, not a relation: the evaluator refuses a
    # trailing guard there rather than ignoring it.
    from taxfill_core.verify import evaluate_expression

    with pytest.raises(ValueError, match="unexpected trailing token 'unless'"):
        evaluate_expression("max(0, 4 - 5) unless alt_tax_method", {"4": 10, "5": 3})


# ---------------------------------------------------------------------------
# relations() over a field dump
# ---------------------------------------------------------------------------

# A single filer on the Income Tax Reduction Worksheet: 7 - 11 = 416, the worksheet's smaller line 3 = 300.
WORKSHEET = {"7": 456, "11": 40, "12": 300}


def _line12(pack: FormPack, values: dict, fields: dict | None):
    (check,) = [c for c in relations(pack, values, fields=fields) if c.relation == GUARDED_12]
    return check


def test_relations_skip_a_guarded_relation_while_its_box_is_checked():
    pack = _pack([GUARDED_12])
    check = _line12(pack, WORKSHEET, {"Check if using alternate tax": ON_STATE})
    assert check.status == "SKIPPED"
    assert check.lhs is None and check.rhs is None and check.blank_as_zero == []
    assert "box 'alt_tax_method' is checked" in check.detail and "suspends this relation" in check.detail


def test_relations_check_a_guarded_relation_while_its_box_is_unchecked():
    pack = _pack([GUARDED_12])
    for unchecked in ({"Check if using alternate tax": "/Off"}, {"Check if using alternate tax": ""}, {}):
        wrong = _line12(pack, WORKSHEET, unchecked)
        assert wrong.status == "FAIL" and (wrong.lhs, wrong.rhs) == (300, 416)
        assert "only while box 'alt_tax_method' is checked, and it is not checked on this PDF" in wrong.detail
        right = _line12(pack, {**WORKSHEET, "12": 416}, unchecked)
        assert right.status == "PASS"


def test_relations_without_a_dump_check_every_guarded_relation():
    # No dump, no box state: the relation is enforced — a guard only suspends what the PDF shows.
    check = _line12(_pack([GUARDED_12]), WORKSHEET, None)
    assert check.status == "FAIL" and "no field dump was supplied" in check.detail


def test_a_radio_member_guard_reads_only_its_own_option():
    # The two filing-status options share ONE field; the guard on 'single' must not read 'married' as checked.
    pack = _pack(["12 == max(7 - 11, 0) unless filing_status.single"])
    (married,) = relations(pack, WORKSHEET, fields={"Filing Status": "/Married Joint"})
    assert married.status == "FAIL"
    (single,) = relations(pack, WORKSHEET, fields={"Filing Status": "/Single"})
    assert single.status == "SKIPPED"


def test_a_skipped_relation_with_a_malformed_equation_still_raises():
    pack = _pack(["12 == max(7 - 11, 0) + unless alt_tax_method"])
    with pytest.raises(ValueError, match="could not parse relation"):
        relations(pack, WORKSHEET, fields={"Check if using alternate tax": ON_STATE})


# ---------------------------------------------------------------------------
# fill -> verify round trip on a synthetic AcroForm
# ---------------------------------------------------------------------------


@pytest.fixture()
def blank(tmp_path):
    from pdf_fixtures import make_acroform_pdf

    specs = [{"name": f["field"], "kind": "text"} for f in _fields() if f["type"] == "money"]
    specs.append({"name": "Check if using alternate tax", "kind": "checkbox", "on_value": ON_STATE})
    specs += [{"name": "Filing Status", "kind": "radio", "on_value": "/Single"},
              {"name": "Filing Status", "kind": "radio", "on_value": "/Married Joint"}]
    return make_acroform_pdf(tmp_path / "blank.pdf", specs)


def _filled(pack: FormPack, blank: Path, out: Path, values: dict) -> Path:
    from taxfill_core.filler import fill_form

    fill_form(pack, values, blank, out)
    return out


def test_verify_form_skips_line_12_on_a_worksheet_return(blank, tmp_path):
    pack = _pack([GUARDED_12, "7 == 5 + 6"])
    out = _filled(pack, blank, tmp_path / "worksheet.pdf",
                  {"5": 456, "7": 456, "11": 40, "12": 300, "alt_tax_method": True})
    assert read_pdf_fields(out)["Check if using alternate tax"] == ON_STATE  # the export name, spaces and all
    report = verify_form(pack, out)
    status = {c.relation: c.status for c in report.relations}
    assert status == {GUARDED_12: "SKIPPED", "7 == 5 + 6": "PASS"}
    assert report.ok is True


def test_verify_form_fails_line_12_when_the_box_is_unchecked_and_the_floor_is_wrong(blank, tmp_path):
    pack = _pack([GUARDED_12])
    out = _filled(pack, blank, tmp_path / "unchecked_wrong.pdf", {"7": 456, "11": 40, "12": 300})
    report = verify_form(pack, out)
    (check,) = report.relations
    assert check.status == "FAIL" and report.ok is False
    assert "box 'alt_tax_method'" in check.detail


def test_verify_form_passes_line_12_when_the_box_is_unchecked_and_the_floor_is_right(blank, tmp_path):
    pack = _pack([GUARDED_12])
    out = _filled(pack, blank, tmp_path / "unchecked_right.pdf", {"7": 456, "11": 40, "12": 416})
    report = verify_form(pack, out)
    assert [c.status for c in report.relations] == ["PASS"] and report.ok is True
    # The box was written /Off on purpose: an explicit "no" reads the same as a box never touched.
    out_off = _filled(pack, blank, tmp_path / "unchecked_off.pdf",
                      {"7": 456, "11": 40, "12": 416, "alt_tax_method": False})
    assert [c.status for c in verify_form(pack, out_off).relations] == ["PASS"]


def test_verify_filing_reads_each_items_own_box(blank, tmp_path):
    pack = _pack([GUARDED_12])
    checked = _filled(pack, blank, tmp_path / "checked.pdf", {"7": 456, "11": 40, "12": 300, "alt_tax_method": True})
    unchecked = _filled(pack, blank, tmp_path / "unchecked.pdf", {"7": 456, "11": 40, "12": 300})
    report = verify_filing([
        FilingItem(form_key="ia_worksheet", pack=pack, pdf_path=checked),
        FilingItem(form_key="ia_plain", pack=pack, pdf_path=unchecked),
    ])
    status = {c.relation: c.status for c in report.relations}
    assert status == {f"ia_worksheet: {GUARDED_12}": "SKIPPED", f"ia_plain: {GUARDED_12}": "FAIL"}
    assert report.ok is False


# ---------------------------------------------------------------------------
# The real IA 1040 packs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", sorted(IA_PACKS))
def test_every_ia1040_year_guards_lines_8_and_12_with_the_step_5_box(year):
    pack = load_pack(IA_PACKS[year])
    box = {f.line: f for f in pack.fields}["alt_tax_method"]
    assert box.type == "checkbox" and box.on_state == ON_STATE
    assert "tax reduction calculation (line 12)" in box.field  # the face's caption is the widget's name
    assert sorted(r for r in pack.relations if " unless " in r) == sorted([GUARDED_8, GUARDED_12])
    assert "7 == 5 + 6" in pack.relations  # the alternate tax replaces line 5's amount; line 7 still adds 5 and 6


@pytest.mark.network
def test_real_ia1040_2025_blank_skips_fails_and_passes_line_12(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank
    from taxfill_core.filler import fill_form

    pack = load_pack(IA_PACKS[2025])
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    # Demo single filer: Step 3 a/d $40, line 4 $12,000 x 3.8% = $456; 7 - 11 = 416. The worksheet's smaller line 3
    # ($300) goes on line 12 and every later balance line carries it.
    base = {"filing_status.single": True, "a": 40, "d": 40, "2": 12000, "4": 12000, "5": 456, "7": 456, "8": 40,
            "11": 40, "14": 300, "16": 300, "18": 300, "20": 300, "22": 300}

    def verify(name: str, values: dict):
        out = tmp_path / name
        fill_form(pack, values, blank, out)
        report = verify_form(pack, out)
        return report, {c.relation: c for c in report.relations}

    report, by_rel = verify("worksheet.pdf", {**base, "12": 300, "alt_tax_method": True})
    assert not [c.detail for c in report.relations if c.status == "FAIL"]  # before JK28: line 12, 300 vs 416
    assert report.ok is True, [c.detail for s in (report.assertions, report.clipping, report.checkboxes)
                               for c in s if c.status == "FAIL"]
    assert by_rel[GUARDED_12].status == "SKIPPED" and "alt_tax_method" in by_rel[GUARDED_12].detail
    assert by_rel[GUARDED_8].status == "SKIPPED"

    report, by_rel = verify("unchecked_wrong.pdf", {**base, "12": 300})
    assert by_rel[GUARDED_12].status == "FAIL" and report.ok is False
    assert by_rel[GUARDED_8].status == "PASS"

    right = {**base, "12": 416, "14": 416, "16": 416, "18": 416, "20": 416, "22": 416}
    report, by_rel = verify("unchecked_right.pdf", right)
    assert by_rel[GUARDED_12].status == "PASS" and by_rel[GUARDED_8].status == "PASS"
    assert report.ok is True


@pytest.mark.network
def test_real_ia1040_2025_blank_low_income_eitc_return_skips_line_8(tmp_path):
    # Line 25 of the 2025 Expanded Instructions (p.45): "check the box between Steps 4 and 5. Skip lines 5 through 19,
    # enter zero on lines 20 and 22, and enter the amount of your Iowa EITC on lines 25, 30, 31, and 32." Step 3 d
    # stays filled ("enter on Step 3, line d and on line 8"), so 8 == d would fail a correct return without the guard.
    from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank
    from taxfill_core.filler import fill_form

    pack = load_pack(IA_PACKS[2025])
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    eitc = {"filing_status.single": True, "a": 40, "d": 40, "2": 6000, "4": 6000, "20": 0, "22": 0,
            "25": 120, "30": 120, "31a": 120, "32": 120}
    out = tmp_path / "eitc_only.pdf"
    fill_form(pack, {**eitc, "alt_tax_method": True}, blank, out)
    report = verify_form(pack, out)
    assert report.ok is True, [c.detail for c in report.relations if c.status == "FAIL"]  # before JK28: 8 == d
    by_rel = {c.relation: c.status for c in report.relations}
    assert by_rel[GUARDED_8] == "SKIPPED" and by_rel[GUARDED_12] == "SKIPPED"

    unchecked = tmp_path / "eitc_only_unchecked.pdf"
    fill_form(pack, eitc, blank, unchecked)
    by_rel = {c.relation: c.status for c in verify_form(pack, unchecked).relations}
    assert by_rel[GUARDED_8] == "FAIL"  # line 8 blank beside a filled Step 3 d
