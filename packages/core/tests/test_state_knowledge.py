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
    non_conform_warned = any("does not conform" in w.lower() for w in filing.warnings)
    conform_noted = any("conforms to federal treaty treatment" in w.lower() for w in filing.warnings)
    if pack.conforms_to_federal_treaties:
        assert conform_noted and not non_conform_warned, (
            f"{code}: conforming state must carry the positive conformity line only"
        )
    else:
        assert non_conform_warned, f"{code}: non-conforming state must warn"


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


# The AWS-backed document store that tax.newmexico.gov links to for its instruction PDFs —
# a knowingly-accepted, self-disclosed exception (see the `unverified` note in nm/2023.yaml).
# Any OTHER non-gov citation host is a defect.
_ALLOWED_NONGOV_CITATION_HOSTS = {"klvg4oyd4j.execute-api.us-west-2.amazonaws.com"}


def _iter_citation_urls(obj):
    """Yield the url of every citation-shaped dict (has both 'source' and a string 'url')."""
    if isinstance(obj, dict):
        if isinstance(obj.get("url"), str) and "source" in obj:
            yield obj["url"]
        for v in obj.values():
            yield from _iter_citation_urls(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_citation_urls(v)


@pytest.mark.parametrize("code,year", STATE_YEARS, ids=STATE_YEAR_IDS)
def test_all_citation_urls_are_gov_hosted(code: str, year: int):
    # Not just credits[].citation: EVERY citation-shaped block (deadlines, all_citations,
    # residency, mailing, ...) must cite an official .gov/.mil/.us host. StateKnowledge uses
    # extra='allow', so these untyped blocks are otherwise never host-validated. Service URLs
    # (payment portals, etc.) are bare 'url:' with no 'source' sibling and are not authority.
    import yaml
    from urllib.parse import urlparse

    from taxfill_core.knowledge import is_official_gov_host

    raw = yaml.safe_load((REPO_ROOT / "knowledge" / "states" / code / f"{year}.yaml").read_text())
    for url in _iter_citation_urls(raw):
        host = (urlparse(url).hostname or "").lower()
        if host in _ALLOWED_NONGOV_CITATION_HOSTS:
            continue
        assert is_official_gov_host(host), (
            f"{code}: citation URL host {host!r} ({url}) is not an official government source"
        )


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
        "az": Decimal("0.025"), "ga": Decimal("0.0519"), "ia": Decimal("0.038"),
        "il": Decimal("0.0495"), "in": Decimal("0.03"), "la": Decimal("0.03"),
        "mi": Decimal("0.0425"), "nc": Decimal("0.0425"), "pa": Decimal("0.0307"),
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
