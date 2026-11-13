"""Walkthrough findings P1-07, P1-06, P1-10 and the estimate part of P1-18 (Phase K-W, JW2a).

Every person here is fictitious. The figures are the walkthrough filer's: single, California, tax year
2025, one W-2 (box 1 177,425; box 2 34,180; box 17 14,250; box 14 state disability insurance 2,479.50).
"""

from datetime import date
from decimal import Decimal

import pytest

from taxfill_core.calc import standard_deduction
from taxfill_core.estimate import IncomeSnapshot, W2Facts, _salt_limit, estimate_refund
from taxfill_core.knowledge import load_knowledge
from taxfill_core.schemas.profile import (
    Answer,
    Household,
    Identity,
    IncomeDocument,
    Profile,
    Provenance,
    ResidencePeriod,
    StateFootprintYear,
    WorkPeriod,
)

US = Provenance.user_stated()
YEAR = 2025


def _ans(value):
    return Answer(value=value, provenance=US)


def _doc(kind: str, status: str = "have") -> IncomeDocument:
    return IncomeDocument(kind=kind, status=status, provenance=US)


def _filer(*docs: IncomeDocument) -> Profile:
    """Avery Example: single, a U.S. person, lived and worked in California all of 2025."""
    whole_year = {"start": date(YEAR, 1, 1), "end": date(YEAR, 12, 31), "provenance": US}
    return Profile(
        identity=Identity(
            name=_ans("Avery Example"), tax_id=_ans("999-88-0001"), dob=_ans(date(1990, 4, 2)),
            us_person=_ans(True), mailing_address=_ans("100 Example Street, San Jose, CA 95113"),
        ),
        household=Household(
            marital_status=_ans("unmarried"), hoh_qualifying_person=_ans(False), filing_status=_ans("single"),
            no_other_taxpayers=_ans(True),
        ),
        state_footprint={YEAR: StateFootprintYear(
            lived=[ResidencePeriod(state="CA", **whole_year)], worked=[WorkPeriod(state="CA", **whole_year)],
        )},
        income_documents=list(docs),
    )


# ── 1a: a document recorded not_applicable is never missing ────────────────────────────────────────


def test_1a_a_not_applicable_document_is_not_reported_missing():
    profile = _filer(
        _doc("W-2"), _doc("1099-INT", "missing"),
        _doc("1095-A", "not_applicable"), _doc("foreign account statement", "not_applicable"),
    )
    est = estimate_refund(profile, YEAR, IncomeSnapshot(wages=177_425, federal_withholding=34_180))
    assert est.roadmap.missing_documents == ["1099-INT"]
    pending = [line for line in est.what_would_change_it if "unconfirmed or missing documents" in line]
    assert len(pending) == 1 and "(1099-INT)" in pending[0]
    assert "1095-A" not in pending[0] and "foreign account" not in pending[0]


def test_1a_only_not_applicable_documents_leave_nothing_missing():
    profile = _filer(_doc("W-2"), _doc("1095-A", "not_applicable"))
    est = estimate_refund(profile, YEAR, IncomeSnapshot(wages=177_425, federal_withholding=34_180))
    assert est.roadmap.missing_documents == []
    assert not any("unconfirmed or missing documents" in line for line in est.what_would_change_it)
    assert "in hand" in est.roadmap.estimated_time


# ── 1b: W-2 boxes as printed ───────────────────────────────────────────────────────────────────────


def test_1b_w2_boxes_are_accepted_with_cents():
    # The walkthrough's call: boxes 4 and 6 as printed, with cents, were refused.
    snap = IncomeSnapshot(w2s=[{
        "employer": "Example Systems", "box1": 177_425, "box2": 34_180, "box3": 176_100, "box4": 10_918.20,
        "box5": 200_225, "box6": 2_905.03, "box17": 14_250, "box12": [{"code": "W", "amount": 4_300.50}],
    }])
    assert snap.w2s[0].box4 == Decimal("10918.20") and snap.w2s[0].box6 == Decimal("2905.03")
    assert snap.ss_withheld_by_employer == [10_918] and snap.medicare_tax_withheld == [2_905]
    assert snap.wages == 177_425 and snap.federal_withholding == 34_180 and snap.medicare_wages == 200_225
    assert snap.w2s[0].coded("W") == 4_301


def test_1b_printed_strings_are_accepted_and_negative_amounts_refused():
    w2 = W2Facts(box1="$177,425.00", box2="34,180.00")
    assert (w2.box1, w2.box2) == (Decimal("177425.00"), Decimal("34180.00"))
    with pytest.raises(ValueError):
        W2Facts(box1=-1)


def test_1b_cents_are_added_before_the_total_is_rounded():
    # Instructions for Form 1040 (2025), Rounding Off to Whole Dollars: "include cents when adding the amounts
    # and round off only the total" — 100.40 + 200.40 is 300.80, so 301, not 100 + 200.
    snap = IncomeSnapshot(w2s=[{"box1": 100.40, "box2": 10.50}, {"box1": 200.40, "box2": 20.50}])
    assert snap.wages == 301
    assert snap.federal_withholding == 31
    # "$2.50 becomes $3": half a dollar rounds up, never to the even dollar.
    assert IncomeSnapshot(w2s=[{"box1": 2.50}]).wages == 3


def test_1b_an_aggregate_given_beside_the_w2s_must_still_agree():
    with pytest.raises(ValueError, match="disagree"):
        IncomeSnapshot(wages=300, w2s=[{"box1": 100.40}, {"box1": 200.40}])
    assert IncomeSnapshot(wages=301, w2s=[{"box1": 100.40}, {"box1": 200.40}]).wages == 301


def test_1b_box_17_and_other_state_and_local_taxes_are_carried_but_never_withholding():
    snap = IncomeSnapshot(
        w2s=[{"box1": 177_425, "box2": 34_180, "box17": 14_250}], other_state_local_taxes=2_627.50,
    )
    assert snap.w2s[0].box17 == Decimal(14_250)
    assert snap.other_state_local_taxes == Decimal("2627.50")
    assert snap.federal_withholding == 34_180   # box 17 is state tax: it is not a federal payment
    # A snapshot saved without the new fields still loads, and prices as before.
    old = IncomeSnapshot.model_validate({"wages": 177_425, "federal_withholding": 34_180})
    assert old.other_state_local_taxes is None
    profile = _filer(_doc("W-2"))
    assert estimate_refund(profile, YEAR, old).point == estimate_refund(
        profile, YEAR, IncomeSnapshot(w2s=[{"box1": 177_425, "box2": 34_180}])).point


def test_1b_the_joint_view_adds_both_spouses_other_state_and_local_taxes():
    one = IncomeSnapshot(other_state_local_taxes=100.25, spouse=IncomeSnapshot(other_state_local_taxes=50.50))
    assert one.combined_with_spouse().other_state_local_taxes == Decimal("150.75")
    neither = IncomeSnapshot(wages=1, spouse=IncomeSnapshot(wages=2))
    assert neither.combined_with_spouse().other_state_local_taxes is None


# ── 1c: the state and local tax already known, against the standard deduction ──────────────────────

W2 = {
    "employer": "Example Systems", "box1": 177_425, "box2": 34_180, "box3": 176_100, "box4": 10_918.20,
    "box5": 200_925, "box6": 2_921.74, "box17": 14_250,
    "box12": [{"code": "D", "amount": 23_500}, {"code": "W", "amount": 4_300}],
}
SDI_AND_VEHICLE_FEE = 2_479.50 + 148   # W-2 box 14 state disability insurance + the vehicle licence fee


def _w2_only(**extra) -> IncomeSnapshot:
    return IncomeSnapshot(w2s=[W2], **extra)


def test_1c_state_tax_close_to_the_standard_deduction_says_what_to_collect_and_keeps_one_figure():
    profile = _filer(_doc("W-2"))
    plain = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=[{**W2, "box17": 0}]))
    est = estimate_refund(profile, YEAR, _w2_only())
    cmp = est.itemizing_comparison
    standard = standard_deduction("single", YEAR).amount
    assert plain.itemizing_comparison is None
    assert cmp is not None and cmp.verdict == "close"
    assert (cmp.state_local_tax_paid, cmp.deductible, cmp.standard_deduction) == (14_250, 14_250, standard)
    assert cmp.itemized_bottom_line is None
    # Nothing is priced differently, so no range is invented.
    assert est.low == est.high == est.point == plain.point
    assert any(a.startswith("Compare itemizing with the standard deduction") for a in est.assumptions)
    collect = next(c for c in est.what_would_change_it if "collect the other Schedule A items" in c)
    for item in ("state disability", "vehicle licence", "real estate tax", "mortgage interest", "gifts to charity",
                 "medical"):
        assert item in collect, item
    assert any(f.startswith("Compare: Schedule A") for f in est.roadmap.returns_and_forms)


def test_1c_state_tax_over_the_standard_deduction_puts_the_itemized_outcome_in_the_range():
    profile = _filer(_doc("W-2"))
    plain = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=[{**W2, "box17": 0}]))
    est = estimate_refund(profile, YEAR, _w2_only(other_state_local_taxes=SDI_AND_VEHICLE_FEE))
    itemized = estimate_refund(profile, YEAR, _w2_only(itemized_deductions=16_878))
    cmp = est.itemizing_comparison
    assert cmp.verdict == "exceeds_standard"
    assert (cmp.state_local_tax_paid, cmp.limit, cmp.deductible) == (16_878, 40_000, 16_878)
    assert cmp.itemized_bottom_line == itemized.point
    assert est.point == plain.point                      # the point stays on the standard deduction
    assert (est.low, est.high) == (plain.point, itemized.point) and itemized.point > plain.point
    note = next(a for a in est.assumptions if a.startswith("Compare itemizing with the standard deduction"))
    assert "the range includes it" in note and "MORE than the $15,750 standard deduction" in note
    assert f"${itemized.point:,}" in note
    assert any("collect the other Schedule A items" in c for c in est.what_would_change_it)
    assert any(f.startswith("Likely: Schedule A") for f in est.roadmap.returns_and_forms)
    # The standard-deduction assumption is still stated, never silent beside the comparison.
    assert any(a.startswith("Standard deduction assumed") for a in est.assumptions)


def test_1c_small_state_tax_and_a_given_itemized_total_add_nothing():
    profile = _filer(_doc("W-2"))
    small = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=[{**W2, "box17": 5_000}]))
    assert small.itemizing_comparison is None and small.low == small.high
    assert not any("Compare itemizing" in a for a in small.assumptions)
    given = estimate_refund(profile, YEAR, _w2_only(other_state_local_taxes=SDI_AND_VEHICLE_FEE,
                                                    itemized_deductions=17_478))
    assert given.itemizing_comparison is None and given.low == given.high
    assert any(f.startswith("Likely: Schedule A (Form 1040) — this estimate itemizes $17,478")
               for f in given.roadmap.returns_and_forms)


@pytest.mark.parametrize("year", [2025, 2026])
def test_1c_the_limit_is_the_packs_block_applied_as_the_schedule_a_worksheet_applies_it(year):
    block = load_knowledge("federal", year).tax.salt_cap
    cap, phase = block["cap"], block["phase_down"]
    # The worksheet halves its result for a separate return, which is what the block's own halves state.
    assert block["cap_mfs"] * 2 == cap and phase["floor_mfs"] * 2 == phase["floor"]
    assert phase["magi_threshold_mfs"] * 2 == phase["magi_threshold"]
    threshold = phase["magi_threshold"]
    assert _salt_limit(block, threshold, "single") == (cap, False)
    assert _salt_limit(block, threshold + 50_000, "married_filing_jointly") == (cap - 15_000, True)
    assert _salt_limit(block, threshold + 1_000_000, "head_of_household") == (phase["floor"], True)
    assert _salt_limit(block, 100_000, "married_filing_separately") == (block["cap_mfs"], False)
    # Separate return: (cap - 30% of the excess over HALF the threshold), then half of that.
    assert _salt_limit(block, phase["magi_threshold_mfs"] + 50_000, "married_filing_separately") == (
        (cap - 15_000) // 2, True)
    assert _salt_limit(block, 5_000_000, "married_filing_separately") == (phase["floor_mfs"], True)


def test_1c_the_phase_down_limits_the_itemized_outcome_in_the_range():
    profile = _filer(_doc("W-2"))
    rich = {"box1": 600_000, "box2": 170_000, "box17": 60_000}
    est = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=[rich]))
    cmp = est.itemizing_comparison
    # AGI 600,000 is 100,000 over the 500,000 threshold: 40,000 less 30,000 leaves the 10,000 floor.
    assert (cmp.state_local_tax_paid, cmp.limit, cmp.deductible) == (60_000, 10_000, 10_000)
    assert cmp.verdict == "close" and est.low == est.high
    assert "the limit is reduced" in cmp.message
    lower = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=[{**rich, "box1": 550_000}]))
    assert lower.itemizing_comparison.limit == 25_000
    assert lower.itemizing_comparison.verdict == "exceeds_standard"
    assert lower.high == estimate_refund(
        profile, YEAR, IncomeSnapshot(w2s=[{**rich, "box1": 550_000}], itemized_deductions=25_000)).point


def test_1c_a_year_whose_pack_has_no_limit_says_the_comparison_was_not_made():
    profile = _filer(_doc("W-2"))
    est = estimate_refund(profile, 2024, IncomeSnapshot(w2s=[{"box1": 150_000, "box2": 25_000, "box17": 12_000}]))
    cmp = est.itemizing_comparison
    assert cmp.verdict == "not_estimated" and cmp.limit is None and cmp.deductible is None
    assert est.low == est.high
    assert any(b.block == "tax.salt_cap" for b in est.missing_blocks)
    assert "NOT ESTIMATED" in cmp.message and cmp.message in est.assumptions


def test_1c_a_candidate_status_whose_standard_deduction_the_tax_beats_is_priced_in_the_range():
    # Married, status not chosen: the tax alone is under the joint standard deduction and over the separate one.
    profile = Profile(household=Household(marital_status=_ans("married")))
    income = IncomeSnapshot(w2s=[{"box1": 150_000, "box2": 22_000, "box17": 18_000}])
    plain = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=[{"box1": 150_000, "box2": 22_000}]))
    est = estimate_refund(profile, YEAR, income)
    separate = estimate_refund(
        Profile(household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_separately"))),
        YEAR, income.model_copy(update={"itemized_deductions": 18_000}))
    assert est.filing_status_used == "married_filing_jointly" and est.point == plain.point
    cmp = est.itemizing_comparison
    assert cmp.verdict == "close" and cmp.standard_deduction == standard_deduction("married_filing_jointly", YEAR).amount
    assert cmp.other_statuses == {"married_filing_separately": separate.point}
    assert "married_filing_separately" in cmp.message
    assert est.low <= separate.point <= est.high
    assert any("itemizing comparison" in a for a in est.assumptions if a.startswith("Filing status not confirmed"))


def test_1c_each_spouses_separate_return_is_weighed_on_its_own_state_tax():
    profile = Profile(household=Household(
        marital_status=_ans("married"), filing_status=_ans("married_filing_separately")))
    mine = {"box1": 120_000, "box2": 20_000, "box17": 17_000}
    theirs = {"box1": 90_000, "box2": 13_000, "box17": 16_500}
    est = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=[mine], spouse=IncomeSnapshot(w2s=[theirs])))
    itemized = estimate_refund(profile, YEAR, IncomeSnapshot(
        w2s=[mine], itemized_deductions=17_000, spouse=IncomeSnapshot(w2s=[theirs], itemized_deductions=16_500)))
    cmp = est.itemizing_comparison
    assert cmp.verdict == "exceeds_standard" and cmp.state_local_tax_paid == 17_000 and cmp.limit == 20_000
    assert cmp.itemized_bottom_line == itemized.point and est.high == itemized.point > est.point


def test_1c_a_nonresident_return_says_the_state_tax_is_not_deducted():
    from taxfill_core.schemas.profile import Immigration, ResidencyFacts, VisaPeriod

    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2024, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2024: _ans(150), 2025: _ans(340)}),
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
    )
    est = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=[{"box1": 40_000, "box2": 4_000, "box17": 1_500}]))
    assert est.itemizing_comparison is None and est.low == est.high
    note = next(a for a in est.assumptions if a.startswith("State and local tax of $1,500 is recorded"))
    assert "NOT deducted" in note and note in est.what_would_change_it


# ── 1d: the roadmap is built from the inputs and names the state returns ───────────────────────────


def _walkthrough_income(**extra) -> IncomeSnapshot:
    return IncomeSnapshot(
        w2s=[W2], interest=2_450, dividends=2_400, qualified_dividends=1_900,
        capital_gain_long=2_800, capital_gain_short=2_300,
        retirement_distributions=[{
            "gross": 7_010, "taxable_amount": 7_010, "taxable_not_determined": True, "codes": "2",
            "ira_sep_simple": True, "converted_to_roth": True, "label": "backdoor Roth conversion",
        }],
        ira_pool={"basis_carryforward": 0, "nondeductible_contributions_this_year": 7_000, "dec31_total_value": 0},
        **extra,
    )


def _entry(est, start: str) -> str | None:
    return next((f for f in est.roadmap.returns_and_forms if f.startswith(start)), None)


def test_1d_the_roadmap_lists_the_forms_the_inputs_imply_and_the_state_return():
    est = estimate_refund(_filer(_doc("W-2")), YEAR, _walkthrough_income())
    forms = est.roadmap.returns_and_forms
    assert forms[0] == "Form 1040"
    assert "is over $1,500" not in _entry(est, "Likely: Schedule B") and "are each over $1,500" in _entry(
        est, "Likely: Schedule B")
    for start in ("Likely: Schedule D", "Likely: Form 8949", "Likely: Form 8889", "Likely: Form 8606",
                  "Likely: Form 8959"):
        assert _entry(est, start) is not None, start
    assert "$4,300" in _entry(est, "Likely: Form 8889")
    state = _entry(est, "State return: CA resident return")
    assert state is not None and "540" in state and "not estimated" in state
    assert "NOT exhaustive" in est.roadmap.note and "FEDERAL return only" in est.roadmap.note
    # Each entry comes from an input that is present: nothing here implies self-employment forms.
    assert not any(f.startswith("Likely: Schedule C") or "Schedule SE" in f for f in forms)


def test_1d_an_entry_appears_only_with_its_input():
    profile = Profile(identity=Identity(us_person=_ans(True)),
                      household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")))
    wages_only = estimate_refund(profile, YEAR, IncomeSnapshot(wages=60_000, federal_withholding=7_000))
    assert wages_only.roadmap.returns_and_forms == ["Form 1040"]   # no footprint recorded: no state entry
    under = estimate_refund(profile, YEAR, IncomeSnapshot(wages=60_000, interest=1_500, dividends=1_500))
    assert _entry(under, "Likely: Schedule B") is None             # "over $1,500", so 1,500 is not
    over = estimate_refund(profile, YEAR, IncomeSnapshot(wages=60_000, interest=1_501))
    assert "taxable interest of $1,501 is over $1,500" in _entry(over, "Likely: Schedule B")
    se = estimate_refund(profile, YEAR, IncomeSnapshot(self_employment_net=30_000))
    assert "Schedule SE" in _entry(se, "Likely: Schedule C")
    assert _entry(se, "Likely: Form 8959") is None
    loss = estimate_refund(profile, YEAR, IncomeSnapshot(wages=60_000, capital_gain_short=-500))
    assert _entry(loss, "Likely: Schedule D") and _entry(loss, "Likely: Form 8949")
    older = estimate_refund(profile, 2022, IncomeSnapshot(wages=60_000, interest=900))
    assert "threshold (not carried here for 2022)" in _entry(older, "Likely: Schedule B")


def test_1d_foreign_tax_is_named_in_the_roadmap_and_never_priced():
    profile = Profile(identity=Identity(us_person=_ans(True)),
                      household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")))
    base = {"wages": 60_000, "federal_withholding": 7_000, "dividends": 2_400}
    plain = estimate_refund(profile, YEAR, IncomeSnapshot(**base))
    est = estimate_refund(profile, YEAR, IncomeSnapshot(**base, foreign_tax_paid="41.60"))
    assert _entry(plain, "Likely: Schedule 3") is None
    entry = _entry(est, "Likely: Schedule 3 (Form 1040), line 1")
    assert "$42 of foreign tax" in entry and "Form 1116" in entry
    assert (est.low, est.point, est.high) == (plain.low, plain.point, plain.high)   # no credit is priced
    note = next(a for a in est.assumptions if a.startswith("NOT ESTIMATED — the foreign tax credit"))
    assert note in est.what_would_change_it
    couple = IncomeSnapshot(wages=1, foreign_tax_paid=10, spouse=IncomeSnapshot(wages=2, foreign_tax_paid="5.25"))
    assert couple.combined_with_spouse().foreign_tax_paid == Decimal("15.25")


def test_1d_state_returns_follow_the_footprint_and_a_nonresident_gets_no_form_1040_list():
    from taxfill_core.schemas.profile import Immigration, ResidencyFacts, VisaPeriod

    moved = _filer(_doc("W-2"))
    moved.state_footprint = {YEAR: StateFootprintYear(
        lived=[ResidencePeriod(state="WA", start=date(YEAR, 1, 1), end=date(YEAR, 6, 30), provenance=US),
               ResidencePeriod(state="CA", start=date(YEAR, 7, 1), end=date(YEAR, 12, 31), provenance=US)],
        worked=[WorkPeriod(state="CA", start=date(YEAR, 7, 1), end=date(YEAR, 12, 31), provenance=US)],
    )}
    est = estimate_refund(moved, YEAR, IncomeSnapshot(wages=90_000, federal_withholding=12_000))
    states = [f for f in est.roadmap.returns_and_forms if f.startswith("State return:")]
    assert len(states) == 1 and states[0].startswith("State return: CA part-year resident return — 540NR")
    student = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2024, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2024: _ans(150), 2025: _ans(340)}),
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
        state_footprint=moved.state_footprint,
    )
    nra = estimate_refund(student, YEAR, IncomeSnapshot(wages=30_000, interest=5_000, capital_gain_long=900))
    assert nra.roadmap.returns_and_forms[:2] == ["Form 1040-NR", "Form 8843"]
    assert not any(f.startswith("Likely:") for f in nra.roadmap.returns_and_forms)
    assert any(f.startswith("State return: CA") for f in nra.roadmap.returns_and_forms)
