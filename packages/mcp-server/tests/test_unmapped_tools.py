"""The no-pack fallback over MCP (Phase K JK16b/JK17b, 2026-10-25; ADR-0002, accepted 2026-10-25).

fetch_blank, get_form_map, fill_form and verify_form take form="unmapped" (routing rule 1, the only switch) and
return from their own unmapped branch before any pack loads; verify_filing refuses an unmapped item (rule 15). The
tests here run the real protocol path (the SDK's in-memory client) on JK16's synthetic demo forms, fetched through a
monkeypatched official-host opener as packages/core/tests/test_fetch_unmapped.py does (no network):

- the e2e chain: fetch -> get_form_map (the sweep page) -> fill_form with confirmed_fields -> verify_form ok with
  verified_at; a tampered draft fails;
- every refusal family (UnmappedBlankRefused, UnmappedFillRefused, UnmappedVerifyRefused, StampRefused, a missing
  required parameter) as ValueError text that says no PDF was written, names a pointer, and echoes no value or local
  path (rule 6);
- every new parameter refused with a pack key (rule 3), before any pack loads;
- rule 15 both ways: verify_filing refuses form "unmapped", and pack-path verify_form / verify_filing refuse an
  unmapped draft before either verdict, while an unreadable file keeps today's error text;
- the grade, limits and next_step on every unmapped response, and no `grade` key on any pack-path response (rule 4),
  with the JK6 guard over every unmapped response (rule 7);
- the reserved-key gate (rule 2), the lazy imports (rule 8), and the tools/list surface (23 tools; every existing
  property unchanged; every new property optional, None by default, with its own description).

Demo values only.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect
from mcp.types import ImageContent

import taxfill_mcp.server as server
from taxfill_core import fetch as fetch_mod
from taxfill_core.unmapped_verify import is_unmapped_draft, verified_at_holds

REPO = Path(__file__).resolve().parents[3]
CORE_TESTS = REPO / "packages" / "core" / "tests"
if str(CORE_TESTS) not in sys.path:
    sys.path.insert(0, str(CORE_TESTS))

from pdf_fixtures import make_demo_return  # noqa: E402
from test_journeys import _carries_unmapped_grade, _filing_grade_claims  # noqa: E402
from test_unmapped_fill import _demo1, _demo2, _demo3  # noqa: E402

JUR = "states/sd"
YEAR = 2025
GRADE = "unmapped_draft"
URL = {n: f"https://www.tax.example.gov/forms/{YEAR}/demo-{n}.pdf" for n in range(1, 6)}
TITLE = {n: f"DEMO-{n}" for n in range(1, 6)}
WHERE = {"form": "unmapped", "year": YEAR, "jurisdiction": JUR}

# every new parameter, per tool (ADR-0002 Decision), with a value of its type
NEW_PARAMS = {
    "fetch_blank": {"source_url": URL[1], "form_title": "DEMO-1", "local_blank": "~/saved.pdf"},
    "get_form_map": {"source_url": URL[1], "blank_sha256": "0" * 64},
    "fill_form": {"source_url": URL[1], "blank_sha256": "0" * 64, "money_fields": ["1"],
                  "provenance": {"1": "from the user"}, "confirmed_fields": ["1"]},
    "verify_form": {"source_url": URL[1], "blank_sha256": "0" * 64, "declared_relations": ["3 == 1 + 2"]},
}
# tools/list before JK16b (main e0b3eb8): every existing property's name, type, default and required status
BEFORE = json.loads((Path(__file__).parent / "fixtures" / "unmapped_tool_schemas_before.json").read_text())


# ── the MCP client ─────────────────────────────────────────────────────────────


def _run(coro):
    return asyncio.run(coro)


async def _session_call(name, args):
    async with connect(server.mcp) as client:
        return await client.call_tool(name, args)


def call(name: str, args: dict):
    """The tool's payload, or raise _ToolError with the error text the agent reads."""
    result = _run(_session_call(name, args))
    if result.isError:
        raise _ToolError("\n".join(getattr(b, "text", "") for b in result.content))
    if result.structuredContent is not None:
        sc = result.structuredContent
        return sc.get("result", sc)
    return json.loads(result.content[0].text)


class _ToolError(Exception):
    pass


def refused(name: str, args: dict) -> str:
    with pytest.raises(_ToolError) as info:
        call(name, args)
    return str(info.value)


# ── the environment: a temporary blank cache and workspace, an official-host opener serving demo bytes ────────


class _Opener:
    def __init__(self):
        self.answers: dict[str, bytes] = {}
        self.seen: list[str] = []

    def __call__(self, request, timeout=None):
        self.seen.append(request.full_url)
        return io.BytesIO(self.answers[request.full_url])


@pytest.fixture
def env(tmp_path, monkeypatch):
    opener = _Opener()
    monkeypatch.setattr(fetch_mod, "_unmapped_open", opener)
    monkeypatch.setattr(fetch_mod, "_sleep", lambda s: None)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("plain urlopen used"))
    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "ws"))
    opener.tmp = tmp_path
    return opener


def _serve(env, n: int, pdf: Path) -> None:
    env.answers[URL[n]] = Path(pdf).read_bytes()


def _fetch(env, n: int, pdf: Path) -> dict:
    _serve(env, n, pdf)
    return call("fetch_blank", {**WHERE, "source_url": URL[n], "form_title": TITLE[n]})


def _ids(n: int, fetched: dict) -> dict:
    return {**WHERE, "source_url": URL[n], "blank_sha256": fetched["sha256"]}


def _assert_graded(response: dict, what: str) -> None:
    """Rule 4 (+ rule 7 through the JK6 guard): grade, limits and next_step at the top level, no claim."""
    assert response["grade"] == GRADE, what
    assert isinstance(response["limits"], list) and response["limits"], what
    assert isinstance(response["next_step"], str) and response["next_step"], what
    assert "never filing-grade" in response["limits"][-1] or "never filing-grade" in response["next_step"], what
    assert not _filing_grade_claims(response), (what, _filing_grade_claims(response))
    if "worksheet" in response:
        assert response["worksheet"]["grade"] == GRADE, what


# ── the e2e chain ──────────────────────────────────────────────────────────────


def test_e2e_demo_1_fetch_map_fill_verify_and_a_tampered_draft_fails(env):
    fetched = _fetch(env, 1, _demo1(env.tmp))
    _assert_graded(fetched, "fetch_blank")
    assert fetched["pinned"] is False and fetched["origin"] == "download" and fetched["kind"] == "acroform"
    assert fetched["first_page"] == {"page": 1, "printed_year": YEAR, "title_found": True}
    assert env.seen == [URL[1]] and Path(fetched["path"]).is_file()
    assert fetched["sha256"] in fetched["next_step"] and "get_form_map" in fetched["next_step"]
    ids = _ids(1, fetched)

    fmap = call("get_form_map", ids)
    _assert_graded(fmap, "get_form_map")
    assert fmap["form"] == "unmapped" and fmap["blank_sha256"] == fetched["sha256"]
    fields = {f["name"]: f for f in fmap["fields"]}
    assert fields["total"]["refusal"] == "calculated" and fields["stray"]["refusal"] == "unanchored"
    assert "high" not in {f["confidence"] for f in fmap["fields"]}
    assert {h["field"] for h in fmap["hand_write"]} >= {"total", "stray"}
    assert is_unmapped_draft(fmap["sweep_path"]) is False and Path(fmap["sweep_path"]).is_file()
    # the agent shows the sweep page before the user confirms a box (KG11)
    pages = _run(_session_call("render_form", {"pdf_path": fmap["sweep_path"]}))
    assert [b for b in pages.content if isinstance(b, ImageContent)]

    out = env.tmp / "drafts" / "demo-1.pdf"
    values = {"wages": 52000, "interest": 120.4, "dividends": "75", "first_name": "Demo", "total": 52195,
              "stray": "A", "demo_check": "yes"}
    filled = call("fill_form", {**ids, "values": values, "out_path": str(out),
                                "money_fields": ["wages", "interest", "total"],
                                "confirmed_fields": ["first_name", "demo_check"],
                                "provenance": {"wages": "from a document"}})
    _assert_graded(filled, "fill_form")
    assert filled["status"] == "unverified_draft" and filled["out_path"] == str(out)
    assert filled["written"] == {"wages": "52000", "interest": "120", "dividends": "75", "first_name": "Demo",
                                 "demo_check": "/1"}
    assert {h["field"]: h["reason"] for h in filled["hand_write"]} == {"total": "calculated", "stray": "unanchored"}
    assert filled["labels"]["wages"] == "agent-computed, unverified; from a document"
    assert filled["confirmed"] == {"first_name": "user-confirmed on the rendered page",
                                   "demo_check": "user-confirmed on the rendered page"}
    assert filled["stamp"]["pages"] == [1] and "NOT FILING-GRADE" in filled["stamp"]["text"]
    assert "verify_form" in filled["next_step"] and is_unmapped_draft(out)

    verdict = call("verify_form", {**ids, "pdf_path": str(out), "expected": filled["written"],
                                   "independent": {"wages": 52000},
                                   "declared_relations": ["wages + interest + dividends == 52195"]})
    _assert_graded(verdict, "verify_form ok")
    assert verdict["ok"] is True and verdict["verdict"] == "UNMAPPED" and "status" not in verdict
    assert all(s["failed"] == 0 for s in verdict["sections"].values())
    assert verdict["sections"]["declared_relations"]["checked"] == 1
    assert verified_at_holds(verdict["verified_at"], out)
    assert verdict["verified_at"]["output_sha256"] == verdict["output_sha256"]
    assert any("not signed" in limit for limit in verdict["limits"])  # verified_at stays unsigned, and says so
    assert {v["field"] for v in verdict["unverified_values"]} == set(filled["written"])

    # any later byte voids verified_at
    out.write_bytes(out.read_bytes() + b"\n% re-saved\n")
    assert not verified_at_holds(verdict["verified_at"], out)
    # a tampered draft (one written value changed in a viewer) fails the verify and gets no verified_at
    from pypdf import PdfWriter

    writer = PdfWriter(clone_from=str(out))
    writer.update_page_form_field_values(writer.pages[0], {"wages": "99999"}, auto_regenerate=False)
    writer.write(str(out))
    tampered = call("verify_form", {**ids, "pdf_path": str(out), "expected": filled["written"]})
    _assert_graded(tampered, "verify_form failed")
    assert tampered["ok"] is False and "verified_at" not in tampered
    assert tampered["sections"]["round_trip"]["failed"] >= 1 and tampered["sections"]["unchanged"]["failed"] >= 1


def test_e2e_demo_2_and_3_multi_page_choice_radio_comb_and_kg7_widgets(env):
    fetched = _fetch(env, 2, _demo2(env.tmp))
    ids = _ids(2, fetched)
    fmap = call("get_form_map", ids)
    by = {f["name"]: f for f in fmap["fields"]}
    assert {w["page"] for w in by["hdr_name"]["widgets"]} == {1, 2} and [o["export"] for o in by["state"]["options"]] == ["SD", "ND", "MN"]
    out = env.tmp / "drafts" / "demo-2.pdf"
    filled = call("fill_form", {**ids, "values": {"state": "SD", "demo_id": "123456789", "credit": 40},
                                "out_path": str(out), "confirmed_fields": ["state", "demo_id"]})
    assert filled["stamp"]["pages"] == [1, 2] and filled["written"]["demo_id"] == "123456789"
    verdict = call("verify_form", {**ids, "pdf_path": str(out), "expected": filled["written"]})
    assert verdict["ok"] is True, verdict["sections"]

    fetched = _fetch(env, 3, _demo3(env.tmp))
    filled = call("fill_form", {**_ids(3, fetched), "out_path": str(env.tmp / "drafts" / "demo-3.pdf"),
                                "values": {"ro_amount": 1, "print_button": "x", "signature": "Demo", "plain": 7},
                                "confirmed_fields": ["plain"]})  # the page-covering guard caps its page at 'med'
    reasons = {h["field"]: h["reason"] for h in filled["hand_write"]}
    assert reasons == {"ro_amount": "read_only", "print_button": "pushbutton", "signature": "signature"}
    assert filled["written"] == {"plain": "7"} and filled["guards_hidden"]
    _assert_graded(filled, "fill_form demo 3")


def test_a_flat_blank_gets_the_graded_worksheet_only_response_and_no_pdf(env):
    flat = make_demo_return(env.tmp / "flat.pdf", form="DEMO-4", texts=[(1, 60, 600, "1 Wages")])
    fetched = _fetch(env, 4, flat)
    assert fetched["kind"] == "flat"
    out = env.tmp / "drafts" / "flat.pdf"
    sheet = call("fill_form", {**_ids(4, fetched), "values": {"1": 52000}, "out_path": str(out)})
    _assert_graded(sheet, "fill_form worksheet only")
    assert sheet["status"] == "worksheet_only" and not out.exists()
    assert sheet["worksheet"]["lines"][0]["value_label"] == "agent-computed, unverified"


# ── refusals (rule 6): no PDF written, a pointer, no value, no local path ─────────────────────────────────────


def _rule_6(text: str, env, *secrets: str) -> None:
    assert re.search(r"no PDF was written|Nothing was verified", text, re.IGNORECASE), text
    assert re.search(r"https://[a-z0-9.-]+\.gov", text), text  # a pointer: the official URL or the forms pages
    assert str(env.tmp) not in text and str(env.tmp.resolve()) not in text, text
    assert not re.search(r"/(?:Users|home)/[^/\s]+/", text), text
    for secret in secrets:
        assert secret not in text, text


def test_unmapped_blank_refused_at_the_fetch_and_at_every_later_step(env):
    # rule 2: an official host only (the opener is never asked)
    text = refused("fetch_blank", {**WHERE, "source_url": "https://forms.example.com/demo.pdf", "form_title": "X"})
    _rule_6(text, env)
    assert "official US government host" in text and "irs.gov/businesses" in text and env.seen == []
    # rule 7: the first page must print the tax year (a 2024 blank asked for 2025)
    _serve(env, 5, make_demo_return(env.tmp / "y.pdf", form="DEMO-5", year="2024"))
    text = refused("fetch_blank", {**WHERE, "source_url": URL[5], "form_title": TITLE[5]})
    _rule_6(text, env)
    assert f"The form's official source: {URL[5]}" in text
    # rule 1: a shipped pack wins (refused before any download)
    pack = next(f for f in server.list_forms("federal", 2025) if f["form_key"] == "f1040")
    text = refused("fetch_blank", {**WHERE, "jurisdiction": "federal", "source_url": pack["source_url"],
                                   "form_title": "1040"})
    _rule_6(text, env)
    assert "'f1040'" in text and pack["source_url"] not in env.seen
    # rule 5 / 6: a later step names a blank that was never stored
    text = refused("get_form_map", {**WHERE, "source_url": URL[1], "blank_sha256": "a" * 64})
    _rule_6(text, env)
    assert "fetch_blank with form='unmapped'" in text and "fetch_unmapped_blank" not in text
    # a missing local blank: the path is shown home-relative at most, never the workspace's absolute path
    text = refused("fetch_blank", {**WHERE, "source_url": URL[1], "form_title": TITLE[1],
                                   "local_blank": str(env.tmp / "ws" / "nope.pdf")})
    _rule_6(text, env)


def test_unmapped_fill_refused_writes_nothing_and_echoes_no_value(env):
    fetched = _fetch(env, 2, _demo2(env.tmp))
    out = env.tmp / "drafts" / "x.pdf"
    secret = "987654321012"
    text = refused("fill_form", {**_ids(2, fetched), "values": {"demo_id": secret}, "out_path": str(out),
                                 "confirmed_fields": ["demo_id"]})
    _rule_6(text, env, secret)
    text = refused("fill_form", {**_ids(2, fetched), "values": {"no_such_field": "Demo"}, "out_path": str(out)})
    _rule_6(text, env, "Demo")
    assert "unknown field name" in text and not out.exists()


def test_unmapped_verify_refused_names_what_to_pass(env):
    fetched = _fetch(env, 1, _demo1(env.tmp))
    text = refused("verify_form", {**_ids(1, fetched), "pdf_path": str(env.tmp / "missing.pdf"),
                                   "expected": {"wages": "52000"}})
    _rule_6(text, env, "52000")
    assert "verify_form (form='unmapped') refused" in text and "out_path fill_form returned" in text
    assert "Nothing was verified and no PDF was written" in text
    text = refused("verify_form", {**_ids(1, fetched), "pdf_path": str(env.tmp / "missing.pdf"),
                                   "expected": {"wages": 52000}})
    _rule_6(text, env)
    assert "written map" in text


def test_stamp_refused_when_a_page_has_no_room(env):
    blank = make_demo_return(env.tmp / "full.pdf", form="DEMO-5",
                             fields=[{"name": "cover", "x": 0, "y": 0, "width": 612, "height": 792}])
    fetched = _fetch(env, 5, blank)
    out = env.tmp / "drafts" / "full.pdf"
    text = refused("fill_form", {**_ids(5, fetched), "values": {}, "out_path": str(out)})
    _rule_6(text, env)
    assert "no place for the stamp" in text and text.lower().count("no pdf was written") == 1 and not out.exists()


@pytest.mark.parametrize(("tool", "missing"), [
    ("fetch_blank", {"source_url": URL[1]}), ("fetch_blank", {"form_title": "DEMO-1"}),
    ("get_form_map", {"source_url": URL[1]}), ("fill_form", {"blank_sha256": "0" * 64}),
    ("verify_form", {"source_url": URL[1], "blank_sha256": "0" * 64}),
])
def test_a_missing_required_parameter_is_refused_with_a_pointer(env, tool, missing):
    args = {**WHERE, **missing}
    if tool == "fill_form":
        args.update(values={}, out_path=str(env.tmp / "x.pdf"))
    if tool == "verify_form":
        args.update(pdf_path=str(env.tmp / "x.pdf"))
    text = refused(tool, args)
    assert "with form='unmapped' needs" in text and re.search(r"https://[a-z0-9.-]+\.gov", text)
    assert env.seen == []


# ── rule 3: every new parameter is refused with a pack key ────────────────────────────────────────────────────


@pytest.mark.parametrize(("tool", "param"), [(t, p) for t, ps in NEW_PARAMS.items() for p in ps])
def test_every_new_parameter_is_refused_with_a_pack_key(tmp_path, monkeypatch, tool, param):
    monkeypatch.setattr(server, "_load_any_pack", lambda *a: pytest.fail("the pack loaded"))
    monkeypatch.setattr(server, "_get_form_map", lambda *a: pytest.fail("the pack map loaded"))
    out = tmp_path / "out.pdf"
    args = {"form": "f8843", "year": 2025, param: NEW_PARAMS[tool][param]}
    if tool == "fill_form":
        args.update(values={"name.first": "Demo"}, out_path=str(out))
    if tool == "verify_form":
        args.update(pdf_path=str(out))
    text = refused(tool, args)
    assert f"{param} is only for form='unmapped'" in text and "'f8843' is a pack key" in text
    assert not out.exists()


# ── rule 15, both ways ─────────────────────────────────────────────────────────


def _a_draft(env) -> Path:
    fetched = _fetch(env, 1, _demo1(env.tmp))
    out = env.tmp / "drafts" / "d.pdf"
    call("fill_form", {**_ids(1, fetched), "values": {"wages": 52000}, "out_path": str(out)})
    assert is_unmapped_draft(out)
    return out


def test_rule_15_verify_filing_refuses_an_unmapped_item_with_a_pointer_to_verify_form(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_load_any_pack", lambda *a: pytest.fail("the pack loaded"))
    text = refused("verify_filing", {"items": [{"form": "unmapped", "year": YEAR, "jurisdiction": JUR,
                                                "pdf_path": str(tmp_path / "d.pdf"), "form_key": "sd_draft"}]})
    assert "'sd_draft' has form 'unmapped'" in text and "verify_form(form='unmapped'" in text
    assert "Nothing was verified" in text and "never filing-grade" in text


def test_rule_15_the_pack_path_refuses_an_unmapped_draft_before_either_verdict(env, monkeypatch):
    draft = _a_draft(env)
    for tool, args in [
        ("verify_form", {"form": "f8843", "year": 2025, "pdf_path": str(draft)}),
        ("verify_form", {"form": "ct1040", "year": 2023, "jurisdiction": "states/ct", "pdf_path": str(draft),
                         "expected": {"1": 1}}),  # the OVERLAY verdict's path
        ("verify_filing", {"items": [{"form": "f8843", "year": 2025, "pdf_path": str(draft)}]}),
    ]:
        text = refused(tool, args)
        assert "is an unmapped draft" in text and "verify_form(form='unmapped'" in text, (tool, text)
        assert "Nothing was verified" in text and str(env.tmp) not in text


def test_rule_15_the_probe_never_raises_today_s_error_text_stands(tmp_path):
    missing = tmp_path / "missing.pdf"
    text = refused("verify_form", {"form": "f8843", "year": 2025, "pdf_path": str(missing)})
    assert "no PDF at" in text and "unmapped draft" not in text
    garbage = tmp_path / "garbage.pdf"
    garbage.write_bytes(b"%PDF-1.7 not really")
    text = refused("verify_filing", {"items": [{"form": "f8843", "year": 2025, "pdf_path": str(garbage)}]})
    assert "unmapped draft" not in text


# ── rule 4: no pack-path response carries a grade ─────────────────────────────────────────────────────────────


def _keys(obj, found: set[str]) -> set[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(re.sub(r"[^a-z0-9]", "", str(k).lower()))
            _keys(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, found)
    return found


def test_no_pack_path_response_carries_a_grade_key():
    # every response the pack-path golden pins (every shipped pack's map, the refusals, the demo chain)
    goldens = REPO / "packages" / "core" / "tests" / "goldens" / "pack_path"
    for path in goldens.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "grade" not in _keys(data, set()), path.name
        assert not _carries_unmapped_grade(data), path.name


# ── rule 2, rule 8 and the tools/list surface ───────────────────────────────────────────────────────────────


def test_the_unmapped_key_is_reserved_no_pack_directory_may_use_it():
    clashes = sorted(str(p.relative_to(REPO)) for p in (REPO / "formpacks").glob("**/unmapped") if p.is_dir())
    assert clashes == [], f"'unmapped' is reserved for the no-pack fallback (ADR-0002 rule 2): {clashes}"
    assert "unmapped" not in {f["form_key"] for f in server.list_forms()}


def test_the_server_imports_the_unmapped_modules_lazily():
    probe = ("import sys, taxfill_mcp.server; print(sorted(m for m in ('taxfill_core.unmapped', "
             "'taxfill_core.unmapped_verify', 'taxfill_core.stamp', 'taxfill_core.anchor', 'taxfill_core.overlay') "
             "if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_the_tool_surface_stays_23_and_only_grows_optional_described_properties():
    tools = {t.name: t for t in _run(server.mcp.list_tools())}
    assert len(tools) == 23
    for name, before in BEFORE.items():
        schema = tools[name].inputSchema
        props = schema["properties"]
        for prop, spec in before["properties"].items():
            assert props[prop] == spec, (name, prop)
        assert schema.get("required", []) == before["required"], name
        added = set(props) - set(before["properties"])
        assert added == set(NEW_PARAMS.get(name, {})), (name, added)
        for prop in added:
            assert props[prop]["default"] is None and "only with form='unmapped'" in props[prop]["description"].lower()


# ── the JK16b review's minors (2026-10-25) ─────────────────────────────────────

FALSY = {"source_url": "", "form_title": "", "local_blank": "", "blank_sha256": "", "money_fields": [],
         "provenance": {}, "confirmed_fields": [], "declared_relations": []}


@pytest.mark.parametrize(("tool", "param"), [(t, p) for t, ps in NEW_PARAMS.items() for p in ps])
def test_a_falsy_new_parameter_is_refused_with_a_pack_key_too(tmp_path, monkeypatch, tool, param):
    # `if value` in place of `is not None` would let "", [] and {} through in silence
    monkeypatch.setattr(server, "_load_any_pack", lambda *a: pytest.fail("the pack loaded"))
    monkeypatch.setattr(server, "_get_form_map", lambda *a: pytest.fail("the pack map loaded"))
    out = tmp_path / "out.pdf"
    args = {"form": "f8843", "year": 2025, param: FALSY[param]}
    if tool == "fill_form":
        args.update(values={"name.first": "Demo"}, out_path=str(out))
    if tool == "verify_form":
        args.update(pdf_path=str(out))
    assert f"{param} is only for form='unmapped'" in refused(tool, args) and not out.exists()


def test_no_refusal_text_claims_filing_grade(env):
    fetched = _fetch(env, 1, _demo1(env.tmp))
    texts = [
        refused("verify_filing", {"items": [{"form": "unmapped", "year": YEAR, "jurisdiction": JUR,
                                             "pdf_path": str(env.tmp / "d.pdf")}]}),
        refused("fill_form", {**_ids(1, fetched), "values": {"no_such_field": "Demo"},
                              "out_path": str(env.tmp / "x.pdf")}),
        refused("verify_form", {**_ids(1, fetched), "pdf_path": str(env.tmp / "missing.pdf"),
                                "expected": {"wages": "1"}}),
        refused("fetch_blank", {**WHERE, "source_url": "http://tax.example.gov/f.pdf", "form_title": TITLE[1]}),
        refused("get_form_map", {**WHERE, "source_url": URL[1], "blank_sha256": "0" * 64}),
    ]
    for text in texts:
        assert not _filing_grade_claims(text), (text, _filing_grade_claims(text))


def test_rule_15_refuses_a_draft_named_with_a_tilde(env, monkeypatch):
    draft = _a_draft(env)
    monkeypatch.setenv("HOME", str(env.tmp))
    tilde = "~/" + str(draft.relative_to(env.tmp))
    for tool, args in [("verify_form", {"form": "f8843", "year": 2025, "pdf_path": tilde}),
                       ("verify_filing", {"items": [{"form": "f8843", "year": 2025, "pdf_path": tilde}]})]:
        assert "is an unmapped draft" in refused(tool, args), tool


def test_a_draft_is_never_written_into_the_shared_blank_cache(env):
    # the sweep page sits beside the blank in the cache, which `taxfill purge` does not clear
    fetched = _fetch(env, 1, _demo1(env.tmp))
    sweep = Path(call("get_form_map", _ids(1, fetched))["sweep_path"])
    before = sweep.read_bytes()
    for target in (sweep, sweep.parent / "other.pdf"):
        text = refused("fill_form", {**_ids(1, fetched), "values": {"wages": 52000}, "out_path": str(target)})
        assert "shared blank cache" in text and "52000" not in text, text
    assert sweep.read_bytes() == before and not (sweep.parent / "other.pdf").exists()


def test_a_bad_pdf_or_a_truncated_download_surfaces_as_rule_6_text(env, monkeypatch):
    import http.client

    from pypdf.errors import PdfReadError

    import taxfill_core.unmapped as unmapped_mod

    fetched = _fetch(env, 1, _demo1(env.tmp))

    def bad_pdf(*a, **k):
        raise PdfReadError("EOF marker not found")

    monkeypatch.setattr(unmapped_mod, "fill_unmapped", bad_pdf)
    text = refused("fill_form", {**_ids(1, fetched), "values": {"wages": 1}, "out_path": str(env.tmp / "y.pdf")})
    assert "fill_form (form='unmapped') refused" in text and "No PDF was written" in text, text

    def truncated(*a, **k):
        raise http.client.IncompleteRead(b"%PDF-1.7 partial")

    monkeypatch.setattr(fetch_mod, "fetch_unmapped_blank", truncated)
    text = refused("fetch_blank", {**WHERE, "source_url": URL[2], "form_title": TITLE[2]})
    assert "fetch_blank (form='unmapped') refused" in text, text
