#!/usr/bin/env python
"""Single source of truth for the counts the docs quote — tools, calc ops, DocSpecs, packs (Phase J JD2).

The test count has its own script (scripts/sync_test_count.py, which stays the entrypoint for it); this one
covers every OTHER number a reader is told: the MCP tool count, the calc op count, the DocSpec kinds, the federal
pack total and its per-year split, the state and hand-fill pack counts. They drifted exactly as the test count
did — the core package's pyproject description still said "21 calculation ops" at 40, and the server's "22
tools" at 23 — so they are derived, never typed.

    python scripts/sync_doc_counts.py            # report the counts
    python scripts/sync_doc_counts.py --write    # rewrite every anchor
    python scripts/sync_doc_counts.py --check    # nonzero exit if any anchor disagrees (CI)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "packages" / "core" / "src"), str(REPO / "packages" / "mcp-server" / "src")]


def counts() -> dict[str, object]:
    import anyio

    from taxfill_core.extract import DOC_SPECS
    from taxfill_mcp.server import mcp

    server = (REPO / "packages" / "mcp-server" / "src" / "taxfill_mcp" / "server.py").read_text(encoding="utf-8")
    federal: dict[int, int] = {}
    for pack in (REPO / "formpacks" / "federal").glob("*/*/pack.yaml"):
        year = int(pack.parent.parent.name)
        federal[year] = federal.get(year, 0) + 1
    return {
        "tools": len(anyio.run(mcp.list_tools)),
        "ops": len(set(re.findall(r'if op == "([a-z0-9_]+)"', server))),
        "doc_kinds": len(DOC_SPECS),
        "federal": sum(federal.values()),
        "federal_by_year": dict(sorted(federal.items())),
        "state": len(list((REPO / "formpacks" / "states").glob("*/*/*/pack.yaml"))),
        "handfill": len(list((REPO / "formpacks").glob("**/handfill.yaml"))),
    }


def anchors(c: dict) -> list[tuple[Path, str, str]]:
    """(file, regex, replacement) for every place a count is quoted. Each regex must match exactly once."""
    readme, skill = REPO / "README.md", REPO / "skills" / "claude" / "SKILL.md"
    by_year = ", ".join(f"{y}:{n}" for y, n in c["federal_by_year"].items())
    return [
        (readme, r"All \d+ tools are available today", f"All {c['tools']} tools are available today"),
        (readme, r"registers exactly \d+", f"registers exactly {c['tools']}"),
        (readme, r"stdio server, \d+ tools", f"stdio server, {c['tools']} tools"),
        (readme, r"Deterministic tax math — \d+ ops \(`calc\(op, args\)`\)",
         f"Deterministic tax math — {c['ops']} ops (`calc(op, args)`)"),
        (readme, r"\*\*M2 — Federal packs:\*\* \*\*\d+ packs\*\*", f"**M2 — Federal packs:** **{c['federal']} packs**"),
        (readme, r"Per year: (?:20\d\d:\d+, )+20\d\d:\d+", f"Per year: {by_year}"),
        (skill, r"deterministic tax math — \d+ ops, one bullet each", f"deterministic tax math — {c['ops']} ops, one bullet each"),
        (skill, r"The federal set is \*\*\d+ packs\*\*", f"The federal set is **{c['federal']} packs**"),
        (REPO / "docs" / "DEV_PLAN.md", r"It carries \d+ kinds", f"It carries {c['doc_kinds']} kinds"),
        (REPO / "packages" / "mcp-server" / "README.md", r"## Tools \(dev plan §8\) — all \d+",
         f"## Tools (dev plan §8) — all {c['tools']}"),
        (REPO / "packages" / "mcp-server" / "README.md", r"`calc` \(\d+\ndeterministic ops",
         f"`calc` ({c['ops']}\ndeterministic ops"),
        (REPO / "docs" / "PUBLISHING.md", r"assert len\(asyncio\.run\(s\.mcp\.list_tools\(\)\)\) == \d+",
         f"assert len(asyncio.run(s.mcp.list_tools())) == {c['tools']}"),
        (REPO / "docs" / "PUBLISHING.md", r"It declares the \*\*\d+ tools\*\*", f"It declares the **{c['tools']} tools**"),
        (REPO / "packages" / "core" / "pyproject.toml", r"and \d+ calculation ops", f"and {c['ops']} calculation ops"),
        (REPO / "packages" / "mcp-server" / "pyproject.toml", r"cited tax math \(\d+ tools\)",
         f"cited tax math ({c['tools']} tools)"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    c = counts()
    print(f"tools={c['tools']} ops={c['ops']} doc_kinds={c['doc_kinds']} federal={c['federal']} "
          f"({', '.join(f'{y}:{n}' for y, n in c['federal_by_year'].items())}) state={c['state']} "
          f"handfill={c['handfill']}")
    stale, texts = [], {}
    for path, pattern, replacement in anchors(c):
        text = texts.setdefault(path, path.read_text(encoding="utf-8"))
        hits = re.findall(pattern, text)
        if len(hits) != 1:
            print(f"ANCHOR LOST: {path.relative_to(REPO)} has {len(hits)} match(es) for {pattern!r} — fix the "
                  f"anchor or this script", file=sys.stderr)
            return 2
        if hits[0] != replacement:
            stale.append(f"{path.relative_to(REPO)}: {hits[0]!r} -> {replacement!r}")
            texts[path] = re.sub(pattern, lambda _m: replacement, text, count=1)
    for line in stale:
        print(("updated " if args.write else "STALE ") + line)
    if args.write:
        for path, text in texts.items():
            if text != path.read_text(encoding="utf-8"):
                path.write_text(text, encoding="utf-8")
        return 0
    if args.check and stale:
        print(f"{len(stale)} stale count(s) — run: uv run python scripts/sync_doc_counts.py --write", file=sys.stderr)
        return 1
    if not stale:
        print("every quoted count is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
