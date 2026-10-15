"""Guard (Phase J JA1): the surfaces PyPI freezes at upload say nothing a later commit cannot correct.

Once a version is on PyPI its metadata and its wheel can never change: the ``description`` field (the PyPI summary
line), the long description (``packages/mcp-server/README.md`` and ``packages/core/README.md``, via each
``pyproject.toml``'s ``readme``) and every module docstring inside the wheel. Before JA1 the descriptions carried
counts that had already drifted twice ("21 calculation ops" at 40, "22 tools" at 23), and the READMEs and both
package docstrings said "IN DEVELOPMENT / not yet published", which would have shipped to PyPI verbatim. So:

(a) no frozen surface (the two ``description`` fields, both long descriptions, both package docstrings) carries a
    count of tools, ops, packs or forms (a count belongs in a doc a later commit can fix, kept current by
    scripts/sync_doc_counts.py);
(b) no frozen surface carries pre-release wording; the four long ones state the release status and the same
    outbound-traffic sentence (an installed copy talks to the tax agencies' own sites or an exact Internet Archive
    copy of a blank, not only to ``.gov`` hosts: the MN packs live on revenue.state.mn.us);
(c) the four version sites, the core pin in the server's dependencies and the .mcpb manifest agree, so a release
    commit that bumps one and forgets another fails here, not on PyPI.

The repo-only surfaces (docs/dev/PUBLISHING.md's list: the root README, docs/USER_GUIDE.md, docs/TOOLS.md,
.github/CONTRIBUTING.md, the bundle recipe and the root pyproject.toml) flip after the upload, in the follow-up
commit. (d) holds them as a strict xfail until then, so the flip commit must drop the marker, and holds
PUBLISHING.md's post-release grep to the same pattern and file list.
"""
from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CORE_PYPROJECT = REPO / "packages" / "core" / "pyproject.toml"
MCP_PYPROJECT = REPO / "packages" / "mcp-server" / "pyproject.toml"
CORE_INIT = REPO / "packages" / "core" / "src" / "taxfill_core" / "__init__.py"
MCP_INIT = REPO / "packages" / "mcp-server" / "src" / "taxfill_mcp" / "__init__.py"
MANIFEST = REPO / "packages" / "mcp-server" / "bundle" / "manifest.json"

# A number followed by a countable noun: "23 tools", "40 calculation ops", "212 packs", "37 forms", "8 document kinds".
# Years ("2019-2026", "the 2026 packs", "the 2026 Form 1040-ES") and "50 states + DC" are facts of scope, not counts
# that move with every commit.
COUNT_CLAIM = re.compile(
    r"\b(?!(?:19|20)\d\d\b)\d+\s+(?:[a-z-]+\s+){0,2}?"
    r"(?:tools?|ops|operations|packs?|forms?|kinds|schedules|worksheets|tests)\b",
    re.IGNORECASE,
)
# One pattern for the frozen surfaces and the repo-only ones; it is written grep -E compatible because
# docs/dev/PUBLISHING.md's post-release checklist greps the repo-only surfaces with exactly this string (test below).
PRE_RELEASE_PATTERN = (
    r"pre-release|pre--release|not on pypi yet|not yet (published|on pypi|available on pypi)|nothing is published|"
    r"coming with v0\.1|once published|once (taxfill is )?installed from pypi|in development|until then"
)
PRE_RELEASE = re.compile(PRE_RELEASE_PATTERN, re.IGNORECASE)
# The outbound-traffic sentence every long surface carries (whitespace-normalized), and the old ".gov only" claim.
OUTBOUND = ("the tax agencies' own sites (or an exact, digest-checked Internet Archive copy when a state site "
            "blocks scripts)")
GOV_ONLY = re.compile(r"\.gov`?\s+(?:urls?|sites?|hosts?)|official\s+\.gov", re.IGNORECASE)
# docs/dev/PUBLISHING.md "The repo-only surfaces flip after the upload": what the post-release grep reads.
REPO_ONLY_SURFACES = ("README.md", "docs/USER_GUIDE.md", "docs/TOOLS.md", ".github/CONTRIBUTING.md",
                      "packages/mcp-server/bundle/README.md", "pyproject.toml")
PUBLISHING = REPO / "docs" / "dev" / "PUBLISHING.md"


def _project(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]


def _readme(pyproject: Path) -> Path:
    return pyproject.parent / _project(pyproject)["readme"]


def _docstring(path: Path) -> str:
    return ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""


def _version_attr(path: Path) -> str:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "__version__" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.relative_to(REPO)} defines no __version__")


def _wheel_surfaces() -> dict[str, str]:
    """Every PyPI-frozen text surface this test reads, by a readable label."""
    return {
        "taxfill-core description": _project(CORE_PYPROJECT)["description"],
        "taxfill-mcp description": _project(MCP_PYPROJECT)["description"],
        "taxfill-core long description (packages/core/README.md)": _readme(CORE_PYPROJECT).read_text(encoding="utf-8"),
        "taxfill-mcp long description (packages/mcp-server/README.md)": _readme(MCP_PYPROJECT).read_text(encoding="utf-8"),
        "taxfill_core.__doc__": _docstring(CORE_INIT),
        "taxfill_mcp.__doc__": _docstring(MCP_INIT),
    }


# ── (a) count-free frozen surfaces ───────────────────────────────────────────


@pytest.mark.parametrize("label", list(_wheel_surfaces()))
def test_no_frozen_surface_carries_a_count(label):
    text = " ".join(_wheel_surfaces()[label].split())
    hits = [m.group(0) for m in COUNT_CLAIM.finditer(text)]
    assert not hits, (
        f"{label} quotes a count ({hits}) — PyPI freezes it at upload; say it without the number (the counts live "
        f"in docs kept current by scripts/sync_doc_counts.py)")


def test_the_count_pattern_catches_the_wordings_that_shipped_before():
    for stale in ("cited tax math (23 tools)", "and 40 calculation ops", "21 deterministic ops", "212 form packs",
                  "8 document kinds", "`calc` (40 deterministic ops over cited per-year data)"):
        assert COUNT_CLAIM.search(stale), stale
    for fine in ("federal 2019-2026, all 50 states + DC", "Form 1040-ES", "TY2025 is the newest filing-grade year",
                 "The 2026 packs are provisional", "the 2026 Form 1040-ES, paid during 2026, fills normally"):
        assert not COUNT_CLAIM.search(fine), fine


# ── (b) no pre-release wording on a frozen surface ───────────────────────────


@pytest.mark.parametrize("label", list(_wheel_surfaces()))
def test_no_pre_release_wording_on_a_frozen_surface(label):
    text = _wheel_surfaces()[label]
    hits = sorted({m.group(0) for m in PRE_RELEASE.finditer(text)})
    assert not hits, f"{label} still says {hits} — PyPI would freeze it; use the release-status wording"


def test_the_pre_release_pattern_catches_the_wordings_that_shipped_before():
    for stale in ("Status: v0.1 IN DEVELOPMENT — not yet published to PyPI.", "Status: v0.1 is IN DEVELOPMENT.",
                  "v0.1 is in development and not yet published to PyPI", "It is **not on PyPI yet**",
                  "**Coming with v0.1 (once published to PyPI):**", "Once published, the one-liner becomes",
                  # the repo-only wordings the post-release grep must find (2026-10-15)
                  "![Status: pre-release](https://img.shields.io/badge/status-pre--release-orange)",
                  "**Project status:** pre-release.", "nothing is published to PyPI yet", "## Until then",
                  "Once taxfill is installed from PyPI, `taxfill` is on", "(once installed from PyPI, just"):
        assert PRE_RELEASE.search(stale), stale


@pytest.mark.parametrize("label", ["taxfill-core long description (packages/core/README.md)",
                                   "taxfill-mcp long description (packages/mcp-server/README.md)",
                                   "taxfill_core.__doc__", "taxfill_mcp.__doc__"])
def test_each_long_surface_states_the_same_outbound_traffic(label):
    text = " ".join(_wheel_surfaces()[label].replace(">", " ").split())
    assert OUTBOUND in text, f"{label} must say the outbound traffic exactly as the other long surfaces do"


@pytest.mark.parametrize("label", list(_wheel_surfaces()))
def test_no_frozen_surface_claims_gov_only_traffic(label):
    text = " ".join(_wheel_surfaces()[label].split())
    hits = [m.group(0) for m in GOV_ONLY.finditer(text)]
    assert not hits, (f"{label} says {hits}: blank forms also come from non-.gov agency hosts "
                      f"(revenue.state.mn.us) and Internet Archive mirrors — use the outbound-traffic sentence")


def test_the_gov_only_pattern_catches_the_wordings_that_shipped_before():
    for stale in ("download **blank** official forms from `.gov` URLs on demand",
                  "downloading blank forms from official .gov URLs (``fetch_blank``)"):
        assert GOV_ONLY.search(" ".join(stale.split())), stale
    assert not GOV_ONLY.search(OUTBOUND)


@pytest.mark.parametrize("label", ["taxfill-core long description (packages/core/README.md)",
                                   "taxfill-mcp long description (packages/mcp-server/README.md)",
                                   "taxfill_core.__doc__", "taxfill_mcp.__doc__"])
def test_each_long_surface_states_the_release_status(label):
    """The three release facts: the filing-grade year, the provisional 2026 packs, and the refusal of a form with
    no pack (a later release adds an unmapped draft that is never filing-grade)."""
    text = " ".join(_wheel_surfaces()[label].replace(">", " ").split())
    assert "TY2025 is the newest filing-grade tax year" in text, label
    assert "The 2026 packs are provisional" in text, label
    assert "A form with no pack is refused today" in text and "never filing-grade" in text, label


@pytest.mark.parametrize("label", ["taxfill-mcp long description (packages/mcp-server/README.md)", "taxfill_mcp.__doc__"])
def test_the_server_surfaces_do_not_promise_a_rehearsal_fill(label):
    """Through the MCP server a 2026 draft is refused: ``rehearsal`` is a core-only fill_form argument that no tool passes
    (filler.fill_form's docstring). The core surfaces may describe the rehearsal API; the server's must not promise it."""
    text = " ".join(_wheel_surfaces()[label].replace(">", " ").split())
    assert "rehearsal mode" not in text, label
    assert "refuses them" in text and "1040-ES" in text, label


# ── (c) one version everywhere ───────────────────────────────────────────────


def test_every_version_site_agrees():
    core = _project(CORE_PYPROJECT)["version"]
    sites = {
        "packages/core/pyproject.toml version": core,
        "packages/mcp-server/pyproject.toml version": _project(MCP_PYPROJECT)["version"],
        "taxfill_core.__version__": _version_attr(CORE_INIT),
        "taxfill_mcp.__version__": _version_attr(MCP_INIT),
        "packages/mcp-server/bundle/manifest.json version": json.loads(MANIFEST.read_text(encoding="utf-8"))["version"],
    }
    pins = [d for d in _project(MCP_PYPROJECT)["dependencies"] if re.match(r"taxfill-core\b", d)]
    assert len(pins) == 1, f"taxfill-mcp must depend on taxfill-core exactly once, found {pins}"
    sites["packages/mcp-server/pyproject.toml taxfill-core pin"] = pins[0].split("==", 1)[1] if "==" in pins[0] else pins[0]
    assert set(sites.values()) == {core}, "version sites disagree (bump them together — docs/dev/PUBLISHING.md):\n" + \
        "\n".join(f"  {k}: {v}" for k, v in sites.items())


# ── (d) the repo-only surfaces, flipped after the upload ─────────────────────


@pytest.mark.xfail(strict=True, reason="the repo-only surfaces flip after the PyPI upload (ROADMAP A6, after JA2); "
                                       "the flip commit removes this marker")
def test_no_repo_only_surface_still_reads_pre_release():
    hits = [f"{rel}:{n}: {line.strip()}" for rel in REPO_ONLY_SURFACES
            for n, line in enumerate((REPO / rel).read_text(encoding="utf-8").splitlines(), 1)
            if PRE_RELEASE.search(line)]
    assert not hits, "pre-release wording left on a repo-only surface:\n" + "\n".join(hits)


def test_the_post_release_grep_reads_the_same_pattern_and_files():
    """PUBLISHING.md's checklist grep is the manual twin of the test above: same pattern, same files."""
    lines = [line for line in PUBLISHING.read_text(encoding="utf-8").splitlines() if "grep -n -i -E" in line]
    assert len(lines) == 1, f"docs/dev/PUBLISHING.md must carry exactly one post-release grep, found {len(lines)}"
    m = re.search(r'grep -n -i -E "([^"]+)" ([^`]+)`', lines[0])
    assert m, lines[0]
    assert m.group(1) == PRE_RELEASE_PATTERN, "PUBLISHING.md's grep pattern drifted from PRE_RELEASE_PATTERN"
    assert tuple(m.group(2).split()) == REPO_ONLY_SURFACES, "PUBLISHING.md's grep file list drifted"
    for rel in REPO_ONLY_SURFACES:
        assert (REPO / rel).is_file(), rel
