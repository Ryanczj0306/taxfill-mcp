"""Form W-2 box 12 codes and the 2026 box 14 split (Phase J JT4a).

The table is data: ``knowledge/forms/w2_box12_codes.yaml``, from the Instructions for Forms W-2 and W-3 (2026), with
each code's title as the 2019-2025 editions print it (Phase K JK28). Every answer is for a TAX YEAR: code II exists from
2024, codes TA, TP and TT from 2026, box 14b from 2026, and a code's title is its year's.
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


def _title(entry: dict, tax_year: int | None) -> str:
    """The title the tax year's instructions print: ``title_until`` keeps an older edition's wording through the named
    year; the 2026 wording holds for 2026 and later, and for an unknown year (Phase K JK28, 2026-10-16)."""
    if tax_year is not None:
        for until, older in sorted((entry.get("title_until") or {}).items(), key=lambda kv: int(kv[0])):
            if tax_year <= int(until):
                return older
    return entry["title"]


def _for_year(entry: dict, tax_year: int | None) -> dict:
    out = {k: v for k, v in entry.items() if k != "title_until"}
    out["title"] = _title(entry, tax_year)
    return out


def codes_for(tax_year: int | None, base_dir: str | Path | None = None) -> dict[str, dict]:
    """The codes a W-2 for ``tax_year`` may carry, titled as that year's instructions print them (all of them, with the
    2026 titles, when the year is unknown)."""
    codes = table(base_dir)["codes"]
    return {c: _for_year(e, tax_year) for c, e in codes.items() if tax_year is None or int(e["since"]) <= tax_year}


def code_entry(code: str, base_dir: str | Path | None = None, *, tax_year: int | None = None) -> dict | None:
    """One code's entry with ``tax_year``'s title (the 2026 title when the year is unknown). A code the year does not
    carry yet is still returned: its ``since`` says which W-2 it starts with."""
    entry = table(base_dir)["codes"].get(code.strip().upper())
    return None if entry is None else _for_year(entry, tax_year)


def parse_box12(raw) -> tuple[str, str | None] | None:
    """A box 12 reading ("D 5300.00", "DD: 7,200", "W") -> (CODE, amount string or None); None when unreadable."""
    if raw is None:
        return None
    m = _BOX12_RE.match(str(raw))
    if not m:
        return None
    amount = m.group(2).replace(",", "") if m.group(2) else None
    return m.group(1).upper(), amount
