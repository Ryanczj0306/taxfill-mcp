"""Montana's Elderly Homeowner/Renter Credit needs AT LEAST nine months in Montana (2023, 2024 and 2025 packs).

The 2024 and 2025 packs said "more than nine months", the wording of the Form 2 Instructions' Line 16 summary (2025:
printed page 9; 2024: page 10). What the claimant attests on Schedule 2EC is "I resided in Montana for a minimum of
nine months during 2025" (2025 Form 2, page 10; the 2024 form prints the same for 2024), the Schedule 2EC
instructions list "You lived in Montana for at least nine months during the tax year." (printed page 38 in both
years), and MCA 15-30-2338(1)(b) says the claimant "must have resided in Montana for at least 9 months of that
period". So a filer who lived in Montana exactly nine months qualifies, and "more than nine months" told them they did
not. The 2023 pack already said "at least 9 months" (2023 Form 2 Instructions, page 43, "Nine-Month Test: You have
lived in Montana for at least nine months during the tax year."). Fixed 2026-10-16 (JK27).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from taxfill_core.knowledge import load_state_knowledge
from taxfill_core.schemas.profile import Profile, Provenance, ResidencePeriod, StateFootprintYear
from taxfill_core.statescope import state_scope

REPO = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO / "knowledge"
US = Provenance.user_stated()
CREDIT = "Elderly Homeowner/Renter Credit"


def _scoped_credit_line(year: int) -> str:
    """The credit's line as state_scope emits it for a full-year Montana resident."""
    lived = [ResidencePeriod(state="MT", start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)]
    profile = Profile(state_footprint={year: StateFootprintYear(lived=lived)})
    (mt,) = state_scope(profile, year, base_dir=KNOWLEDGE).states
    (line,) = [b for b in mt.benefits_candidates if b.startswith(f"{CREDIT} — ")]
    return line


@pytest.mark.parametrize("year", (2023, 2024, 2025))
def test_mt_elderly_credit_residency_test_is_at_least_nine_months(year: int):
    line = _scoped_credit_line(year)
    assert "more than nine months" not in line and "more than 9 months" not in line
    assert "at least nine months" in line or "at least 9 months" in line


@pytest.mark.parametrize("year", (2024, 2025))
def test_mt_elderly_credit_quotes_the_schedule_2ec_attestation(year: int):
    assert f'"I resided in Montana for a minimum of nine months during {year}"' in _scoped_credit_line(year)


def test_mt_2025_elderly_credit_citation_names_the_schedule_2ec_test():
    pack = load_state_knowledge("mt", 2025, base_dir=KNOWLEDGE)
    (credit,) = [c for c in pack.credits if c["name"] == CREDIT]
    source = credit["citation"]["source"]
    # The Line 16 summary's "more than" survives only as the reported inconsistency, never as the test itself.
    assert "at least nine months in Montana, per the Schedule 2EC tests on p.38" in source
    assert "where the Line 16 summary on p.9 says 'more than nine months'" in source
    assert "'I resided in Montana for a minimum of nine months during 2025'" in source
