"""Eval (v): "is this ready to file?" on a form with no pack (Phase K JK18, 2026-10-25; ADR-0002 KG5, KG7, KG11).

The no-pack fallback (``form="unmapped"`` on fetch_blank, get_form_map, fill_form and verify_form) writes an
UNMAPPED DRAFT that is never filing-grade. Two halves hold the agent to that:

- THE SKILL TEXT. Each of the three synced skill files (skills/claude/SKILL.md, skills/codex/AGENTS.md,
  skills/copilot/instructions.md) tells the agent to say up front that no pack exists, to show the sweep page before
  the user confirms a box, never to fill what comes back in ``hand_write`` and to relay every get_form_map
  ``hand_write`` box the form fills itself, by line or else label (whatever they print is the blank's default), to keep the "agent-computed, unverified"
  label and mark its own lines, to run verify_form and then render_form on every page, never to say "done",
  "complete", "ready", "finished", "final" or "all set" before verify_form returned ok for that output's sha256,
  and, asked "is this ready to file?", to say no because the draft is never filing-grade. The old pointer-only guidance is gone, and the skills' one
  "checksum-verified" promise is qualified for a pack.
- THE TOOL RESPONSES. Over the real MCP protocol path, on a synthetic demo form served by a monkeypatched official
  host (no network, demo values only, KG10): nothing the agent reads for an unmapped draft — fetch, map, fill, a
  passing verify, the pack path's verify_form and verify_filing refusals, filing_summary and file_and_pay — claims
  filing-grade under the journey guard's ``_filing_grade_claims`` (packages/mcp-server/tests/test_journeys.py), and
  each unmapped response says the draft is never filing-grade. The journey-level done guard (no "done" step before
  verify_form ok on the same output_sha256) lives with the journeys: ``_check_done_order`` there.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
for _tests in (REPO / "packages" / "core" / "tests", REPO / "packages" / "mcp-server" / "tests"):
    if str(_tests) not in sys.path:
        sys.path.insert(0, str(_tests))

from mcp.shared.memory import create_connected_server_and_client_session as connect  # noqa: E402

import taxfill_mcp.server as server  # noqa: E402
from taxfill_core import fetch as fetch_mod  # noqa: E402
from test_journeys import _filing_grade_claims  # noqa: E402
from test_unmapped_fill import _demo1  # noqa: E402

SKILLS = {
    "claude": REPO / "skills" / "claude" / "SKILL.md",
    "codex": REPO / "skills" / "codex" / "AGENTS.md",
    "copilot": REPO / "skills" / "copilot" / "instructions.md",
}
LABEL = "UNMAPPED DRAFT — NOT FILING-GRADE"
NEVER = "never filing-grade"


def _flat(path: Path) -> str:
    """The skill text with its line breaks and markdown blockquote marks folded into single spaces."""
    return re.sub(r"\s+", " ", " ".join(re.sub(r"^>\s?", "", line) for line in path.read_text().splitlines()))


# ── the skill text ─────────────────────────────────────────────────────────────

RULES = {
    "says up front that no pack exists": r"say so up front",
    "keeps the draft label": re.escape(LABEL),
    "uses all four tools with form=unmapped": (r'fetch_blank\(form="unmapped".*get_form_map\(form="unmapped".*'
                                               r'fill_form\(form="unmapped".*verify_form\(form="unmapped"'),
    "takes the blank from the agency's own .gov site": r"\.gov",
    "shows the sweep page before any box is confirmed": r"sweep page.{0,80}render_form|render_form.{0,40}sweep",
    "has the user confirm low and med boxes": r"`low`\s*(?:or|/)\s*`med`.{0,120}confirmed_fields",
    "never fills hand_write boxes": r"never (?:try to )?fill.{0,40}`?hand_write`?",
    # Phase K JK18 review (2026-10-25): fill_form's hand_write lists only the values passed; a calculated, read-only
    # or custom-format box (Georgia 500X lines 7c, 10, 11, 13 and 16, read or not) is listed by get_form_map and may
    # print the blank's default 0, so the agent relays EVERY such box, by line or else by label, and says the figure
    # is not a computed one. The first fix relayed only boxes whose printed line was read, and missed 7c and 16.
    "relays every map hand_write box the form fills itself": (r"relay every get_form_map `hand_write` entry the "
                                                               r"form fills itself"),
    "names each by its line, else its label": r"`printed_line`.{0,30}(?:else|otherwise).{0,10}(?:by )?its `label`",
    "says a figure printed there is the blank's default": r"blank's own default, not a computed figure",
    "has the user work those lines out from the instructions": r"works? (?:each|the) line out by hand from the form's "
                                                               r"instructions",
    "passes the same source_url and blank_sha256 every step": r"same `source_url` and `blank_sha256`",
    "names the draft's pdf_path for verify": r'verify_form\(form="unmapped",.{0,80}pdf_path',
    "labels every value": r'"agent-computed, unverified"',
    "labels the lines it computed itself": r"computed yourself",
    "renders and checks every page after verify": r"verify_form\(form=\"unmapped\".{0,200}`render_form` (?:on )?every page",
    "never says done before verify ok on that sha256": (r'never say "done", "complete", "ready", "finished", "final" or '
                                                        r'"all set"(?: about the draft)? before `verify_form` '
                                                        r"(?:returned|was) `ok` for that (?:output's )?`output_sha256`"),
    'refuses "is this ready to file?"': r'asked "is this ready to file\?"[,:]? (?:say )?no\b.{0,40}never filing-grade',
    "names the way to a filing": r"a pack, or .{0,40}(?:transcribing|copying) the .{0,40}by hand onto .{0,30}official",
}


@pytest.mark.parametrize("rule", sorted(RULES))
@pytest.mark.parametrize("name", sorted(SKILLS))
def test_eval_v_every_skill_file_carries_the_no_pack_rule(name, rule):
    text = _flat(SKILLS[name])
    assert re.search(RULES[rule], text, re.IGNORECASE | re.DOTALL), f"skills/{name}: does not say it {rule}"


@pytest.mark.parametrize("tool", ["fetch_blank", "get_form_map", "fill_form", "verify_form"])
def test_eval_v_the_claude_tool_table_row_names_the_unmapped_form(tool):
    """Each of the four tools' rows in SKILL.md's tool table says it also takes form="unmapped" (Phase K JK18 review,
    2026-10-25: only the fetch_blank row did)."""
    rows = [line for line in SKILLS["claude"].read_text().splitlines() if line.startswith(f"| `{tool}(")
            or (line.startswith("| `") and f"/ `{tool}(" in line.split("|")[1])]
    assert len(rows) == 1, (tool, rows)
    assert 'form="unmapped"' in rows[0] and "Recipe U" in rows[0], rows[0][:200]


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_eval_v_the_pointer_only_guidance_is_gone(name):
    text = _flat(SKILLS[name])
    for stale in ("fall back to `get_sources` + the official blank", "fall back to `get_sources` + the state's own blank",
                  "return computes but cannot be filled.", "computes but **cannot be filled**"):
        assert stale not in text, f"skills/{name} still says {stale!r} (JK18 replaced it with the unmapped draft)"
    for m in re.finditer(r"checksum-verified", text):  # ADR-0002 Docs: the promise holds only for a pack
        assert "for a pack" in text[m.end():m.end() + 20], f"skills/{name}: {text[m.start() - 60:m.end() + 40]!r}"


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_eval_v_the_question_is_answered_no_in_the_same_breath(name):
    """The refusal is the answer to the question, not a separate rule elsewhere: the words right after the quoted
    question are "no" and why (never filing-grade), and nothing between claims otherwise."""
    text = _flat(SKILLS[name])
    m = re.search(r'"is this ready to file\?"(.{0,80})', text, re.IGNORECASE)
    assert m, f"skills/{name} never quotes the question"
    after = m.group(1)
    assert re.match(r"[,:]? (?:say )?no\b", after) and NEVER in after, (name, after)
    assert not _filing_grade_claims(after.split(NEVER)[0] + NEVER), (name, after)


# ── the tool responses ─────────────────────────────────────────────────────────

URL = "https://www.tax.example.gov/forms/2025/demo-1.pdf"
WHERE = {"form": "unmapped", "year": 2025, "jurisdiction": "states/sd", "source_url": URL}


class _Opener:
    def __init__(self, answers: dict[str, bytes]):
        self.answers = answers

    def __call__(self, request, timeout=None):
        return io.BytesIO(self.answers[request.full_url])


def _call(name: str, args: dict) -> tuple[bool, object]:
    async def go():
        async with connect(server.mcp) as client:
            return await client.call_tool(name, args)
    result = asyncio.run(go())
    if result.isError:
        return True, "\n".join(getattr(b, "text", "") for b in result.content)
    if result.structuredContent is not None:
        return False, result.structuredContent.get("result", result.structuredContent)
    return False, json.loads(result.content[0].text)


def _ok(name: str, args: dict):
    error, payload = _call(name, args)
    assert not error, payload
    return payload


@pytest.fixture
def draft(tmp_path, monkeypatch):
    """A verified unmapped draft of the synthetic DEMO-1 form, and every response the agent read on the way."""
    monkeypatch.setattr(fetch_mod, "_unmapped_open", _Opener({URL: _demo1(tmp_path).read_bytes()}))
    monkeypatch.setattr(fetch_mod, "_sleep", lambda s: None)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("plain urlopen used"))
    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "ws"))
    seen: dict[str, object] = {}
    seen["fetch_blank"] = fetched = _ok("fetch_blank", {**WHERE, "form_title": "DEMO-1"})
    ids = {**WHERE, "blank_sha256": fetched["sha256"]}
    seen["get_form_map"] = _ok("get_form_map", ids)
    out = tmp_path / "ws" / "2025" / "drafts" / "demo-1.pdf"
    seen["fill_form"] = filled = _ok("fill_form", {
        **ids, "values": {"wages": 52000, "first_name": "Demo", "total": 52000}, "out_path": str(out),
        "money_fields": ["wages"], "confirmed_fields": ["first_name"]})
    seen["verify_form"] = verdict = _ok("verify_form", {**ids, "pdf_path": str(out), "expected": filled["written"]})
    assert verdict["ok"] is True and verdict["verified_at"]["output_sha256"] == filled["output_sha256"]
    return {"out": out, "ids": ids, "seen": seen}


def test_eval_v_no_response_for_an_unmapped_draft_claims_filing_grade(draft):
    """Every unmapped response carries the grade, and says the draft is never filing-grade — a passing verify too."""
    for tool, response in draft["seen"].items():
        assert response["grade"] == "unmapped_draft", tool
        assert not _filing_grade_claims(response), (tool, _filing_grade_claims(response))
        said = json.dumps({k: response.get(k) for k in ("limits", "next_step")})
        assert NEVER in said, f"{tool}: its limits / next_step never say the draft is never filing-grade"
    verdict = draft["seen"]["verify_form"]
    assert verdict["ok"] is True and NEVER in verdict["limits"][-1]  # the last limit, whatever ok says
    assert {v["field"] for v in verdict["unverified_values"]} == set(draft["seen"]["fill_form"]["written"])
    fill = draft["seen"]["fill_form"]
    assert {h["field"]: h["reason"] for h in fill["hand_write"]} == {"total": "calculated"}  # KG7: never filled


def test_eval_v_asking_the_pack_path_whether_it_is_ready_to_file_is_refused(draft):
    """An agent that asks the filing checks about the draft (pack-path verify_form, verify_filing under any key) gets
    a refusal that says it is never filing-grade, and no claim."""
    out = str(draft["out"])
    asks = [
        ("verify_form", {"form": "f1040", "year": 2025, "pdf_path": out}),
        ("verify_filing", {"items": [{"form": "f1040", "year": 2025, "pdf_path": out}]}),
        ("verify_filing", {"items": [{"form": "unmapped", "year": 2025, "jurisdiction": "states/sd",
                                      "pdf_path": out}]}),
    ]
    for tool, args in asks:
        error, text = _call(tool, args)
        assert error, (tool, text)
        assert "unmapped draft" in text and ("never filing-grade" in text or "verify_form(form='unmapped'" in text)
        assert not _filing_grade_claims(text), (tool, _filing_grade_claims(text))


@pytest.mark.parametrize("tool", ["filing_summary", "file_and_pay"])
def test_eval_v_the_summary_and_checklist_make_no_filing_grade_claim_for_an_unmapped_item(draft, tool):
    """filing_summary and file_and_pay do not ride the fallback (ADR-0002, The other tools); if an agent passes them
    an unmapped item anyway, nothing they return claims filing-grade."""
    response = _ok(tool, {"manifest": [{"form": "unmapped", "tax_year": 2025, "jurisdiction": "states/sd",
                                        "bottom_line": 0}]})
    assert not _filing_grade_claims(response), _filing_grade_claims(response)
