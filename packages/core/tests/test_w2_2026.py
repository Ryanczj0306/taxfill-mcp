"""The 2026 Form W-2 and structured W-2 facts (Phase J JT4a). All data synthetic: hypothetical demo W-2s."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from taxfill_core import w2_codes
from taxfill_core.calc import dependent_care_credit
from taxfill_core.estimate import IncomeSnapshot, W2Box12, W2Facts, estimate_refund
from taxfill_core.extract import extract_document
from taxfill_core.schemas.profile import Answer, Dependent, Household, Identity, Profile, Provenance

US = Provenance.user_stated()


def _ans(v):
    return Answer(value=v, provenance=US)


def _single(dependents=()) -> Profile:
    return Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans(
        "head_of_household" if dependents else "single"), dependents=list(dependents)),
        identity=Identity(us_person=_ans(True)))


_A = W2Facts(employer="Demo Corp A", box1=60_000, box2=6_000, box3=64_000, box4=3_968, box5=64_000, box6=928,
             box12=[W2Box12(code="D", amount=4_000), W2Box12(code="DD", amount=7_200)])
_B = W2Facts(employer="Demo Corp B", box1=20_000, box2=1_500, box3=20_000, box4=1_240, box5=20_000, box6=290)


def test_jt4a_the_code_table_reads_the_2026_instructions():
    codes = w2_codes.codes_for(2026)
    assert len(codes) == 33 and set(w2_codes.codes_for(2025)) == set(codes) - {"TA", "TP", "TT"}
    assert codes["TP"]["title"] == "Total amount of cash tips reported to the employer"
    assert codes["TT"]["title"] == "Total amount of qualified overtime compensation"
    assert (codes["TP"]["route"], codes["TT"]["route"], codes["W"]["route"]) == (
        "schedule_1a_tips", "schedule_1a_overtime", "hsa_employer")
    assert {c for c, e in codes.items() if e["route"] == "elective_deferral_402g"} == {"D", "E", "F", "S", "AA", "BB"}
    assert {c for c, e in codes.items() if e["route"] == "deferral_457b"} == {"G", "EE"}
    box14 = w2_codes.table()["box14"]
    assert box14["split_from"] == 2026 and "Box 14b was created" in box14["split"]
    assert w2_codes.parse_box12("DD: 7,200") == ("DD", "7200") and w2_codes.parse_box12("1234") is None


def test_jt4a_the_aggregates_derive_from_the_w2s_and_a_mismatch_raises():
    derived = IncomeSnapshot(w2s=[_A, _B])
    hand = IncomeSnapshot(wages=80_000, federal_withholding=7_500, ss_wages=84_000, medicare_wages=84_000,
                          ss_withheld_by_employer=[3_968, 1_240], medicare_tax_withheld=[928, 290])
    for f in ("wages", "federal_withholding", "ss_wages", "medicare_wages"):
        assert getattr(derived, f) == getattr(hand, f), f
    assert sorted(derived.ss_withheld_by_employer) == sorted(hand.ss_withheld_by_employer)
    a = estimate_refund(_single(), 2025, derived)
    b = estimate_refund(_single(), 2025, hand)
    assert (a.low, a.point, a.high) == (b.low, b.point, b.high)
    # Estimated payments may sit on top of box 2 — never below it.
    assert IncomeSnapshot(w2s=[_A, _B], federal_withholding=9_000).federal_withholding == 9_000
    for bad in ({"wages": 75_000}, {"medicare_wages": 80_000}, {"federal_withholding": 7_000},
                {"ss_withheld_by_employer": [3_968]}):
        with pytest.raises(ValidationError, match="the W-2 facts and the aggregates disagree"):
            IncomeSnapshot(w2s=[_A, _B], **bad)


def test_jt4a_box_10_reduces_the_2441_expense_limit():
    # A closed year (2025): $3,000 of care for one child, $2,000 of it paid by the employer's plan (box 10).
    kid = Dependent(name="Kid", relationship="child", dob=date(2020, 3, 1), has_ssn=True, provenance=US)
    w2 = W2Facts(employer="Demo Corp", box1=45_000, box2=3_000, box3=45_000, box4=2_790, box5=45_000, box6=653,
                 box10=2_000)
    est = estimate_refund(_single([kid]), 2025, IncomeSnapshot(w2s=[w2], dependent_care_expenses=3_000,
                                                              dependent_care_persons=1))
    line = -sum(c.amount for c in est.composition if c.slot == "dependent_care_credit_nonrefundable")
    op = dependent_care_credit(3_000, 1, 45_000, agi=45_000, filing_status="head_of_household", year=2025,
                               employer_benefits=2_000)
    none = dependent_care_credit(3_000, 1, 45_000, agi=45_000, filing_status="head_of_household", year=2025)
    assert line == op.credit < none.credit
    assert any("box 10, $2,000" in a for a in est.assumptions)


def test_jt4a_overtime_and_the_joint_view():
    tt = W2Facts(employer="Demo Shop", box1=50_000, box2=4_000, box3=50_000, box4=3_100, box5=50_000, box6=725,
                 box12=[W2Box12(code="TT", amount=3_100)])
    one = IncomeSnapshot(w2s=[tt])
    assert one.qualified_overtime_premium == 3_100
    assert IncomeSnapshot(w2s=[tt], qualified_overtime_premium=2_000).qualified_overtime_premium == 2_000
    couple = IncomeSnapshot(w2s=[_A], spouse=IncomeSnapshot(w2s=[_B, tt])).combined_with_spouse()
    assert couple.wages == 130_000 and len(couple.w2s) == 3 and couple.qualified_overtime_premium == 3_100


def test_jt4a_the_402g_excess_and_the_code_w_guard_are_disclosed():
    heavy = [W2Facts(employer="Demo A", box1=90_000, box2=12_000, box3=110_000, box4=6_820, box5=110_000, box6=1_595,
                     box12=[W2Box12(code="D", amount=20_000)]),
             W2Facts(employer="Demo B", box1=30_000, box2=3_000, box3=35_000, box4=2_170, box5=35_000, box6=508,
                     box12=[W2Box12(code="AA", amount=5_000), W2Box12(code="W", amount=1_200)])]
    est = estimate_refund(_single(), 2026, IncomeSnapshot(w2s=heavy, pre_agi_adjustments=1_200))
    assert any(a.startswith("EXCESS DEFERRAL") and "$25,000" in a and "$24,500" in a for a in est.assumptions)
    assert any("code W" in a and "NEVER also deducted" in a for a in est.assumptions)
    calm = estimate_refund(_single(), 2026, IncomeSnapshot(w2s=[_A]))
    assert not any(a.startswith("EXCESS DEFERRAL") for a in calm.assumptions)


def _w2(tax_year, **over):
    reading = {"employee_ssn": "123-45-6789", "employer_ein": "12-3456789", "1": "60,000.00", "2": "6,000.00"}
    reading.update(over)
    return extract_document("docs/demo-w2.pdf", "W-2", reading, tax_year=tax_year)


def test_jt4a_the_w2_reading_checks_its_codes_and_box_14b():
    doc = _w2(2026, **{"12a": "D 4000.00", "12b": "TP 2,100.00", "14b": "10100", "12c": "W 1200"})
    ids = [(f.rule_id, f.severity) for f in doc.findings]
    assert ("V25", "info") in ids and not [i for i in ids if i[1] == "error"]
    assert any("402(g)" in f.message for f in doc.findings) and any("NEVER a second deduction" in f.message
                                                                        for f in doc.findings)
    # TT on a 2025 W-2 is not a 2025 code; an unknown code; an unreadable entry.
    old = _w2(2025, **{"12a": "TT 1500"})
    assert [(f.rule_id, f.severity) for f in old.findings] == [("V22", "error")] and "2026 W-2" in old.findings[0].message
    assert [f.rule_id for f in _w2(2026, **{"12a": "XX 10"}).findings] == ["V22"]
    assert [f.rule_id for f in _w2(2026, **{"12a": "5000"}).findings] == ["V22"]
    # Box 14b: not on a 2025 W-2, needs code TP, and TP needs it.
    assert "V23" in [f.rule_id for f in _w2(2025, **{"14b": "10100"}).findings]
    assert "V24" in [f.rule_id for f in _w2(2026, **{"14b": "10100"}).findings]
    assert "V24" in [f.rule_id for f in _w2(2026, **{"12a": "TP 900"}).findings]
    assert any("nonqualifying occupation" in f.message
               for f in _w2(2026, **{"12a": "TP 900", "14b": "10100 000"}).findings)
    # The 2025 form's single box 14 reads as box 14a.
    fields = {f.key: f for f in _w2(2025, **{"14": "SDI 312.00"}).fields}
    assert fields["14a"].value == "SDI 312.00"
