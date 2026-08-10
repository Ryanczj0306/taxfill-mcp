#!/usr/bin/env python
"""Generate knowledge/sources_states.yaml — the per-state source registry.

The freshness protocol (DEV_PLAN §7) was federal-only: ``sources.yaml`` shipped
``states: {}`` while 126 state knowledge packs were live, so
``get_sources(topic, year, "states/xx")`` matched nothing and a state year
newer than the newest pack (the TY2026 planning case) had no registered
authority to resolve against.

This script derives the registry EXCLUSIVELY from the state knowledge packs'
own citations (newest year per state): every citation URL in a pack was
web-verified when the pack was authored, so nothing here is invented — the
generator only regroups verified (source, url) pairs by topic. Non-government
hosts (a DOR occasionally serves a PDF from a CDN) are dropped by the same
rule the typed Citation enforces.

Usage:
    python scripts/assemble_state_sources.py          # write the file
    python scripts/assemble_state_sources.py --check  # CI: fail if stale
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
from taxfill_core.knowledge import validate_gov_url  # noqa: E402

STATES_DIR = REPO / "knowledge" / "states"
OUT = REPO / "knowledge" / "sources_states.yaml"

# Which pack block a citation sits under decides the registry topic it backs.
_BLOCK_TO_TOPIC = {
    "citation": "forms_and_instructions",
    "all_citations": "forms_and_instructions",
    "tax": "tax_rates_and_brackets",
    "credits": "credits",
    "credits_verification": "credits",
    "mailing_addresses": "filing_logistics",
    "deadlines": "filing_logistics",
    "payment": "filing_logistics",
    "filing_requirement": "filing_logistics",
    "convenience_rule": "remote_work_sourcing",
    "effective_law_changes": "law_changes",
}
_FALLBACK_TOPIC = "forms_and_instructions"

HEADER = """\
# GENERATED FILE — do not hand-edit. Regenerate with:
#     python scripts/assemble_state_sources.py
# (CI runs --check; test_sources.py fails if this file is stale.)
#
# Per-state source registry for the freshness protocol (DEV_PLAN section 7).
# Derived EXCLUSIVELY from each state's newest knowledge pack's own verified
# citations — no URL here was invented; the generator only regroups the
# (source, url) pairs the pack authors web-verified, keyed by the pack block
# each citation backs. Hand-authored overrides belong in sources.yaml's
# `states:` mapping, which wins over this file per state.
"""


def _is_gov(url: str) -> bool:
    try:
        validate_gov_url(url)
        return True
    except ValueError:
        return False


def _walk_citations(node, top_key: str | None = None):
    """Yield (top_level_block, {source, url}) for every citation-shaped dict."""
    if isinstance(node, dict):
        if isinstance(node.get("source"), str) and isinstance(node.get("url"), str):
            yield top_key, node
        for key, value in node.items():
            yield from _walk_citations(value, top_key if top_key is not None else key)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_citations(item, top_key)


def _newest_pack(state_dir: Path) -> tuple[int, dict] | None:
    years = sorted(
        (int(p.stem), p) for p in state_dir.glob("*.yaml") if p.stem.isdigit()
    )
    if not years:
        return None
    year, path = years[-1]
    return year, yaml.safe_load(path.read_text(encoding="utf-8"))


def build() -> dict:
    states: dict[str, dict] = {}
    for state_dir in sorted(STATES_DIR.iterdir()):
        if not state_dir.is_dir():
            continue
        newest = _newest_pack(state_dir)
        if newest is None:
            continue
        year, pack = newest
        st = state_dir.name
        by_topic: dict[str, list] = {}
        seen: set[tuple[str, str]] = set()
        for block, cite in _walk_citations(pack):
            url = cite["url"].strip()
            if not _is_gov(url):
                continue
            topic = _BLOCK_TO_TOPIC.get(block or "", _FALLBACK_TOPIC)
            if (topic, url) in seen:
                continue
            seen.add((topic, url))
            by_topic.setdefault(topic, []).append({
                "url": url,
                "answers": cite["source"].strip(),
                "cadence": (
                    f"annual (per tax year; the newest shipped {st.upper()} pack covers "
                    f"{year} — for any newer year re-resolve at this URL family and cite)"
                ),
            })
        if not by_topic:
            continue
        primary = pack.get("citation") or {}
        change_channels = []
        if isinstance(primary.get("url"), str) and _is_gov(primary["url"]):
            change_channels.append({
                "url": primary["url"].strip(),
                "answers": (
                    f"The newest shipped {st.upper()} pack's primary authority (TY{year}). A revision "
                    f"newer than {year} published by the state supersedes the shipped pack — treat its "
                    f"appearance as the staleness signal."
                ),
                "cadence": "annual (each filing season)",
            })
        change_channels.append({
            "url": "https://www.irs.gov/businesses/small-businesses-self-employed/state-government-websites",
            "answers": (
                "IRS directory of every state government / tax agency website — the fallback channel "
                "when a state DOR reorganizes and a cited URL moves."
            ),
            "cadence": "standing page",
        })
        states[st] = {"by_topic": dict(sorted(by_topic.items())), "change_channels": change_channels}
    return {"states": states}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail (exit 1) if the committed file is stale")
    args = ap.parse_args()

    text = HEADER + yaml.dump(build(), sort_keys=False, allow_unicode=True, width=110)
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print(f"STALE: {OUT} does not match the packs — regenerate with scripts/assemble_state_sources.py")
            return 1
        print(f"{OUT.name} is current ({len(yaml.safe_load(text)['states'])} states)")
        return 0
    OUT.write_text(text, encoding="utf-8")
    n = len(yaml.safe_load(text)["states"])
    print(f"wrote {OUT} ({n} states)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
