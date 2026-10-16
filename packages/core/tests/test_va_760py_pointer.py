"""Virginia's state_scope entry cites the form it names for a part-year or nonresident filer (2023, 2024, 2025).

The Virginia packs name "Part-year resident: Form 760PY" and "Nonresident: Form 763", but their top-level citation is
the RESIDENT Form 760 instructions, and before 2026-10-16 that was the only document state_scope cited for either
role: a part-year filer got no pointer to Form 760PY or its instructions (found by the JK6 journey golden, the strict
xfail test_journey_3_the_760py_pointer_cites_the_760py_instructions). Each year's own instructions say which form a
filer uses, on printed page 7 under the "Which Form To File" heading (its capitalization varies by year): "As a general
rule, part-year residents file Form 760PY." (Form 760PY Instructions) and "Nonresidents File Form 763" (Form 763
Instructions). Each pack now lists the role's instructions and return under ``forms.citations.<role>``, and
state_scope adds them for that role only (JK27).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from taxfill_core.knowledge import Citation
from taxfill_core.schemas.profile import Profile, Provenance, ResidencePeriod, StateFootprintYear, WorkPeriod
from taxfill_core.sources import get_sources
from taxfill_core.statescope import StateFiling, state_scope

REPO = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO / "knowledge"
US = Provenance.user_stated()
YEARS = (2023, 2024, 2025)
VA_HOST = "https://www.tax.virginia.gov/"


def _va(year: int, lived: list[ResidencePeriod], worked: list[WorkPeriod] | None = None) -> StateFiling:
    profile = Profile(state_footprint={year: StateFootprintYear(lived=lived, worked=worked or [])})
    return {s.state: s for s in state_scope(profile, year, base_dir=KNOWLEDGE).states}["VA"]


def _part_year(year: int) -> StateFiling:  # Virginia to California on July 1, the JK6 journey-3 shape
    return _va(year, [ResidencePeriod(state="VA", start=date(year, 1, 1), end=date(year, 6, 30), provenance=US),
                      ResidencePeriod(state="CA", start=date(year, 7, 1), end=date(year, 12, 31), provenance=US)])


def _nonresident(year: int) -> StateFiling:  # lived in Washington, worked in Virginia
    return _va(year, [ResidencePeriod(state="WA", start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)],
               [WorkPeriod(state="VA", start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)])


def _resident(year: int) -> StateFiling:
    return _va(year, [ResidencePeriod(state="VA", start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)])


def _citing(filing: StateFiling, token: str) -> list[Citation]:
    # The journey's own test: the token anywhere in the serialized citation (url or source).
    return [c for c in filing.citations if token in json.dumps(c.model_dump()).lower()]


@pytest.mark.parametrize("year", YEARS)
def test_va_part_year_entry_cites_the_760py_instructions_and_return(year: int):
    va = _part_year(year)
    assert va.filing_role == "part_year" and "Form 760PY" in va.forms[0]
    py = _citing(va, "760py")
    assert len(py) == 2
    instructions, form = py
    assert "760py" in instructions.url and "instructions" in instructions.url
    assert "'As a general rule, part-year residents file Form 760PY.'" in instructions.source
    assert form.url == f"{VA_HOST}sites/default/files/taxforms/individual-income-tax/{year}/760py-{year}.pdf"
    assert f"{year} Form 760PY, Virginia Part-Year Resident Income Tax Return" in form.source
    # Virginia's own site only, and the resident booklet stays cited (it carries the pack's figures).
    assert all(c.url.startswith(VA_HOST) for c in va.citations)
    assert any(c.url.endswith(f"{year}-760-instructions.pdf") for c in va.citations)
    assert not _citing(va, "763"), "a part-year filer is pointed at the nonresident form"


@pytest.mark.parametrize("year", YEARS)
def test_va_nonresident_entry_cites_the_763_instructions_and_return(year: int):
    va = _nonresident(year)
    assert va.filing_role == "nonresident" and "Form 763" in va.forms[0]
    nr = _citing(va, "763")
    assert [c.url for c in nr] == [
        f"{VA_HOST}sites/default/files/vatax-pdf/{year}-763-instructions.pdf",
        f"{VA_HOST}sites/default/files/taxforms/individual-income-tax/{year}/763-{year}.pdf",
    ]
    assert "'Nonresidents File Form 763'" in nr[0].source
    assert all(c.url.startswith(VA_HOST) for c in va.citations)
    assert not _citing(va, "760py"), "a nonresident is pointed at the part-year form"


@pytest.mark.parametrize("year", YEARS)
def test_va_resident_entry_gains_no_role_citation(year: int):
    va = _resident(year)
    assert va.filing_role == "resident"
    assert not _citing(va, "760py") and not _citing(va, "763")


def test_every_pack_role_citation_is_a_valid_citation_under_a_known_role():
    # state_scope reads forms.citations[<filing role>]; a misspelled role key would be silently skipped and a
    # malformed entry would crash state_scope at run time — so both are held here for every shipped pack.
    roles = {"resident", "part_year", "nonresident"}
    found = 0
    for path in sorted((KNOWLEDGE / "states").glob("*/[0-9][0-9][0-9][0-9].yaml")):
        forms = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("forms") or {}
        by_role = forms.get("citations") or {}
        assert set(by_role) <= roles, f"{path.parent.name}/{path.stem}: unknown role {set(by_role) - roles}"
        for role, cites in by_role.items():
            assert isinstance(cites, list) and cites, f"{path.parent.name}/{path.stem}: {role} lists no citation"
            for c in cites:
                Citation.model_validate(c)
                found += 1
    assert found >= 12  # VA 2023-2025: two documents per role, two roles


def test_va_get_sources_routes_a_part_year_question_to_the_760py_instructions():
    # knowledge/sources_states.yaml is generated from each state's newest pack (scripts/assemble_state_sources.py),
    # so the 2025 role citations also reach get_sources, under forms_and_instructions. A part-year question that
    # matched no Virginia topic before now lands on the 760PY instructions, and each other topic's own questions
    # still route where they did (the neighbour check).
    hit = get_sources("part-year resident", 2025, "states/va", base_dir=KNOWLEDGE)
    assert hit.matched and {s.topic for s in hit.sources} == {"forms_and_instructions"}
    assert f"{VA_HOST}sites/default/files/vatax-pdf/2025-760py-instructions.pdf" in [s.url for s in hit.sources]
    for query, topics in {
        "tax rates": {"tax_rates_and_brackets"},
        "credit for low-income individuals": {"credits"},
        "earned income credit": {"credits"},
        "law changes": {"law_changes"},
        "mailing address": {"filing_logistics", "forms_and_instructions", "law_changes"},
    }.items():
        assert {s.topic for s in get_sources(query, 2025, "states/va", base_dir=KNOWLEDGE).sources} == topics, query
