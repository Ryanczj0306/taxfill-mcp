"""Data-driven harness over every federal form pack (M2, dev plan section 5).

Auto-discovers ``formpacks/federal/<tax_year>/<form_key>/pack.yaml`` and
parametrizes every check by pack path — adding a pack directory is enough to
put it under test, no edits here. Two layers:

- **offline structural checks** (always run): the pack parses via
  ``load_pack``; the sha256 is real (never the ``"..."`` placeholder); every
  line id matches the binding grammar in ``formpacks/CONVENTIONS.md``;
  relations parse in verify's evaluator.
- **golden round-trip** (``@pytest.mark.network``): fetch the official
  blank (shared cache ``.cache/blanks/``), fill EVERY mapped line with
  distinct synthetic values, verify (assertion diff, clipping scan,
  checkbox audit), and render page 1. Skips gracefully when the cache is
  empty and the network is unreachable.

Two invariants that USED to live here are repo-wide and now live in
``test_pack_invariants.py`` instead: cross_form target resolution and the
checkbox-``group`` rule. Both were parametrized over ``PACK_PATHS`` (federal
only) while ``formpacks/CONVENTIONS.md`` called them binding on every pack,
and three dangling ``f1040.11`` refs plus two packs' worth of missing group
ids shipped past CI through that gap. ``KNOWN_FORM_KEYS`` and ``LINE_ID_RE``
still live here and are imported from there.

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
        "f8606",
        "f8833",
        "f8889",
        "f8949",
        "f8938",
        "f1116",
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


# cross_form target resolution and the checkbox-`group` invariant used to live
# here, parametrized over PACK_PATHS — i.e. federal packs only, while
# formpacks/CONVENTIONS.md advertised both as binding on every pack. They now
# sweep every discovered pack, federal AND state, from
# packages/core/tests/test_pack_invariants.py, along with
# CROSS_FORM_TARGET_ALLOWLIST and KNOWN_UNGROUPED_YESNO_PAIRS. Do not
# reintroduce a federal-only copy: three dangling `f1040.11` refs and two
# packs' worth of missing group ids shipped past CI in exactly that gap.


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

# The generic sweep (every pack, every option spelling) lives in
# test_pack_invariants.py, together with KNOWN_UNGROUPED_YESNO_PAIRS. What
# stays here is the form-specific pin on the pack that CARRIED the defect:
# Schedule E's three Yes/No questions, whose widget names, on-states and
# not-required verdicts are asserted individually so a port cannot re-derive
# them wrongly.

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
# Form 1116 — the two one-of-N option sets, and the three-column grid (P-008,
# P-007, pitfall P-011)
# ---------------------------------------------------------------------------

# Form 1116 has TWO printed one-of-N option sets and BOTH are the dangerous
# topology formpacks/CONVENTIONS.md says "gets no exemption": every option is
# its own single-widget /Btn field, so nothing in the PDF makes them exclusive
# and the `group` id is the only thing preventing a return that answers one
# question twice. Reproduced on the 2023 blank before the groups were written,
# and again on the 2024 and 2025 blanks during their ports: a sweep that turned
# on every /Btn produced a page 1 with ALL SEVEN category boxes ticked under
# "Check only one box on each Form 1116" and both "(j) Paid" and "(k) Accrued"
# ticked under "(you must check one)". The six new *_ReadOrder /
# ActiveHeaderElements wrappers do NOT change that: dumped on the 2024 blank,
# every one carries no /FT, no /V and no /Ff, so they are name-tree grouping
# nodes and each option is still its own terminal field.
#
# The category on-states are also the a..g ORDER, which is what a column shift
# would silently break: /1..../7 map to boxes a..g reading left to right along
# the upper printed row (a, c, e, g) then the lower one (b, d, f).
#
# WHY THESE TABLES ARE KEYED BY YEAR, and it is not tidiness. The re-authoring
# landed in the 2024 REVISION and persists in 2025. Against the 2023 blank, the
# 2024 blank keeps all 120 widgets and every printed line label but loses 99 of
# the 120 fully-qualified names, adds 99, and changes THREE of the eleven /Btn
# on-states (line 1b "/Yes" -> "/1"; (j) Paid "/Paid" -> "/1"; (k) Accrued
# "/Accrued" -> "/2"). 2025 goes further: 99 of the 2023 names gone, 97 new.
# And — the case that made a per-year table mandatory — the ONE category name
# that survived verbatim now binds a DIFFERENT PRINTED BOX.
# topmostSubform[0].Page1[0].c1_1[0] sat at /Rect x 43.2 with on-state "/1" in
# 2023 (box a, section 951A category income) and sits at x 475.2 with on-state
# "/7" in BOTH 2024 and 2025 (box g, lump-sum distributions), because a..f were
# re-parented into new LineA-B_/LineC-D_/LineE-F_ReadOrder subforms and only g
# was left on Page1[0]. A single shared table would have forced the 2024 and
# 2025 packs to bind `category.section_951a` to the lump-sum box to stay green —
# the wrong basket, the wrong limitation and the wrong Part IV row, with the
# field name and the pack diff both looking clean. Every row below was read off
# its OWN year's blank (/AP /N states dumped, printed letters read off a
# 200/300-dpi crop; 2024 used two complementary discriminating renders, since a
# sweep that ticks all seven cannot tell them apart).
# A year with no row FAILS rather than being skipped, so a new port has to
# introspect before it can pass.
F1116_CATEGORY_BOXES_BY_YEAR: dict[int, tuple[tuple[str, str, str], ...]] = {
    2023: (
        ("category.section_951a", "Page1[0].c1_1[0]", "/1"),        # a Section 951A category income
        ("category.foreign_branch", "Page1[0].c1_1[1]", "/2"),      # b Foreign branch category income
        ("category.passive", "Page1[0].c1_1[2]", "/3"),             # c Passive category income
        ("category.general", "Page1[0].c1_1[3]", "/4"),             # d General category income
        ("category.section_901j", "Page1[0].c1_1[4]", "/5"),        # e Section 901(j) income
        ("category.resourced_by_treaty", "Page1[0].c1_1[5]", "/6"), # f Certain income re-sourced by treaty
        ("category.lump_sum", "Page1[0].c1_1[6]", "/7"),            # g Lump-sum distributions
    ),
    # The re-authoring landed in 2024, not 2025: the 2024 blank already carries
    # the LineA-B_/LineC-D_/LineE-F_ReadOrder wrappers and already leaves box g
    # on the bare 2023 name Page1[0].c1_1[0] (/Rect moved 432.0 pt right,
    # 43.20 -> 475.20; on-state /1 -> /7). Read off the 2024 blank and proved by
    # two complementary discriminating 200-dpi renders (a/d/e ticked, then
    # b/c/f/g), never by the name.
    2024: (
        ("category.section_951a", "Page1[0].LineA-B_ReadOrder[0].c1_1[0]", "/1"),        # a Section 951A category income
        ("category.foreign_branch", "Page1[0].LineA-B_ReadOrder[0].c1_1[1]", "/2"),      # b Foreign branch category income
        ("category.passive", "Page1[0].LineC-D_ReadOrder[0].c1_1[0]", "/3"),             # c Passive category income
        ("category.general", "Page1[0].LineC-D_ReadOrder[0].c1_1[1]", "/4"),             # d General category income
        ("category.section_901j", "Page1[0].LineE-F_ReadOrder[0].c1_1[0]", "/5"),        # e Section 901(j) income
        ("category.resourced_by_treaty", "Page1[0].LineE-F_ReadOrder[0].c1_1[1]", "/6"), # f Certain income re-sourced by treaty
        ("category.lump_sum", "Page1[0].c1_1[0]", "/7"),                                 # g Lump-sum distributions <- 2023's box a
    ),
    2025: (
        ("category.section_951a", "Page1[0].LineA-B_ReadOrder[0].c1_1[0]", "/1"),        # a Section 951A category income
        ("category.foreign_branch", "Page1[0].LineA-B_ReadOrder[0].c1_1[1]", "/2"),      # b Foreign branch category income
        ("category.passive", "Page1[0].LineC-D_ReadOrder[0].c1_1[0]", "/3"),             # c Passive category income
        ("category.general", "Page1[0].LineC-D_ReadOrder[0].c1_1[1]", "/4"),             # d General category income
        ("category.section_901j", "Page1[0].LineE-F_ReadOrder[0].c1_1[0]", "/5"),        # e Section 901(j) income
        ("category.resourced_by_treaty", "Page1[0].LineE-F_ReadOrder[0].c1_1[1]", "/6"), # f Certain income re-sourced by treaty
        ("category.lump_sum", "Page1[0].c1_1[0]", "/7"),                                 # g Lump-sum distributions <- 2023's box a
    ),
}

_F1116_CREDIT_CLAIMED_BY_YEAR: dict[int, tuple[tuple[str, str, str], ...]] = {
    2023: (
        ("credit_claimed.paid",
         "Page1[0].Part2TableHeader[0].ColumnJ[0].CreditClaimedCheckboxes[0].c1_3[0]", "/Paid"),
        ("credit_claimed.accrued",
         "Page1[0].Part2TableHeader[0].ColumnJ[0].CreditClaimedCheckboxes[0].c1_3[1]", "/Accrued"),
    ),
    # 2024 dropped the CreditClaimedCheckboxes/ColumnJ nesting for a bare
    # Page1[0].ActiveHeaderElements[0]; 2025 then re-nested the SAME wrapper
    # under a new Part2[0]. So the three years have three different paths for
    # one printed pair, and only 2024 and 2025 share the "/1"/"/2" states.
    2024: (
        ("credit_claimed.paid", "Page1[0].ActiveHeaderElements[0].c1_3[0]", "/1"),
        ("credit_claimed.accrued", "Page1[0].ActiveHeaderElements[0].c1_3[1]", "/2"),
    ),
    2025: (
        ("credit_claimed.paid", "Page1[0].Part2[0].ActiveHeaderElements[0].c1_3[0]", "/1"),
        ("credit_claimed.accrued", "Page1[0].Part2[0].ActiveHeaderElements[0].c1_3[1]", "/2"),
    ),
}

# The two INDEPENDENT /Btn boxes (no group), pinned per year because one of the
# two states changed and the other, absurdly, did not. Line 1b's attestation box
# exported "/Yes" in 2023 and exports "/1" from 2024 on; the line-10 "you don't
# need to attach Schedule B" box exports "/Accrued" in ALL THREE years — a DOR
# authoring leftover from the Part II pair that has nothing to do with what the
# box means, and the one /Btn state on this form that has never moved. Guessing
# either one writes nothing and warns about nothing. Both bindings were also
# re-parented into "_ReadOrder" wrappers in 2024 and kept there in 2025.
_F1116_STANDALONE_BOXES_BY_YEAR: dict[int, tuple[tuple[str, str, str], ...]] = {
    2023: (
        ("1b", "Page1[0].Part1Table[0].Line1b[0].Line1BText[0].c1_2[0]", "/Yes"),
        ("10.no_schedule_b", "Page2[0].c2_1[0]", "/Accrued"),
    ),
    2024: (
        ("1b", "Page1[0].Line1b_ReadOrder[0].c1_2[0]", "/1"),
        ("10.no_schedule_b", "Page2[0].Line10_ReadOrder[0].c2_1[0]", "/Accrued"),
    ),
    2025: (
        ("1b", "Page1[0].Line1b_ReadOrder[0].c1_2[0]", "/1"),
        ("10.no_schedule_b", "Page2[0].Line10_ReadOrder[0].c2_1[0]", "/Accrued"),
    ),
}

# Line 1a's printed LABEL column carries three dashed rules for the description
# of the income type ("enter 'Dividends' on the dotted line"). How many WIDGETS
# sit on them is a per-year fact the name diff cannot see: 2023 shipped three
# (f1_7/f1_8/f1_9, one per rule) and 2025 shipped ONE 36-pt Multiline box
# (f1_07, /Ff 8392704) spanning all three. The keys therefore differ by year, and
# the sibling keys must NOT exist in the year that has one box — otherwise
# fill_form silently accepts a line that reaches no widget.
_F1116_INCOME_TYPE_KEYS_BY_YEAR: dict[int, tuple[str, ...]] = {
    2023: ("1a.income_type_1", "1a.income_type_2", "1a.income_type_3"),
    # 2024 still ships THREE 12-pt boxes, one per printed dashed rule
    # (f1_07 [115.2,504,259.2,516], f1_08 [64.8,492,259.2,504],
    # f1_09 [64.8,480,259.2,492]), all /Ff 8388608 with the Multiline bit CLEAR
    # — so the single-box collapse is a 2025 change, not a 2024 one, and this
    # year keeps the base's three keys. Measured on the 2024 blank.
    2024: ("1a.income_type_1", "1a.income_type_2", "1a.income_type_3"),
    2025: ("1a.income_type",),
}

F1116_PACK_PATHS = [path for path in PACK_PATHS if path.parent.name == "f1116"]


def _f1116_year_table(table: dict, pack, what: str):
    """Per-year pin lookup: an unported year FAILS instead of silently passing."""
    assert pack.tax_year in table, (
        f"f1116 {pack.tax_year} has no {what} row. The 2024 revision re-authored every "
        f"AcroForm name and moved three /Btn on-states while KEEPING one name bound to a "
        f"different printed box, so this table is per-year by necessity: dump THIS year's "
        f"blank (/AP /N states, /Rect, /Ff through /Parent), read the printed face at "
        f"200 dpi, and add the row"
    )
    return table[pack.tax_year]


@pytest.mark.parametrize("pack_path", F1116_PACK_PATHS, ids=_pack_id)
def test_f1116_one_of_n_sets_are_grouped_and_exclusive(pack_path: Path, tmp_path: Path):
    """P-008 shape on separate-widget /Btn fields: the group id is the only guard."""
    pack = load_pack(pack_path)
    by_line = {pf.line: pf for pf in pack.fields}
    categories = _f1116_year_table(F1116_CATEGORY_BOXES_BY_YEAR, pack, "category-box")
    credit_claimed = _f1116_year_table(_F1116_CREDIT_CLAIMED_BY_YEAR, pack, "Paid/Accrued")
    standalone = _f1116_year_table(_F1116_STANDALONE_BOXES_BY_YEAR, pack, "standalone-box")

    for line, field, on_state in categories:
        pf = by_line.get(line)
        assert pf is not None, f"{pack.tax_year} f1116 lost category line '{line}'"
        assert pf.field == field, f"{line} binds {pf.field}, expected {field}"
        assert pf.on_state == on_state, (
            f"{line} on_state is {pf.on_state}, expected {on_state} — the a..g order IS the "
            f"on-state order; dump the blank's /AP /N states rather than porting this by name"
        )
        assert pf.group == "category", f"{line} must share group 'category' (P-008)"
    for line, field, on_state in credit_claimed:
        pf = by_line.get(line)
        assert pf is not None and pf.field == field and pf.on_state == on_state, (
            f"{pack.tax_year} f1116 Part II '{line}' mis-mapped: {pf}"
        )
        assert pf.group == "credit_claimed", f"{line} must share group 'credit_claimed' (P-008)"

    # Both sets are printed imperatives, so exactly one member of each carries
    # `required` (f1040's filing_status spelling: the flag on any member makes the
    # whole group required, and the audit then FAILs an unanswered question).
    for group, members in (("category", categories), ("credit_claimed", credit_claimed)):
        required = [line for line, _, _ in members if by_line[line].required]
        assert required == [members[0][0]], (
            f"{pack.tax_year} f1116 group '{group}' should mark exactly its FIRST member required, "
            f"got {required}"
        )

    # The other two /Btn widgets are INDEPENDENT boxes, not options: no group.
    # Their bindings AND their on-states are pinned per year, because 1b's state
    # went "/Yes" -> "/1" in 2024 (and stayed there in 2025) while line 10's
    # stayed the leftover "/Accrued" in all three years even though its FIELD
    # moved into Page2[0].Line10_ReadOrder[0] in 2024.
    for line, field, on_state in standalone:
        pf = by_line.get(line)
        assert pf is not None and pf.type == "checkbox", f"{line} missing"
        assert pf.group is None, (
            f"{line} is a standalone attestation box, not one option of a question — a group id "
            f"here would make it mutually exclusive with something"
        )
        assert pf.field == field and pf.on_state == on_state, (
            f"{pack.tax_year} f1116 '{line}' binds {pf.field} at {pf.on_state}, expected "
            f"{field} at {on_state} — read the state off /AP /N on THIS year's blank; a state "
            f"the widget does not define writes nothing and warns about nothing"
        )

    # The guard is real, not decorative. fill_form checks the blank EXISTS before
    # it validates the group but raises before parsing it, so a stub file is
    # enough (sched_e's P-008 test does the same).
    stub = tmp_path / "unparsed-blank.pdf"
    stub.write_bytes(b"not a pdf")
    for group, a, b in (
        ("category", "category.passive", "category.general"),
        ("credit_claimed", "credit_claimed.paid", "credit_claimed.accrued"),
    ):
        with pytest.raises(ValueError, match=rf"checkbox group '{group}'"):
            fill_form(pack, {a: True, b: True}, stub, tmp_path / "out.pdf")
    # ...and exactly one answer is still accepted (the guard is not over-broad):
    # it gets past the group check and dies on the unparseable stub instead.
    for line in ("category.passive", "category.lump_sum", "credit_claimed.accrued"):
        with pytest.raises(ValueError, match="could not be parsed as a PDF"):
            fill_form(pack, {line: True}, stub, tmp_path / "out.pdf")


@pytest.mark.parametrize("pack_path", F1116_PACK_PATHS, ids=_pack_id)
def test_f1116_column_grid_keys_are_unambiguous_and_complete(pack_path: Path):
    """The column-key convention, and the reason it is not sched_d's `.a`.

    Form 1116 prints sub-line letters (1a/1b, 3a-3g, 4a/4b) AND lettered country
    columns (A/B/C), so the literal house spelling `1a.b` reads exactly like
    printed line `1b`, `4a.b` like `4b` and `3a.c` like `3c`. The pack uses
    `col_a`/`col_b`/`col_c`/`total` instead. This test pins that no bare
    `<line>.<single letter>` column key ever creeps back into Part I, and that
    every column of every gridded row is present — a missing column is how a
    three-column form ships two-thirds filled.
    """
    pack = load_pack(pack_path)
    lines = {pf.line for pf in pack.fields}
    gridded_money = ("1a", "2", "3a", "3b", "3c", "3d", "3e", "3g", "4a", "4b", "5", "6")
    for row in gridded_money + ("i", "3f"):
        for col in ("col_a", "col_b", "col_c"):
            assert f"{row}.{col}" in lines, f"{pack.tax_year} f1116 is missing '{row}.{col}'"
        # The lookalike spelling must not exist.
        for bad in ("a", "b", "c"):
            assert f"{row}.{bad}" not in lines, (
                f"{pack.tax_year} f1116 maps '{row}.{bad}' — a bare column letter collides by eye "
                f"with a printed sub-line letter on this form; use col_a/col_b/col_c"
            )
    # Only three rows have a widget in the printed Total column; the rest of that
    # column is solid grey with NO widget, so those keys must not exist.
    assert {"1a.total", "6.total"} <= lines
    for row in ("i", "2", "3a", "3b", "3c", "3d", "3e", "3f", "3g", "4a", "4b", "5"):
        assert f"{row}.total" not in lines, (
            f"{pack.tax_year} f1116 maps '{row}.total' — that Total cell is shaded and holds no "
            f"widget at all"
        )
    # Part II: three lines x ten printed columns (l)..(u), and (m)-(p) are
    # "In foreign currency" so they are TEXT, not dollars.
    by_line = {pf.line: pf for pf in pack.fields}
    for row in ("line_a", "line_b", "line_c"):
        for col in "lmnopqrstu":
            key = f"{row}.{col}"
            assert key in lines, f"{pack.tax_year} f1116 is missing '{key}'"
            expected = "text" if col in "lmnop" else "money"
            assert by_line[key].type == expected, (
                f"{key} is {by_line[key].type}, expected {expected} — the masthead prints 'Report "
                f"all amounts in U.S. dollars EXCEPT where specified in Part II below', and "
                f"columns (m)-(p) are headed 'In foreign currency' while (l) takes '1099 taxes' "
                f"or '909 taxes' as often as a date"
            )
    # The two ratio lines are text for the same kind of reason (verify compares
    # relation sides in whole dollars, so a 0.8757 would round to 0).
    for key in ("3f.col_a", "3f.col_b", "3f.col_c", "19"):
        assert by_line[key].type == "text", f"{key} is a DECIMAL RATIO, not money"
    # Line 1a's dashed description rules: how many WIDGETS the IRS put on them is
    # a per-year fact (three in 2023 AND 2024, one Multiline box in 2025), and the keys the
    # other year uses must NOT exist here or fill_form accepts a line that
    # reaches no widget.
    expected_income_type = set(
        _f1116_year_table(_F1116_INCOME_TYPE_KEYS_BY_YEAR, pack, "line-1a description")
    )
    every_income_type = {k for keys in _F1116_INCOME_TYPE_KEYS_BY_YEAR.values() for k in keys}
    assert {k for k in lines if k.startswith("1a.income_type")} == expected_income_type, (
        f"{pack.tax_year} f1116 line-1a description keys are "
        f"{sorted(k for k in lines if k.startswith('1a.income_type'))}, expected "
        f"{sorted(expected_income_type)} — count the widgets on the printed dashed rules"
    )
    for stale in sorted(every_income_type - expected_income_type):
        assert stale not in lines, f"{pack.tax_year} f1116 kept another year's key '{stale}'"


@pytest.mark.parametrize("pack_path", F1116_PACK_PATHS, ids=_pack_id)
def test_f1116_credit_lands_on_schedule_3_line_1(pack_path: Path):
    """Printed line 35: "Enter here and on Schedule 3 (Form 1040), line 1"."""
    pack = load_pack(pack_path)
    assert "35 == sched_3.1" in pack.cross_form
    assert pack.signature is None and pack.mailing is None, (
        "Form 1116 is attachment-only ('Attach to Form 1040, 1040-SR, 1040-NR, 1041, or 990-T'): "
        "no signature block of its own, mailed inside the parent return's envelope"
    )


@pytest.mark.network
@pytest.mark.parametrize("pack_path", F1116_PACK_PATHS, ids=_pack_id)
def test_f1116_blank_has_no_readonly_widgets_and_the_states_are_real(pack_path: Path):
    """P-007 and P-008 against the official blank: prove the flags and the states.

    Form 1116 is one of the few packs whose blank carries ZERO ReadOnly widgets,
    so the P-007 adjudication has nothing to allowlist — and that is a fact about
    the blank, not an assumption, so it is asserted here rather than asserted in
    prose. The category and Paid/Accrued sets are also proved to be SEPARATE
    terminal fields (the dangerous topology), since a future revision could
    re-author them as radio kids and silently change what the group id is for.
    """
    from pypdf import PdfReader

    pack = load_pack(pack_path)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")

    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    assert _read_only_widget_names(Path(blank)) == set(), (
        f"f1116 {pack.tax_year}: the blank grew a ReadOnly widget. Render the page, read the "
        f"printed row text and place it in one of P-007's four classes before mapping or "
        f"unmapping it"
    )

    reader = PdfReader(str(blank))
    states: dict[str, set[str]] = {}
    owners: dict[str, str] = {}
    for page in reader.pages:
        for annot_ref in page.get("/Annots") or []:
            annot = annot_ref.get_object()
            parts, node, hops = [], annot, 0
            while node is not None and hops < 32:
                title = node.get("/T")
                if title:
                    parts.append(str(title))
                parent = node.get("/Parent")
                node = parent.get_object() if parent is not None else None
                hops += 1
            name = ".".join(reversed(parts))
            appearance = annot.get("/AP")
            if appearance is not None and appearance.get_object().get("/N") is not None:
                normal = appearance.get_object()["/N"].get_object()
                try:
                    states[name] = {str(k) for k in normal.keys()} - {"/Off"}
                except AttributeError:
                    continue
            owners[name] = "terminal" if annot.get("/T") is not None else "kid"

    pinned = (
        _f1116_year_table(F1116_CATEGORY_BOXES_BY_YEAR, pack, "category-box")
        + _f1116_year_table(_F1116_CREDIT_CLAIMED_BY_YEAR, pack, "Paid/Accrued")
        + _f1116_year_table(_F1116_STANDALONE_BOXES_BY_YEAR, pack, "standalone-box")
    )
    for line, field, on_state in pinned:
        full = prefix + field
        assert states.get(full) == {on_state}, (
            f"f1116 {pack.tax_year} line '{line}': widget {full} exports {states.get(full)}, "
            f"the pack claims {on_state}"
        )
        assert owners.get(full) == "terminal", (
            f"f1116 {pack.tax_year} line '{line}': {full} is no longer its own terminal field — "
            f"if the IRS re-authored the set as radio kids of one field, the group id now means "
            f"something different and CONVENTIONS.md's two topologies must be re-read"
        )
    # Every mapped widget must still exist on the blank, all 1:1.
    mapped = {prefix + pf.field for pf in pack.fields}
    assert len(mapped) == len(pack.fields), "two lines bind one widget"
    assert mapped <= set(owners), (
        f"f1116 {pack.tax_year} binds widget(s) the blank does not have: "
        f"{sorted(mapped - set(owners))}"
    )
    assert len(owners) == len(mapped), (
        f"f1116 {pack.tax_year}: the blank has {len(owners)} widgets and the pack maps "
        f"{len(mapped)} — a new revision added or dropped a box; re-introspect and re-audit"
    )


# ---------------------------------------------------------------------------
# Form 8833 — the two decisions this pack's adversarial audit turned on
# ---------------------------------------------------------------------------
#
# Form 8833 (Rev. 12-2022) prints FIVE checkboxes, and they fall into the two
# topologies CONVENTIONS.md says are "not equally dangerous" — in OPPOSITE
# directions, which is why both halves are pinned here rather than argued in the
# pack banner:
#
#   * line 5 Yes/No — `c1_4[0]` and `c1_4[1]` are two DIFFERENT terminal fields
#     (the `[0]`/`[1]` index is part of /T, not a kid index), so nothing in the
#     PDF makes them exclusive and the `group` id is the ONLY thing standing
#     between a caller and a return that answers one question both Yes and No.
#     That is the P-008 / WV it140 shape verbatim, and it gets no exemption.
#   * the two bullet boxes — `c1_1[0]` (section 6114) and `c1_2[0]`
#     (301.7701(b)-7 dual resident) must NOT share a group, because the printed
#     face says "Check one or both of the following boxes as applicable" and
#     verify.checkbox_audit FAILs any group, required or not, with MORE than one
#     member checked. Grouping them would reject the legitimate filing of a
#     dual-resident taxpayer who is also disclosing under section 6114 — the
#     exact both-boxes case the form invites. A later "tidy-up" that adds the
#     group would look like an improvement and break a real return, so the
#     absence of the group is asserted, not merely commented.
#
# Sources for every printed quotation below: Form 8833 (Rev. 12-2022) page 1,
# rendered at 200 dpi and read (https://www.irs.gov/pub/irs-pdf/f8833.pdf).

F8833_PACK_PATHS = [path for path in PACK_PATHS if path.parent.name == "f8833"]

# line -> (field, on_state, group, required). Dumped from the blank's /AP /N
# appearance states and tied to the printed label by /Rect, never guessed.
F8833_CHECKBOXES: dict[str, tuple[str, str, str | None, bool]] = {
    "disclosure.section_6114": ("Page1[0].BulletedList1[0].Bullet1[0].c1_1[0]", "/1", None, False),
    "disclosure.dual_resident": ("Page1[0].BulletedList1[0].Bullet2[0].c1_2[0]", "/1", None, False),
    "us_person": ("Page1[0].c1_3[0]", "/1", None, False),
    "5.yes": ("Page1[0].c1_4[0]", "/1", "line5", True),
    "5.no": ("Page1[0].c1_4[1]", "/2", "line5", False),
}

# The line-6 explanation area, which a field-name dump ("f1_12 ... f1_36") makes
# look like one big multiline box and is not: `6` is the SHORT tail of the third
# printed instruction row and `6.cont01`..`6.cont24` are the 24 full-width dashed
# rules under it. line -> (field, widget width in PDF points).
F8833_LINE6_GEOMETRY: tuple[tuple[str, str, float], ...] = (
    ("6", "Page1[0].f1_12[0]", 252.0),
) + tuple(
    (f"6.cont{n:02d}", f"Page1[0].f1_{12 + n}[0]", 511.2) for n in range(1, 25)
)


@pytest.mark.parametrize("pack_path", F8833_PACK_PATHS, ids=_pack_id)
def test_f8833_line5_is_grouped_while_the_two_bullets_are_deliberately_not(
    pack_path: Path, tmp_path: Path
):
    """P-003 and P-008 on Form 8833: one exclusive question, three independent boxes."""
    pack = load_pack(pack_path)
    by_line = {pf.line: pf for pf in pack.fields}

    # fill_form checks the blank exists before it validates the group, and raises
    # before parsing, so an unparseable stub is enough to reach both verdicts
    # offline (same trick as the Schedule E group test).
    stub = tmp_path / "unparsed-blank.pdf"
    stub.write_bytes(b"not a pdf")

    for line, (field, on_state, group, required) in F8833_CHECKBOXES.items():
        pf = by_line.get(line)
        assert pf is not None, f"f8833 {pack.tax_year} lost checkbox line '{line}'"
        assert pf.type == "checkbox", f"f8833 {pack.tax_year} '{line}' is {pf.type}, not a checkbox"
        assert pf.field == field, (
            f"f8833 {pack.tax_year} '{line}' binds {pf.field}, expected {field} — re-dump the "
            f"blank's /AP /N states and /Rect positions before trusting this map"
        )
        assert pf.on_state == on_state, (
            f"f8833 {pack.tax_year} '{line}' on_state is {pf.on_state!r}, expected {on_state!r}"
        )
        assert pf.group == group, (
            f"f8833 {pack.tax_year} '{line}' group is {pf.group!r}, expected {group!r}. The two "
            f"bullets and the U.S.-person box are INDEPENDENT questions: page 1 prints 'Check one "
            f"or both of the following boxes as applicable', and verify.checkbox_audit FAILs any "
            f"group with more than one member checked — grouping them would reject a "
            f"dual-resident taxpayer who is also disclosing under section 6114"
        )
        assert bool(pf.required) == required, (
            f"f8833 {pack.tax_year} '{line}' required is {pf.required!r}, expected {required}. "
            f"Only line 5 is asked of every filer (the face prints a dot leader to it); a "
            f"required flag on either bullet would false-FAIL whichever population the other "
            f"bullet covers"
        )

    # The two Yes/No widgets are SEPARATE fields — the topology that makes the
    # group id load-bearing rather than decorative.
    assert by_line["5.yes"].field != by_line["5.no"].field, (
        f"f8833 {pack.tax_year}: line 5 Yes/No now shares one AcroForm field. A shared field "
        f"holds a single /V and cannot store a double answer, so the exclusivity story changes "
        f"— re-read CONVENTIONS.md's two topologies before relying on the group id"
    )

    # The guard, proved by execution: Yes AND No is a hard error...
    with pytest.raises(ValueError, match="checkbox group 'line5'"):
        fill_form(pack, {"5.yes": True, "5.no": True}, stub, tmp_path / "out.pdf")
    # ...while either answer alone is accepted (it reaches the PDF parse and
    # fails there, which is as far as an unparseable stub can go).
    for line in ("5.yes", "5.no"):
        with pytest.raises(ValueError, match="could not be parsed as a PDF"):
            fill_form(pack, {line: True}, stub, tmp_path / "out.pdf")
    # ...and BOTH bullets together is NOT an error: that is the printed
    # "one or both" case, and the whole reason they carry no group.
    with pytest.raises(ValueError, match="could not be parsed as a PDF"):
        fill_form(
            pack,
            {"disclosure.section_6114": True, "disclosure.dual_resident": True},
            stub,
            tmp_path / "out.pdf",
        )


@pytest.mark.network
@pytest.mark.parametrize("pack_path", F8833_PACK_PATHS, ids=_pack_id)
def test_f8833_blank_is_the_rev_12_2022_layout_it_was_mapped_against(pack_path: Path):
    """Against the official blank: no ReadOnly widgets, and line 6 is 25 boxes not one.

    Form 8833 is revision-dated, so all three filing-year packs pin the SAME
    Rev. 12-2022 file and a silent IRS revision would move every one of them at
    once. These are the facts the map rests on, asserted rather than remembered:

    * ZERO ReadOnly widgets, so P-007's four classes are all vacuous here and
      test_readonly_widget_mapping.py needs no allowlist row for this pack. If
      the blank grows one, read the printed row text and place it in a class
      before mapping or unmapping the widget.
    * 41 terminal widgets, all on page 1, mapped 1:1 by 41 lines. Pages 3-5 are
      the instructions and page 2 prints "[This page left blank intentionally]";
      none of the four carries a widget.
    * /MaxLen on exactly ONE widget (the TIN box, 11 — wide enough for a dashed
      SSN or ITIN, and NOT a comb: bit 25 is clear, so no ssn_digits_only).
    * The line-6 block is 25 single-line DoNotScroll boxes whose WIDTHS are what
      the pack's "split the explanation, ~110 characters per row" advice rests
      on. An over-long row is CLIPPED, not wrapped, and no /MaxLen catches it.
    """
    from pypdf import PdfReader

    pack = load_pack(pack_path)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")

    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    assert _read_only_widget_names(Path(blank)) == set(), (
        f"f8833 {pack.tax_year}: the blank grew a ReadOnly widget. Render page 1, read the "
        f"printed row text and place it in one of P-007's four classes before mapping or "
        f"unmapping it — 'ReadOnly means unfillable' is the premise P-007 overturned"
    )

    def inherited(node, key):
        hops = 0
        while node is not None and hops < 64:
            if key in node:
                return node[key]
            parent = node.get("/Parent")
            node = parent.get_object() if parent is not None else None
            hops += 1
        return None

    reader = PdfReader(str(blank))
    widgets: dict[str, dict] = {}
    for page_number, page in enumerate(reader.pages, start=1):
        for annot_ref in page.get("/Annots") or []:
            annot = annot_ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            parts, node, hops = [], annot, 0
            while node is not None and hops < 64:
                title = node.get("/T")
                if title:
                    parts.append(str(title))
                parent = node.get("/Parent")
                node = parent.get_object() if parent is not None else None
                hops += 1
            rect = [float(v) for v in annot["/Rect"]]
            appearance = annot.get("/AP")
            states: set[str] = set()
            if appearance is not None and appearance.get_object().get("/N") is not None:
                normal = appearance.get_object()["/N"].get_object()
                try:
                    states = {str(key) for key in normal.keys()} - {"/Off"}
                except AttributeError:
                    states = set()
            widgets[".".join(reversed(parts))] = {
                "page": page_number,
                "width": round(rect[2] - rect[0], 1),
                "maxlen": inherited(annot, "/MaxLen"),
                "flags": int(inherited(annot, "/Ff") or 0),
                "states": states,
                "terminal": annot.get("/T") is not None,
            }

    mapped = {prefix + pf.field for pf in pack.fields}
    assert len(mapped) == len(pack.fields), f"f8833 {pack.tax_year}: two lines bind one widget"
    assert mapped == set(widgets), (
        f"f8833 {pack.tax_year}: the pack and the blank disagree on the widget set. Only in the "
        f"pack: {sorted(mapped - set(widgets))}; only on the blank: "
        f"{sorted(set(widgets) - mapped)} — re-introspect and re-audit"
    )
    assert len(widgets) == 41, (
        f"f8833 {pack.tax_year}: the blank now has {len(widgets)} widgets, not the 41 this map "
        f"was audited against — the IRS revised the form; re-read page 1 at 200 dpi"
    )
    assert {info["page"] for info in widgets.values()} == {1}, (
        f"f8833 {pack.tax_year}: a widget left page 1. Pages 3-5 are the instructions and page 2 "
        f"prints '[This page left blank intentionally]' — a widget elsewhere means a new layout"
    )

    # /MaxLen: exactly one widget carries it, and it is the TIN box.
    with_maxlen = {name: info["maxlen"] for name, info in widgets.items() if info["maxlen"]}
    assert with_maxlen == {prefix + "Page1[0].f1_2[0]": 11}, (
        f"f8833 {pack.tax_year}: /MaxLen widgets are {with_maxlen}, expected only the "
        f"'U.S. taxpayer identifying number' box at 11"
    )
    assert not int(widgets[prefix + "Page1[0].f1_2[0]"]["flags"]) & (1 << 24), (
        f"f8833 {pack.tax_year}: the TIN box became a comb field — it now needs "
        f"comb/format: ssn_digits_only (P-001), which the pack deliberately omits today"
    )

    for line, (field, on_state, _group, _required) in F8833_CHECKBOXES.items():
        info = widgets[prefix + field]
        assert info["states"] == {on_state}, (
            f"f8833 {pack.tax_year} '{line}': widget {field} exports {sorted(info['states'])}, "
            f"the pack claims {on_state}"
        )
        assert info["terminal"], (
            f"f8833 {pack.tax_year} '{line}': {field} is no longer its own terminal field. If "
            f"the IRS re-authored these as radio kids of one field, the group id means something "
            f"different and CONVENTIONS.md's two topologies must be re-read"
        )

    # Line 6's geometry — the fact a field-name dump hides.
    for line, field, width in F8833_LINE6_GEOMETRY:
        info = widgets[prefix + field]
        assert info["width"] == width, (
            f"f8833 {pack.tax_year} '{line}': widget {field} is {info['width']}pt wide, not "
            f"{width}pt. The pack's per-row character advice is derived from this width; "
            f"re-measure before changing it"
        )
        assert int(info["flags"]) & (1 << 23) and not int(info["flags"]) & (1 << 12), (
            f"f8833 {pack.tax_year} '{line}': {field} is no longer a single-line DoNotScroll box "
            f"(/Ff {info['flags']}). If it became multiline the explanation no longer needs "
            f"splitting across 25 rows"
        )
    # ...and the three boxes that ARE multiline stayed that way.
    for field in ("Page1[0].f1_4[0]", "Page1[0].f1_5[0]", "Page1[0].f1_9[0]"):
        assert int(widgets[prefix + field]["flags"]) & (1 << 12), (
            f"f8833 {pack.tax_year}: {field} lost its Multiline bit — a viewer will no longer "
            f"wrap the address/payor block, so the value must now be split or shortened"
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
