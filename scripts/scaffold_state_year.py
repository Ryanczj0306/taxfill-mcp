#!/usr/bin/env python
"""Scaffold a state form-pack year tranche: derive + probe candidate blank-PDF URLs.

The D2a blocker named in the ROADMAP: state form packs are TY2023-only, and the
pipeline made a new year expensive — ``fetch_blank`` takes a literal URL+digest,
only some state URLs carry a substitutable year token, and there was no tool
that turned "46 packs for TY<year>" into a managed work-list.

This script does the mechanical half. For every state pack of a BASE year it:

1. reads the pack's ``source_url``;
2. derives a candidate URL for the TARGET year by substituting every year token
   it can prove is a year token (4-digit year, 2-digit form-year prefixes like
   ``23f40.pdf``, and year-containing path segments);
3. optionally probes each candidate with an HTTP HEAD/GET (``--probe``) and
   records found / redirect / 404 / no-token;
4. emits a work-list JSON + a human table.

What it deliberately does NOT do: download-and-trust, introspect, or author
packs. Every candidate that probes OK still goes through the full quality gate
(fetch_blank with a human-confirmed digest -> taxfill introspect -> vision
field-map -> adversarial audit -> golden tests) — see docs/CONTRIBUTING-PACKS.md.
A no-token or 404 row is REAL WORK (find the year's URL on the DOR forms index;
MA additionally needs its Wayback cache-seed) and the work-list makes that
visible instead of silently truncating the tranche.

Usage:
    python scripts/scaffold_state_year.py --base-year 2023 --target-year 2025
    python scripts/scaffold_state_year.py --base-year 2023 --target-year 2025 --probe
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
STATES = REPO / "formpacks" / "states"


def _candidate_url(url: str, base_year: int, target_year: int) -> tuple[str, bool]:
    """Substitute year tokens; returns (candidate, changed)."""
    by, ty = str(base_year), str(target_year)
    by2, ty2 = by[-2:], ty[-2:]
    out = url.replace(by, ty)
    # Two-digit form-year prefixes in the basename only (e.g. 23f40.pdf -> 25f40.pdf),
    # guarded to the digit pair followed by a letter so we never touch route numbers.
    head, _, tail = out.rpartition("/")
    tail2 = re.sub(rf"(?<![0-9]){by2}(?=[A-Za-z])", ty2, tail)
    if tail2 != tail:
        out = f"{head}/{tail2}"
    return out, out != url


def _probe(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "taxfill-scaffold/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https .gov URLs from packs)
            ctype = resp.headers.get("Content-Type", "")
            return f"ok ({resp.status}, {ctype.split(';')[0] or 'unknown type'})"
    except Exception as exc:  # noqa: BLE001 — every failure is a work-list row, not a crash
        return f"unreachable ({type(exc).__name__}: {str(exc)[:60]})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-year", type=int, required=True)
    ap.add_argument("--target-year", type=int, required=True)
    ap.add_argument("--probe", action="store_true", help="HTTP HEAD each candidate (network)")
    ap.add_argument("--out", type=Path, default=None, help="work-list JSON path (default: stdout summary only)")
    args = ap.parse_args()

    rows = []
    for pack_path in sorted(STATES.glob(f"*/{args.base_year}/*/pack.yaml")) + sorted(
        STATES.glob(f"*/{args.base_year}/*/handfill.yaml")
    ):
        state = pack_path.parts[-4]
        form = pack_path.parts[-2]
        raw = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
        url = raw.get("source_url") or ""
        if not url:
            rows.append({"state": state, "form": form, "status": "no-source-url", "base_url": "", "candidate_url": ""})
            continue
        candidate, changed = _candidate_url(url, args.base_year, args.target_year)
        status = "candidate" if changed else "no-year-token"
        if changed and args.probe:
            status = _probe(candidate)
        rows.append({"state": state, "form": form, "kind": pack_path.name,
                     "base_url": url, "candidate_url": candidate if changed else "",
                     "status": status})

    n_candidates = sum(1 for r in rows if r["candidate_url"])
    n_blocked = len(rows) - n_candidates
    for r in rows:
        print(f"{r['state']:>3} {r['form']:<16} {r['status']:<40} {r['candidate_url'] or r['base_url']}")
    print(f"\n{len(rows)} packs: {n_candidates} with a derivable candidate URL, "
          f"{n_blocked} needing manual URL research (no year token / no source_url) — "
          f"none are done until they pass fetch_blank + introspect + vision audit + golden tests.")
    if args.out:
        args.out.write_text(json.dumps(
            {"base_year": args.base_year, "target_year": args.target_year, "packs": rows},
            indent=2), encoding="utf-8")
        print(f"work-list written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
