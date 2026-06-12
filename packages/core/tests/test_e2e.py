"""End-to-end M1 loop: calc -> fill -> verify -> render (dev plan sections 2, 10).

One synthetic mini form exercises the whole engine: a text field, a 9-cell
comb SSN, a required filing-status checkbox group, three money lines tied by
the relation ``3 == 1 + 2``, and a tax line independently recomputed by the
calc engine. The happy path must come out clean; then each pitfall class is
deliberately triggered and must be caught.

Entirely offline and synthetic: the "blank form" is a reportlab AcroForm
fixture (real IRS PDFs are never vendored, dev plan section 5) and all data
is obviously fake (000-00-0000-style SSNs).

Every import comes from the top-level ``taxfill_core`` package on purpose —
this file doubles as the test of the public M1 API surface.
"""

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

import taxfill_core
from pdf_fixtures import make_acroform_pdf
from taxfill_core import (
    FormPack,
    fill_form,
    load_pack,
    read_pdf_fields,
    render_pdf,
    tax_from_taxable_income,
    verify_form,
)

ROOT = "topmostSubform[0]"

# Logical line -> AcroForm field path (relative to ROOT), mirrored in the
# pack YAML below and in the synthetic blank PDF fixture.
FIELD_PATHS = {
    "name": "Page1[0].f1_4[0]",
    "identifying_number": "Page1[0].f1_7[0]",
    "filing_status.single": "Page1[0].c1_1[0]",
    "filing_status.mfs": "Page1[0].c1_2[0]",
    "1": "Page1[0].f1_28[0]",
    "2": "Page1[0].f1_29[0]",
    "3": "Page1[0].f1_30[0]",
    "16": "Page1[0].f1_31[0]",
}

QUALIFIED = {line: f"{ROOT}.{path}" for line, path in FIELD_PATHS.items()}

PACK_YAML = f"""\
form: MINI-1
jurisdiction: federal
tax_year: 2023
source_url: https://www.irs.gov/pub/irs-pdf/mini1.pdf
pdf_sha256: "..."
acroform_root: {ROOT}
fields:
  - line: name
    field: {FIELD_PATHS["name"]}
    type: text
    maxlen: 30
  - line: identifying_number
    field: {FIELD_PATHS["identifying_number"]}
    type: text
    maxlen: 9
    comb: true
    format: ssn_digits_only
  - line: filing_status.single
    field: {FIELD_PATHS["filing_status.single"]}
    type: checkbox
    on_state: "/1"
    required: true
    group: filing_status
  - line: filing_status.mfs
    field: {FIELD_PATHS["filing_status.mfs"]}
    type: checkbox
    on_state: "/2"
    group: filing_status
  - line: "1"
    field: {FIELD_PATHS["1"]}
    type: money
  - line: "2"
    field: {FIELD_PATHS["2"]}
    type: money
  - line: "3"
    field: {FIELD_PATHS["3"]}
    type: money
  - line: "16"
    field: {FIELD_PATHS["16"]}
    type: money
relations:
  - "3 == 1 + 2"
"""

# Toy synthetic income: wages + interest = taxable income (line 3); the tax
# on line 16 must come from the calc engine, never from mental math.
WAGES = 50_000
INTEREST = 1_200
TAXABLE = WAGES + INTEREST


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> FormPack:
    """The mini pack, loaded through load_pack to exercise the YAML path."""
    path = tmp_path_factory.mktemp("pack") / "pack.yaml"
    path.write_text(PACK_YAML, encoding="utf-8")
    return load_pack(path)


@pytest.fixture(scope="module")
def blank_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Synthetic blank whose AcroForm matches the pack exactly (never mutated)."""
    return make_acroform_pdf(
        tmp_path_factory.mktemp("blank") / "blank.pdf",
        [
            {"name": QUALIFIED["name"], "maxlen": 30},
            {"name": QUALIFIED["identifying_number"], "maxlen": 9, "comb": True},
            {"name": QUALIFIED["filing_status.single"], "kind": "checkbox", "on_value": "/1"},
            {"name": QUALIFIED["filing_status.mfs"], "kind": "checkbox", "on_value": "/2"},
            {"name": QUALIFIED["1"]},
            {"name": QUALIFIED["2"]},
            {"name": QUALIFIED["3"]},
            {"name": QUALIFIED["16"]},
        ],
    )


def happy_values(tax: int) -> dict[str, object]:
    """The fill_form input for the clean return (synthetic identity)."""
    return {
        "name": "Avery Example",
        "identifying_number": "000-00-0000",  # ssn_digits_only strips the dashes
        "filing_status.single": True,
        "1": WAGES,
        "2": INTEREST,
        "3": TAXABLE,
        "16": tax,
    }


def numeric_values(tax: int) -> dict[str, int]:
    """The money lines as numbers, for relation math and the recompute pass."""
    return {"1": WAGES, "2": INTEREST, "3": TAXABLE, "16": tax}


# --- (a) happy path: calc -> fill -> verify -> render -----------------------


def test_happy_path_full_loop(pack: FormPack, blank_pdf: Path, tmp_path: Path):
    # 1. calc: the tax comes from the versioned 2023 tables, with work shown.
    calc_result = tax_from_taxable_income(TAXABLE, "single", year=2023)
    assert calc_result.method == "tax_table"  # below $100,000 the table is mandatory
    assert calc_result.tax > 0
    assert calc_result.citation.url.startswith("https://www.irs.gov")

    # 2. fill: deterministic, field-map-driven.
    out = tmp_path / "drafts" / "mini1.pdf"
    fill = fill_form(pack, happy_values(calc_result.tax), blank_pdf, out)
    assert out.is_file()
    assert fill.written[QUALIFIED["identifying_number"]] == "000000000"
    assert fill.written[QUALIFIED["16"]] == str(calc_result.tax)

    # 3. verify: every section against what is actually on disk.
    report = verify_form(
        pack,
        out,
        expected=happy_values(calc_result.tax),
        values=numeric_values(calc_result.tax),
        independent={"16": calc_result.tax},
    )
    assert report.ok
    assert report.assertions and all(c.status == "PASS" for c in report.assertions)
    assert report.relations and all(c.status == "PASS" for c in report.relations)
    assert report.recompute and all(c.status == "PASS" for c in report.recompute)
    assert report.clipping and all(c.status == "PASS" for c in report.clipping)
    assert report.checkboxes and all(c.status == "PASS" for c in report.checkboxes)
    assert {c.id for c in report.pitfall_checks} == {"P-001", "P-003"}
    assert all(c.status == "PASS" for c in report.pitfall_checks)

    # 4. render: a PNG artifact for the vision-review pass.
    pages = render_pdf(out, tmp_path / "renders")
    assert len(pages) == 1
    png = pages[0]
    assert png.page == 1
    assert png.path.is_file()
    assert png.path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert png.width_px > 0 and png.height_px > 0


# --- (b) pitfall P-001: comb overflow ----------------------------------------


def test_p001_comb_overflow_rejected_at_fill_time(pack: FormPack, blank_pdf: Path, tmp_path: Path):
    # 11 digits even after the dashes are stripped — fill_form must refuse
    # with the dev plan's prescriptive wording (section 11).
    with pytest.raises(ValueError, match=r"exceeds comb MaxLen 9 — resubmit digits only"):
        fill_form(
            pack,
            {"identifying_number": "000-00-0000-99"},
            blank_pdf,
            tmp_path / "never_written.pdf",
        )


def test_p001_bypassed_overflow_caught_by_clipping_scan(pack: FormPack, blank_pdf: Path, tmp_path: Path):
    # Reproduce the original P-001 incident: write the dashed 11-char SSN
    # straight into the 9-cell comb field with raw pypdf, bypassing the
    # filler's guard. pypdf keeps all 11 chars in /V while the appearance
    # clips — invisible in a field dump, so the clipping scan must catch it.
    bad = tmp_path / "bad_ssn.pdf"
    writer = PdfWriter(clone_from=str(blank_pdf))
    writer.update_page_form_field_values(
        None, {QUALIFIED["identifying_number"]: "000-00-0000"}, auto_regenerate=False
    )
    writer.set_need_appearances_writer(True)
    with bad.open("wb") as fh:
        writer.write(fh)
    # Prove the bypass took: the full 11-char value really is in the PDF.
    assert PdfReader(bad).get_fields()[QUALIFIED["identifying_number"]].value == "000-00-0000"

    report = verify_form(pack, bad)
    assert not report.ok
    clip_failures = [c for c in report.clipping if c.status == "FAIL"]
    assert any(QUALIFIED["identifying_number"] in c.name for c in clip_failures)
    p001 = next(c for c in report.pitfall_checks if c.id == "P-001")
    assert p001.status == "FAIL"


# --- (c) pitfall P-003: required checkbox group left /Off --------------------


def test_p003_unanswered_required_checkbox_group_fails(pack: FormPack, blank_pdf: Path, tmp_path: Path):
    calc_result = tax_from_taxable_income(TAXABLE, "single", year=2023)
    values = happy_values(calc_result.tax)
    del values["filing_status.single"]  # the question is silently skipped
    out = tmp_path / "no_status.pdf"
    fill_form(pack, values, blank_pdf, out)

    report = verify_form(pack, out)
    assert not report.ok
    group_checks = [c for c in report.checkboxes if "filing_status" in c.group]
    assert group_checks and group_checks[0].status == "FAIL"
    assert set(group_checks[0].members) == {"filing_status.single", "filing_status.mfs"}
    p003 = next(c for c in report.pitfall_checks if c.id == "P-003")
    assert p003.status == "FAIL"
    # The failure is isolated: clipping (P-001) stays clean on this file.
    p001 = next(c for c in report.pitfall_checks if c.id == "P-001")
    assert p001.status == "PASS"


# --- (d) relation break: 3 == 1 + 2 ------------------------------------------


def test_relation_break_fails_verification(pack: FormPack, blank_pdf: Path, tmp_path: Path):
    calc_result = tax_from_taxable_income(TAXABLE, "single", year=2023)
    values = happy_values(calc_result.tax)
    values["3"] = TAXABLE + 8_800  # a total that is NOT wages + interest
    out = tmp_path / "bad_total.pdf"
    fill_form(pack, values, blank_pdf, out)

    numeric = numeric_values(calc_result.tax)
    numeric["3"] = TAXABLE + 8_800
    report = verify_form(pack, out, values=numeric)
    assert not report.ok
    relation = next(c for c in report.relations if c.relation == "3 == 1 + 2")
    assert relation.status == "FAIL"
    assert relation.lhs == TAXABLE + 8_800
    assert relation.rhs == TAXABLE


# --- (e) independent recompute: filled tax disagrees with calc ---------------


def test_independent_recompute_disagreement_fails(pack: FormPack, blank_pdf: Path, tmp_path: Path):
    calc_result = tax_from_taxable_income(TAXABLE, "single", year=2023)
    wrong_tax = calc_result.tax + 50  # "model mental math" landed on the form
    out = tmp_path / "wrong_tax.pdf"
    fill_form(pack, happy_values(wrong_tax), blank_pdf, out)

    report = verify_form(
        pack,
        out,
        values=numeric_values(wrong_tax),
        independent={"16": calc_result.tax},
    )
    assert not report.ok
    recompute = next(c for c in report.recompute if c.line == "16")
    assert recompute.status == "FAIL"
    assert recompute.filled == wrong_tax
    assert recompute.recomputed == calc_result.tax
    assert "rerun calc" in recompute.detail  # prescriptive: says what to do next
    # Internal consistency still holds — only the recompute pass catches this.
    assert all(c.status == "PASS" for c in report.relations)


# --- (f) regression: refill changing one line --------------------------------


def test_regression_diff_pinpoints_the_changed_line(pack: FormPack, blank_pdf: Path, tmp_path: Path):
    calc_result = tax_from_taxable_income(TAXABLE, "single", year=2023)
    baseline_pdf = tmp_path / "baseline.pdf"
    fill_form(pack, happy_values(calc_result.tax), blank_pdf, baseline_pdf)
    baseline = read_pdf_fields(baseline_pdf)

    refill = happy_values(calc_result.tax)
    refill["2"] = INTEREST + 100  # the one intended change
    refilled_pdf = tmp_path / "refilled.pdf"
    fill_form(pack, refill, blank_pdf, refilled_pdf)

    report = verify_form(pack, refilled_pdf, baseline=baseline)
    assert report.regression is not None
    assert report.regression.added == {}
    assert report.regression.removed == {}
    assert report.regression.changed == {
        QUALIFIED["2"]: (str(INTEREST), str(INTEREST + 100)),
    }


# --- public API surface -------------------------------------------------------


def test_public_api_exports_resolve():
    """Every name in taxfill_core.__all__ must resolve (integrator contract)."""
    missing = [name for name in taxfill_core.__all__ if not hasattr(taxfill_core, name)]
    assert missing == []
    # The M1 entry points named in the dev plan are all reachable top-level.
    for name in (
        "FormPack",
        "load_pack",
        "Profile",
        "tax_from_taxable_income",
        "standard_deduction",
        "se_tax",
        "irs_round",
        "presence_days",
        "classify",
        "substantial_presence_test",
        "fill_form",
        "render_pdf",
        "verify_form",
        "verify_filing",
        "read_pdf_fields",
        "load_knowledge",
    ):
        assert callable(getattr(taxfill_core, name)) or isinstance(getattr(taxfill_core, name), type)
