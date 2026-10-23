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


def test_a_2025_w2s_code_findings_cite_the_2025_instructions():
    # Phase K JK5: the release-candidate walkthrough's 2025 W-2 got "Instructions for Forms W-2 and W-3 (2026)".
    cites = {f.rule_id: f.citation for f in _w2(2025, **{"12a": "D 4000.00", "12b": "TT 10", "14b": "10100"}).findings}
    assert cites["V25"] == cites["V22"] == "Instructions for Forms W-2 and W-3 (2025), Box 12—Codes"
    assert cites["V23"] == "Instructions for Forms W-2 and W-3 (2026), Box 12—Codes and Box 14b"  # box 14b is 2026's
    assert {f.citation for f in _w2(2026, **{"12a": "D 4000.00"}).findings} == {
        "Instructions for Forms W-2 and W-3 (2026), Box 12—Codes and Box 14b"}


# The index entries "Codes for box 12, Form W-2" of the Instructions for Forms W-2 and W-3, edition by edition, verbatim:
# page references dropped, wrapped lines joined with one space (irs.gov/pub/irs-prior/iw2w3--YYYY.pdf, read 2026-10-16;
# w2_box12_codes.yaml's header records each file's sha256 and page). The 2020-2023 editions print 2019's entries.
_INDEX_2019 = {
    "A": "Uncollected social security or RRTA tax on tips",
    "B": "Uncollected Medicare tax on tips",
    "C": "Taxable cost of group-term life insurance over $50,000",
    "D": "Elective deferrals under section 401(k) cash or deferred arrangement (plan)",
    "E": "Elective deferrals under a section 403(b) salary reduction agreement",
    "F": "Elective deferrals under a section 408(k)(6) salary reduction SEP",
    "G": "Elective deferrals and employer contributions (including nonelective deferrals) to any governmental or "
         "nongovernmental section 457(b) deferred compensation plan",
    "H": "Elective deferrals under section 501(c) (18)(D) tax-exempt organization plan",
    "J": "Nontaxable sick pay",
    "K": "20% excise tax on excess golden parachute payments",
    "L": "Substantiated employee business expense reimbursements",
    "M": "Uncollected social security or RRTA tax on taxable cost of group-term life insurance over $50,000 (for "
         "former employees).",
    "N": "Uncollected Medicare tax on taxable cost of group-term life insurance over $50,000 (for former employees)",
    "P": "Excludable moving expense reimbursements paid directly to a member of the U.S. Armed Forces",
    "Q": "Nontaxable combat pay",
    "R": "Employer contributions to an Archer MSA",
    "S": "Employee salary reduction contributions under a section 408(p) SIMPLE plan",
    "T": "Adoption benefits",
    "V": "Income from the exercise of nonstatutory stock option(s)",
    "W": "Employer contributions to a health savings account (HSA)",
    "Y": "Deferrals under a section 409A nonqualified deferred compensation plan",
    "Z": "Income under section 409A on a nonqualified deferred compensation plan",
    "AA": "Designated Roth contributions under a section 401(k) plan",
    "BB": "Designated Roth contributions under a section 403(b) plan",
    "DD": "Cost of employer-sponsored health coverage",
    "EE": "Designated Roth contributions under a governmental section 457(b) plan",
    "FF": "Permitted benefits under a qualified small employer health reimbursement arrangement",
    "GG": "Income from qualified equity grants under section 83(i)",
    "HH": "Aggregate deferrals under section 83(i) elections as of the close of the calendar year",
}
_INDEX_2024 = {**_INDEX_2019, "II": "Medicaid waiver payments"}
_INDEX_2025 = {
    **_INDEX_2024,
    "F": "Elective deferrals under a section 408(k)(6) salary reduction SEP (this includes elective deferrals made to a "
         "Roth SEP IRA)",
    "M": "Uncollected social security or RRTA tax on taxable cost of group-term life insurance over $50,000 (for "
         "former employees)",
    "S": "Employee salary reduction contributions under a section 408(p) SIMPLE plan (this includes salary reduction "
         "contributions made to a Roth SIMPLE IRA)",
}
_INDEX_2026 = {
    **_INDEX_2025,
    "P": "Excludable moving expense reimbursements paid directly to a member of the U.S. Armed Forces or intelligence "
         "community",
    "TA": "Employer contributions under a section 128 Trump account contribution program paid to a Trump account of "
          "an employee or a dependent of an employee",
    "TP": "Total amount of cash tips reported to the employer",
    "TT": "Total amount of qualified overtime compensation",
}
_INDEX = {2019: _INDEX_2019, 2020: _INDEX_2019, 2021: _INDEX_2019, 2022: _INDEX_2019, 2023: _INDEX_2019,
          2024: _INDEX_2024, 2025: _INDEX_2025, 2026: _INDEX_2026}


@pytest.mark.parametrize("year", sorted(_INDEX))
def test_each_code_carries_its_own_years_index_title(year):
    # Phase K JK28: the table gave every year the 2026 titles, and dated code II from 2019.
    assert {c: e["title"] for c, e in w2_codes.codes_for(year).items()} == _INDEX[year]
    assert {c: w2_codes.code_entry(c, tax_year=year)["title"] for c in _INDEX[year]} == _INDEX[year]


def test_later_and_unknown_years_keep_the_2026_titles():
    for year in (2027, None):
        assert {c: e["title"] for c, e in w2_codes.codes_for(year).items()} == _INDEX_2026
    assert w2_codes.code_entry("f")["title"] == _INDEX_2026["F"]
    assert w2_codes.code_entry("TT", tax_year=2025)["since"] == 2026  # a code its year does not carry yet


def test_f_and_s_name_the_roth_iras_from_the_2025_edition():
    # Phase K JK28: the editions keep the old F and S titles through 2024 (the 2024 edition's What's New, page 2, already
    # describes Roth SEP and Roth SIMPLE IRAs under SECURE 2.0 Act section 601) and add the Roth IRA words in 2025, so a
    # 2022 and a 2023 W-2 read alike and a 2024 and a 2025 one do not.
    for code, roth in (("F", "Roth SEP IRA"), ("S", "Roth SIMPLE IRA")):
        titles = {y: w2_codes.codes_for(y)[code]["title"] for y in (2022, 2023, 2024, 2025)}
        assert titles[2022] == titles[2023] == titles[2024] != titles[2025]
        assert roth not in titles[2024] and roth in titles[2025]
        v25 = {y: next(f.message for f in _w2(y, **{"12a": f"{code} 3000.00"}).findings if f.rule_id == "V25")
               for y in (2022, 2023, 2024, 2025)}
        assert v25[2022] == v25[2023] == v25[2024] != v25[2025]
        assert roth not in v25[2024] and roth in v25[2025]


@pytest.mark.parametrize("year", sorted(_INDEX))
def test_v25_shows_the_w2s_own_years_title(year):
    # Phase K JK28: V25 showed the 2026 title beside the W-2's own year's citation. The 2019-2024 indexes close code M's
    # entry with a period, which the message's colon replaces.
    routed = [c for c, e in w2_codes.codes_for(year).items() if e["route"] != "info"]
    for i in range(0, len(routed), 4):
        boxes = dict(zip(("12a", "12b", "12c", "12d"), routed[i:i + 4]))
        doc = _w2(year, **{box: f"{code} 100.00" for box, code in boxes.items()})
        v25 = {f.boxes[0]: f.message for f in doc.findings if f.rule_id == "V25"}
        for box, code in boxes.items():
            assert v25[box].startswith(f"box {box} code {code} — {_INDEX[year][code].rstrip('.')}: "), v25[box]


def test_code_ii_starts_with_the_2024_w2():
    # Phase K JK28: the table dated code II from 2019. The 2024 edition's What's New (page 1): "There is a new code II
    # for box 12 used to report Medicaid waiver payments not included in box 1 of Form W-2."
    old = _w2(2023, **{"12a": "II 5000.00"}).findings
    assert [(f.rule_id, f.severity) for f in old] == [("V22", "error")]
    assert "(it starts with the 2024 W-2)" in old[0].message
    assert not _w2(2024, **{"12a": "II 5000.00"}).findings


def test_box_8_allocated_tips_are_read_and_flagged_as_outside_box_1():
    # Phase K JK5: the W-2 spec had no box 8, so allocated tips (income that is not in box 1) were never read.
    doc = _w2(2025, **{"8": "1,234.50"})
    assert {f.key: f.value for f in doc.fields}["8"] == "1234.50" and not doc.unexpected
    v30 = [f for f in doc.findings if f.rule_id == "V30"]
    assert len(v30) == 1 and v30[0].severity == "info" and v30[0].boxes == ["8"]
    assert "$1,234.50 are not in box 1" in v30[0].message and "unless you can prove" in v30[0].message
    assert "Box 8—Allocated tips" in v30[0].citation and "Line 1c" in v30[0].citation
    assert "Form 4137" in v30[0].message and "leaves these tips and that tax out" in v30[0].message
    assert not [f for f in _w2(2025, **{"8": "0.00"}).findings if f.rule_id == "V30"]
    assert not [f for f in _w2(2025).findings if f.rule_id == "V30"]


@pytest.mark.parametrize(("tax_year", "edition"), [(2024, 2024), (2022, 2022), (2026, 2025), (2020, 2025), (None, 2025)])
def test_box_8_cites_the_w2s_own_year_where_line_1c_says_so(tax_year, edition):
    # Line 1c's words hold from 2022 (the year line 1c began) to 2025, the newest edition read.
    v30 = next(f for f in _w2(tax_year, **{"8": "500"}).findings if f.rule_id == "V30")
    assert v30.citation == (f"Instructions for Forms W-2 and W-3 ({edition}), Box 8—Allocated tips; Instructions for "
                            f"Form 1040 ({edition}), Line 1c")
    assert f"The {edition} Form 1040 instructions (line 1c)" in v30.message


@pytest.mark.parametrize("reading", ["NaN", "nan", "sNaN", "Infinity", "-inf", "1e999999999", "1000000000000000",
                                     "1,234.5e3", "1e-999999999", "1.5E+3"])
def test_a_non_finite_or_absurd_amount_is_a_misread_not_a_crash(reading):
    # Phase K JK5: "NaN" in box 8 raised decimal.InvalidOperation out of extract_document (the whole W-2 reading was
    # lost), "Infinity" read as $Infinity, and "1e999999999" hung the int coercion.
    from taxfill_core.extract import _coerce

    doc = _w2(2025, **{"8": reading, "3": reading})
    fields = {f.key: f for f in doc.fields}
    assert fields["8"].status == fields["3"].status == "invalid"
    assert not [f for f in doc.findings if f.rule_id == "V30"]
    assert _coerce(reading, "money") == (reading, False) and _coerce(reading, "int") == (reading, False)

