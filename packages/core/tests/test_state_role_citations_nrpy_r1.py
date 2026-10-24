"""Part-year and nonresident filers of ten states get their own form's citations (TY2025, Phase K JK28).

The 2025 packs for AL, AR, AZ, CO, CT, DC, DE, HI, IA and ID each name a part-year or nonresident form under
``forms.part_year_or_nonresident`` (AL Form 40NR, AR AR1000NR, AZ Forms 140PY and 140NR, CO DR 0104PN, CT Form
CT-1040NR/PY, DC Forms D-40 and D-40B, DE Form PIT-NON, HI Form N-15, IA Schedule IA 126, ID Forms 43 and 39NR), but
before 2026-10-16 each cited only its resident booklet or return: the defect JK27 fixed for Virginia
(test_va_760py_pointer.py). Each pack now lists under ``forms.citations.part_year`` and ``forms.citations.nonresident``
the 2025 sentence that tells that filer which return to file, quoted with its page, and the return or schedule itself;
state_scope adds a role's list to that role's entry only.

The source registry (knowledge/sources_states.yaml) is generated from the same packs, and it keeps only the first
citation of a URL under each topic, reading ``forms`` before ``all_citations``. A role citation that reuses a URL the
pack already describes would therefore replace that description in the registry, and get_sources would stop routing
to it.
So the first role entry of such a URL repeats the older description (AL's Form 40NR booklet, CO's DR 0104, CT's
CT-1040NR/PY instructions, HI's N-15 instructions), and each document is cited under one URL only.

Every URL and quote below was read from the state revenue department's own 2025 documents, each downloaded twice on
2026-10-16. The digests are in each pack's comment above its ``citations`` block; for DRS's HTML page, whose bytes
differ between fetches, the comment records that the visible text is the same in both.

Since Phase K JK20 (2026-10-24) the registry keeps every description of a (topic, url), the first one leading and
the rest joined after it (test_state_sources_table.py); the paragraph above describes the registry as JK28 found it.
"""
from __future__ import annotations

from datetime import date
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

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

# state -> role -> (the role's own return or schedule, which its list must cite; a sentence its sources must quote)
EXPECTED: dict[str, dict[str, tuple[str, str]]] = {
    "al": {
        "part_year": (
            "https://www.revenue.alabama.gov/wp-content/uploads/2026/01/25f40.pdf",
            "'You MUST Use Both Form 40 and Form 40NR If: You had sufficient income to require the filing of a "
            "part-year return",
        ),
        "nonresident": (
            "https://www.revenue.alabama.gov/wp-content/uploads/2026/01/25f40nr.pdf",
            "'You MUST Use Form 40NR If:' — 'You are not a resident of Alabama",
        ),
    },
    "ar": {
        "part_year": (
            "https://www.dfa.arkansas.gov/wp-content/uploads/2025_AR1000NR_PartYear_or_Non-ResidentIndividualIncomeTaxReturn_1.pdf",
            "'PART YEAR RESIDENTS (Use Form AR1000NR)'",
        ),
        "nonresident": (
            "https://www.dfa.arkansas.gov/wp-content/uploads/2025_AR1000NR_PartYear_or_Non-ResidentIndividualIncomeTaxReturn_1.pdf",
            "'NONRESIDENTS (Use Form AR1000NR)'",
        ),
    },
    "az": {
        "part_year": (
            "https://azdor.gov/sites/default/files/document/FORMS_INDIVIDUAL_2025_140PY_f.pdf",
            "'If you are a part-year resident, you must file Arizona Form 140PY, Part-Year Resident Personal Income Tax "
            "Return.'",
        ),
        "nonresident": (
            "https://azdor.gov/sites/default/files/document/FORMS_INDIVIDUAL_2025_140NR_f.pdf",
            "'If you are a nonresident (including nonresident aliens), you must file Arizona Form 140NR, Nonresident "
            "Personal Income Tax Return.'",
        ),
    },
    "co": {
        "part_year": (
            "https://tax.colorado.gov/sites/tax/files/documents/DR0104PN_2025.pdf",
            "'A part-year Colorado resident who received taxable income while residing here (you must file DR 0104 "
            "with DR 0104PN), or'",
        ),
        "nonresident": (
            "https://tax.colorado.gov/sites/tax/files/documents/DR0104PN_2025.pdf",
            "'Not a Colorado resident, but received income from Colorado sources (you must file DR 0104 with DR "
            "0104PN).'",
        ),
    },
    "ct": {
        "part_year": (
            "https://portal.ct.gov/-/media/drs/forms/2025/income/ct-1040nrpy_1225.pdf",
            "'You were a part-year resident who meets the Gross Income Test or who had a federal alternative minimum "
            "tax liability'",
        ),
        "nonresident": (
            "https://portal.ct.gov/-/media/drs/forms/2025/income/ct-1040nrpy_1225.pdf",
            "'You were a nonresident with Connecticut-sourced income who meets the Gross Income Test or had a federal "
            "alternative minimum tax liability.'",
        ),
    },
    "dc": {
        "part_year": (
            "https://otr.cfo.dc.gov/sites/default/files/dc/sites/otr/publication/attachments/2025_D40_Form_030526.pdf",
            "'You were a part-year resident of DC during 2025 (see instructions for part-year residents, page 18);'",
        ),
        "nonresident": (
            "https://otr.cfo.dc.gov/sites/default/files/dc/sites/otr/publication/attachments/2025_D40B_Form_012026.pdf",
            "'You were not considered a resident of DC during 2025;'",
        ),
    },
    "de": {
        "part_year": (
            "https://revenuefiles.delaware.gov/2025/PITForms_Instructions/PIT-NON_2025-01_PaperInteractiveIPM.pdf",
            "'Part-Year Residents may elect to file either a resident or non- resident return.",
        ),
        "nonresident": (
            "https://revenuefiles.delaware.gov/2025/PITForms_Instructions/PIT-NON_2025-01_PaperInteractiveIPM.pdf",
            "'1. Non-Residents – File a tax return if you have any gross income during the tax year from sources in "
            "Delaware.'",
        ),
    },
    "hi": {
        "part_year": (
            "https://files.hawaii.gov/tax/forms/2025/n15_i.pdf",
            "'A part-year resident must file an Individual Income Tax Return—Nonresident and Part-Year Resident (Form "
            "N-15), if required to do so.'",
        ),
        "nonresident": (
            "https://files.hawaii.gov/tax/forms/2025/n15_i.pdf",
            "'A nonresident must file an Individual Income Tax Return—Nonresident and Part-Year Resident (Form N-15), "
            "if required to do so.'",
        ),
    },
    "ia": {
        "part_year": (
            "https://revenue.iowa.gov/media/4385/download?inline",
            "'... you were a resident or part-year resident of Iowa in 2025 and meet any of the following "
            "requirements.'",
        ),
        "nonresident": (
            "https://revenue.iowa.gov/media/4385/download?inline",
            "'Nonresidents, see items f and g.'",
        ),
    },
    "id": {
        "part_year": (
            "https://tax.idaho.gov/wp-content/uploads/forms/EFO00091/EFO00091_03-02-2026.pdf",
            "'Every part-year resident with a total of more than $2,500 gross income from either or both of these:'",
        ),
        "nonresident": (
            "https://tax.idaho.gov/wp-content/uploads/forms/EFO00091/EFO00091_03-02-2026.pdf",
            "'Every nonresident with more than $2,500 gross income from Idaho sources'",
        ),
    },
}
STATES = tuple(EXPECTED)


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
    return _entry(st, [ResidencePeriod(state=st.upper(), start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)])


def _role_citations(st: str, role: str) -> list[Citation]:
    forms = load_state_knowledge(st, YEAR, KNOWLEDGE).forms or {}
    return [Citation.model_validate(c) for c in (forms.get("citations") or {}).get(role) or []]


def _pairs(cites: list[Citation]) -> set[tuple[str, str]]:
    return {(c.source, c.url) for c in cites}


@pytest.mark.parametrize("st", STATES)
@pytest.mark.parametrize("role", ROLES)
def test_the_2025_pack_cites_the_role_form_and_the_sentence_that_sends_the_filer_there(st: str, role: str):
    cites = _role_citations(st, role)
    assert cites, f"{st}/2025: forms.citations.{role} is missing or empty"
    for c in cites:
        assert validate_gov_url(c.url) == c.url
        assert c.source.strip()
    form_url, quote = EXPECTED[st][role]
    assert form_url in [c.url for c in cites], f"{st}/2025 {role}: the role's own return or schedule is not cited"
    assert any(quote in c.source for c in cites), f"{st}/2025 {role}: the who-files sentence is not quoted"


@pytest.mark.parametrize("st", STATES)
def test_state_scope_gives_a_part_year_filer_the_part_year_citations(st: str):
    entry = _part_year(st)
    assert entry.filing_role == "part_year" and entry.must_file
    got = _pairs(entry.citations)
    part_year, nonresident = _pairs(_role_citations(st, "part_year")), _pairs(_role_citations(st, "nonresident"))
    assert part_year and part_year <= got
    assert not (nonresident - part_year) & got, f"{st}: a part-year filer is handed the nonresident citations"


@pytest.mark.parametrize("st", STATES)
def test_state_scope_gives_a_nonresident_the_nonresident_citations(st: str):
    entry = _nonresident(st)
    assert entry.filing_role == "nonresident"
    got = _pairs(entry.citations)
    part_year, nonresident = _pairs(_role_citations(st, "part_year")), _pairs(_role_citations(st, "nonresident"))
    assert nonresident and nonresident <= got
    assert not (part_year - nonresident) & got, f"{st}: a nonresident is handed the part-year citations"


@pytest.mark.parametrize("st", STATES)
def test_a_full_year_resident_gains_no_role_citation(st: str):
    entry = _resident(st)
    assert entry.filing_role == "resident"
    roles = _pairs(_role_citations(st, "part_year")) | _pairs(_role_citations(st, "nonresident"))
    assert not roles & _pairs(entry.citations)


@pytest.mark.parametrize("st", STATES)
def test_get_sources_routes_a_part_year_question_to_the_role_form_and_leaves_neighbours_alone(st: str):
    # knowledge/sources_states.yaml is generated from each state's newest pack (scripts/assemble_state_sources.py), so
    # the 2025 role citations also reach get_sources, under forms_and_instructions. Before them a part-year question
    # missed five of these states outright and reached none of the ten states' part-year returns. The two neighbour
    # queries route exactly as they did before the role citations were added.
    jurisdiction = f"states/{st}"
    hit = get_sources("part-year resident", YEAR, jurisdiction, base_dir=KNOWLEDGE)
    assert hit.matched and {s.topic for s in hit.sources} == {"forms_and_instructions"}
    assert EXPECTED[st]["part_year"][0] in [s.url for s in hit.sources]
    for query, topics in {"tax rates": {"tax_rates_and_brackets"}, "law changes": {"law_changes"}}.items():
        assert {s.topic for s in get_sources(query, YEAR, jurisdiction, base_dir=KNOWLEDGE).sources} == topics, query


def test_an_alabama_part_year_filer_is_pointed_at_form_40nr_as_well_as_form_40():
    # A part-year resident who also had Alabama-source income while a nonresident files BOTH returns ('You MUST Use Both
    # Form 40 and Form 40NR If: ...', 2025 Form 40 booklet, p. 5; the 40NR booklet prints the same rule on its p. 5), so
    # the part-year list carries the Form 40NR return beside Form 40, while a nonresident is never sent to Form 40.
    part_year = [c.url for c in _part_year("al").citations]
    nonresident = [c.url for c in _nonresident("al").citations]
    form_40 = "https://www.revenue.alabama.gov/wp-content/uploads/2026/01/25f40.pdf"
    form_40nr = "https://www.revenue.alabama.gov/wp-content/uploads/2026/01/25f40nr.pdf"
    assert form_40 in part_year and form_40nr in part_year
    assert form_40nr in nonresident and form_40 not in nonresident


def test_the_alabama_which_form_quotes_are_whole_rules():
    # Each rule is quoted to its end (2025 Form 40 and Form 40NR booklets, 'Which Form To File', p. 5). Form 40A needs a
    # full-year resident; the 'You MUST Use Form 40 If' rule has two bullets joined by 'and'; and the Form 40NR rule
    # ends with the Military Spouses Residency Relief Act case. Cut off earlier, part of a rule reads as a whole rule.
    part_year = " ".join(c.source for c in _role_citations("al", "part_year"))
    nonresident = " ".join(c.source for c in _role_citations("al", "nonresident"))
    assert "'You were a resident of Alabama for the entire year,'" in part_year
    assert "requirements to file Form 40A, and' — 'You are itemizing deductions.'" in part_year
    assert 'under the "Military Spouses Residency Relief Act."\'' in nonresident


@cache
def _raw_pack(st: str) -> dict:
    return yaml.safe_load((KNOWLEDGE / "states" / st / f"{YEAR}.yaml").read_text(encoding="utf-8"))


@cache
def _registry() -> dict:
    return yaml.safe_load((KNOWLEDGE / "sources_states.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("st", STATES)
def test_no_role_citation_drops_an_older_description_from_the_source_registry(st: str):
    # state_sources.state_block keeps the FIRST citation of each (topic, url) and walks `forms` before `all_citations`.
    # Before this check, the role citations of AL's 40NR booklet, CT's CT-1040NR/PY instructions and HI's N-15
    # instructions replaced each document's all_citations description, and 'filing threshold' (AL), 'treaty' (AL) and
    # 'standard deduction' (HI) stopped reaching them. The first role entry of a shared URL carries the older text.
    raw = _raw_pack(st)
    role_ids = {id(c) for lst in ((raw.get("forms") or {}).get("citations") or {}).values() for c in lst}
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
    by_topic = _registry()["states"][st]["by_topic"]
    for topic, url, text in carried:
        assert any(e["url"] == url and text in e["answers"] for e in by_topic[topic]), (st, url)


@pytest.mark.parametrize("st", STATES)
def test_each_pdf_is_cited_under_one_url(st: str):
    # A document cited under two URLs is listed twice by the registry and by get_sources. CO's role citations once used
    # the sites/default/files/ paths, while the rest of the pack (and the DR 0104 form pack) cites sites/tax/files/
    # paths that 301-redirect to the same bytes.
    urls: dict[tuple[str, str], set[str]] = {}
    for _, cite in walk_citations(_raw_pack(st)):
        parts = urlsplit(cite["url"].strip())
        name = parts.path.rsplit("/", 1)[-1]
        if name.lower().endswith(".pdf"):
            urls.setdefault((parts.netloc.lower(), name), set()).add(cite["url"].strip())
    assert not {name: found for name, found in urls.items() if len(found) > 1}


@pytest.mark.parametrize(
    ("st", "query", "topics", "url"),
    [
        ("al", "filing threshold", {"forms_and_instructions"},
         "https://www.revenue.alabama.gov/wp-content/uploads/2026/01/25f40nrbk.pdf"),
        ("al", "treaty", {"forms_and_instructions"},
         "https://www.revenue.alabama.gov/wp-content/uploads/2026/01/25f40nrbk.pdf"),
        ("hi", "standard deduction", {"forms_and_instructions", "tax_rates_and_brackets"},
         "https://files.hawaii.gov/tax/forms/2025/n15ins.pdf"),
        ("ct", "tax tables", {"forms_and_instructions"},
         "https://portal.ct.gov/-/media/drs/forms/2025/income/2025-ct-1040-nrpy-instructions_1225.pdf"),
    ],
)
def test_get_sources_still_routes_to_the_documents_whose_url_a_role_citation_reuses(
    st: str, query: str, topics: set[str], url: str
):
    # The topics each query reached before the role citations were added (TY2025, the same registry block).
    hit = get_sources(query, YEAR, f"states/{st}", base_dir=KNOWLEDGE)
    assert {s.topic for s in hit.sources} == topics
    assert url in [s.url for s in hit.sources if s.topic == "forms_and_instructions"]
