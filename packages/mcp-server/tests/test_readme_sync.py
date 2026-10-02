"""Guard (Phase J JD1): the documented tool table and counts must equal the runtime.

Before JD1 the README's table listed 16 of the 23 tools, and its calc row named a non-op (a routing-number
checksum, which ``calc`` answers with "unknown calc op") while omitting twenty real ops. These tests derive every
count from the runtime, so the docs can say more than the code but never less, and never something else. The tool
table now lives in docs/TOOLS.md and the README carries a short coverage table; both are checked here.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
README = (REPO / "README.md").read_text(encoding="utf-8")
TOOLS_MD = (REPO / "docs" / "TOOLS.md").read_text(encoding="utf-8")


def _runtime_tool_names() -> set[str]:
    import anyio

    from taxfill_mcp.server import mcp

    return {t.name for t in anyio.run(mcp.list_tools)}


def _runtime_calc_ops() -> set[str]:
    src = (REPO / "packages" / "mcp-server" / "src" / "taxfill_mcp" / "server.py").read_text()
    return set(re.findall(r'if op == "([a-z0-9_]+)"', src))


def _table_rows() -> list[str]:
    start = TOOLS_MD.index("## MCP tools")
    end = TOOLS_MD.index("\n## ", start + 1)
    return [line for line in TOOLS_MD[start:end].splitlines() if line.startswith("| `")]


def test_every_runtime_tool_has_a_tools_md_row():
    named = set()
    for row in _table_rows():
        first_cell = row.split("|")[1]
        named |= set(re.findall(r"`([a-z_]+)`", first_cell))
    assert named == _runtime_tool_names(), (
        f"docs/TOOLS.md tool table: missing {sorted(_runtime_tool_names() - named)}, "
        f"not a tool {sorted(named - _runtime_tool_names())}")


def test_the_documented_tool_count_is_the_runtime_count():
    n = len(_runtime_tool_names())
    assert f"All {n} tools are available today" in TOOLS_MD and f"registers exactly {n}" in TOOLS_MD
    assert f"Look up the {n} MCP tools" in README


def test_the_calc_row_names_exactly_the_runtime_ops():
    row = next(r for r in _table_rows() if r.startswith("| `calc` |"))
    named = set(re.findall(r"`([a-z0-9_]+)`", row.split("|")[2]))
    ops = _runtime_calc_ops()
    assert named == ops, f"docs/TOOLS.md calc row: missing {sorted(ops - named)}, not an op {sorted(named - ops)}"
    assert f"{len(ops)} ops" in row


def test_the_federal_pack_count_is_the_discovered_count():
    per_year = {}
    for pack in (REPO / "formpacks" / "federal").glob("*/*/pack.yaml"):
        year = int(pack.parent.parent.name)
        per_year[year] = per_year.get(year, 0) + 1
    total = sum(per_year.values())
    row = next(line for line in README.splitlines() if line.startswith("| **Federal forms** |"))
    assert f"— {total} packs" in row and f"Form 8843 from TY{min(per_year)}" in row, row
    coverage = (REPO / "docs" / "COVERAGE.md").read_text(encoding="utf-8")
    assert f"**{total} federal form packs**" in coverage, "run scripts/sync_doc_counts.py --write"
    for year in per_year:  # the byte-exact check is sync_doc_counts --check (test_the_quoted_doc_counts_are_current)
        assert f"| {year} " in coverage, f"docs/COVERAGE.md has no {year} column"


def test_the_bundle_manifest_lists_the_runtime_tools_and_ops():
    import json

    manifest = json.loads((REPO / "packages" / "mcp-server" / "bundle" / "manifest.json").read_text())
    assert {t["name"] for t in manifest["tools"]} == _runtime_tool_names()
    calc = next(t for t in manifest["tools"] if t["name"] == "calc")["description"]
    ops = _runtime_calc_ops()
    listed = set(calc.split(": ", 1)[1].split(", "))
    assert listed == ops and f"{len(ops)} ops" in calc, "run scripts/sync_bundle_manifest.py --write"



def test_the_quoted_doc_counts_are_current():
    """JD2: tools, ops, DocSpec kinds and pack counts in README / SKILL / DEV_PLAN / pyproject are derived."""
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "sync_doc_counts.py"), "--check"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_open_roadmap_box_names_its_tranche():
    """JD2: an open box ("- [ ]" or a partial "- [~]") names the Phase J tranche that carries it, so no open item
    hides outside the plan; the completed phases live in docs/dev/HISTORY.md, which holds no open box at all."""
    tranche = re.compile(r"\bJ[A-Z]{1,2}(?:\d+[a-z]?|[a-z])\b")
    lines = (REPO / "docs" / "dev" / "ROADMAP.md").read_text(encoding="utf-8").splitlines()
    unnamed = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)- \[[ ~]\]", line)
        if not m:
            continue
        block = [line]
        for nxt in lines[i + 1:]:
            if not nxt.strip() or len(nxt) - len(nxt.lstrip()) <= len(m.group(1)):
                break
            block.append(nxt)
        if not tranche.search(" ".join(block)):
            unnamed.append(f"ROADMAP.md:{i + 1}: {line.strip()[:90]}")
    assert not unnamed, "open box(es) with no Phase J tranche named:\n" + "\n".join(unnamed)
    history = (REPO / "docs" / "dev" / "HISTORY.md").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\s*- \[[ ~]\]", history), "docs/dev/HISTORY.md holds only completed work"
