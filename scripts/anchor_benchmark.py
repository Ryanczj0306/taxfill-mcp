#!/usr/bin/env python
"""JK15 / KG6: benchmark the pack-blind anchor (taxfill_core.anchor) against the shipped packs' line maps.

The anchor never sees a pack. This script runs it on each selected pack's own cached blank, then compares every
widget's ``printed_line`` with the line the pack binds that widget to, under the conservative key->line rule below.
Shipped maps have held rotations (P-031, P-032), so a disagreement is not scored against the anchor until a blind
vision adjudication says which side is right; the committed table records both the provisional numbers and,
after ``--finalize``, the adjudicated ones. The adjudication is ONE blind read per item: each item (a crop of the
row with the box outlined and the candidate lines sorted, never which side claims which) is read by exactly one
adjudicator, and the items are sharded across adjudicators; no item is read twice or reconciled.

What the table reports (Phase K JK15, 2026-10-24, round 2): the scored top tier (widgets whose pack binds a numbered
key), the unscored top-tier sample (SAMPLE_SIZE widgets the packs bind no numbered key to), and a combined
size-weighted estimate over the whole top tier, each with a 95% Wilson interval; checkbox and radio widgets are
reported apart from text boxes. The gate is the SCORED top-tier precision (>= 0.99). The per-form "any
mis-anchored" rate covers the top tier only: a form counts when a scored top-tier widget or an unscored-sample widget
is adjudicated anchor_wrong (round 4: over the text group only, like the sample). A row designator does not identify
a box on a multi-column row (taxfill_core.anchor caps those boxes below the top tier).

Round 3 (Phase K JK15, 2026-10-24): the unscored sample is drawn from, and the combined estimate computed over, the
SAMPLED_GROUPS only (text boxes), and only those groups can be licensed for the top tier (``top_tier_kinds``), so
every number beside the gate covers exactly the widgets the table can license. Checkbox and radio widgets keep their
scored numbers (``top_by_kind``). taxfill_core.anchor enforces its row-identification invariant (its module doc).

Key -> line rule (KEY_RULE; tested in test_anchor_benchmark.py). A key scores as a printed line only in these shapes:

    "21", "5a"            -> the line itself (1-3 digits, optional ONE lowercase letter; leading zeros dropped)
    "line_21", "line21a"  -> the line after the "line" prefix
    "21.col_b"            -> line 21 (a column of that row: "<line>.col_<x>")

Every other shape is excluded (the widget is unscored for that key): sub-fields and row/cell indexes
("dependents.1.ssn", "14.r1.a", "5.cont1", "22a.ein.1", "7.2013"), yes/no and named options ("8.yes",
"filing_status.single", "17.standard"), suffixed keys ("20_amount", "10c_ssn", "line15_d01"), upper-case or
two-letter designators ("5A", "C11_A", "10ab_more_space"), prefixed schedules ("s1.7a", "schedule_e.4a") and
coded keys ("SCHAATCLN1"). A widget's truth is the set of lines of EVERY numbered key bound to its field (one value
fills every widget of a field); a checkbox key with an on_state binds only the widgets that carry that on-state.

Carry-forward boxes: a box whose caption repeats another line ("Amount from line 11" at the top of page 2) is
anchored by its own row's designator only; the "11" inside the caption is caption text, never its printed_line.
When the pack binds it under line 11's key (the same field as line 11, or a mirror key that matches the rule), its
truth is {11}: the anchor then emits no printed_line for it (unscored), or the row's own designator ("11b") if the
form prints one, which scores against the key exactly like any other row.

Modes (``--out`` is a scratch directory OUTSIDE the repo for crops and the disagreement files):

    anchor_benchmark.py --select              # write knowledge/anchor/selection.yaml (once; then frozen)
    anchor_benchmark.py --dev [--out DIR]     # tune: DEV only, prints the report, never touches TEST
    anchor_benchmark.py --test --out DIR --note "..." [--event "..."]   # the measured TEST run: counts in
                                              # test_runs, writes the table (passed: false) + disagreements/crops/
                                              # unscored sample; each --event adds a history entry that is not a run
                                              # (a fix to the scoring or the join made since the last run)
    anchor_benchmark.py --finalize --out DIR  # join knowledge/anchor/adjudications.yaml, write the final table
    anchor_benchmark.py --check               # recompute from the cache; exit 1 on any drift from the table

Every TEST run is counted in the table's ``test_runs``; a method change after a TEST run must be recorded in its
``history`` with what changed (``--note``). --finalize and --check recompute the same deterministic run and do not
count as new TEST runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))

from taxfill_core import anchor as A  # noqa: E402
from taxfill_core.datadir import home_display, knowledge_dir  # noqa: E402
from taxfill_core.fetch import _cache_path, default_cache_dir  # noqa: E402
from taxfill_core.packbuild import extract_fields  # noqa: E402
from taxfill_core.schemas.formpack import load_pack  # noqa: E402

ANCHOR_DIR = knowledge_dir() / "anchor"
TABLE = ANCHOR_DIR / "benchmark.yaml"
SELECTION = ANCHOR_DIR / "selection.yaml"
ADJUDICATIONS = ANCHOR_DIR / "adjudications.yaml"
MANDATORY_DIR = ANCHOR_DIR / "mandatory"

# The candidate tier thresholds this method is measured with; the table records them and anchor.py reads them
# back from the table only once it has passed.
THRESHOLDS = {"top": 3.0, "med": 2.0}
# the tier_for argument the benchmark measures with: every widget group at the candidate thresholds (licensing fails
# closed in taxfill_core.anchor, so the groups are named; the table then licenses groups from the measurement)
MEASURE_THRESHOLDS = {**THRESHOLDS, "top_kinds": frozenset(("text", "checkbox"))}
MIN_SCORABLE = 15
SPLIT_SALT = "jk15-split-v1"
SAMPLE_SEED = 20261024
SAMPLE_SIZE = 48
WILSON_Z = 1.959964  # 95%
CHECKBOX_KINDS = ("checkbox", "radio")
# Phase K JK15 round 3 (2026-10-24): the widget groups the unscored sample and the combined estimate cover; only
# these can be licensed for the top tier, so the estimates beside the gate cover exactly the licensable widgets.
SAMPLED_GROUPS = ("text",)
CROP_DPI = 150
CROP_MARGIN = 60.0

KEY_RULE = (
    re.compile(r"^0*(\d{1,3})([a-z])?$"),
    re.compile(r"^line_?0*(\d{1,3})([a-z])?$"),
    re.compile(r"^0*(\d{1,3})([a-z])?\.col_[a-z0-9]+$"),
)


def key_line(key: str) -> str | None:
    """The printed line a pack key scores as (see KEY_RULE in the module doc), or None when it does not score."""
    for pattern in KEY_RULE:
        m = pattern.match(key)
        if m and int(m.group(1)) > 0:
            return f"{int(m.group(1))}{m.group(2) or ''}"
    return None


def line_sort_key(line: str) -> tuple[int, str]:
    m = re.match(r"^(\d+)(.*)$", line)
    return (int(m.group(1)), m.group(2)) if m else (10**6, line)


def wilson(k: int, n: int) -> list[float] | None:
    """The 95% Wilson score interval for k right of n (None when n is 0)."""
    if n <= 0:
        return None
    z2 = WILSON_Z * WILSON_Z
    p = k / n
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = WILSON_Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def kind_group(kind: str) -> str:
    return "checkbox" if kind in CHECKBOX_KINDS else "text"


# ── packs, blanks, truth ─────────────────────────────────────────────────────


def pack_id(path: Path) -> str:
    return path.parent.relative_to(REPO / "formpacks").as_posix()


def family_of(pid: str) -> str:
    parts = pid.split("/")
    return f"federal/{parts[2]}" if parts[0] == "federal" else f"states/{parts[1]}/{parts[3]}"


def cached_blank(url: str) -> Path | None:
    path = _cache_path(default_cache_dir(), url)
    return path if path.is_file() else None


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def truth_map(keys: list[dict], widgets: list[dict], root: str) -> dict[tuple[str, int], set[str]]:
    """(qualified field, widget index) -> the lines its numbered keys claim.

    ``keys``: {"key", "field", "on_state"?, "line"?}; "line" overrides KEY_RULE (the mandatory fixtures' explicit
    claims for shapes such as "20_amount").
    """
    index: dict[str, list[tuple[int, dict]]] = {}
    counts: Counter = Counter()
    for w in widgets:
        index.setdefault(w["name"], []).append((counts[w["name"]], w))
        counts[w["name"]] += 1
    out: dict[tuple[str, int], set[str]] = {}
    for k in keys:
        line = k.get("line") or key_line(str(k["key"]))
        if line is None:
            continue
        name = f"{root}.{k['field']}" if root else k["field"]
        targets = index.get(name, [])
        if k.get("on_state"):
            narrowed = [(i, w) for i, w in targets if k["on_state"] in (w.get("on_states") or [])]
            targets = narrowed or targets
        for i, _ in targets:
            out.setdefault((name, i), set()).add(line)
    return out


def pack_keys(pack) -> list[dict]:
    return [{"key": f.line, "field": f.field, "on_state": f.on_state} for f in pack.fields]


# ── selection ────────────────────────────────────────────────────────────────


def select() -> dict:
    families: dict[str, list[Path]] = {}
    for path in sorted((REPO / "formpacks").glob("**/pack.yaml")):
        families.setdefault(family_of(pack_id(path)), []).append(path)
    chosen = []
    skipped = Counter()
    for fam, paths in sorted(families.items()):
        for path in sorted(paths, key=lambda p: pack_id(p), reverse=True):
            try:
                pack = load_pack(path)
            except Exception:  # noqa: BLE001 — a hand-fill or other non-AcroForm pack
                skipped["not_a_form_pack"] += 1
                break
            blank = cached_blank(pack.source_url)
            if blank is None or sha256_of(blank) != pack.pdf_sha256:
                skipped["blank_not_cached"] += 1
                continue
            widgets = extract_fields(blank)
            scorable = len(truth_map(pack_keys(pack), widgets, pack.acroform_root))
            if scorable >= MIN_SCORABLE:
                chosen.append({"family": fam, "pack": pack_id(path), "year": pack.tax_year,
                               "pdf_sha256": pack.pdf_sha256, "scorable": scorable})
                break
            skipped["under_min_scorable"] += 1
    dev, test = [], []
    for item in chosen:
        h = hashlib.sha256(f"{SPLIT_SALT}:{item['family']}".encode()).hexdigest()
        (test if int(h[:8], 16) % 2 == 0 else dev).append(item)
    return {"min_scorable": MIN_SCORABLE, "split_salt": SPLIT_SALT, "families": len(families),
            "skipped": dict(sorted(skipped.items())), "dev": dev, "test": test}


def load_selection() -> dict:
    if not SELECTION.is_file():
        raise SystemExit("no knowledge/anchor/selection.yaml — run scripts/anchor_benchmark.py --select first")
    return yaml.safe_load(SELECTION.read_text(encoding="utf-8"))


# ── scoring ──────────────────────────────────────────────────────────────────


@dataclass
class Scored:
    pack: str
    blank: Path
    widget: A.WidgetAnchor
    tier: str
    truth: set[str]
    mandatory: bool = False

    @property
    def id(self) -> str:
        return f"{self.pack}:p{self.widget.page}:{self.widget.field}:w{self.widget.widget_index}"

    @property
    def status(self) -> str:
        if not self.widget.printed_line:
            return "no_line"
        if not self.truth:
            return "unscored"
        return "agree" if self.widget.printed_line in self.truth else "disagree"


@dataclass
class PackRun:
    pack: str
    blank: Path
    rows: list[Scored] = field(default_factory=list)


def tier_of(w: A.WidgetAnchor) -> str:
    return A.tier_for(w, MEASURE_THRESHOLDS)


def run_pack(pid: str, keys: list[dict] | None = None, url: str | None = None, sha: str | None = None,
             root: str | None = None, mandatory: bool = False) -> PackRun:
    if keys is None:
        pack = load_pack(REPO / "formpacks" / pid / "pack.yaml")
        keys, url, sha, root = pack_keys(pack), pack.source_url, pack.pdf_sha256, pack.acroform_root
    blank = cached_blank(url)
    if blank is None or sha256_of(blank) != sha:
        raise SystemExit(f"{pid}: its blank ({url}) is not in the blank cache with sha256 {sha[:16]} — set "
                         f"TAXFILL_BLANKS_CACHE or fetch it (taxfill fetch-blank) and rerun")
    anchors = A.raw_anchors(blank)
    widgets = extract_fields(blank)
    truth = truth_map(keys, widgets, root or "")
    run = PackRun(pack=pid, blank=blank)
    for w in anchors:
        if "not_an_entry" in w.evidence:
            continue
        run.rows.append(Scored(pack=pid, blank=blank, widget=w, tier=tier_of(w),
                               truth=truth.get((w.field, w.widget_index), set()), mandatory=mandatory))
    return run


def report(runs: list[PackRun]) -> dict:
    tiers = {}
    for t in A.TIERS:
        rows = [r for run in runs for r in run.rows if r.tier == t]
        c = Counter(r.status for r in rows)
        scored = c["agree"] + c["disagree"]
        tiers[_tier_key(t)] = {
            "emitted": len(rows), "scored": scored, "agree": c["agree"], "disagree": c["disagree"],
            "unscored": len(rows) - scored,
            "provisional_precision": round(c["agree"] / scored, 4) if scored else None,
            "wilson_95": wilson(c["agree"], scored),
        }
    top_by_kind = {}
    for group in ("text", "checkbox"):
        rows = [r for run in runs for r in run.rows if r.tier == A.TOP and kind_group(r.widget.kind) == group]
        c = Counter(r.status for r in rows)
        scored = c["agree"] + c["disagree"]
        top_by_kind[group] = {"emitted": len(rows), "scored": scored, "agree": c["agree"],
                              "provisional_precision": round(c["agree"] / scored, 4) if scored else None,
                              "wilson_95": wilson(c["agree"], scored)}
    missed = sum(1 for run in runs for r in run.rows if r.truth and not r.widget.printed_line)
    with_truth = sum(1 for run in runs for r in run.rows if r.truth)
    # Phase K JK15 round 4 (2026-10-24): the per-form rate covers the licensable groups (text), like the sample
    top_forms = [run for run in runs
                 if any(r.tier == A.TOP and r.status == "disagree" and _sampled(r) for r in run.rows)]
    with_top = [run for run in runs if any(r.tier == A.TOP and _sampled(r) for r in run.rows)]
    return {
        "packs": len(runs),
        "federal": sum(1 for r in runs if r.pack.startswith("federal/")),
        "state": sum(1 for r in runs if r.pack.startswith("states/")),
        "states_distinct": len({r.pack.split("/")[1] for r in runs if r.pack.startswith("states/")}),
        "tiers": tiers,
        "top_by_kind": top_by_kind,
        "forms_with_a_mis_anchored_top_widget": len(top_forms),
        "per_form_any_mis_anchored_top_rate": round(len(top_forms) / len(with_top), 4) if with_top else None,
        "forms_with_top_tier": len(with_top),
        "widgets_with_truth": with_truth,
        "widgets_with_truth_but_no_printed_line": missed,
    }


def _sampled(r: Scored) -> bool:
    """The widget belongs to a group the table can license (SAMPLED_GROUPS: text boxes)."""
    return kind_group(r.widget.kind) in SAMPLED_GROUPS


def _tier_key(t: str) -> str:
    return {A.TOP: "top", A.MED: "med", A.LOW: "low", A.NONE: "none"}[t]


def print_report(name: str, rep: dict) -> None:
    print(f"== {name}: {rep['packs']} packs ({rep['federal']} federal, {rep['state']} state from "
          f"{rep['states_distinct']} states)")
    for t, v in rep["tiers"].items():
        print(f"  {t:5s} emitted {v['emitted']:6d} scored {v['scored']:6d} agree {v['agree']:6d} "
              f"disagree {v['disagree']:5d} precision {v['provisional_precision']} wilson95 {v.get('wilson_95')}")
    for group, v in (rep.get("top_by_kind") or {}).items():
        print(f"  top/{group:8s} emitted {v['emitted']:6d} scored {v['scored']:6d} agree {v['agree']:6d} "
              f"precision {v['provisional_precision']} wilson95 {v['wilson_95']}")
    print(f"  forms with a mis-anchored top-tier widget: {rep['forms_with_a_mis_anchored_top_widget']} of "
          f"{rep['forms_with_top_tier']} ({rep['per_form_any_mis_anchored_top_rate']})")
    print(f"  widgets with truth {rep['widgets_with_truth']}, of which no printed line "
          f"{rep['widgets_with_truth_but_no_printed_line']}")


# ── mandatory cases (KG6) ────────────────────────────────────────────────────


def load_mandatory() -> list[dict]:
    cases = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(MANDATORY_DIR.glob("*.yaml"))]
    if {c["case"] for c in cases} != {"me_1040me_2023", "al_form40_2023"}:
        raise SystemExit("knowledge/anchor/mandatory/ must hold exactly the ME 1040ME 2023 and AL Form 40 2023 cases")
    return cases


def run_mandatory(case: dict) -> tuple[PackRun, dict]:
    run = run_pack(f"mandatory/{case['case']}", keys=case["keys"], url=case["source_url"], sha=case["pdf_sha256"],
                   root=case.get("acroform_root") or "", mandatory=True)
    field_of = {str(k["key"]): k["field"] for k in case["keys"]}
    claim_of = {str(k["key"]): k.get("line") or key_line(str(k["key"])) for k in case["keys"]}
    root = case.get("acroform_root") or ""
    flagged, missed = [], []
    for key in case["must_flag"]:
        name = f"{root}.{field_of[key]}" if root else field_of[key]
        rows = [r for r in run.rows if r.widget.field == name]
        bad = [r for r in rows if r.widget.printed_line and r.widget.printed_line != claim_of[key]]
        (flagged if rows and len(bad) == len(rows) else missed).append(
            {"key": key, "claims": claim_of[key], "anchor": sorted({r.widget.printed_line or "-" for r in rows})})
    return run, {"must_flag": len(case["must_flag"]), "flagged": len(flagged), "missed": missed,
                 "all_flagged": not missed, "detail": flagged}


# ── disagreements, crops, the unscored sample ───────────────────────────────


def _crop_name(item_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", item_id)[:100]
    return f"{slug}-{hashlib.sha256(item_id.encode()).hexdigest()[:10]}.png"


def render_crop(blank: Path, page: int, rect: list[float], out: Path) -> None:
    """The row band plus CROP_MARGIN pt above and below, full page width, the widget outlined in red."""
    import ctypes

    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    from PIL import ImageDraw

    doc = pdfium.PdfDocument(str(blank))
    try:
        pg = doc[page - 1]
        scale = CROP_DPI / 72.0
        img = pg.render(scale=scale, may_draw_forms=False).to_pil().convert("RGB")
        w, h = img.size
        pts = []
        for x, y in ((rect[0], rect[1]), (rect[2], rect[3]), (rect[0], rect[3]), (rect[2], rect[1])):
            dx, dy = ctypes.c_int(), ctypes.c_int()
            pdfium_c.FPDF_PageToDevice(pg.raw, 0, 0, w, h, 0, ctypes.c_double(x), ctypes.c_double(y),
                                       ctypes.byref(dx), ctypes.byref(dy))
            pts.append((dx.value, dy.value))
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        margin = int(CROP_MARGIN * scale)
        top, bottom = max(0, y0 - margin), min(h, y1 + margin)
        ImageDraw.Draw(img).rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline=(255, 0, 0), width=3)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.crop((0, top, w, bottom)).save(out)
    finally:
        doc.close()


def item_of(r: Scored, crops: Path | None, candidates: list[str], split: str) -> dict:
    w = r.widget
    crop = crops / _crop_name(r.id) if crops is not None else None
    return {"id": r.id, "pack": r.pack, "split": split, "mandatory": r.mandatory, "blank": home_display(r.blank),
            "page": w.page, "field": w.field, "widget_index": w.widget_index, "rect": w.rect,
            "crop": home_display(crop) if crop is not None else None, "candidates": candidates}


def key_of(r: Scored) -> dict:
    w = r.widget
    return {"anchor_line": w.printed_line, "pack_lines": sorted(r.truth, key=line_sort_key), "tier": r.tier,
            "score": w.score, "evidence": w.evidence, "label": w.label}


def disagreement_rows(test_runs: list[PackRun], mandatory_runs: list[PackRun]) -> list[tuple[Scored, str]]:
    rows = [(r, "test") for run in test_runs for r in run.rows if r.status == "disagree"]
    rows += [(r, "mandatory") for run in mandatory_runs for r in run.rows if r.status == "disagree"]
    return sorted(rows, key=lambda t: t[0].id)


def unscored_sample(test_runs: list[PackRun]) -> list[Scored]:
    pool = sorted((r for run in test_runs for r in run.rows if r.tier == A.TOP and r.status == "unscored"
                   and kind_group(r.widget.kind) in SAMPLED_GROUPS), key=lambda r: r.id)
    k = min(SAMPLE_SIZE, len(pool))
    return sorted(random.Random(SAMPLE_SEED).sample(pool, k), key=lambda r: r.id)


# ── the table ────────────────────────────────────────────────────────────────


def _digest(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16]


def load_adjudications() -> dict:
    if not ADJUDICATIONS.is_file():
        return {"items": [], "unscored_sample": []}
    data = yaml.safe_load(ADJUDICATIONS.read_text(encoding="utf-8")) or {}
    return {"items": data.get("items") or [], "unscored_sample": data.get("unscored_sample") or []}


def _seen(entry: dict) -> str | None:
    """An adjudicator's seen_line normalised the way the anchor normalises a printed designator ("6C" -> "6c"), so the
    join compares designators, not spellings (Phase K JK15 finalize fix, 2026-10-24: "6C" was scored against "6c")."""
    raw = entry.get("seen_line")
    if raw is None:
        return None
    return A.normalize_line(str(raw)) or str(raw)


def adjudicate(test_runs: list[PackRun], dis: list[tuple[Scored, str]], sample: list[Scored], adj: dict) -> dict:
    """Join the blind adjudications onto the recomputed disagreements (see the module doc).

    A widget the adjudicator reads as the anchor's line counts right, and its id goes in
    ``pack_keys_not_the_printed_line``: the pack's key is not the designator printed on that row. That is either a
    mis-bind (the mandatory ME and AL maps) or a key that names something else, such as a column (DE PIT-RES and
    PIT-NON key column A of line N as "Na"); the benchmark does not tell the two apart, JK10 does.
    """
    by_id = {e["id"]: e for e in adj["items"]}
    verdict: dict[str, str] = {}
    pack_wrong = []
    for r, _split in dis:
        e = by_id.get(r.id)
        if e is None:
            verdict[r.id] = "unadjudicated"
        elif e.get("ambiguous"):
            verdict[r.id] = "ambiguous"
        elif _seen(e) is not None and _seen(e) == r.widget.printed_line:
            verdict[r.id] = "anchor_right"
            pack_wrong.append(r.id)
        else:
            verdict[r.id] = "anchor_wrong"
    def _counts(rows: list[Scored]) -> dict:
        c = Counter("agree" if r.status == "agree" else verdict[r.id] for r in rows)
        right = c["agree"] + c["anchor_right"]
        denom = right + c["anchor_wrong"]
        return {"scored": len(rows), "right": right, "wrong": c["anchor_wrong"], "ambiguous": c["ambiguous"],
                "unadjudicated": c["unadjudicated"], "precision": round(right / denom, 4) if denom else None,
                "wilson_95": wilson(right, denom)}

    tiers = {}
    for t in A.TIERS:
        rows = [r for run in test_runs for r in run.rows if r.tier == t and r.status in ("agree", "disagree")]
        tiers[_tier_key(t)] = _counts(rows)
    top_scored = [r for run in test_runs for r in run.rows if r.tier == A.TOP and r.status in ("agree", "disagree")]
    top_by_kind = {g: _counts([r for r in top_scored if kind_group(r.widget.kind) == g]) for g in ("text", "checkbox")}
    # Phase K JK15 round 4 (2026-10-24): over the licensable groups (text) only, like the sample and the estimate
    forms_bad = {r.pack for r, _ in dis if r.tier == A.TOP and _sampled(r) and verdict[r.id] == "anchor_wrong"}
    forms_top = {run.pack for run in test_runs if any(r.tier == A.TOP and _sampled(r) for r in run.rows)}
    s_by_id = {e["id"]: e for e in adj["unscored_sample"]}
    sc = Counter()
    for r in sample:
        e = s_by_id.get(r.id)
        if e is None:
            sc["unadjudicated"] += 1
        elif e.get("ambiguous"):
            sc["ambiguous"] += 1
        elif _seen(e) is not None and _seen(e) == r.widget.printed_line:
            sc["right"] += 1
        else:
            sc["wrong"] += 1
            forms_bad.add(r.pack)  # an unscored-sample widget read as anchor_wrong is a mis-anchored top-tier widget
    s_denom = sc["right"] + sc["wrong"]
    population = sum(1 for run in test_runs for r in run.rows if r.tier == A.TOP and r.status == "unscored"
                     and kind_group(r.widget.kind) in SAMPLED_GROUPS)
    top = _counts([r for r in top_scored if kind_group(r.widget.kind) in SAMPLED_GROUPS])
    s_right_wrong = top["right"] + top["wrong"]
    combined = None
    if s_right_wrong and s_denom:
        w_s = s_right_wrong / (s_right_wrong + population)
        w_u = 1.0 - w_s
        lo_s, hi_s = wilson(top["right"], s_right_wrong)
        lo_u, hi_u = wilson(sc["right"], s_denom)
        combined = {
            "groups": list(SAMPLED_GROUPS), "scored_n": s_right_wrong, "unscored_population": population,
            "weights": {"scored": round(w_s, 4), "unscored": round(w_u, 4)},
            "precision": round(w_s * top["right"] / s_right_wrong + w_u * sc["right"] / s_denom, 4),
            "wilson_95": [round(w_s * lo_s + w_u * lo_u, 4), round(w_s * hi_s + w_u * hi_u, 4)],
            "how": "each stratum's precision weighted by its size in the top tier; the interval is the same "
                   "size-weighted mix of the two strata's 95% Wilson bounds (conservative)",
        }
    return {
        "adjudicated": sum(1 for v in verdict.values() if v != "unadjudicated"),
        "unadjudicated": sum(1 for v in verdict.values() if v == "unadjudicated"),
        "tiers": tiers,
        "top_by_kind": top_by_kind,
        "per_form_any_mis_anchored_top_rate": round(len(forms_bad) / len(forms_top), 4) if forms_top else None,
        "forms_with_top_tier": len(forms_top),
        "forms_with_a_mis_anchored_top_widget": sorted(forms_bad),
        "pack_keys_not_the_printed_line": sorted(pack_wrong),
        "unscored_sample": {"groups": list(SAMPLED_GROUPS), "size": len(sample), "population": population,
                            "right": sc["right"], "wrong": sc["wrong"],
                            "ambiguous": sc["ambiguous"], "unadjudicated": sc["unadjudicated"],
                            "precision": round(sc["right"] / s_denom, 4) if s_denom else None,
                            "wilson_95": wilson(sc["right"], s_denom)},
        "combined_top_estimate": combined,
    }


def measure(sel: dict) -> tuple[dict, list[PackRun], list[PackRun], list[PackRun]]:
    dev_runs = [run_pack(item["pack"]) for item in sel["dev"]]
    test_runs = [run_pack(item["pack"]) for item in sel["test"]]
    mandatory_runs, mandatory = [], {}
    for case in load_mandatory():
        run, result = run_mandatory(case)
        mandatory_runs.append(run)
        mandatory[case["case"]] = result
    dis = disagreement_rows(test_runs, mandatory_runs)
    sample = unscored_sample(test_runs)
    measured = {
        "selection_sha256": hashlib.sha256(SELECTION.read_bytes()).hexdigest()[:16],
        "selection_disclosure": sel.get("disclosure"),
        "test": report(test_runs),
        "dev": report(dev_runs),
        "mandatory": mandatory,
        "disagreements": {"count": len(dis), "test": sum(1 for _, s in dis if s == "test"),
                          "mandatory": sum(1 for _, s in dis if s == "mandatory"),
                          "ids_sha256": _digest([r.id for r, _ in dis])},
        "unscored_sample": {"size": len(sample), "seed": SAMPLE_SEED, "ids_sha256": _digest([r.id for r in sample])},
    }
    return measured, dev_runs, test_runs, mandatory_runs


def build_table(measured: dict, adjudication: dict | None, meta: dict) -> dict:
    test = measured["test"]
    criteria = {
        "test_packs_at_least_30": test["packs"] >= 30,
        "test_federal_at_least_10": test["federal"] >= 10,
        "test_state_at_least_20_from_12_states": test["state"] >= 20 and test["states_distinct"] >= 12,
        "mandatory_cases_flagged": all(m["all_flagged"] for m in measured["mandatory"].values()),
        "every_disagreement_adjudicated": bool(adjudication) and adjudication["unadjudicated"] == 0,
        "scored_top_tier_precision_at_least_0.99": bool(adjudication)
        and (adjudication["tiers"]["top"]["precision"] or 0) >= 0.99,
    }
    by_kind = (adjudication or {}).get("top_by_kind") or {}
    top_kinds = sorted(k for k, v in by_kind.items()
                       if k in SAMPLED_GROUPS and v.get("scored") and (v.get("precision") or 0) >= 0.99)
    return {
        "schema": 1,
        "method": A.METHOD,
        "thresholds": dict(THRESHOLDS),
        "top_tier_kinds": top_kinds,
        "passed": all(criteria.values()),
        "adjudicated": adjudication["adjudicated"] if adjudication else 0,
        "test_runs": meta["test_runs"],
        "history": meta["history"],
        "criteria": criteria,
        "key_rule": [
            '"21", "5a" (1-3 digits, one lowercase letter) score as themselves',
            '"line_21", "line21a" score as the line after "line"',
            '"21.col_b" scores as line 21',
            "every other key shape is unscored (see scripts/anchor_benchmark.py)",
        ],
        "notes": TABLE_NOTES,
        "measured": measured,
        "adjudication": adjudication,
    }


TABLE_NOTES = [
    "Known limits (the fourth review, 2026-10-24): a designator that a second schedule on the page prints again with "
    "no box beside that copy is not counted, so Wisconsin Form 1 page 4's Schedule 1 line 7 and Schedule 2 line 8 "
    "keep the top tier although the other schedule prints a line 7 and a line 8 as preprinted rates; widgets hidden "
    "by their annotation flags (/F Hidden or NoView) are anchored like any other, and the pack-less fill (JK16) must "
    "refuse them; text outside a page's crop box is read (no wrong anchor in the cache comes of it).",
    "The gate is the SCORED top-tier precision: top-tier widgets whose pack binds a numbered key, after the blind "
    "adjudication of every disagreement (>= 0.99). The unscored top-tier sample and the combined size-weighted "
    "estimate (each with a 95% Wilson interval) are reported beside it, not gated; both cover text boxes only "
    "(unscored_sample.groups, combined_top_estimate.groups), the only group the table can license.",
    "Checkbox and radio widgets are reported apart from text boxes (top_by_kind); the gate covers both, and the top "
    "tier is licensed per group: top_tier_kinds lists the text group when its scored top-tier precision is >= 0.99 "
    "(checkbox and radio widgets are never licensed: run 2 measured checkboxes 10/11, and the sample does not cover "
    "them), and taxfill_core.anchor caps every other group at 'med'. A table of this method whose top_tier_kinds is "
    "missing or not a list licenses no group for the top tier.",
    "Row identification (method jk15-v3): a printed designator names a row, and a fill by line number needs it to "
    "name a box. taxfill_core.anchor gives a widget the top tier only when (i) no fillable text box of any other field "
    "shares its row band, or (ii) every fillable text box in that row band, its own included, carries its own "
    "printed_line, all distinct, each read from the designator printed immediately before the box (beside evidence, "
    "not a gutter number or a /TU alone): the 1040 '2a [box] b ... 2b [box]' row. Every other widget caps at 'med' "
    "with a shared_row:<field> evidence entry (Georgia 500 line 14's count box, the 1040-X line 23 year box).",
    "The per-form 'any mis-anchored' rate covers the top tier of the licensable group (text boxes) only, like the "
    "sample and the combined estimate: a form counts in the denominator when it has a top-tier text box, and in the "
    "numerator when a scored top-tier text box or an unscored-sample widget is adjudicated anchor_wrong.",
    "One-to-one rule (method jk15-v4): a designator must map to one box on its page. taxfill_core.anchor gives a "
    "widget the top tier only when no other field's fillable box on the page (text, choice or unknown kind) carries "
    "the same printed_line at any score, has that designator printed immediately before it (even when it got no "
    "line), or names that line through its /TU or field name; else it caps at 'med' with same_line:<field> "
    "(Wisconsin Form 1 line 30's count box above the line-30 amount box, Form 2555's description boxes above their "
    "amount boxes, Wisconsin 2023 line 15a's rent box beside the '15a' credit box).",
    "The adjudication is one blind read per item: each crop is read by exactly one adjudicator, sharded across "
    "adjudicators, with the candidate lines sorted and never which side claims which.",
    "A row designator does not identify a box on a multi-column row (Delaware prints 'N.' before the spouse's "
    "Column A and again before Column B), nor a designator printed once per Part on one page (Alabama 40NR "
    "page 2): taxfill_core.anchor caps those boxes below the top tier.",
    "Selection: sibling forms of one return can sit on opposite sides of the DEV/TEST split, and both mandatory "
    "cases belong to DEV families; measured.selection_disclosure lists them.",
]


TABLE_HEADER = """\
# Phase K JK15 (2026-10-24): the KG6 accuracy table for the pack-blind anchor (taxfill_core.anchor), written by
# scripts/anchor_benchmark.py; do not edit by hand. taxfill_core.anchor reads `thresholds` from this file ONLY when
# `passed` is true and `method` matches its METHOD; otherwise it emits nothing above "low". `measured` holds the
# provisional numbers (a disagreement with a pack counts against the anchor until adjudicated); `adjudication` holds
# the numbers after the blind vision adjudication in adjudications.yaml (--finalize): one blind read per item,
# sharded across adjudicators. The gate is the scored top-tier precision; `notes` says what each number covers.
# A top-tier anchor is worded "anchored (unverified line map)": it is still not a verified line map.
"""


def write_table(table: dict) -> None:
    TABLE.write_text(TABLE_HEADER + yaml.safe_dump(table, sort_keys=False, width=120, allow_unicode=True),
                     encoding="utf-8")


def write_outputs(out: Path, dis: list[tuple[Scored, str]], sample: list[Scored]) -> None:
    crops = out / "crops"
    items, key = [], {}
    for r, split in dis:
        cands = sorted({r.widget.printed_line, *r.truth}, key=line_sort_key)
        items.append(item_of(r, crops, cands, split))
        key[r.id] = key_of(r)
        render_crop(r.blank, r.widget.page, r.widget.rect, crops / _crop_name(r.id))
    s_items, s_key = [], {}
    for r in sample:
        s_items.append(item_of(r, crops, [], "test"))
        s_key[r.id] = key_of(r)
        render_crop(r.blank, r.widget.page, r.widget.rect, crops / _crop_name(r.id))
    out.mkdir(parents=True, exist_ok=True)
    (out / "disagreements.json").write_text(json.dumps({"items": items}, indent=1) + "\n", encoding="utf-8")
    (out / "unscored_sample.json").write_text(json.dumps({"items": s_items}, indent=1) + "\n", encoding="utf-8")
    (out / "disagreements_key.json").write_text(json.dumps({"items": key, "unscored_sample": s_key}, indent=1) + "\n",
                                                encoding="utf-8")


def _comparable(table: dict) -> dict:
    return {k: v for k, v in table.items() if k not in ("history", "test_runs")}


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--select", action="store_true")
    mode.add_argument("--dev", action="store_true")
    mode.add_argument("--test", action="store_true")
    mode.add_argument("--finalize", action="store_true")
    mode.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--note", default="")
    ap.add_argument("--event", action="append", default=[],
                    help="with --test: a history entry that is not a run (a scoring or join fix made since the last run)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.select:
        sel = select()
        ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
        SELECTION.write_text(yaml.safe_dump(sel, sort_keys=False, width=120), encoding="utf-8")
        print(f"selection: {len(sel['dev'])} DEV, {len(sel['test'])} TEST packs from {sel['families']} families")
        return 0
    sel = load_selection()
    if args.dev:
        runs = [run_pack(item["pack"]) for item in sel["dev"]]
        rep = report(runs)
        print_report("DEV", rep)
        hist: dict[float, Counter] = {}
        for run in runs:
            for r in run.rows:
                if r.widget.printed_line:
                    hist.setdefault(r.widget.score, Counter())[r.status] += 1
        for sc in sorted(hist, reverse=True):
            c = hist[sc]
            print(f"  score {sc:5.2f}: agree {c['agree']:5d} disagree {c['disagree']:4d} unscored {c['unscored']:5d}")
        sig: dict[str, Counter] = {}
        for run in runs:
            for r in run.rows:
                if r.widget.printed_line:
                    key = f"{r.widget.score:4.1f} " + "+".join(sorted({e.split(':')[0] for e in r.widget.evidence}))
                    sig.setdefault(key, Counter())[r.status] += 1
        if args.verbose:
            for k in sorted(sig, reverse=True):
                c = sig[k]
                print(f"  {k:70s} agree {c['agree']:5d} disagree {c['disagree']:4d} unscored {c['unscored']:5d}")
        if args.verbose or args.out:
            dis = [r for run in runs for r in run.rows if r.status == "disagree"]
            dis.sort(key=lambda r: (-r.widget.score, r.pack))
            lines = [f"{r.tier[:4]} {r.widget.score} {r.id} anchor={r.widget.printed_line} pack={sorted(r.truth)} "
                     f"ev={r.widget.evidence} label={(r.widget.label or '')[:60]!r}" for r in dis]
            miss = [r for run in runs for r in run.rows if r.truth and not r.widget.printed_line]
            lines += [f"MISS {r.id} pack={sorted(r.truth)} ev={r.widget.evidence} label={(r.widget.label or '')[:60]!r}"
                      for r in miss]
            if args.out:
                args.out.mkdir(parents=True, exist_ok=True)
                (args.out / "dev_disagreements.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            if args.verbose:
                print("\n".join(lines))
        return 0
    old = yaml.safe_load(TABLE.read_text(encoding="utf-8")) if TABLE.is_file() else None
    if args.test:
        if args.out is None:
            raise SystemExit("--test needs --out DIR (a scratch directory outside the repo) for the crops")
        runs_so_far = (old or {}).get("test_runs", 0)
        if runs_so_far and not args.note:
            raise SystemExit("a TEST run is already counted in the table: say what changed with --note")
        measured, _, test_runs, mandatory_runs = measure(sel)
        events = [{"event": text, "date": date.today().isoformat()} for text in args.event]
        meta = {"test_runs": runs_so_far + 1, "history": [*((old or {}).get("history") or []), *events, {
            "run": runs_so_far + 1, "date": date.today().isoformat(), "method": A.METHOD,
            "thresholds": dict(THRESHOLDS),
            "note": args.note or "first measured TEST run"}]}
        dis = disagreement_rows(test_runs, mandatory_runs)
        sample = unscored_sample(test_runs)
        write_outputs(args.out, dis, sample)
        write_table(build_table(measured, None, meta))
        print_report("TEST", measured["test"])
        print_report("DEV", measured["dev"])
        print(f"mandatory: {json.dumps({k: v['all_flagged'] for k, v in measured['mandatory'].items()})}")
        print(f"disagreements: {len(dis)}; unscored sample: {len(sample)}; table: knowledge/anchor/benchmark.yaml")
        return 0
    if old is None:
        raise SystemExit("no knowledge/anchor/benchmark.yaml yet — run --test first")
    adj = load_adjudications()
    measured, _, test_runs, mandatory_runs = measure(sel)
    dis = disagreement_rows(test_runs, mandatory_runs)
    sample = unscored_sample(test_runs)
    adjudication = None
    if (adj["items"] or adj["unscored_sample"]) and (args.finalize or old.get("adjudication") is not None):
        # --check of a table written by --test (not yet finalized) recomputes the measured numbers only
        adjudication = adjudicate(test_runs, dis, sample, adj)
    meta = {"test_runs": old.get("test_runs", 0), "history": old.get("history") or []}
    table = build_table(measured, adjudication, meta)
    if args.finalize:
        unknown = sorted({e["id"] for e in adj["items"]} - {r.id for r, _ in dis})
        if unknown:
            raise SystemExit(f"{len(unknown)} adjudicated ids are not current disagreements, e.g. {unknown[0]!r} — "
                             "the method or the cache changed since the TEST run; rerun --test with --note")
        write_table(table)
        print(f"passed: {table['passed']}; adjudicated {table['adjudicated']} of {len(dis)}")
        print(json.dumps(table["criteria"], indent=1))
        return 0
    # --check
    if _comparable(table) != _comparable(old):
        drift = [k for k in _comparable(table) if table.get(k) != old.get(k)]
        print(f"DRIFT: the recomputed table differs from knowledge/anchor/benchmark.yaml in {drift}")
        return 1
    print("knowledge/anchor/benchmark.yaml matches a recomputation from the blank cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
