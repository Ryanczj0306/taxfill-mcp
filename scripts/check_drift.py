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
  * **Mailing addresses / where-to-file** — for every ``mailing_addresses``
    citation URL in the federal and per-state knowledge packs (the "where do you
    file?" pages the shipped paper-filing addresses are transcribed from),
    confirm it still resolves. These verify-URLs live inside the knowledge YAMLs
    and are *not* in ``sources.yaml``, so without this check a relocated
    where-to-file page — and the silently-stale address it leaves behind — would
    go unnoticed until a user mailed a return to the wrong PO box. Reachability
    only (page content moves legitimately); a dead URL is drift.

Exit code is nonzero if anything DRIFTED (revised blank, a dead source URL, or a
dead where-to-file page), zero otherwise. Network access required — this is a
scheduled job, not part of the offline unit suite. Run:
``python scripts/check_drift.py``.
"""
from __future__ import annotations

import ssl
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


def _collect_mailing_urls(node, out: list[str]) -> None:
    """Recursively gather every ``url:`` nested under a ``mailing_addresses`` key.

    Scoped deliberately to mailing-address blocks so this checks the where-to-file
    pages specifically — not every cited fact in the knowledge pack (those carry
    their own ``citation.url`` and are out of scope for the address-drift check).
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "mailing_addresses":
                _collect_source_urls(value, out)
            else:
                _collect_mailing_urls(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_mailing_urls(item, out)


def _not_drift_reason(exc: BaseException) -> str | None:
    """Classify a fetch failure that is NOT evidence a form moved/changed.

    Returns a short warn label ('SSL cert' / 'blocked HTTP <code>' / 'timeout')
    when the failure is a transport/trust issue — an incomplete TLS chain (some
    state .gov sites serve missing intermediates that browsers fetch via AIA but
    a strict CA bundle rejects), a 403/429 bot block, or a read/connect timeout
    (the host answered but was slow — a transient flake) — and ``None`` when it
    is genuine, actionable drift (404/moved, DNS-gone, connection refused).
    Walks the exception chain because ``fetch._download`` wraps the original
    error in FetchError/OfflineFetchError ``from exc``.
    """
    seen: BaseException | None = exc
    while seen is not None:
        reason = getattr(seen, "reason", None)
        if isinstance(seen, ssl.SSLError) or isinstance(reason, ssl.SSLError):
            return "SSL cert"
        if isinstance(seen, urllib.error.HTTPError) and seen.code in (403, 429):
            return f"blocked HTTP {seen.code}"
        # A read/connect TIMEOUT means we reached the host but it was slow — a
        # transient flake, not a moved form (these state hosts return 200 most
        # nights). Genuine drift is DNS-gone / refused / 404, which are NOT timeouts.
        if isinstance(seen, TimeoutError) or isinstance(reason, TimeoutError):
            return "timeout"
        seen = seen.__cause__ or seen.__context__
    return None


def _probe_urls(urls: list[str], label: str) -> list[str]:
    """Confirm each URL still resolves. TLS-chain and 403/429 failures are warn-only
    (transport/trust, not a move); any other failure is drift. Returns the drift list."""
    drift: list[str] = []
    print(f"\n=== {label} ({len(urls)} URLs) ===")
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
                drift.append(f"{label}: {url} -> HTTP {exc.code}")
                print(f"  DRIFT  {exc.code} {url}")
        except Exception as exc:
            reason = _not_drift_reason(exc)
            if reason is not None:
                print(f"  warn   {reason} (not drift) {url}")
            else:
                drift.append(f"{label}: {url} unreachable — {exc}")
                print(f"  DRIFT  unreachable {url}")
    return drift


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
            # A TLS-chain / 403-block failure is a transport/trust issue, not a moved
            # or revised form — warn like _probe_urls, don't fail the job. Only a genuine
            # move (404/DNS/refused) counts as drift. (Fixes the recurring nightly-CI red
            # from state hosts like www.dor.ms.gov serving an incomplete cert chain.)
            reason = _not_drift_reason(exc)
            if reason is not None:
                print(f"  warn   {rel}: {reason} (not drift) {pack.source_url}")
                continue
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
    return _probe_urls(sorted(set(urls)), "Source registry")


def check_mailing_addresses() -> list[str]:
    """Re-fetch every where-to-file / mailing-address citation URL in the federal
    and per-state knowledge packs and flag any that no longer resolve."""
    urls: list[str] = []
    knowledge = REPO / "knowledge"
    packs = sorted(knowledge.glob("federal/*.yaml")) + sorted(knowledge.glob("states/**/*.yaml"))
    for path in packs:
        try:
            raw = yaml.safe_load(path.read_text())
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  skip   {path.relative_to(REPO)}: parse error — {exc}")
            continue
        _collect_mailing_urls(raw, urls)
    return _probe_urls(sorted(set(urls)), "Mailing addresses / where-to-file")


def main() -> int:
    drift = check_form_blanks() + check_source_urls() + check_mailing_addresses()
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
