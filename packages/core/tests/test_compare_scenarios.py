"""compare_scenarios golden tests — Phase H item H7 (field notes N-9, N-15).

The canonical use case is a three-way what-if (single / MFS / MFJ via the
§6013(g) election) that must be re-run each
time an input fact changes. These tests pin the two properties that make the
tests pin the two properties that make the surface trustworthy:

  * BOTH attributions are exact — the ledger diff sums to the headline delta
    (spine invariant) AND the sequential input walk telescopes to it (every
    intermediate is a real computed bottom line);
  * the comparison stays honest across years — a provisional-year scenario is
    labeled PROJECTION and its missing blocks are named, because a silent
    cross-year diff was exactly the $2,126 credit-drop trap.

All data synthetic. Offline.
"""

from __future__ import annotations

import pytest

from taxfill_core.estimate import IncomeSnapshot
from taxfill_core.scenarios import ScenarioSpec, compare_scenarios
from taxfill_core.schemas.profile import Answer, Identity, Profile, Provenance
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
            "interest": 700,
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
    assert any(c.startswith("us_resident_election") for c in changed)
    assert any(c.startswith("filing_status") for c in changed)
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
    # A what-if gets revised mid-flight; each revision of a base fact must be
    # rebuild.
    from taxfill_mcp.server import compare_scenarios as tool

    root = str(tmp_path)
    first = tool(2025, scenarios=THREE_WAY,
                 income={"wages": 96_000, "federal_withholding": 13_000},
                 save_as="demo-what-if", root=root)
    assert first["saved_as"] == "demo-what-if"
    baseline_first = next(o for o in first["outcomes"] if o["name"] == "stay single")

    # A base fact changes (e.g. a raise): update ONE base fact and re-run.
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
