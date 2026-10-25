"""Phase K JK15 (2026-10-24): scripts/anchor_benchmark.py — the key->line rule, finalize and the KG6 network cases."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("anchor_benchmark", REPO / "scripts" / "anchor_benchmark.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["anchor_benchmark"] = mod
    spec.loader.exec_module(mod)
    return mod


B = _load()
A = B.A


# ── the key -> line rule ─────────────────────────────────────────────────────


@pytest.mark.parametrize("key,line", [
    ("21", "21"), ("5a", "5a"), ("05", "5"), ("line_21", "21"), ("line21a", "21a"), ("21.col_b", "21"),
    ("1a.col_a", "1a"), ("100", "100"),
])
def test_numbered_keys_score_as_their_line(key, line):
    assert B.key_line(key) == line


@pytest.mark.parametrize("key", [
    "dependents.1.ssn", "filing_status.single", "14.r1.a", "5.cont1", "22a.ein.1", "7.2013", "8.yes", "17.standard",
    "20_amount", "34_total_donations", "10c_ssn", "line15_d01", "5A", "C11_A", "10ab_more_space", "s1.7a",
    "schedule_e.4a", "SCHAATCLN1", "0", "1000", "21.amount", "identifying_number", "4_filing_status::mfj",
])
def test_every_other_key_shape_is_unscored(key):
    assert B.key_line(key) is None


def test_truth_is_every_numbered_key_of_the_field_and_a_checkbox_key_binds_its_on_state_widget():
    widgets = [
        {"name": "root.f1", "on_states": []},
        {"name": "root.f1", "on_states": []},          # the same field's second widget (a carry-forward echo)
        {"name": "root.c1", "on_states": ["/1"]},
        {"name": "root.c1", "on_states": ["/2"]},
    ]
    keys = [{"key": "11", "field": "f1"}, {"key": "11b", "field": "f1"}, {"key": "name.first", "field": "f1"},
            {"key": "7", "field": "c1", "on_state": "/2"}, {"key": "20_amount", "field": "c1", "line": "20",
                                                           "on_state": "/1"}]
    truth = B.truth_map(keys, widgets, "root")
    assert truth == {("root.f1", 0): {"11", "11b"}, ("root.f1", 1): {"11", "11b"}, ("root.c1", 1): {"7"},
                     ("root.c1", 0): {"20"}}


# ── finalize / check on a fixture ────────────────────────────────────────────


def _row(pack, field, printed, truth, tier=A.TOP):
    w = A.WidgetAnchor(field=field, widget_index=0, page=1, rect=[0, 0, 1, 1], kind="text", printed_line=printed)
    return B.Scored(pack=pack, blank=Path("blank.pdf"), widget=w, tier=tier, truth=set(truth))


def _fixture(n_packs=30):
    runs = []
    for i in range(n_packs):
        run = B.PackRun(pack=f"states/s{i % 15}/2025/f{i}" if i >= 10 else f"federal/2025/f{i}", blank=Path("b.pdf"))
        run.rows = [_row(run.pack, f"a{j}", str(j + 1), {str(j + 1)}) for j in range(10)]
        runs.append(run)
    runs[0].rows.append(_row(runs[0].pack, "rotated", "21", {"22"}))      # the pack is wrong here
    runs[1].rows.append(_row(runs[1].pack, "wrong", "5", {"6"}))          # the anchor is wrong here
    runs[2].rows.append(_row(runs[2].pack, "unclear", "7", {"7a"}))       # nobody can tell
    runs[3].rows.append(_row(runs[3].pack, "nolist", "9", set()))         # top tier, no truth: sampled
    return runs


def _measured(runs, dis, sample, flagged=True):
    return {"test": B.report(runs), "dev": B.report(runs[:2]),
            "mandatory": {"me_1040me_2023": {"all_flagged": flagged}, "al_form40_2023": {"all_flagged": True}},
            "disagreements": {"count": len(dis)}, "unscored_sample": {"size": len(sample)}}


def test_adjudication_joins_by_id_and_decides_passed():
    runs = _fixture()
    dis = B.disagreement_rows(runs, [])
    sample = B.unscored_sample(runs)
    assert [r.widget.field for r, _ in dis] == ["rotated", "wrong", "unclear"] or len(dis) == 3
    ids = {r.widget.field: r.id for r, _ in dis}
    adj = {"items": [{"id": ids["rotated"], "seen_line": "21", "ambiguous": False, "reason": "row 21"},
                     {"id": ids["wrong"], "seen_line": "6", "ambiguous": False, "reason": "row 6"},
                     {"id": ids["unclear"], "seen_line": None, "ambiguous": True, "reason": "column letter"}],
           "unscored_sample": [{"id": sample[0].id, "seen_line": "9", "ambiguous": False, "reason": "row 9"}]}
    out = B.adjudicate(runs, dis, sample, adj)
    top = out["tiers"]["top"]
    assert (top["right"], top["wrong"], top["ambiguous"], top["unadjudicated"]) == (301, 1, 1, 0)
    assert top["precision"] == round(301 / 302, 4)
    assert out["pack_keys_not_the_printed_line"] == [ids["rotated"]]
    assert out["unscored_sample"]["precision"] == 1.0
    table = B.build_table(_measured(runs, dis, sample), out, {"test_runs": 1, "history": []})
    assert table["passed"] is True and table["adjudicated"] == 3
    # one item left unadjudicated, a mandatory case missed, or too few packs: not passed
    partial = B.adjudicate(runs, dis, sample, {"items": adj["items"][:2], "unscored_sample": []})
    assert B.build_table(_measured(runs, dis, sample), partial, {"test_runs": 1, "history": []})["passed"] is False
    assert B.build_table(_measured(runs, dis, sample, flagged=False), out,
                         {"test_runs": 1, "history": []})["passed"] is False
    small = _fixture(29)
    assert B.build_table(_measured(small, dis, sample), out, {"test_runs": 1, "history": []})["passed"] is False
    assert B.build_table(_measured(runs, dis, sample), None, {"test_runs": 1, "history": []})["passed"] is False


def test_finalize_and_check_run_end_to_end_on_a_fixture(tmp_path, monkeypatch):
    runs = _fixture()
    dis = B.disagreement_rows(runs, [])
    sample = B.unscored_sample(runs)
    measured = _measured(runs, dis, sample)
    monkeypatch.setattr(B, "measure", lambda sel: (measured, [], runs, []))
    monkeypatch.setattr(B, "load_selection", lambda: {"dev": [], "test": []})
    for name in ("TABLE", "ADJUDICATIONS"):
        monkeypatch.setattr(B, name, tmp_path / f"{name.lower()}.yaml")
    B.write_table(B.build_table(measured, None, {"test_runs": 1, "history": [{"run": 1, "note": "fixture"}]}))
    adj = {"items": [{"id": r.id, "seen_line": r.widget.printed_line, "ambiguous": False, "reason": "seen"}
                     for r, _ in dis],
           "unscored_sample": [{"id": r.id, "seen_line": r.widget.printed_line, "ambiguous": False, "reason": "seen"}
                               for r in sample]}
    B.ADJUDICATIONS.write_text(yaml.safe_dump(adj), encoding="utf-8")
    assert B.main(["--finalize"]) == 0
    table = yaml.safe_load(B.TABLE.read_text(encoding="utf-8"))
    assert table["passed"] is True and table["adjudicated"] == 3 and table["test_runs"] == 1
    assert table["adjudication"]["tiers"]["top"]["precision"] == 1.0
    licensed = A._licensed(table)
    assert {k: licensed[k] for k in ("top", "med")} == {"top": B.THRESHOLDS["top"], "med": B.THRESHOLDS["med"]}
    assert licensed["top_kinds"] == frozenset(table["top_tier_kinds"])  # the groups the fixture measured >= 0.99
    assert B.main(["--check"]) == 0
    B.ADJUDICATIONS.write_text(yaml.safe_dump({"items": adj["items"][:1], "unscored_sample": []}), encoding="utf-8")
    assert B.main(["--check"]) == 1  # the committed table no longer matches a recomputation


def test_an_adjudication_for_an_unknown_id_is_refused(tmp_path, monkeypatch):
    runs = _fixture()
    measured = _measured(runs, [], [])
    monkeypatch.setattr(B, "measure", lambda sel: (measured, [], runs, []))
    monkeypatch.setattr(B, "load_selection", lambda: {"dev": [], "test": []})
    for name in ("TABLE", "ADJUDICATIONS"):
        monkeypatch.setattr(B, name, tmp_path / f"{name.lower()}.yaml")
    B.write_table(B.build_table(measured, None, {"test_runs": 1, "history": []}))
    B.ADJUDICATIONS.write_text(yaml.safe_dump({"items": [{"id": "x:p1:f:w0", "seen_line": "1", "ambiguous": False,
                                                          "reason": "?"}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="not current disagreements"):
        B.main(["--finalize"])


def test_the_table_and_adjudications_live_where_the_wheel_stages_them_and_no_gate_reads_them_as_packs():
    from taxfill_core.datadir import knowledge_dir

    assert B.TABLE.parent == knowledge_dir() / "anchor" == A.table_path().parent
    staged = {p.suffix for p in (REPO / "knowledge" / "anchor").rglob("*") if p.is_file()}
    assert staged <= {".yaml"}  # scripts/stage_data.py copies .yaml/.yml/.md
    assert not list((REPO / "knowledge" / "anchor").rglob("pack.yaml"))
    adj = yaml.safe_load(B.ADJUDICATIONS.read_text(encoding="utf-8"))
    # retired_unscored_sample keeps run-1 sample verdicts whose ids the current method no longer samples (never joined);
    # retired_items keeps verdicts on disagreements a later pack re-key removed (Phase K JK10, 2026-10-24; never joined)
    assert {"items", "unscored_sample"} <= set(adj) <= {"items", "unscored_sample", "retired_unscored_sample",
                                                         "retired_items"}
    live = {e["id"] for e in adj["items"]}
    assert not live & {e["id"] for e in adj.get("retired_items") or []}, "a retired verdict is still joined"


# ── network: the committed fixtures and tables against the real cached blanks ──


def _ensure(url: str, sha: str) -> Path:
    from taxfill_core.fetch import FetchError, fetch_blank

    try:
        return fetch_blank(url, sha256=sha)
    except (FetchError, OSError) as exc:  # pragma: no cover — offline
        pytest.skip(f"blank not available: {exc}")


@pytest.mark.network
def test_both_mandatory_cases_are_flagged_exactly():
    for case in B.load_mandatory():
        _ensure(case["source_url"], case["pdf_sha256"])
        run, result = B.run_mandatory(case)
        assert result["all_flagged"], result["missed"]
        assert sorted(d["key"] for d in result["detail"]) == sorted(case["must_flag"])
        assert set(case["must_flag"]) == MUST_FLAG[case["case"]]  # the fixture cannot quietly shrink its own list
        if case["case"] == "me_1040me_2023":
            got = {r.widget.field: r.widget.printed_line for r in run.rows if r.status == "disagree"}
            assert got == {"1040ME Total tax": "21", "1040ME Tax credits": "22", "1040ME Nonresident credit": "23"}


# Phase K JK15 (2026-10-24): the shifted keys of each mandatory case, written out here rather than read back from the
# fixture. AL Form 40 2023 before P-031 sat one number high from 20a on: 15 keys.
MUST_FLAG = {
    "me_1040me_2023": {"21", "22", "23"},
    "al_form40_2023": {"20_amount", "21_amount", *(str(n) for n in range(22, 34)), "34_total_donations"},
}


def test_the_hard_coded_mandatory_lists_match_the_fixtures():
    assert len(MUST_FLAG["al_form40_2023"]) == 15
    assert {c["case"]: set(c["must_flag"]) for c in B.load_mandatory()} == MUST_FLAG


@pytest.mark.network
def test_spot_check_a_federal_and_a_state_blank():
    from taxfill_core.schemas.formpack import load_pack

    fed = load_pack(REPO / "formpacks" / "federal" / "2025" / "f1040" / "pack.yaml")
    w = {a.field: a for a in A.raw_anchors(_ensure(fed.source_url, fed.pdf_sha256))}
    line_1a = w["topmostSubform[0].Page1[0].f1_47[0]"]
    assert line_1a.printed_line == "1a" and A.tier_for(line_1a, B.MEASURE_THRESHOLDS) == A.TOP
    me = load_pack(REPO / "formpacks" / "states" / "me" / "2025" / "f1040me" / "pack.yaml")
    w = {a.field: a for a in A.raw_anchors(_ensure(me.source_url, me.pdf_sha256))}
    assert w["1040ME Total tax"].printed_line == "21" and "tu_words_other_row" in w["1040ME Total tax"].evidence
    assert A.tier_for(w["1040ME Total tax"], B.MEASURE_THRESHOLDS) == A.LOW
    assert w["1040ME Net tax"].printed_line == "24" and A.tier_for(w["1040ME Net tax"], B.MEASURE_THRESHOLDS) == A.TOP


@pytest.mark.network
def test_the_committed_table_matches_a_recomputation():
    adj = B.load_adjudications()
    if not (adj["items"] or adj["unscored_sample"]):
        pytest.skip("knowledge/anchor/adjudications.yaml is still empty: the blind adjudication has not run")
    sel = B.load_selection()
    for item in sel["dev"] + sel["test"]:
        _ensure(*_url_sha(item["pack"]))
    assert B.main(["--check"]) == 0


def _url_sha(pid: str) -> tuple[str, str]:
    from taxfill_core.schemas.formpack import load_pack

    pack = load_pack(REPO / "formpacks" / pid / "pack.yaml")
    return pack.source_url, pack.pdf_sha256


def test_the_adjudication_join_compares_designators_not_spellings():
    """Phase K JK15 finalize fix: an adjudicator who copies the printed "6C" agrees with the anchor's normalised "6c"
    (AZ Form 140NR line 6C was scored wrong on the spelling alone)."""
    assert B._seen({"seen_line": "6C"}) == "6c"
    assert B._seen({"seen_line": "21."}) == "21"
    assert B._seen({"seen_line": None}) is None
    assert B._seen({"seen_line": "Part II"}) == "Part II"  # not a designator: compared as written


# ── Phase K JK15 (2026-10-24) round 2: what the table reports ───────────────


def test_wilson_interval():
    assert B.wilson(0, 0) is None
    assert B.wilson(10, 10) == [round(10 / (10 + B.WILSON_Z ** 2), 4), 1.0]  # p = 1: the lower bound is n / (n + z^2)
    lo, hi = B.wilson(301, 302)
    assert lo < 301 / 302 < hi <= 1.0


def test_the_adjudication_reports_scored_sample_combined_and_checkboxes_apart():
    runs = _fixture()
    box = _row(runs[5].pack, "box", "3", {"3"})
    box.widget.kind = "checkbox"
    runs[5].rows.append(box)
    for i, kind in enumerate(("checkbox", "radio")):  # unscored top-tier buttons: never sampled, never in the estimate
        button = _row(runs[6 + i].pack, f"button{i}", "4", set())
        button.widget.kind = kind
        runs[6 + i].rows.append(button)
    dis = B.disagreement_rows(runs, [])
    sample = B.unscored_sample(runs)
    ids = {r.widget.field: r.id for r, _ in dis}
    adj = {"items": [{"id": ids["rotated"], "seen_line": "21", "ambiguous": False, "reason": "row 21"},
                     {"id": ids["wrong"], "seen_line": "5", "ambiguous": False, "reason": "row 5"},
                     {"id": ids["unclear"], "seen_line": "7", "ambiguous": False, "reason": "row 7"}],
           "unscored_sample": [{"id": sample[0].id, "seen_line": "8", "ambiguous": False, "reason": "row 8"}]}
    out = B.adjudicate(runs, dis, sample, adj)
    top = out["tiers"]["top"]
    assert (top["right"], top["wrong"]) == (304, 0) and top["wilson_95"] == B.wilson(304, 304)
    assert out["top_by_kind"]["checkbox"]["scored"] == 1 and out["top_by_kind"]["text"]["scored"] == 303
    s = out["unscored_sample"]
    assert [r.widget.field for r in sample] == ["nolist"] and s["groups"] == ["text"]
    assert (s["size"], s["population"], s["right"], s["wrong"], s["precision"]) == (1, 1, 0, 1, 0.0)
    assert s["wilson_95"] == B.wilson(0, 1)
    # the sample's anchor_wrong widget makes its form a mis-anchored top-tier form
    assert out["forms_with_a_mis_anchored_top_widget"] == [sample[0].pack]
    assert out["per_form_any_mis_anchored_top_rate"] == round(1 / 30, 4)
    # Phase K JK15 round 3: the combined estimate covers the licensable group (text) only: 303 scored text boxes
    # (the checkbox's 1 scored widget is left out) and 1 unscored text box
    comb = out["combined_top_estimate"]
    assert comb["groups"] == ["text"] and comb["scored_n"] == 303 and comb["unscored_population"] == 1
    assert comb["weights"] == {"scored": round(303 / 304, 4), "unscored": round(1 / 304, 4)}
    assert comb["precision"] == round(303 / 304, 4)
    lo_s, hi_s = B.wilson(303, 303)
    lo_u, hi_u = B.wilson(0, 1)
    w_s = 303 / 304
    assert comb["wilson_95"] == [round(w_s * lo_s + (1 - w_s) * lo_u, 4), round(w_s * hi_s + (1 - w_s) * hi_u, 4)]
    table = B.build_table(_measured(runs, dis, sample), out, {"test_runs": 1, "history": []})
    # the checkbox group measured 1/1, yet only the sampled group can be licensed
    assert out["top_by_kind"]["checkbox"]["precision"] == 1.0 and table["top_tier_kinds"] == ["text"]
    assert "scored_top_tier_precision_at_least_0.99" in table["criteria"] and table["passed"] is True
    notes = " ".join(table["notes"])
    for phrase in ("SCORED top-tier precision", "one blind read per item", "sharded across adjudicators",
                   "covers the top tier of the licensable group", "multi-column row", "Checkbox and radio",
                   "mandatory", "text boxes only", "Row identification", "immediately before the box",
                   "shared_row:<field>", "One-to-one rule", "same_line:<field>"):
        assert phrase in notes, phrase


def test_the_per_form_rate_covers_the_licensable_group_only():
    """Phase K JK15 round 4 (2026-10-24): the per-form 'any mis-anchored' rate is computed over the text group, like
    the sample: a form whose only mis-anchored top-tier widget is a checkbox does not count in the numerator, and a
    form whose only top-tier widgets are checkboxes does not count in the denominator."""
    runs = _fixture()
    box = _row(runs[4].pack, "boxwrong", "3", {"4"})
    box.widget.kind = "checkbox"
    runs[4].rows.append(box)
    only = B.PackRun(pack="states/s99/2025/fbox", blank=Path("b.pdf"))
    button = _row(only.pack, "box", "2", {"2"})
    button.widget.kind = "checkbox"
    only.rows = [button]
    runs.append(only)
    dis = B.disagreement_rows(runs, [])
    sample = B.unscored_sample(runs)
    ids = {r.widget.field: r.id for r, _ in dis}
    adj = {"items": [{"id": ids["rotated"], "seen_line": "21", "ambiguous": False, "reason": "row 21"},
                     {"id": ids["wrong"], "seen_line": "6", "ambiguous": False, "reason": "row 6"},
                     {"id": ids["unclear"], "seen_line": None, "ambiguous": True, "reason": "column letter"},
                     {"id": ids["boxwrong"], "seen_line": "4", "ambiguous": False, "reason": "row 4"}],
           "unscored_sample": [{"id": sample[0].id, "seen_line": "9", "ambiguous": False, "reason": "row 9"}]}
    out = B.adjudicate(runs, dis, sample, adj)
    assert out["top_by_kind"]["checkbox"]["wrong"] == 1  # still reported, apart
    assert out["forms_with_a_mis_anchored_top_widget"] == [runs[1].pack]
    assert out["per_form_any_mis_anchored_top_rate"] == round(1 / 30, 4)
    rep = B.report(runs)
    assert rep["forms_with_top_tier"] == 30 and rep["forms_with_a_mis_anchored_top_widget"] == 3
    assert rep["per_form_any_mis_anchored_top_rate"] == round(3 / 30, 4)


def test_a_test_run_records_events_and_check_accepts_a_table_not_yet_finalized(tmp_path, monkeypatch):
    runs = _fixture()
    dis = B.disagreement_rows(runs, [])
    sample = B.unscored_sample(runs)
    measured = _measured(runs, dis, sample)
    monkeypatch.setattr(B, "measure", lambda sel: (measured, [], runs, []))
    monkeypatch.setattr(B, "load_selection", lambda: {"dev": [], "test": []})
    monkeypatch.setattr(B, "write_outputs", lambda out, d, s: None)
    for name in ("TABLE", "ADJUDICATIONS"):
        monkeypatch.setattr(B, name, tmp_path / f"{name.lower()}.yaml")
    B.write_table(B.build_table(measured, None, {"test_runs": 1, "history": [{"run": 1, "note": "first"}]}))
    B.ADJUDICATIONS.write_text(yaml.safe_dump({"items": [{"id": dis[0][0].id, "seen_line": "21", "ambiguous": False,
                                                          "reason": "seen"}], "unscored_sample": []}), encoding="utf-8")
    assert B.main(["--test", "--out", str(tmp_path / "out"), "--note", "method v2",
                   "--event", "finalize join normalises designators (6C equals 6c)"]) == 0
    table = yaml.safe_load(B.TABLE.read_text(encoding="utf-8"))
    assert table["test_runs"] == 2 and table["passed"] is False and table["adjudication"] is None
    assert [h.get("run") or h.get("event") for h in table["history"]] == [
        1, "finalize join normalises designators (6C equals 6c)", 2]
    assert table["history"][-1]["note"] == "method v2" and table["history"][-1]["method"] == A.METHOD
    assert B.main(["--check"]) == 0  # the adjudications on file are for --finalize, not for this table


def test_the_selection_discloses_siblings_across_the_split_and_the_mandatory_families():
    sel = B.load_selection()
    dev = {i["family"] for i in sel["dev"]}
    test = {i["family"] for i in sel["test"]}
    pairs = {(x["dev"], x["test"]) for x in sel["disclosure"]["siblings_across_split"]}
    assert pairs == {("states/al/al40", "states/al/al40nr"), ("states/ca/form540", "states/ca/form540nr"),
                     ("federal/sched_a", "federal/sched_a_nr")}
    assert all(d in dev and t in test for d, t in pairs)
    # every pair of selected families whose names differ only by a nr/pn/py suffix is disclosed somewhere
    listed = pairs | {(row[1], f) for row in sel["disclosure"]["siblings_same_side"] for f in row[2:]}
    for a in dev | test:
        for b in dev | test:
            if b != a and b.startswith(a) and re.fullmatch(r"_?(nr|pn|py|non)", b[len(a):]):
                assert (a, b) in listed, (a, b)
    assert {(m["case"], m["family"]) for m in sel["disclosure"]["mandatory_cases_in_dev_families"]} == {
        ("me_1040me_2023", "states/me/f1040me"), ("al_form40_2023", "states/al/al40")}
    assert {"states/me/f1040me", "states/al/al40"} <= dev
