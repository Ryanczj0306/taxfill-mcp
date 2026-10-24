"""The form a part-year or nonresident filer is told to file is cited for that role (Phase K JK28; TY2025).

Ten 2025 packs named a part-year or nonresident form in ``forms.part_year_or_nonresident`` (CA Form 540NR, NY IT-203,
IL Schedule NR, PA's one PA-40 with its residency ovals, OH IT 1040 with IT NRC, MI Schedule NR, GA Form 500 with
Schedule 3, NC D-400 with Schedule PN, NJ NJ-1040NR, MA Form 1-NR/PY) while their top-level citation was the RESIDENT
booklet or form, or a residency publication: state_scope gave a part-year or nonresident filer no pointer to the
document that tells that filer what to file. This is the defect JK27 fixed for Virginia
(test_va_760py_pointer.py). Each pack now lists, under ``forms.citations.<role>``, the 2025 instructions' own sentence
for that role (with its printed page) and, where it is a separate PDF, the form or schedule itself; state_scope adds
them for that role only.

New Jersey's entry was also wrong for a part-year filer: it named NJ-1040NR alone, but the 2025 instructions say "There
is no part-year resident return. You may have to file both Form NJ-1040 to report income you received for the part of
the year you were a resident and Form NJ-1040NR if you had income from New Jersey sources for the part of the year you
were a nonresident." (NJ-1040 instructions p. 3; NJ-1040NR instructions p. 2).

The same citations also feed the source registry (knowledge/sources_states.yaml, one description per URL and topic), so
the last three tests hold that they only ADD registry entries, leave the queries they used to move where they were, and
route a part-year or nonresident question to the role documents.

Since Phase K JK20 (2026-10-24) the registry keeps every description of a (topic, url), the first one leading and
the rest joined after it (test_state_sources_table.py); the paragraph above describes the registry as JK28 found it.
"""
from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from taxfill_core.knowledge import Citation, load_state_knowledge, validate_gov_url
from taxfill_core.schemas.profile import Profile, Provenance, ResidencePeriod, StateFootprintYear, WorkPeriod
from taxfill_core.sources import get_sources
from taxfill_core.state_sources import state_block
from taxfill_core.statescope import StateFiling, state_scope

REPO = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO / "knowledge"
US = Provenance.user_stated()
YEAR = 2025
STATES = ("ca", "ny", "il", "pa", "oh", "mi", "ga", "nc", "nj", "ma")
ROLES = ("part_year", "nonresident")
OTHER = "WA"  # the other side of the move / the home state: no income tax, so it adds no citation of its own

# Each role's own document, by the host its revenue department publishes on and a token of the document's URL.
ROLE_DOCUMENT = {
    ("ca", "part_year"): ("https://www.ftb.ca.gov/", "540nr"),
    ("ca", "nonresident"): ("https://www.ftb.ca.gov/", "540nr"),
    ("ny", "part_year"): ("https://www.tax.ny.gov/", "it203"),
    ("ny", "nonresident"): ("https://www.tax.ny.gov/", "it203"),
    ("il", "part_year"): ("https://tax.illinois.gov/", "schedule-nr"),
    ("il", "nonresident"): ("https://tax.illinois.gov/", "schedule-nr"),
    ("pa", "part_year"): ("https://www.pa.gov/", "pa-40"),
    ("pa", "nonresident"): ("https://www.pa.gov/", "pa-40"),
    ("oh", "part_year"): ("https://dam.assets.ohio.gov/", "itnrc"),
    ("oh", "nonresident"): ("https://dam.assets.ohio.gov/", "itnrc"),
    ("mi", "part_year"): ("https://www.michigan.gov/", "schedule-nr"),
    ("mi", "nonresident"): ("https://www.michigan.gov/", "schedule-nr"),
    ("ga", "part_year"): ("https://dor.georgia.gov/", "it-511"),
    ("ga", "nonresident"): ("https://dor.georgia.gov/", "it-511"),
    ("nc", "part_year"): ("https://www.ncdor.gov/", "schedule-pn"),
    ("nc", "nonresident"): ("https://www.ncdor.gov/", "schedule-pn"),
    ("nj", "part_year"): ("https://www.nj.gov/", "1040nri"),
    ("nj", "nonresident"): ("https://www.nj.gov/", "1040nr"),
    ("ma", "part_year"): ("https://www.mass.gov/", "1-nrpy"),
    ("ma", "nonresident"): ("https://www.mass.gov/", "1-nrpy"),
}
_PINPOINT = re.compile(r"\(p\. \d|\bpage \d|\bSide \d")


def _entry(st: str, lived: list[ResidencePeriod], worked: list[WorkPeriod] | None = None) -> StateFiling:
    profile = Profile(state_footprint={YEAR: StateFootprintYear(lived=lived, worked=worked or [])})
    return {s.state: s for s in state_scope(profile, YEAR, base_dir=KNOWLEDGE).states}[st.upper()]


def _filing(st: str, role: str) -> StateFiling:
    code = st.upper()
    if role == "part_year":  # lived in the state until June 30, then moved away
        return _entry(st, [ResidencePeriod(state=code, start=date(YEAR, 1, 1), end=date(YEAR, 6, 30), provenance=US),
                           ResidencePeriod(state=OTHER, start=date(YEAR, 7, 1), end=date(YEAR, 12, 31), provenance=US)])
    if role == "nonresident":  # lived elsewhere all year, worked in the state
        return _entry(st, [ResidencePeriod(state=OTHER, start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)],
                      [WorkPeriod(state=code, start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)])
    return _entry(st, [ResidencePeriod(state=code, start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)])


def _role_citations(st: str, role: str) -> list[Citation]:
    forms = getattr(load_state_knowledge(st, YEAR, KNOWLEDGE), "forms", None) or {}
    return [Citation.model_validate(c) for c in (forms.get("citations") or {}).get(role) or []]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("st", STATES)
def test_the_2025_pack_cites_the_role_form_on_the_state_site(st: str, role: str):
    cites = _role_citations(st, role)
    assert cites, f"{st} 2025: no forms.citations.{role}"
    host, token = ROLE_DOCUMENT[(st, role)]
    for c in cites:
        assert validate_gov_url(c.url) == c.url
        assert c.url.startswith(host), f"{st} {role}: {c.url} is not on the revenue department's own site"
        # a verbatim quote with the printed page it is on, as the JK27 Virginia citations carry
        assert "'" in c.source and _PINPOINT.search(c.source), f"{st} {role}: no quoted pinpoint in {c.source!r}"
    assert any(token in c.url.lower() for c in cites), f"{st} {role}: the role's own document ({token}) is not cited"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("st", STATES)
def test_state_scope_gives_the_role_its_citations(st: str, role: str):
    cites = _role_citations(st, role)
    assert cites, f"{st} 2025: no forms.citations.{role} for state_scope to add"
    entry = _filing(st, role)
    assert entry.filing_role == role and entry.must_file
    # compared as (source, url) pairs: PA, OH, GA, NC and NJ cite the primary URL again, pinned to the role's pages
    missing = [c.url for c in cites if c not in entry.citations]
    assert not missing, f"{st} {role}: state_scope entry lacks {missing}"


@pytest.mark.parametrize("st", STATES)
def test_a_resident_gains_no_role_citation(st: str):
    entry = _filing(st, "resident")
    assert entry.filing_role == "resident"
    for role in ROLES:
        cites = _role_citations(st, role)
        assert cites, f"{st} 2025: no forms.citations.{role}"
        assert not [c for c in cites if c in entry.citations], f"{st}: a full-year resident got the {role} citations"


def test_nj_part_year_filer_is_sent_to_nj_1040_for_the_resident_part():
    forms = _filing("nj", "part_year").forms
    assert len(forms) == 1
    text = forms[0]
    assert "Part-year resident: there is no part-year resident return" in text
    assert "Form NJ-1040 (New Jersey Resident Income Tax Return) for the part of the year you were a resident" in text
    assert "also Form NJ-1040NR (New Jersey Nonresident Income Tax Return) if you had income from New Jersey" in text
    assert "Nonresident: Form NJ-1040NR, if you had income from New Jersey sources." in text
    # the citation that says so is the part-year filer's, and a nonresident is not sent to the part-year rules
    quote = "You may have to file both Form NJ-1040 to report income"
    assert any(quote in c.source for c in _filing("nj", "part_year").citations)
    assert not any(quote in c.source for c in _filing("nj", "nonresident").citations)


# --- The source registry (knowledge/sources_states.yaml) is built from these same packs ------------------------------
# taxfill_core.state_sources keeps the FIRST citation of each URL per topic in file order, and get_sources routes a
# question by those descriptions. Four packs' role citations reuse a URL `all_citations` already describes (PA's PA-40,
# MI's MI-1040 book, GA's IT-511, NJ's NJ-1040NR instructions and return); with `forms` before `all_citations`, as
# Virginia's pack has it, the role pinpoints replaced those descriptions, and get_sources dropped e.g. MI "homestead
# credit" and PA "federal adjusted gross income" to a clean miss. Those packs keep `forms` at the end.


def _pack(st: str) -> dict:
    return yaml.safe_load((KNOWLEDGE / "states" / st / f"{YEAR}.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("st", STATES)
def test_role_citations_only_add_source_registry_entries(st: str):
    pack = _pack(st)
    bare = copy.deepcopy(pack)
    bare["forms"].pop("citations", None)
    before = state_block(st, YEAR, bare, newest=True)["by_topic"]
    after = state_block(st, YEAR, pack, newest=True)["by_topic"]
    for topic, entries in before.items():
        urls = {e["url"] for e in entries}
        assert [e for e in after[topic] if e["url"] in urls] == entries, (
            f"{st} {topic}: a role citation rewrote or reordered a registry entry another block describes")


# Queries whose routing the role citations moved until they were placed and quoted as they are now; each pin is the
# topic set the query reached before JK28 (and still does). CA's booklet once quoted a second 'file Form 540NR'
# sentence (one more 'file' out-tied filing_logistics); MI's Schedule NR once quoted its page-2 'must pay' sentence
# ("pay online").
_NEIGHBOURS = {
    ("ca", "do i have to file"): {"filing_logistics", "forms_and_instructions", "law_changes"},
    ("mi", "pay online"): {"filing_logistics"},
    ("mi", "homestead credit"): {"forms_and_instructions"},
    ("mi", "income tax rate"): {"forms_and_instructions", "tax_rates_and_brackets"},
    ("ga", "income tax rate"): {"forms_and_instructions", "tax_rates_and_brackets"},
    ("ga", "personal exemption"): {"forms_and_instructions", "tax_rates_and_brackets"},
    ("pa", "federal adjusted gross income"): {"forms_and_instructions"},
    ("pa", "amended return"): {"filing_logistics", "forms_and_instructions"},
    # Phase K JK20 (2026-10-24): the registry now keeps every description of a URL, and the NJ-1040NR instructions'
    # second and third ones quote "the filing threshold for your filing status" and "your filing status is: ...".
    # filing_logistics reached these two questions on its topic name alone (its entries are the mailing address and
    # the due date), so the documents that name them win.
    ("nj", "filing status"): {"forms_and_instructions"},
    ("nj", "filing threshold"): {"forms_and_instructions"},
}


@pytest.mark.parametrize(("st", "query"), sorted(_NEIGHBOURS))
def test_role_citations_leave_the_neighbouring_queries_where_they_were(st: str, query: str):
    hit = get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE)
    assert {s.topic for s in hit.sources} == _NEIGHBOURS[(st, query)], query


# A residency question reaches the role documents wherever the registry carries their text. GA's role documents (the
# IT-511 and Form 500) and PA's nonresident ones are in the registry only under descriptions other blocks give them
# (rates, deductions), which neither question reaches; that was so before JK28 and stays so here (one description per
# URL and topic).
_ROUTED = ([(st, "part_year") for st in STATES if st != "ga"]
           + [(st, "nonresident") for st in STATES if st not in ("ga", "pa")])


@pytest.mark.parametrize(("st", "role"), _ROUTED)
def test_get_sources_routes_the_residency_question_to_the_role_documents(st: str, role: str):
    cites = _role_citations(st, role)
    assert cites, f"{st} 2025: no forms.citations.{role} for the registry to carry"
    query = {"part_year": "part-year resident", "nonresident": "nonresident"}[role]
    hit = get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE)
    assert hit.matched and {s.topic for s in hit.sources} == {"forms_and_instructions"}
    urls = [s.url for s in hit.sources]
    assert all(c.url in urls for c in cites), f"{st} {query!r}: {urls}"
