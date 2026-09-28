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
        "state_by_year": {y: len(list((REPO / "formpacks" / "states").glob(f"*/{y}/*/pack.yaml")))
                          for y in sorted({int(p.parent.parent.name)
                                           for p in (REPO / "formpacks" / "states").glob("*/*/*/pack.yaml")})},
        "handfill": len(list((REPO / "formpacks").glob("**/handfill.yaml"))),
        **_state_years(),
    }


def _state_years() -> dict[str, object]:
    """Which jurisdictions can fill which post-2023 years — the state lists the docs quote (Phase J JS3b)."""
    states = REPO / "formpacks" / "states"
    years: dict[str, set[int]] = {}
    for pack in states.glob("*/*/*/*.yaml"):
        if pack.name in ("pack.yaml", "handfill.yaml") and pack.parent.parent.name.isdigit():
            years.setdefault(pack.parts[-4], set()).add(int(pack.parent.parent.name))
    post = {st: ys for st, ys in years.items() if any(y > 2023 for y in ys)}
    both = sorted(st.upper() for st, ys in post.items() if {2024, 2025} <= ys)
    only24 = sorted(st.upper() for st, ys in post.items() if 2024 in ys and 2025 not in ys)
    return {"jurisdictions": len(years), "post2023": len(post), "both_years": both, "only_2024": only24}


def anchors(c: dict) -> list[tuple[Path, str, str]]:
    """(file, regex, replacement) for every place a count is quoted. Each regex must match exactly once."""
    readme, skill = REPO / "README.md", REPO / "skills" / "claude" / "SKILL.md"
    roadmap = REPO / "docs" / "ROADMAP.md"
    sy = c["state_by_year"]
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
        # Phase J JS3b: the state form-pack counts (they drifted: "61 state" survived the UT 2025 port).
        (skill, r"are \*\*thinner and uneven\*\*: \d+ packs", f"are **thinner and uneven**: {c['state']} packs"),
        (readme, r"38 via fillable AcroForm \(\*\*\d+\*\* state `pack\.yaml` in total\)",
         f"38 via fillable AcroForm (**{c['state']}** state `pack.yaml` in total)"),
        (skill, r"post-2023 for only \*\*\d+\*\* — \*\*[A-Z, ]+ \(2024 and 2025\)\*\* and\n> \*\*[A-Z, ]+ \(2024\)\*\*\. "
                r"For the other \d+ jurisdictions",
         f"post-2023 for only **{c['post2023']}** — **{', '.join(c['both_years'])} (2024 and 2025)** and\n"
         f"> **{', '.join(c['only_2024'])} (2024)**. For the other {c['jurisdictions'] - c['post2023']} jurisdictions"),
        (readme, r"\*\*TY2024 \d+\*\* \(", f"**TY2024 {sy[2024]}** ("),
        (readme, r"\*\*TY2025 \d+\*\* \(", f"**TY2025 {sy[2025]}** ("),
        (readme, r"\*\*\d+ of the 42 jurisdictions now fill a post-2023 year\*\* \([A-Z, ]+\); for the other \d+,",
         f"**{c['post2023']} of the 42 jurisdictions now fill a post-2023 year** "
         f"({', '.join(sorted(c['both_years'] + c['only_2024']))}); for the other {c['jurisdictions'] - c['post2023']},"),
        (readme, r"took \d+ jurisdictions \([A-Z, ]+\) past TY2023, so the remaining \d+ still fill",
         f"took {c['post2023']} jurisdictions ({', '.join(sorted(c['both_years'] + c['only_2024']))}) past TY2023, so "
         f"the remaining {c['jurisdictions'] - c['post2023']} still fill"),
        (roadmap, r"\*\*State form packs — \d+ across three years\*\* \(TY2023 \d+ / TY2024 \d+ / TY2025 \d+\)",
         f"**State form packs — {c['state']} across three years** (TY2023 {sy[2023]} / TY2024 {sy[2024]} / "
         f"TY2025 {sy[2025]})"),
        (roadmap, r"\*\*\d+ of the 42 jurisdictions fill a post-2023 year\*\*",
         f"**{c['post2023']} of the 42 jurisdictions fill a post-2023 year**"),
        (roadmap, r"fill a post-2023 year\*\* — [A-Z, ]+\n> and [A-Z]+ \(2024\+2025\), and [A-Z/]+ \(2024\) — after",
         f"fill a post-2023 year** — {', '.join(c['both_years'][:-1])}\n> and {c['both_years'][-1]} (2024+2025), "
         f"and {'/'.join(c['only_2024'])} (2024) — after"),
        (roadmap, r"For the remaining \*\*\d+\*\*, state \*knowledge\*",
         f"For the remaining **{c['jurisdictions'] - c['post2023']}**, state *knowledge*"),
        (roadmap, r"That asymmetry is now \d+\n> jurisdictions wide",
         f"That asymmetry is now {c['jurisdictions'] - c['post2023']}\n> jurisdictions wide"),
        (roadmap, r"\*\*\d+ of the 42 jurisdictions\*\* can fill a post-2023 year — [A-Z, ]+(?: and [A-Z]+)?\n      for both "
                  r"2024 and 2025; [A-Z, ]+ for 2024\. For the\n      other \*\*\d+\*\*",
         f"**{c['post2023']} of the 42 jurisdictions** can fill a post-2023 year — "
         f"{', '.join(c['both_years'][:-1])} and {c['both_years'][-1]}\n      for both 2024 and 2025; "
         f"{', '.join(c['only_2024'])} for 2024. For the\n      other **{c['jurisdictions'] - c['post2023']}**"),
        (roadmap, r"\*\*\d+ form packs total\*\* — \d+ `pack\.yaml` \(\d+ federal \+ \d+ state\) \+ \d+",
         f"**{c['federal'] + c['state'] + c['handfill']} form packs total** — {c['federal'] + c['state']} `pack.yaml` "
         f"({c['federal']} federal + {c['state']} state) + {c['handfill']}"),
        (roadmap, r"The state \d+ breaks down \*\*TY2023 \d+ / TY2024 \d+ / TY2025 \d+\*\*",
         f"The state {c['state']} breaks down **TY2023 {sy[2023]} / TY2024 {sy[2024]} / TY2025 {sy[2025]}**"),
        (roadmap, r"38 via fillable AcroForm \(\d+ packs across TY2023–TY2025\)",
         f"38 via fillable AcroForm ({c['state']} packs across TY2023–TY2025)"),
        (roadmap, r"TY2023-only\*\*: \d+ packs across TY2023 \(\d+\) / TY2024 \(\d+\) / TY2025 \(\d+\)",
         f"TY2023-only**: {c['state']} packs across TY2023 ({sy[2023]}) / TY2024 ({sy[2024]}) / TY2025 ({sy[2025]})"),
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
