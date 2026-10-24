#!/usr/bin/env python
"""Assemble per-state StateKnowledge packs for one tax year from an all-states fetch.

Usage:
    python scripts/assemble_state_knowledge.py --year 2026 --input /path/to/states_kb.json

The input JSON is the cited fetch output: {"<ST>": {...facts, "citations": [{source, url}],
"unverified": [...]}} per state — produced by the verbatim-transcription fetch agents
(never from memory). Writes knowledge/states/<st>/<year>.yaml for each state, mapped
to the keys the engine reads (state_scope: forms/conforms_to_federal_treaties;
file_and_pay/filing_summary: payment/mailing_addresses/deadlines). Honest provenance:
each state's `unverified` items ship as a top-level caveat; nothing is asserted that
the fetch flagged as unconfirmed. Validates every pack against StateKnowledge before
writing.

History: the 2023 cohort was assembled by this script from a /tmp fetch whose input
no longer exists; the 2024/2025 cohorts were authored by per-state verification agents
directly. The --year/--input parameters (added 2026-08-10, D2b) make future cohorts
(TY2026+) re-runnable from a preserved input file — commit the input alongside the
packs or note where it lives.

Phase K JK20 (2026-10-24): a TY2025-and-later pack also carries a top-level ``sources``
table that the source registry is built from. Run ``python scripts/hoist_state_sources.py
--year <year>`` after this script (test_state_sources_table.py fails on a pack without one).

Phase K JK25 (2026-10-24): TY2026 AND LATER packs are written as schema v2
(taxfill_core.knowledge_v2.StateKnowledgeV2) by scripts/state_knowledge_v2_writer.py, which
this script hands every state's fact set to:

    python scripts/assemble_state_knowledge.py --year 2026 --input facts.json \
        [--tax-dir DIR] [--credits credits.json] [--knowledge-dir knowledge]

The v2 input shape (quotes with their citations, credit pointers, logistics, gaps) is in the
writer's docstring; ``--tax-dir`` takes the tax-block workflow's verified JSON (the
assemble_state_tax_blocks.py input, its ``notes`` written as ``caveats``) and ``--credits`` the
credits research (the assemble_state_credits.py input, items as credit pointers). The pack is
written whole, `sources` table included, so neither those two scripts nor
hoist_state_sources.py runs after it. A v1 field (residency_summary, filing_requirement_note,
starts_from, treaty_basis, a credit amount, ...) is refused with what to drop or reword.
TY2025 and earlier keep the v1 behaviour above, byte for byte.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
from taxfill_core.knowledge import StateKnowledge  # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))
import state_knowledge_v2_writer as v2_writer  # noqa: E402


def _is_gov_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == t or host.endswith("." + t) for t in ("gov", "mil", "us"))


def build(st: str, d: dict, year: int) -> dict:
    cites = d.get("citations") or []
    # The typed Citation fields require a government host; some DORs serve form
    # PDFs from a CDN (e.g. NM on amazonaws.com) but also cite a .gov page — pick
    # the first government-host citation as primary.
    gov_cites = [c for c in cites if _is_gov_host(c.get("url", ""))]
    primary = (gov_cites or cites or [None])[0] or {"source": f"{st} Department of Revenue", "url": "https://www.irs.gov/businesses/small-businesses-self-employed/state-government-websites"}
    if not _is_gov_host(primary.get("url", "")):
        primary = {"source": f"{st} Department of Revenue", "url": "https://www.irs.gov/businesses/small-businesses-self-employed/state-government-websites"}
    pack = {
        "jurisdiction": f"states/{st.lower()}",
        "tax_year": year,
        "income_tax": True,
        "conforms_to_federal_treaties": bool(d["conforms_to_federal_treaties"]),
        "treaty_note": d["treaty_basis"],
        "citation": {"source": primary["source"], "url": primary["url"]},
        "starts_from": d.get("starts_from", ""),
        "residency": {"summary": d.get("residency_summary", "")},
        "forms": {
            "resident": d.get("resident_form", ""),
            "part_year_or_nonresident": d.get("nonresident_or_part_year_form", ""),
        },
        "filing_requirement": {"note": d.get("filing_requirement_note", "")},
        "mailing_addresses": {
            "refund_or_no_payment": (d.get("mailing") or {}).get("refund_or_no_payment", ""),
            "with_payment": (d.get("mailing") or {}).get("with_payment", ""),
            "citation": {"source": primary["source"], "url": primary["url"]},
        },
        "payment": {
            "check_payee": (d.get("payment") or {}).get("check_payee", ""),
            "web_pay_url": (d.get("payment") or {}).get("online_portal_url", ""),
        },
        "deadlines": {
            "filing_due_date": d.get("filing_due_date", ""),
            "citation": {"source": primary["source"], "url": primary["url"]},
        },
        "all_citations": [{"source": c["source"], "url": c["url"]} for c in cites],
    }
    unver = d.get("unverified") or []
    if unver:
        pack["unverified"] = unver
        pack["mailing_addresses"]["verification"] = "Some state facts could not be independently re-confirmed — see the pack's `unverified` list; confirm at the cited DOR source before relying on a specific figure/address."
    return pack


def _main_v2(kb: dict, args: argparse.Namespace) -> int:
    """TY2026+: every state's fact set through the v2 writer (Phase K JK25)."""
    wrote, refused = v2_writer.assemble(kb, args.year, args.knowledge_dir, tax_dir=args.tax_dir,
                                        credits_file=args.credits)
    print(f"wrote {len(wrote)} schema v2 state knowledge packs for TY{args.year}: {sorted(wrote)}")
    if refused:
        print(f"REFUSED ({len(refused)}), nothing written for these states:")
        for _, why in refused:
            print(f"  {why}")
    if wrote:
        print("each pack carries its own `sources` table: do not run hoist_state_sources.py, "
              "assemble_state_tax_blocks.py or assemble_state_credits.py after this")
    return 1 if refused else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True, help="tax year the fetch covers, e.g. 2026")
    ap.add_argument("--input", type=Path, required=True, help="path to the cited all-states fetch JSON")
    ap.add_argument("--knowledge-dir", type=Path, default=REPO / "knowledge",
                    help="the knowledge tree to write into (default: the repo's)")
    ap.add_argument("--tax-dir", type=Path, help="TY2026+: the tax-block workflow's verified <st>.json files")
    ap.add_argument("--credits", type=Path, help="TY2026+: the credits research JSON ({result: [...]})")
    args = ap.parse_args(argv)
    kb = json.loads(args.input.read_text(encoding="utf-8"))
    if args.year >= v2_writer.V2_FIRST_WRITTEN_YEAR:
        return _main_v2(kb, args)
    if args.tax_dir is not None or args.credits is not None:
        ap.error(f"--tax-dir and --credits are for TY{v2_writer.V2_FIRST_WRITTEN_YEAR}+ (schema v2); a TY{args.year} "
                 f"pack takes its tax block and credits from assemble_state_tax_blocks.py / assemble_state_credits.py")

    wrote, failed = [], []
    for st, d in kb.items():
        pack = build(st, d, args.year)
        try:
            StateKnowledge.model_validate(pack)
        except Exception as exc:
            failed.append((st, str(exc)[:120]))
            continue
        out = args.knowledge_dir / "states" / st.lower() / f"{args.year}.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# {st} state knowledge — tax year {args.year}. Fetched + cited from the {st} DOR (.gov) and\n"
            f"# assembled by scripts/assemble_state_knowledge.py. Loaded as a StateKnowledge.\n"
            f"# conforms_to_federal_treaties: whether federally treaty-exempt income flows through\n"
            f"# (most states start from federal AGI) or is added back (CA/CT/MD/MS-style). Figures the\n"
            f"# fetch could not independently confirm are in `unverified` — confirm at the cited source.\n"
        )
        out.write_text(header + yaml.dump(pack, sort_keys=False, allow_unicode=True, width=110))
        wrote.append(st)
    print(f"wrote {len(wrote)} state knowledge packs: {sorted(wrote)}")
    if failed:
        print(f"FAILED ({len(failed)}):")
        for st, e in failed:
            print(f"  {st}: {e}")
    nonconf = [st for st, d in kb.items() if d["conforms_to_federal_treaties"] is False]
    print(f"treaty NON-conforming (warn NRA filers): {sorted(nonconf)}")
    if wrote:
        print(f"next: python scripts/hoist_state_sources.py --year {args.year}  (each pack's `sources` table)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
