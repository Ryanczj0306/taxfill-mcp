#!/usr/bin/env python
"""Single source of truth for the headline test count — README badge + ROADMAP line.

The count is quoted in three places (README's badge alt text, the badge's own
shields.io URL, README's status paragraph, and the ROADMAP "Where we are" line),
and every one of them was maintained by hand. It went stale four separate times:
the ROADMAP records truth-ups from ~903 -> ~1076 -> 1222 -> 1,401 -> 2,297, and by
2026-08-07 the README badge had drifted so far that its ALT TEXT (2,178) disagreed
with its own URL (2,297) while the real number was 2,824. ROADMAP:343 claimed
"wire the true test count into a CI badge / README line — DONE"; it was not, and
the drift is structural: the state-knowledge and form-pack suites are
glob-parametrized, so the number moves every time a YAML pack lands.

So: derive it, never type it.

    python scripts/sync_test_count.py            # report the counts
    python scripts/sync_test_count.py --write    # rewrite README + ROADMAP
    python scripts/sync_test_count.py --check    # nonzero exit if they disagree (CI)

`--check` runs in CI, so a pack that changes the count fails the build with an
exact instruction rather than rotting silently.

Counting uses `pytest --collect-only`, which imports test modules but executes no
tests, so `--check` costs seconds, not a full suite run.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Files that quote the count, and the patterns that carry it. Each entry is
# (path, regex with a single {n} placeholder group, how to render the number).
README = REPO / "README.md"
ROADMAP = REPO / "docs" / "ROADMAP.md"


def _collect(marker: str | None) -> int:
    """Total tests pytest would run, via --collect-only (no test executes)."""
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    if marker:
        cmd += ["-m", marker]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0 and "error" in proc.stdout.lower():
        raise SystemExit(f"pytest collection failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-2000:]}")
    # `-q --collect-only` prints one "path/to/test_file.py: N" line per module,
    # then a summary. Sum the per-module counts; the summary line has no colon-N shape.
    total = 0
    for line in proc.stdout.splitlines():
        m = re.match(r"^\S+\.py: (\d+)$", line.strip())
        if m:
            total += int(m.group(1))
    if total == 0:
        raise SystemExit(f"collected 0 tests — is pytest configured?\n{proc.stdout[-2000:]}")
    return total


def counts() -> tuple[int, int, int]:
    """(total, offline, network). Network = the live-.gov round-trips."""
    total = _collect(None)
    offline = _collect("not network")
    return total, offline, total - offline


def _edits(total: int, offline: int, network: int) -> list[tuple[Path, str, str]]:
    """(path, regex, replacement) for every place the count is quoted."""
    t, o = f"{total:,}", f"{offline:,}"
    t_url = t.replace(",", "%2C")
    return [
        # README badge — BOTH the alt text and the shields.io URL. These drifted
        # apart from each other once; keeping them in one rule makes that impossible.
        (README, r"!\[Tests: [\d,]+ passing\]\(https://img\.shields\.io/badge/tests-[\d%C,A-Za-z]+?-brightgreen\)",
         f"![Tests: {t} passing](https://img.shields.io/badge/tests-{t_url}%20passing-brightgreen)"),
        # README status paragraph
        (README, r"covered by [\d,]+ tests", f"covered by {t} tests"),
        # ROADMAP "Where we are"
        (ROADMAP, r"\*\*[\d,]+ tests, all green\*\* — offline [\d,]+ \+ live-\.gov \d+",
         f"**{t} tests, all green** — offline {o} + live-.gov {network}"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="rewrite README + ROADMAP with the real counts")
    g.add_argument("--check", action="store_true", help="exit nonzero if any quoted count is stale (CI)")
    args = ap.parse_args()

    total, offline, network = counts()
    print(f"collected: total={total:,}  offline={offline:,}  network={network}")

    stale: list[str] = []
    for path, pattern, replacement in _edits(total, offline, network):
        text = path.read_text(encoding="utf-8")
        found = re.search(pattern, text)
        rel = path.relative_to(REPO)
        if not found:
            stale.append(f"{rel}: no text matching /{pattern}/ — the doc changed shape; update this script")
            continue
        if found.group(0) == replacement:
            continue
        stale.append(f"{rel}: quotes {found.group(0)!r}\n      should be {replacement!r}")
        if args.write:
            path.write_text(text.replace(found.group(0), replacement), encoding="utf-8")

    if not stale:
        print("every quoted test count is current.")
        return 0
    if args.write:
        print(f"updated {len(stale)} stale reference(s).")
        return 0
    for s in stale:
        print(f"  STALE  {s}")
    if args.check:
        print("\nRun `python scripts/sync_test_count.py --write` and commit the result.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
