"""Five journey goldens (Phase K JK6; KG10: demo personas only).

Five scripted journeys of the TY2025 filing season (journey 5 amends TY2024) through the MCP tools, run in-process over the SDK's in-memory client<->server
transport (the same path as test_server_e2e.py): the calls an agent makes, in the order it makes them, on
hypothetical people. Every name, number and address below is fictitious ("Example" surnames, the never-issued
999-88-xxxx SSN range, "Example ..." employers and schools).

  1. A W-2 employee: the docs/samples/w2_2025_synthetic persona that docs/dev/ACCEPTANCE.md walks (Washington, single).
  2. An F-1 nonresident-alien student from China: residency, the U.S.-China treaty, Form 1040-NR + Schedule OI +
     Form 8843.
  3. A part-year mover from Virginia to California (moved 2025-07-01).
  4. A city-tax filer: an Ohio resident of a taxing school district (Ohio IT 1040 + the school district SD 100).
  5. An amended prior-year return: a Georgia resident's TY2024 Form 1040-X, and the Georgia Form 500X beside it.

PATHS. Every step records, as data (``Step.path``), how the tools serve it:

  pack     — a shipped pack serves the step: a form pack fills the form, or a knowledge / treaty / DocSpec pack
             computes, scopes or structures the answer, with its citation.
  fallback — the no-pack unmapped draft of JK16-JK18. It does not exist yet, so no journey records it today.
  pointer  — nothing fills or computes it: the tools name the official form or source (an https .gov URL) instead.
  refusal  — the tool refuses with an error that says why (no pack for that form, and which form keys do exist).

Journeys 3-5 hold the honest pointer or refusal where nothing fills the form today (Virginia Form 760PY, Ohio SD 100,
Georgia Form 500X); JK18 upgrades those steps to labeled drafts. Key figures are recomputed through calc (and across
tools: estimate_refund's ledger against calc's tax and deduction) wherever a figure is arithmetic, never typed.

THE GUARD (module level). ``_check_step`` runs on every step as it is recorded: a fallback, pointer or refusal step
whose output claims filing-grade fails the journey (KG5: unmapped output is never filing-grade). The only grade a
non-pack output may carry is ``unmapped_draft``; "filing-grade" / "ready to file" may appear only negated ("NOT
FILING-GRADE"). ``test_no_fallback_pointer_or_refusal_step_claims_filing_grade`` re-checks every recorded step and
``test_the_guard_catches_a_planted_claim`` holds the guard itself to planted claims. This is the test the fallback
path will have to pass.

WHERE EACH STEP RUNS. CI's offline job (``pytest -m "not network"``, .github/workflows/ci.yml) runs every step that
needs no official blank PDF:
  J1  extract_document, state_scope, estimate_refund, calc (standard_deduction, tax), list_forms, filing_summary,
      file_and_pay; and ACCEPTANCE.md is held to the figures they return.
  J2  residency, calc (treaty_benefit, tax), estimate_refund, list_forms, state_scope, filing_summary, file_and_pay.
  J3  state_scope, estimate_refund, list_forms, get_form_map, calc (state_tax), and the Form 760PY refusals
      (get_form_map, fill_form) and pointer.
  J4  state_scope, list_forms, calc (state_tax), get_sources (the SD 100 pointer), and the SD 100 refusals
      (get_form_map, hand_fill_worksheet).
  J5  state_scope, estimate_refund (original and corrected), calc (standard_deduction, tax, state_tax), list_forms,
      get_form_map, the Form 500X refusal (get_form_map) and pointer (file_and_pay).
The fetch_blank / fill_form / verify_form / render_form steps need the official blanks, so they are network-marked
tests (the weekly ``pytest -m network`` job in .github/workflows/freshness.yml): J1 Form 1040 (fill, verify with the
independent recompute, render page 1), J2 Form 1040-NR + Schedule OI (verify_filing with the recompute) and Form 8843
(verify_form), J3 Form 540NR, J5 Form 1040-X (2024, with the recompute). With no network and a cold blank cache they
skip. J4 runs offline only (its IT 1040 pack is held by the Ohio pack's own golden).

KNOWN DEFECTS the journeys found are held as strict xfails (each turns red when the tool is fixed, so the mark comes
off): file_and_pay prices a Form 1040-X as a Form 1040 and returns the 1040 address (offline); it also routes a Georgia
Form 500X like an original Form 500 (offline); Virginia's state_scope entry names Form 760PY but cites only the resident
Form 760 instructions (offline); and verify_filing fails an attached Form 8843 whose address boxes are blank as the form
instructs (network). Phase K JK27 fixes them.
"""
from __future__ import annotations

import asyncio
import tempfile
import functools
import importlib.util
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect
from mcp.types import ImageContent

from taxfill_core.calc import irs_round
from taxfill_core.discovery import load_form_pack
from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank
from taxfill_mcp.server import mcp

REPO = Path(__file__).resolve().parents[3]
ACCEPTANCE = REPO / "docs" / "dev" / "ACCEPTANCE.md"
SAMPLE_PNG = "docs/samples/w2_2025_synthetic.png"  # the reading's document provenance, repo-relative

PATHS = ("pack", "fallback", "pointer", "refusal")
_USER = {"kind": "user_stated"}


def _sample_script():
    spec = importlib.util.spec_from_file_location("make_sample_w2", REPO / "scripts" / "make_sample_w2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The sample W-2's persona and boxes come from the script that drew it (packages/core/tests/test_sample_w2.py holds the
# committed PDF to the same boxes), so journey 1 and ACCEPTANCE.md move with the sample.
MAKE = _sample_script()


# ── the step record, and the module-level guard ────────────────────────────────


@dataclass(frozen=True)
class Step:
    name: str
    tool: str
    path: str  # one of PATHS
    output: Any  # the tool's payload; for a refusal, the error text
    error: bool


@dataclass
class JourneyRun:
    steps: list[Step] = field(default_factory=list)
    figures: dict[str, Any] = field(default_factory=dict)


_GRADE_ALLOWED = {"unmapped_draft"}  # KG5: the only grade an unmapped / pointer / refusal output may carry
_CLAIM_TEXT = re.compile(
    r"filing[\s_-]*grade|ready[\s_-]+(?:to[\s_-]+(?:file|sign|mail)|for[\s_-]+filing)|\bis[\s_-]+final\b", re.IGNORECASE)
# A claim counts as negated only when "not" / "never" (optionally "yet", "a" or "an") sits IMMEDIATELY before it:
# "NOT FILING-GRADE" and "never filing-grade" pass; "Not a draft, this is filing-grade." does not.
_NEGATED = re.compile(r"\b(?:not|never)\s+(?:(?:yet|a|an)\s+)?$", re.IGNORECASE)
_CLAIM_KEYS = {"filinggrade", "filingready", "readytofile", "readyforfiling"}


def _filing_grade_claims(obj: Any, where: str = "$") -> list[str]:
    """Every place ``obj`` claims filing-grade: a grade other than unmapped_draft, a truthy filing-grade / ready flag,
    a filing-grade or final status, or the words "filing-grade" / "ready to file" not negated just before."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{where}.{key}"
            k = re.sub(r"[^a-z0-9]", "", str(key).lower())  # FilingGrade, filing-grade and filing_grade are one key
            if k == "grade" and value not in _GRADE_ALLOWED:
                found.append(f"{here} = {value!r}")
            elif k in _CLAIM_KEYS and value:
                found.append(f"{here} = {value!r}")
            elif k in ("status", "sourcestatus") and isinstance(value, str) and (
                    value.lower() in ("final", "ready") or _CLAIM_TEXT.search(value)):
                found.append(f"{here} = {value!r}")
            found += _filing_grade_claims(value, here)
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            found += _filing_grade_claims(value, f"{where}[{i}]")
    elif isinstance(obj, str):
        for m in _CLAIM_TEXT.finditer(obj):
            if not _NEGATED.search(obj[max(0, m.start() - 40):m.start()]):
                found.append(f"{where}: ...{obj[max(0, m.start() - 60):m.end() + 20]}...")
    return found


_OFFICIAL_URL = re.compile(r"https://[a-z0-9.-]+\.gov(?:/|\b)", re.IGNORECASE)


def _check_step(step: Step) -> None:
    """The invariants every recorded step must hold (applied as each step is recorded)."""
    assert step.path in PATHS, f"{step.name}: unknown path {step.path!r}"
    text = step.output if isinstance(step.output, str) else json.dumps(step.output)
    if step.path == "refusal":
        assert step.error, f"{step.name}: a refusal is a tool error"
        assert re.search(r"\bno (?:form|hand-fill) pack for form\b", text), f"{step.name}: the refusal must say why"
    else:
        assert not step.error, f"{step.name}: {text[:400]}"
    if step.path == "pointer":
        assert _OFFICIAL_URL.search(text), f"{step.name}: a pointer names an official https .gov source"
    if step.path == "fallback":
        assert isinstance(step.output, dict) and step.output.get("grade") == "unmapped_draft", (
            f"{step.name}: a fallback output carries grade 'unmapped_draft' (KG5)")
    if step.path != "pack":
        claims = _filing_grade_claims(step.output)
        assert not claims, f"{step.name} ({step.path}) claims filing-grade: {claims}"
    else:  # a step labelled "pack" whose output carries the unmapped grade is a mislabelled fallback
        assert not _carries_unmapped_grade(step.output), f"{step.name}: a pack step carries grade 'unmapped_draft'"


def _carries_unmapped_grade(obj: Any) -> bool:
    if isinstance(obj, dict):
        return any((re.sub(r"[^a-z0-9]", "", str(k).lower()) == "grade" and v == "unmapped_draft") or _carries_unmapped_grade(v)
                   for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return any(_carries_unmapped_grade(v) for v in obj)
    return False


def _data(result):
    """A tool's payload (structured when present, else JSON text) — the test_server_e2e.py helper."""
    if result.structuredContent is not None:
        sc = result.structuredContent
        return sc.get("result", sc)  # list-returning tools wrap under "result"
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    return None


class Recorder:
    """Calls the tools over one MCP session and records each call as a Step."""

    def __init__(self, client, run: JourneyRun):
        self.client = client
        self.run = run

    async def call(self, name: str, path: str, tool: str, args: dict) -> Any:
        result = await self.client.call_tool(tool, args)
        if result.isError:
            output = "\n".join(getattr(b, "text", "") for b in result.content)
        elif tool == "render_form":
            output = [{"mimeType": b.mimeType, "bytes": len(b.data)} for b in result.content if isinstance(b, ImageContent)]
        else:
            output = _data(result)
        return self.record(name, path, tool, output, error=bool(result.isError))

    def record(self, name: str, path: str, tool: str, output: Any, *, error: bool = False) -> Any:
        """Record a step; ``call`` uses it, and a step that reads a part of an earlier call's answer uses it directly."""
        step = Step(name, tool, path, output, error)
        _check_step(step)
        self.run.steps.append(step)
        return output


def _run_journey(body) -> JourneyRun:
    async def go():
        run = JourneyRun()
        async with connect(mcp) as client:
            await body(Recorder(client, run), run.figures)
        return run
    return asyncio.run(go())


def _comp(estimate: dict) -> dict[str, int]:
    return {c["slot"]: c["amount"] for c in estimate["composition"]}


def _need_blank(form: str, year: int, jurisdiction: str = "federal") -> None:
    """Skip cleanly when the blank is neither cached nor downloadable (offline + cold cache)."""
    try:
        fetch_pack_blank(load_form_pack(form, year, jurisdiction))
    except OfflineFetchError as exc:
        pytest.skip(f"{jurisdiction} {form} {year}: cache empty and network unreachable: {exc}")


def _days(start: date, end: date) -> int:
    return (end - start).days + 1


# ── Journey 1 — the W-2 employee of ACCEPTANCE.md (Washington, single) ─────────

J1_PROFILE = {
    "household": {"marital_status": {"value": "unmarried", "provenance": _USER},
                  "filing_status": {"value": "single", "provenance": _USER}},
    "identity": {"us_person": {"value": True, "provenance": _USER}},
    "state_footprint": {"2025": {
        "lived": [{"state": "WA", "start": "2025-01-01", "end": "2025-12-31", "provenance": _USER}],
        "worked": [{"state": "WA", "start": "2025-01-01", "end": "2025-12-31", "provenance": _USER}]}},
}
J1_EXPECTED_PATHS = [
    ("read the sample W-2", "pack"),
    ("scope the state returns", "pack"),
    ("estimate the refund", "pack"),
    ("standard deduction (line 12e)", "pack"),
    ("tax on taxable income (line 16)", "pack"),
    ("find the 2025 Form 1040 pack", "pack"),
    ("filing summary", "pack"),
    ("file and pay", "pack"),
]


async def _journey_1(j: Recorder, fig: dict) -> None:
    extracted = await j.call("read the sample W-2", "pack", "extract_document", {
        "path": SAMPLE_PNG, "kind": "W-2", "fields": MAKE.w2_boxes(), "page": 1, "tax_year": 2025})
    assert extracted["gaps"] == [] and extracted["unexpected"] == []
    box = {f["key"]: f["value"] for f in extracted["fields"] if f["status"] == "ok"}
    wages, withheld = irs_round(box["1"]), irs_round(box["2"])

    scope = await j.call("scope the state returns", "pack", "state_scope", {"profile": J1_PROFILE, "year": 2025})
    assert [(s["state"], s["filing_role"], s["must_file"], s["forms"]) for s in scope["states"]] == [
        ("WA", "none", False, [])]  # Washington does not tax wages: no state return

    w2 = {"employer": MAKE.PERSONA["employer_name"],
          **{f"box{k}": irs_round(box[k]) for k in ("1", "2", "3", "4", "5", "6")},
          "box12": [{"code": code, "amount": irs_round(amount)}
                    for code, amount in (box[k].split() for k in ("12a", "12b"))]}
    est = await j.call("estimate the refund", "pack", "estimate_refund", {
        "profile": J1_PROFILE, "year": 2025, "income": {"w2s": [w2]}})
    assert est["label"] == "ESTIMATE" and est["low"] == est["high"] == est["point"]  # status confirmed: one number
    ledger = _comp(est)

    std = await j.call("standard deduction (line 12e)", "pack", "calc", {
        "op": "standard_deduction", "args": {"filing_status": "single", "year": 2025}})
    taxable = wages - std["amount"]
    tax = await j.call("tax on taxable income (line 16)", "pack", "calc", {
        "op": "tax", "args": {"taxable_income": taxable, "filing_status": "single", "year": 2025}})
    assert std["citation"]["url"].startswith("https://www.irs.gov/") and tax["citation"]["url"].startswith("https://www.irs.gov/")
    # estimate_refund's ledger, recomputed through calc: AGI = box 1, deduction = calc's, tax = calc's.
    assert ledger["agi"] == wages and ledger["deduction"] == -std["amount"]
    assert ledger["taxable_income"] == taxable and ledger["income_tax"] == tax["tax"] == ledger["total_tax"]
    refund = withheld - tax["tax"]
    assert ledger["withholding"] == -withheld and est["point"] == ledger["bottom_line"] == refund > 0

    forms = await j.call("find the 2025 Form 1040 pack", "pack", "list_forms", {"jurisdiction": "federal", "year": 2025})
    f1040 = next(f for f in forms if f["form_key"] == "f1040")
    assert f1040["source_status"] == "final" and f1040["source_url"].startswith("https://www.irs.gov/")

    # ACCEPTANCE.md: the persona declines direct deposit (a demo has no bank account).
    manifest = [{"form": "1040", "tax_year": 2025, "bottom_line": refund, "state": "WA"}]
    summary = await j.call("filing summary", "pack", "filing_summary", {"manifest": manifest})
    headline = summary["items"][0]["headline"]
    assert headline.startswith(f"Federal 2025: refund ${refund:,}")
    paid = await j.call("file and pay", "pack", "file_and_pay", {"manifest": manifest})
    address = paid["returns"][0]["mailing_address"]
    assert paid["returns"][0]["payment"] == [] and address.startswith("Department of the Treasury, Internal Revenue Service, ")
    fig.update(wages=wages, withheld=withheld, std=std["amount"], taxable=taxable, tax=tax["tax"], refund=refund,
               headline=headline, address=address.split("Internal Revenue Service, ", 1)[1])


@functools.cache
def _journey_1_run() -> JourneyRun:
    return _run_journey(_journey_1)


def test_journey_1_w2_employee():
    run = _journey_1_run()
    assert [(s.name, s.path) for s in run.steps] == J1_EXPECTED_PATHS


def _acceptance_section(text: str, start: str, end: str) -> str:
    assert start in text and end in text.split(start, 1)[1], f"ACCEPTANCE.md lost its {start!r} / {end!r} headings"
    return text.split(start, 1)[1].split(end, 1)[0]


def test_acceptance_walks_journey_1():
    """ACCEPTANCE.md walks journey 1: same persona, and every figure it states is what the tools return."""
    fig = _journey_1_run().figures
    text = ACCEPTANCE.read_text(encoding="utf-8")
    steps = " ".join(_acceptance_section(text, "## Guided filing", "## Pass criteria").split())  # unwrap the lines
    persona = MAKE.PERSONA
    for quoted in (
        "samples/w2_2025_synthetic.png",
        f"{persona['employee_first']} {persona['employee_last']}", persona["employee_ssn"],
        ", ".join(persona["employee_address"]), "Washington", "single",
        f"wages ${fig['wages']:,}", f"federal tax withheld ${fig['withheld']:,}",
        f"a refund of about ${fig['refund']:,}", f"${fig['tax']:,}",
        f"lines 1a, 9 and 11a read {fig['wages']}",
        f"Federal 2025: refund ${fig['refund']:,}", fig["address"],
        f"wages {fig['wages']}, AGI {fig['wages']}",
    ):
        assert quoted in steps, f"ACCEPTANCE.md does not state {quoted!r} (journey 1 returns it)"


@pytest.mark.network
def test_journey_1_network_fill_verify_render_the_1040(tmp_path):
    fig = _journey_1_run().figures
    _need_blank("f1040", 2025)
    persona = MAKE.PERSONA
    street, city_line = persona["employee_address"]
    city, state_zip = city_line.split(", ")
    state, zip_code = state_zip.split()
    tax, refund = fig["tax"], fig["refund"]
    values = {
        "name.first": persona["employee_first"].rstrip("."), "name.last": persona["employee_last"],
        "identifying_number": persona["employee_ssn"].replace("-", ""),
        "mailing_address.street": street.rsplit(" Apt ", 1)[0], "mailing_address.apt": street.rsplit(" Apt ", 1)[1],
        "mailing_address.city": city, "mailing_address.state": state, "mailing_address.zip": zip_code,
        "filing_status.single": True, "digital_assets.no": True,  # the persona holds no digital assets
        "1a": fig["wages"], "1z": fig["wages"], "9": fig["wages"], "11a": fig["wages"], "11b": fig["wages"],
        "12e": fig["std"], "14": fig["std"], "15": fig["taxable"],
        "16": tax, "18": tax, "22": tax, "24": tax,
        "25a": fig["withheld"], "25d": fig["withheld"], "33": fig["withheld"], "34": refund, "35a": refund,
    }
    out = str(tmp_path / "f1040_2025_journey1.pdf")

    async def body(j: Recorder, _fig: dict) -> None:
        fetched = await j.call("fetch the official 2025 Form 1040", "pack", "fetch_blank", {"form": "f1040", "year": 2025})
        assert fetched["source_url"].startswith("https://www.irs.gov/") and fetched["sha256"]
        filled = await j.call("fill the Form 1040", "pack", "fill_form", {
            "form": "f1040", "year": 2025, "values": values, "out_path": out})
        assert filled["warnings"] == [] and len(filled["written"]) >= len(values)
        report = await j.call("verify the Form 1040", "pack", "verify_form", {
            "form": "f1040", "year": 2025, "pdf_path": out,
            "expected": {k: v for k, v in values.items() if isinstance(v, int) and not isinstance(v, bool)},
            "independent": {"16": tax, "12e": fig["std"]}})
        assert report["ok"] is True, report
        rec = report["sections"]["recompute"]
        assert rec["checked"] == 2 and rec["failed"] == 0 and "note" not in rec  # the independent recompute ran
        images = await j.call("render page 1", "pack", "render_form", {"pdf_path": out, "pages": [1]})
        assert len(images) == 1 and images[0]["mimeType"] == "image/png" and images[0]["bytes"] > 1000

    run = _run_journey(body)
    assert [s.path for s in run.steps] == ["pack"] * 4
    # ACCEPTANCE.md: "render_form shows page 1 of the filled 1040 (lines 1a, 9 and 11a read 168100)" — those three
    # lines sit on page 1 of the pack's blank.
    fields = {ln["line"]: ln["field"] for ln in _form_map_lines("f1040", 2025)}
    assert all(fields[line].startswith("Page1[") for line in ("1a", "9", "11a"))


def _form_map_lines(form: str, year: int, jurisdiction: str = "federal") -> list[dict]:
    async def go():
        async with connect(mcp) as client:
            return _data(await client.call_tool("get_form_map", {"form": form, "year": year, "jurisdiction": jurisdiction}))
    return asyncio.run(go())["lines"]


# ── Journey 2 — an F-1 nonresident-alien student (China; Form 1040-NR + 8843) ──

J2_ARRIVED = date(2023, 8, 15)  # entered on an F-1 visa; never left since
J2_DAYS = {str(y): _days(max(J2_ARRIVED, date(y, 1, 1)), date(y, 12, 31)) for y in (2023, 2024, 2025)}
J2_PERSON = {"first": "Avery", "last": "Example", "ssn": "999-88-0502", "country": "China",
             "street": "1 Demo Way", "apt": "2", "city": "Sampleton", "state": "CA", "zip": "90000",
             "school": "Example University, 1 Demo Way, Sampleton, CA 90000"}
J2_WAGES, J2_WITHHELD = 12000, 900  # on-campus job at Example University (Form W-2 boxes 1 and 2)
J2_PROFILE = {
    "household": {"marital_status": {"value": "unmarried", "provenance": _USER},
                  "filing_status": {"value": "single", "provenance": _USER}},
    "identity": {"us_person": {"value": False, "provenance": _USER},
                 "citizenship_country": {"value": J2_PERSON["country"], "provenance": _USER}},
    "immigration": {"visa_timeline": [{"status": "F-1", "sub_status": "student", "start": J2_ARRIVED.isoformat(),
                                       "end": None, "provenance": _USER}]},
    "residency_facts": {"days_in_us": {y: {"value": d, "provenance": _USER} for y, d in J2_DAYS.items()}},
    "state_footprint": {"2025": {
        "lived": [{"state": "CA", "start": "2025-01-01", "end": "2025-12-31", "provenance": _USER}],
        "worked": [{"state": "CA", "start": "2025-01-01", "end": "2025-12-31", "provenance": _USER}]}},
}
J2_EXPECTED_PATHS = [
    ("residency for 2025", "pack"),
    ("U.S.-China treaty on student wages", "pack"),
    ("estimate the refund (1040-NR rules)", "pack"),
    ("tax on taxable income (1040-NR line 16)", "pack"),
    ("find the 1040-NR, Schedule OI and 8843 packs", "pack"),
    ("scope the state return (California)", "pack"),
    ("filing summary", "pack"),
    ("file and pay", "pack"),
]


async def _journey_2(j: Recorder, fig: dict) -> None:
    res = await j.call("residency for 2025", "pack", "residency", {
        "visa_periods": [{"status": "F-1", "start": J2_ARRIVED.isoformat(), "end": None}],
        "days_by_year": J2_DAYS, "target_year": 2025})
    assert res["classification"] == "nonresident"  # an F-1 student's first five calendar years are exempt years
    assert f"2025: {J2_DAYS['2025']} day(s) present excluded from the SPT" in res["work"]

    treaty = await j.call("U.S.-China treaty on student wages", "pack", "calc", {"op": "treaty_benefit", "args": {
        "country": "china", "income_class": "student_wages", "amount": J2_WAGES, "year": 2025, "resident_alien": False}})
    exempt, taxable_wages = treaty["exempt_amount"], treaty["taxable_remainder"]
    assert 0 < exempt < J2_WAGES and exempt + taxable_wages == J2_WAGES
    assert treaty["article"].startswith("Art. 20") and treaty["citation"]["url"].startswith("https://www.irs.gov/")
    assert "Schedule OI" in treaty["work"] and "line 1k" in treaty["work"]  # where a nonresident reports it

    est = await j.call("estimate the refund (1040-NR rules)", "pack", "estimate_refund", {
        "profile": J2_PROFILE, "year": 2025,
        "income": {"wages": J2_WAGES, "federal_withholding": J2_WITHHELD, "treaty_exempt_income": exempt}})
    ledger = _comp(est)
    assert ledger["treaty_exempt_exclusion"] == -exempt and ledger["agi"] == taxable_wages
    assert ledger["deduction"] == 0  # a nonresident alien takes no standard deduction (itemized only)
    assert ledger["taxable_income"] == taxable_wages
    tax = await j.call("tax on taxable income (1040-NR line 16)", "pack", "calc", {
        "op": "tax", "args": {"taxable_income": taxable_wages, "filing_status": "single", "year": 2025}})
    assert ledger["income_tax"] == tax["tax"]
    refund = J2_WITHHELD - tax["tax"]
    assert est["point"] == ledger["bottom_line"] == refund > 0

    forms = await j.call("find the 1040-NR, Schedule OI and 8843 packs", "pack", "list_forms", {
        "jurisdiction": "federal", "year": 2025})
    status = {f["form_key"]: f["source_status"] for f in forms}
    assert all(status.get(k) == "final" for k in ("f1040nr", "sched_oi", "f8843"))

    scope = await j.call("scope the state return (California)", "pack", "state_scope", {"profile": J2_PROFILE, "year": 2025})
    (ca,) = scope["states"]
    assert (ca["state"], ca["filing_role"], ca["must_file"], ca["forms"]) == ("CA", "resident", True, ["540", "Schedule CA"])
    # California does not follow the federal treaty exclusion: the state taxes the treaty-exempt wages.
    assert any(w.startswith("Treaty conformity — CA does NOT conform") for w in ca["warnings"])

    manifest = [{"form": "1040-NR", "tax_year": 2025, "bottom_line": refund, "attached_forms": ["8843"]}]
    summary = await j.call("filing summary", "pack", "filing_summary", {"manifest": manifest})
    assert summary["items"][0]["headline"].startswith(f"Federal 2025: refund ${refund:,}")
    paid = await j.call("file and pay", "pack", "file_and_pay", {"manifest": manifest})
    ret = paid["returns"][0]
    # Instructions for Form 1040-NR (2025), "Where To File": not enclosing a payment -> Austin, TX 73301-0215.
    assert "Austin, TX 73301-0215" in ret["mailing_address"]
    assert any("Form 8843 is attached" in s and "do NOT sign it separately" in s for s in ret["sign"])
    fig.update(exempt=exempt, taxable=taxable_wages, tax=tax["tax"], refund=refund, article=treaty["article"])


@functools.cache
def _journey_2_run() -> JourneyRun:
    return _run_journey(_journey_2)


def test_journey_2_f1_nonresident_student():
    run = _journey_2_run()
    assert [(s.name, s.path) for s in run.steps] == J2_EXPECTED_PATHS


def _report_failures(report: dict) -> str:
    failed = {k: v["failures"] for k, v in report["sections"].items() if v["failed"]}
    return json.dumps({"sections": failed, "pitfalls": [p for p in report["pitfalls"] if p["status"] == "FAIL"]}, indent=1)


def _journey_2_filled(tmp_path) -> tuple[JourneyRun, dict[str, str]]:
    """Fetch and fill the 1040-NR, Schedule OI and Form 8843 on journey 2's figures; returns the run and the PDFs."""
    fig = _journey_2_run().figures
    for key in ("f1040nr", "sched_oi", "f8843"):
        _need_blank(key, 2025)
    p = J2_PERSON
    ssn_digits = p["ssn"].replace("-", "")
    tax, refund = fig["tax"], fig["refund"]
    nr = {
        "name.first": p["first"], "name.last": p["last"], "identifying_number": ssn_digits,
        "mailing_address.street": p["street"], "mailing_address.apt": p["apt"], "mailing_address.city": p["city"],
        "mailing_address.state": p["state"], "mailing_address.zip": p["zip"],
        "filing_status.single": True, "digital_assets.no": True,
        # Instructions for Form 1040-NR (2025), line 1a, "Amounts Exempt Under a Treaty": treaty-exempt wages are not
        # reported on line 1a (it is reduced by the exempt amount); they go on line 1k with Schedule OI item L.
        "1a": fig["taxable"], "1k": fig["exempt"], "1z": fig["taxable"], "9": fig["taxable"],
        "11a": fig["taxable"], "11b": fig["taxable"], "15": fig["taxable"],
        "16": tax, "18": tax, "22": tax, "24": tax,
        "25a": J2_WITHHELD, "25d": J2_WITHHELD, "33": J2_WITHHELD, "34": refund, "35a": refund,
    }
    oi = {
        "name": f"{p['first']} {p['last']}", "identifying_number": ssn_digits, "a": p["country"], "b": p["country"],
        "c.no": True, "d1.no": True, "d2.no": True, "e": "F-1", "f.no": True,
        **{f"h.{y}": str(d) for y, d in J2_DAYS.items()},
        "i.no": True, "j.no": True, "k.no": True,  # no earlier U.S. income tax return; no trust; under $250,000
        "treaty_1.country": p["country"], "treaty_1.article": fig["article"].split(" ")[1],
        "treaty_1.months_claimed": "0", "treaty_1.exempt_amount": fig["exempt"], "1e": fig["exempt"],
        "l2.no": True, "l3.no": True,
    }
    # The 2025 Form 8843 prints "Fill in your addresses only if you are filing this form by itself and not with your
    # U.S. tax return": attached to the 1040-NR, both address boxes stay blank.
    f8843 = {
        "name.first": p["first"], "name.last": p["last"], "identifying_number": ssn_digits,
        "1a": f"F-1, {J2_ARRIVED:%m/%d/%Y}", "1b": "F-1", "2": p["country"], "3a": p["country"], "3b": "DEMO00000",
        **{f"4a.{y}": str(d) for y, d in J2_DAYS.items()}, "4b": str(J2_DAYS["2025"]),
        "9": p["school"], "10": f"Demo Director, International Programs, {p['school']}",
        "11.2023": "F", "11.2024": "F", "12.no": True, "13.no": True,
    }
    paths = {key: str(tmp_path / f"{key}_2025_journey2.pdf") for key in ("f1040nr", "sched_oi", "f8843")}

    async def body(j: Recorder, _fig: dict) -> None:
        for key, values in (("f1040nr", nr), ("sched_oi", oi), ("f8843", f8843)):
            await j.call(f"fetch the official {key}", "pack", "fetch_blank", {"form": key, "year": 2025})
            filled = await j.call(f"fill {key}", "pack", "fill_form", {
                "form": key, "year": 2025, "values": values, "out_path": paths[key]})
            assert filled["warnings"] == [], filled["warnings"]

    return _run_journey(body), paths


@pytest.mark.network
def test_journey_2_network_fill_and_verify_the_1040nr_filing(tmp_path):
    fill_run, paths = _journey_2_filled(tmp_path)
    assert [s.path for s in fill_run.steps] == ["pack"] * 6
    tax = _journey_2_run().figures["tax"]

    async def body(j: Recorder, _fig: dict) -> None:
        report = await j.call("verify the 1040-NR with Schedule OI", "pack", "verify_filing", {
            "items": [{"form": key, "year": 2025, "pdf_path": paths[key]} for key in ("f1040nr", "sched_oi")],
            "independent": {"f1040nr": {"16": tax}}})
        assert report["ok"] is True, _report_failures(report)
        assert report["sections"]["recompute"]["checked"] == 1 and report["sections"]["recompute"]["failed"] == 0
        assert report["sections"]["cross_form"]["failed"] == 0 and report["sections"]["cross_form"]["checked"] >= 1
        f8843 = await j.call("verify the Form 8843", "pack", "verify_form", {
            "form": "f8843", "year": 2025, "pdf_path": paths["f8843"]})
        assert f8843["ok"] is True, _report_failures(f8843)

    run = _run_journey(body)
    assert [s.path for s in run.steps] == ["pack"] * 2


@pytest.mark.network
@pytest.mark.xfail(strict=True, reason=(
    "verify_filing's identity check (P-002) requires the Form 8843 address box even when the 8843 is attached to the "
    "1040-NR, where the 2025 form itself prints 'Fill in your addresses only if you are filing this form by itself and "
    "not with your U.S. tax return' — it fails the blank box. Remove this mark when the identity check honours it."))
def test_journey_2_network_verify_filing_accepts_the_attached_8843_without_an_address(tmp_path):
    _fill_run, paths = _journey_2_filled(tmp_path)

    async def go():
        async with connect(mcp) as client:
            return _data(await client.call_tool("verify_filing", {
                "items": [{"form": key, "year": 2025, "pdf_path": path} for key, path in paths.items()]}))
    report = asyncio.run(go())
    assert report["ok"] is True, _report_failures(report)


# ── Journey 3 — a part-year mover, Virginia -> California on 2025-07-01 ─────────

J3_MOVED = date(2025, 7, 1)
J3_PERSON = {"first": "Riley", "last": "Example", "ssn": "999-88-0503",
             "street": "20 Sample Street", "city": "Sampleton", "state": "CA", "zip": "90000"}
J3_WAGES, J3_WITHHELD = 85000, 11000  # two Forms W-2: a Virginia employer, then a California one
J3_PROFILE = {
    "household": {"marital_status": {"value": "unmarried", "provenance": _USER},
                  "filing_status": {"value": "single", "provenance": _USER}},
    "identity": {"us_person": {"value": True, "provenance": _USER}},
    "state_footprint": {"2025": {
        "lived": [{"state": "VA", "start": "2025-01-01", "end": "2025-06-30", "provenance": _USER},
                  {"state": "CA", "start": J3_MOVED.isoformat(), "end": "2025-12-31", "provenance": _USER}],
        "worked": [{"state": "VA", "start": "2025-01-01", "end": "2025-06-30", "provenance": _USER},
                   {"state": "CA", "start": J3_MOVED.isoformat(), "end": "2025-12-31", "provenance": _USER}]}},
}
J3_EXPECTED_PATHS = [
    ("scope the state returns", "pack"),
    ("federal AGI", "pack"),
    ("find the California part-year packs", "pack"),
    ("California Form 540NR line map", "pack"),
    ("California tax base (540NR lines 18-19)", "pack"),
    ("Virginia Form 760PY line map", "refusal"),
    ("fill Virginia Form 760PY", "refusal"),
    ("Virginia Form 760PY: where it is", "pointer"),
]


async def _journey_3(j: Recorder, fig: dict) -> None:
    scope = await j.call("scope the state returns", "pack", "state_scope", {"profile": J3_PROFILE, "year": 2025})
    by_state = {s["state"]: s for s in scope["states"]}
    assert sorted(by_state) == ["CA", "VA"]
    assert all(s["filing_role"] == "part_year" and s["must_file"] for s in by_state.values())
    assert by_state["CA"]["forms"] == ["540NR", "Schedule CA"]
    (va_form,) = by_state["VA"]["forms"]
    assert "Form 760PY" in va_form  # the part-year form Virginia names; no pack fills it (below)

    est = await j.call("federal AGI", "pack", "estimate_refund", {
        "profile": J3_PROFILE, "year": 2025, "income": {"wages": J3_WAGES, "federal_withholding": J3_WITHHELD}})
    agi = _comp(est)["agi"]
    assert agi == J3_WAGES

    ca_forms = await j.call("find the California part-year packs", "pack", "list_forms", {
        "jurisdiction": "states/ca", "year": 2025})
    assert {f["form_key"]: f["source_status"] for f in ca_forms if f["form_key"].endswith("540nr")} == {
        "form540nr": "final", "sched_ca_540nr": "final"}
    fm = await j.call("California Form 540NR line map", "pack", "get_form_map", {
        "form": "form540nr", "year": 2025, "jurisdiction": "states/ca"})
    assert "19 == max(0, 17 - 18)" in fm["relations"] and {"13", "17", "18", "19"} <= {ln["line"] for ln in fm["lines"]}

    # 540NR line 17 (AGI from all sources) = federal AGI here (no California adjustments); calc subtracts the
    # California standard deduction (line 18) to reach line 19, the total taxable income.
    ca = await j.call("California tax base (540NR lines 18-19)", "pack", "calc", {"op": "state_tax", "args": {
        "state": "ca", "taxable_base": agi, "filing_status": "single", "year": 2025}})
    ca_std = agi - ca["base_after_exemptions"]
    assert ca_std > 0 and ca["citation"]["url"].startswith("https://www.ftb.ca.gov/")
    assert f"standard deduction [single] = ${ca_std:,}" in ca["work"]

    refused = await j.call("Virginia Form 760PY line map", "refusal", "get_form_map", {
        "form": "va760py", "year": 2025, "jurisdiction": "states/va"})
    assert "Available form keys for states/va 2025: ['va760']" in refused
    await j.call("fill Virginia Form 760PY", "refusal", "fill_form", {
        "form": "va760py", "year": 2025, "jurisdiction": "states/va", "values": {},
        "out_path": str(Path(tempfile.mkdtemp(prefix="journey3-")) / "unused.pdf")})
    pointer = j.record("Virginia Form 760PY: where it is", "pointer", "state_scope", by_state["VA"])
    # The entry names Form 760PY and cites Virginia's own site, but only the RESIDENT Form 760 instructions (strict xfail
    # test_journey_3_the_760py_pointer_cites_the_760py_instructions below; Phase K JK27).
    assert all(c["url"].startswith("https://www.tax.virginia.gov/") for c in pointer["citations"]) and pointer["citations"]
    fig.update(agi=agi, ca_std=ca_std, ca_taxable=ca["base_after_exemptions"])


@functools.cache
def _journey_3_run() -> JourneyRun:
    return _run_journey(_journey_3)


@pytest.mark.xfail(strict=True, reason=(
    "Virginia's state_scope entry names Form 760PY but cites only the resident Form 760 instructions, so a part-year "
    "filer gets no pointer to the 760PY form or its instructions. Remove this mark when knowledge/states/va cites the "
    "760PY instructions (Phase K JK27)."))
def test_journey_3_the_760py_pointer_cites_the_760py_instructions():
    pointer = next(s for s in _journey_3_run().steps if s.name == "Virginia Form 760PY: where it is").output
    assert any("760py" in json.dumps(c).lower() for c in pointer["citations"])


def test_journey_3_part_year_mover():
    run = _journey_3_run()
    assert [(s.name, s.path) for s in run.steps] == J3_EXPECTED_PATHS


@pytest.mark.network
def test_journey_3_network_fill_and_verify_the_540nr(tmp_path):
    fig = _journey_3_run().figures
    _need_blank("form540nr", 2025, "states/ca")
    p = J3_PERSON
    values = {
        "name.first": p["first"], "name.last": p["last"], "identifying_number": p["ssn"],
        "mailing_address.street": p["street"], "mailing_address.city": p["city"],
        "mailing_address.state": p["state"], "mailing_address.zip": p["zip"], "filing_status.single": True,
        "13": fig["agi"], "15": fig["agi"], "17": fig["agi"], "18": fig["ca_std"], "19": fig["ca_taxable"],
    }
    out = str(tmp_path / "form540nr_2025_journey3.pdf")

    async def body(j: Recorder, _fig: dict) -> None:
        await j.call("fetch the official 540NR", "pack", "fetch_blank", {
            "form": "form540nr", "year": 2025, "jurisdiction": "states/ca"})
        filled = await j.call("fill the 540NR", "pack", "fill_form", {
            "form": "form540nr", "year": 2025, "jurisdiction": "states/ca", "values": values, "out_path": out})
        assert filled["warnings"] == [], filled["warnings"]
        report = await j.call("verify the 540NR", "pack", "verify_form", {
            "form": "form540nr", "year": 2025, "jurisdiction": "states/ca", "pdf_path": out,
            "expected": {k: v for k, v in values.items() if isinstance(v, int) and not isinstance(v, bool)}})
        assert report["ok"] is True, report

    run = _run_journey(body)
    assert [s.path for s in run.steps] == ["pack"] * 3


# ── Journey 4 — a city-tax filer: an Ohio taxing-school-district resident ──────

J4_PROFILE = {
    "household": {"marital_status": {"value": "unmarried", "provenance": _USER},
                  "filing_status": {"value": "single", "provenance": _USER}},
    "identity": {"us_person": {"value": True, "provenance": _USER}},
    "state_footprint": {"2025": {
        "lived": [{"state": "OH", "start": "2025-01-01", "end": "2025-12-31", "provenance": _USER}],
        "worked": [{"state": "OH", "start": "2025-01-01", "end": "2025-12-31", "provenance": _USER}]}},
}
J4_OHIO_AGI = 60000  # Ohio IT 1040 line 3 (federal AGI from wages; no Ohio adjustments)
J4_EXEMPTION = 2150  # IT 1040 line 4, one exemption at MAGI $40,001-$80,000 — held below to the calc op's own text
J4_EXPECTED_PATHS = [
    ("scope the state return", "pack"),
    ("find the Ohio packs", "pack"),
    ("Ohio IT 1040 line 8a tax", "pack"),
    ("school district tax (SD 100): where it is computed", "pointer"),
    ("school district SD 100 line map", "refusal"),
    ("school district SD 100 worksheet", "refusal"),
]


async def _journey_4(j: Recorder, fig: dict) -> None:
    scope = await j.call("scope the state return", "pack", "state_scope", {"profile": J4_PROFILE, "year": 2025})
    (oh,) = scope["states"]
    assert (oh["state"], oh["filing_role"], oh["must_file"]) == ("OH", "resident", True)
    assert oh["forms"][0].startswith("Ohio IT 1040")

    oh_forms = await j.call("find the Ohio packs", "pack", "list_forms", {"jurisdiction": "states/oh", "year": 2025})
    assert [(f["form_key"], f["source_status"]) for f in oh_forms] == [("it1040_oh", "final")]  # no SD 100 pack

    line7 = J4_OHIO_AGI - J4_EXEMPTION
    tax = await j.call("Ohio IT 1040 line 8a tax", "pack", "calc", {"op": "state_tax", "args": {
        "state": "oh", "taxable_base": line7, "filing_status": "single", "year": 2025}})
    work = tax["work"]
    assert f"${J4_EXEMPTION:,} if MAGI is $40,001-$80,000" in work  # the exemption used above, in the op's own words
    assert tax["tax"] > 0 and f"-> ${tax['tax']:,}" in work
    # The op computes the state line and says the school district tax is NOT modeled: the pointer below.
    assert re.search(r"school district income tax \(form SD 100\)[^.]*not modeled", work, re.IGNORECASE)

    sources = await j.call("school district tax (SD 100): where it is computed", "pointer", "get_sources", {
        "topic": "school district income tax", "year": 2025, "jurisdiction": "states/oh"})
    assert sources["matched"] is True
    assert any("ohio.gov/" in s["url"] and "SD 100" in s["answers"] for s in sources["sources"])

    refused = await j.call("school district SD 100 line map", "refusal", "get_form_map", {
        "form": "sd100", "year": 2025, "jurisdiction": "states/oh"})
    assert "Available form keys for states/oh 2025: ['it1040_oh']" in refused
    await j.call("school district SD 100 worksheet", "refusal", "hand_fill_worksheet", {
        "form": "sd100", "year": 2025, "jurisdiction": "states/oh"})
    fig.update(line7=line7, tax=tax["tax"])


@functools.cache
def _journey_4_run() -> JourneyRun:
    return _run_journey(_journey_4)


def test_journey_4_city_tax_filer():
    run = _journey_4_run()
    assert [(s.name, s.path) for s in run.steps] == J4_EXPECTED_PATHS


# ── Journey 5 — an amended prior-year return (TY2024 Form 1040-X, Georgia) ─────

J5_PERSON = {"first": "Morgan", "last": "Example", "ssn": "999-88-0505",
             "street": "10 Sample Street", "city": "Exampleville", "state": "GA", "zip": "30000"}
J5_WAGES, J5_WITHHELD, J5_MISSED_INTEREST = 72000, 9000, 1200  # a Form 1099-INT left off the original return
J5_PROFILE = {
    "household": {"marital_status": {"value": "unmarried", "provenance": _USER},
                  "filing_status": {"value": "single", "provenance": _USER}},
    "identity": {"us_person": {"value": True, "provenance": _USER}},
    "state_footprint": {"2024": {
        "lived": [{"state": "GA", "start": "2024-01-01", "end": "2024-12-31", "provenance": _USER}],
        "worked": [{"state": "GA", "start": "2024-01-01", "end": "2024-12-31", "provenance": _USER}]}},
}
J5_EXPECTED_PATHS = [
    ("scope the 2024 state return", "pack"),
    ("2024 as originally filed", "pack"),
    ("2024 as corrected", "pack"),
    ("2024 standard deduction", "pack"),
    ("2024 tax, original", "pack"),
    ("2024 tax, corrected", "pack"),
    ("find the 2024 Form 1040-X pack", "pack"),
    ("Form 1040-X line map", "pack"),
    ("Georgia tax, original", "pack"),
    ("Georgia tax, corrected", "pack"),
    ("Georgia Form 500X line map", "refusal"),
    ("Georgia Form 500X: where it goes", "pointer"),
]


async def _journey_5(j: Recorder, fig: dict) -> None:
    scope = await j.call("scope the 2024 state return", "pack", "state_scope", {"profile": J5_PROFILE, "year": 2024})
    (ga,) = scope["states"]
    assert (ga["state"], ga["filing_role"], ga["must_file"]) == ("GA", "resident", True)
    assert ga["forms"][0].startswith("Form 500 ")

    original = await j.call("2024 as originally filed", "pack", "estimate_refund", {
        "profile": J5_PROFILE, "year": 2024, "income": {"wages": J5_WAGES, "federal_withholding": J5_WITHHELD}})
    corrected = await j.call("2024 as corrected", "pack", "estimate_refund", {
        "profile": J5_PROFILE, "year": 2024,
        "income": {"wages": J5_WAGES, "interest": J5_MISSED_INTEREST, "federal_withholding": J5_WITHHELD}})
    lo, lc = _comp(original), _comp(corrected)
    assert (lo["agi"], lc["agi"]) == (J5_WAGES, J5_WAGES + J5_MISSED_INTEREST)

    std = await j.call("2024 standard deduction", "pack", "calc", {
        "op": "standard_deduction", "args": {"filing_status": "single", "year": 2024}})
    taxable_o, taxable_c = lo["agi"] - std["amount"], lc["agi"] - std["amount"]
    tax_o = await j.call("2024 tax, original", "pack", "calc", {
        "op": "tax", "args": {"taxable_income": taxable_o, "filing_status": "single", "year": 2024}})
    tax_c = await j.call("2024 tax, corrected", "pack", "calc", {
        "op": "tax", "args": {"taxable_income": taxable_c, "filing_status": "single", "year": 2024}})
    assert (lo["deduction"], lc["deduction"]) == (-std["amount"], -std["amount"])
    assert (lo["taxable_income"], lc["taxable_income"]) == (taxable_o, taxable_c)
    assert (lo["income_tax"], lc["income_tax"]) == (tax_o["tax"], tax_c["tax"])

    forms = await j.call("find the 2024 Form 1040-X pack", "pack", "list_forms", {"jurisdiction": "federal", "year": 2024})
    assert next(f for f in forms if f["form_key"] == "f1040x")["source_status"] == "final"
    fm = await j.call("Form 1040-X line map", "pack", "get_form_map", {"form": "f1040x", "year": 2024})
    assert {"19 == 17 - 18", "20 == max(0, 11 - 19)"} <= set(fm["relations"])
    # Form 1040-X, column C: line 18 is the original return's overpayment (refunded), line 19 = 17 - 18, line 20 the
    # amount owed — which is exactly the corrected tax minus the original tax, and the two estimates' difference.
    overpaid_original = J5_WITHHELD - tax_o["tax"]
    line19 = J5_WITHHELD - overpaid_original
    line20 = max(0, tax_c["tax"] - line19)
    assert line20 == tax_c["tax"] - tax_o["tax"] == original["point"] - corrected["point"] > 0

    ga_o = await j.call("Georgia tax, original", "pack", "calc", {"op": "state_tax", "args": {
        "state": "ga", "taxable_base": lo["agi"], "filing_status": "single", "year": 2024}})
    ga_c = await j.call("Georgia tax, corrected", "pack", "calc", {"op": "state_tax", "args": {
        "state": "ga", "taxable_base": lc["agi"], "filing_status": "single", "year": 2024}})
    assert ga_o["rate"] == ga_c["rate"] and ga_c["base_after_exemptions"] - ga_o["base_after_exemptions"] == J5_MISSED_INTEREST
    ga_more = ga_c["tax"] - ga_o["tax"]
    assert ga_more > 0

    refused = await j.call("Georgia Form 500X line map", "refusal", "get_form_map", {
        "form": "ga500x", "year": 2024, "jurisdiction": "states/ga"})
    assert "Available form keys for states/ga 2024: ['ga500']" in refused
    paid = await j.call("Georgia Form 500X: where it goes", "pointer", "file_and_pay", {"manifest": [
        {"form": "500X", "tax_year": 2024, "jurisdiction": "states/ga", "bottom_line": -ga_more}]})
    ret = paid["returns"][0]
    # Scoped on purpose: this proves only that the answer carries the IT-511's 500X box. It leads with the Form 500
    # address and the original due date instead (strict xfail test_journey_5_file_and_pay_routes_the_500x_as_an_amendment).
    assert "Form 500X amended: PO BOX 740318" in ret["mailing_address"]
    assert any("2024-it-511" in c["url"] and c["url"].startswith("https://dor.georgia.gov/") for c in ret["citations"])
    fig.update(std=std["amount"], taxable_o=taxable_o, taxable_c=taxable_c, tax_o=tax_o["tax"], tax_c=tax_c["tax"],
               overpaid_original=overpaid_original, line19=line19, line20=line20, ga_more=ga_more)


@functools.cache
def _journey_5_run() -> JourneyRun:
    return _run_journey(_journey_5)


def test_journey_5_amended_prior_year_return():
    run = _journey_5_run()
    assert [(s.name, s.path) for s in run.steps] == J5_EXPECTED_PATHS


@pytest.mark.xfail(strict=True, reason=(
    "file_and_pay has no Form 1040-X model: it prices a 1040-X as a Form 1040 and returns the 1040 address "
    "(Charlotte, NC for a Georgia balance due). Instructions for Form 1040-X (Rev. December 2025), Where To File: "
    "a Georgia resident mails Form 1040-X to Austin, TX 73301-0052. Remove this mark when file_and_pay learns 1040-X."))
def test_journey_5_file_and_pay_sends_the_1040x_to_the_1040x_address():
    owed = _journey_5_run().figures["line20"]

    async def go():
        async with connect(mcp) as client:
            return _data(await client.call_tool("file_and_pay", {"manifest": [
                {"form": "1040-X", "tax_year": 2024, "bottom_line": -owed, "state": "GA"}]}))
    assert "Austin, TX 73301-0052" in asyncio.run(go())["returns"][0]["mailing_address"]


@pytest.mark.xfail(strict=True, reason=(
    "file_and_pay has no state amended-return model either: for a Georgia Form 500X balance due it leads with the "
    "Form 500 payment address (PO BOX 740399), gives the original return's due date and names the 525-TV voucher; "
    "the 500X box (PO BOX 740318) appears only as a trailing note. Remove this mark when file_and_pay learns amended "
    "state returns (Phase K JK27)."))
def test_journey_5_file_and_pay_routes_the_500x_as_an_amendment():
    ret = next(s for s in _journey_5_run().steps if s.name == "Georgia Form 500X: where it goes").output["returns"][0]
    assert "740399" not in ret["mailing_address"]
    assert "2025-04-15" not in json.dumps(ret.get("deadlines"))


@pytest.mark.network
def test_journey_5_network_fill_and_verify_the_1040x(tmp_path):
    fig = _journey_5_run().figures
    _need_blank("f1040x", 2024)
    p = J5_PERSON
    o_agi, c_agi = J5_WAGES, J5_WAGES + J5_MISSED_INTEREST
    tax_o, tax_c = fig["tax_o"], fig["tax_c"]
    values = {
        "amended_year": "2024", "name.first": p["first"], "name.last": p["last"],
        "identifying_number": p["ssn"].replace("-", ""),
        "mailing_address.street": p["street"], "mailing_address.city": p["city"],
        "mailing_address.state": p["state"], "mailing_address.zip": p["zip"], "filing_status.single": True,
        "1.original": o_agi, "1.net_change": c_agi - o_agi, "1": c_agi,
        "2.original": fig["std"], "2": fig["std"],
        "3.original": fig["taxable_o"], "3.net_change": fig["taxable_c"] - fig["taxable_o"], "3": fig["taxable_c"],
        "5.original": fig["taxable_o"], "5.net_change": fig["taxable_c"] - fig["taxable_o"], "5": fig["taxable_c"],
        "6.original": tax_o, "6.net_change": tax_c - tax_o, "6": tax_c,
        "8.original": tax_o, "8.net_change": tax_c - tax_o, "8": tax_c,
        "11.original": tax_o, "11.net_change": tax_c - tax_o, "11": tax_c,
        "12.original": J5_WITHHELD, "12": J5_WITHHELD,
        "17": J5_WITHHELD, "18": fig["overpaid_original"], "19": fig["line19"], "20": fig["line20"],
        "explanation": f"Line 1: a Form 1099-INT reporting ${J5_MISSED_INTEREST:,} of interest was left off the "
                       f"original 2024 return.",
    }
    out = str(tmp_path / "f1040x_2024_journey5.pdf")

    async def body(j: Recorder, _fig: dict) -> None:
        await j.call("fetch the official Form 1040-X", "pack", "fetch_blank", {"form": "f1040x", "year": 2024})
        filled = await j.call("fill the Form 1040-X", "pack", "fill_form", {
            "form": "f1040x", "year": 2024, "values": values, "out_path": out})
        assert filled["warnings"] == [], filled["warnings"]
        report = await j.call("verify the Form 1040-X", "pack", "verify_form", {
            "form": "f1040x", "year": 2024, "pdf_path": out,
            "expected": {k: v for k, v in values.items() if isinstance(v, int) and not isinstance(v, bool)},
            "independent": {"6": tax_c}})
        assert report["ok"] is True, report
        assert report["sections"]["recompute"]["checked"] == 1 and report["sections"]["recompute"]["failed"] == 0

    run = _run_journey(body)
    assert [s.path for s in run.steps] == ["pack"] * 3


# ── the guard, across every journey ──────────────────────────────────────────

JOURNEYS = {
    "1_w2_employee": _journey_1_run,
    "2_f1_nonresident_student": _journey_2_run,
    "3_part_year_mover": _journey_3_run,
    "4_city_tax_filer": _journey_4_run,
    "5_amended_prior_year": _journey_5_run,
}


@pytest.mark.parametrize("journey", sorted(JOURNEYS))
def test_no_fallback_pointer_or_refusal_step_claims_filing_grade(journey):
    steps = JOURNEYS[journey]().steps
    for step in steps:
        _check_step(step)
    if journey[0] in "345":  # the honest non-pack step is the point of journeys 3-5 today (JK18 upgrades them)
        assert {s.path for s in steps} & {"pointer", "refusal", "fallback"}, f"journey {journey} has no non-pack step"
    assert all(s.path != "fallback" for s in steps)  # JK16-JK18 have not landed: no step may claim the fallback yet


@pytest.mark.parametrize("planted", [
    {"grade": "filing"},
    {"grade": "filing_grade"},
    {"filing_grade": True},
    {"status": "final"},
    {"source_status": "final"},
    {"result": {"note": "This draft is filing-grade."}},
    ["Ready to file: sign and mail it."],
    "a FILING GRADE draft",
    "Not a draft, this is filing-grade.",       # the negator must sit right before the claim
    "No edits needed, it is filing-grade.",
    "Ready for filing.",
    "This return is final: sign and mail it.",
    {"FilingGrade": True},                      # keys are normalized before matching
    {"filing-grade": True},
])
def test_the_guard_catches_a_planted_claim(planted):
    assert _filing_grade_claims(planted)
    with pytest.raises(AssertionError, match="claims filing-grade"):
        _check_step(Step("planted", "fill_form", "pointer",
                         {"payload": planted, "source": "https://www.irs.gov/forms-pubs"}, False))


@pytest.mark.parametrize("honest", [
    {"grade": "unmapped_draft", "stamp": "UNMAPPED DRAFT — NOT FILING-GRADE"},
    "Unmapped output is never filing-grade.",
    "This draft is not ready to file.",
    {"status": "unverified_draft"},
])
def test_the_guard_passes_an_honest_label(honest):
    assert _filing_grade_claims(honest) == []


def test_a_pack_step_that_carries_the_unmapped_grade_fails():
    with pytest.raises(AssertionError, match="unmapped_draft"):
        _check_step(Step("mislabelled", "fill_form", "pack", {"result": {"grade": "unmapped_draft"}}, False))
