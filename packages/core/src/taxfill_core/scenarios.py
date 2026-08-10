"""Scenario comparison — Phase H item H7 (field notes N-9, N-15).

Planning questions arrive as "compare A vs B vs C" (unmarried / married-MFS /
married + §6013(g) election), and until this module the engine had every
primitive and no way to run and diff a set — the one real planning session
rebuilt the comparison table by hand in a scratch script, and re-derived it
from scratch each of the four times an input fact changed.

Design commitments:

* **Deterministic scenarios.** Every scenario names its filing status
  explicitly; the estimator's candidate-status selection never guesses inside
  a comparison (a confirmed status wins unconditionally in
  ``_candidate_statuses``, which is what makes forcing MFJ for an election
  scenario possible on an otherwise-NRA profile).
* **Two attributions, both EXACT.** The ledger diff itemizes per-slot effect
  differences and must sum to the headline delta (the Stage-2 spine
  invariant). The sequential attribution walks from the baseline to the
  scenario ONE INPUT CHANGE at a time, computing a real bottom line after
  each step — the steps telescope, so they too sum exactly, and they answer
  the question the ledger cannot: an above-the-line change (a deduction, a
  new income item) shows up in the ledger only inside the income-tax slot,
  while the sequential steps name the INPUT that moved the number.
  Attribution order dependence is inherent and disclosed, never hidden.
* **Honest across years.** A scenario on a provisional year is labeled
  PROJECTION and carries its missing_blocks — and the comparison SAYS when
  one side of a diff omits blocks the other side computes, because a silent
  cross-year comparison was exactly the $2,126 trap the estimator disclosure
  work closed.

Persistence lives in :mod:`taxfill_core.workspace` (a scenario set is saved
under the year's workspace and re-run with revised facts — N-15's actual
interaction); this module is pure computation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.estimate import (
    DeltaLine,
    IncomeSnapshot,
    MissingBlock,
    RefundEstimate,
    _slot_effects,
    estimate_refund,
)
from taxfill_core.schemas.profile import Answer, Household, Profile, Provenance

__all__ = ["ScenarioSpec", "ScenarioOutcome", "AttributionStep", "ScenarioDelta", "ScenarioComparison", "compare_scenarios"]

_VALID_STATUSES = (
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
    "qualifying_surviving_spouse",
)

# Marital fact consistent with each forced status, so the hypothetical profile
# never contradicts itself. QSS maps to widowed; the confirmed status bypasses
# the QSS death-year-window candidate gate by design (scenarios are what-ifs).
_MARITAL_FOR_STATUS = {
    "single": "unmarried",
    "head_of_household": "unmarried",
    "married_filing_jointly": "married",
    "married_filing_separately": "married",
    "qualifying_surviving_spouse": "widowed",
}


class ScenarioSpec(BaseModel):
    """One what-if: a filing posture plus the input facts that differ from the base."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Unique label, e.g. 'stay single', 'marry + §6013(g)'.")
    filing_status: str = Field(description="REQUIRED — scenarios are deterministic, never candidate-selected.")
    year: int | None = Field(default=None, description="Override the set's year (cross-year what-ifs).")
    us_resident_election: bool = Field(
        default=False,
        description=(
            "Model a §6013(g)/(h) election: the profile is treated as resident so MFJ is available. "
            "The election makes WORLDWIDE income taxable — include the spouse's foreign income in "
            "income_overrides yourself — and it does NOT start FICA on an exempt spouse's wages "
            "(both auto-disclosed)."
        ),
    )
    income_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "IncomeSnapshot fields that DIFFER from the base income, e.g. {'wages': 120000, "
            "'spouse': {'wages': 60000}}. A 'spouse' entry replaces the whole spouse snapshot. "
            "Sequential attribution applies these one at a time IN THIS ORDER."
        ),
    )
    note: str = Field(default="", description="Why this scenario exists — carried into the outcome.")


class ScenarioOutcome(BaseModel):
    """One scenario's computed bottom line, with the honesty markers it ran under."""

    model_config = ConfigDict(extra="forbid")

    name: str
    bottom_line: int = Field(description="Signed (+ refund, - owed).")
    label: str = Field(description="ESTIMATE (filing-grade year) or PROJECTION (provisional pack).")
    filing_status: str
    year: int
    missing_blocks: list[MissingBlock] = Field(
        description="Blocks this scenario's year could not price — a cross-year diff must weigh these."
    )
    note: str


class AttributionStep(BaseModel):
    """One telescoping step of the input-level attribution."""

    model_config = ConfigDict(extra="forbid")

    changed: str = Field(description="The single input changed, e.g. \"filing_status: single -> married_filing_jointly\".")
    bottom_before: int
    bottom_after: int
    delta: int = Field(description="after - before; the steps sum EXACTLY to the scenario's headline delta.")


class ScenarioDelta(BaseModel):
    """One scenario diffed against the baseline, attributed two ways — both exact."""

    model_config = ConfigDict(extra="forbid")

    name: str
    delta: int = Field(description="scenario bottom line - baseline bottom line (signed).")
    ledger_deltas: list[DeltaLine] = Field(
        description="Per-slot effect differences (scenario minus baseline), largest first; sum == delta."
    )
    input_attribution: list[AttributionStep] = Field(
        description=(
            "The walk from baseline to scenario one input at a time; steps telescope to exactly "
            "`delta`. Order follows the spec (status first, then each override) and the attribution "
            "is order-DEPENDENT by nature — a different order splits the same total differently."
        ),
    )


class ScenarioComparison(BaseModel):
    """The full comparison: every outcome, every delta, and the caveats that gate them."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="PROJECTION when ANY scenario ran on a provisional pack, else ESTIMATE.")
    year: int = Field(description="The set's base year (individual scenarios may override).")
    baseline: str
    outcomes: list[ScenarioOutcome]
    deltas: list[ScenarioDelta] = Field(description="One per non-baseline scenario, in spec order.")
    recommended: str = Field(description="The scenario with the highest signed bottom line.")
    assumptions: list[str]
    work: str


def _scenario_profile(base: Profile, spec: ScenarioSpec) -> Profile:
    """A hypothetical profile forcing the spec's filing posture (never persisted)."""
    prov = Provenance.user_stated()
    prof = base.model_copy(deep=True)
    hh = prof.household.model_copy(deep=True) if prof.household is not None else Household()
    hh.filing_status = Answer(value=spec.filing_status, provenance=prov)
    hh.marital_status = Answer(value=_MARITAL_FOR_STATUS[spec.filing_status], provenance=prov)
    prof.household = hh
    if spec.us_resident_election:
        ident = prof.identity.model_copy(deep=True) if prof.identity is not None else None
        if ident is None:
            from taxfill_core.schemas.profile import Identity

            ident = Identity()
        ident.us_person = Answer(value=True, provenance=prov)
        prof.identity = ident
    return prof


def _apply_overrides(base_income: IncomeSnapshot, overrides: dict[str, Any]) -> IncomeSnapshot:
    unknown = sorted(k for k in overrides if k not in IncomeSnapshot.model_fields)
    if unknown:
        raise ValueError(
            f"unknown income_overrides key(s) {unknown} — valid IncomeSnapshot fields: "
            f"{sorted(IncomeSnapshot.model_fields)}"
        )
    # Re-VALIDATE rather than model_copy(update=...): update= assigns raw values
    # without coercion, so a {'spouse': {...}} override would smuggle a bare dict
    # where the engine expects an IncomeSnapshot.
    return IncomeSnapshot.model_validate({**base_income.model_dump(), **overrides})


def _run(
    base_profile: Profile,
    base_income: IncomeSnapshot,
    spec: ScenarioSpec,
    set_year: int,
    knowledge_dir,
    *,
    overrides_upto: int | None = None,
) -> RefundEstimate:
    """Run one scenario (optionally with only the first N overrides applied — the
    telescoping walk's intermediate configurations)."""
    keys = list(spec.income_overrides)
    if overrides_upto is not None:
        keys = keys[:overrides_upto]
    income = _apply_overrides(base_income, {k: spec.income_overrides[k] for k in keys})
    return estimate_refund(
        _scenario_profile(base_profile, spec),
        spec.year or set_year,
        income,
        knowledge_dir=knowledge_dir,
    )


def _ledger_deltas(scenario: RefundEstimate, baseline: RefundEstimate) -> list[DeltaLine]:
    """Signed per-slot diff (scenario minus baseline); sums exactly by the spine invariant."""
    s_fx, s_lbl = _slot_effects(scenario.composition)
    b_fx, b_lbl = _slot_effects(baseline.composition)
    rows = []
    for slot in s_fx.keys() | b_fx.keys():
        s, b = s_fx.get(slot, 0), b_fx.get(slot, 0)
        if s == b:
            continue
        rows.append(DeltaLine(
            slot=slot,
            label=s_lbl.get(slot) or b_lbl.get(slot) or slot,
            best_effect=s,
            worst_effect=b,
            delta=s - b,
        ))
    rows.sort(key=lambda r: (-abs(r.delta), r.slot))
    residue = (scenario.point - baseline.point) - sum(r.delta for r in rows)
    if residue != 0:
        raise RuntimeError(
            f"scenario ledger diff does not reconcile (residue {residue}) — a ledger stopped "
            f"reconciling; fix the emitting site, never this check."
        )
    return rows


def compare_scenarios(
    profile: Profile,
    year: int,
    income: IncomeSnapshot,
    scenarios: list[ScenarioSpec] | list[dict],
    knowledge_dir=None,
) -> ScenarioComparison:
    """Run every scenario and diff each against the FIRST (the baseline), with
    two exact attributions per diff (see the module docstring).

    ``scenarios[0]`` is the baseline — typically the "change nothing" posture.
    A revision of any base fact means calling this again; the workspace stores
    the set so the re-run is one call, not a rebuild (N-15).
    """
    specs = [s if isinstance(s, ScenarioSpec) else ScenarioSpec.model_validate(s) for s in scenarios]
    if len(specs) < 2:
        raise ValueError(
            "compare_scenarios needs at least 2 scenarios — the first is the baseline the others "
            "are diffed against (e.g. [{'name': 'stay single', 'filing_status': 'single'}, "
            "{'name': 'marry + election', 'filing_status': 'married_filing_jointly', "
            "'us_resident_election': true, 'income_overrides': {...}}])"
        )
    names = [s.name for s in specs]
    if len(set(names)) != len(names):
        raise ValueError(f"scenario names must be unique, got {names}")
    for s in specs:
        if s.filing_status not in _VALID_STATUSES:
            raise ValueError(
                f"scenario {s.name!r}: unknown filing_status {s.filing_status!r} — use one of: "
                f"{', '.join(_VALID_STATUSES)}"
            )

    results = {s.name: _run(profile, income, s, year, knowledge_dir) for s in specs}
    baseline_spec, baseline = specs[0], results[specs[0].name]

    outcomes = [
        ScenarioOutcome(
            name=s.name,
            bottom_line=results[s.name].point,
            label=results[s.name].label,
            filing_status=s.filing_status,
            year=s.year or year,
            missing_blocks=results[s.name].missing_blocks,
            note=s.note,
        )
        for s in specs
    ]

    deltas: list[ScenarioDelta] = []
    for s in specs[1:]:
        res = results[s.name]
        # The telescoping walk: baseline config -> (year) -> (election) -> (status)
        # -> each income override in order. Every intermediate is a REAL computed
        # bottom line, so the steps sum exactly by construction — still re-checked.
        steps: list[AttributionStep] = []
        current = baseline.point

        def _step(changed: str, est: RefundEstimate) -> None:
            nonlocal current
            steps.append(AttributionStep(
                changed=changed, bottom_before=current, bottom_after=est.point, delta=est.point - current
            ))
            current = est.point

        walk = ScenarioSpec(
            name=s.name, filing_status=baseline_spec.filing_status,
            year=baseline_spec.year, us_resident_election=baseline_spec.us_resident_election,
            income_overrides={},
        )
        if (s.year or year) != (baseline_spec.year or year):
            walk = walk.model_copy(update={"year": s.year})
            _step(f"year: {baseline_spec.year or year} -> {s.year or year}",
                  _run(profile, income, walk, year, knowledge_dir))
        if s.us_resident_election != baseline_spec.us_resident_election:
            walk = walk.model_copy(update={"us_resident_election": s.us_resident_election})
            _step(f"us_resident_election: {baseline_spec.us_resident_election} -> {s.us_resident_election}",
                  _run(profile, income, walk, year, knowledge_dir))
        if s.filing_status != baseline_spec.filing_status:
            walk = walk.model_copy(update={"filing_status": s.filing_status})
            _step(f"filing_status: {baseline_spec.filing_status} -> {s.filing_status}",
                  _run(profile, income, walk, year, knowledge_dir))
        for i, key in enumerate(s.income_overrides, start=1):
            walk = walk.model_copy(update={"income_overrides": dict(list(s.income_overrides.items())[:i])})
            base_val = getattr(income, key, None)
            _step(f"income.{key}: {base_val!r} -> {s.income_overrides[key]!r}",
                  _run(profile, income, walk, year, knowledge_dir))

        if current != res.point:
            raise RuntimeError(
                f"scenario {s.name!r}: the attribution walk ended at {current} but the scenario "
                f"computes {res.point} — the walk did not reproduce the scenario's configuration; "
                f"fix _run/the walk order, never this check."
            )
        deltas.append(ScenarioDelta(
            name=s.name,
            delta=res.point - baseline.point,
            ledger_deltas=_ledger_deltas(res, baseline),
            input_attribution=steps,
        ))

    label = "PROJECTION" if any(r.label == "PROJECTION" for r in results.values()) else "ESTIMATE"
    recommended = max(outcomes, key=lambda o: o.bottom_line).name

    assumptions: list[str] = [
        "Scenarios are HYPOTHETICALS run under forced filing postures — nothing here is recorded on "
        "the profile; the workspace stores the scenario set itself so a revised fact is one re-run, "
        "not a rebuild.",
        "Input attribution is order-dependent by nature: the steps telescope exactly, and a different "
        "step order would split the same total differently.",
    ]
    if any(s.us_resident_election for s in specs):
        assumptions.append(
            "A §6013(g)/(h) election makes the couple's WORLDWIDE income taxable — the election "
            "scenario is only as complete as the income you gave it (include the spouse's foreign "
            "income) — and the election does NOT start FICA on an exempt F/J spouse's wages: the FICA "
            "exemption is STATUS-based, not marital (calc op employee_fica models the segments)."
        )
    cross_year = {o.year for o in outcomes}
    if len(cross_year) > 1:
        assumptions.append(
            f"Scenarios span multiple years ({sorted(cross_year)}): compare their missing_blocks — a "
            f"planning year prices absent blocks at $0, which can skew a cross-year delta by exactly "
            f"the missing item."
        )
    for o in outcomes:
        if o.missing_blocks:
            assumptions.append(
                f"Scenario {o.name!r} ({o.year}) could NOT price: "
                + "; ".join(f"{mb.item} ({mb.direction})" for mb in o.missing_blocks)
            )

    lines = [f"Scenario comparison ({label}), baseline {baseline_spec.name!r}:"]
    for o in outcomes:
        lines.append(f"* {o.name}: {'+' if o.bottom_line >= 0 else ''}{o.bottom_line:,} ({o.filing_status}, {o.year})")
    for d in deltas:
        lines.append(f"Δ {d.name} vs baseline: {'+' if d.delta >= 0 else ''}{d.delta:,}")
        for st in d.input_attribution:
            lines.append(f"    {st.changed}: {'+' if st.delta >= 0 else ''}{st.delta:,}")
        top = d.ledger_deltas[:4]
        if top:
            lines.append("    ledger view: " + "; ".join(f"{r.slot} {'+' if r.delta >= 0 else ''}{r.delta:,}" for r in top))
    lines.append(f"Recommended (highest bottom line): {recommended}")

    return ScenarioComparison(
        label=label,
        year=year,
        baseline=baseline_spec.name,
        outcomes=outcomes,
        deltas=deltas,
        recommended=recommended,
        assumptions=assumptions,
        work="\n".join(lines),
    )
