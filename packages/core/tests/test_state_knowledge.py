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
STATE_KB = sorted((REPO_ROOT / "knowledge" / "states").glob("*/2023.yaml"))
STATE_CODES = [p.parent.name for p in STATE_KB]
US = Provenance.user_stated()

# Treaty NON-conformity — these add back / do not pass through federally
# treaty-exempt income, so a treaty filer must be warned (cited per pack).
KNOWN_NONCONFORMING = {"ca", "al", "ar", "ct", "md", "ms", "nd", "nj", "pa"}


def test_state_knowledge_packs_exist():
    # All income-tax jurisdictions: 41 states + DC (the 9 no-tax states need no pack).
    assert len(STATE_CODES) >= 42


@pytest.mark.parametrize("code", STATE_CODES, ids=lambda c: c)
def test_state_pack_loads_and_is_cited(code: str):
    pack = load_state_knowledge(code, 2023, base_dir=REPO_ROOT / "knowledge")
    assert isinstance(pack, StateKnowledge)
    assert pack.jurisdiction == f"states/{code}"
    assert isinstance(pack.conforms_to_federal_treaties, bool)
    assert pack.citation is not None  # cited to an official gov host (validated by the model)


@pytest.mark.parametrize("code", STATE_CODES, ids=lambda c: c)
def test_treaty_conformity_drives_the_nra_warning(code: str):
    pack = load_state_knowledge(code, 2023, base_dir=REPO_ROOT / "knowledge")
    profile = Profile(
        identity=Identity(us_person=Answer(value=False, provenance=US)),  # treaty filer
        state_footprint={2023: StateFootprintYear(
            lived=[ResidencePeriod(state=code.upper(), start=date(2023, 1, 1), end=date(2023, 12, 31), provenance=US)]
        )},
    )
    filing = next(s for s in state_scope(profile, 2023, base_dir=REPO_ROOT / "knowledge").states if s.state == code.upper())
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


@pytest.mark.parametrize("code", STATE_CODES, ids=lambda c: c)
def test_state_pack_has_cited_credits(code: str):
    # Every income-tax pack now ships a credits block; each credit cites a gov host
    # and the pack carries the verification caveat.
    from urllib.parse import urlparse

    from taxfill_core.knowledge import is_official_gov_host

    pack = load_state_knowledge(code, 2023, base_dir=REPO_ROOT / "knowledge")
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


@pytest.mark.parametrize("code", STATE_CODES, ids=lambda c: c)
def test_all_citation_urls_are_gov_hosted(code: str):
    # Not just credits[].citation: EVERY citation-shaped block (deadlines, all_citations,
    # residency, mailing, ...) must cite an official .gov/.mil/.us host. StateKnowledge uses
    # extra='allow', so these untyped blocks are otherwise never host-validated. Service URLs
    # (payment portals, etc.) are bare 'url:' with no 'source' sibling and are not authority.
    import yaml
    from urllib.parse import urlparse

    from taxfill_core.knowledge import is_official_gov_host

    raw = yaml.safe_load((REPO_ROOT / "knowledge" / "states" / code / "2023.yaml").read_text())
    for url in _iter_citation_urls(raw):
        host = (urlparse(url).hostname or "").lower()
        if host in _ALLOWED_NONGOV_CITATION_HOSTS:
            continue
        assert is_official_gov_host(host), (
            f"{code}: citation URL host {host!r} ({url}) is not an official government source"
        )


def test_known_nonconforming_states_are_flagged():
    flagged = {c for c in STATE_CODES if not load_state_knowledge(c, 2023, base_dir=REPO_ROOT / "knowledge").conforms_to_federal_treaties}
    # Every confirmed add-back state present in the repo must be flagged non-conforming.
    assert (KNOWN_NONCONFORMING & set(STATE_CODES)) <= flagged


# ── Phase G item G4: the flat-rate tax blocks (IL, PA, IN, MI, NC, CO, KY, AZ) ──

# The eight shipped flat-rate 2023 states with their verified exact rates.
FLAT_TAX_RATES = {
    "il": Decimal("0.0495"),
    "pa": Decimal("0.0307"),
    "in": Decimal("0.0315"),
    "mi": Decimal("0.0405"),
    "nc": Decimal("0.0475"),
    "co": Decimal("0.044"),
    "ky": Decimal("0.045"),
    "az": Decimal("0.025"),
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


def test_states_outside_the_flat_eight_ship_no_tax_block():
    kb = REPO_ROOT / "knowledge"
    for code in STATE_CODES:
        pack = load_state_knowledge(code, 2023, base_dir=kb)
        if code in FLAT_TAX_RATES:
            assert pack.tax is not None, f"{code}: flat state must ship the tax block"
        else:
            assert pack.tax is None, (
                f"{code}: unexpected tax block — graduated-rate states are NOT in the G4 "
                f"first tranche; extend calc.state_tax before shipping one"
            )
