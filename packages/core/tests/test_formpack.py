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

    assert len(pack.fields) == 3
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
