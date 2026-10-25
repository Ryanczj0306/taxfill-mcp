#!/usr/bin/env python
"""Named watches as triggers (Phase K JK8, KG4): every dated tranche gets an automated trigger issue.

check_finals.py watches the IRS finals of the draft packs (JT6's trigger). This script watches the other named
signals the TY2026 season waits on. Each watch files ITS OWN issue, so one signal cannot hide another:

  drafts   JT5g    the irs-dft drafts of Schedule NEC and Schedule OI (Form 1040-NR), re-posted NEWER than the
                   recorded 2025 drafts (Last-Modified, or the "Created" footer read from the file)
  revproc  JT6     the IRS news release announcing the inflation adjustments for tax year <y+1> (the Rev. Proc. that
                   JT6 authors the TY<y+1> knowledge pack from, after TY<y> flips), read from the newsroom's month pages
  revised  re-pin  the current revision (irs.gov/pub/irs-pdf/<form>.pdf) of every NON-draft <y> federal pack, when its
                   sha256 differs from the pack's pinned pdf_sha256
  states   JS7a    each tier-1 state's TY<y> blank (scripts/tier1_states.yaml, candidates from
                   scaffold_state_year.py): a candidate that answers 200 AND whose first page prints <y>

Every target ends in one of four states:

  FIRED  the trigger holds                                        -> listed in its watch's issue
  BLIND  the watch cannot see the target, and retrying will not help: a host that refuses scripts (401/403), a
         target that vanished, a 200 whose year or date cannot be read -> listed in the issue under "check by
         hand" (it opens the issue: blind is never quiet)
  QUIET  not yet: a 404, an older year, an unchanged digest, the same draft re-uploaded
  ERROR  a transient failure that survived the retries (5xx, timeout, connection) -> exit 1, as in check_finals.py

    python scripts/check_watches.py                       # fetch, then file/update each watch's issue via gh
    python scripts/check_watches.py --dry-run             # fetch, print every target and the issues; file nothing
    python scripts/check_watches.py --dry-run --only states

The watched year <y> is check_finals.provisional_year(): the OLDEST provisional federal year, so a next-year pack
started early cannot move the watches off the season in progress. An issue opened by BLIND rows alone is titled as
blind ("check by hand"), never as if something fired. Closing an issue acknowledges it (check_finals.CLOSING_NOTE).

Why a sibling of check_finals.py rather than more of it (Phase K JK8, 2026-10-24): check_finals HEADs one URL
pattern and files one issue; these watches GET and read content (a PDF's footer or first page, a news page, a
digest) and file four issues. Kept apart, the finals watch keeps its contract and tests unchanged, and the workflow
(.github/workflows/finals.yml) runs the two as separate steps, so a red in one cannot stop or mask the other.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import io
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import check_finals  # noqa: E402
import scaffold_state_year  # noqa: E402
from taxfill_core.fetch import _USER_AGENT, UnmappedBlankRefused, inspect_unmapped_blank  # noqa: E402
from taxfill_core.schemas.formpack import load_pack  # noqa: E402

TIMEOUT = 60.0
MAX_BYTES = 64 * 1024 * 1024

FIRED, BLIND, QUIET, ERROR = "FIRED", "BLIND", "QUIET", "ERROR"


# ── fetching ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes = b""
    last_modified: str | None = None   # the raw Last-Modified header


def get(url: str, sleep: Callable[[float], None] = time.sleep) -> Reply:
    """GET ``url`` with check_finals' retry policy (JK2): a 5xx, a timeout or a connection failure is retried
    (RETRY_ATTEMPTS, RETRY_BACKOFF); any other status is an answer. After the retries a 5xx comes back as its
    status and a connection failure is raised, so the watch reports either as an ERROR."""
    attempts, backoff = check_finals.RETRY_ATTEMPTS, check_finals.RETRY_BACKOFF
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 (fixed official https URLs)
                return Reply(resp.getcode(), resp.read(MAX_BYTES), resp.headers.get("Last-Modified"))
        except urllib.error.HTTPError as exc:
            if attempt == attempts or not 500 <= exc.code <= 599:
                return Reply(exc.code)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt == attempts:
                raise
        sleep(backoff[min(attempt, len(backoff)) - 1])
    raise AssertionError("unreachable")  # pragma: no cover


Fetch = Callable[[str], Reply]


def _is_pdf(body: bytes) -> bool:
    return b"%PDF" in body[:1024]


# ── the report every watch returns ──────────────────────────────────────────


@dataclass(frozen=True)
class Item:
    target: str    # "f1040nrn", "MA form1", ...
    url: str
    state: str     # FIRED / BLIND / QUIET / ERROR
    detail: str


@dataclass
class Watch:
    key: str            # "drafts", "revproc", "revised", "states"
    tranche: str        # what the issue triggers
    label: str
    title: str
    color: str
    action: str         # the issue's closing instruction
    blind_title: str = ""   # the title when nothing FIRED and only BLIND rows open the issue
    items: list[Item] = field(default_factory=list)

    def add(self, target: str, url: str, state: str, detail: str) -> None:
        self.items.append(Item(target, url, state, detail))
        print(f"  {state:<6} {target:<22} {url}  {detail}")

    def by(self, state: str) -> list[Item]:
        return [i for i in self.items if i.state == state]

    def should_file(self) -> bool:
        return bool(self.by(FIRED) or self.by(BLIND))

    def issue_title(self) -> str:
        """The FIRED title only when something fired; a blind-only issue says it is blind (Phase K JK8)."""
        return self.title if self.by(FIRED) or not self.blind_title else self.blind_title

    def signature(self) -> str:
        """What the issue says, minus the quiet list: the fired and blind rows. A closed issue with the same
        signature was acknowledged, so the next run does not re-open it (check_finals.upsert_issue)."""
        rows = sorted(f"{i.state}|{i.target}|{i.url}|{i.detail}" for i in self.items if i.state in (FIRED, BLIND))
        digest = hashlib.sha256("\n".join([self.key, *rows]).encode()).hexdigest()[:16]
        return f"<!-- watch-signature: {self.key} {digest} -->"

    def body(self) -> str:
        fired, blind, quiet = self.by(FIRED), self.by(BLIND), self.by(QUIET)
        lines = [f"The {self.key} watch (scripts/check_watches.py, Phase K JK8) — the trigger for {self.tranche}.", ""]
        lines.append(f"**Fired ({len(fired)}):**" if fired else "**Fired:** none yet.")
        lines += [f"- [ ] `{i.target}` — {i.url} — {i.detail}" for i in fired]
        if blind:
            lines += ["", f"**Blind — check by hand ({len(blind)}):** the watch cannot see these, and retrying will "
                          "not help."]
            lines += [f"- [ ] `{i.target}` — {i.url} — {i.detail}" for i in blind]
        lines += ["", f"Quiet ({len(quiet)}): " + (", ".join(f"`{i.target}`" for i in quiet) or "none"), "",
                  self.action, "", check_finals.CLOSING_NOTE, "", self.signature()]
        return "\n".join(lines)

    def comment(self) -> str:
        return f"{self.key} watch: now {len(self.by(FIRED))} fired, {len(self.by(BLIND))} to check by hand."


# ── (a) JT5g: the irs-dft drafts of Schedules NEC / OI (Form 1040-NR) ───────


DRAFT_URL = "https://www.irs.gov/pub/irs-dft/{stem}--dft.pdf"


@dataclass(frozen=True)
class DraftBaseline:
    stem: str
    name: str
    year: int                # the form year the recorded draft prints
    last_modified: dt.date   # the Last-Modified date irs.gov serves for the recorded draft
    created: dt.date         # its footer's "Created M/D/YY" stamp
    sha256: str


# The drafts JT5g waits to see replaced, recorded 2026-10-24: each downloaded twice from DRAFT_URL with identical
# digests. Both are the 2025 drafts (metadata /Title "2025 Schedule NEC (Form 1040-NR)" / "2025 Schedule OI (Form
# 1040-NR)"); irs.gov serves them with Last-Modified "Tue, 13 May 2025 02:10:13 GMT" / "... 02:10:16 GMT", the date
# the roadmap records them by. When JT5g ships (or folds into JT6 on 2027-01-05), record the new drafts or drop these.
DRAFT_BASELINES = (
    DraftBaseline("f1040nrn", "Schedule NEC (Form 1040-NR)", 2025, dt.date(2025, 5, 13), dt.date(2025, 4, 16),
                  "f87cc1ee45ade164f54def5b8ad3e22c6322c2db48499afb0dab521562504efa"),   # f87cc1ee45ade164
    DraftBaseline("f1040nro", "Schedule OI (Form 1040-NR)", 2025, dt.date(2025, 5, 13), dt.date(2025, 4, 17),
                  "c290a7d4c07f2658f317e2fb3835eadacdfc3ea93097ca64d43e0ae2c5712ecb"),   # c290a7d4c07f2658
)
_CREATED = re.compile(r"\bCreated\s+(\d{1,2})/(\d{1,2})/(\d{2})\b")
_FORM_YEAR = re.compile(r"\(Form 1040-NR\)\s*(20\d\d)\b")


def _draft_facts(body: bytes) -> tuple[dt.date | None, int | None]:
    """(the footer's Created date, the printed form year) read from a draft's text; None where not printed."""
    from pypdf import PdfReader

    text = "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(body)).pages)
    created = None
    if (m := _CREATED.search(text)) is not None:
        created = dt.date(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)))
    year = _FORM_YEAR.search(text)
    return created, int(year.group(1)) if year else None


def _lm_date(header: str | None) -> dt.date | None:
    if not header:
        return None
    try:
        return email.utils.parsedate_to_datetime(header).astimezone(dt.timezone.utc).date()
    except (TypeError, ValueError):
        return None


def watch_drafts(fetch: Fetch, year: int) -> Watch:
    w = Watch("drafts", f"JT5g (the TY{year} Schedule NEC / OI packs)", f"ty{year}-nr-drafts: build JT5g",
              f"IRS TY{year} Schedule NEC / OI (Form 1040-NR) drafts re-posted: build the packs (JT5g)", "1D76DB",
              f"Build per docs/dev/ROADMAP.md JT5g: author each pack against the new draft (source_status: draft, "
              f"draft_created from its footer), then record the new draft here (DRAFT_BASELINES) so the watch goes "
              f"quiet. If none has posted by {year + 1}-01-05, JT5g folds into JT6 and builds from the finals.",
              blind_title=f"TY{year} Schedule NEC / OI (Form 1040-NR) drafts watch is blind: check by hand (JT5g)")
    print(f"\n=== drafts watch: JT5g, {len(DRAFT_BASELINES)} irs-dft drafts ===")
    for base in DRAFT_BASELINES:
        url = DRAFT_URL.format(stem=base.stem)
        reply = fetch(url)
        if reply.status in (401, 403, 404, 410):
            gone = "gone from irs-dft (removed or renamed)" if reply.status in (404, 410) else "refused"
            w.add(base.stem, url, BLIND, f"HTTP {reply.status}: the draft is {gone} — check "
                                         f"https://www.irs.gov/draft-tax-forms by hand for the {base.name} draft")
            continue
        if reply.status != 200:
            w.add(base.stem, url, ERROR, f"HTTP {reply.status}")
            continue
        if hashlib.sha256(reply.body).hexdigest() == base.sha256:
            w.add(base.stem, url, QUIET, f"the recorded draft (Created {base.created}, Last-Modified "
                                         f"{base.last_modified}), unchanged")
            continue
        lm = _lm_date(reply.last_modified)
        created = year_printed = None
        if _is_pdf(reply.body):
            try:
                created, year_printed = _draft_facts(reply.body)
            except Exception:  # noqa: BLE001 — an unreadable PDF is a blind target, not a crash
                pass
        seen = f"Created {created or '?'}, Last-Modified {lm or '?'}, prints {year_printed or '?'}"
        recorded = f"(recorded: Created {base.created}, Last-Modified {base.last_modified}, prints {base.year})"
        # The footer and the printed year say WHICH draft this is; Last-Modified only says the file was touched
        # (Phase K JK8 fix wave): a re-upload of the recorded draft must not fire, so Last-Modified decides only
        # when the footer cannot be read.
        if (created and created > base.created) or (year_printed and year_printed > base.year):
            w.add(base.stem, url, FIRED, f"a newer draft: {seen} {recorded}")
        elif created is not None:
            w.add(base.stem, url, QUIET, f"changed bytes, not newer: re-uploaded, same draft ({seen}) {recorded}")
        elif lm and lm > base.last_modified:
            w.add(base.stem, url, FIRED, f"a newer upload whose Created footer cannot be read: {seen} {recorded} "
                                         f"— confirm it is the TY{year} draft")
        elif lm is None:
            w.add(base.stem, url, BLIND, "the file changed but neither its Last-Modified nor its Created footer can "
                                         "be read — open it and compare with the recorded draft")
        else:
            w.add(base.stem, url, QUIET, f"changed bytes, not newer: {seen}")
    return w


# ── (b) the inflation-adjustments Rev. Proc. for TY<y+1> ────────────────────

# The signal is the IRS news release, not the IRB or the irs-drop PDF (Phase K JK8, 2026-10-24): the release posts
# the day the Rev. Proc. drops and links its PDF (IR-2025-103, Oct. 9, 2025, links /pub/irs-drop/rp-25-32.pdf),
# while the Internal Revenue Bulletin prints it weeks later (Rev. Proc. 2025-32 is in IRB 2025-45) and the
# rp-YY-NN number cannot be guessed. Its title has carried the same words three years running, each read on the
# newsroom's month page (fetched twice 2026-10-24, identical digests):
#   "IRS releases tax inflation adjustments for tax year 2026, including amendments from the One, Big, Beautiful
#    Bill" (IR-2025-103, news-releases-for-october-2025, 8bf904a191968582)
#   "IRS releases tax inflation adjustments for tax year 2025" (IR-2024-273, news-releases-for-october-2024,
#    39d1e086d5ff83b8)
#   "IRS provides tax inflation adjustments for tax year 2024" (IR-2023-208, news-releases-for-november-2023,
#    91e329f694c569ab)
# The current month is only on news-releases-for-current-month (the month's own slug 404s until the month ends), so
# the watch reads that page plus every month page from September of the year before, and a release on the 30th
# survives the month rollover. A page that lists no "IR-" release at all means the layout moved: BLIND, not quiet.
NEWSROOM_CURRENT = "https://www.irs.gov/newsroom/news-releases-for-current-month"
NEWSROOM_MONTH = "https://www.irs.gov/newsroom/news-releases-for-{month}-{year}"
IRS = "https://www.irs.gov"
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_RELEASE_ID = re.compile(r"\bIR-20\d\d-\d+\b")
_REVPROC_PDF = re.compile(r'href="([^"]*/irs-drop/rp-\d\d-\d+\.pdf)"')


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href") or "", []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def newsroom_pages(tax_year: int, today: dt.date) -> list[tuple[str, bool]]:
    """(url, may_404) for the current-month page and each month page from September of ``tax_year - 1`` (the
    release has come Oct. 9 to Nov. 9) to the month before ``today``. The month that just ended may not be archived
    yet, so its 404 is quiet."""
    pages = [(NEWSROOM_CURRENT, False)]
    y, m = tax_year - 1, 9
    last = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    while (y, m) <= last:
        pages.append((NEWSROOM_MONTH.format(month=_MONTHS[m - 1], year=y), (y, m) == last))
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return pages


def watch_revproc(fetch: Fetch, tax_year: int, today: dt.date) -> Watch:
    # Phase K JK8 fix wave: the issue RECORDS the Rev. Proc. for JT6; it does not start the TY<y+1> pack. JT6
    # authors knowledge/federal/<y+1>.yaml after TY<y> flips to final (docs/dev/ROADMAP.md JT6 "Next year").
    w = Watch("revproc", f"JT6 (the TY{tax_year} knowledge pack, authored after TY{tax_year - 1} flips to final)",
              f"ty{tax_year}-revproc: record for JT6",
              f"TY{tax_year} inflation Rev. Proc. released: record it for JT6 (no {tax_year} pack yet)", "5319E7",
              f"Record the Rev. Proc. for JT6: open the release, fetch the Rev. Proc. it links "
              f"(irs.gov/pub/irs-drop/rp-YY-NN.pdf) twice, and comment here with its number, URL and sha256 (first "
              f"16 hex). Do NOT add knowledge/federal/{tax_year}.yaml yet: per docs/dev/ROADMAP.md JT6 it is "
              f"authored from this Rev. Proc. after TY{tax_year - 1} flips to final, when the watches move on to "
              f"TY{tax_year}.",
              blind_title=f"TY{tax_year} inflation Rev. Proc. watch is blind: check the IRS newsroom by hand (JT6)")
    title = re.compile(rf"inflation adjustments for tax year {tax_year}\b", re.IGNORECASE)
    pages = newsroom_pages(tax_year, today)
    print(f"\n=== revproc watch: the TY{tax_year} inflation adjustments, {len(pages)} newsroom pages ===")
    found: dict[str, str] = {}
    for url, may_404 in pages:
        reply = fetch(url)
        name = url.rsplit("/", 1)[-1]
        if reply.status == 404 and may_404:
            w.add(name, url, QUIET, "the month just ended is not archived yet")
            continue
        if reply.status in (401, 403, 404, 410):
            w.add(name, url, BLIND, f"HTTP {reply.status}: the newsroom page is gone — find the month's news "
                                    f"releases from https://www.irs.gov/newsroom by hand")
            continue
        if reply.status != 200:
            w.add(name, url, ERROR, f"HTTP {reply.status}")
            continue
        text = reply.body.decode("utf-8", "replace")
        if not _RELEASE_ID.search(html.unescape(text)):
            w.add(name, url, BLIND, "the page lists no IR- news release: its layout moved, so the watch reads "
                                    "nothing there — read it by hand and fix newsroom parsing")
            continue
        parser = _Anchors()
        parser.feed(text)
        hits = [(href, label) for href, label in parser.anchors if title.search(label)]
        for href, label in hits:
            found.setdefault(href if href.startswith("http") else IRS + href, label)
            print(f"  {'':<6} {name:<22} {url}  lists \"{label}\"")
        if not hits:
            w.add(name, url, QUIET, f"no release for tax year {tax_year}")
    for release, label in found.items():
        reply = fetch(release)
        pdfs = sorted({p if p.startswith("http") else IRS + p
                       for p in _REVPROC_PDF.findall(reply.body.decode("utf-8", "replace"))}) \
            if reply.status == 200 else []
        w.add("release", release, FIRED, f'"{label}"' + (f"; links {', '.join(pdfs)}" if pdfs else
                                                         "; open it for the Rev. Proc. number"))
    return w


# ── (c) the revised current revision of each non-draft pack ─────────────────

CURRENT_PDF = "https://www.irs.gov/pub/irs-pdf/{stem}.pdf"


def nondraft_packs(year: int, repo: Path = REPO) -> list[tuple[str, str, str]]:
    """(IRS file stem, pack dir, pinned sha256) for every non-draft federal pack of ``year``."""
    out = []
    for path in sorted((repo / "formpacks" / "federal" / str(year)).glob("*/pack.yaml")):
        pack = load_pack(path)
        if pack.source_status != "draft":
            stem = pack.source_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".pdf").split("--")[0]
            out.append((stem, path.parent.relative_to(repo).as_posix(), pack.pdf_sha256))
    return out


def watch_revised(fetch: Fetch, year: int, repo: Path = REPO) -> Watch:
    w = Watch("revised", f"a re-pin of the TY{year} non-draft packs", f"ty{year}-revised: re-pin",
              f"TY{year} non-draft packs: the IRS revised a form, re-audit and re-pin", "FBCA04",
              "A new digest is a revised form or the next year's (Form 1040-ES turns over each January): read the "
              "PDF's printed year and revision date. A revision of the pack's year: re-audit the face, re-read every "
              "form_line, re-pin source_url and pdf_sha256. The next year's form: it belongs to that year's pack.",
              blind_title=f"TY{year} non-draft packs watch is blind: check the current revisions by hand (re-pin)")
    packs = nondraft_packs(year, repo)
    print(f"\n=== revised watch: {len(packs)} non-draft TY{year} packs vs their current revision ===")
    for stem, rel, pinned in packs:
        url = CURRENT_PDF.format(stem=stem)
        reply = fetch(url)
        if reply.status in (401, 403, 404, 410):
            w.add(stem, url, BLIND, f"HTTP {reply.status}: no current revision at this URL — find {stem} on "
                                    f"https://www.irs.gov/forms-instructions by hand ({rel})")
        elif reply.status != 200:
            w.add(stem, url, ERROR, f"HTTP {reply.status}")
        elif not _is_pdf(reply.body):
            w.add(stem, url, BLIND, f"answers 200 with a web page, not the PDF — check {stem} by hand ({rel})")
        else:
            digest = hashlib.sha256(reply.body).hexdigest()
            if digest == pinned:
                w.add(stem, url, QUIET, f"matches {rel}'s pin ({pinned[:16]})")
            else:
                w.add(stem, url, FIRED, f"sha256 {digest[:16]} differs from {rel}'s pin {pinned[:16]}")
    return w


# ── (d) JS7a: the tier-1 states' TY<y> blanks ───────────────────────────────

_WRONG_YEAR = re.compile(r"is the (\d{4}) form")
_NOT_FOUND = re.compile(rb"not found|\b404\b|no longer (?:available|exists)|does not exist|cannot be found",
                        re.IGNORECASE)
# JK8 re-verify (2026-10-24): match the page's visible text only. pa.gov's normal forms page carries "not found" inside
# its JavaScript (console.error('Result card not found')), which read as a soft 404 and made the state quiet.
_SCRIPT_STYLE = re.compile(rb"<(script|style)\b[^>]*>.*?</\1\s*>|<!--.*?-->", re.IGNORECASE | re.DOTALL)


def _visible(body: bytes) -> bytes:
    """The page with its script and style blocks and its comments removed."""
    return _SCRIPT_STYLE.sub(b" ", body)


def state_targets(year: int, tier1: Path = scaffold_state_year.DEFAULT_TIER1) -> list[dict]:
    """The JK9 work-list rows (scaffold_state_year --tier1, base newest) for ``year``: one per tier-1 form."""
    return scaffold_state_year.scaffold(year, "newest", states=set(scaffold_state_year.load_tier1(tier1)))


def watch_states(fetch: Fetch, year: int, rows: list[dict]) -> Watch:
    w = Watch("states", f"JS7a (the TY{year} tier-1 state packs)", f"ty{year}-state-blanks: JS7a",
              f"TY{year} tier-1 state blanks posted: port them (JS7a)", "0E8A16",
              "Port each fired blank per docs/dev/ROADMAP.md JS7a (fetch_blank, introspect, the vision audit, the "
              "golden round trip). A blind state's blank must be found and read by hand: the watch cannot tell "
              "whether it posted. Re-run scaffold_state_year.py --tier1 --probe to refresh the work-list.",
              blind_title=f"TY{year} tier-1 state blanks watch is blind for some states: check by hand (JS7a)")
    print(f"\n=== states watch: JS7a, {len(rows)} tier-1 forms for TY{year} ===")
    for row in rows:
        target = f"{row['state'].upper()} {row['form']}"
        status = row["status"]
        if status.startswith("shipped"):
            w.add(target, row["base_url"], QUIET, status)
            continue
        if row["candidate_url"]:
            url, rotating = row["candidate_url"], False
        elif status == "no-year-token" and row["base_url"]:
            url, rotating = row["base_url"], True   # a rotating "current" slot (IL, NJ): read by content
        else:
            w.add(target, row["base_url"] or "-", BLIND, f"no candidate URL ({status}): find the {year} blank on "
                                                         f"the state's forms page by hand")
            continue
        reply = fetch(url)
        if reply.status in (401, 403):
            w.add(target, url, BLIND, f"HTTP {reply.status}: the host refuses scripts, so the watch cannot tell "
                                      f"whether the {year} blank posted — check the state's forms page by hand")
            continue
        if reply.status in (404, 410):
            w.add(target, url, QUIET, f"HTTP {reply.status}: not posted")
            continue
        if reply.status != 200:
            w.add(target, url, ERROR, f"HTTP {reply.status}")
            continue
        if not _is_pdf(reply.body):
            # Phase K JK8 fix wave: only a page that reads as not-found is a soft 404; any other page (a bot
            # challenge served with 200, a moved forms page) hides the answer, so it is blind, not quiet.
            if _NOT_FOUND.search(_visible(reply.body[:200_000])):
                w.add(target, url, QUIET, "200 with a not-found web page (a soft 404): not posted")
            else:
                w.add(target, url, BLIND, "200 with a web page that is not a not-found page (a bot challenge or a "
                                          "moved page?): open it and find the blank by hand")
            continue
        try:
            _, _, first = inspect_unmapped_blank(reply.body, tax_year=year, what=url)
        except UnmappedBlankRefused as exc:
            printed = _WRONG_YEAR.search(str(exc))
            if exc.reason == "wrong_year" and printed:
                where = "the rotating slot still serves" if rotating else "the URL serves"
                w.add(target, url, QUIET, f"{where} the {printed.group(1)} blank")
            else:
                w.add(target, url, BLIND, f"200, but the first page's year cannot be confirmed ({exc.reason}): "
                                          f"open it and read the printed year")
            continue
        except Exception as exc:  # noqa: BLE001 — an unreadable PDF is a blind target, not a crash
            w.add(target, url, BLIND, f"200, but the PDF cannot be read ({type(exc).__name__}): open it by hand")
            continue
        w.add(target, url, FIRED, f"posted: page {first.page} prints {first.printed_year}")
    return w


# ── the run ─────────────────────────────────────────────────────────────────

WATCHES = ("drafts", "revproc", "revised", "states")


def run(only: tuple[str, ...], year: int, fetch: Fetch, today: dt.date, *, repo: Path = REPO,
        state_rows: list[dict] | None = None) -> list[Watch]:
    watches = []
    for key in only:
        try:
            if key == "drafts":
                watches.append(watch_drafts(fetch, year))
            elif key == "revproc":
                watches.append(watch_revproc(fetch, year + 1, today))
            elif key == "revised":
                watches.append(watch_revised(fetch, year, repo))
            elif key == "states":
                watches.append(watch_states(fetch, year, state_rows if state_rows is not None
                                            else state_targets(year)))
        except Exception as exc:  # noqa: BLE001 — one watch's crash must not silence the others
            w = Watch(key, "", "", "", "", "")
            w.add(key, "-", ERROR, f"{type(exc).__name__}: {exc}")
            watches.append(w)
    return watches


def _safe(fetch: Fetch) -> Fetch:
    """A connection failure that survived the retries becomes HTTP 599 (an ERROR row), not an aborted watch."""
    def wrapped(url: str) -> Reply:
        try:
            return fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  (fetch failed: {url}: {type(exc).__name__}: {exc})")
            return Reply(599)
    return wrapped


def main(argv: list[str] | None = None, fetch: Fetch = get, runner=subprocess.run, today: dt.date | None = None,
         state_rows: list[dict] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="print every target and the issues; file nothing")
    parser.add_argument("--year", type=int, help="the watched tax year (default: the oldest provisional year)")
    parser.add_argument("--only", default=",".join(WATCHES), help=f"comma-separated subset of {', '.join(WATCHES)}")
    args = parser.parse_args(argv)
    only = tuple(k.strip() for k in args.only.split(",") if k.strip())
    if unknown := [k for k in only if k not in WATCHES]:
        parser.error(f"unknown watch {', '.join(unknown)}; choose from {', '.join(WATCHES)}")
    year = args.year or check_finals.provisional_year()
    if year is None:
        print("No provisional federal knowledge pack ships: every year is filing-grade, nothing to watch.")
        return 0
    watches = run(only, year, _safe(fetch), today or dt.date.today(), state_rows=state_rows)
    print("\n=== summary ===")
    errors = []
    for w in watches:
        counts = ", ".join(f"{len(w.by(s))} {s.lower()}" for s in (FIRED, BLIND, QUIET, ERROR))
        print(f"  {w.key:<8} {counts}")
        errors += [f"{w.key}: {i.target} {i.url}: {i.detail}" for i in w.by(ERROR)]
    for w in watches:
        if w.label and w.should_file():
            check_finals.upsert_issue(w.label, w.issue_title(), w.body(), comment=w.comment(), color=w.color,
                                      description=f"Phase K JK8 watch: the trigger for {w.tranche}"[:100],
                                      dry_run=args.dry_run, runner=runner, signature=w.signature())
    if errors:
        print(f"\nWATCH ERROR for {len(errors)} target(s) (transient failures that survived the retries):")
        for e in errors:
            print(f"  • {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
