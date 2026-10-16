"""State knowledge-pack tests (dev plan section 6) — all shipped states/*/2023.yaml.

Each pack loads as a StateKnowledge, declares its treaty conformity (the
NRA-critical flag), and cites an official government host. The states that add
back federally treaty-exempt income (CA/CT/MD/MS-style) must surface the
treaty-non-conformity warning to a treaty filer via state_scope.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from taxfill_core.knowledge import StateKnowledge, StateTaxParams, load_state_knowledge
from taxfill_core.schemas.profile import Answer, Identity, Profile, Provenance, ResidencePeriod, StateFootprintYear
from taxfill_core.statescope import state_scope

REPO_ROOT = Path(__file__).resolve().parents[3]

# EVERY shipped state-year enrolls automatically: the generic invariants below run
# per (code, year), so a new knowledge/states/<st>/<year>.yaml is covered the moment
# it lands (no test edit needed). 2023 is the full-cohort baseline used by the
# year-pinned spot tests further down.
STATE_YEAR_PATHS = sorted((REPO_ROOT / "knowledge" / "states").glob("*/[0-9][0-9][0-9][0-9].yaml"))
STATE_YEARS = [(p.parent.name, int(p.stem)) for p in STATE_YEAR_PATHS]
SHIPPED_YEARS = sorted({y for _, y in STATE_YEARS})
STATE_CODES = sorted({c for c, y in STATE_YEARS if y == 2023})
# A year is COMPLETE once every 2023-cohort jurisdiction ships that year (mid-rollout
# years are still checked pack-by-pack, just not for full-cohort coverage).
COMPLETE_YEARS = sorted(
    y for y in SHIPPED_YEARS if {c for c, yy in STATE_YEARS if yy == y} == set(STATE_CODES)
)
# Years that ship SOME packs but not the full cohort. This must be declared, because
# COMPLETE_YEARS alone is self-silencing: an incomplete year is quietly exempted from
# test_tax_block_shipping_matches_the_g4_rollout — the very test that would report it
# incomplete. RI/2025 hid here for weeks that way. Empty means every shipped year is
# complete; a year appearing here without an entry below is a hard failure.
KNOWN_INCOMPLETE_YEARS: dict[int, str] = {}
STATE_YEAR_IDS = [f"{c}-{y}" for c, y in STATE_YEARS]

US = Provenance.user_stated()

# Treaty NON-conformity — these add back / do not pass through federally
# treaty-exempt income, so a treaty filer must be warned (cited per pack).
KNOWN_NONCONFORMING = {"ca", "al", "ar", "ct", "md", "ms", "nd", "nj", "pa"}


def test_state_knowledge_packs_exist():
    # All income-tax jurisdictions: 41 states + DC (the 9 no-tax states need no pack).
    assert len(STATE_CODES) >= 42


@pytest.mark.parametrize("code,year", STATE_YEARS, ids=STATE_YEAR_IDS)
def test_state_pack_loads_and_is_cited(code: str, year: int):
    pack = load_state_knowledge(code, year, base_dir=REPO_ROOT / "knowledge")
    assert pack.tax_year == year
    assert isinstance(pack, StateKnowledge)
    assert pack.jurisdiction == f"states/{code}"
    assert isinstance(pack.conforms_to_federal_treaties, bool)
    assert pack.citation is not None  # cited to an official gov host (validated by the model)


@pytest.mark.parametrize("code,year", STATE_YEARS, ids=STATE_YEAR_IDS)
def test_treaty_conformity_drives_the_nra_warning(code: str, year: int):
    pack = load_state_knowledge(code, year, base_dir=REPO_ROOT / "knowledge")
    profile = Profile(
        identity=Identity(us_person=Answer(value=False, provenance=US)),  # treaty filer
        state_footprint={year: StateFootprintYear(
            lived=[ResidencePeriod(state=code.upper(), start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)]
        )},
    )
    filing = next(s for s in state_scope(profile, year, base_dir=REPO_ROOT / "knowledge").states if s.state == code.upper())
    # A treaty filer ALWAYS gets an explicit conformity line — negative warning for
    # non-conforming states, positive confirmation for conforming ones (never silent).
    #
    # Keyed on the "Treaty conformity —" PREFIX, not on grepping every warning for
    # "does not conform": conformity is not one question, and once law-change
    # warnings joined this list a state could legitimately say it "does not conform
    # to the federal standard deduction" while conforming on TREATIES (North
    # Carolina 2025 does exactly that). The prefix is the structured signal.
    treaty_lines = [w for w in filing.warnings if w.startswith("Treaty conformity —")]
    assert len(treaty_lines) == 1, (
        f"{code}: expected exactly one prefixed treaty-conformity line, got {treaty_lines}"
    )
    line = treaty_lines[0]
    if pack.conforms_to_federal_treaties:
        assert "conforms to federal treaty treatment" in line and "does NOT conform" not in line, (
            f"{code}: conforming state must carry the positive conformity line: {line}"
        )
    else:
        assert "does NOT conform to federal tax treaties" in line, f"{code}: non-conforming state must warn"


@pytest.mark.parametrize("code,year", STATE_YEARS, ids=STATE_YEAR_IDS)
def test_state_pack_has_cited_credits(code: str, year: int):
    # Every income-tax pack now ships a credits block; each credit cites a gov host
    # and the pack carries the verification caveat.
    from urllib.parse import urlparse

    from taxfill_core.knowledge import is_official_gov_host

    pack = load_state_knowledge(code, year, base_dir=REPO_ROOT / "knowledge")
    credits = getattr(pack, "credits", None) or []
    assert credits, f"{code}: no credits block"
    assert getattr(pack, "credits_verification", None), f"{code}: missing credits_verification caveat"
    for c in credits:
        url = c["citation"]["url"]
        host = (urlparse(url).hostname or "").lower()
        assert is_official_gov_host(host), f"{code}: {c['name']} cites non-gov {url}"
        assert c.get("type") in ("refundable", "nonrefundable"), f"{code}: {c['name']} bad type"


def _iter_citation_shaped(node, path: str = "$", parent_key: str | None = None):
    """Yield (path, mapping) for every mapping a consumer may turn into a Citation.

    That is: any mapping under a ``citation`` key, any element of ``all_citations``, and any
    other mapping that carries both ``source`` and ``url``.
    """
    if isinstance(node, dict):
        if parent_key in ("citation", "all_citations") or {"source", "url"} <= set(node):
            yield path, node
        for key, value in node.items():
            yield from _iter_citation_shaped(value, f"{path}.{key}", key)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_citation_shaped(item, f"{path}[{i}]", parent_key)


@pytest.mark.parametrize("code,year", STATE_YEARS, ids=STATE_YEAR_IDS)
def test_every_citation_shaped_mapping_validates_as_a_citation(code: str, year: int):
    # Not just credits[].citation: EVERY citation-shaped block (deadlines, all_citations,
    # residency, mailing, ...). StateKnowledge uses extra='allow', so these untyped blocks are
    # never validated at load, yet file_and_pay and filing_summary build Citation(**block) from
    # mailing_addresses and deadlines at call time. JK27 (2026-10-16): this test used to check
    # the url HOST only, and allow-listed New Mexico's AWS document-API host — a host the
    # Citation model rejects. So nm/2025.yaml's mailing_addresses and deadlines citations passed
    # here while filing_summary and file_and_pay raised a ValidationError on every NM 2025 return.
    # Now each mapping must validate as the Citation model itself (government host, http(s),
    # exactly source + url), with no allow-list. Service URLs (payment.web_pay_url, ...) are not
    # citations and are not walked.
    import yaml
    from pydantic import ValidationError

    from taxfill_core.knowledge import Citation

    raw = yaml.safe_load((REPO_ROOT / "knowledge" / "states" / code / f"{year}.yaml").read_text(encoding="utf-8"))
    found, rejected = 0, []
    for path, mapping in _iter_citation_shaped(raw):
        found += 1
        try:
            Citation.model_validate(mapping)
        except ValidationError as exc:
            rejected.append(f"{path} ({mapping.get('url')!r}): {exc.errors()[0]['msg']}")
    assert found, f"{code} {year}: no citation-shaped mapping found — the walker no longer matches the pack shape"
    assert not rejected, (
        f"{code} {year}: citation-shaped mappings the Citation model rejects (cite an official government "
        f"page or PDF instead):\n" + "\n".join(rejected)
    )


@pytest.mark.parametrize("code,year", STATE_YEARS, ids=STATE_YEAR_IDS)
def test_file_and_pay_and_filing_summary_run_on_every_state_pack(code: str, year: int):
    # JK27 (2026-10-16): filing_summary and file_and_pay raised a pydantic ValidationError for
    # every New Mexico 2025 return: nm/2025.yaml cited its mailing addresses and deadlines to the
    # Department's AWS document-API host, and both tools build a Citation from those blocks at
    # call time (the JK21 golden nm_2025.json recorded the error). Every shipped pack must survive
    # both tools, for a refund and for an unpaid balance due (the two pick different addresses).
    from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay
    from taxfill_core.filing_summary import filing_summary
    from taxfill_core.knowledge import Citation

    kb = REPO_ROOT / "knowledge"
    pack = load_state_knowledge(code, year, base_dir=kb)
    form = (getattr(pack, "forms", None) or {}).get("resident") or "state return"
    manifest = [
        FilingManifestItem(form=form, tax_year=year, jurisdiction=f"states/{code}", bottom_line=512),
        FilingManifestItem(form=form, tax_year=year, jurisdiction=f"states/{code}", bottom_line=-347),
    ]
    returns = file_and_pay(manifest, knowledge_dir=kb).returns
    items = filing_summary(manifest, today=date(year + 1, 3, 1), knowledge_dir=kb).items
    assert [r.bottom_line for r in returns] == ["Refund of $512", "You owe $347."]
    assert [(i.refund, i.owed) for i in items] == [(512, 0), (0, 347)]

    mailing = getattr(pack, "mailing_addresses", None) or {}
    deadlines = getattr(pack, "deadlines", None) or {}
    assert returns[0].mailing_address == mailing.get("refund_or_no_payment")
    assert returns[1].mailing_address == mailing.get("with_payment")
    for block in (mailing, deadlines):
        if block.get("citation"):
            assert all(Citation(**block["citation"]) in r.citations for r in returns), f"{code} {year}"
    if deadlines.get("filing_due_date"):
        due = f"Due {deadlines['filing_due_date']}."
        assert all(due in r.deadlines for r in returns), f"{code} {year}"
        assert all(i.deadline_status == due for i in items), f"{code} {year}"
        if deadlines.get("citation"):
            assert all(Citation(**deadlines["citation"]) in i.citations for i in items), f"{code} {year}"


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_known_nonconforming_states_are_flagged(year: int):
    kb = REPO_ROOT / "knowledge"
    codes = {c for c, y in STATE_YEARS if y == year}
    flagged = {c for c in codes if not load_state_knowledge(c, year, base_dir=kb).conforms_to_federal_treaties}
    # Every confirmed add-back state shipped for this year must be flagged non-conforming
    # (treaty conformity is structural — it must never silently flip between years).
    assert (KNOWN_NONCONFORMING & codes) <= flagged


# ── Phase G item G4: the tax blocks, per year ──

# Verified flat rates per (year, state). Rates move almost every year — several
# states legislate scheduled cuts (IN 3.15 -> 3.05 -> 3.00; MI's 4.05 was a
# one-year dip back to 4.25; NC 4.75 -> 4.5 -> 4.25; KY 4.5 -> 4.0; CO's TABOR
# adjustment; GA/IA/LA newly flat) — so this table is the drift alarm: a pack
# whose rate changes silently fails here. Anything NOT listed for a year must be
# a graduated block.
FLAT_TAX_RATES_BY_YEAR: dict[int, dict[str, Decimal]] = {
    2023: {
        "az": Decimal("0.025"), "co": Decimal("0.044"), "il": Decimal("0.0495"),
        "in": Decimal("0.0315"), "ky": Decimal("0.045"), "ma": Decimal("0.05"),
        "mi": Decimal("0.0405"), "nc": Decimal("0.0475"), "pa": Decimal("0.0307"),
        "ut": Decimal("0.0465"),
    },
    2024: {
        "az": Decimal("0.025"), "co": Decimal("0.0425"), "ga": Decimal("0.0539"),
        "il": Decimal("0.0495"), "in": Decimal("0.0305"), "ky": Decimal("0.04"),
        "ma": Decimal("0.05"), "mi": Decimal("0.0425"), "nc": Decimal("0.045"),
        "pa": Decimal("0.0307"), "ut": Decimal("0.0455"),
    },
    2025: {
        "az": Decimal("0.025"), "co": Decimal("0.044"), "ga": Decimal("0.0519"),
        "ia": Decimal("0.038"), "il": Decimal("0.0495"), "in": Decimal("0.03"),
        "ky": Decimal("0.04"), "la": Decimal("0.03"), "ma": Decimal("0.05"),
        "mi": Decimal("0.0425"), "nc": Decimal("0.0425"), "pa": Decimal("0.0307"),
        "ut": Decimal("0.045"),
    },
}


@pytest.mark.parametrize("code,year", STATE_YEARS, ids=STATE_YEAR_IDS)
def test_every_shipped_state_year_ships_a_typed_gov_cited_tax_block(code: str, year: int):
    # The one invariant every state-year must satisfy: a typed, gov-cited tax block
    # whose SHAPE and (for flat states) exact rate match the verified year table.
    from urllib.parse import urlparse

    from taxfill_core.knowledge import is_official_gov_host

    tax = load_state_knowledge(code, year, base_dir=REPO_ROOT / "knowledge").tax
    assert isinstance(tax, StateTaxParams), f"{code} {year}: tax block missing or untyped"
    expected_flat = FLAT_TAX_RATES_BY_YEAR.get(year, {}).get(code)
    if expected_flat is not None:
        assert tax.flat_rate == expected_flat, (
            f"{code} {year}: flat rate drifted from the verified table — re-verify against "
            f"the year's official instructions before changing FLAT_TAX_RATES_BY_YEAR"
        )
    else:
        assert tax.flat_rate is None and tax.brackets is not None, (
            f"{code} {year}: unexpected flat rate — add it to FLAT_TAX_RATES_BY_YEAR "
            f"with a citation, or ship the graduated schedules"
        )
        for status in ("single", "married_filing_jointly", "married_filing_separately", "head_of_household"):
            assert tax.brackets[status], f"{code} {year}: missing {status} schedule"
    assert is_official_gov_host((urlparse(tax.citation.url).hostname or "").lower())
    assert tax.tax_line.strip() and tax.notes
    for key, ex in tax.exemptions.items():
        assert ex.amount >= 0 and ex.note.strip(), f"{code} {year}: exemption {key} incomplete"


@pytest.mark.parametrize("year", sorted(FLAT_TAX_RATES_BY_YEAR))
def test_flat_rate_table_has_no_stale_entries(year: int):
    # The table may not name a state-year that isn't shipped (catches typos and
    # entries left behind when a pack is renamed or a year is rolled back).
    shipped = {c for c, y in STATE_YEARS if y == year}
    assert set(FLAT_TAX_RATES_BY_YEAR[year]) <= shipped, (
        f"{year}: FLAT_TAX_RATES_BY_YEAR names unshipped states "
        f"{sorted(set(FLAT_TAX_RATES_BY_YEAR[year]) - shipped)}"
    )


# The 2023 baseline, kept as its own name for the year-pinned spot tests below.
FLAT_TAX_RATES = {
    "il": Decimal("0.0495"),
    "pa": Decimal("0.0307"),
    "in": Decimal("0.0315"),
    "mi": Decimal("0.0405"),
    "nc": Decimal("0.0475"),
    "co": Decimal("0.044"),
    "ky": Decimal("0.045"),
    "az": Decimal("0.025"),
    # Formerly-C3 flat states, adopted + verified 2026-08-01:
    "ut": Decimal("0.0465"),  # TC-40 line 10 (4.55% for 2024)
    "ma": Decimal("0.05"),    # Form 1 line 21 5% Part B (4% surtax >$1M is a notes-disclosed add-on)
}


@pytest.mark.parametrize("code", sorted(FLAT_TAX_RATES), ids=lambda c: c)
def test_flat_state_tax_block_loads_typed_and_gov_cited(code: str):
    # Every shipped flat-state yaml block loads through the TYPED model with a
    # gov-cited URL (the Citation model runs validate_gov_url) and the exact rate.
    from urllib.parse import urlparse

    from taxfill_core.knowledge import is_official_gov_host

    pack = load_state_knowledge(code, 2023, base_dir=REPO_ROOT / "knowledge")
    assert isinstance(pack.tax, StateTaxParams), f"{code}: tax block missing or untyped"
    assert pack.tax.flat_rate == FLAT_TAX_RATES[code]
    assert is_official_gov_host((urlparse(pack.tax.citation.url).hostname or "").lower())
    assert pack.tax.tax_line.strip()
    for key, ex in pack.tax.exemptions.items():
        assert ex.amount >= 0 and ex.note.strip(), f"{code}: exemption {key} incomplete"


def test_flat_state_tax_bases_match_the_research():
    kb = REPO_ROOT / "knowledge"
    bases = {c: load_state_knowledge(c, 2023, base_dir=kb).tax.base for c in FLAT_TAX_RATES}
    assert bases["pa"] == "state_gross_income"     # eight separately-computed classes
    assert bases["co"] == "federal_taxable_income"  # DR 0104 line 1
    for code in ("il", "in", "mi", "nc", "ky", "az"):
        assert bases[code] == "federal_agi", code


def test_az_exemptions_are_the_verifier_corrected_form_140_lines_38_41():
    # The verifier's correction over the researcher: AZ DOES have exemptions —
    # Form 140 lines 38-41, subtracted before Arizona taxable income. Only the
    # plain dependent exemption was replaced by the Line 49 credit, so there is
    # NO 'personal' or 'dependent' key.
    tax = load_state_knowledge("az", 2023, base_dir=REPO_ROOT / "knowledge").tax
    amounts = {k: v.amount for k, v in tax.exemptions.items()}
    assert amounts == {
        "age_65": 2100,
        "blind": 1500,
        "other": 2300,
        "qualifying_parent_grandparent": 10000,
    }
    assert tax.exemptions["age_65"].note.startswith("Form 140 Line 38")
    assert "mutually exclusive" in tax.exemptions["qualifying_parent_grandparent"].note
    assert tax.standard_deduction == {
        "single": 13850,
        "married_filing_jointly": 27700,
        "married_filing_separately": 13850,
        "head_of_household": 20800,
    }
    assert any("Line 49" in n and "CREDIT" in n for n in tax.notes)


def test_nc_and_ky_standard_deductions_match_the_charts():
    kb = REPO_ROOT / "knowledge"
    nc = load_state_knowledge("nc", 2023, base_dir=kb).tax
    assert nc.standard_deduction == {
        "single": 12750,
        "married_filing_jointly": 25500,
        "married_filing_separately": 12750,
        "head_of_household": 19125,
    }
    ky = load_state_knowledge("ky", 2023, base_dir=kb).tax
    # ONE $2,980 per return — the same figure in every column, never doubled for MFJ.
    assert set(ky.standard_deduction.values()) == {2980}


def test_il_omits_the_unverified_dependent_amount():
    # The Schedule IL-E/EIC per-dependent multiplication was not independently
    # verified, so IL ships personal/age_65/blind but NO 'dependent' key, and the
    # omission is disclosed in the notes.
    tax = load_state_knowledge("il", 2023, base_dir=REPO_ROOT / "knowledge").tax
    assert tax.exemptions["personal"].amount == 2425
    assert tax.exemptions["age_65"].amount == 1000
    assert tax.exemptions["blind"].amount == 1000
    assert "dependent" not in tax.exemptions
    assert any("Schedule IL-E/EIC" in n and "NOT shipped" in n for n in tax.notes)


# G4 second tranche (two-pass verified 2026-07-24): the 27 graduated-bracket
# 2023 packs. Together with the flat eight, every adopted state ships a block.
GRADUATED_TAX_STATES = sorted([
    "al", "ar", "ca", "dc", "de", "ga", "id", "ks", "la", "md", "me", "mn", "mo",
    "ms", "mt", "nd", "ne", "nj", "ny", "oh", "ok", "or", "ri", "va", "vt", "wi", "wv",
    # Formerly-C3 graduated states, adopted + verified 2026-08-01:
    "ct", "sc", "nm", "hi", "ia",
])

# Rollout complete (2026-08-01): every jurisdiction ships a verified tax block.
NO_TAX_BLOCK_YET: set[str] = set()


@pytest.mark.parametrize("year", COMPLETE_YEARS)
def test_tax_block_shipping_matches_the_g4_rollout(year: int):
    # For every COMPLETE year, all 42 adopted jurisdictions ship a cited tax block
    # (the former C3 seven — ct/hi/ia/ma/nm/sc/ut — joined 2026-08-01 once their
    # form packs were adopted and the data passed two-pass verification), and the
    # flat/graduated split partitions the cohort exactly.
    kb = REPO_ROOT / "knowledge"
    flat, graduated = set(), set()
    for code in STATE_CODES:
        tax = load_state_knowledge(code, year, base_dir=kb).tax
        assert tax is not None, f"{code} {year}: adopted state must ship the tax block"
        (flat if tax.flat_rate is not None else graduated).add(code)
    assert flat | graduated == set(STATE_CODES)
    assert flat == set(FLAT_TAX_RATES_BY_YEAR[year]), (
        f"{year}: flat-state cohort disagrees with FLAT_TAX_RATES_BY_YEAR"
    )
    if year == 2023:  # the documented baseline split
        assert graduated == set(GRADUATED_TAX_STATES)


def test_every_shipped_year_is_a_complete_cohort():
    # The guard on the guard. test_tax_block_shipping_matches_the_g4_rollout only runs
    # for COMPLETE_YEARS, so a year missing a jurisdiction exempts ITSELF from the only
    # test that checks full-cohort coverage. RI/2025 sat in that blind spot: 41 of 42
    # packs shipped, 2025 dropped out of COMPLETE_YEARS, and nothing went red.
    #
    # So assert the exemption list is empty. A deliberate mid-rollout year is allowed,
    # but it has to be WRITTEN DOWN in KNOWN_INCOMPLETE_YEARS with a reason — the point
    # is that an incomplete cohort can never again be silent.
    incomplete = {y: sorted(set(STATE_CODES) - {c for c, yy in STATE_YEARS if yy == y}) for y in SHIPPED_YEARS}
    incomplete = {y: missing for y, missing in incomplete.items() if missing}
    undeclared = {y: missing for y, missing in incomplete.items() if y not in KNOWN_INCOMPLETE_YEARS}
    assert not undeclared, (
        f"state-year cohort holes that no test would otherwise report: {undeclared}. "
        f"Ship the missing pack(s), or declare the year in KNOWN_INCOMPLETE_YEARS with a reason."
    )
    stale = sorted(set(KNOWN_INCOMPLETE_YEARS) - set(incomplete))
    assert not stale, f"KNOWN_INCOMPLETE_YEARS lists {stale}, which are now complete — drop the entries"


@pytest.mark.parametrize("code", GRADUATED_TAX_STATES, ids=lambda c: c)
def test_graduated_state_tax_block_loads_typed_and_gov_cited(code: str):
    # Every graduated block loads through the TYPED model: gov-cited, bracket
    # schedules for all four statuses (contiguity/zero-floor rules are enforced
    # by the schema itself), and disclosure notes present.
    from urllib.parse import urlparse

    from taxfill_core.knowledge import is_official_gov_host

    pack = load_state_knowledge(code, 2023, base_dir=REPO_ROOT / "knowledge")
    tax = pack.tax
    assert isinstance(tax, StateTaxParams), f"{code}: tax block missing or untyped"
    assert tax.flat_rate is None and tax.brackets is not None, f"{code}: expected a graduated block"
    for status in ("single", "married_filing_jointly", "married_filing_separately", "head_of_household"):
        assert tax.brackets[status], f"{code}: missing {status} schedule"
    assert is_official_gov_host((urlparse(tax.citation.url).hostname or "").lower())
    assert tax.tax_line.strip()
    assert tax.notes, f"{code}: a graduated pack must carry its disclosure notes"
    for key, ex in tax.exemptions.items():
        assert ex.amount >= 0 and ex.note.strip(), f"{code}: exemption {key} incomplete"


def test_graduated_state_verified_spot_data():
    # A handful of two-pass-verified anchor figures, one per modeling pattern.
    kb = REPO_ROOT / "knowledge"
    ca = load_state_knowledge("ca", 2023, base_dir=kb).tax
    # CA: exemptions are CREDITS ($144/$446) — never shipped as base reductions;
    # the MFS schedule is the single schedule; the top marginal rate is 12.3%.
    assert ca.exemptions == {}
    assert ca.brackets["married_filing_separately"] == ca.brackets["single"]
    assert ca.brackets["single"][-1].rate == Decimal("0.123")
    oh = load_state_knowledge("oh", 2023, base_dir=kb).tax
    # OH: zero-rate floor to $26,050 and the CRITICAL $360.69 schedule-jump note.
    assert oh.brackets["single"][0].rate == 0 and oh.brackets["single"][0].but_not_over == 26_050
    assert any("360.69" in n for n in oh.notes)
    ms = load_state_knowledge("ms", 2023, base_dir=kb).tax
    # MS: zero floor to $10,000; the per-status personal exemption is FOLDED
    # into the shipped standard_deduction ($2,300 + $6,000 single).
    assert ms.brackets["single"][0].but_not_over == 10_000
    assert ms.standard_deduction["single"] == 8_300
    wi = load_state_knowledge("wi", 2023, base_dir=kb).tax
    # WI: sliding standard deduction -> the caller supplies the form's own
    # taxable-income line and no standard_deduction ships.
    assert wi.base == "state_taxable_income" and wi.standard_deduction is None
    wv = load_state_knowledge("wv", 2023, base_dir=kb).tax
    # WV: NO standard deduction (null, never zeros); $2,000 per exemption.
    assert wv.standard_deduction is None
    assert wv.exemptions["personal"].amount == 2_000 and wv.exemptions["dependent"].amount == 2_000
    ks = load_state_knowledge("ks", 2023, base_dir=kb).tax
    # KS: qualifying surviving spouse maps to HEAD OF HOUSEHOLD in Kansas —
    # the pack warns against the engine's QSS->MFJ default.
    assert any("HEAD OF HOUSEHOLD" in n for n in ks.notes)


# ── TY2025 pins (Phase K JK21) ──
# The three TY2023 caveat pins above (OH's $360.69 jump, AZ's Line 49, IL's IL-E/EIC) have TY2025
# twins that JK26's notes triage must keep. These pin what calc.state_tax and state_scope EMIT,
# not only what the pack holds, so a migration that keeps the YAML text but drops it from the
# output still fails here.


def test_oh_2025_discontinuity_is_surfaced_by_state_tax():
    # knowledge/states/oh/2025.yaml:292-304 (the "CRITICAL — printed-constant divergence" note):
    # the middle row prints "$342.00 plus 2.750%" over a $0.00 cumulative floor, and the top row's
    # $2,394.32 was left unchanged, so the printed schedule runs $342.00 ahead of bracket math between
    # $26,050 and $100,000 and $360.695 ahead above $100,000.
    from taxfill_core.calc import state_tax

    kb = REPO_ROOT / "knowledge"
    middle = state_tax("oh", 68_050, year=2025, knowledge_dir=kb)
    # The booklet's own example: $42,000 x 0.0275 = $1,155 by bracket math; the form says $1,497.
    assert middle.tax == 1_155 and middle.marginal_rate == Decimal("0.0275")
    assert "'$1,155 + $342 = $1,497'" in middle.work
    assert "the jump is NOT 2024's $360.69" in middle.work
    assert (
        "add $342.00 to this op's result when line 7 is between $26,050 and $100,000, "
        "and $360.695 when line 7 exceeds $100,000." in middle.work
    )
    assert "R.C. 5747.02(A)(3)(b) prints the same $342.00 and $2,394.32 pair" in middle.work
    top = state_tax("oh", 110_000, year=2025, knowledge_dir=kb)
    # $0 + 2.75% x $73,950 = $2,033.625, + 3.125% x $10,000 = $2,346.125 -> $2,346; the printed
    # schedule gives $2,394.32 + $312.50 = $2,706.82, i.e. $360.695 more.
    assert top.tax == 2_346 and top.marginal_rate == Decimal("0.03125")
    assert "the printed top row starts at $2,394.32" in top.work


def test_az_2025_line_49_dependent_credit_is_disclosed_not_applied():
    # knowledge/states/az/2025.yaml:267-270: no personal exemption; the dependent exemption became the
    # Line 49 Dependent Tax CREDIT, which calc.state_tax does not model.
    from taxfill_core.calc import state_tax

    kb = REPO_ROOT / "knowledge"
    r = state_tax("az", 50_000, year=2025, knowledge_dir=kb)
    # ($50,000 - the $15,750 single standard deduction) x 2.5% = $856.25 -> $856.
    assert r.tax == 856 and r.base_after_exemptions == 34_250
    assert (
        "the plain dependent exemption was replaced by the Line 49 Dependent Tax Credit ($100 per qualifying "
        "dependent under 17, $25 per dependent 17 or over" in r.work
    )
    assert "It is a CREDIT against tax, not a base reduction, and is NOT modeled by calc.state_tax." in r.work
    # A dependents count is refused, never silently applied as a base exemption.
    with pytest.raises(ValueError, match="AZ's Line 49 dependent CREDIT"):
        state_tax("az", 50_000, year=2025, dependents_count=1, knowledge_dir=kb)


def test_il_2025_schedule_il_e_eitc_caveats_reach_the_output():
    # knowledge/states/il/2025.yaml:242-245 + :255-257: for 2025 the per-dependent $2,850 IS verified on
    # Schedule IL-E/EITC Step 2 Line 1, so it ships and is applied (the TY2023 pin above checks the
    # opposite, NOT-shipped caveat). :58-78 (the Illinois EITC, Schedule IL-E/EITC Step 4) and :271-293
    # (the unmodeled Child Tax Credit increase to 40% of the Illinois EITC, Step 5) reach state_scope.
    from taxfill_core.calc import state_tax

    kb = REPO_ROOT / "knowledge"
    r = state_tax("il", 60_000, year=2025, exemptions_count=1, dependents_count=1, knowledge_dir=kb)
    # ($60,000 - $2,850 - $2,850) x 4.95% = $2,687.85 -> $2,688.
    assert r.tax == 2_688 and r.base_after_exemptions == 54_300
    assert "1 dependent exemption(s) x $2,850 = $2,850.00" in r.work
    assert (
        "Dependent exemptions (Line 10d) ship for 2025 at $2,850 each: the 2025 Schedule IL-E/EITC form prints "
        "the per-dependent multiplication (Step 2 Line 1, $2,850 per dependent)" in r.work
    )
    il = state_scope(
        Profile(state_footprint={2025: StateFootprintYear(
            lived=[ResidencePeriod(state="IL", start=date(2025, 1, 1), end=date(2025, 12, 31), provenance=US)],
        )}),
        2025,
        base_dir=REPO_ROOT / "knowledge",
    ).states[0]
    assert il.state == "IL" and il.filing_role == "resident"
    assert any(
        b.startswith("Illinois Earned Income Tax Credit (EITC) — In general, anyone who qualified for the federal EITC")
        for b in il.benefits_candidates
    )
    child_credit = [w for w in il.warnings if "Illinois Child Tax Credit INCREASED to 40% of the Illinois Earned" in w]
    assert len(child_credit) == 1
    assert child_credit[0].startswith("Law change NOT modeled by the engine (status final_form_published):")
    assert "Resolve via: 2025 Schedule IL-E/EITC Step 5 (Lines 11-12)" in child_credit[0]


# ── IA 1040 face locations (JK27, 2026-10-16) ──
# Every IA 1040 since the 2023 redesign prints the school district / EMS surtax as line 19, inside Step 5: "19. School
# district surtax or EMS surtax. Multiply line 18 by the percentage from table." (2023; "from list" in 2024 and 2025).
# Step 6 is "Refundable Credits and Payments", lines 23-30. The 2024 and 2025 faces print the alternate tax / tax
# reduction / low-income exemption box on its own row under the Step 5 heading, above line 5 (page 2, 41-001b), and
# the 2024 Schedule 1 prints line 17, the Iowa NOL, as one box. The instructions of both years still say "check the
# box between Steps 4 and 5" (2024 p.44; the 2025 "Line 25" page), and the 2024 p.10 add-back list still says
# "Schedule 1, line 17b": the packs keep that wording as quotes and state what the face prints.


def _ia_pack_strings(year: int) -> list[str]:
    """Every string value in the IA pack for ``year``: credits, notes, unverified, citations."""
    pack = load_state_knowledge("ia", year, base_dir=REPO_ROOT / "knowledge")
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            found.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(pack.model_dump(mode="json"))
    return found


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_ia_surtax_is_line_19_in_step_5(year: int):
    from taxfill_core.calc import state_tax

    work = state_tax("ia", 40_000, year=year, knowledge_dir=REPO_ROOT / "knowledge").work
    assert (
        'SCHOOL DISTRICT SURTAX and EMS surtax (line 19, in Step 5: "School district surtax or EMS surtax. '
        "Multiply line 18 by the percentage from"
    ) in work
    assert 'Step 6 is "Refundable Credits and Payments", lines 23-30)' in work
    # Nothing in the pack (notes, unverified) places the surtax in Step 6 any more.
    assert not [s for s in _ia_pack_strings(year) if "surtax" in s and "(Step 6" in s]


@pytest.mark.parametrize("year", [2024, 2025])
def test_ia_low_income_box_is_placed_under_the_step_5_heading(year: int):
    from taxfill_core.calc import state_tax

    work = state_tax("ia", 40_000, year=year, knowledge_dir=REPO_ROOT / "knowledge").work
    assert f"(check the box the {year} IA 1040 prints under the Step 5 heading, above line 5:" in work
    pack = load_state_knowledge("ia", year, base_dir=REPO_ROOT / "knowledge")
    (low,) = [c for c in pack.credits if c["name"].startswith("Low-Income Exemption")]
    assert low["claimed_on"].startswith(
        "IA 1040 Step 5 — check the box printed under the Step 5 heading, above line 5"
    )
    # "between Steps 4 and 5" is the instructions' wording; it survives only inside a quote of them.
    strings = _ia_pack_strings(year)
    said = sum(s.count("between Steps 4 and 5") for s in strings)
    quoted = sum(
        s.count('"the box between Steps 4 and 5"') + s.count('"check the box between Steps 4 and 5"') for s in strings
    )
    assert said and said == quoted


def test_ia_2023_low_income_box_is_placed_on_the_step_5_heading_row():
    # The 2023 face prints the box on the Step 5 heading row, after line 4 (the 2024 and 2025 faces moved it under the
    # heading); "between Steps 4 and 5" is the 2023 instructions' wording, p.49, and survives only as their quote.
    from taxfill_core.calc import state_tax

    pack = load_state_knowledge("ia", 2023, base_dir=REPO_ROOT / "knowledge")
    (low,) = [c for c in pack.credits if c["name"].startswith("Low-Income Exemption")]
    assert low["claimed_on"].startswith("IA 1040 Step 5 — check the box the 2023 IA 1040 prints on the Step 5 heading row")
    work = state_tax("ia", 40_000, year=2023, knowledge_dir=REPO_ROOT / "knowledge").work
    assert '(check the Step 5 box "Check if using alternate tax (line 5)' in work
    strings = _ia_pack_strings(2023)
    said = sum(s.count("between Steps 4 and 5") for s in strings)
    quoted = sum(s.count('"check the box between Steps 4 and 5"') for s in strings)
    assert said and said == quoted


def test_ia_2024_nol_add_back_is_the_one_box_schedule_1_line_17():
    ia = state_scope(
        Profile(state_footprint={2024: StateFootprintYear(
            lived=[ResidencePeriod(state="IA", start=date(2024, 1, 1), end=date(2024, 12, 31), provenance=US)],
        )}),
        2024,
        base_dir=REPO_ROOT / "knowledge",
    ).states[0]
    assert ia.state == "IA" and ia.filing_role == "resident"
    (low,) = [b for b in ia.benefits_candidates if b.startswith("Low-Income Exemption")]
    assert "lump-sum distributions, and the Schedule 1 line 17 NOL carryover)" in low
    assert (
        'The 2024 IA 1040 Schedule 1 prints line 17 as one box, "Iowa net operating loss prior to 1/1/23. '
        'Include IA 124"'
    ) in low
    # "line 17b" is the p.10 add-back list's wording and appears only inside that quote.
    assert sum(s.count("17b") for s in _ia_pack_strings(2024)) == 1
    assert 'claimed on the IA 1040 Schedule 1, line 17b"' in low


# ── G4 second tranche: the graduated-bracket StateTaxParams schema ──

_ZZ_CITE = {"source": "synthetic", "url": "https://www.irs.gov/"}
_ZZ_SCHEDULE = [
    {"over": 0, "but_not_over": 10_000, "rate": "0.02"},
    {"over": 10_000, "but_not_over": None, "rate": "0.04"},
]


def _graduated_params(**overrides):
    payload = {
        "citation": _ZZ_CITE,
        "base": "state_taxable_income",
        "tax_line": "ZZ-1 Line 9 (synthetic)",
        "brackets": {
            "single": _ZZ_SCHEDULE,
            "married_filing_jointly": _ZZ_SCHEDULE,
            "married_filing_separately": _ZZ_SCHEDULE,
            "head_of_household": _ZZ_SCHEDULE,
        },
    }
    payload.update(overrides)
    return payload


def test_state_tax_params_requires_exactly_one_of_flat_or_brackets():
    with pytest.raises(ValueError, match="exactly ONE"):
        StateTaxParams.model_validate(_graduated_params(flat_rate="0.05"))
    with pytest.raises(ValueError, match="exactly ONE"):
        StateTaxParams.model_validate(_graduated_params(brackets=None))
    # Each alone is fine.
    assert StateTaxParams.model_validate(_graduated_params()).flat_rate is None
    flat = StateTaxParams.model_validate(_graduated_params(brackets=None, flat_rate="0.05"))
    assert flat.brackets is None and flat.flat_rate == Decimal("0.05")


def test_state_tax_params_bracket_integrity():
    # All four statuses required.
    with pytest.raises(ValueError, match="all four filing statuses"):
        StateTaxParams.model_validate(_graduated_params(brackets={"single": _ZZ_SCHEDULE}))
    # Contiguity: a gap between brackets is refused.
    gapped = [
        {"over": 0, "but_not_over": 10_000, "rate": "0.02"},
        {"over": 12_000, "but_not_over": None, "rate": "0.04"},
    ]
    with pytest.raises(ValueError, match="contiguous"):
        StateTaxParams.model_validate(
            _graduated_params(brackets={s: gapped for s in (
                "single", "married_filing_jointly", "married_filing_separately", "head_of_household")})
        )
    # Top bracket must be unbounded; bottom must start at 0.
    bounded_top = [{"over": 0, "but_not_over": 10_000, "rate": "0.02"}]
    with pytest.raises(ValueError, match="but_not_over: null"):
        StateTaxParams.model_validate(
            _graduated_params(brackets={s: bounded_top for s in (
                "single", "married_filing_jointly", "married_filing_separately", "head_of_household")})
        )
    floating = [{"over": 5_000, "but_not_over": None, "rate": "0.02"}]
    with pytest.raises(ValueError, match="over=0"):
        StateTaxParams.model_validate(
            _graduated_params(brackets={s: floating for s in (
                "single", "married_filing_jointly", "married_filing_separately", "head_of_household")})
        )


def test_state_tax_params_zero_rate_floor_allowed_but_not_all_zero():
    # A 0% bottom bracket is legal (Ohio/Mississippi shape) ...
    floor = [
        {"over": 0, "but_not_over": 26_050, "rate": "0"},
        {"over": 26_050, "but_not_over": None, "rate": "0.0275"},
    ]
    params = StateTaxParams.model_validate(
        _graduated_params(brackets={s: floor for s in (
            "single", "married_filing_jointly", "married_filing_separately", "head_of_household")})
    )
    assert params.brackets["single"][0].rate == Decimal("0")
    # ... but an all-zero schedule is a no-income-tax state, not a tax block.
    all_zero = [{"over": 0, "but_not_over": None, "rate": "0"}]
    with pytest.raises(ValueError, match="no-income-tax"):
        StateTaxParams.model_validate(
            _graduated_params(brackets={s: all_zero for s in (
                "single", "married_filing_jointly", "married_filing_separately", "head_of_household")})
        )


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_hi_nine_month_presence_test_names_the_pack_year(year: int):
    # Phase K JK27: the TY2024 pack said "more than nine months during 2023" for the food/excise and renters credits,
    # carried over from 2023 (the 2024 N-311 and Schedule X say "more than nine months in 2024").
    pack = load_state_knowledge("hi", year, base_dir=REPO_ROOT / "knowledge")
    texts = [str(c.get("eligibility", "")) for c in pack.credits if "nine months" in str(c.get("eligibility", ""))]
    assert len(texts) >= 2
    assert all(f"nine months during {year}" in text for text in texts), texts


def test_hi_2024_due_date_and_citations_are_the_2024_documents():
    # Phase K JK27 final review: the TY2024 pack carried the 2023 pack's labels. Its due date read 2025-04-22, but the
    # 2024 N-11 and N-15 instructions say April 21, 2025 (April 20 was a Sunday), and its mailing and deadline citations
    # named Form N-11 (Rev. 2023) lines 7 and 10 instead of the instructions that print them.
    pack = load_state_knowledge("hi", 2024, base_dir=REPO_ROOT / "knowledge")
    assert pack.deadlines["filing_due_date"] == "2025-04-21"
    assert "April 21, 2025" in pack.deadlines["citation"]["source"]
    assert pack.mailing_addresses["citation"]["url"].endswith("/2024/n11ins.pdf")
    import yaml

    raw = (REPO_ROOT / "knowledge" / "states" / "hi" / "2024.yaml").read_text(encoding="utf-8")
    loaded = yaml.safe_load(raw)
    stale = [c["source"] for c in _walk_sources(loaded) if "Rev. 2023" in c["source"] or "2023 N-1" in c["source"]]
    assert stale == []


def _walk_sources(node):
    if isinstance(node, dict):
        if isinstance(node.get("source"), str) and isinstance(node.get("url"), str):
            yield node
        for value in node.values():
            yield from _walk_sources(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_sources(value)
