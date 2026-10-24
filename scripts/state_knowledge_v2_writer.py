#!/usr/bin/env python
"""The TY2026+ state knowledge writer: one cited fact set in, one schema v2 pack out (Phase K JK25, 2026-10-24).

From TY2026 a state pack is written as schema v2 (taxfill_core.knowledge_v2.StateKnowledgeV2: pointer-first, every
printed text a verbatim quote or a pointer, ADR-0001). The three assemblers that build a v1 pack in turn
(scripts/assemble_state_knowledge.py, then assemble_state_tax_blocks.py, then assemble_state_credits.py, then
hoist_state_sources.py) all feed this one writer instead: ``assemble_state_knowledge.py --year 2026 --input FACTS
[--tax-dir DIR] [--credits FILE]`` hands it each state's fact set, the verified tax JSON of the tax-block workflow
and the credits research, and it writes the whole pack in one pass. The tax-block and credits assemblers refuse a
TY2026+ year and point here. Years up to 2025 keep the v1 scripts unchanged.

WHAT IT DOES, per state:

1. builds the ``sources`` table (JK20) from the input's inline citations: one row per distinct (registry topic, url),
   the topic the one the citation's block maps to (state_sources.BLOCK_TO_TOPIC, by the v1 block name, so a citation
   lands on the row JK20 would have hoisted it to), ids ``<topic prefix>-<n>`` numbered per topic in first-seen
   order, and every distinct ``source`` text kept as a description; each citation becomes a SourceRef into it;
2. puts each fact in its v2 slot (base_line, treaty, tax with caveats, credit pointers, law_changes, forms with
   per-role refs, logistics, gaps);
3. REFUSES what it cannot write honestly, saying which field to drop or reword: a v1 block JK22 dropped (residency,
   filing_requirement, starts_from), v1 prose (treaty_basis, tax.notes, a credit's prose eligibility), a caveat that
   is neither a quote with its citation nor a not-modeled statement, a credit amount or income limit, a citation to
   a non-government host, and any key it does not know (nothing is dropped silently); a figure in a credits caveat
   or a credit's name, a rate that is not a decimal string, a bracket row without over / but_not_over / rate, a
   --credits entry key other than state / caveat / credits, and a state code named twice (in any case) are refused
   too, each with its field path, and the run goes on with the other states (JK25 verifier minors, 2026-10-24);
4. validates the mapping with StateKnowledgeV2, then writes it, re-reads it through the dual loader (the v1
   projection today's tools read), checks every rate round-trips exactly and recomputes the tax JSON's test vectors
   through calc.state_tax; on any failure the file is restored.

THE INPUT (one state's entry of the ``--input`` JSON, keyed by its two-letter code). A citation is
``{source, url, pinpoint?}`` (``source`` the document's description, ``pinpoint`` a page, section or line; a .gov or
state .us URL). A quote is ``{quote, citation}``: the source's own words, at most 400 characters
(scripts/check_quotes.py holds it to the source)::

    citation: <citation>                    # required: the pack's primary authority
    citations: [<citation>]                 # every other document the fetch read (each becomes a sources row)
    conforms_to_federal_treaties: bool      # required
    treaty_note: <quote>
    base_line: {form, line, quote, citation}            # the line the computation starts from, quoted off the form
    tax: <the tax-block JSON below>         # or from --tax-dir
    credits: {caveat?, items: [{name, line?, type: refundable|nonrefundable, eligibility?: <quote>, citation,
              unverified?}]}                # or from --credits; pointers, no amounts
    law_changes: {changes: [{description, quotes: [<quote>], status, lookup_path?, source_topic?, affects?, modeled?,
                  citation}], checked: {checked: YYYY-MM-DD, finding, citation}}   # one of the two is required
    convenience_rule: {summary, trigger, exceptions?, citation}
    forms: {resident, part_year_or_nonresident?, schedule?, citations: {resident|part_year|nonresident: [<citation>]}}
    logistics: {mailing: {refund_or_no_payment?, with_payment?, verification?, citation},
                deadlines: {filing_due_date: YYYY-MM-DD, automatic_extension?, verification?, citation},
                payment: {check_payee?, check_payee_note?, web_pay_url?, note?, citation?},
                amended_return: {form, ..., citations: [<citation>, ...]}}     # the first citation is the form
    gaps: [{about, detail}]                 # what the pack knowingly does not cover
    unverified: [str]                       # each becomes a gap with about: unverified

The tax block is the tax-block workflow's verified JSON (scripts/assemble_state_tax_blocks.py's PACK_SCHEMA) with
its disclosures as ``caveats`` instead of ``notes``: ``citation``, ``base``, ``tax_line``, ``flat_rate`` or
``brackets``, ``standard_deduction``, ``exemptions``, ``exemption_credits`` (its ``citation`` inline),
``caveats: [<quote> | {not_modeled, citation}]`` (``not_modeled`` names what calc.state_tax does not compute, in
at most 200 characters and with no figure) and ``test_vectors`` (recomputed, not written). ``state`` and
``classification`` are read and dropped. The ``--credits`` file is assemble_state_credits.py's ``{result: [...]}``
list, each entry ``{state, caveat?, credits: [<credit item>]}``.
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[1]
for _path in (REPO / "packages" / "core" / "src", REPO / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from taxfill_core.knowledge import load_state_knowledge  # noqa: E402
from taxfill_core.knowledge_v2 import (  # noqa: E402
    _FIGURE_RE,
    POINTER_ONLY_FIRST_TAX_YEAR,
    StateKnowledgeV2,
    _bare_figure,
)
from taxfill_core.state_sources import BLOCK_TO_TOPIC, FALLBACK_TOPIC, TOPIC_ID_PREFIX, is_gov  # noqa: E402

# The first tax year written as v2 by the assemblers (TY2025 stays v1 until JK26 converts it).
V2_FIRST_WRITTEN_YEAR = POINTER_ONLY_FIRST_TAX_YEAR

# v1 fetch keys a TY2026+ input may not carry, and what to do instead.
_V1_TOP_KEYS = {
    "residency_summary": "drop it: JK22 dropped the never-read `residency` block, and v2 has none",
    "residency": "drop it: JK22 dropped the never-read `residency` block, and v2 has none",
    "filing_requirement_note": "drop it: JK22 dropped the never-read `filing_requirement` block, and v2 has none",
    "filing_requirement": "drop it: JK22 dropped the never-read `filing_requirement` block, and v2 has none",
    "starts_from": ("drop it (JK22 dropped the never-read `starts_from`), and quote the line the computation starts "
                    "from as base_line {form, line, quote, citation}"),
    "treaty_basis": ("reword it as treaty_note {quote, citation}: the source's own words, at most 400 characters; "
                     "or drop it and keep only conforms_to_federal_treaties"),
    "treaty_note_text": "reword it as treaty_note {quote, citation}, or drop it",
    "resident_form": "move it to forms.resident",
    "nonresident_or_part_year_form": "move it to forms.part_year_or_nonresident",
    "mailing": "move it to logistics.mailing {refund_or_no_payment, with_payment, citation}",
    "mailing_addresses": "move it to logistics.mailing {refund_or_no_payment, with_payment, citation}",
    "payment": "move it to logistics.payment {check_payee, web_pay_url, citation}",
    "filing_due_date": "move it to logistics.deadlines {filing_due_date, citation}",
    "deadlines": "move it to logistics.deadlines {filing_due_date, citation}",
    "amended_return": "move it to logistics.amended_return",
    "all_citations": "rename it to citations",
    "credits_verification": "move it to credits.caveat",
    "effective_law_changes": "move it to law_changes.changes (each with quotes and a citation)",
    "law_changes_checked": "move it to law_changes.checked {checked, finding, citation}",
}
_TOP_KEYS = {
    "citation", "citations", "conforms_to_federal_treaties", "treaty_note", "base_line", "tax", "credits",
    "law_changes", "convenience_rule", "forms", "logistics", "gaps", "unverified",
}
_NO_AMOUNT = ("drop it: a v2 credit is a pointer (name, line, type, eligibility quote, citation) and carries no "
              "amount or income limit; the figure stays in the cited source (ADR-0001)")
_V1_CREDIT_KEYS = {
    "amount": _NO_AMOUNT,
    "income_limit": _NO_AMOUNT,
    "claimed_on": "rename it to line",
    "citation_url": "write citation {source, url} instead of citation_source / citation_url",
    "citation_source": "write citation {source, url} instead of citation_source / citation_url",
}
_CREDIT_ENTRY_KEYS = {"state", "caveat", "credits"}  # one entry of the --credits file


def _entry_v1_keys(entry: dict) -> dict[str, str]:
    """The v1 credit-key messages for one --credits entry's keys: an amount or income limit has no v2 slot."""
    keys = {"amount": _NO_AMOUNT, "income_limit": _NO_AMOUNT}
    keys.update({k: _NO_AMOUNT for k in entry if isinstance(k, str) and k.startswith("income_limit_")})
    return keys


_CREDIT_KEYS = {"name", "line", "type", "eligibility", "citation", "unverified"}
_TAX_KEYS = {
    "state", "classification", "citation", "base", "tax_line", "flat_rate", "brackets", "standard_deduction",
    "exemptions", "exemption_credits", "caveats", "test_vectors",
}
_CAVEAT_HOW = ("write it as {quote, citation} (the source's own words, at most 400 characters) or as "
               "{not_modeled, citation} (what calc.state_tax does not compute, at most 200 characters, no figure)")
_LOGISTICS_KEYS = {
    "mailing": ("mailing_addresses", {"refund_or_no_payment", "with_payment", "verification", "citation"}),
    "deadlines": ("deadlines", {"filing_due_date", "automatic_extension", "verification", "citation"}),
    "payment": ("payment", {"check_payee", "check_payee_note", "web_pay_url", "note", "citation"}),
}
_AMENDED_KEYS = {
    "form", "mailing_address", "with_payment", "refund_or_no_payment", "payment", "assemble", "timing", "mail",
    "notes", "citations",
}


class InputRefused(ValueError):
    """The input says something a v2 pack cannot carry honestly; the message names the field and what to do."""


def _refuse(st: str, where: str, what: str) -> InputRefused:
    return InputRefused(f"{st.upper()} {where}: {what}")


def _only(st: str, block: Any, allowed: set[str], where: str, v1: dict[str, str] | None = None) -> dict:
    """``block`` when every key has a v2 slot; else one refusal naming every key that has none (JK25 minors)."""
    if not isinstance(block, dict):
        raise _refuse(st, where, f"expected a mapping, got {type(block).__name__}")
    problems = []
    for key in block:
        path = f"{where}.{key}" if where else key
        if v1 and key in v1:
            problems.append(_refuse(st, path, v1[key]))
        elif key not in allowed:
            problems.append(_refuse(st, path, f"no v2 slot for this key; drop it or put it in one of {sorted(allowed)}"))
    if problems:
        raise InputRefused("\n    ".join(str(p) for p in problems))
    return block


# Phase K JK25 (2026-10-24): a figure enters a v2 pack only as the source's words. knowledge_v2's not-modeled figure
# check (signs, words, thousands separators, and a bare decimal or 4+ digit number that is not a form or line
# designator) also guards the free text a credits block carries: its caveat and each credit's name.
_FIGURE_HOW = "a figure goes in only as the source's words: put it in eligibility {quote, citation} or drop it"


def _figure_free(st: str, value: Any, where: str) -> Any:
    if isinstance(value, str):
        match = _FIGURE_RE.search(value)
        figure = match.group(0) if match else _bare_figure(value)
        if figure:
            raise _refuse(st, where, f"states a figure ({figure!r}); {_FIGURE_HOW}")
    return value


class _Sources:
    """The pack's ``sources`` table, built as citations are met (JK20's numbering: per topic, first seen first)."""

    def __init__(self, st: str):
        self.st = st
        self.rows: dict[tuple[str, str], dict] = {}
        self.counters: dict[str, int] = {}

    def ref(self, block: str, cite: Any, where: str) -> dict:
        cite = _only(self.st, cite, {"source", "url", "pinpoint"}, where)
        source, url = cite.get("source"), cite.get("url")
        if not isinstance(source, str) or not source.strip() or not isinstance(url, str) or not url.strip():
            raise _refuse(self.st, where, "a citation needs a non-empty source (the document's description) and url")
        url = url.strip()
        if not is_gov(url):
            raise _refuse(self.st, where, f"{url} is not a government host; cite the .gov / state .us document the "
                                          f"text comes from, or drop the fact")
        topic = BLOCK_TO_TOPIC.get(block, FALLBACK_TOPIC)
        row = self.rows.get((topic, url))
        if row is None:
            prefix = TOPIC_ID_PREFIX[topic]
            self.counters[prefix] = self.counters.get(prefix, 0) + 1
            row = {"id": f"{prefix}-{self.counters[prefix]}", "topic": topic, "url": url, "descriptions": []}
            self.rows[(topic, url)] = row
        text = source.strip()
        if text not in row["descriptions"]:
            row["descriptions"].append(text)
        ref: dict[str, Any] = {"id": row["id"]}
        index = row["descriptions"].index(text)
        if index:
            ref["description"] = index
        if cite.get("pinpoint") is not None:
            ref["pinpoint"] = cite["pinpoint"]
        return ref

    def table(self) -> list[dict]:
        return list(self.rows.values())


def _quote(st: str, src: _Sources, block: str, value: Any, where: str) -> dict:
    if isinstance(value, str):
        raise _refuse(st, where, "is prose; a v2 pack prints only the source's words: write {quote, citation} "
                                 "(at most 400 characters), or drop it")
    value = _only(st, value, {"quote", "citation"}, where,
                  {"text": "is the pack's own wording ({text}), which only a TY2025 conversion carries; write "
                           "{quote, citation} with the source's own words, or drop it"})
    if "quote" not in value or "citation" not in value:
        raise _refuse(st, where, "a quote needs both `quote` (the source's own words) and `citation` (where they are)")
    return {"quote": value["quote"], "ref": src.ref(block, value["citation"], f"{where}.citation")}


def _caveat(st: str, src: _Sources, value: Any, where: str) -> dict:
    if isinstance(value, dict) and "not_modeled" in value:
        value = _only(st, value, {"not_modeled", "citation"}, where)
        if "citation" not in value:
            raise _refuse(st, where, "a not-modeled caveat needs a citation (the rule it is about)")
        return {"not_modeled": value["not_modeled"], "ref": src.ref("tax", value["citation"], f"{where}.citation")}
    if isinstance(value, dict) and "quote" in value:
        return _quote(st, src, "tax", value, where)
    raise _refuse(st, where, f"is neither a quote nor a not-modeled statement: {_CAVEAT_HOW}")


_RATE_RE = re.compile(r"^(?:0|0?\.\d+)$")
_BRACKET_KEYS = {"over", "but_not_over", "rate"}


def _rate(st: str, value: Any, where: str) -> float:
    """A JSON rate string ('0.0425') as the YAML float the v1 tax-block assembler writes (exactness re-checked).

    Phase K JK25 (2026-10-24): checked up front, so a percent ('4.25%'), a percentage number ('4.25') or a JSON
    float is refused with its field path instead of failing the float conversion or the exactness gate unnamed.
    """
    if not isinstance(value, str) or not _RATE_RE.match(value.strip()):
        raise _refuse(st, where, f'a decimal string such as "0.0425" (the rate as a fraction, below 1); got {value!r}')
    return float(value)


def _brackets(st: str, brackets: Any) -> dict:
    if not isinstance(brackets, dict):
        raise _refuse(st, "tax.brackets", "a mapping of filing status to a list of {over, but_not_over, rate} rows")
    out = {}
    for status, rows in brackets.items():
        if not isinstance(rows, list):
            raise _refuse(st, f"tax.brackets.{status}", "a list of {over, but_not_over, rate} rows")
        out[status] = []
        for i, row in enumerate(rows):
            where = f"tax.brackets.{status}[{i}]"
            if not isinstance(row, dict) or set(row) != _BRACKET_KEYS:
                raise _refuse(st, where, "needs over, but_not_over, rate (but_not_over null for the top bracket) "
                                         "and nothing else")
            out[status].append({"over": row["over"], "but_not_over": row["but_not_over"],
                                "rate": _rate(st, row["rate"], f"{where}.rate")})
    return out


def _tax(st: str, src: _Sources, tax: Any) -> tuple[dict, list[dict]]:
    tax = _only(st, copy.deepcopy(tax), _TAX_KEYS, "tax",
                {"notes": f"a v2 tax block carries no prose notes: move each one to tax.caveats and {_CAVEAT_HOW}"})
    if "citation" not in tax:
        raise _refuse(st, "tax", "the tax block needs its citation (the rate schedule's source)")
    if tax.get("state") is not None and str(tax["state"]).lower() != st.lower():
        raise _refuse(st, "tax.state", f"this tax JSON is for {tax['state']!r}, not {st.upper()}")
    out: dict[str, Any] = {"citation": src.ref("tax", tax["citation"], "tax.citation")}
    if tax.get("flat_rate") is not None:
        out["flat_rate"] = _rate(st, tax["flat_rate"], "tax.flat_rate")
    if tax.get("brackets") is not None:
        out["brackets"] = _brackets(st, tax["brackets"])
    for key in ("base", "tax_line", "exemptions", "standard_deduction"):
        if tax.get(key) is not None:
            out[key] = tax[key]
    if tax.get("exemption_credits") is not None:
        ec = dict(tax["exemption_credits"])
        if "citation" not in ec:
            raise _refuse(st, "tax.exemption_credits", "the exemption-credit block needs its citation")
        out["exemption_credits"] = {"citation": src.ref("tax", ec.pop("citation"), "tax.exemption_credits.citation"),
                                    **ec}
    out["caveats"] = [_caveat(st, src, c, f"tax.caveats[{i}]") for i, c in enumerate(tax.get("caveats") or [])]
    return out, list(tax.get("test_vectors") or [])


def _credit(st: str, src: _Sources, item: Any, where: str, year: int) -> dict:
    v1 = dict(_V1_CREDIT_KEYS)
    v1[f"income_limit_{year}"] = _NO_AMOUNT
    if isinstance(item, dict):
        for key in item:
            if key.startswith("income_limit_"):
                v1.setdefault(key, _NO_AMOUNT)
    item = _only(st, item, _CREDIT_KEYS, where, v1)
    for key in ("name", "type", "citation"):
        if key not in item:
            raise _refuse(st, where, f"a credit pointer needs `{key}`")
    out: dict[str, Any] = {"name": _figure_free(st, item["name"], f"{where}.name")}
    if item.get("line") is not None:
        out["line"] = item["line"]
    out["type"] = item["type"]
    if item.get("eligibility") is not None:
        out["eligibility"] = _quote(st, src, "credits", item["eligibility"], f"{where}.eligibility")
    out["ref"] = src.ref("credits", item["citation"], f"{where}.citation")
    if item.get("unverified"):
        out["unverified"] = True
    return out


def _credits(st: str, src: _Sources, credits: Any, year: int) -> dict:
    credits = _only(st, credits, {"caveat", "items"}, "credits")
    out: dict[str, Any] = {}
    if credits.get("caveat") is not None:
        out["caveat"] = _figure_free(st, credits["caveat"], "credits.caveat")
    items = [_credit(st, src, c, f"credits.items[{i}]", year) for i, c in enumerate(credits.get("items") or [])]
    if items:
        out["items"] = items
    return out


def _law_changes(st: str, src: _Sources, law: Any) -> dict:
    law = _only(st, law, {"changes", "checked"}, "law_changes")
    out: dict[str, Any] = {}
    changes = []
    allowed = {"description", "quotes", "status", "lookup_path", "source_topic", "affects", "modeled", "citation"}
    for i, change in enumerate(law.get("changes") or []):
        where = f"law_changes.changes[{i}]"
        change = _only(st, change, allowed, where)
        if "citation" not in change:
            raise _refuse(st, where, "a law change needs its citation (the booklet section that states it)")
        entry = {k: v for k, v in change.items() if k not in ("quotes", "citation")}
        entry["quotes"] = [_quote(st, src, "effective_law_changes", q, f"{where}.quotes[{j}]")
                           for j, q in enumerate(change.get("quotes") or [])]
        entry["ref"] = src.ref("effective_law_changes", change["citation"], f"{where}.citation")
        changes.append(entry)
    if changes:
        out["changes"] = changes
    if law.get("checked") is not None:
        ck = dict(_only(st, law["checked"], {"checked", "finding", "citation"}, "law_changes.checked"))
        if "citation" not in ck:
            raise _refuse(st, "law_changes.checked", "the sweep record needs the citation of the section read")
        ck["ref"] = src.ref("law_changes_checked", ck.pop("citation"), "law_changes.checked.citation")
        out["checked"] = ck
    return out


def _forms(st: str, src: _Sources, forms: Any) -> dict:
    forms = _only(st, forms, {"resident", "part_year_or_nonresident", "schedule", "citations"}, "forms")
    out = {k: forms[k] for k in ("resident", "part_year_or_nonresident", "schedule") if forms.get(k) is not None}
    if forms.get("citations"):
        roles = _only(st, forms["citations"], {"resident", "part_year", "nonresident"}, "forms.citations")
        out["refs"] = {role: [src.ref("forms", c, f"forms.citations.{role}[{i}]") for i, c in enumerate(cites)]
                       for role, cites in roles.items()}
    return out


def _logistics(st: str, src: _Sources, logistics: Any) -> dict:
    logistics = _only(st, logistics, {*_LOGISTICS_KEYS, "amended_return"}, "logistics")
    out: dict[str, Any] = {}
    for key, (v1_block, allowed) in _LOGISTICS_KEYS.items():
        block = logistics.get(key)
        if block is None:
            continue
        block = _only(st, block, allowed, f"logistics.{key}")
        entry = {k: v for k, v in block.items() if k != "citation"}
        if block.get("citation") is not None:
            entry["ref"] = src.ref(v1_block, block["citation"], f"logistics.{key}.citation")
        out[key] = entry
    if logistics.get("amended_return") is not None:
        am = _only(st, logistics["amended_return"], _AMENDED_KEYS, "logistics.amended_return")
        if not am.get("citations"):
            raise _refuse(st, "logistics.amended_return", "list its citations, the amended form's own first")
        entry = {k: v for k, v in am.items() if k != "citations"}
        entry["refs"] = [src.ref("amended_return", c, f"logistics.amended_return.citations[{i}]")
                         for i, c in enumerate(am["citations"])]
        out["amended_return"] = entry
    return out


def build_pack(st: str, facts: dict, year: int, *, tax: dict | None = None,
               credits: dict | None = None) -> tuple[dict, list[dict]]:
    """The validated v2 mapping for one state, and the tax JSON's test vectors (raises InputRefused).

    ``tax`` / ``credits`` come from the tax-block and credits workflows' files; each is refused when the fact set
    carries the same block too (one source per block).
    """
    st = st.lower()
    if year < V2_FIRST_WRITTEN_YEAR:
        raise _refuse(st, "tax_year", f"TY{year} packs are written as v1 by the assemble_state_* scripts; the v2 "
                                      f"writer starts at TY{V2_FIRST_WRITTEN_YEAR}")
    facts = _only(st, facts, _TOP_KEYS, "", _V1_TOP_KEYS)
    if tax is not None and facts.get("tax") is not None:
        raise _refuse(st, "tax", "the fact set and --tax-dir both carry a tax block; keep one")
    if credits is not None and facts.get("credits") is not None:
        raise _refuse(st, "credits", "the fact set and --credits both carry credits; keep one")
    tax = tax if tax is not None else facts.get("tax")
    credits = credits if credits is not None else facts.get("credits")
    for key in ("citation", "conforms_to_federal_treaties"):
        if key not in facts:
            raise _refuse(st, key, "required: the pack's primary authority and its treaty conformity")
    if not isinstance(facts["conforms_to_federal_treaties"], bool):
        raise _refuse(st, "conforms_to_federal_treaties", "must be true or false")

    src = _Sources(st)
    pack: dict[str, Any] = {"schema_version": 2, "jurisdiction": f"states/{st}", "tax_year": year,
                            "income_tax": True}
    pack["citation"] = src.ref("citation", facts["citation"], "citation")
    treaty: dict[str, Any] = {"conforms_to_federal_treaties": facts["conforms_to_federal_treaties"]}
    if facts.get("treaty_note") is not None:
        treaty["note"] = _quote(st, src, "treaty_note", facts["treaty_note"], "treaty_note")
    pack["treaty"] = treaty
    if facts.get("base_line") is not None:
        bl = _only(st, facts["base_line"], {"form", "line", "quote", "citation"}, "base_line")
        quoted = _quote(st, src, "base_line", {"quote": bl.get("quote"), "citation": bl.get("citation")},
                        "base_line")
        pack["base_line"] = {"form": bl.get("form"), "line": bl.get("line"), "quote": quoted}
    vectors: list[dict] = []
    if tax is not None:
        pack["tax"], vectors = _tax(st, src, tax)
    pack["credits"] = _credits(st, src, credits, year) if credits is not None else {}
    pack["law_changes"] = _law_changes(st, src, facts.get("law_changes") or {})
    if facts.get("convenience_rule") is not None:
        rule = dict(_only(st, facts["convenience_rule"], {"summary", "trigger", "exceptions", "citation"},
                          "convenience_rule"))
        if "citation" not in rule:
            raise _refuse(st, "convenience_rule", "the rule needs its citation")
        rule["ref"] = src.ref("convenience_rule", rule.pop("citation"), "convenience_rule.citation")
        pack["convenience_rule"] = rule
    if facts.get("forms") is not None:
        pack["forms"] = _forms(st, src, facts["forms"])
    pack["logistics"] = _logistics(st, src, facts.get("logistics") or {})
    gaps = []
    for i, gap in enumerate(facts.get("gaps") or []):
        gaps.append(dict(_only(st, gap, {"about", "detail"}, f"gaps[{i}]")))
    gaps += [{"about": "unverified", "detail": text} for text in facts.get("unverified") or []]
    pack["gaps"] = gaps
    for i, cite in enumerate(facts.get("citations") or []):
        src.ref("all_citations", cite, f"citations[{i}]")
    pack["sources"] = src.table()
    try:
        StateKnowledgeV2.model_validate(pack)
    except ValidationError as exc:
        raise _refuse(st, "pack", f"does not validate as StateKnowledgeV2 — fix the input field named below (the pack's "
                                    f"`ref` is the input's `citation`):\n{exc}")
    return pack, vectors


def render(pack: dict) -> str:
    st = pack["jurisdiction"].split("/")[1]
    year = pack["tax_year"]
    header = (
        f"# {st.upper()} state knowledge — tax year {year}, schema v2 (taxfill_core.knowledge_v2.StateKnowledgeV2).\n"
        f"# Written by scripts/assemble_state_knowledge.py --year {year} (scripts/state_knowledge_v2_writer.py) from a\n"
        f"# cited fetch input. Each quote is the source's own words (scripts/check_quotes.py --pack holds it to its\n"
        f"# `sources` row); the pack knowingly leaves out what its `gaps` list says.\n"
    )
    return header + yaml.safe_dump(pack, sort_keys=False, allow_unicode=True, width=118, default_flow_style=False)


def write_pack(pack: dict, vectors: list[dict], tax_input: dict | None, knowledge_dir: Path) -> Path:
    """Write one v2 pack and gate it through the loader and calc.state_tax; restore the file on any failure."""
    from assemble_state_tax_blocks import _check_rates_exact, check_vectors  # noqa: PLC0415

    st = pack["jurisdiction"].split("/")[1]
    year = pack["tax_year"]
    text = render(pack)
    if yaml.safe_load(text) != pack:
        raise _refuse(st, "pack", "the rendered YAML does not round-trip; nothing written")
    path = knowledge_dir / "states" / st / f"{year}.yaml"
    before = path.read_text(encoding="utf-8") if path.is_file() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        loaded = load_state_knowledge(st, year, base_dir=knowledge_dir)  # the v1 projection the tools read
        if tax_input is not None:
            _check_rates_exact(tax_input, loaded.tax)
            check_vectors(st, year, vectors, knowledge_dir)
    except BaseException:
        if before is None:
            path.unlink()
        else:
            path.write_text(before, encoding="utf-8")
        raise
    return path


def assemble(kb: dict, year: int, knowledge_dir: Path, *, tax_dir: Path | None = None,
             credits_file: Path | None = None) -> tuple[list[str], list[tuple[str, str]]]:
    """Write a v2 pack for every state of the fact sets; (written codes, [(code, why refused)])."""
    import json  # noqa: PLC0415

    taxes: dict[str, dict] = {}
    if tax_dir is not None:
        for f in sorted(tax_dir.glob("*.json")):
            if f.name.startswith("pending-"):
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            code = str(data.get("state") or "").lower()
            if code:
                if code in taxes:
                    raise SystemExit(f"{code}: duplicate tax JSON ({f}) — one verified tax block per state")
                taxes[code] = data
    credits: dict[str, dict] = {}
    early: dict[str, str] = {}  # code -> why the state is refused before its fact set is read (JK25 minors)
    if credits_file is not None:
        raw = json.loads(credits_file.read_text(encoding="utf-8"))
        for i, entry in enumerate(raw["result"] if isinstance(raw, dict) and "result" in raw else raw):
            where = f"--credits[{i}]"
            code = str(entry.get("state") or "").lower() if isinstance(entry, dict) else ""
            if not code:
                raise SystemExit(f"{where}: a credits entry is {{state, caveat?, credits}}; name its state")
            if code in credits:
                early.setdefault(code, str(_refuse(code, where, "a second entry for this state; keep one")))
                continue
            try:
                _only(code, entry, _CREDIT_ENTRY_KEYS, where, _entry_v1_keys(entry))
            except InputRefused as exc:
                early.setdefault(code, str(exc))
            credits[code] = {k: v for k, v in (("caveat", entry.get("caveat")), ("items", entry.get("credits")))
                             if v is not None}
    seen: dict[str, list[str]] = {}
    for st in kb:
        seen.setdefault(str(st).lower(), []).append(str(st))
    for code, spellings in seen.items():
        if len(spellings) > 1:
            early[code] = (f"{code.upper()}: the fact set names this state more than once "
                           f"({', '.join(map(repr, spellings))}); keep one")
    wrote, refused = [], []
    for st, facts in kb.items():
        code = st.lower()
        if code in early:
            if code not in {c for c, _ in refused}:  # one refusal per state, however many spellings
                refused.append((code, early[code]))
            continue
        try:
            pack, vectors = build_pack(code, facts, year, tax=taxes.get(code), credits=credits.get(code))
            tax_input = taxes.get(code) or (facts.get("tax") if isinstance(facts, dict) else None)
            write_pack(pack, vectors, tax_input, knowledge_dir)
        except InputRefused as exc:
            refused.append((code, str(exc)))
            continue
        except (AssertionError, ValueError) as exc:
            refused.append((code, f"{code.upper()} gate failed, file restored: {exc}"))
            continue
        wrote.append(code)
    unused = sorted((set(taxes) | set(credits)) - {st.lower() for st in kb})
    for code in unused:
        refused.append((code, f"{code.upper()}: a tax or credits input names a state the fact set lacks; add its "
                              f"fact set (citation, conforms_to_federal_treaties, ...) or remove the input"))
    return wrote, refused
