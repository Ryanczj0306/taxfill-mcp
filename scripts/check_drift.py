#!/usr/bin/env python
"""Freshness / drift check — dev plan section 7 (the nightly job).

The shipped knowledge packs and form-pack field maps are snapshots of moving
official sources. This script re-fetches every authoritative URL the repo
depends on and flags drift loudly, so a moved page or a new form revision is
caught by CI rather than by a user mid-filing:

  * **Form blanks** — for every ``formpacks/**/pack.yaml`` with a real
    ``pdf_sha256``, download ``source_url`` and recompute the digest. A mismatch
    means the official blank was revised (the field map may no longer line up);
    an unreachable URL means it moved.
  * **Source registry** — for every URL in ``knowledge/sources.yaml`` (the
    section-7 "where truth lives" registry), confirm it still resolves. Pages
    legitimately change content, so we check reachability, not a checksum.

Exit code is nonzero if anything DRIFTED (revised blank, or a dead source URL),
zero otherwise. Network access required — this is a scheduled job, not part of
the offline unit suite. Run: ``python scripts/check_drift.py``.
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))

from taxfill_core.fetch import _USER_AGENT, _download, compute_sha256  # noqa: E402
from taxfill_core.schemas.formpack import load_pack  # noqa: E402

SHA_PLACEHOLDER = "." * 3
TIMEOUT = 30.0


def _collect_source_urls(node, out: list[str]) -> None:
    """Recursively gather every ``url:`` value in sources.yaml."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "url" and isinstance(value, str):
                out.append(value)
            else:
                _collect_source_urls(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_source_urls(item, out)


def check_form_blanks() -> list[str]:
    drift: list[str] = []
    packs = sorted((REPO / "formpacks").rglob("pack.yaml"))
    print(f"\n=== Form blanks ({len(packs)} packs) ===")
    for path in packs:
        rel = path.relative_to(REPO).parent
        try:
            pack = load_pack(path)
        except Exception as exc:  # pragma: no cover - defensive
            drift.append(f"{rel}: pack failed to load — {exc}")
            print(f"  DRIFT  {rel}: pack load error")
            continue
        if not pack.pdf_sha256 or pack.pdf_sha256.startswith(SHA_PLACEHOLDER):
            print(f"  skip   {rel}: no recorded digest (unverified pack)")
            continue
        try:
            tmp = REPO / ".cache" / "drift" / (rel.as_posix().replace("/", "_") + ".pdf")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(_download(pack.source_url, TIMEOUT))
            actual = compute_sha256(tmp)
        except Exception as exc:
            drift.append(f"{rel}: source_url unreachable — {pack.source_url} ({exc})")
            print(f"  DRIFT  {rel}: UNREACHABLE {pack.source_url}")
            continue
        if actual.lower() != pack.pdf_sha256.lower():
            drift.append(f"{rel}: blank REVISED — recorded {pack.pdf_sha256[:12]}…, now {actual[:12]}… ({pack.source_url})")
            print(f"  DRIFT  {rel}: REVISED (checksum changed)")
        else:
            print(f"  ok     {rel}")
    return drift


def check_source_urls() -> list[str]:
    raw = yaml.safe_load((REPO / "knowledge" / "sources.yaml").read_text())
    urls: list[str] = []
    _collect_source_urls(raw, urls)
    urls = sorted(set(urls))
    drift: list[str] = []
    print(f"\n=== Source registry ({len(urls)} URLs) ===")
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                code = resp.getcode()
            print(f"  ok     {code} {url}")
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):  # blocked/throttled bot, not a move — warn only
                print(f"  warn   {exc.code} (blocked, not drift) {url}")
            else:
                drift.append(f"source URL {url} -> HTTP {exc.code}")
                print(f"  DRIFT  {exc.code} {url}")
        except Exception as exc:
            drift.append(f"source URL {url} unreachable — {exc}")
            print(f"  DRIFT  unreachable {url}")
    return drift


def main() -> int:
    drift = check_form_blanks() + check_source_urls()
    print("\n" + "=" * 60)
    if drift:
        print(f"DRIFT DETECTED — {len(drift)} item(s) need attention:")
        for d in drift:
            print(f"  • {d}")
        print("\nRe-verify the moved/revised source, re-audit the affected pack, and update the digest.")
        return 1
    print("No drift — all form blanks match their recorded digest and all source URLs resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
