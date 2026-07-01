"""State knowledge-pack tests (dev plan section 6) — all shipped states/*/2023.yaml.

Each pack loads as a StateKnowledge, declares its treaty conformity (the
NRA-critical flag), and cites an official government host. The states that add
back federally treaty-exempt income (CA/CT/MD/MS-style) must surface the
treaty-non-conformity warning to a treaty filer via state_scope.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from taxfill_core.knowledge import StateKnowledge, load_state_knowledge
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
    warned = any("treat" in w.lower() for w in filing.warnings)
    assert warned == (not pack.conforms_to_federal_treaties), (
        f"{code}: treaty warning ({warned}) must match non-conformity ({not pack.conforms_to_federal_treaties})"
    )


@pytest.mark.parametrize("code", STATE_CODES, ids=lambda c: c)
def test_state_pack_has_cited_credits(code: str):
    # Every income-tax pack now ships a credits block; each credit cites a gov host
    # and the pack carries the verification caveat.
    from urllib.parse import urlparse

    pack = load_state_knowledge(code, 2023, base_dir=REPO_ROOT / "knowledge")
    credits = getattr(pack, "credits", None) or []
    assert credits, f"{code}: no credits block"
    assert getattr(pack, "credits_verification", None), f"{code}: missing credits_verification caveat"
    for c in credits:
        url = c["citation"]["url"]
        host = (urlparse(url).hostname or "").lower()
        assert any(host == t or host.endswith("." + t) for t in ("gov", "mil", "us")), f"{code}: {c['name']} cites non-gov {url}"
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

    raw = yaml.safe_load((REPO_ROOT / "knowledge" / "states" / code / "2023.yaml").read_text())
    for url in _iter_citation_urls(raw):
        host = (urlparse(url).hostname or "").lower()
        if host in _ALLOWED_NONGOV_CITATION_HOSTS:
            continue
        assert any(host == t or host.endswith("." + t) for t in ("gov", "mil", "us")), (
            f"{code}: citation URL host {host!r} ({url}) is not an official .gov/.mil/.us source"
        )


def test_known_nonconforming_states_are_flagged():
    flagged = {c for c in STATE_CODES if not load_state_knowledge(c, 2023, base_dir=REPO_ROOT / "knowledge").conforms_to_federal_treaties}
    # Every confirmed add-back state present in the repo must be flagged non-conforming.
    assert (KNOWN_NONCONFORMING & set(STATE_CODES)) <= flagged
