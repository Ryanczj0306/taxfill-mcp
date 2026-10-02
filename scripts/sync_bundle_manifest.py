"""Keep packages/mcp-server/bundle/manifest.json's tool list equal to the runtime (Phase J JD1).

The manifest's `tools` entries are what a one-click install shows before the server ever runs, so they drift
silently: until JD1 the calc entry said "32 ops" and named none of the six ops added since, and
estimate_refund still promised only an ESTIMATE. This script rewrites the calc entry from the dispatch chain
and checks that the tool names equal the registered tools.

    uv run python scripts/sync_bundle_manifest.py          # check only (exit 1 on drift)
    uv run python scripts/sync_bundle_manifest.py --write  # rewrite the calc entry
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "packages" / "mcp-server" / "bundle" / "manifest.json"
SERVER = REPO / "packages" / "mcp-server" / "src" / "taxfill_mcp" / "server.py"


def runtime_ops() -> list[str]:
    """The ops `calc` dispatches, in dispatch order."""
    seen: list[str] = []
    for op in re.findall(r'if op == "([a-z0-9_]+)"', SERVER.read_text()):
        if op not in seen:
            seen.append(op)
    return seen


def calc_description(ops: list[str]) -> str:
    return f"Deterministic tax math — {len(ops)} ops over cited per-year data: " + ", ".join(ops)


def main(argv: list[str]) -> int:
    manifest = json.loads(MANIFEST.read_text())
    calc = next(t for t in manifest["tools"] if t["name"] == "calc")
    want = calc_description(runtime_ops())
    if calc["description"] == want:
        print("packages/mcp-server/bundle/manifest.json calc entry is current")
        return 0
    if "--write" not in argv:
        print("packages/mcp-server/bundle/manifest.json calc entry is stale — run with --write")
        return 1
    calc["description"] = want
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print("packages/mcp-server/bundle/manifest.json calc entry rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
