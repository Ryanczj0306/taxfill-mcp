#!/usr/bin/env python
"""Re-pin a draft pack to the IRS final (Phase J JT6): compare, then write the pins as data.

A draft pack (``source_status: draft``, irs.gov/pub/irs-dft/<stem>--dft.pdf) moves to the final revision
(irs.gov/pub/irs-prior/<stem>--<year>.pdf) when scripts/check_finals.py reports it posted.

    repin_final.py [STEM ...]                 # compare; default: every watched stem that answers 200
    repin_final.py --final STEM=PATH ...      # compare against a local final PDF (replays, tests)
    repin_final.py STEM ... --render DIR      # sentinel fill of the final + PNG pages, to be READ
    repin_final.py STEM ... --write           # edit the pins; refused (exit 1, nothing edited) on needs_remap
    repin_final.py ... --json                 # the comparison as JSON

COMPARE (writes nothing). The final is fetched twice and must hash equal; the pinned draft comes from the blank
cache, checksum-verified against the pack (or, once re-pinned, against the ledger). Reported: pages and whether the
draft's cover sheet was dropped (read from the pages); every widget matched by fully qualified name and index with
/FT, /Ff, /MaxLen, /DA, /Q, the /AP state names and /Rect (page offset applied); the page words, where only the
DRAFT banners and the footer "Created" date may differ. Verdict:

    identical       nothing but the banners (and tooltips, XFA) differs
    geometry_moved  same names, types, flags, states and words; a /Rect edge moved 0.1 pt or more, or a /DA or
                    /Q changed: READ THE RENDER (a smaller /Rect difference is reported as a nudge)
    needs_remap     a widget added, removed, renamed, retyped or on another page; a flag, /MaxLen or /AP state
                    changed; a mapped field missing; words changed beyond banners and footer; pages unexplained

WRITE edits, as text (the hand-written comments stay): the pack (source_url, pdf_sha256, source_status,
draft_created, signature.page by the cover-sheet offset, one header line); knowledge/anchor/selection.yaml and
adjudications.yaml; the form's ``form_lines`` entries in knowledge/federal/<year>.yaml, each caption first checked
VERBATIM on the final (scripts/check_quotes.py); the ledger row in formpacks/federal/repins.yaml. Then it removes
the label-adjacency exception rows that cleared themselves, rewrites the pack's coverage row, and regenerates the
pack-path golden and the doc counts. A second --write changes nothing. Exit 2: written, with follow-ups by hand.

Never done here: reading the render (a human or agent step), the anchor benchmark (three commands, printed, once
per batch), the knowledge blocks that still cite a draft (listed).
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import check_finals  # noqa: E402
from taxfill_core.datadir import home_display  # noqa: E402
from taxfill_core.fetch import cached_blank_path, seed_blank  # noqa: E402
from taxfill_core.knowledge import FormLineEntry  # noqa: E402
from taxfill_core.schemas.formpack import FormPack, load_pack  # noqa: E402

DRAFT_URL = "https://www.irs.gov/pub/irs-dft/{stem}--dft.pdf"
FINAL_URL = check_finals.FINAL_URL
LEDGER = Path("formpacks") / "federal" / "repins.yaml"
IDENTICAL, GEOMETRY_MOVED, NEEDS_REMAP = "identical", "geometry_moved", "needs_remap"
WRITABLE = (IDENTICAL, GEOMETRY_MOVED)
# A /Rect edge that differs by less than this many points is a NUDGE: reported and kept in the ledger's largest
# delta, but not a move (Form 8843's final has one edge 0.05 pt off its draft, 1/1440 inch; Schedule 8812's smallest
# real move is 0.25 pt).
MOVE_THRESHOLD = 0.1
RECT_NOISE = 0.005       # an edge within this is the same edge (Form 2555: 17 boxes 0.003 pt apart); not listed

# What a draft prints and its final does not (every TY2026 draft, read 2026-11-12).
_BANNER_RE = re.compile(r"TREASURY/IRS AND OMB USE ONLY DRAFT(?: Version \S+ Cycle \d+)?|DRAFT [—–-] DO NOT FILE")
_CREATED_RE = re.compile(r"Created\s+(\d{1,2}/\d{1,2}/\d{2,4})")
_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


class RepinError(RuntimeError):
    """The re-pin cannot go on; the message says what to do."""


# ── reading a blank ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Widget:
    name: str                 # fully qualified field name
    index: int                # among the widgets of that name, in document order
    page: int                 # 1-based
    ft: str
    ff: int
    maxlen: int | None
    da: str
    q: int
    states: tuple[str, ...]   # the /AP /N state names (checkboxes and radio kids)
    rect: tuple[float, float, float, float]

    @property
    def key(self) -> tuple[str, int]:
        return self.name, self.index


@dataclass
class Blank:
    sha256: str
    pages: int
    widgets: list[Widget]
    words: list[list[str]]    # per page
    created: str | None       # the footer's "Created <date>"
    posted: str | None        # ISO date from the PDF metadata (/ModDate, else /CreationDate)
    tooltips: int
    xfa: bool

    def on_page(self, page: int) -> list[Widget]:
        return [w for w in self.widgets if w.page == page]


def _inherited(node, key: str):
    for _ in range(32):
        if node is None:
            return None
        if key in node:
            return node[key]
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
    return None


def _qualified_name(node) -> str:
    parts = []
    for _ in range(32):
        if node is None:
            break
        if node.get("/T") is not None:
            parts.append(str(node["/T"]))
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
    return ".".join(reversed(parts))


def _states(annot) -> tuple[str, ...]:
    from pypdf.generic import StreamObject

    ap = annot.get("/AP")
    normal = ap.get_object().get("/N") if ap is not None else None
    normal = normal.get_object() if normal is not None else None
    if normal is None or isinstance(normal, StreamObject):
        return ()
    return tuple(sorted(str(k) for k in normal.keys()))


def read_blank(data: bytes) -> Blank:
    """Everything the comparison reads off one blank PDF."""
    import io

    import pypdfium2 as pdfium
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    widgets: list[Widget] = []
    seen: dict[str, int] = {}
    tooltips = 0
    for pno, page in enumerate(reader.pages, 1):
        annots = page.get("/Annots")
        for ref in (annots.get_object() if annots is not None else []):
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            name = _qualified_name(annot)
            index = seen.get(name, 0)
            seen[name] = index + 1
            x0, y0, x1, y1 = (float(v) for v in annot["/Rect"])
            maxlen = _inherited(annot, "/MaxLen")
            tooltips += _inherited(annot, "/TU") is not None
            widgets.append(Widget(
                name=name, index=index, page=pno, ft=str(_inherited(annot, "/FT") or ""),
                ff=int(_inherited(annot, "/Ff") or 0), maxlen=int(maxlen) if maxlen is not None else None,
                da=str(_inherited(annot, "/DA") or ""), q=int(_inherited(annot, "/Q") or 0), states=_states(annot),
                rect=(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))))
    root = reader.trailer["/Root"]
    acroform = root.get("/AcroForm")
    xfa = acroform is not None and "/XFA" in acroform.get_object()
    info = reader.metadata or {}
    stamp = re.match(r"D:(\d{4})(\d{2})(\d{2})", str(info.get("/ModDate") or info.get("/CreationDate") or ""))
    words: list[list[str]] = []
    doc = pdfium.PdfDocument(data)
    try:
        for page in doc:
            textpage = page.get_textpage()
            words.append(textpage.get_text_range().split())
            textpage.close()
            page.close()
    finally:
        doc.close()
    created = next((m.group(1) for page in words if (m := _CREATED_RE.search(" ".join(page)))), None)
    return Blank(sha256=hashlib.sha256(data).hexdigest(), pages=len(reader.pages), widgets=widgets, words=words,
                 created=created, posted="-".join(stamp.groups()) if stamp else None, tooltips=tooltips, xfa=xfa)


# ── the comparison ───────────────────────────────────────────────────────────


def strip_banners(words: list[str]) -> tuple[list[str], int]:
    """A page's words without the DRAFT banners, and how many words the banners held."""
    kept = _BANNER_RE.sub(" ", " ".join(words)).split()
    return kept, len(words) - len(kept)


def _similar(a: list[str], b: list[str]) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def page_offset(draft: Blank, final: Blank) -> tuple[int, bool, str | None]:
    """(page offset, cover sheet dropped, a problem or None), decided from the pages: a cover sheet is ONE leading
    draft page that carries no widget and is not the final's page 1, while the draft's page 2 is."""
    if draft.pages == final.pages:
        return 0, False, None
    if draft.pages == final.pages + 1 and final.pages >= 1 and not draft.on_page(1):
        cover, _ = strip_banners(draft.words[0])
        second, _ = strip_banners(draft.words[1])
        first, _ = strip_banners(final.words[0])
        if _similar(second, first) >= 0.9 and _similar(cover, first) < 0.5:
            return 1, True, None
    return 0, False, (f"the draft has {draft.pages} page(s) and the final {final.pages}, and a dropped cover sheet "
                      "does not explain it")


@dataclass
class Comparison:
    stem: str
    pack: str                    # "federal/2026/sched_c"
    draft_url: str
    final_url: str
    draft: Blank
    final: Blank
    offset: int = 0
    cover_sheet_dropped: bool = False
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)        # retyped, flags, /MaxLen, /AP states, page
    appearance: list[str] = field(default_factory=list)     # /DA, /Q
    moved: list[dict] = field(default_factory=list)         # {"name", "index", "page", "delta": [dx0, dy0, dx1, dy1]}
    nudged: list[dict] = field(default_factory=list)        # the same, for a difference under MOVE_THRESHOLD
    max_delta: float = 0.0                                  # the largest /Rect edge difference of any widget
    banner_words: int = 0
    footer: tuple[str, str] | None = None                   # ("4/24/26", "8/18/26") when the footer date changed
    words_changed: list[dict] = field(default_factory=list)  # {"page", "draft", "final"}
    mapped_missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    clearing: list[str] | None = None      # label-adjacency exception rows the final clears (None: not measured)
    unexcused: list[str] | None = None     # label-adjacency disagreements the final brings

    @property
    def largest_delta(self) -> float:
        return round(self.max_delta, 3)

    @property
    def verdict(self) -> str:
        if (self.problems or self.added or self.removed or self.changed or self.words_changed
                or self.mapped_missing):
            return NEEDS_REMAP
        return GEOMETRY_MOVED if self.moved or self.appearance else IDENTICAL

    def ledger_row(self, repinned: str | None, exceptions_cleared: int) -> dict:
        return {
            "pack": self.pack, "stem": self.stem,
            "draft_url": self.draft_url, "draft_sha256": self.draft.sha256, "draft_created": self.draft.created,
            "draft_pages": self.draft.pages,
            "final_url": self.final_url, "final_sha256": self.final.sha256, "final_posted": self.final.posted,
            "final_created": self.final.created, "pages": self.final.pages, "widgets": len(self.final.widgets),
            "cover_sheet_dropped": self.cover_sheet_dropped, "rects_moved": len(self.moved),
            "largest_rect_delta": self.largest_delta, "words_changed": len(self.words_changed),
            "exceptions_cleared": exceptions_cleared, "verdict": self.verdict, "repinned": repinned,
        }

    def as_json(self) -> dict:
        side = lambda b: {"sha256": b.sha256, "pages": b.pages, "widgets": len(b.widgets), "created": b.created,  # noqa: E731
                          "posted": b.posted, "tooltips": b.tooltips, "xfa": b.xfa}
        return {
            "stem": self.stem, "pack": self.pack, "verdict": self.verdict,
            "draft": side(self.draft) | {"url": self.draft_url}, "final": side(self.final) | {"url": self.final_url},
            "page_offset": self.offset, "cover_sheet_dropped": self.cover_sheet_dropped,
            "widgets_added": self.added, "widgets_removed": self.removed, "widgets_changed": self.changed,
            "appearance_changed": self.appearance, "rects_moved": self.moved, "rects_nudged": self.nudged,
            "largest_rect_delta": self.largest_delta,
            "banner_words": self.banner_words, "footer_created": list(self.footer) if self.footer else None,
            "words_changed": self.words_changed, "mapped_missing": self.mapped_missing, "problems": self.problems,
            "exceptions_clearing": self.clearing, "label_adjacency_unexcused": self.unexcused,
            "ledger_row": self.ledger_row(None, len(self.clearing or [])),   # --write adds the date
        }


def _diff_words(c: Comparison) -> None:
    for i, final_words in enumerate(c.final.words):
        draft_words, banners = strip_banners(c.draft.words[i + c.offset])
        c.banner_words += banners
        final_kept, final_banners = strip_banners(final_words)
        if final_banners:
            c.problems.append(f"page {i + 1} of the final still prints a DRAFT banner: is it the final?")
        ops = difflib.SequenceMatcher(None, draft_words, final_kept, autojunk=False).get_opcodes()
        for tag, a0, a1, b0, b1 in ops:
            if tag == "equal":
                continue
            was, now = draft_words[a0:a1], final_kept[b0:b1]
            if (tag == "replace" and len(was) == len(now) == 1 and _DATE_RE.fullmatch(was[0])
                    and _DATE_RE.fullmatch(now[0]) and a0 and draft_words[a0 - 1] == "Created"):
                c.footer = (was[0], now[0])
                continue
            c.words_changed.append({"page": i + 1, "draft": " ".join(was), "final": " ".join(now)})


def _diff_widgets(c: Comparison) -> None:
    draft = {w.key: w for w in c.draft.widgets}
    final = {w.key: w for w in c.final.widgets}
    label = lambda w: f"p{w.page} {w.name}" + (f" #{w.index}" if w.index else "")  # noqa: E731
    c.removed = [label(w) for k, w in draft.items() if k not in final]
    c.added = [label(w) for k, w in final.items() if k not in draft]
    for key, now in final.items():
        was = draft.get(key)
        if was is None:
            continue
        hard = [f"{what} {a!r} -> {b!r}" for what, a, b in (
            ("/FT", was.ft, now.ft), ("/Ff", was.ff, now.ff), ("/MaxLen", was.maxlen, now.maxlen),
            ("/AP states", list(was.states), list(now.states)), ("page", was.page - c.offset, now.page)) if a != b]
        if hard:
            c.changed.append(f"{label(now)}: " + "; ".join(hard))
        soft = [f"{what} {a!r} -> {b!r}" for what, a, b in (("/DA", was.da, now.da), ("/Q", was.q, now.q)) if a != b]
        if soft:
            c.appearance.append(f"{label(now)}: " + "; ".join(soft))
        delta = [round(n - o, 3) for o, n in zip(was.rect, now.rect)]
        largest = max(abs(d) for d in delta)
        c.max_delta = max(c.max_delta, largest)
        if largest > RECT_NOISE:
            row = {"name": now.name, "index": now.index, "page": now.page, "delta": delta}
            (c.moved if largest >= MOVE_THRESHOLD else c.nudged).append(row)


def compare(stem: str, pack_id: str, pack: FormPack, draft: bytes, final: bytes, *, draft_url: str,
            final_url: str) -> Comparison:
    """The final against the pinned draft; nothing is written."""
    c = Comparison(stem=stem, pack=pack_id, draft_url=draft_url, final_url=final_url, draft=read_blank(draft),
                   final=read_blank(final))
    c.offset, c.cover_sheet_dropped, problem = page_offset(c.draft, c.final)
    if problem:
        c.problems.append(problem)
        return c
    _diff_widgets(c)
    _diff_words(c)
    root = f"{pack.acroform_root}." if pack.acroform_root else ""
    names = {w.name for w in c.final.widgets}
    c.mapped_missing = sorted({root + f.field for f in pack.fields} - names)
    return c


def report(c: Comparison) -> str:
    d, f = c.draft, c.final
    lines = [
        f"{c.stem}  {c.pack}  verdict: {c.verdict}",
        f"  draft  {d.sha256[:16]}…  Created {d.created}  {d.pages} page(s)  {len(d.widgets)} widgets, "
        f"{d.tooltips} tooltips",
        f"  final  {f.sha256[:16]}…  posted {f.posted}  Created {f.created}  {f.pages} page(s)  {len(f.widgets)} "
        f"widgets, {f.tooltips} tooltips{', XFA' if f.xfa else ''}  {c.final_url}",
        f"  pages: {'cover sheet dropped, every page one lower' if c.cover_sheet_dropped else 'no cover sheet dropped'}",
    ]
    for p in c.problems:
        lines.append(f"  PROBLEM: {p}")
    lines.append(f"  widgets: {len(c.added)} added, {len(c.removed)} removed, {len(c.changed)} changed "
                 f"(/FT /Ff /MaxLen /AP page), {len(c.appearance)} with another /DA or /Q, "
                 f"{len(c.mapped_missing)} mapped field(s) missing")
    for what, rows in (("added", c.added), ("removed", c.removed), ("changed", c.changed),
                       ("appearance", c.appearance), ("mapped but missing", c.mapped_missing)):
        lines += [f"      {what}: {r}" for r in rows]
    lines.append(f"  rectangles: {len(c.moved)} moved, {len(c.nudged)} nudged under {MOVE_THRESHOLD} pt"
                 + (f"; largest delta {c.largest_delta} pt" if c.max_delta else ""))
    for what, rows in (("", c.moved), ("nudge ", c.nudged)):
        for m in rows:
            dx0, dy0, dx1, dy1 = m["delta"]
            lines.append(f"      {what}p{m['page']} {m['name']}{' #%d' % m['index'] if m['index'] else ''}  "
                         f"x0 {dx0:+g}  y0 {dy0:+g}  x1 {dx1:+g}  y1 {dy1:+g}")
    footer = f"footer Created {c.footer[0]} -> {c.footer[1]}" if c.footer else "footer date unchanged"
    lines.append(f"  words: {c.banner_words} banner word(s) gone; {footer}; {len(c.words_changed)} other change(s)")
    lines += [f"      p{w['page']}: {w['draft']!r} -> {w['final']!r}" for w in c.words_changed]
    if c.clearing is not None:
        lines.append(f"  label adjacency on the final: {len(c.clearing)} exception row(s) clear, "
                     f"{len(c.unexcused or [])} new disagreement(s)")
        lines += [f"      clears: {r}" for r in c.clearing] + [f"      NEW: {r}" for r in c.unexcused or []]
    if c.verdict == GEOMETRY_MOVED:
        lines.append("  -> geometry moved: run --render and READ every page before --write")
    return "\n".join(lines)


# ── the ledger ───────────────────────────────────────────────────────────────

LEDGER_HEADER = """\
# The TY2026+ finals ledger (Phase J JT6): one row per draft pack re-pinned to its IRS final. Written by
# scripts/repin_final.py --write from its own comparison of the pinned draft and the final; never typed. The tests
# read it (every row is its pack's pin; a pack's draft "Created" stamp lives on here after the re-pin).
#   draft_* / final_*   the two blanks: url, sha256, the footer's "Created" date, pages; final_posted is the PDF's
#                       own metadata date
#   pages, widgets      of the final; cover_sheet_dropped: the draft's page 1 was the IRS cover sheet
#   rects_moved         widgets with a /Rect edge 0.1 pt or more off the draft's; largest_rect_delta is the largest
#                       difference of any edge in points, a nudge under 0.1 pt included
#   words_changed       page words that differ beyond the DRAFT banners and the footer date (0 on every row:
#                       anything else is needs_remap and is never written)
#   exceptions_cleared  label-adjacency exception rows the final cleared (formpacks/label_adjacency_exceptions.yaml)
#   verdict             identical | geometry_moved (the render was read); repinned: the date the pack moved

repins:
"""
LEDGER_KEYS = ("pack", "stem", "draft_url", "draft_sha256", "draft_created", "draft_pages", "final_url",
               "final_sha256", "final_posted", "final_created", "pages", "widgets", "cover_sheet_dropped",
               "rects_moved", "largest_rect_delta", "words_changed", "exceptions_cleared", "verdict", "repinned")
_QUOTED = {"draft_created", "final_posted", "final_created", "repinned"}


def load_ledger(repo: Path = REPO) -> dict[str, dict]:
    """pack id -> its ledger row. A row with a missing or unknown key, or a second row for a pack, is refused."""
    path = repo / LEDGER
    if not path.is_file():
        return {}
    rows: dict[str, dict] = {}
    for row in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("repins") or []:
        if set(row) != set(LEDGER_KEYS):
            raise RepinError(f"{LEDGER.as_posix()}: the row for {row.get('pack')!r} must carry exactly "
                             f"{', '.join(LEDGER_KEYS)}")
        if row["pack"] in rows:
            raise RepinError(f"{LEDGER.as_posix()}: two rows for {row['pack']}")
        rows[row["pack"]] = row
    return rows


def format_row(row: dict) -> str:
    def cell(key: str) -> str:
        value = row[key]
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        return json.dumps(value) if key in _QUOTED else str(value)

    return "".join(f"{'- ' if key == 'pack' else '  '}{key}: {cell(key)}\n" for key in LEDGER_KEYS)


def ledger_text(text: str, rows: list[dict]) -> str:
    """The ledger file with ``rows`` under its header comment (the rows are machine-written, the header is not)."""
    head, sep, _ = text.partition("\nrepins:")
    if not sep:
        raise RepinError(f"{LEDGER.as_posix()}: no top-level 'repins:' block")
    return head + "\nrepins:\n" + "".join(format_row(r) for r in rows)


# ── packs, stems and blanks ──────────────────────────────────────────────────


def irs_stem(url: str) -> str | None:
    """'f1040sc' for irs-dft/f1040sc--dft.pdf and irs-prior/f1040sc--2026.pdf; None for any other URL."""
    m = re.fullmatch(r"https://www\.irs\.gov/pub/irs-(?:dft|prior)/([a-z0-9]+)--(?:dft|\d{4})\.pdf", url)
    return m.group(1) if m else None


def packs_by_stem(year: int, repo: Path = REPO) -> dict[str, tuple[str, Path, FormPack]]:
    out = {}
    for path in sorted((repo / "formpacks" / "federal" / str(year)).glob("*/pack.yaml")):
        pack = load_pack(path)
        stem = irs_stem(pack.source_url)
        if stem and (pack.source_status == "draft" or pack.source_url == FINAL_URL.format(stem=stem, year=year)):
            out[stem] = (f"federal/{year}/{path.parent.name}", path, pack)
    return out


def fetch_twice(url: str) -> bytes:
    """The final, downloaded twice; both downloads must hash equal (a CDN can serve a half-rolled file)."""
    import check_watches

    bodies = []
    for _ in range(2):
        reply = check_watches.get(url)
        if reply.status != 200 or b"%PDF" not in reply.body[:1024]:
            raise RepinError(f"{url} answered HTTP {reply.status}: no final PDF to compare")
        bodies.append(reply.body)
    a, b = (hashlib.sha256(x).hexdigest() for x in bodies)
    if a != b:
        raise RepinError(f"{url}: two downloads differ (sha256 {a[:16]}… and {b[:16]}…); try again later")
    return bodies[0]


def pinned_draft(stem: str, pack_id: str, pack: FormPack, final_sha: str, ledger: dict[str, dict],
                 cache_dir: Path | None) -> tuple[str, bytes]:
    """(draft url, bytes) of the draft the pack was authored on, from the blank cache and checksum-verified: the
    pack's own pin while it is a draft, the ledger's once it is re-pinned."""
    if pack.source_status == "draft":
        url, sha = pack.source_url, pack.pdf_sha256
    else:
        row = ledger.get(pack_id)
        if row is None:
            raise RepinError(f"{pack_id} is already final and {LEDGER.as_posix()} has no row for it: nothing "
                             "records which draft it was authored on")
        if pack.pdf_sha256 != final_sha:
            raise RepinError(f"{pack_id} is pinned to the final {pack.pdf_sha256[:16]}… and this file is "
                             f"{final_sha[:16]}…: the IRS revised a final, which is a re-audit by hand")
        url, sha = row["draft_url"], row["draft_sha256"]
    path = cached_blank_path(url, sha, cache_dir=cache_dir)
    if path is None:
        raise RepinError(f"{pack_id}: the pinned draft {url} (sha256 {sha[:16]}…) is not in the blank cache; "
                         "the comparison needs it (TAXFILL_BLANKS_CACHE, or `taxfill fetch-blank` while irs-dft "
                         "still serves it)")
    return url, path.read_bytes()


def label_adjacency_preview(c: Comparison, pack: FormPack, final: bytes) -> None:
    """What the label-adjacency gate will say once the pack points at the final (read-only)."""
    import label_adjacency as LA

    with tempfile.TemporaryDirectory() as tmp:
        blank = Path(tmp) / "final.pdf"
        blank.write_bytes(final)
        res = LA.check_blank(c.pack, blank, LA.B.pack_keys(pack), pack.acroform_root or "", LA.load_conventions())
        exceptions = LA.load_exceptions()
        c.clearing = res.stale(exceptions)
        c.unexcused = [f"{r.id} anchor={r.widget.printed_line} keys={sorted(r.claims)}"
                       for r in res.unexcused(exceptions)]


# ── the write: every edit as text ────────────────────────────────────────────


def _sub_once(pattern: str, repl, text: str, what: str) -> str:
    out, n = re.subn(pattern, repl, text, count=0, flags=re.M)
    if n != 1:
        raise RepinError(f"{what}: expected exactly one match, found {n}; edit it by hand")
    return out


def pack_text(text: str, c: Comparison, date: str) -> str:
    """The pack re-pinned: four keys, signature.page (the only page-indexed key of the FormPack schema) and one
    header line."""
    text = _sub_once(r"^source_url:[ \t]*\S+[ \t]*$", f"source_url: {c.final_url}", text, "pack source_url")
    text = _sub_once(r'^pdf_sha256:[ \t]*(["\']?)[0-9a-f]{64}\1[ \t]*$',
                     lambda m: f"pdf_sha256: {m.group(1)}{c.final.sha256}{m.group(1)}", text, "pack pdf_sha256")
    text = _sub_once(r"^source_status:[ \t]*draft\b.*$", "source_status: final", text, "pack source_status")
    text = _sub_once(r"^draft_created:.*\n", "", text, "pack draft_created")
    if c.offset:
        note = "# the final's page {new} (page {old} of the draft, behind its cover sheet)"

        def inline(m: re.Match) -> str:
            new = int(m.group(2)) - c.offset
            return f"{m.group(1)}{new}{m.group(3)}   {note.format(new=new, old=m.group(2))}"

        def block(m: re.Match) -> str:
            new = int(m.group(2)) - c.offset
            return f"{m.group(1)}{new}   {note.format(new=new, old=m.group(2))}"

        if re.search(r"^signature:[ \t]*\{", text, flags=re.M):
            text = _sub_once(r"^(signature:[ \t]*\{[^}\n]*?\bpage:[ \t]*)(\d+)([^}\n]*\})[^\n]*$", inline, text,
                             "pack signature.page")
        elif re.search(r"^signature:[ \t]*(#.*)?\n(?:[ \t]+.*\n)*?[ \t]+page:", text, flags=re.M):
            text = _sub_once(r"^(signature:[ \t]*(?:#.*)?\n(?:[ \t]+.*\n)*?[ \t]+page:[ \t]*)(\d+)[^\n]*$", block,
                             text, "pack signature.page")
    header = (f"# RE-PINNED TO THE IRS FINAL {date} (scripts/repin_final.py; verdict {c.verdict}; row in "
              f"{LEDGER.as_posix()}). The text below was written on the draft.\n")
    return header + text


def selection_text(text: str, c: Comparison) -> str:
    pattern = rf"^(- family:[^\n]*\n(?:  [^\n]*\n)*?  pack: {re.escape(c.pack)}\n(?:  [^\n]*\n)*?  pdf_sha256: )[0-9a-f]{{64}}"
    return re.sub(pattern, lambda m: m.group(1) + c.final.sha256, text, flags=re.M)


def adjudications_text(text: str, c: Comparison) -> tuple[str, int]:
    """Ids ``<pack>:p<N>:...`` re-keyed to the final's page."""
    if not c.offset:
        return text, 0
    return re.subn(rf"\b{re.escape(c.pack)}:p(\d+):", lambda m: f"{c.pack}:p{int(m.group(1)) - c.offset}:", text)


def form_lines_text(text: str, c: Comparison, final: bytes, date: str, rel: str) -> tuple[str, list[str], list[str]]:
    """(the knowledge pack with this form's ``form_lines`` entries recorded final, the keys moved, the keys whose
    caption is NOT verbatim on the final). An entry belongs to the form when its ``url`` is the pinned draft."""
    import check_quotes

    data = yaml.safe_load(text)
    mine = {k: e for k, e in (data.get("form_lines") or {}).items()
            if isinstance(e, dict) and e.get("url") == c.draft_url}
    if not mine:
        return text, [], []
    source = check_quotes.source_from_bytes(c.final_url, final, "repin")
    year = int(data.get("tax_year") or 0)
    failed = []
    for key, entry in mine.items():
        if not isinstance(entry.get("printed"), str):
            continue
        span = check_quotes.Span("form_lines", rel, year, f"form_lines.{key}", entry["printed"], [c.final_url],
                                 designator=entry["line"] if isinstance(entry.get("line"), str) else None)
        row = check_quotes.check_span(span, {c.final_url: source})
        if row["status"] != check_quotes.VERBATIM:
            failed.append(f"{key}: {row['status']} ({row.get('reason', '')}); closest: {row.get('closest', '')!r}")
    if failed:
        return text, [], failed
    lines = text.split("\n")
    start = lines.index("form_lines:")
    moved, key = [], None
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line and not line.startswith((" ", "#")):
            break                                       # the next top-level key
        m = re.fullmatch(r"  ([^\s#][^:]*):[ \t]*(#.*)?", line)
        if m:
            key = m.group(1).strip("'\"")
            continue
        if key not in mine:
            continue
        m = re.fullmatch(r"(    )(line_source|url|read):[ \t]*(.*)", line)
        if not m:
            continue
        quote = m.group(3)[:1] if m.group(3)[:1] in "'\"" else ""
        value = {"line_source": "final", "url": f"{quote}{c.final_url}{quote}",
                 "read": f"{quote or chr(34)}{date}{quote or chr(34)}"}[m.group(2)]
        lines[i] = f"{m.group(1)}{m.group(2)}: {value}"
        if m.group(2) == "url":
            moved.append(key)
    if sorted(moved) != sorted(mine):
        raise RepinError(f"{rel}: could not edit form_lines {sorted(set(mine) - set(moved))} as text; edit by hand")
    out = "\n".join(lines)
    for key in mine:
        FormLineEntry.model_validate(yaml.safe_load(out)["form_lines"][key])
    return out, moved, []


@dataclass
class Plan:
    texts: dict[Path, str] = field(default_factory=dict)   # repo-relative path -> new text
    notes: list[str] = field(default_factory=list)
    reminders: list[str] = field(default_factory=list)     # the steps this script never does


def plan_write(c: Comparison, pack_path: Path, final: bytes, *, date: str, repo: Path = REPO,
               exceptions_cleared: int = 0) -> Plan:
    """Every text edit of one re-pin, computed and validated in memory; nothing is written. Idempotent: a pack
    already pinned to this final keeps its text, its ledger row and its date."""
    if c.verdict not in WRITABLE:
        raise RepinError(f"{c.stem}: verdict {c.verdict}; --write is for {' or '.join(WRITABLE)} only")
    plan = Plan()
    year = int(c.pack.split("/")[1])
    old = pack_path.read_text(encoding="utf-8")
    transition = load_pack(pack_path).source_status == "draft"
    ledger = load_ledger(repo)

    def put(rel: Path, new: str, was: str) -> None:
        if new != was:
            plan.texts[rel] = new

    if transition:
        new = pack_text(old, c, date)
        repinned = FormPack.model_validate(yaml.safe_load(new))
        assert (repinned.source_url, repinned.pdf_sha256, repinned.source_status) == (c.final_url, c.final.sha256, "final")
        put(pack_path.relative_to(repo), new, old)
        if repinned.signature is not None and c.offset:
            plan.notes.append(f"signature.page is now {repinned.signature.page}")

    rel = Path("knowledge") / "anchor" / "selection.yaml"
    if (repo / rel).is_file():
        was = (repo / rel).read_text(encoding="utf-8")
        put(rel, selection_text(was, c), was)
    rel = Path("knowledge") / "anchor" / "adjudications.yaml"
    if transition and (repo / rel).is_file():
        was = (repo / rel).read_text(encoding="utf-8")
        new, n = adjudications_text(was, c)
        put(rel, new, was)
        if n:
            plan.notes.append(f"{n} adjudication id(s) re-keyed one page lower")

    rel = Path("knowledge") / "federal" / f"{year}.yaml"
    was = (repo / rel).read_text(encoding="utf-8")
    new, moved, failed = form_lines_text(was, c, final, date, rel.as_posix())
    if failed:
        raise RepinError(f"{c.stem}: {len(failed)} form_lines caption(s) are not VERBATIM on the final; nothing "
                         "was written. Re-read them on the final face and correct `printed`:\n    "
                         + "\n    ".join(failed))
    put(rel, new, was)
    if moved:
        plan.notes.append(f"form_lines recorded final, captions verbatim on the final: {', '.join(moved)}")
    still = [i for i, line in enumerate(new.split("\n"), 1) if c.draft_url in line or f"{c.stem}--dft.pdf" in line]
    if still:
        plan.reminders.append(f"{rel.as_posix()} still cites the draft {c.stem}--dft.pdf on line(s) "
                               f"{', '.join(map(str, still[:12]))}{' …' if len(still) > 12 else ''}: re-verify "
                               "those blocks on the final (JT6 Knowledge)")

    rows = list(ledger.values())
    mine = ledger.get(c.pack)
    if mine is None or mine["final_sha256"] != c.final.sha256:
        rows = [r for r in rows if r["pack"] != c.pack] + [c.ledger_row(date, exceptions_cleared)]
    was = (repo / LEDGER).read_text(encoding="utf-8") if (repo / LEDGER).is_file() else ""
    put(LEDGER, ledger_text(was or LEDGER_HEADER, rows), was)
    return plan


def exception_rows_text(text: str, stale: list[str]) -> tuple[str, list[str]]:
    """The label-adjacency exceptions table without the one-line rows named by ``stale`` ("<pack>:<field>:w<n>")."""
    out, removed = [], []
    for line in text.split("\n"):
        m = re.match(r'\s*- \{pack: ([^,]+), field: "([^"]+)", widget: (\d+),', line)
        if m and f"{m.group(1)}:{m.group(2)}:w{m.group(3)}" in stale:
            removed.append(f"{m.group(1)}:{m.group(2)}:w{m.group(3)}")
            continue
        out.append(line)
    return "\n".join(out), removed


def _run(args: list[str], what: str, follow_ups: list[str]) -> bool:
    done = subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True, text=True)
    if done.returncode:
        tail = "\n      ".join((done.stdout + done.stderr).strip().splitlines()[-6:])
        follow_ups.append(f"{what} exited {done.returncode}:\n      {tail}")
    return not done.returncode


def clear_exceptions(pack_id: str, final_path: Path, follow_ups: list[str]) -> list[str]:
    """Remove the label-adjacency exception rows the final cleared; the rows removed."""
    import label_adjacency as LA

    stale = LA.check_pack(pack_id, final_path).stale(LA.load_exceptions())
    if not stale:
        return []
    was = LA.EXCEPTIONS.read_text(encoding="utf-8")
    new, removed = exception_rows_text(was, stale)
    LA.EXCEPTIONS.write_text(new, encoding="utf-8")
    try:
        LA.load_exceptions()
    except ValueError as exc:   # a family left without rows: that is a hand edit
        LA.EXCEPTIONS.write_text(was, encoding="utf-8")
        follow_ups.append(f"label-adjacency exception rows {stale} cleared themselves but removing them leaves "
                          f"the table invalid ({exc}); edit {LA.EXCEPTIONS.name} by hand")
        return []
    if sorted(removed) != sorted(stale):
        follow_ups.append(f"stale label-adjacency rows not found as one-line rows: {sorted(set(stale) - set(removed))}")
    return removed


def regenerate(pack_ids: list[str], follow_ups: list[str]) -> None:
    """The generated files a re-pin moves: the label-adjacency coverage rows, the pack-path golden, the counts."""
    args = [a for pid in pack_ids for a in ("--pack", pid)]
    _run(["scripts/label_adjacency.py", *args, "--write-ledger"], "label_adjacency.py --write-ledger", follow_ups)
    _run(["scripts/label_adjacency.py", *args], "the label-adjacency gate (adjudicate the new disagreements)",
         follow_ups)
    _run(["scripts/golden_pack_path.py", "--write"], "golden_pack_path.py --write", follow_ups)
    _run(["scripts/sync_doc_counts.py", "--write"], "sync_doc_counts.py --write", follow_ups)


# ── the render ───────────────────────────────────────────────────────────────


def render(c: Comparison, pack: FormPack, final: bytes, out_dir: Path) -> list[str]:
    """A rehearsal fill of the FINAL blank through the pack's map, a sentinel on every fillable line, each page a
    PNG; returns what a reader must check. The reading is a human / agent step: this script never does it."""
    sys.path.insert(0, str(REPO / "packages" / "core" / "tests"))
    from taxfill_core.filler import fill_form, rehearsal_only
    from taxfill_core.render import render_pdf
    from test_formpacks_federal import synthetic_values

    out_dir = out_dir / c.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    blank = out_dir / f"{c.stem}_final_blank.pdf"
    blank.write_bytes(final)
    reserved = {f.line for f in pack.fields if f.reserved}
    values = {line: v for line, v in synthetic_values(pack).items() if line not in reserved}
    filled = out_dir / f"{c.stem}_filled.pdf"
    fill_form(pack, values, blank, filled, rehearsal=rehearsal_only(pack))
    pages = render_pdf(filled, out_dir, dpi=170)
    root = f"{pack.acroform_root}." if pack.acroform_root else ""
    page_of = {w.name: w.page for w in c.final.widgets}
    moved = {m["name"] for m in c.moved}
    rows = [{"line": f.line, "shows": "[X]" if values[f.line] is True else values[f.line], "page": page_of.get(root + f.field),
             "field": f.field, "moved": root + f.field in moved} for f in pack.fields if f.line in values]
    (out_dir / f"{c.stem}_sentinels.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    checks = [f"{c.stem}: READ {len(pages)} page(s) in {home_display(out_dir)} against {c.stem}_sentinels.json "
              f"({len(rows)} sentinels): each value sits in the box of its own printed line, none clipped"]
    if moved:
        checks.append(f"{c.stem}: the {len(moved)} moved boxes first: "
                      + ", ".join(r["line"] for r in rows if r["moved"]))
    if c.cover_sheet_dropped and pack.signature is not None:
        on_final = pack.signature.page - (c.offset if pack.source_status == "draft" else 0)
        checks.append(f"{c.stem}: the signature block is on page {on_final} of the final")
    return checks


# ── the command ──────────────────────────────────────────────────────────────

BENCHMARK = """The anchor benchmark, ONCE after the whole batch (every --test counts as a run; OUT is a scratch directory
outside the repo):
    uv run python scripts/anchor_benchmark.py --test --out OUT --note "JT6 re-pin: {stems} finals; no method change"
    uv run python scripts/anchor_benchmark.py --finalize --out OUT
    uv run python scripts/anchor_benchmark.py --check"""


def posted_stems(year: int) -> list[str]:
    stems = []
    for watched in check_finals.watch_list(year):
        code = check_finals.head_status(watched.final_url(year))
        print(f"  {code}  {watched.final_url(year)}")
        if code == 200:
            stems.append(watched.stem)
    return stems


def main(argv: list[str] | None = None, *, repo: Path = REPO, cache_dir: Path | None = None,
         regen: bool = True) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stems", nargs="*", help="IRS file stems (f1040, f1040s1 ...); default: every posted watched stem")
    ap.add_argument("--final", action="append", default=[], metavar="STEM=PATH", help="a local final PDF for a stem")
    ap.add_argument("--year", type=int, help="the tax year (default: the oldest provisional year)")
    ap.add_argument("--write", action="store_true", help="edit the pins (identical or geometry_moved only)")
    ap.add_argument("--render", type=Path, metavar="DIR", help="sentinel fill of each final, pages as PNG, into DIR")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="the re-pin date recorded (default: today)")
    ap.add_argument("--json", action="store_true", help="print the comparisons as JSON instead of the report")
    args = ap.parse_args(argv)
    say = (lambda *a: print(*a, file=sys.stderr)) if args.json else print
    try:
        dt.date.fromisoformat(args.date)
        local = dict(item.split("=", 1) for item in args.final)
        year = args.year or check_finals.provisional_year(repo)
        if year is None:
            raise RepinError("no provisional federal year: nothing to re-pin (pass --year)")
        packs = packs_by_stem(year, repo)
        stems = list(dict.fromkeys([*args.stems, *local]))
        if not stems:
            say(f"=== HEAD of every watched TY{year} stem ===")
            stems = posted_stems(year)
        ledger = load_ledger(repo)
        work = []
        for stem in stems:
            if stem not in packs:
                say(f"{stem}: no TY{year} pack mirrors this stem (a publication is a knowledge step, by hand)")
                continue
            pack_id, pack_path, pack = packs[stem]
            final_url = FINAL_URL.format(stem=stem, year=year)
            final = Path(local[stem]).expanduser().read_bytes() if stem in local else fetch_twice(final_url)
            draft_url, draft = pinned_draft(stem, pack_id, pack, hashlib.sha256(final).hexdigest(), ledger, cache_dir)
            c = compare(stem, pack_id, pack, draft, final, draft_url=draft_url, final_url=final_url)
            if regen and repo == REPO and c.verdict in WRITABLE:
                label_adjacency_preview(c, pack, final)
            work.append((c, pack_path, pack, final))
    except (RepinError, OSError, ValueError) as exc:
        print(f"repin_final: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([c.as_json() for c, *_ in work], indent=1))
    else:
        for c, *_ in work:
            print(report(c) + "\n")
        print("verdicts: " + (", ".join(f"{c.stem} {c.verdict}" for c, *_ in work) or "nothing to compare"))
    checks: list[str] = []
    if args.render:
        try:
            for c, _path, pack, final in work:
                if c.verdict in WRITABLE:
                    checks += render(c, pack, final, args.render)
        except (ValueError, OSError) as exc:
            print(f"repin_final: the rehearsal fill failed, which is a finding: {exc}", file=sys.stderr)
            return 1
        say("\nTO READ (a human or agent step; this script renders, it does not read):")
        for check in checks:
            say(f"  - {check}")
    if not args.write:
        return 0

    refused = [c.stem for c, *_ in work if c.verdict not in WRITABLE]
    if refused:
        print(f"repin_final: --write refused, nothing edited: {', '.join(refused)} need(s) a re-map by hand",
              file=sys.stderr)
        return 1
    follow_ups: list[str] = []
    reminders: list[str] = []
    try:
        for c, pack_path, _pack, final in work:
            cleared = len(c.clearing or [])
            plan = plan_write(c, pack_path, final, date=args.date, repo=repo, exceptions_cleared=cleared)
            if cached_blank_path(c.final_url, c.final.sha256, cache_dir=cache_dir) is None:
                with tempfile.TemporaryDirectory() as tmp:
                    (Path(tmp) / "final.pdf").write_bytes(final)
                    seed_blank(Path(tmp) / "final.pdf", c.final_url, c.final.sha256, cache_dir=cache_dir)
            for rel, text in plan.texts.items():
                (repo / rel).write_text(text, encoding="utf-8")
            say(f"{c.stem}: wrote " + (", ".join(p.as_posix() for p in plan.texts) or "nothing (already re-pinned)"))
            for note in plan.notes:
                say(f"    {note}")
            reminders += plan.reminders
            if regen and repo == REPO:
                final_path = cached_blank_path(c.final_url, c.final.sha256, cache_dir=cache_dir)
                removed = clear_exceptions(c.pack, final_path, follow_ups)
                if removed:
                    say(f"    {len(removed)} label-adjacency exception row(s) cleared themselves and were removed: "
                        + ", ".join(removed))
            if c.verdict == GEOMETRY_MOVED:
                reminders.append(f"{c.stem}: geometry moved ({len(c.moved)} boxes, largest {c.largest_delta} pt); "
                                  "the render must have been READ (--render DIR)")
    except RepinError as exc:
        print(f"repin_final: {exc}", file=sys.stderr)
        return 1
    if regen and repo == REPO and work:
        regenerate([c.pack for c, *_ in work], follow_ups)
        say("regenerated: the label-adjacency coverage rows, the pack-path golden, the doc counts")
    if work:
        say("\nNOT DONE HERE:")
        for item in reminders:
            say(f"  - {item}")
        say("  - " + BENCHMARK.format(stems=", ".join(c.stem for c, *_ in work)))
    if follow_ups:
        say("\nFOLLOW-UPS BY HAND:")
        for item in follow_ups:
            say(f"  - {item}")
    return 2 if follow_ups else 0


if __name__ == "__main__":
    raise SystemExit(main())
