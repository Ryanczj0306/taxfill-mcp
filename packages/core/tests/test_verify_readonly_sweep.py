"""Repo-wide: a real one-line fill never FAILs P-001 on text the filer did not write.

COVERAGE NOTE: every per-pack case here needs the pack's blank in the local
cache, so CI (offline, empty cache) SKIPS them and the weekly network job
deselects this module (it carries no network mark) — it runs only on a
machine with a warm .cache/blanks. Each half of the fix also has a
CI-runnable test in test_verify.py / test_verify_readonly_scan.py; wiring
this sweep into the freshness job is Phase J JEa.

The 2026-09-11 fix for P-007(b) widened verify's clipping scan to the
ReadOnly text widgets a pack MAPS (test_verify_readonly_scan.py). It shipped
a regression no existing test could see (PJ-02): AL-40 2023 mapped twelve
ReadOnly DOR instruction banners as lines (Instructions, Instructions1-5,
Instructions7-11, NonDriver) and MO-1040 2023/2024 five checkbox captions
(Texto7, Texto8, Texto9, MOAText, lblNRI), so a real fill of ONE line —
fill_form(al40, {"FIRSTNAME": "Pat"}) — verified ok=False with twelve P-001
FAILs (five for MO) over text baked into the blank, where the pre-fix
verifier said ok=True. The golden round trips cannot see that shape: their
sentinel values overwrite every mapped widget, banners included, and only a
fill that leaves lines alone — which is every real fill — exposes it. (They
did trip on MO-1040 for a different reason: the sentinel written into Text1,
an empty ReadOnly checkbox frame, clipped. It is unmapped too.)

Both halves of the fix are pinned here, on the real blanks:

- the verifier half — verify_form / verify_filing skip a mapped ReadOnly
  widget while its value is still the pinned blank's own. Proven by
  RE-MAPPING the banners onto today's packs (the pre-fix shape) and showing a
  one-line fill still verifies clean, and by the control that proves the blank
  is what does it: with the blank cache emptied, exactly those banners FAIL,
  each naming the fix;
- the pack half — the banners are unmapped (the keys are refused by
  fill_form), and no pack may map a ReadOnly widget whose text already clips
  on the UNFILLED blank (the reviewer's exact scan, run over every pack).

And the sweep itself: for EVERY pack with a cached blank, filling one plain
editable text line and verifying reports zero clipping FAILs. It found one
more pre-existing false FAIL on its first run — WV IT-140 2023's seven blank
state-picker combos hold five spaces under a maxlen-2 hint — now closed in
_pack_maxlen_checks (test_verify.py pins it).

Blanks come from the shared cache ONLY (fetch's own cache path, sha-checked
against the pack's pin); nothing here downloads, so the tests are not
network-marked and a pack whose blank is not cached SKIPS with the command
that warms it. On 2026-09-23 all 172 packs' blanks were cached: 0 skipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.fetch import CACHE_DIR_ENV, _cache_path, compute_sha256, default_cache_dir
from taxfill_core.filler import fill_form
from taxfill_core.schemas.formpack import FormPack, PackField, load_pack
from taxfill_core.verify import (
    FilingItem,
    bound_widget_names,
    clipping_scan,
    qualified_field_name,
    read_text_widgets,
    verify_filing,
    verify_form,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FORMPACKS = REPO_ROOT / "formpacks"
ALL_PACK_PATHS = sorted(FORMPACKS.glob("**/pack.yaml"))

# The ReadOnly DOR banners unmapped 2026-09-23 — each has no /TU and a /V
# baked into the blank (the pack headers quote every one).
AL40_2023 = "states/al/2023/al40/pack.yaml"
MO1040_2023 = "states/mo/2023/mo1040/pack.yaml"
MO1040_2024 = "states/mo/2024/mo1040/pack.yaml"
_AL_BANNERS = ("Instructions", *(f"Instructions{n}" for n in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11)), "NonDriver")
_MO_BANNERS = ("Texto7", "Texto8", "Texto9", "MOAText", "lblNRI")
BANNERS_UNMAPPED: dict[str, tuple[str, ...]] = {
    AL40_2023: _AL_BANNERS,
    MO1040_2023: _MO_BANNERS,
    MO1040_2024: _MO_BANNERS,
}
# Unmapped with them: MO's Text1, an EMPTY ReadOnly /Tx that only draws the
# border of the c.ownfullyear checkbox inside it. It has no baked-in text, so
# it never broke a one-line fill — the round trip's sentinel in it FAILed the
# widened scan instead (test_formpacks_states' network round trip pins that).
NOT_LINES_UNMAPPED: dict[str, tuple[str, ...]] = {
    AL40_2023: _AL_BANNERS,
    MO1040_2023: (*_MO_BANNERS, "Text1"),
    MO1040_2024: (*_MO_BANNERS, "Text1"),
}
# The one-line fill the reviewer reproduced the regression with.
FIRST_NAME_LINE = {AL40_2023: "FIRSTNAME", MO1040_2023: "firstname-1", MO1040_2024: "firstname-1"}


def _pack_id(pack_path: Path) -> str:
    return str(pack_path.relative_to(FORMPACKS)).removesuffix("/pack.yaml").replace("/", "-")


def _cached_blank(pack: FormPack) -> Path:
    """The pack's sha-pinned blank from the shared cache, or SKIP — never a download."""
    path = _cache_path(default_cache_dir(), pack.source_url)
    if not path.is_file():
        pytest.skip(
            f"blank not cached at {path}; warm it with "
            f"fetch_blank({pack.source_url!r}, sha256={pack.pdf_sha256!r}) — this sweep never downloads"
        )
    if compute_sha256(path) != pack.pdf_sha256:
        pytest.skip(f"cached blank {path} does not match the pack's pdf_sha256 — re-fetch it before trusting the sweep")
    return path


def _clip_fails(report) -> list[str]:
    return [f"{check.name}: {check.detail}" for check in report.clipping if check.status == "FAIL"]


def _with_banners_remapped(pack: FormPack, banners: tuple[str, ...]) -> FormPack:
    """Today's pack with the banners mapped again as plain text lines — the pre-2026-09-23 shape."""
    extra = [PackField(line=name, field=name, type="text") for name in banners]
    return pack.model_copy(update={"fields": [*pack.fields, *extra]})


# ---------------------------------------------------------------------------
# The sweep: every pack, one plain text line, zero clipping FAILs
# ---------------------------------------------------------------------------


def _one_plain_text_line(pack: FormPack, blank: Path) -> tuple[str, str]:
    """(line, value) for the first mapped EDITABLE /Tx line with no comb or format rule."""
    editable = {widget.name for widget in read_text_widgets(blank)}  # no bound_names: ReadOnly skipped
    for pack_field in pack.fields:
        if (
            pack_field.type == "text"
            and not pack_field.comb
            and pack_field.format is None
            and qualified_field_name(pack, pack_field) in editable
        ):
            return pack_field.line, "Pat"[: pack_field.maxlen or 3]
    pytest.fail(
        "the pack maps no plain editable text line to fill — pick another minimal line shape for "
        "this sweep rather than letting a pack go unswept"
    )


@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_one_line_fill_verifies_with_zero_clipping_fails(pack_path: Path, tmp_path: Path):
    """P-001 / P-007: a real fill leaves most lines alone; verify must not FAIL on what it left."""
    pack = load_pack(pack_path)
    blank = _cached_blank(pack)
    line, value = _one_plain_text_line(pack, blank)
    filled = tmp_path / "one_line.pdf"
    fill_form(pack, {line: value}, blank, filled)
    report = verify_form(pack, filled)
    fails = _clip_fails(report)
    assert not fails, (
        f"{_pack_id(pack_path)}: filling ONLY line {line!r} = {value!r} FAILed the clipping scan on "
        f"{len(fails)} field(s) the fill never touched:\n  " + "\n  ".join(fails) + "\n\nA value the "
        "DOR baked into the blank is not this fill's clipping. If the field is a ReadOnly banner or "
        "caption (no /TU, DOR prose in its /V) it is not a line — unmap it (P-007 class 1) and "
        "re-pin STATE_COMPUTED_READONLY; if verify should have recognised it as the blank's own "
        "value, the defect is in verify.py's _drop_blank_owned / _pack_maxlen_checks (P-001)."
    )
    assert {check.id: check.status for check in report.pitfall_checks}["P-001"] == "PASS"


@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_no_pack_maps_a_read_only_widget_whose_blank_text_already_clips(pack_path: Path):
    """The pack half: the reviewer's scan of the UNFILLED blank, over every pack."""
    pack = load_pack(pack_path)
    blank = _cached_blank(pack)
    baked = [
        widget
        for widget in read_text_widgets(blank, bound_names=bound_widget_names(pack))
        if widget.read_only and widget.value.strip()
    ]
    fails = [f"{check.name}: {check.detail}" for check in clipping_scan(baked) if check.status == "FAIL"]
    assert not fails, (
        f"{_pack_id(pack_path)} maps ReadOnly widget(s) whose text is baked into the blank and "
        f"already clips BEFORE anything is filled:\n  " + "\n  ".join(fails) + "\n\nA widget that "
        "holds the form's own text is a banner or caption, not a line (P-007 class 1 — the AL-40 "
        "instruction panels and MO-1040 captions unmapped 2026-09-23). Read its /TU and /V off the "
        "blank, unmap it with a header note, and re-pin STATE_COMPUTED_READONLY in "
        "test_readonly_widget_mapping.py."
    )


# ---------------------------------------------------------------------------
# The AL-40 / MO-1040 regression, both halves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack_key", sorted(NOT_LINES_UNMAPPED), ids=lambda key: _pack_id(FORMPACKS / key))
def test_the_banner_keys_stay_unmapped_and_fill_form_refuses_them(pack_key: str, tmp_path: Path):
    """Offline: the pack half of PJ-02 cannot quietly come back."""
    pack = load_pack(FORMPACKS / pack_key)
    lines = {pack_field.line for pack_field in pack.fields}
    bound = bound_widget_names(pack)
    for banner in NOT_LINES_UNMAPPED[pack_key]:
        assert banner not in lines and banner not in bound, (
            f"{pack_key} maps {banner!r} again — a DOR banner, caption or checkbox frame, not a "
            f"taxpayer line (the pack header records its /V, /TU and geometry); remapped, a banner "
            f"FAILs P-001 on every real fill the moment verify cannot consult the blank"
        )
        # fill_form validates line keys before it opens the blank, so no PDF is needed.
        with pytest.raises(ValueError, match=r"unknown line key"):
            fill_form(pack, {banner: "x"}, tmp_path / "absent-blank.pdf", tmp_path / "out.pdf")


@pytest.mark.parametrize("pack_key", sorted(BANNERS_UNMAPPED), ids=lambda key: _pack_id(FORMPACKS / key))
def test_al_and_mo_one_line_fills_verify_clean_in_both_paths(pack_key: str, tmp_path: Path):
    """The exact PJ-02 reproduction, on today's packs: zero clipping FAILs, form AND filing."""
    pack = load_pack(FORMPACKS / pack_key)
    blank = _cached_blank(pack)
    filled = tmp_path / "first_name_only.pdf"
    fill_form(pack, {FIRST_NAME_LINE[pack_key]: "Pat"}, blank, filled)
    form_report = verify_form(pack, filled)
    assert not _clip_fails(form_report)
    assert form_report.ok is True  # the whole single-form gate, as at HEAD before the widening
    filing_report = verify_filing([FilingItem(form_key="state_return", pack=pack, pdf_path=filled)])
    assert not _clip_fails(filing_report)
    assert {check.id: check.status for check in filing_report.pitfall_checks}["P-001"] == "PASS"


@pytest.mark.parametrize("pack_key", sorted(BANNERS_UNMAPPED), ids=lambda key: _pack_id(FORMPACKS / key))
def test_the_verifier_alone_absorbs_remapped_banners_and_the_blank_is_why(
    pack_key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The verifier half, independent of the pack cleanup — plus the control that proves the mechanism."""
    banners = BANNERS_UNMAPPED[pack_key]
    remapped = _with_banners_remapped(load_pack(FORMPACKS / pack_key), banners)
    blank = _cached_blank(remapped)
    filled = tmp_path / "first_name_only.pdf"
    fill_form(remapped, {FIRST_NAME_LINE[pack_key]: "Pat"}, blank, filled)

    # With the pinned blank cached: every banner still holds the blank's own
    # text, so neither verify path flags one.
    assert not _clip_fails(verify_form(remapped, filled))
    assert not _clip_fails(verify_filing([FilingItem(form_key="state_return", pack=remapped, pdf_path=filled)]))

    # Control — the same PDF with the blank cache emptied: verify can no longer
    # tell the DOR's text from the filler's, so EXACTLY the banners FAIL (the
    # widened scan's regression, reproduced), and each one names the fix.
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "empty-cache"))
    blind = [check for check in verify_form(remapped, filled).clipping if check.status == "FAIL"]
    assert {check.name for check in blind} == set(banners)
    assert all("run fetch_blank" in check.detail for check in blind)


def test_a_banner_the_fill_did_rewrite_is_still_scanned(tmp_path: Path):
    """Positive control on the real AL-40 blank: the skip is 'unchanged', never 'banner'."""
    remapped = _with_banners_remapped(load_pack(FORMPACKS / AL40_2023), _AL_BANNERS)
    blank = _cached_blank(remapped)
    filled = tmp_path / "banner_rewritten.pdf"
    fill_form(remapped, {"FIRSTNAME": "Pat", "Instructions": "SEE ATTACHED STATEMENT " * 20}, blank, filled)
    fails = {check.name: check for check in verify_form(remapped, filled).clipping if check.status == "FAIL"}
    assert set(fails) == {"Instructions"}  # the rewritten panel only; the other eleven are the blank's
    assert "ReadOnly widget the pack maps" in fails["Instructions"].detail
    assert "fetch_blank" not in fails["Instructions"].detail
