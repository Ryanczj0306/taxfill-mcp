"""TY2025 IN, KS, KY, LA, MD, ME, MN, MO, MS and MT: state_scope cites each role's own form (Phase K JK28).

Each of these packs names what a part-year resident and a nonresident file (``forms.part_year_or_nonresident``):
Indiana's Form IT-40PNR (and IT-40RNR for reciprocal-state wage earners), Kansas's Schedule S Part B, Kentucky's Form
740-NP (and 740-NP-R), Louisiana's IT-540B, Maryland's Forms 505/505NR/515, Maine's Schedules NR and NRH, Minnesota's
Schedule M1NR, Missouri's Forms MO-NRI and MO-CR, Mississippi's Form 80-205 and Montana's Schedule II. But each pack's
top-level citation is its RESIDENT booklet or form, so before 2026-10-16 a part-year or nonresident filer got no
pointer to the role's own document — the defect JK27 fixed for Virginia (test_va_760py_pointer.py). Each pack now
lists that role's instructions and form under ``forms.citations.<role>``, quoting the sentence that says who files
it, and state_scope adds them for that role only.

The Maryland entry was also wrong: it said "Part-year residents do NOT use 505", but the 2025 Form 505 instructions
send a mover who "received income from Maryland sources while you were a nonresident of Maryland" to "Form 505
Nonresident Return and Form 502 Resident Return" (Instruction 1) — "you are required to file two returns with the
State of Maryland" (Instruction 28).

The source registry (knowledge/sources_states.yaml) is generated from the same packs and keeps only the first citation
of a URL under each topic, reading ``forms`` before ``all_citations``. A role citation that reuses a URL the pack
already describes therefore becomes that URL's registry description, so the first role entry of such a URL (Maryland's
nonresident booklet, Kansas's Schedule S) ends, after ' | ', with the older description verbatim.

Since Phase K JK20 (2026-10-24) the registry keeps every description of a (topic, url), the first one leading and
the rest joined after it (test_state_sources_table.py); the paragraph above describes the registry as JK28 found it.
"""
from __future__ import annotations

from datetime import date
from functools import cache
from pathlib import Path

import pytest
import yaml

from taxfill_core.knowledge import Citation, load_state_knowledge, validate_gov_url
from taxfill_core.schemas.profile import Profile, Provenance, ResidencePeriod, StateFootprintYear, WorkPeriod
from taxfill_core.sources import get_sources
from taxfill_core.state_sources import BLOCK_TO_TOPIC, FALLBACK_TOPIC, is_gov, walk_citations
from taxfill_core.statescope import StateFiling, state_scope

REPO = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO / "knowledge"
US = Provenance.user_stated()
YEAR = 2025
ROLES = ("part_year", "nonresident")
STATES = ("in", "ks", "ky", "la", "md", "me", "mn", "mo", "ms", "mt")
MD_NR_BOOKLET = "https://www.marylandcomptroller.gov/content/dam/mdcomp/tax/instructions/2025/nonresident-booklet.pdf"
KS_SCHEDULE_S = "https://www.ksrevenue.gov/pdf/schs25.pdf"

# Per state and role: a URL fragment of the role's own document, and the form it must name.
KEY_DOCS = {
    "in": {"part_year": ("forms.in.gov/Download.aspx?id=16919", "IT-40PNR"),
           "nonresident": ("forms.in.gov/Download.aspx?id=16925", "IT-40RNR")},
    "ks": {"part_year": ("ksrevenue.gov/pdf/schs25.pdf", "Part B of Schedule S"),
           "nonresident": ("ksrevenue.gov/pdf/schs25.pdf", "Part B of Schedule S")},
    "ky": {"part_year": ("revenue.ky.gov/Forms/25_42A740-NP.pdf", "Form 740-NP"),
           "nonresident": ("revenue.ky.gov/Forms/740-NP-R%20(2025).pdf", "Form 740-NP-R")},
    "la": {"part_year": ("dam.ldr.la.gov/taxforms/IT540B(2025)WEB-BC-F.pdf", "IT-540B"),
           "nonresident": ("dam.ldr.la.gov/taxforms/IT540B(2025)WEB-BC-F.pdf", "IT-540B")},
    "md": {"part_year": ("tax/instructions/2025/nonresident-booklet.pdf", "two returns"),
           "nonresident": ("tax/forms/2025/505.pdf", "Form 505")},
    "me": {"part_year": ("25_1040me_sch_nr_fillable.pdf", "Schedule NR"),
           "nonresident": ("25_1040me_sch_nr_fillable.pdf", "Schedule NR")},
    "mn": {"part_year": ("revenue.state.mn.us/sites/default/files/2026-07/m1nr-25.pdf", "Schedule M1NR"),
           "nonresident": ("revenue.state.mn.us/sites/default/files/2026-07/m1nr-25.pdf", "Schedule M1NR")},
    "mo": {"part_year": ("dor.mo.gov/forms/MO-NRI_2025.pdf", "MO-NRI"),
           "nonresident": ("dor.mo.gov/forms/MO-NRI_2025.pdf", "MO-NRI")},
    "ms": {"part_year": ("tax-forms/individual/80205258%201.pdf", "Form 80-205"),
           "nonresident": ("tax-forms/individual/80205258%201.pdf", "Form 80-205")},
    "mt": {"part_year": ("Form_2_2025_Schedule_II.pdf", "Schedule II"),
           "nonresident": ("Form_2_2025_Schedule_II.pdf", "Schedule II")},
}

# A reciprocal-state form is for a full-year nonresident only; a part-year filer must not be pointed at it.
NONRESIDENT_ONLY = {"in": "Download.aspx?id=16925", "ky": "740-NP-R"}


def _raw_pack(st: str) -> dict:
    return yaml.safe_load((KNOWLEDGE / "states" / st / f"{YEAR}.yaml").read_text(encoding="utf-8")) or {}


@cache
def _registry() -> dict:
    return yaml.safe_load((KNOWLEDGE / "sources_states.yaml").read_text(encoding="utf-8"))


def _role_cites(st: str) -> dict[str, list[dict]]:
    return (_raw_pack(st).get("forms") or {}).get("citations") or {}


def _entry(st: str, lived: list[ResidencePeriod], worked: list[WorkPeriod] | None = None) -> StateFiling:
    profile = Profile(state_footprint={YEAR: StateFootprintYear(lived=lived, worked=worked or [])})
    return {s.state: s for s in state_scope(profile, YEAR, base_dir=KNOWLEDGE).states}[st.upper()]


def _part_year(st: str) -> StateFiling:  # moved from the state to California on July 1
    return _entry(st, [ResidencePeriod(state=st.upper(), start=date(YEAR, 1, 1), end=date(YEAR, 6, 30), provenance=US),
                       ResidencePeriod(state="CA", start=date(YEAR, 7, 1), end=date(YEAR, 12, 31), provenance=US)])


def _nonresident(st: str) -> StateFiling:  # lived in Washington all year, worked in the state
    return _entry(st, [ResidencePeriod(state="WA", start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)],
                  [WorkPeriod(state=st.upper(), start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)])


def _resident(st: str) -> StateFiling:
    full_year = ResidencePeriod(state=st.upper(), start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)
    return _entry(st, [full_year])


def _pairs(cites) -> list[tuple[str, str]]:
    return [(c.source, c.url) if isinstance(c, Citation) else (c["source"].strip(), c["url"]) for c in cites]


def _topics(st: str, query: str) -> set[str]:
    return {s.topic for s in get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE).sources}


@pytest.mark.parametrize("st", STATES)
def test_pack_carries_sourced_citations_for_both_roles(st: str):
    by_role = _role_cites(st)
    for role in ROLES:
        cites = by_role.get(role) or []
        assert cites, f"{st}/{YEAR}: forms.citations.{role} is missing or empty"
        for c in cites:
            assert validate_gov_url(c["url"]) == c["url"]
            Citation.model_validate(c)
            # every pointer is to the 2025 document and quotes or describes it in place
            assert c["source"].startswith(f"{YEAR} "), (st, role, c["source"][:60])
        url_part, form = KEY_DOCS[st][role]
        assert any(url_part in c["url"] for c in cites), (st, role, url_part)
        assert any(form in c["source"] for c in cites), (st, role, form)
    # the loader keeps the block (it is what state_scope reads)
    assert (load_state_knowledge(st, YEAR, KNOWLEDGE).forms or {}).get("citations") == by_role


@pytest.mark.parametrize("st", STATES)
def test_part_year_entry_cites_the_part_year_documents(st: str):
    entry = _part_year(st)
    assert entry.filing_role == "part_year" and entry.must_file is True
    got = _pairs(entry.citations)
    want = _pairs(_role_cites(st)["part_year"])
    assert want and all(w in got for w in want), [w for w in want if w not in got]
    if st in NONRESIDENT_ONLY:
        assert not any(NONRESIDENT_ONLY[st] in url for _, url in got), \
            "a part-year filer is pointed at a nonresident-only form"


@pytest.mark.parametrize("st", STATES)
def test_nonresident_entry_cites_the_nonresident_documents(st: str):
    entry = _nonresident(st)
    assert entry.filing_role == "nonresident" and entry.must_file is True
    got = _pairs(entry.citations)
    want = _pairs(_role_cites(st)["nonresident"])
    assert want and all(w in got for w in want), [w for w in want if w not in got]


@pytest.mark.parametrize("st", STATES)
def test_resident_entry_gains_no_role_citation(st: str):
    entry = _resident(st)
    assert entry.filing_role == "resident"
    got = _pairs(entry.citations)
    role_sources = {s for role in ROLES for s, _ in _pairs(_role_cites(st).get(role) or [])}
    assert not any(s in role_sources for s, _ in got)


def test_md_part_year_entry_names_the_two_return_rule():
    # The 2025 Form 505 instructions (Instructions 1 and 28): a mover with Maryland-source income while a nonresident
    # files Form 505 AND Form 502 — the old entry said "Part-year residents do NOT use 505".
    entry = _part_year("md")
    assert "do NOT use 505" not in entry.forms[0]
    assert "two returns, Form 502 and Form 505" in entry.forms[0]
    rule = "you are required to file two returns with the State of Maryland"
    two_returns = [c for c in entry.citations if rule in c.source]
    assert [c.url for c in two_returns] == [MD_NR_BOOKLET]


# --- The source registry (knowledge/sources_states.yaml) is built from these same packs ------------------------------
@pytest.mark.parametrize("st", STATES)
def test_no_role_citation_drops_an_older_description_from_the_source_registry(st: str):
    # state_sources.state_block keeps the FIRST citation of each (topic, url) and walks `forms` before `all_citations`.
    # Maryland's part-year quote once replaced the nonresident booklet's all_citations description (the second-pass
    # source for Tax Rate Schedules I and II, the Form 505NR worksheet rows and the line 31a/32d additional tax on net
    # capital gain income), and get_sources stopped routing "capital gain", "worksheet" and "net capital gain additional
    # tax" to the booklet. The first role entry of a shared URL now ends with the older description, verbatim.
    raw = _raw_pack(st)
    role_ids = {id(c) for cites in ((raw.get("forms") or {}).get("citations") or {}).values() for c in cites}
    first: dict[tuple[str, str], dict] = {}
    carried: list[tuple[str, str, str]] = []
    for block, cite in walk_citations(raw):
        url = cite["url"].strip()
        if not is_gov(url):
            continue
        key = (BLOCK_TO_TOPIC.get(block or "", FALLBACK_TOPIC), url)
        if key not in first:
            first[key] = cite
        elif id(first[key]) in role_ids and id(cite) not in role_ids:
            text = cite["source"].strip()
            assert text in first[key]["source"], f"{st}: the role citation of {url} drops {text[:90]!r}"
            carried.append((*key, text))
    if st in ("ks", "md"):  # the two packs whose role citations reuse a URL all_citations describes
        assert {url for _, url, _ in carried} == {"ks": {KS_SCHEDULE_S}, "md": {MD_NR_BOOKLET}}[st]
    by_topic = _registry()["states"][st]["by_topic"]
    for topic, url, text in carried:
        assert any(e["url"] == url and text in e["answers"] for e in by_topic[topic]), (st, url)


@pytest.mark.parametrize(
    ("st", "query", "url"),
    [
        ("md", "capital gain", MD_NR_BOOKLET),
        ("md", "worksheet", MD_NR_BOOKLET),
        ("md", "net capital gain additional tax", MD_NR_BOOKLET),
        ("md", "second pass", MD_NR_BOOKLET),
        ("ks", "Schedule S", KS_SCHEDULE_S),
        ("ks", "modifications", KS_SCHEDULE_S),
    ],
)
def test_get_sources_still_reaches_the_documents_whose_url_a_role_citation_reuses(st: str, query: str, url: str):
    hit = get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE)
    assert url in [s.url for s in hit.sources if s.topic == "forms_and_instructions"], (st, query)


# The role citations land under forms_and_instructions, so a role question now reaches the role's documents.
@pytest.mark.parametrize("st", STATES)
def test_get_sources_routes_role_questions_to_the_role_documents(st: str):
    for query, role in (("part-year resident", "part_year"), ("nonresident", "nonresident")):
        hit = get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE)
        assert hit.matched and "forms_and_instructions" in {s.topic for s in hit.sources}, (st, query)
        url_part = KEY_DOCS[st][role][0]
        assert any(url_part in s.url for s in hit.sources if s.topic == "forms_and_instructions"), (st, query, url_part)


# Neighbouring topics keep their questions: each route below is the one the query took in the registry before JK28
# (compared over 128 queries per state, before and after the role citations). Some were moved by an earlier draft of
# the role text and put back: Kentucky's "refund" questions (the 740-NP-R sentence is quoted up to "nonresidents", so
# its "to claim a refund" clause no longer out-counts the filing_logistics refund address), Indiana's "other state
# credit" (the IT-40RNR entry describes the form; its note's "a state other than those listed" had out-counted
# tax_rates_and_brackets), Louisiana's "rate schedules" (the IT-540B entry no longer says "schedules") and Maryland's
# capital-gain, worksheet and "second pass" questions (the nonresident booklet's older description is back, see the
# registry test above). The other routes added with them never moved: Kansas's Schedule S questions (the role entry
# carries Schedule S's older description), Indiana's "credit for taxes paid to another state", Maryland's "rate
# schedules" and Maine's "refund". Only routes that matched something are pinned, so a later fix to one of the misses
# does not trip this test.
NEIGHBOUR_ROUTES = {
    "in": {"tax rates": {"tax_rates_and_brackets"}, "earned income credit": {"credits"}, "law changes": {"law_changes"},
           "mailing address": {"forms_and_instructions"}, "due date": {"forms_and_instructions"},
           "payment": {"filing_logistics", "forms_and_instructions"},
           "other state credit": {"tax_rates_and_brackets"},
           "credit for taxes paid to another state": {"tax_rates_and_brackets"}},
    "ks": {"tax rates": {"tax_rates_and_brackets"}, "law changes": {"law_changes"},
           "mailing address": {"forms_and_instructions"}, "due date": {"filing_logistics"},
           "payment": {"forms_and_instructions"}, "standard deduction": {"forms_and_instructions"},
           "Schedule S": {"forms_and_instructions"}, "modifications": {"forms_and_instructions"}},
    "ky": {"tax rates": {"tax_rates_and_brackets"}, "law changes": {"law_changes"},
           "mailing address": {"filing_logistics", "forms_and_instructions", "law_changes"},
           "due date": {"filing_logistics"}, "extension": {"filing_logistics"}, "payment": {"forms_and_instructions"},
           "standard deduction": {"tax_rates_and_brackets"},
           "refund": {"filing_logistics", "forms_and_instructions"},
           "refund mailing address": {"filing_logistics", "forms_and_instructions"}},
    "la": {"tax rates": {"tax_rates_and_brackets"}, "law changes": {"law_changes"},
           "mailing address": {"law_changes"}, "due date": {"forms_and_instructions"},
           # JK20: + forms_and_instructions, whose joined descriptions name "payment" too.
           "payment": {"filing_logistics", "forms_and_instructions", "law_changes"},
           "standard deduction": {"law_changes"},
           "rate schedules": {"tax_rates_and_brackets"}},
    "md": {"tax rates": {"tax_rates_and_brackets"}, "law changes": {"law_changes"},
           "mailing address": {"filing_logistics"}, "payment": {"filing_logistics"},
           "standard deduction": {"law_changes"},
           "capital gain": {"forms_and_instructions", "law_changes"},
           "capital gains": {"forms_and_instructions", "law_changes"},
           "net capital gain additional tax": {"forms_and_instructions"},
           "capital gain additional tax": {"forms_and_instructions"},
           "worksheet": {"forms_and_instructions", "law_changes", "tax_rates_and_brackets"},
           "second pass": {"forms_and_instructions", "tax_rates_and_brackets"},
           "rate schedules": {"tax_rates_and_brackets"}},
    "me": {"tax rates": {"tax_rates_and_brackets"}, "earned income credit": {"credits"}, "law changes": {"law_changes"},
           "mailing address": {"filing_logistics", "forms_and_instructions"},
           # JK20: + law_changes, whose joined booklet descriptions name the "due date" as well.
           "due date": {"filing_logistics", "forms_and_instructions", "law_changes"},
           "payment": {"filing_logistics", "forms_and_instructions"},
           "standard deduction": {"forms_and_instructions", "tax_rates_and_brackets"},
           "refund": {"filing_logistics", "forms_and_instructions"}},
    "mn": {"tax rates": {"tax_rates_and_brackets"}, "earned income credit": {"credits"}, "law changes": {"law_changes"},
           "mailing address": {"forms_and_instructions"}, "due date": {"forms_and_instructions", "law_changes"},
           "payment": {"forms_and_instructions"}, "standard deduction": {"forms_and_instructions"}},
    "mo": {"tax rates": {"tax_rates_and_brackets"}, "law changes": {"law_changes"},
           "mailing address": {"forms_and_instructions", "law_changes"},
           # JK20: + filing_logistics, whose joined descriptions name the "due date" (it reached it on one word before).
           "due date": {"filing_logistics", "forms_and_instructions", "law_changes"},
           "payment": {"forms_and_instructions"},
           "standard deduction": {"law_changes"}},
    "ms": {"tax rates": {"tax_rates_and_brackets"}, "law changes": {"law_changes"},
           "mailing address": {"filing_logistics", "forms_and_instructions"}, "due date": {"forms_and_instructions"},
           "payment": {"forms_and_instructions"}, "standard deduction": {"tax_rates_and_brackets"}},
    "mt": {"tax rates": {"tax_rates_and_brackets"}, "earned income credit": {"credits"}, "law changes": {"law_changes"},
           "mailing address": {"forms_and_instructions", "law_changes"},
           "due date": {"forms_and_instructions", "law_changes"},
           "payment": {"filing_logistics", "forms_and_instructions"}, "standard deduction": {"forms_and_instructions"}},
}


@pytest.mark.parametrize("st", STATES)
def test_get_sources_neighbour_topics_keep_their_questions(st: str):
    for query, topics in NEIGHBOUR_ROUTES[st].items():
        assert _topics(st, query) == topics, (st, query)


# Routes the role citations DID move, each reviewed and accepted, and pinned so that a later edit cannot move them
# again unseen; every route that lost a topic on the 73 queries the JK28 verifier sampled is here. get_sources scores
# a topic by the query's words in the joined text of its entries, with a point for every repeat, so the long role
# quotes win close calls.
MOVED_ROUTES = {
    # A residency or which-form question now reaches the role documents (the earlier topic is named after each).
    ("in", "resident"): {"forms_and_instructions"},  # + credits + filing_logistics
    ("ky", "resident"): {"forms_and_instructions"},  # + tax_rates
    ("la", "resident"): {"forms_and_instructions"},  # + law_changes + tax_rates
    ("mo", "resident"): {"forms_and_instructions"},  # + law_changes
    ("md", "nonresident"): {"forms_and_instructions"},  # tax_rates; Forms 505, 505NR and 515 are now cited
    ("me", "part-year resident"): {"forms_and_instructions"},  # credits
    ("la", "who must file"): {"forms_and_instructions"},  # law_changes; quoted 'WHO MUST FILE A RETURN (FORM IT-540B)'
    ("md", "who must file"): {"forms_and_instructions"},  # law_changes; quoted Instruction 1 'WHO MUST FILE?'
    ("me", "who must file"): {"forms_and_instructions"},  # + filing_logistics; the same booklet is under both
    ("me", "schedule"): {"forms_and_instructions"},  # tax_rates; Schedules NR and NRH are now cited
    ("mo", "income percentage"): {"forms_and_instructions"},  # law_changes + tax_rates; Form MO-NRI is its title
    ("md", "505NR"): {"forms_and_instructions"},  # + tax_rates; Form 505NR itself is now cited
    ("md", "nonresident tax rate"): {"forms_and_instructions"},  # tax_rates; the 505 booklet prints the schedules
    ("md", "local income tax"): {"forms_and_instructions"},  # law_changes; Form 515 is the nonresident local return
    # filing_logistics matched these on its topic NAME alone (its entries do not use the words); the role quote does:
    ("mn", "minimum filing"): {"forms_and_instructions"},  # M1NR: 'if you meet the minimum filing requirement'
    ("me", "filing status"): {"forms_and_instructions"},  # Schedule NR: 'use the same filing status'
    # Decided by a word every role sentence needs ("return", "file", "year", "spouse", "personal", the "2" of "p. 2");
    # no topic speaks to the question itself, before or after: no Indiana, Kentucky or Maine entry says "amended", and
    # the filing_logistics entries these left are mailing addresses and due dates.
    ("in", "amended return"): {"forms_and_instructions"},  # filing_logistics
    ("ky", "amended return"): {"forms_and_instructions"},  # + filing_logistics + tax_rates
    ("me", "amended return"): {"forms_and_instructions"},  # + filing_logistics
    ("ky", "e-file"): {"forms_and_instructions"},  # filing_logistics
    ("la", "e-file"): {"forms_and_instructions"},  # law_changes
    ("md", "e-file"): {"forms_and_instructions"},  # law_changes
    ("me", "e-file"): {"forms_and_instructions"},  # + filing_logistics + tax_rates
    ("ky", "fiscal year"): {"forms_and_instructions"},  # filing_logistics
    ("mn", "fiscal year"): {"forms_and_instructions"},  # tax_rates
    ("mo", "spouse"): {"forms_and_instructions"},  # + tax_rates; MO-CR 'if you or your spouse have income'
    ("la", "W-2"): {"forms_and_instructions"},  # tax_rates
    ("md", "personal exemption"): {"forms_and_instructions"},  # law_changes; Form 515's 'personal services'
    # A clean miss before, now a match on an incidental word (open: the ranker keeps one content word of "use tax").
    ("la", "earned income credit"): {"forms_and_instructions"},  # 'income earned in 2025' (IT-540B who-must-file)
    ("me", "use tax"): {"forms_and_instructions"},  # Schedule NR 'use the same filing status'
    ("mo", "use tax"): {"forms_and_instructions"},  # MO-NRI 'you may use Form MO-NRI or Form MO-CR'
}


@pytest.mark.parametrize(("st", "query"), sorted(MOVED_ROUTES))
def test_get_sources_routes_the_reviewed_moved_questions_as_pinned(st: str, query: str):
    assert _topics(st, query) == MOVED_ROUTES[(st, query)], (st, query)
