#!/usr/bin/env python
"""Stage the shared data trees into the core package for a self-contained build.

The ``knowledge/`` and ``formpacks/`` trees live at the repo root (the layout the
scripts and tests read). A published wheel must carry them, so before building we
copy them into ``packages/core/src/taxfill_core/_data/`` — the location the
``datadir`` resolver falls back to when installed. The copy is a build artifact:
it is git-ignored, force-included into the distribution via ``[tool.hatch.build]
artifacts`` in the core ``pyproject.toml``, and recreated fresh on every run.

Usage (release step, see docs/PUBLISHING.md):

    python scripts/stage_data.py && uv build --package taxfill-core
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEST = REPO / "packages" / "core" / "src" / "taxfill_core" / "_data"
TREES = ("knowledge", "formpacks")


def main() -> int:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    total = 0
    for tree in TREES:
        src = REPO / tree
        if not src.is_dir():
            print(f"ERROR: {src} not found — run from the repo with the data trees present")
            return 1
        # YAML/markdown only; never copy a cached blank PDF or other binary into the wheel.
        n = 0
        for path in src.rglob("*"):
            if path.is_dir():
                continue
            if path.suffix.lower() not in {".yaml", ".yml", ".md"}:
                continue
            rel = path.relative_to(REPO)
            out = DEST / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
            n += 1
        print(f"staged {n:>4} files from {tree}/")
        total += n
    print(f"staged {total} files into {DEST.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
