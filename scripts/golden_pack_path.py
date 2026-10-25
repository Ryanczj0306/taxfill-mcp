#!/usr/bin/env python
"""The pack-path golden: what fetch_blank, get_form_map, fill_form, verify_form and verify_filing return (Phase K
JK16b, 2026-10-25; the golden JK14 left open).

ADR-0002 ("What stays byte-identical for packs") lets the no-pack fallback ride four pack tools only if their
pack-path output stays byte-identical, and KG8 freezes that output from 2026-12-01 to 2027-04-15. JK21's harness
(scripts/golden_snapshots.py) snapshots only the tools that read state knowledge, so this one pins the rest. It is
the KG8 gate for every change that touches those tools. Offline, nothing stubbed:

* ``form_maps_<jurisdiction>.json`` — ``get_form_map`` over every shipped pack (what ``list_forms`` lists), keyed
  ``<year>/<form_key>``.
* ``_refusals.json`` — today's refusal texts on the shipped data, each raised before any download: get_form_map
  for an unknown key, year and jurisdiction and for every hand-fill key; fetch_blank / fill_form / verify_form /
  verify_filing on an unknown key; the e-file-only hand-fill packs (the FBAR) at fetch_blank and fill_form; verify_form
  on a hand-fill pack without ``expected``; verify_filing on hand-fill items alone.
* ``_demo_chain.json`` — fetch_blank, get_form_map, fill_form, verify_form and verify_filing through the server's real
  ``_load_any_pack`` and ``fetch_pack_blank`` on synthetic demo packs: a temporary ``TAXFILL_DATA_DIR`` holds an
  AcroForm pack, a print-only hand-fill pack with overlay coordinates and one without, and their committed synthetic
  blanks (packages/core/tests/fixtures/pack_path_golden/) are seeded into a temporary ``TAXFILL_BLANKS_CACHE`` under
  their source_url's cache name, where fetch_blank finds them by digest with no download. The demo source URLs sit on
  an example.gov host, so a cache miss fails offline instead of reaching an agency. Each fill's field values are read
  back from the written PDF (pypdf) and stored with the response.

No call passes the form key unmapped (that key routes to the fallback). Errors are output too, stored as
"<Type>: <msg>".
The data root, the blank cache and the temporary output folder are replaced by ``<data>``, ``<cache>`` and ``<out>``
(and the knowledge tree's own root by ``<knowledge>``), and a snapshot that still names a local path is refused.
Each dict whose values are all scalars is written on one line, so a diff names the line that moved.

Usage:
    python scripts/golden_pack_path.py --write   # regenerate every snapshot
    python scripts/golden_pack_path.py --check   # exit 1 with a per-file drift summary
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for _src in (REPO / "packages" / "core" / "src", REPO / "packages" / "mcp-server" / "src"):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

GOLDENS_DIR = REPO / "packages" / "core" / "tests" / "goldens" / "pack_path"
FIXTURES = REPO / "packages" / "core" / "tests" / "fixtures" / "pack_path_golden"
REFUSALS_FILE = "_refusals.json"
DEMO_FILE = "_demo_chain.json"

# ── the synthetic demo packs (demo values only) ────────────────────────────────

DEMO_YEAR = 2025
DEMO_JURISDICTION = "federal"
DEMO_FORM = "demo_golden"
DEMO_URL = "https://www.tax.example.gov/forms/2025/demo-golden.pdf"
DEMO_BLANK = "demo_acroform.pdf"
PRINT_JURISDICTION = "states/nm"
PRINT_FORM = "demo_print"
PRINT_URL = "https://www.tax.example.gov/forms/2025/demo-print.pdf"
PRINT_BLANK = "demo_print.pdf"
BARE_FORM = "demo_bare"  # a hand-fill pack with no overlay coordinates
BARE_URL = "https://www.tax.example.gov/forms/2025/demo-bare.pdf"


def make_demo_blanks(directory: Path) -> None:
    """Write the two synthetic blanks (reportlab, invariant output). Run once with --write-blanks; the committed
    bytes are what the golden pins, so a reportlab upgrade never moves it."""
    from reportlab.lib.pagesizes import letter  # noqa: PLC0415
    from reportlab.pdfgen import canvas  # noqa: PLC0415

    directory.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(directory / DEMO_BLANK), pagesize=letter, invariant=1)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 740, "Form DEMO-G  Demo Golden Return  2025")
    c.setFont("Helvetica", 9)
    rows = [("Your name", "name", 680), ("Demo identifying number", "ssn", 650), ("1  Wages", "line1", 600),
            ("2  Interest", "line2", 570), ("3  Total. Add lines 1 and 2", "line3", 540)]
    for label, name, y in rows:
        c.drawString(72, y + 4, label)
        if name == "ssn":
            c.acroForm.textfield(name=name, x=300, y=y, width=135, height=18, maxlen=9, fieldFlags="comb",
                                 borderWidth=0)
        else:
            c.acroForm.textfield(name=name, x=300, y=y, width=180, height=18, borderWidth=0)
    c.drawString(72, 514, "4  Check if a demo filer")
    c.acroForm.checkbox(name="demo_check", x=300, y=510, size=12, buttonStyle="cross", borderWidth=0)
    c.showPage()
    c.setFont("Helvetica", 9)
    c.drawString(72, 700, "Name shown on page 1")
    c.acroForm.textfield(name="p2_name", x=300, y=696, width=180, height=18, borderWidth=0)
    c.showPage()
    c.save()

    c = canvas.Canvas(str(directory / PRINT_BLANK), pagesize=letter, invariant=1)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 740, "Form DEMO-P  Demo Print-Only Return  2025")
    c.setFont("Helvetica", 9)
    for label, y in (("1  Your name", 680), ("2  Wages", 650), ("3  Tax", 620), ("4  Total. Add lines 2 and 3", 590)):
        c.drawString(72, y + 4, label)
        c.rect(300, y, 180, 16)
    c.showPage()
    c.save()


def _sha256(path: Path) -> str:
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_demo_data(data: Path) -> None:
    """The temporary TAXFILL_DATA_DIR: the shipped knowledge tree (copied) and the three demo packs."""
    shutil.copytree(REPO / "knowledge", data / "knowledge")
    acro = data / "formpacks" / DEMO_JURISDICTION / str(DEMO_YEAR) / DEMO_FORM
    acro.mkdir(parents=True)
    (acro / "pack.yaml").write_text(
        "form: DEMO-G\n"
        f"jurisdiction: {DEMO_JURISDICTION}\n"
        f"tax_year: {DEMO_YEAR}\n"
        f"source_url: {DEMO_URL}\n"
        f"pdf_sha256: \"{_sha256(FIXTURES / DEMO_BLANK)}\"\n"
        "acroform_root: \"\"\n"
        "fields:\n"
        "  - {line: name, field: name, type: text}\n"
        "  - {line: identifying_number, field: ssn, type: text, maxlen: 9, comb: true}\n"
        "  - {line: \"1\", field: line1, type: money}\n"
        "  - {line: \"2\", field: line2, type: money}\n"
        "  - {line: \"3\", field: line3, type: money}\n"
        "  - {line: \"4\", field: demo_check, type: checkbox, on_state: /Yes}\n"
        "  - {line: name.page2, field: p2_name, type: text}\n"
        "relations:\n"
        "  - \"3 == 1 + 2\"\n"
        "identity_fields: [name, identifying_number]\n",
        encoding="utf-8")
    for form, url, overlay in ((PRINT_FORM, PRINT_URL, True), (BARE_FORM, BARE_URL, False)):
        pack = data / "formpacks" / PRINT_JURISDICTION / str(DEMO_YEAR) / form
        pack.mkdir(parents=True)
        def box(y: float) -> str:
            return f", overlay: {{page: 1, x: 300, y: {y}, w: 180}}" if overlay else ""
        (pack / "handfill.yaml").write_text(
            "form: DEMO-P\n"
            f"jurisdiction: {PRINT_JURISDICTION}\n"
            f"tax_year: {DEMO_YEAR}\n"
            "render_mode: hand_fill\n"
            f"source_url: {url}\n"
            f"pdf_sha256: \"{_sha256(FIXTURES / PRINT_BLANK)}\"\n"
            "lines:\n"
            f"  - {{line: \"1\", label: Your name, type: text{box(683)}}}\n"
            f"  - {{line: \"2\", label: Wages, type: money{box(653)}}}\n"
            f"  - {{line: \"3\", label: Tax, type: money{box(623)}}}\n"
            f"  - {{line: \"4\", label: Total, type: money, compute: \"2 + 3\"{box(593)}}}\n",
            encoding="utf-8")


def _seed_cache(cache: Path) -> None:
    """Each demo blank under its source_url's cache name, where fetch_blank finds it by digest with no download."""
    from taxfill_core.fetch import _cache_path  # noqa: PLC0415

    cache.mkdir(parents=True, exist_ok=True)
    for url, blank in ((DEMO_URL, DEMO_BLANK), (PRINT_URL, PRINT_BLANK), (BARE_URL, PRINT_BLANK)):
        shutil.copyfile(FIXTURES / blank, _cache_path(cache, url))


# ── calls ──────────────────────────────────────────────────────────────────────


def _server():
    import taxfill_mcp.server as server  # noqa: PLC0415  (imported lazily: FastMCP builds the tool table)

    return server


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """The tool's return value, or the error it raises (a refusal is output too)."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — every exception type is snapshotted, none is swallowed silently
        return {"error": f"{type(exc).__name__}: {exc}"}


def _pdf_values(path: Path) -> dict[str, str] | dict[str, Any]:
    """Every field's /V as written (the same field values in the written PDF), or the read error."""
    from pypdf import PdfReader  # noqa: PLC0415

    try:
        fields = PdfReader(str(path)).get_fields() or {}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {name: str(f.get("/V")) for name, f in sorted(fields.items()) if f.get("/V") is not None}


def _page_text(path: Path) -> list[str] | dict[str, Any]:
    """The stamped print-only draft's text layer per page (what the overlay wrote)."""
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415

        doc = pdfium.PdfDocument(str(path))
        try:
            return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def snapshot_form_maps(jurisdictions: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """get_form_map over every shipped pack, one dict per jurisdiction (``<year>/<form_key>`` -> the map);
    ``jurisdictions`` limits the run (a quick check of one file)."""
    server = _server()
    out: dict[str, dict[str, Any]] = {}
    for s in server.list_forms():
        if jurisdictions is not None and s["jurisdiction"] not in jurisdictions:
            continue
        key = f"{s['tax_year']}/{s['form_key']}"
        out.setdefault(s["jurisdiction"], {})[key] = _call(server.get_form_map, s["form_key"], s["tax_year"],
                                                            s["jurisdiction"])
    return out


def _hand_fill_keys() -> list[tuple[str, int, str]]:
    from taxfill_core.datadir import formpacks_dir  # noqa: PLC0415

    root = formpacks_dir()
    keys = []
    for path in sorted(root.glob("**/handfill.yaml")):
        rel = path.parent.relative_to(root).parts  # (federal, year, form) or (states, xx, year, form)
        jurisdiction = "/".join(rel[:-2])
        keys.append((rel[-1], int(rel[-2]), jurisdiction))
    return keys


def snapshot_refusals() -> dict[str, Any]:
    """Today's pack-path refusal texts on the shipped data, each raised before any download."""
    from taxfill_core.handfill import load_hand_fill_pack, hand_fill_pack_path  # noqa: PLC0415

    server = _server()
    out: dict[str, Any] = {
        "get_form_map": {
            "unknown_form": _call(server.get_form_map, "zz_no_such_form", 2025, "federal"),
            "unknown_year": _call(server.get_form_map, "f1040", 1999, "federal"),
            "unknown_jurisdiction": _call(server.get_form_map, "f1040", 2025, "states/zz"),
        },
        "fetch_blank": {"unknown_form": _call(server.fetch_blank, "zz_no_such_form", 2025, "federal")},
        "fill_form": {"unknown_form": _call(server.fill_form, "zz_no_such_form", 2025, {"1": 1}, "unused.pdf",
                                            "federal")},
        "verify_form": {"unknown_form": _call(server.verify_form, "zz_no_such_form", 2025, "unused.pdf")},
        "verify_filing": {
            "unknown_form": _call(server.verify_filing, [{"form": "zz_no_such_form", "year": 2025,
                                                          "pdf_path": "unused.pdf"}]),
            "empty": _call(server.verify_filing, []),
        },
    }
    hand = out["get_form_map"]["hand_fill"] = {}
    efile = out["fetch_blank"]["efile_only"] = {}
    overlay = out["verify_form"]["hand_fill_without_expected"] = {}
    fill_efile = out["fill_form"]["efile_only"] = {}
    filing = out["verify_filing"]["hand_fill_only"] = {}
    filing_missing = out["verify_filing"]["hand_fill_without_expected"] = {}
    for form, year, jurisdiction in _hand_fill_keys():
        key = f"{jurisdiction}/{year}/{form}"
        hand[key] = _call(server.get_form_map, form, year, jurisdiction)
        pack = load_hand_fill_pack(hand_fill_pack_path(form, year, jurisdiction))
        if pack.efile_only:
            efile[key] = _call(server.fetch_blank, form, year, jurisdiction)
            fill_efile[key] = _call(server.fill_form, form, year, {}, "unused.pdf", jurisdiction)
        overlay[key] = _call(server.verify_form, form, year, "unused.pdf", None, None, jurisdiction)
        item = {"form": form, "year": year, "jurisdiction": jurisdiction, "pdf_path": "unused.pdf"}
        filing[key] = _call(server.verify_filing, [{**item, "expected": {}}])
        filing_missing[key] = _call(server.verify_filing, [item])
    return out


@contextlib.contextmanager
def _env(**values: str) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


DEMO_VALUES = {"name": "Riley Example", "identifying_number": "123456789", "1": 50000, "2": 125.5, "3": 50126,
               "4": "yes", "name.page2": "Riley Example"}
PRINT_VALUES = {"1": "Riley Example", "2": 40000, "3": 1200}


def snapshot_demo_chain(root: Path) -> dict[str, Any]:
    """fetch -> map -> fill -> verify -> verify_filing on the demo packs, under ``root`` (data, cache, out)."""
    import logging  # noqa: PLC0415

    logging.getLogger("pypdf").setLevel(logging.ERROR)  # the not-a-PDF call logs a header warning; its error is stored
    server = _server()
    data, cache, out = root / "data", root / "cache", root / "out"
    _write_demo_data(data)
    _seed_cache(cache)
    out.mkdir()
    a = {"year": DEMO_YEAR, "jurisdiction": DEMO_JURISDICTION}
    p = {"year": DEMO_YEAR, "jurisdiction": PRINT_JURISDICTION}
    result: dict[str, Any] = {}
    with _env(TAXFILL_DATA_DIR=str(data), TAXFILL_BLANKS_CACHE=str(cache)):
        acro: dict[str, Any] = {}
        acro["list_forms"] = _call(server.list_forms, DEMO_JURISDICTION, DEMO_YEAR)
        acro["fetch_blank"] = _call(server.fetch_blank, DEMO_FORM, **a)
        acro["get_form_map"] = _call(server.get_form_map, DEMO_FORM, **a)
        good = out / "demo_golden.pdf"
        acro["fill_form"] = _call(server.fill_form, DEMO_FORM, values=DEMO_VALUES, out_path=str(good), **a)
        acro["fill_form_pdf_values"] = _pdf_values(good)
        acro["fill_form_unknown_line"] = _call(server.fill_form, DEMO_FORM, values={"99": 1},
                                               out_path=str(out / "unknown.pdf"), **a)
        acro["fill_form_comb_violation"] = _call(server.fill_form, DEMO_FORM,
                                                 values={"identifying_number": "1234567890"},
                                                 out_path=str(out / "comb.pdf"), **a)
        expected = {k: v for k, v in DEMO_VALUES.items()}
        acro["verify_form"] = _call(server.verify_form, DEMO_FORM, pdf_path=str(good), expected=expected,
                                    independent={"3": 50126}, **a)
        acro["verify_form_no_independent"] = _call(server.verify_form, DEMO_FORM, pdf_path=str(good), **a)
        acro["verify_form_wrong_expected"] = _call(server.verify_form, DEMO_FORM, pdf_path=str(good),
                                                   expected={**expected, "1": 50001}, **a)
        acro["verify_form_wrong_independent"] = _call(server.verify_form, DEMO_FORM, pdf_path=str(good),
                                                      independent={"3": 99999}, **a)
        bad_relation = out / "bad_relation.pdf"
        acro["fill_form_bad_relation"] = _call(server.fill_form, DEMO_FORM, values={**DEMO_VALUES, "3": 1},
                                               out_path=str(bad_relation), **a)
        acro["verify_form_bad_relation"] = _call(server.verify_form, DEMO_FORM, pdf_path=str(bad_relation), **a)
        acro["verify_form_missing_pdf"] = _call(server.verify_form, DEMO_FORM, pdf_path=str(out / "missing.pdf"), **a)
        not_pdf = out / "not_a.pdf"
        not_pdf.write_text("not a PDF", encoding="utf-8")
        acro["verify_form_not_a_pdf"] = _call(server.verify_form, DEMO_FORM, pdf_path=str(not_pdf), **a)
        result["acroform"] = acro

        hf: dict[str, Any] = {}
        hf["fetch_blank"] = _call(server.fetch_blank, PRINT_FORM, **p)
        hf["get_form_map"] = _call(server.get_form_map, PRINT_FORM, **p)
        stamped = out / "demo_print.pdf"
        hf["fill_form"] = _call(server.fill_form, PRINT_FORM, values=PRINT_VALUES, out_path=str(stamped), **p)
        hf["fill_form_text_layer"] = _page_text(stamped)
        hf["verify_form"] = _call(server.verify_form, PRINT_FORM, pdf_path=str(stamped),
                                  expected={**PRINT_VALUES}, independent={"4": 41200}, **p)
        hf["verify_form_without_expected"] = _call(server.verify_form, PRINT_FORM, pdf_path=str(stamped), **p)
        hf["verify_form_wrong_expected"] = _call(server.verify_form, PRINT_FORM, pdf_path=str(stamped),
                                                 expected={**PRINT_VALUES, "2": 40001}, **p)
        hf["bare_fetch_blank"] = _call(server.fetch_blank, BARE_FORM, **p)
        hf["bare_fill_form"] = _call(server.fill_form, BARE_FORM, values=PRINT_VALUES,
                                     out_path=str(out / "bare.pdf"), **p)
        result["hand_fill"] = hf

        acro_item = {"form": DEMO_FORM, "pdf_path": str(good), **a}
        print_item = {"form": PRINT_FORM, "pdf_path": str(stamped), "expected": {**PRINT_VALUES}, **p}
        filing: dict[str, Any] = {}
        filing["acroform"] = _call(server.verify_filing, [acro_item], independent={DEMO_FORM: {"3": 50126}})
        filing["acroform_no_independent"] = _call(server.verify_filing, [acro_item])
        filing["mixed"] = _call(server.verify_filing, [acro_item, print_item],
                                independent={DEMO_FORM: {"3": 50126}, PRINT_FORM: {"4": 41200}})
        filing["stray_independent"] = _call(server.verify_filing, [acro_item], independent={"zz": {"1": 1}})
        filing["missing_pdf"] = _call(server.verify_filing, [{**acro_item, "pdf_path": str(out / "missing.pdf")}])
        filing["form_key"] = _call(server.verify_filing, [{**acro_item, "form_key": "demo_alias"}])
        result["verify_filing"] = filing
    return result


# ── rendering ──────────────────────────────────────────────────────────────────


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not JSON-serialisable in a snapshot: {type(value).__name__}")


def _scrub(obj: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(obj, dict):
        return {k: _scrub(v, replacements) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v, replacements) for v in obj]
    if isinstance(obj, str):
        for old, new in replacements:
            obj = obj.replace(old, new)
        return obj
    return obj


def _replacements(pairs: list[tuple[Path, str]]) -> list[tuple[str, str]]:
    """Every spelling of each path (as given, resolved, and home-relative), longest first."""
    from taxfill_core.datadir import home_display  # noqa: PLC0415

    out: dict[str, str] = {}
    for path, token in pairs:
        for spelling in (str(path), str(path.resolve()), home_display(path), home_display(path.resolve())):
            if spelling and spelling not in (".", "~"):
                out.setdefault(spelling, token)
    return sorted(out.items(), key=lambda kv: -len(kv[0]))


def _dumps(obj: Any, indent: int = 0) -> str:
    """JSON with sorted keys, one key per line, except a dict or list of scalars, which sits on one line."""
    pad, inner = " " * indent, " " * (indent + 1)
    if isinstance(obj, dict) and obj and any(isinstance(v, (dict, list)) for v in obj.values()):
        items = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {_dumps(obj[k], indent + 1)}" for k in sorted(obj)]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(obj, list) and obj and any(isinstance(v, (dict, list)) for v in obj):
        return "[\n" + ",\n".join(f"{inner}{_dumps(v, indent + 1)}" for v in obj) + "\n" + pad + "]"
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _render(raw: Any, replacements: list[tuple[str, str]]) -> str:
    plain = json.loads(json.dumps(raw, sort_keys=True, ensure_ascii=False, default=_json_default))
    plain = _scrub(plain, replacements)
    text = _dumps(plain) + "\n"
    if json.loads(text) != plain:
        raise AssertionError("the snapshot writer is not lossless — fix _dumps()")
    for old, _ in replacements:
        if old in text:
            raise ValueError("a snapshot still names a local path — scrub it before writing")
    if str(REPO) in text or str(Path.home()) in text:
        raise ValueError("a snapshot still names a local path — scrub it before writing")
    return text


def _file_name(jurisdiction: str) -> str:
    return f"form_maps_{jurisdiction.replace('/', '_')}.json"


def build_all(only: set[str] | None = None) -> dict[str, str]:
    """Every snapshot file name -> its exact text."""
    from taxfill_core.datadir import data_root, knowledge_dir  # noqa: PLC0415
    from taxfill_core.fetch import default_cache_dir  # noqa: PLC0415

    base = [(data_root(), "<data>"), (knowledge_dir(), "<knowledge>"), (default_cache_dir(), "<cache>")]
    files: dict[str, str] = {}
    wanted = None
    if only is not None:
        wanted = {s["jurisdiction"] for s in _server().list_forms() if _file_name(s["jurisdiction"]) in only}
    for jurisdiction, maps in snapshot_form_maps(wanted).items():
        files[_file_name(jurisdiction)] = _render(maps, _replacements(base))
    if only is None or REFUSALS_FILE in only:
        files[REFUSALS_FILE] = _render(snapshot_refusals(), _replacements(base))
    if only is None or DEMO_FILE in only:
        with tempfile.TemporaryDirectory(prefix="taxfill-pack-golden-") as tmp:
            root = Path(tmp)
            raw = snapshot_demo_chain(root)
            reps = _replacements([(root / "data" / "knowledge", "<knowledge>"), (root / "data", "<data>"),
                                  (root / "cache", "<cache>"), (root / "out", "<out>"), (root, "<tmp>"), *base])
            files[DEMO_FILE] = _render(raw, reps)
    return files


def _first_difference(old: Any, new: Any, path: str = "") -> str | None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            here = f"{path}.{key}" if path else str(key)
            if key not in old:
                return f"{here}: added"
            if key not in new:
                return f"{here}: removed"
            found = _first_difference(old[key], new[key], here)
            if found:
                return found
        return None
    if isinstance(old, list) and isinstance(new, list):
        for i, (a, b) in enumerate(zip(old, new)):
            found = _first_difference(a, b, f"{path}[{i}]")
            if found:
                return found
        return f"{path}: list length {len(old)} -> {len(new)}" if len(old) != len(new) else None
    if old != new:
        a, b = json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False)
        return f"{path}: {a[:160]} -> {b[:160]}"
    return None


def drift(goldens_dir: Path = GOLDENS_DIR, current: dict[str, str] | None = None,
          only: set[str] | None = None) -> list[str]:
    """One line per drifted, missing or stale snapshot file; empty when every snapshot matches."""
    current = build_all(only) if current is None else current
    on_disk = {p.name for p in goldens_dir.glob("*.json")} if goldens_dir.is_dir() else set()
    if only is not None:
        on_disk &= only
    problems = []
    for name in sorted(set(current) | on_disk):
        if name not in current:
            problems.append(f"{name}: stale snapshot — nothing produces it any more")
            continue
        if name not in on_disk:
            problems.append(f"{name}: missing snapshot — run scripts/golden_pack_path.py --write")
            continue
        committed = (goldens_dir / name).read_text(encoding="utf-8")
        if committed != current[name]:
            where = _first_difference(json.loads(committed), json.loads(current[name]))
            problems.append(f"{name}: drifted at {where or '(layout only — regenerate)'}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate every snapshot")
    mode.add_argument("--check", action="store_true", help="exit 1 when any snapshot drifted")
    mode.add_argument("--write-blanks", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--only", nargs="+", metavar="FILE", help="limit --check to these snapshot files")
    parser.add_argument("--goldens", type=Path, default=GOLDENS_DIR, help=argparse.SUPPRESS)
    ns = parser.parse_args(argv)
    if ns.write_blanks:
        make_demo_blanks(FIXTURES)
        print(f"wrote {DEMO_BLANK} and {PRINT_BLANK}")
        return 0
    if ns.write and ns.only:
        parser.error("--only is for --check; --write always regenerates every snapshot")
    only = set(ns.only) if ns.only else None
    current = build_all(only)
    if ns.write:
        ns.goldens.mkdir(parents=True, exist_ok=True)
        for stale in {p.name for p in ns.goldens.glob("*.json")} - set(current):
            (ns.goldens / stale).unlink()
        for name, text in current.items():
            (ns.goldens / name).write_text(text, encoding="utf-8")
        size = sum(len(t.encode("utf-8")) for t in current.values())
        print(f"wrote {len(current)} pack-path snapshots ({size:,} bytes)")
        return 0
    problems = drift(ns.goldens, current, only)
    if problems:
        print(f"{len(problems)} pack-path snapshot(s) differ from the tools' output:")
        for line in problems:
            print(f"  {line}")
        print("If the change is intended (KG8: a pack-path wrong-value fix only), regenerate with: "
              "python scripts/golden_pack_path.py --write")
        return 1
    print(f"all {len(current)} pack-path snapshots match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
