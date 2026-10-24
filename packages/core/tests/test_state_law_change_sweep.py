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

from taxfill_core.knowledge import LawChangesChecked, StateKnowledge, load_state_knowledge
from taxfill_core.knowledge_v2 import SCHEMA_VERSION, v1_mapping

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


def check_law_changes_recorded(raw: dict, st: str, year: int) -> None:
    """The per-pack body of test_every_ty2024_plus_state_pack_records_its_law_changes over a raw pack mapping."""
    where = f"{st}/{year}"
    v2 = raw.get("schema_version") == SCHEMA_VERSION
    # Phase K JK24 (2026-10-24): a schema v2 pack records them as law_changes {changes, checked} (StateKnowledgeV2
    # holds it to this rule at load); read the v1 projection the consumers read. A v1 mapping passes unchanged.
    raw = v1_mapping(raw)
    assert "effective_law_changes" in raw, (
        f"{where}: record the year's law changes — read the booklet's What's New section and list each delta, or "
        f"write `effective_law_changes: []` with a `law_changes_checked` record naming the section read")
    # What load_state_knowledge returns, minus the path checks (a v2 mapping was validated by the projection above).
    pack = StateKnowledge.model_validate(raw if v2 else {k: v for k, v in raw.items() if k != "schema_version"})
    checked = pack.law_changes_checked
    if not pack.effective_law_changes:
        assert checked is not None, f"{where}: an empty list must say which section was read (law_changes_checked)"
    if checked is not None:
        assert checked.finding.strip(), f"{where}: law_changes_checked.finding is empty"
        others = _urls({k: v for k, v in raw.items() if k != "law_changes_checked"})
        assert checked.citation.url in others, (
            f"{where}: law_changes_checked cites {checked.citation.url}, which the pack cites nowhere else")


@pytest.mark.parametrize("path", PACKS, ids=lambda p: f"{p.parent.name}-{p.stem}")
def test_every_ty2024_plus_state_pack_records_its_law_changes(path: Path):
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    check_law_changes_recorded(raw, path.parent.name, int(path.stem))
    # The shipped pack also loads through the real loader (path checks included).
    load_state_knowledge(path.parent.name, int(path.stem), base_dir=REPO / "knowledge")


def test_law_changes_checked_is_a_typed_record():
    ok = {"checked": "2026-09-28", "finding": "What's New read in full: no change.",
          "citation": {"source": "2025 booklet, What's New", "url": "https://tax.example.gov/booklet.pdf"}}
    assert LawChangesChecked.model_validate(ok).checked.year == 2026
    for bad in ({**ok, "checked": "last week"}, {**ok, "extra": 1},
                {**ok, "citation": {"source": "a blog", "url": "https://blog.example.com/x"}}):
        with pytest.raises(ValidationError):
            LawChangesChecked.model_validate(bad)
