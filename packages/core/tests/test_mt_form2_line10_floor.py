"""MT Form 2 line 10 never goes below zero (2024 and 2025 packs).

Line 10 prints "Subtract line 9 from line 8." with no floor, but Montana's instructions say "Nonrefundable credits reduce
the amount of tax you owe but cannot reduce your tax liability below zero" (2025 Form 2 Instructions, Schedule III Part I,
printed page 30 of 42; the 2024 booklet says the same). A filer whose Schedule III line 14 credits exceed the line-8 tax
enters line 9 in full and 0 on line 10. Before 2026-10-15 the 2025 pack declared "10 == 8 - 9", so that correct return
FAILED verify; found by the TY2024 port's semantic verify (tax 500, credits 800, line 10 = 0 -> rhs -300).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.schemas.formpack import load_pack
from taxfill_core.verify import relations as check_relations

REPO = Path(__file__).resolve().parents[3]
PACKS = [REPO / "formpacks" / "states" / "mt" / str(year) / "form2" / "pack.yaml" for year in (2024, 2025)]


def _line10(pack) -> str:
    (rel,) = [r for r in pack.relations if r.split("==")[0].strip() == "10"]
    return rel


@pytest.mark.parametrize("pack_path", PACKS, ids=lambda p: p.parts[-3])
def test_mt_form2_line10_is_floored_at_zero(pack_path: Path):
    pack = load_pack(pack_path)
    assert _line10(pack) == "10 == max(0, 8 - 9)"

    def line10(values: dict[str, int]):
        (check,) = [c for c in check_relations(pack, values) if c.relation == "10 == max(0, 8 - 9)"]
        return check

    assert line10({"8": 500, "9": 800, "10": 0}).status == "PASS"      # credits above the tax: line 10 is 0
    assert line10({"8": 4200, "9": 700, "10": 3500}).status == "PASS"  # the ordinary case is unchanged
    assert line10({"8": 500, "9": 800, "10": -300}).status == "FAIL"   # a negative line 10 is never right
