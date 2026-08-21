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
        "sched_1a",
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
        # (The 2025 Schedule 3 f1040nr legs and the 2025 f1040 Schedule
        # 1/2/1-A legs were allowlisted here while those packs were pending;
        # the 2025 f1040nr, sched_1, sched_2, and sched_1a packs have all
        # shipped, so those targets now resolve directly.)
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
# Pitfall P-007 — Schedule D's two shaded no-adjustment (g) cells stay unmapped
# ---------------------------------------------------------------------------

# Schedule D rows 1a and 8a are the NO-ADJUSTMENT rows: "Totals for all
# short-term [long-term] transactions reported on Form 1099-B [or Form 1099-DA]
# for which basis was reported to the IRS and for which you have no adjustments
# (see instructions)". Column (g) is headed "Adjustments to gain or loss from
# Form(s) 8949, Part I [Part II], line 2, column (g)" — and a transaction that
# HAS an adjustment is routed by that same printed text to line 1b/8b + Form
# 8949. So no correct entry exists in those two cells (for these rows column
# (h) is just (d) - (e)), and the blank agrees: it prints them solid grey and
# sets the AcroForm ReadOnly bit on exactly those 2 of its 55 widgets
# (/Ff = 8388609 = DoNotScroll|ReadOnly).
#
# They were mapped as ordinary money lines through 2026-08-20, so the filler
# printed digits inside the grey boxes with no warning — and verify's clipping
# scan skips ReadOnly widgets, so nothing downstream caught it. Keyed by year
# because the 2025 revision dropped the "_RO" suffix from the widget NAMES
# while keeping the flag; a name-only port audit reads that as cosmetic.
SCHED_D_SHADED_G_WIDGETS: dict[int, tuple[str, ...]] = {
    2023: (
        "Page1[0].Table_PartI[0].Row1a[0].f1_05_RO[0]",
        "Page1[0].Table_PartII[0].Row8a[0].f1_25_RO[0]",
    ),
    2024: (
        "Page1[0].Table_PartI[0].Row1a[0].f1_05_RO[0]",
        "Page1[0].Table_PartII[0].Row8a[0].f1_25_RO[0]",
    ),
    2025: (
        "Page1[0].Table_PartI[0].Row1a[0].f1_5[0]",
        "Page1[0].Table_PartII[0].Row8a[0].f1_25[0]",
    ),
}

SCHED_D_PACK_PATHS = [path for path in PACK_PATHS if path.parent.name == "sched_d"]


def _read_only_widget_names(pdf_path: Path) -> set[str]:
    """Fully qualified names of every ReadOnly (/Ff bit 1) widget in a PDF.

    Deliberately independent of taxfill_core.verify's own helpers: this test
    audits the engine's premise that ReadOnly widgets are never written, so it
    must read the flags for itself.
    """
    from pypdf import PdfReader

    def inherited(node, key):
        hops = 0
        while node is not None and hops < 64:
            if key in node:
                return node[key]
            parent = node.get("/Parent")
            node = parent.get_object() if parent is not None else None
            hops += 1
        return None

    def qualified_name(node) -> str:
        parts: list[str] = []
        hops = 0
        while node is not None and hops < 64:
            title = node.get("/T")
            if title:
                parts.append(str(title))
            parent = node.get("/Parent")
            node = parent.get_object() if parent is not None else None
            hops += 1
        return ".".join(reversed(parts))

    names: set[str] = set()
    for page in PdfReader(str(pdf_path)).pages:
        for annot_ref in page.get("/Annots") or []:
            annot = annot_ref.get_object()
            flags = inherited(annot, "/Ff")
            if flags is not None and int(flags) & 1:
                names.add(qualified_name(annot))
    return names


@pytest.mark.parametrize("pack_path", SCHED_D_PACK_PATHS, ids=_pack_id)
def test_sched_d_never_maps_the_shaded_no_adjustment_g_cells(pack_path: Path, tmp_path: Path):
    """P-007: no line id, no binding, and the filler refuses the keys outright."""
    pack = load_pack(pack_path)
    shaded = SCHED_D_SHADED_G_WIDGETS.get(pack.tax_year)
    assert shaded is not None, (
        f"sched_d {pack.tax_year} is not covered by SCHED_D_SHADED_G_WIDGETS — dump the "
        f"blank's /Ff flags for the Row1a/Row8a column (g) widgets and add the year "
        f"(pitfall P-007); never port the map without re-reading those two flags"
    )
    by_line = {pf.line: pf.field for pf in pack.fields}
    mapped_fields = set(by_line.values())
    for line in ("1a.g", "8a.g"):
        assert line not in by_line, (
            f"sched_d {pack.tax_year} maps '{line}' — that is the SHADED, ReadOnly "
            f"adjustments cell on the form's own 'no adjustments' row, so any value "
            f"written there prints inside a grey box the IRS locked. Drop the binding "
            f"(pitfall P-007); the row stays reachable through .d/.e/.h"
        )
    for widget in shaded:
        assert widget not in mapped_fields, (
            f"sched_d {pack.tax_year} binds the shaded ReadOnly widget '{widget}' "
            f"(re-mapped under a different line id?) — it must stay unmapped (P-007)"
        )
    # Only column (g) of rows 1a/8a is impossible: the rest of both rows, and
    # column (g) of every OTHER row, are ordinary fillable cells.
    for line in ("1a.d", "1a.e", "1a.h", "8a.d", "8a.e", "8a.h"):
        assert line in by_line, f"sched_d {pack.tax_year} lost line '{line}' (P-007 over-reach)"
    for line in ("1b.g", "2.g", "3.g", "8b.g", "9.g", "10.g"):
        assert line in by_line, (
            f"sched_d {pack.tax_year} lost line '{line}' — rows 1b/2/3/8b/9/10 DO take "
            f"Form 8949 adjustments; their (g) cells are white and fillable (P-007)"
        )
    # The keys are now hard errors, not silent writes. fill_form validates
    # unknown line keys before it opens the blank, so no PDF is needed here.
    for line in ("1a.g", "8a.g"):
        with pytest.raises(ValueError, match=r"unknown line key"):
            fill_form(pack, {line: 99999}, tmp_path / "absent-blank.pdf", tmp_path / "out.pdf")


@pytest.mark.network
@pytest.mark.parametrize("pack_path", SCHED_D_PACK_PATHS, ids=_pack_id)
def test_sched_d_shaded_g_cells_are_the_only_readonly_widgets_and_unmapped(pack_path: Path):
    """P-007 against the official blank: prove the flags, then prove nothing maps them."""
    pack = load_pack(pack_path)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")

    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    read_only = _read_only_widget_names(Path(blank))
    expected = {prefix + widget for widget in SCHED_D_SHADED_G_WIDGETS[pack.tax_year]}
    assert read_only == expected, (
        f"sched_d {pack.tax_year}: the blank's ReadOnly widget set changed. Expected the "
        f"two shaded no-adjustment (g) cells {sorted(expected)}, got {sorted(read_only)} — "
        f"render page 1, read the printed row text for every changed cell, and update "
        f"SCHED_D_SHADED_G_WIDGETS plus the pack's exclusion note (P-007)"
    )
    mapped = {prefix + pf.field for pf in pack.fields}
    overlap = sorted(mapped & read_only)
    assert not overlap, (
        f"sched_d {pack.tax_year} maps ReadOnly widget(s) {overlap} — the filler would "
        f"write a value into a box the IRS greyed out and locked (P-007)"
    )


# ---------------------------------------------------------------------------
# Pitfall P-008 — separate-widget Yes/No pairs need a `group` id
# ---------------------------------------------------------------------------

# The pre-existing group gate (test_pack_radio_options_share_one_group_and_
# distinct_states) only fires when two checkbox lines SHARE one AcroForm
# field. Real IRS forms implement Yes/No the other way just as often: TWO
# independent terminal /Btn fields (c1_1[0] and c1_1[1]), each with its own
# /V and a single on-state. Nothing in the PDF makes those exclusive and the
# shared-field gate never sees them, so an ungrouped pair sails through and
# fill_form will happily set BOTH boxes on. This test covers that topology by
# LINE SHAPE ("<stem>.yes" + "<stem>.no") instead of by shared field, which is
# the check that would have caught the sched_e miss.

# Yes/No line pairs that are knowingly still ungrouped. Each entry is a
# visible, self-clearing debt: when the pack gets its group ids, this test
# fails on the stale entry and the entry must be deleted.
#   sched_d 2023/2024/2025 — the SAME defect on 4 questions per year (qof,
#   17, 20, 22; all separate-widget pairs, zero group keys). Found by this
#   test's own sweep while fixing sched_e and deliberately NOT fixed in the
#   same change: sched_d is under concurrent P-007 work, and each question
#   needs its own printed-face read to decide the group id and whether the
#   question is `required`. Tracked in knowledge/pitfalls.yaml P-008.
KNOWN_UNGROUPED_YESNO_PAIRS: frozenset[tuple[int, str, str]] = frozenset(
    (year, "sched_d", stem)
    for year in (2023, 2024, 2025)
    for stem in ("qof", "17", "20", "22")
)


def _yesno_pairs(pack: FormPack) -> dict[str, list[PackField]]:
    """Checkbox lines grouped by stem, for stems that have a .yes AND a .no."""
    stems: dict[str, list[PackField]] = {}
    for pack_field in pack.fields:
        if pack_field.type != "checkbox" or "." not in pack_field.line:
            continue
        stem, last = pack_field.line.rsplit(".", 1)
        if last in ("yes", "no"):
            stems.setdefault(stem, []).append(pack_field)
    return {stem: members for stem, members in stems.items() if len(members) > 1}


@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=_pack_id)
def test_every_yes_no_pair_shares_one_group_id(pack_path: Path):
    """P-008: exclusivity comes from the `group` id, not from the PDF."""
    pack = load_pack(pack_path)
    form_key = pack_path.parent.name
    for stem, members in _yesno_pairs(pack).items():
        groups = {member.group for member in members}
        grouped = None not in groups and len(groups) == 1
        known = (pack.tax_year, form_key, stem) in KNOWN_UNGROUPED_YESNO_PAIRS
        if known:
            assert not grouped, (
                f"{form_key} {pack.tax_year}: '{stem}' now has its group id — delete "
                f"({pack.tax_year}, {form_key!r}, {stem!r}) from "
                f"KNOWN_UNGROUPED_YESNO_PAIRS so the rule applies to it again (P-008)"
            )
            continue
        assert grouped, (
            f"{form_key} {pack.tax_year}: lines {sorted(m.line for m in members)} are the "
            f"Yes/No boxes of ONE question but do not share one 'group' id (groups="
            f"{sorted(str(g) for g in groups)}). They map to SEPARATE AcroForm fields "
            f"{sorted({m.field for m in members})}, so the PDF does not make them "
            f"exclusive and fill_form would set both boxes on — a return showing Yes AND "
            f"No. Give both lines the same group (formpacks/CONVENTIONS.md, pitfall P-008)"
        )


SCHED_E_PACK_PATHS = [path for path in PACK_PATHS if path.parent.name == "sched_e"]

# Schedule E's three Yes/No questions: printed label -> (group id, the two
# separate /Btn fields, Yes state, No state). Question A ("Did you make any
# payments in <year> that would require you to file Form(s) 1099?") and B ("If
# 'Yes,' did you or will you file required Form(s) 1099?") head Part I; line 27
# (the at-risk / prior-year-unallowed-loss question) heads Part II. Verified on
# the 2023, 2024 and 2025 blanks: identical widget names, identical states.
SCHED_E_YESNO: dict[str, tuple[str, str, str]] = {
    "a": ("question_a", "Page1[0].c1_1[0]", "Page1[0].c1_1[1]"),
    "b": ("question_b", "Page1[0].c1_2[0]", "Page1[0].c1_2[1]"),
    "27": ("line27", "Page2[0].c2_1[0]", "Page2[0].c2_1[1]"),
}


@pytest.mark.parametrize("pack_path", SCHED_E_PACK_PATHS, ids=_pack_id)
def test_sched_e_yes_no_questions_are_grouped_and_reject_double_answers(
    pack_path: Path, tmp_path: Path
):
    """P-008 on the pack that carried the defect: ids, topology, and the guard."""
    pack = load_pack(pack_path)
    by_line = {pf.line: pf for pf in pack.fields}
    # fill_form checks the blank exists before it validates the group, so the
    # guard needs a file — but it raises before parsing, so any file will do.
    stub = tmp_path / "unparsed-blank.pdf"
    stub.write_bytes(b"not a pdf")

    for stem, (group_id, yes_field, no_field) in SCHED_E_YESNO.items():
        yes, no = by_line[f"{stem}.yes"], by_line[f"{stem}.no"]
        assert yes.group == no.group == group_id, (
            f"sched_e {pack.tax_year}: '{stem}.yes'/'{stem}.no' must both carry "
            f"group '{group_id}' (got {yes.group!r}/{no.group!r}) — P-008"
        )
        # The topology that makes the group id load-bearing: two DIFFERENT
        # fields, so the shared-field gate above can never cover this pair.
        assert (yes.field, no.field) == (yes_field, no_field), (
            f"sched_e {pack.tax_year}: '{stem}' Yes/No widgets moved to "
            f"{(yes.field, no.field)} — re-read the blank and update SCHED_E_YESNO "
            f"before trusting the group ids (P-008)"
        )
        assert yes.field != no.field, (
            f"sched_e {pack.tax_year}: '{stem}' now shares one field — re-derive the "
            f"exclusivity story; a shared field is a radio group (P-008)"
        )
        assert (yes.on_state, no.on_state) == ("/1", "/2"), (
            f"sched_e {pack.tax_year}: '{stem}' on_states are "
            f"{(yes.on_state, no.on_state)}, expected ('/1', '/2') — P-008"
        )
        # Part I (A/B) and Part II (27) are each skipped by filers who do not
        # use that part, so no member is unconditionally required. Marking one
        # would FAIL verification on every legitimately blank Schedule E.
        assert not yes.required and not no.required, (
            f"sched_e {pack.tax_year}: '{stem}' is marked required, but a filer using "
            f"only the other Parts leaves it blank (P-008)"
        )
        # The guard itself: answering Yes AND No is now a hard error.
        with pytest.raises(ValueError, match=rf"checkbox group '{group_id}'"):
            fill_form(
                pack, {f"{stem}.yes": True, f"{stem}.no": True}, stub, tmp_path / "out.pdf"
            )
        # ...and exactly one answer is still accepted (no over-reach).
        for line in (f"{stem}.yes", f"{stem}.no"):
            with pytest.raises(ValueError, match="could not be parsed as a PDF"):
                fill_form(pack, {line: True}, stub, tmp_path / "out.pdf")


@pytest.mark.parametrize("pack_path", SCHED_E_PACK_PATHS, ids=_pack_id)
def test_sched_e_declares_all_four_whole_line_combine_relations(pack_path: Path):
    """The pack's relation note promised every all-plain-operand combine; it now keeps it.

    26 ("Combine lines 24 and 25") and 41 ("Combine lines 26, 32, 37, 39, and
    40") have all-plain mapped operands and are stated unconditionally on the
    printed face, but only 32 and 37 were declared while the header claimed
    those were the only two that qualified. Losses are submitted SIGNED
    (filler._render_money never writes accountant parens), so the pre-printed
    "( )" on lines 25/31/36 does not change the arithmetic — 32 and 37 already
    depended on that, via 31 and 36.
    """
    pack = load_pack(pack_path)
    expected = [
        "26 == 24 + 25",
        "32 == 30 + 31",
        "37 == 35 + 36",
        "41 == 26 + 32 + 37 + 39 + 40",
    ]
    assert sorted(pack.relations) == sorted(expected), (
        f"sched_e {pack.tax_year} declares {sorted(pack.relations)}; expected "
        f"{sorted(expected)} — if a printed line changed, re-read the blank and update "
        f"the pack's relation note in the SAME edit (the note is what went stale before)"
    )
    signed = {
        "24": 1000, "25": -400, "26": 600,     # 25 prints "( )": stored negative
        "30": 10, "31": -4, "32": 6,           # 31 prints "( )"
        "35": 7, "36": -2, "37": 5,            # 36 prints "( )"
        "39": 3, "40": 2, "41": 616,
    }
    checks = {check.relation: check.status for check in relations(pack, signed)}
    assert set(checks.values()) == {"PASS"}, f"signed-value example failed: {checks}"
    # And a wrong total is caught, so the relations are not vacuous.
    broken = {**signed, "41": 615}
    statuses = {c.relation: c.status for c in relations(pack, broken)}
    assert statuses["41 == 26 + 32 + 37 + 39 + 40"] == "FAIL", statuses


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
