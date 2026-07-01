#!/usr/bin/env python
"""Merge the cited state-credits research into each state knowledge pack.

Reads the state-credits-fetch workflow output (a {result:[...]} JSON) and adds a
`credits` block (+ a `credits_verification` caveat) to knowledge/states/<st>/
2023.yaml, mirroring the CA pack's shape. Honest provenance: every credit keeps
its DOR citation; any figure the research could not independently confirm is kept
with `unverified: true` and named in the caveat. Validates each pack against
StateKnowledge before writing.

Usage: python scripts/assemble_state_credits.py /tmp/credits_raw.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
from taxfill_core.knowledge import StateKnowledge, load_state_knowledge  # noqa: E402

NAME_TO_CODE = {
    "indiana": "in", "new mexico": "nm", "oklahoma": "ok", "vermont": "vt",
}


def _code(state: str) -> str:
    s = state.strip().lower()
    return NAME_TO_CODE.get(s, s)


def _is_gov(url: str) -> bool:
    h = (urlparse(url).hostname or "").lower()
    return any(h == t or h.endswith("." + t) for t in ("gov", "mil", "us"))


def _build_credits(entry: dict) -> tuple[list[dict], str]:
    credits: list[dict] = []
    unverified_names: list[str] = []
    for c in entry.get("credits", []):
        if not _is_gov(c.get("citation_url", "")):
            # Defensive: never ship a credit cited to a non-government host.
            continue
        item = {
            "name": c["name"],
            "type": c["type"],
            "eligibility": c.get("eligibility", ""),
        }
        if c.get("amount"):
            item["amount"] = c["amount"]
        if c.get("income_limit"):
            item["income_limit_2023"] = c["income_limit"]
        if c.get("claimed_on"):
            item["claimed_on"] = c["claimed_on"]
        item["citation"] = {
            "source": c.get("citation_source") or f"{entry['state']} Department of Revenue",
            "url": c["citation_url"],
        }
        if c.get("unverified"):
            item["unverified"] = True
            unverified_names.append(c["name"])
        credits.append(item)

    caveat = (
        "State credits were researched from the cited DOR sources and are not tax advice — confirm "
        "each amount and your eligibility at the cited source before claiming it."
    )
    if unverified_names:
        caveat += " Not independently confirmed (verify the figure): " + "; ".join(unverified_names) + "."
    return credits, caveat


def main() -> int:
    raw = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/credits_raw.json"))
    data = raw["result"] if isinstance(raw, dict) and "result" in raw else raw
    wrote, failed, total_credits = [], [], 0
    for entry in data:
        code = _code(entry["state"])
        path = REPO / "knowledge" / "states" / code / "2023.yaml"
        if not path.exists():
            failed.append((code, "pack file not found"))
            continue
        pack = yaml.safe_load(path.read_text())
        credits, caveat = _build_credits(entry)
        if not credits:
            continue
        # inject after `forms`
        new: dict = {}
        for k, v in pack.items():
            if k in ("credits", "credits_verification"):
                continue
            new[k] = v
            if k == "forms":
                new["credits_verification"] = caveat
                new["credits"] = credits
        if "credits" not in new:  # no `forms` key — append
            new["credits_verification"] = caveat
            new["credits"] = credits
        try:
            StateKnowledge.model_validate(new)
        except Exception as exc:
            failed.append((code, str(exc)[:140]))
            continue
        header = path.read_text().split("\n")
        comment = "\n".join(ln for ln in header if ln.startswith("#"))
        path.write_text((comment + "\n" if comment else "") + yaml.dump(new, sort_keys=False, allow_unicode=True, width=110))
        wrote.append(code)
        total_credits += len(credits)

    print(f"wrote credits into {len(wrote)} packs ({total_credits} credits total): {sorted(wrote)}")
    if failed:
        print(f"FAILED ({len(failed)}):")
        for c, e in failed:
            print(f"  {c}: {e}")
    # smoke: reload a couple and confirm benefits surface
    for code in ("ar", "ny", "co"):
        if code in wrote:
            sk = load_state_knowledge(code, 2023, base_dir=REPO / "knowledge")
            print(f"  {code}: {len(getattr(sk, 'credits', []) or [])} credits load OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
