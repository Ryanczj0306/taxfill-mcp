"""compare_scenarios golden tests — Phase H item H7 (field notes N-9, N-15).

The canonical use case is a three-way what-if (single / MFS / MFJ via the
§6013(g) election) that must be re-run each time an input fact changes. These
tests pin the two properties that make the surface trustworthy:

  * BOTH attributions are exact — the ledger diff sums to the headline delta
    (spine invariant) AND the sequential input walk telescopes to it (every
    intermediate is a real computed bottom line);
  * the comparison stays honest across years — a provisional-year scenario is
    labeled PROJECTION and its missing blocks are named, because a silent
    cross-year diff was exactly the $2,126 credit-drop trap.

All data synthetic (mechanical demo numbers, not tied to any persona).
Offline.
"""

from __future__ import annotations

from datetime import date

import pytest

from taxfill_core import scenarios as scenarios_module
from taxfill_core.calc import niit, standard_deduction, tax_from_taxable_income
from taxfill_core.estimate import IncomeSnapshot
from taxfill_core.scenarios import ScenarioSpec, compare_scenarios
from taxfill_core.schemas.profile import (
    Answer,
    Household,
    Identity,
    Immigration,
    Profile,
    Provenance,
    ResidencyFacts,
    Spouse,
    VisaPeriod,
)
from taxfill_core.workspace import Workspace

US = Provenance.user_stated()


def _nra_profile() -> Profile:
    return Profile(identity=Identity(us_person=Answer(value=False, provenance=US)))


THREE_WAY = [
    {"name": "stay single", "filing_status": "single"},
    {"name": "marry, file separately", "filing_status": "married_filing_separately"},
    {
        "name": "marry + §6013(g) election",
        "filing_status": "married_filing_jointly",
        "us_resident_election": True,
        "income_overrides": {
            "spouse": {"wages": 52_000, "federal_withholding": 5_000},
            "federal_withholding": 11_500,  # a post-marriage W-4 lowers withholding
        },
    },
]


def test_the_three_way_election_comparison():
    income = IncomeSnapshot(wages=96_000, federal_withholding=13_000)
    r = compare_scenarios(_nra_profile(), 2025, income, THREE_WAY)
    assert r.baseline == "stay single"
    assert [o.name for o in r.outcomes] == [s["name"] for s in THREE_WAY]
    # The election scenario forces MFJ on an otherwise-NRA profile — a confirmed
    # status wins unconditionally, which is what makes the what-if runnable.
    election = next(o for o in r.outcomes if "election" in o.name)
    assert election.filing_status == "married_filing_jointly"
    # The caveats an election scenario must disclose unprompted.
    joined = " ".join(r.assumptions)
    assert "WORLDWIDE" in joined
    assert "does NOT start FICA" in joined  # N-7b, stated unprompted


def test_both_attributions_are_exact_for_every_delta():
    income = IncomeSnapshot(wages=96_000, federal_withholding=13_000)
    r = compare_scenarios(_nra_profile(), 2025, income, THREE_WAY)
    for d in r.deltas:
        assert sum(s.delta for s in d.input_attribution) == d.delta  # telescoping
        assert sum(x.delta for x in d.ledger_deltas) == d.delta      # spine invariant
    # The walk names the inputs, in override order — the ledger alone cannot
    # say "spouse income cost $X"; the walk can.
    election = next(d for d in r.deltas if "election" in d.name)
    changed = [s.changed for s in election.input_attribution]
    # P-018: the election needs a spouse on the return, so from the single baseline it
    # switches on WITH the married status — the status step names it.
    assert any(c.startswith("filing_status") and "us_resident_election reading: False -> True" in c for c in changed)
    assert any(c.startswith("income.spouse") for c in changed)
    assert any(c.startswith("income.federal_withholding") for c in changed)


def test_cross_year_comparison_is_labeled_projection_and_names_the_skew():
    income = IncomeSnapshot(wages=60_000, federal_withholding=4_000)
    r = compare_scenarios(_nra_profile(), 2025, income, [
        {"name": "TY2025", "filing_status": "single"},
        {"name": "TY2026 (planning)", "filing_status": "single", "year": 2026},
    ])
    assert r.label == "PROJECTION"
    assert any("multiple years" in a for a in r.assumptions)
    ty26 = next(o for o in r.outcomes if o.year == 2026)
    assert ty26.label == "PROJECTION"


def test_recommended_is_the_highest_bottom_line():
    income = IncomeSnapshot(wages=96_000, federal_withholding=13_000)
    r = compare_scenarios(_nra_profile(), 2025, income, THREE_WAY)
    best = max(r.outcomes, key=lambda o: o.bottom_line)
    assert r.recommended == best.name


def test_prescriptive_errors():
    income = IncomeSnapshot(wages=50_000)
    with pytest.raises(ValueError, match="at least 2"):
        compare_scenarios(_nra_profile(), 2025, income, [{"name": "only one", "filing_status": "single"}])
    with pytest.raises(ValueError, match="unique"):
        compare_scenarios(_nra_profile(), 2025, income, [
            {"name": "x", "filing_status": "single"}, {"name": "x", "filing_status": "single"},
        ])
    with pytest.raises(ValueError, match="unknown filing_status"):
        compare_scenarios(_nra_profile(), 2025, income, [
            {"name": "a", "filing_status": "single"}, {"name": "b", "filing_status": "married"},
        ])
    with pytest.raises(ValueError, match="income_overrides"):
        compare_scenarios(_nra_profile(), 2025, income, [
            {"name": "a", "filing_status": "single"},
            {"name": "b", "filing_status": "single", "income_overrides": {"wages_total": 1}},
        ])


def test_scenario_specs_validate_from_dicts_and_models_alike():
    income = IncomeSnapshot(wages=50_000, federal_withholding=5_000)
    specs = [
        ScenarioSpec(name="base", filing_status="single"),
        ScenarioSpec(name="hoh", filing_status="head_of_household"),
    ]
    r = compare_scenarios(_nra_profile(), 2025, income, specs)
    assert len(r.deltas) == 1


# ── persistence: the change-one-fact-and-re-diff loop (N-15) ───────────────────


def test_scenario_sets_round_trip_through_the_workspace(tmp_path):
    ws = Workspace.open(tmp_path, 2026, now="2026-03-02 12:00")
    payload = {
        "year": 2026,
        "income": {"wages": 96_000, "federal_withholding": 13_000},
        "scenarios": THREE_WAY,
        "profile": None,
    }
    ws.save_scenario_set("demo-what-if", payload, now="2026-03-02 12:00")
    loaded = ws.load_scenario_set("demo-what-if")
    assert loaded["income"]["wages"] == 96_000
    assert [s["name"] for s in loaded["scenarios"]] == [s["name"] for s in THREE_WAY]
    assert ws.status()["scenario_sets"] == ["demo-what-if"]
    # The set stores INPUTS, never results — results recompute on every load, so
    # a pack correction after saving is picked up silently.
    assert "outcomes" not in loaded and "deltas" not in loaded
    with pytest.raises(ValueError, match="no scenario set named"):
        ws.load_scenario_set("nope")


def test_the_revise_one_fact_loop_via_the_mcp_tool(tmp_path, monkeypatch):
    # A revision of any base fact must be ONE call over the saved set, not a
    # rebuild.
    from taxfill_mcp.server import compare_scenarios as tool

    root = str(tmp_path)
    first = tool(2025, scenarios=THREE_WAY,
                 income={"wages": 96_000, "federal_withholding": 13_000},
                 save_as="demo-what-if", root=root)
    assert first["saved_as"] == "demo-what-if"
    baseline_first = next(o for o in first["outcomes"] if o["name"] == "stay single")

    # A base fact changes (e.g. a raise): update ONE fact and re-run.
    second = tool(2025, load="demo-what-if", income_updates={"wages": 104_000}, root=root)
    baseline_second = next(o for o in second["outcomes"] if o["name"] == "stay single")
    assert baseline_second["bottom_line"] != baseline_first["bottom_line"]
    # Re-saved: the stored base now carries the revision.
    ws = Workspace(root, 2025)
    assert ws.load_scenario_set("demo-what-if")["income"]["wages"] == 104_000
    # Attributions stay exact on the re-run.
    for d in second["deltas"]:
        assert sum(s["delta"] for s in d["input_attribution"]) == d["delta"]
        assert sum(x["delta"] for x in d["ledger_deltas"]) == d["delta"]


# ── P-018 (Phase J JF5a): the election on a TIMELINE-BEARING profile ───────────
# Every test above uses a timeline-free profile, where flipping identity.us_person
# happened to reach the classifier — which is why no test saw the bug: on a profile
# that carries a visa timeline and day counts, the estimator classifies residency
# from THOSE, so the old "election" scenario was a joint return under Form 1040-NR
# rules (itemized-only deduction of $0, no NIIT). Pub 519 (2025) ch. 1: "If you make
# this choice, you and your spouse are treated for income tax purposes as residents
# for your entire tax year." Hypothetical demo fixture: an F-1 student arriving in
# 2022, so 2025 is an exempt year and the SPT fails (nonresident without the election).

_MFS_NR = {"name": "MFS on 1040-NR", "filing_status": "married_filing_separately"}
_ELECT_MFJ = {"name": "MFJ + election", "filing_status": "married_filing_jointly", "us_resident_election": True}
_ELECT_MFS = {"name": "MFS + election (later year)", "filing_status": "married_filing_separately",
              "us_resident_election": True}


def _timeline_nra_profile() -> Profile:
    return Profile(
        identity=Identity(us_person=Answer(value=False, provenance=US)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2022, 8, 20), provenance=US)]),
        residency_facts=ResidencyFacts(
            days_in_us={y: Answer(value=d, provenance=US) for y, d in {2022: 130, 2023: 330, 2024: 330, 2025: 330}.items()}
        ),
    )


def _spy(monkeypatch) -> list:
    """Record every estimate compare_scenarios computes, with the profile it ran on."""
    runs: list = []
    real = scenarios_module.estimate_refund

    def spy(profile, year, income, **kwargs):
        est = real(profile, year, income, **kwargs)
        runs.append((profile, est))
        return est

    monkeypatch.setattr(scenarios_module, "estimate_refund", spy)
    return runs


def _elected_runs(runs: list, status: str) -> list:
    return [
        est for prof, est in runs
        if prof.household.filing_status.value == status
        and prof.residency_facts.section_6013_election is not None
        and prof.residency_facts.section_6013_election.value is True
    ]


def test_p018_election_mfj_on_a_timeline_profile_takes_the_mfj_standard_deduction(monkeypatch):
    runs = _spy(monkeypatch)
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000)
    r = compare_scenarios(_timeline_nra_profile(), 2025, income, [_MFS_NR, _ELECT_MFJ])
    outcomes = {o.name: o.bottom_line for o in r.outcomes}
    # The baseline is the nonresident's own Form 1040-NR (deduction $0) — unchanged.
    assert outcomes["MFS on 1040-NR"] == 6_000 - tax_from_taxable_income(60_000, "married_filing_separately", 2025).tax
    # The election figure is a RESIDENT joint return: the pack's MFJ standard deduction.
    mfj_sd = standard_deduction("married_filing_jointly", 2025).amount
    elected = 6_000 - tax_from_taxable_income(60_000 - mfj_sd, "married_filing_jointly", 2025).tax
    nra_rules_joint = 6_000 - tax_from_taxable_income(60_000, "married_filing_jointly", 2025).tax  # the old figure
    assert outcomes["MFJ + election"] == elected != nra_rules_joint
    # What compare_scenarios actually computed for the election scenario.
    ests = _elected_runs(runs, "married_filing_jointly")
    assert ests and all(e.point == elected for e in ests)
    est = ests[0]
    labels = {ln.label: ln.amount for ln in est.composition}
    assert labels["Less: standard deduction"] == -mfj_sd
    assert not any("1040-NR" in ln.label for ln in est.composition)
    assert est.roadmap.returns_and_forms[0] == "Form 1040"
    assert not any("1040-NR" in f for f in est.roadmap.returns_and_forms)
    # The input walk: switching the election on at the baseline's MFS status already
    # moves the number (resident MFS with its standard deduction) — it was +0 when the
    # scenario only flipped us_person.
    delta = next(d for d in r.deltas if d.name == "MFJ + election")
    step = next(s for s in delta.input_attribution if s.changed.startswith("us_resident_election"))
    mfs_sd = standard_deduction("married_filing_separately", 2025).amount
    assert step.bottom_after == 6_000 - tax_from_taxable_income(60_000 - mfs_sd, "married_filing_separately", 2025).tax
    assert step.delta > 0
    assert sum(s.delta for s in delta.input_attribution) == delta.delta
    # The comparison says the scenario ran under resident rules, and names the precondition.
    joined = " ".join(r.assumptions)
    assert "RESIDENT rules for both spouses" in joined and "P-018" in joined
    assert "one spouse is a U.S. citizen or a resident alien" in joined
    # The scenario never rewrote the citizenship fact.
    assert all(prof.identity.us_person.value is False for prof, _ in runs)


def test_p018_election_on_a_timeline_profile_evaluates_niit():
    # A nonresident's Form 1040-NR owes no NIIT; under the election the joint figure
    # evaluates it (AGI $270,000 against the joint threshold; the Treas. Reg.
    # 1.1411-2(a)(2)(iii)(B) second election is disclosed by the estimator).
    income = IncomeSnapshot(wages=240_000, federal_withholding=40_000, interest=30_000)
    r = compare_scenarios(_timeline_nra_profile(), 2025, income, [_MFS_NR, _ELECT_MFJ])
    delta = next(d for d in r.deltas if d.name == "MFJ + election")
    niit_row = next(x for x in delta.ledger_deltas if x.slot == "niit")
    expected = niit(30_000, 270_000, "married_filing_jointly", 2025).niit
    assert expected > 0
    assert niit_row.best_effect == -expected   # the election figure owes NIIT ...
    assert niit_row.worst_effect == 0          # ... the 1040-NR baseline does not


def test_p018_election_mfs_on_a_timeline_profile_ends_the_deposit_exclusion(monkeypatch):
    # A later year of a continuing election may be filed separately ("you and your spouse
    # can file joint or separate returns in later years", Pub 519 ch. 1) — both still
    # residents, so the 871(i)(2)(A) deposit-interest exclusion is off on MFS too.
    runs = _spy(monkeypatch)
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000, interest=900, bank_deposit_interest=900)
    r = compare_scenarios(_timeline_nra_profile(), 2025, income, [_MFS_NR, _ELECT_MFS])
    outcomes = {o.name: o.bottom_line for o in r.outcomes}
    # Control: the 1040-NR baseline excludes the characterized deposit interest.
    assert outcomes["MFS on 1040-NR"] == 3_000 - tax_from_taxable_income(40_000, "married_filing_separately", 2025).tax
    mfs_sd = standard_deduction("married_filing_separately", 2025).amount
    assert outcomes["MFS + election (later year)"] == (
        3_000 - tax_from_taxable_income(40_900 - mfs_sd, "married_filing_separately", 2025).tax
    )
    est = _elected_runs(runs, "married_filing_separately")[0]
    assert not any(ln.slot == "deposit_interest_exclusion" for ln in est.composition)
    assert any(a.startswith("Under the §6013(g)/(h) election recorded on this profile the $900") for a in est.assumptions)
    assert any("LATER year of a continuing election" in a for a in est.assumptions)


def test_p018_the_mcp_tool_prices_the_election_on_a_timeline_profile(tmp_path):
    # The same repro through the compare_scenarios MCP tool, profile passed as JSON.
    from taxfill_mcp.server import compare_scenarios as tool

    out = tool(2025, scenarios=[_MFS_NR, _ELECT_MFJ], income={"wages": 60_000, "federal_withholding": 6_000},
               profile=_timeline_nra_profile().model_dump(mode="json"), root=str(tmp_path))
    mfj_sd = standard_deduction("married_filing_jointly", 2025).amount
    elected = next(o for o in out["outcomes"] if o["name"] == "MFJ + election")
    assert elected["bottom_line"] == 6_000 - tax_from_taxable_income(60_000 - mfj_sd, "married_filing_jointly", 2025).tax


def _recorded(profile: Profile, value: bool) -> Profile:
    profile.residency_facts.section_6013_election = Answer(value=value, provenance=US)
    return profile


def test_p018_a_recorded_election_is_followed_and_an_override_named():
    # A continuing election (recorded on the profile) is never silently revoked: a
    # scenario that omits us_resident_election FOLLOWS the recorded fact, so its MFS
    # figure is the resident MFS return the estimator computes for the same profile.
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000)
    profile = _recorded(_timeline_nra_profile(), True)
    r = compare_scenarios(profile, 2025, income, [
        {"name": "MFJ", "filing_status": "married_filing_jointly"},
        {"name": "MFS", "filing_status": "married_filing_separately"},
    ])
    outs = {o.name: o for o in r.outcomes}
    mfs_sd = standard_deduction("married_filing_separately", 2025).amount
    assert outs["MFS"].bottom_line == 6_000 - tax_from_taxable_income(60_000 - mfs_sd, "married_filing_separately", 2025).tax
    assert outs["MFS"].section_6013_election and outs["MFJ"].section_6013_election
    assert "treated for income tax purposes as residents for your entire tax year" in outs["MFS"].residency_caveat
    assert "LATER year of a continuing election" in outs["MFS"].residency_caveat
    joined = " ".join(r.assumptions)
    assert "'MFS' (recorded on the profile)" in joined
    assert not any("OVERRIDING" in a for a in r.assumptions)
    # The walk has no election step: both scenarios run under the recorded election.
    assert not any(s.changed.startswith("us_resident_election") for s in r.deltas[0].input_attribution)
    # An explicit false overrides the recorded fact for that scenario — and says so.
    r2 = compare_scenarios(profile, 2025, income, [
        {"name": "MFJ", "filing_status": "married_filing_jointly"},
        {"name": "MFS, not electing", "filing_status": "married_filing_separately", "us_resident_election": False},
    ])
    override = next(a for a in r2.assumptions if "OVERRIDING" in a)
    assert "'MFS, not electing'" in override and "neither spouse can make this choice in any later tax year" in override
    outs2 = {o.name: o for o in r2.outcomes}
    assert outs2["MFS, not electing"].bottom_line == (
        6_000 - tax_from_taxable_income(60_000, "married_filing_separately", 2025).tax      # Form 1040-NR rules
    )
    assert not outs2["MFS, not electing"].section_6013_election
    step = next(s for s in r2.deltas[0].input_attribution if s.changed.startswith("us_resident_election"))
    assert step.changed == "us_resident_election: True -> False"
    assert sum(s.delta for s in r2.deltas[0].input_attribution) == r2.deltas[0].delta


def test_p018_an_unavailable_election_is_never_recommended():
    # Pub 519 ch. 1: the choice needs "one spouse is a U.S. citizen or a resident alien" at
    # year end, and IRC 6013(g)(3) suspends an earlier one when "neither spouse is a citizen
    # or resident of the United States at any time during such year". Two nonresidents on
    # the recorded facts: the election is NOT applied (priced without it) and the scenario
    # is not a filing option.
    profile = _timeline_nra_profile()
    spouse_profile = _timeline_nra_profile()
    profile.household = Household(spouse=Spouse(
        us_person=Answer(value=False, provenance=US),
        immigration=spouse_profile.immigration, residency_facts=spouse_profile.residency_facts,
    ))
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000)
    r = compare_scenarios(profile, 2025, income, [_MFS_NR, _ELECT_MFJ])
    outs = {o.name: o for o in r.outcomes}
    assert outs["MFJ + election"].bottom_line == outs["MFS on 1040-NR"].bottom_line   # two Form 1040-NRs
    assert not outs["MFJ + election"].section_6013_election
    assert r.recommended == "MFS on 1040-NR"
    assert "NOT available" in outs["MFJ + election"].residency_caveat
    assert any(a.startswith("Scenario 'MFJ + election' seeks the §6013(g)/(h) election, but on the recorded facts")
               for a in r.assumptions)
    assert "among the filing options" in r.work


def test_p018_an_election_flag_on_a_single_status_is_named_as_not_applied():
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000)
    r = compare_scenarios(_timeline_nra_profile(), 2025, income, [
        _MFS_NR, {"name": "single + flag", "filing_status": "single", "us_resident_election": True},
    ])
    assert any("'single + flag' sets us_resident_election" in a and "NOT applied" in a for a in r.assumptions)
    assert not any("These scenarios ran under the election" in a for a in r.assumptions)
    assert not {o.name: o for o in r.outcomes}["single + flag"].section_6013_election


def test_p018_a_recorded_election_followed_onto_a_single_status_is_named_as_not_applied():
    # A scenario that omits the flag FOLLOWS the recorded election; on a status with no
    # spouse at year end it cannot apply — and the comparison must say so, not stay silent.
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000)
    r = compare_scenarios(_recorded(_timeline_nra_profile(), True), 2025, income, [
        {"name": "MFJ", "filing_status": "married_filing_jointly"},
        {"name": "single", "filing_status": "single"},
    ])
    note = next(a for a in r.assumptions if a.startswith("Scenario 'single'"))
    assert "follows the §6013(g)/(h) election recorded on the profile" in note and "NOT applied" in note
    outs = {o.name: o for o in r.outcomes}
    assert outs["MFJ"].section_6013_election and not outs["single"].section_6013_election


# P-018, the second verify round (2026-09-26): an explicit us_resident_election=false on
# a joint scenario is honored (never overruled by the joint-status reading), the walk's
# election step follows the estimator's actual reading, and a scenario that is not a
# filing option is never recommended — even when none is. Hypothetical demo fixtures.

_MFS = "married_filing_separately"
_FAQ = "Generally, you cannot file as married filing jointly if either spouse was a nonresident alien"


def test_p018_mfj_with_the_election_declined_is_not_a_filing_option():
    # The ROADMAP's original +0 shape: [MFJ true, MFJ false]. Pub 519 FAQ: a joint return
    # with a nonresident alien exists only under the election, so 'MFJ false' is priced
    # as the separate return (Form 1040-NR here) and is never recommended.
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000)
    r = compare_scenarios(_timeline_nra_profile(), 2025, income, [
        _ELECT_MFJ, {"name": "MFJ, declined", "filing_status": "married_filing_jointly", "us_resident_election": False},
    ])
    outs = {o.name: o for o in r.outcomes}
    assert outs["MFJ, declined"].bottom_line == 6_000 - tax_from_taxable_income(60_000, _MFS, 2025).tax
    assert not outs["MFJ, declined"].section_6013_election and outs["MFJ + election"].section_6013_election
    assert outs["MFJ, declined"].residency_caveat.startswith("CONTRADICTION")
    assert r.recommended == "MFJ + election"
    note = next(a for a in r.assumptions if a.startswith("Scenario 'MFJ, declined' is married-filing-jointly"))
    assert "NOT a filing option" in note and _FAQ in note
    assert not any("false models NOT electing" in a for a in r.assumptions)
    step = next(s for s in r.deltas[0].input_attribution if s.changed.startswith("us_resident_election"))
    assert step.changed == "us_resident_election: True -> False" and step.delta != 0
    assert sum(s.delta for s in r.deltas[0].input_attribution) == r.deltas[0].delta


def test_p018_the_walk_names_an_implied_election():
    # An MFJ scenario of a nonresident with the flag omitted runs under the implied
    # election; the walk books that residency switch to an election step, not to the status.
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000)
    r = compare_scenarios(_timeline_nra_profile(), 2025, income, [
        _MFS_NR, {"name": "MFJ", "filing_status": "married_filing_jointly"},
    ])
    steps = r.deltas[0].input_attribution
    assert steps[0].changed == ("us_resident_election: False -> True (the scenario's election is read from its "
                                "joint status; priced here at married_filing_separately)")
    mfs_sd = standard_deduction(_MFS, 2025).amount
    assert steps[0].bottom_after == 6_000 - tax_from_taxable_income(60_000 - mfs_sd, _MFS, 2025).tax
    assert steps[1].changed.startswith("filing_status:")
    assert sum(s.delta for s in steps) == r.deltas[0].delta


def test_p018_a_recorded_election_with_a_declined_joint_scenario():
    # The edge verifier's shape: recorded True, [MFS, MFS false, MFJ false]. Only the MFS
    # override is a revocation note; the MFJ-false scenario is not a filing option.
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000)
    r = compare_scenarios(_recorded(_timeline_nra_profile(), True), 2025, income, [
        {"name": "MFS", "filing_status": _MFS},
        {"name": "MFS-no", "filing_status": _MFS, "us_resident_election": False},
        {"name": "MFJ-no", "filing_status": "married_filing_jointly", "us_resident_election": False},
    ])
    overrides = [a for a in r.assumptions if "OVERRIDING" in a]
    assert len(overrides) == 1 and "'MFS-no'" in overrides[0]
    assert r.recommended != "MFJ-no"
    outs = {o.name: o for o in r.outcomes}
    assert outs["MFJ-no"].bottom_line == outs["MFS-no"].bottom_line          # the same separate return
    walk = next(d for d in r.deltas if d.name == "MFJ-no").input_attribution
    assert not any(s.changed.startswith("filing_status") and s.delta != 0 for s in walk)


def test_p018_only_the_joint_scenario_seeking_an_unavailable_election_is_excluded():
    profile = _timeline_nra_profile()
    spouse_profile = _timeline_nra_profile()
    profile.household = Household(spouse=Spouse(
        us_person=Answer(value=False, provenance=US),
        immigration=spouse_profile.immigration, residency_facts=spouse_profile.residency_facts,
    ))
    r = compare_scenarios(profile, 2025, IncomeSnapshot(wages=40_000, federal_withholding=3_000),
                          [_ELECT_MFJ, _ELECT_MFS])
    assert not any(o.section_6013_election for o in r.outcomes)
    # Round 3: the SEPARATE scenario, priced without the unavailable election, is exactly the
    # returns this couple files (Pub 519, Suspending the Choice), so it stays a filing option;
    # only the joint one is not.
    assert r.recommended == _ELECT_MFS["name"]
    assert f"* {_ELECT_MFJ['name']}:" in r.work and "NOT a filing option" in r.work
    assert any("stays a filing option" in a for a in r.assumptions)


def test_p018_a_head_of_household_scenario_means_ending_a_recorded_election():
    # Pub 501, Considered Unmarried, and Pub 519 ch. 1, Ending the Choice: the CITIZEN
    # spouse of a nonresident may file head of household only without the election.
    citizen = Profile(
        identity=Identity(us_person=Answer(value=True, provenance=US)),
        household=Household(marital_status=Answer(value="married", provenance=US), spouse=Spouse(
            us_person=Answer(value=False, provenance=US),
            immigration=_timeline_nra_profile().immigration, residency_facts=_timeline_nra_profile().residency_facts,
        )),
        residency_facts=ResidencyFacts(section_6013_election=Answer(value=True, provenance=US)),
    )
    r = compare_scenarios(citizen, 2025, IncomeSnapshot(wages=40_000, federal_withholding=3_000), [
        {"name": "MFJ", "filing_status": "married_filing_jointly"},
        {"name": "HOH", "filing_status": "head_of_household"},
    ])
    note = next(a for a in r.assumptions if a.startswith("Scenario 'HOH'"))
    assert "NOT applied" in note and "exists only WITHOUT the election" in note
    assert "neither spouse can make this choice in any later tax year" in note
    assert "has no spouse" not in note


def test_p018_a_nonresident_taxpayers_head_of_household_scenario_is_not_a_filing_option():
    # Pub 519 ch. 5: "You cannot file as head of household if you are a nonresident alien at any
    # time during the tax year" — never the recommendation, and no citizen-side ending text.
    r = compare_scenarios(_recorded(_timeline_nra_profile(), True), 2025,
                          IncomeSnapshot(wages=40_000, federal_withholding=3_000), [
                              {"name": "MFS", "filing_status": _MFS},
                              {"name": "HOH", "filing_status": "head_of_household"},
                          ])
    note = next(a for a in r.assumptions if a.startswith("Scenario 'HOH'"))
    assert "You cannot file as head of household if you are a nonresident alien" in note
    assert "ending" not in note and r.recommended != "HOH"
    assert "NOT a filing option: a nonresident alien cannot file as head of household" in r.work
