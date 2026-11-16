"""California's HSA and U.S.-obligation adjustments reach the tools (Phase K-W JW2b, walkthrough finding P1-08; P-038).

The first end-to-end walkthrough's California filer had W-2 box 12 code W HSA contributions and U.S. Treasury
interest. The TY2025 California pack carried nothing on either, so the agent planned the employer HSA contribution on
Schedule CA (540) line 1a and found line 1h only in the FTB booklet. The pack now carries an ``adjustments`` block,
each entry read in the 2025 Schedule CA (540) instructions (2025 Form 540 booklet pp. 59-66, and FTB's web edition):
line, column, effect on California AGI and the quote. These tests pin the entries to what was read, the use sites
(state_scope for a resident, calc state_tax's work), the source routes both ways, and that every other pack loads
as before.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.calc import state_tax
from taxfill_core.knowledge import StateAdjustmentItem, load_state_knowledge
from taxfill_core.schemas.profile import Profile, Provenance, ResidencePeriod, StateFootprintYear
from taxfill_core.sources import get_sources
from taxfill_core.statescope import state_scope

REPO_ROOT = Path(__file__).resolve().parents[3]
STATES = REPO_ROOT / "knowledge" / "states"
US = Provenance.user_stated()

# (line, column, effect) as the 2025 Schedule CA (540) instructions direct each entry (quotes in the pack).
READ = {
    "hsa_employer_contribution": ("1h", "C", "raises_state_agi"),       # p. 59, Line 1h
    "hsa_earnings": ("2", "C", "raises_state_agi"),                     # p. 59, Line 2
    "us_obligations_interest": ("2", "B", "lowers_state_agi"),          # p. 59, Line 2
    "hsa_investment_sales": ("7a", None, "figured_on_schedule"),        # p. 60, Line 7a (Schedule D (540))
    "archer_msa_rollover_to_hsa": ("8e", "C", "raises_state_agi"),      # p. 62, Line 8e
    "hsa_nonqualified_distribution": ("8f", "B", "lowers_state_agi"),   # p. 62, Line 8f
    "hsa_deduction": ("13", "B", "raises_state_agi"),                   # p. 65, Line 13 (Section C: column B raises)
    "hsa_qualified_distribution_itemized": ("4", "C", "itemized_deduction"),  # p. 66, Part II
}


def _resident(year: int, state: str = "CA", start: date | None = None) -> Profile:
    lived = [ResidencePeriod(state=state, start=start or date(year, 1, 1), end=date(year, 12, 31), provenance=US)]
    return Profile(state_footprint={year: StateFootprintYear(lived=lived, worked=[])})


def _ca_filing(profile: Profile, year: int):
    return next(s for s in state_scope(profile, year).states if s.state == "CA")


def test_p038_the_2025_pack_carries_each_entry_as_read():
    adj = load_state_knowledge("ca", 2025).adjustments
    assert adj is not None
    assert {i.id: (i.line, i.column, i.effect) for i in adj.items} == READ
    assert (adj.form, adj.schedule, adj.agi_line, adj.roles) == ("540", "Schedule CA (540)", "17", ["resident"])
    for item in adj.items:
        # the column the entry names is the column its quote names; the direction is stored apart from it
        if item.column is not None:
            assert f"column {item.column}" in item.quote, item.id
        assert item.pinpoint.startswith("booklet p. "), item.id
    assert "line 1h, column C" in adj.tagged("w2_box12_code_w")[0].quote
    assert [i.id for i in adj.tagged("us_obligations")] == ["us_obligations_interest"]
    assert adj.citation.url == "https://www.ftb.ca.gov/forms/2025/2025-540-booklet.pdf"


def test_p038_a_section_c_column_b_entry_is_said_to_raise_agi():
    # Line 13 sits in Section C (adjustments to income); line 27 subtracts line 26 from line 10 in each column, so a
    # column B entry there lowers the subtractions total. The mechanics carry the form's own words for that.
    adj = load_state_knowledge("ca", 2025).adjustments
    text = " ".join(adj.mechanics)
    assert "Subtract line 26 from line 10 in columns A, B, and C." in text
    assert "B Subtractions" in text and "C Additions" in text
    deduction = next(i for i in adj.items if i.id == "hsa_deduction")
    assert "line 13, column B (raises CA AGI)" in adj.entry_text(deduction, "CA", quoted=False)


@pytest.mark.parametrize("bad, message", [
    ({"effect": "figured_on_schedule", "column": "C"}, "names no column"),
    ({"effect": "raises_state_agi", "column": None}, "needs the `column`"),
])
def test_p038_the_column_and_the_effect_must_agree(bad, message):
    base = {"id": "x", "subject": "s", "part": "Part I", "line": "1", "quote": "q", "pinpoint": "p. 1"}
    with pytest.raises(ValidationError, match=message):
        StateAdjustmentItem.model_validate({**base, **bad})


def test_every_other_pack_loads_without_the_block():
    others = [
        (p.parent.name, int(p.stem)) for p in sorted(STATES.glob("*/*.yaml"))
        if p.stem.isdigit() and (p.parent.name, p.stem) != ("ca", "2025")
    ]
    assert len(others) >= 120
    for st, year in others:
        raw = yaml.safe_load((STATES / st / f"{year}.yaml").read_text(encoding="utf-8"))
        assert "adjustments" not in raw, (st, year)
        assert load_state_knowledge(st, year).adjustments is None, (st, year)


def test_p038_state_scope_names_the_hsa_addition_and_the_treasury_subtraction_for_a_resident():
    ca = _ca_filing(_resident(2025), 2025)
    line = next(w for w in ca.warnings if w.startswith("CA adjustments (Schedule CA (540)"))
    assert "verified on the 2025 Schedule CA (540) instructions" in line
    assert "Schedule CA (540), Part I, Section A, line 1h, column C (raises CA AGI)" in line
    assert "box 12, code W on line 1h, column C" in line
    assert "line 2, column B (lowers CA AGI)" in line and "U.S. Treasury bills, notes, and bonds" in line
    assert "Part I, Section C, line 13, column B (raises CA AGI)" in line
    assert "Form 540 line 17" in line and "many other adjustments" in line
    urls = {c.url for c in ca.citations}
    assert "https://www.ftb.ca.gov/forms/2025/2025-540-ca-instructions.html" in urls


def test_p038_a_part_year_filer_and_other_years_get_no_resident_schedule_lines():
    # The block was read off the resident Schedule CA (540); a part-year filer files Form 540NR and its own schedule.
    part_year = _ca_filing(_resident(2025, start=date(2025, 7, 1)), 2025)
    assert part_year.filing_role == "part_year"
    assert not any(w.startswith("CA adjustments") for w in part_year.warnings)
    for year in (2023, 2024):
        resident = _ca_filing(_resident(year), year)
        assert not any(w.startswith("CA adjustments") for w in resident.warnings), year


def test_p038_state_tax_work_says_what_california_agi_must_carry():
    work = state_tax("ca", 120_000, 2025).work
    tail = work[work.index("CA AGI (Form 540 line 17) must already carry"):]
    assert "line 1h, column C (raises CA AGI)" in tail and "line 2, column B (lowers CA AGI)" in tail
    assert "line 13, column B (raises CA AGI)" in tail
    assert "itemized" not in tail.split("[", 1)[0]   # Part II line 4 is not part of the AGI the op starts from
    assert "Schedule CA (540) entries" not in state_tax("ca", 120_000, 2024).work
    assert "must already carry" not in state_tax("il", 120_000, 2025).work


# ── routing both ways (the knowledge-gap pattern's neighbour theft) ──────────────────────────────────────────────

FORWARD = ("HSA deduction", "HSA", "HSA contributions", "California adjustments", "subtractions and additions",
           "Treasury interest", "U.S. obligations interest", "U.S. savings bonds")
# The TY2025 California routes before JW2b (main 464642f) of queries a first cut of the new topic took (JW2b fix
# round): its descriptions carried the bare words "schedule", "interest", "W-2", "savings", "federal AGI" and three
# "540"s, and the assembly rows "Schedule CA (540)" twice and "540" four times. [] is a clean miss, which must not
# turn into a false match. "health savings account" stays a clean miss here: its words would bring "savings" along.
BACKWARD = {
    "interest and penalties": [], "W-2 withholding": [], "W-2 wages": [], "savings": [], "college savings": [],
    "health savings account": [], "health insurance": ["forms_and_instructions", "law_changes", "tax_rates_and_brackets"],
    "tax schedule": ["forms_and_instructions"], "schedule": ["forms_and_instructions"],
    "federal AGI": ["forms_and_instructions"], "Schedule CA": ["forms_and_instructions"],
    "Schedule CA (540)": ["forms_and_instructions"], "Schedule CA instructions": ["forms_and_instructions"],
    "Schedule D": ["forms_and_instructions"], "Schedule D (540)": ["forms_and_instructions"],
    "Form 540": ["tax_rates_and_brackets"], "W-2": ["tax_rates_and_brackets"],
    "interest": ["filing_logistics"], "California adjusted gross income": ["filing_logistics"],
    "payment voucher": ["forms_and_instructions", "law_changes"], "line 13": ["forms_and_instructions"],
}
FEDERAL = {   # the federal routes before JW2b, unchanged
    "HSA deduction": ["contribution_limits"],
    "HSA contribution limit": ["contribution_limits"],
    "health savings account": ["investment_income"],
    "Form 8889": [],
}
# The pinned TY2025 California routes of the JK20 route probe (test_state_source_routes.py): the new topic takes
# none of them, and each still reaches what it reached before JW2b.
PIN = REPO_ROOT / "packages" / "core" / "tests" / "goldens" / "state_source_routes.json"


@pytest.mark.parametrize("query", FORWARD)
def test_p038_california_hsa_and_schedule_ca_queries_reach_the_adjustments_topic(query):
    result = get_sources(query, 2025, "states/ca")
    assert {s.topic for s in result.sources} == {"income_adjustments"}, query
    assert "income_adjustments" in result.available_topics


@pytest.mark.parametrize("query, topics", BACKWARD.items())
def test_the_adjustments_topic_takes_no_neighbour_query(query, topics):
    assert sorted({s.topic for s in get_sources(query, 2025, "states/ca").sources}) == topics, query


def test_a_540nr_filer_asking_for_schedule_ca_still_reaches_the_540nr_booklet():
    urls = {s.url for s in get_sources("Schedule CA (540)", 2025, "states/ca").sources}
    assert "https://www.ftb.ca.gov/forms/2025/2025-540nr-booklet.pdf" in urls


@pytest.mark.parametrize("query, topics", FEDERAL.items())
def test_federal_hsa_queries_still_route_federal(query, topics):
    assert sorted({s.topic for s in get_sources(query, 2025, "federal").sources}) == topics


def test_the_existing_california_topics_keep_their_queries():
    import json

    pinned = {q: routes["ca|2025"] for q, routes in json.loads(PIN.read_text(encoding="utf-8"))["routes"].items()
              if "ca|2025" in routes}
    assert len(pinned) >= 10
    for query, topics in pinned.items():
        now = sorted({s.topic for s in get_sources(query, 2025, "states/ca").sources})
        assert now == sorted(topics) and "income_adjustments" not in now, (query, now)


def test_older_california_years_offer_no_adjustments_topic():
    for year in (2023, 2024):
        assert "income_adjustments" not in get_sources("HSA", year, "states/ca").available_topics
