"""Form pack schema tests (dev plan section 5). Synthetic/spec data only."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.schemas.formpack import FormPack, load_pack

FIXTURE = Path(__file__).parent / "fixtures" / "f1040nr_2022_pack.yaml"


def fixture_dict() -> dict:
    """The section 5 example pack as a mutable dict for invalid-pack tests."""
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def test_dev_plan_example_pack_parses_and_validates():
    pack = load_pack(FIXTURE)

    assert pack.form == "1040-NR"
    assert pack.jurisdiction == "federal"
    assert pack.tax_year == 2022
    assert pack.source_url == "https://www.irs.gov/pub/irs-prior/f1040nr--2022.pdf"
    assert pack.pdf_sha256 == "..."  # authoring placeholder allowed by the schema
    assert pack.acroform_root == "topmostSubform[0]"

    assert len(pack.fields) == 5
    ssn = pack.fields[0]
    assert ssn.line == "identifying_number"
    assert ssn.field == "Page1[0].f1_7[0]"
    assert ssn.type == "text"
    assert ssn.maxlen == 9
    assert ssn.comb is True
    assert ssn.format == "ssn_digits_only"

    checkbox = pack.fields[1]
    assert checkbox.line == "filing_status.single"
    assert checkbox.type == "checkbox"
    assert checkbox.on_state == "/1"

    money = pack.fields[2]
    assert money.line == "1a"
    assert money.type == "money"
    assert money.maxlen is None and money.comb is False

    assert pack.relations == [
        "1z == sum(1a..1h)",
        "11 == 9 - 10",
        "37 == max(0, 24 - 33)",
    ]
    assert pack.cross_form == ["1k == sched_oi.L1e", "8 == sched_1.10"]
    assert pack.identity_fields == ["name", "identifying_number", "mailing_address"]

    assert pack.signature is not None
    assert pack.signature.page == 2
    assert pack.signature.standalone_only is False

    assert pack.mailing is not None
    assert pack.mailing.no_payment == "Department of the Treasury, IRS, Austin, TX 73301-0215"
    assert pack.mailing.with_payment == "IRS, P.O. Box 1303, Charlotte, NC 28201-1303"
    assert pack.mailing.verify_url == "https://www.irs.gov/filing/..."


def test_identity_field_referencing_acroform_name_rejected():
    # identity_fields must be line keys, not AcroForm field names (the LA/OR/WI bug class).
    raw = fixture_dict()
    raw["identity_fields"] = ["Page1[0].f1_7[0]"]  # the field: name of identifying_number
    with pytest.raises(ValidationError, match="identity_fields"):
        FormPack.model_validate(raw)


def test_cross_form_digit_led_dotted_local_ref_rejected():
    # A digit-led dotted local id ('5.b') is misread as form key '5' and silently skipped (KY bug).
    raw = fixture_dict()
    raw["cross_form"] = ["5.b == f1040.11"]
    with pytest.raises(ValidationError, match="cross_form"):
        FormPack.model_validate(raw)


def test_source_url_non_gov_host_rejected():
    # source_url drives the only outbound fetch; it must be an official government host.
    raw = fixture_dict()
    raw["source_url"] = "https://evil.example.com/form.pdf"
    with pytest.raises(ValidationError, match="official US government host"):
        FormPack.model_validate(raw)


def test_source_url_bare_us_rejected_but_state_gov_us_accepted():
    # .us is an open registry: bare evil.us must be rejected; the state-government
    # namespace (*.state.<xx>.us, e.g. Minnesota's DOR) must be accepted.
    raw = fixture_dict()
    raw["source_url"] = "https://evil.us/form.pdf"
    with pytest.raises(ValidationError, match="official US government host"):
        FormPack.model_validate(raw)
    raw["source_url"] = "https://www.revenue.state.mn.us/form.pdf"
    assert FormPack.model_validate(raw).source_url.endswith("state.mn.us/form.pdf")


def test_unknown_field_type_rejected():
    raw = fixture_dict()
    raw["fields"][0]["type"] = "date"  # not one of text|checkbox|money
    with pytest.raises(ValidationError):
        FormPack.model_validate(raw)


@pytest.mark.parametrize("missing_key", ["form", "tax_year", "source_url", "acroform_root", "fields"])
def test_missing_required_top_level_key_rejected(missing_key):
    raw = fixture_dict()
    del raw[missing_key]
    with pytest.raises(ValidationError):
        FormPack.model_validate(raw)


def test_missing_required_field_key_rejected():
    raw = fixture_dict()
    del raw["fields"][0]["field"]
    with pytest.raises(ValidationError):
        FormPack.model_validate(raw)


def test_unknown_top_level_key_rejected():
    raw = fixture_dict()
    raw["efile"] = True  # no e-filing, and no unknown keys either
    with pytest.raises(ValidationError):
        FormPack.model_validate(raw)


def test_checkbox_without_on_state_rejected():
    raw = fixture_dict()
    del raw["fields"][1]["on_state"]
    with pytest.raises(ValidationError, match="on_state"):
        FormPack.model_validate(raw)


def test_on_state_on_text_field_rejected():
    raw = fixture_dict()
    raw["fields"][2]["on_state"] = "/1"
    with pytest.raises(ValidationError, match="checkbox"):
        FormPack.model_validate(raw)


def test_comb_without_maxlen_rejected():
    raw = fixture_dict()
    del raw["fields"][0]["maxlen"]
    with pytest.raises(ValidationError, match="maxlen"):
        FormPack.model_validate(raw)


def test_duplicate_line_rejected():
    raw = fixture_dict()
    raw["fields"].append(dict(raw["fields"][2], field="Page1[0].f1_29[0]"))
    with pytest.raises(ValidationError, match="duplicate line"):
        FormPack.model_validate(raw)


def test_bad_sha256_rejected():
    raw = fixture_dict()
    raw["pdf_sha256"] = "deadbeef"  # not 64 hex chars, not the '...' placeholder
    with pytest.raises(ValidationError, match="SHA-256"):
        FormPack.model_validate(raw)


def test_real_sha256_accepted_and_lowercased():
    raw = fixture_dict()
    raw["pdf_sha256"] = "A" * 64
    pack = FormPack.model_validate(raw)
    assert pack.pdf_sha256 == "a" * 64


def test_bad_jurisdiction_rejected():
    raw = fixture_dict()
    raw["jurisdiction"] = "california"
    with pytest.raises(ValidationError, match="jurisdiction"):
        FormPack.model_validate(raw)


def test_states_jurisdiction_accepted():
    raw = fixture_dict()
    raw["jurisdiction"] = "states/ca"
    assert FormPack.model_validate(raw).jurisdiction == "states/ca"


def test_empty_fields_rejected():
    raw = fixture_dict()
    raw["fields"] = []
    with pytest.raises(ValidationError):
        FormPack.model_validate(raw)


def test_load_pack_rejects_non_mapping(tmp_path):
    bad = tmp_path / "pack.yaml"
    bad.write_text("- this\n- is\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="YAML mapping"):
        load_pack(bad)



def test_jd2_load_pack_serves_independent_copies_and_reloads_an_edited_file(tmp_path):
    src = Path(__file__).resolve().parents[3] / "formpacks" / "federal" / "2025" / "f8889" / "pack.yaml"
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    first, second = load_pack(pack_path), load_pack(pack_path)
    assert first == second and first is not second
    first.fields.clear()                                # a caller mutating its copy ...
    assert load_pack(pack_path).fields                  # ... never reaches the next caller
    edited = src.read_text(encoding="utf-8").replace('tax_year: 2025', 'tax_year: 2024', 1)
    pack_path.write_text(edited, encoding="utf-8")
    assert load_pack(pack_path).tax_year == 2024        # a changed file is parsed again


def test_js1b_mirror_urls_must_be_exact_wayback_snapshots_of_the_source_url():
    data = fixture_dict()
    data["pdf_sha256"] = "a" * 64
    official = data["source_url"]
    data["mirror_urls"] = [f"https://web.archive.org/web/20240101000000id_/{official}"]
    assert FormPack.model_validate(data).mirror_urls == data["mirror_urls"]
    for bad in (f"https://web.archive.org/web/2024id_/{official}",                 # not a 14-digit timestamp
                f"https://web.archive.org/web/20240101000000/{official}",          # the framed page, not id_ bytes
                "https://web.archive.org/web/20240101000000id_/https://www.irs.gov/other.pdf",  # another url
                f"https://mirror.example.com/{official}"):
        with pytest.raises(ValidationError, match="exact Wayback snapshot"):
            FormPack.model_validate({**data, "mirror_urls": [bad]})
    with pytest.raises(ValidationError, match="need a real pdf_sha256"):
        FormPack.model_validate({**data, "pdf_sha256": "..."})


def test_font_size_is_optional_positive_and_text_or_money_only():
    """Phase K JEe2 (2026-10-25): a per-line font_size for a box the blank sizes edge to edge for its glyphs."""
    raw = fixture_dict()
    assert FormPack.model_validate(raw).fields[0].font_size is None  # optional: absent everywhere it is not needed
    raw["fields"][0]["font_size"] = 11.7
    assert FormPack.model_validate(raw).fields[0].font_size == 11.7
    for bad in (0, -1):
        raw["fields"][0]["font_size"] = bad
        with pytest.raises(ValidationError, match="greater than or equal to 6"):
            FormPack.model_validate(raw)
    raw = fixture_dict()
    raw["fields"][1]["font_size"] = 9  # a checkbox
    with pytest.raises(ValidationError, match="'font_size' apply only to text and money fields"):
        FormPack.model_validate(raw)


def test_font_size_is_a_finite_real_number_no_smaller_than_the_overlay_floor():
    """Phase K JEe2 (2026-10-25): a bool, inf, nan or a tiny size never reaches a widget's /DA (fill_form writes it
    with :g, and 1e-05 Tf is no PDF number); 6 pt is the floor overlay.MIN_FONT_SIZE already holds the repo to."""
    raw = fixture_dict()
    for good in (6, 8.5, 12):
        raw["fields"][0]["font_size"] = good
        assert FormPack.model_validate(raw).fields[0].font_size == float(good)
    for bad, why in ((True, "valid number"), (float("inf"), "finite number"), (float("nan"), "finite number"),
                     (1e-9, "greater than or equal to 6"), (5.9, "greater than or equal to 6"), ("9", "valid number")):
        raw["fields"][0]["font_size"] = bad
        with pytest.raises(ValidationError, match=why):
            FormPack.model_validate(raw)
