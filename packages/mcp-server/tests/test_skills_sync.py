"""Guard: the agent-facing surfaces must not drift from the runtime surface.

The 22-tool count is gated in four places (server, EXPECTED_TOOLS, bundle manifest,
CI) — but until 2026-08-07 NOTHING guarded `skills/`, which is the text the model
actually reads before it decides which tool to call. The result was a silent,
45-commit regression: `calc(state_tax)` grew from 8 flat-rate states to all 42
income-tax jurisdictions with graduated brackets across three tax years, while
SKILL.md (and the tool's own MCP docstring) kept advertising

    "the flat-rate STATE income-tax line for the 2023 flat-rate states
     IL/PA/IN/MI/NC/CO/KY/AZ"

so an agent preparing a California or New York return would never call the op that
existed for it, and would fall back to its own arithmetic — violating hard rule #1
("every number on a return comes from a taxfill tool"). Engine coverage was fine;
*reachability* was broken.

These tests make the skill files fail loudly on that class of drift. They assert
structure and reachability, NOT prose: a doc may say more than the runtime, never
less, and no doc may name a per-year roster that the packs are free to change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SKILLS = REPO / "skills"
SKILL_FILES = {
    "claude": SKILLS / "claude" / "SKILL.md",
    "codex": SKILLS / "codex" / "AGENTS.md",
    "copilot": SKILLS / "copilot" / "instructions.md",
}

# The one skill that carries the full cookbook; the other two are deliberately terse
# summaries that point at it, so only this one must enumerate every calc op.
FULL_SKILL = SKILL_FILES["claude"]


def _runtime_tool_names() -> set[str]:
    from taxfill_mcp.server import mcp

    import anyio

    return {t.name for t in anyio.run(mcp.list_tools)}


def _runtime_calc_ops() -> set[str]:
    """The ops `calc` actually dispatches, read from the dispatch chain itself."""
    src = (REPO / "packages" / "mcp-server" / "src" / "taxfill_mcp" / "server.py").read_text()
    ops = set(re.findall(r'if op == "([a-z0-9_]+)"', src))
    assert len(ops) == 32, f"calc op count changed ({len(ops)}) — update the skills, then this number"
    return ops


def _jurisdictions_with_tax_block(year: int) -> set[str]:
    from taxfill_core.knowledge import load_state_knowledge

    out = set()
    for d in sorted((REPO / "knowledge" / "states").iterdir()):
        if not d.is_dir():
            continue
        try:
            sk = load_state_knowledge(d.name, year, base_dir=REPO / "knowledge")
        except Exception:
            continue
        if getattr(sk, "tax", None) is not None:
            out.add(d.name)
    return out


@pytest.mark.parametrize("name", sorted(SKILL_FILES))
def test_every_mcp_tool_is_named_in_every_skill_file(name: str) -> None:
    """A tool the model cannot read about is a tool the model will not call."""
    text = SKILL_FILES[name].read_text()
    missing = sorted(t for t in _runtime_tool_names() if t not in text)
    assert not missing, f"skills/{name} never mentions these live tools: {missing}"


@pytest.mark.parametrize("name", sorted(SKILL_FILES))
def test_no_skill_file_invents_a_tool(name: str) -> None:
    """The reverse drift: a doc promising a tool that was renamed or removed."""
    text = SKILL_FILES[name].read_text()
    live = _runtime_tool_names()
    # Only check backticked identifiers that look like our tool names, to avoid
    # flagging ordinary prose.
    claimed = {m for m in re.findall(r"`([a-z][a-z0-9_]{4,})\(", text)}
    known_non_tools = {"calc", "load_state_knowledge", "state_tax"}
    bogus = sorted(c for c in claimed - live - known_non_tools if "_" in c)
    assert not bogus, f"skills/{name} documents tools that do not exist: {bogus}"


def test_every_calc_op_is_named_in_the_full_skill() -> None:
    """`calc` is one MCP tool wrapping 30 ops — the ops are only discoverable in prose."""
    text = FULL_SKILL.read_text()
    missing = sorted(op for op in _runtime_calc_ops() if op not in text)
    assert not missing, f"skills/claude/SKILL.md never mentions these calc ops: {missing}"


@pytest.mark.parametrize("name", sorted(SKILL_FILES))
def test_no_skill_understates_state_tax_coverage(name: str) -> None:
    """The exact regression this module exists for.

    `state_tax` covers every jurisdiction that ships a `tax` block. Any doc that
    still describes it as flat-rate-only, or pins it to the original eight states,
    tells the agent to do the arithmetic itself for the other 34.
    """
    text = SKILL_FILES[name].read_text()
    stale = [
        "flat-rate STATE income-tax line",
        "the 2023 flat-rate states",
        "IL/PA/IN/MI/NC/CO/KY/AZ",
        "34 states + DC",
        "35 adopted",
    ]
    hits = [s for s in stale if s in text]
    assert not hits, (
        f"skills/{name} still carries a superseded state_tax description: {hits}. "
        f"state_tax now covers {len(_jurisdictions_with_tax_block(2023))} jurisdictions for 2023."
    )


@pytest.mark.parametrize("name", sorted(SKILL_FILES))
def test_skills_quote_the_real_jurisdiction_count(name: str) -> None:
    n = len(_jurisdictions_with_tax_block(2023))
    text = SKILL_FILES[name].read_text()
    assert str(n) in text, (
        f"skills/{name} does not quote the real jurisdiction count ({n}); "
        "a stale count is how the last drift went unnoticed for 45 commits"
    )


@pytest.mark.parametrize("name", sorted(SKILL_FILES))
def test_skills_name_every_hand_fill_state(name: str) -> None:
    """Hand-fill states are invisible to list_forms — an agent that does not know
    they exist reads the empty list as a missing pack and gives up."""
    codes = sorted(p.parent.parent.name for p in (REPO / "formpacks" / "states").rglob("handfill.yaml"))
    text = SKILL_FILES[name].read_text().upper()
    missing = [c for c in codes if c.upper() not in text]
    assert not missing, f"skills/{name} never names these print-only states: {missing}"


def test_state_tax_shape_is_data_not_a_hardcoded_roster() -> None:
    """Whether a state is flat or graduated moves BY YEAR, so no roster survives.

    GA converted to a flat rate for 2024; IA and LA for 2025. This test pins the
    fact that the split is year-dependent, so anyone tempted to re-introduce a
    hardcoded list into a docstring sees it fail.
    """
    from taxfill_core.knowledge import load_state_knowledge

    def flat_set(year: int) -> set[str]:
        out = set()
        for code in _jurisdictions_with_tax_block(year):
            sk = load_state_knowledge(code, year, base_dir=REPO / "knowledge")
            if getattr(sk.tax, "flat_rate", None) is not None:
                out.add(code)
        return out

    f23, f24, f25 = flat_set(2023), flat_set(2024), flat_set(2025)
    assert f23 != f24 or f24 != f25, "the flat/graduated split is expected to vary by year"
    assert "ga" in f24 - f23, "GA's 2024 flat conversion is the canonical example"
    assert {"ia", "la"} <= f25 - f24, "IA and LA converted to flat rates for 2025"
