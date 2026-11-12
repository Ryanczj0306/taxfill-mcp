"""The finals ledger for the tests (formpacks/federal/repins.yaml, written by scripts/repin_final.py).

A federal pack authored on an IRS early-release draft moves to the final when it posts (Phase J JT6). The tests
that describe such a pack must hold before and after that move with NO edit, so they ask this module instead of
typing "draft" or "final": the pack's own pin while it is the draft, the ledger's row once it is re-pinned.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from taxfill_core.schemas.formpack import FormPack, load_pack

REPO = Path(__file__).resolve().parents[3]


def _script(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


repin_final = _script("repin_final")


def ledger() -> dict[str, dict]:
    """pack id ("federal/2026/sched_c") -> its ledger row."""
    return repin_final.load_ledger(REPO)


def row_of(pack: FormPack) -> dict | None:
    """The ledger row of a re-pinned pack (found by the final it pins); None for any other pack."""
    return next((r for r in ledger().values() if r["final_url"] == pack.source_url), None)


def draft_created(pack: FormPack) -> str | None:
    """The footer "Created" stamp of the IRS draft ``pack`` was authored on: the pack's own while it still pins that
    draft, the ledger's once it pins the final (which must then be exactly the ledger's final). None for a pack
    that never was a draft."""
    if pack.source_status == "draft":
        assert "/pub/irs-dft/" in pack.source_url and pack.source_url.endswith("--dft.pdf"), pack.source_url
        assert row_of(pack) is None
        return pack.draft_created
    row = row_of(pack)
    if row is None:
        return None
    assert (pack.pdf_sha256, pack.draft_created) == (row["final_sha256"], None), pack.source_url
    return row["draft_created"]


def page_on_draft(pack: FormPack, page: int) -> int:
    """``page`` of the pack's pinned blank as the page it was on the draft (one higher once a final dropped the
    draft's cover sheet)."""
    row = row_of(pack)
    return page + (1 if row is not None and row["cover_sheet_dropped"] else 0)


def repinned_keys(year: int) -> dict[str, str]:
    """form key -> IRS file stem for every pack of ``year`` the ledger records as re-pinned."""
    prefix = f"federal/{year}/"
    return {pid.removeprefix(prefix): row["stem"] for pid, row in ledger().items() if pid.startswith(prefix)}


def federal_pack(year: int, key: str) -> FormPack:
    return load_pack(REPO / "formpacks" / "federal" / str(year) / key / "pack.yaml")
