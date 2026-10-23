#!/usr/bin/env python
"""Golden-diff harness over every MCP tool that reads state knowledge (Phase K JK21).

Later Phase K tranches restructure the state knowledge layer (JK20 hoists citations,
JK22 drops never-read blocks, JK24 adds the v2 loader, JK26 migrates TY2025). Each must
prove that what the tools emit did not change. This script snapshots that output.

For every ``knowledge/states/<st>/<year>.yaml`` it writes one deterministic JSON file,
``packages/core/tests/goldens/state_knowledge/<st>_<year>.json``, holding what the MCP
tool functions in ``taxfill_mcp.server`` return (the same functions the MCP host calls):

* ``calc`` op ``state_tax`` (calc.py ``state_tax``, plus the server's provisional stamp)
  over the fixed demo grid below.
* ``state_scope`` (statescope.py) for three demo profiles: a full-year resident, a
  part-year treaty filer and a nonresident treaty filer with remote work.
* ``filing_summary`` and ``file_and_pay`` (filing_summary.py / file_and_pay.py) for a
  four-return demo manifest of the jurisdiction (three originals and, since JK27, one amended return).
* ``get_sources`` (sources.py over knowledge/sources.yaml + sources_states.yaml) for every
  topic the jurisdiction's registry lists, plus one query that matches nothing.

One extra file, ``_no_income_tax.json``, covers the jurisdictions in
``knowledge/states/no_income_tax.yaml`` (state_scope, filing_summary and file_and_pay read
it; it is not year-specific, so it is snapshotted for the newest knowledge year only).

The residency tool is not covered: it calls ``_classify`` only and reads no state knowledge.

THE state_tax GRID (per jurisdiction-year), all inputs demo values:

* Filing statuses: every status the pack's ``tax`` block models (the bracket schedules'
  keys, else the standard-deduction keys); a flat-rate pack with neither uses ``single``
  only (the status cannot change its output).
* Bases per status, where ``D`` is the status's standard deduction (0 when none ships):
  ``0`` (the clamp), ``D`` (zero after the deduction), and ``D + p`` for a point ``p`` inside
  the first, the middle and the top bracket of the status's schedule (a bounded bracket's
  midpoint, capped at 5,000 above its floor; the top bracket's floor plus 10,000). The
  top-bracket call's work string prints every bracket's floor, ceiling, rate and amount, so
  it pins the whole schedule. A flat-rate pack uses ``p`` in {40,000}.
* Exemptions: where the pack ships a ``personal`` or ``dependent`` amount, one more call per
  status at ``D + 40,000 + exemptions`` with 2 personal exemptions (married statuses) or 1,
  and 1 dependent. For each of the two kinds the pack does NOT ship, one call passing that
  count snapshots the refusal text (e.g. AZ's "Line 49 dependent CREDIT" pointer).
* One ``qualifying_surviving_spouse`` call per pack at ``D[mfj] + 40,000`` (the alias path).
* Exemption credits (Phase K JK28), only where the pack ships ``tax.exemption_credits``: per
  status, ``exemption_credit_counts`` of 2 per credit kind (married statuses) or 1, capped at the
  kind's ``max_count``, at ``D + 40,000`` with ``federal_agi`` below the limitation threshold and
  again ``30,001`` above it (a fraction of a step rounds up); one ``single`` call ``100,000``
  above the threshold (a group floors at $0); and one call without ``federal_agi`` (the refusal).
  A pack with an AGI CEILING instead (OR) gets, per status, a call at each distinct ceiling and
  one dollar above it (the cliff), plus the single refusal without ``federal_agi``; a pack with
  neither gets the per-status call at the base alone (its credits read no AGI).

Errors are part of the output: a call that raises is stored as ``{"args": ..., "error":
"<Type>: <msg>"}``. A result is stored without the args, because it echoes them in ``inputs``.

SIZE: the stored form is the tool output with three lossless transforms (``expand`` inverts
them; ``build_all`` asserts ``expand(compress(raw)) == raw`` on every file):

* every state_tax ``work`` string of one pack ends with the same text (the tax line, the
  not-modeled disclaimer and every pack note): it is stored once as
  ``state_tax.work_common_tail`` and each call keeps ``work_head`` (work = head + tail);
* result fields equal across all of a pack's state_tax results (citation, base_kind, ...) are
  stored once as ``state_tax.common_result``;
* a string of 80+ characters that occurs twice or more is stored once under ``_strings`` and
  referenced as ``@@<first 12 hex of its sha256>``.

So any change to any emitted value changes the file, and ``--check`` reports the first
difference on the expanded output (``state_tax[3].tax``), never on a storage id.

No timestamps, no absolute paths: the data root is replaced by ``<data>`` before writing, and
a snapshot that still names it is refused.

Usage:
    python scripts/golden_snapshots.py --write   # regenerate every snapshot
    python scripts/golden_snapshots.py --check   # exit 1 with a per-file drift summary
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import sys
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for _src in (REPO / "packages" / "core" / "src", REPO / "packages" / "mcp-server" / "src"):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

GOLDENS_DIR = REPO / "packages" / "core" / "tests" / "goldens" / "state_knowledge"
NO_INCOME_TAX_FILE = "_no_income_tax.json"
UNMATCHED_TOPIC = "zzqx unmatched probe"
MARRIED = ("married_filing_jointly", "qualifying_surviving_spouse")


def _server():
    import taxfill_mcp.server as server  # noqa: PLC0415  (imported lazily: FastMCP builds the tool table)

    return server


def _call(fn: Callable[..., Any], *args: Any) -> Any:
    """The tool's return value, or the error it raises (a refusal is output too)."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 — every exception type is snapshotted, none is swallowed silently
        return {"error": f"{type(exc).__name__}: {exc}"}


# ── state_tax ──────────────────────────────────────────────────────────────────


def _bracket_points(schedule) -> list[int]:
    """Post-deduction points inside the first, the middle and the top bracket.

    A call whose base lands in the top bracket prints EVERY bracket's floor, ceiling, rate and
    contribution in its work string, so it pins the whole schedule; the first- and middle-bracket
    points add the marginal rate and the partial-bracket arithmetic lower down.
    """

    def inside(bracket) -> int:
        over = int(bracket.over)
        if bracket.but_not_over is None:
            return over + 10_000
        return over + min((int(bracket.but_not_over) - over) // 2, 5_000)

    picks = {0, len(schedule) // 2, len(schedule) - 1}
    return sorted({inside(schedule[i]) for i in picks})


def state_tax_grid(tax) -> list[dict[str, Any]]:
    """The demo argument sets for one pack's ``tax`` block (see the module docstring)."""
    if tax is None:
        return [{"taxable_base": 40_000, "filing_status": "single"}]
    std = tax.standard_deduction or {}
    if tax.brackets:
        statuses = sorted(tax.brackets)
    elif std:
        statuses = sorted(std)
    else:
        statuses = ["single"]
    personal = tax.exemptions.get("personal")
    dependent = tax.exemptions.get("dependent")
    grid: list[dict[str, Any]] = []
    for status in statuses:
        d = int(std.get(status, 0))
        points = _bracket_points(tax.brackets[status]) if tax.brackets else [40_000]
        bases = sorted({0, d, *(d + p for p in points)})
        grid += [{"taxable_base": b, "filing_status": status} for b in bases]
        if personal is not None or dependent is not None:
            n_personal = (2 if status in MARRIED else 1) if personal is not None else 0
            n_dependent = 1 if dependent is not None else 0
            extra = n_personal * int(personal.amount if personal else 0) + n_dependent * int(
                dependent.amount if dependent else 0
            )
            grid.append({
                "taxable_base": d + 40_000 + extra,
                "filing_status": status,
                "exemptions_count": n_personal,
                "dependents_count": n_dependent,
            })
    # A count for a kind the pack does not ship is refused with a prescriptive message; snapshot it.
    if personal is None:
        grid.append({"taxable_base": 40_000, "filing_status": statuses[0], "exemptions_count": 1})
    if dependent is None:
        grid.append({"taxable_base": 40_000, "filing_status": statuses[0], "dependents_count": 1})
    grid.append({
        "taxable_base": int(std.get("married_filing_jointly", 0)) + 40_000,
        "filing_status": "qualifying_surviving_spouse",
    })
    grid += _exemption_credit_grid(tax, statuses, std)
    return grid


def _exemption_credit_grid(tax, statuses: list[str], std: dict) -> list[dict[str, Any]]:
    """The exemption-credit calls for a pack that ships ``tax.exemption_credits`` (Phase K JK28); none otherwise."""
    block = getattr(tax, "exemption_credits", None)
    if block is None:
        return []
    lim = block.agi_limitation
    ceiling = getattr(block, "agi_ceiling", None)
    grid: list[dict[str, Any]] = []
    for status in statuses:
        counts = {
            kind: min(2 if status in MARRIED else 1, credit.max_count[status] if credit.max_count else 2)
            for kind, credit in block.credits.items()
        }
        base = int(std.get(status, 0)) + 40_000
        agis = [base] + ([lim.threshold[status] + 30_001] if lim is not None else [])
        if ceiling is not None:  # Phase K JK28 (2026-10-23): each ceiling, and one dollar over it
            caps = sorted({table[status] for table in ceiling.ceilings.values()})
            agis = [base] + [agi for cap in caps for agi in (cap, cap + 1)]
        if lim is None and ceiling is None:  # credits that read no AGI: no federal_agi to pass
            grid.append({"taxable_base": base, "filing_status": status, "exemption_credit_counts": counts})
            continue
        grid += [
            {"taxable_base": base, "filing_status": status, "exemption_credit_counts": counts, "federal_agi": agi}
            for agi in agis
        ]
    if lim is not None:
        single = {kind: 1 for kind in block.credits}
        grid.append({
            "taxable_base": int(std.get("single", 0)) + 40_000, "filing_status": "single",
            "exemption_credit_counts": single, "federal_agi": lim.threshold["single"] + 100_000,
        })
        grid.append({"taxable_base": 40_000, "filing_status": "single", "exemption_credit_counts": single})
    elif ceiling is not None:
        single = {kind: 1 for kind in block.credits}
        grid.append({"taxable_base": 40_000, "filing_status": "single", "exemption_credit_counts": single})
    if getattr(block, "limited_to_tax_line", None) is not None:  # Phase K JK28 (2026-10-23): a tax under the credits
        grid.append({
            "taxable_base": int(std.get("single", 0)) + 2_500, "filing_status": "single",
            "exemption_credit_counts": {kind: 1 for kind in block.credits},
        })
    return grid


def _snapshot_state_tax(code: str, year: int, pack) -> list[dict[str, Any]]:
    server = _server()
    calls: list[dict[str, Any]] = []
    for grid_args in state_tax_grid(pack.tax):
        args = {"state": code, "year": year, **grid_args}
        result = _call(server.calc, "state_tax", dict(args))
        # A result echoes its own arguments under "inputs"; a refusal does not, so it keeps them.
        calls.append(result if "inputs" in result else {"args": args, **result})
    return calls


# ── state_scope / filing_summary / file_and_pay / get_sources ─────────────────────


def _period(state: str, start: str, end: str, **extra: Any) -> dict[str, Any]:
    return {"state": state, "start": start, "end": end, "provenance": {"kind": "user_stated"}, **extra}


def demo_profiles(st: str, year: int) -> dict[str, dict[str, Any]]:
    """Three demo footprints for the state ``st`` (upper case). TX is the no-income-tax neighbour."""
    y = str(year)
    resident = {
        "identity": {"us_person": {"value": True, "provenance": {"kind": "user_stated"}}},
        "state_footprint": {y: {
            "lived": [_period(st, f"{y}-01-01", f"{y}-12-31")],
            "worked": [_period(st, f"{y}-01-01", f"{y}-12-31")],
        }},
    }
    part_year = {
        "identity": {"us_person": {"value": False, "provenance": {"kind": "user_stated"}}},
        "state_footprint": {y: {
            "lived": [_period(st, f"{y}-01-01", f"{y}-06-30"), _period("TX", f"{y}-07-01", f"{y}-12-31")],
            "worked": [_period(st, f"{y}-01-01", f"{y}-06-30"), _period("TX", f"{y}-07-01", f"{y}-12-31")],
        }},
    }
    nonresident = {
        "identity": {"us_person": {"value": False, "provenance": {"kind": "user_stated"}}},
        "state_footprint": {y: {
            "lived": [_period("TX", f"{y}-01-01", f"{y}-12-31")],
            "worked": [
                _period(st, f"{y}-01-01", f"{y}-03-31"),
                _period("TX", f"{y}-04-01", f"{y}-12-31", remote=True, employer_state=st),
            ],
        }},
    }
    return {"resident": resident, "part_year": part_year, "nonresident": nonresident}


def demo_manifest(code: str, year: int, form: str) -> list[dict[str, Any]]:
    """A refund (joint), an unpaid balance and a paid-online balance for one state return, and an amended return
    with a balance due (Phase K JK27: the amended-return model reads the pack's ``amended_return`` block, and a
    state without one gets the DOR pointer; both stay inside the byte-identical gate)."""
    j = f"states/{code}"
    return [
        {"form": form, "tax_year": year, "jurisdiction": j, "bottom_line": 512, "filing_jointly": True,
         "direct_deposit": True},
        {"form": form, "tax_year": year, "jurisdiction": j, "bottom_line": -347},
        {"form": form, "tax_year": year, "jurisdiction": j, "bottom_line": -1205, "paid_online": True},
        {"form": form, "tax_year": year, "jurisdiction": j, "bottom_line": -88, "amended": True},
    ]


def _snapshot_logistics(code: str, year: int, form: str) -> dict[str, Any]:
    server = _server()
    manifest = demo_manifest(code, year, form)
    scope = {
        name: _call(server.state_scope, profile, year)
        for name, profile in demo_profiles(code.upper(), year).items()
    }
    return {
        "state_scope": scope,
        "filing_summary": _call(server.filing_summary, manifest),
        "file_and_pay": _call(server.file_and_pay, manifest),
    }


def _snapshot_sources(code: str, year: int) -> dict[str, Any]:
    server = _server()
    jurisdiction = f"states/{code}"
    probe = _call(server.get_sources, UNMATCHED_TOPIC, year, jurisdiction)
    out = {UNMATCHED_TOPIC: probe}
    for topic in probe.get("available_topics", []) if isinstance(probe, dict) else []:
        out[topic] = _call(server.get_sources, topic, year, jurisdiction)
    return out


# ── assembly ───────────────────────────────────────────────────────────────────


@contextlib.contextmanager
def _memoized_yaml() -> Iterator[None]:
    """Parse each distinct YAML text once for the whole run (speed only; output is unchanged).

    The tools re-read and re-parse their packs on every call (the sources registry alone is
    parsed twice per get_sources call), which made a full run take minutes. ``yaml.safe_load``
    is a pure function of its input text, so the cache is keyed on the text itself and every
    hit returns a deep copy: a caller that mutates its result never sees another call's data.
    """
    import yaml  # noqa: PLC0415

    original = yaml.safe_load
    cache: dict[str, Any] = {}

    def safe_load(stream: Any) -> Any:
        if not isinstance(stream, str):
            return original(stream)
        key = hashlib.sha256(stream.encode("utf-8")).hexdigest()
        if key not in cache:
            cache[key] = original(stream)
        return copy.deepcopy(cache[key])

    yaml.safe_load = safe_load
    try:
        yield
    finally:
        yaml.safe_load = original



def jurisdiction_years(knowledge: Path) -> list[tuple[str, int]]:
    return sorted(
        (p.parent.name, int(p.stem))
        for p in (knowledge / "states").glob("*/[0-9][0-9][0-9][0-9].yaml")
    )


def _resident_form(pack) -> str:
    forms = getattr(pack, "forms", None) or {}
    return str(forms.get("resident") or "state return")


def snapshot_jurisdiction_year(code: str, year: int) -> dict[str, Any]:
    """The raw (uncompressed) tool output for one jurisdiction-year."""
    from taxfill_core.knowledge import load_state_knowledge  # noqa: PLC0415

    pack = load_state_knowledge(code, year)
    raw: dict[str, Any] = {
        "jurisdiction": f"states/{code}",
        "year": year,
        "state_tax": _snapshot_state_tax(code, year, pack),
        **_snapshot_logistics(code, year, _resident_form(pack)),
    }
    raw["get_sources"] = _snapshot_sources(code, year)
    return raw


def snapshot_no_income_tax(knowledge: Path, year: int) -> dict[str, Any]:
    from taxfill_core.statescope import _load_no_income_tax  # noqa: PLC0415

    server = _server()
    no_tax, _ = _load_no_income_tax(knowledge)
    out: dict[str, Any] = {"year": year, "jurisdictions": {}}
    for st in sorted(no_tax):
        manifest = demo_manifest(st.lower(), year, "state return")
        out["jurisdictions"][st] = {
            "state_scope": _call(server.state_scope, demo_profiles(st, year)["resident"], year),
            "filing_summary": _call(server.filing_summary, manifest),
            "file_and_pay": _call(server.file_and_pay, manifest),
        }
    return out


# ── the lossless on-disk form ──────────────────────────────────────────────────

_REF = "@@"          # an interned string is stored as "@@<12 hex of its sha256>"
_INTERN_MIN = 80     # only strings at least this long, and only those that occur twice or more


def _walk_strings(obj: Any, fn: Callable[[str], Any]) -> Any:
    if isinstance(obj, dict):
        return {k: _walk_strings(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_strings(v, fn) for v in obj]
    if isinstance(obj, str):
        return fn(obj)
    return obj


def _jsonable(obj: Any, data_root: str) -> Any:
    """Plain JSON types, with the data root replaced by ``<data>`` (no absolute path is ever written)."""
    plain = json.loads(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=_json_default))
    return _walk_strings(plain, lambda s: s.replace(data_root, "<data>"))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not JSON-serialisable in a snapshot: {type(value).__name__}")


def _common_tail(texts: list[str]) -> str:
    if len(texts) < 2:
        return ""
    tail = texts[0]
    for text in texts[1:]:
        n = 0
        limit = min(len(tail), len(text))
        while n < limit and tail[-1 - n] == text[-1 - n]:
            n += 1
        tail = tail[len(tail) - n:]
        if not tail:
            break
    return tail


def compress(raw: dict[str, Any]) -> dict[str, Any]:
    """The on-disk form: the state_tax work tail split off, long repeated strings interned.

    ``expand(compress(raw)) == raw`` always (``build_all`` asserts it), so any change to
    any emitted value changes the file.
    """
    obj = copy.deepcopy(raw)
    calls = obj.get("state_tax")
    if isinstance(calls, list):
        results = [c for c in calls if isinstance(c.get("work"), str)]
        tail = _common_tail([c["work"] for c in results])
        common: dict[str, Any] = {}
        if len(results) > 1:
            shared = set.intersection(*(set(c) for c in results)) - {"work"}
            common = {k: results[0][k] for k in sorted(shared) if all(c[k] == results[0][k] for c in results)}
        for c in results:
            work = c.pop("work")
            for key in common:
                del c[key]
            c["work_head"] = work[: len(work) - len(tail)]
        obj["state_tax"] = {"common_result": common, "work_common_tail": tail, "calls": calls}

    counts: dict[str, int] = {}

    def count(s: str) -> str:
        if s.startswith(_REF):
            raise ValueError(f"a tool emitted a string starting with the reference marker {_REF!r}: {s[:60]!r}")
        if len(s) >= _INTERN_MIN:
            counts[s] = counts.get(s, 0) + 1
        return s

    _walk_strings(obj, count)
    table: dict[str, str] = {}
    refs: dict[str, str] = {}
    for text, n in counts.items():
        if n < 2:
            continue
        ref = _REF + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        if ref in table:
            raise ValueError(f"interned-string id collision on {ref}")
        table[ref] = text
        refs[text] = ref
    obj = _walk_strings(obj, lambda s: refs.get(s, s))
    obj["_strings"] = table
    return obj


def expand(stored: dict[str, Any]) -> dict[str, Any]:
    """The raw tool output a stored snapshot stands for (the inverse of :func:`compress`)."""
    obj = copy.deepcopy(stored)
    table = obj.pop("_strings", {})
    obj = _walk_strings(obj, lambda s: table.get(s, s) if s.startswith(_REF) else s)
    block = obj.get("state_tax")
    if isinstance(block, dict):
        tail, common = block["work_common_tail"], block["common_result"]
        calls = []
        for c in block["calls"]:
            if "work_head" in c:
                head = c.pop("work_head")
                c = {**common, **c, "work": head + tail}
            calls.append(c)
        obj["state_tax"] = calls
    return obj


def _render(raw: dict[str, Any], data_root: str) -> str:
    plain = _jsonable(raw, data_root)
    stored = compress(plain)
    if expand(stored) != plain:
        raise AssertionError("snapshot compression is not lossless — fix compress()/expand()")
    text = json.dumps(stored, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    if str(REPO) in text or data_root in text:
        raise ValueError("a snapshot still names a local path — scrub it before writing")
    return text


def build_all(
    progress: Callable[[str], None] | None = None, only: set[str] | None = None
) -> dict[str, str]:
    """Every snapshot file name -> its exact text, computed from the knowledge tree the engine reads.

    ``only`` restricts the run to those file names (a quick look at one jurisdiction-year).

    get_sources is snapshotted in every jurisdiction-year file: a state's registry block is per year
    (sources_states.yaml holds each state's newest pack, and an older year that ships a pack gets that
    year's own citations, Phase K JK27). Until then it was snapshotted in the newest-year file only.
    """
    from taxfill_core.datadir import data_root, knowledge_dir  # noqa: PLC0415

    knowledge = knowledge_dir()
    root = str(data_root().resolve())
    files: dict[str, str] = {}
    pairs = jurisdiction_years(knowledge)
    with _memoized_yaml():
        for code, year in pairs:
            name = f"{code}_{year}.json"
            if only is not None and name not in only:
                continue
            raw = snapshot_jurisdiction_year(code, year)
            files[name] = _render(raw, root)
            if progress:
                progress(name)
        if only is None or NO_INCOME_TAX_FILE in only:
            newest = max(year for _, year in pairs)
            files[NO_INCOME_TAX_FILE] = _render(snapshot_no_income_tax(knowledge, newest), root)
    return files


def _first_difference(old: Any, new: Any, path: str = "") -> str | None:
    """Dotted path of the first differing key (sorted-key order), with both values abridged."""
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
        if len(old) != len(new):
            return f"{path}: list length {len(old)} -> {len(new)}"
        return None
    if isinstance(old, str) and isinstance(new, str) and old != new:
        i = next((k for k, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
        lo = max(0, i - 50)
        return (
            f"{path}: first change at character {i}: "
            f"{_abridge(old[lo:i + 70])} -> {_abridge(new[lo:i + 70])}"
        )
    if old != new:
        return f"{path}: {_abridge(old)} -> {_abridge(new)}"
    return None


def _abridge(value: Any, width: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= width else text[: width - 3] + "..."


def drift(
    goldens_dir: Path = GOLDENS_DIR, current: dict[str, str] | None = None, only: set[str] | None = None
) -> list[str]:
    """One line per drifted, missing or stale snapshot file; empty when every snapshot matches.

    The first difference is located on the EXPANDED output, so it names the tool field that
    changed (e.g. ``state_tax[3].tax``), not an interned-string id.
    """
    current = build_all(only=only) if current is None else current
    problems: list[str] = []
    on_disk = {p.name for p in goldens_dir.glob("*.json")} if goldens_dir.is_dir() else set()
    if only is not None:
        on_disk &= only
    for name in sorted(set(current) | on_disk):
        if name not in current:
            problems.append(f"{name}: stale snapshot — no knowledge pack produces it any more")
            continue
        if name not in on_disk:
            problems.append(f"{name}: missing snapshot — run scripts/golden_snapshots.py --write")
            continue
        committed = (goldens_dir / name).read_text(encoding="utf-8")
        if committed == current[name]:
            continue
        where = _first_difference(expand(json.loads(committed)), expand(json.loads(current[name])))
        problems.append(f"{name}: drifted at {where or '(storage form only — regenerate)'}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate every snapshot")
    mode.add_argument("--check", action="store_true", help="exit 1 when any snapshot drifted")
    parser.add_argument("--only", nargs="+", metavar="FILE", help="limit --check to these snapshot files (e.g. oh_2025.json)")
    parser.add_argument("--goldens", type=Path, default=GOLDENS_DIR, help=argparse.SUPPRESS)
    ns = parser.parse_args(argv)
    if ns.write and ns.only:
        parser.error("--only is for --check; --write always regenerates every snapshot")

    only = set(ns.only) if ns.only else None
    current = build_all(only=only)
    if only is not None and only - set(current):
        parser.error(f"no knowledge pack produces: {', '.join(sorted(only - set(current)))}")
    if ns.write:
        ns.goldens.mkdir(parents=True, exist_ok=True)
        for stale in set(p.name for p in ns.goldens.glob("*.json")) - set(current):
            (ns.goldens / stale).unlink()
        for name, text in current.items():
            (ns.goldens / name).write_text(text, encoding="utf-8")
        size = sum(len(t.encode("utf-8")) for t in current.values())
        print(f"wrote {len(current)} snapshots ({size:,} bytes)")
        return 0
    problems = drift(ns.goldens, current, only)
    if problems:
        print(f"{len(problems)} state-knowledge snapshot(s) differ from the tools' output:")
        for line in problems:
            print(f"  {line}")
        print("If the change is intended, regenerate with: python scripts/golden_snapshots.py --write")
        return 1
    print(f"all {len(current)} state-knowledge snapshots match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
