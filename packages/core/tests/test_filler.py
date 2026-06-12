"""fill_form tests (dev plan sections 3, 10, 11). Synthetic data only.

Every fill is verified by RE-READING the output PDF with pypdf — never by
trusting the FillResult alone. SSNs are obviously fake (000-00-0000 style).
"""

from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from pdf_fixtures import make_acroform_pdf
from taxfill_core.filler import FillResult, fill_form
from taxfill_core.schemas.formpack import FormPack

ROOT = "topmostSubform[0]"


def mini_pack(fields: list[dict]) -> FormPack:
    """A minimal valid pack around the given fields (schema requires the rest)."""
    return FormPack.model_validate(
        {
            "form": "TEST-1",
            "jurisdiction": "federal",
            "tax_year": 2023,
            "source_url": "https://www.irs.gov/pub/irs-pdf/test1.pdf",
            "pdf_sha256": "...",
            "acroform_root": ROOT,
            "fields": fields,
        }
    )


PACK = mini_pack(
    [
        {
            "line": "identifying_number",
            "field": "Page1[0].f1_7[0]",
            "type": "text",
            "maxlen": 9,
            "comb": True,
            "format": "ssn_digits_only",
        },
        {"line": "name", "field": "Page1[0].f1_4[0]", "type": "text", "maxlen": 30},
        {"line": "zip", "field": "Page1[0].f1_9[0]", "type": "text", "maxlen": 5, "comb": True},
        {"line": "filing_status.single", "field": "Page1[0].c1_1[0]", "type": "checkbox", "on_state": "/1"},
        {"line": "filing_status.mfs", "field": "Page1[0].c1_2[0]", "type": "checkbox", "on_state": "/3"},
        {"line": "1a", "field": "Page1[0].f1_28[0]", "type": "money"},
        {"line": "25d", "field": "Page2[0].f2_3[0]", "type": "money"},
    ]
)

LINE_TO_QUALIFIED = {pf.line: f"{ROOT}.{pf.field}" for pf in PACK.fields}


@pytest.fixture
def blank_pdf(tmp_path: Path) -> Path:
    """Synthetic blank PDF whose fields match PACK exactly (two pages)."""
    return make_acroform_pdf(
        tmp_path / "blank.pdf",
        [
            {"name": f"{ROOT}.Page1[0].f1_7[0]", "maxlen": 9, "comb": True},
            {"name": f"{ROOT}.Page1[0].f1_4[0]", "maxlen": 30},
            {"name": f"{ROOT}.Page1[0].f1_9[0]", "maxlen": 5, "comb": True},
            {"name": f"{ROOT}.Page1[0].c1_1[0]", "kind": "checkbox", "on_value": "/1"},
            {"name": f"{ROOT}.Page1[0].c1_2[0]", "kind": "checkbox", "on_value": "/3"},
            {"name": f"{ROOT}.Page1[0].f1_28[0]"},
            {"name": f"{ROOT}.Page2[0].f2_3[0]", "page": 2},
        ],
    )


def find_widget(reader: PdfReader, qualified: str) -> dict:
    """The raw widget annotation for a field (fixture fields are flat: /T == qualified)."""
    for page in reader.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            if annot.get("/T") == qualified:
                return annot
    raise AssertionError(f"widget {qualified!r} not found in PDF")


# --- happy path: every value re-read from disk ------------------------------


def test_fill_text_money_comb_land_on_disk(blank_pdf: Path, tmp_path: Path):
    out = tmp_path / "filled.pdf"
    result = fill_form(
        PACK,
        {
            "identifying_number": "000-00-0000",  # dashes stripped by ssn_digits_only
            "name": "Test Taxpayer",
            "1a": Decimal("12345.49"),
            "25d": 7,
        },
        blank_pdf,
        out,
    )

    assert isinstance(result, FillResult)
    assert out.is_file()

    fields = PdfReader(out).get_fields()
    assert fields[LINE_TO_QUALIFIED["identifying_number"]].value == "000000000"
    assert fields[LINE_TO_QUALIFIED["name"]].value == "Test Taxpayer"
    assert fields[LINE_TO_QUALIFIED["1a"]].value == "12345"  # plain integer: no $, no commas
    assert fields[LINE_TO_QUALIFIED["25d"]].value == "7"  # page-2 field reached

    assert result.written == {
        LINE_TO_QUALIFIED["identifying_number"]: "000000000",
        LINE_TO_QUALIFIED["name"]: "Test Taxpayer",
        LINE_TO_QUALIFIED["1a"]: "12345",
        LINE_TO_QUALIFIED["25d"]: "7",
    }
    # 12345.49 -> 12345 was a real rounding adjustment; 7 was exact.
    assert any("1a" in w and "round" in w.lower() for w in result.warnings)


def test_ssn_digits_only_strips_spaces_too(blank_pdf: Path, tmp_path: Path):
    out = tmp_path / "filled.pdf"
    fill_form(PACK, {"identifying_number": "000 00 0000"}, blank_pdf, out)
    fields = PdfReader(out).get_fields()
    assert fields[LINE_TO_QUALIFIED["identifying_number"]].value == "000000000"


def test_money_rounding_is_irs_whole_dollar(blank_pdf: Path, tmp_path: Path):
    # 50 cents or more rounds up; under 50 cents rounds down (away from zero on ties).
    cases = [
        (Decimal("88.50"), "89"),
        (Decimal("88.49"), "88"),
        (1234.99, "1235"),
        (0, "0"),
        (Decimal("-2.50"), "-3"),
    ]
    for raw, expected in cases:
        out = tmp_path / f"filled_{expected}.pdf"
        result = fill_form(PACK, {"1a": raw}, blank_pdf, out)
        assert PdfReader(out).get_fields()[LINE_TO_QUALIFIED["1a"]].value == expected
        assert result.written[LINE_TO_QUALIFIED["1a"]] == expected


def test_money_negative_fraction_renders_plain_zero(blank_pdf: Path, tmp_path: Path):
    # Regression: Decimal keeps the sign of zero, so -0.4 quantized to whole
    # dollars is Decimal('-0') and rendered '-0' on the form before the fix.
    for raw in (Decimal("-0.4"), -0.49):
        out = tmp_path / "filled_zero.pdf"
        result = fill_form(PACK, {"1a": raw}, blank_pdf, out)
        assert result.written[LINE_TO_QUALIFIED["1a"]] == "0"
        assert PdfReader(out).get_fields()[LINE_TO_QUALIFIED["1a"]].value == "0"
        assert any("round" in w.lower() for w in result.warnings)  # it WAS an adjustment


def test_checkbox_accepts_int_zero_and_one(blank_pdf: Path, tmp_path: Path):
    out = tmp_path / "filled.pdf"
    fill_form(PACK, {"filing_status.single": 1, "filing_status.mfs": 0}, blank_pdf, out)
    reader = PdfReader(out)
    assert find_widget(reader, LINE_TO_QUALIFIED["filing_status.single"])["/AS"] == "/1"
    assert find_widget(reader, LINE_TO_QUALIFIED["filing_status.mfs"])["/AS"] == "/Off"


def test_checkbox_sets_both_v_and_as(blank_pdf: Path, tmp_path: Path):
    out = tmp_path / "filled.pdf"
    result = fill_form(
        PACK,
        {"filing_status.single": True, "filing_status.mfs": "no"},
        blank_pdf,
        out,
    )

    reader = PdfReader(out)
    single = find_widget(reader, LINE_TO_QUALIFIED["filing_status.single"])
    assert single["/V"] == "/1"  # field value
    assert single["/AS"] == "/1"  # widget appearance state — both, per dev plan section 10
    mfs = find_widget(reader, LINE_TO_QUALIFIED["filing_status.mfs"])
    assert mfs["/V"] == "/Off"
    assert mfs["/AS"] == "/Off"

    assert result.written[LINE_TO_QUALIFIED["filing_status.single"]] == "/1"
    assert result.written[LINE_TO_QUALIFIED["filing_status.mfs"]] == "/Off"


def test_checkbox_yes_word_maps_to_custom_on_state(blank_pdf: Path, tmp_path: Path):
    out = tmp_path / "filled.pdf"
    fill_form(PACK, {"filing_status.mfs": "yes"}, blank_pdf, out)
    widget = find_widget(PdfReader(out), LINE_TO_QUALIFIED["filing_status.mfs"])
    assert widget["/V"] == "/3"
    assert widget["/AS"] == "/3"


def test_need_appearances_flag_is_set(blank_pdf: Path, tmp_path: Path):
    out = tmp_path / "filled.pdf"
    fill_form(PACK, {"name": "Test Taxpayer"}, blank_pdf, out)
    acroform = PdfReader(out).trailer["/Root"]["/AcroForm"].get_object()
    assert acroform["/NeedAppearances"].value is True


def test_only_submitted_lines_are_touched(blank_pdf: Path, tmp_path: Path):
    out = tmp_path / "filled.pdf"
    result = fill_form(PACK, {"name": "Test Taxpayer"}, blank_pdf, out)

    assert set(result.written) == {LINE_TO_QUALIFIED["name"]}
    reader = PdfReader(out)
    fields = reader.get_fields()
    assert fields[LINE_TO_QUALIFIED["identifying_number"]].value in (None, "")
    assert fields[LINE_TO_QUALIFIED["1a"]].value in (None, "")
    # untouched checkboxes stay /Off exactly as in the blank
    widget = find_widget(reader, LINE_TO_QUALIFIED["filing_status.single"])
    assert widget["/V"] == "/Off"
    assert widget["/AS"] == "/Off"


# --- prescriptive errors ------------------------------------------------------


def test_unknown_line_lists_valid_line_ids(blank_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError) as exc:
        fill_form(PACK, {"totally_bogus": "x"}, blank_pdf, tmp_path / "out.pdf")
    message = str(exc.value)
    assert "totally_bogus" in message
    assert "valid line ids" in message
    for line in ("identifying_number", "1a", "filing_status.single"):
        assert line in message


def test_comb_overflow_is_the_p001_error(blank_pdf: Path, tmp_path: Path):
    # No format on 'zip', so an over-long value must hit the P-001 style error.
    with pytest.raises(ValueError, match=r"exceeds comb MaxLen 5 — resubmit digits only"):
        fill_form(PACK, {"zip": "123456789"}, blank_pdf, tmp_path / "out.pdf")


def test_dashed_ssn_without_format_would_clip_but_strip_saves_it(blank_pdf: Path, tmp_path: Path):
    # The same dashed value that P-001 clipped passes once ssn_digits_only
    # strips it to 9 digits BEFORE the MaxLen check — that is the format's job.
    out = tmp_path / "out.pdf"
    result = fill_form(PACK, {"identifying_number": "000-00-0000"}, blank_pdf, out)
    assert result.written[LINE_TO_QUALIFIED["identifying_number"]] == "000000000"


def test_text_maxlen_overflow_says_shorten(blank_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"at most 30 — shorten it"):
        fill_form(PACK, {"name": "X" * 31}, blank_pdf, tmp_path / "out.pdf")


def test_comb_rejects_non_digits(blank_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"digits only.*strip dashes, spaces and letters"):
        fill_form(PACK, {"zip": "12a45"}, blank_pdf, tmp_path / "out.pdf")


def test_money_rejects_strings_prescriptively(blank_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"money field.*strip any '\$' or ','"):
        fill_form(PACK, {"1a": "$1,234"}, blank_pdf, tmp_path / "out.pdf")


def test_money_rejects_bool(blank_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"money field.*got bool"):
        fill_form(PACK, {"1a": True}, blank_pdf, tmp_path / "out.pdf")


def test_money_rejects_nan(blank_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"whole-dollar.*finite"):
        fill_form(PACK, {"1a": float("nan")}, blank_pdf, tmp_path / "out.pdf")


def test_text_rejects_non_string_prescriptively(blank_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"text field — pass a string"):
        fill_form(PACK, {"name": 12.5}, blank_pdf, tmp_path / "out.pdf")


def test_checkbox_rejects_ambiguous_word(blank_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"supply yes\|no"):
        fill_form(PACK, {"filing_status.single": "maybe"}, blank_pdf, tmp_path / "out.pdf")


def test_checkbox_rejects_none(blank_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"omit the line"):
        fill_form(PACK, {"filing_status.single": None}, blank_pdf, tmp_path / "out.pdf")


def test_checkbox_rejects_unmappable_objects(blank_pdf: Path, tmp_path: Path):
    # Regression: bool(value) used to silently coerce 2, 2.5, lists, ... to checked.
    for bad in (2, 2.5, ["yes"]):
        with pytest.raises(ValueError, match=r"supply yes\|no"):
            fill_form(PACK, {"filing_status.single": bad}, blank_pdf, tmp_path / "out.pdf")


def test_duplicate_field_target_is_rejected(blank_pdf: Path, tmp_path: Path):
    # Regression: two lines mapping to one field silently lost the first value
    # AND `written` only recorded the survivor, hiding the loss from verify.
    pack = mini_pack(
        [
            {"line": "a", "field": "Page1[0].f1_4[0]", "type": "text"},
            {"line": "b", "field": "Page1[0].f1_4[0]", "type": "text"},
        ]
    )
    with pytest.raises(ValueError) as exc:
        fill_form(pack, {"a": "first", "b": "second"}, blank_pdf, tmp_path / "out.pdf")
    message = str(exc.value)
    assert "'a'" in message and "'b'" in message
    assert f"{ROOT}.Page1[0].f1_4[0]" in message
    assert "submit only one of these lines" in message
    # One of the two alone is fine — the pack ambiguity only bites when both arrive.
    fill_form(pack, {"a": "first"}, blank_pdf, tmp_path / "ok.pdf")


def test_corrupt_blank_pdf_says_refetch(tmp_path: Path):
    # Regression: pypdf's raw PdfStreamError ('Stream has ended unexpectedly')
    # gave the agent no next step.
    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"%PDF-1.7 truncated garbage")
    with pytest.raises(ValueError, match=r"could not be parsed as a PDF.*fetch_blank"):
        fill_form(PACK, {"name": "T"}, bad, tmp_path / "out.pdf")


def test_missing_blank_pdf_says_fetch_first(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match=r"blank PDF not found.*source_url"):
        fill_form(PACK, {"name": "T"}, tmp_path / "nope.pdf", tmp_path / "out.pdf")


def test_field_missing_from_pdf_mentions_root_and_samples(blank_pdf: Path, tmp_path: Path):
    bad_pack = mini_pack(
        [{"line": "ghost", "field": "Page1[0].does_not_exist[0]", "type": "text"}]
    )
    with pytest.raises(ValueError) as exc:
        fill_form(bad_pack, {"ghost": "x"}, blank_pdf, tmp_path / "out.pdf")
    message = str(exc.value)
    assert "does_not_exist" in message
    assert "acroform_root" in message
    assert f"{ROOT}.Page1[0].f1_4[0]" in message  # shows real fields to copy from


def test_wrong_on_state_lists_pdf_states(blank_pdf: Path, tmp_path: Path):
    bad_pack = mini_pack(
        [{"line": "box", "field": "Page1[0].c1_1[0]", "type": "checkbox", "on_state": "/9"}]
    )
    with pytest.raises(ValueError) as exc:
        fill_form(bad_pack, {"box": "yes"}, blank_pdf, tmp_path / "out.pdf")
    message = str(exc.value)
    assert "'/9'" in message
    assert "/1" in message and "/Off" in message  # the states the PDF actually offers
    assert "on_state" in message


def test_unknown_pack_format_is_rejected(blank_pdf: Path, tmp_path: Path):
    odd_pack = mini_pack(
        [{"line": "x", "field": "Page1[0].f1_4[0]", "type": "text", "format": "ein_dashless"}]
    )
    with pytest.raises(ValueError, match=r"unknown format 'ein_dashless'.*supported"):
        fill_form(odd_pack, {"x": "12-3456789"}, blank_pdf, tmp_path / "out.pdf")


# --- true hierarchical AcroForms (the real IRS shape) -------------------------


def hierarchical_blank(tmp_path: Path) -> Path:
    """A blank whose fields are TRUE parent/kid trees, like real IRS forms."""
    return make_acroform_pdf(
        tmp_path / "hier_blank.pdf",
        [
            {
                "name": f"{ROOT}.Page1[0].f1_7[0]",
                "maxlen": 9,
                "comb": True,
                "hierarchical": True,
            },
            {
                "name": f"{ROOT}.Page1[0].c1_1[0]",
                "kind": "checkbox",
                "on_value": "/1",
                "hierarchical": True,
            },
        ],
    )


def find_hierarchical_widget(reader: PdfReader, terminal_part: str) -> dict:
    """The /T-less widget annotation whose parent field carries terminal_part."""
    for page in reader.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget" or annot.get("/T") is not None:
                continue
            parent = annot.get("/Parent")
            if parent is not None and str(parent.get_object().get("/T")) == terminal_part:
                return annot
    raise AssertionError(f"no hierarchical widget under field {terminal_part!r}")


def test_fill_form_hierarchical_checkbox_puts_v_on_field_and_as_on_widget(tmp_path: Path):
    # Regression (coverage gap): every fixture used to be a flat merged
    # field/widget, so the /Parent-walking code written for real IRS
    # hierarchical AcroForms was never exercised. On a true parent-field/
    # kid-widget tree, /V must land on the /T-bearing FIELD dict and /AS on
    # the widget annotation (dev plan section 10).
    blank = hierarchical_blank(tmp_path)
    pack = mini_pack(
        [
            {"line": "box", "field": "Page1[0].c1_1[0]", "type": "checkbox", "on_state": "/1"},
            {
                "line": "ssn",
                "field": "Page1[0].f1_7[0]",
                "type": "text",
                "maxlen": 9,
                "comb": True,
                "format": "ssn_digits_only",
            },
        ]
    )
    out = tmp_path / "hier_filled.pdf"
    result = fill_form(pack, {"box": True, "ssn": "000-00-0000"}, blank, out)
    assert result.written == {
        f"{ROOT}.Page1[0].c1_1[0]": "/1",
        f"{ROOT}.Page1[0].f1_7[0]": "000000000",
    }

    reader = PdfReader(out)
    widget = find_hierarchical_widget(reader, "c1_1[0]")
    assert widget["/AS"] == "/1"  # appearance state on the KID widget
    assert "/V" not in widget  # never on the /T-less widget itself
    field = widget["/Parent"].get_object()
    assert field["/V"] == "/1"  # value on the /T-bearing FIELD dict
    # pypdf re-reads both fields under their fully qualified dotted names.
    fields = reader.get_fields()
    assert fields[f"{ROOT}.Page1[0].c1_1[0]"].value == "/1"
    assert fields[f"{ROOT}.Page1[0].f1_7[0]"].value == "000000000"


def test_fill_form_hierarchical_wrong_on_state_still_lists_pdf_states(tmp_path: Path):
    # The on_state typo guard must also work when /AP lives on the kid widget.
    blank = hierarchical_blank(tmp_path)
    bad_pack = mini_pack(
        [{"line": "box", "field": "Page1[0].c1_1[0]", "type": "checkbox", "on_state": "/9"}]
    )
    with pytest.raises(ValueError, match=r"on_state '/9'.*the PDF offers"):
        fill_form(bad_pack, {"box": "yes"}, blank, tmp_path / "out.pdf")


# --- misc behavior ------------------------------------------------------------


def test_empty_values_writes_untouched_copy(blank_pdf: Path, tmp_path: Path):
    out = tmp_path / "copy.pdf"
    result = fill_form(PACK, {}, blank_pdf, out)
    assert result.written == {} and result.warnings == []
    assert out.is_file()
    assert PdfReader(out).get_fields()[LINE_TO_QUALIFIED["name"]].value in (None, "")


def test_out_path_parent_directories_are_created(blank_pdf: Path, tmp_path: Path):
    out = tmp_path / "drafts" / "2023" / "filled.pdf"
    fill_form(PACK, {"name": "T"}, blank_pdf, out)
    assert out.is_file()
