"""Verification engine tests (dev plan section 10).

Most tests run on constructed dicts and geometry; the pypdf layer
(:func:`read_pdf_fields`, :func:`read_text_widgets`, ``verify_form(path)``)
is covered by an offline round-trip over a synthetic AcroForm PDF generated
at test time (``pdf_fixtures.make_acroform_pdf`` — no network, nothing
vendored). Synthetic data only — SSN-style values are the obviously-fake
000-00-0000 family.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from taxfill_core.schemas.formpack import FormPack
from taxfill_core.verify import (
    FilingItem,
    TextWidget,
    assertion_diff,
    checkbox_audit,
    clipping_scan,
    digits_only,
    independent_recompute,
    irs_round,
    normalize_text,
    parse_money,
    read_pdf_fields,
    read_text_widgets,
    regression_diff,
    relations,
    render_money,
    verify_filing,
    verify_form,
)

ROOT = "topmostSubform[0]"


# ---------------------------------------------------------------------------
# Synthetic pack builders
# ---------------------------------------------------------------------------


def text_field(line: str, **overrides) -> dict:
    safe = line.replace(".", "_")
    return {"line": line, "field": f"Page1[0].f_{safe}[0]", "type": "text", **overrides}


def money_field(line: str, **overrides) -> dict:
    safe = line.replace(".", "_")
    return {"line": line, "field": f"Page1[0].f_{safe}[0]", "type": "money", **overrides}


def checkbox_field(line: str, **overrides) -> dict:
    safe = line.replace(".", "_")
    return {"line": line, "field": f"Page1[0].c_{safe}[0]", "type": "checkbox", "on_state": "/1", **overrides}


def make_pack(fields: list[dict], **overrides) -> FormPack:
    raw = {
        "form": "TEST-1",
        "jurisdiction": "federal",
        "tax_year": 2023,
        "source_url": "https://www.irs.gov/pub/irs-prior/test.pdf",
        "pdf_sha256": "...",
        "acroform_root": ROOT,
        "fields": fields,
        **overrides,
    }
    return FormPack.model_validate(raw)


def disk_fields(pack: FormPack, raw_by_line: dict[str, str]) -> dict[str, str]:
    """Build a fully-qualified on-disk field dump from line: raw pairs."""
    by_line = {f.line: f for f in pack.fields}
    return {f"{ROOT}.{by_line[line].field}": raw for line, raw in raw_by_line.items()}


# ---------------------------------------------------------------------------
# Normalizers (the documented rendering rules, reimplemented independently)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2.4, 2), (2.5, 3), (-2.5, -3), (0.49, 0), ("1234.50", 1235), (Decimal("99.499"), 99)],
)
def test_irs_round_half_away_from_zero(value, expected):
    assert irs_round(value) == expected


def test_irs_round_rejects_non_numbers_prescriptively():
    with pytest.raises(ValueError, match="pass a finite number"):
        irs_round("not-a-number")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "nan", "Infinity", Decimal("NaN")])
def test_irs_round_rejects_non_finite_with_value_error(value):
    # Regression: NaN/Infinity used to leak a raw decimal.InvalidOperation
    # (not even a ValueError) out of quantize, with no prescriptive message.
    with pytest.raises(ValueError, match="pass a finite number"):
        irs_round(value)


def test_irs_round_handles_amounts_beyond_default_decimal_precision():
    # Regression: quantize raised InvalidOperation above the default
    # 28-digit decimal context; irs_round now widens the context like the
    # filler does.
    big = "1" + "0" * 40
    assert irs_round(big) == int(big)


@pytest.mark.parametrize("raw", ["nan", "NaN", "Infinity", "-inf", float("nan"), float("inf")])
def test_parse_money_non_finite_is_none(raw):
    # NaN/Infinity are not money; Decimal() happily parses them, so
    # parse_money must reject them itself (they would crash render_money).
    assert parse_money(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,234.56", Decimal("1234.56")),
        ("(123)", Decimal("-123")),
        ("-42", Decimal("-42")),
        ("", None),
        ("abc", None),
        (None, None),
    ],
)
def test_parse_money_formats(raw, expected):
    assert parse_money(raw) == expected


def test_render_money_whole_dollars_no_commas():
    assert render_money(1234.5) == "1235"
    assert render_money(-2.5) == "-3"
    assert render_money(0) == "0"


def test_digits_only_and_text_collapse():
    assert digits_only("000-00-0000") == "000000000"
    assert normalize_text("  John   Q\tPublic ") == "John Q Public"


# ---------------------------------------------------------------------------
# Relation math — grammar, sum ranges, blank-as-zero, rounding
# ---------------------------------------------------------------------------


def test_relation_sum_range_with_blank_as_zero_reporting():
    lines = [money_field(f"1{c}") for c in "abcdefgh"] + [money_field("1z")]
    pack = make_pack(lines, relations=["1z == sum(1a..1h)"])
    checks = relations(pack, {"1a": 100, "1b": 50.4, "1z": 150})
    assert len(checks) == 1
    check = checks[0]
    assert check.status == "PASS"  # 100 + 50.4 -> 150 after IRS rounding
    assert check.lhs == 150 and check.rhs == 150
    assert check.blank_as_zero == ["1c", "1d", "1e", "1f", "1g", "1h"]
    assert "blank-as-zero" in check.detail


def test_relation_max_with_literal_zero_disambiguation():
    pack = make_pack(
        [money_field("24"), money_field("33"), money_field("37")],
        relations=["37 == max(0, 24 - 33)"],
    )
    # 24 - 33 is negative, so max picks the literal 0 (no line '0' exists).
    ok = relations(pack, {"24": 1000, "33": 2500, "37": 0})[0]
    assert ok.status == "PASS" and ok.rhs == 0
    bad = relations(pack, {"24": 1000, "33": 2500, "37": 5})[0]
    assert bad.status == "FAIL"
    assert bad.lhs == 5 and bad.rhs == 0
    assert "difference" in bad.detail and "recompute" in bad.detail


def test_relation_min_function():
    pack = make_pack(
        [money_field("5"), money_field("1a"), money_field("1b")],
        relations=["5 == min(1a, 1b)"],
    )
    assert relations(pack, {"5": 10, "1a": 10, "1b": 20})[0].status == "PASS"


def test_relation_precedence_and_parentheses():
    pack = make_pack(
        [money_field("9"), money_field("12")],
        relations=["9 == 1 + 2 * 4", "12 == (1 + 2) * 4"],
    )
    checks = relations(pack, {"9": 9, "12": 12})
    assert [c.status for c in checks] == ["PASS", "PASS"]


def test_relation_division_and_unary_minus():
    pack = make_pack(
        [money_field("2"), money_field("3")],
        relations=["2 == 10 / 5", "3 == -(-3)"],
    )
    checks = relations(pack, {"2": 2, "3": 3})
    assert [c.status for c in checks] == ["PASS", "PASS"]


def test_relation_division_by_zero_fails_prescriptively():
    pack = make_pack(
        [money_field("1"), money_field("1a")],
        relations=["1 == 10 / 1a"],
    )
    check = relations(pack, {"1": 0})[0]  # 1a missing -> 0 -> division by zero
    assert check.status == "FAIL"
    assert "division by zero" in check.detail
    assert "fill the denominator" in check.detail


def test_relation_bare_integer_in_values_is_a_line_reference():
    # '6' is not in the pack's field map but IS in values -> line reference;
    # '1' appears nowhere -> numeric literal.
    pack = make_pack([money_field("7")], relations=["7 == 6 + 1"])
    check = relations(pack, {"7": 11, "6": 10})[0]
    assert check.status == "PASS"
    assert check.blank_as_zero == []


def test_relation_word_line_ids_resolve():
    pack = make_pack([money_field("1k")], relations=["1k == L1e"])
    check = relations(pack, {"1k": 5000, "L1e": 5000})[0]
    assert check.status == "PASS"


@pytest.mark.parametrize(
    ("relation", "match"),
    [
        ("1a == ", "could not parse"),
        ("1a = 1b", "unexpected character"),
        ("1a == sum(1..3)", "sum\\(\\) range"),
        ("1a == sum(1a..2h)", "sum\\(\\) range"),
        ("1a == foo(1)", "unknown function"),
        ("1a == 1b == 1c", "trailing"),
    ],
)
def test_malformed_relations_raise_prescriptive_errors(relation, match):
    pack = make_pack([money_field("1a"), money_field("1b")], relations=[relation])
    with pytest.raises(ValueError, match=match):
        relations(pack, {"1a": 1})


def test_relation_compares_whole_dollars_after_irs_rounding():
    pack = make_pack([money_field("1"), money_field("2")], relations=["1 == 2"])
    assert relations(pack, {"1": 100.4, "2": 100})[0].status == "PASS"
    assert relations(pack, {"1": 100.5, "2": 100})[0].status == "FAIL"


def test_relation_math_is_exact_decimal_at_the_50_cent_boundary():
    # Regression: the evaluator used binary floats — 63135.54 + 86324.49 +
    # 71512.45 + 2107.02 accumulates to 223079.49999999997 in float (rounds
    # to 223079) while the exact sum is 223079.50 (IRS-rounds to 223080).
    # A correctly filled whole-dollar total would spuriously FAIL.
    lines = [money_field(c) for c in ("1a", "1b", "1c", "1d")] + [money_field("5")]
    pack = make_pack(lines, relations=["5 == 1a + 1b + 1c + 1d"])
    cents = {"1a": 63135.54, "1b": 86324.49, "1c": 71512.45, "1d": 2107.02}
    good = relations(pack, {**cents, "5": 223080})[0]
    assert good.status == "PASS"
    assert good.lhs == 223080 and good.rhs == 223080
    # ...and the off-by-a-dollar value must FAIL (it spuriously PASSed in float).
    bad = relations(pack, {**cents, "5": 223079})[0]
    assert bad.status == "FAIL"
    assert bad.rhs == 223080


def test_relation_nan_and_inf_values_fail_instead_of_crashing():
    # Regression: agent-supplied NaN/inf propagated to irs_round and raised
    # ValueError, crashing the whole verify run — data-shaped failures must
    # be FAIL checks, like division by zero already was.
    pack = make_pack([money_field("1"), money_field("2")], relations=["1 == 2"])
    for bad in (float("nan"), float("inf"), float("-inf")):
        check = relations(pack, {"1": bad, "2": 0})[0]
        assert check.status == "FAIL"
        assert "non-numeric or non-finite" in check.detail
        assert "'1'" in check.detail  # names the offending line


def test_relation_huge_literal_fails_instead_of_crashing():
    # Regression: an integer literal big enough to overflow float became inf
    # and crashed irs_round. Decimal parses it; the rounding step reports it.
    pack = make_pack([money_field("1")], relations=[f"1 == {'9' * 400}"])
    check = relations(pack, {"1": 1})[0]
    assert check.status == "FAIL"
    assert "cannot be rounded" in check.detail


def test_relation_deep_nesting_raises_prescriptive_grammar_error():
    # Regression: ~2500 nested parentheses raised a raw RecursionError with
    # no prescriptive message — it must surface as the standard grammar
    # ValueError (a pack-authoring problem, with a fix instruction).
    depth = 5000
    pack = make_pack([money_field("1")], relations=["1 == " + "(" * depth + "1" + ")" * depth])
    with pytest.raises(ValueError, match="nests too deeply"):
        relations(pack, {"1": 1})


# ---------------------------------------------------------------------------
# Assertion diff
# ---------------------------------------------------------------------------


def test_assertion_money_normalizes_both_sides():
    pack = make_pack([money_field("1a")])
    fields = disk_fields(pack, {"1a": "1,235"})
    check = assertion_diff(pack, fields, {"1a": 1234.5})[0]
    assert check.status == "PASS"
    assert check.expected == "1235"

    paren = assertion_diff(pack, disk_fields(pack, {"1a": "(123)"}), {"1a": -123})[0]
    assert paren.status == "PASS"

    bad = assertion_diff(pack, disk_fields(pack, {"1a": "1234"}), {"1a": 1234.5})[0]
    assert bad.status == "FAIL"
    assert "refill" in bad.detail


def test_assertion_comb_ssn_normalizes_to_digits():
    pack = make_pack([text_field("identifying_number", maxlen=9, comb=True, format="ssn_digits_only")])
    fields = disk_fields(pack, {"identifying_number": "000000000"})
    check = assertion_diff(pack, fields, {"identifying_number": "000-00-0000"})[0]
    assert check.status == "PASS"
    assert check.expected == "000000000"  # the documented digits-only rendering


def test_assertion_checkbox_states():
    pack = make_pack([checkbox_field("filing_status.single")])
    on = disk_fields(pack, {"filing_status.single": "/1"})
    off = disk_fields(pack, {"filing_status.single": ""})
    assert assertion_diff(pack, on, {"filing_status.single": True})[0].status == "PASS"
    assert assertion_diff(pack, off, {"filing_status.single": True})[0].status == "FAIL"
    assert assertion_diff(pack, off, {"filing_status.single": False})[0].status == "PASS"


def test_assertion_wrong_slash_export_value_is_not_coerced_to_checked():
    # Regression: any slash-led expected value used to count as 'checked', so
    # asserting '/2' against a field whose on_state is '/1' silently PASSed
    # against an on-disk '/1'. A wrong export value must be reported, not
    # normalized away.
    pack = make_pack([checkbox_field("filing_status.single")])  # on_state '/1'
    on = disk_fields(pack, {"filing_status.single": "/1"})
    check = assertion_diff(pack, on, {"filing_status.single": "/2"})[0]
    assert check.status == "FAIL"
    assert "ambiguous" in check.detail
    assert "'/1'" in check.detail  # the prescriptive message names the real on_state
    # The exact on_state and '/Off' still work as explicit string answers.
    assert assertion_diff(pack, on, {"filing_status.single": "/1"})[0].status == "PASS"
    assert assertion_diff(pack, on, {"filing_status.single": "/Off"})[0].status == "FAIL"


def test_assertion_unknown_line_fails_prescriptively():
    pack = make_pack([money_field("1a")])
    check = assertion_diff(pack, {}, {"nope": 1})[0]
    assert check.status == "FAIL"
    assert "not in the TEST-1 pack's field map" in check.detail
    assert "get_form_map" in check.detail


def test_assertion_field_missing_from_dump_fails_prescriptively():
    pack = make_pack([money_field("1a")])
    check = assertion_diff(pack, {}, {"1a": 100})[0]
    assert check.status == "FAIL"
    assert "missing from the PDF dump" in check.detail


def test_assertion_text_whitespace_collapses():
    pack = make_pack([text_field("name")])
    fields = disk_fields(pack, {"name": "John Q Public"})
    check = assertion_diff(pack, fields, {"name": "  John  Q   Public "})[0]
    assert check.status == "PASS"


def test_assertion_intentional_blank():
    pack = make_pack([money_field("1a")])
    assert assertion_diff(pack, disk_fields(pack, {"1a": ""}), {"1a": ""})[0].status == "PASS"
    assert assertion_diff(pack, disk_fields(pack, {"1a": "5"}), {"1a": ""})[0].status == "FAIL"


@pytest.mark.parametrize("garbage", ["NaN", "Infinity", "n/a"])
def test_assertion_garbage_money_on_disk_fails_instead_of_crashing(garbage):
    # Regression: a money field whose on-disk text was 'NaN' crashed
    # assertion_diff (Decimal('NaN') survived parse_money and blew up in
    # render_money). Garbage on disk must be a FAIL check, never a crash.
    pack = make_pack([money_field("1a")])
    check = assertion_diff(pack, disk_fields(pack, {"1a": garbage}), {"1a": 100})[0]
    assert check.status == "FAIL"
    assert check.actual == garbage
    assert "refill" in check.detail


# ---------------------------------------------------------------------------
# Clipping scan — pitfall P-001
# ---------------------------------------------------------------------------


def test_clipping_p001_dashed_ssn_in_nine_cell_comb():
    # The production incident: 11 characters written into a 9-cell comb field.
    widget = TextWidget(
        name=f"{ROOT}.Page1[0].f1_7[0]",
        value="000-00-0000",
        max_len=9,
        da="/Helv 10 Tf 0 g",
        rect_width=120.0,
    )
    check = clipping_scan([widget])[0]
    assert check.status == "FAIL"
    assert "11 characters" in check.detail
    assert "MaxLen is 9" in check.detail
    assert "P-001" in check.detail
    assert "000-00-0000" not in check.detail  # never echo the (PII-shaped) value


def test_clipping_auto_size_is_safe():
    widget = TextWidget(name="w", value="a very long street address line", da="/Helv 0 Tf 0 g", rect_width=20.0)
    check = clipping_scan([widget])[0]
    assert check.status == "PASS"
    assert "auto-size" in check.detail


def test_clipping_width_heuristic_overflow():
    # 20 chars * 0.5 * 12pt = 120pt > 80pt rect.
    widget = TextWidget(name="w", value="x" * 20, da="/Helv 12 Tf 0 g", rect_width=80.0)
    check = clipping_scan([widget])[0]
    assert check.status == "FAIL"
    assert "120.0pt" in check.detail and "80.0pt" in check.detail


def test_clipping_width_heuristic_fits():
    # 6 chars * 0.5 * 10pt = 30pt <= 100pt rect.
    widget = TextWidget(name="w", value="123456", da="/Helv 10 Tf 0 g", rect_width=100.0)
    assert clipping_scan([widget])[0].status == "PASS"


def test_clipping_missing_da_assumes_10pt():
    # 30 chars * 0.5 * assumed 10pt = 150pt > 100pt rect.
    widget = TextWidget(name="w", value="x" * 30, da=None, rect_width=100.0)
    check = clipping_scan([widget])[0]
    assert check.status == "FAIL"
    assert "assumed 10pt" in check.detail


def test_clipping_skips_empty_values_and_accepts_plain_dicts():
    checks = clipping_scan(
        [
            {"name": "empty", "value": "", "rect_width": 5.0},
            {"name": "filled", "value": "ok", "da": "/Helv 10 Tf 0 g", "rect_width": 50.0},
        ]
    )
    assert [c.name for c in checks] == ["filled"]
    assert checks[0].status == "PASS"


# ---------------------------------------------------------------------------
# Checkbox audit — pitfall P-003
# ---------------------------------------------------------------------------


def yes_no_group_pack() -> FormPack:
    return make_pack(
        [
            checkbox_field("line12.yes", required=True, group="line12"),
            checkbox_field("line12.no", group="line12"),
        ]
    )


def test_required_group_all_off_fails_naming_the_group():
    pack = yes_no_group_pack()
    fields = disk_fields(pack, {"line12.yes": "", "line12.no": "/Off"})
    check = checkbox_audit(pack, fields)[0]
    assert check.status == "FAIL"
    assert check.group == "line12"
    assert check.members == ["line12.yes", "line12.no"]
    assert "'line12'" in check.detail and "P-003" in check.detail
    assert "line12.yes, line12.no" in check.detail  # tells the agent what to set


def test_required_group_with_one_member_on_passes():
    pack = yes_no_group_pack()
    fields = disk_fields(pack, {"line12.yes": "", "line12.no": "/1"})
    check = checkbox_audit(pack, fields)[0]
    assert check.status == "PASS"


def test_required_single_checkbox_both_ways():
    pack = make_pack([checkbox_field("item_i", required=True)])
    off = checkbox_audit(pack, disk_fields(pack, {"item_i": ""}))[0]
    assert off.status == "FAIL" and "unanswered" in off.detail
    on = checkbox_audit(pack, disk_fields(pack, {"item_i": "/1"}))[0]
    assert on.status == "PASS"


def test_non_required_checkboxes_are_not_audited():
    pack = make_pack(
        [
            checkbox_field("optional.yes", group="optional"),
            checkbox_field("optional.no", group="optional"),
            checkbox_field("lone_optional"),
        ]
    )
    assert checkbox_audit(pack, {}) == []


def filing_status_group_pack() -> FormPack:
    # Five separate single-widget /Btn fields that share only a `group` id —
    # the real 1040 filing-status shape (c1_3[0]..c1_3[4]).
    return make_pack(
        [
            checkbox_field("filing_status.single", required=True, group="filing_status"),
            checkbox_field("filing_status.mfj", group="filing_status"),
            checkbox_field("filing_status.hoh", group="filing_status"),
        ]
    )


def test_group_with_two_members_on_fails_at_most_one():
    pack = filing_status_group_pack()
    fields = disk_fields(pack, {"filing_status.single": "/1", "filing_status.hoh": "/1"})
    check = checkbox_audit(pack, fields)[0]
    assert check.status == "FAIL"
    assert check.group == "filing_status"
    assert "2 boxes checked" in check.detail
    assert "exactly one is allowed" in check.detail
    assert "filing_status.single" in check.detail and "filing_status.hoh" in check.detail


def test_non_required_group_with_two_members_on_also_fails():
    # At-most-one holds for EVERY group, required or not.
    pack = make_pack(
        [
            checkbox_field("optional.yes", group="optional"),
            checkbox_field("optional.no", group="optional"),
        ]
    )
    fields = disk_fields(pack, {"optional.yes": "/1", "optional.no": "/1"})
    check = checkbox_audit(pack, fields)[0]
    assert check.status == "FAIL" and check.group == "optional"
    assert "exactly one is allowed" in check.detail


def test_group_with_exactly_one_member_on_passes():
    pack = filing_status_group_pack()
    fields = disk_fields(pack, {"filing_status.single": "/1", "filing_status.hoh": "/Off"})
    checks = checkbox_audit(pack, fields)
    assert len(checks) == 1 and checks[0].status == "PASS"


# ---------------------------------------------------------------------------
# Schema additions (required / group on PackField)
# ---------------------------------------------------------------------------


def test_packfield_required_and_group_defaults():
    pack = make_pack([text_field("name"), checkbox_field("box", required=True, group="g1")])
    assert pack.fields[0].required is False and pack.fields[0].group is None
    assert pack.fields[1].required is True and pack.fields[1].group == "g1"


def test_packfield_group_on_text_field_rejected():
    with pytest.raises(ValidationError, match="'group' applies only to checkbox fields"):
        make_pack([text_field("name", group="g1")])


def test_packfield_required_allowed_on_text_field():
    pack = make_pack([text_field("name", required=True)])
    assert pack.fields[0].required is True


# ---------------------------------------------------------------------------
# Regression diff
# ---------------------------------------------------------------------------


def test_regression_diff_added_removed_changed():
    baseline = {"a": "1", "b": "2", "c": "3"}
    fields = {"a": "1", "b": "9", "d": "4"}
    diff = regression_diff(fields, baseline)
    assert diff.added == {"d": "4"}
    assert diff.removed == {"c": "3"}
    assert diff.changed == {"b": ("2", "9")}
    assert not diff.is_empty()


def test_regression_diff_identical_is_empty():
    fields = {"a": "1"}
    assert regression_diff(fields, dict(fields)).is_empty()


# ---------------------------------------------------------------------------
# Independent recompute
# ---------------------------------------------------------------------------


def test_independent_recompute_match_mismatch_and_missing():
    checks = independent_recompute(
        {"16": 4500.4, "24": 4700},
        {"16": 4500, "24": 4658, "37": 100},
    )
    by_line = {check.line: check for check in checks}
    assert by_line["16"].status == "PASS"  # 4500.4 rounds to 4500
    assert by_line["24"].status == "FAIL"
    assert by_line["24"].filled == 4700 and by_line["24"].recomputed == 4658
    assert "no-LLM-arithmetic" in by_line["24"].detail
    assert by_line["37"].status == "FAIL"
    assert "no filled value was supplied" in by_line["37"].detail


# ---------------------------------------------------------------------------
# verify_filing — identity + cross-form
# ---------------------------------------------------------------------------


def identity_pack(form: str, *, cross_form: list[str] | None = None) -> FormPack:
    return make_pack(
        [
            text_field("name"),
            text_field("identifying_number", maxlen=9, comb=True, format="ssn_digits_only"),
            text_field("mailing_address"),
            money_field("1k"),
        ],
        form=form,
        identity_fields=["name", "identifying_number", "mailing_address"],
        cross_form=cross_form or [],
    )


def filing_item(form_key: str, pack: FormPack, raw_by_line: dict[str, str], values=None) -> FilingItem:
    return FilingItem(form_key=form_key, pack=pack, fields=disk_fields(pack, raw_by_line), values=values or {})


def test_identity_mismatch_across_two_forms_fails_with_both_addresses():
    pack_a = identity_pack("F-MAIN")
    pack_b = identity_pack("F-ATTACH")
    item_a = filing_item(
        "main", pack_a, {"name": "Pat Q Sample", "identifying_number": "000000000", "mailing_address": "100 Current St, Testville, CA 00000"}
    )
    item_b = filing_item(
        "attach", pack_b, {"name": "Pat Q Sample", "identifying_number": "000000000", "mailing_address": "9 Old Apartment Rd, Pastburg, NY 00000"}
    )
    report = verify_filing([item_a, item_b])
    assert report.ok is False
    address = next(check for check in report.identity if check.field == "mailing_address")
    assert address.status == "FAIL"
    assert "100 Current St" in address.detail and "9 Old Apartment Rd" in address.detail
    assert "P-002" in address.detail
    name = next(check for check in report.identity if check.field == "name")
    assert name.status == "PASS"
    p002 = next(check for check in report.pitfall_checks if check.id == "P-002")
    assert p002.status == "FAIL"


def test_identity_match_reports_the_address_used():
    address = "100 Current St, Testville, CA 00000"
    pack_a, pack_b = identity_pack("F-MAIN"), identity_pack("F-ATTACH")
    common = {"name": "Pat Q Sample", "identifying_number": "000000000", "mailing_address": address}
    report = verify_filing([filing_item("main", pack_a, common), filing_item("attach", pack_b, dict(common))])
    assert report.ok is True
    p002 = next(check for check in report.pitfall_checks if check.id == "P-002")
    assert p002.status == "PASS"
    assert address in p002.detail  # the report shows the address actually used
    assert "TODAY" in p002.detail


def test_consistent_but_wrong_address_fails_against_confirmed_current_address():
    # Regression (the ORIGINAL P-002 incident shape): one wrong historical
    # address landing consistently on every form passed with only a
    # "confirm this" note. With the user-confirmed current address supplied,
    # the verifier must FAIL P-002 outright.
    old_address = "9 Old Apartment Rd, Pastburg, NY 00000"
    pack_a, pack_b = identity_pack("F-MAIN"), identity_pack("F-ATTACH")
    common = {"name": "Pat Q Sample", "identifying_number": "000000000", "mailing_address": old_address}
    report = verify_filing(
        [filing_item("main", pack_a, common), filing_item("attach", pack_b, dict(common))],
        confirmed_current_address="100 Current St, Testville, CA 00000",
    )
    assert report.ok is False
    confirmed = next(check for check in report.identity if "user-confirmed" in check.field)
    assert confirmed.status == "FAIL"
    assert "9 Old Apartment Rd" in confirmed.detail and "100 Current St" in confirmed.detail
    assert "P-002" in confirmed.detail
    p002 = next(check for check in report.pitfall_checks if check.id == "P-002")
    assert p002.status == "FAIL"


def test_matching_confirmed_current_address_passes_exactly():
    address = "100 Current St, Testville, CA 00000"
    pack_a, pack_b = identity_pack("F-MAIN"), identity_pack("F-ATTACH")
    common = {"name": "Pat Q Sample", "identifying_number": "000000000", "mailing_address": address}
    report = verify_filing(
        [filing_item("main", pack_a, common), filing_item("attach", pack_b, dict(common))],
        confirmed_current_address="  100 Current  St, Testville, CA 00000 ",  # whitespace-normalized
    )
    assert report.ok is True
    p002 = next(check for check in report.pitfall_checks if check.id == "P-002")
    assert p002.status == "PASS"
    assert "user-confirmed" in p002.detail


def test_verify_form_supports_confirmed_current_address():
    pack = identity_pack("F-MAIN")
    fields = disk_fields(
        pack,
        {"name": "Pat", "identifying_number": "000000000", "mailing_address": "9 Old Apartment Rd"},
    )
    report = verify_form(pack, fields, confirmed_current_address="100 Current St")
    assert report.ok is False
    assert any(check.id == "P-002" and check.status == "FAIL" for check in report.pitfall_checks)
    ok = verify_form(pack, fields, confirmed_current_address="9 Old Apartment Rd")
    assert any(check.id == "P-002" and check.status == "PASS" for check in ok.pitfall_checks)


def test_confirmed_address_with_no_address_line_fails_prescriptively():
    pack = make_pack([money_field("1a")])
    report = verify_form(pack, {}, confirmed_current_address="100 Current St")
    assert report.ok is False
    confirmed = next(check for check in report.identity if "user-confirmed" in check.field)
    assert "no pack in this filing maps an address line" in confirmed.detail


def test_identity_ssn_comb_normalization_matches_dashed_vs_digits():
    # One form carries digits, the other dashes — same identity after the
    # documented digits-only normalization for ssn comb fields.
    pack_a, pack_b = identity_pack("F-MAIN"), identity_pack("F-ATTACH")
    item_a = filing_item("main", pack_a, {"name": "Pat", "identifying_number": "000000000", "mailing_address": "X"})
    item_b = filing_item("attach", pack_b, {"name": "Pat", "identifying_number": "000-00-0000", "mailing_address": "X"})
    report = verify_filing([item_a, item_b])
    ssn = next(check for check in report.identity if check.field == "identifying_number")
    assert ssn.status == "PASS"
    # ... but the dashed value still trips the P-001 clipping check (maxlen 9).
    p001 = next(check for check in report.pitfall_checks if check.id == "P-001")
    assert p001.status == "FAIL"


def test_cross_form_relation_pass_fail_and_missing_form():
    pack_main = identity_pack("F-MAIN", cross_form=["1k == sched_oi.L1e"])
    pack_oi = make_pack([money_field("L1e")], form="SCHED-OI")
    main_ok = filing_item("main", pack_main, {"name": "Pat", "identifying_number": "000000000", "mailing_address": "X"}, {"1k": 5000})
    oi = FilingItem(form_key="sched_oi", pack=pack_oi, fields={}, values={"L1e": 5000})
    report = verify_filing([main_ok, oi])
    cross = report.cross_form[0]
    assert cross.status == "PASS" and cross.lhs == 5000 and cross.rhs == 5000

    oi_bad = FilingItem(form_key="sched_oi", pack=pack_oi, fields={}, values={"L1e": 4000})
    bad = verify_filing([main_ok, oi_bad]).cross_form[0]
    assert bad.status == "FAIL" and "disagree" in bad.detail

    missing = verify_filing([main_ok]).cross_form[0]
    assert missing.status == "SKIPPED"
    assert "not part of this filing" in missing.detail


def test_cross_form_skip_when_target_form_absent_is_nonfatal():
    # A filing that legitimately omits a schedule (no Schedule 2 when there are
    # no additional taxes) must not FAIL the parent's cross_form rules: the
    # rule is SKIPPED — visible in the report, never flipping ok — and a
    # nonzero present-side amount earns an explicit attach-and-reverify caution.
    pack_main = identity_pack("F-MAIN", cross_form=["1k == sched_oi.L1e"])
    ident = {"name": "Pat", "identifying_number": "000000000", "mailing_address": "X"}

    blank = filing_item("main", pack_main, dict(ident))
    report = verify_filing([blank])
    check = report.cross_form[0]
    assert check.status == "SKIPPED"
    assert "not part of this filing" in check.detail
    assert "caution" not in check.detail  # 1k blank: nothing flows through sched_oi
    assert report.ok is True

    nonzero = filing_item("main", pack_main, dict(ident), {"1k": 5000})
    report = verify_filing([nonzero])
    check = report.cross_form[0]
    assert check.status == "SKIPPED"
    assert "caution" in check.detail and "5000" in check.detail and "sched_oi" in check.detail
    assert report.ok is True  # SKIPPED is non-fatal by design


def test_cross_form_blank_lines_count_as_zero_and_are_reported():
    pack_main = identity_pack("F-MAIN", cross_form=["1k == sched_oi.L1e"])
    pack_oi = make_pack([money_field("L1e")], form="SCHED-OI")
    main = filing_item("main", pack_main, {"name": "Pat", "identifying_number": "000000000", "mailing_address": "X"})
    oi = FilingItem(form_key="sched_oi", pack=pack_oi, fields={}, values={})
    report = verify_filing([main, oi])
    cross = report.cross_form[0]
    assert cross.status == "PASS"  # 0 == 0, blank-means-zero
    assert cross.blank_as_zero == ["main.1k", "sched_oi.L1e"]
    assert set(cross.blank_as_zero) <= set(report.blank_as_zero)


def test_filing_item_requires_fields_or_pdf_path():
    pack = make_pack([money_field("1a")])
    with pytest.raises(ValidationError, match="supply 'fields'"):
        FilingItem(form_key="main", pack=pack)


def test_verify_filing_rejects_duplicate_form_keys():
    pack = make_pack([money_field("1a")])
    item = FilingItem(form_key="main", pack=pack, fields={})
    with pytest.raises(ValueError, match="duplicate form_key"):
        verify_filing([item, item])


def test_verify_filing_rejects_empty_filing_prescriptively():
    with pytest.raises(ValueError, match="at least one filing item"):
        verify_filing([])


@pytest.mark.parametrize("rule", ["1k = sched_oi.L1e", "1k == a == b", "=="])
def test_malformed_cross_form_rule_raises_prescriptively(rule):
    pack = make_pack([money_field("1k")], cross_form=[rule])
    item = FilingItem(form_key="main", pack=pack, fields={}, values={"1k": 1})
    with pytest.raises(ValueError, match="'<ref> == <ref>'"):
        verify_filing([item])


# ---------------------------------------------------------------------------
# Report aggregation + pitfall_checks
# ---------------------------------------------------------------------------


def aggregation_pack() -> FormPack:
    return make_pack(
        [
            text_field("identifying_number", maxlen=9, comb=True, format="ssn_digits_only"),
            money_field("1a"),
            money_field("1b"),
            money_field("1z"),
            checkbox_field("line12.yes", required=True, group="line12"),
            checkbox_field("line12.no", group="line12"),
        ],
        relations=["1z == sum(1a..1b)"],
    )


def test_verify_form_report_failing_then_fixed():
    pack = aggregation_pack()
    values = {"1a": 100, "1b": 50, "1z": 150}
    expected = {"1z": 150}

    bad_fields = disk_fields(
        pack,
        {"identifying_number": "000-00-0000", "1z": "150", "line12.yes": "", "line12.no": ""},
    )
    bad = verify_form(pack, bad_fields, expected=expected, values=values, independent={"1z": 150})
    assert bad.ok is False
    pitfalls = {check.id: check.status for check in bad.pitfall_checks}
    assert pitfalls == {"P-001": "FAIL", "P-003": "FAIL"}  # both shown, both failing
    assert any(check.status == "FAIL" for check in bad.clipping)  # 11 chars in 9-cell comb
    assert any(check.status == "FAIL" for check in bad.checkboxes)
    assert all(check.status == "PASS" for check in bad.assertions)
    assert all(check.status == "PASS" for check in bad.relations)
    assert all(check.status == "PASS" for check in bad.recompute)

    good_fields = disk_fields(
        pack,
        {"identifying_number": "000000000", "1z": "150", "line12.yes": "/1", "line12.no": ""},
    )
    good = verify_form(pack, good_fields, expected=expected, values=values, independent={"1z": 150})
    assert good.ok is True
    assert {check.id: check.status for check in good.pitfall_checks} == {"P-001": "PASS", "P-003": "PASS"}
    assert good.form_keys == ["TEST-1"]


def test_verify_form_pitfalls_present_even_with_nothing_to_check():
    pack = make_pack([money_field("1a")])
    report = verify_form(pack, {})
    assert [check.id for check in report.pitfall_checks] == ["P-001", "P-003"]
    assert all(check.status == "PASS" for check in report.pitfall_checks)
    assert "no filled text fields" in report.pitfall_checks[0].detail
    assert "no required checkboxes" in report.pitfall_checks[1].detail
    assert report.ok is True


def test_verify_form_catches_maxlen_overflow_from_dump_alone():
    # No widget geometry supplied: the pack's maxlen still catches P-001.
    pack = make_pack([text_field("identifying_number", maxlen=9, comb=True, format="ssn_digits_only")])
    fields = disk_fields(pack, {"identifying_number": "000-00-0000"})
    report = verify_form(pack, fields)
    assert report.ok is False
    p001 = next(check for check in report.pitfall_checks if check.id == "P-001")
    assert p001.status == "FAIL"
    assert report.clipping[0].status == "FAIL"
    assert "line identifying_number" in report.clipping[0].name


def test_verify_form_widgets_take_precedence_over_pack_maxlen():
    pack = make_pack([text_field("identifying_number", maxlen=9, comb=True)])
    fields = disk_fields(pack, {"identifying_number": "000000000"})
    widgets = [
        TextWidget(
            name=f"{ROOT}.Page1[0].f_identifying_number[0]",
            value="000000000",
            max_len=9,
            da="/Helv 0 Tf 0 g",
            rect_width=90.0,
        )
    ]
    report = verify_form(pack, fields, widgets=widgets)
    # One clipping entry only: the widget covers the field, no duplicate pack check.
    assert len(report.clipping) == 1
    assert report.clipping[0].status == "PASS"


def test_pack_maxlen_skip_requires_a_name_component_boundary():
    # Regression: a widget for a DIFFERENT field whose name merely
    # suffix-overlapped the pack field ('...OtherPage1[0].f1_7[0]' vs
    # 'Page1[0].f1_7[0]') suppressed the pack MaxLen check, letting an
    # 11-char value in a 9-cell comb field verify clean (a P-001 escape).
    pack = make_pack([{"line": "ssn", "field": "Page1[0].f1_7[0]", "type": "text", "maxlen": 9, "comb": True}])
    fields = {f"{ROOT}.Page1[0].f1_7[0]": "000-00-0000"}
    overlapping = TextWidget(
        name=f"{ROOT}.OtherPage1[0].f1_7[0]", value="ok", da="/Helv 0 Tf 0 g", rect_width=50.0
    )
    report = verify_form(pack, fields, widgets=[overlapping])
    assert report.ok is False
    pack_check = next(check for check in report.clipping if "line ssn" in check.name)
    assert pack_check.status == "FAIL"
    # A genuinely deeper-rooted widget for the SAME field still covers it.
    same_field = TextWidget(
        name=f"deeperRoot[0].{ROOT}.Page1[0].f1_7[0]",
        value="000-00-0000",
        max_len=9,
        da="/Helv 0 Tf 0 g",
        rect_width=50.0,
    )
    covered = verify_form(pack, fields, widgets=[same_field])
    assert all("line ssn" not in check.name for check in covered.clipping)
    assert covered.ok is False  # the widget's own MaxLen check still fails


def test_verify_form_relations_blanks_aggregate_into_report():
    pack = make_pack(
        [money_field(f"1{c}") for c in "ab"] + [money_field("1z")],
        relations=["1z == sum(1a..1b)"],
    )
    report = verify_form(pack, {}, values={"1z": 0})
    assert report.blank_as_zero == ["1a", "1b"]
    assert report.relations[0].status == "PASS"  # 0 == 0, blank-means-zero


def test_verify_form_regression_is_informational():
    pack = make_pack([money_field("1a")])
    fields = disk_fields(pack, {"1a": "100"})
    baseline = disk_fields(pack, {"1a": "90"})
    report = verify_form(pack, fields, baseline=baseline)
    assert report.regression is not None
    assert report.regression.changed  # the change is visible...
    assert report.ok is True  # ...but the caller judges intent; ok unaffected


# ---------------------------------------------------------------------------
# Disk is the source of truth — relation math / recompute tied to the dump
# ---------------------------------------------------------------------------


def disk_truth_pack() -> FormPack:
    return make_pack(
        [money_field("1"), money_field("2"), money_field("3")],
        relations=["3 == 1 + 2"],
    )


def test_self_consistent_caller_values_cannot_greenlight_a_wrong_disk():
    # Regression (blocker): verify_form ran relation math purely on the
    # caller-supplied values, so a PDF whose total on disk is 9999 returned
    # ok=True for values={'1':50000,'2':1200,'3':51200}. The disk value must
    # drive the math, and the divergence must be its own FAIL.
    pack = disk_truth_pack()
    fields = disk_fields(pack, {"1": "50000", "2": "1200", "3": "9999"})
    report = verify_form(pack, fields, values={"1": 50000, "2": 1200, "3": 51200})
    assert report.ok is False
    relation = report.relations[0]
    assert relation.status == "FAIL"
    assert relation.lhs == 9999  # the ON-DISK number, not the caller's claim
    assert relation.rhs == 51200
    divergence = next(check for check in report.assertions if check.line == "3")
    assert divergence.status == "FAIL"
    assert "on disk" in divergence.detail.lower() and "9999" in divergence.detail


def test_relations_run_from_disk_even_without_caller_values():
    # The mechanical section-11 flow (no values at all) still relation-checks
    # what is actually on disk.
    pack = disk_truth_pack()
    fields = disk_fields(pack, {"1": "50000", "2": "1200", "3": "9999"})
    report = verify_form(pack, fields)
    assert report.ok is False
    assert report.relations[0].status == "FAIL"
    assert report.relations[0].lhs == 9999

    good = verify_form(pack, disk_fields(pack, {"1": "50000", "2": "1200", "3": "51200"}))
    assert good.ok is True
    assert good.relations[0].status == "PASS"


def test_recompute_runs_against_the_disk_value_not_the_caller_claim():
    pack = disk_truth_pack()
    fields = disk_fields(pack, {"3": "9999"})
    report = verify_form(pack, fields, values={"3": 51200}, independent={"3": 51200})
    assert report.ok is False
    recompute = next(check for check in report.recompute if check.line == "3")
    assert recompute.status == "FAIL"
    assert recompute.filled == 9999  # disk, not the self-reported 51200


def test_caller_value_for_a_blank_disk_line_fails():
    # Blank means 0 on IRS forms: claiming a nonzero value for a line that
    # was never filled must fail, not silently pass the relation on claims.
    pack = disk_truth_pack()
    fields = disk_fields(pack, {"1": "50000", "2": "1200", "3": ""})
    report = verify_form(pack, fields, values={"3": 51200})
    assert report.ok is False
    blank_check = next(check for check in report.assertions if check.line == "3")
    assert "BLANK on disk" in blank_check.detail
    # A claimed 0 for a blank line is consistent (blank-means-zero).
    zero_ok = verify_form(
        pack, disk_fields(pack, {"1": "0", "2": "0", "3": ""}), values={"3": 0}
    )
    assert all(check.status == "PASS" for check in zero_ok.relations)
    assert zero_ok.ok is True


def test_garbage_money_on_disk_fails_the_math_sections():
    pack = disk_truth_pack()
    fields = disk_fields(pack, {"1": "50000", "2": "1200", "3": "n/a"})
    report = verify_form(pack, fields)
    assert report.ok is False
    garbage = next(check for check in report.assertions if check.line == "3")
    assert garbage.status == "FAIL"
    assert "non-numeric" in garbage.detail and "refill" in garbage.detail


def test_verify_filing_cross_form_uses_disk_values():
    # Same blocker shape across forms: FilingItem.values were free-floating.
    pack_main = identity_pack("F-MAIN", cross_form=["1k == sched_oi.L1e"])
    pack_oi = make_pack([money_field("L1e")], form="SCHED-OI")
    main = filing_item(
        "main",
        pack_main,
        {"name": "Pat", "identifying_number": "000000000", "mailing_address": "X", "1k": "5000"},
        {"1k": 5000},
    )
    # On disk the schedule says 4000; the agent claims 5000 on both sides.
    oi = FilingItem(
        form_key="sched_oi",
        pack=pack_oi,
        fields=disk_fields(pack_oi, {"L1e": "4000"}),
        values={"L1e": 5000},
    )
    report = verify_filing([main, oi])
    assert report.ok is False
    cross = report.cross_form[0]
    assert cross.status == "FAIL"
    assert cross.lhs == 5000 and cross.rhs == 4000  # disk numbers
    divergence = next(check for check in report.assertions if "L1e" in check.line)
    assert divergence.status == "FAIL"
    assert divergence.line.startswith("sched_oi:")


def test_verify_filing_independent_unknown_form_key_raises_naming_valid_keys():
    # The unknown-form-key guard: an `independent` set keyed by a form_key
    # that is not among the filing items must raise, naming the valid keys.
    pack_main = identity_pack("F-MAIN")
    pack_oi = make_pack([money_field("L1e")], form="SCHED-OI")
    main = filing_item("main", pack_main, {"name": "Pat", "identifying_number": "000000000", "mailing_address": "X", "1k": "5000"})
    oi = FilingItem(form_key="sched_oi", pack=pack_oi, fields=disk_fields(pack_oi, {"L1e": "5000"}))
    with pytest.raises(ValueError, match="unknown form_key") as excinfo:
        verify_filing([main, oi], independent={"nope": {"L1e": 5000}})
    message = str(excinfo.value)
    assert "main" in message and "sched_oi" in message  # names the valid form_key(s)


def test_verify_filing_independent_recompute_passes_and_prefixes_form_key():
    # A matching independent recompute against an item's disk value yields a
    # PASS whose .line is prefixed "<form_key>: <line>"; report.ok stays True.
    pack_oi = make_pack([money_field("L1e")], form="SCHED-OI")
    oi = FilingItem(form_key="sched_oi", pack=pack_oi, fields=disk_fields(pack_oi, {"L1e": "5000"}))
    report = verify_filing([oi], independent={"sched_oi": {"L1e": 5000}})
    assert report.ok is True
    recompute = next(check for check in report.recompute if "L1e" in check.line)
    assert recompute.status == "PASS"
    assert recompute.line == "sched_oi: L1e"  # prefixed with the item's form_key
    assert recompute.filled == 5000 and recompute.recomputed == 5000


def test_verify_filing_independent_recompute_mismatch_flips_ok_to_false():
    # An independent expected value that disagrees with the item's disk value
    # is a recompute FAIL and flips report.ok to False (aggregated via _all_pass).
    pack_oi = make_pack([money_field("L1e")], form="SCHED-OI")
    oi = FilingItem(form_key="sched_oi", pack=pack_oi, fields=disk_fields(pack_oi, {"L1e": "5000"}))
    report = verify_filing([oi], independent={"sched_oi": {"L1e": 4000}})
    assert report.ok is False
    recompute = next(check for check in report.recompute if "L1e" in check.line)
    assert recompute.status == "FAIL"
    assert recompute.line == "sched_oi: L1e"
    assert recompute.filled == 5000 and recompute.recomputed == 4000  # disk vs. recompute


# ---------------------------------------------------------------------------
# pypdf layer — offline round-trip over a synthetic AcroForm PDF
# ---------------------------------------------------------------------------

SSN_FIELD = f"{ROOT}.Page1[0].f_identifying_number[0]"
NAME_FIELD = f"{ROOT}.Page1[0].f_name[0]"
BOX_FIELD = f"{ROOT}.Page1[0].c_box[0]"


@pytest.fixture()
def filled_pdf(tmp_path):
    """A synthetic filled PDF: dashed SSN in a 9-cell comb (the P-001 shape)."""
    from pdf_fixtures import make_acroform_pdf
    from pypdf import PdfWriter

    blank = make_acroform_pdf(
        tmp_path / "blank.pdf",
        [
            {"name": SSN_FIELD, "kind": "text", "maxlen": 9, "comb": True, "width": 120},
            {"name": NAME_FIELD, "kind": "text", "width": 200},
            {"name": BOX_FIELD, "kind": "checkbox", "on_value": "/1"},
        ],
    )
    # Fill via pypdf directly (NOT the filler — verification must stay an
    # independent pass; the filler would also refuse this overlong value).
    writer = PdfWriter(clone_from=str(blank))
    writer.update_page_form_field_values(
        None, {SSN_FIELD: "000-00-0000", NAME_FIELD: "Pat Q Sample"}, auto_regenerate=False
    )
    out = tmp_path / "filled.pdf"
    with out.open("wb") as fh:
        writer.write(fh)
    return out


def test_read_pdf_fields_round_trip(filled_pdf):
    fields = read_pdf_fields(filled_pdf)
    # /V keeps all 11 characters even though pypdf truncates the rendered
    # appearance stream at MaxLen — the P-001 incident shape verbatim.
    assert fields[SSN_FIELD] == "000-00-0000"
    assert fields[NAME_FIELD] == "Pat Q Sample"
    assert fields[BOX_FIELD] == "/Off"  # reportlab writes an explicit /V /Off


def test_read_pdf_fields_missing_file_is_prescriptive(tmp_path):
    with pytest.raises(FileNotFoundError, match="fill_form"):
        read_pdf_fields(tmp_path / "nope.pdf")


def test_read_text_widgets_geometry_round_trip(filled_pdf):
    widgets = {w.name: w for w in read_text_widgets(filled_pdf)}
    assert BOX_FIELD not in widgets  # checkboxes are not text widgets
    ssn = widgets[SSN_FIELD]
    assert ssn.value == "000-00-0000"
    assert ssn.max_len == 9
    assert ssn.rect_width == pytest.approx(120.0)
    name = widgets[NAME_FIELD]
    assert name.max_len is None
    assert name.rect_width == pytest.approx(200.0)
    assert name.da  # reportlab writes a /DA; the heuristic has a font size


def test_read_layer_reconstructs_hierarchical_qualified_names(tmp_path):
    # Regression (coverage gap): real IRS forms are TRUE parent/kid AcroForm
    # trees (topmostSubform[0] -> Page1[0] -> f1_7[0]); the fixtures used to
    # be flat merged fields, so _widget_qualified_name's /T-joining walk and
    # _inherited's /Parent-chain key resolution were never exercised.
    from pdf_fixtures import make_acroform_pdf

    hier_name = f"{ROOT}.Page1[0].f1_7[0]"
    pdf = make_acroform_pdf(
        tmp_path / "hier.pdf",
        [
            {
                "name": hier_name,
                "kind": "text",
                "maxlen": 9,
                "comb": True,
                "value": "000000000",
                "hierarchical": True,
            }
        ],
    )
    widgets = {w.name: w for w in read_text_widgets(pdf)}
    ssn = widgets[hier_name]  # dotted name rebuilt from the /T parts
    assert ssn.value == "000000000"  # /V inherited from the field dict
    assert ssn.max_len == 9  # /MaxLen inherited from the field dict
    assert ssn.da  # /DA inherited from the field dict
    assert read_pdf_fields(pdf)[hier_name] == "000000000"
    # The whole verify_form path works against the hierarchical shape too.
    pack = make_pack(
        [
            {
                "line": "identifying_number",
                "field": "Page1[0].f1_7[0]",
                "type": "text",
                "maxlen": 9,
                "comb": True,
                "format": "ssn_digits_only",
            }
        ]
    )
    report = verify_form(pack, str(pdf), expected={"identifying_number": "000-00-0000"})
    assert report.ok is True
    assert all(check.status == "PASS" for check in report.assertions)


def test_verify_form_from_pdf_path_catches_p001_end_to_end(filled_pdf):
    # The full production incident on a real PDF: the dashed SSN MATCHES its
    # intended digits in the assertion diff (invisible in dumps) yet FAILS
    # the clipping scan read from the same file.
    pack = make_pack(
        [
            text_field("identifying_number", maxlen=9, comb=True, format="ssn_digits_only"),
            text_field("name"),
            checkbox_field("box", required=True),
        ]
    )
    report = verify_form(
        pack,
        str(filled_pdf),
        expected={"identifying_number": "000-00-0000", "name": "Pat Q Sample"},
    )
    assert report.ok is False
    assert all(check.status == "PASS" for check in report.assertions)
    ssn_clip = next(check for check in report.clipping if check.name == SSN_FIELD)
    assert ssn_clip.status == "FAIL"
    assert "MaxLen is 9" in ssn_clip.detail
    assert "000-00-0000" not in ssn_clip.detail  # PII-safe detail
    pitfalls = {check.id: check.status for check in report.pitfall_checks}
    assert pitfalls["P-001"] == "FAIL"
    assert pitfalls["P-003"] == "FAIL"  # the required checkbox is still /Off
