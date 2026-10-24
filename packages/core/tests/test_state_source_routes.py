"""Neighbour theft in the state source registry: where get_sources routes a fixed query set (Phase K JK20, 2026-10-24).

get_sources scores a query against each topic's key and the joined ``answers`` text (taxfill_core.sources
``_score_topic``), so longer answers text can pull a query to another topic: the knowledge-gap pattern's
"neighbour theft". JK20 merged every description of a (topic, url) into one registry entry, which lengthened 176
of the 519 TY2025 entries (and the TY2023 / TY2024 blocks get_sources builds from their own packs). A route probe of
21 queries over all 126 state-years (2,646 routes) BEFORE and AFTER the merge found, with a plain merge, 360 moved
routes, 74 of them away from the topic that owns the subject: the catch-all booklet topic, cited from many blocks,
out-counted filing_logistics on repetition ("due date", "where to file", "mailing address"), and a stray word of a
joined description ("Who must FILE", "income EARNED while a resident", "Homestead ... TABLE 2") turned clean misses
into false matches. Both were prevented in the scorer: joined descriptions count only when the topic's text names
the whole query as one literal run of words, and the occurrence tiebreak reads each entry's primary description.
105 routes still moved, and in each one the topic that gained is one whose joined text names the whole query
(a canonical topic newly reached in 71 of them, e.g. "amended return" to filing_logistics, "child tax credit" to
credits). The pinned routes below are the post-JK20 table, so a future merge or scorer change cannot
move one silently.

A deliberate change regenerates the pin and is reviewed in its diff:
    python packages/core/tests/test_state_source_routes.py --write
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO_ROOT / "knowledge"
PIN = REPO_ROOT / "packages" / "core" / "tests" / "goldens" / "state_source_routes.json"

# The registry topic names as phrases, then the queries an agent typically sends.
QUERIES = (
    "forms and instructions",
    "tax rates and brackets",
    "credits",
    "filing logistics",
    "remote work sourcing",
    "law changes",
    "mailing address",
    "due date",
    "where to file",
    "part-year resident",
    "nonresident",
    "amended return",
    "estimated tax",
    "extension",
    "standard deduction",
    "personal exemption",
    "earned income credit",
    "child tax credit",
    "tax table",
    "withholding",
    "convenience of the employer",
)


@lru_cache(maxsize=1)
def current_routes() -> dict[str, dict[str, list[str]]]:
    """{query: {"<st>|<year>": ranked topics}} for every state pack year, as get_sources ranks them (misses left out)."""
    from taxfill_core.sources import _jurisdiction_block, _load_registry, _rank_topics

    registry = _load_registry(KNOWLEDGE)
    years = sorted(
        (d.name, int(p.stem)) for d in (KNOWLEDGE / "states").iterdir() if d.is_dir()
        for p in d.glob("*.yaml") if p.stem.isdigit()
    )
    routes: dict[str, dict[str, list[str]]] = {q: {} for q in QUERIES}
    for st, year in years:
        block, _ = _jurisdiction_block(registry, f"states/{st}", year, KNOWLEDGE)
        by_topic = block.get("by_topic") or {}
        for query in QUERIES:
            ranked = _rank_topics(by_topic, query)
            if ranked:
                routes[query][f"{st}|{year}"] = ranked
    return routes


def _pinned() -> dict[str, dict[str, list[str]]]:
    return json.loads(PIN.read_text(encoding="utf-8"))["routes"]


@pytest.mark.parametrize("query", QUERIES)
def test_the_pinned_state_routes_hold(query: str):
    pinned, now = _pinned().get(query, {}), current_routes()[query]
    moved = [
        f"{key}: {pinned.get(key, [])} -> {now.get(key, [])}"
        for key in sorted(set(pinned) | set(now))
        if pinned.get(key) != now.get(key)
    ]
    assert not moved, (
        f"get_sources({query!r}, <year>, 'states/<st>') moved in {len(moved)} state-years:\n  " + "\n  ".join(moved)
        + "\nA moved route must be justified (the topic's own text names the query) or prevented. If every move is "
        "justified, regenerate the pin with: python packages/core/tests/test_state_source_routes.py --write"
    )


# The canonical routes JK20 decided, each with its reason. These survive a regenerated pin only if still true.
CANONICAL = [
    # Prevented: the catch-all booklet topic out-counted the specific topic on repetition with a plain merge.
    ("sc", 2025, "due date", ["filing_logistics"]),
    ("ne", 2024, "due date", ["filing_logistics"]),
    ("il", 2025, "mailing address", ["filing_logistics", "forms_and_instructions", "law_changes"]),
    # Prevented: a stray word of a joined description turned a clean miss into a false match ("income earned while
    # a resident", "Homestead Property Tax Credit ... Table 2", "Who must file"). Idaho's registry text has no EITC
    # sentence. Michigan's merged credits text does ("a Michigan EITC equal to 30 percent of the taxpayer's federal
    # credit", MI-1040 line 28), but the literal whole-query rule does not read "EITC" as "earned income credit": a
    # known gap an alias could close later, pinned so that change is deliberate. Either way the agent is told to pick a
    # topic, not handed a wrong one.
    ("id", 2025, "earned income credit", []),
    ("mi", 2025, "earned income credit", []),
    ("mi", 2025, "tax table", []),
    ("il", 2023, "amended return", []),
    # Justified: the joined text names the subject. DC's 2025 booklet says the DC Child Tax Credit was repealed
    # (law_changes and the booklet entry); New York's IT-201-I entry names "Where to file" (p. 41), the same PDF as
    # the filing_logistics entry, so the top URL is unchanged.
    ("dc", 2025, "child tax credit", ["forms_and_instructions", "law_changes"]),
    ("ny", 2025, "where to file", ["forms_and_instructions"]),
    ("ky", 2024, "where to file", ["filing_logistics", "forms_and_instructions"]),
    # Unchanged: a JK28 description that joins two texts with ' | ' is ONE description (the merge joins with ' || '),
    # so it keeps its full weight and Hawaii's N-15 instructions still reach a standard-deduction question.
    ("hi", 2025, "standard deduction", ["forms_and_instructions", "tax_rates_and_brackets"]),
]


@pytest.mark.parametrize("st,year,query,topics", CANONICAL, ids=[f"{c[0]}-{c[1]}-{c[2]}" for c in CANONICAL])
def test_a_canonical_state_route(st: str, year: int, query: str, topics: list[str]):
    from taxfill_core.sources import get_sources

    result = get_sources(query, year, f"states/{st}")
    assert sorted({s.topic for s in result.sources}) == topics
    assert result.matched is bool(topics)


def test_the_merge_rule_is_inert_on_the_federal_registry():
    # The scorer reads a ' || '-joined answers text differently (JK20); no federal answers text carries one, so the
    # federal routes (pinned throughout test_sources.py) score exactly as before.
    from taxfill_core.state_sources import ANSWERS_SEPARATOR

    federal = yaml.safe_load((KNOWLEDGE / "sources.yaml").read_text(encoding="utf-8"))["federal"]["by_topic"]
    joined = [topic for topic, entries in federal.items() for e in entries if ANSWERS_SEPARATOR in e["answers"]]
    assert not joined, joined


def _write() -> None:
    PIN.write_text(
        json.dumps({"queries": list(QUERIES), "routes": current_routes()}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {PIN.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("usage: python packages/core/tests/test_state_source_routes.py --write")
    sys.path.insert(0, str(REPO_ROOT / "packages" / "core" / "src"))
    _write()


def test_a_whole_query_match_never_straddles_two_descriptions():
    """JK20 review (2026-10-24): the whole-query rule tests each joined description on its own."""
    from taxfill_core.sources import _names_whole_query
    from taxfill_core.state_sources import ANSWERS_SEPARATOR

    assert _names_whole_query("due date", f"Form 1 instructions: return due date (p. 3){ANSWERS_SEPARATOR}Schedule A")
    assert not _names_whole_query("due date", f"Payment is due{ANSWERS_SEPARATOR}Date of birth box (p. 1)")
    assert not _names_whole_query("where to file", f"Where to{ANSWERS_SEPARATOR}file the schedule")
