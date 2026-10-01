"""Repo-wide pack invariants — the gates that used to be federal-only.

Two invariants in ``test_formpacks_federal.py`` were parametrized over
``PACK_PATHS = formpacks/federal/*/*/pack.yaml``, so **no state pack was ever
checked by either one**, and three real defects shipped past CI because of it:

1. **cross_form targets never resolved for state packs.** ``or/2025/or40``,
   ``ny/2025/it201`` and ``ny/2025/it203`` all cited ``f1040.11`` after the
   TY2025 Form 1040 split that line into ``11a`` (AGI) and ``11b`` (the page-2
   restatement). Three dangling references, in three packs, invisible.
2. **the checkbox-group invariant never ran over state packs.** ``nc/*/d400``
   shipped seven printed "fill in one circle only" sets with ZERO ``group:``
   ids, and ``nj/2024/nj1040`` shipped thirteen. ``formpacks/CONVENTIONS.md``
   called the rule "harness enforced" the whole time; for 57 state packs it
   was not.
3. and the yes/no half of that invariant only recognised the DOTTED option
   spelling (``a.yes``), while 22 state packs spell options with ``::`` and
   the three ``ny/*/it203`` packs spell them with ``_``. Even widening the
   glob alone would have left those pairs invisible.

So this file sweeps **every** discovered pack, federal and state (172 today),
in the same way ``test_readonly_widget_mapping.py`` does. The helpers it needs
stay in ``test_formpacks_federal.py``; the invariants themselves live here
because they are repo-wide, and a federal-named module reporting a Wisconsin
failure is how a gate gets ignored.

**The two checkbox topologies are not equally dangerous, and the tests treat
them differently on purpose.**

- *N options on ONE AcroForm field* (a real radio group). The PDF itself holds
  a single ``/V``, so two "yes" answers cannot coexist in the file, and
  ``fill_form`` refuses the request before it opens the blank. A missing
  ``group:`` here is a CONVENTION gap, not a filable-wrong-return defect. 21
  state packs have it; they are listed in
  ``SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID`` with their counts pinned, and
  ``test_shared_field_debt_is_covered_by_fill_forms_same_field_guard`` proves
  the substitute mechanism actually fires for all 120 of those option sets —
  the row is an adjudication backed by execution, not a waiver.
- *options on SEPARATE single-widget ``/Btn`` fields*. Nothing in the PDF makes
  those exclusive and nothing in the engine can infer it, so the ``group:`` id
  is the ONLY thing standing between a caller and a return that answers one
  question both Yes and No. This shape gets no pack-level exemption: the only
  entries are ``KNOWN_UNGROUPED_YESNO_PAIRS``, per (year, form, stem), each
  self-clearing.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import pytest

from taxfill_core.filler import fill_form
from taxfill_core.schemas.formpack import FormPack, PackField, load_pack

from test_formpacks_federal import KNOWN_FORM_KEYS, LINE_ID_RE

REPO_ROOT = Path(__file__).resolve().parents[3]
FORMPACKS = REPO_ROOT / "formpacks"
FEDERAL_PACK_PATHS = sorted((FORMPACKS / "federal").glob("*/*/pack.yaml"))
STATE_PACK_PATHS = sorted((FORMPACKS / "states").glob("*/*/*/pack.yaml"))
ALL_PACK_PATHS = FEDERAL_PACK_PATHS + STATE_PACK_PATHS


@lru_cache(maxsize=None)
def _load(pack_path: Path) -> FormPack:
    """Memoized load_pack.

    Every parametrized case here needs the WHOLE repo's line index to resolve a
    cross_form target, so an uncached helper re-parses every pack once per rule. The
    tests are read-only, so one parse per pack per session is sound.
    """
    return load_pack(pack_path)


def _pack_key(pack_path: Path) -> str:
    """Pack identity shared with test_readonly_widget_mapping and the fixtures."""
    return str(pack_path.relative_to(FORMPACKS))


def _pack_id(pack_path: Path) -> str:
    return _pack_key(pack_path).removesuffix("/pack.yaml").replace("/", "-")


# ---------------------------------------------------------------------------
# cross_form: every target must be a real line of a real pack
# ---------------------------------------------------------------------------

# (tax_year, form_key, target_line) triples a cross_form rule may legitimately
# reference even though no in-scope pack provides them YET. Every row is
# checked for staleness by test_cross_form_allowlist_rows_are_all_still_needed,
# so a row cannot outlive the gap it documents.
#
# The 2024 f1040nr rows that used to sit here ("the 2024 scope ships f1040 but
# no f1040nr pack") were DELETED on 2026-08-21: formpacks/federal/2024/f1040nr
# now exists and keys both "20" and "31", so Schedule 3's f1040nr legs resolve
# directly and the rows were suppressing a check that passes on its own.
CROSS_FORM_TARGET_ALLOWLIST: frozenset[tuple[int, str, str]] = frozenset(
    {
        # The 2022 1040-NR keeps its Schedule 2/3 cross_form rules so the verifier
        # can emit its runtime "attach Schedule 2/3 and re-verify" caution when a
        # back-filer puts a nonzero amount on lines 17/20/23b/31, but the M2 2022
        # scope (dev plan section 15) ships no 2022 sched_2/sched_3 pack, so those
        # targets cannot resolve yet. Remove once 2022 sched_2/sched_3 ship.
        (2022, "sched_2", "3"),
        (2022, "sched_2", "21"),
        (2022, "sched_3", "8"),
        (2022, "sched_3", "15"),
        # The 2026 1040-NR draft prints line 1k "Total income exempt by a treaty
        # from Schedule OI (Form 1040-NR), item L, line 1(e)", but no 2026
        # Schedule OI draft has posted (JT5g). Remove when the 2026 sched_oi ships.
        (2026, "sched_oi", "1e"),
    }
)


def _cross_form_target_keys() -> frozenset[str]:
    """Form keys a cross_form ref may name: the federal list + every state dir.

    ``KNOWN_FORM_KEYS`` is the federal DIRECTORY whitelist and stays that way —
    it is what pins ``formpacks/federal/<year>/<form_key>/`` to a known form.
    But a cross_form ref is a different question: with state packs in scope a
    ref could legitimately name a state form (no pack does today; every state
    leg targets f1040 or f1040nr), and hardcoding the federal list would make
    the first state-to-state reference fail for the wrong reason.
    """
    return frozenset(KNOWN_FORM_KEYS | {path.parent.name for path in ALL_PACK_PATHS})


@lru_cache(maxsize=1)
def _lines_by_year_and_form() -> dict[tuple[int, str], set[str]]:
    """Map (tax_year, form_key) -> line ids, over EVERY discovered pack.

    form_key is the pack DIRECTORY name, which is what cross_form refs and
    FilingItem keys use. Safe as a flat map because
    test_pack_year_and_form_key_pairs_are_unique_across_the_repo proves the key
    is collision-free across federal and state packs alike. Cached and treated
    as read-only by every caller.
    """
    by_key: dict[tuple[int, str], set[str]] = {}
    for path in ALL_PACK_PATHS:
        loaded = _load(path)
        by_key[(loaded.tax_year, path.parent.name)] = {pf.line for pf in loaded.fields}
    return by_key


def test_pack_year_and_form_key_pairs_are_unique_across_the_repo():
    """The precondition for one flat (year, form_key) -> lines map.

    Sharing ``_lines_by_year_and_form`` between federal and state packs is only
    sound while no two packs of the same year use the same directory name. If a
    state ever ships a directory called ``f1040`` — or two states pick the same
    form name in one year — the map would silently resolve one pack's
    cross_form ref against the OTHER pack's lines, which is worse than the
    dangling reference this file exists to catch.
    """
    seen: dict[tuple[int, str], str] = {}
    collisions: list[str] = []
    for path in ALL_PACK_PATHS:
        key = (_load(path).tax_year, path.parent.name)
        if key in seen:
            collisions.append(f"{key} claimed by BOTH {seen[key]} and {_pack_key(path)}")
        seen[key] = _pack_key(path)
    assert not collisions, (
        "cross_form resolution keys off (tax_year, pack directory name), and these "
        "collide:\n  " + "\n  ".join(collisions) + "\nDisambiguate the directory names, "
        "or teach _lines_by_year_and_form to key off the jurisdiction too — do NOT leave "
        "it resolving refs against the wrong pack"
    )


@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_pack_cross_form_targets_resolve_to_an_existing_pack_line(pack_path: Path):
    """Every cross_form ref names a line that really exists — repo-wide.

    Federal-only until 2026-08-21, which is why three TY2025 state packs could
    cite the renumbered ``f1040.11`` and stay green.
    """
    pack = _load(pack_path)
    lines_by_key = _lines_by_year_and_form()
    known_keys = _cross_form_target_keys()
    local_lines = {pf.line for pf in pack.fields}
    for rule in pack.cross_form:
        sides = [side.strip() for side in rule.split("==")]
        assert len(sides) == 2 and all(sides), (
            f"{_pack_key(pack_path)}: cross_form rule {rule!r} must be "
            f"'<ref> == <ref>' with exactly one '=='"
        )
        for side in sides:
            if "." in side:
                form_key, _, target = side.partition(".")
                assert form_key in known_keys, (
                    f"{_pack_key(pack_path)}: cross_form rule {rule!r} names form key "
                    f"'{form_key}', which is neither a known federal form key nor any "
                    f"discovered pack directory — refs are '<form_key>.<line>'"
                )
                assert LINE_ID_RE.fullmatch(target), (
                    f"{_pack_key(pack_path)}: cross_form rule {rule!r} target line "
                    f"'{target}' violates the line-id grammar"
                )
                if (pack.tax_year, form_key, target) in CROSS_FORM_TARGET_ALLOWLIST:
                    continue  # out-of-scope-for-now target, explicitly allowed
                target_lines = lines_by_key.get((pack.tax_year, form_key))
                assert target_lines is not None, (
                    f"{_pack_key(pack_path)}: cross_form rule {rule!r} has no pack "
                    f"'{form_key}' for tax_year {pack.tax_year} — add the target pack, "
                    f"remove the rule, or allowlist ({pack.tax_year}, {form_key!r}, "
                    f"{target!r}) in CROSS_FORM_TARGET_ALLOWLIST with a reason"
                )
                assert target in target_lines, (
                    f"{_pack_key(pack_path)}: cross_form rule {rule!r} points at line "
                    f"'{target}', which pack '{form_key}' ({pack.tax_year}) does not have. "
                    f"Its nearest keys are "
                    f"{sorted(x for x in target_lines if x.startswith(target[:2]))[:8]}.\n"
                    f"A cross_form target is a (form_key, LINE KEY OF THAT YEAR'S PACK) "
                    f"pair, never a line number remembered from a prior year: TY2025 split "
                    f"Form 1040 line 11 into 11a (AGI) and 11b (the page-2 restatement), "
                    f"and three state packs kept citing '11'. Point at the DEFINING line, "
                    f"not the restatement, and re-point per year — the 2023/2024 state legs "
                    f"citing f1040.11 are correct for their own years and must not be "
                    f"'harmonised'"
                )
            else:
                assert side in local_lines, (
                    f"{_pack_key(pack_path)}: cross_form rule {rule!r} local ref '{side}' "
                    f"is not a line of this pack — fix the ref or add the line to fields[]"
                )


def test_cross_form_allowlist_rows_are_all_still_needed():
    """A suppression may not outlive the gap it documents.

    Two rows in this allowlist ((2024, f1040nr, 20) and (2024, f1040nr, 31))
    went stale when the 2024 f1040nr pack shipped, and nothing noticed for
    months: they kept suppressing a check that would have passed unaided. This
    test makes that impossible — a row survives only while its target really
    cannot be resolved.
    """
    lines_by_key = _lines_by_year_and_form()
    stale: list[str] = []
    for year, form_key, target in sorted(CROSS_FORM_TARGET_ALLOWLIST):
        target_lines = lines_by_key.get((year, form_key))
        if target_lines is not None and target in target_lines:
            stale.append(f"({year}, {form_key!r}, {target!r})")
    assert not stale, (
        "CROSS_FORM_TARGET_ALLOWLIST row(s) " + ", ".join(stale) + " now resolve on "
        "their own — the pack they were waiting for has shipped. DELETE them: a stale "
        "allowlist row is a live check that has been quietly switched off"
    )


def test_cross_form_allowlist_rows_name_a_plausible_target():
    """The allowlist may only excuse a MISSING pack, never a wrong line id."""
    known_keys = _cross_form_target_keys()
    for year, form_key, target in sorted(CROSS_FORM_TARGET_ALLOWLIST):
        assert form_key in known_keys, (
            f"allowlist row ({year}, {form_key!r}, {target!r}) names an unknown form key"
        )
        assert LINE_ID_RE.fullmatch(target), (
            f"allowlist row ({year}, {form_key!r}, {target!r}) target violates the "
            f"line-id grammar — the allowlist excuses a missing PACK, not a bad line id"
        )


def test_no_pack_cites_a_federal_line_that_year_renumbered_away():
    """The exact shape that shipped three times: a bare ``f1040.11`` in TY2025.

    Cheap, specific, and aimed at the regression rather than the class: TY2025
    Form 1040 has 11a/11b and no "11" at all, so any ``f1040.11`` reference in a
    TY2025 pack is a leftover from the 2023/2024 face. The general check above
    catches it too; this one names it, so the failure explains itself.
    """
    # TY2026 (the draft, Phase J JT3a): line 24 split into 24a/24b/24c and line 32
    # into 32a/32b/32c, so neither bare number exists on the 2026 face.
    renumbered = {(2025, "f1040", "11"), (2026, "f1040", "24"), (2026, "f1040", "32")}
    offenders: list[str] = []
    for path in ALL_PACK_PATHS:
        pack = _load(path)
        for rule in pack.cross_form:
            for side in (side.strip() for side in rule.split("==")):
                form_key, dot, target = side.partition(".")
                if dot and (pack.tax_year, form_key, target) in renumbered:
                    offenders.append(f"{_pack_key(path)}: {rule!r}")
    assert not offenders, (
        "pack(s) cite a federal line their target year renumbered:\n  "
        + "\n  ".join(offenders)
        + "\nTY2025 Form 1040 prints '11a Subtract line 10 from line 9. This is your "
        "adjusted gross income' and '11b Amount from line 11a', and the pack keys 11a/11b "
        "with no '11'. A state line that means FAGI must target 11a, the DEFINING line"
    )


# ---------------------------------------------------------------------------
# Checkbox groups, topology 1 — N options sharing ONE AcroForm field
# ---------------------------------------------------------------------------


class SharedFieldDebt(NamedTuple):
    """One pack that omits ``group:`` on option sets sharing one /Btn field."""

    pack: str  # path relative to formpacks/
    sets: int  # how many shared AcroForm fields carry >1 option line and NO one group id
    why: str


# These 21 state packs map N option lines onto ONE AcroForm field without a
# ``group:`` id. That is a CONVENTION gap rather than a filable-wrong-return
# defect, and the distinction is load-bearing: the PDF field holds a single
# ``/V``, so the contradictory state cannot exist in the file, and fill_form's
# same-field guard refuses the request before it opens the blank ("... both turn
# on AcroForm field 'X' — these are options of ONE radio/choice group"). That
# guard is proved to fire for every one of the 120 sets below by
# test_shared_field_debt_is_covered_by_fill_forms_same_field_guard, so these
# rows are backed by execution rather than by argument.
#
# What the missing id DOES cost, and why the debt is recorded instead of
# ignored: verify's checkbox_audit builds its groups from ``group:``/``required:``
# alone (verify.py checkbox_audit), never from widget topology, so an ungrouped
# set emits ZERO read-side checks — nothing confirms a required question was
# answered, and nothing catches a contradictory PDF that some other tool wrote.
# The house convention (vt/in111, nc/d400, ar/ar1000f, sched_e) is to declare
# the id anyway. Each row is self-clearing: give the pack its ids and the count
# no longer matches, which forces the row out.
#
# Counts measured 2026-08-21 with the metric this test uses: shared AcroForm
# fields carrying >1 checkbox line whose members do not all share one non-None
# group id. NOT the number of option LINES (120 sets, 321 option lines).
SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID: tuple[SharedFieldDebt, ...] = (
    SharedFieldDebt(
        "states/co/2023/dr0104/pack.yaml",
        2,
        "the direct-deposit account type (checking/savings/CollegeInvest) and the "
        "third-party-designee Yes/No, each N options on one /Btn",
    ),
    SharedFieldDebt(
        "states/il/2023/il1040/pack.yaml",
        4,
        "filing status (5 options on 'Filing status'), step-1 residency, and the "
        "line-38 refund-method election",
    ),
    SharedFieldDebt(
        "states/il/2024/il1040/pack.yaml",
        4,
        "the 2023 IL-1040 set, ported unchanged — filing status (5 options on "
        "'Filing status'), step-1 residency, and the refund-method election "
        "(printed line 39 on the 2024 face, 38 on 2023); all four re-measured "
        "as N-options-on-ONE-/Btn against the 2024 blank",
    ),
    # states/ky/2023/form740 row (5 sets) retired 2026-09-28 (Phase J JS3b): the
    # 2023 base and its 2024 / 2025 ports all carry the five group ids.
    SharedFieldDebt(
        "states/mi/2023/mi1040/pack.yaml",
        2,
        "the line-7 filing status and the direct-deposit account type",
    ),
    SharedFieldDebt(
        "states/mo/2023/mo1040/pack.yaml",
        1,
        "the two 'CalcOption' UI options, which share one /Btn field",
    ),
    SharedFieldDebt(
        "states/mo/2024/mo1040/pack.yaml",
        1,
        "the 2023 row's two 'CalcOption' UI options sharing one /Btn field, "
        "verified unchanged on the 2024 blank (one field, two page-1 widgets, "
        "/AP states /X and /N)",
    ),
    # states/nj/2023/nj1040 row (13 sets) retired 2026-08-24: the 2023 base got
    # the same 38 group ids as its 2024 sibling and now has 0 ungrouped sets.
    SharedFieldDebt(
        "states/ny/2023/it201/pack.yaml",
        11,
        "filing status, the B/C/D1/D2/D4/E1 Yes/No questions, the line-34 deduction "
        "election, the line-78 refund method, the line-83a account type and the "
        "third-party designee — all '::'-spelled options on shared /Btn fields",
    ),
    SharedFieldDebt(
        "states/ny/2023/it203/pack.yaml",
        12,
        "the IT-203 counterpart of the IT-201 set, spelled with '_' instead of '::' "
        "(B_itemized_federal_yes/_no), plus the G last-day and H quarters questions",
    ),
    SharedFieldDebt(
        "states/ny/2024/it201/pack.yaml", 11, "the 2023 IT-201 set, ported unchanged"
    ),
    SharedFieldDebt(
        "states/ny/2024/it203/pack.yaml", 12, "the 2023 IT-203 set, ported unchanged"
    ),
    SharedFieldDebt(
        "states/ny/2025/it201/pack.yaml", 11, "the 2023 IT-201 set, ported unchanged"
    ),
    SharedFieldDebt(
        "states/ny/2025/it203/pack.yaml", 12, "the 2023 IT-203 set, ported unchanged"
    ),
    SharedFieldDebt(
        "states/oh/2023/it1040_oh/pack.yaml",
        3,
        "CHK_PRIM_RES and CHK_SP_RES (resident/part-year/nonresident) and "
        "CHK_FILING_STATUS (single-HOH-QSS / MFJ / MFS), three options per /Btn",
    ),
    SharedFieldDebt(
        "states/oh/2024/it1040_oh/pack.yaml",
        3,
        "the same three Ohio radio fields as 2023, ported unchanged",
    ),
    SharedFieldDebt(
        "states/pa/2023/pa40/pack.yaml",
        3,
        "residency status, filing status and the tax-forgiveness marital status",
    ),
    SharedFieldDebt(
        "states/pa/2024/pa40/pack.yaml", 3, "the 2023 PA-40 set, ported unchanged"
    ),
    SharedFieldDebt(
        "states/pa/2025/pa40/pack.yaml", 3, "the 2023 PA-40 set, ported unchanged"
    ),
    SharedFieldDebt(
        "states/va/2023/va760/pack.yaml",
        1,
        "the direct-deposit 'Account Type' checking/savings pair",
    ),
    SharedFieldDebt(
        "states/va/2024/va760/pack.yaml",
        1,
        "the same Form 760 account-type pair as 2023, ported unchanged",
    ),
    SharedFieldDebt(
        "states/wi/2023/wi_form1/pack.yaml",
        3,
        "filing status (5 options on 'status'), the city/village/town tax district and "
        "the third-party-designee Yes/No",
    ),
)


def _shared_field_debt() -> dict[str, SharedFieldDebt]:
    return {row.pack: row for row in SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID}


def _shared_field_option_sets(pack: FormPack) -> dict[str, list[PackField]]:
    """Checkbox lines grouped by the AcroForm field they share, sets of 2+."""
    by_field: dict[str, list[PackField]] = {}
    for pack_field in pack.fields:
        if pack_field.type == "checkbox":
            by_field.setdefault(pack_field.field, []).append(pack_field)
    return {field: members for field, members in by_field.items() if len(members) > 1}


def _ungrouped_shared_field_sets(pack: FormPack) -> dict[str, list[PackField]]:
    out: dict[str, list[PackField]] = {}
    for field, members in _shared_field_option_sets(pack).items():
        groups = {member.group for member in members}
        if None in groups or len(groups) != 1:
            out[field] = members
    return out


@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_pack_radio_options_share_one_group_and_distinct_states(pack_path: Path):
    """Options on one /Btn share one group id and never reuse an on_state.

    Federal-only until 2026-08-21. The on_state half has NO exemption in either
    lane — a reused appearance state means two option lines write the SAME box,
    so one of them is simply mis-mapped, and the repo has zero instances.
    """
    pack = _load(pack_path)
    key = _pack_key(pack_path)
    debt = _shared_field_debt().get(key)

    for field, members in _shared_field_option_sets(pack).items():
        states = [pf.on_state for pf in members]
        assert len(set(states)) == len(states), (
            f"{key}: radio options on field '{field}' reuse an on_state ({states}) — each "
            f"option needs its own state; dump the blank PDF's appearance states. Two "
            f"lines sharing one state are not a group, they are a mis-mapping"
        )

    ungrouped = _ungrouped_shared_field_sets(pack)
    if debt is not None:
        assert len(ungrouped) == debt.sets, (
            f"{key} has {len(ungrouped)} ungrouped shared-field option set(s); "
            f"SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID pins {debt.sets}.\n"
            f"currently ungrouped: {sorted(ungrouped)}\n"
            f"If the pack GAINED its group ids, lower the count — and delete the row "
            f"entirely once it reaches 0, so the rule applies to this pack again. If it "
            f"GREW, a port has copied the omission forward: give the new options their "
            f"group id instead of bumping the number. Recorded because: {debt.why}"
        )
        return

    for field, members in ungrouped.items():
        groups = {pf.group for pf in members}
        raise AssertionError(
            f"{key}: checkbox lines {sorted(pf.line for pf in members)} share AcroForm "
            f"field '{field}' (a radio group) but not one 'group' id (groups="
            f"{sorted(str(g) for g in groups)}) — give every option the same group "
            f"(formpacks/CONVENTIONS.md).\nThe shared field means fill_form will refuse a "
            f"double answer even without the id, so this cannot file a contradictory "
            f"return; what it DOES cost is the read side — verify's checkbox_audit builds "
            f"its groups from 'group:'/'required:' alone and emits no check at all for an "
            f"ungrouped set, so nothing confirms a required question was answered. If this "
            f"is a pre-existing state pack you are not fixing today, add a row to "
            f"SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID naming the questions"
        )


@pytest.mark.parametrize(
    "row",
    SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID,
    ids=lambda row: _pack_id(FORMPACKS / row.pack),
)
def test_shared_field_debt_is_covered_by_fill_forms_same_field_guard(
    row: SharedFieldDebt, tmp_path: Path
):
    """The debt rows above are safe only because of this guard — so prove it.

    Every exemption in ``SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID`` rests on one
    claim: that answering two options of the same shared field is a hard error
    even with no ``group:`` id. That claim is checked here per pack and per
    option set, not asserted in prose. If the guard ever narrows, these rows
    stop being convention debt and become filable-wrong-return defects, and
    this test is what says so.
    """
    pack_path = FORMPACKS / row.pack
    assert pack_path.is_file(), (
        f"SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID names {row.pack}, which does not exist — "
        f"delete the row"
    )
    pack = _load(pack_path)
    # fill_form validates line keys and group/field conflicts BEFORE it parses
    # the blank, so an unparseable stub is enough (and keeps this offline).
    stub = tmp_path / "unparsed-blank.pdf"
    stub.write_bytes(b"not a pdf")

    ungrouped = _ungrouped_shared_field_sets(pack)
    assert ungrouped, (
        f"{row.pack} has no ungrouped shared-field option sets left — delete its "
        f"SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID row"
    )
    for field, members in sorted(ungrouped.items()):
        first, second = members[0], members[1]
        with pytest.raises(ValueError, match=r"AcroForm field") as excinfo:
            fill_form(
                pack, {first.line: True, second.line: True}, stub, tmp_path / "out.pdf"
            )
        message = str(excinfo.value)
        assert field in message and "single selection" in message, (
            f"{row.pack}: fill_form rejected the double answer on '{field}' but not as a "
            f"shared-field conflict ({message!r}). The exemption for this pack depends on "
            f"that specific refusal — re-derive the row before trusting it"
        )
        # ...and exactly one answer is still accepted (no over-reach): the only
        # thing left to stop it is the unparseable stub.
        for line in (first.line, second.line):
            with pytest.raises(ValueError, match="could not be parsed as a PDF"):
                fill_form(pack, {line: True}, stub, tmp_path / "out.pdf")


def test_shared_field_debt_rows_are_state_only_and_carry_a_justification():
    """No federal pack may take this exemption, and no row may be a rubber stamp."""
    federal = sorted(
        row.pack for row in SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID
        if not row.pack.startswith("states/")
    )
    assert not federal, (
        f"{federal} are federal packs. The federal lane has no shared-field group debt "
        f"and must not acquire any — fix the pack"
    )
    packs = [row.pack for row in SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID]
    assert len(packs) == len(set(packs)), "duplicate pack rows in the debt table"
    thin = [row.pack for row in SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID if len(row.why.split()) < 4]
    assert not thin, (
        f"row(s) {thin} have no real justification. The row must name the printed "
        f"QUESTIONS whose options are ungrouped, so the next reader can fix them without "
        f"re-deriving the list"
    )
    discovered = {_pack_key(path) for path in ALL_PACK_PATHS}
    missing = sorted(set(packs) - discovered)
    assert not missing, f"debt row(s) name packs that no longer exist: {missing}"


# ---------------------------------------------------------------------------
# Checkbox groups, topology 2 — Yes/No on SEPARATE fields (pitfall P-008)
# ---------------------------------------------------------------------------

# The option separator is not settled house-wide: federal packs and some state
# packs spell an option `<stem>.yes`, 22 state packs spell it `<stem>::yes`, and
# the three ny/*/it203 packs spell it `<stem>_yes`. _yesno_pairs accepts all
# three, because a gate that only knows one spelling is a gate with a hole in
# it: the dotted-only version could not see NC's five Yes/No questions even
# after the glob was widened. Measured on 2026-08-21, the three spellings find
# 326 pairs repo-wide (dotted 268, '::' 37, '_' 21) with ZERO false pairs — no
# stem picks up a member that is not a real Yes/No option.
_OPTION_SEPARATORS = ("::", ".", "_")

# Yes/No line pairs on SEPARATE AcroForm fields that are knowingly still
# ungrouped. Each entry is a visible, self-clearing debt: when the pack gets
# its group ids, this test fails on the stale entry and the entry must go.
#
# EMPTY as of 2026-08-24 — the last 13 rows self-cleared and were retired:
# sched_d 2023/2024/2025 x (qof, 17, 20, 22) got group ids qof/line17/line20/
# line22 (required: true on qof.yes only), and states/wv/2023/it140 got
# `group: heptc.required_federal_return` on both HEPTC-1 Part I circles.
# The rule now applies to every discovered pack with no exemptions.
KNOWN_UNGROUPED_YESNO_PAIRS: frozenset[tuple[int, str, str]] = frozenset()


def _yesno_pairs(pack: FormPack) -> dict[str, list[PackField]]:
    """Checkbox lines grouped by stem, for stems that have a .yes AND a .no.

    Tries each house separator in turn and keeps the FIRST one that yields a
    yes/no token, so `heptc.required_federal_return.yes` (dotted),
    `residency_taxpayer::yes` ('::') and `B_itemized_federal_yes` ('_') all
    resolve to their own stem. Trying-in-turn rather than first-separator-wins
    matters: a hypothetical `sch_f.1_yes` splits on '.' to the non-token
    '1_yes' and would otherwise be missed.
    """
    stems: dict[str, list[PackField]] = {}
    for pack_field in pack.fields:
        if pack_field.type != "checkbox":
            continue
        for separator in _OPTION_SEPARATORS:
            if separator not in pack_field.line:
                continue
            stem, last = pack_field.line.rsplit(separator, 1)
            if last.casefold() in ("yes", "no"):
                stems.setdefault(stem, []).append(pack_field)
                break
    return {stem: members for stem, members in stems.items() if len(members) > 1}


@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_every_yes_no_pair_shares_one_group_id(pack_path: Path):
    """P-008, repo-wide: exclusivity comes from the `group` id, not from the PDF."""
    pack = _load(pack_path)
    key = _pack_key(pack_path)
    form_key = pack_path.parent.name
    debt = _shared_field_debt().get(key)

    for stem, members in _yesno_pairs(pack).items():
        groups = {member.group for member in members}
        grouped = None not in groups and len(groups) == 1
        known = (pack.tax_year, form_key, stem) in KNOWN_UNGROUPED_YESNO_PAIRS
        if known:
            assert not grouped, (
                f"{key}: '{stem}' now has its group id — delete "
                f"({pack.tax_year}, {form_key!r}, {stem!r}) from "
                f"KNOWN_UNGROUPED_YESNO_PAIRS so the rule applies to it again (P-008)"
            )
            continue
        if grouped:
            continue
        fields = {member.field for member in members}
        # A pair on ONE shared field cannot file a contradiction (the field holds
        # a single /V and fill_form refuses the double answer), so for a pack
        # already carrying a SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID row the debt
        # is recorded — and guard-proved — there rather than duplicated here.
        # No federal pack has such a row, so the federal rule is unchanged.
        if len(fields) == 1 and debt is not None:
            continue
        assert grouped, (
            f"{key}: lines {sorted(m.line for m in members)} are the Yes/No boxes of ONE "
            f"question but do not share one 'group' id (groups="
            f"{sorted(str(g) for g in groups)}). They map to SEPARATE AcroForm fields "
            f"{sorted(fields)}, so the PDF does not make them exclusive and fill_form "
            f"would set BOTH boxes on with no warning — a return that answers the same "
            f"question Yes and No. Give both lines the same group "
            f"(formpacks/CONVENTIONS.md, pitfall P-008)"
        )


def test_known_ungrouped_yesno_rows_all_still_describe_a_real_pair():
    """Every P-008 debt row must point at a pair that exists — or be deleted."""
    live: set[tuple[int, str, str]] = set()
    for path in ALL_PACK_PATHS:
        pack = _load(path)
        for stem in _yesno_pairs(pack):
            live.add((pack.tax_year, path.parent.name, stem))
    stale = sorted(row for row in KNOWN_UNGROUPED_YESNO_PAIRS if row not in live)
    assert not stale, (
        f"KNOWN_UNGROUPED_YESNO_PAIRS row(s) {stale} name a stem that is no longer a "
        f"Yes/No pair in any discovered pack — the lines were renamed, retyped or "
        f"dropped, so delete the rows (P-008)"
    )


def test_yesno_pair_helper_accepts_every_house_option_spelling():
    """Unit-pin the separator set: this is the hole that hid the NC defect."""
    pack = FormPack.model_validate(
        {
            "form": "SEPARATOR-HARNESS",
            "jurisdiction": "federal",
            "tax_year": 2023,
            "source_url": "https://www.irs.gov/pub/irs-pdf/test.pdf",
            "pdf_sha256": "...",
            "acroform_root": "",
            "fields": [
                # dotted (federal + some state packs)
                {"line": "dotted.yes", "field": "a", "type": "checkbox", "on_state": "/1"},
                {"line": "dotted.no", "field": "b", "type": "checkbox", "on_state": "/1"},
                # '::' (22 state packs)
                {"line": "colons::yes", "field": "c", "type": "checkbox", "on_state": "/1"},
                {"line": "colons::no", "field": "d", "type": "checkbox", "on_state": "/1"},
                # '_' (the three ny it203 packs)
                {"line": "under_yes", "field": "e", "type": "checkbox", "on_state": "/1"},
                {"line": "under_no", "field": "f", "type": "checkbox", "on_state": "/1"},
                # dotted stem whose yes/no token is '_'-separated
                {"line": "sch_f.1_yes", "field": "g", "type": "checkbox", "on_state": "/1"},
                {"line": "sch_f.1_no", "field": "h", "type": "checkbox", "on_state": "/1"},
                # NOT a pair: a lone "check here if" box whose name merely ends in
                # a word that is not a yes/no token
                {"line": "18_no_consumer_use_tax_due", "field": "i", "type": "checkbox", "on_state": "/1"},
                # NOT a pair: a multi-option radio, no yes/no token
                {"line": "filing_status::mfj", "field": "j", "type": "checkbox", "on_state": "/1"},
                {"line": "filing_status::single", "field": "j", "type": "checkbox", "on_state": "/2"},
                # NOT a pair: a yes with no matching no
                {"line": "amended_return.yes", "field": "k", "type": "checkbox", "on_state": "/1"},
                # money/text lines are never options
                {"line": "1a", "field": "m", "type": "money"},
            ],
        }
    )
    pairs = _yesno_pairs(pack)
    assert set(pairs) == {"dotted", "colons", "under", "sch_f.1"}, sorted(pairs)
    assert all(len(members) == 2 for members in pairs.values())


# ---------------------------------------------------------------------------
# Identity page mirrors (pitfall P-007 class 4) — a mirror needs its source
# ---------------------------------------------------------------------------

# The single most-repeated state defect in this repo is an identity banner that
# ships BLANK on pages 2..N. The form repeats the filer's name and SSN at the
# top of every later page, the DOR propagates it (embedded JavaScript, or an
# XFA `<bind match="global"/>`), taxfill runs neither, and a pack that maps only
# the page-1 original files a return whose every continuation page has an empty
# header. ri/2023 + ri/2024 shipped exactly that — twelve unmapped mirrors each
# — and oh/2023 + oh/2024 shipped it on eleven pages through one 12-kid field.
#
# Nothing anywhere asserted the relationship, in either direction. These checks
# do, at the level a pack can actually express:
#
#   * a mirror line must have a SOURCE line in the same pack (otherwise a
#     caller has no canonical key to copy from, and the mirrors drift);
#   * the mirror must bind a DIFFERENT AcroForm field (this is the fact the
#     Ohio pack originally got wrong — TP_SSN1 is a separate field from TP_SSN,
#     so writing tp_ssn cannot populate it);
#   * mirror and source must agree on `type`, `comb` and `format`, because
#     those drive how the value is normalised — an SSN mirror written through a
#     different path is exactly the P-001 shape, and verify's clipping scan
#     skipped ReadOnly widgets until Phase J J0.3 (it now scans a MAPPED one
#     only once a fill changes its value), so this gate is what catches it.
#
# What is NOT asserted, and cannot be: that the VALUES agree on a real filing.
# `relations` is arithmetic over money lines and `identity_fields` drives a
# CROSS-form check, so `page4_name_last == name.last` has no home in the pack
# schema. A caller that fills a mirror with something else produces an
# internally inconsistent return and no gate will catch it. Both RI pack
# headers say so; it is recorded here because this is where a reader looks.
#
# `maxlen` is deliberately NOT compared: a DOR often prints a narrower box on
# the continuation page, and the packs are right to follow it (nc d400
# tp_last_name 25 -> tp_last_name_page2 10; ri page4/page5 name_last 26 over an
# unconstrained page-1 source). Each pack's maxlen tracks its own widget's
# /MaxLen, which is what keeps ReadOnly mirrors inside _pack_maxlen_checks'
# reach even though the geometry half of the clipping scan cannot see them.

# Mirror line shapes in house use, most specific first. `_page1` is excluded on
# purpose: ny it201/it203's `name_as_shown_page1` names the page a widget sits
# on, it is not a mirror of anything.
_MIRROR_SHAPES = (
    re.compile(r"^page(?P<page>[2-9])_(?P<stem>.+)$"),
    re.compile(r"^(?P<stem>.+)_page(?P<page>[2-9])$"),
    re.compile(r"^(?P<stem>.+)_pg(?P<page>[2-9])$"),
)


class MirrorPair(NamedTuple):
    """One identity mirror whose line key does not follow a house shape."""

    pack: str
    mirror: str
    source: str
    why: str


# Mirrors the shape rules above cannot find, listed explicitly. Only ONE form
# needs this today, and it is the one that shipped the defect.
EXTRA_IDENTITY_MIRRORS: tuple[MirrorPair, ...] = (
    MirrorPair(
        "states/oh/2023/it1040_oh/pack.yaml",
        "tp_ssn_page_header",
        "tp_ssn",
        "Ohio names the mirror after the header it fills rather than the page it sits on, "
        "so no page-number shape matches it. TP_SSN1 is a SEPARATE AcroForm field from the "
        "page-1 TP_SSN with 12 widget kids, 11 of them on document pages 2-12, every one of "
        "which prints an SSN caption — so writing tp_ssn alone leaves 11 blank headers",
    ),
    MirrorPair(
        "states/oh/2024/it1040_oh/pack.yaml",
        "tp_ssn_page_header",
        "tp_ssn",
        "same field topology as the 2023 base, ported unchanged",
    ),
    MirrorPair(
        "states/oh/2025/it1040_oh/pack.yaml",
        "tp_ssn_page_header",
        "tp_ssn",
        "same field topology as 2024 on the 2025 blank (TP_SSN1: one field, 12 widget kids, "
        "11 on pages 2-12 under an SSN caption), re-read on the Phase J JS5 port renders",
    ),
)


class MirrorlessPack(NamedTuple):
    """A pack whose mirror-shaped keys have no single source key, and why."""

    pack: str
    lines: tuple[str, ...]
    why: str


# A mirror-shaped key with no resolvable source is usually a bug. These are
# not: the page-1 identity is spelled with a DIFFERENT SHAPE from the mirror,
# many-to-one, so no key-rewriting rule can pair them up and inventing one
# would be a false assertion.
MIRRORS_WITHOUT_A_SINGLE_SOURCE_KEY: tuple[MirrorlessPack, ...] = (
    *(
        MirrorlessPack(
            f"states/nj/{year}/nj1040/pack.yaml",
            ("page2_names", "page2_ssn", "page3_names", "page3_ssn", "page4_names", "page4_ssn"),
            "NJ-1040 splits the page-1 SSN across NINE comb boxes (tp_ssn_d01..d09) and "
            "prints the page-1 name as the single combined tp_name_last_first_initial, "
            "while each continuation header is ONE box. The pairing is nine-to-one and "
            "one-to-one-under-another-name, so it cannot be derived from the key",
        )
        for year in (2023, 2024)
    ),
    *(
        MirrorlessPack(
            f"states/pa/{year}/pa40/pack.yaml",
            ("name_on_page2",),
            "PA-40's page-2 header is one 'name on' box over a page-1 identity split into "
            "tp_first_name / tp_mi / tp_last_name / tp_suffix, so again many-to-one. Note "
            "PA needs no SSN mirror key at all: your_ssn is ONE AcroForm field whose widget "
            "repeats at the top of page 2, so a single write fills both",
        )
        for year in (2023, 2024, 2025)
    ),
)


def _source_key_candidates(stem: str) -> tuple[str, ...]:
    """Spellings a mirror's stem may use for its page-1 source key.

    House packs spell the source both ways: sched_e mirrors `identifying_number`
    as `identifying_number_page2` (undotted both ends), while ri1040 mirrors the
    dotted `name.first` as `page2_name_first`. So a mirror stem resolves against
    the bare stem AND its first-underscore-to-dot rewrite.
    """
    if "_" not in stem:
        return (stem,)
    return (stem, stem.replace("_", ".", 1))


def _discovered_mirrors(pack: FormPack) -> tuple[list[tuple[str, str]], list[str]]:
    """(mirror, source) pairs found by shape, plus mirror-shaped keys with no source."""
    lines = {pf.line for pf in pack.fields}
    pairs: list[tuple[str, str]] = []
    orphans: list[str] = []
    for line in sorted(lines):
        for shape in _MIRROR_SHAPES:
            match = shape.match(line)
            if match is None:
                continue
            stem = match.group("stem")
            source = next(
                (c for c in _source_key_candidates(stem) if c in lines and c != line), None
            )
            if source is None:
                orphans.append(line)
            else:
                pairs.append((line, source))
            break
    return pairs, orphans


# Mirror pairs per pack, measured 2026-08-21 by the shape rules above. Pinned so
# that DROPPING a mirror fails — which is the direction the defect actually took:
# ri/2023 and ri/2024 each shipped 0 of their 12 for months.
IDENTITY_MIRROR_COUNTS: dict[str, int] = {
    # Form 8949's page-2 header prints "Name(s) shown on return. Name and SSN or
    # taxpayer identification no. not required if shown on other side" over its
    # OWN AcroForm fields (Page2[0].f2_1[0]/f2_2[0]). The escape clause is "if
    # shown on other side", and the instructions make a Part-II-only filing
    # correct ("complete and file either Part I or II"), so that filing has no
    # other side and the page-2 header is the only place the identity appears.
    "federal/2023/f8949/pack.yaml": 2,
    "federal/2024/f8949/pack.yaml": 2,
    # 2025 binds the renamed page-2 widgets (Page2[0].f2_01[0]/f2_02[0]); the
    # header text, the escape clause and the count are all unchanged.
    "federal/2025/f8949/pack.yaml": 2,
    "federal/2026/f8949/pack.yaml": 2,   # the 2026 draft keeps the 2025 widgets (Phase J JT3d)
    "federal/2023/sched_e/pack.yaml": 2,
    "federal/2024/sched_e/pack.yaml": 2,
    "federal/2025/sched_e/pack.yaml": 2,
    # The 2026 draft adds a third page (Part V) that repeats the header: page 2 AND page 3 mirrors (JT5d).
    "federal/2026/sched_e/pack.yaml": 4,
    "states/nc/2023/d400/pack.yaml": 1,
    "states/nc/2024/d400/pack.yaml": 1,
    # 2025 keeps the page-2 "Last Name (First 10 Characters)" box on its own widget (y_d400wf_lname2_PG2); the SSN
    # echo is the same field as page 1 and so is not a mirror (Phase J JS5).
    "states/nc/2025/d400/pack.yaml": 1,
    # The 2025 port maps the page-2 and page-3 header "SSN" boxes (Page2SSN / Page3SSN: their own /Tx widgets, a
    # keystroke filter and no JavaScript that copies the page-1 SSN) as identifying_number_page2 / _page3; the 2023
    # pack had left them unmapped, so its continuation headers shipped blank (Phase J JS5).
    # The 2024 port maps the page-2 and page-3 header "SSN" boxes (Page2SSN / Page3SSN: their own /Tx widgets, a
    # keystroke filter and no JavaScript that copies the page-1 SSN) as identifying_number_page2 / _page3; the 2023
    # pack had left them unmapped, so its continuation headers shipped blank (Phase J JS5, as the 2025 port in
    # commit 8959461).
    "states/ms/2024/f80105/pack.yaml": 2,
    "states/ms/2025/f80105/pack.yaml": 2,
    "states/ri/2023/ri1040/pack.yaml": 12,
    "states/ri/2024/ri1040/pack.yaml": 12,
    "states/va/2023/va760/pack.yaml": 1,
    "states/va/2024/va760/pack.yaml": 1,
    # 2025 renamed the pair: the page-1 SSN is now "SSN 1" (2024: "Your SSN") and the
    # page-2 header mirror is "SSN 2" (2024: "SSN 1") — still one mirror (Phase J JS5).
    "states/va/2025/va760/pack.yaml": 1,
    "states/wi/2023/wi_form1/pack.yaml": 15,
    # The 2025 Form 1 adds a fifth page (Schedule 3) whose header repeats the name in two NEW
    # ReadOnly widgets (lnamepg5 / fnamepg5); its SSN cells are second widgets of the page-4
    # fields, so they need no key. 15 + 2 (Phase J JS5).
    "states/wi/2025/wi_form1/pack.yaml": 17,
}


@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_identity_page_mirrors_agree_with_the_line_they_mirror(pack_path: Path):
    """A page-2..N identity mirror binds its own widget and matches its source."""
    pack = _load(pack_path)
    key = _pack_key(pack_path)
    by_line = {pf.line: pf for pf in pack.fields}

    pairs, orphans = _discovered_mirrors(pack)
    extra = [
        (row.mirror, row.source) for row in EXTRA_IDENTITY_MIRRORS if row.pack == key
    ]
    for mirror, source in extra:
        assert mirror in by_line and source in by_line, (
            f"{key}: EXTRA_IDENTITY_MIRRORS names '{mirror}' -> '{source}' but the pack no "
            f"longer maps both. If the mirror was intentionally dropped, the continuation "
            f"pages now ship a BLANK header — re-read the printed face before deleting the "
            f"row (P-007 class 4)"
        )

    for mirror, source in [*pairs, *extra]:
        mirror_field, source_field = by_line[mirror], by_line[source]
        assert mirror_field.field != source_field.field, (
            f"{key}: '{mirror}' and '{source}' bind the SAME AcroForm field "
            f"'{mirror_field.field}', so the mirror line is redundant — one write already "
            f"fills both widgets. Drop the mirror key, or re-derive the binding: the "
            f"opposite mistake (assuming one field when the DOR authored two) is what left "
            f"Ohio's page 2-12 SSN headers blank"
        )
        assert mirror_field.type == source_field.type, (
            f"{key}: '{mirror}' is type {mirror_field.type!r} but its source '{source}' is "
            f"{source_field.type!r} — a mirror carries the same value, so it takes the same "
            f"type"
        )
        assert (mirror_field.comb, mirror_field.format) == (
            source_field.comb,
            source_field.format,
        ), (
            f"{key}: '{mirror}' has comb={mirror_field.comb!r} format="
            f"{mirror_field.format!r} while '{source}' has comb={source_field.comb!r} "
            f"format={source_field.format!r}. Those drive normalisation, so a mismatch "
            f"means the same SSN reaches the two boxes spelled differently — verify's clipping "
            f"scan checks a mapped ReadOnly mirror's width and /MaxLen, not whether its "
            f"spelling matches its source's, so nothing downstream would catch it (P-001)"
        )

    exempt = {
        line
        for row in MIRRORS_WITHOUT_A_SINGLE_SOURCE_KEY
        if row.pack == key
        for line in row.lines
    }
    unexplained = sorted(set(orphans) - exempt)
    assert not unexplained, (
        f"{key}: mirror-shaped line(s) {unexplained} have no source line in this pack. "
        f"Either the page-1 original is unmapped (then the caller has nothing to copy "
        f"from), or the source is spelled in a shape _source_key_candidates does not know. "
        f"If the pairing is genuinely many-to-one — NJ splits its page-1 SSN across nine "
        f"comb boxes — add a MIRRORS_WITHOUT_A_SINGLE_SOURCE_KEY row saying so"
    )

    pinned = IDENTITY_MIRROR_COUNTS.get(key, 0)
    assert len(pairs) == pinned, (
        f"{key} has {len(pairs)} identity page mirror(s) ({sorted(m for m, _ in pairs)}); "
        f"IDENTITY_MIRROR_COUNTS pins {pinned}.\nA count that DROPPED is the defect this "
        f"pins: ri1040 shipped 0 of its 12 banner mirrors for months, filing a blank "
        f"'Name(s) shown on Form RI-1040' header on pages 2-5. A count that GREW is "
        f"usually right — confirm each new mirror against the printed continuation-page "
        f"header, then update the number"
    )


def test_identity_mirror_tables_name_real_packs_and_carry_justifications():
    """Stale mirror-table rows must surface, and no row may be a rubber stamp."""
    discovered = {_pack_key(path) for path in ALL_PACK_PATHS}
    named = (
        {row.pack for row in EXTRA_IDENTITY_MIRRORS}
        | {row.pack for row in MIRRORS_WITHOUT_A_SINGLE_SOURCE_KEY}
        | set(IDENTITY_MIRROR_COUNTS)
    )
    missing = sorted(named - discovered)
    assert not missing, f"mirror table row(s) name packs that no longer exist: {missing}"
    thin = [
        f"{row.pack}:{row.mirror if isinstance(row, MirrorPair) else row.lines[0]}"
        for row in (*EXTRA_IDENTITY_MIRRORS, *MIRRORS_WITHOUT_A_SINGLE_SOURCE_KEY)
        if len(row.why.split()) < 4
    ]
    assert not thin, f"row(s) {thin} carry no real justification"
    zero = sorted(pack for pack, count in IDENTITY_MIRROR_COUNTS.items() if count < 1)
    assert not zero, (
        f"IDENTITY_MIRROR_COUNTS row(s) {zero} pin ZERO mirrors — a pack with no mirrors "
        f"is simply absent from the table; a row pinned at 0 asserts nothing"
    )


# ---------------------------------------------------------------------------
# Year tokens in line keys — the "stale port" shape, mechanised
# ---------------------------------------------------------------------------

# A printed row often names a year ("Give number of days you were present in
# the United States during: 2022, 2023, and 2024"; "credit to your 2025 tax"),
# and a pack that embeds that year in the LINE KEY has made a promise it has to
# keep on every port. When it does not, the key names one year and writes the
# box printed for another — silently, because the binding still resolves.
#
# The check that makes that mechanical: for every 4-digit token in a line key,
# take ``tax_year - year`` and compare the resulting OFFSET SET against a pinned
# expectation per (form_key, family), where the family is the key with each year
# replaced by ``<Y>``. An offset set is stable across years whenever the pack is
# right, and it moves the moment a port forgets to roll the labels. Grounded in
# a full 2026-08-21 sweep of every year-bearing key in all 150 packs, which is
# how the two stale rows below were found.
#
# The sweep also settles what the convention should be — four classes, not two:
#   * offsets like {0,1,2} or {1..6}: PRINTED-YEAR boxes, where the year IS the
#     label of its own widget (f8843 4a/7/11, sched_oi item H). Roll them on
#     every port; the offset set is what proves you did.
#   * a small positive offset set on an option group: WIDGET-SELECTING, same
#     rule (nj1040 filing_status_qw_year_of_death::<Y>, offsets {1,2}).
#   * offset -1 ("next year"): the year merely LABELS the meaning and does not
#     pick the widget, so it should not be in the key at all — name the role
#     (`refund_applied_to_next_year`) and put the printed year in a comment.
#     These are the ones that go stale, and ny it203 did.
#   * a year-SHAPED token that is not a tax year: a statutory year, or a form
#     number. Pinned with an empty offset tuple so the check skips it.
_YEAR_TOKEN = re.compile(r"(?:19|20)\d{2}")


class YearFamily(NamedTuple):
    """Expected (tax_year - year) offsets for one family of year-bearing keys."""

    form_key: str
    family: str  # the line key with every 4-digit token replaced by "<Y>"
    offsets: tuple[int, ...]  # sorted expected offsets; () = not a tax year at all
    why: str


YEAR_BEARING_KEY_FAMILIES: tuple[YearFamily, ...] = (
    # --- printed-year boxes: the year labels its own widget ---
    YearFamily(
        "f8843", "4a.<Y>", (0, 1, 2),
        "Part I line 4a prints three columns for the current year and the two before it, "
        "each its own box; consistent across all seven shipped f8843 years",
    ),
    YearFamily(
        "f8843", "7.<Y>", (1, 2, 3, 4, 5, 6),
        "Part III line 7 prints the six years before the filing year, one box each",
    ),
    YearFamily(
        "f8843", "11.<Y>", (1, 2, 3, 4, 5, 6),
        "Part IV line 11 prints the same six prior years as line 7, one box each",
    ),
    YearFamily(
        "sched_oi", "h.<Y>", (0, 1, 2),
        "item H prints 'you were present in the United States during: <ty-2>, <ty-1>, and "
        "<ty>' with one box per year, so the offsets are always {0,1,2}",
    ),
    # --- widget-selecting option groups ---
    YearFamily(
        "nj1040", "filing_status_qw_year_of_death::<Y>", (1, 2),
        "NJ-1040 line 5 prints two qualifying-widow ovals for the two years before the "
        "filing year; the year picks WHICH OVAL, so it belongs in the key and must be "
        "re-derived from the printed face on every port",
    ),
    # --- derived from a statutory age rule, not from a printed year list ---
    *(
        YearFamily(
            "f1040", family, (64,),
            "the standard-deduction age box prints 'born before January 2, <ty-64>', which "
            "is the 65-or-older test expressed as a birth date; the offset is fixed by the "
            "rule, so it never varies even though the printed year moves every year",
        )
        for family in (
            "age_blindness.you_born_before_jan_2_<Y>",
            "age_blindness.spouse_born_before_jan_2_<Y>",
            "12d.you_born_before_jan_2_<Y>",
            "12d.spouse_born_before_jan_2_<Y>",
        )
    ),
    # --- 'next year' labels: the year does NOT pick the widget ---
    # This class deliberately has NO live rows. Every shipped instance —
    # nj1040 line69_credit_to_<Y>_tax_d01..d10, tc40 refund_applied_to_<Y>,
    # form40 56.apply_to_<Y>, it203 69_amount_applied_to_<Y>_estimate — was
    # renamed to its year-free ROLE key on 2026-08-24 (the printed year now
    # lives in each pack's inline comment; each pack's header records the
    # rename and its measured blast radius). If a key of this shape ever ships
    # again, the not-classified assertion below firing is the intended catch:
    # the fix is the role rename, never a new (-1,) row here.
    # --- year-SHAPED tokens that are not tax years ---
    *(
        YearFamily(
            "az140", family, (),
            "a STATUTORY year in the printed line's own name (pre-1990 pollution-control "
            "amortization / exploration expenses). It is fixed by law and never moves with "
            "tax_year, so no offset applies",
        )
        for family in (
            "oa_N_amortization_pollution_facility_<Y>",
            "os_O_exploration_expenses_pre<Y>",
        )
    ),
    YearFamily(
        "it540", "22b.amount_from_r<Y>0a", (),
        "not a year at all — Louisiana Schedule R-19000A is a FORM NUMBER whose digits "
        "happen to match the year pattern",
    ),
    YearFamily(
        "it540", "23b.amount_from_r<Y>0a", (),
        "the same Form R-19000A box: the 2025 IT-540 renumbers 22B to 23B (a new line 8 "
        "pushes every later line by one), the form number is unchanged",
    ),
)


# (pack, family) pairs whose offsets are wrong in the shipped pack. Each is a
# real, reproduced defect that the pack's owner must fix; recorded so the gate
# stays green while the defect stays loud, and self-clearing the moment the keys
# are rolled. EMPTIED 2026-08-24: the three rows the 2026-08-21 sweep found are
# fixed — federal/2024/sched_oi rolled item H to h.2022/h.2023/h.2024 against
# the same widgets (offsets {0,1,2}, re-verified on the filled render), and the
# ny it203 2024/2025 line-69 keys took the year-free role rename (which retired
# their it203 family row above, so those keys carry no year token at all now).
KNOWN_STALE_PRINTED_YEAR_LABELS: tuple[tuple[str, str, str], ...] = ()


def _year_families(pack: FormPack) -> dict[str, set[int]]:
    """Family -> set of (tax_year - year) offsets for every year-bearing key."""
    families: dict[str, set[int]] = {}
    for pack_field in pack.fields:
        tokens = _YEAR_TOKEN.findall(pack_field.line)
        if not tokens:
            continue
        family = _YEAR_TOKEN.sub("<Y>", pack_field.line)
        offsets = families.setdefault(family, set())
        offsets.update(pack.tax_year - int(token) for token in tokens)
    return families


@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_year_bearing_line_keys_keep_their_offset_from_tax_year(pack_path: Path):
    """A key that names a year must name the RIGHT year for its own pack."""
    pack = _load(pack_path)
    key = _pack_key(pack_path)
    form_key = pack_path.parent.name
    expected = {
        (row.form_key, row.family): row for row in YEAR_BEARING_KEY_FAMILIES
    }
    stale = {(row[0], row[1]): row[2] for row in KNOWN_STALE_PRINTED_YEAR_LABELS}

    for family, offsets in sorted(_year_families(pack).items()):
        row = expected.get((form_key, family))
        assert row is not None, (
            f"{key}: line key family '{family}' embeds a 4-digit year but is not classified "
            f"in YEAR_BEARING_KEY_FAMILIES (offsets from tax_year {pack.tax_year}: "
            f"{sorted(offsets)}).\nRead the printed row and pick a class: if the year LABELS "
            f"its own widget (a printed per-year box, or an option that picks one oval), pin "
            f"the offsets and roll the key on every port; if the year merely describes the "
            f"meaning — 'credit to your <next> tax' — the year does not belong in the key at "
            f"all, so name the ROLE and put the printed year in a comment; if the token is "
            f"not a tax year (a statute year, a form number) pin an empty offset tuple"
        )
        if not row.offsets:
            continue  # classified as not-a-tax-year
        if tuple(sorted(offsets)) == row.offsets:
            assert (key, family) not in stale, (
                f"{key}: '{family}' now has the right offsets {row.offsets} — delete its "
                f"KNOWN_STALE_PRINTED_YEAR_LABELS row so the rule applies to it again"
            )
            continue
        reason = stale.get((key, family))
        assert reason is not None, (
            f"{key}: line key family '{family}' has offsets {sorted(offsets)} from tax_year "
            f"{pack.tax_year}, but this family is pinned at {list(row.offsets)}.\nThat is "
            f"the STALE-PORT shape: the key still binds a real widget, so nothing else "
            f"complains, but it NAMES one year while writing the box printed for another. "
            f"Re-read the printed row on this year's blank and roll the year in the key "
            f"(the widget bindings usually do not move). Family pinned because: {row.why}"
        )


def test_year_family_and_stale_tables_are_consistent_and_justified():
    """No duplicate rows, no stale-row without a family, no thin justification."""
    keys = [(row.form_key, row.family) for row in YEAR_BEARING_KEY_FAMILIES]
    assert len(keys) == len(set(keys)), (
        f"duplicate (form_key, family) rows: "
        f"{sorted({k for k in keys if keys.count(k) > 1})}"
    )
    thin = [
        f"{row.form_key}:{row.family}"
        for row in YEAR_BEARING_KEY_FAMILIES
        if len(row.why.split()) < 4
    ]
    assert not thin, f"row(s) {thin} carry no real justification"
    discovered = {_pack_key(path) for path in ALL_PACK_PATHS}
    for pack, family, why in KNOWN_STALE_PRINTED_YEAR_LABELS:
        assert pack in discovered, f"stale row names a missing pack: {pack}"
        form_key = Path(pack).parent.name
        assert (form_key, family) in set(keys), (
            f"KNOWN_STALE_PRINTED_YEAR_LABELS row ({pack}, {family}) has no matching "
            f"YEAR_BEARING_KEY_FAMILIES row — the stale row would never be consulted"
        )
        assert len(why.split()) >= 8, (
            f"stale row ({pack}, {family}) needs the printed evidence and the consequence, "
            f"not a label — it is a live defect someone has to fix"
        )



# ---------------------------------------------------------------------------
# Checkbox groups, topology 3 — option sets on SEPARATE fields whose tokens are NOT yes/no (Phase J JEb)
# ---------------------------------------------------------------------------

# Filing statuses, residencies, account types and form checklists spread over one AcroForm field per box are
# invisible to both gates above: the shared-field gate needs two lines on ONE field, and the Yes/No gate needs
# yes/no tokens. Nothing then stops fill_form from ticking two filing statuses. JEb measured 377 such sets over
# 212 packs (240 without one shared group id), grouped the ones the printed face makes exclusive (ID / KS / NE
# filing status, KS / NE residency, KS "Amended Return (Mark ONE)", the ID / MD / MO / IN account types, MD's
# "select one method", AZ's per-dependent under-17 / 17-or-over boxes, CA's 5805 / 5805F and tax method, MO-NRI's
# home of record, GA's paper / electronic voucher), and adjudicated the rest here.
#
# Keyed (family, stem) with family = "federal/<form_key>" or "states/<st>/<form_key>", so a row covers every
# year of that form. Each reason starts INDEPENDENT (the face lets several boxes apply) or PARTIAL (a grouped
# subset sits beside independent boxes). A set whose members all share ONE group id passes without a row.
SEPARATE_OPTION_SETS_ADJUDICATED: dict[tuple[str, str], str] = {
    ('federal/f1040', '12a'):
        'INDEPENDENT: "Someone can claim: You as a dependent / Your spouse as a dependent" — both may apply',
    ('federal/f1040', '12d'):
        'INDEPENDENT: the age / blindness boxes, one per condition per person; any combination may apply ("You: Were born before January 2, ... / Are blind. Spouse: ...")',
    ('federal/f1040', '16'):
        'INDEPENDENT: "Check if any from Form(s): 1 8814 2 4972 3 ..." — any number may apply',
    ('federal/f1040', '3c'):
        'INDEPENDENT: "Check if your child\'s dividends are included in line 3a / line 3b" — both may apply',
    ('federal/f1040', '4c'):
        'INDEPENDENT: the 4c boxes (Rollover, QCD, Other) describe different IRA distributions; several may apply',
    ('federal/f1040', '5c'):
        'INDEPENDENT: the 5c boxes (Rollover, PSO, Other) describe different pension distributions; several may apply',
    ('federal/f1040', '7b'):
        'INDEPENDENT: "Schedule D not required" and "Includes child\'s capital gain or (loss)" are separate facts; both may apply',
    ('federal/f1040', 'age_blindness'):
        'INDEPENDENT: the age / blindness boxes, one per condition per person; any combination may apply ("You: Were born before January 2, ... / Are blind. Spouse: ...")',
    ('federal/f1040', 'dependent_1'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_1_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040', 'dependent_2'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_2_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040', 'dependent_3'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_3_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040', 'dependent_4'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_4_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040', 'filing_status'):
        'PARTIAL: the five statuses share group filing_status; nra_spouse_election is the separate box for treating a nonresident spouse as a resident',
    ('federal/f1040', 'presidential_campaign'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply ("Presidential Election Campaign ... You / Spouse")',
    ('federal/f1040', 'special_processing'):
        'INDEPENDENT: the header boxes (301.9100-2, Combat zone, Deceased, Other) mark separate circumstances; several may apply',
    ('federal/f1040', 'standard_deduction'):
        'INDEPENDENT: "Someone can claim: You as a dependent / Your spouse as a dependent" and the separate "Spouse itemizes on a separate return or you were a dual-status alien" box',
    ('federal/f1040nr', '16'):
        'INDEPENDENT: "Check if any from Form(s): 1 8814 2 4972 3 ..." — any number may apply',
    ('federal/f1040nr', '3c'):
        'INDEPENDENT: "Check if your child\'s dividends are included in line 3a / line 3b" — both may apply',
    ('federal/f1040nr', '4c'):
        'INDEPENDENT: the 4c boxes (Rollover, QCD, Other) describe different IRA distributions; several may apply',
    ('federal/f1040nr', '5c'):
        'INDEPENDENT: the 5c boxes (Rollover, PSO, Other) describe different pension distributions; several may apply',
    ('federal/f1040nr', '7b'):
        'INDEPENDENT: "Schedule D not required" and "Includes child\'s capital gain or (loss)" are separate facts; both may apply',
    ('federal/f1040nr', 'dependent_1'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_1_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040nr', 'dependent_2'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_2_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040nr', 'dependent_3'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_3_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040nr', 'dependent_4'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_4_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040nr', 'special_processing'):
        'INDEPENDENT: the header boxes (301.9100-2, Combat zone, Deceased, Other) mark separate circumstances; several may apply',
    ('federal/f1040x', '15'):
        'INDEPENDENT: line 15 checks every form the refundable credits came from (Schedule 8812, 2439, 4136, 8863, 8885, 8962, other); any number may apply',
    ('federal/f1040x', 'dependent_1'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_1_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040x', 'dependent_2'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_2_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040x', 'dependent_3'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_3_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040x', 'dependent_4'):
        'PARTIAL: child_tax_credit / credit_for_other_dependents share group dependent_4_credit (a dependent qualifies for one); the lived-with / student / disabled boxes are separate facts',
    ('federal/f1040x', 'filing_status'):
        'PARTIAL: the five statuses share group filing_status; nra_spouse_election is the separate box for treating a nonresident spouse as a resident',
    ('federal/f1040x', 'presidential_campaign'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply ("Presidential Election Campaign ... You / Spouse")',
    ('federal/f1040x', 'special_processing'):
        'INDEPENDENT: the header boxes (301.9100-2, Combat zone, Deceased, Other) mark separate circumstances; several may apply',
    ('federal/f2210', 'part_ii'):
        'INDEPENDENT: Part II prints "Check applicable boxes" (A-E); several may apply',
    ('federal/f8833', 'disclosure'):
        'INDEPENDENT: the face prints "Check one or both of the following boxes as applicable" (section 6114; dual-resident 301.7701(b)-7)',
    ('federal/f8960', 'elections'):
        'INDEPENDENT: three separate elections (section 6013(g), 6013(h), Regulations 1.1411-10(g)); any may be made',
    ('federal/fw7', 'reason'):
        'INDEPENDENT: box a prints "(you must also check and complete box h)", so a and h are checked together; a group would block that',
    ('federal/sched_1', '4'):
        'INDEPENDENT: line 4 checks each form the other gains came from (Form 4684, Form 4797); both may apply',
    ('federal/sched_2', '4'):
        'INDEPENDENT: line 4 prints "Check if any exemption from: 1 4361 2 4029 3 ..."; several may apply',
    ('federal/sched_e', '28.a'):
        'INDEPENDENT: the row\'s "foreign partnership", "basis computation required" and "not at risk" boxes are separate facts',
    ('federal/sched_e', '28.b'):
        'INDEPENDENT: the row\'s "foreign partnership", "basis computation required" and "not at risk" boxes are separate facts',
    ('federal/sched_e', '28.c'):
        'INDEPENDENT: the row\'s "foreign partnership", "basis computation required" and "not at risk" boxes are separate facts',
    ('federal/sched_e', '28.d'):
        'INDEPENDENT: the row\'s "foreign partnership", "basis computation required" and "not at risk" boxes are separate facts',
    ('states/ar/ar1000f', '7a'):
        'INDEPENDENT: the 7A personal-credit boxes (yourself / spouse, 65 or over, 65 Special, blind, deaf, head of household / surviving spouse) are separate credits; several may apply',
    ('states/ar/ar1000f', 'deceased'):
        'INDEPENDENT: a deceased-taxpayer box and a deceased-spouse box; both may apply',
    ('states/az/az140', '58_credit'):
        'INDEPENDENT: line 58 checks each credit form claimed (308-I, 334, 349); several may apply',
    ('states/az/az140', 'oe_10_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/az/az140', 'oe_1_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/az/az140', 'oe_2_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/az/az140', 'oe_3_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/az/az140', 'oe_4_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/az/az140', 'oe_5_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/az/az140', 'oe_6_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/az/az140', 'oe_7_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/az/az140', 'oe_8_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/az/az140', 'oe_9_age65'):
        'INDEPENDENT: C1 and C2 are two sub-boxes under "(c) AGE 65 OR OVER (see instructions)"; the face does not print them as alternatives',
    ('states/ca/form540', '31'):
        'PARTIAL: Tax Table / Tax Rate Schedule share group 31.tax_method (one regular-tax method); the FTB 3800 and 3803 boxes add to it independently',
    ('states/ca/form540', '34'):
        'INDEPENDENT: "Schedule G-1 / FTB 5870A" are separate additional taxes; both may apply',
    ('states/ca/form540', 'filing_status'):
        'PARTIAL: the five statuses share group filing_status; the separate box marks a CA status different from the federal one',
    ('states/ca/form540', 'organ_donor'):
        'INDEPENDENT: the 2025 Side 5 "Organ Donor Election" prints one box per person ("Primary taxpayer" / "Spouse/RDP (if joint tax return)"); both may apply',
    ('states/ca/form540nr', '31'):
        'PARTIAL: Tax Table / Tax Rate Schedule share group 31.tax_method (one regular-tax method); the FTB 3800 and 3803 boxes add to it independently',
    ('states/ca/form540nr', '41'):
        'INDEPENDENT: "Schedule G-1 / FTB 5870A" are separate additional taxes; both may apply',
    ('states/ca/form540nr', 'filing_status'):
        'PARTIAL: the five statuses share group filing_status; the separate box marks a CA status different from the federal one',
    ('states/dc/d40', 'deceased'):
        'INDEPENDENT: a deceased-taxpayer box and a deceased-spouse box; both may apply',
    ('states/de/pit_res', '20'):
        'INDEPENDENT: the age / blindness boxes, one per condition per person; any combination may apply',
    ('states/de/pit_res', '26b'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply (over-60)',
    ('states/de/pit_res', '6'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply (military pension)',
    ('states/de/pit_res', '8b'):
        'INDEPENDENT: the 529 and ABLE boxes for each person are separate subtractions; several may apply',
    ('states/de/pit_res', '21'):
        'INDEPENDENT: the 2025 revision prints the 2023 line-20 age / blindness boxes ("Column A - if Spouse was: '
        '65 or over / blind", "Column B - if You were: 65 or over / blind") on line 21, one per condition per '
        'person; any combination may apply',
    ('states/de/pit_res', '27b'):
        'INDEPENDENT: the 2025 revision prints the 2023 line-26b row ("CHECK BOXES Spouse 60 or over (Column A)", '
        '"Self 60 or over (Column B)") as line 27b, one box for each person; both may apply',
    ('states/ga/ga500', '11_self'):
        'INDEPENDENT: the age / blindness boxes, one per condition per person; any combination may apply',
    ('states/ga/ga500', '11_spouse'):
        'INDEPENDENT: the age / blindness boxes, one per condition per person; any combination may apply',
    ('states/ga/ga500', 's3'):
        "INDEPENDENT: Schedule 3's line-9 time-ratio box and the line-10b age / blind boxes per person are separate facts",
    ('states/ga/ga500', 's4'):
        'INDEPENDENT: the Schedule 4 TYPE OF LOSS boxes (normal, casualty, insurance 2-year, farm 2-year) print no "check one"',
    ('states/ga/ga500', 'voucher'):
        'PARTIAL: Paper Return / Electronically Filed share group voucher.return_medium; Amended Return is independent of both',
    ('states/ia/ia1040', 'age65'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/ia/ia1040', 'blind'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/id/form40', '12a'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/id/form40', '12b'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/il/il1040', '10b_65_or_older'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/il/il1040', '10c_legally_blind'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/il/il1040', '42_household_needs_insurance'):
        'INDEPENDENT: the 2025 line-42 row prints "Tell us who in your household needs health insurance: Self Spouse Dependent(s)" — one box per household member on separate /Btn fields; any combination may apply',
    ('states/il/il1040', 'C_claimed_as_dependent'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/ky/form740', '13'):
        'INDEPENDENT: line 13 checks each form the added taxes came from (4972-K, Schedule RCR, DSR, angel investor recapture); several may apply',
    ('states/ky/form740', 'deceased'):
        'INDEPENDENT: a deceased-taxpayer box and a deceased-spouse box; both may apply',
    ('states/la/it540', '6a'):
        'INDEPENDENT: the 6A boxes (65 or older, blind, qualifying surviving spouse) are separate exemptions; several may apply; '
        'from 2025 the row is "6A AGE DESIGNATION" with one box per person (Taxpayer 65 or Older / Spouse 65 or Older), both may apply',
    ('states/la/it540', '6b'):
        'INDEPENDENT: the 6B boxes (spouse, 65 or older, blind) are separate exemptions; several may apply',
    ('states/ma/form1', '2c'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/ma/form1', '2d'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/ma/form1', 'campaign_fund'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/ma/form1', 'name_changed'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/ma/form1', 'schedule'):
        'INDEPENDENT: the Schedule FCI and TDS boxes mark separate attached schedules',
    ('states/md/md502', '10a_pension_exclusion'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/md/md502', '10b_ranger_pension'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/md/md502', 'exemption_A'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/md/md502', 'exemption_B_65_or_over'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/md/md502', 'exemption_B_blind'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/me/f1040me', '1'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/mo/mo1040', '33'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/mo/mo1040', '34'):
        'INDEPENDENT: "Lump sum distribution (Form 4972)" and "Recapture of low income housing credit (Form 8611)" are separate taxes; both may apply',
    ('states/mo/mo1040', 'c'):
        'INDEPENDENT: the MO-CRP / line-55 boxes mark separate credit rows',
    ('states/mo/mo1040', 'moa'):
        'INDEPENDENT: the MO-A modification boxes each mark their own modification line',
    ('states/mo/mo1040', 'nri'):
        'PARTIAL: Missouri / Non-Missouri Home of Record share group nri_line3.yourself (and nri_line3.spouse) per person; the two persons are independent',
    ('states/mo/mo1040', 'nri_line1'):
        'INDEPENDENT: the MO-NRI line 1 Nonresident and Remote Work boxes, one per person; separate facts',
    ('states/mo/mo1040', 'nri_line2'):
        'INDEPENDENT: the MO-NRI line 2 boxes and their Remote Work boxes, one per person; separate facts',
    ('states/mo/mo1040', 'nri_line3'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/ms/f80105', 'age65_blind'):
        'INDEPENDENT: the age / blindness boxes, one per condition per person; any combination may apply',
    ('states/mt/form2', 'amended'):
        'INDEPENDENT: "indicate the reasons for the changes you made" (a-e); several reasons may apply',
    ('states/mt/form2', 'cpi'):
        'INDEPENDENT: the annualization-method and farming-gross-income boxes are separate estimated-tax facts',
    ('states/mt/form2', 'dd'):
        'PARTIAL: checking / savings share group dd_account_type; the outside-US box is independent',
    ('states/mt/form2', 'exemptions.a'):
        'INDEPENDENT: the age / blindness boxes, one per condition per person; any combination may apply',
    ('states/mt/form2', 'exemptions.b'):
        'INDEPENDENT: the age / blindness boxes, one per condition per person; any combination may apply (and the spouse box)',
    ('states/mt/form2', 'residency'):
        'PARTIAL: the three residency statuses share group residency_status; the military-spouse and ND-reciprocity boxes are independent',
    ('states/nd/nd1', 'amended'):
        'INDEPENDENT: "Fill in if applicable: Amended: General / Amended: Federal NOL (See instructions)" — the face does not mark them alternatives',
    ('states/nd/nd1', 'deceased'):
        'INDEPENDENT: a deceased-taxpayer box and a deceased-spouse box; both may apply',
    ('states/ne/f1040n', '2a'):
        'INDEPENDENT: the age / blindness boxes, one per condition per person; any combination may apply',
    ('states/ne/f1040n', '2b'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/oh/it1040_oh', 'nonresident_statement'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/ok/form511', 'age_65'):
        'INDEPENDENT: one box for each person (you / your spouse) on the same printed row; both may apply',
    ('states/ok/form511', 'f538s'):
        'INDEPENDENT: the 538-S qualification boxes (age 65, physical disability) and the discuss-with-preparer box are separate facts',
    ('states/or/or40', '6a'):
        'INDEPENDENT: the face prints "Check boxes that apply: Regular / Severely disabled / Someone else can claim you as a dependent"',
    ('states/or/or40', '6b'):
        'INDEPENDENT: the face prints "Check boxes that apply: Regular / Severely disabled / Someone else can claim you as a dependent"',
    ('states/pa/pa40', 'deceased'):
        'INDEPENDENT: a deceased-taxpayer box and a deceased-spouse box; both may apply',
}


def _family(pack_path: Path) -> str:
    parts = _pack_key(pack_path).split("/")
    return "/".join(parts[:1] + [parts[-2]]) if parts[0] == "federal" else "/".join(parts[:2] + [parts[-2]])


def _separate_option_sets(pack: FormPack) -> dict[str, list[PackField]]:
    """Checkbox lines sharing a stem (split at the last house separator) that bind two or more AcroForm fields and
    whose option tokens are not yes/no (that pair is test_every_yes_no_pair_shares_one_group_id's)."""
    stems: dict[str, list[PackField]] = {}
    for pack_field in pack.fields:
        if pack_field.type != "checkbox":
            continue
        for separator in _OPTION_SEPARATORS:
            if separator not in pack_field.line:
                continue
            stem, last = pack_field.line.rsplit(separator, 1)
            if last.casefold() not in ("yes", "no"):
                stems.setdefault(stem, []).append(pack_field)
            break
    return {stem: members for stem, members in stems.items()
            if len(members) > 1 and len({member.field for member in members}) > 1}


def _ungrouped(members: list[PackField]) -> bool:
    groups = {member.group for member in members}
    return None in groups or len(groups) > 1


@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_separate_widget_option_sets_are_adjudicated(pack_path: Path):
    """JEb: an option set on separate fields is either one group (fill_form enforces it) or an adjudicated row."""
    family = _family(pack_path)
    for stem, members in _separate_option_sets(_load(pack_path)).items():
        if not _ungrouped(members):
            continue
        assert (family, stem) in SEPARATE_OPTION_SETS_ADJUDICATED, (
            f"{_pack_key(pack_path)}: lines {sorted(m.line for m in members)} are one option set on SEPARATE "
            f"AcroForm fields without one shared 'group' id, so fill_form would tick any combination. Read the printed "
            f"row: if the face makes them alternatives, give them one group (pitfall P-008); if several may apply, "
            f"add ({family!r}, {stem!r}) to SEPARATE_OPTION_SETS_ADJUDICATED quoting the row")


def test_every_option_set_row_still_describes_an_ungrouped_set():
    """The table self-clears: a row whose set is gone or now fully grouped must be deleted."""
    live = {(_family(path), stem) for path in ALL_PACK_PATHS
            for stem, members in _separate_option_sets(_load(path)).items() if _ungrouped(members)}
    stale = sorted(set(SEPARATE_OPTION_SETS_ADJUDICATED) - live)
    assert not stale, f"SEPARATE_OPTION_SETS_ADJUDICATED row(s) {stale} no longer describe an ungrouped set — delete them"
    thin = [key for key, why in SEPARATE_OPTION_SETS_ADJUDICATED.items()
            if not why.startswith(("INDEPENDENT: ", "PARTIAL: ")) or len(why.split()) < 8]
    assert not thin, f"row(s) {thin} need INDEPENDENT/PARTIAL and the printed evidence, not a label"
