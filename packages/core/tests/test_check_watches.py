"""Phase K JK8 (2026-10-24): the named watches (scripts/check_watches.py) and the finals cron (.github/workflows/
finals.yml) — offline.

Every watch reads a fake web (a URL -> reply map; anything else answers 404) and a fake `gh`. A planted 200 (for a
state, a planted first page printing 2026) must open THAT watch's issue; a 404 stays quiet; a host that answers 403
is BLIND (listed under "check by hand" and opening the issue), never quiet; a rotating "current" slot still serving
the 2025 blank does not fire. The cron test parses finals.yml and walks the calendar from October to 03-15.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

REPO = Path(__file__).resolve().parents[3]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cw = _load("check_watches")
cf = sys.modules["check_finals"]

TODAY = dt.date(2026, 10, 24)
NEC = "https://www.irs.gov/pub/irs-dft/f1040nrn--dft.pdf"
OI = "https://www.irs.gov/pub/irs-dft/f1040nro--dft.pdf"
BASE_LM = "Tue, 13 May 2025 02:10:13 GMT"


# ── fakes ────────────────────────────────────────────────────────────────────


class _Web:
    """URL -> Reply; every other URL answers 404. Records what was fetched."""

    def __init__(self, pages: dict[str, cw.Reply] | None = None):
        self.pages = dict(pages or {})
        self.seen: list[str] = []

    def __call__(self, url: str) -> cw.Reply:
        self.seen.append(url)
        return self.pages.get(url, cw.Reply(404))


class _Runner:
    """A fake `gh`: records each call, answers `issue list` (open / closed) and `issue view` from a script."""

    def __init__(self, open_issue: str = "", body: str = "", closed: str = ""):
        self.calls: list[list[str]] = []
        self.open_issue, self.body, self.closed = open_issue, body, closed

    def __call__(self, cmd, check, capture_output, text):
        self.calls.append(cmd[1:])
        if cmd[1:3] == ["issue", "list"]:
            out = self.closed if "closed" in cmd else self.open_issue
        else:
            out = self.body if cmd[1:3] == ["issue", "view"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out)

    def created(self) -> list[tuple[str, str, str]]:
        """(label, title, body) of every `gh issue create`."""
        out = []
        for c in self.calls:
            if c[:2] == ["issue", "create"]:
                out.append((c[c.index("--label") + 1], c[c.index("--title") + 1], c[c.index("--body") + 1]))
        return out


def _pdf(lines: list[tuple[str, int, int, int]]) -> bytes:
    """A one-page demo PDF: (text, font size, x, y) per line."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for text, size, x, y in lines:
        c.setFont("Helvetica-Bold" if size > 14 else "Helvetica", size)
        c.drawString(x, y, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def _draft(year: int, created: str) -> bytes:
    return _pdf([("DRAFT - DO NOT FILE", 12, 72, 750),
                 (f"Cat. No. 00000X Schedule NEC (Form 1040-NR) {year} Created {created}", 7, 72, 40)])


def _blank(year: int | None, title: str = "Form DEMO-1") -> bytes:
    """A demo state blank: title + the tax year at title size in the top third (as test_fetch_unmapped draws it)."""
    lines = [(f"{title}  Demo Individual Income Tax Return", 12, 72, 750), ("Due April 15", 8, 72, 700),
             ("1  Wages", 8, 72, 420)]
    if year is not None:
        lines.append((str(year), 28, 420, 720))
    return _pdf(lines)


def _newsroom(*titles: str) -> bytes:
    teasers = "".join(
        f'<div class="field--item"><h2><a href="/newsroom/release-{n}" rel="bookmark"><span>{t}</span></a></h2>'
        f'<div>IR-2026-{130 + n}, Oct. 2{n}, 2026 — The Internal Revenue Service today ...</div></div>'
        for n, t in enumerate(titles))
    return f"<html><body><h1>News releases for current month</h1>{teasers}</body></html>".encode()


def _row(state: str, form: str, url: str, status: str = "candidate", base_url: str = "") -> dict:
    return {"state": state, "form": form, "kind": "pack.yaml", "base_year": 2025, "base_url": base_url or url,
            "candidate_url": url if status == "candidate" else "", "source": "derived", "status": status}


def _main(web: _Web, argv: list[str], runner: _Runner | None = None, today: dt.date = TODAY,
          state_rows: list[dict] | None = None) -> int:
    return cw.main(argv, fetch=web, runner=runner or _Runner(), today=today,
                   state_rows=state_rows if state_rows is not None else [])


# ── the named target lists ───────────────────────────────────────────────────


def test_the_named_targets_are_the_roadmap_s():
    assert [b.stem for b in cw.DRAFT_BASELINES] == ["f1040nrn", "f1040nro"]
    assert all(b.last_modified == dt.date(2025, 5, 13) for b in cw.DRAFT_BASELINES)
    assert [s for s, _, _ in cw.nondraft_packs(2026)] == ["f1040es", "f8316", "f843", "f8833", "fw7"]
    rows = cw.state_targets(2026)
    tier1 = [r["state"].lower() for r in yaml.safe_load((REPO / "scripts" / "tier1_states.yaml").read_text())["tier1"]]
    assert sorted({r["state"] for r in rows}) == sorted(tier1) and len(tier1) == 12
    rotating = {r["state"]: r["base_url"] for r in rows if r["status"] == "no-year-token"}
    assert set(rotating) == {"il", "nj"} and all("current" in u for u in rotating.values())
    assert cw.newsroom_pages(2027, TODAY) == [
        (cw.NEWSROOM_CURRENT, False),
        ("https://www.irs.gov/newsroom/news-releases-for-september-2026", True)]
    march = cw.newsroom_pages(2027, dt.date(2027, 3, 10))
    assert [u.rsplit("-for-", 1)[-1] for u, _ in march[1:]] == [
        "september-2026", "october-2026", "november-2026", "december-2026", "january-2027", "february-2027"]
    assert [may for _, may in march] == [False, False, False, False, False, False, True]


def test_the_dry_run_lists_every_target_and_files_nothing(capsys):
    web, runner = _Web(), _Runner()
    rows = cw.state_targets(2026)
    assert cw.main(["--dry-run"], fetch=web, runner=runner, today=TODAY, state_rows=rows) == 0
    out = capsys.readouterr().out
    for target in ["f1040nrn", "f1040nro", "news-releases-for-current-month", "news-releases-for-september-2026",
                   "f1040es", "f8316", "f843", "f8833", "fw7"]:
        assert f" {target} " in out, target
    for r in rows:
        assert f"{r['state'].upper()} {r['form']}" in out
        assert (r["candidate_url"] or r["base_url"]) in out
    assert runner.calls == []
    # Everything 404s here: the drafts and the current revisions vanished (BLIND), the state blanks are not posted
    # (QUIET). Each blind watch would file its own issue — four labels, never one.
    assert out.count("DRY RUN: would file") == 3
    for label in ("ty2026-nr-drafts: build JT5g", "ty2027-revproc: record for JT6", "ty2026-revised: re-pin"):
        assert f"would file the '{label}' issue" in out
    assert "ty2026-state-blanks" not in out
    # Nothing FIRED, so no title may claim something posted, released or was revised (Phase K JK8 fix wave).
    titles = [line for line in out.splitlines() if "gh issue create" in line]
    assert len(titles) == 3 and all("blind" in t and "by hand" in t for t in titles), titles
    assert not any(word in t for t in titles for word in ("re-posted", "released", "revised a form"))


# ── (a) JT5g drafts ──────────────────────────────────────────────────────────


def test_a_newer_draft_opens_the_jt5g_issue_and_the_recorded_one_stays_quiet(capsys):
    quiet = _Web({NEC: cw.Reply(200, _draft(2025, "4/16/25"), BASE_LM),
                  OI: cw.Reply(200, _draft(2025, "4/17/25"), BASE_LM)})
    runner = _Runner()
    assert _main(quiet, ["--only", "drafts"], runner) == 0
    assert runner.calls == [] and "re-uploaded, same draft" in capsys.readouterr().out
    # A planted 200: the 2026 draft (new Last-Modified, new Created footer).
    newer = _Web({**quiet.pages, NEC: cw.Reply(200, _draft(2026, "6/2/26"), "Tue, 02 Jun 2026 02:10:13 GMT")})
    assert _main(newer, ["--only", "drafts"], runner) == 0
    [(label, title, body)] = runner.created()
    assert label == "ty2026-nr-drafts: build JT5g" and "JT5g" in title
    assert "`f1040nrn`" in body and "Created 2026-06-02" in body and "prints 2026" in body
    assert "Quiet (1): `f1040nro`" in body
    # The footer alone is enough (Last-Modified absent); Last-Modified alone only when the footer cannot be read.
    footer = _Web({**quiet.pages, OI: cw.Reply(200, _draft(2026, "6/3/26"), None)})
    stamp = _Web({**quiet.pages, OI: cw.Reply(200, _pdf([("DRAFT - DO NOT FILE", 12, 72, 750)]),
                                              "Mon, 01 Jun 2026 00:00:00 GMT")})
    for web in (footer, stamp):
        w = cw.watch_drafts(web, 2026)
        assert [i.target for i in w.by(cw.FIRED)] == ["f1040nro"]


def test_a_re_uploaded_2025_draft_does_not_fire():
    # Phase K JK8 fix wave: new bytes and a newer Last-Modified, but the footer still says Created 4/17/25 and the
    # face prints 2025 — the same draft re-uploaded, not the TY2026 draft JT5g waits for.
    web = _Web({NEC: cw.Reply(200, _draft(2025, "4/16/25"), BASE_LM),
                OI: cw.Reply(200, _draft(2025, "4/17/25") + b"\n", "Thu, 17 Sep 2026 00:00:00 GMT")})
    w = cw.watch_drafts(web, 2026)
    assert w.by(cw.FIRED) == [] and not w.should_file()
    assert "re-uploaded, same draft" in w.items[1].detail


def test_a_vanished_draft_is_blind_not_quiet():
    w = cw.watch_drafts(_Web({OI: cw.Reply(200, _draft(2025, "4/17/25"), BASE_LM)}), 2026)
    [blind] = w.by(cw.BLIND)
    assert blind.target == "f1040nrn" and "gone from irs-dft" in blind.detail and w.should_file()


# ── (b) the TY2027 inflation Rev. Proc. ──────────────────────────────────────


SEPT = "https://www.irs.gov/newsroom/news-releases-for-september-2026"
OCT = "https://www.irs.gov/newsroom/news-releases-for-october-2026"


def test_the_inflation_release_for_2027_opens_the_revproc_issue(capsys):
    older = _newsroom("IRS reminder: Take steps now", "IRS releases tax inflation adjustments for tax year 2026")
    web = _Web({cw.NEWSROOM_CURRENT: cw.Reply(200, older), SEPT: cw.Reply(200, _newsroom("IRS reminder"))})
    runner = _Runner()
    assert _main(web, ["--only", "revproc"], runner) == 0                  # tax year 2026's release: quiet
    assert runner.calls == []
    posted = _newsroom("IRS reminder: Take steps now",
                       "IRS releases tax inflation adjustments for tax year 2027, including amendments")
    release = "https://www.irs.gov/newsroom/release-1"
    web.pages[cw.NEWSROOM_CURRENT] = cw.Reply(200, posted)
    web.pages[release] = cw.Reply(200, b'<a href="/pub/irs-drop/rp-26-45.pdf">Revenue Procedure 2026-45</a>')
    assert _main(web, ["--only", "revproc"], runner) == 0
    [(label, title, body)] = runner.created()
    assert label == "ty2027-revproc: record for JT6" and "TY2027" in title and "Rev. Proc." in title
    assert release in body and "https://www.irs.gov/pub/irs-drop/rp-26-45.pdf" in body
    # The issue must not send the reader to start knowledge/federal/2027.yaml in mid-season (ROADMAP JT6 order).
    assert "JT6" in title and "start the TY2027 knowledge" not in title
    assert "Do NOT add knowledge/federal/2027.yaml" in body and "start knowledge/federal" not in body


def test_a_provisional_next_year_pack_does_not_move_the_watches_off_the_season(tmp_path: Path, monkeypatch):
    # Phase K JK8 fix wave: a provisional 2027 knowledge pack added before TY2026 flips to final must not move the
    # watches to 2027 — the TY2026 draft packs stay in the finals watch and the non-draft packs in the revised one.
    federal = tmp_path / "knowledge" / "federal"
    federal.mkdir(parents=True)
    text = (REPO / "knowledge" / "federal" / "2026.yaml").read_text()
    (federal / "2026.yaml").write_text(text)
    (federal / "2027.yaml").write_text(text.replace("\ntax_year: 2026\n", "\ntax_year: 2027\n", 1))
    (tmp_path / "formpacks").symlink_to(REPO / "formpacks")
    monkeypatch.setenv("TAXFILL_DATA_DIR", str(tmp_path))
    year = cf.provisional_year(tmp_path)
    assert year == 2026
    stems = [w.stem for w in cf.watch_list(year, repo=tmp_path)]
    assert len(stems) > 10 and "f1040" in stems
    assert [s for s, _, _ in cw.nondraft_packs(year, tmp_path)] == ["f1040es", "f8316", "f843", "f8833", "fw7"]


def test_a_release_on_the_last_day_of_october_survives_the_month_rollover():
    web = _Web({cw.NEWSROOM_CURRENT: cw.Reply(200, _newsroom("IRS reminder")),
                SEPT: cw.Reply(200, _newsroom("IRS reminder")),
                OCT: cw.Reply(200, _newsroom("IRS provides tax inflation adjustments for tax year 2027"))})
    w = cw.watch_revproc(web, 2027, dt.date(2026, 11, 2))
    assert len(w.by(cw.FIRED)) == 1 and OCT in web.seen
    # The month just ended may not be archived yet: its 404 is quiet; an older month's 404 is blind.
    del web.pages[OCT]
    w = cw.watch_revproc(web, 2027, dt.date(2026, 11, 2))
    assert w.by(cw.BLIND) == [] and not w.should_file()
    w = cw.watch_revproc(web, 2027, dt.date(2026, 12, 2))
    assert [i.url for i in w.by(cw.BLIND)] == [OCT]


def test_a_newsroom_page_that_lists_no_release_is_blind():
    web = _Web({cw.NEWSROOM_CURRENT: cw.Reply(200, b"<html>Access Denied</html>"),
                SEPT: cw.Reply(200, _newsroom("IRS reminder"))})
    w = cw.watch_revproc(web, 2027, TODAY)
    [blind] = w.by(cw.BLIND)
    assert blind.url == cw.NEWSROOM_CURRENT and "layout moved" in blind.detail


# ── (c) the 2026 non-draft packs' current revisions ─────────────────────────


def test_a_revised_current_revision_opens_the_repin_issue(monkeypatch):
    old, new = b"%PDF-1.7 the pinned revision", b"%PDF-1.7 a revised revision"
    pin = hashlib.sha256(old).hexdigest()
    monkeypatch.setattr(cw, "nondraft_packs", lambda year, repo=None: [
        ("f8833", "formpacks/federal/2026/f8833", pin), ("fw7", "formpacks/federal/2026/fw7", pin)])
    pdf = "https://www.irs.gov/pub/irs-pdf/{}.pdf"
    same = _Web({pdf.format("f8833"): cw.Reply(200, old), pdf.format("fw7"): cw.Reply(200, old)})
    runner = _Runner()
    assert _main(same, ["--only", "revised"], runner) == 0 and runner.calls == []
    revised = _Web({**same.pages, pdf.format("f8833"): cw.Reply(200, new)})
    assert _main(revised, ["--only", "revised"], runner) == 0
    [(label, title, body)] = runner.created()
    assert label == "ty2026-revised: re-pin" and "non-draft" in title
    assert "`f8833`" in body and hashlib.sha256(new).hexdigest()[:16] in body and "Quiet (1): `fw7`" in body
    # A 5xx that survived the retries is an ERROR (exit 1), never a quiet target (Phase K JK8 fix wave).
    down = _Web({**same.pages, pdf.format("fw7"): cw.Reply(503)})
    assert _main(down, ["--only", "revised"], _Runner()) == 1
    assert [i.target for i in cw.watch_revised(down, 2026).by(cw.ERROR)] == ["fw7"]


# ── (d) JS7a tier-1 state blanks ─────────────────────────────────────────────


CA = "https://www.ftb.ca.gov/forms/2026/2026-540.pdf"
MA = "https://www.mass.gov/doc/2026-form-1-massachusetts-resident-income-tax-return/download"
IL = "https://tax.illinois.gov/content/dam/soi/en/web/tax/forms/incometax/documents/currentyear/individual/il-1040.pdf"
NY = "https://www.tax.ny.gov/pdf/2026/inc/it201_2026_fill_in.pdf"
ROWS = [_row("ca", "form540", CA), _row("il", "il1040", "", "no-year-token", IL), _row("ny", "it201", NY)]


def test_a_planted_2026_first_page_opens_the_js7a_issue_and_a_404_stays_quiet(capsys):
    runner = _Runner()
    assert _main(_Web(), ["--only", "states"], runner, state_rows=ROWS) == 0
    assert runner.calls == [] and "HTTP 404: not posted" in capsys.readouterr().out
    web = _Web({CA: cw.Reply(200, _blank(2026, "Form 540"))})
    assert _main(web, ["--only", "states"], runner, state_rows=ROWS) == 0
    [(label, title, body)] = runner.created()
    assert label == "ty2026-state-blanks: JS7a" and "JS7a" in title
    assert "`CA form540`" in body and "prints 2026" in body and "Quiet (2): `IL il1040`, `NY it201`" in body


def test_a_200_whose_first_page_is_not_2026_does_not_fire():
    # A year-token URL can answer 200 with last year's blank, or with a web page (a soft 404).
    for reply in (cw.Reply(200, _blank(2025)), cw.Reply(200, b"<html>Page not found</html>")):
        w = cw.watch_states(_Web({CA: reply}), 2026, ROWS[:1])
        assert w.by(cw.FIRED) == [] and not w.should_file()


def test_a_200_web_page_that_is_not_a_not_found_page_is_blind():
    # Phase K JK8 fix wave: a bot challenge served with status 200 must not make a state silently quiet.
    challenge = b"<html><title>Just a moment...</title>Checking your browser before accessing</html>"
    w = cw.watch_states(_Web({CA: cw.Reply(200, challenge)}), 2026, ROWS[:1])
    [blind] = w.by(cw.BLIND)
    assert blind.target == "CA form540" and "not a not-found page" in blind.detail and w.should_file()


def test_a_rotating_slot_fires_only_when_it_serves_the_2026_blank():
    w = cw.watch_states(_Web({IL: cw.Reply(200, _blank(2025, "IL-1040"))}), 2026, ROWS[1:2])
    [quiet] = w.by(cw.QUIET)
    assert "rotating slot still serves the 2025 blank" in quiet.detail and not w.should_file()
    w = cw.watch_states(_Web({IL: cw.Reply(200, _blank(2026, "IL-1040"))}), 2026, ROWS[1:2])
    assert [i.target for i in w.by(cw.FIRED)] == ["IL il1040"]


def test_a_403_state_is_blind_not_quiet(capsys):
    rows = [_row("ma", "form1", MA)]
    runner = _Runner()
    assert _main(_Web({MA: cw.Reply(403)}), ["--only", "states"], runner, state_rows=rows) == 0
    out = capsys.readouterr().out
    assert "BLIND  MA form1" in out and "refuses scripts" in out
    [(_, _, body)] = runner.created()
    assert "Blind — check by hand (1)" in body and "`MA form1`" in body and "Quiet (0)" in body


def test_a_200_whose_year_cannot_be_read_is_blind():
    w = cw.watch_states(_Web({NY: cw.Reply(200, _blank(None, "IT-201"))}), 2026, ROWS[2:])
    [blind] = w.by(cw.BLIND)
    assert blind.target == "NY it201" and "cannot be confirmed (no_printed_year)" in blind.detail


# ── errors, retries, and one watch never silencing another ───────────────────


def test_a_transient_failure_fails_the_run_but_the_other_watches_still_report(capsys):
    def flaky(url: str) -> cw.Reply:
        if url == NEC:
            raise urllib.error.URLError(TimeoutError("timed out"))
        return cw.Reply(503) if url == OI else _Web({CA: cw.Reply(200, _blank(2026, "Form 540"))})(url)

    runner = _Runner()
    assert cw.main(["--only", "drafts,states"], fetch=flaky, runner=runner, today=TODAY, state_rows=ROWS[:1]) == 1
    out = capsys.readouterr().out
    assert "WATCH ERROR for 2 target(s)" in out and "timed out" in out and "HTTP 503" in out
    assert [label for label, _, _ in runner.created()] == ["ty2026-state-blanks: JS7a"]
    with pytest.raises(SystemExit):
        cw.main(["--only", "finals"], fetch=_Web(), runner=runner, today=TODAY, state_rows=[])


def test_get_retries_a_5xx_but_not_a_404(monkeypatch):
    script: list = []
    sleeps: list[float] = []

    class _Resp:
        def __init__(self, code):
            self.code, self.headers = code, {"Last-Modified": BASE_LM}

        def getcode(self):
            return self.code

        def read(self, n=-1):
            return b"%PDF-1.7"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        answer = script.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return _Resp(answer)

    monkeypatch.setattr(cw.urllib.request, "urlopen", urlopen)
    script[:] = [urllib.error.HTTPError(NEC, 503, "Service Unavailable", {}, None), 200]
    assert cw.get(NEC, sleep=sleeps.append) == cw.Reply(200, b"%PDF-1.7", BASE_LM) and sleeps == [2.0]
    script[:] = [urllib.error.HTTPError(NEC, 404, "Not Found", {}, None), 200]
    assert cw.get(NEC, sleep=sleeps.append).status == 404 and script == [200]


def test_an_unchanged_issue_is_not_commented_on_daily():
    web = _Web({MA: cw.Reply(403)})
    rows = [_row("ma", "form1", MA)]
    first = _Runner()
    _main(web, ["--only", "states"], first, state_rows=rows)
    [(_, _, body)] = first.created()
    again = _Runner(open_issue="7", body=body)
    _main(web, ["--only", "states"], again, state_rows=rows)
    assert [c[:2] for c in again.calls] == [["label", "create"], ["issue", "list"], ["issue", "view"]]
    posted = _Runner(open_issue="7", body=body)
    web.pages[CA] = cw.Reply(200, _blank(2026, "Form 540"))
    _main(web, ["--only", "states"], posted, state_rows=rows + ROWS[:1])
    assert [c[:2] for c in posted.calls][-2:] == [["issue", "edit"], ["issue", "comment"]]


def test_a_closed_issue_with_the_same_rows_is_not_reopened_daily():
    # Phase K JK8 fix wave: closing a watch issue acknowledges it. While the watch finds the same fired and blind
    # rows it stays closed; anything new files a fresh issue. The body says so.
    web = _Web({MA: cw.Reply(403)})
    rows = [_row("ma", "form1", MA)]
    first = _Runner()
    _main(web, ["--only", "states"], first, state_rows=rows)
    [(_, _, body)] = first.created()
    assert "Closing this issue" in body and "<!-- watch-signature:" in body
    closed = json.dumps([{"number": 9, "body": body}])
    again = _Runner(closed=closed)
    _main(web, ["--only", "states"], again, state_rows=rows)
    assert again.created() == []
    web.pages[CA] = cw.Reply(200, _blank(2026, "Form 540"))
    grown = _Runner(closed=closed)
    _main(web, ["--only", "states"], grown, state_rows=rows + ROWS[:1])
    [(_, _, new_body)] = grown.created()
    assert "`CA form540`" in new_body


# ── the cron: October to 03-15 ───────────────────────────────────────────────


def _field(spec: str, value: int) -> bool:
    if spec == "*":
        return True
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        if int(lo) <= value <= int(hi or lo):
            return True
    return False


def _fires_on(cron: str, day: dt.date) -> bool:
    """Whether a 5-field cron fires on ``day`` (POSIX: day-of-month and day-of-week are ORed when both are set)."""
    _, _, dom, month, dow = cron.split()
    if not _field(month, day.month):
        return False
    by_dom, by_dow = _field(dom, day.day), _field(dow, day.isoweekday() % 7)
    if dom != "*" and dow != "*":
        return by_dom or by_dow
    return by_dom and by_dow


def test_the_finals_cron_covers_october_to_march_15():
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "finals.yml").read_text())
    crons = [s["cron"] for s in (workflow.get("on") or workflow[True])["schedule"]]
    season = [dt.date(2026, 10, 1) + dt.timedelta(days=n) for n in range(365)]
    runs = [d for d in season if any(_fires_on(c, d) for c in crons)]
    daily = [d for d in season if dt.date(2026, 12, 15) <= d <= dt.date(2027, 3, 15)]
    assert set(daily) <= set(runs), sorted(set(daily) - set(runs))[:5]          # daily 12-15 .. 03-15
    weekly = [d for d in runs if d < dt.date(2026, 12, 15)]
    assert weekly[0] <= dt.date(2026, 10, 7)
    assert max((b - a).days for a, b in zip(weekly, weekly[1:] + [dt.date(2026, 12, 15)])) <= 7
    assert max(runs) == dt.date(2027, 3, 15)                                     # and nothing after 03-15
    steps = workflow["jobs"]["watch"]["steps"]
    runs_of = {s.get("name"): s for s in steps}
    assert "scripts/check_finals.py" in runs_of["Watch for the finals"]["run"]
    watches = runs_of["Watch the named targets (JK8)"]
    assert "scripts/check_watches.py" in watches["run"] and "!cancelled()" in watches["if"]


def test_not_found_in_a_pages_script_does_not_make_a_state_quiet():
    """JK8 re-verify (2026-10-24): only the page's visible text decides a soft 404."""
    page = (b"<html><head><title>Forms and publications</title><script>console.error('Result card not found')</script>"
            b"</head><body><h1>Forms and publications</h1></body></html>")
    w = cw.watch_states(_Web({CA: cw.Reply(200, page)}), 2026, ROWS[:1])
    [blind] = w.by(cw.BLIND)
    assert blind.target == "CA form540" and w.by(cw.QUIET) == []
    w = cw.watch_states(_Web({CA: cw.Reply(200, b"<html><h1>Page not found</h1></html>")}), 2026, ROWS[:1])
    assert [i.target for i in w.by(cw.QUIET)] == ["CA form540"]
