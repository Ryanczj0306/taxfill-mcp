#!/usr/bin/env python
"""Check a release tag against the repo and print its notes from docs/CHANGELOG.md (Phase J JA1).

.github/workflows/release.yml runs this as its FIRST step, before anything is built or uploaded, so a tag that
cannot be released stops the workflow while nothing irreversible has happened:

- the tag must be ``v<version>`` for the one version every site carries (both pyprojects, the core pin, the bundle
  manifest and the bundle pyproject's taxfill-mcp pin; test_release_surfaces.py holds the same agreement in CI);
- the version must be a public release: a ``.dev`` build or a local ``+label`` version is never uploaded;
- docs/CHANGELOG.md must hold a non-empty section ``## [<version>] - <YYYY-MM-DD>`` with a real date: the release
  commit dates the section (docs/dev/PUBLISHING.md step 1), which also freezes its generated coverage lines.

The section's body, without the GENERATED marker comments and with the file's hard-wrapped lines joined (a GitHub
release body renders every newline as a line break), becomes the GitHub release notes.

    python scripts/release_notes.py --tag v0.1.0 --out release-notes.md
    python scripts/release_notes.py --tag v0.1.0             # print the notes

Stdlib only (Python 3.11+), so the workflow can run it before ``uv sync``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHANGELOG = REPO / "docs" / "CHANGELOG.md"
HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?P<rest>.*)$", re.M)
DATED = re.compile(r"^ - (?P<date>\d{4}-\d{2}-\d{2})\s*$")
LINK_REFS = re.compile(r"^\[[^\]]+\]:\s*\S+", re.M)
COMMENT_LINE = re.compile(r"^<!--.*-->\s*$")
# PEP 440 public release: N.N.N, optionally a/b/rc N or .postN. No .devN, no +local.
PUBLIC_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?$")


class ReleaseError(Exception):
    """The tag cannot be released as the repo stands."""


def version_sites(repo: Path = REPO) -> dict[str, str]:
    """Every place the release version is written, as {label: version}."""
    def project(rel: str) -> dict:
        return tomllib.loads((repo / rel).read_text(encoding="utf-8"))["project"]

    def pin(deps: list[str], name: str, where: str) -> str:
        hits = [d for d in deps if re.match(rf"{re.escape(name)}\s*==", d)]
        if len(hits) != 1:
            raise ReleaseError(f"{where} must pin {name}== exactly once, found {hits or 'none'}")
        return hits[0].split("==", 1)[1].strip()

    core, mcp = project("packages/core/pyproject.toml"), project("packages/mcp-server/pyproject.toml")
    bundle = project("packages/mcp-server/bundle/pyproject.toml")
    manifest = json.loads((repo / "packages/mcp-server/bundle/manifest.json").read_text(encoding="utf-8"))
    return {
        "packages/core/pyproject.toml version": core["version"],
        "packages/mcp-server/pyproject.toml version": mcp["version"],
        "packages/mcp-server/pyproject.toml taxfill-core pin": pin(mcp["dependencies"], "taxfill-core",
                                                                   "packages/mcp-server/pyproject.toml"),
        "packages/mcp-server/bundle/manifest.json version": manifest["version"],
        "packages/mcp-server/bundle/pyproject.toml version": bundle["version"],
        "packages/mcp-server/bundle/pyproject.toml taxfill-mcp pin": pin(bundle["dependencies"], "taxfill-mcp",
                                                                         "packages/mcp-server/bundle/pyproject.toml"),
    }


def release_version(tag: str, sites: dict[str, str]) -> str:
    """The version the tag releases; raises unless every site agrees with the tag and it is a public release."""
    versions = set(sites.values())
    if len(versions) != 1:
        raise ReleaseError("the version sites disagree (docs/dev/PUBLISHING.md step 1):\n"
                           + "\n".join(f"  {k}: {v}" for k, v in sites.items()))
    version = versions.pop()
    if tag != f"v{version}":
        raise ReleaseError(f"tag {tag!r} does not match the repo's version {version!r} (expected 'v{version}')")
    if not PUBLIC_VERSION.match(version):
        raise ReleaseError(f"{version!r} is not a public release version (a .dev or +local build is never uploaded)")
    return version


def section_notes(text: str, version: str) -> tuple[str, str]:
    """(date, notes) of the CHANGELOG section for ``version``; raises if it is missing, undated or empty."""
    headings = list(HEADING.finditer(text))
    found = [m for m in headings if m.group("version") == version]
    if len(found) != 1:
        raise ReleaseError(f"docs/CHANGELOG.md needs exactly one '## [{version}] - YYYY-MM-DD' section, "
                           f"found {len(found)}")
    m = found[0]
    dated = DATED.match(m.group("rest"))
    if not dated:
        raise ReleaseError(f"the CHANGELOG section '{m.group(0).strip()}' has no date: the release commit sets "
                           f"'## [{version}] - YYYY-MM-DD' (docs/dev/PUBLISHING.md step 1)")
    try:
        dt.date.fromisoformat(dated.group("date"))
    except ValueError as exc:
        raise ReleaseError(f"the CHANGELOG section date {dated.group('date')!r} is not a date: {exc}") from None
    later = [h.start() for h in headings if h.start() > m.start()]
    refs = LINK_REFS.search(text, m.end())
    end = min([*later, refs.start() if refs else len(text)])
    lines = [ln for ln in text[m.end():end].splitlines() if not COMMENT_LINE.match(ln.strip())]
    notes = unwrap("\n".join(lines)).strip()
    if not notes:
        raise ReleaseError(f"the CHANGELOG section for {version} is empty")
    return dated.group("date"), notes + "\n"


BLOCK_START = re.compile(r"^(?:#{1,6} |[-*+] |\d+[.)] |>|\||```|<!--)")


def unwrap(markdown: str) -> str:
    """Join hard-wrapped continuation lines onto their paragraph or list item; leave fenced code alone."""
    out: list[str] = []
    fenced = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        joinable = (not fenced and out and out[-1].strip() and stripped and not BLOCK_START.match(stripped)
                    and not out[-1].lstrip().startswith(("#", "```", "|")))
        if joinable:
            out[-1] = f"{out[-1].rstrip()} {stripped}"
        else:
            out.append(line)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME"),
                        help="the pushed tag, e.g. v0.1.0 (default: $GITHUB_REF_NAME)")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG)
    parser.add_argument("--out", type=Path, help="write the notes here instead of stdout")
    args = parser.parse_args(argv)
    if not args.tag:
        parser.error("--tag is required outside GitHub Actions")
    try:
        version = release_version(args.tag, version_sites())
        date, notes = section_notes(args.changelog.read_text(encoding="utf-8"), version)
    except ReleaseError as exc:
        print(f"release_notes: {exc}", file=sys.stderr)
        return 1
    if args.out:
        args.out.write_text(notes, encoding="utf-8")
        print(f"release {version} ({date}): {len(notes.splitlines())} lines of notes -> {args.out}")
    else:
        sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
