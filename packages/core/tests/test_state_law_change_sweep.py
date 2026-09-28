"""Phase J JS2 — every TY2024+ state knowledge pack records its year's law changes, or that its booklet had none.

An absent ``effective_law_changes`` key and an empty list used to look the same: "no delta" and "nobody looked". The
sweep read each year's own What's New / legislative-changes section (or, where the booklet has none, compared its
lines with the prior year's). A pack with an empty list carries ``law_changes_checked`` naming the section it read.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.knowledge import LawChangesChecked, load_state_knowledge

REPO = Path(__file__).resolve().parents[3]
STATES = REPO / "knowledge" / "states"
PACKS = sorted(p for p in STATES.glob("*/*.yaml") if p.stem.isdigit() and int(p.stem) >= 2024)


def _urls(node) -> set[str]:
    if isinstance(node, dict):
        return {v.strip() for k, v in node.items() if k == "url" and isinstance(v, str)} | {
            u for k, v in node.items() if k != "url" for u in _urls(v)}
    if isinstance(node, list):
        return {u for item in node for u in _urls(item)}
    return set()


def test_the_sweep_covers_every_2024_and_2025_pack():
    assert len([p for p in PACKS if p.stem in ("2024", "2025")]) == 84


@pytest.mark.parametrize("path", PACKS, ids=lambda p: f"{p.parent.name}-{p.stem}")
def test_every_ty2024_plus_state_pack_records_its_law_changes(path: Path):
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    where = f"{path.parent.name}/{path.stem}"
    assert "effective_law_changes" in raw, (
        f"{where}: record the year's law changes — read the booklet's What's New section and list each delta, or "
        f"write `effective_law_changes: []` with a `law_changes_checked` record naming the section read")
    pack = load_state_knowledge(path.parent.name, int(path.stem), base_dir=REPO / "knowledge")
    checked = pack.law_changes_checked
    if not pack.effective_law_changes:
        assert checked is not None, f"{where}: an empty list must say which section was read (law_changes_checked)"
    if checked is not None:
        assert checked.finding.strip(), f"{where}: law_changes_checked.finding is empty"
        others = _urls({k: v for k, v in raw.items() if k != "law_changes_checked"})
        assert checked.citation.url in others, (
            f"{where}: law_changes_checked cites {checked.citation.url}, which the pack cites nowhere else")


def test_law_changes_checked_is_a_typed_record():
    ok = {"checked": "2026-09-28", "finding": "What's New read in full: no change.",
          "citation": {"source": "2025 booklet, What's New", "url": "https://tax.example.gov/booklet.pdf"}}
    assert LawChangesChecked.model_validate(ok).checked.year == 2026
    for bad in ({**ok, "checked": "last week"}, {**ok, "extra": 1},
                {**ok, "citation": {"source": "a blog", "url": "https://blog.example.com/x"}}):
        with pytest.raises(ValidationError):
            LawChangesChecked.model_validate(bad)
