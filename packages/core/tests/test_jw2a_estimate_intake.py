"""Walkthrough findings P1-07, P1-06, P1-10 and the estimate part of P1-18 (Phase K-W, JW2a).

Every person here is fictitious. The figures are the walkthrough filer's: single, California, tax year
2025, one W-2 (box 1 177,425; box 2 34,180; box 17 14,250; box 14 state disability insurance 2,479.50).
"""

from datetime import date
from decimal import Decimal

import pytest

from taxfill_core.estimate import IncomeSnapshot, W2Facts, estimate_refund
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
