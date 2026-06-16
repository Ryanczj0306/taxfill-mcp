"""estimate_refund tests (dev plan sections 2/12, eval (j)). All data synthetic.

The estimate must only orchestrate calc, so each numeric assertion is checked
against an independent calc call — never a hand-computed magic number.
"""

from taxfill_core.calc import standard_deduction, tax_from_taxable_income
from taxfill_core.estimate import IncomeSnapshot, RefundEstimate, estimate_refund
from taxfill_core.schemas.profile import (
    Answer,
    Household,
    IncomeDocument,
    Profile,
    Provenance,
)

US = Provenance.user_stated()


def _ans(v):
    return Answer(value=v, provenance=US)


def _single(filing_status="single"):
    return Profile(household=Household(marital_status=_ans("single"), filing_status=_ans(filing_status)))


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
