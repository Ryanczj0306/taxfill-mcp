#!/usr/bin/env python
"""Quote-verbatim checker (Phase K JK23, 2026-10-24): hold every quoted span in the knowledge packs to its source.

The knowledge packs quote official documents: the state packs inside their prose (``tax.notes``, credit
``eligibility`` and a few other fields, where a quoted span is written '...' or "..." or with curly quotes), the
federal packs in ``form_lines`` (each entry's ``printed`` is the face's caption, quoted whole), and a v2 pack
(Phase K JK24) in its ``{quote, ref}`` objects. A quote is a promise that the source prints exactly those words.
This script checks the promise: it collects every span with the URLs it can have come from, fetches each URL once
into a cache keyed by url + sha256 (the ``scripts/check_drift.py`` pattern), extracts the text (PDF through
pdfium, HTML through a plain parser) and reports each span as

  * **VERBATIM** -- found in a candidate source (the url and the PDF page are recorded);
  * **MISMATCH** -- every candidate source was read and none prints the span; the closest source passage and
    its similarity are recorded, so the fix tranche starts from the right sentence;
  * **UNCHECKED** -- the span has no candidate URL, or a candidate could not be read (the host refused the
    script, the URL is in the freshness quarantine, the download failed, the file is neither PDF nor HTML, the
    PDF has no text layer). A span is never called a MISMATCH while one of its candidates is unread: the words
    may be in the unread one. The reason is always recorded.

Candidates: a span's own citation when it has one (a form_lines entry's ``url``; a credit's ``citation.url``; a
v2 quote's ``ref`` row); otherwise every URL the pack cites (its ``sources`` table when it has one, else every
inline ``url``).

Normalisation (both sides, so it is symmetric): NFKC; whitespace, quote marks (straight and curly), hyphens and
dashes, dot leaders, soft hyphens, underscores and form-face arrows / bullets are dropped, so a PDF's line-break
hyphenation, its lost or extra spaces and a quote's re-typed punctuation do not count; a span's ellipsis ("..."
or the single character) is a gap of at most ``ELLIPSIS_GAP`` characters and an editorial ``[bracket]`` one of at
most ``BRACKET_GAP``; leading and trailing sentence punctuation of a span is not compared. Case must match except
where the source passage is ALL-CAPS, and for the span's first letter (a quote may start a sentence the source
continues); a span found only ignoring case is a MISMATCH that says so.

REPORT mode (the default, JK23) always exits 0. ``--strict`` (for JK26) exits 1 on any MISMATCH. Mismatches go to
a JK27-style fix tranche: each is re-read at the pack's own cited source before anything is changed (JS2c's
procedure, docs/dev/HISTORY.md "JS2c"; CONTRIBUTING.md "Quote-verbatim checker").

Network: the weekly ``.github/workflows/freshness.yml`` runs it; ``ci.yml`` runs only the offline tests
(packages/core/tests/test_check_quotes.py). A URL already in the shared blank cache (``.cache/blanks``,
``TAXFILL_BLANKS_CACHE``) is read from there; ``--offline`` reads only the caches; ``--pack`` checks named pack
files only. Run: ``uv run python scripts/check_quotes.py [--json report.json] [--strict] [--pack PATH ...]``.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import difflib
import hashlib
import html.parser
import json
import http.cookiejar
import re
import ssl
import sys
import urllib.request
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from taxfill_core import fetch as _fetch  # noqa: E402

import freshness_quarantine  # noqa: E402

VERBATIM, MISMATCH, UNCHECKED, CLOSED = "VERBATIM", "MISMATCH", "UNCHECKED", "CLOSED"
STATUSES = (VERBATIM, MISMATCH, CLOSED, UNCHECKED)
DEFAULT_CACHE = REPO / ".cache" / "quotes"
# Phase K JK31 (2026-10-25): the MISMATCHes closed as the checker's false positives, each with the reason it was
# re-read and found to be the printed words (see load_closures). Self-clearing: an entry that no longer matches a
# MISMATCH is reported as stale, and --strict fails on it.
DEFAULT_CLOSED = REPO / "scripts" / "check_quotes_closed.yaml"
TIMEOUT = 60.0
ELLIPSIS_GAP = 4000  # normalised characters an ellipsis may stand for (a form face's caption ... line total)
BRACKET_GAP = 40  # an editorial [insertion] replaces at most this many normalised characters
MIN_WORDS = 2  # a one-word span ('z', 'Exempt') is a term, not a quote: too short to attribute
PASSAGE_CHARS = 400
GARBLED_SHARE = 0.05  # an English tax document's text layer with more non-ASCII letters than this is mis-encoded

# ── span extraction ──────────────────────────────────────────────────────────────────────────────────────────────

_OPEN_BEFORE = set(" \t\n([{/—–-:;,\"“")  # what may precede an opening single quote


def _closes_single(text: str, i: int) -> bool:
    """A ' or ’ at ``i`` can close a single-quoted span: it follows a non-space and is not inside a word (What's)."""
    if i == 0 or text[i - 1].isspace():
        return False
    return i + 1 >= len(text) or not text[i + 1].isalnum()


def _opens_single(text: str, i: int) -> bool:
    """A ' at ``i`` can open a span: at the start or after a space / bracket / dash, and followed by a non-space."""
    if i + 1 >= len(text) or text[i + 1].isspace():
        return False
    return i == 0 or text[i - 1] in _OPEN_BEFORE


def extract_spans(text: str) -> list[str]:
    """The quoted spans of a prose string, outermost first, in order.

    Openers: ``"`` and ``“`` (closed by the next ``"`` / ``”``), ``‘`` and a ``'`` that starts a word (closed by
    the next ``'`` / ``’`` that ends one, so the apostrophes in "What's" and "Georgia's" neither open nor close).
    Quotes nested in a span stay part of it. A span of fewer than ``MIN_WORDS`` words is dropped.
    """
    spans: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        end = -1
        if ch in "\"“":
            closers = "\"”" if ch == '"' else "”\""
            end = next((j for j in range(i + 1, n) if text[j] in closers), -1)
        elif ch == "‘" or (ch == "'" and _opens_single(text, i)):
            end = next((j for j in range(i + 1, n) if text[j] in "'’" and _closes_single(text, j)), -1)
        if end > i:
            span = text[i + 1:end].strip()
            if len(span.split()) >= MIN_WORDS:
                spans.append(span)
            i = end + 1
            continue
        i += 1
    return spans


# ── normalisation ────────────────────────────────────────────────────────────────────────────────────────────────

_DROP = (set("\"'\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f\u00b4`\u2032\u2033")  # quote marks
         | set("-\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00ad_")  # hyphens, dashes, soft hyphen, underscore
         | set("\u25b6\u25ba\u25b8\u2022\u25aa\u25a0\u25a1\u2610\u2713\u2714\u2192\u21d2")  # arrows, bullets
         | set("\ufffe\ufffd\uffff"))  # pdfium writes U+FFFE for a soft hyphen at a line break
_DOT_LEADER = re.compile(r"\.(?:\s*\.){2,}|\.(?:\s+\.)+")  # "....", ". . . .", and a form face's short ". ."
_GAP = re.compile(r"…|\.\s*\.\s*\.|\[[^\]]{0,60}\]")
_EDGE_PUNCT = ".,;:!?"
_DIGIT_DASH = re.compile(r"(?<=\d)\s*([-\u2010\u2011\u2012\u2013\u2014\u2015\u2212])\s*(?=\d)")


def _lower(c: str) -> str:
    low = c.lower()
    return low if len(low) == 1 else c


def normalise(text: str) -> tuple[str, list[int]]:
    """(key, origin): ``text`` with the ignorable characters dropped, and each key character's index in ``text``.

    NFKC is applied per character, so ``origin`` points into ``text`` itself (a ligature or a full-width digit
    expands without shifting later positions). Case is kept: the caller lowers per character, which keeps
    positions. Dot leaders are dropped whole.
    """
    leaders = {k for m in _DOT_LEADER.finditer(text) for k in range(m.start(), m.end())}
    # Phase K JK23 review (2026-10-24): a hyphen or dash BETWEEN TWO DIGITS is a separator, not a line-break hyphen, so it
    # is kept as "-" (any dash style); dropping it merged figures, and a quoted "line 1-4" matched a source's "line 14".
    ranges = {m.start(1) for m in _DIGIT_DASH.finditer(text)}
    key: list[str] = []
    origin: list[int] = []
    for idx, raw in enumerate(text):
        if idx in leaders:
            continue
        if idx in ranges:
            key.append("-")
            origin.append(idx)
            continue
        for c in (raw if raw.isascii() else unicodedata.normalize("NFKC", raw)):
            if c.isspace() or c in _DROP or unicodedata.category(c) == "Cc":
                continue
            key.append(c)
            origin.append(idx)
    return "".join(key), origin


def _segments(span: str) -> list[tuple[str, int]]:
    """The span cut at its gaps: [(normalised segment, the gap allowed BEFORE it)], edge punctuation stripped."""
    out: list[tuple[str, int]] = []
    gap_before = 0
    pos = 0
    pieces: list[tuple[str, int]] = []
    for m in _GAP.finditer(span):
        pieces.append((span[pos:m.start()], gap_before))
        gap_before = BRACKET_GAP if m.group(0).startswith("[") else ELLIPSIS_GAP
        pos = m.end()
    pieces.append((span[pos:], gap_before))
    for piece, gap in pieces:
        key = normalise(piece)[0].strip(_EDGE_PUNCT)
        if key:
            out.append((key, gap if out else 0))
    return out


# ── sources ──────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclasses.dataclass
class Source:
    """One URL's text (or why it could not be read)."""

    url: str
    text: str = ""
    sha256: str = ""
    kind: str = ""  # pdf | html
    pages: list[int] = dataclasses.field(default_factory=list)  # start offset of each PDF page in ``text``
    origin: str = ""  # where the bytes came from: download | blank cache | quote cache
    unreadable: str = ""  # the reason, when the text could not be read

    def __post_init__(self) -> None:
        self._key: str | None = None
        self._relaxed: str | None = None

    def keyed(self) -> tuple[str, str, list[int]]:
        if self._key is None:
            key, self._origin = normalise(self.text)
            self._orig_key = key
            self._key = "".join(_lower(c) for c in key)
        return self._key, self._orig_key, self._origin

    def page_of(self, offset: int) -> int | None:
        if not self.pages:
            return None
        page = 0
        for i, start in enumerate(self.pages):
            if start <= offset:
                page = i
        return page + 1


class _Text(html.parser.HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    _BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_text(data: bytes) -> str:
    match = re.search(rb"charset=[\"']?([A-Za-z0-9_-]+)", data[:4096])
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    try:
        decoded = data.decode(encoding, errors="replace")
    except LookupError:
        decoded = data.decode("utf-8", errors="replace")
    parser = _Text()
    parser.feed(decoded)
    parser.close()
    return "".join(parser.parts)


# Phase K JK31 (2026-10-25): a SHIFTED text layer. Some subset fonts carry no Unicode map and number their glyphs
# 29 below the character they draw, so the text layer reads "6SHFLDO" for "Special", "0XOWLSO\\" for "Multiply",
# a control character U+0003 for each space and U+0011 ... U+001C for ". / 0 ... 9" (Arkansas DFA's AR1000F,
# AR1000NR, AR2441 and AR1000TC, 2023-2025, render-checked). Every letter is ASCII, so the garbled-share test
# below does not catch it, and a span quoted from such a face was a MISMATCH with no closest passage at all. The
# fix is per font: a subset font ("ABCDEF+Name") whose characters include these control characters is decoded by
# +29 (and its ligature and curly-quote codes to theirs); every other font on the page is read as it is.
SHIFT = 29
_SHIFT_CONTROL = re.compile(r"[\x03-\x08\x0b\x0c\x0e-\x1f]")
# the codes these subsets give their ligatures and curly quotes ("GH\u00bfQHG" defined, "RႈFH" office, "Dependent\u00b6s")
_SHIFT_GLYPHS = {"\u00bf": "fi", "\u1087": "ff", "\u1088": "ffi", "\u00b6": "\u2019", "\u00b3": "\u201c", "\u00b4": "\u201d"}
_SUBSET_FONT = re.compile(r"^[A-Z]{6}\+")
EXTRACTOR = 2  # bumped when the text extraction changes, so a quote cache written by an older one is re-read


def _font_name(raw, textpage, index: int, buf) -> str:
    import ctypes

    flags = ctypes.c_int()
    length = raw.FPDFText_GetFontInfo(textpage, index, buf, len(buf), ctypes.byref(flags))
    return buf.raw[:max(0, length - 1)].decode("latin-1") if length else ""


def unshift_page(chars: list[tuple[str, str]]) -> str:
    """A page's text from its (character, font name) pairs, a shifted subset font's characters decoded."""
    seen: Counter[str] = Counter()
    ctrl: Counter[str] = Counter()
    for ch, font in chars:
        seen[font] += 1
        if _SHIFT_CONTROL.match(ch):
            ctrl[font] += 1
    shifted = {f for f in ctrl if _SUBSET_FONT.match(f) and ctrl[f] >= 3 and ctrl[f] / seen[f] >= 0.02}
    out: list[str] = []
    for ch, font in chars:
        if font in shifted:
            if 3 <= ord(ch) <= 93:
                ch = chr(ord(ch) + SHIFT)
            else:
                ch = _SHIFT_GLYPHS.get(ch, ch)
        out.append(ch)
    return "".join(out)


def _page_text(textpage) -> str:
    text = textpage.get_text_range()
    if not _SHIFT_CONTROL.search(text):
        return text
    import ctypes

    import pypdfium2.raw as raw

    buf = ctypes.create_string_buffer(256)
    count = raw.FPDFText_CountChars(textpage.raw)
    chars = [(chr(raw.FPDFText_GetUnicode(textpage.raw, i)), _font_name(raw, textpage.raw, i, buf))
             for i in range(count)]
    return unshift_page(chars)


def pdf_text(data: bytes) -> tuple[str, list[int]]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    parts: list[str] = []
    pages: list[int] = []
    offset = 0
    try:
        for page in doc:
            textpage = page.get_textpage()
            text = _page_text(textpage) + "\n"
            textpage.close()
            page.close()
            pages.append(offset)
            parts.append(text)
            offset += len(text)
    finally:
        doc.close()
    return "".join(parts), pages


def sniff(data: bytes) -> str:
    head = data[:2048].lstrip()
    if b"%PDF" in data[:1024]:
        return "pdf"
    low = head.lower()
    if low.startswith((b"<!doctype html", b"<html", b"<?xml")) or b"<html" in low or b"<body" in low:
        return "html"
    return ""


def source_from_bytes(url: str, data: bytes, origin: str) -> Source:
    """Extract ``data``'s text; a non-PDF/HTML file or a PDF without a text layer is unreadable, with the reason."""
    digest = hashlib.sha256(data).hexdigest()
    kind = sniff(data)
    if not data:
        return Source(url, sha256=digest, origin=origin, unreadable="the host answered with an empty body")
    if not kind:
        return Source(url, sha256=digest, origin=origin, unreadable="not a PDF or HTML document")
    try:
        text, pages = pdf_text(data) if kind == "pdf" else (html_text(data), [])
    except Exception as exc:  # a damaged file is unreadable, not a mismatch
        return Source(url, sha256=digest, kind=kind, origin=origin, unreadable=f"{kind} text extraction failed: {exc}")
    why = unreadable_text(text, kind)
    if why:
        # a garbled layer keeps its text: a span found verbatim in its clean fonts is still verbatim (check_span)
        keep = text if why.startswith("the text layer is garbled") else ""
        return Source(url, text=keep, sha256=digest, kind=kind, pages=pages if keep else [], origin=origin, unreadable=why)
    return Source(url, text=text, sha256=digest, kind=kind, pages=pages, origin=origin)


def unreadable_text(text: str, kind: str) -> str:
    """Why an extracted text cannot be checked against ('' when it can)."""
    if len(normalise(text)[0]) < 40:
        return "the PDF has no text layer" if kind == "pdf" else "the HTML page has no text"
    letters = [c for c in text if c.isalpha()]
    garbled = sum(1 for c in letters if not c.isascii()) / len(letters)
    if garbled > GARBLED_SHARE:
        # a font without a Unicode map: the text layer reads "taÝ year" for "tax year" (DC's 2023-2025 D-40 books)
        return f"the text layer is garbled ({garbled:.0%} of its letters are not ASCII)"
    return ""


def _fetch_failure(exc: BaseException) -> str:
    """A short reason for a failed download (the host refused, not found, unreachable, ...)."""
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, ssl.SSLError) or isinstance(getattr(seen, "reason", None), ssl.SSLError):
            # some state hosts serve an incomplete chain a browser completes and urllib does not (check_drift: warn)
            return "download failed: the host's TLS certificate could not be verified"
        seen = seen.__cause__ or seen.__context__
    if isinstance(exc, _fetch.RefusedFetchError):
        code = re.search(r"HTTP (\d+)", str(exc))
        return f"host refused the script (HTTP {code.group(1) if code else '403'})"
    code = re.search(r"HTTP (\d+)", str(exc))
    if code:
        return f"download failed: HTTP {code.group(1)}"
    if isinstance(exc, _fetch.OfflineFetchError):
        return "download failed: host unreachable"
    return f"download failed: {type(exc).__name__}"


def _download_with_cookies(url: str) -> bytes:
    """fetch._download (browser User-Agent, retries) through a fresh cookie jar, so a portal's cookie handshake
    completes instead of redirecting in a loop (check_drift._resolve's fix)."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    return _fetch._download(url, TIMEOUT, open_url=opener.open)


class SourceCache:
    """URL -> Source, fetched once per run and cached on disk keyed by url + sha256.

    ``<dir>/index.json`` maps each url to the sha256 of the bytes last read (and when); ``<dir>/text/<sha256>.json``
    holds the extracted text. Unreadable answers are not cached, so the next run tries again.
    """

    def __init__(self, directory: Path, *, offline: bool = False, refresh: bool = False,
                 blank_cache: Path | None = None, quarantined: dict[str, str] | None = None,
                 download=None) -> None:
        self.dir = directory
        self.offline = offline
        self.refresh = refresh
        self.blank_cache = blank_cache
        self.quarantined = quarantined or {}
        self._download = download or _download_with_cookies
        self._mem: dict[str, Source] = {}
        index = directory / "index.json"
        try:
            self.index: dict[str, dict] = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.index = {}

    def _cached(self, url: str) -> Source | None:
        row = self.index.get(url)
        if row is None or self.refresh:
            return None
        try:
            stored = json.loads((self.dir / "text" / f"{row['sha256']}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            return None
        if stored.get("extractor", 1) != EXTRACTOR:
            return None  # an older extraction: read the bytes again
        why = unreadable_text(stored["text"], stored["kind"])
        if why:
            return Source(url, sha256=row["sha256"], kind=stored["kind"], origin="quote cache", unreadable=why)
        return Source(url, text=stored["text"], sha256=row["sha256"], kind=stored["kind"], pages=stored["pages"],
                      origin="quote cache")

    def _store(self, source: Source) -> None:
        if source.unreadable or source.origin == "quote cache":
            return
        (self.dir / "text").mkdir(parents=True, exist_ok=True)
        path = self.dir / "text" / f"{source.sha256}.json"
        path.write_text(json.dumps({"text": source.text, "kind": source.kind, "pages": source.pages,
                                    "extractor": EXTRACTOR}), encoding="utf-8")
        self.index[source.url] = {"sha256": source.sha256, "read": dt.date.today().isoformat()}

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "index.json").write_text(json.dumps(self.index, indent=1, sort_keys=True), encoding="utf-8")

    def _bytes(self, url: str) -> tuple[bytes | None, str]:
        """(bytes, origin) or (None, reason)."""
        if self.blank_cache is not None:
            path = _fetch._cache_path(self.blank_cache, url)
            if path.is_file():
                return path.read_bytes(), "blank cache"
        if self.offline:
            return None, "not in the cache (offline run)"
        try:
            return self._download(url), "download"
        except Exception as exc:
            return None, _fetch_failure(exc)

    def get_many(self, urls: list[str], workers: int = 8) -> dict[str, Source]:
        """Read every url (downloads in parallel; pdfium text extraction serially, it is not thread-safe)."""
        todo: list[str] = []
        for url in dict.fromkeys(urls):
            if url in self._mem:
                continue
            if url in self.quarantined:
                self._mem[url] = Source(url, unreadable=f"in the freshness quarantine ({self.quarantined[url]})")
                continue
            cached = self._cached(url)
            if cached is not None:
                self._mem[url] = cached
            else:
                todo.append(url)
        if todo:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                for url, (data, how) in zip(todo, pool.map(self._bytes, todo)):
                    source = Source(url, unreadable=how) if data is None else source_from_bytes(url, data, how)
                    self._store(source)
                    self._mem[url] = source
        return {url: self._mem[url] for url in urls}


# ── matching ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _word_at(text: str, idx: int) -> str:
    """The run of letters and digits around ``text[idx]``."""
    lo = idx
    while lo > 0 and text[lo - 1].isalnum():
        lo -= 1
    hi = idx
    while hi < len(text) and text[hi].isalnum():
        hi += 1
    return text[lo:hi]


def _case_ok(span_seg: str, at: int, source: "Source", first: bool) -> bool:
    """Does ``span_seg`` match the source's key at ``at`` case-sensitively, but for the allowed differences?

    Allowed: a source word printed ALL-CAPS (a heading, an emphasised MULTIPLY), and the span's first letter (a
    quote may capitalise the word it starts with, or start mid-sentence in lower case).
    """
    _, orig_key, origin = source.keyed()
    src_seg = orig_key[at:at + len(span_seg)]
    if span_seg == src_seg:
        return True
    first_alpha = next((i for i, c in enumerate(span_seg) if c.isalpha()), None) if first else None
    for i, (a, b) in enumerate(zip(span_seg, src_seg)):
        if a == b or i == first_alpha:
            continue
        word = _word_at(source.text, origin[at + i])
        if any(c.islower() for c in word):
            return False
    return True


def _joins(left: str, right: str, *, at_end: bool) -> bool:
    """Would the span's edge character sit inside one word with its source neighbour (a quote cut mid-word)?

    Letters joined to letters are one word unless lower case meets upper case (a PDF's lost space: "incomeThis");
    digits joined to digits are one number; a digit followed by a lower-case letter at the span's END is a line
    designator cut short ('line 11' where the source prints 'line 11a'), and a letter after a digit at its START
    is a designator's tail ('a Gambling' inside '8a Gambling').
    """
    if left.isalpha() and right.isalpha():
        return not (left.islower() and right.isupper())
    if left.isdigit() and right.isdigit():
        return True
    if at_end:
        return left.isdigit() and right.isalpha() and right.islower()
    return left.isdigit() and right.isalpha()


def _edges_ok(source: "Source", start: int, end: int, first: str, last: str) -> bool:
    _, _, origin = source.keyed()
    lo, hi = origin[start], origin[end - 1]
    text = source.text
    if lo > 0 and _joins(text[lo - 1], first, at_end=False):
        return False
    return not (hi + 1 < len(text) and _joins(last, text[hi + 1], at_end=True))


_SENTENCE_PUNCT = re.compile(r"(?<!\d)[.,:;!?]|[.,:;!?](?!\d)")  # not the separators inside a figure


def _found_relaxed(span: str, source: Source) -> bool:
    """Is ``span`` in ``source`` once case and sentence punctuation are ignored on both sides? (Only classifies a
    MISMATCH: a heading the author ended with a period, a dropped serial comma.)"""
    if source._relaxed is None:
        source._relaxed = _SENTENCE_PUNCT.sub("", source.keyed()[0])
    key = source._relaxed
    segments = [(_SENTENCE_PUNCT.sub("", "".join(_lower(c) for c in seg)), gap) for seg, gap in _segments(span)]
    segments = [(seg, gap) for seg, gap in segments if seg]
    if not segments:
        return False
    start = key.find(segments[0][0])
    while start != -1:
        pos = start + len(segments[0][0])
        for seg, gap in segments[1:]:
            nxt = key.find(seg, pos, pos + gap + len(seg))
            if nxt == -1:
                break
            pos = nxt + len(seg)
        else:
            return True
        start = key.find(segments[0][0], start + 1)
    return False


# A span that ends a sentence must not stop where the source's sentence goes on: the next word the source prints
# after the hit starts in lower case (Phase K JK31 review, 2026-10-25: "If your total MGI is $41,496 or less, you may
# qualify." read VERBATIM against "... you may qualify for Kentucky Family Size Tax Credit."). A span that ends in an
# ellipsis says it stops early.
_SENTENCE_END = re.compile(r"[.!?][\"'\u201d\u2019)\]]*\s*$")
_ELLIPSIS_END = re.compile(r"(?:\.\.\.|\u2026)[\"'\u201d\u2019)\]]*\s*$")
_NEXT_PRINTED = re.compile(r"[\s\u00a0]*(\S)")


def _sentence_goes_on(source: "Source", end: int) -> bool:
    """Whether the source's next printed character after key position ``end`` continues a sentence (lower case)."""
    _, _, origin = source.keyed()
    m = _NEXT_PRINTED.match(source.text, origin[end - 1] + 1)
    return bool(m) and m.group(1).islower()


def find_span(span: str, source: Source) -> tuple[str, int, int] | None:
    """Where ``span`` occurs in ``source``: ('verbatim' | 'case', key start, key end), or None.

    A hit must start and end on a word boundary of the source (see :func:`_joins`), and a span that ends a sentence
    must not stop where the source's sentence goes on (:func:`_sentence_goes_on`).
    """
    segments = _segments(span)
    if not segments:
        return None
    key = source.keyed()[0]
    lowered = [("".join(_lower(c) for c in seg), seg, gap) for seg, gap in segments]
    first_low, first_orig, _ = lowered[0]
    first_char, last_char = segments[0][0][0], segments[-1][0][-1]
    ends_sentence = bool(_SENTENCE_END.search(span)) and not _ELLIPSIS_END.search(span)
    best: tuple[str, int, int] | None = None
    start = key.find(first_low)
    tries = 0
    while start != -1 and tries < 500:
        tries += 1
        ok_case = _case_ok(first_orig, start, source, True)
        pos = start + len(first_low)
        chained = True
        for low, orig, gap in lowered[1:]:
            nxt = key.find(low, pos, pos + gap + len(low))
            if nxt == -1:
                chained = False
                break
            ok_case = ok_case and _case_ok(orig, nxt, source, False)
            pos = nxt + len(low)
        if (chained and _edges_ok(source, start, pos, first_char, last_char)
                and not (ends_sentence and _sentence_goes_on(source, pos))):
            if ok_case:
                return "verbatim", start, pos
            best = best or ("case", start, pos)
        start = key.find(first_low, start + 1)
    return best


def _caption(span: str, designator: str) -> str:
    """A form_lines ``printed`` without the line designator its author set at its edges ("15 This is your
    taxable income", "9 9 Employer contributions ...", "Pensions and annuities 5a")."""
    tags = {designator, designator + ".", designator + ":"}
    words = span.split()
    while words and words[0] in tags:
        words.pop(0)
    while words and words[-1] in tags:
        words.pop()
    return " ".join(words)


def _designator_near(source: "Source", start: int, end: int, designator: str, reach: int = 300) -> bool:
    """Is ``designator`` printed as its own token within ``reach`` characters of the caption at key [start, end)?"""
    _, _, origin = source.keyed()
    lo, hi = max(0, origin[start] - reach), origin[end - 1] + reach
    window = source.text[lo:hi]
    token = r"(?<![A-Za-z0-9]){}(?![A-Za-z0-9])"
    if re.search(token.format(re.escape(designator)), window):
        return True
    split = re.fullmatch(r"(\d+)([a-z])", designator)  # "1k" printed as a "1" column beside a "k" row label
    return bool(split and re.search(token.format(split.group(1)), window)
                and re.search(token.format(split.group(2)), window))


def closest(span: str, source: Source) -> tuple[float, str, int | None]:
    """(similarity 0-1, the source passage that best resembles ``span``, its PDF page) by k-gram offset voting."""
    target = "".join(_lower(c) for c in "".join(seg for seg, _ in _segments(span)))
    key, _, origin = source.keyed()
    if not target or not key:
        return 0.0, "", None
    k = min(10, len(target))
    step = max(1, (len(target) - k) // 40)
    votes: Counter[int] = Counter()
    for i in range(0, len(target) - k + 1, step):
        gram = target[i:i + k]
        pos, hits = key.find(gram), 0
        while pos != -1 and hits < 40:
            votes[(pos - i) // 16] += 1
            hits += 1
            pos = key.find(gram, pos + 1)
    if not votes:
        return 0.0, "", None
    best_score, best = 0.0, (0, 0)
    for bucket, _ in votes.most_common(5):
        lo = max(0, bucket * 16 - 24)
        hi = min(len(key), bucket * 16 + len(target) + 40)
        matcher = difflib.SequenceMatcher(None, target, key[lo:hi], autojunk=False)
        blocks = [b for b in matcher.get_matching_blocks() if b.size]
        if not blocks:
            continue
        a, b = lo + blocks[0].b, lo + blocks[-1].b + blocks[-1].size
        score = difflib.SequenceMatcher(None, target, key[a:b], autojunk=False).ratio()
        if score > best_score:
            best_score, best = score, (a, b)
    a, b = best
    if b <= a:
        return 0.0, "", None
    passage = " ".join(source.text[origin[a]:origin[b - 1] + 1].split())
    if len(passage) > PASSAGE_CHARS:
        passage = passage[:PASSAGE_CHARS] + " …"
    return round(best_score, 3), passage, source.page_of(origin[a])


@dataclasses.dataclass
class Span:
    """One quoted span and where it lives."""

    kind: str  # tax.notes | credits | other | form_lines | v2.quote
    pack: str  # repo-relative pack path
    year: int
    where: str  # a path inside the pack, e.g. tax.notes[3]
    text: str
    urls: list[str]
    designator: str | None = None  # a form_lines entry's printed line designator
    elsewhere: list[str] = dataclasses.field(default_factory=list)  # the pack's other URLs, for a miscited span


def check_span(span: Span, sources: dict[str, Source]) -> dict:
    """The verdict for one span against its candidate sources (all already read)."""
    row = {"status": "", "kind": span.kind, "pack": span.pack, "year": span.year, "where": span.where,
           "span": span.text, "candidates": len(span.urls)}
    if not span.urls:
        return row | {"status": UNCHECKED, "reason": "no candidate source URL (the span has no citation and the "
                                                      "pack cites none)"}
    readable = [sources[u] for u in span.urls if not sources[u].unreadable]
    unread = [sources[u] for u in span.urls if sources[u].unreadable]
    case_hit = None
    for source in readable:
        found = find_span(span.text, source)
        if found and found[0] == "verbatim":
            _, _, origin = source.keyed()
            return row | {"status": VERBATIM, "url": source.url, "sha256": source.sha256,
                          "page": source.page_of(origin[found[1]])}
        if found and case_hit is None:
            case_hit = source
    caption = _caption(span.text, span.designator) if span.designator else span.text
    if caption != span.text and len(caption.split()) >= MIN_WORDS:
        # A face prints the designator in its own column, away from the caption on the text layer: the caption must
        # be verbatim and the designator printed as a token near it.
        for source in readable:
            found = find_span(caption, source)
            if found and found[0] == "verbatim" and _designator_near(source, found[1], found[2], span.designator):
                _, _, origin = source.keyed()
                return row | {"status": VERBATIM, "url": source.url, "sha256": source.sha256,
                              "page": source.page_of(origin[found[1]]),
                              "note": f"the designator {span.designator!r} is printed apart from the caption"}
    best = max(((closest(span.text, s), s) for s in readable), key=lambda t: t[0][0], default=None)
    near = {}
    if best is not None and best[0][1]:
        (score, passage, page), source = best
        near = {"closest": passage, "similarity": score, "closest_url": source.url, "closest_page": page,
                "closest_sha256": source.sha256}
    for source in unread:
        # Phase K JK31 (2026-10-25): a garbled text layer (DC's D-40 books: some fonts carry no Unicode map) is not
        # read for a MISMATCH, but a span found verbatim in its clean fonts is printed there.
        found = find_span(span.text, source) if source.text else None
        if found and found[0] == "verbatim":
            _, _, origin = source.keyed()
            return row | {"status": VERBATIM, "url": source.url, "sha256": source.sha256,
                          "page": source.page_of(origin[found[1]]),
                          "note": "found in the readable fonts of a partly garbled text layer"}
    if unread:
        reasons = sorted({f"{s.url}: {s.unreadable}" for s in unread})
        head = (f"not found in the {len(readable)} readable candidate source(s); " if readable else "")
        return row | {"status": UNCHECKED, "reason": head + f"{len(unread)} could not be read", "unread": reasons} | near
    # Every MISMATCH is reported; ``class`` says how far off it is, so the fix tranche takes the wording first.
    if case_hit:
        return row | {"status": MISMATCH, "class": "case", "reason": f"found only ignoring case (in {case_hit.url})"} | near
    punct = next((s for s in readable if _found_relaxed(span.text, s)), None)
    if punct:
        return row | {"status": MISMATCH, "class": "punctuation",
                      "reason": f"found only ignoring sentence punctuation (in {punct.url})"} | near
    for url in span.elsewhere:
        # a credit / v2 quote whose words ARE in another source the pack cites: the citation is what is wrong
        other = sources.get(url)
        hit = find_span(span.text, other) if other is not None and not other.unreadable else None
        if hit and hit[0] == "verbatim":
            return row | {"status": MISMATCH, "class": "citation", "found_in": url,
                          "reason": f"miscited: verbatim in {url}, which its own citation does not name"} | near
    return row | {"status": MISMATCH, "class": "wording",
                  "reason": f"not found in any of the {len(readable)} candidate source(s)"} | near


# ── collection ───────────────────────────────────────────────────────────────────────────────────────────────────


def _clean_url(value: object) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value.split()[0]
    return None


def _walk_urls(node: object, out: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            url = _clean_url(value) if key == "url" else None
            if url:
                out.append(url)
            else:
                _walk_urls(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_urls(item, out)


_LINK = re.compile(r"https?://[^\s'\"()<>]+\.pdf")


def _document_links(node: object, out: list[str], key: str | None = None) -> None:
    """Off-.gov PDF links written into citation ``source`` texts (see :func:`pack_urls`)."""
    from taxfill_core.state_sources import is_gov

    if isinstance(node, dict):
        for k, v in node.items():
            _document_links(v, out, k)
    elif isinstance(node, list):
        for v in node:
            _document_links(v, out, key)
    elif isinstance(node, str) and key in ("source", "descriptions"):
        out += [u for u in _LINK.findall(node) if not is_gov(u)]


def pack_urls(pack: dict) -> list[str]:
    """The URLs a pack cites: its ``sources`` table when it has one (JK20), else every inline ``url``; then the
    document links its citation texts name on a host the Citation model rejects.

    Phase K JK31 (2026-10-25): New Mexico's 2023/2024 PIT-1 instructions, rate tables and PIT-RC exist only on the
    Department's AWS document host (JK27): each citation's ``url`` is the .gov page that publishes them and the file
    link stays in its ``source`` text. Their words were MISMATCHes against the page; the file is the source."""
    table = pack.get("sources")
    urls: list[str] = []
    if isinstance(table, list) and table:
        urls = [u for row in table if isinstance(row, dict) and (u := _clean_url(row.get("url")))]
    else:
        _walk_urls(pack, urls)
    _document_links(pack, urls)
    return list(dict.fromkeys(urls))


def _own_urls(node: object) -> list[str]:
    """A dict's own citations: ``citation.url`` (or a citation list's single url), else its ``url``; then the url of
    each entry of its ``citations`` list. Phase K JK31 (2026-10-25): a credit that quotes two documents (its
    instructions, and the form face that prints the line's caption) names the second in ``citations``, as an
    ``amended_return`` block already does; before, the face's words were a MISMATCH ("citation" class)."""
    if not isinstance(node, dict):
        return []
    own: list[str] = []
    cite = node.get("citation")
    if isinstance(cite, dict) and (url := _clean_url(cite.get("url"))):
        own.append(url)
    elif isinstance(cite, list):
        urls = [u for c in cite if isinstance(c, dict) and (u := _clean_url(c.get("url")))]
        if len(set(urls)) == 1:
            own.append(urls[0])
    if not own and (url := _clean_url(node.get("url"))):
        own.append(url)
    more = node.get("citations")
    if own and isinstance(more, list):
        own += [u for c in more if isinstance(c, dict) and (u := _clean_url(c.get("url")))]
    if own:  # and the off-.gov document links its citation texts name (see pack_urls)
        _document_links({k: node.get(k) for k in ("citation", "citations")}, own)
    return list(dict.fromkeys(own))


# Strings that describe a source rather than state what it says: citation descriptions, the sources table,
# URLs and the pack's bookkeeping.
_SKIP_KEYS = {"citation", "citations", "all_citations", "sources", "source", "url", "web_pay_url", "jurisdiction",
              "tax_year", "schema_version", "credits_verification", "unverified", "verification", "lookup_path",
              "source_topic", "affects", "read", "line_source", "checked"}


def _prose(node: object, path: str, own: list[str], out: list[tuple[str, str, list[str]]]) -> None:
    """Every prose string under ``node`` with its path and its own citation: the url of the dict that holds it
    (directly, or through a list of strings), never one inherited from further up."""
    if isinstance(node, dict):
        own = _own_urls(node)
        for key, value in node.items():
            if key not in _SKIP_KEYS:
                _prose(value, f"{path}.{key}" if path else str(key), own, out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _prose(item, f"{path}[{i}]", own, out)
    elif isinstance(node, str):
        out.append((path, node, own))


def _v2_walk(node: object, path: str, own: str | None, rows: dict[str, str], out: list[tuple[str, str, str, str | None]]) -> None:
    """A v2 pack's checkable text as (what, path, text, url): ``quote`` for a knowledge_v2.Quote (``{quote, ref}``),
    ``prose`` for any other string (a Wording's ``text``, a plain field). The url is the row its own ``ref`` (or
    ``citation``) names, never one inherited from further up."""
    if isinstance(node, dict):
        ref = node.get("ref") if isinstance(node.get("ref"), dict) else node.get("citation")
        own = rows.get(ref.get("id")) if isinstance(ref, dict) and isinstance(ref.get("id"), str) else None
        if isinstance(node.get("quote"), str) and isinstance(node.get("ref"), dict):
            out.append(("quote", path, node["quote"], own))
            return
        for key, value in node.items():
            if key not in _SKIP_KEYS and key not in ("ref", "refs", "gaps"):
                _v2_walk(value, f"{path}.{key}" if path else str(key), own, rows, out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _v2_walk(item, f"{path}[{i}]", own, rows, out)
    elif isinstance(node, str):
        out.append(("prose", path, node, own))


def _kind(path: str) -> str:
    if path.startswith(("tax.notes", "tax.caveats")):
        return "tax.notes"
    return "credits" if path.startswith("credits") else "other"


def _span(kind: str, rel: str, year: int, path: str, text: str, own: list[str] | str | None,
          urls: list[str]) -> Span:
    """Candidates: a credit's or a v2 quote's own citations alone (the pack's other URLs are searched only to say
    where a miscited span does appear); any other span's own citations first, then every URL the pack cites."""
    own = [own] if isinstance(own, str) else list(own or [])
    if kind in ("credits", "v2.quote") and own:
        return Span(kind, rel, year, path, text, own, elsewhere=[u for u in urls if u not in own])
    if kind == "v2.quote":
        return Span(kind, rel, year, path, text, [])
    return Span(kind, rel, year, path, text, list(dict.fromkeys([*own, *urls])))


def collect_state_pack(pack: dict, rel: str) -> list[Span]:
    """A state pack's spans. v1: quoted spans in its prose. v2 (JK24): every Quote object, plus the quoted spans in
    its Wording texts and plain strings. See :func:`_span` for each span's candidate URLs."""
    year = int(pack.get("tax_year") or 0)
    urls = pack_urls(pack)
    spans: list[Span] = []
    if pack.get("schema_version") == 2:
        rows = {row["id"]: u for row in pack.get("sources") or []
                if isinstance(row, dict) and isinstance(row.get("id"), str) and (u := _clean_url(row.get("url")))}
        found: list[tuple[str, str, str, str | None]] = []
        _v2_walk(pack, "", None, rows, found)
        for what, path, text, own in found:
            if what == "quote":
                spans.append(_span("v2.quote", rel, year, path, text, own, urls))
                continue
            spans += [_span(_kind(path), rel, year, path, span, own, urls) for span in extract_spans(text)]
        return spans
    prose: list[tuple[str, str, list[str]]] = []
    _prose(pack, "", [], prose)
    for path, text, own in prose:
        spans += [_span(_kind(path), rel, year, path, span, own, urls) for span in extract_spans(text)]
    return spans


def collect_federal_pack(pack: dict, rel: str) -> list[Span]:
    year = int(pack.get("tax_year") or 0)
    spans: list[Span] = []
    for key, entry in (pack.get("form_lines") or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("printed"), str):
            url = _clean_url(entry.get("url"))
            spans.append(Span("form_lines", rel, year, f"form_lines.{key}", entry["printed"], [url] if url else [],
                              designator=entry.get("line") if isinstance(entry.get("line"), str) else None))
    return spans


def collect(knowledge: Path, packs: list[Path] | None = None) -> list[Span]:
    """Every span in the knowledge tree's federal and state packs, or in ``packs`` alone when given."""
    def rel(path: Path) -> str:
        try:
            return path.resolve().relative_to(REPO).as_posix()
        except ValueError:
            return path.name

    paths = list(packs) if packs else (sorted(knowledge.glob("federal/*.yaml"))
                                       + sorted(knowledge.glob("states/*/*.yaml")))
    spans: list[Span] = []
    for path in paths:
        pack = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(pack, dict):
            continue
        if "form_lines" in pack or path.parent.name == "federal":
            spans += collect_federal_pack(pack, rel(path))
        elif "jurisdiction" in pack:
            spans += collect_state_pack(pack, rel(path))
    return spans


# ── report ───────────────────────────────────────────────────────────────────────────────────────────────────────


def load_closures(path: Path | None) -> list[dict]:
    """The committed false-positive closures: a list of {pack, where, span, reason, read}, each one MISMATCH the
    fix tranche re-read at its cited source and found printed there (the text layer is what differs: a sentence
    split by a page break and the next page's running head, two columns read across, ...). ``span`` is the span
    exactly as the pack quotes it; ``read`` says how it was read (the rendered page, the digest); ``closest_sha256``
    is the first 16 hex of the sha256 of the source the checker's closest passage came from ('none': no close
    passage), and the closure holds only while that source is unchanged."""
    if path is None or not path.is_file():
        return []
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    for row in rows:
        missing = {"pack", "where", "span", "reason", "read", "closest_sha256"} - set(row)
        if missing:
            raise ValueError(f"{path.name}: an entry lacks {sorted(missing)}: {row}")
        if not re.fullmatch(r"[0-9a-f]{16}|none", str(row["closest_sha256"])):
            raise ValueError(f"{path.name}: closest_sha256 is the first 16 hex of the closest source's sha256, or "
                             f"'none' when the checker found no close passage: {row}")
    return rows


def _closure_holds(row: dict, closure: dict) -> bool:
    """Whether the source the MISMATCH's closest passage came from is still the one the closure was re-read against
    (Phase K JK31 review, 2026-10-25): a closure is bound to that digest, so a reissued source re-opens the span."""
    got = str(row.get("closest_sha256") or "")[:16]
    return got == ("" if closure["closest_sha256"] == "none" else closure["closest_sha256"])


def apply_closures(rows: list[dict], closures: list[dict]) -> list[dict]:
    """Mark each MISMATCH a closure names as CLOSED (in place); return the closures that matched no MISMATCH among
    the packs checked (stale: the quote was edited, the source now reads verbatim, or the source the closure was
    re-read against changed: its digest no longer matches, and the span stays a MISMATCH)."""
    checked = {r["pack"] for r in rows}
    by_key = {(c["pack"], c["where"], c["span"]): c for c in closures}
    used: set[tuple[str, str, str]] = set()
    for r in rows:
        key = (r["pack"], r["where"], r["span"])
        if r["status"] == MISMATCH and key in by_key and not _closure_holds(r, by_key[key]):
            r["closure_drift"] = (f"closed against the source {by_key[key]['closest_sha256']}, which now reads "
                                  f"{str(r.get('closest_sha256') or '')[:16] or 'no close passage'}: re-read it")
        elif r["status"] == MISMATCH and key in by_key:
            r["status"] = CLOSED
            r["closed_reason"] = by_key[key]["reason"]
            used.add(key)
    return [c for key, c in by_key.items() if key not in used and c["pack"] in checked]


def build_report(spans: list[Span], cache: SourceCache, workers: int = 8, closures: list[dict] | None = None) -> dict:
    sources = cache.get_many(sorted({u for s in spans for u in (*s.urls, *s.elsewhere)}), workers=workers)
    rows = [check_span(s, sources) for s in spans]
    stale = apply_closures(rows, closures or [])
    totals = Counter(r["status"] for r in rows)
    by = defaultdict(Counter)
    for r in rows:
        by[f"{r['kind']} {r['year']}"][r["status"]] += 1
    unread = Counter(s.unreadable.split(" (")[0] for s in sources.values() if s.unreadable)
    return {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "totals": {k: totals.get(k, 0) for k in STATUSES} | {"spans": len(rows)},
        "mismatch_classes": dict(Counter(r["class"] for r in rows if r["status"] == MISMATCH)),
        "stale_closures": stale,
        "by_kind_year": {k: dict(v) for k, v in sorted(by.items())},
        "sources": {"total": len(sources), "readable": sum(1 for s in sources.values() if not s.unreadable),
                    "unreadable_reasons": dict(unread.most_common()),
                    "rows": [{"url": s.url, "sha256": s.sha256, "kind": s.kind, "origin": s.origin,
                              "unreadable": s.unreadable} for s in sources.values()]},
        "spans": rows,
    }


def summary(report: dict, top: int = 25) -> str:
    t = report["totals"]
    src = report["sources"]
    lines = [f"Quote-verbatim check: {t['spans']} spans -- {t[VERBATIM]} VERBATIM, {t[MISMATCH]} MISMATCH, "
             f"{t.get(CLOSED, 0)} CLOSED (false positives; reasons in {DEFAULT_CLOSED.name}), "
             f"{t[UNCHECKED]} UNCHECKED",
             f"Sources: {src['total']} URLs, {src['readable']} read; unreadable: "
             + (", ".join(f"{k} x{v}" for k, v in src["unreadable_reasons"].items()) or "none"),
             "", f"{'kind year':<18} {'VERBATIM':>9} {'MISMATCH':>9} {'CLOSED':>7} {'UNCHECKED':>10}"]
    for key, counts in report["by_kind_year"].items():
        lines.append(f"{key:<18} {counts.get(VERBATIM, 0):>9} {counts.get(MISMATCH, 0):>9} "
                     f"{counts.get(CLOSED, 0):>7} {counts.get(UNCHECKED, 0):>10}")
    # wording first (closest first: a near miss is a paraphrase to restore), then citation, punctuation, case
    order = {"wording": 0, "citation": 1, "punctuation": 2, "case": 3}
    mism = sorted((r for r in report["spans"] if r["status"] == MISMATCH),
                  key=lambda r: (order[r["class"]], -r.get("similarity", 0), r["pack"], r["where"]))
    if mism:
        classes = Counter(r["class"] for r in mism)
        lines += ["", "MISMATCHES by class: " + ", ".join(f"{k} {classes[k]}" for k in order if classes[k]),
                  f"(wording first, closest first; {min(top, len(mism))} of {len(mism)}):"]
        for r in mism[:top]:
            page = f" p.{r['closest_page']}" if r.get("closest_page") else ""
            lines.append(f"  {r['pack']} {r['where']}: '{r['span'][:160]}'")
            lines.append(f"      {r['reason']}; closest ({r.get('similarity', 0):.2f}) "
                         f"{r.get('closest_url', '-')}{page}: '{r.get('closest', '')[:200]}'")
    for c in report.get("stale_closures") or []:
        lines.append(f"  STALE closure (matches no MISMATCH; delete it): {c['pack']} {c['where']}: '{c['span'][:120]}'")
    lines += ["", "Classes: wording = the words differ; citation = verbatim in another source the pack cites, not "
              "the one the span names; punctuation / case = found once sentence punctuation / case is ignored.",
              "Report mode: a MISMATCH is re-read at the pack's own cited source in a JK27-style fix tranche "
              "(JS2c's procedure) before anything changes."]
    return "\n".join(lines)


def _quarantined_urls(today: dt.date) -> dict[str, str]:
    try:
        entries = freshness_quarantine.load()
    except Exception:  # pragma: no cover - a broken quarantine file is check_drift's red, not ours
        return {}
    return {e.target: f"{e.fixed_by}, expires {e.expires}" for e in entries
            if e.kind == "drift" and not e.expired(today)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--knowledge", type=Path, default=REPO / "knowledge", help="the knowledge tree to scan")
    parser.add_argument("--pack", type=Path, action="append", default=[],
                        help="check only this pack file (repeat); default: the whole knowledge tree")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="the url + sha256 text cache")
    parser.add_argument("--closed", type=Path, default=DEFAULT_CLOSED,
                        help="the committed false-positive closures (MISMATCH -> CLOSED)")
    parser.add_argument("--json", type=Path, help="write the full JSON report here")
    parser.add_argument("--strict", action="store_true", help="exit 1 on any MISMATCH (JK26: enforcing mode)")
    parser.add_argument("--offline", action="store_true", help="read only the caches; download nothing")
    parser.add_argument("--refresh", action="store_true", help="re-download every URL even when cached")
    parser.add_argument("--top", type=int, default=25, help="mismatches listed in the summary")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    spans = collect(args.knowledge, args.pack)
    cache = SourceCache(args.cache, offline=args.offline, refresh=args.refresh,
                        blank_cache=_fetch.default_cache_dir(), quarantined=_quarantined_urls(dt.date.today()))
    report = build_report(spans, cache, workers=args.workers, closures=load_closures(args.closed))
    cache.save()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(summary(report, args.top))
    if args.strict and (report["totals"][MISMATCH] or report["stale_closures"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
