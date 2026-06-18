"""Locate the shipped data trees (``knowledge/`` and ``formpacks/``).

The same loaders must work whether the code runs from a source checkout, an
editable workspace install, or a published wheel launched by ``uvx taxfill-mcp``.
The two layouts differ:

* **checkout / editable install** — the data lives at the repo root, alongside
  ``packages/``. We find it by walking up from this module to the first ancestor
  that contains both ``knowledge/`` and ``formpacks/``.
* **built wheel** — the trees are force-included under ``taxfill_core/_data/``
  (see ``packages/core/pyproject.toml``), so they sit next to this module.

``TAXFILL_DATA_DIR`` overrides everything: point it at a directory that contains
``knowledge/`` and ``formpacks/`` (used for testing a packaged install, or to
run against a patched data set). Every public loader still accepts an explicit
``base_dir`` / ``knowledge_dir`` argument that bypasses this resolver entirely.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["DATA_DIR_ENV", "data_root", "knowledge_dir", "formpacks_dir"]

DATA_DIR_ENV = "TAXFILL_DATA_DIR"


def _has_data(directory: Path) -> bool:
    return (directory / "knowledge").is_dir() and (directory / "formpacks").is_dir()


def data_root() -> Path:
    """Directory that contains both ``knowledge/`` and ``formpacks/``.

    Resolution order: ``$TAXFILL_DATA_DIR`` → nearest ancestor holding both trees
    (source checkout / editable install) → the wheel-packaged ``_data/`` beside
    this module. Falls back to the historical repo-root guess so a missing-data
    error names a concrete path.
    """
    env = os.environ.get(DATA_DIR_ENV)
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if _has_data(parent):
            return parent
    packaged = here.parent / "_data"
    if _has_data(packaged):
        return packaged
    return here.parents[4]


def knowledge_dir() -> Path:
    return data_root() / "knowledge"


def formpacks_dir() -> Path:
    return data_root() / "formpacks"
