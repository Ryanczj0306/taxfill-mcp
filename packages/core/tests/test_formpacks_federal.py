"""Data-driven harness over every federal form pack (M2, dev plan section 5).

Auto-discovers ``formpacks/federal/<tax_year>/<form_key>/pack.yaml`` and
parametrizes every check by pack path — adding a pack directory is enough to
put it under test, no edits here. Two layers:

- **offline structural checks** (always run): the pack parses via
  ``load_pack``; the sha256 is real (never the ``"..."`` placeholder); every
  line id matches the binding grammar in ``formpacks/CONVENTIONS.md``;
  relations parse in verify's evaluator; cross_form targets use known form
  keys; radio options sharing one field share one group.
- **golden round-trip** (``@pytest.mark.network``): fetch the official
  blank (shared cache ``.cache/blanks/``), fill EVERY mapped line with
  distinct synthetic values, verify (assertion diff, clipping scan,
  checkbox audit), and render page 1. Skips gracefully when the cache is
  empty and the network is unreachable.

With zero packs the parametrized tests collect to zero cases and the
harness still proves itself through the synthetic-value generator unit
tests and an offline round-trip over a synthetic fixture PDF.

Synthetic data only: SSN-style values are obviously fake (999-88-xxxx).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pdf_fixtures import make_acroform_pdf
from taxfill_core.fetch import OfflineFetchError, fetch_blank
from taxfill_core.filler import fill_form
from taxfill_core.render import render_pdf
from taxfill_core.schemas.formpack import FormPack, PackField, load_pack
from taxfill_core.verify import relations, verify_form

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_PATHS = sorted((REPO_ROOT / "formpacks" / "federal").glob("*/*/pack.yaml"))

# The only valid <form_key> directory names AND cross_form reference targets
# (formpacks/CONVENTIONS.md).
KNOWN_FORM_KEYS = frozenset(
    {
        "f8843",
        "f8863",
        "f2555",
        "f4868",
        "f1040es",
        "f1040x",
        "fw7",
        "f8959",
        "f8960",
        "f8962",
        "sched_8812",
        "f2441",
        "f843",
        "f8316",
        "sched_a_nr",
        "sched_nec",
        "f1040nr",
        "f1040",
        "sched_1",
        "sched_2",
        "sched_3",
        "sched_a",
        "sched_b",
        "sched_c",
        "sched_d",
        "sched_e",
        "sched_oi",
        "sched_se",
    }
)

# The binding line-id grammar (formpacks/CONVENTIONS.md): dot-separated
# segments, each a lowercased printed line label (1a, 16, 23) or a word
# (filing_status, dependent_1, ssn).
LINE_ID_RE = re.compile(r"^(?:[0-9]+[a-z]?|[a-z][a-z0-9_]*)(?:\.(?:[0-9]+[a-z]?|[a-z][a-z0-9_]*))*$")

_SHA256_PLACEHOLDER = "..."


def _pack_id(pack_path: Path) -> str:
    return f"{pack_path.parent.parent.name}-{pack_path.parent.name}"


# ---------------------------------------------------------------------------
# Synthetic-value generator: distinct, type-appropriate fill data per line
# ---------------------------------------------------------------------------


def _synthetic_text(pack_field: PackField, index: int) -> str:
    """Type-appropriate fake text for one line, keyed by format/comb/maxlen/name."""
    line = pack_field.line.casefold()
    if pack_field.comb or pack_field.format == "ssn_digits_only":
        # Obviously-fake digits (999-88-xxxx style), distinct per index,
        # sized to the comb cell count.
        width = pack_field.maxlen or 9
        return str(999_880_000 + index)[-width:]
    if "name" in line:
        base = f"Test Taxpayer {index}"
    elif "street" in line or "address" in line:
        base = f"{100 + index} Synthetic Way"
    elif "city" in line:
        base = f"Faketown {index}"
    elif "zip" in line or "postal" in line:
        base = str(99500 + index)[:5]
    elif "country" in line:
        base = "Testland"
    elif "date" in line:
        base = "01/15/2024"
    elif "phone" in line:
        base = "0000000000"
    else:
        base = f"Test {index}"
    if pack_field.maxlen is not None and len(base) > pack_field.maxlen:
        base = base[: pack_field.maxlen]
    return base


def synthetic_values(pack: FormPack) -> dict[str, object]:
    """Fill values for EVERY mapped line of a pack, radio-group safe.

    - money lines get distinct small whole-dollar amounts (101, 112, 123, ...
      — small enough never to trip the width clipping heuristic);
    - every checkbox question is exercised exactly once: the FIRST member of
      each ``group`` — and of each shared AcroForm ``field`` (radio kids) —
      is answered yes, siblings are omitted (a radio field holds one choice);
    - text lines get type-appropriate fake data (SSN comb fields get
      obviously fake 999-88-xxxx digits).
    """
    values: dict[str, object] = {}
    money_index = 0
    text_index = 0
    answered: set[tuple[str, str]] = set()
    for pack_field in pack.fields:
        if pack_field.type == "money":
            values[pack_field.line] = 101 + 11 * money_index
            money_index += 1
        elif pack_field.type == "checkbox":
            keys = {("field", pack_field.field)}
            if pack_field.group:
                keys.add(("group", pack_field.group))
            if keys & answered:
                continue  # this question/radio field is already answered
            answered |= keys
            values[pack_field.line] = True
        else:
            values[pack_field.line] = _synthetic_text(pack_field, text_index)
            text_index += 1
    return values


def _assert_section_clean(section, section_name: str) -> None:
    failures = [check for check in section if check.status == "FAIL"]
    assert not failures, f"{section_name} failures:\n" + "\n".join(
        f"- {check.detail}" for check in failures
    )


# ---------------------------------------------------------------------------
# Offline structural checks — one parametrized case per discovered pack
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=_pack_id)
def test_pack_parses_and_matches_its_directory(pack_path: Path):
    pack = load_pack(pack_path)
    form_key = pack_path.parent.name
    year_dir = pack_path.parent.parent.name
    assert form_key in KNOWN_FORM_KEYS, (
        f"directory '{form_key}' is not a known form key — use one of "
        f"{sorted(KNOWN_FORM_KEYS)} (formpacks/CONVENTIONS.md)"
    )
    assert year_dir.isdigit() and int(year_dir) == pack.tax_year, (
        f"directory tax year '{year_dir}' must equal the pack's tax_year {pack.tax_year}"
    )
    assert pack.jurisdiction == "federal"


@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=_pack_id)
def test_pack_sha256_is_real_not_placeholder(pack_path: Path):
    pack = load_pack(pack_path)
    assert pack.pdf_sha256 != _SHA256_PLACEHOLDER, (
        "pdf_sha256 is the authoring placeholder '...' — packs never ship without the "
        "real digest; download the blank with fetch_blank(source_url), confirm the "
        "printed revision year and title by rendering page 1, then pin "
        "compute_sha256(path)"
    )


@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=_pack_id)
def test_pack_source_url_is_official_irs(pack_path: Path):
    pack = load_pack(pack_path)
    assert pack.source_url.startswith(
        ("https://www.irs.gov/pub/irs-pdf/", "https://www.irs.gov/pub/irs-prior/")
    ), (
        f"source_url {pack.source_url!r} is not an official IRS pattern — use "
        f"https://www.irs.gov/pub/irs-pdf/<file>.pdf (current year) or "
        f"https://www.irs.gov/pub/irs-prior/<file>--<year>.pdf (prior revision)"
    )


@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=_pack_id)
def test_pack_line_ids_match_the_conventions_grammar(pack_path: Path):
    pack = load_pack(pack_path)
    bad = [pf.line for pf in pack.fields if not LINE_ID_RE.fullmatch(pf.line)]
    assert not bad, (
        f"line id(s) {bad} violate the binding grammar in formpacks/CONVENTIONS.md — "
        f"lowercased printed labels ('1a', '16') or dotted lowercase words "
        f"('filing_status.single', 'mailing_address.street')"
    )


@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=_pack_id)
def test_pack_relations_parse_in_verifys_evaluator(pack_path: Path):
    pack = load_pack(pack_path)
    # Malformed relation STRINGS raise ValueError; evaluating against an
    # empty value set (everything blank-as-zero) only produces PASS/FAIL
    # checks, so this is a pure parse gate.
    relations(pack, {})


# (tax_year, form_key, target_line) triples a cross_form rule may legitimately
# reference even though no in-scope pack provides them YET — kept explicit and
# commented so the gap stays visible and a stale entry surfaces when the pack
# does ship. (The 2022 1040-NR sched_2/sched_3 rules were REMOVED from the pack
# rather than allowlisted, since sched_2/sched_3 are out of the 2022 scope.)
CROSS_FORM_TARGET_ALLOWLIST: frozenset[tuple[int, str, str]] = frozenset(
    {
        # 2024 Schedule 3 can attach to a 1040 OR a 1040-NR, so it carries both
        # "8 == f1040.20"/"f1040nr.20" and "15 == f1040.31"/"f1040nr.31". The
        # 2024 scope ships f1040 but no f1040nr pack, so the f1040nr legs cannot
        # resolve yet (the f1040 legs do). Remove these once a 2024 f1040nr pack
        # ships.
        (2024, "f1040nr", "20"),
        (2024, "f1040nr", "31"),
        # The 2022 1040-NR keeps its Schedule 2/3 cross_form rules so the verifier
        # can emit its runtime "attach Schedule 2/3 and re-verify" caution when a
        # back-filer puts a nonzero amount on lines 17/20/23b/31, but the M2 2022
        # scope (dev plan section 15) ships no 2022 sched_2/sched_3 pack, so those
        # targets cannot resolve yet. Remove once 2022 sched_2/sched_3 ship.
        (2022, "sched_2", "3"),
        (2022, "sched_2", "21"),
        (2022, "sched_3", "8"),
        (2022, "sched_3", "15"),
    }
)


def _lines_by_year_and_form() -> dict[tuple[int, str], set[str]]:
    """Map (tax_year, form_key) -> set of line ids, over every discovered pack.

    form_key is the pack DIRECTORY name (what cross_form refs and FilingItem
    keys use), which the parses-and-matches test already pins to the pack's
    own form; tax_year comes from the loaded pack.
    """
    by_key: dict[tuple[int, str], set[str]] = {}
    for path in PACK_PATHS:
        loaded = load_pack(path)
        form_key = path.parent.name
        by_key[(loaded.tax_year, form_key)] = {pf.line for pf in loaded.fields}
    return by_key


@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=_pack_id)
def test_pack_cross_form_targets_resolve_to_an_existing_pack_line(pack_path: Path):
    pack = load_pack(pack_path)
    lines_by_key = _lines_by_year_and_form()
    local_lines = {pf.line for pf in pack.fields}
    for rule in pack.cross_form:
        sides = [side.strip() for side in rule.split("==")]
        assert len(sides) == 2 and all(sides), (
            f"cross_form rule {rule!r} must be '<ref> == <ref>' with exactly one '=='"
        )
        for side in sides:
            if "." in side:
                form_key, _, target = side.partition(".")
                assert form_key in KNOWN_FORM_KEYS, (
                    f"cross_form rule {rule!r}: '{form_key}' is not a known form key — "
                    f"refs are '<form_key>.<line>' with form_key in {sorted(KNOWN_FORM_KEYS)}"
                )
                assert LINE_ID_RE.fullmatch(target), (
                    f"cross_form rule {rule!r}: target line '{target}' violates the line-id grammar"
                )
                if (pack.tax_year, form_key, target) in CROSS_FORM_TARGET_ALLOWLIST:
                    continue  # out-of-scope-for-now target, explicitly allowed
                target_lines = lines_by_key.get((pack.tax_year, form_key))
                assert target_lines is not None, (
                    f"cross_form rule {rule!r}: no pack '{form_key}' exists for tax_year "
                    f"{pack.tax_year} — add the target pack, remove the rule, or allowlist "
                    f"({pack.tax_year}, {form_key!r}, {target!r}) in "
                    f"CROSS_FORM_TARGET_ALLOWLIST with a reason"
                )
                assert target in target_lines, (
                    f"cross_form rule {rule!r}: line '{target}' is not a line of pack "
                    f"'{form_key}' ({pack.tax_year}) — fix the target line or add it to that "
                    f"pack's fields[]"
                )
            else:
                assert side in local_lines, (
                    f"cross_form rule {rule!r}: local ref '{side}' is not a line of this "
                    f"pack — fix the ref or add the line to fields[]"
                )


@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=_pack_id)
def test_pack_radio_options_share_one_group_and_distinct_states(pack_path: Path):
    pack = load_pack(pack_path)
    by_field: dict[str, list[PackField]] = {}
    for pf in pack.fields:
        if pf.type == "checkbox":
            by_field.setdefault(pf.field, []).append(pf)
    for field, members in by_field.items():
        if len(members) < 2:
            continue
        groups = {pf.group for pf in members}
        assert None not in groups and len(groups) == 1, (
            f"checkbox lines {[pf.line for pf in members]} share AcroForm field "
            f"'{field}' (a radio group) but not one 'group' id — give every option "
            f"the same group (formpacks/CONVENTIONS.md)"
        )
        states = [pf.on_state for pf in members]
        assert len(set(states)) == len(states), (
            f"radio options on field '{field}' reuse an on_state ({states}) — each "
            f"option needs its own state; dump the blank PDF's appearance states"
        )


# ---------------------------------------------------------------------------
# Golden round-trip per pack — network (or warm cache)
# ---------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=_pack_id)
def test_pack_golden_roundtrip(pack_path: Path, tmp_path: Path):
    """fetch -> fill every line -> verify -> render EVERY page, per pack."""
    pack = load_pack(pack_path)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")

    values = synthetic_values(pack)
    filled = tmp_path / f"{_pack_id(pack_path)}_filled.pdf"
    result = fill_form(pack, values, blank, filled)
    assert set(result.written), "the pack mapped no fillable lines"

    report = verify_form(pack, filled, expected=values)
    _assert_section_clean(report.assertions, "assertion diff")
    _assert_section_clean(report.clipping, "clipping scan")
    _assert_section_clean(report.checkboxes, "checkbox audit")

    # Render EVERY page (not just page 1): a mis-placed field or clipped value
    # on a later page (e.g. the f1040 page 2 totals, sched_c page 2 expenses)
    # only shows up in a full-document render — the vision-review pass the dev
    # plan (section 10) makes mandatory before "done" needs all pages on disk.
    pages = render_pdf(filled, tmp_path / "png")
    assert len(pages) >= 1, "render produced no pages"
    for page in pages:
        assert page.path.is_file() and page.path.stat().st_size > 1000, (
            f"page {page.page} rendered to an (almost) empty PNG — the blank may be wrong"
        )


# ---------------------------------------------------------------------------
# Harness self-tests (always run, packs or none): the generator + round-trip
# machinery against a synthetic fixture
# ---------------------------------------------------------------------------

ROOT = "topmostSubform[0]"


def _harness_pack() -> FormPack:
    """A pack exercising every value kind the generator must handle."""
    return FormPack.model_validate(
        {
            "form": "TEST-HARNESS",
            "jurisdiction": "federal",
            "tax_year": 2023,
            "source_url": "https://www.irs.gov/pub/irs-pdf/test.pdf",
            "pdf_sha256": "...",
            "acroform_root": ROOT,
            "fields": [
                {
                    "line": "identifying_number",
                    "field": "Page1[0].f1_7[0]",
                    "type": "text",
                    "maxlen": 9,
                    "comb": True,
                    "format": "ssn_digits_only",
                },
                {"line": "name", "field": "Page1[0].f1_4[0]", "type": "text", "maxlen": 30},
                {"line": "mailing_address.street", "field": "Page1[0].f1_5[0]", "type": "text"},
                {"line": "1a", "field": "Page1[0].f1_28[0]", "type": "money"},
                {"line": "1b", "field": "Page1[0].f1_29[0]", "type": "money"},
                {"line": "25d", "field": "Page1[0].f1_30[0]", "type": "money"},
                # yes/no question: two separate checkbox fields, one group
                {"line": "digital_assets.yes", "field": "Page1[0].c1_8[0]", "type": "checkbox", "on_state": "/1", "group": "digital_assets", "required": True},
                {"line": "digital_assets.no", "field": "Page1[0].c1_9[0]", "type": "checkbox", "on_state": "/1", "group": "digital_assets"},
                # radio group: three option lines on ONE /Btn field
                {"line": "filing_status.single", "field": "Page1[0].c1_3[0]", "type": "checkbox", "on_state": "/1", "group": "filing_status", "required": True},
                {"line": "filing_status.mfj", "field": "Page1[0].c1_3[0]", "type": "checkbox", "on_state": "/2", "group": "filing_status"},
                {"line": "filing_status.hoh", "field": "Page1[0].c1_3[0]", "type": "checkbox", "on_state": "/3", "group": "filing_status"},
            ],
        }
    )


def _harness_blank(tmp_path: Path) -> Path:
    return make_acroform_pdf(
        tmp_path / "harness_blank.pdf",
        [
            {"name": f"{ROOT}.Page1[0].f1_7[0]", "maxlen": 9, "comb": True},
            {"name": f"{ROOT}.Page1[0].f1_4[0]", "maxlen": 30},
            {"name": f"{ROOT}.Page1[0].f1_5[0]"},
            {"name": f"{ROOT}.Page1[0].f1_28[0]"},
            {"name": f"{ROOT}.Page1[0].f1_29[0]"},
            {"name": f"{ROOT}.Page1[0].f1_30[0]"},
            {"name": f"{ROOT}.Page1[0].c1_8[0]", "kind": "checkbox", "on_value": "/1"},
            {"name": f"{ROOT}.Page1[0].c1_9[0]", "kind": "checkbox", "on_value": "/1"},
            {"name": f"{ROOT}.Page1[0].c1_3[0]", "kind": "radio", "on_value": "/1"},
            {"name": f"{ROOT}.Page1[0].c1_3[0]", "kind": "radio", "on_value": "/2"},
            {"name": f"{ROOT}.Page1[0].c1_3[0]", "kind": "radio", "on_value": "/3"},
        ],
    )


def test_line_id_grammar_accepts_conventional_ids():
    for good in (
        "1a",
        "16",
        "23",
        "25d",
        "name",
        "identifying_number",
        "mailing_address",
        "mailing_address.street",
        "filing_status.single",
        "digital_assets.yes",
        "dependent_1.ssn",
    ):
        assert LINE_ID_RE.fullmatch(good), f"grammar must accept {good!r}"


def test_line_id_grammar_rejects_unconventional_ids():
    for bad in ("1A", "Line1", "L16", "1aa", "", ".x", "1a.", "filing status", "1a..b", "_x"):
        assert not LINE_ID_RE.fullmatch(bad), f"grammar must reject {bad!r}"


def test_synthetic_money_values_are_distinct_whole_dollars():
    values = synthetic_values(_harness_pack())
    money = [values["1a"], values["1b"], values["25d"]]
    assert len(set(money)) == 3
    assert all(isinstance(amount, int) and amount > 0 for amount in money)


def test_synthetic_values_cover_every_text_and_money_line():
    pack = _harness_pack()
    values = synthetic_values(pack)
    for pf in pack.fields:
        if pf.type != "checkbox":
            assert pf.line in values, f"generator skipped line '{pf.line}'"


def test_synthetic_checkboxes_exercise_each_group_exactly_once():
    pack = _harness_pack()
    values = synthetic_values(pack)
    # First member of each question answered yes; siblings omitted (a radio
    # field holds one choice — two yes answers would be rejected by fill_form).
    assert values.get("digital_assets.yes") is True
    assert "digital_assets.no" not in values
    assert values.get("filing_status.single") is True
    assert "filing_status.mfj" not in values and "filing_status.hoh" not in values


def test_synthetic_comb_values_are_obviously_fake_digits_within_maxlen():
    pack = _harness_pack()
    values = synthetic_values(pack)
    ssn = values["identifying_number"]
    assert isinstance(ssn, str) and ssn.isdigit() and len(ssn) == 9
    assert ssn.startswith("99988")  # 999-88-xxxx: never a real SSN


def test_synthetic_text_respects_maxlen():
    pack = _harness_pack()
    values = synthetic_values(pack)
    name = values["name"]
    assert isinstance(name, str) and 0 < len(name) <= 30


def test_offline_golden_roundtrip_over_synthetic_fixture(tmp_path: Path):
    """The exact network round-trip flow, proven offline on a fixture PDF."""
    pack = _harness_pack()
    blank = _harness_blank(tmp_path)
    values = synthetic_values(pack)

    filled = tmp_path / "filled.pdf"
    result = fill_form(pack, values, blank, filled)
    assert set(result.written)

    report = verify_form(pack, filled, expected=values)
    _assert_section_clean(report.assertions, "assertion diff")
    _assert_section_clean(report.clipping, "clipping scan")
    _assert_section_clean(report.checkboxes, "checkbox audit")
    # Both required groups (yes/no pair AND the radio group) were audited.
    assert {check.group for check in report.checkboxes} == {"digital_assets", "filing_status"}

    pages = render_pdf(filled, tmp_path / "png", pages=[1])
    assert pages[0].path.is_file() and pages[0].path.stat().st_size > 1000
