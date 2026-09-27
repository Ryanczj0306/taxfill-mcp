"""Phase J JT0c: the freshness quarantine (scripts/freshness_quarantine.*) and the finals watch
(scripts/check_finals.py) — offline."""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import subprocess
import sys
import textwrap
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


def test_the_quarantine_names_real_targets_each_with_an_expiry_and_a_fix():
    entries = fq.load()
    assert {e.fixed_by for e in entries} <= {"JS1a", "JS1b"}
    knowledge = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "knowledge").rglob("*.yaml"))
    for e in entries:
        assert e.expires <= e.added + dt.timedelta(days=fq.MAX_DAYS)
        if e.kind == "network_test":
            path, _, rest = e.target.partition("::")
            func = rest.split("[", 1)[0]
            assert f"def {func}(" in (REPO / path).read_text(encoding="utf-8"), e.target
        else:
            assert e.target in knowledge, f"quarantined URL no longer cited anywhere — delete the row: {e.target}"


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
        spec = importlib.util.spec_from_file_location("taxfill_root_conftest", {str(REPO / "conftest.py")!r})
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


def test_check_drift_quarantines_the_known_red_but_fails_a_new_one(monkeypatch, capsys):
    known = f"Mailing addresses / where-to-file: {DC_BOOKLET} -> HTTP 404"
    _drift(monkeypatch, [known])
    assert cd.main(today=dt.date(2026, 10, 5)) == 0
    assert "QUARANTINED" in capsys.readouterr().out
    _drift(monkeypatch, [known, "Source registry: https://www.irs.gov/moved -> HTTP 404"])
    assert cd.main(today=dt.date(2026, 10, 5)) == 1


def test_an_expired_quarantine_row_fails_the_drift_job(monkeypatch, capsys):
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


def test_check_finals_nothing_posted_files_nothing_and_a_blind_watch_fails(capsys):
    runner = _Runner()
    assert cf.main([], head=_head(set()), runner=runner) == 0
    assert runner.calls == [] and "none yet" in capsys.readouterr().out
    assert cf.main([], head=lambda url: 403, runner=runner) == 1
    assert "WATCH BLIND" in capsys.readouterr().out
