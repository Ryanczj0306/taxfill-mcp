"""The 2026 education credits and their new SSN rule (Phase J JT1e, pitfall P-024).

All data synthetic: hypothetical demo households; the tax IDs are the placeholder SSN 123-45-6789 and an
ITIN-range placeholder 900-70-0000.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.calc import education_credits
from taxfill_core.datadir import knowledge_dir
from taxfill_core.estimate import IncomeSnapshot, estimate_refund
from taxfill_core.knowledge import KnowledgePack, load_knowledge
from taxfill_core.schemas.profile import Answer, Household, Identity, Profile, Provenance, Spouse

US = Provenance.user_stated()
SSN, ITIN = "123-45-6789", "900-70-0000"


def _ans(v):
    return Answer(value=v, provenance=US)


def _single(tax_id: str | None) -> Profile:
    return Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
                   identity=Identity(us_person=_ans(True), tax_id=_ans(tax_id) if tax_id else None))


def _joint(tp: str | None, sp: str | None) -> Profile:
    return Profile(
        household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_jointly"),
                            spouse=Spouse(us_person=_ans(True), tax_id=_ans(sp) if sp else None)),
        identity=Identity(us_person=_ans(True), tax_id=_ans(tp) if tp else None))


def _credit(est) -> int:
    return -sum(c.amount for c in est.composition if c.slot in ("education_credits_nonrefundable", "aotc_refundable"))


def _income(**kw) -> IncomeSnapshot:
    return IncomeSnapshot(wages=40_000, federal_withholding=3_000, aotc_qualified_expenses=[4_000], **kw)


def test_p024_the_2026_block_reads_its_sources():
    edu = load_knowledge("federal", 2026).tax.education_credits
    assert (edu.aotc.per_student_cap, edu.aotc.first_dollar_cap, edu.aotc.refundable_fraction) == (2_500, 2_000, Decimal("0.40"))
    assert (edu.aotc.phaseout.other.start, edu.aotc.phaseout.other.end) == (80_000, 90_000)
    assert (edu.llc.phaseout.married_filing_jointly.start, edu.llc.phaseout.married_filing_jointly.end) == (160_000, 180_000)
    rule = edu.ssn_requirement
    assert rule is not None and rule.one_spouse_suffices_on_joint_return and rule.dependent_student_needs_ssn
    assert "such individual's social security number" in rule.statute and "section 24(h)(7)" in rule.statute
    assert "after December 31, 2025" in rule.effective
    assert "valid for employment" in rule.instructions and "(including extensions)" in rule.instructions
    assert load_knowledge("federal", 2025).tax.education_credits.ssn_requirement is None


def test_p024_a_2026_block_without_the_rule_is_refused():
    data = yaml.safe_load((knowledge_dir() / "federal" / "2026.yaml").read_text(encoding="utf-8"))
    data["tax"]["education_credits"].pop("ssn_requirement")
    with pytest.raises(ValidationError, match="no ssn_requirement"):
        KnowledgePack.model_validate(data)


def test_p024_the_2026_op_prices_and_names_the_rule():
    r = education_credits([4_000], 0, magi=85_000, filing_status="single", year=2026)
    assert (r.aotc_total, r.aotc_refundable) == (1_250, 500)              # halfway through $80,000-$90,000
    assert "valid for employment" in r.work and "An ITIN is not one" in r.work
    assert "ELIGIBILITY (P-024)" not in education_credits([4_000], 0, magi=50_000, year=2025).work


def test_p024_an_ssn_filer_gets_the_credit_and_an_itin_filer_does_not():
    ok = estimate_refund(_single(SSN), 2026, _income(aotc_students_ssn_ok=[True]))
    assert _credit(ok) == 2_500
    itin = estimate_refund(_single(ITIN), 2026, _income(aotc_students_ssn_ok=[True]))
    assert _credit(itin) == 0
    assert any(a.startswith("No education credit:") and "ITIN" in a for a in itin.assumptions)


def test_p024_an_itin_only_student_gets_no_aotc():
    est = estimate_refund(_single(SSN), 2026, _income(aotc_students_ssn_ok=[False]))
    assert _credit(est) == 0
    assert any(a.startswith("No education credit for a dependent student") for a in est.assumptions)


def test_p024_an_unknown_status_is_not_estimated():
    for profile, income in ((_single(None), _income(aotc_students_ssn_ok=[True])), (_single(SSN), _income())):
        est = estimate_refund(profile, 2026, income)
        assert _credit(est) == 0
        assert any(a.startswith("NOT ESTIMATED — education credits") for a in est.assumptions)


def test_p024_one_spouse_suffices_on_a_joint_return():
    # The joint return's lower tax caps the nonrefundable part, so the yardstick is the all-SSN couple.
    full = _credit(estimate_refund(_joint(SSN, SSN), 2026, _income(aotc_students_ssn_ok=[True])))
    est = estimate_refund(_joint(ITIN, SSN), 2026, _income(aotc_students_ssn_ok=[True]))
    assert full > 0 and _credit(est) == full
    both = estimate_refund(_joint(ITIN, ITIN), 2026, _income(aotc_students_ssn_ok=[True]))
    assert _credit(both) == 0


def test_p024_2025_keeps_no_ssn_gate():
    est = estimate_refund(_single(ITIN), 2025, _income())
    assert _credit(est) == 2_500
    assert not [a for a in est.assumptions if "25A(g)(1)" in a]
