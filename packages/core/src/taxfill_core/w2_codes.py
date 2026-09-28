"""Form W-2 box 12 codes and the 2026 box 14 split (Phase J JT4a).

The table is data: ``knowledge/forms/w2_box12_codes.yaml``, from the Instructions for Forms W-2 and W-3 (2026).
Every answer is for a TAX YEAR: codes TA, TP and TT exist from 2026, box 14b from 2026.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from taxfill_core.datadir import knowledge_dir

__all__ = ["code_entry", "codes_for", "parse_box12", "table"]

_BOX12_RE = re.compile(r"^\s*([A-Za-z]{1,2})\s*[:\-]?\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)?\s*$")


def _table_path(base_dir: str | Path | None) -> Path:
    base = Path(base_dir) if base_dir is not None else knowledge_dir()
    return base / "forms" / "w2_box12_codes.yaml"


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def table(base_dir: str | Path | None = None) -> dict:
    return _load(str(_table_path(base_dir)))


def codes_for(tax_year: int | None, base_dir: str | Path | None = None) -> dict[str, dict]:
    """The codes a W-2 for ``tax_year`` may carry (all of them when the year is unknown)."""
    codes = table(base_dir)["codes"]
    return {c: e for c, e in codes.items() if tax_year is None or int(e["since"]) <= tax_year}


def code_entry(code: str, base_dir: str | Path | None = None) -> dict | None:
    return table(base_dir)["codes"].get(code.strip().upper())


def parse_box12(raw) -> tuple[str, str | None] | None:
    """A box 12 reading ("D 5300.00", "DD: 7,200", "W") -> (CODE, amount string or None); None when unreadable."""
    if raw is None:
        return None
    m = _BOX12_RE.match(str(raw))
    if not m:
        return None
    amount = m.group(2).replace(",", "") if m.group(2) else None
    return m.group(1).upper(), amount
