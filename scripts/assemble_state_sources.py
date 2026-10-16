#!/usr/bin/env python
"""Generate knowledge/sources_states.yaml — the per-state source registry.

The freshness protocol (DEV_PLAN §7) was federal-only: ``sources.yaml`` shipped
``states: {}`` while 126 state knowledge packs were live, so
``get_sources(topic, year, "states/xx")`` matched nothing and a state year
newer than the newest pack (the TY2026 planning case) had no registered
authority to resolve against.

This script derives the registry EXCLUSIVELY from the state knowledge packs'
own citations (newest year per state; taxfill_core.state_sources builds each block,
and get_sources builds an older year's block from that year's pack the same way): every citation URL in a pack was
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
from taxfill_core.state_sources import state_block  # noqa: E402

STATES_DIR = REPO / "knowledge" / "states"
OUT = REPO / "knowledge" / "sources_states.yaml"

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
        block = state_block(state_dir.name, year, pack, newest=True)
        if block is not None:
            states[state_dir.name] = block
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
