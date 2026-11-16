"""Walkthrough findings P1-07, P1-06, P1-10 and the estimate part of P1-18 (Phase K-W, JW2a).

Every person here is fictitious. The figures are the walkthrough filer's: single, California, tax year
2025, one W-2 (box 1 177,425; box 2 34,180; box 17 14,250; box 14 state disability insurance 2,479.50).
"""

import ast
import re
import types
import typing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from taxfill_core.calc import standard_deduction
from taxfill_core.estimate import IncomeSnapshot, W2Facts, _salt_limit, estimate_refund
from taxfill_core import intake as intake_module
from taxfill_core.intake import example_profile, intake_checklist
from taxfill_core.knowledge import load_knowledge
from taxfill_core.schemas.profile import (
    Answer,
    DeductionsAndPaymentsYear,
    Household,
    Identity,
    Immigration,
    IncomeDocument,
    Profile,
    Provenance,
    ResidencePeriod,
    ResidencyFacts,
    StateFootprintYear,
    VisaPeriod,
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
    # The standing "missing inputs" line names the 1095-A only when no answer says there is none.
    assert not any("1095-A" in line for line in est.what_would_change_it)
    for other in (_filer(_doc("W-2")), _filer(_doc("W-2"), _doc("1095-A", "missing"))):
        unanswered = estimate_refund(other, YEAR, IncomeSnapshot(wages=177_425, federal_withholding=34_180))
        assert any("missing inputs" in line and "Form 1095-A amounts" in line for line in unanswered.what_would_change_it)


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
    entry = _entry(est, "Likely: Schedule 3 (Form 1040), the foreign tax credit")
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
    # A pack whose form note runs to a paragraph gives its first sentence; state_scope keeps the rest.
    commuter = _filer(_doc("W-2"))
    commuter.state_footprint = {YEAR: StateFootprintYear(
        lived=[ResidencePeriod(state="WA", start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)],
        worked=[WorkPeriod(state="OR", start=date(YEAR, 1, 1), end=date(YEAR, 12, 31), provenance=US)],
    )}
    oregon = [f for f in estimate_refund(commuter, YEAR, IncomeSnapshot(wages=90_000)).roadmap.returns_and_forms
              if f.startswith("State return:")]
    assert len(oregon) == 1 and oregon[0].startswith("State return: OR nonresident return — Form OR-40-P")
    assert len(oregon[0]) < 260 and oregon[0].endswith("(state_scope has the full note) (state tax is not estimated here).")
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


# ── 2a: the deductions-and-payments part of the interview ──────────────────────────────────────────

_DP = "deductions_and_payments"
_EVERY_FILER = ("itemizable_items", "estimated_payments", "extension", "prior_year_overpayment_applied")
_NO_ANSWERS = (_doc("1095-A", "not_applicable"), _doc("foreign account statement", "not_applicable"))


def _dp_ids(checklist) -> list[str]:
    return [q.id for q in checklist.next_questions if q.section == _DP]


def _answered(*fields: str, value: str = "none") -> DeductionsAndPaymentsYear:
    return DeductionsAndPaymentsYear(**{f: _ans(value) for f in fields})


def test_2a_one_document_is_no_longer_ready_and_the_result_says_what_holds_it_back():
    # On main this profile (identity, a filing status, one W-2 in hand) was ready_to_fill.
    cl = intake_checklist(_filer(_doc("W-2"), *_NO_ANSWERS), tax_year=YEAR)
    expected = [f"{_DP}.{f}" for f in (*_EVERY_FILER, "w2_box14", "hsa_coverage")]
    assert cl.ready_to_fill is False
    assert cl.ready_to_fill_blockers == expected == _dp_ids(cl)
    prompts = {q.id: q for q in cl.next_questions}
    items = prompts[f"{_DP}.itemizable_items"]
    for word in ("state disability", "vehicle licence fee", "real estate tax", "mortgage interest",
                 "gifts to charity", "medical"):
        assert word in items.prompt, word
    assert "other_state_local_taxes" in items.disambiguation
    assert "Form 4868" in prompts[f"{_DP}.extension"].prompt
    assert "box 14" in prompts[f"{_DP}.w2_box14"].prompt
    assert "code W" in prompts[f"{_DP}.hsa_coverage"].prompt and "self-only or family" in prompts[
        f"{_DP}.hsa_coverage"].prompt
    assert all("'none' and 'unknown' are answers" in q.disambiguation for q in cl.next_questions if q.section == _DP)


def test_2a_the_w2_other_box_is_named_as_the_years_form_prints_it():
    def prompt(year):
        cl = intake_checklist(_filer(_doc("W-2")), tax_year=year)
        return next(q.prompt for q in cl.next_questions if q.id == f"{_DP}.w2_box14")

    assert "does box 14 show" in prompt(2025) and "does box 14 show" in prompt(None)
    assert "does box 14a (box 14 before 2026) show" in prompt(2026)


def test_2a_every_filer_is_asked_the_four_questions_even_with_no_documents():
    cl = intake_checklist(tax_year=YEAR)
    assert _dp_ids(cl) == [f"{_DP}.{f}" for f in _EVERY_FILER]
    assert cl.ready_to_fill_blockers == _dp_ids(cl)


@pytest.mark.parametrize("kind, field, words", [
    ("1099-R", "ira_basis", ("SEP and SIMPLE", "December 31, 2025", "Form 8606")),
    ("Form 5498 (Example Brokerage)", "ira_basis", ("basis",)),
    ("1099-B", "employer_stock_sales", ("RSUs", "ESPP", "stock options", "Form 3922", "Form 3921")),
    ("Consolidated 1099 (Example Brokerage)", "employer_stock_sales", ("RSUs",)),
    ("1099-DIV", "dividend_boxes", ("box 5", "box 7")),
    ("1099 composite statement", "dividend_boxes", ("box 5",)),
])
def test_2a_a_document_kind_in_the_inventory_raises_its_follow_up(kind, field, words):
    without = intake_checklist(_filer(_doc("W-2")), tax_year=YEAR)
    assert f"{_DP}.{field}" not in _dp_ids(without)
    cl = intake_checklist(_filer(_doc("W-2"), _doc(kind, "missing")), tax_year=YEAR)   # 'missing' is still expected
    question = next(q for q in cl.next_questions if q.id == f"{_DP}.{field}")
    for word in words:
        assert word in question.prompt, word
    assert question.id in cl.ready_to_fill_blockers
    # A recorded "no such document" raises nothing.
    none = intake_checklist(_filer(_doc("W-2"), _doc(kind, "not_applicable")), tax_year=YEAR)
    assert f"{_DP}.{field}" not in _dp_ids(none)


def _visa_filer(status: str, start: date, days: dict[int, int] | None) -> Profile:
    """Ravi Example, a visa holder with one W-2 (fictitious)."""
    return Profile(
        identity=Identity(name=_ans("Ravi Example"), tax_id=_ans("999-88-0002"), dob=_ans(date(1998, 4, 2)),
                          us_person=_ans(False), mailing_address=_ans("100 Example Street")),
        immigration=Immigration(visa_timeline=[VisaPeriod(status=status, start=start, provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in days.items()}) if days else None,
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
        income_documents=[_doc("W-2")],
    )


def _dp_text(checklist, field: str) -> str:
    q = next(q for q in checklist.next_questions if q.id == f"{_DP}.{field}")
    return " ".join((q.prompt, q.why, q.disambiguation or ""))


_RESIDENT_ONLY = ("standard deduction", "mortgage", "real estate", "medical", "7.5%", "decide itemizing")


def test_2a_a_nonresident_is_asked_the_schedule_a_form_1040_nr_items_only():
    # Verifier F1: an F-1 student (nonresident for 2025 on these facts) was told the Form 1040 Schedule A story:
    # real estate tax, mortgage interest, medical costs, "itemizing beats the standard deduction". Instructions
    # for Form 1040-NR (2025): its Schedule A "doesn't have a line for medical expense deductions"; line 1a is
    # state and local income tax, then "Gifts to U.S. Charities".
    cl = intake_checklist(_visa_filer("F-1", date(2024, 8, 1), {2024: 150, 2025: 340}), tax_year=YEAR)
    items = _dp_text(cl, "itemizable_items")
    assert "Schedule A (Form 1040-NR)" in items and "gifts to U.S. charities" in items
    assert "state or local income tax" in items
    for word in _RESIDENT_ONLY:
        assert word not in items.lower(), word
    box14 = _dp_text(cl, "w2_box14")
    assert "decide itemizing" not in box14 and "other_state_local_taxes" not in box14
    assert "itemized_deductions" in items          # the only way the estimate deducts on this return


def test_2a_a_dual_status_year_takes_the_resident_items_for_the_period_of_residence():
    # Arrived 2025-06-01 with no earlier U.S. days: a dual-status year. Instructions for Form 1040-NR (2025): "You
    # can't take the standard deduction even for the part of the year you were a resident alien"; "For the period
    # of residence, allowable deductions include all deductions on Schedule A (Form 1040), including medical
    # expenses, real property taxes, and certain interest."
    cl = intake_checklist(_visa_filer("H-1B", date(2025, 6, 1), {2023: 0, 2024: 0, 2025: 214}), tax_year=YEAR)
    items = _dp_text(cl, "itemizable_items")
    assert "no standard deduction" in items and "weighs them against" not in items
    assert "for the part of 2025 you were a resident" in items and "medical" in items
    assert "Schedule A (Form 1040-NR)" in items
    assert "decide itemizing" not in _dp_text(cl, "w2_box14")


def test_2a_a_visa_filer_with_residency_unsettled_is_told_what_a_resident_result_adds():
    cl = intake_checklist(_visa_filer("F-1", date(2024, 8, 1), None), tax_year=YEAR)
    items = _dp_text(cl, "itemizable_items")
    assert "Schedule A (Form 1040-NR)" in items and "not settled yet" in items
    assert "standard deduction" not in items


def test_2a_a_us_person_keeps_the_form_1040_comparison():
    items = _dp_text(intake_checklist(_filer(_doc("W-2")), tax_year=YEAR), "itemizable_items")
    assert "beats the standard deduction" in items and "Form 1040-NR" not in items


def test_2a_state_estimated_payments_count_by_the_date_paid_not_the_year_they_are_for():
    # Verifier F10. Instructions for Schedule A (2025), line 5a: "State and local estimated tax payments made during
    # 2025, including any part of a prior year refund that you chose to have credited to your 2025 state or local
    # income taxes." A fourth-quarter 2025 payment made in January 2026 is not 2025 state tax paid.
    cl = intake_checklist(_filer(_doc("W-2")), tax_year=YEAR)
    for field in ("itemizable_items", "estimated_payments"):
        text = _dp_text(cl, field)
        assert f"made during {YEAR}" in text and "by payment date" in text, field
        assert f"state refund from {YEAR - 1} applied to {YEAR}" in text, field
    assert "state tax paid when itemizing" not in _dp_text(cl, "estimated_payments")
    from taxfill_core.estimate import _ITEMS_TO_COLLECT

    assert "state estimated payments made during the year (by payment date" in _ITEMS_TO_COLLECT[0]


def test_2a_look_alike_kinds_raise_no_follow_up():
    cl = intake_checklist(_filer(_doc("W-2G"), _doc("5498-SA"), _doc("1099-INT")), tax_year=YEAR)
    assert _dp_ids(cl) == [f"{_DP}.{f}" for f in _EVERY_FILER]


def test_2a_none_and_unknown_are_answers_and_the_interview_ends():
    profile = _filer(_doc("W-2"), _doc("1099-R"), _doc("1099-B"), _doc("1099-DIV"), *_NO_ANSWERS)
    from taxfill_core.schemas.profile import PriorFilings

    profile.prior_filings = PriorFilings(filed_years=_ans([2024]))
    every = (*_EVERY_FILER, "w2_box14", "hsa_coverage", "ira_basis", "employer_stock_sales", "dividend_boxes")
    # All but one answered: that one holds readiness back, alone.
    profile.deductions_and_payments = {YEAR: _answered(*every[:-1], value="unknown")}
    cl = intake_checklist(profile, tax_year=YEAR)
    assert cl.ready_to_fill is False and cl.ready_to_fill_blockers == [f"{_DP}.dividend_boxes"]
    profile.deductions_and_payments = {YEAR: _answered(*every)}
    done = intake_checklist(profile, tax_year=YEAR)
    assert done.ready_to_fill is True and done.ready_to_fill_blockers == [] and done.next_questions == []
    # Another year's answers never carry over.
    assert intake_checklist(profile, tax_year=YEAR + 1).ready_to_fill_blockers[0] == f"{_DP}.itemizable_items"
    # With no year named, the latest year on file is the one read.
    assert intake_checklist(profile).ready_to_fill is True


def test_2a_with_no_year_named_an_older_years_answers_never_make_the_interview_ready():
    # Verifier F3: 2024 answers and a 2025 state footprint, intake_checklist called with no tax_year, came back
    # ready on the 2024 answers. The year read is the latest the profile names, the footprint's included.
    profile = _filer(_doc("W-2"))
    profile.deductions_and_payments = {YEAR - 1: _answered(*_EVERY_FILER, "w2_box14", "hsa_coverage")}
    cl = intake_checklist(profile)
    assert cl.ready_to_fill is False
    assert cl.ready_to_fill_blockers == intake_checklist(profile, tax_year=YEAR).ready_to_fill_blockers
    assert cl.ready_to_fill_blockers[0] == f"{_DP}.itemizable_items"
    item = next(q for q in cl.next_questions if q.id == f"{_DP}.itemizable_items")
    assert item.answers_into == f"{_DP}.{YEAR}.itemizable_items" and str(YEAR) in item.prompt
    # Answered for the footprint's year, the same call is ready.
    profile.deductions_and_payments[YEAR] = _answered(*_EVERY_FILER, "w2_box14", "hsa_coverage")
    assert intake_checklist(profile).ready_to_fill is True


def test_2a_the_answers_live_in_additive_optional_fields():
    # A profile saved by an earlier version (no such section) still loads, and round-trips once it has one.
    saved = _filer(_doc("W-2")).model_dump(mode="json")
    del saved["deductions_and_payments"]
    assert Profile.model_validate(saved).deductions_and_payments == {}
    profile = _filer(_doc("W-2"))
    profile.deductions_and_payments = {YEAR: _answered("itemizable_items", value="SDI 2,479.50 in box 14")}
    again = Profile.model_validate(profile.model_dump(mode="json"))
    assert again.deductions_and_payments[YEAR].itemizable_items.value == "SDI 2,479.50 in box 14"
    assert again.deductions_and_payments[YEAR].extension is None
    with pytest.raises(ValueError, match="a blank answer records nothing"):
        DeductionsAndPaymentsYear(extension=_ans("  "))


# ── 2b: the profile is discoverable ────────────────────────────────────────────────────────────────


def _unwrap(annotation):
    """The annotation without ``| None``."""
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        inner = [a for a in typing.get_args(annotation) if a is not type(None)]
        assert len(inner) == 1, annotation
        return inner[0]
    return annotation


def _is_answer(tp) -> bool:
    return isinstance(tp, type) and issubclass(tp, Answer)


def _is_section(tp) -> bool:
    return isinstance(tp, type) and issubclass(tp, BaseModel) and not _is_answer(tp)


def _path_problem(path: str) -> str | None:
    """None when ``path`` names an exact Profile field: dots descend, ``[]`` / ``[n]`` is a list entry, and a
    year-keyed mapping takes a year (digits, or the placeholder ``<tax_year>``) as its next segment. A path that
    stops at a whole section (a model, or a year-keyed mapping of models) is not exact."""
    current, via_entry = Profile, False
    for part in path.split("."):
        if typing.get_origin(current) is dict:
            if not re.fullmatch(r"\d{4}|<tax_year>", part):
                return f"{path}: {part!r} should be a tax year"
            current, via_entry = _unwrap(typing.get_args(current)[1]), False
            continue
        name, bracket, _ = part.partition("[")
        if not _is_section(current) or name not in current.model_fields:
            return f"{path}: no field {name!r} there"
        current, via_entry = _unwrap(current.model_fields[name].annotation), False
        if bracket:
            if typing.get_origin(current) is not list or not re.fullmatch(r"\[\d*\]", bracket + part.partition("[")[2]):
                return f"{path}: {name!r} is not a list"
            current, via_entry = _unwrap(typing.get_args(current)[0]), True
    if _is_section(current) and not via_entry:
        return f"{path}: stops at the section {current.__name__}, not a field"
    if typing.get_origin(current) is dict and _is_section(_unwrap(typing.get_args(current)[1])):
        return f"{path}: stops at a year-keyed section — name the year and the field"
    return None


def _problems(answers_into: str) -> list[str]:
    return [p for p in (_path_problem(path.strip()) for path in answers_into.split(",")) if p]


def test_2b_the_path_check_itself_tells_a_field_from_a_section():
    for good in ("identity.name", "income_documents[]", "income_documents[].kind", "household.dependents[0].dob",
                 "state_footprint.2025.lived[]", "state_footprint.<tax_year>.worked[].employer_state",
                 "prior_filings.return_forms.2024", "deductions_and_payments.2025.extension",
                 "residency_facts.days_in_us", "banking.routing_number, banking.account_number"):
        assert _problems(good) == [], good
    # The values main carried for these questions: a section, not a field.
    for bad in ("state_footprint", "banking", "prior_filings", "retirement_contributions", "identity.nmae",
                "state_footprint.lived", "deductions_and_payments.2025", "income_documents.kind"):
        assert _problems(bad), bad


def test_2b_every_question_in_the_source_names_an_exact_field_path():
    # Every _q(...) call in intake.py, reached by a test or not: its answers_into (the fifth argument), with the
    # names an f-string uses replaced by sample values, must resolve against the Profile schema.
    samples = {"tax_year": "2025", "prior": "2024", "key": "2025", "i": "0", "_DP": "deductions_and_payments",
               "field": "extension", "f": "hsa"}

    def render(node) -> list[str]:
        if isinstance(node, ast.Constant):
            return [node.value]
        if isinstance(node, ast.JoinedStr):
            out = ""
            for piece in node.values:
                if isinstance(piece, ast.Constant):
                    out += piece.value
                else:
                    names = {n.id for n in ast.walk(piece.value) if isinstance(n, ast.Name)}
                    assert names and names <= set(samples), f"line {node.lineno}: add a sample for {names}"
                    # "{tax_year if tax_year is not None else '<tax_year>'}" renders as the year.
                    out += samples[sorted(names)[0]]
            return [out]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
            return render(node.args[0].elt)          # ", ".join(f"...{f}" for f in (...))
        raise AssertionError(f"line {node.lineno}: answers_into is built in a way this test cannot read")

    tree = ast.parse(Path(intake_module.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_q"]
    assert len(calls) >= 45
    problems = []
    for call in calls:
        for text in render(call.args[4]):
            problems += [f"line {call.lineno}: {p}" for p in _problems(text)]
            if text in Profile.model_fields:
                problems.append(f"line {call.lineno}: {text!r} is a whole section")
    assert problems == []


def test_2b_the_questions_a_run_returns_name_exact_field_paths():
    from taxfill_core.schemas.profile import Immigration, VisaPeriod

    visa = Profile(identity=Identity(us_person=_ans(False)), immigration=Immigration(
        visa_timeline=[VisaPeriod(status="F-1", start=date(2024, 8, 1), provenance=US)]))
    remote = _filer(_doc("W-2"), _doc("1099-R"), _doc("1099-B"), _doc("1099-DIV"))
    remote.state_footprint[YEAR].worked[0].remote = True
    profiles = [None, visa, remote, _filer(_doc("W-2")), Profile(household=Household(marital_status=_ans("married")))]
    seen = set()
    for profile in profiles:
        for year in (None, YEAR, 2026):
            for q in intake_checklist(profile, tax_year=year).next_questions:
                assert _problems(q.answers_into) == [], (q.id, q.answers_into)
                seen.add(q.id)
    for qid in ("income_documents.inventory", "state_footprint.lived_worked", "state_footprint.remote_employer_state",
                "banking.account", "prior_filings.history", "retirement.deferral_split",
                "deductions_and_payments.itemizable_items", "deductions_and_payments.ira_basis"):
        assert qid in seen, qid
    by_id = {q.id: q.answers_into for q in intake_checklist(remote, tax_year=YEAR).next_questions}
    assert by_id["state_footprint.remote_employer_state"] == "state_footprint.2025.worked[].employer_state"
    assert by_id["prior_filings.history"] == "prior_filings.filed_years, prior_filings.late_filing_context"
    assert by_id["deductions_and_payments.extension"] == "deductions_and_payments.2025.extension"
    assert by_id["banking.account"] == "banking.routing_number, banking.account_number, banking.account_type"


def test_2b_the_empty_profile_result_carries_an_example_profile_that_validates():
    start = intake_checklist(tax_year=YEAR)
    example = start.example_profile
    assert example == example_profile(YEAR) and start.worksheet is not None
    profile = Profile.model_validate(example)                      # the shape the tools accept
    assert Profile.model_validate(profile.model_dump(mode="json")) == profile
    # The three things the walkthrough's agent learned from validation errors.
    assert example["identity"]["name"] == {"value": "Avery Example", "provenance": {"kind": "user_stated"}}
    assert {d["provenance"]["kind"] for d in example["income_documents"]} == {"document", "user_stated"}
    assert set(example["state_footprint"]) == {"2025"} and set(example["state_footprint"]["2025"]) == {"lived", "worked"}
    assert {d["status"] for d in example["income_documents"]} == {"have", "missing", "not_applicable"}
    # Small, fictitious, and gone once the interview has started.
    assert len(str(example)) < 2_000 and "Example" in example["identity"]["name"]["value"]
    assert example["identity"]["tax_id"]["value"].startswith("999-88-")
    assert intake_checklist().example_profile["prior_filings"]["filed_years"]["value"] == [2024]
    assert intake_checklist(Profile(identity=Identity(us_person=_ans(True)))).example_profile is None
    # It is a usable starting point: the interview reads it and asks only what it lacks.
    ids = {q.id for q in intake_checklist(profile, tax_year=YEAR).next_questions}
    assert "identity.name" not in ids and "state_footprint.lived_worked" not in ids
    assert "deductions_and_payments.estimated_payments" not in ids
    assert "deductions_and_payments.prior_year_overpayment_applied" in ids
