"""Hatchling build hook: stage the data trees into the package before building.

Guarantees a built taxfill-core distribution is never silently shipped without
its knowledge/ + formpacks/ data. Runs on every sdist/wheel build, copying the
repo-root trees (YAML/md only — no vendored PDFs) into src/taxfill_core/_data/
(force-included via [tool.hatch.build] artifacts), and fails loudly if the
source data is missing or the staged copy ends up empty.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_TREES = ("knowledge", "formpacks")
_EXTS = {".yaml", ".yml", ".md"}


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        project = Path(self.root)                      # packages/core (or an unpacked sdist)
        repo = project.parents[1]                      # repo root, when building from a checkout
        dest = project / "src" / "taxfill_core" / "_data"

        if all((repo / t).is_dir() for t in _TREES):
            # Building from a checkout: stage a fresh copy from the repo trees.
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            total = 0
            for tree in _TREES:
                for path in (repo / tree).rglob("*"):
                    if path.is_file() and path.suffix.lower() in _EXTS:
                        out = dest / path.relative_to(repo)
                        out.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, out)
                        total += 1
            if total == 0:
                raise RuntimeError("build aborted: staged 0 data files — knowledge/ and formpacks/ are empty")
        else:
            # Building from an sdist (no repo trees on disk): _data is already
            # carried inside the sdist; just confirm it is non-empty.
            staged = [p for p in dest.rglob("*") if p.is_file()] if dest.exists() else []
            if not staged:
                raise RuntimeError(
                    "build aborted: no repo data trees and _data/ is empty — "
                    "run from a checkout or rebuild the sdist with the data present"
                )
