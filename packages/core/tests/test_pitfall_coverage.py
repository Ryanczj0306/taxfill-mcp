"""Pitfall-coverage meta-test (dev plan section 14).

"Every pitfall in knowledge/pitfalls.yaml has a corresponding regression
test; CI fails if a pitfall lacks one." CI is a bare ``uv run pytest``, so
this test IS the enforcement: it parses the registry and asserts every
pitfall id appears in at least one test file. Deferred pitfalls (whose
countermeasure ships in a later milestone) live in an explicit allowlist
with the reason, so a gap is a visible, documented decision — never an
invisible omission that nothing will catch when the milestone ships.
"""

from pathlib import Path

import yaml

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
PITFALLS_PATH = REPO_ROOT / "knowledge" / "pitfalls.yaml"

# Pitfalls whose permanent countermeasure is deliberately deferred to a later
# milestone. Adding an entry requires recording the deferral in
# knowledge/pitfalls.yaml too (the countermeasure text must say "DEFERRED").
# When the countermeasure ships WITH its regression test, the entry must be
# removed — test_deferred_allowlist_is_current fails otherwise.
# (P-004 treaty eligibility shipped its countermeasure in Tier 2: the
# treaty_exempt_income estimate path + eval scenario carry P-004-tagged tests,
# so the deferral entry was removed per the rule above.)
DEFERRED: dict[str, str] = {}


def _pitfall_ids() -> list[str]:
    data = yaml.safe_load(PITFALLS_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "pitfalls" in data, (
        f"{PITFALLS_PATH} must be a mapping with a 'pitfalls' list — see the schema "
        f"comment at the top of the file"
    )
    ids = [entry["id"] for entry in data["pitfalls"]]
    assert ids, f"{PITFALLS_PATH} lists no pitfalls — the registry must never be emptied"
    return ids


def _test_sources() -> dict[str, str]:
    """Source text of every test file except this meta-test itself."""
    me = Path(__file__).name
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in TESTS_DIR.glob("test_*.py")
        if path.name != me
    }


def test_every_pitfall_has_a_regression_test():
    sources = _test_sources()
    missing = [
        pitfall_id
        for pitfall_id in _pitfall_ids()
        if pitfall_id not in DEFERRED
        and not any(pitfall_id in source for source in sources.values())
    ]
    assert missing == [], (
        f"pitfall(s) {missing} have no regression test (dev plan section 14: every "
        f"pitfall gets one) — add a test referencing the id, or, if the countermeasure "
        f"genuinely belongs to a later milestone, add the id to DEFERRED in "
        f"{Path(__file__).name} with the reason AND record the deferral in "
        f"knowledge/pitfalls.yaml"
    )


def test_deferred_allowlist_is_current():
    ids = set(_pitfall_ids())
    unknown = sorted(set(DEFERRED) - ids)
    assert unknown == [], (
        f"DEFERRED lists id(s) {unknown} that are not in knowledge/pitfalls.yaml — "
        f"remove them or fix the registry"
    )
    sources = _test_sources()
    now_covered = sorted(
        pitfall_id
        for pitfall_id in DEFERRED
        if any(pitfall_id in source for source in sources.values())
    )
    assert now_covered == [], (
        f"deferred pitfall(s) {now_covered} now have regression tests — remove them "
        f"from DEFERRED in {Path(__file__).name} so the coverage requirement applies again"
    )


def test_deferrals_are_recorded_in_the_registry():
    # The allowlist and the registry must tell the same story: pitfalls.yaml
    # promises countermeasures, so a deferral hidden only in test code would
    # leave the registry overstating what shipped.
    data = yaml.safe_load(PITFALLS_PATH.read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in data["pitfalls"]}
    not_recorded = sorted(
        pitfall_id
        for pitfall_id in DEFERRED
        if "DEFERRED" not in by_id[pitfall_id].get("countermeasure", "")
    )
    assert not_recorded == [], (
        f"pitfall(s) {not_recorded} are deferred in {Path(__file__).name} but "
        f"knowledge/pitfalls.yaml does not say so — add 'DEFERRED: ...' to the "
        f"countermeasure text so the registry matches what actually shipped"
    )
