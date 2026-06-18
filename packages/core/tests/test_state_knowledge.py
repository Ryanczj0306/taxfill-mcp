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

# Confirmed (cited, verbatim) treaty NON-conformity — these add back federally
# treaty-exempt income, so a treaty filer must be warned.
KNOWN_NONCONFORMING = {"ca", "al", "ar", "ct", "md", "ms"}


def test_state_knowledge_packs_exist():
    assert len(STATE_CODES) >= 27  # CA + the 26 fetched in the first wave


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


def test_known_nonconforming_states_are_flagged():
    flagged = {c for c in STATE_CODES if not load_state_knowledge(c, 2023, base_dir=REPO_ROOT / "knowledge").conforms_to_federal_treaties}
    # Every confirmed add-back state present in the repo must be flagged non-conforming.
    assert (KNOWN_NONCONFORMING & set(STATE_CODES)) <= flagged
