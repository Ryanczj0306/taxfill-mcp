"""Per-state source blocks for the freshness protocol, built from one state knowledge pack's own citations.

Every citation URL in a state pack was web-verified when the pack was authored, so a block built here invents nothing:
it only regroups the pack's verified (source, url) pairs by the pack block each one backs. Non-government hosts (a DOR
occasionally serves a PDF from a CDN) are dropped by the same rule the typed Citation enforces.

Two callers share this one builder:

* ``scripts/assemble_state_sources.py`` writes each state's NEWEST pack into ``knowledge/sources_states.yaml`` (the
  registry for the newest year and for any year without a pack, such as a planning year);
* ``get_sources`` builds the block for an OLDER year from that year's own pack, so a TY2024 question about a state gets
  the TY2024 booklet and not the TY2025 one (Phase K JK27, 2026-10-16; before it every year got the newest pack's URLs).

Phase K JK20 (2026-10-24): a TY2025-and-later pack carries a top-level ``sources`` table (one entry per distinct
(topic, url), every distinct inline description kept; generated once by scripts/hoist_state_sources.py), and the
builder reads it when present, so a citation outlives the block that carried it: JK22 (2026-10-24) dropped the TY2025
residency and filing_requirement blocks, and their citations are in the table alone.
A pack without the table (TY2023 / TY2024, frozen) is walked as before. Either way a URL cited under one topic with
several descriptions is ONE registry entry whose ``answers`` joins them (before JK20 the first won and the rest were
dropped: 89 / 222 / 328 descriptions in the 2023 / 2024 / 2025 packs).
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from taxfill_core.knowledge import validate_gov_url

__all__ = [
    "ANSWERS_SEPARATOR",
    "BLOCK_TO_TOPIC",
    "FALLBACK_TOPIC",
    "TOPIC_ID_PREFIX",
    "hoist_sources",
    "is_gov",
    "merge_descriptions",
    "source_entries",
    "state_block",
    "walk_citations",
]

# Which pack block a citation sits under decides the registry topic it backs.
BLOCK_TO_TOPIC = {
    "citation": "forms_and_instructions",
    "all_citations": "forms_and_instructions",
    "tax": "tax_rates_and_brackets",
    "credits": "credits",
    "credits_verification": "credits",
    "mailing_addresses": "filing_logistics",
    "deadlines": "filing_logistics",
    "payment": "filing_logistics",
    "amended_return": "filing_logistics",
    "filing_requirement": "filing_logistics",
    "convenience_rule": "remote_work_sourcing",
    "effective_law_changes": "law_changes",
    "law_changes_checked": "law_changes",
}
FALLBACK_TOPIC = "forms_and_instructions"
# The id prefix of a ``sources`` table entry per registry topic (scripts/hoist_state_sources.py numbers them per topic).
TOPIC_ID_PREFIX = {
    "forms_and_instructions": "forms",
    "tax_rates_and_brackets": "rates",
    "credits": "credits",
    "filing_logistics": "logistics",
    "remote_work_sourcing": "remote",
    "law_changes": "law",
}
# Joins the descriptions of one (topic, url) into the registry entry's ``answers``. It carries no word, so it adds no
# routing token, and no description contains it (some contain ' | ': JK28's forms.citations entries end with an
# all_citations description after one), so the get_sources scorer can tell where an entry's first description ends.
ANSWERS_SEPARATOR = " || "

_IRS_STATE_DIRECTORY = {
    "url": "https://www.irs.gov/businesses/small-businesses-self-employed/state-government-websites",
    "answers": (
        "IRS directory of every state government / tax agency website — the fallback channel "
        "when a state DOR reorganizes and a cited URL moves."
    ),
    "cadence": "standing page",
}


def is_gov(url: str) -> bool:
    try:
        validate_gov_url(url)
        return True
    except ValueError:
        return False


def walk_citations(node: Any, top_key: str | None = None) -> Iterator[tuple[str | None, dict]]:
    """Yield (top_level_block, {source, url}) for every citation-shaped dict."""
    if isinstance(node, dict):
        if isinstance(node.get("source"), str) and isinstance(node.get("url"), str):
            yield top_key, node
        for key, value in node.items():
            yield from walk_citations(value, top_key if top_key is not None else key)
    elif isinstance(node, list):
        for item in node:
            yield from walk_citations(item, top_key)


def hoist_sources(pack: dict) -> list[dict]:
    """The pack's .gov inline citations as ``sources`` rows: one per distinct (topic, url), in first-seen walk order.

    Each row is ``{topic, url, descriptions}``: every distinct inline ``source`` text (stripped, verbatim) in walk
    order. Non-government URLs are left out, as the registry always dropped them. A ``sources`` table already in the
    pack is not walked (its rows carry no ``source`` key), so hoisting is idempotent.
    """
    rows: dict[tuple[str, str], dict] = {}
    for block, cite in walk_citations({k: v for k, v in pack.items() if k != "sources"}):
        url = cite["url"].strip()
        if not is_gov(url):
            continue
        topic = BLOCK_TO_TOPIC.get(block or "", FALLBACK_TOPIC)
        row = rows.setdefault((topic, url), {"topic": topic, "url": url, "descriptions": []})
        text = cite["source"].strip()
        if text not in row["descriptions"]:
            row["descriptions"].append(text)
    return list(rows.values())


def source_entries(pack: dict) -> list[dict]:
    """The rows the registry block is built from: the pack's ``sources`` table when it has one, else the inline walk."""
    table = pack.get("sources")
    if isinstance(table, list) and table:
        return [
            {"topic": row["topic"], "url": row["url"].strip(), "descriptions": [d.strip() for d in row["descriptions"]]}
            for row in table
            if is_gov(row["url"].strip())
        ]
    return hoist_sources(pack)


def merge_descriptions(descriptions: list[str]) -> str:
    """One ``answers`` text for a (topic, url) cited with several descriptions: the first first, joined by ' || '.

    A description already contained word for word in the text so far adds nothing and is skipped: the JK28
    forms.citations entries end (after ' | ') with the all_citations description of the same URL, so without this
    the merged text would carry that description twice.
    """
    merged = ""
    for text in descriptions:
        if not text or re.search(rf"(?<!\w){re.escape(text)}(?!\w)", merged):
            continue
        merged = f"{merged}{ANSWERS_SEPARATOR}{text}" if merged else text
    return merged


def state_block(st: str, year: int, pack: dict, *, newest: bool) -> dict | None:
    """The registry block ({by_topic, change_channels}) for one state pack, or None when it cites no .gov URL.

    ``newest`` picks the wording: the generated registry says the pack is the newest shipped one and that any NEWER
    year is re-resolved at the same URL family; a block for an older year says whose citations these are instead.
    """
    code = st.upper()
    if newest:
        cadence = (
            f"annual (per tax year; the newest shipped {code} pack covers "
            f"{year} — for any newer year re-resolve at this URL family and cite)"
        )
    else:
        cadence = (
            f"annual (per tax year; the shipped {code} {year} pack's own citation — for another year "
            f"re-resolve at this URL family and cite)"
        )
    by_topic: dict[str, list] = {}
    for row in source_entries(pack):
        by_topic.setdefault(row["topic"], []).append(
            {"url": row["url"], "answers": merge_descriptions(row["descriptions"]), "cadence": cadence}
        )
    if not by_topic:
        return None
    primary = pack.get("citation") or {}
    change_channels = []
    if isinstance(primary.get("url"), str) and is_gov(primary["url"]):
        if newest:
            answers = (
                f"The newest shipped {code} pack's primary authority (TY{year}). A revision "
                f"newer than {year} published by the state supersedes the shipped pack — treat its "
                f"appearance as the staleness signal."
            )
        else:
            answers = (
                f"The shipped {code} {year} pack's primary authority (TY{year}). A re-issue of this "
                f"{year} document by the state supersedes what the pack shipped — treat its appearance as "
                f"the staleness signal."
            )
        change_channels.append({"url": primary["url"].strip(), "answers": answers, "cadence": "annual (each filing season)"})
    change_channels.append(dict(_IRS_STATE_DIRECTORY))
    return {"by_topic": dict(sorted(by_topic.items())), "change_channels": change_channels}
