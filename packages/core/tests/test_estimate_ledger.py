"""The composition-ledger invariants — the Phase H spine (Stage 2).

The composition used to be narrative-only: a worksheet story whose raw amounts
deliberately do not sum to the bottom line, which is why _build_comparison could
only report two bottom lines and a delta with no attribution, and why the one
real planning session rebuilt the "where does the difference come from" table by
hand in a scratch script. Every line now carries slot/role/effect, and TWO
invariants are enforced at runtime on every computation (never only in tests):

    1. RECONCILIATION:  sum(line.effect) == bottom, exactly, in integers.
    2. ATTRIBUTION:     StatusComparison.delta_lines sum exactly to delta.

The property tests here drive randomized profiles through the public surface so
the runtime checks fire across the whole input space — ARPA-2021 paths, the
spouse-split two-return MFS, NRA paths, missing-block planning years. All data
is synthetic; the generator is seeded, so a failure reproduces exactly.
"""

from __future__ import annotations

import random
from datetime import date

from taxfill_core.estimate import (
    _LEDGER_SLOTS,
    IncomeSnapshot,
    estimate_refund,
)
from taxfill_core.schemas.profile import (
    Answer,
    Dependent,
    Household,
    Identity,
    Profile,
    Provenance,
)

US = Provenance.user_stated()


def _ans(v):
    return Answer(value=v, provenance=US)


def _profile(status: str | None, marital: str, deps: list[Dependent]) -> Profile:
    hh = Household(
        marital_status=_ans(marital),
        filing_status=_ans(status) if status else None,
        dependents=deps,
        hoh_qualifying_person=_ans(True) if status == "head_of_household" else None,
    )
    return Profile(identity=Identity(us_person=_ans(True)), household=hh)


def _random_snapshot(rng: random.Random, *, with_spouse: bool) -> IncomeSnapshot:
    dividends = rng.choice([0, 0, 1200, 8000])
    fields = dict(
        wages=rng.choice([0, 18000, 52000, 110000, 260000]),
        federal_withholding=rng.choice([0, 2500, 9000, 30000]),
        interest=rng.choice([0, 300, 4000]),
        dividends=dividends,
        qualified_dividends=rng.randint(0, dividends) if dividends else 0,
        capital_gain_long=rng.choice([0, 0, 7000, -9000]),
        capital_gain_short=rng.choice([0, 0, 1500, -2500]),
        self_employment_net=rng.choice([0, 0, 350, 24000, -3000]),
        social_security_benefits=rng.choice([0, 0, 0, 21000]),
        student_loan_interest_paid=rng.choice([0, 0, 1800]),
        pre_agi_adjustments=rng.choice([0, 0, 3000]),
        aotc_qualified_expenses=rng.choice([[], [], [4000]]),
        dependent_care_expenses=rng.choice([0, 0, 5000]),
        dependent_care_persons=1,
        itemized_deductions=rng.choice([None, None, 21000]),
        ss_withheld_by_employer=rng.choice([[], [], [9000, 4500]]),
    )
    if with_spouse:
        fields["spouse"] = IncomeSnapshot(
            wages=rng.choice([0, 30000, 90000]),
            federal_withholding=rng.choice([0, 4000]),
            self_employment_net=rng.choice([0, 12000]),
        )
    return IncomeSnapshot(**fields)


def _random_deps(rng: random.Random, year: int) -> list[Dependent]:
    deps = []
    for i in range(rng.choice([0, 0, 1, 2])):
        deps.append(
            Dependent(
                name=f"Dep{i}",
                dob=date(rng.choice([year - 3, year - 10, year - 20]), 6, 1),
                has_ssn=rng.choice([True, False]),
                relationship="child",
                provenance=US,
            )
        )
    return deps


def _cases(seed: int, n: int):
    rng = random.Random(seed)
    for _ in range(n):
        year = rng.choice([2021, 2023, 2023, 2024, 2025, 2026])
        deps = _random_deps(rng, year)
        confirmed = rng.random() < 0.6
        if confirmed:
            status = rng.choice(["single", "married_filing_jointly", "head_of_household"])
            marital = "married" if status == "married_filing_jointly" else "unmarried"
            profile = _profile(status, marital, deps)
            with_spouse = status == "married_filing_jointly" and rng.random() < 0.5
        else:
            # Unconfirmed married -> MFJ + MFS candidates -> a comparison with delta_lines.
            profile = _profile(None, "married", deps)
            with_spouse = rng.random() < 0.5
        yield year, profile, _random_snapshot(rng, with_spouse=with_spouse)


def test_every_ledger_reconciles_across_the_generated_input_space():
    # The runtime _reconcile check raises on any non-reconciling ledger, so simply
    # DRIVING these cases is the assertion; the explicit re-check below guards the
    # public surface independently of the internal one.
    ran = 0
    for year, profile, income in _cases(seed=20260807, n=120):
        est = estimate_refund(profile, year, income)
        assert sum(line.effect for line in est.composition) == est.point
        for line in est.composition:
            assert line.slot in _LEDGER_SLOTS, f"unregistered slot {line.slot!r} ({line.label!r})"
            if line.role != "operand":
                assert line.effect == 0, f"non-operand {line.slot!r} carries effect {line.effect}"
        assert est.composition[-1].slot == "bottom_line"
        assert est.composition[-1].amount == est.point
        ran += 1
    assert ran == 120


def test_every_comparison_attributes_its_delta_exactly():
    saw_delta_lines = 0
    for year, profile, income in _cases(seed=20260808, n=120):
        est = estimate_refund(profile, year, income)
        if est.comparison is None:
            continue
        best = max(c.bottom_line for c in est.comparison.candidates)
        worst = min(c.bottom_line for c in est.comparison.candidates)
        assert est.comparison.delta == best - worst
        assert sum(dl.delta for dl in est.comparison.delta_lines) == est.comparison.delta
        for dl in est.comparison.delta_lines:
            assert dl.slot in _LEDGER_SLOTS
            assert dl.delta == dl.best_effect - dl.worst_effect != 0
        if est.comparison.delta_lines:
            saw_delta_lines += 1
            # Largest-first ordering: the first row is the headline explanation.
            magnitudes = [abs(dl.delta) for dl in est.comparison.delta_lines]
            assert magnitudes == sorted(magnitudes, reverse=True)
    assert saw_delta_lines >= 10, "the generator must exercise real comparisons"


def test_the_true_two_return_mfs_ledger_reconciles():
    # The spouse-split MFS path folds the spouse's whole return into one operand
    # row (the single effect = +amount exception); its ledger must reconcile too,
    # and the comparison built on it must attribute the MFJ-vs-MFS delta exactly.
    income = IncomeSnapshot(
        wages=95000,
        federal_withholding=14000,
        spouse=IncomeSnapshot(wages=28000, federal_withholding=2500),
    )
    est = estimate_refund(_profile(None, "married", []), 2023, income)
    assert est.comparison is not None
    mfs_lines = None
    if est.filing_status_used == "married_filing_separately":
        mfs_lines = est.composition
    if mfs_lines is not None:
        assert any(line.slot == "spouse_mfs_return" and line.effect == line.amount for line in mfs_lines)
    assert sum(dl.delta for dl in est.comparison.delta_lines) == est.comparison.delta


def test_missing_blocks_is_the_structured_twin_of_the_prose():
    # The 2026 family case from Stage 0: the dropped CTC must appear BOTH as the
    # NOT ESTIMATED assumption (for the human) and as a MissingBlock (for H4/H7).
    kid = Dependent(name="Kid", dob=date(2019, 5, 1), has_ssn=True, relationship="child", provenance=US)
    est = estimate_refund(
        _profile("head_of_household", "unmarried", [kid]),
        2026,
        IncomeSnapshot(wages=60000, federal_withholding=4000),
    )
    blocks = {mb.block: mb for mb in est.missing_blocks}
    assert "credits.child_tax_credit" in blocks
    assert blocks["credits.child_tax_credit"].direction == "understates_refund"
    assert any(a.startswith("NOT ESTIMATED — child tax credit") for a in est.assumptions)

    # A fully-covered year is clean: no missing blocks, no NOT ESTIMATED prose.
    est25 = estimate_refund(
        _profile("head_of_household", "unmarried", [kid]),
        2025,
        IncomeSnapshot(wages=60000, federal_withholding=4000),
    )
    assert est25.missing_blocks == []
    assert not [a for a in est25.assumptions if a.startswith("NOT ESTIMATED")]


def test_the_runtime_invariants_actually_bite():
    # A guard that cannot fail is a comment. Feed _reconcile the exact failure
    # modes it exists for and assert each raises with the prescriptive message.
    import pytest

    from taxfill_core.estimate import CompositionLine, _line, _reconcile

    # (1) an operand added without its effect (the classic: a new tax line whose
    #     author forgot the ledger) -> the sum no longer reaches the bottom.
    good = [_line("withholding", label="Less: federal tax withheld / payments", amount=-5000)]
    bad = [*good, CompositionLine(label="Plus: some new tax", amount=700, slot="niit", role="operand", effect=0)]
    with pytest.raises(RuntimeError, match="does not reconcile"):
        _reconcile(5000 - 700, bad)

    # (2) a line built around _line() with an unregistered slot.
    with pytest.raises(RuntimeError, match="not in _LEDGER_SLOTS"):
        _line("brand_new_slot", label="x", amount=1)

    # (3) a narrative slot smuggling a nonzero effect.
    with pytest.raises(RuntimeError, match="must be 0"):
        _line("agi", label="Adjusted gross income (AGI)", amount=50000, effect=1)

    # (4) an unslotted line reaching the reconciler.
    with pytest.raises(RuntimeError, match="without a registered slot"):
        _reconcile(0, [CompositionLine(label="legacy", amount=0)])

    # And the healthy path stays healthy.
    _reconcile(5000, good)
