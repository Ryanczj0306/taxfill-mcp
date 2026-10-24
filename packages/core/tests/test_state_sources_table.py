"""The state packs' ``sources`` table and the merged source registry (Phase K JK20, 2026-10-24).

JK22 drops never-read blocks from the TY2025 state packs, and the source registry was built only by walking the
citations inside those blocks, so dropping a block would have shrunk get_sources. Every TY2025 pack now carries a
top-level ``sources`` table (scripts/hoist_state_sources.py generated it once), and
``taxfill_core.state_sources.state_block`` reads it. These tests hold:

* CONSISTENCY: the table and the inline citations agree, both ways (a new citation goes inline AND into the table),
  except for the descriptions whose block JK22 dropped (``JK22_DROPPED``): they stay in the table with no inline
  citation left;
* PARITY: the registry block built from the table equals the one built by walking the inline citations (with the
  ``JK22_DROPPED`` descriptions set aside);
* MERGE: a URL cited under one topic with several descriptions is one registry entry whose answers joins them
  (before JK20 the first description won and the rest were dropped);
* the typed model rejects a malformed table at load.

The routing side (the merged text must not steal a neighbour's query) is test_state_source_routes.py.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.knowledge import StateKnowledge, load_state_knowledge
from taxfill_core.state_sources import (
    ANSWERS_SEPARATOR,
    BLOCK_TO_TOPIC,
    FALLBACK_TOPIC,
    hoist_sources,
    merge_descriptions,
    state_block,
    walk_citations,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STATES = REPO_ROOT / "knowledge" / "states"
FIRST_TABLE_YEAR = 2025


def _packs(min_year: int = 0) -> list[tuple[str, int]]:
    return sorted(
        (p.parent.name, int(p.stem)) for p in STATES.glob("*/*.yaml") if p.stem.isdigit() and int(p.stem) >= min_year
    )


TABLE_PACKS = _packs(FIRST_TABLE_YEAR)
ALL_PACKS = _packs()

# Phase K JK22 (2026-10-24): the table descriptions whose ONLY inline citation sat in a block JK22 dropped from the
# TY2025 packs (residency, filing_requirement: no tool reads either, and the JK21 goldens did not move without them).
# The table keeps them, so get_sources still lists every (topic, url) and description; no inline citation backs them
# any more. Exactly these, frozen: (state, row id) -> (the dropped block, the first 16 hex of the description's
# sha256); the comment shows how the description starts (a prefix alone is not unique in a row).
JK22_DROPPED_YEAR = 2025
JK22_DROPPED = {
    ("ca", "forms-1"): ("residency", "7536034e681b65e1"),  # FTB Publication 1031 (2025), Guidelines for Determining Res
    ("ca", "logistics-1"): ("filing_requirement", "90bc51046be4f360"),  # 2025 Personal Income Tax Booklet (Form 540), "
    ("ct", "forms-2"): ("residency", "45cff402e1b9d810"),  # CT DRS Resident Income Tax — Tax Information (2025 edition:
    ("ct", "logistics-1"): ("filing_requirement", "b59a3bf980e03d04"),  # CT DRS Resident Income Tax — Tax Information,
    ("dc", "logistics-1"): ("filing_requirement", "fa008b7fae74faca"),  # DC OTR — 2025 D-40 booklet, "New for 2025 Inco
    ("de", "forms-1"): ("residency", "bdcd400ea12dd208"),  # DE Division of Revenue - 2025 Form PIT-RES Instructions, "W
    ("de", "logistics-1"): ("filing_requirement", "dbf56f5311908c33"),  # DE Division of Revenue - 2025 Form PIT-RES Ins
    ("hi", "forms-2"): ("residency", "7ad947083c91679e"),  # Hawaii 2025 N-11 Resident Income Tax Instructions — "Reside
    ("hi", "logistics-1"): ("filing_requirement", "a55a5e443c1edc18"),  # Hawaii 2025 N-11 Resident Income Tax Instructi
    ("md", "forms-2"): ("residency", "65591e539bab3932"),  # 2025 Maryland State & Local Tax Forms & Instructions (Resid
    ("nj", "forms-1"): ("residency", "833f01991782c115"),  # 2025 NJ-1040 Resident Income Tax Return Instructions - Term
    ("oh", "forms-1"): ("residency", "830eb8eca5d914c6"),  # 2025 Ohio IT 1040 / SD 100 Instruction Booklet - 'Ohio Resi
    ("va", "forms-1"): ("residency", "bb860c5720f75f1c"),  # 2025 Form 760 Resident Individual Income Tax Instructions -
}


def _jk22_dropped(st: str, year: int, row: dict, text: str) -> bool:
    """Whether ``text`` of table ``row`` is one of the JK22_DROPPED descriptions."""
    hit = JK22_DROPPED.get((st, row["id"])) if year == JK22_DROPPED_YEAR else None
    return hit is not None and hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] == hit[1]


def _table_without_jk22_dropped(st: str, year: int, table: list[dict]) -> list[dict]:
    """The table rows as hoist_sources shapes them, minus the JK22_DROPPED descriptions (and any row left empty)."""
    out = []
    for row in table:
        kept = [text for text in row["descriptions"] if not _jk22_dropped(st, year, row, text)]
        if kept:
            out.append({"topic": row["topic"], "url": row["url"], "descriptions": kept})
    return out


def _raw(st: str, year: int) -> dict:
    return yaml.safe_load((STATES / st / f"{year}.yaml").read_text(encoding="utf-8"))


def _inline(raw: dict) -> list[tuple[str, str, str]]:
    """(topic, url, source) for every .gov inline citation, the way the registry maps it."""
    from taxfill_core.state_sources import is_gov

    out = []
    for block, cite in walk_citations({k: v for k, v in raw.items() if k != "sources"}):
        url = cite["url"].strip()
        if is_gov(url):
            out.append((BLOCK_TO_TOPIC.get(block or "", FALLBACK_TOPIC), url, cite["source"].strip()))
    return out


def test_every_ty2025_and_later_pack_has_a_sources_table():
    assert len(TABLE_PACKS) >= 42
    missing = [f"{st} {year}" for st, year in TABLE_PACKS if not _raw(st, year).get("sources")]
    assert not missing, (
        f"TY{FIRST_TABLE_YEAR}+ packs without a `sources` table: {missing} — run "
        f"python scripts/hoist_state_sources.py --year <year> <st>"
    )


def test_ty2023_and_ty2024_packs_stay_frozen_without_a_table():
    # TY2023 / TY2024 stay schema v1 (ROADMAP K-K); their registry block is still built by walking the citations.
    have = [f"{st} {year}" for st, year in ALL_PACKS if year < FIRST_TABLE_YEAR and "sources" in _raw(st, year)]
    assert not have, have


@pytest.mark.parametrize("st,year", TABLE_PACKS, ids=[f"{st}-{year}" for st, year in TABLE_PACKS])
def test_the_sources_table_and_the_inline_citations_agree(st: str, year: int):
    raw = _raw(st, year)
    table = raw["sources"]
    rows = {(row["topic"], row["url"]): row for row in table}
    # Every inline .gov citation is in the table: same topic and url, its text among the descriptions.
    absent = []
    for topic, url, source in _inline(raw):
        row = rows.get((topic, url))
        if row is None or source not in row["descriptions"]:
            absent.append(f"{topic} {url}: {source[:80]!r}")
    assert not absent, (
        f"{st} {year}: inline citations missing from the `sources` table (add each one there too, same topic, url "
        f"and text):\n  " + "\n  ".join(absent)
    )
    # Every table row and description is backed by an inline citation, except exactly the JK22_DROPPED ones: JK22
    # (2026-10-24) dropped the residency and filing_requirement blocks, and their citations stay in the table with no
    # inline citation left (that is the point of the table). Only this half is relaxed, and only for those rows.
    inline = {(topic, url): set() for topic, url, _ in _inline(raw)}
    for topic, url, source in _inline(raw):
        inline[(topic, url)].add(source)
    unbacked = [(row, text) for row in table for text in row["descriptions"]
                if text not in inline.get((row["topic"], row["url"]), set())]
    orphans = [
        f"{row['id']} {row['topic']} {row['url']}: {text[:80]!r}"
        for row, text in unbacked
        if not _jk22_dropped(st, year, row, text)
    ]
    assert not orphans, f"{st} {year}: `sources` rows no inline citation backs:\n  " + "\n  ".join(orphans)
    # And each JK22_DROPPED entry of this pack is still in the table and still unbacked (a stale entry fails here).
    expected = sorted(rid for (s, rid) in JK22_DROPPED if s == st and year == JK22_DROPPED_YEAR)
    assert sorted(row["id"] for row, text in unbacked if _jk22_dropped(st, year, row, text)) == expected


@pytest.mark.parametrize("st,year", TABLE_PACKS, ids=[f"{st}-{year}" for st, year in TABLE_PACKS])
def test_the_block_built_from_the_table_equals_the_walked_block(st: str, year: int):
    raw = _raw(st, year)
    walked = {k: v for k, v in raw.items() if k != "sources"}
    hoisted = hoist_sources(walked)
    if any(s == st and year == JK22_DROPPED_YEAR for s, _ in JK22_DROPPED):
        # JK22 (2026-10-24): with the dropped blocks' descriptions set aside, the table holds exactly what the walk
        # hoists: same (topic, url) rows, same descriptions in the same order. Row order can differ (a dropped block
        # cited a url first), so the rows are compared by key; the registry follows the table's order.
        rest = _table_without_jk22_dropped(st, year, raw["sources"])
        assert len(rest) == len(hoisted)
        assert {(r["topic"], r["url"]): r["descriptions"] for r in rest} == {
            (r["topic"], r["url"]): r["descriptions"] for r in hoisted
        }
        return
    for newest in (True, False):
        from_table = state_block(st, year, raw, newest=newest)
        from_walk = state_block(st, year, walked, newest=newest)
        assert yaml.safe_dump(from_table, sort_keys=False) == yaml.safe_dump(from_walk, sort_keys=False)
    # And the table's rows are exactly what the walk hoists (order, topics, urls, descriptions).
    assert [{k: v for k, v in row.items() if k != "id"} for row in raw["sources"]] == hoisted


@pytest.mark.parametrize("st,year", TABLE_PACKS, ids=[f"{st}-{year}" for st, year in TABLE_PACKS])
def test_the_typed_model_loads_the_table(st: str, year: int):
    pack = load_state_knowledge(st, year, base_dir=REPO_ROOT / "knowledge")
    assert pack.sources and len({row.id for row in pack.sources}) == len(pack.sources)


# ── MERGE ──────────────────────────────────────────────────────────────────────────────────────────────────────────

_BOOKLET = "https://www.revenue.example.gov/2025-booklet.pdf"
_PACK = {
    "jurisdiction": "states/zz",
    "tax_year": 2025,
    "conforms_to_federal_treaties": True,
    "citation": {"source": "2025 booklet — tax table (p. 30)", "url": _BOOKLET},
    "all_citations": [{"source": "2025 booklet — Where To File (p. 12)", "url": _BOOKLET}],
    "forms": {"citations": {"part_year": {"source": "2025 booklet — Part-year residents (p. 4)", "url": _BOOKLET}}},
    "deadlines": {"citation": {"source": "2025 booklet — When To File (p. 5)", "url": _BOOKLET}},
    "payment": {"citation": {"source": "2025 booklet — When To File (p. 5)", "url": _BOOKLET}},
    "residency": {"citation": {"source": "A private guide", "url": "https://www.example.com/guide"}},
}


def test_a_url_cited_twice_under_one_topic_is_one_entry_that_keeps_every_description():
    block = state_block("zz", 2025, _PACK, newest=True)
    forms = block["by_topic"]["forms_and_instructions"]
    # citation, all_citations and forms.citations map to one topic and one URL: one entry, first description first.
    assert [e["url"] for e in forms] == [_BOOKLET]
    assert forms[0]["answers"] == ANSWERS_SEPARATOR.join([
        "2025 booklet — tax table (p. 30)",
        "2025 booklet — Where To File (p. 12)",
        "2025 booklet — Part-year residents (p. 4)",
    ])
    # The same description cited from two blocks of one topic is kept once; the non-.gov citation is dropped.
    assert block["by_topic"]["filing_logistics"] == [
        {"url": _BOOKLET, "answers": "2025 booklet — When To File (p. 5)", "cadence": forms[0]["cadence"]}
    ]
    assert "example.com" not in yaml.safe_dump(block)


def test_the_table_path_merges_the_same_way():
    table = [
        {"id": "forms-1", "topic": "forms_and_instructions", "url": _BOOKLET,
         "descriptions": ["2025 booklet — tax table (p. 30)", "2025 booklet — Where To File (p. 12)"]},
    ]
    block = state_block("zz", 2025, {**_PACK, "sources": table}, newest=False)
    # The table wins over the inline walk: its rows, merged, are the whole registry block.
    assert list(block["by_topic"]) == ["forms_and_instructions"]
    assert block["by_topic"]["forms_and_instructions"][0]["answers"] == (
        "2025 booklet — tax table (p. 30) || 2025 booklet — Where To File (p. 12)"
    )


def test_a_description_already_quoted_word_for_word_is_not_repeated():
    # JK28's forms.citations entries end with the all_citations description of the same URL after ' | '.
    first = "Form X instructions, 'Who must file' (p. 3) | 2025 booklet — Where To File (p. 12)"
    assert merge_descriptions([first, "2025 booklet — Where To File (p. 12)"]) == first
    # Containment is whole-word: "Form 4" is not inside "Form 40".
    assert merge_descriptions(["Form 40 booklet", "Form 4"]) == "Form 40 booklet || Form 4"
    assert merge_descriptions(["one"]) == "one"


def test_hoisting_is_idempotent():
    rows = hoist_sources(_PACK)
    assert hoist_sources({**_PACK, "sources": [{"id": "forms-1", **row} for row in rows]}) == rows


# ── the typed model rejects a malformed table ─────────────────────────────────────────────────────────────────────

_ROW = {"id": "forms-1", "topic": "forms_and_instructions", "url": _BOOKLET, "descriptions": ["2025 booklet"]}


@pytest.mark.parametrize(
    "rows,message",
    [
        ([_ROW, {**_ROW, "url": _BOOKLET + "?2"}], "id 'forms-1' is used twice"),
        ([_ROW, {**_ROW, "id": "forms-2"}], "has two rows"),
        ([{**_ROW, "topic": "residency"}], "is not a registry topic"),
        ([{**_ROW, "url": "https://www.example.com/booklet.pdf"}], "official US government host"),
        ([{**_ROW, "descriptions": []}], "at least 1 item"),
        ([{**_ROW, "descriptions": ["  "]}], "must be non-empty"),
        ([{**_ROW, "id": "Forms 1"}], "should match pattern"),
        ([{**_ROW, "source": "stray"}], "Extra inputs are not permitted"),
    ],
)
def test_a_malformed_sources_table_fails_at_load(rows, message):
    with pytest.raises(ValidationError, match=message):
        StateKnowledge.model_validate({**_PACK, "sources": rows})
