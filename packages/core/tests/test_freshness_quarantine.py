"""Phase J JT0c: the freshness quarantine (scripts/freshness_quarantine.*) and the finals watch
(scripts/check_finals.py) — offline."""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import re
import subprocess
import sys
import textwrap
import urllib.error
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fq = _load("freshness_quarantine")
cd = _load("check_drift")
cf = _load("check_finals")

DC_BOOKLET = ("https://otr.cfo.dc.gov/sites/default/files/dc/sites/otr/publication/attachments/"
              "2025_D40_Book_Final_wLinks_030526_v1.0.pdf")


# ── the quarantine file ──────────────────────────────────────────────────────


# JK2 (2026-10-15): the ten MA Form 1 network tests the GitHub-hosted runner cannot fetch for — mass.gov answers
# 403 and the pack's Wayback mirror 429 / connection refused — until the CI blank cache has served them green on
# two consecutive weekly runs. Pinned exactly, so deleting the rows (or adding one) must revisit this test.
# JK27 (2026-10-16): twelve — the /FT /Sig every-pack sweep (test_signature_widget_mapping.py) adds its two MA cases.
# JK28 (2026-10-16): twenty — test_pack_maxlen.py's MEASURED_WITHOUT_MAXLEN network check adds the six rows of the
# MA signature-date and line 43c boxes (2023 and 2025), and the ink-signature tooltip sweep
# (test_signature_line_mapping.py) its two MA cases.
MA_FORM1_NETWORK_TESTS = frozenset(
    f"packages/core/tests/{module}::{func}[{param}]"
    for module, func, params in (
        ("test_formpacks_states.py", "test_state_pack_golden_roundtrip", ("ma_2023_form1", "ma_2025_form1")),
        ("test_pack_maxlen.py", "test_pack_maxlen_never_exceeds_the_widget_and_tracks_it",
         ("states-ma-2023-form1", "states-ma-2025-form1")),
        ("test_pack_maxlen.py", "test_every_tighter_budget_row_is_still_tighter",
         ("states/ma/2023/form1-43a", "states/ma/2025/form1-43a")),
        ("test_readonly_widget_mapping.py", "test_state_pack_readonly_mapped_count_matches_the_pinned_audit",
         ("states-ma-2023-form1", "states-ma-2025-form1")),
        ("test_readonly_widget_mapping.py", "test_every_nonzero_readonly_default_is_adjudicated_class_4",
         ("states-ma-2023-form1", "states-ma-2025-form1")),
        ("test_signature_widget_mapping.py", "test_pack_maps_no_digital_signature_widget",
         ("states-ma-2023-form1", "states-ma-2025-form1")),
        ("test_signature_line_mapping.py", "test_pack_maps_no_signature_line_by_its_tooltip",
         ("states-ma-2023-form1", "states-ma-2025-form1")),
        ("test_pack_maxlen.py", "test_every_measured_budget_row_still_describes_its_widget",
         tuple(f"states/ma/{y}/form1-{line}" for y in (2023, 2025)
               for line in ("tp_signature_date", "spouse_signature_date", "43_multiplier"))),
    )
    for param in params
)


# JK30 (2026-10-24): uscode.house.gov "is currently operating in a temporary format", and the view.xhtml section pages
# the source registries cite answer HTTP 404. The rows cover all of them or none: the whole service is down.
def _registry_uscode_view_urls() -> set[str]:
    """Every uscode.house.gov view.xhtml URL the two source registries cite (what check_drift probes)."""
    text = "".join((REPO / "knowledge" / name).read_text(encoding="utf-8") for name in ("sources.yaml", "sources_states.yaml"))
    return set(re.findall(r"https://uscode\.house\.gov/view\.xhtml\?[^\s\"']+", text))


def test_the_quarantine_names_real_targets_each_with_an_expiry_and_a_fix():
    entries = fq.load()
    assert {e.fixed_by for e in entries} == {"JK2", "JK30"}  # JS1a/JS1b/JS5 retired theirs; JK2's rows self-clear
    knowledge = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "knowledge").rglob("*.yaml"))
    knowledge += "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "formpacks").rglob("pack.yaml"))
    for e in entries:
        assert e.expires <= e.added + dt.timedelta(days=fq.MAX_DAYS)
        if e.kind == "network_test":
            path, _, rest = e.target.partition("::")
            func = rest.split("[", 1)[0]
            assert f"def {func}(" in (REPO / path).read_text(encoding="utf-8"), e.target
        else:
            assert e.target in knowledge, f"quarantined URL no longer cited anywhere — delete the row: {e.target}"
    # JS1b's acceptance (every blank fetch green) holds on a developer machine; from the GitHub-hosted runner the
    # two MA packs are served only by the CI blank cache, so exactly their twenty node ids are quarantined (JK2,
    # JK27, JK28).
    assert {e.target for e in entries if e.kind == "network_test"} == MA_FORM1_NETWORK_TESTS
    # The MN M1 booklet move was FIXED (new URL), not quarantined. The only drift rows are JK30's (2026-10-24): the
    # uscode.house.gov view.xhtml section pages the source registries cite, while that site runs in a temporary format.
    drift = [e for e in entries if e.kind == "drift"]
    assert not drift or {e.target for e in drift} == _registry_uscode_view_urls()
    assert all(e.fixed_by == "JK30" and e.expires == dt.date(2026, 12, 15) for e in drift)
    assert all("temporary format" in e.why and "govinfo.gov" in e.why for e in drift)
    assert {e.added for e in entries} == {dt.date(2026, 10, 15), dt.date(2026, 10, 16), dt.date(2026, 10, 24)}
    assert all("mass.gov" in e.why and "mirror" in e.why and "cache" in e.why
               for e in entries if e.kind == "network_test")


@pytest.mark.parametrize(("row", "message"), [
    ({"kind": "flaky"}, "kind must be one of"),
    ({"kind": "drift", "added": "2026-09-27", "expires": "2026-10-27", "fixed_by": "JS1a", "why": "x"}, "names its url"),
    ({"kind": "drift", "url": "u", "added": "2026-09-27", "expires": "2027-09-27", "fixed_by": "JS1a", "why": "x"},
     "within 200 days"),
    ({"kind": "drift", "url": "u", "added": "2026-09-27", "expires": "2026-10-27", "why": "x"}, "fixed_by"),
    ({"kind": "drift", "url": "u", "added": "27 Sep", "expires": "2026-10-27", "fixed_by": "JS1a", "why": "x"},
     "not an ISO date"),
])
def test_a_malformed_row_is_refused(tmp_path: Path, row: dict, message: str):
    path = tmp_path / "q.yaml"
    path.write_text(yaml.safe_dump({"entries": [row]}))
    with pytest.raises(ValueError, match=message):
        fq.load(path)


# ── network tests: only a NEW red fails ──────────────────────────────────────


def _run_pytest(tmp_path: Path, quarantine: list[dict], *extra: str) -> subprocess.CompletedProcess:
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    network: live .gov access\n")
    (tmp_path / "conftest.py").write_text(textwrap.dedent(f"""
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location("taxfill_root_conftest", {str(REPO / "packages" / "conftest.py")!r})
        root = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = root
        spec.loader.exec_module(root)
        pytest_collection_modifyitems = root.pytest_collection_modifyitems
    """))
    (tmp_path / "test_q.py").write_text(textwrap.dedent("""
        import pytest
        from taxfill_core.fetch import FetchError

        @pytest.mark.network
        def test_known_red():
            raise FetchError("HTTP 403 (Forbidden)")

        @pytest.mark.network
        def test_new_red():
            raise FetchError("HTTP 404 (Not Found)")

        @pytest.mark.network
        def test_known_but_broken():
            assert 1 == 2

        @pytest.mark.network
        def test_expired_red():
            raise FetchError("HTTP 403 (Forbidden)")
    """))
    qfile = tmp_path / "quarantine.yaml"
    qfile.write_text(yaml.safe_dump({"entries": quarantine}))
    env = {**os.environ, "TAXFILL_FRESHNESS_QUARANTINE": str(qfile)}
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rA", *extra],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


def test_a_new_failing_network_test_fails_freshness_while_the_quarantined_one_does_not(tmp_path: Path):
    today = dt.date.today()
    active = {"added": str(today - dt.timedelta(days=1)), "expires": str(today + dt.timedelta(days=30)),
              "fixed_by": "JS1b", "why": "a 403 the runner cannot get past"}
    quarantine = [
        {"kind": "network_test", "id": "test_q.py::test_known_red", **active},
        {"kind": "network_test", "id": "test_q.py::test_known_but_broken", **active},
        {"kind": "network_test", "id": "test_q.py::test_expired_red", "added": "2020-01-01",
         "expires": "2020-02-01", "fixed_by": "JS1b", "why": "long gone"},
    ]
    run = _run_pytest(tmp_path, quarantine)
    out = run.stdout
    assert run.returncode == 1, out
    assert "XFAIL test_q.py::test_known_red" in out
    assert "FAILED test_q.py::test_new_red" in out            # not on the allowlist
    assert "FAILED test_q.py::test_known_but_broken" in out   # the quarantine masks a FETCH failure only
    assert "FAILED test_q.py::test_expired_red" in out        # an expired row quarantines nothing
    # With only the allowlisted red selected, the network layer is green.
    alone = _run_pytest(tmp_path, quarantine, "-k", "known_red")
    assert alone.returncode == 0, alone.stdout


# ── check_drift: the DC row, a new drift, an expired row ────────────────────


def _drift(monkeypatch, items: list[str]) -> None:
    monkeypatch.setattr(cd, "check_form_blanks", lambda: [])
    monkeypatch.setattr(cd, "check_source_urls", lambda: [])
    monkeypatch.setattr(cd, "check_mailing_addresses", lambda: list(items))


def test_check_drift_quarantines_the_known_red_but_fails_a_new_one(monkeypatch, capsys, tmp_path):
    # A synthetic drift row (the live file's last one, the DC booklet, retired with JS1a on 2026-09-28).
    (tmp_path / "q.yaml").write_text(yaml.safe_dump({"entries": [{
        "kind": "drift", "url": DC_BOOKLET, "added": "2026-09-27", "expires": "2027-03-31", "fixed_by": "JS1a",
        "why": "the DC 2025 booklet 404"}]}), encoding="utf-8")
    monkeypatch.setenv("TAXFILL_FRESHNESS_QUARANTINE", str(tmp_path / "q.yaml"))
    known = f"Mailing addresses / where-to-file: {DC_BOOKLET} -> HTTP 404"
    _drift(monkeypatch, [known])
    assert cd.main(today=dt.date(2026, 10, 5)) == 0
    assert "QUARANTINED" in capsys.readouterr().out
    _drift(monkeypatch, [known, "Source registry: https://www.irs.gov/moved -> HTTP 404"])
    assert cd.main(today=dt.date(2026, 10, 5)) == 1


def test_an_expired_quarantine_row_fails_the_drift_job(monkeypatch, capsys, tmp_path):
    # A synthetic row, so the test does not move with the live file's own expiries (JS5 retired the last drift
    # row; JK2's rows are network_test rows and an expired one fails the drift job the same way).
    (tmp_path / "q.yaml").write_text(yaml.safe_dump({"entries": [{
        "kind": "drift", "url": DC_BOOKLET, "added": "2026-09-27", "expires": "2027-03-31", "fixed_by": "JS1a",
        "why": "the DC 2025 booklet 404"}]}), encoding="utf-8")
    monkeypatch.setenv("TAXFILL_FRESHNESS_QUARANTINE", str(tmp_path / "q.yaml"))
    _drift(monkeypatch, [])
    expiry = max(e.expires for e in fq.load())
    assert cd.main(today=expiry) == 0
    assert cd.main(today=expiry + dt.timedelta(days=1)) == 1
    assert "EXPIRED" in capsys.readouterr().out


# ── the finals watch ─────────────────────────────────────────────────────────


def _draft_repo(tmp_path: Path) -> Path:
    pack = {
        "form": "1040 (Schedule 1-A)", "jurisdiction": "federal", "tax_year": 2026,
        "source_url": "https://www.irs.gov/pub/irs-dft/f1040s1a--dft.pdf", "pdf_sha256": "...",
        "acroform_root": "topmostSubform[0]", "source_status": "draft", "draft_created": "6/16/26",
        "fields": [{"line": "name", "field": "Page1[0].f1_1[0]", "type": "text"}],
    }
    folder = tmp_path / "formpacks" / "federal" / "2026" / "sched_1a"
    folder.mkdir(parents=True)
    (folder / "pack.yaml").write_text(yaml.safe_dump(pack))
    return tmp_path


def test_the_watch_list_is_every_draft_pack_plus_the_publications(tmp_path: Path):
    watched = cf.watch_list(2026, repo=_draft_repo(tmp_path))
    assert [w.stem for w in watched] == ["f1040s1a", "p1040", "i1040gi", "p501"]
    assert "Created 6/16/26" in watched[0].why
    assert watched[0].final_url(2026) == "https://www.irs.gov/pub/irs-prior/f1040s1a--2026.pdf"
    assert cf.provisional_year() == 2026  # the shipped 2026 federal pack is planning-only


class _Runner:
    """A fake `gh`: records each call, answers `issue list` / `issue view` from a script."""

    def __init__(self, open_issue: str = "", body: str = ""):
        self.calls: list[list[str]] = []
        self.open_issue, self.body = open_issue, body

    def __call__(self, cmd, check, capture_output, text):
        self.calls.append(cmd[1:])
        out = self.open_issue if cmd[1:3] == ["issue", "list"] else self.body if cmd[1:3] == ["issue", "view"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out)


def _head(posted: set[str]):
    return lambda url: 200 if any(f"/{s}--" in url for s in posted) else 404


def test_check_finals_dry_run_prints_the_repin_list_and_the_issue_and_files_nothing(monkeypatch, capsys):
    runner = _Runner()
    assert cf.main(["--dry-run"], head=_head({"i1040gi"}), runner=runner) == 0
    out = capsys.readouterr().out
    assert "Re-pin list (1): i1040gi" in out
    assert "gh issue create" in out and '"ty2026-finals: re-pin now"' in out
    assert "https://www.irs.gov/pub/irs-prior/i1040gi--2026.pdf" in out
    assert runner.calls == []
    # --assume-posted rehearses the same issue with nothing posted.
    assert cf.main(["--dry-run", "--assume-posted", "p501"], head=_head(set()), runner=runner) == 0
    assert "Re-pin list (1): p501" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cf.main(["--assume-posted", "p501"], head=_head(set()), runner=runner)


def test_check_finals_opens_one_issue_then_updates_it_only_when_the_list_changes(capsys):
    fresh = _Runner()
    assert cf.main([], head=_head({"p1040"}), runner=fresh) == 0
    assert [c[:2] for c in fresh.calls] == [["label", "create"], ["issue", "list"], ["issue", "create"]]
    body = fresh.calls[-1][fresh.calls[-1].index("--body") + 1]
    same = _Runner(open_issue="12", body=body)
    assert cf.main([], head=_head({"p1040"}), runner=same) == 0
    assert [c[:2] for c in same.calls] == [["label", "create"], ["issue", "list"], ["issue", "view"]]
    grown = _Runner(open_issue="12", body=body)
    assert cf.main([], head=_head({"p1040", "p501"}), runner=grown) == 0
    assert [c[:2] for c in grown.calls][-2:] == [["issue", "edit"], ["issue", "comment"]]


def _head_answers(monkeypatch, script: list) -> tuple[list[str], list[float]]:
    """cf.urllib.request.urlopen pops the next scripted answer (an exception to raise, or a status to return);
    returns (urls seen, backoffs that would have been slept)."""
    seen: list[str] = []
    sleeps: list[float] = []

    class _Resp:
        def __init__(self, code):
            self.code = code

        def getcode(self):
            return self.code

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        seen.append(req.full_url)
        answer = script.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return _Resp(answer)

    monkeypatch.setattr(cf.urllib.request, "urlopen", urlopen)
    return seen, sleeps


U = "https://www.irs.gov/pub/irs-prior/p1040--2026.pdf"


def _503(url: str = U) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)


def test_jk2_head_status_retries_a_5xx_or_a_timeout_but_not_a_404(monkeypatch):
    seen, sleeps = _head_answers(monkeypatch, [_503(), 200])
    assert cf.head_status("https://www.irs.gov/pub/irs-prior/p1040--2026.pdf", sleep=sleeps.append) == 200
    assert len(seen) == 2 and sleeps == [2.0]
    seen, sleeps = _head_answers(monkeypatch, [_503(), urllib.error.URLError(TimeoutError("timed out")), 404])
    assert cf.head_status(U, sleep=sleeps.append) == 404
    assert len(seen) == 3 and sleeps == [2.0, 6.0]
    seen, sleeps = _head_answers(monkeypatch, [urllib.error.HTTPError(U, 404, "Not Found", {}, None), 200])
    assert cf.head_status(U, sleep=sleeps.append) == 404                        # an answer: never retried
    assert len(seen) == 1 and sleeps == []
    seen, sleeps = _head_answers(monkeypatch, [_503()] * 3)
    assert cf.head_status(U, sleep=sleeps.append) == 503                        # exhausted: the status comes back
    assert len(seen) == 3 and sleeps == [2.0, 6.0]
    seen, sleeps = _head_answers(monkeypatch, [urllib.error.URLError(OSError("Network is unreachable"))] * 3)
    with pytest.raises(urllib.error.URLError):                                  # exhausted: the failure is raised
        cf.head_status(U, sleep=sleeps.append)
    assert len(seen) == 3 and sleeps == [2.0, 6.0]


def test_jk2_one_503_then_200_is_posted_and_three_503s_are_an_error(monkeypatch, capsys):
    watched = [cf.Watched("p1040", "publication")]
    _, sleeps = _head_answers(monkeypatch, [_503(), 200])
    result = cf.run_watch(2026, watched, head=lambda url: cf.head_status(url, sleep=sleeps.append))
    assert [w.stem for w in result.posted] == ["p1040"] and result.errors == []
    assert "POSTED" in capsys.readouterr().out and sleeps == [2.0]
    _, sleeps = _head_answers(monkeypatch, [_503()] * 3)
    result = cf.run_watch(2026, watched, head=lambda url: cf.head_status(url, sleep=sleeps.append))
    assert result.posted == [] and result.errors == ["https://www.irs.gov/pub/irs-prior/p1040--2026.pdf: HTTP 503"]
    assert "ERROR" in capsys.readouterr().out and sleeps == [2.0, 6.0]
    _, sleeps = _head_answers(monkeypatch, [urllib.error.URLError(TimeoutError("timed out"))] * 3)
    result = cf.run_watch(2026, watched, head=lambda url: cf.head_status(url, sleep=sleeps.append))
    assert len(result.errors) == 1 and "timed out" in result.errors[0] and sleeps == [2.0, 6.0]


def test_check_finals_nothing_posted_files_nothing_and_a_blind_watch_fails(capsys):
    runner = _Runner()
    assert cf.main([], head=_head(set()), runner=runner) == 0
    assert runner.calls == [] and "none yet" in capsys.readouterr().out
    assert cf.main([], head=lambda url: 403, runner=runner) == 1
    assert "WATCH BLIND" in capsys.readouterr().out
