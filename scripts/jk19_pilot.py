#!/usr/bin/env python
"""The JK19 pilot: five long-tail forms and one refusal case through the no-pack fallback (Phase K JK19, 2026-10-25).

Each form runs through the four tools that take ``form="unmapped"`` (ADR-0002) the way an agent following Recipe U
calls them, in-process over the MCP protocol (the SDK's in-memory client, as packages/mcp-server/tests/
test_unmapped_tools.py does), against the agency's live blank (network):

    fetch_blank -> get_form_map -> render_form(sweep) -> fill_form -> verify_form -> render_form(every page)

The pilot is in two stages because an agent must LOOK at the sweep page before the user confirms a box (KG11):

* ``--stage map``  fetches, maps and renders the sweep pages, and writes ``fields.txt`` (one line per field: index,
  name, kind, refusal, confidence, page, printed line, label) for the reviewer to read beside the sweep images;
* ``--stage fill`` fills with the form's DEMO values and the boxes the reviewer confirmed on the sweep (``PLAN``
  below, decided by looking at the rendered sweep pages), verifies, and renders every page of the draft;
* ``--stage all`` (the default) runs both.

Everything goes under ``--out`` (a scratch directory, never the repo): the blank cache (``TAXFILL_BLANKS_CACHE``) and
the workspace (``TAXFILL_WORKSPACE``) are pointed there before the server is imported, and each form's
``record.json``, sweep and draft PNGs land in ``<out>/<slot>/``. Renders hold only demo values, but they stay out of
git (docs/dev/JK19-PILOT.md records what they showed).

Demo values only (KG10): fictitious names, 999-88-xxxx identifiers, "Example" addresses. No form here is promoted to
filing-grade: every draft is an UNMAPPED DRAFT — NOT FILING-GRADE.

Usage:
    uv run python scripts/jk19_pilot.py --out /path/to/scratch [--only city,federal,...] [--stage map|fill|all]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for _src in (REPO / "packages" / "core" / "src", REPO / "packages" / "mcp-server" / "src"):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

# ── the pilot set (Phase K JK19, 2026-10-25): one form per ROADMAP slot, each with no shipped pack for its year ─────
# "city_gr" is the first city candidate, kept because its refusal is pilot data (a scanned page 6, rule 9). The
# refusal case's local_blank run ("refusal_ma_local") is added by --ma-local-blank: a copy of the form the user saved.

FORMS: dict[str, dict[str, Any]] = {
    "city": {
        "what": "City of Philadelphia School Income Tax (SIT) return, TY2023 (phila.gov; a municipal tax on unearned "
                "income)",
        "jurisdiction": "states/pa", "year": 2023, "form_title": "School Income Tax",
        "source_url": "https://www.phila.gov/media/20240102133536/2023-School-Income-Tax-return.pdf",
    },
    "city_gr": {
        "what": "City of Grand Rapids (MI) GR-1040PR, part-year resident individual return, TY2025 (refused)",
        "jurisdiction": "states/mi", "year": 2025, "form_title": "GR-1040PR",
        "source_url": "https://www.grandrapidsmi.gov/media/zrqn423z/2025-part-year-fillable-form-revised.pdf",
    },
    "federal": {
        "what": "Schedule H (Form 1040), Household Employment Taxes, TY2025 (irs-pdf final)",
        "jurisdiction": "federal", "year": 2025, "form_title": "SCHEDULE H",
        "source_url": "https://www.irs.gov/pub/irs-pdf/f1040sh.pdf",
    },
    "ct_nrpy": {
        "what": "Connecticut CT-1040NR/PY, nonresident and part-year resident return, TY2025",
        "jurisdiction": "states/ct", "year": 2025, "form_title": "CT-1040NR/PY",
        "source_url": "https://portal.ct.gov/-/media/drs/forms/2025/income/ct-1040nrpy_1225.pdf",
    },
    "ty2023": {
        "what": "Oregon Form OR-40-N, nonresident individual income tax return, TY2023",
        "jurisdiction": "states/or", "year": 2023, "form_title": "OR-40-N",
        "source_url": "https://www.oregon.gov/dor/forms/FormsPubs/form-or-40-n_101-048_2023.pdf",
    },
    "ty2025": {
        "what": "Wisconsin Form 1NPR, nonresident and part-year resident return, TY2025 (WI is not tier-1)",
        "jurisdiction": "states/wi", "year": 2025, "form_title": "1NPR",
        "source_url": "https://www.revenue.wi.gov/TaxForms2025/2025-Form1NPRf.pdf",
    },
    "refusal_ma": {
        "what": "Massachusetts Form 1, resident return, TY2024 (the refusal case: mass.gov answers 403 to scripts)",
        "jurisdiction": "states/ma", "year": 2024, "form_title": "Form 1",
        "source_url": "https://www.mass.gov/doc/2024-form-1-massachusetts-resident-income-tax-return/download",
    },
}

# What the reviewer decided per form after looking at its rendered sweep pages (demo values only):
# ``confirmed_fields`` are the fields whose numbered boxes the sweep showed in the box their printed line or caption
# names, and ``values`` cover the lines a filer of that form fills. A value whose
# field get_form_map refuses (custom_format_script, unanchored, read_only, ...) is passed anyway when a filer of the
# form would fill that line, to record that it comes back in hand_write.
_H1 = "topmostSubform[0].Page1[0]."
_H2 = "topmostSubform[0].Page2[0]."
PLAN: dict[str, dict[str, Any]] = {
    "city": {  # a full-year resident with dividends and interest; line 12 is the printed rate (.037500) x line 11
        "values": {"SSN": "999-88-1023", "First Name": "Avery", "Last Name": "Example",
                   "Street Address": "100 Example Street", "City": "Philadelphia", "State": "PA",
                   "Zip/Postal Code": "19107", "Line1": 1250, "Line2": 300, "Line9": 1550, "Line10": 0,
                   "Line11": 1550, "Line12": "58.13", "Line14": "58.13"},
        "money_fields": ["Line1", "Line2", "Line9", "Line10", "Line11"],
        "confirmed_fields": ["SSN", "First Name", "Last Name", "Street Address", "City", "State", "Zip/Postal Code"],
        "provenance": {"Line1": "from a document", "Line2": "from a document"},
        "declared_relations": ["Line9 == Line1 + Line2", "Line11 == Line9 - Line10"],
    },
    "federal": {  # one household employee paid $30,000 cash wages; one state's unemployment fund (Section A)
        "values": {_H1 + "f1_1[0]": "Jordan Example", _H1 + "f1_2[0]": "999-88-2045",
                   _H1 + "CombField[0].f1_3[0]": "998812345", _H1 + "c1_1[0]": "yes",
                   _H1 + "f1_4[0]": 30000, _H1 + "f1_5[0]": 3720, _H1 + "f1_6[0]": 30000, _H1 + "f1_7[0]": 870,
                   _H1 + "f1_11[0]": 4590, _H1 + "c1_4[0]": "yes",
                   _H2 + "Line10[0].c2_1[0]": "yes", _H2 + "c2_2[0]": "yes", _H2 + "c2_3[0]": "yes",
                   _H2 + "f2_1[0]": "Michigan", _H2 + "f2_2[0]": 420, _H2 + "f2_3[0]": 7000, _H2 + "f2_4[0]": 42,
                   _H2 + "f2_31[0]": 4590, _H2 + "f2_32[0]": 4632, _H2 + "c2_5[0]": "yes"},
        "money_fields": [_H1 + n for n in ("f1_4[0]", "f1_5[0]", "f1_6[0]", "f1_7[0]", "f1_11[0]")]
        + [_H2 + n for n in ("f2_2[0]", "f2_3[0]", "f2_4[0]", "f2_31[0]", "f2_32[0]")],
        "confirmed_fields": [_H1 + "f1_1[0]", _H1 + "f1_2[0]", _H1 + "CombField[0].f1_3[0]", _H1 + "c1_1[0]",
                             _H2 + "Line10[0].c2_1[0]", _H2 + "c2_2[0]", _H2 + "c2_3[0]", _H2 + "f2_1[0]",
                             _H2 + "c2_5[0]"],
        "declared_relations": [
            "{%sf1_5[0]} == {%sf1_4[0]} * 0.124" % (_H1, _H1),
            "{%sf1_11[0]} == {%sf1_5[0]} + {%sf1_7[0]}" % (_H1, _H1, _H1),
            "{%sf2_32[0]} == {%sf2_4[0]} + {%sf2_31[0]}" % (_H2, _H2, _H2),
        ],
    },
    "ct_nrpy": {  # a flat blank: values keyed by the printed line as the agent reads it (worksheet only)
        "values": {"Your first name": "Morgan", "Last name": "Example", "1": 90000, "2": 0, "3": 90000, "4": 0,
                   "5": 90000, "6": 30000, "7": 90000},
        "money_fields": ["1", "2", "3", "4", "5", "6", "7"],
    },
    "ty2023": {  # a Washington resident with Oregon wages; Oregon's name and address boxes carry an uppercase script
        "values": {"or-40-n-p1-13": "TAYLOR", "or-40-n-p1-16": "EXAMPLE", "or-40-n-p1-15": "01/15/1990",
                   "or-40-n-p1-17": "999-88-3023", "or-40-n-p1-29": "100 EXAMPLE AVE", "or-40-n-p1-30": "VANCOUVER",
                   "or-40-n-p1-31": "WA", "or-40-n-p1-32a": "98660", "Check Box3": "yes",
                   "or-40-n-p2-1": "1", "or-40-n-p2-33": "1",
                   "or-40-n-p3-1": 48000, "or-40-n-p3-2": 12000, "or-40-n-p3-3": 150,
                   "or-40-n-p4-9": 48150, "or-40-n-p4-10": 12000, "or-40-n-p8-2": 540},
        "money_fields": ["or-40-n-p3-1", "or-40-n-p3-2", "or-40-n-p3-3", "or-40-n-p4-9", "or-40-n-p4-10",
                         "or-40-n-p8-2"],
        "confirmed_fields": ["or-40-n-p1-15", "or-40-n-p1-17", "or-40-n-p1-32a", "Check Box3", "or-40-n-p3-1",
                             "or-40-n-p3-2", "or-40-n-p3-3", "or-40-n-p4-9", "or-40-n-p4-10"],
        "declared_relations": ["{or-40-n-p4-9} == {or-40-n-p3-1} + {or-40-n-p3-3}"],
    },
    "refusal_ma_local": {  # the refusal case's local_blank route; 63 of MA's dollar boxes carry a minus-strip script
        "values": {"fname": "Casey", "lname": "Example", "SSN": "999881024", "madd": "300 Example Lane",
                   "city": "Worcester", "state": "MA", "zip": "01608", "filing status": "/Single",
                   "res2a": 4400, "res3": 52000, "res18": 4400},
        "money_fields": ["res2a", "res3", "res18"],
        "confirmed_fields": ["fname", "lname", "SSN", "madd", "city", "state", "zip", "filing status"],
    },
    "ty2025": {  # a Minnesota resident with Wisconsin wages
        "values": {"lname": "Example", "fname": "Riley", "ss3": "999", "ss2": "88", "ss4": "5025",
                   "address": "200 Example Road", "city": "Duluth", "state": "MN", "zip": "55802",
                   "status": "single", "resident1": "non", "residenceST": "MN",
                   "1a": 60000, "1b": 15000, "2a": 200, "2b": 0, "16a": 60200, "16b": 15000, "30": 15000,
                   "31": 60200},
        "money_fields": ["1a", "1b", "2a", "2b", "16a", "16b", "30", "31"],
        "confirmed_fields": ["lname", "fname", "ss3", "ss2", "ss4", "address", "city", "zip", "status", "1a", "1b",
                             "2a", "2b", "16a", "16b", "30"],
        "declared_relations": ["{16a} == {1a} + {2a}", "{16b} == {1b} + {2b}", "{31} == {16a}"],
    },
}


# ── the MCP client (the protocol path an agent's client takes) ─────────────────


async def _session_call(name: str, args: dict):
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    import taxfill_mcp.server as server

    async with connect(server.mcp) as client:
        return await client.call_tool(name, args)


class ToolError(Exception):
    pass


def call(name: str, args: dict) -> Any:
    result = asyncio.run(_session_call(name, args))
    if result.isError:
        raise ToolError("\n".join(getattr(b, "text", "") for b in result.content))
    if result.structuredContent is not None:
        sc = result.structuredContent
        return sc.get("result", sc)
    return json.loads(result.content[0].text)


def render(pdf: str, out_dir: Path, prefix: str, pages: list[int] | None = None, dpi: float = 110) -> list[str]:
    """render_form over MCP; the returned images are saved as PNGs for the reviewer to look at."""
    from mcp.types import ImageContent

    args: dict[str, Any] = {"pdf_path": pdf, "dpi": dpi}
    if pages:
        args["pages"] = pages
    result = asyncio.run(_session_call("render_form", args))
    if result.isError:
        raise ToolError("\n".join(getattr(b, "text", "") for b in result.content))
    images = [b for b in result.content if isinstance(b, ImageContent)]
    names = []
    for i, img in enumerate(images):
        page = pages[i] if pages else i + 1
        path = out_dir / f"{prefix}-p{page:02d}.png"
        path.write_bytes(base64.b64decode(img.data))
        names.append(path.name)
    return names


# ── one form ───────────────────────────────────────────────────────────────────


def _timed(record: dict, step: str, fn, *a, **k):
    t0 = time.monotonic()
    try:
        return fn(*a, **k)
    finally:
        record.setdefault("seconds", {})[step] = round(time.monotonic() - t0, 2)


def _ids(spec: dict, sha: str) -> dict:
    return {"form": "unmapped", "year": spec["year"], "jurisdiction": spec["jurisdiction"],
            "source_url": spec["source_url"], "blank_sha256": sha}


def stage_map(slot: str, spec: dict, out: Path) -> dict:
    d = out / slot
    d.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"slot": slot, "what": spec["what"], "source_url": spec["source_url"],
                              "jurisdiction": spec["jurisdiction"], "year": spec["year"],
                              "form_title": spec["form_title"]}
    args = {"form": "unmapped", "year": spec["year"], "jurisdiction": spec["jurisdiction"],
            "source_url": spec["source_url"], "form_title": spec["form_title"]}
    if spec.get("local_blank"):
        args["local_blank"] = spec["local_blank"]
    try:
        fetched = _timed(record, "fetch_blank", call, "fetch_blank", args)
    except ToolError as exc:
        record["refused_at"] = "fetch_blank"
        record["refusal"] = str(exc)
        _save(d, record)
        return record
    record["fetch"] = {k: fetched.get(k) for k in ("sha256", "pinned", "origin", "kind", "page_count", "first_page",
                                                   "grade", "next_step")}
    try:
        fmap = _timed(record, "get_form_map", call, "get_form_map", _ids(spec, fetched["sha256"]))
    except ToolError as exc:
        record["refused_at"] = "get_form_map"
        record["refusal"] = str(exc)
        _save(d, record)
        return record
    fields = fmap["fields"]
    record["map"] = {
        "fields": len(fields), "fillable": sum(1 for f in fields if f["fillable"]),
        "needs_confirmation": sum(1 for f in fields if f.get("needs_confirmation")),
        "refusals": dict(Counter(f["refusal"] for f in fields if f["refusal"])),
        "tiers": dict(Counter(f["confidence"] for f in fields)),
        "fillable_tiers": dict(Counter(f["confidence"] for f in fields if f["fillable"])),
        "kinds": dict(Counter(f["kind"] for f in fields)),
        "hand_write": len(fmap["hand_write"]), "anchor_basis": fmap["anchor_basis"].get("table"),
        "sweep_path": fmap["sweep_path"],
    }
    lines = []
    for f in fields:
        w = f["widgets"][0] if f["widgets"] else {"page": None, "anchor": {}}
        a = w["anchor"]
        lines.append(f"#{f['index']:<4} {f['name'][:60]:<60} {f['kind']:<9} {str(f['refusal'] or ''):<20} "
                     f"{f['confidence']:<32} p{w['page']} line={a.get('printed_line')!s:<8} "
                     f"label={(a.get('label') or '')[:70]}")
    (d / "fields.txt").write_text("\n".join(lines) + "\n")
    (d / "fields.json").write_text(json.dumps(fields, indent=1))
    pages = sorted({w["page"] for f in fields for w in f["widgets"]}) or None
    if fetched.get("kind") != "flat":
        record["sweep_pngs"] = _timed(record, "render_sweep", render, fmap["sweep_path"], d, "sweep", pages)
    _save(d, record)
    return record


def stage_fill(slot: str, spec: dict, out: Path) -> dict:
    d = out / slot
    record = json.loads((d / "record.json").read_text())
    plan = PLAN.get(slot)
    if "fetch" not in record or plan is None:
        record["fill_skipped"] = "refused before a map" if "fetch" not in record else "no PLAN entry"
        _save(d, record)
        return record
    ids = _ids(spec, record["fetch"]["sha256"])
    ws = Path(os.environ["TAXFILL_WORKSPACE"]) / str(spec["year"]) / "drafts"
    ws.mkdir(parents=True, exist_ok=True)
    out_pdf = ws / f"jk19-{slot}.pdf"
    fill_args = {**ids, "values": plan["values"], "out_path": str(out_pdf)}
    for key in ("money_fields", "confirmed_fields", "provenance"):
        if plan.get(key):
            fill_args[key] = plan[key]
    try:
        filled = _timed(record, "fill_form", call, "fill_form", fill_args)
    except ToolError as exc:
        record["refused_at"] = "fill_form"
        record["refusal"] = str(exc)
        _save(d, record)
        return record
    record["fill"] = {
        "status": filled["status"], "attempted": len(plan["values"]),
        "written": filled.get("written"), "hand_write": filled.get("hand_write"),
        "warnings": filled.get("warnings"), "stamp": filled.get("stamp"), "confirmed": filled.get("confirmed"),
        "guards_hidden": filled.get("guards_hidden"), "worksheet_lines": len((filled.get("worksheet") or {})
                                                                             .get("lines") or []),
        "next_step": filled.get("next_step"),
    }
    if filled["status"] == "worksheet_only":
        (d / "worksheet.json").write_text(json.dumps(filled.get("worksheet"), indent=1))
        _save(d, record)
        return record
    verdict = _timed(record, "verify_form", call, "verify_form",
                     {**ids, "pdf_path": str(out_pdf), "expected": filled["written"],
                      **({"declared_relations": plan["declared_relations"]} if plan.get("declared_relations") else {}),
                      **({"independent": plan["independent"]} if plan.get("independent") else {})})
    record["verify"] = {
        "ok": verdict["ok"], "verdict": verdict["verdict"],
        "failed_sections": {k: s for k, s in verdict["sections"].items() if s.get("failed")},
        "checked": {k: s.get("checked") for k, s in verdict["sections"].items()},
        "verified_at": bool(verdict.get("verified_at")),
    }
    record["draft_pngs"] = _timed(record, "render_draft", render, str(out_pdf), d, "draft")
    _save(d, record)
    return record


def _save(d: Path, record: dict) -> None:
    (d / "record.json").write_text(json.dumps(record, indent=1, default=str))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="scratch directory (never inside the repo)")
    ap.add_argument("--only", default="", help="comma-separated slots (default: all)")
    ap.add_argument("--stage", choices=("map", "fill", "all"), default="all")
    ap.add_argument("--ma-local-blank", default=None,
                    help="a copy of MA Form 1 2024 saved from its mass.gov URL; adds the refusal case's local_blank run")
    a = ap.parse_args(argv)
    if a.ma_local_blank:
        FORMS["refusal_ma_local"] = {**FORMS["refusal_ma"], "local_blank": str(Path(a.ma_local_blank).resolve()),
                                     "what": FORMS["refusal_ma"]["what"] + ", with the saved copy as local_blank"}
    out = Path(a.out).expanduser().resolve()
    if out == REPO or REPO in out.parents:
        ap.error("--out must be outside the repo: renders and drafts stay out of git")
    out.mkdir(parents=True, exist_ok=True)
    os.environ["TAXFILL_BLANKS_CACHE"] = str(out / "cache")
    os.environ["TAXFILL_WORKSPACE"] = str(out / "workspace")
    import taxfill_mcp.server as server

    server.WORKSPACE_ROOT = os.environ["TAXFILL_WORKSPACE"]
    slots = [s for s in a.only.split(",") if s] or list(FORMS)
    for slot in slots:
        spec = FORMS[slot]
        rec = stage_map(slot, spec, out) if a.stage in ("map", "all") else None
        if a.stage in ("fill", "all"):
            rec = stage_fill(slot, spec, out)
        summary = {k: rec.get(k) for k in ("slot", "refused_at", "seconds")} if rec else {}
        if rec and "map" in rec:
            summary["map"] = {k: rec["map"][k] for k in ("fields", "fillable", "tiers", "refusals")}
        if rec and "verify" in rec:
            summary["verify"] = {k: rec["verify"][k] for k in ("ok", "failed_sections")}
        print(json.dumps(summary, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
