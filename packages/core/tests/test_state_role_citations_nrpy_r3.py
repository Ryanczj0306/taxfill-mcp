"""TY2025 ND, NE, NM, OK, OR, RI, SC, UT, VT, WI and WV: state_scope cites each role's own form (Phase K JK28).

Each of these packs names what a part-year resident and a nonresident file (``forms.part_year_or_nonresident``):
North Dakota's Schedule ND-1NR, Nebraska's Schedule III, New Mexico's Schedule PIT-B, Oklahoma's Form 511-NR, Oregon's
Forms OR-40-P and OR-40-N, Rhode Island's Form RI-1040NR with Schedule III (part-year) or Schedule II (nonresident),
South Carolina's Schedule NR, Utah's Schedule TC-40B, Vermont's Schedule IN-113, Wisconsin's Form 1NPR and West
Virginia's Schedule A. But each pack's top-level citation is its resident booklet (New Mexico's is an overview web
page), so before 2026-10-16 a part-year or nonresident filer got no pointer to the role's own document — the defect
JK27 fixed for Virginia (test_va_760py_pointer.py). Each pack now lists that role's instructions and form under
``forms.citations.<role>``, quoting the sentence that says who files it, and state_scope adds them for that role only.

Four entries were also wrong for 2025 and are corrected from the documents now cited:

* Oregon said a part-year or nonresident filer prorates deductions and the federal tax liability subtraction by the
  Oregon percentage. The 2025 Form OR-40-N and Form OR-40-P instructions limit that to "Form OR-40-N filers only"
  (p. 21); for a part-year filer "Your Oregon tax is found by multiplying the tax on your income after Oregon
  modifications (your taxable income) by your Oregon percentage" (p. 22). The ``all_citations`` description of those
  instructions now carries the same "Form OR-40-N filers only" limit.
* West Virginia said to check "Filing as Nonresident" or "Filing as Part-Year Resident". The 2025 Form IT-140 has one
  "NONRESIDENT/PART YEAR RESIDENT" box ("Enter a check mark in this box if you are filing as a nonresident or
  part-year resident", instructions p. 24) beside a separate "NONRESIDENT SPECIAL" box. (Schedule A's Part II note
  still carries the old two-box wording; the return itself prints the one box.)
* Rhode Island said nonresidents complete RI Schedule II and part-year residents RI Schedule III. The 2025 RI-1040NR
  gives each schedule to a filer "with income from outside Rhode Island" and says "NONRESIDENTS and PART-YEAR
  RESIDENTS with all income from Rhode Island sources do not need to complete either schedule II or III" (page 3).
  The pack's ``residency.summary`` carried the same rule and is corrected with it.
* Nebraska said nonresidents and partial-year residents must attach Schedule III, leaving out the exception the 2025
  booklet prints beside that rule: a couple with one full-year resident spouse who elect a married, filing jointly
  return file a resident return, "and Schedule III cannot be used" (p. 12, Line 3).

The role citations also reach get_sources through the generated source registry, which keeps the first description of
each URL per topic. Nebraska's, New Mexico's and Oregon's role citations reuse a URL that their ``all_citations``
describe, so their ``forms`` block sits at the end of the pack, after ``all_citations``: placed before it, the role
quote replaced that description, and "treaty", "check payee" or "proration" found nothing. The tests at the end pin
both the questions and the ordering rule.

Since Phase K JK20 (2026-10-24) the registry keeps every description of a (topic, url), the first one leading and
the rest joined after it (test_state_sources_table.py); the paragraph above describes the registry as JK28 found it.
"""
from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

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
ROLES = ("part_year", "nonresident")

# Per state: the revenue department's host, then per role a URL fragment of the role's own form or schedule and the
# form name a citation for that role must carry.
STATES = {
    "nd": ("www.tax.nd.gov", {"part_year": ("28724-schedule-nd-1nr-2025.pdf", "Schedule ND-1NR"),
                              "nonresident": ("28724-schedule-nd-1nr-2025.pdf", "Schedule ND-1NR")}),
    "ne": ("revenue.nebraska.gov", {"part_year": ("2025/f_1040N_Schs.pdf", "Schedule III"),
                                    "nonresident": ("2025/f_1040N_Schs.pdf", "Schedule III")}),
    "nm": ("realfile.tax.newmexico.gov", {"part_year": ("/2025pit-b.pdf", "PIT-B"),
                                          "nonresident": ("/2025pit-b.pdf", "PIT-B")}),
    "ok": ("oklahoma.gov", {"part_year": ("/511-NR-Pkt.pdf", "Form 511-NR"),
                            "nonresident": ("/511-NR-Pkt.pdf", "Form 511-NR")}),
    "or": ("www.oregon.gov", {"part_year": ("form-or-40-p_101-055_2025.pdf", "Form OR-40-P"),
                              "nonresident": ("form-or-40-n_101-048_2025.pdf", "Form OR-40-N")}),
    "ri": ("tax.ri.gov", {"part_year": ("2025%20RI-1040NR%20Schedule%20III_w.pdf", "Schedule III"),
                          "nonresident": ("2025%20RI-1040NR%20Schedule%20II_w.pdf", "Schedule II")}),
    "sc": ("dor.sc.gov", {"part_year": ("SchNR_2025.pdf", "Schedule NR"),
                          "nonresident": ("SchNR_2025.pdf", "Schedule NR")}),
    "ut": ("files.tax.utah.gov", {"part_year": ("/2025/tc-40b.pdf", "TC-40B"),
                                  "nonresident": ("/2025/tc-40b.pdf", "TC-40B")}),
    "vt": ("tax.vermont.gov", {"part_year": ("IN-113-2025.pdf", "Schedule IN-113"),
                               "nonresident": ("IN-113-2025.pdf", "Schedule IN-113")}),
    "wi": ("www.revenue.wi.gov", {"part_year": ("2025-Form1NPR.pdf", "Form 1NPR"),
                                  "nonresident": ("2025-Form1NPR.pdf", "Form 1NPR")}),
    "wv": ("tax.wv.gov", {"part_year": ("it140.Schedule-A.2025.pdf", "Schedule A"),
                          "nonresident": ("it140.Schedule-A.2025.pdf", "Schedule A")}),
}

# Where each role has its own document, the other role must not be pointed at it.
OTHER_ROLE_ONLY = {
    "or": {"part_year": "form-or-40-n_101-048_2025.pdf", "nonresident": "form-or-40-p_101-055_2025.pdf"},
    "ri": {"part_year": "Schedule%20II_w.pdf", "nonresident": "Schedule%20III_w.pdf"},
}


def _role_cites(st: str) -> dict[str, list[dict]]:
    raw = yaml.safe_load((KNOWLEDGE / "states" / st / f"{YEAR}.yaml").read_text(encoding="utf-8")) or {}
    return (raw.get("forms") or {}).get("citations") or {}


def _entry(st: str, lived: list[ResidencePeriod], worked: list[WorkPeriod] | None = None) -> StateFiling:
    profile = Profile(state_footprint={YEAR: StateFootprintYear(lived=lived, worked=worked or [])})
    return {s.state: s for s in state_scope(profile, YEAR, base_dir=KNOWLEDGE).states}[st.upper()]


def _part_year(st: str) -> StateFiling:  # moved from the state to Washington (no income tax) on July 1
    return _entry(st, [ResidencePeriod(state=st.upper(), start=date(YEAR, 1, 1), end=date(YEAR, 6, 30), provenance=US),
                       ResidencePeriod(state="WA", start=date(YEAR, 7, 1), end=date(YEAR, 12, 31), provenance=US)])


def _nonresident(st: str) -> StateFiling:  # lived in Washington all year, worked in the state
    return _entry(st, [ResidencePeriod(state="WA", start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)],
                  [WorkPeriod(state=st.upper(), start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)])


def _resident(st: str) -> StateFiling:
    whole_year = ResidencePeriod(state=st.upper(), start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)
    return _entry(st, [whole_year])


def _pairs(cites) -> list[tuple[str, str]]:
    return [(c.source, c.url) if isinstance(c, Citation) else (c["source"].strip(), c["url"]) for c in cites]


@pytest.mark.parametrize("st", sorted(STATES))
def test_pack_carries_sourced_citations_for_both_roles(st: str):
    host, key_docs = STATES[st]
    by_role = _role_cites(st)
    assert set(by_role) == set(ROLES), f"{st}/{YEAR}: forms.citations roles {sorted(by_role)}"
    for role in ROLES:
        cites = by_role[role]
        assert cites, f"{st}/{YEAR}: forms.citations.{role} is empty"
        for c in cites:
            assert validate_gov_url(c["url"]) == c["url"]
            Citation.model_validate(c)
            assert urlparse(c["url"]).hostname == host, (st, role, c["url"])
            assert "'" in c["source"], (st, role, "no verbatim quote", c["source"][:80])
        url_part, form = key_docs[role]
        assert any(url_part in c["url"] for c in cites), (st, role, url_part)
        assert any(form in c["source"] for c in cites), (st, role, form)
    # the loader keeps the block (it is what state_scope reads)
    assert (load_state_knowledge(st, YEAR, KNOWLEDGE).forms or {}).get("citations") == by_role


@pytest.mark.parametrize("st", sorted(STATES))
def test_part_year_entry_cites_the_part_year_documents(st: str):
    entry = _part_year(st)
    assert entry.filing_role == "part_year" and entry.must_file is True
    url_part, form = STATES[st][1]["part_year"]
    assert any(url_part in c.url for c in entry.citations), f"{st}: the part-year entry cites no {form} document"
    got = _pairs(entry.citations)
    want = _pairs(_role_cites(st).get("part_year") or [])
    assert want and all(w in got for w in want), [w for w in want if w not in got]
    if st in OTHER_ROLE_ONLY:
        assert not any(OTHER_ROLE_ONLY[st]["part_year"] in url for _, url in got), "part-year filer sent to the NR form"


@pytest.mark.parametrize("st", sorted(STATES))
def test_nonresident_entry_cites_the_nonresident_documents(st: str):
    entry = _nonresident(st)
    assert entry.filing_role == "nonresident" and entry.must_file is True
    url_part, form = STATES[st][1]["nonresident"]
    assert any(url_part in c.url for c in entry.citations), f"{st}: the nonresident entry cites no {form} document"
    got = _pairs(entry.citations)
    want = _pairs(_role_cites(st).get("nonresident") or [])
    assert want and all(w in got for w in want), [w for w in want if w not in got]
    if st in OTHER_ROLE_ONLY:
        assert not any(OTHER_ROLE_ONLY[st]["nonresident"] in url for _, url in got), "nonresident sent to the PY form"


@pytest.mark.parametrize("st", sorted(STATES))
def test_resident_entry_gains_no_role_citation(st: str):
    entry = _resident(st)
    assert entry.filing_role == "resident"
    got = set(_pairs(entry.citations))
    for role in ROLES:
        leaked = [p for p in _pairs(_role_cites(st).get(role) or []) if p in got]
        assert not leaked, (st, role, leaked)
        url_part, _form = STATES[st][1][role]
        assert not any(url_part in url for _, url in got), (st, role, "resident pointed at", url_part)


def test_oregon_2025_entry_prorates_by_return_type():
    text = load_state_knowledge("or", YEAR, KNOWLEDGE).forms["part_year_or_nonresident"]
    assert "a part-year or nonresident filer prorates deductions" not in text
    assert "A nonresident (Form OR-40-N) prorates the standard or itemized deductions" in text
    assert "part-year resident (Form OR-40-P) instead multiplies the tax on taxable income by the Oregon" in text
    for entry in (_part_year("or"), _nonresident("or")):
        assert entry.forms[0] == text
    sources = " ".join(c["source"] for c in _role_cites("or")["part_year"])
    assert "Line 44 multiplied by the Oregon percentage" in sources
    # each 'What form do I use?' quote prints its whole list (p. 7), not the first lines of it
    which_form = {role: " ".join(cites[0]["source"].split()) for role, cites in _role_cites("or").items()}
    assert "qualified as an Oregon resident living abroad for part of the year." in which_form["part_year"]
    assert "are in the military, and you're treated as a nonresident for state income tax purposes." in which_form["nonresident"]
    assert "qualified as an Oregon resident living abroad for the entire year." in which_form["nonresident"]
    # the all_citations description of the same instructions carries the same limit
    raw = yaml.safe_load((KNOWLEDGE / "states" / "or" / f"{YEAR}.yaml").read_text(encoding="utf-8"))
    (described,) = [c["source"] for c in raw["all_citations"] if c["url"].endswith("or-40-p-inst_101-048-1_2025.pdf")]
    assert "the federal tax liability subtraction ('Form OR-40-N filers only', p. 21)" in " ".join(described.split())


def test_rhode_island_2025_entry_limits_the_schedules_to_income_from_outside_rhode_island():
    raw = load_state_knowledge("ri", YEAR, KNOWLEDGE).forms["part_year_or_nonresident"]
    text = " ".join(raw.split())
    assert "nonresidents complete RI Schedule II; part-year residents complete RI Schedule III" not in text
    assert "a nonresident with income from outside Rhode Island completes RI Schedule II" in text
    assert "part-year resident with income from outside Rhode Island completes RI Schedule III" in text
    assert "all from Rhode Island sources completes neither schedule" in text
    for entry in (_part_year("ri"), _nonresident("ri")):
        assert entry.forms[0] == raw
    form_quotes = {role: " ".join(c["source"] for c in cites if "1040NRWE" in c["url"])
                   for role, cites in _role_cites("ri").items()}
    assert "Schedule III should be completed by PART-YEAR" in " ".join(form_quotes["part_year"].split())
    assert "Schedule II should be completed by NONRESIDENTS" in " ".join(form_quotes["nonresident"].split())
    for role in ROLES:
        assert "do not need to complete either schedule II or III" in " ".join(form_quotes[role].split())
    # the residency summary said the same thing as the old forms entry; it now says what the forms entry says
    summary = " ".join(load_state_knowledge("ri", YEAR, KNOWLEDGE).residency["summary"].split())
    assert "nonresidents complete RI Schedule II; part-year residents complete RI Schedule III" not in summary
    assert ("(a nonresident with income from outside Rhode Island completes RI Schedule II and a part-year resident with "
            "income from outside Rhode Island completes RI Schedule III; a filer whose income is all from Rhode Island "
            "sources completes neither)") in summary


def test_nebraska_2025_entry_states_the_joint_return_exception():
    text = " ".join(load_state_knowledge("ne", YEAR, KNOWLEDGE).forms["part_year_or_nonresident"].split())
    assert "must attach Schedule III, except that a married couple with one full-year resident spouse" in text
    assert "must file a resident return, on which Schedule III cannot be used" in text
    for entry in (_part_year("ne"), _nonresident("ne")):
        assert " ".join(entry.forms[0].split()) == text
    for role in ROLES:
        booklet = " ".join(c["source"] for c in _role_cites("ne")[role] if "Booklet" in c["url"])
        assert "a resident return must be filed and Schedule III cannot be used" in " ".join(booklet.split()), role


def test_west_virginia_2025_entry_names_the_single_residency_box():
    text = load_state_knowledge("wv", YEAR, KNOWLEDGE).forms["part_year_or_nonresident"]
    assert "Filing as Nonresident" not in text and "Filing as Part-Year Resident" not in text
    assert 'single "NONRESIDENT/PART YEAR RESIDENT" box' in text and '"NONRESIDENT SPECIAL" box' in text
    for entry in (_part_year("wv"), _nonresident("wv")):
        assert entry.forms[0] == text
    sources = " ".join(c["source"] for c in _role_cites("wv")["part_year"])
    assert "NONRESIDENT OR PART-YEAR RESIDENT - Enter a check mark in this box" in sources


# knowledge/sources_states.yaml is generated from each state's newest pack (scripts/assemble_state_sources.py), so the
# role citations also reach get_sources, under forms_and_instructions. A part-year or nonresident question now lands on
# the role's own document where the pack's wording carries the query's words (Nebraska says "partial-year", New Mexico
# "non-resident", so those two keep their earlier routing), and the role text must not pull the other topics' own
# questions away from them (the neighbour check; each route below is unchanged from before the role citations).
ROUTED = {
    "part-year resident": ("part_year", ("nd", "nm", "ok", "or", "ri", "sc", "ut", "vt", "wi", "wv")),
    "nonresident": ("nonresident", ("nd", "ok", "or", "ri", "sc", "ut", "vt", "wi", "wv")),
}
NEIGHBOURS = {"tax rates": {"tax_rates_and_brackets"}, "tax brackets": {"tax_rates_and_brackets"},
              "law changes": {"law_changes"}, "credits": {"credits"}}
# Filing-logistics questions these packs answer from their filing_logistics block alone, by a wide margin, before the
# role citations and after: the role text (long, and full of "return" and "file") must not pull them into
# forms_and_instructions. (Routes decided by a point or two of token counts, such as South Carolina's "due date", are
# left out: they turn on incidental wording, not on what the role citations say.)
FILING_LOGISTICS_ROUTES = {"ne": ("extension",), "sc": ("extension",), "ut": ("mailing address",)}


@pytest.mark.parametrize("st", sorted(STATES))
def test_get_sources_routes_role_questions_to_the_role_documents(st: str):
    for query, (role, states) in ROUTED.items():
        if st not in states:
            continue
        hit = get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE)
        assert hit.matched and "forms_and_instructions" in {s.topic for s in hit.sources}, (st, query)
        url_part = STATES[st][1][role][0]
        role_docs = [s for s in hit.sources if url_part in s.url and s.topic == "forms_and_instructions"]
        assert role_docs, (st, query, url_part)
    for query, topics in NEIGHBOURS.items():
        routed = {s.topic for s in get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE).sources}
        assert routed == topics, (st, query, routed)
    for query in FILING_LOGISTICS_ROUTES.get(st, ()):
        routed = {s.topic for s in get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE).sources}
        assert routed == {"filing_logistics"}, (st, query, routed)


# The registry keeps ONE answers text per (topic, url): state_sources.state_block skips a repeat, first one wins, in file
# order. Nebraska's, New Mexico's and Oregon's role citations reuse a URL their `all_citations` describe (the Schedules
# I-III, the PIT-1 instructions, the Form OR-40-N and Form OR-40-P instructions). With `forms` before `all_citations`
# (where Virginia keeps it) the role quote replaced that description, and every question below lost the document its
# words reached ("treaty", "bullion", "check payee" and "proration" found nothing at all; the others kept only another
# topic). So those packs keep `forms` last; these pin the routes as they were before the role citations, and the guard
# after them holds the ordering rule for every state here.
KEPT_ROUTES = {
    "ne": ("2025/f_1040N_Schs.pdf", ("treaty", "bullion", "relocation incentive", "food donation")),
    "nm": ("/2025pit-1-ins.pdf", ("check payee", "PIT-PV", "where to mail", "Working Families Tax Credit", "line 16")),
    "or": ("form-or-40-n_or-40-p-inst_101-048-1_2025.pdf", ("proration", "breakpoints",
                                                            "federal tax liability subtraction")),
}


@pytest.mark.parametrize(("st", "query"), [(st, q) for st, (_, qs) in sorted(KEPT_ROUTES.items()) for q in qs])
def test_get_sources_still_reaches_the_document_a_role_citation_shares_its_url_with(st: str, query: str):
    url_part = KEPT_ROUTES[st][0]
    hit = get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE)
    assert any(url_part in s.url and s.topic == "forms_and_instructions" for s in hit.sources), (
        st, query, sorted({(s.topic, s.url.rsplit("/", 1)[-1]) for s in hit.sources}))


@pytest.mark.parametrize("st", sorted(STATES))
def test_role_citations_only_add_to_the_source_registry(st: str):
    raw = yaml.safe_load((KNOWLEDGE / "states" / st / f"{YEAR}.yaml").read_text(encoding="utf-8"))
    without = copy.deepcopy(raw)
    assert without["forms"].pop("citations", None), f"{st}/{YEAR}: no forms.citations"
    full = state_block(st, YEAR, raw, newest=True)["by_topic"]
    before = state_block(st, YEAR, without, newest=True)["by_topic"]
    for topic, entries in before.items():
        kept = {(e["url"], e["answers"]) for e in full.get(topic, [])}
        replaced = [e["url"] for e in entries if (e["url"], e["answers"]) not in kept]
        assert not replaced, f"{st}/{YEAR}: a role citation replaced the registry description of {replaced} ({topic})"
    # what ships is this block (test_sources.py::test_generated_state_registry_is_current holds the whole file current)
    shipped = yaml.safe_load((KNOWLEDGE / "sources_states.yaml").read_text(encoding="utf-8"))["states"][st]["by_topic"]
    assert shipped == full
