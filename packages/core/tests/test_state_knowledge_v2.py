"""State knowledge schema v2 and the dual-version loader (Phase K JK24, 2026-10-24).

The acceptance: both shapes load, and the JK21 golden diff is byte-identical. The fixtures under
fixtures/state_knowledge_v2/ are real TY2025 packs converted to v2 by scripts/convert_state_pack_v2.py (PA flat with
a convenience rule and a law-change sweep record, CA graduated with long notes and exemption credits, GA with the
amended-return block, NY graduated with a convenience rule). Swapped into a copy of the knowledge tree, each must give
its v1 pack's golden byte for byte through every JK21 reader, because today's consumers read a v2 pack through its v1
projection. No TY2025 pack in knowledge/ is v2 until JK26.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.knowledge import (
    QUOTE_MAX_CHARS,
    FormLineEntry,
    StateKnowledge,
    load_state_knowledge,
    load_state_knowledge_v2,
)
from taxfill_core.knowledge_v2 import (
    MIGRATED_WORDING_MAX_CHARS,
    NOT_MODELED_MAX_CHARS,
    BaseLine,
    NotModeled,
    Quote,
    SourceRef,
    StateKnowledgeV2,
    Wording,
)
from taxfill_core.state_sources import state_block

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO_ROOT / "knowledge"
GOLDENS = REPO_ROOT / "packages" / "core" / "tests" / "goldens" / "state_knowledge"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "state_knowledge_v2"
FIXTURE_STATES = ("pa", "ca", "ga", "ny")


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = sys.modules.get(spec.name)
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


def _fixture(st: str) -> dict:
    return yaml.safe_load((FIXTURES / f"{st}_2025.yaml").read_text(encoding="utf-8"))


def _tree_with(tmp_path: Path, packs: dict[tuple[str, int], dict | str]) -> Path:
    """A copy of knowledge/ (as <tmp>/data/knowledge) with the given state packs written over it."""
    data = tmp_path / "data"
    shutil.copytree(KNOWLEDGE, data / "knowledge")
    (data / "formpacks").mkdir()
    for (st, year), pack in packs.items():
        text = pack if isinstance(pack, str) else yaml.safe_dump(pack, sort_keys=False, allow_unicode=True)
        target = data / "knowledge" / "states" / st / f"{year}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return data / "knowledge"


# ── the acceptance: parity through every JK21 reader ─────────────────────────────


def test_the_fixtures_are_fresh_conversions_of_the_v1_packs():
    convert = _script("convert_state_pack_v2")
    assert convert.FIXTURE_STATES == FIXTURE_STATES
    for st in FIXTURE_STATES:
        assert (FIXTURES / f"{st}_2025.yaml").read_text(encoding="utf-8") == convert.convert_file(st), (
            f"{st}_2025.yaml is stale — regenerate with: python scripts/convert_state_pack_v2.py --fixtures"
        )


def test_v2_fixtures_give_every_jk21_golden_byte_for_byte(tmp_path, monkeypatch):
    knowledge = _tree_with(tmp_path, {(st, 2025): (FIXTURES / f"{st}_2025.yaml").read_text() for st in FIXTURE_STATES})
    monkeypatch.setenv("TAXFILL_DATA_DIR", str(knowledge.parent))
    for st in FIXTURE_STATES:  # the swapped packs really are read as v2
        pack = load_state_knowledge(st, 2025)
        assert isinstance(pack.schema_v2, StateKnowledgeV2), st
    problems = _script("golden_snapshots").drift(GOLDENS)
    assert not problems, "a v2 pack's projection changed what the tools emit:\n  " + "\n  ".join(problems)


def test_the_parity_check_sees_a_v2_edit(tmp_path, monkeypatch):
    # Negative control: one character of one CA caveat, in the v2 fixture, drifts the CA golden alone.
    text = (FIXTURES / "ca_2025.yaml").read_text(encoding="utf-8")
    edited = text.replace("caveats:\n  - text: '", "caveats:\n  - text: 'X", 1)
    assert edited != text
    knowledge = _tree_with(tmp_path, {("ca", 2025): edited})
    monkeypatch.setenv("TAXFILL_DATA_DIR", str(knowledge.parent))
    problems = _script("golden_snapshots").drift(GOLDENS, only={"ca_2025.json", "ca_2024.json"})
    assert len(problems) == 1 and problems[0].startswith("ca_2025.json: drifted at state_tax"), problems


@pytest.mark.parametrize("st", FIXTURE_STATES)
def test_the_source_registry_block_of_a_v2_pack_matches_its_v1_pack(st):
    v1 = yaml.safe_load((KNOWLEDGE / "states" / st / "2025.yaml").read_text(encoding="utf-8"))
    for newest in (True, False):
        assert state_block(st, 2025, _fixture(st), newest=newest) == state_block(st, 2025, v1, newest=newest)


@pytest.mark.parametrize("st", FIXTURE_STATES)
def test_the_projection_equals_the_v1_pack_field_for_field(st):
    v1 = yaml.safe_load((KNOWLEDGE / "states" / st / "2025.yaml").read_text(encoding="utf-8"))
    expected = StateKnowledge.model_validate({k: v for k, v in v1.items() if k not in ("all_citations", "unverified")})
    v2 = StateKnowledgeV2.model_validate(_fixture(st))
    assert v2.to_v1().model_dump() == expected.model_dump()
    # What v2 does not carry as typed data is said in gaps, never dropped silently.
    gaps = [g.detail for g in v2.gaps]
    assert all(any(item == g for g in gaps) for item in v1["unverified"])
    assert any(g.startswith(f"all_citations ({len(v1['all_citations'])} entries)") for g in gaps)
    assert any(g.startswith("tax.caveats: the ") for g in gaps)


def test_every_v1_pack_still_loads_unchanged():
    paths = sorted((KNOWLEDGE / "states").glob("*/[0-9][0-9][0-9][0-9].yaml"))
    assert len(paths) > 100
    for path in paths:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "schema_version" not in raw, f"{path}: no shipped pack is v2 before JK26"
        pack = load_state_knowledge(path.parent.name, int(path.stem))
        assert pack.schema_v2 is None
        assert pack.model_dump() == StateKnowledge.model_validate(raw).model_dump(), path


def test_an_explicit_schema_version_1_is_the_v1_shape(tmp_path):
    raw = yaml.safe_load((KNOWLEDGE / "states" / "ga" / "2025.yaml").read_text(encoding="utf-8"))
    knowledge = _tree_with(tmp_path, {("ga", 2025): {"schema_version": 1, **raw}})
    pack = load_state_knowledge("ga", 2025, knowledge)
    assert pack.model_dump() == load_state_knowledge("ga", 2025).model_dump()
    assert "schema_version" not in (pack.model_extra or {})


def test_load_state_knowledge_v2_returns_the_v2_model_and_refuses_v1(tmp_path):
    knowledge = _tree_with(tmp_path, {("ga", 2025): _fixture("ga")})
    v2 = load_state_knowledge_v2("ga", 2025, knowledge)
    assert isinstance(v2, StateKnowledgeV2)
    assert v2.logistics.amended_return.form == "Form 500X"
    assert load_state_knowledge("ga", 2025, knowledge).schema_v2 == v2
    with pytest.raises(ValueError, match="a schema v1 state pack — read it with load_state_knowledge"):
        load_state_knowledge_v2("ga", 2024, knowledge)


# ── refusals ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("version", [3, 0, "2", True, None])
def test_an_unknown_schema_version_is_refused(tmp_path, version):
    knowledge = _tree_with(tmp_path, {("ga", 2025): {**_fixture("ga"), "schema_version": version}})
    with pytest.raises(ValueError, match=r"is not a state knowledge schema this engine reads — write `schema_version: 2`"):
        load_state_knowledge("ga", 2025, knowledge)


@pytest.mark.parametrize("year", [2023, 2024])
def test_v2_is_refused_for_the_frozen_years(tmp_path, year):
    pack = {**_fixture("ga"), "tax_year": year}
    knowledge = _tree_with(tmp_path, {("ga", year): pack})
    with pytest.raises(ValueError, match=rf"TY{year} state packs are frozen in schema v1"):
        load_state_knowledge("ga", year, knowledge)
    with pytest.raises(ValidationError, match=rf"TY{year} state packs are frozen in schema v1"):
        StateKnowledgeV2.model_validate(pack)


def test_a_v2_file_whose_year_disagrees_with_its_path_is_refused(tmp_path):
    knowledge = _tree_with(tmp_path, {("ga", 2026): _fixture("ga")})
    with pytest.raises(ValueError, match="declares jurisdiction 'states/ga', tax_year 2025 but was loaded"):
        load_state_knowledge("ga", 2026, knowledge)


@pytest.mark.parametrize("where, extra", [
    ((), {"residency": {"rule": "x"}}),                       # a block JK22 dropped
    (("credits", "items", 0), {"amount": 100}),               # credits are pointers: no amounts
    (("logistics", "mailing"), {"citation": {"source": "s", "url": "https://dor.georgia.gov/"}}),  # refs, not citations
    (("treaty",), {"treaty_note": "x"}),
])
def test_extra_keys_are_refused(where, extra):
    pack = _fixture("ga")
    node = pack
    for key in where:
        node = node[key]
    node.update(extra)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StateKnowledgeV2.model_validate(pack)


def test_v1_tax_notes_are_refused_in_v2():
    pack = _fixture("ga")
    pack["tax"]["notes"] = ["a v1 note"]
    with pytest.raises(ValidationError, match="carries its disclosures as tax.caveats"):
        StateKnowledgeV2.model_validate(pack)


def test_a_dangling_or_out_of_range_ref_is_refused():
    pack = _fixture("ga")
    pack["citation"] = {"id": "forms-99"}
    with pytest.raises(ValidationError, match="source ref 'forms-99' names no row"):
        StateKnowledgeV2.model_validate(pack)
    pack = _fixture("ga")
    pack["citation"] = {"id": "forms-1", "description": 50}
    with pytest.raises(ValidationError, match="asks for description 50"):
        StateKnowledgeV2.model_validate(pack)


def test_the_quote_cap():
    ref = SourceRef(id="forms-1")
    assert Quote(quote="x" * QUOTE_MAX_CHARS, ref=ref).printed == "x" * QUOTE_MAX_CHARS
    with pytest.raises(ValidationError, match=f"a quote holds at most {QUOTE_MAX_CHARS}"):
        Quote(quote="x" * (QUOTE_MAX_CHARS + 1), ref=ref)
    with pytest.raises(ValidationError, match="must not start or end with whitespace"):
        Quote(quote=" Line 16 ", ref=ref)
    with pytest.raises(ValidationError, match="must not be empty"):
        Quote(quote="  ", ref=ref)
    # In a pack: an over-long caveat quote is refused at load.
    pack = _fixture("ga")
    pack["tax"]["caveats"][0] = {"quote": "y" * (QUOTE_MAX_CHARS + 1), "ref": {"id": "rates-1"}}
    with pytest.raises(ValidationError, match="a quote holds at most"):
        StateKnowledgeV2.model_validate(pack)


def test_a_caveat_quote_projects_to_the_note_state_tax_prints():
    pack = _fixture("ga")
    pack["tax"]["caveats"] = [{"quote": "Multiply Line 15c by 5.19%.", "ref": {"id": "rates-1", "pinpoint": "Line 16"}}]
    pack["citation"] = {"id": "forms-1", "pinpoint": "p. 1"}
    v1 = StateKnowledgeV2.model_validate(pack).to_v1()
    assert v1.tax.notes == ["Multiply Line 15c by 5.19%."]
    assert v1.citation.source.endswith(" — p. 1")


def test_the_formline_quote_check_is_shared():
    # FormLineEntry.printed is the federal form of a Quote: the same cap applies (Phase K JK24 generalised it).
    entry = dict(line="8", line_source="final", url="https://www.irs.gov/pub/irs-prior/f1040--2025.pdf",
                 read="2026-01-10")
    assert FormLineEntry(**entry, printed="8 Additional income from Schedule 1, line 10").line == "8"
    with pytest.raises(ValidationError, match="printed is 401 characters"):
        FormLineEntry(**entry, printed="8 " + "z" * 399)


def test_the_base_line_quote_must_show_its_designator():
    ref = SourceRef(id="forms-1")
    assert BaseLine(form="Form 500", line="8", quote=Quote(quote="8. Federal adjusted gross income", ref=ref))
    with pytest.raises(ValidationError, match="must quote the face's text at line '8'"):
        BaseLine(form="Form 500", line="8", quote=Quote(quote="Federal adjusted gross income", ref=ref))


# ── Phase K JK24 (2026-10-24) fix wave: pointer-first text binds a TY2026+ author ────────────────────────────────
#
# The review found the v2 text rules bound nothing for a new pack: {text} (Wording) was accepted wherever a Quote was
# asked for, with no length cap and an optional ref, so any amount of unreferenced prose (figures included) went in.
# Now Wording is the TY2025 conversion's carrier only (capped, and owned up to in a `migration` gap); a TY2026+ pack
# quotes ({quote, ref}) or, for a tax caveat about what the calc does not compute, says so as {not_modeled, ref}.


def _ty2026_pack() -> dict:
    """The GA fixture re-labelled TY2026 with every Wording replaced the TY2026 way (a shape fixture, tmp only)."""
    pack = _fixture("ga")
    pack["tax_year"] = 2026
    pack["tax"]["caveats"] = [
        {"quote": "Multiply Line 15c by 5.19%.", "ref": {"id": "rates-1", "pinpoint": "Line 16"}},
        {"not_modeled": "the low income credit worksheet", "ref": {"id": "credits-1"}},
    ]
    del pack["treaty"]["note"]
    for item in pack["credits"]["items"]:
        item.pop("eligibility", None)
    return pack


def test_a_ty2026_pack_that_quotes_or_points_loads_and_projects(tmp_path):
    knowledge = _tree_with(tmp_path, {("ga", 2026): _ty2026_pack()})
    pack = load_state_knowledge("ga", 2026, knowledge)
    assert pack.tax.notes == ["Multiply Line 15c by 5.19%.", "Not modeled: the low income credit worksheet"]
    assert isinstance(pack.schema_v2, StateKnowledgeV2)


_TY2026_ONLY = r"tax\.caveats\[0\]|treaty\.note|credits\.items\[0\]\.eligibility"
_REFUSED_WORDING = r"is the pack's own wording \(\{text\}\), which only a TY2025 conversion may carry"


@pytest.mark.parametrize("where, value, message", [
    (("tax", "caveats", 0), {"text": "z" * 5000}, f"at most {MIGRATED_WORDING_MAX_CHARS} characters"),  # over-long
    (("tax", "caveats", 0), {"text": "county tax is not modeled"}, _REFUSED_WORDING),                 # unreferenced
    (("tax", "caveats", 0), {"text": "county tax is not modeled", "ref": {"id": "rates-1"}}, _REFUSED_WORDING),
    (("treaty", "note"), {"text": "treaty income stays exempt"}, _REFUSED_WORDING),
    (("credits", "items", 0, "eligibility"), {"text": "Credit of $1,234 for AGI under $50,000"}, _REFUSED_WORDING),
    (("tax", "caveats", 0), {"note": "a key no text kind has"}, r"printed text must be one of \{quote, ref\}"),
])
def test_wording_is_refused_in_a_ty2026_pack(tmp_path, where, value, message):
    pack = _ty2026_pack()
    node = pack
    for key in where[:-1]:
        node = node[key]
    node[where[-1]] = value
    with pytest.raises(ValidationError, match=message) as refused:
        StateKnowledgeV2.model_validate(pack)
    if message == _REFUSED_WORDING:  # the refusal names where the wording sits
        assert re.search(_TY2026_ONLY, str(refused.value))
    knowledge = _tree_with(tmp_path, {("ga", 2026): pack})
    with pytest.raises(ValueError, match=message):
        load_state_knowledge("ga", 2026, knowledge)


def test_wording_is_capped_even_in_a_conversion():
    assert Wording(text="x" * MIGRATED_WORDING_MAX_CHARS).printed == "x" * MIGRATED_WORDING_MAX_CHARS
    with pytest.raises(ValidationError, match=f"at most {MIGRATED_WORDING_MAX_CHARS} characters"):
        Wording(text="x" * (MIGRATED_WORDING_MAX_CHARS + 1))
    pack = _fixture("ca")
    pack["tax"]["caveats"].append({"text": "z" * 5000})
    with pytest.raises(ValidationError, match=f"at most {MIGRATED_WORDING_MAX_CHARS} characters"):
        StateKnowledgeV2.model_validate(pack)


def test_the_wording_cap_holds_every_ty2025_note():
    # The cap is sized to the conversion it serves: the longest TY2025 text a converted pack carries as {text}.
    longest = 0
    for path in sorted((KNOWLEDGE / "states").glob("*/2025.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        texts = [*((raw.get("tax") or {}).get("notes") or []), raw.get("treaty_note") or ""]
        texts += [c.get("eligibility") or "" for c in raw.get("credits") or []]
        longest = max(longest, *map(len, texts))
    assert 2000 < longest <= MIGRATED_WORDING_MAX_CHARS


def test_a_ty2025_conversion_owns_up_to_its_wording_in_a_migration_gap():
    pack = _fixture("ga")
    pack["gaps"] = [g for g in pack["gaps"] if g["about"] != "migration"]
    with pytest.raises(ValidationError, match="carries the pack's own wording .* but no `gaps` entry with about: migration"):
        StateKnowledgeV2.model_validate(pack)


def test_a_not_modeled_caveat_is_short_cited_and_figure_free():
    ref = {"id": "rates-1"}
    assert NotModeled(not_modeled="the county income tax", ref=ref).printed == "Not modeled: the county income tax"
    assert NotModeled(not_modeled="the Line 49 recapture", ref=ref)  # a line number is a pointer, not a figure
    # Phase K JK24 (2026-10-24) fix round 2: a designator is not a figure, whatever its length — after the word that
    # names it, or as a letter-number code.
    for designator in ["the Georgia NOL on Line 15b", "Schedule 1 additions", "Form IT-201 line 38", "Line 1234 credits",
                       "Form 8949 basis adjustments", "Form 1040-X amendments", "Form 1099-R rollovers",
                       "the Form 540NR allocation", "the IT-2105 estimates", "the TY2026 county tax",
                       "Section 290.0131 additions", "the § 40-18-15 deduction"]:
        assert NotModeled(not_modeled=designator, ref=ref).printed == f"Not modeled: {designator}"
    for bad, message in [
        ("a per-exemption credit of $5-$26", "states a figure"),
        ("the 1% surcharge", "states a figure"),
        ("income over 1,000,000", "states a figure"),
        # Phase K JK24 (2026-10-24) fix round 2: the re-verifier's bypasses — a figure in words, the fullwidth signs,
        # a decimal, an unseparated number — and their neighbours.
        ("the 80 percent NOL limit", "states a figure \\('80 percent'\\)"),
        ("a 20 per cent surcharge", "states a figure \\('20 per cent'\\)"),
        ("credit up to 300 dollars below AGI 20000", "states a figure \\('300 dollars'\\)"),
        ("credit below AGI 20000", "states a figure \\('20000'\\)"),
        ("a credit of USD 300", "states a figure \\('USD 300'\\)"),
        ("a credit of 300 USD", "states a figure \\('300 USD'\\)"),
        ("a credit of ＄300", "states a figure \\('＄300'\\)"),
        ("the 5 ％ surcharge", "states a figure \\('5 ％'\\)"),
        ("the 5.19 rate", "states a figure \\('5.19'\\)"),
        ("income over 20 thousand", "states a figure \\('20 thousand'\\)"),
        ("the 2026 county tax", "states a figure \\('2026'\\).*write it after its word"),
        ("w" * (NOT_MODELED_MAX_CHARS + 1), f"at most {NOT_MODELED_MAX_CHARS}"),
        ("  ", "must not be empty"),
    ]:
        with pytest.raises(ValidationError, match=message):
            NotModeled(not_modeled=bad, ref=ref)
    with pytest.raises(ValidationError, match="ref\n  Field required"):
        NotModeled(not_modeled="the county income tax")


def test_a_pack_must_record_its_law_changes_or_the_check():
    # The JS2 rule (test_state_law_change_sweep.py) holds for every TY2024+ pack, so for every v2 pack.
    pack = _fixture("ga")
    pack["law_changes"] = {"changes": []}
    with pytest.raises(ValidationError, match="records no law change and no `law_changes.checked`"):
        StateKnowledgeV2.model_validate(pack)
    del pack["law_changes"]
    with pytest.raises(ValidationError, match="records no law change and no `law_changes.checked`"):
        StateKnowledgeV2.model_validate(pack)


@pytest.mark.parametrize("credit_type", [None, "partial", "Refundable"])
def test_a_credit_pointer_is_refundable_or_nonrefundable(credit_type):
    pack = _fixture("ga")
    if credit_type is None:
        del pack["credits"]["items"][0]["type"]
    else:
        pack["credits"]["items"][0]["type"] = credit_type
    with pytest.raises(ValidationError, match="credits.items.0.type"):
        StateKnowledgeV2.model_validate(pack)


# ── Phase K JK24 (2026-10-24) fix round 2: every raw-YAML gate runs over v2 packs ────────────────────────────
#
# The repo gates below read each pack's raw YAML, and no shipped pack is v2 before JK26, so over the real tree they
# never saw a v2 mapping: test_every_state_year_gets_its_own_packs_sources failed on every correct v2 pack (a v2
# `sources` table keeps rows no reference points at: the ones that backed v1 all_citations and unverified items).
# Each gate's per-pack body runs here over the four converted fixtures and the TY2026 shape pack.


def _own_packs_sources(raw: dict, st: str, year: int) -> None:
    from test_sources import check_own_packs_sources

    for newest in (True, False):  # the newest pack's registry block, and an older year's block built on demand
        check_own_packs_sources(raw, st, year, state_block(st, year, raw, newest=newest), None)


def _raw_yaml_gates():
    from test_state_knowledge import check_citation_shaped_mappings
    from test_state_law_change_sweep import check_law_changes_recorded
    from test_state_sources_table import check_table_agrees, check_table_parity

    return {
        "citation_shaped": check_citation_shaped_mappings,
        "law_changes": check_law_changes_recorded,
        "table_agrees": check_table_agrees,
        "table_parity": check_table_parity,
        "own_packs_sources": _own_packs_sources,
    }


_V2_PACKS = {**{f"{st}_2025": (lambda st=st: (_fixture(st), st, 2025)) for st in FIXTURE_STATES},
             "ga_2026": lambda: (_ty2026_pack(), "ga", 2026)}


@pytest.mark.parametrize("gate", ["citation_shaped", "law_changes", "table_agrees", "table_parity",
                                  "own_packs_sources"])
@pytest.mark.parametrize("pack", sorted(_V2_PACKS))
def test_every_raw_yaml_gate_passes_a_correct_v2_pack(gate, pack):
    raw, st, year = _V2_PACKS[pack]()
    assert raw["schema_version"] == 2
    _raw_yaml_gates()[gate](raw, st, year)


def test_the_v2_fixtures_keep_sources_rows_no_reference_points_at():
    # Why the own-sources gate reads a v2 pack's table: these rows are cited by no SourceRef (they backed v1
    # all_citations or unverified items), so the projection's citation walk never prints their URLs.
    from taxfill_core.state_sources import walk_citations

    for st in FIXTURE_STATES:
        raw = _fixture(st)
        printed = {c["url"].strip() for _, c in walk_citations(StateKnowledgeV2.model_validate(raw).to_v1().model_dump())}
        assert {row["url"].strip() for row in raw["sources"]} - printed, st


def test_the_converter_converts_ty2025_only():
    convert = _script("convert_state_pack_v2")
    raw = yaml.safe_load((KNOWLEDGE / "states" / "ga" / "2025.yaml").read_text(encoding="utf-8"))
    with pytest.raises(convert.ConversionError, match="TY2026 packs are authored in v2, not converted"):
        convert.convert({**raw, "tax_year": 2026}, "ga")
