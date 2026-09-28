"""Schedule 3-A (2026): the refunded portion of four refundable credits as a PRWORA federal public benefit
(Phase J JT1c, pitfall P-023). All data synthetic: hypothetical demo households, demo figures.

The 2026 pack has no credits block until JT1d, so the estimator cases run on a scratch copy of the knowledge
tree whose 2026 pack borrows the 2025 credits block — the rule under test is Schedule 3-A's, not the credit
figures.
"""
from __future__ import annotations

import shutil
import typing
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.datadir import knowledge_dir
from taxfill_core.estimate import IncomeSnapshot, estimate_refund
from taxfill_core.knowledge import KnowledgePack, load_knowledge
from taxfill_core.schemas.profile import (
    Answer,
    Dependent,
    Household,
    Identity,
    Immigration,
    Profile,
    Provenance,
    QualifiedAlienStatus,
    ResidencyFacts,
    Spouse,
    VisaPeriod,
)

US = Provenance.user_stated()


def _ans(v):
    return Answer(value=v, provenance=US)


@pytest.fixture(scope="module")
def kdir(tmp_path_factory) -> Path:
    """A knowledge tree whose 2026 pack carries the 2025 credits block (a stand-in until JT1d)."""
    source = knowledge_dir()
    base = tmp_path_factory.mktemp("jt1c") / "knowledge"
    for part in ("federal", "treaties", "forms"):
        if (source / part).is_dir():
            shutil.copytree(source / part, base / part)
    for name in ("sources.yaml", "pitfalls.yaml"):
        shutil.copy(source / name, base / name)
    path = base / "federal" / "2026.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["credits"] = yaml.safe_load((source / "federal" / "2025.yaml").read_text(encoding="utf-8"))["credits"]
    absent = data["provisional"].get("blocks_deliberately_absent", [])
    data["provisional"]["blocks_deliberately_absent"] = [b for b in absent if b != "credits"]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return base


def _kids():
    return [Dependent(name=f"Child {i}", relationship="child", dob=date(2018 + i, 3, 1), has_ssn=True, provenance=US)
            for i in (1, 2)]


def _resident_visa(status: str = "H-1B", year: int = 2026):
    """A hypothetical visa holder in the U.S. all year for several years — a resident alien for tax."""
    first = year - 4
    return (Immigration(visa_timeline=[VisaPeriod(status=status, start=date(first, 1, 2), provenance=US)]),
            ResidencyFacts(days_in_us={y: _ans(365) for y in range(first, year + 1)}))


def _single_parent(*, us_person=False, status: str = "H-1B", answer: str | None = None) -> Profile:
    imm, rf = _resident_visa(status)
    return Profile(
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single"), dependents=_kids()),
        identity=Identity(us_person=_ans(us_person),
                          qualified_alien_status=_ans(answer) if answer is not None else None),
        immigration=None if us_person else imm,
        residency_facts=None if us_person else rf,
    )


_INCOME = IncomeSnapshot(wages=30_000, federal_withholding=1_500)


def _amount(est, slot: str) -> int:
    return sum(c.amount for c in est.composition if c.slot == slot)


def _benefit(est) -> int:
    """Schedule 3-A lines 1a-6, from the estimate's own ledger: the affected credits over the total tax (these
    households owe no Section B tax; the Additional Medicare Tax case below prices it)."""
    assert not _amount(est, "additional_medicare_tax")
    affected = -sum(_amount(est, s) for s in ("eitc", "actc_refundable", "aotc_refundable"))
    return max(0, affected - max(0, _amount(est, "total_tax")))


def _schedule_3a_note(est) -> str:
    notes = [a for a in est.assumptions if a.startswith("Schedule 3-A")]
    assert len(notes) == 1, est.assumptions
    return notes[0]


def test_p023_the_2026_block_reads_its_sources():
    block = load_knowledge("federal", 2026).federal_public_benefit
    assert block is not None and block.rule_status == "proposed"
    assert "published as final regulations" in block.applicability
    assert block.affected_credits == ["eitc", "actc_refundable", "aotc_refundable", "adoption_refundable"]
    assert "subtitle A of the Code" in block.refunded_portion
    assert "one spouse" in block.joint_return_rule and "on the date the taxpayer files" in block.status_date_rule
    assert "8 U.S.C. 1641(b)" in block.qualified_alien_definition
    assert "federalregister.gov" in block.citation.url
    # The profile's answers are the block's categories, plus the three that are not 1641 categories.
    categories = {c.id for c in (*block.qualified_categories, *block.statute_also_includes)}
    assert categories | {"us_citizen", "us_national", "none_of_these"} == set(typing.get_args(QualifiedAlienStatus))
    assert {c.cite for c in block.statute_also_includes} == {"8 U.S.C. 1641(c)(1)-(3)", "8 U.S.C. 1641(c)(4)"}
    # No block before the schedule exists.
    assert load_knowledge("federal", 2025).federal_public_benefit is None


def test_p023_a_2026_credits_block_needs_the_public_benefit_block():
    base = knowledge_dir() / "federal"
    data = yaml.safe_load((base / "2026.yaml").read_text(encoding="utf-8"))
    data["credits"] = yaml.safe_load((base / "2025.yaml").read_text(encoding="utf-8"))["credits"]
    KnowledgePack.model_validate(data)                       # with the block: fine
    data.pop("federal_public_benefit")
    with pytest.raises(ValidationError, match="no federal_public_benefit block"):
        KnowledgePack.model_validate(data)
    # A final rule belongs in the point, which the estimator does not price yet: the block refuses it.
    data = yaml.safe_load((base / "2026.yaml").read_text(encoding="utf-8"))
    data["federal_public_benefit"]["rule_status"] = "final"
    with pytest.raises(ValidationError):
        KnowledgePack.model_validate(data)


def test_p023_an_h1b_household_loses_the_refunded_portion_on_the_low_end(kdir):
    est = estimate_refund(_single_parent(), 2026, _INCOME, knowledge_dir=kdir)
    lost = _benefit(est)
    assert lost > 0 and _amount(est, "actc_refundable") < 0
    assert est.point == est.high and est.low == est.point - lost
    note = _schedule_3a_note(est)
    assert "'H-1B'" in note and "neither 8 U.S.C. 1641(b) nor (c)" in note
    assert f"holds the ${lost:,} back" in note and "published as final regulations" in note
    assert "Tax residency is not the test" in note


def test_p023_an_lpr_household_is_unchanged(kdir):
    est = estimate_refund(_single_parent(us_person=True), 2026, _INCOME, knowledge_dir=kdir)
    assert _benefit(est) > 0
    assert est.low == est.point == est.high
    note = _schedule_3a_note(est)
    assert "Nothing is held back" in note and "us_person answer is True" in note
    # A recorded answer decides, whatever the visa timeline says.
    est = estimate_refund(_single_parent(answer="refugee"), 2026, _INCOME, knowledge_dir=kdir)
    assert est.low == est.point == est.high and "'refugee'" in _schedule_3a_note(est)


def test_p023_the_1641c_categories_are_a_reading_not_a_yes(kdir):
    for profile in (_single_parent(answer="t_nonimmigrant"), _single_parent(status="T-1")):
        est = estimate_refund(profile, 2026, _INCOME, knowledge_dir=kdir)
        assert est.low == est.point - _benefit(est) < est.point
        assert "cites 1641(b) only" in _schedule_3a_note(est)


def test_p023_a_joint_return_needs_only_one_qualifying_spouse(kdir):
    imm, rf = _resident_visa()

    def couple(spouse: Spouse) -> Profile:
        return Profile(
            household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_jointly"),
                                dependents=_kids(), spouse=spouse),
            identity=Identity(us_person=_ans(False)), immigration=imm, residency_facts=rf)

    one = estimate_refund(couple(Spouse(us_person=_ans(True))), 2026, _INCOME, knowledge_dir=kdir)
    assert _benefit(one) > 0 and one.low == one.point == one.high
    assert "your spouse's us_person answer is True" in _schedule_3a_note(one)
    neither = estimate_refund(couple(Spouse(us_person=_ans(False), immigration=imm, residency_facts=None)), 2026,
                              _INCOME, knowledge_dir=kdir)
    lost = _benefit(neither)
    assert lost > 0 and neither.low <= neither.point - lost


def test_p023_an_unrecorded_answer_asks_for_it(kdir):
    profile = Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single"),
                                          dependents=_kids()))
    est = estimate_refund(profile, 2026, _INCOME, knowledge_dir=kdir)
    lost = _benefit(est)
    assert lost > 0 and est.low == est.point - lost
    assert "is not recorded" in _schedule_3a_note(est)
    assert any("identity.qualified_alien_status" in c and f"${lost:,}" in c for c in est.what_would_change_it)


def test_p023_the_liability_leaves_out_the_section_b_wage_tax(kdir):
    # Hypothetical demo figures: box 5 Medicare wages far above box 1 put 0.9% of them in the Additional Medicare
    # Tax, which Schedule 2 files in Section B — outside subtitle A, so it does not absorb the credits.
    income = IncomeSnapshot(wages=30_000, medicare_wages=230_000, federal_withholding=1_500)
    est = estimate_refund(_single_parent(), 2026, income, knowledge_dir=kdir)
    addmed = _amount(est, "additional_medicare_tax")
    assert addmed == 270                                   # 0.9% x (230,000 - 200,000)
    affected = -sum(_amount(est, s) for s in ("eitc", "actc_refundable", "aotc_refundable"))
    lost = max(0, affected - max(0, _amount(est, "total_tax") - addmed))
    assert lost > 0 and est.low == est.point - lost


def test_p023_before_2026_nothing_changes():
    imm, rf = _resident_visa(year=2025)
    profile = Profile(
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single"), dependents=_kids()),
        identity=Identity(us_person=_ans(False)), immigration=imm, residency_facts=rf)
    est = estimate_refund(profile, 2025, _INCOME)
    assert _amount(est, "actc_refundable") < 0
    assert est.low == est.point == est.high
    assert not [a for a in est.assumptions if a.startswith("Schedule 3-A")]
