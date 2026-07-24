#!/usr/bin/env python
"""Assemble G4 verified state ``tax:`` blocks into knowledge/states/<st>/<year>.yaml.

Reads per-state VERIFIED research JSON (the two-pass workflow's clean packs —
never raw researcher output) and appends a typed ``tax:`` block to each state's
knowledge pack, matching the flat-tranche file style. Every write is gated:

1. the rendered YAML round-trips through ``StateKnowledge``/``StateTaxParams``
   with exact ``Decimal`` equality for every rate;
2. every shipped test vector is recomputed through ``calc.state_tax`` from the
   assembled file — ``expected_base_after`` and ``expected_tax`` must both
   match, or the state is skipped with a loud error.

Usage:
    python scripts/assemble_state_tax_blocks.py <dir-with-clean-jsons> \
        [--year 2023] [--states ca,ny] [--knowledge-dir knowledge] [--dry-run]

JSON shape per state (the workflow PACK_SCHEMA): state, classification
(flat|graduated), citation{source,url}, base, tax_line, flat_rate (string|null),
brackets ({status: [{over, but_not_over, rate}]} | null), standard_deduction
({status: int} | null), exemptions ({key: {amount, note}}), notes [..],
test_vectors [{taxable_base, filing_status, exemptions_count, dependents_count,
expected_base_after, expected_tax, work}].
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))

from taxfill_core.calc import state_tax  # noqa: E402
from taxfill_core.knowledge import StateTaxParams, load_state_knowledge  # noqa: E402

STATUS_ORDER = ("single", "married_filing_jointly", "married_filing_separately", "head_of_household")


def _dump_kv(key: str, value, indent: int) -> str:
    """One key/value as YAML at ``indent`` spaces, PyYAML handling quoting/wrapping."""
    text = yaml.safe_dump({key: value}, width=110, sort_keys=False, allow_unicode=True, default_flow_style=False)
    pad = " " * indent
    return "".join(pad + line + "\n" for line in text.rstrip("\n").split("\n"))


def render_tax_block(pack: dict) -> str:
    lines: list[str] = ["tax:\n"]
    lines.append("  citation:\n")
    lines.append(_dump_kv("source", pack["citation"]["source"], 4))
    lines.append(f"    url: {pack['citation']['url']}\n")
    if pack.get("flat_rate"):
        lines.append(f"  flat_rate: {pack['flat_rate']}\n")
    else:
        lines.append("  brackets:\n")
        for status in STATUS_ORDER:
            lines.append(f"    {status}:\n")
            for b in pack["brackets"][status]:
                bno = "null" if b["but_not_over"] is None else b["but_not_over"]
                lines.append(f"    - {{over: {b['over']}, but_not_over: {bno}, rate: {b['rate']}}}\n")
    lines.append(f"  base: {pack['base']}\n")
    lines.append(_dump_kv("tax_line", pack["tax_line"], 2))
    exemptions = pack.get("exemptions") or {}
    if not exemptions:
        lines.append("  exemptions: {}\n")
    else:
        lines.append("  exemptions:\n")
        for key in exemptions:
            lines.append(f"    {key}:\n")
            lines.append(f"      amount: {exemptions[key]['amount']}\n")
            lines.append(_dump_kv("note", exemptions[key]["note"], 6))
    if pack.get("standard_deduction"):
        lines.append("  standard_deduction:\n")
        for status in STATUS_ORDER:
            lines.append(f"    {status}: {pack['standard_deduction'][status]}\n")
    notes = pack.get("notes") or []
    if notes:
        lines.append("  notes:\n")
        for note in notes:
            text = yaml.safe_dump([note], width=110, allow_unicode=True, default_flow_style=False)
            lines.append("".join("  " + line + "\n" for line in text.rstrip("\n").split("\n")))
    return "".join(lines)


def _check_rates_exact(pack: dict, params: StateTaxParams) -> None:
    """YAML floats must round-trip to the JSON strings' exact Decimals."""
    if pack.get("flat_rate"):
        assert params.flat_rate == Decimal(pack["flat_rate"]), (
            f"flat_rate drift: yaml {params.flat_rate} != json {pack['flat_rate']}"
        )
        return
    for status in STATUS_ORDER:
        for i, b in enumerate(pack["brackets"][status]):
            got = params.brackets[status][i]
            assert got.rate == Decimal(b["rate"]), (
                f"{status}[{i}] rate drift: yaml {got.rate} != json {b['rate']}"
            )
            assert got.over == b["over"] and got.but_not_over == b["but_not_over"], f"{status}[{i}] bound drift"


def assemble(pack: dict, year: int, knowledge_dir: Path, dry_run: bool) -> None:
    code = pack["state"]
    path = knowledge_dir / "states" / code / f"{year}.yaml"
    existing = path.read_text(encoding="utf-8")
    if "\ntax:" in existing or existing.startswith("tax:"):
        raise SystemExit(f"{code}: {path} already ships a top-level tax block — refusing to append another")

    block = render_tax_block(pack)
    # Gate 1: the block alone round-trips through the typed model with exact Decimals.
    params = StateTaxParams.model_validate(yaml.safe_load(block)["tax"])
    _check_rates_exact(pack, params)

    candidate = existing.rstrip("\n") + "\n" + block
    path.write_text(candidate, encoding="utf-8")
    try:
        loaded = load_state_knowledge(code, year, base_dir=knowledge_dir)
        assert loaded.tax is not None
        _check_rates_exact(pack, loaded.tax)
        # Gate 2: every verified test vector recomputes through the real calc op.
        for i, v in enumerate(pack["test_vectors"]):
            r = state_tax(
                code,
                v["taxable_base"],
                year=year,
                exemptions_count=v["exemptions_count"],
                dependents_count=v["dependents_count"],
                filing_status=v["filing_status"],
                knowledge_dir=knowledge_dir,
            )
            assert r.base_after_exemptions == v["expected_base_after"], (
                f"{code} vector {i}: base_after {r.base_after_exemptions} != expected {v['expected_base_after']}"
            )
            assert r.tax == v["expected_tax"], (
                f"{code} vector {i}: tax {r.tax} != expected {v['expected_tax']} — {v['work']}"
            )
    except BaseException:
        path.write_text(existing, encoding="utf-8")  # restore on any gate failure
        raise
    if dry_run:
        path.write_text(existing, encoding="utf-8")
        print(f"{code}: OK (dry-run, {len(pack['test_vectors'])} vectors) — not written")
    else:
        print(f"{code}: tax block written to {path} ({len(pack['test_vectors'])} vectors recomputed clean)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("json_dir", type=Path, help="directory of verified <st>.json / g4-<st>.json packs")
    ap.add_argument("--year", type=int, default=2023)
    ap.add_argument("--states", default=None, help="comma-separated subset, e.g. ca,ny")
    ap.add_argument("--knowledge-dir", type=Path, default=REPO / "knowledge")
    ap.add_argument("--dry-run", action="store_true", help="run every gate but restore the file afterwards")
    args = ap.parse_args()

    only = set(args.states.split(",")) if args.states else None
    files = sorted(f for f in args.json_dir.glob("*.json") if not f.name.startswith("pending-"))
    if not files:
        raise SystemExit(f"no .json packs found in {args.json_dir}")
    failures: list[str] = []
    seen: set[str] = set()
    for f in files:
        pack = json.loads(f.read_text(encoding="utf-8"))
        code = pack.get("state")
        if not code:
            continue
        if only and code not in only:
            continue
        if code in seen:
            raise SystemExit(f"{code}: duplicate pack ({f}) — one verified pack per state")
        seen.add(code)
        try:
            assemble(pack, args.year, args.knowledge_dir, args.dry_run)
        except SystemExit:
            raise
        except BaseException as exc:  # loud per-state failure, keep going
            failures.append(code)
            print(f"{code}: FAILED a gate — file restored. {exc}", file=sys.stderr)
    if failures:
        raise SystemExit(f"gates failed for: {', '.join(failures)} — fix the packs and re-run")


if __name__ == "__main__":
    main()
