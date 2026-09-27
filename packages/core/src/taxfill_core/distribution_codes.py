"""Form 1099-R box 7 (2026: box 7a) distribution codes — parse, validate, interpret (Phase J JR1).

The table is data: ``knowledge/forms/1099r_distribution_codes.yaml``, Table 1 (Guide to Distribution
Codes) of the Instructions for Forms 1099-R and 5498, transcribed from the 2019, 2023, 2024, 2025 and
2026 revisions. Codes change by revision — Y is new in 2025, S pairs with J from 2025, and the N/R/8/P
titles name years relative to the form's own — so every answer is for a TAX YEAR.

A finding is not a correction: a payer error is a real reading, so a flagged box keeps its 'ok'
status and the message says "misread OR payer error: request a CORRECTED Form 1099-R".
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.datadir import knowledge_dir

__all__ = ["Box7Interpretation", "CodeMeaning", "Finding", "codes_for", "interpret", "parse_box7", "validate"]

Severity = Literal["error", "warning", "info"]
_CORRECTED = "misread OR payer error: request a CORRECTED Form 1099-R from the payer"


class Finding(BaseModel):
    """One semantic check on a document reading (JR1)."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity
    rule_id: str
    boxes: list[str]
    message: str
    citation: str


class CodeMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    title: str
    account: str
    return_effect: str | None = None


class Box7Interpretation(BaseModel):
    """What a box 7 reading means for one tax year."""

    model_config = ConfigDict(extra="forbid")

    raw: str
    codes: list[str]
    tax_year: int | None
    revision: int = Field(description="The Table 1 revision the codes were read against.")
    meanings: list[CodeMeaning]
    unknown: list[str] = Field(default_factory=list, description="Codes that revision does not carry.")


def _table_path(base_dir: str | Path | None) -> Path:
    base = Path(base_dir) if base_dir is not None else knowledge_dir()
    return base / "forms" / "1099r_distribution_codes.yaml"


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    table = data["codes"]
    for rev in data["revisions"]:
        pairs = {c: _used_with(entry, rev) for c, entry in table.items() if _carried(entry, rev)}
        for a, bs in pairs.items():
            for b in bs:
                if a not in pairs.get(b, set()):
                    raise ValueError(f"1099r_distribution_codes.yaml: {rev} pairs {a} with {b} but not {b} with {a}")
    return data


def _carried(entry: dict, rev: int) -> bool:
    return entry.get("since") is None or rev >= entry["since"]


def _used_with(entry: dict, rev: int) -> set[str]:
    out = set(entry.get("used_with") or [])
    for year, extra in (entry.get("used_with_from") or {}).items():
        if rev >= int(year):
            out |= set(extra)
    return out


def _revision(data: dict, tax_year: int | None) -> int:
    revs = sorted(data["revisions"])
    if tax_year is None:
        return revs[-1]
    earlier = [r for r in revs if r <= tax_year]
    return earlier[-1] if earlier else revs[0]


def codes_for(tax_year: int | None, *, base_dir: str | Path | None = None) -> dict[str, dict]:
    """Every code of the revision that governs ``tax_year``: {code: {title, used_with, account, return_effect}}."""
    data = _load(str(_table_path(base_dir)))
    rev = _revision(data, tax_year)
    year = tax_year if tax_year is not None else rev
    out: dict[str, dict] = {}
    for code, entry in data["codes"].items():
        if not _carried(entry, rev):
            continue
        title = entry["title"]
        for until, older in sorted((entry.get("title_until") or {}).items()):
            if rev <= int(until):
                title = older
                break
        out[code] = {
            "title": title.format(year=year, prior_year=year - 1),
            "used_with": _used_with(entry, rev),
            "account": entry.get("account", "any"),
            "return_effect": entry.get("return_effect"),
        }
    return out


def parse_box7(raw: str | None) -> list[str]:
    """The codes in a box 7 reading, in order: every letter or digit, separators ignored ("7 1", "8/1",
    "Q+B", "G, 4" and "NQ7" all split into single-character codes)."""
    return re.findall(r"[0-9A-Z]", str(raw or "").upper())


def _rules(base_dir: str | Path | None) -> dict:
    return _load(str(_table_path(base_dir)))["rules"]


def validate(codes: list[str], tax_year: int | None, *, base_dir: str | Path | None = None) -> list[Finding]:
    """The combination rules of box 7 for the tax year's revision (V1-V5)."""
    rules = _rules(base_dir)
    table = codes_for(tax_year, base_dir=base_dir)
    rev = _revision(_load(str(_table_path(base_dir))), tax_year)
    cite = f"Instructions for Forms 1099-R and 5498 ({rev}), box 7 and Table 1"
    findings: list[Finding] = []
    box = ["7"]
    unknown = [c for c in codes if c not in table]
    for c in unknown:
        findings.append(Finding(severity="error", rule_id="V0", boxes=box, citation=cite,
                                message=f"'{c}' is not a distribution code in the {rev} revision of Table 1 — {_CORRECTED}."))
    if len(codes) > rules["max_codes"]:
        findings.append(Finding(severity="error", rule_id="V1", boxes=box, citation=cite, message=(
            f"{len(codes)} codes ({''.join(codes)}): \"{rules['quotes']['max_codes']}\" — {_CORRECTED}.")))
    known = [c for c in codes if c in table]
    if len(known) == 2:
        a, b = known
        numeric = a.isdigit() and b.isdigit()
        if numeric and sorted([a, b]) not in [sorted(p) for p in rules["numeric_pairs"]]:
            findings.append(Finding(severity="error", rule_id="V2", boxes=box, citation=cite, message=(
                f"codes {a} and {b}: \"{rules['quotes']['numeric_pairs']}\" — {_CORRECTED}.")))
        elif set(known) & set(rules["standalone"]):
            findings.append(Finding(severity="error", rule_id="V4", boxes=box, citation=cite, message=(
                f"codes {a} and {b}: \"{rules['quotes']['standalone']}\" — {_CORRECTED}.")))
        elif b not in table[a]["used_with"]:
            findings.append(Finding(severity="error", rule_id="V3", boxes=box, citation=cite, message=(
                f"code {a} is not used with code {b} in the {rev} revision of Table 1 (code {a} pairs with "
                f"{', '.join(sorted(table[a]['used_with'])) or 'no other code'}) — {_CORRECTED}.")))
    if known == ["Y"]:
        findings.append(Finding(severity="error", rule_id="V5", boxes=box, citation=cite, message=(
            f"code Y alone: \"{rules['quotes']['code_y']}\" — {_CORRECTED}.")))
    return findings


def interpret(raw: str | None, tax_year: int | None, *, base_dir: str | Path | None = None) -> Box7Interpretation:
    """What each code in a box 7 reading means for the tax year (unknown codes listed, never guessed)."""
    codes = parse_box7(raw)
    table = codes_for(tax_year, base_dir=base_dir)
    rev = _revision(_load(str(_table_path(base_dir))), tax_year)
    meanings = [
        CodeMeaning(code=c, title=table[c]["title"], account=table[c]["account"], return_effect=table[c]["return_effect"])
        for c in codes if c in table
    ]
    return Box7Interpretation(raw=str(raw or ""), codes=codes, tax_year=tax_year, revision=rev, meanings=meanings,
                              unknown=[c for c in codes if c not in table])
