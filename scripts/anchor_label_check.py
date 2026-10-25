#!/usr/bin/env python
"""JK15b: how often a checkbox or radio widget's anchor ``label`` names its own option (Phase K JK15b, 2026-10-25).

The KG6 benchmark (scripts/anchor_benchmark.py) scores ``printed_line`` only. A checkbox's ``label`` is what
get_form_map, ``hand_write`` and the worksheet show, and Recipe U tells the agent to name a hand-write box by it
(docs/dev/JK19-PILOT.md, D3 and D5). This script measures that label, and licenses nothing: no tier, no table.

Population: every shipped pack (formpacks/**/pack.yaml) whose blank sits in the blank cache with the pack's
sha256; every pack key bound to a checkbox or radio widget whose last dotted segment NAMES THE OPTION (lower-case
words joined by "_", no digit: "filing_status.single", "8.yes", "married_filing_jointly"; not "13a", "box_1", "c1"
or a generic "check"/"checkbox"); a key with an on_state binds only the widgets carrying that on-state, as
truth_map does. Each (blank, field, widget, option) is counted once, however many packs share the blank.

A label NAMES the option when every content word of the option (OPTION_STOP words such as "of", "the" dropped)
is a word of the label: "yes" and "no" exactly (so "No" never matches "Note" or "not"), any other word exactly or by
a shared first five letters ("qualifying" ~ "qualified", "separate" ~ "separately"). An abbreviated key ("mfj",
"hoh") or a label that words the option differently counts as a miss, before and after alike.

It also reports, for Yes/No keys whose prefix is a numbered line ("9.yes"), whether the widget's printed_line is
that line (``yes_no_keyed_by_line``): a cross-check of the Yes/No pair anchoring, not a benchmark score.

    anchor_label_check.py            # print the measurement for the current method
    anchor_label_check.py --write    # also record it under the current method in knowledge/anchor/labels.yaml
    anchor_label_check.py --check    # recompute; exit 1 when the current method's recorded entry drifted
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))

from taxfill_core import anchor as A  # noqa: E402
from taxfill_core.datadir import knowledge_dir  # noqa: E402
from taxfill_core.packbuild import extract_fields  # noqa: E402
from taxfill_core.schemas.formpack import load_pack  # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))
from anchor_benchmark import cached_blank, key_line, sha256_of  # noqa: E402

LABELS = knowledge_dir() / "anchor" / "labels.yaml"
OPTION = re.compile(r"^[a-z]+(?:_[a-z]+)*$")
GENERIC = {"check", "checkbox", "box", "cb", "chk", "x", "on", "off", "flag", "mark", "indicator", "select"}
OPTION_STOP = {"of", "the", "and", "or", "with", "a", "an", "to", "for", "in", "on", "by", "if", "is"}
EXACT = {"yes", "no"}
HEADER = """\
# Phase K JK15b (2026-10-25): how often a checkbox or radio widget's anchor label names its own option, over the
# shipped packs' cached blanks. Written by scripts/anchor_label_check.py --write; do not edit by hand. A measurement
# only: it licenses no tier (knowledge/anchor/benchmark.yaml does that, for printed_line). One entry per anchor
# METHOD; jk15-v4 is the method before the JK15b label fix (docs/dev/JK19-PILOT.md D3, D5), jk15-v6 its fix wave
# (a sub-letter row under a joined head such as "47a" took the line before it, "46b").
"""


def option_of(key: str) -> str | None:
    last = key.rsplit(".", 1)[-1]
    if not OPTION.match(last) or last in GENERIC:
        return None
    return last


def option_words(option: str) -> list[str]:
    return [w for w in option.split("_") if w not in OPTION_STOP]


def names_option(label: str | None, option: str) -> bool:
    words = set(re.findall(r"[a-z]+", (label or "").lower()))
    for w in option_words(option):
        if w in EXACT or len(w) < 5:
            if w not in words:
                return False
        elif not any(t == w or (len(t) >= 5 and t[:5] == w[:5]) for t in words):
            return False
    return bool(option_words(option))


def population() -> tuple[list[dict], int]:
    """(blank, field, widget index, option) rows, each once, and how many packs contributed."""
    rows: dict[tuple, dict] = {}
    anchors: dict[str, dict] = {}
    packs = 0
    for path in sorted((REPO / "formpacks").glob("**/pack.yaml")):
        try:
            pack = load_pack(path)
        except Exception:  # noqa: BLE001 — a hand-fill or other non-AcroForm pack
            continue
        blank = cached_blank(pack.source_url)
        if blank is None or sha256_of(blank) != pack.pdf_sha256:
            continue
        keys = [(f.line, f.field, f.on_state) for f in pack.fields if option_of(f.line)]
        if not keys:
            continue
        packs += 1
        sha = pack.pdf_sha256
        if sha not in anchors:
            widgets = extract_fields(blank)
            by_name: dict[str, list[dict]] = {}
            for w in widgets:
                by_name.setdefault(w["name"], []).append(w)
            anchors[sha] = {"widgets": by_name, "anchors": {(a.field, a.widget_index): a for a in A.raw_anchors(blank)}}
        cached = anchors[sha]
        root = pack.acroform_root
        for key, fld, on_state in keys:
            name = f"{root}.{fld}" if root else fld
            targets = list(enumerate(cached["widgets"].get(name, [])))
            if on_state:
                narrowed = [(i, w) for i, w in targets if on_state in (w.get("on_states") or [])]
                targets = narrowed or targets
            for i, w in targets:
                if w["kind"] not in ("checkbox", "radio"):
                    continue
                a = cached["anchors"].get((name, i))
                if a is None:
                    continue
                opt = option_of(key)
                rows[(sha, name, i, opt)] = {"pack": path.parent.relative_to(REPO / "formpacks").as_posix(),
                                             "field": name, "widget": i, "option": opt, "label": a.label,
                                             "printed_line": a.printed_line, "key_line": key_line(key.rsplit(".", 1)[0])
                                             if "." in key else None}
    return list(rows.values()), packs


def measure(rows: list[dict] | None = None, packs: int | None = None) -> dict:
    if rows is None:
        rows, packs = population()

    def count(sel: list[dict]) -> dict:
        hit = sum(1 for r in sel if names_option(r["label"], r["option"]))
        return {"widgets": len(sel), "label_names_option": hit,
                "rate": round(hit / len(sel), 4) if sel else None,
                "no_label": sum(1 for r in sel if not r["label"])}

    yes_no = [r for r in rows if r["option"] in ("yes", "no")]
    filing = [r for r in rows if r["option"] in FILING_STATUSES]
    misses = Counter(r["option"] for r in rows if not names_option(r["label"], r["option"]))
    return {"method": A.METHOD, "packs": packs, "all_named_options": count(rows), "yes_no": count(yes_no),
            "filing_status": count(filing), "yes_no_with_printed_line": sum(1 for r in yes_no if r["printed_line"]),
            "yes_no_keyed_by_line": line_check([r for r in yes_no if r["key_line"]]),
            "top_missed_options": dict(misses.most_common(12))}


def line_check(rows: list[dict]) -> dict:
    """A Yes/No key whose prefix is a numbered line under the benchmark's KEY_RULE ("9.yes" -> 9): how often the
    widget's printed_line is that line, another line, or none. Not a benchmark score (the KG6 table does not score
    these keys); a cross-check of the D5 pair anchoring."""
    c = Counter("same" if r["printed_line"] == r["key_line"] else "other" if r["printed_line"] else "none"
                for r in rows)
    return {"widgets": len(rows), "printed_line_is_key_line": c["same"], "other_line": c["other"],
            "no_line": c["none"]}


FILING_STATUSES = {"single", "married_filing_jointly", "married_filing_separately", "head_of_household",
                   "qualifying_surviving_spouse", "qualifying_widow", "qualifying_widower", "married_joint",
                   "married_separate"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true", help="print every miss")
    args = ap.parse_args(argv)
    rows, packs = population()
    got = measure(rows, packs)
    print(yaml.safe_dump(got, sort_keys=False, width=120))
    if args.list:
        for r in sorted(rows, key=lambda r: (r["pack"], r["field"])):
            if r["key_line"] and r["option"] in ("yes", "no") and r["printed_line"] != r["key_line"]:
                print(f"LINE {r['pack']} {r['field']}[{r['widget']}] key_line={r['key_line']} "
                      f"printed_line={r['printed_line']}")
            if not names_option(r["label"], r["option"]):
                print(f"MISS {r['pack']} {r['field']}[{r['widget']}] option={r['option']} label={r['label']!r}")
    old = yaml.safe_load(LABELS.read_text(encoding="utf-8")) if LABELS.is_file() else {}
    entries = {e["method"]: e for e in (old or {}).get("measurements") or []}
    if args.check:
        if entries.get(A.METHOD) != got:
            print(f"DRIFT: knowledge/anchor/labels.yaml's {A.METHOD} entry differs from a recomputation")
            return 1
        print(f"knowledge/anchor/labels.yaml's {A.METHOD} entry matches a recomputation from the blank cache")
        return 0
    if args.write:
        entries[A.METHOD] = got
        LABELS.write_text(HEADER + yaml.safe_dump({"measurements": list(entries.values())}, sort_keys=False,
                                                  width=120), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
