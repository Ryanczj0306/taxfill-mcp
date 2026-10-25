"""Phase K JK15b (2026-10-25): scripts/anchor_label_check.py — the checkbox-label measurement (JK19 pilot D3, D5)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("anchor_label_check", REPO / "scripts" / "anchor_label_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["anchor_label_check"] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load()


@pytest.mark.parametrize("key,option", [
    ("filing_status.single", "single"), ("8.yes", "yes"), ("a.no", "no"),
    ("filing_status.married_filing_jointly", "married_filing_jointly"),
])
def test_a_key_whose_last_segment_is_words_names_an_option(key, option):
    assert L.option_of(key) == option


@pytest.mark.parametrize("key", ["13a", "box_1", "c1", "line5.check", "filing_status.checkbox"])
def test_numbered_coded_and_generic_keys_name_no_option(key):
    assert L.option_of(key) is None


def test_a_label_names_its_option_by_whole_words_and_yes_no_exactly():
    assert L.names_option("Married filing jointly", "married_filing_jointly")
    assert L.names_option("Qualifying surviving spouse", "qualifying_surviving_spouse")
    assert L.names_option("Married filing separately (enter spouse information above)", "married_filing_separately")
    assert L.names_option("Yes. Go to line 10.", "yes")
    assert not L.names_option("Single", "married_filing_jointly")  # the previous option's caption (D3)
    assert not L.names_option("Note: see instructions", "no") and not L.names_option("Not applicable", "no")
    assert not L.names_option(None, "yes")
    assert not L.names_option("Check here", "mfj")  # an abbreviated key counts as a miss before and after alike


def test_the_committed_measurement_records_the_method_before_and_the_current_method():
    from taxfill_core import anchor as A

    data = yaml.safe_load(L.LABELS.read_text(encoding="utf-8"))
    by = {e["method"]: e for e in data["measurements"]}
    assert {"jk15-v4", A.METHOD} <= set(by)
    before, after = by["jk15-v4"], by[A.METHOD]
    assert before["all_named_options"]["widgets"] == after["all_named_options"]["widgets"]  # one population
    for group in ("all_named_options", "yes_no", "filing_status"):
        assert after[group]["rate"] > before[group]["rate"], group
    assert after["yes_no_with_printed_line"] > before["yes_no_with_printed_line"]
    # the D5 cross-check: Yes/No keys named by a numbered line ("9.yes") now mostly carry that line
    b, a = before["yes_no_keyed_by_line"], after["yes_no_keyed_by_line"]
    assert a["printed_line_is_key_line"] > b["printed_line_is_key_line"] and a["no_line"] < b["no_line"]
    assert a["printed_line_is_key_line"] / (a["printed_line_is_key_line"] + a["other_line"]) >= 0.95


@pytest.mark.network
def test_the_committed_measurement_matches_a_recomputation():
    """A full recompute over the shipped packs' cached blanks; skipped when the cache does not hold every pack's blank
    (fewer packs contribute than the committed entry counted)."""
    from taxfill_core import anchor as A

    data = yaml.safe_load(L.LABELS.read_text(encoding="utf-8"))
    recorded = {e["method"]: e for e in data["measurements"]}[A.METHOD]
    rows, packs = L.population()
    if packs < recorded["packs"]:
        pytest.skip(f"only {packs} of {recorded['packs']} packs' blanks are cached")
    assert L.measure(rows, packs) == recorded
