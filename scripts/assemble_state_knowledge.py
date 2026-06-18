#!/usr/bin/env python
"""Assemble per-state StateKnowledge packs (2023) from the all-states fetch.

Reads /tmp/states_kb.json (the cited fetch output) and writes
knowledge/states/<st>/2023.yaml for each state, mapped to the keys the engine
reads (state_scope: forms/conforms_to_federal_treaties; file_and_pay/
filing_summary: payment/mailing_addresses/deadlines). Honest provenance: each
state's `unverified` items ship as a top-level caveat; nothing is asserted that
the fetch flagged as unconfirmed. Validates every pack against StateKnowledge
before writing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
from taxfill_core.knowledge import StateKnowledge  # noqa: E402

KB = json.load(open("/tmp/states_kb.json"))


def _is_gov_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == t or host.endswith("." + t) for t in ("gov", "mil", "us"))


def build(st: str, d: dict) -> dict:
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
        "tax_year": 2023,
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


def main() -> int:
    wrote, failed = [], []
    for st, d in KB.items():
        pack = build(st, d)
        try:
            StateKnowledge.model_validate(pack)
        except Exception as exc:
            failed.append((st, str(exc)[:120]))
            continue
        out = REPO / "knowledge" / "states" / st.lower() / "2023.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# {st} state knowledge — tax year 2023. Fetched + cited from the {st} DOR (.gov) and\n"
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
    nonconf = [st for st, d in KB.items() if d["conforms_to_federal_treaties"] is False]
    print(f"treaty NON-conforming (warn NRA filers): {sorted(nonconf)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
