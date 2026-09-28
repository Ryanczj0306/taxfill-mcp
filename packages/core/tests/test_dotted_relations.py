"""Phase J JEc — the printed relations the dotted-id grammar (JP5c) now lets the packs declare.

Each family is checked both ways on demo figures: a consistent fill PASSes every relation, and one wrong cell FAILs
exactly the relation that prints its arithmetic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.schemas.formpack import load_pack
from taxfill_core.verify import relations

FED = Path(__file__).resolve().parents[3] / "formpacks" / "federal"


def _by_relation(pack, values) -> dict[str, str]:
    return {c.relation: c.status for c in relations(pack, values)}


@pytest.mark.parametrize("year", [2023, 2024, 2025, 2026])
def test_jec_schedule_d_rows_combine_proceeds_cost_and_adjustments(year):
    pack = load_pack(FED / f"{year}/sched_d/pack.yaml")
    good = {"1a.d": 6000, "1a.e": 2000, "1a.h": 4000, "1b.d": 6000, "1b.e": 2000, "1b.g": -1000, "1b.h": 3000,
            "9.d": 500, "9.e": 800, "9.g": 100, "9.h": -200}
    checks = _by_relation(pack, good)
    assert {r: s for r, s in checks.items() if r.split(" ==")[0].endswith(".h")} == {
        f"{r}.h == {r}.d - {r}.e" + ("" if r in ("1a", "8a") else f" + {r}.g"): "PASS"
        for r in ("1a", "1b", "2", "3", "8a", "8b", "9", "10")}
    bad = _by_relation(pack, {**good, "1b.h": 5000})    # (g) forgotten: 6,000 - 2,000 + 1,000
    assert bad["1b.h == 1b.d - 1b.e + 1b.g"] == "FAIL"


@pytest.mark.parametrize("year", [2022, 2023, 2024, 2025])
def test_jec_schedule_oi_item_l_total_is_the_sum_of_column_d(year):
    pack = load_pack(FED / f"{year}/sched_oi/pack.yaml")
    rows = {"treaty_1.exempt_amount": 40000, "treaty_2.exempt_amount": 2500}
    rel = "1e == treaty_1.exempt_amount + treaty_2.exempt_amount + treaty_3.exempt_amount"
    assert _by_relation(pack, {**rows, "1e": 42500})[rel] == "PASS"
    assert _by_relation(pack, {**rows, "1e": 40000})[rel] == "FAIL"


@pytest.mark.parametrize("year,rows", [(2023, 14), (2024, 14), (2025, 11), (2026, 11)])
def test_jec_form_8949_rows_and_totals(year, rows):
    pack = load_pack(FED / f"{year}/f8949/pack.yaml")
    assert len(pack.relations) == 2 * (rows + 4)
    # The Instructions for Form 8949 (2025), Column (h): "Column (d) is $6,000, column (e) is $2,000, and column
    # (g) is ($1,000). Enter $3,000 in column (h)." A second demo row, and the totals.
    values = {"short_term.1.row01.d": 6000, "short_term.1.row01.e": 2000, "short_term.1.row01.g": -1000,
              "short_term.1.row01.h": 3000, "short_term.1.row02.d": 1500, "short_term.1.row02.e": 1800,
              "short_term.1.row02.h": -300, "short_term.2.d": 7500, "short_term.2.e": 3800, "short_term.2.g": -1000,
              "short_term.2.h": 2700}
    checks = relations(pack, values)
    assert checks and all(c.status == "PASS" for c in checks), [c.relation for c in checks if c.status != "PASS"]
    bad = _by_relation(pack, {**values, "short_term.2.h": 3000})
    assert [r for r, s in bad.items() if s == "FAIL"] == [r for r in bad if r.startswith("short_term.2.h ==")]


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_jec_schedule_nec_line_13_adds_each_column(year):
    pack = load_pack(FED / f"{year}/sched_nec/pack.yaml")
    values = {"1a.a": 800, "2c.a": 200, "13a": 1000, "14a": 100, "10c.c": 300, "11c": 700, "13c": 1000, "14c": 300,
              "15": 400}
    checks = _by_relation(pack, values)
    assert all(s == "PASS" for s in checks.values()), {r: s for r, s in checks.items() if s != "PASS"}
    bad = _by_relation(pack, {**values, "13c": 700})     # the Canada gambling net income on 10c left out
    assert [r for r, s in bad.items() if s == "FAIL" and r.startswith("13")] == [
        r for r in bad if r.startswith("13c ==")]


STATES = FED.parent / "states"


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_js3b_ut_tc40_part_4_total_adds_the_four_rows(year):
    pack = load_pack(STATES / f"ut/{year}/tc40/pack.yaml")
    rel = "contributions_total == contrib_a.amount + contrib_b.amount + contrib_c.amount + contrib_d.amount"
    rows = {"contrib_a.amount": 50, "contrib_b.amount": 25, "contrib_d.amount": 10}
    assert _by_relation(pack, {**rows, "contributions_total": 85, "28": 85})[rel] == "PASS"
    assert _by_relation(pack, {**rows, "contributions_total": 75, "28": 75})[rel] == "FAIL"   # row d left out
