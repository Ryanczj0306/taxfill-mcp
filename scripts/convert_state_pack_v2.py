#!/usr/bin/env python
"""Convert a v1 TY2025 state knowledge pack to schema v2 (Phase K JK24, 2026-10-24).

The JK24 parity proof: a v2 pack converted from a v1 one must load through today's dual loader
(taxfill_core.knowledge.load_state_knowledge) and give every JK21 golden byte for byte. This script writes those v2
packs. It is mechanical: every inline ``{source, url}`` citation becomes a reference to its row of the pack's
``sources`` table (JK20) and the index of its description there; every printed text is carried unchanged, as the
pack's own words (``{text: ...}``), never promoted to a quote it has not been checked to be. What v2 cannot carry as
typed data, or carries only as unquoted wording, is written into the pack's ``gaps``; nothing is dropped silently,
and an unknown v1 key stops the conversion.

Before writing, the conversion checks itself: the v2 pack's v1 projection must equal the v1 pack (less
``all_citations`` and ``unverified``, which v2 carries as ``sources`` rows and ``gaps``), field for field.

The output is NOT a shipped pack: TY2025 stays v1 in knowledge/ until JK26 (no earlier than 2027-04-16, KG8).
The committed fixtures (packages/core/tests/fixtures/state_knowledge_v2/) are the JK24 parity set.

Usage:
    python scripts/convert_state_pack_v2.py --fixtures          # rewrite the committed parity fixtures
    python scripts/convert_state_pack_v2.py --check             # exit 1 when a fixture is stale
    python scripts/convert_state_pack_v2.py ga ny --out DIR     # convert TY2025 packs into DIR/<st>/2025.yaml
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
_SRC = REPO / "packages" / "core" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from taxfill_core.knowledge import StateKnowledge  # noqa: E402
from taxfill_core.knowledge_v2 import StateKnowledgeV2  # noqa: E402
from taxfill_core.state_sources import BLOCK_TO_TOPIC, FALLBACK_TOPIC  # noqa: E402

KNOWLEDGE = REPO / "knowledge"
FIXTURES_DIR = REPO / "packages" / "core" / "tests" / "fixtures" / "state_knowledge_v2"
# A flat-rate state with a convenience rule and a law-change sweep record (PA), a graduated state with long tax
# notes and exemption credits (CA), the one pack with an amended-return block (GA, flat since 2024), and a graduated
# state with a convenience rule (NY).
FIXTURE_STATES = ("pa", "ca", "ga", "ny")
YEAR = 2025

# The v1 keys the conversion carries; any other key stops it (no silent drop).
_TOP_KEYS = {
    "jurisdiction", "tax_year", "income_tax", "conforms_to_federal_treaties", "treaty_note", "citation", "tax",
    "credits", "credits_verification", "effective_law_changes", "law_changes_checked", "convenience_rule", "forms",
    "mailing_addresses", "payment", "deadlines", "amended_return", "all_citations", "unverified", "sources",
}
_NOT_PROJECTED = ("all_citations", "unverified")  # carried as sources rows and gaps; no consumer reads them
_CREDIT_KEYS = {"name", "type", "eligibility", "claimed_on", "citation", "unverified"}
_MAILING_KEYS = {"refund_or_no_payment", "with_payment", "verification", "citation"}
_PAYMENT_KEYS = {"check_payee", "check_payee_note", "web_pay_url", "note", "citation"}
_DEADLINE_KEYS = {"filing_due_date", "automatic_extension", "verification", "citation"}
_AMENDED_KEYS = {
    "form", "mailing_address", "with_payment", "refund_or_no_payment", "payment", "assemble", "timing", "mail",
    "notes", "citation", "citations",
}
_FORMS_KEYS = {"resident", "part_year_or_nonresident", "schedule", "citations"}
_LAW_KEYS = {"description", "citation", "status", "lookup_path", "source_topic", "affects", "modeled"}


class ConversionError(ValueError):
    pass


def _only(block: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(block) - allowed)
    if unknown:
        raise ConversionError(f"{where}: no v2 home for key(s) {unknown}; extend the converter and the v2 model")


class _Refs:
    """Maps an inline citation to its ``sources`` row (by the topic its top-level block backs) and description."""

    def __init__(self, rows: list[dict]):
        self.rows = {(r["topic"], r["url"]): r for r in rows}

    def __call__(self, block: str, cite: dict) -> dict:
        _only(cite, {"source", "url"}, f"{block} citation")
        topic = BLOCK_TO_TOPIC.get(block, FALLBACK_TOPIC)
        row = self.rows.get((topic, cite["url"].strip()))
        if row is None:
            raise ConversionError(f"{block}: citation {cite['url']} has no `sources` row under topic {topic}")
        text = cite["source"].strip()
        if text != cite["source"] or text not in row["descriptions"]:
            raise ConversionError(f"{block}: citation text is not, verbatim, a description of row {row['id']}")
        ref: dict[str, Any] = {"id": row["id"]}
        index = row["descriptions"].index(text)
        if index:
            ref["description"] = index
        return ref


def convert(v1: dict, st: str) -> dict:
    """The v2 mapping for one v1 pack mapping (raises ConversionError rather than drop anything)."""
    v1 = copy.deepcopy(v1)
    _only(v1, _TOP_KEYS, f"{st} {v1.get('tax_year')}")
    year = v1["tax_year"]
    if year < 2025:
        raise ConversionError(f"TY{year} packs are frozen in schema v1; only TY2025 converts")
    if year > 2025:  # Phase K JK24 (2026-10-24): the {text} carrier is for the TY2025 conversion only
        raise ConversionError(
            f"TY{year} packs are authored in v2, not converted: the conversion carries v1 prose as {{text}}, which "
            f"StateKnowledgeV2 refuses from TY2026 — quote the source ({{quote, ref}}) or write {{not_modeled, ref}}"
        )
    ref = _Refs(v1["sources"])
    gaps: list[dict] = []
    v2: dict[str, Any] = {"schema_version": 2, "jurisdiction": v1["jurisdiction"], "tax_year": year}
    if "income_tax" in v1:
        v2["income_tax"] = v1["income_tax"]
    if v1.get("citation"):
        v2["citation"] = ref("citation", v1["citation"])
    treaty: dict[str, Any] = {"conforms_to_federal_treaties": v1["conforms_to_federal_treaties"]}
    if v1.get("treaty_note"):
        treaty["note"] = {"text": v1["treaty_note"]}
    v2["treaty"] = treaty

    plain = ["tax.tax_line", "the exemption notes"]
    tax = v1.get("tax")
    if tax is not None:
        tax = dict(tax)
        tax["citation"] = ref("tax", tax["citation"])
        notes = tax.pop("notes", []) or []
        if tax.get("exemption_credits") is not None:
            ec = dict(tax["exemption_credits"])
            ec["citation"] = ref("tax", ec["citation"])
            tax["exemption_credits"] = ec
            if ec.get("notes"):
                plain.append("the exemption-credit notes")
        tax["caveats"] = [{"text": n} for n in notes]
        v2["tax"] = tax
        gaps.append({"about": "base_line", "detail": (
            f"No quoted base line: the v1 pack quotes none (JK22 dropped `starts_from`); tax.base says only which "
            f"kind of figure the computation starts from ({tax['base']}).")})
        if notes:
            gaps.append({"about": "migration", "detail": (
                f"tax.caveats: the {len(notes)} v1 tax.notes are carried as the pack's own words, not as checked "
                f"quotes; JK26 triages each into base_line, a quoted caveat or a dropped diary.")})

    items = []
    for i, c in enumerate(v1.get("credits") or []):
        _only(c, _CREDIT_KEYS, f"credits[{i}]")
        item: dict[str, Any] = {"name": c["name"]}
        if c.get("claimed_on") is not None:
            item["line"] = c["claimed_on"]
        if c.get("type") is not None:
            item["type"] = c["type"]
        if c.get("eligibility") is not None:
            item["eligibility"] = {"text": c["eligibility"]}
        item["ref"] = ref("credits", c["citation"])
        if c.get("unverified"):
            item["unverified"] = True
        items.append(item)
    credits: dict[str, Any] = {}
    if v1.get("credits_verification") is not None:
        credits["caveat"] = v1["credits_verification"]
    if items:
        credits["items"] = items
    v2["credits"] = credits
    worded = ["treaty.note"] if "note" in treaty else []
    if any("eligibility" in it for it in items):
        worded.append(f"the eligibility of the {sum('eligibility' in it for it in items)} credits")
    if worded:
        gaps.append({"about": "migration", "detail": (
            f"Carried as the pack's own words, not checked quotes: {' and '.join(worded)}.")})

    changes = []
    for i, c in enumerate(v1.get("effective_law_changes") or []):
        _only(c, _LAW_KEYS, f"effective_law_changes[{i}]")
        change = {k: v for k, v in c.items() if k != "citation"}
        change["ref"] = ref("effective_law_changes", c["citation"])
        changes.append(change)
    law: dict[str, Any] = {}
    if changes:
        law["changes"] = changes
        gaps.append({"about": "law_changes", "detail": (
            f"The {len(changes)} law-change descriptions are carried as written, any of the source's words inline; "
            f"quotes[] stays empty until JK26 splits them out for the JK23 checker.")})
    if v1.get("law_changes_checked"):
        ck = dict(v1["law_changes_checked"])
        _only(ck, {"checked", "finding", "citation"}, "law_changes_checked")
        ck["ref"] = ref("law_changes_checked", ck.pop("citation"))
        law["checked"] = ck
    v2["law_changes"] = law

    if v1.get("convenience_rule"):
        rule = dict(v1["convenience_rule"])
        _only(rule, {"summary", "trigger", "exceptions", "citation"}, "convenience_rule")
        rule["ref"] = ref("convenience_rule", rule.pop("citation"))
        v2["convenience_rule"] = rule

    if v1.get("forms") is not None:
        f = v1["forms"]
        _only(f, _FORMS_KEYS, "forms")
        forms = {k: f[k] for k in ("resident", "part_year_or_nonresident", "schedule") if f.get(k) is not None}
        if f.get("citations"):
            forms["refs"] = {role: [ref("forms", c) for c in cites] for role, cites in f["citations"].items()}
        v2["forms"] = forms

    logistics: dict[str, Any] = {}
    for v1_key, v2_key, allowed in (
        ("mailing_addresses", "mailing", _MAILING_KEYS), ("deadlines", "deadlines", _DEADLINE_KEYS),
        ("payment", "payment", _PAYMENT_KEYS),
    ):
        block = v1.get(v1_key)
        if block is None:
            continue
        _only(block, allowed, v1_key)
        out = {k: v for k, v in block.items() if k != "citation"}
        if block.get("citation") is not None:
            out["ref"] = ref(v1_key, block["citation"])
        logistics[v2_key] = out
        if block.get("verification"):
            plain.append(f"{v1_key}.verification")
    if v1.get("amended_return") is not None:
        am = v1["amended_return"]
        _only(am, _AMENDED_KEYS, "amended_return")
        out = {k: v for k, v in am.items() if k not in ("citation", "citations")}
        for key in ("payment", "assemble", "timing", "mail", "notes"):
            if isinstance(out.get(key), str):
                out[key] = [out[key]]
        cites = ([am["citation"]] if am.get("citation") else []) + list(am.get("citations") or [])
        out["refs"] = [ref("amended_return", c) for c in cites]
        logistics["amended_return"] = out
        plain.append("the amended-return checklist lines (each quoting its source inline, JK27)")
    v2["logistics"] = logistics
    gaps.append({"about": "migration", "detail": (
        f"Kept as plain strings, neither a quote nor a pointer: {', '.join(plain)}. JK26 types them.")})

    all_cites = v1.get("all_citations") or []
    if all_cites:
        ids = [ref("all_citations", c)["id"] for c in all_cites]
        gaps.append({"about": "migration", "detail": (
            f"all_citations ({len(all_cites)} entries) is not carried: each is a `sources` row "
            f"({', '.join(dict.fromkeys(ids))}) whose descriptions hold its text.")})
    gaps.append({"about": "migration", "detail": (
        f"The v1 file's YAML comments (provenance and authoring notes) are not carried; read them in the git history "
        f"of knowledge/states/{st}/{year}.yaml.")})
    gaps += [{"about": "unverified", "detail": text} for text in v1.get("unverified") or []]
    v2["gaps"] = gaps
    v2["sources"] = v1["sources"]
    _check_projection(v1, v2, st)
    return v2


def _check_projection(v1: dict, v2: dict, st: str) -> None:
    expected = StateKnowledge.model_validate({k: v for k, v in v1.items() if k not in _NOT_PROJECTED}).model_dump()
    got = StateKnowledgeV2.model_validate(v2).to_v1().model_dump()
    if got != expected:
        diff = sorted(k for k in set(got) | set(expected) if got.get(k) != expected.get(k))
        raise ConversionError(f"{st}: the v2 pack's v1 projection differs from the v1 pack in {diff}")


def render(v2: dict, st: str, year: int = YEAR) -> str:
    header = (
        f"# Schema v2 conversion of knowledge/states/{st}/{year}.yaml — Phase K JK24 parity fixture, NOT a shipped pack.\n"
        f"# Generated by scripts/convert_state_pack_v2.py; regenerate, never hand-edit. Loaded through\n"
        f"# load_state_knowledge, it must give the {st}_{year} JK21 golden byte for byte (test_state_knowledge_v2.py).\n"
    )
    return header + yaml.safe_dump(v2, sort_keys=False, allow_unicode=True, width=118, default_flow_style=False)


def convert_file(st: str, year: int = YEAR, knowledge: Path = KNOWLEDGE) -> str:
    raw = yaml.safe_load((knowledge / "states" / st / f"{year}.yaml").read_text(encoding="utf-8"))
    return render(convert(raw, st), st, year)


def fixture_path(st: str, year: int = YEAR) -> Path:
    return FIXTURES_DIR / f"{st}_{year}.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("states", nargs="*", help="two-letter codes to convert into --out")
    parser.add_argument("--out", type=Path, help="write <out>/<st>/2025.yaml for each state named")
    parser.add_argument("--fixtures", action="store_true", help="rewrite the committed parity fixtures")
    parser.add_argument("--check", action="store_true", help="exit 1 when a committed fixture is stale")
    ns = parser.parse_args(argv)
    if ns.fixtures or ns.check:
        stale = []
        for st in FIXTURE_STATES:
            text, path = convert_file(st), fixture_path(st)
            if ns.check:
                if not path.is_file() or path.read_text(encoding="utf-8") != text:
                    stale.append(path.name)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(REPO)}")
        if stale:
            print(f"stale v2 fixtures: {', '.join(stale)} — regenerate with scripts/convert_state_pack_v2.py --fixtures")
            return 1
        if ns.check:
            print(f"all {len(FIXTURE_STATES)} v2 fixtures match a fresh conversion")
        return 0
    if not ns.states or ns.out is None:
        parser.error("name the states and --out, or pass --fixtures / --check")
    for st in ns.states:
        target = ns.out / st / f"{YEAR}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(convert_file(st.lower()), encoding="utf-8")
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
