"""Guard: every relative link in the repo's Markdown resolves.

The 2026-10 layout cleanup moved a dozen docs (CONTRIBUTING/SECURITY into .github/, the maintainer docs into
docs/dev/, evals and the bundle under packages/). A moved file silently breaks every link that pointed at it, and
GitHub renders a dead link without complaint — so this test resolves each one: the target file or directory must
exist, and a ``#fragment`` into a Markdown file must name one of its headings (GitHub's slug rules).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[3]
SKIP_DIRS = {".git", ".venv", ".cache", ".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__", "_data",
             "dist", "build", "node_modules", "taxfill-workspace"}
# every "](target)" — inline links, images, a badge's link target — with an optional "title"; plus reference
# definitions ("[id]: target")
LINK = re.compile(r'\]\((<[^>]+>|[^)\s]+)(?:\s+"[^"]*")?\)')
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.M)
FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
CODE_SPAN = re.compile(r"`[^`\n]+`")


def _markdown_files() -> list[Path]:
    out = []
    for path in REPO.rglob("*.md"):
        rel = path.relative_to(REPO).parts
        if any(part in SKIP_DIRS or (part.startswith(".") and part != ".github") for part in rel[:-1]):
            continue
        out.append(path)
    return sorted(out)


def _slug(heading: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for line in FENCE.sub("", path.read_text(encoding="utf-8")).splitlines():
        m = re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not m:
            continue
        slug = _slug(m.group(1))
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        out.add(slug if n == 0 else f"{slug}-{n}")
    return out


def test_the_scan_sees_the_docs():
    names = {p.relative_to(REPO).as_posix() for p in _markdown_files()}
    assert {"README.md", "docs/README.md", ".github/CONTRIBUTING.md", "docs/dev/ROADMAP.md"} <= names


def test_every_relative_markdown_link_resolves():
    broken = []
    for path in _markdown_files():
        text = CODE_SPAN.sub("", FENCE.sub("", path.read_text(encoding="utf-8")))
        for target in LINK.findall(text) + REF_DEF.findall(text):
            target = target.strip("<>")
            if re.match(r"[a-z][a-z0-9+.-]*:", target):  # http:, https:, mailto: ...
                continue
            file_part, _, fragment = target.partition("#")
            file_part, fragment = unquote(file_part), unquote(fragment)
            base = REPO if file_part.startswith("/") else path.parent  # GitHub resolves "/x" from the repo root
            dest = (base / file_part.lstrip("/")).resolve() if file_part else path
            where = f"{path.relative_to(REPO)} -> {target}"
            if not dest.exists():
                broken.append(f"{where} (no such file)")
            elif fragment and dest.suffix == ".md" and fragment.lower() not in _anchors(dest):
                broken.append(f"{where} (no heading #{fragment})")
    assert not broken, "broken Markdown link(s):\n" + "\n".join(broken)
