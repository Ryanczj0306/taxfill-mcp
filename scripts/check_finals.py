#!/usr/bin/env python
"""Finals watch (Phase J JT0c): has the IRS posted the final revision of a form a draft pack mirrors?

A draft pack (``source_status: draft``) is authored against ``irs.gov/pub/irs-dft/<form>--dft.pdf``
while its year's knowledge pack is provisional. The final revision lands at
``irs.gov/pub/irs-prior/<form>--<year>.pdf``. This script HEADs that URL for every draft pack of the
newest provisional federal year, plus the publications the year's knowledge pack waits on (Pub 1040,
the Form 1040 instructions and Pub 501; all 404 for 2026 on 2026-09-23). Any that answer 200 are
the re-pin list, and the script opens or updates ONE issue labeled ``ty<year>-finals: re-pin now``.
That issue is JT6's only trigger, so the watch runs in its own workflow (.github/workflows/finals.yml),
not in freshness.yml, whose failures carry other reds.

    python scripts/check_finals.py                 # HEAD, then file/update the issue via gh
    python scripts/check_finals.py --dry-run       # HEAD, print the re-pin list and the issue; file nothing
    python scripts/check_finals.py --dry-run --assume-posted f1040es   # rehearse the issue offline

Exit 0 when the watch ran (whether or not anything posted), 1 when a HEAD failed for a reason
other than 404 (a blind watch must not look like a quiet one).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))

from taxfill_core.fetch import _USER_AGENT  # noqa: E402
from taxfill_core.knowledge import provisional_marker  # noqa: E402
from taxfill_core.schemas.formpack import load_pack  # noqa: E402

# The year-level publications the provisional knowledge pack waits on (docs/ROADMAP.md JT0c).
PUBLICATIONS = ("p1040", "i1040gi", "p501")
FINAL_URL = "https://www.irs.gov/pub/irs-prior/{stem}--{year}.pdf"
TIMEOUT = 30.0


@dataclass(frozen=True)
class Watched:
    stem: str      # the IRS file stem, e.g. "f1040s1a"
    why: str       # "draft pack formpacks/federal/2026/sched_1a (Created 4/27/26)" or "publication"

    def final_url(self, year: int) -> str:
        return FINAL_URL.format(stem=self.stem, year=year)


def provisional_year(repo: Path = REPO) -> int | None:
    """The newest federal year whose knowledge pack is provisional; None when every year is filing-grade."""
    years = sorted(int(p.stem) for p in (repo / "knowledge" / "federal").glob("[0-9][0-9][0-9][0-9].yaml"))
    provisional = [y for y in years if provisional_marker("federal", y) is not None]
    return provisional[-1] if provisional else None


def _draft_stem(source_url: str) -> str:
    name = source_url.rstrip("/").rsplit("/", 1)[-1]
    return name.removesuffix(".pdf").removesuffix("--dft")


def watch_list(year: int, repo: Path = REPO) -> list[Watched]:
    """Every federal draft pack of ``year`` (by its IRS file stem) plus the year-level publications."""
    watched: dict[str, Watched] = {}
    for path in sorted((repo / "formpacks" / "federal" / str(year)).glob("*/pack.yaml")):
        pack = load_pack(path)
        if pack.source_status == "draft":
            stem = _draft_stem(pack.source_url)
            rel = path.parent.relative_to(repo).as_posix()
            watched.setdefault(stem, Watched(stem, f"draft pack {rel} (Created {pack.draft_created})"))
    for stem in PUBLICATIONS:
        watched.setdefault(stem, Watched(stem, "publication"))
    return list(watched.values())


def head_status(url: str) -> int:
    """The HTTP status of a HEAD request (404 is an answer, not an error)."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.getcode()
    except urllib.error.HTTPError as exc:
        return exc.code


@dataclass
class WatchResult:
    year: int
    posted: list[Watched]
    missing: list[Watched]
    errors: list[str]


def run_watch(year: int, watched: list[Watched], head: Callable[[str], int] = head_status,
              assume_posted: frozenset[str] = frozenset()) -> WatchResult:
    result = WatchResult(year, [], [], [])
    for w in watched:
        url = w.final_url(year)
        if w.stem in assume_posted:
            result.posted.append(w)
            print(f"  ASSUMED  {url}  ({w.why})")
            continue
        try:
            code = head(url)
        except Exception as exc:  # a timeout or DNS failure blinds the watch
            result.errors.append(f"{url}: {exc}")
            print(f"  ERROR    {url}  {exc}")
            continue
        if code == 200:
            result.posted.append(w)
            print(f"  POSTED   {url}  ({w.why})")
        elif code == 404:
            result.missing.append(w)
            print(f"  404      {url}")
        else:
            result.errors.append(f"{url}: HTTP {code}")
            print(f"  ERROR    {url}  HTTP {code}")
    return result


def issue_label(year: int) -> str:
    return f"ty{year}-finals: re-pin now"


def issue_title(year: int) -> str:
    return f"TY{year} finals posted: re-pin the draft packs (JT6)"


def issue_body(result: WatchResult) -> str:
    lines = [
        f"The finals watch (scripts/check_finals.py) found {len(result.posted)} TY{result.year} final revision(s) "
        f"on irs.gov/pub/irs-prior/:",
        "",
    ]
    lines += [f"- [ ] `{w.stem}` — {w.final_url(result.year)} ({w.why})" for w in result.posted]
    lines += [
        "",
        f"Still 404 ({len(result.missing)}): " + (", ".join(f"`{w.stem}`" for w in result.missing) or "none"),
        "",
        "Re-pin per docs/ROADMAP.md JT6: re-audit each pack against the FINAL face, set source_status: final, "
        "record the final's pdf_sha256, and re-read every form_line off the final.",
    ]
    return "\n".join(lines)


def _gh(args: list[str], dry_run: bool, runner=subprocess.run) -> str:
    shown = ("<the issue body below>" if "\n" in a else json.dumps(a) if " " in a else a for a in args)
    print("  $ gh " + " ".join(shown))
    if dry_run:
        return ""
    out = runner(["gh", *args], check=True, capture_output=True, text=True)
    return out.stdout.strip()


def file_issue(result: WatchResult, dry_run: bool, runner=subprocess.run) -> None:
    """Open the re-pin issue, or update the open one's body and comment on it."""
    label, body = issue_label(result.year), issue_body(result)
    print(f"\n=== {'DRY RUN: would file' if dry_run else 'Filing'} the '{label}' issue ===")
    _gh(["label", "create", label, "--color", "D93F0B", "--force",
         "--description", f"TY{result.year} IRS finals posted; JT6 re-pins the draft packs"], dry_run, runner)
    found = _gh(["issue", "list", "--label", label, "--state", "open", "--json", "number", "--jq", ".[0].number"],
                dry_run, runner)
    if found:
        # The daily run comments only when the posted set changed, so the issue is not a daily echo.
        if _gh(["issue", "view", found, "--json", "body", "--jq", ".body"], dry_run, runner) == body:
            print(f"  issue #{found} already lists these finals; unchanged")
            return
        _gh(["issue", "edit", found, "--body", body], dry_run, runner)
        _gh(["issue", "comment", found, "--body", f"Finals watch: now {len(result.posted)} posted."], dry_run, runner)
    else:
        _gh(["issue", "create", "--title", issue_title(result.year), "--label", label, "--body", body],
            dry_run, runner)
    if dry_run:
        print("\n--- issue body ---\n" + body)


def main(argv: list[str] | None = None, head: Callable[[str], int] = head_status, runner=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="print the re-pin list and the issue; file nothing")
    parser.add_argument("--year", type=int, help="the watched tax year (default: the newest provisional year)")
    parser.add_argument("--assume-posted", default="", help="dry run only: comma-separated stems to treat as posted")
    args = parser.parse_args(argv)
    assume = frozenset(s.strip() for s in args.assume_posted.split(",") if s.strip())
    if assume and not args.dry_run:
        parser.error("--assume-posted is for --dry-run only")
    year = args.year or provisional_year()
    if year is None:
        print("No provisional federal knowledge pack ships: every year is filing-grade, nothing to watch.")
        return 0
    watched = watch_list(year)
    print(f"=== TY{year} finals watch ({len(watched)} watched) ===")
    result = run_watch(year, watched, head=head, assume_posted=assume)
    print(f"\nRe-pin list ({len(result.posted)}): " + (", ".join(w.stem for w in result.posted) or "none yet"))
    if result.posted:
        file_issue(result, args.dry_run, runner)
    if result.errors:
        print(f"\nWATCH BLIND for {len(result.errors)} URL(s):")
        for e in result.errors:
            print(f"  • {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
