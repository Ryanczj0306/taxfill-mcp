#!/usr/bin/env python
"""Scaffold a state form-pack year tranche: derive + probe candidate blank-PDF URLs.

The D2a blocker named in the ROADMAP: state form packs were TY2023-only, and the
pipeline made a new year expensive — ``fetch_blank`` takes a literal URL+digest,
only some state URLs carry a substitutable year token, and there was no tool
that turned "46 packs for TY<year>" into a managed work-list.

This script does the mechanical half. For every state pack of a BASE year it:

1. reads the pack's ``source_url``;
2. derives a candidate URL for the TARGET year by substituting every year token
   it can prove is a year token: 4-digit years (the base year AND the base+1
   upload-folder year, mapped together — AL files its TY2023 Form 40 under
   ``uploads/2024/01/23f40.pdf``), 2-digit form-year prefixes like ``23f40.pdf``,
   and MMYY revision suffixes like CT's ``ct-1040_1223.pdf``. A basename carrying
   a revision DATE (DC's ``…_01222024.pdf``, ID's ``…_08-23-2023.pdf``) cannot be
   derived and is reported as ``revision-dated``;
3. optionally probes each candidate with an HTTP HEAD/GET (``--probe``) and
   records found / redirect / 404 / no-token;
4. emits a work-list JSON + a human table.

Phase J JS3a added:

* ``--base newest`` — each form's base is the NEWEST shipped year below the
  target (UT 2025 triages against UT 2024, not 2023);
* ``--rows <json>`` — recorded discovery rows (``scripts/state_discovery_rows.json``:
  state, form_dir, year, url, sha256, verdict) replace the derived candidate for
  their (state, form, year), and the triage reports whether it reproduces the
  recorded verdict;
* a cache-first triage: a blank already in ``--cache-dir`` (or in the shared
  blank cache, when the row pins a digest) is triaged without a download, a
  digest mismatch is reported instead of trusted, and ``--offline`` never touches
  the network (an uncached candidate is ``NOT-CACHED``).

What it deliberately does NOT do: download-and-trust, introspect, or author
packs. Every candidate that probes OK still goes through the full quality gate
(fetch_blank with a human-confirmed digest -> taxfill introspect -> vision
field-map -> adversarial audit -> golden tests) — see docs/dev/CONTRIBUTING-PACKS.md.
A no-token or 404 row is REAL WORK (find the year's URL on the DOR forms index;
MA additionally needs a digest-verified Wayback mirror) and the work-list makes
that visible instead of silently truncating the tranche.

Usage:
    python scripts/scaffold_state_year.py --base-year 2023 --target-year 2025
    python scripts/scaffold_state_year.py --base newest --target-year 2025 --triage \\
        --rows scripts/state_discovery_rows.json
    python scripts/scaffold_state_year.py --base newest --target-year 2025 --triage --offline
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
STATES = REPO / "formpacks" / "states"
DEFAULT_ROWS = REPO / "scripts" / "state_discovery_rows.json"

# A revision DATE in a basename: MMDDYY / MMDDYYYY / MM-DD-YYYY (DC 01222024, 011525; ID 08-23-2023). Month and day
# are range-checked so a form number next to a year (SC1040_2023) is not mistaken for one.
_REVISION_DATE = re.compile(r"(?<!\d)(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])[-_]?(?:20)?\d{2}(?!\d)")


def _candidate_url(url: str, base_year: int, target_year: int) -> tuple[str, bool]:
    """Substitute year tokens; returns (candidate, changed)."""
    shift = target_year - base_year
    head, _, tail = url.rpartition("/")
    # 4-digit years: the base year and the base+1 upload/publication year move together (AL: uploads/2024/01/23f40.pdf
    # -> uploads/2025/01/24f40.pdf). One pass, so base+1 -> target+1 cannot collide with base -> target.
    years = {str(base_year): str(target_year), str(base_year + 1): str(base_year + 1 + shift)}
    four = r"(?:(?<=%20)|(?<!\d))(\d{4})(?!\d)"      # a URL-encoded space (%20) separates, it does not join digits
    out_head = re.sub(four, lambda m: years.get(m.group(1), m.group(1)), head)
    out_tail = re.sub(four, lambda m: years.get(m.group(1), m.group(1)), tail)
    by2, ty2 = f"{base_year % 100:02d}", f"{target_year % 100:02d}"
    # Two-digit form-year prefixes in the basename only (e.g. 23f40.pdf -> 25f40.pdf),
    # guarded to the digit pair followed by a letter so we never touch route numbers.
    out_tail = re.sub(rf"(?<![0-9]){by2}(?=[A-Za-z])", ty2, out_tail)
    # MMYY revision suffixes at the end of the basename (CT: ct-1040_1223.pdf -> ct-1040_1224.pdf).
    def _mmyy(m: re.Match) -> str:
        yy = int(m.group(2))
        if yy in (base_year % 100, (base_year + 1) % 100):
            return f"{m.group(1)}{(yy + shift) % 100:02d}"
        return m.group(0)
    out_tail = re.sub(r"(?<=[_-])(0[1-9]|1[0-2])(\d{2})(?=\.pdf$)", _mmyy, out_tail)
    out = f"{out_head}/{out_tail}" if head else out_tail
    return out, out != url


def _revision_dated(url: str) -> bool:
    """True when the basename carries a revision DATE (MMDDYY / MMDDYYYY / MM-DD-YYYY) — not derivable."""
    return bool(_REVISION_DATE.search(urllib.parse.unquote(url.rpartition("/")[2])))


def _probe(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "taxfill-scaffold/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https .gov URLs from packs)
            ctype = resp.headers.get("Content-Type", "")
            return f"ok ({resp.status}, {ctype.split(';')[0] or 'unknown type'})"
    except Exception as exc:  # noqa: BLE001 — every failure is a work-list row, not a crash
        return f"unreachable ({type(exc).__name__}: {str(exc)[:60]})"


def _cached_blank(url: str, cache: Path, sha256: str | None) -> tuple[bytes | None, str | None]:
    """(bytes, None) from the triage cache or the shared blank cache; (None, reason) when absent or not the pin."""
    if cache.is_file():
        data = cache.read_bytes()
        if sha256 and hashlib.sha256(data).hexdigest() != sha256:
            return None, f"DIGEST-MISMATCH (cached {hashlib.sha256(data).hexdigest()[:12]}…, recorded {sha256[:12]}…)"
        return data, None
    if sha256:
        sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
        from taxfill_core.fetch import cached_blank_path  # noqa: PLC0415

        shared = cached_blank_path(url, sha256)
        if shared is not None:
            return shared.read_bytes(), None
    return None, None


def _triage(url: str, mapped: set[str], cache: Path, timeout: float = 45.0, *, sha256: str | None = None,
            offline: bool = False, base_sha256: str | None = None) -> tuple[str, dict]:
    """Classify the port cost of the candidate blank against the base pack — cache first, digest-checked.

    This is the measurement that string-derivation alone CANNOT give (and whose
    absence made this script's first version over-optimistic: 39 of 46 URLs
    *derive*, but only 16 of 42 actually resolve to a PDF for TY2025). A blank
    whose AcroForm carries every field name the base pack maps is a cheap port
    — the f1040nr path; anything else is real vision-mapping work.
    """
    data, problem = _cached_blank(url, cache, sha256)
    if problem:
        return problem, {}
    if data is None:
        if offline:
            return "NOT-CACHED (offline)", {}
        try:
            data = _download(url, timeout)
        except Exception as exc:  # noqa: BLE001
            return f"URL-DEAD ({type(exc).__name__})", {}
        if not data.startswith(b"%PDF"):
            return "URL-DEAD (not a PDF)", {}
        if sha256 and hashlib.sha256(data).hexdigest() != sha256:
            return f"DIGEST-MISMATCH (downloaded {hashlib.sha256(data).hexdigest()[:12]}…, recorded {sha256[:12]}…)", {}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    elif not data.startswith(b"%PDF"):
        return "URL-DEAD (not a PDF)", {}
    if base_sha256 and hashlib.sha256(data).hexdigest() == base_sha256:
        # JS5: NM TRD's gateway names a file by the GUID in its path, so a year swapped into the file name still
        # serves the BASE year's blank — once triaged as a print-only candidate for 2024 and 2025.
        return "SAME-AS-BASE (the candidate URL serves the base year's own blank)", {}
    try:
        from pypdf import PdfReader

        names = set((PdfReader(str(cache) if cache.is_file() else _spool(data, cache)).get_fields() or {}).keys())
    except Exception as exc:  # noqa: BLE001
        return f"UNREADABLE ({type(exc).__name__})", {}
    if not names:
        return "NO-ACROFORM (print-only that year?)", {}
    missing = [n for n in mapped if n not in names and not any(f.endswith("." + n) for f in names)]
    detail = {"blank_fields": len(names), "mapped": len(mapped), "missing": len(missing),
              "missing_sample": sorted(missing)[:5]}
    if not missing:
        return "PORTABLE (identical topology)", detail
    if len(missing) <= max(2, 0.05 * len(mapped)):
        return f"NEAR-PORT ({len(missing)} fields moved)", detail
    return f"RE-MAP ({len(missing)}/{len(mapped)} fields gone)", detail


# The browser User-Agent taxfill_core.fetch uses: CO's host 403s a non-browser agent (JS3a, 2026-09-28).
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0.0.0 Safari/537.36")


def _download(url: str, timeout: float) -> bytes:
    """GET with the browser User-Agent. A host with an incomplete TLS chain (tax.idaho.gov: Python's store lacks the
    intermediate a browser fetches by AIA) is retried through curl, which verifies against the system store — the
    bytes are still classified and, for a recorded row, digest-checked before they are used."""
    import ssl  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read()
    except urllib.error.URLError as exc:
        if not isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            raise
        done = subprocess.run(["curl", "-sSfL", "--max-time", str(int(timeout)), "-A", _BROWSER_UA, url],
                              capture_output=True, check=True)
        return done.stdout


def _spool(data: bytes, cache: Path) -> str:
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return str(cache)


def base_packs(target_year: int, base: str, states_dir: Path = STATES) -> list[tuple[int, Path]]:
    """(base year, pack path) for every form to triage: one fixed ``base`` year, or each form's newest year below target."""
    found: dict[tuple[str, str], tuple[int, Path]] = {}
    for pack_path in sorted(states_dir.glob("*/*/*/pack.yaml")) + sorted(states_dir.glob("*/*/*/handfill.yaml")):
        state, year_dir, form = pack_path.parts[-4], pack_path.parts[-3], pack_path.parts[-2]
        if not year_dir.isdigit():
            continue
        year = int(year_dir)
        if base == "newest":
            if year >= target_year:
                continue
            key = (state, form)
            if key not in found or year > found[key][0]:
                found[key] = (year, pack_path)
        elif year == int(base):
            found[(state, form)] = (year, pack_path)
    return [found[k] for k in sorted(found)]


def load_rows(path: Path | None) -> dict[tuple[str, str, int], dict]:
    if path is None or not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    return {(r["state"], r["form_dir"], int(r["year"])): r for r in rows}


def scaffold(target_year: int, base: str, *, rows_path: Path | None = None, probe: bool = False, triage: bool = False,
             offline: bool = False, cache_dir: Path | None = None, states_dir: Path = STATES) -> list[dict]:
    cache_dir = cache_dir or (REPO / ".cache" / "triage-blanks")
    rows = load_rows(rows_path)
    out = []
    for base_year, pack_path in base_packs(target_year, base, states_dir):
        state, form = pack_path.parts[-4], pack_path.parts[-2]
        raw = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
        url = raw.get("source_url") or ""
        row = {"state": state, "form": form, "kind": pack_path.name, "base_year": base_year, "base_url": url}
        shipped = states_dir / state / str(target_year) / form / pack_path.name
        if base == "newest" and shipped.is_file():
            # Nothing to port: the newest-base work-list is the OPEN work (a fixed --base keeps the old census).
            out.append({**row, "status": f"shipped ({target_year} pack exists)", "candidate_url": ""})
            continue
        recorded = rows.get((state, form, target_year))
        if recorded:
            candidate, changed, source = recorded["url"], True, "recorded"
        elif not url:
            out.append({**row, "status": "no-source-url", "candidate_url": ""})
            continue
        else:
            candidate, changed = _candidate_url(url, base_year, target_year)
            source = "derived"
        if source == "derived" and changed and _revision_dated(url):
            out.append({**row, "status": "revision-dated (needs a recorded row)", "candidate_url": candidate,
                        "source": source})
            continue
        status = "candidate" if changed else "no-year-token"
        detail: dict = {}
        if changed and triage:
            mapped = {e["field"] for e in (raw.get("fields") or []) if isinstance(e, dict) and "field" in e}
            status, detail = _triage(candidate, mapped, cache_dir / f"{state}-{form}-{target_year}.pdf",
                                     sha256=(recorded or {}).get("sha256"), offline=offline,
                                     base_sha256=raw.get("pdf_sha256"))
        elif changed and probe and not offline:
            status = _probe(candidate)
        if recorded:
            detail["recorded_verdict"] = recorded["verdict"]
            detail["reproduces"] = status.split(" (")[0] == recorded["verdict"] if triage else None
        out.append({**row, "candidate_url": candidate if changed else "", "source": source, "status": status,
                    **detail})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-year", type=int, default=None, help="the base year (same as --base <year>)")
    ap.add_argument("--base", default=None, help="a base year, or 'newest' (each form's newest year below the target)")
    ap.add_argument("--target-year", type=int, required=True)
    ap.add_argument("--rows", type=Path, default=None,
                    help=f"recorded discovery rows (JSON), e.g. {DEFAULT_ROWS.relative_to(REPO)}")
    ap.add_argument("--probe", action="store_true", help="HTTP HEAD each candidate (network)")
    ap.add_argument("--triage", action="store_true",
                    help="classify the port cost against the base pack's field map, cache first (downloads a "
                         "missing candidate unless --offline). This is the number that matters — string "
                         "derivation alone over-reports by ~2x.")
    ap.add_argument("--offline", action="store_true", help="never touch the network: triage only cached blanks")
    ap.add_argument("--cache-dir", type=Path, default=None, help="where --triage looks for and stores blanks")
    ap.add_argument("--out", type=Path, default=None, help="work-list JSON path (default: stdout summary only)")
    args = ap.parse_args()
    base = args.base or (str(args.base_year) if args.base_year else None)
    if base is None:
        ap.error("pass --base <year|newest> (or --base-year <year>)")

    rows = scaffold(args.target_year, base, rows_path=args.rows, probe=args.probe, triage=args.triage,
                    offline=args.offline, cache_dir=args.cache_dir)
    n_shipped = sum(1 for r in rows if r["status"].startswith("shipped"))
    n_candidates = sum(1 for r in rows if r["candidate_url"])
    n_blocked = len(rows) - n_candidates - n_shipped
    for r in rows:
        mark = "" if r.get("reproduces") in (None, True) else f"  [recorded {r['recorded_verdict']}]"
        print(f"{r['state']:>3} {r['form']:<16} {r['base_year']} {r['status']:<44} "
              f"{r['candidate_url'] or r['base_url']}{mark}")
    print(f"\n{len(rows)} packs: {n_shipped} already shipped, {n_candidates} with a candidate URL, {n_blocked} needing "
          f"manual URL research "
          f"(no year token / no source_url) — none are done until they pass fetch_blank + introspect + vision audit "
          f"+ golden tests.")
    if args.triage:
        buckets: dict[str, int] = {}
        for r in rows:
            buckets[r["status"].split(" (")[0]] = buckets.get(r["status"].split(" (")[0], 0) + 1
        print("Triage verdicts (this is the real cost breakdown):")
        for verdict, count in sorted(buckets.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>3}  {verdict}")
        recorded = [r for r in rows if r.get("recorded_verdict")]
        if recorded:
            print(f"  recorded rows reproduced: {sum(1 for r in recorded if r['reproduces'])}/{len(recorded)}")
        print("  PORTABLE/NEAR-PORT = the cheap path (swap URL+digest, then STILL vision-audit every "
              "page: identical field NAMES do not prove the state kept its line NUMBERING).")
    if args.out:
        args.out.write_text(json.dumps({"base": base, "target_year": args.target_year, "packs": rows}, indent=2),
                            encoding="utf-8")
        print(f"work-list written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
