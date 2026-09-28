"""calc op charitable_deduction and the estimator's IRC 170(p) slot (Phase J JF9, pitfall P-022).

Hypothetical demo gifts and incomes only.
"""

from __future__ import annotations

import pytest

from taxfill_core.calc import charitable_deduction
from taxfill_core.estimate import IncomeSnapshot, estimate_refund
from taxfill_core.knowledge import load_knowledge
from taxfill_core.schemas.profile import Profile


def _gift(amount, **kw):
    return {"amount": amount, "teos_code": "PC", **kw}


def _slot(est, slot):
    return next((ln.amount for ln in est.composition if ln.slot == slot), None)


def test_p022_the_2026_block_reads_its_sources():
    cc = load_knowledge("federal", 2026).charitable_contributions
    assert (cc.nonitemizer.cap.for_status("single"), cc.nonitemizer.cap.for_status("married_filing_jointly")) == (1_000, 2_000)
    assert cc.nonitemizer.excluded_teos_codes == ["SO", "SONFI", "SOUNK"] and cc.nonitemizer.excludes_donor_advised_funds
    assert str(cc.itemizer_floor_rate) == "0.005"
    ib = cc.insubstantial_benefit
    assert (str(ib.token_item_cost_max), str(ib.token_item_minimum_payment), str(ib.two_percent_dollar_cap)) == (
        "13.90", "69.50", "139")   # Rev. Proc. 2025-32 §4.33(2)
    assert (cc.membership_disregard_max_annual_payment, cc.quid_pro_quo_statement_over, cc.written_acknowledgment_at) == (
        75, 75, 250)
    assert load_knowledge("federal", 2025).charitable_contributions is None


def test_p022_the_op_refuses_a_year_before_the_law():
    with pytest.raises(ValueError, match="after December 31, 2025"):
        charitable_deduction(2025, "single", [_gift(100)], agi=50_000)


def test_p022_the_nonitemizer_cap_and_the_payee_exclusions():
    r = charitable_deduction(2026, "single", [
        _gift(600), _gift(700),                                   # public charities: $1,300 -> capped at $1,000
        _gift(400, teos_code="SO"), _gift(400, teos_code="SONFI"), _gift(400, teos_code="SOUNK"),
        _gift(500, donor_advised_fund=True), _gift(300, cash=False), _gift(200, teos_code="PF"),
    ], agi=60_000)
    assert r.nonitemizer_deduction == 1_000
    assert [g.nonitemizer_eligible for g in r.gifts] == [True, True, False, False, False, False, False, False]
    assert "509(a)(3)" in r.gifts[2].nonitemizer_reason and "donor advised fund" in r.gifts[5].nonitemizer_reason
    assert "cash" in r.gifts[6].nonitemizer_reason
    joint = charitable_deduction(2026, "married_filing_jointly", [_gift(2_500)], agi=90_000)
    assert joint.nonitemizer_deduction == 2_000


def test_p022_a_depends_code_needs_the_callers_determination():
    r = charitable_deduction(2026, "single", [_gift(300, teos_code="EO"), _gift(300, teos_code="GROUP", donee_170b1a=True)],
                             agi=60_000)
    assert [g.nonitemizer_eligible for g in r.gifts] == [False, True]
    assert "Depends on various factors" in r.gifts[0].nonitemizer_reason


def test_p022_the_characterization_rules():
    r = charitable_deduction(2026, "single", [
        _gift(1_000, benefit="recognition_only"),                            # a plaque: no return benefit
        _gift(60, benefit="membership"),                                     # $75 or less: disregarded
        _gift(120, benefit="membership", benefit_value=40),                  # over $75: the value comes off
        _gift(100, benefit="token_items", benefit_value=10),                 # >= $69.50 and <= $13.90
        _gift(5_000, benefit="goods_or_services", benefit_value=100),        # <= min(2%, $139)
        _gift(500, benefit="goods_or_services", benefit_value=150),          # a gala dinner comes off
    ], agi=100_000)
    assert [g.deductible for g in r.gifts] == [1_000, 60, 80, 100, 5_000, 350]
    assert "INFO 2010-0172" in r.gifts[0].benefit_rule and "$75 or less" in r.gifts[1].benefit_rule
    # The characterization rules are repeated in the work the user reads.
    assert "Pub 526" in r.work and "Rev. Proc. 2025-32" in r.work


def test_p022_a_membership_over_75_without_its_value_is_refused_prescribing_the_statement():
    with pytest.raises(ValueError, match="6115") as exc:
        charitable_deduction(2026, "single", [_gift(150, benefit="membership")], agi=60_000)
    assert "written statement" in str(exc.value) and "benefit_value" in str(exc.value)


def test_p022_substantiation_duties():
    r = charitable_deduction(2026, "single", [_gift(250), _gift(300, written_acknowledgment=True), _gift(50)],
                             agi=60_000)
    assert any("OBTAIN" in d and "170(f)(8)" in d for d in r.gifts[0].duties)
    assert any("in hand" in d for d in r.gifts[1].duties)
    assert not any("170(f)(8)" in d for d in r.gifts[2].duties)
    assert all(any("170(f)(17)" in d for d in g.duties) for g in r.gifts)   # the cash record, any amount


def test_p022_the_itemizer_floor_and_the_better_path():
    # AGI $200,000: 0.5% = $1,000 comes off $6,000 of gifts; with $20,000 of other itemized deductions itemizing wins.
    r = charitable_deduction(2026, "single", [_gift(6_000)], agi=200_000, other_itemized=20_000)
    assert (r.floor, r.itemized_charitable_after_floor, r.itemized_path_total) == (1_000, 5_000, 25_000)
    assert (r.standard_path_total, r.better_path) == (16_100 + 1_000, "itemize")
    small = charitable_deduction(2026, "single", [_gift(6_000)], agi=200_000)
    assert small.better_path == "standard" and small.standard_path_total == 17_100


# ── The estimator ────────────────────────────────────────────────────────────


def _est(year, **kw):
    return estimate_refund(Profile(), year, IncomeSnapshot(wages=60_000, federal_withholding=6_000, **kw))


def test_p022_the_2026_estimate_takes_170p_below_the_standard_deduction():
    base = _est(2026)
    six = _est(2026, charitable_cash_nonitemizer=600)
    capped = _est(2026, charitable_cash_nonitemizer=1_400)
    assert _slot(six, "nonitemizer_charitable_deduction") == -600
    assert _slot(base, "taxable_income") - _slot(six, "taxable_income") == 600
    assert _slot(capped, "nonitemizer_charitable_deduction") == -1_000
    label = next(ln.label for ln in six.composition if ln.slot == "nonitemizer_charitable_deduction")
    assert "line 12f" in label and "170(p)" in label


def test_p022_itemizing_wins_and_the_input_goes_unused():
    est = _est(2026, charitable_cash_nonitemizer=1_000, itemized_deductions=30_000)
    assert _slot(est, "nonitemizer_charitable_deduction") is None
    assert any("does not elect to itemize" in a for a in est.assumptions)


def test_p022_2025_ignores_the_input_and_says_why():
    est = _est(2025, charitable_cash_nonitemizer=600)
    assert _slot(est, "nonitemizer_charitable_deduction") is None
    assert any("ignored for 2025" in a for a in est.assumptions)


def test_p022_a_planning_pack_without_the_block_names_it_missing(planning_year, synthetic_provisional_pack):
    kdir = synthetic_provisional_pack(["charitable_contributions"])
    est = estimate_refund(Profile(), planning_year,
                          IncomeSnapshot(wages=60_000, federal_withholding=6_000, charitable_cash_nonitemizer=600),
                          knowledge_dir=kdir)
    assert [m.block for m in est.missing_blocks if m.block == "charitable_contributions"] == ["charitable_contributions"]
    assert any("NOT ESTIMATED" in a and "non-itemizer" in a for a in est.assumptions)
