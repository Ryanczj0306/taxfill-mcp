"""Per-state source blocks for the freshness protocol, built from one state knowledge pack's own citations.

Every citation URL in a state pack was web-verified when the pack was authored, so a block built here invents nothing:
it only regroups the pack's verified (source, url) pairs by the pack block each one backs. Non-government hosts (a DOR
occasionally serves a PDF from a CDN) are dropped by the same rule the typed Citation enforces.

Two callers share this one builder:

* ``scripts/assemble_state_sources.py`` writes each state's NEWEST pack into ``knowledge/sources_states.yaml`` (the
  registry for the newest year and for any year without a pack, such as a planning year);
* ``get_sources`` builds the block for an OLDER year from that year's own pack, so a TY2024 question about a state gets
  the TY2024 booklet and not the TY2025 one (Phase K JK27, 2026-10-16; before it every year got the newest pack's URLs).
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from taxfill_core.knowledge import validate_gov_url

__all__ = ["BLOCK_TO_TOPIC", "FALLBACK_TOPIC", "is_gov", "state_block", "walk_citations"]

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
    seen: set[tuple[str, str]] = set()
    for block, cite in walk_citations(pack):
        url = cite["url"].strip()
        if not is_gov(url):
            continue
        topic = BLOCK_TO_TOPIC.get(block or "", FALLBACK_TOPIC)
        if (topic, url) in seen:
            continue
        seen.add((topic, url))
        by_topic.setdefault(topic, []).append({"url": url, "answers": cite["source"].strip(), "cadence": cadence})
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
