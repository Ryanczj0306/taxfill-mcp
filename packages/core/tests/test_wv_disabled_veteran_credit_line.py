"""West Virginia's Disabled Veterans Real Property Tax Credit is claimed on IT-140 line 21, box B (2024 and 2025 packs).

It is a refundable credit, not a Tax Credit Recap Schedule credit. JS2c corrected the 2024 entry (2026-10-15); the
2025 widowed-spouse entry still said "Tax Credit Recap Schedule (the Disabled Veterans Real Property Tax Credit)" until
2026-10-16 (JK27). The 2025 booklet prints, on the return (page 2), line 21 "WV Property Tax Adjustment Tax Credits
(claim each separately below. Enter sum on line 21)" with box B "DISABLED VETERAN REAL PROPERTY TAX", and line 23
"Payments and Refundable Credits (add lines 15 through 22)"; the RECAP's last line is "27. TOTAL NON REFUNDABLE
CREDITS — add all recap lines. Enter on IT-140 line 9", and none of its lines 1-26 is this credit. The widowed-spouse
rule itself (Important Information for 2025, printed page 15) and its conditions (Disabled Veterans Real Property Tax
Credit, page 20: the widow(er) has not remarried, the property has not been reclassified or sold) reach state_scope.
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


@pytest.mark.parametrize("year", (2024, 2025))
def test_wv_disabled_veteran_credit_is_placed_on_line_21_box_b_not_the_recap(year: int):
    pack = load_state_knowledge("wv", year, base_dir=KNOWLEDGE)
    changes = [c for c in pack.effective_law_changes if "DISABLED VETERAN" in c.description.upper()]
    assert changes, f"wv/{year}: no law change names the Disabled Veterans Real Property Tax Credit"
    for change in changes:
        assert change.affects[0].startswith("Form IT-140 line 21, WV Property Tax Adjustment Tax Credits")
        assert "box B Disabled Veteran Real Property Tax" in change.affects[0]
        assert "NOT the Tax Credit Recap Schedule" in change.affects[0]
        assert not any(a.startswith("Tax Credit Recap Schedule") for a in change.affects)
        assert "IT-140 line 21 instructions (p.25)" in (change.lookup_path or "")


def test_wv_2025_widowed_spouse_change_reaches_state_scope_with_its_line_and_conditions():
    lived = [ResidencePeriod(state="WV", start=date(2025, 1, 1), end=date(2025, 12, 31), provenance=US)]
    profile = Profile(state_footprint={2025: StateFootprintYear(lived=lived)})
    (wv,) = state_scope(profile, 2025, base_dir=KNOWLEDGE).states
    (warning,) = [w for w in wv.warnings if "EXTENDED TO A WIDOWED SPOUSE" in w]
    assert "claimed on Form IT-140 line 21, box B" in warning
    assert "has not remarried and the qualifying property has not been reclassified or sold" in warning
    assert "Recap" not in warning and "RECAP" not in warning
    (cite,) = [c for c in wv.citations if "Widowed spouses may now claim" in c.source]
    assert "'WV Property Tax Adjustment Tax Credits (claim each separately below. Enter sum on line 21)'" in cite.source
    assert cite.url == "https://tax.wv.gov/Documents/PIT/2025/it140.PersonalIncomeTaxFormsAndInstructions.2025.pdf"
