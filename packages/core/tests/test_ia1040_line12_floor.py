"""IA 1040 line 12 never goes below zero (2023, 2024 and 2025 packs).

Line 12 is "BALANCE. Subtract line 11 from line 7". The 2023 face prints the floor itself ("If less than zero, enter
zero"); the 2024 and 2025 faces drop the printed words, but the instructions for both years keep the rule: "Subtract
line 11 from line 7. If less than zero, enter zero." (2024 IA 1040 instructions, revenue.iowa.gov media/4152; 2025 IA 1040
expanded instructions, "Line 12: Balance", Instruction Year 2025). A filer whose line-11 credits exceed the line-7 tax
enters 0 on line 12. Before 2026-10-16 the 2023 and 2025 packs declared "12 == 7 - 11", so that correct return FAILED
verify while the 2024 pack, built from the instructions, passed it (JK27).

Since Phase K JK28 the relation carries " unless alt_tax_method": a single filer who uses the Income Tax Reduction
Worksheet (41-146) enters its amount on line 12 and checks the Step 5 box. The floor itself is unchanged, and with no
field dump the box reads as unchecked, so these checks still evaluate it (test_relation_guard.py covers the box).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.schemas.formpack import load_pack
from taxfill_core.verify import relations as check_relations

REPO = Path(__file__).resolve().parents[3]
YEARS = (2023, 2024, 2025)
PACKS = [REPO / "formpacks" / "states" / "ia" / str(year) / "ia1040" / "pack.yaml" for year in YEARS]
FLOORED = "12 == max(7 - 11, 0) unless alt_tax_method"


@pytest.mark.parametrize("pack_path", PACKS, ids=lambda p: p.parts[-3])
def test_ia1040_line12_is_floored_at_zero(pack_path: Path):
    pack = load_pack(pack_path)
    (rel,) = [r for r in pack.relations if r.split("==")[0].strip() == "12"]
    assert rel == FLOORED

    def line12(values: dict[str, int]):
        (check,) = [c for c in check_relations(pack, values) if c.relation == FLOORED]
        return check

    assert line12({"7": 300, "11": 450, "12": 0}).status == "PASS"      # credits above the tax: line 12 is 0
    assert line12({"7": 2400, "11": 150, "12": 2250}).status == "PASS"  # the ordinary case is unchanged
    assert line12({"7": 300, "11": 450, "12": -150}).status == "FAIL"   # a negative line 12 is never right


@pytest.mark.parametrize("pack_path", PACKS, ids=lambda p: p.parts[-3])
def test_ia1040_later_balance_lines_stay_plain_subtraction(pack_path: Path):
    # Lines 14, 16 and 18 print no floor on any of the three faces, and the instructions add none.
    pack = load_pack(pack_path)
    for rel in ("14 == 12 - 13", "16 == 14 - 15", "18 == 16 - 17"):
        assert rel in pack.relations
