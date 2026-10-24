"""The state packs' ``sources`` table and the merged source registry (Phase K JK20, 2026-10-24).

JK22 drops never-read blocks from the TY2025 state packs, and the source registry was built only by walking the
citations inside those blocks, so dropping a block would have shrunk get_sources. Every TY2025 pack now carries a
top-level ``sources`` table (scripts/hoist_state_sources.py generated it once), and
``taxfill_core.state_sources.state_block`` reads it. These tests hold:

* CONSISTENCY: the table and the inline citations agree, both ways (a new citation goes inline AND into the table);
* PARITY: the registry block built from the table equals the one built by walking the inline citations;
* MERGE: a URL cited under one topic with several descriptions is one registry entry whose answers joins them
  (before JK20 the first description won and the rest were dropped);
* the typed model rejects a malformed table at load.

The routing side (the merged text must not steal a neighbour's query) is test_state_source_routes.py.
"""
from __future__ import annotations

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
    # Every table row and description is backed by an inline citation. JK22 relaxes this half: once it drops a
    # block, the rows of that block's citations stay in the table with no inline citation left (that is the point
    # of the table), and this assertion then allows rows whose block JK22 dropped.
    inline = {(topic, url): set() for topic, url, _ in _inline(raw)}
    for topic, url, source in _inline(raw):
        inline[(topic, url)].add(source)
    orphans = [
        f"{row['id']} {row['topic']} {row['url']}: {text[:80]!r}"
        for row in table
        for text in row["descriptions"]
        if text not in inline.get((row["topic"], row["url"]), set())
    ]
    assert not orphans, f"{st} {year}: `sources` rows no inline citation backs:\n  " + "\n  ".join(orphans)


@pytest.mark.parametrize("st,year", TABLE_PACKS, ids=[f"{st}-{year}" for st, year in TABLE_PACKS])
def test_the_block_built_from_the_table_equals_the_walked_block(st: str, year: int):
    raw = _raw(st, year)
    walked = {k: v for k, v in raw.items() if k != "sources"}
    for newest in (True, False):
        from_table = state_block(st, year, raw, newest=newest)
        from_walk = state_block(st, year, walked, newest=newest)
        assert yaml.safe_dump(from_table, sort_keys=False) == yaml.safe_dump(from_walk, sort_keys=False)
    # And the table's rows are exactly what the walk hoists (order, topics, urls, descriptions).
    assert [{k: v for k, v in row.items() if k != "id"} for row in raw["sources"]] == hoist_sources(walked)


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
