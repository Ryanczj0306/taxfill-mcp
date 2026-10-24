#!/usr/bin/env python
"""Hoist a state pack's inline citations into a top-level ``sources`` table (Phase K JK20, 2026-10-24).

The per-state source registry (``taxfill_core.state_sources.state_block``, behind knowledge/sources_states.yaml and
get_sources) used to be built only by walking the citations INSIDE a pack's blocks. JK22 drops never-read blocks from
the TY2025 packs (residency, filing_requirement, starts_from, ...), and with them the citations they carry, which
would shrink get_sources. This script copies every .gov inline citation of a pack into one table the builder reads
instead, so a citation outlives the block that carried it.

One row per distinct (registry topic, url), in first-seen walk order, shaped
``{id, topic, url, descriptions}``: ``topic`` is the registry topic the citation's top-level block maps to
(``BLOCK_TO_TOPIC``, else ``FALLBACK_TOPIC``), ``descriptions`` every distinct inline ``source`` text for that pair,
verbatim and in walk order, and ``id`` a short stable name (``<topic prefix>-<n>``, numbered per topic). Non-.gov
citations are left out, as the registry always dropped them. The inline citations stay where they are.

The table is generated ONCE per pack; afterwards it is maintained by hand: a new citation goes inline AND into
``sources`` (test_state_sources_table.py fails otherwise). A pack that already has a table is skipped, and only
TY2025-and-later packs are hoisted (TY2023 / TY2024 stay frozen as schema v1). A TY2026+ pack is written as schema
v2 with its table already in it (Phase K JK25: scripts/state_knowledge_v2_writer.py, through
assemble_state_knowledge.py), so this script skips it; it is for the TY2025 v1 packs.

Usage:
    python scripts/hoist_state_sources.py              # every knowledge/states/<st>/2025.yaml without a table
    python scripts/hoist_state_sources.py --year 2025 ca ny
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
from taxfill_core.state_sources import TOPIC_ID_PREFIX, hoist_sources  # noqa: E402

STATES_DIR = REPO / "knowledge" / "states"
FIRST_YEAR = 2025

COMMENT = """\

# ── sources: this pack's citation table (Phase K JK20, 2026-10-24) ──────────────────────────────────────────────
# One row per distinct (registry topic, url) of the .gov citations this pack carries inline, in first-seen order;
# `descriptions` holds each distinct inline `source` text for that pair, verbatim. Generated once by
# scripts/hoist_state_sources.py. The source registry (taxfill_core.state_sources.state_block, behind
# knowledge/sources_states.yaml and get_sources) is built from this table, so a citation outlives the block that
# carries it when JK22 drops never-read blocks. The inline citations stay where they are: their consumers read them.
# A new citation goes inline AND here (test_state_sources_table.py fails on an inline .gov citation this table
# lacks, and on a row no inline citation backs).
"""


def table_rows(pack: dict) -> list[dict]:
    """The ``sources`` rows for one pack, with ids, in walk order."""
    counters: dict[str, int] = {}
    rows = []
    for row in hoist_sources(pack):
        prefix = TOPIC_ID_PREFIX[row["topic"]]
        counters[prefix] = counters.get(prefix, 0) + 1
        rows.append({"id": f"{prefix}-{counters[prefix]}", **row})
    return rows


def hoist(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    pack = yaml.safe_load(text)
    if "sources" in pack:
        return "skipped (already has a sources table)"
    rows = table_rows(pack)
    if not rows:
        return "skipped (no .gov inline citation)"
    block = yaml.dump({"sources": rows}, sort_keys=False, allow_unicode=True, width=110)
    new_text = text.rstrip("\n") + "\n" + COMMENT + block
    reloaded = yaml.safe_load(new_text)
    if reloaded.pop("sources") != rows or reloaded != pack:
        raise SystemExit(f"{path}: the appended table does not round-trip; nothing written")
    path.write_text(new_text, encoding="utf-8")
    return f"hoisted {len(rows)} rows"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("states", nargs="*", help="two-letter codes (default: every state with a pack for --year)")
    ap.add_argument("--year", type=int, default=FIRST_YEAR)
    args = ap.parse_args()
    if args.year < FIRST_YEAR:
        print(f"refused: TY{args.year} packs stay frozen as schema v1; only TY{FIRST_YEAR}+ packs get a sources table")
        return 2
    paths = (
        [STATES_DIR / st.lower() / f"{args.year}.yaml" for st in args.states]
        if args.states
        else sorted(STATES_DIR.glob(f"*/{args.year}.yaml"))
    )
    missing = [p for p in paths if not p.is_file()]
    if missing:
        print("no pack at: " + ", ".join(str(p.relative_to(REPO)) for p in missing) + " — check the state codes and --year")
        return 2
    for path in paths:
        print(f"{path.relative_to(REPO)}: {hoist(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
