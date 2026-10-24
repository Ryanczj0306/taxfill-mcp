"""The TY2026+ state scaffold writes schema v2 (Phase K JK25, 2026-10-24).

scripts/assemble_state_knowledge.py hands a TY2026+ fact set to scripts/state_knowledge_v2_writer.py, which writes a
StateKnowledgeV2 pack whole (its `sources` table included) and refuses what v2 cannot carry honestly. The acceptance:
a v2 scaffold validates and passes the JK23 quote checker. The demo input (fixtures/state_scaffold_v2/) is a short
NC fact set labelled TY2026 whose every quote and figure is copied from the 2025 D-401 and Form D-400; the checker
reads those documents offline from verbatim excerpts (nc_2025_source_excerpts.yaml). No knowledge/states/*/2026.yaml
is added to the repo: every pack here is written into a temporary tree.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from taxfill_core.knowledge import StateKnowledge, load_state_knowledge, load_state_knowledge_v2
from taxfill_core.knowledge_v2 import StateKnowledgeV2

REPO = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO / "knowledge"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "state_scaffold_v2"
DEMO_INPUT = FIXTURES / "nc_2026_demo_input.json"
D401 = "https://www.ncdor.gov/2025-d-401-individual-income-tax-instructions/open"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = sys.modules.get(spec.name)
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses resolve their module by name
        spec.loader.exec_module(module)
    return module


def _demo() -> dict:
    return json.loads(DEMO_INPUT.read_text(encoding="utf-8"))


def _run(tmp_path: Path, facts: dict, year: int = 2026, *extra: str) -> tuple[int, Path]:
    """Run assemble_state_knowledge.py on ``facts`` into <tmp>/knowledge; (exit code, knowledge dir)."""
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "facts.json"
    source.write_text(json.dumps(facts), encoding="utf-8")
    code = _script("assemble_state_knowledge").main(
        ["--year", str(year), "--input", str(source), "--knowledge-dir", str(knowledge), *extra])
    return code, knowledge


@pytest.fixture(scope="module")
def demo_pack(tmp_path_factory) -> Path:
    """The demo input written by the scaffold into a copy of the knowledge tree (as <tmp>/data/knowledge)."""
    data = tmp_path_factory.mktemp("scaffold") / "data"
    shutil.copytree(KNOWLEDGE, data / "knowledge")
    (data / "formpacks").mkdir()
    code = _script("assemble_state_knowledge").main(
        ["--year", "2026", "--input", str(DEMO_INPUT), "--knowledge-dir", str(data / "knowledge")])
    assert code == 0
    return data / "knowledge" / "states" / "nc" / "2026.yaml"


# ── the acceptance: a v2 scaffold validates and passes JK23 ─────────────────────────────────────────────────────


def test_the_demo_input_becomes_a_v2_pack_that_validates(demo_pack):
    raw = yaml.safe_load(demo_pack.read_text(encoding="utf-8"))
    pack = StateKnowledgeV2.model_validate(raw)
    assert raw["schema_version"] == 2 and pack.tax_year == 2026
    # none of the blocks JK22 dropped, no v1 prose carrier
    for v1_key in ("residency", "filing_requirement", "starts_from", "treaty_note", "all_citations", "unverified"):
        assert v1_key not in raw
    assert "notes" not in raw["tax"] and all("amount" not in c for c in raw["credits"]["items"])
    # the sources table is JK20's: one row per (topic, url), ids numbered per topic in first-seen order
    assert [(r["id"], r["topic"]) for r in raw["sources"]] == [
        ("forms-1", "forms_and_instructions"), ("forms-2", "forms_and_instructions"),
        ("rates-1", "tax_rates_and_brackets"), ("rates-2", "tax_rates_and_brackets"), ("credits-1", "credits"),
        ("law-1", "law_changes"), ("logistics-1", "filing_logistics"),
    ]
    assert raw["tax"]["caveats"][2] == {"not_modeled": "the N.C. child deduction (Form D-400 Line 10)",
                                        "ref": {"id": "rates-1", "pinpoint": "Line 10"}}
    assert [g["about"] for g in raw["gaps"]] == ["logistics", "unverified"]


def test_the_v2_pack_passes_the_quote_checker_offline(demo_pack, tmp_path, monkeypatch):
    cq = _script("check_quotes")
    excerpts = yaml.safe_load((FIXTURES / "nc_2025_source_excerpts.yaml").read_text(encoding="utf-8"))
    cache = tmp_path / "quotes"
    (cache / "text").mkdir(parents=True)
    index = {}
    for url, entry in excerpts.items():  # the quote cache's own layout (check_quotes.SourceCache)
        index[url] = {"sha256": entry["sha256"], "read": "2026-10-24"}
        (cache / "text" / f"{entry['sha256']}.json").write_text(
            json.dumps({"text": entry["excerpt"], "kind": "pdf", "pages": [0]}), encoding="utf-8")
    (cache / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", str(tmp_path / "no-blanks"))

    def report(pack: Path) -> dict:
        out = tmp_path / "report.json"
        assert cq.main(["--pack", str(pack), "--cache", str(cache), "--offline", "--json", str(out), "--strict"]) in (0, 1)
        return json.loads(out.read_text(encoding="utf-8"))

    got = report(demo_pack)
    quotes = [r for r in got["spans"] if r["kind"] == "v2.quote"]
    assert {r["where"] for r in quotes} == {"treaty.note", "base_line.quote", "tax.caveats[0]", "tax.caveats[1]",
                                           "credits.items[0].eligibility"}
    assert got["totals"] == {"VERBATIM": 5, "MISMATCH": 0, "UNCHECKED": 0, "spans": 5}, got["spans"]
    # negative control: the checker really reads the excerpts — one re-worded quote is a MISMATCH
    edited = tmp_path / "edited.yaml"
    edited.write_text(demo_pack.read_text(encoding="utf-8").replace("are not entitled", "are never entitled"),
                      encoding="utf-8")
    bad = report(edited)
    assert bad["totals"]["MISMATCH"] == 1
    assert [r["where"] for r in bad["spans"] if r["status"] == "MISMATCH"] == ["credits.items[0].eligibility"]


def test_the_v2_pack_loads_as_its_v1_projection(demo_pack):
    knowledge = demo_pack.parents[2]
    pack = load_state_knowledge("nc", 2026, knowledge)
    assert isinstance(pack, StateKnowledge) and isinstance(pack.schema_v2, StateKnowledgeV2)
    assert pack.tax.notes == [
        "Multiply Line 14 by 4.25% (0.0425). If zero or less, enter a zero.",
        "If you are not eligible for the federal standard deduction, your NC standard deduction is ZERO.",
        "Not modeled: the N.C. child deduction (Form D-400 Line 10)",
        "Not modeled: N.C. itemized deductions (Form D-400 Schedule A)",
    ]
    assert pack.treaty_note.startswith("The starting point for determining North Carolina taxable income")
    assert pack.credits[0]["claimed_on"].startswith("Form D-400TC, Part 1")
    assert pack.mailing_addresses["citation"]["source"].endswith("— Where Do I File?")
    assert load_state_knowledge_v2("nc", 2026, knowledge).base_line.line == "6"


def test_the_v2_pack_works_through_the_tools(demo_pack, monkeypatch):
    monkeypatch.setenv("TAXFILL_DATA_DIR", str(demo_pack.parents[3]))
    snapshots = _script("golden_snapshots")
    raw = snapshots.snapshot_jurisdiction_year("nc", 2026)  # every JK21 reader, through the MCP server
    assert all("error" not in c for c in raw["state_tax"] if "inputs" in c)
    # calc.state_tax: the demo vector (base 50,000, single) and the printed caveats
    single = snapshots._server().calc("state_tax", {"state": "nc", "year": 2026, "taxable_base": 50000,
                                                    "filing_status": "single"})
    assert single["tax"] == 1583 and single["base_after_exemptions"] == 37250
    assert "Not modeled: the N.C. child deduction (Form D-400 Line 10)" in single["work"]
    # state_scope: the forms, the credit pointer with its quoted eligibility, the pack's citations
    [resident] = raw["state_scope"]["resident"]["states"]
    assert resident["forms"] == ["Form D-400"] and resident["must_file"] is True
    assert resident["benefits_candidates"] == [
        "Credit for Income Tax Paid to Another State or Country — Nonresidents are not entitled to this tax credit."]
    # file_and_pay and filing_summary: the mailing addresses, the payee, and no invented due date
    refund, owed = raw["file_and_pay"]["returns"][:2]
    assert refund["mailing_address"].endswith("PO Box R, Raleigh, NC 27634-0001")
    assert owed["mailing_address"].endswith("PO Box 25000, Raleigh, NC 27640-0640")
    assert any("NC Department of Revenue" in line for line in owed["payment"])
    assert refund["deadlines"] == []
    items = raw["filing_summary"]["items"]
    assert items[0]["headline"] == "NC 2026: refund $512"
    assert items[0]["deadline_status"] == "Confirm the state deadline at the state DOR."


def _own_packs_sources(raw: dict, st: str, year: int) -> None:
    from taxfill_core.state_sources import state_block
    from test_sources import check_own_packs_sources

    for newest in (True, False):
        check_own_packs_sources(raw, st, year, state_block(st, year, raw, newest=newest), None)


@pytest.mark.parametrize("gate", ["citation_shaped", "law_changes", "table_agrees", "table_parity",
                                  "own_packs_sources"])
def test_every_raw_yaml_repo_gate_passes_the_scaffolded_pack(demo_pack, gate):
    from test_state_knowledge import check_citation_shaped_mappings
    from test_state_law_change_sweep import check_law_changes_recorded
    from test_state_sources_table import check_table_agrees, check_table_parity

    gates = {"citation_shaped": check_citation_shaped_mappings, "law_changes": check_law_changes_recorded,
             "table_agrees": check_table_agrees, "table_parity": check_table_parity,
             "own_packs_sources": _own_packs_sources}
    gates[gate](yaml.safe_load(demo_pack.read_text(encoding="utf-8")), "nc", 2026)


# ── what v2 cannot carry is refused, with what to do ──────────────────────────────────────────────────────────────


def _set(facts: dict, path: tuple, value) -> dict:
    facts = copy.deepcopy(facts)
    node = facts["NC"]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return facts


_CITE = {"source": "2025 D-401 North Carolina Individual Income Tax Instructions", "url": D401}


@pytest.mark.parametrize("path, value, message", [
    (("residency_summary",), "Lived in NC for the whole year.", r"NC residency_summary: drop it: JK22 dropped"),
    (("filing_requirement_note",), "File if gross income exceeds the chart.",
     r"NC filing_requirement_note: drop it: JK22 dropped"),
    (("starts_from",), "federal AGI", r"NC starts_from: drop it .* quote the line .* as base_line"),
    (("treaty_basis",), "NC starts from federal AGI.", r"NC treaty_basis: reword it as treaty_note \{quote, citation\}"),
    (("treaty_note",), "NC starts from federal AGI.", r"NC treaty_note: is prose; .* write \{quote, citation\}"),
    (("treaty_note",), {"text": "NC starts from federal AGI."}, r"NC treaty_note.text: is the pack's own wording"),
    (("tax", "notes"), ["NC has no personal exemptions."], r"NC tax.notes: .* move each one to tax.caveats"),
    (("tax", "caveats", 0), "NC has no personal exemptions.",
     r"NC tax.caveats\[0\]: is neither a quote nor a not-modeled statement: write it as \{quote, citation\}"),
    (("tax", "caveats", 0), {"text": "NC has no personal exemptions.", "citation": _CITE},
     r"NC tax.caveats\[0\]: is neither a quote nor a not-modeled statement"),
    (("credits", "items", 0, "amount"), "up to the NC tax on that income", r"items\[0\].amount: drop it: a v2 credit is a pointer"),
    (("credits", "items", 0, "income_limit_2026"), "none", r"items\[0\].income_limit_2026: drop it"),
    (("credits", "items", 0, "eligibility"), "NC residents only.", r"eligibility: is prose"),
    (("credits", "items", 0, "claimed_on"), "Form D-400TC", r"items\[0\].claimed_on: rename it to line"),
    (("logistics", "mailing", "citation"), {"source": "a mirror", "url": "https://example.com/d401.pdf"},
     r"logistics.mailing.citation: https://example.com/d401.pdf is not a government host"),
    (("payment",), {"check_payee": "NC Department of Revenue"}, r"NC payment: move it to logistics.payment"),
    (("county_tax",), "none", r"NC county_tax: no v2 slot for this key"),
    # the v2 model's own rules come back with the field named
    (("tax", "caveats", 2, "not_modeled"), "the N.C. child deduction of $3,000",
     r"not_modeled states a figure \('\$3,000'\)"),
    (("tax", "caveats", 0, "quote"), "x" * 401, r"tax.caveats.0.quote"),
    # Phase K JK25 verifier minors (2026-10-24): a credit amount in prose, a rate that is not a decimal string
    (("credits", "caveat"), "Up to $500 per return.",
     r"NC credits.caveat: states a figure \('\$500'\); a figure goes in only as the source's words: put it in "
     r"eligibility \{quote, citation\} or drop it"),
    (("credits", "items", 0, "name"), "Credit for Tax Paid to Another State (up to $5,000)",
     r"NC credits.items\[0\].name: states a figure \('\$5,000'\); a figure goes in only as the source's words"),
    (("credits", "items", 0, "name"), "Credit for Tax Paid to Another State of 20000",
     r"NC credits.items\[0\].name: states a figure \('20000'\)"),
    (("tax", "flat_rate"), "4.25%", r'NC tax.flat_rate: a decimal string such as "0.0425"'),
    (("tax", "flat_rate"), "4.25", r'NC tax.flat_rate: a decimal string such as "0.0425" .*below 1'),
])
def test_a_field_v2_cannot_carry_is_refused_with_what_to_do(tmp_path, capsys, path, value, message):
    code, knowledge = _run(tmp_path, _set(_demo(), path, value))
    out = capsys.readouterr().out
    assert code == 1 and "REFUSED (1)" in out
    assert re.search(message, out), out
    assert not (knowledge / "states" / "nc" / "2026.yaml").exists()


def test_every_top_level_v1_key_is_named_in_one_refusal(tmp_path, capsys):
    facts = _set(_set(_demo(), ("residency_summary",), "Lived in NC."), ("treaty_basis",), "NC starts from AGI.")
    code, _ = _run(tmp_path, facts)
    out = capsys.readouterr().out
    assert code == 1 and "REFUSED (1)" in out
    assert "NC residency_summary: drop it" in out and "NC treaty_basis: reword it" in out, out


def _second_state(facts: dict, code: str = "SC") -> dict:
    """``facts`` plus a copy of its NC fact set under ``code`` (its tax block no longer names NC)."""
    facts = copy.deepcopy(facts)
    other = copy.deepcopy(facts["NC"])
    other["tax"]["state"] = None
    return {code: other, **facts}


@pytest.mark.parametrize("row, message", [
    ({"over": 0, "rate": "0.0425"}, r"SC tax.brackets.single\[0\]: needs over, but_not_over, rate"),
    ({"over": 0, "but_not_over": None, "rate": 0.0425}, r'SC tax.brackets.single\[0\].rate: a decimal string'),
    ("0-50000 at 4.25%", r"SC tax.brackets.single\[0\]: needs over, but_not_over, rate"),
])
def test_a_malformed_tax_block_is_refused_and_the_run_goes_on(tmp_path, capsys, row, message):
    facts = _second_state(_demo())
    facts["SC"]["tax"].update(flat_rate=None, classification="graduated", brackets={"single": [row]})
    code, knowledge = _run(tmp_path, facts)
    out = capsys.readouterr().out
    assert code == 1 and "REFUSED (1)" in out and re.search(message, out), out
    assert not (knowledge / "states" / "sc" / "2026.yaml").exists()
    assert (knowledge / "states" / "nc" / "2026.yaml").is_file()  # the state after it is still written


def test_a_state_code_repeated_in_another_case_is_refused(tmp_path, capsys):
    facts = _demo()
    facts["nc"] = copy.deepcopy(facts["NC"])
    code, knowledge = _run(tmp_path, facts)
    out = capsys.readouterr().out
    assert code == 1 and re.search(r"NC: the fact set names this state more than once \('NC', 'nc'\)", out), out
    assert not (knowledge / "states" / "nc" / "2026.yaml").exists()


def _credits_run(tmp_path: Path, entries: list[dict]) -> tuple[int, Path]:
    facts = _demo()
    facts["NC"].pop("credits")
    credits_file = tmp_path / "credits.json"
    credits_file.write_text(json.dumps({"result": entries}), encoding="utf-8")
    return _run(tmp_path, facts, 2026, "--credits", str(credits_file))


@pytest.mark.parametrize("key, value, message", [
    ("amount", "up to $500", r"NC --credits\[0\].amount: drop it: a v2 credit is a pointer"),
    ("income_limit", 50000, r"NC --credits\[0\].income_limit: drop it: a v2 credit is a pointer"),
    ("income_limit_2026", 50000, r"NC --credits\[0\].income_limit_2026: drop it: a v2 credit is a pointer"),
    ("notes", "see the booklet", r"NC --credits\[0\].notes: no v2 slot for this key; drop it or put it in one of "
                                 r"\['caveat', 'credits', 'state'\]"),
])
def test_a_credits_entry_key_with_no_v2_slot_is_refused(tmp_path, capsys, key, value, message):
    item = _demo()["NC"]["credits"]["items"][0]
    code, knowledge = _credits_run(tmp_path, [{"state": "NC", "credits": [item], key: value}])
    out = capsys.readouterr().out
    assert code == 1 and "REFUSED (1)" in out and re.search(message, out), out
    assert not (knowledge / "states" / "nc" / "2026.yaml").exists()


def test_a_state_repeated_in_the_credits_file_is_refused(tmp_path, capsys):
    item = _demo()["NC"]["credits"]["items"][0]
    code, knowledge = _credits_run(tmp_path, [{"state": "NC", "credits": [item]}, {"state": "nc", "credits": []}])
    out = capsys.readouterr().out
    assert code == 1 and re.search(r"NC --credits\[1\]: a second entry for this state; keep one", out), out
    assert not (knowledge / "states" / "nc" / "2026.yaml").exists()


def test_a_failed_test_vector_restores_the_tree(tmp_path, capsys):
    facts = _set(_demo(), ("tax", "test_vectors", 0, "expected_tax"), 1584)
    code, knowledge = _run(tmp_path, facts)
    assert code == 1 and "gate failed, file restored" in capsys.readouterr().out
    assert not (knowledge / "states" / "nc" / "2026.yaml").exists()


def test_a_law_change_is_written_with_its_quotes(tmp_path):
    rate = {"quote": "For tax year 2025, the individual income tax rate is 4.25%.", "citation": _CITE}
    change = {"description": "Demo: the rate the booklet states.", "quotes": [rate], "status": "final_form_published",
              "affects": ["tax.flat_rate"], "modeled": True, "citation": _CITE}
    code, knowledge = _run(tmp_path, _set(_demo(), ("law_changes", "changes"), [change]))
    assert code == 0
    raw = yaml.safe_load((knowledge / "states" / "nc" / "2026.yaml").read_text(encoding="utf-8"))
    assert raw["law_changes"]["changes"][0]["quotes"] == [{"quote": rate["quote"], "ref": {"id": "law-1"}}]
    projected = StateKnowledgeV2.model_validate(raw).to_v1()
    assert projected.effective_law_changes[0].citation.url == D401


def test_the_tax_and_credits_workflow_files_feed_the_same_pack(tmp_path):
    """--tax-dir (the tax-block workflow's JSON) and --credits (the credits research) give the same pack bytes."""
    whole_code, whole = _run(tmp_path / "whole", _demo())
    facts = _demo()
    tax, credits = facts["NC"].pop("tax"), facts["NC"].pop("credits")
    tax_dir = tmp_path / "tax"
    tax_dir.mkdir()
    (tax_dir / "nc.json").write_text(json.dumps(tax), encoding="utf-8")
    credits_file = tmp_path / "credits.json"
    credits_file.write_text(json.dumps({"result": [{"state": "NC", "caveat": credits["caveat"],
                                                    "credits": credits["items"]}]}), encoding="utf-8")
    split_code, split = _run(tmp_path / "split", facts, 2026, "--tax-dir", str(tax_dir),
                             "--credits", str(credits_file))
    assert whole_code == split_code == 0
    assert (split / "states/nc/2026.yaml").read_text() == (whole / "states/nc/2026.yaml").read_text()


def test_the_tax_block_and_credits_assemblers_refuse_ty2026_and_point_at_the_writer(tmp_path, monkeypatch, capsys):
    tax_blocks = _script("assemble_state_tax_blocks")
    monkeypatch.setattr(sys, "argv", ["assemble_state_tax_blocks.py", str(tmp_path), "--year", "2026"])
    with pytest.raises(SystemExit, match=r"--year 2026 --input FACTS --tax-dir"):
        tax_blocks.main()
    monkeypatch.setattr(sys, "argv", ["assemble_state_credits.py", str(tmp_path / "credits.json"), "2026"])
    sys.modules.pop("assemble_state_credits", None)  # YEAR is read from argv at import
    assert _script("assemble_state_credits").main() == 2
    assert "--year 2026 --input FACTS --credits FILE" in capsys.readouterr().out
    sys.modules.pop("assemble_state_credits", None)


# ── TY2025 and earlier: today's v1 behaviour, byte for byte ──────────────────────────────────────────────────────


def test_a_ty2025_run_writes_the_same_v1_bytes_as_before(tmp_path):
    # nc_2025_v1_demo_expected.yaml is the output of assemble_state_knowledge.py at main 7621b99 (before JK25) on
    # nc_2025_v1_demo_input.json.
    facts = json.loads((FIXTURES / "nc_2025_v1_demo_input.json").read_text(encoding="utf-8"))
    code, knowledge = _run(tmp_path, facts, 2025)
    assert code == 0
    written = (knowledge / "states" / "nc" / "2025.yaml").read_text(encoding="utf-8")
    assert written == (FIXTURES / "nc_2025_v1_demo_expected.yaml").read_text(encoding="utf-8")
    assert "schema_version" not in yaml.safe_load(written)


def test_the_v2_inputs_are_refused_for_a_v1_year(tmp_path):
    with pytest.raises(SystemExit):
        _run(tmp_path, {}, 2025, "--tax-dir", str(tmp_path))
    writer = _script("state_knowledge_v2_writer")
    with pytest.raises(writer.InputRefused, match=r"TY2025 packs are written as v1"):
        writer.build_pack("nc", _demo()["NC"], 2025)
