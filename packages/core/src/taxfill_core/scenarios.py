"""Scenario comparison — Phase H item H7 (field notes N-9, N-15).

Planning questions arrive as "compare A vs B vs C" (unmarried / married-MFS /
married + §6013(g) election), and until this module the engine had every
primitive and no way to run and diff a set — without it a caller rebuilds the
comparison table by hand and re-derives it every time an input fact changes.

Design commitments:

* **Deterministic scenarios.** Every scenario names its filing status
  explicitly; the estimator's candidate-status selection never guesses inside
  a comparison (a confirmed status wins unconditionally in
  ``_candidate_statuses``, which is what makes forcing MFJ for an election
  scenario possible on an otherwise-NRA profile).
* **The election is a residency fact, not a status.** ``us_resident_election``
  sets ``residency_facts.section_6013_election`` on the scenario's profile
  (P-018), which the estimator applies BEFORE any rule runs — so the elected
  figure takes resident rules even on a profile whose visa timeline and day
  counts classify the filer nonresident. Rewriting ``identity.us_person``
  instead (the pre-JF5a shape) reached the classifier only on timeline-free
  profiles. Omitted (None) it FOLLOWS the profile — the recorded fact (a
  continuing election is never silently revoked) or the estimator's joint-
  status reading — and True/False override it for that scenario, which the
  comparison says. Every scenario that ran under the election is named with
  its residency caveat, and the input walk ends on each scenario's own
  configuration, booking a change of the election's reading to the step
  where it happens. Never recommended, because not a filing option: a JOINT
  scenario seeking an election its recorded facts rule out (both spouses
  nonresident — a separate one, priced without it, is the couple's actual
  returns and stays an option), a joint scenario with the election declined
  for a couple with a nonresident in it (priced as the separate returns), a
  separate figure under a definite 6013(h) choice, and head of household for
  a nonresident-alien taxpayer (Pub 519 ch. 5).
* **Two attributions, both EXACT.** The ledger diff itemizes per-slot effect
  differences and must sum to the headline delta (the Stage-2 spine
  invariant). The sequential attribution walks from the baseline to the
  scenario ONE INPUT CHANGE at a time (a subset and its parent move together,
  so no intermediate snapshot is invalid), computing a real bottom line after
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
    INCOME_LINKED_FIELDS,
    DeltaLine,
    IncomeSnapshot,
    MissingBlock,
    RefundEstimate,
    _slot_effects,
    estimate_refund,
)
from taxfill_core.estimate import _election_state
from taxfill_core.residency import SECTION_6013_NO_JOINT, section_6013_effect_quote, section_6013_texts
from taxfill_core.schemas.profile import Answer, Household, Profile, Provenance, ResidencyFacts

__all__ = ["ScenarioSpec", "ScenarioOutcome", "AttributionStep", "ScenarioDelta", "ScenarioComparison", "compare_scenarios"]

# Pub 519 (2025) ch. 1, Ending the Choice (read 2026-09-26): revoking a continuing election
# is final (P-018).
_ENDING_THE_CHOICE = (
    "Pub 519 ch. 1 (Ending the Choice): \"If the choice is ended in one of the following ways, neither spouse can "
    "make this choice in any later tax year.\""
)

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
    us_resident_election: bool | None = Field(
        default=None,
        description=(
            "Model a §6013(g)/(h) election (P-018). Omitted (null, the default): FOLLOW the profile — its "
            "recorded residency_facts.section_6013_election (a continuing election stays in effect, a recorded "
            "decline stays declined), or else the estimator's reading of a married_filing_jointly status of a "
            "nonresident AS the election (a joint return with a nonresident alien exists only under it). true: "
            "set it, so both spouses are 'treated for income tax purposes as residents for your entire tax year' "
            "(Pub 519 ch. 1) whatever the visa timeline says — resident rules on MFJ AND on MFS (the standard "
            "deduction, NIIT evaluated under the Treas. Reg. 1.1411-2(a)(2)(iii)/(iv) default unless the second "
            "election applies, no 871(i)(2)(A) deposit-interest exclusion); an MFS figure under it is a "
            "LATER year of a continuing 6013(g) election, because the year a choice is made — 6013(g) or 6013(h) — "
            "is joint. false: model NOT electing (declined; for a continuing election, revoked) — it pairs with "
            "married_filing_separately (or head of household for a citizen or resident spouse): false on "
            "married_filing_jointly for a couple with a nonresident in it is NOT a filing option (Pub 519 FAQ: "
            "\"Generally, you cannot file as married filing jointly if either spouse was a nonresident alien at "
            "any time during the tax year\"), priced as married-filing-separately and never recommended. A value "
            "that differs from the recorded fact is named in the assumptions. The election applies only to a "
            "married status, and never when the recorded facts show neither spouse a U.S. citizen or resident "
            "(IRC 6013(g)(3): priced without it — a joint scenario is then never recommended, a separate one is the "
            "couple's actual returns). It makes WORLDWIDE income taxable — include "
            "the spouse's foreign income in income_overrides yourself — and it does NOT start FICA on an exempt "
            "spouse's wages (both auto-disclosed)."
        ),
    )
    income_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "IncomeSnapshot fields that DIFFER from the base income, e.g. {'wages': 96000, "
            "'spouse': {'wages': 52000}}. A 'spouse' entry replaces the whole spouse snapshot. "
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
    section_6013_election: bool = Field(
        default=False,
        description=(
            "True when this scenario's figure ran under the §6013(g)/(h) election — flagged, recorded on the "
            "profile, or read from a confirmed joint status of a nonresident (P-018)."
        ),
    )
    residency_caveat: str | None = Field(
        default=None,
        description=(
            "The scenario estimate's residency caveat (the election's effect, statement, precondition, FICA "
            "and worldwide-income text, or the dual-status / nonresident-spouse caveat), or None."
        ),
    )


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
            "is order-DEPENDENT by nature — a different order splits the same total differently. "
            "Overridden fields the snapshot checks against each other (a subset and its parent, "
            "dependent-care expenses and persons: estimate.INCOME_LINKED_FIELDS) are one step."
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
    recommended: str | None = Field(
        description=(
            "The scenario with the highest signed bottom line among the FILING OPTIONS (P-018): a JOINT "
            "scenario seeking a §6013(g)/(h) election its recorded facts rule out, a married-filing-jointly "
            "scenario with the election declined for a couple with a nonresident in it, a separate figure under "
            "a definite 6013(h) choice, and head of household for a nonresident-alien taxpayer (Pub 519 ch. 5) "
            "are excluded. None when no scenario is a filing option."
        )
    )
    assumptions: list[str]
    work: str


def _scenario_profile(base: Profile, spec: ScenarioSpec) -> Profile:
    """A hypothetical profile forcing the spec's filing posture (never persisted).

    The §6013(g)/(h) election is set as the residency FACT it is —
    ``residency_facts.section_6013_election`` (P-018). Until JF5a the scenario
    flipped ``identity.us_person`` instead, which the estimator ignores whenever a
    visa timeline and day counts classify the filer, so the "election" figure kept
    the nonresident rules (no standard deduction, no NIIT). us_person is a
    citizenship / green-card fact and is never rewritten here.
    """
    prov = Provenance.user_stated()
    prof = base.model_copy(deep=True)
    hh = prof.household.model_copy(deep=True) if prof.household is not None else Household()
    hh.filing_status = Answer(value=spec.filing_status, provenance=prov)
    # A married household's head-of-household figure stays MARRIED: a married filer reaches
    # head of household only as "considered unmarried" (Pub 501), and the spouse still files
    # their own return — so the scenario prices both returns, as estimate_refund does,
    # instead of silently dropping the spouse's.
    keep_married = (
        spec.filing_status == "head_of_household"
        and base.household is not None
        and base.household.marital_status is not None
        and base.household.marital_status.value == "married"
    )
    if not keep_married:
        hh.marital_status = Answer(value=_MARITAL_FOR_STATUS[spec.filing_status], provenance=prov)
    prof.household = hh
    if spec.us_resident_election is not None:
        rf = prof.residency_facts.model_copy(deep=True) if prof.residency_facts is not None else ResidencyFacts()
        rf.section_6013_election = Answer(value=spec.us_resident_election, provenance=prov)
        prof.residency_facts = rf
    return prof


def _recorded_election(profile: Profile) -> bool | None:
    """The profile's recorded residency_facts.section_6013_election value, or None."""
    rf = profile.residency_facts
    return rf.section_6013_election.value if rf is not None and rf.section_6013_election is not None else None


def _effective_election(profile: Profile, spec: ScenarioSpec) -> bool:
    """Whether the spec runs WITH a recorded-or-flagged election (the implied joint reading aside)."""
    value = spec.us_resident_election if spec.us_resident_election is not None else _recorded_election(profile)
    return value is True


def _flag(value: bool | None) -> str:
    """A scenario's us_resident_election flag as the walk labels it."""
    return "omitted" if value is None else str(value).lower()


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


def _override_steps(overrides: dict[str, Any]) -> list[list[str]]:
    """The walk's override steps, in the scenario's key order: a key alone, or — for the
    fields the snapshot validator checks against each other (estimate.INCOME_LINKED_FIELDS:
    a subset and its parent, dependent-care expenses and persons) — every overridden member of
    its group together, at the first member's position (JF1b.6). One member alone could leave
    the intermediate snapshot invalid (interest cut below the base's bank_deposit_interest),
    so the pair moves as one step whichever order the keys were given in."""
    steps: list[list[str]] = []
    placed: set[str] = set()
    for key in overrides:
        if key in placed:
            continue
        group = next((g for g in INCOME_LINKED_FIELDS if key in g), frozenset({key}))
        members = [k for k in overrides if k in group]
        steps.append(members)
        placed.update(members)
    return steps


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
    # How the §6013(g)/(h) election stands in each scenario (P-018) — the estimator's own
    # reading, so the comparison names exactly what each figure ran under.
    elections = {s.name: _election_state(_scenario_profile(profile, s), s.year or year) for s in specs}
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
            section_6013_election=elections[s.name].election,
            residency_caveat=results[s.name].residency_caveat,
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
        def _reading(spec: ScenarioSpec) -> bool:
            return _election_state(_scenario_profile(profile, spec), spec.year or year).election

        def _with_reading(before: bool, after: bool) -> str:
            return f" (with it, the us_resident_election reading: {before} -> {after})" if after != before else ""

        reading = elections[baseline_spec.name].election
        if (s.year or year) != (baseline_spec.year or year):
            walk = walk.model_copy(update={"year": s.year})
            after = _reading(walk)
            _step(f"year: {baseline_spec.year or year} -> {s.year or year}{_with_reading(reading, after)}",
                  _run(profile, income, walk, year, knowledge_dir))
            reading = after
        # The election stage, at the baseline status (P-018). The walk carries the scenario's
        # OWN flag, so it always ends on the scenario's exact configuration; an omitted flag
        # whose scenario runs UNDER the election (recorded or read from a joint status) is
        # carried as an explicit true, so the residency switch is its own step and not booked
        # to the filing status, and restored after the status step. An omitted flag never
        # becomes a new explicit false (that would be a recorded decline, a different fact).
        scenario_elected = elections[s.name].election
        target_flag = s.us_resident_election
        if target_flag is None:
            # Never a NEW explicit false; a baseline's own false is kept while the scenario does
            # not run under the election, and restored to omitted at the scenario's status.
            target_flag = True if scenario_elected else (False if walk.us_resident_election is False else None)
        if target_flag != walk.us_resident_election:
            prev_flag = walk.us_resident_election
            walk = walk.model_copy(update={"us_resident_election": target_flag})
            est = _run(profile, income, walk, year, knowledge_dir)
            after = _reading(walk)
            if after != reading:
                how = (
                    f" (the scenario's election is read from its joint status; priced here at "
                    f"{baseline_spec.filing_status})"
                    if elections[s.name].implied else ""
                )
                _step(f"us_resident_election: {reading} -> {after}{how}", est)
            elif est.point != current:
                _step(f"us_resident_election flag: {_flag(prev_flag)} -> {_flag(target_flag)}", est)
            reading = after
        if s.filing_status != baseline_spec.filing_status:
            walk = walk.model_copy(update={"filing_status": s.filing_status})
            after = _reading(walk)
            # The election's reading can change WITH the status (it needs a married status, and an
            # implied election is read only from a joint one) — the step says so.
            _step(f"filing_status: {baseline_spec.filing_status} -> {s.filing_status}{_with_reading(reading, after)}",
                  _run(profile, income, walk, year, knowledge_dir))
            reading = after
        if walk.us_resident_election != s.us_resident_election:
            prev_flag = walk.us_resident_election
            walk = walk.model_copy(update={"us_resident_election": s.us_resident_election})
            est = _run(profile, income, walk, year, knowledge_dir)
            after = _reading(walk)
            if est.point != current or after != reading:
                _step(f"us_resident_election flag: {_flag(prev_flag)} -> {_flag(s.us_resident_election)} "
                      f"(as specified){_with_reading(reading, after)}", est)
            reading = after
        applied: list[str] = []
        for members in _override_steps(s.income_overrides):
            # A linked group (a subset and its parent, ...) is ONE step, so no intermediate
            # snapshot fails the validator (JF1b.6); the label names every member.
            applied.extend(members)
            walk = walk.model_copy(update={"income_overrides": {k: s.income_overrides[k] for k in applied}})
            label = "; ".join(
                f"income.{key}: {getattr(income, key, None)!r} -> {s.income_overrides[key]!r}" for key in members
            )
            if len(members) > 1:
                label += " (applied together: the snapshot checks these fields against each other)"
            _step(label, _run(profile, income, walk, year, knowledge_dir))

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
    # Not a filing option (P-018), so never the recommendation: a JOINT scenario that sought
    # the election its recorded facts rule out (neither spouse a U.S. citizen or resident), a
    # joint status those facts rule out (a declined election with a nonresident in the
    # couple — priced by the estimator as married-filing-separately), a separate figure
    # under a DEFINITE 6013(h) choice (the year of the choice must be joint), and head of
    # household for a nonresident-alien taxpayer.
    blocked = [s.name for s in specs if elections[s.name].joint_blocked and not elections[s.name].precondition_unmet]
    unavailable = [s.name for s in specs if elections[s.name].precondition_unmet]
    # Only a JOINT scenario seeking an unavailable election is not a filing option: a
    # separate one, priced without it, is exactly the returns the couple files (Pub 519
    # ch. 1, Suspending the Choice: "each spouse must file a separate return as a
    # nonresident alien for that year if either meets the filing requirements ...").
    status_of = {s.name: s.filing_status for s in specs}
    unavailable_joint = [n for n in unavailable if status_of[n] == "married_filing_jointly"]
    h_separate = [
        s.name for s in specs
        if elections[s.name].election and elections[s.name].kind == "h" and s.filing_status == "married_filing_separately"
    ]
    # Pub 519 ch. 5: "You cannot file as head of household if you are a nonresident alien at
    # any time during the tax year" — a head-of-household scenario of a taxpayer the estimator
    # prices as a nonresident (or dual-status) is not a filing option; the same classification
    # the estimate's own caveat keys on, so the two never disagree.
    nra_hoh = [
        s.name for s in specs
        if s.filing_status == "head_of_household" and not elections[s.name].election
        and elections[s.name].own_classification in ("nonresident", "dual_status_candidate")
    ]
    excluded = set(blocked) | set(unavailable_joint) | set(h_separate) | set(nra_hoh)
    options = [o for o in outcomes if o.name not in excluded]
    recommended = max(options, key=lambda o: o.bottom_line).name if options else None

    assumptions: list[str] = [
        "Scenarios are HYPOTHETICALS run under forced filing postures — nothing here is recorded on "
        "the profile; the workspace stores the scenario set itself so a revised fact is one re-run, "
        "not a rebuild.",
        "Input attribution is order-dependent by nature: the steps telescope exactly, and a different "
        "step order would split the same total differently.",
    ]
    recorded = _recorded_election(profile)
    for s in specs:
        if s.name in blocked:
            continue  # its own not-a-filing-option note below says what the flag did
        if s.us_resident_election is not None and recorded is not None and s.us_resident_election != recorded:
            assumptions.append(
                f"Scenario {s.name!r} sets us_resident_election={str(s.us_resident_election).lower()}, OVERRIDING "
                f"the §6013(g)/(h) election recorded on the profile ({str(recorded).lower()}) for that scenario only"
                + (
                    " — false models NOT electing: for an election made in an earlier year that is revoking it, "
                    f"and {_ENDING_THE_CHOICE}"
                    if s.us_resident_election is False
                    else "."
                )
            )
    elected = [s for s in specs if elections[s.name].election]
    if elected:
        def _how(s: ScenarioSpec) -> str:
            if elections[s.name].implied:
                return "read from its confirmed married-filing-jointly status of a nonresident"
            return "flagged" if s.us_resident_election is True else "recorded on the profile"

        kinds = {elections[s.name].kind for s in elected}
        kind = kinds.pop() if len(kinds) == 1 else "either"
        assumptions.append(
            "A §6013(g)/(h) election makes the couple's WORLDWIDE income taxable — the election "
            "scenario is only as complete as the income you gave it (include the spouse's foreign "
            "income) — and the election does NOT start FICA on an exempt F/J spouse's wages: the FICA "
            "exemption is STATUS-based, not marital (calc op employee_fica models the segments). "
            "These scenarios ran under the election, with RESIDENT rules for both spouses (P-018: "
            + section_6013_effect_quote(kind)
            + "): "
            + "; ".join(f"{s.name!r} ({_how(s)})" for s in elected)
            + ". Each one's residency_caveat carries the statement, the precondition and the FICA text. "
            + section_6013_texts(kind)[1]
        )
    for name in nra_hoh:
        assumptions.append(
            f"Scenario {name!r} is head of household for a taxpayer who is a nonresident alien on the visa timeline "
            f"and day counts — NOT a filing option (Pub 519 ch. 5: \"You cannot file as head of household if you "
            f"are a nonresident alien at any time during the tax year.\"), so never the recommended scenario."
        )
    for s in specs:
        if s.name in nra_hoh:
            continue  # its own note above says why no head-of-household figure is a filing option
        if _effective_election(profile, s) and not elections[s.name].election and not elections[s.name].precondition_unmet:
            # Flagged on the spec, or recorded on the profile and followed (flag omitted):
            # either way the comparison says the figure did NOT run under it, and why.
            source = (
                "sets us_resident_election" if s.us_resident_election is True
                else "follows the §6013(g)/(h) election recorded on the profile"
            )
            if s.filing_status == "head_of_household":
                why = (
                    "head of household exists only WITHOUT the election (Pub 501, Considered Unmarried: \"You are "
                    "considered unmarried for head of household purposes if your spouse was a nonresident alien at "
                    "any time during the year and you don't choose to treat your nonresident spouse as a resident "
                    "alien\")"
                    + (
                        f" — with the election recorded on the profile, a head-of-household figure means ending it, "
                        f"and {_ENDING_THE_CHOICE}"
                        if recorded is True else ""
                    )
                )
            else:
                why = (
                    f"its filing status ({s.filing_status}) has no spouse on the return, and the choice needs one "
                    "(Pub 519 ch. 1: \"If, at the end of your tax year, you are married ...\")"
                )
            assumptions.append(f"Scenario {s.name!r} {source}, but the election was NOT applied: {why}.")
    for name in unavailable:
        assumptions.append(
            f"Scenario {name!r} seeks the §6013(g)/(h) election, but on the recorded facts NEITHER spouse is a U.S. "
            f"citizen or resident, so it is NOT available (IRC 6013(g)(3); its residency_caveat quotes why) and the "
            f"figure is priced WITHOUT it"
            + (
                " — a joint return is not a filing option as specified, so never the recommended scenario."
                if name in unavailable_joint else
                " — the separate returns the couple files on these facts, so it stays a filing option."
            )
        )
    for name in blocked:
        reopen = (
            " On these facts the election is not available either (neither spouse is a U.S. citizen or resident — "
            "IRC 6013(g)(3)), so no joint return exists for this couple."
            if elections[name].unavailable else
            " To price a joint return, run it with us_resident_election true."
        )
        assumptions.append(
            f"Scenario {name!r} is married-filing-jointly with the §6013(g)/(h) election declined for a couple with a "
            f"nonresident alien in it — NOT a filing option ({SECTION_6013_NO_JOINT}), so no joint figure is shown: "
            f"its bottom line is the married-filing-separately figure the estimator prices with the decline recorded, "
            f"and it is never the recommended scenario.{reopen}"
        )
    for name in h_separate:
        assumptions.append(
            f"Scenario {name!r} is a separate figure under a 6013(h) choice read from a joint status, and \"You and "
            f"your spouse must file a joint return for the year of the choice\" (Pub 519 ch. 1) — never recommended."
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
        why_not = (
            " — NOT a filing option: priced married_filing_separately, see the assumptions"
            if o.name in blocked or o.name in unavailable_joint else
            " — NOT a filing option: the year of a 6013(h) choice is joint" if o.name in h_separate else
            " — NOT a filing option: a nonresident alien cannot file as head of household" if o.name in nra_hoh
            else ""
        )
        lines.append(
            f"* {o.name}: {'+' if o.bottom_line >= 0 else ''}{o.bottom_line:,} ({o.filing_status}, {o.year}){why_not}"
        )
    for d in deltas:
        lines.append(f"Δ {d.name} vs baseline: {'+' if d.delta >= 0 else ''}{d.delta:,}")
        for st in d.input_attribution:
            lines.append(f"    {st.changed}: {'+' if st.delta >= 0 else ''}{st.delta:,}")
        top = d.ledger_deltas[:4]
        if top:
            lines.append("    ledger view: " + "; ".join(f"{r.slot} {'+' if r.delta >= 0 else ''}{r.delta:,}" for r in top))
    lines.append(
        f"Recommended (highest bottom line{' among the filing options' if excluded else ''}): {recommended}"
        if recommended is not None else
        "Recommended: none — no scenario is a filing option on the recorded facts (see the assumptions)."
    )

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
