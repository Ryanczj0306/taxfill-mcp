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
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

__all__ = [
    "DATA_DIR_ENV", "data_root", "knowledge_dir", "formpacks_dir", "display_path", "home_display", "user_path",
    "write_output",
]

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
        return user_path(env)
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


def user_path(path: str | os.PathLike[str]) -> Path:
    """A path a user or an agent supplied, with a leading ``~`` expanded to the home folder (Phase K JK28).

    Tool and CLI arguments arrive unexpanded: a JSON tool call, a quoted shell argument, ``--root=~/x`` and an MCP
    client's ``env`` block all pass ``~`` through literally, so ``open("~/taxes/f1040.pdf")`` would look for a folder
    named ``~`` in the server's working directory. Every taxfill entry point that opens or writes a supplied path
    reads it through here. Results keep the absolute path (an agent passes it on to its own file tools); messages
    that only mention one show it through :func:`home_display`. A relative path is made absolute here too (Phase K
    JK28 final review, 2026-10-23): it would otherwise be read against the MCP server's working directory, which the
    client chose, and come back in a result the agent's own file tools resolve against theirs.
    """
    return Path(path).expanduser().absolute()


def home_display(path: str | os.PathLike[str]) -> str:
    """A path for a message, with the user's home folder shown as ``~`` (Phase K JK27, privacy).

    A path still spelled ``~/...`` is expanded first (Phase K JK28): resolved as typed, it would read as a folder
    named ``~`` under the working directory, and from a working directory inside the home folder it would print as
    ``~/<cwd>/~/...``.
    """
    p = Path(path).expanduser()
    try:
        return str(Path("~") / p.resolve().relative_to(Path.home().resolve()))
    except (ValueError, OSError, RuntimeError):
        return str(p)


def write_output(path: Path, write: Callable[[BinaryIO], object]) -> None:
    """Create ``path``'s folder and write the file through ``write``; an OS refusal names the path as ``~``.

    Phase K JK28 final review (2026-10-23): an ``out_path`` that is a folder, or one in an unwritable folder, raised
    Python's raw IsADirectoryError / PermissionError, whose message prints the absolute home path and says nothing
    about what to do. The same exception type is re-raised with the path shown by :func:`home_display` and the next
    step.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            write(fh)
    except OSError as exc:
        message = (
            f"cannot write {home_display(path)}: {exc.strerror or type(exc).__name__} — pass a file path, not a "
            f"folder, in a folder you can write to, such as ~/taxfill-workspace/<year>/drafts/<form>.pdf"
        )
        raise (type(exc)(exc.errno, message) if exc.errno is not None else type(exc)(message)) from None


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
