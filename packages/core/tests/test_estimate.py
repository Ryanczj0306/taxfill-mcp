"""estimate_refund tests (dev plan sections 2/12, eval (j)). All data synthetic.

The estimate must only orchestrate calc, so each numeric assertion is checked
against an independent calc call — never a hand-computed magic number.
"""

import pytest

from taxfill_core.calc import standard_deduction, tax_from_taxable_income
from taxfill_core.estimate import IncomeSnapshot, RefundEstimate, estimate_refund
from taxfill_core.schemas.profile import (
    Answer,
    Dependent,
    Household,
    IncomeDocument,
    Profile,
    Provenance,
)

US = Provenance.user_stated()


def _ans(v):
    return Answer(value=v, provenance=US)


def _single(filing_status="single"):
    return Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans(filing_status)))


def _independent_refund(wages, withholding, status, year=2023):
    taxable = max(0, wages - standard_deduction(status, year).amount)
    tax = tax_from_taxable_income(taxable, status, year).tax
    return withholding - tax


def test_label_is_always_estimate():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.label == "ESTIMATE"
    assert isinstance(est, RefundEstimate)


def test_w2_only_known_status_matches_independent_calc():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    expected = _independent_refund(50000, 6000, "single")
    assert est.point == expected
    assert est.low == est.high == expected  # status known -> single number


def test_w2_only_estimate_brackets_the_final_number():
    # eval (j): the early W-2-only estimate must bracket the final computed refund.
    income = IncomeSnapshot(wages=50000, federal_withholding=6000)
    est = estimate_refund(_single(), 2023, income)
    final = _independent_refund(50000, 6000, "single")
    assert est.low <= final <= est.high


def test_unknown_status_widens_range_and_confirming_it_tightens():
    income = IncomeSnapshot(wages=90000, federal_withholding=9000)
    # Married but MFJ-vs-MFS not chosen: range spans both.
    undecided = Profile(household=Household(marital_status=_ans("married")))
    wide = estimate_refund(undecided, 2023, income)
    assert wide.status_assumed is True
    assert wide.low < wide.high  # genuine range across MFJ/MFS
    # The true MFJ outcome is inside the range.
    mfj_final = _independent_refund(90000, 9000, "married_filing_jointly")
    assert wide.low <= mfj_final <= wide.high
    # Confirming the status collapses the range.
    decided = Profile(household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_jointly")))
    narrow = estimate_refund(decided, 2023, income)
    assert narrow.status_assumed is False
    assert narrow.low == narrow.high == mfj_final


def test_self_employment_tax_is_included_and_halved_in_agi():
    from taxfill_core.calc import se_tax

    income = IncomeSnapshot(self_employment_net=48000, federal_withholding=0)
    est = estimate_refund(_single(), 2023, income)
    se = se_tax(48000, 2023)
    labels = {c.label: c.amount for c in est.composition}
    assert labels["Plus: self-employment tax"] == se.se_tax
    assert labels["Less: ½ self-employment tax (adjustment)"] == -se.deduction_half
    # AGI reflects the half-SE adjustment.
    assert labels["Adjusted gross income (AGI)"] == 48000 - se.deduction_half


def test_composition_ties_out_to_the_bottom_line():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, interest=500, federal_withholding=6000))
    labels = {c.label: c.amount for c in est.composition}
    assert labels["Total income"] == 50500
    # taxable = AGI - deduction; bottom line = withholding - total tax
    assert labels["Taxable income"] == max(0, labels["Adjusted gross income (AGI)"] + labels["Less: standard deduction"])
    assert est.point == labels["Estimated refund (+) or amount owed (-)"]


def test_assumptions_and_caveats_are_present():
    profile = _single()
    profile.income_documents = [IncomeDocument(kind="1099-INT", status="missing", provenance=US)]
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert any("Before unclaimed credits" in a for a in est.assumptions)
    assert any("credits" in c.lower() for c in est.what_would_change_it)
    assert any("1099-INT" in c for c in est.what_would_change_it)  # missing doc flagged


def test_citations_are_gov_and_present():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.citations
    assert all(c.url.startswith("https://") and ".gov" in c.url for c in est.citations)


def test_owing_headline_when_underwithheld():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=90000, federal_withholding=1000))
    assert est.point < 0
    assert "owing" in est.headline.lower() or "owe" in est.headline.lower()


def test_mfj_vs_mfs_comparison_surfaces_both_amounts_delta_recommendation_and_caveat():
    # eval (l): the comparison must show BOTH amounts + the dollar delta + a
    # recommendation + the joint-liability caveat.
    income = IncomeSnapshot(wages=90000, federal_withholding=9000)
    undecided = Profile(household=Household(marital_status=_ans("married")))
    est = estimate_refund(undecided, 2023, income)
    comp = est.comparison
    assert comp is not None
    statuses = {c.status for c in comp.candidates}
    assert {"married_filing_jointly", "married_filing_separately"} <= statuses
    # Both amounts independently verified against calc (no magic numbers).
    by_status = {c.status: c.bottom_line for c in comp.candidates}
    assert by_status["married_filing_jointly"] == _independent_refund(90000, 9000, "married_filing_jointly")
    assert by_status["married_filing_separately"] == _independent_refund(90000, 9000, "married_filing_separately")
    # Recommendation = the most-favorable signed bottom line; delta = abs(best - worst).
    values = list(by_status.values())
    assert comp.recommended_status == max(by_status, key=by_status.get)
    assert comp.delta == abs(max(values) - min(values))
    # Joint-liability caveat present whenever both MFJ and MFS are candidates.
    assert comp.joint_liability_caveat is not None
    assert "jointly" in comp.joint_liability_caveat.lower() and "liab" in comp.joint_liability_caveat.lower()


def test_no_comparison_when_single_candidate_status():
    # A confirmed status computes exactly one candidate -> no side-by-side comparison.
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.comparison is None


def test_roadmap_present_with_returns_and_missing_documents():
    profile = _single()
    profile.income_documents = [
        IncomeDocument(kind="W-2", status="have", provenance=US),
        IncomeDocument(kind="1099-INT", status="missing", provenance=US),
    ]
    # us_person True -> best-effort Form 1040; missing docs surfaced as honest gaps.
    profile.identity = None  # exercise the no-identity branch (still produces a roadmap)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.roadmap is not None
    assert "1099-INT" in est.roadmap.missing_documents
    assert "W-2" not in est.roadmap.missing_documents  # already in hand
    assert est.roadmap.estimated_time  # a coarse, honest string


def test_roadmap_returns_form_1040_for_us_person():
    from taxfill_core.schemas.profile import Identity

    profile = _single()
    profile.identity = Identity(us_person=_ans(True))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.roadmap.returns_and_forms == ["Form 1040"]


def _unmarried(hoh_qualifying=None, dependents=None):
    hh = Household(marital_status=_ans("unmarried"))
    if hoh_qualifying is not None:
        hh.hoh_qualifying_person = _ans(hoh_qualifying)
    if dependents:
        hh.dependents = dependents
    return Profile(household=hh)


def test_hoh_is_not_headline_when_qualifying_person_unconfirmed():
    # M3-EST-5: with a dependent but the HOH qualifying-person test NOT confirmed,
    # single is the conservative headline; HoH stays a candidate so the range brackets it.
    profile = _unmarried(dependents=[Dependent(name="Kid", relationship="child", provenance=US)])
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.filing_status_used == "single"
    assert est.comparison is not None
    assert {c.status for c in est.comparison.candidates} == {"single", "head_of_household"}


def test_hoh_is_headline_when_qualifying_person_confirmed():
    # When hoh_qualifying_person is confirmed True, head_of_household is the primary/headline.
    profile = _unmarried(hoh_qualifying=True, dependents=[Dependent(name="Kid", relationship="child", provenance=US)])
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.filing_status_used == "head_of_household"


def test_estimate_raises_for_year_with_no_knowledge_pack():
    # Freshness-protocol propagation: a year with no shipped pack surfaces the
    # loader's FileNotFoundError rather than inventing numbers.
    with pytest.raises(FileNotFoundError):
        estimate_refund(_single(), 1999, IncomeSnapshot(wages=50000, federal_withholding=6000))


def test_golden_2023_single_published_tax_table_value():
    # GOLDEN anchored to a PUBLISHED 2023 figure as a literal (NOT recomputed via calc):
    # single filer, $50,000 wages - $13,850 std deduction -> $36,150 taxable.
    # The published 2023 Tax Table tax for the row 'at least $36,150 but less than
    # $36,200' (single column) is $4,121 (IRS 2023 Form 1040 Tax Table).
    PUBLISHED_2023_TAX = 4121  # literal from the published table — do not compute here
    # Sanity-anchor the deduction the scenario depends on (a published 2023 figure too).
    assert standard_deduction("single", 2023).amount == 13850
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.point == 6000 - PUBLISHED_2023_TAX
