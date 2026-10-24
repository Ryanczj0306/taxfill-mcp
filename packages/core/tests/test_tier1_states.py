"""Phase K JK9 (2026-10-24) — scripts/tier1_states.yaml, the tier-1 state triage table JS7a and JK8 work from.

The table ranks the income-tax jurisdictions by the IRS SOI return count and records, per tier-1 state, the forms, the
amend route and whether the 2025 pack maps the amended indicator. These tests keep each claim tied to the repo it
describes, so a pack or knowledge change that contradicts a row fails here instead of rotting silently.
"""
from __future__ import annotations

import importlib.util
import json
import re
import urllib.parse
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
TABLE_PATH = REPO / "scripts" / "tier1_states.yaml"
STATES = REPO / "formpacks" / "states"
KNOWLEDGE = REPO / "knowledge" / "states"
WORKLIST = REPO / "scripts" / "worklists" / "tier1_ty2026_2026-10-24.json"
ROUTES = {"same_form_indicator", "separate_x_form"}
_AMEND = re.compile(r"amend", re.I)

_spec = importlib.util.spec_from_file_location("scaffold_state_year", REPO / "scripts" / "scaffold_state_year.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

TABLE = yaml.safe_load(TABLE_PATH.read_text(encoding="utf-8"))
TIER1 = TABLE["tier1"]


def _gov(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").endswith(".gov")


def _sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value or ""))


def _income_tax_jurisdictions() -> set[str]:
    """Every jurisdiction with a TY2025 pack and TY2025 knowledge (the 41 states + DC)."""
    return {d.name.upper() for d in STATES.iterdir() if (d / "2025").is_dir() and (KNOWLEDGE / d.name / "2025.yaml").is_file()}


def _pack(rel: str) -> dict:
    return yaml.safe_load((STATES / rel / "pack.yaml").read_text(encoding="utf-8"))


def test_the_volume_citation_is_a_pinned_gov_table():
    vol = TABLE["volume"]
    assert _gov(vol["url"]) and _gov(vol["index_url"]) and _gov(vol["documentation"]["url"])
    assert _sha(vol["sha256"]) and _sha(vol["documentation"]["sha256"])
    assert vol["column"] == "N1" and vol["documentation"]["variables"]["N1"].startswith("Number of returns")
    assert isinstance(vol["table_year"], int)
    assert vol["url"].rsplit("/", 1)[1].startswith(f"{vol['table_year'] % 100:02d}in")   # SOI names a year's file YYin…


def test_the_ranking_is_every_income_tax_jurisdiction_sorted_by_returns():
    ranking = TABLE["ranking"]
    states = [r["state"] for r in ranking]
    counts = [r["returns"] for r in ranking]
    assert [r["rank"] for r in ranking] == list(range(1, len(ranking) + 1))
    assert counts == sorted(counts, reverse=True), "the ranking is not sorted by return count"
    assert all(isinstance(c, int) and c > 0 for c in counts)
    assert len(set(states)) == len(states) == 42
    assert set(states) == _income_tax_jurisdictions()


def test_the_excluded_states_are_the_no_income_tax_list():
    raw = yaml.safe_load((KNOWLEDGE / "no_income_tax.yaml").read_text(encoding="utf-8"))
    listed = {e["state"] for v in raw.values() if isinstance(v, list) for e in v}
    assert set(TABLE["excluded_no_income_tax"]) == listed
    assert not listed & {r["state"] for r in TABLE["ranking"]}


def test_the_cut_is_the_stated_rule():
    cut, ranking = TABLE["cut"], TABLE["ranking"]
    assert 10 <= cut["size"] <= 14                                    # "about 12"
    assert [r["state"] for r in TIER1] == [r["state"] for r in ranking[: cut["size"]]]
    assert cut["income_tax_returns_total"] == sum(r["returns"] for r in ranking)
    assert cut["tier1_returns_total"] == sum(r["returns"] for r in ranking[: cut["size"]])
    # The NRA-student weighting is a recommendation for the user; until accepted the cut is volume only.
    assert TABLE["recommendation"]["status"] in {"pending", "accepted", "rejected"}
    if TABLE["recommendation"]["status"] != "accepted":
        assert "no other weighting" in cut["rule"]


@pytest.mark.parametrize("row", TIER1, ids=[r["state"] for r in TIER1])
def test_the_forms_agree_with_the_2025_knowledge(row):
    forms = yaml.safe_load((KNOWLEDGE / row["state"].lower() / "2025.yaml").read_text(encoding="utf-8"))["forms"]
    assert row["resident_form"] in forms["resident"]
    for form in row["nrpy_forms"]:
        assert form in forms["part_year_or_nonresident"], (form, forms["part_year_or_nonresident"])


@pytest.mark.parametrize("row", TIER1, ids=[r["state"] for r in TIER1])
def test_the_amend_route_is_cited_and_matches_the_resident_pack(row):
    for key in ("amend", "nrpy_amend"):
        amend = row.get(key)
        if amend is None:
            continue
        assert amend["route"] in ROUTES
        assert _gov(amend["url"]) and _sha(amend["sha256"]) and amend["page"] and amend["quote"]
    # A same-form state amends through the return's own indicator, so its resident pack must map it; an X-form state's
    # resident return has none (JS7a: "the amended checkbox mapped where the state amends on the same form").
    resident = row["packs"][0]
    assert (resident["amended_indicator"] is not None) == (row["amend"]["route"] == "same_form_indicator"), row["state"]
    # The NR/PY route belongs to the NR/PY pack (JK9 review, 2026-10-24): CA 540NR amends on its own AMENDED box,
    # NY IT-203 through Form IT-203-X, so each NR/PY pack's indicator must agree with nrpy_amend's route.
    if row.get("nrpy_amend"):
        nrpy = [p for p in row["packs"] if p["pack"] in (row.get("nrpy_lineage") or [])]
        assert nrpy, f"{row['state']}: nrpy_amend names a route but no 2025 NR/PY pack is listed in packs"
        for pack in nrpy:
            same_form = row["nrpy_amend"]["route"] == "same_form_indicator"
            assert (pack["amended_indicator"] is not None) == same_form, (row["state"], pack["pack"])
    knowledge = yaml.safe_load((KNOWLEDGE / row["state"].lower() / "2025.yaml").read_text(encoding="utf-8"))
    if "amended_return" in knowledge:                                  # GA: the knowledge names the X form
        assert knowledge["amended_return"]["form"] in row["amend"]["form"]


@pytest.mark.parametrize("entry", [(r["state"], p) for r in TIER1 for p in r["packs"]],
                         ids=[p["pack"] for r in TIER1 for p in r["packs"]])
def test_each_amended_indicator_claim_matches_the_pack(entry):
    _state, row = entry
    pack = _pack(row["pack"])
    assert pack["tax_year"] == 2025
    boxes = {e["line"]: e["field"] for e in pack.get("fields") or []
             if isinstance(e, dict) and e.get("type") == "checkbox"
             and (_AMEND.search(str(e.get("line"))) or _AMEND.search(str(e.get("field"))))}
    others = row.get("not_the_indicator") or {}
    claim = row["amended_indicator"]
    expected = set(others) | ({claim["line"]} if claim else set())
    assert set(boxes) == expected, (
        f"{row['pack']}: the pack's amend checkboxes {sorted(boxes)} are not the table's {sorted(expected)}; "
        f"update scripts/tier1_states.yaml (amended_indicator / not_the_indicator)")
    if claim:
        assert boxes[claim["line"]] == claim["field"]


@pytest.mark.parametrize("row", TIER1, ids=[r["state"] for r in TIER1])
def test_every_pack_of_a_tier1_state_is_in_its_row(row):
    st = row["state"].lower()
    newest: dict[str, int] = {}
    for pack in (STATES / st).glob("*/*/pack.yaml"):
        year, form = pack.parts[-3], pack.parts[-2]
        if year.isdigit() and int(year) <= 2025:
            newest[form] = max(newest.get(form, 0), int(year))
    listed = {p["pack"] for p in row["packs"]} | set(row["nrpy_lineage"]) | set(row.get("schedules", []))
    assert listed == {f"{st}/{y}/{f}" for f, y in newest.items()}, row["state"]


def test_load_tier1_reads_the_table_and_refuses_a_cut_that_is_not_the_ranking(tmp_path):
    assert sc.load_tier1() == [r["state"].lower() for r in TIER1]
    doctored = dict(TABLE, tier1=list(reversed(TIER1)))
    bad = tmp_path / "tier1.yaml"
    bad.write_text(yaml.safe_dump(doctored), encoding="utf-8")
    with pytest.raises(SystemExit, match="not the top"):
        sc.load_tier1(bad)


def test_scaffold_filters_to_the_given_states():
    rows = sc.scaffold(2026, "newest", offline=True, states={"ca"})
    assert {r["state"] for r in rows} == {"ca"}
    assert {r["form"] for r in rows} == {"form540", "form540nr", "sched_ca_540", "sched_ca_540nr"}


def test_the_staged_worklist_covers_the_tier1_states():
    listing = json.loads(WORKLIST.read_text(encoding="utf-8"))
    assert listing["target_year"] == 2026 and listing["base"] == "newest"
    assert listing["tier1"] == [r["state"].lower() for r in TIER1]
    assert {r["state"] for r in listing["packs"]} == set(listing["tier1"])
