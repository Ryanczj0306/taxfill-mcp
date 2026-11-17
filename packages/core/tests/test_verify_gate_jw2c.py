"""JW2c (walkthrough finding P1-05): relations added to the TY2025 Schedule D and Schedule CA (540) packs.

Each rule passes on a correct fictitious return whose totals are worked by hand from the printed line text, and each
fails when its line is changed by one dollar. Schedule D lines 6 and 14 (loss carryovers printed inside "( )") pass
under either sign convention. All amounts are fictitious.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.schemas.formpack import load_pack
from taxfill_core.verify import FilingItem, _tokenize, qualified_field_name, relations, verify_filing

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHED_D = load_pack(REPO_ROOT / "formpacks/federal/2025/sched_d/pack.yaml")
SCHED_CA = load_pack(REPO_ROOT / "formpacks/states/ca/2025/sched_ca_540/pack.yaml")

SCHED_D_NEW = [
    "7 == 1a.h + 1b.h + 2.h + 3.h + 4 + 5 - max(6, -6)",
    "15 == 8a.h + 8b.h + 9.h + 10.h + 11 + 12 + 13 - max(14, -14)",
]

# A correct fictitious Schedule D: every row (h) = (d) - (e) + (g); line 6 carries a 1,500 carryover, line 14 a 700
# carryover. 7 = 1000 + 500 - 500 + 200 - 100 - 1500 = -400; 15 = 2500 - 200 + 300 - 50 + 300 - 700 = 2150.
SCHED_D_RETURN = {
    "1a.d": 5000, "1a.e": 4000, "1a.h": 1000,
    "1b.d": 8500, "1b.e": 6375, "1b.g": -1625, "1b.h": 500,
    "2.d": 3000, "2.e": 3500, "2.h": -500,
    "4": 200, "5": -100, "6": 1500, "7": -400,
    "8a.d": 9000, "8a.e": 6500, "8a.h": 2500,
    "8b.d": 1000, "8b.e": 1200, "8b.h": -200,
    "11": 300, "12": -50, "13": 300, "14": 700, "15": 2150,
    "16": 1750,
}

# A correct fictitious Schedule CA (540), totals worked by hand from the printed lines (see the pack's comments).
SCHED_CA_RETURN = {
    # Part I, Section A. 1z_A = 120000 + 500 + 2000; 1z_C = 300 + 4300 + 700 (1i prints column C only).
    "1a_A": 120000, "1c_A": 500, "1h_A": 2000, "1z_A": 122500,
    "1a_B": 1000, "1z_B": 1000,
    "1a_C": 300, "1h_C": 4300, "1i_C": 700, "1z_C": 5300,
    "2a": 900, "2b_A": 2450, "2b_B": 600, "2b_C": 25,
    "3a": 1900, "3b_A": 2400, "3b_B": 100,
    "4a": 7010, "4b_A": 10, "4b_C": 50,
    "5b_A": 8000, "5b_B": 8000, "6b_A": 9000, "6b_B": 9000,
    "7a_A": -1200, "7a_C": 300,
    # Section B. The net operating loss (8a) is written positive and the exclusion (8d) negative: the two printed "( )"
    # conventions; 9a_A = 700 + 1000 + 300 - 2000 - 5000.
    "B1_A": 400, "B1_B": 400, "B2a_A": 6000, "B3_A": -2500, "B3_C": 200,
    "B5_A": 3000, "B5_B": 500, "B7_A": 1500, "B7_B": 1500,
    "B8a_A": 2000, "B8a_C": 2000, "B8b_A": 700, "B8b_B": 700, "B8d_A": -5000, "B8d_C": 5000,
    "B8p_A": 1000, "B8z_A": 300,
    "B9a_A": -5000, "B9a_B": 700, "B9a_C": 7000, "B9b2_B": 800,
    # 10_A = 122500 + 2450 + 2400 + 10 + 8000 + 9000 - 1200 + 400 + 6000 - 2500 + 3000 + 1500 - 5000
    # 10_B = 1000 + 600 + 100 + 8000 + 9000 + 400 + 500 + 1500 + 700 + 800
    # 10_C = 5300 + 25 + 50 + 300 + 200 + 7000
    "B10_A": 146560, "B10_B": 22600, "B10_C": 12875,
    # Section C. 26_A = 300 + 4300 + 1000 + 7000 + 2500 + 200; 26_B = 300 + 200; 26_C = 100.
    "C11_A": 300, "C11_B": 300, "C13_A": 4300, "C15_A": 1000, "C20_A": 7000, "C21_A": 2500,
    "C24z_A": 200, "C24z_B": 200, "C24b_C": 100,
    "C25_A": 200, "C25_B": 200, "C25_C": 100,
    "C26_A": 15300, "C26_B": 500, "C26_C": 100,
    "C27_A": 131260, "C27_B": 22100, "C27_C": 12775,
    # Part II. 4_A = 20000 - 9845; 5d = 12000 + 30000 + 500; 5e_A capped at 40000, so 5e_C = 2500.
    "II1": 20000, "II2": 131260, "II3": 9845, "II4_A": 10155,
    "II5a_A": 12000, "II5a_B": 12000, "II5b_A": 30000, "II5c_A": 500, "II5d_A": 42500,
    "II5e_A": 40000, "II5e_B": 12000, "II5e_C": 2500,
    "II6_A": 300, "II6_B": 300, "II7_A": 40300, "II7_B": 12300, "II7_C": 2500,
    "II8a_A": 15000, "II8a_C": 1000, "II8c_A": 200, "II8e_A": 15200, "II8e_C": 1000,
    "II9_A": 800, "II9_B": 100, "II10_A": 16000, "II10_B": 100, "II10_C": 1000,
    "II11_A": 3000, "II12_A": 500, "II12_C": 50, "II13_A": 200, "II14_A": 3700, "II14_C": 50,
    "II16_A": 400, "II16_B": 400,
    # 17_A = 10155 + 40300 + 16000 + 3700 + 400; 17_B = 12300 + 100 + 400; 17_C = 2500 + 1000 + 50
    "II17_A": 70555, "II17_B": 12800, "II17_C": 3550, "II18": 61305,
    "II19": 3000, "II20": 300, "II21": 400, "II22": 3700, "II23": 131260, "II24": 2625, "II25": 1075,
    "II26": 62380, "II27": -100, "II28": 62280,
}


def _lhs(relation: str) -> str:
    return relation.split("==", 1)[0].strip()


def test_a_column_suffixed_line_key_is_one_token():
    assert _tokenize("1z_A == 1a_A + B10_A") == [
        ("lineid", "1z_A"), ("op", "=="), ("lineid", "1a_A"), ("op", "+"), ("name", "B10_A")]


def test_the_new_schedule_d_relations_are_declared():
    for relation in SCHED_D_NEW:
        assert relation in SCHED_D.relations


def test_schedule_ca_declares_a_relation_for_each_printed_total():
    lhs = {_lhs(relation) for relation in SCHED_CA.relations}
    assert lhs == {
        "1z_A", "1z_B", "1z_C", "B9a_A", "B9a_B", "B9a_C", "B10_A", "B10_B", "B10_C",
        "C25_A", "C25_B", "C25_C", "C26_A", "C26_B", "C26_C", "C27_A", "C27_B", "C27_C",
        "II4_A", "II5d_A", "II5e_B", "II5e_C", "II7_A", "II7_B", "II7_C", "II8e_A", "II8e_C",
        "II10_A", "II10_B", "II10_C", "II14_A", "II14_B", "II14_C", "II17_A", "II17_B", "II17_C",
        "II18", "II22", "II25", "II26", "II28",
    }
    assert SCHED_CA.cross_form == []


@pytest.mark.parametrize("carryover_sign", [1, -1], ids=["carryover-positive", "carryover-negative"])
def test_schedule_d_correct_return_passes_under_either_carryover_sign(carryover_sign):
    values = {**SCHED_D_RETURN, "6": carryover_sign * 1500, "14": carryover_sign * 700}
    checks = relations(SCHED_D, values)
    assert [c.detail for c in checks if c.status != "PASS"] == []


def test_schedule_ca_correct_return_passes():
    checks = relations(SCHED_CA, SCHED_CA_RETURN)
    assert [c.detail for c in checks if c.status != "PASS"] == []


def test_a_blank_schedule_ca_passes():
    # A Schedule CA filed for one adjustment leaves most lines blank; blank reads as zero everywhere.
    checks = relations(SCHED_CA, {"2b_A": 2450, "2b_B": 600, "B10_A": 2450, "B10_B": 600,
                                  "C27_A": 2450, "C27_B": 600})
    assert [c.detail for c in checks if c.status != "PASS"] == []


@pytest.mark.parametrize("relation", SCHED_D_NEW)
def test_schedule_d_rule_fails_when_its_line_moves_a_dollar(relation):
    values = {**SCHED_D_RETURN, _lhs(relation): SCHED_D_RETURN[_lhs(relation)] + 1}
    check = next(c for c in relations(SCHED_D, values) if c.relation == relation)
    assert check.status == "FAIL", check.detail


def test_schedule_d_carryover_added_instead_of_subtracted_fails():
    # Line 7 figured as if the 1,500 carryover were a gain: -400 + 3000.
    values = {**SCHED_D_RETURN, "7": 2600, "16": 4750}
    check = next(c for c in relations(SCHED_D, values) if c.relation == SCHED_D_NEW[0])
    assert check.status == "FAIL"


@pytest.mark.parametrize("relation", SCHED_CA.relations)
def test_schedule_ca_rule_fails_when_its_line_moves_a_dollar(relation):
    line = _lhs(relation)
    values = {**SCHED_CA_RETURN, line: SCHED_CA_RETURN.get(line, 0) + 1}
    check = next(c for c in relations(SCHED_CA, values) if c.relation == relation)
    assert check.status == "FAIL", check.detail


@pytest.mark.parametrize("operand", ["1h_C", "B8s_A", "B9b3_B", "C19a_A", "C24k_A", "II15_C", "II27"])
def test_schedule_ca_rule_fails_when_an_operand_moves(operand):
    values = {**SCHED_CA_RETURN, operand: SCHED_CA_RETURN.get(operand, 0) + 1}
    failed = [c.relation for c in relations(SCHED_CA, values) if c.status == "FAIL"]
    assert failed, f"no relation reads {operand}"


def _dump(pack, values: dict[str, int], render=str) -> dict[str, str]:
    by_line = {f.line: f for f in pack.fields}
    return {qualified_field_name(pack, by_line[line]): render(amount) for line, amount in values.items()}


def test_verify_filing_reads_a_parenthesised_carryover_from_disk():
    def accountant(amount: int) -> str:
        return f"({-amount})" if amount < 0 else str(amount)

    disk = {**SCHED_D_RETURN, "6": -1500, "14": -700}
    report = verify_filing([
        FilingItem(form_key="sched_d", pack=SCHED_D, fields=_dump(SCHED_D, disk, accountant)),
        FilingItem(form_key="sched_ca_540", pack=SCHED_CA, fields=_dump(SCHED_CA, SCHED_CA_RETURN)),
    ])
    failing = [c.detail for c in report.relations if c.status == "FAIL"]
    assert failing == []
    names = {c.relation for c in report.relations}
    assert f"sched_d: {SCHED_D_NEW[0]}" in names and "sched_ca_540: II18 == II17_A - II17_B + II17_C" in names
