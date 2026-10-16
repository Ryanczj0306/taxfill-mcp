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

__all__ = ["DATA_DIR_ENV", "data_root", "knowledge_dir", "formpacks_dir", "display_path", "home_display"]

DATA_DIR_ENV = "TAXFILL_DATA_DIR"


def _has_data(directory: Path) -> bool:
    return (directory / "knowledge").is_dir() and (directory / "formpacks").is_dir()


def data_root() -> Path:
    """Directory that contains both ``knowledge/`` and ``formpacks/``.

    Resolution order: ``$TAXFILL_DATA_DIR`` → nearest ancestor holding both trees
    (source checkout / editable install) → the wheel-packaged ``_data/`` beside
    this module. With neither, it returns the packaged location; a missing-data
    error then names the data-relative tree it looked for (``knowledge``,
    ``formpacks``) and the ``$TAXFILL_DATA_DIR`` setting that fixes it, never the
    absolute install path (Phase K JK27, privacy).
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
    # Neither a checkout ancestor nor the wheel-packaged copy has the data. Return
    # the packaged location (rather than a meaningless venv-root guess); the
    # loaders' not-found errors name $TAXFILL_DATA_DIR as the fix.
    return packaged


def knowledge_dir() -> Path:
    return data_root() / "knowledge"


def formpacks_dir() -> Path:
    return data_root() / "formpacks"


def home_display(path: str | os.PathLike[str]) -> str:
    """A path for a message, with the user's home folder shown as ``~`` (Phase K JK27, privacy)."""
    p = Path(path)
    try:
        return str(Path("~") / p.resolve().relative_to(Path.home().resolve()))
    except (ValueError, OSError, RuntimeError):
        return str(p)


def display_path(path: str | os.PathLike[str], base: str | os.PathLike[str] | None = None) -> str:
    """How a data-tree path appears in a message an agent sees (Phase K JK27, privacy).

    Error messages land in the agent's transcript, and an absolute path into an installed copy names the user's
    home folder (the user's name is in it, and in a uv cache under it). So a path inside the data tree is shown
    relative to it (``formpacks/federal/2025/f1040/pack.yaml``); with an explicit ``base`` (a caller's ``base_dir`` override) it
    is shown relative to that base, under the base's own name; a path in neither shows only its file name.
    """
    p = Path(path)
    roots: list[tuple[Path, str]] = []
    if base is not None:
        roots.append((Path(base), Path(base).name))
    roots.append((data_root(), ""))
    for root, prefix in roots:
        try:
            rel = p.resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        return (Path(prefix) / rel).as_posix() if prefix else rel.as_posix()
    return p.name
