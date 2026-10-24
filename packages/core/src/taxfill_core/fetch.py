"""Blank-form fetching — dev plan sections 5, 7 and 8 (``fetch_blank``).

Blank official PDFs are **never vendored in the repo** (dev plan section 5).
:func:`fetch_blank` downloads them at runtime from official URLs into a
shared, gitignored cache directory (default ``<repo>/.cache/blanks/``) and
verifies them against the pack's ``pdf_sha256``. Official URL patterns:

- current-year forms:  ``https://www.irs.gov/pub/irs-pdf/<file>.pdf``
- prior-year revisions: ``https://www.irs.gov/pub/irs-prior/<file>--<year>.pdf``

Concurrency: writes are atomic (temp file + ``os.replace``) so multiple
agents can share one cache without ever observing a half-written PDF.

Freshness protocol (dev plan section 7): a checksum mismatch usually means
the IRS published a NEW revision of the form. The mismatching download is
quarantined next to the cache entry (never installed under the verified
name) and the error tells the author to render page 1, READ the printed
revision year and title, and only then update the pack's ``pdf_sha256`` —
a wrong-revision pack is worse than no pack.

Every failure message is prescriptive (dev plan section 11): it says exactly
what to do next.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from taxfill_core.datadir import home_display, user_path

__all__ = [
    "FetchError",
    "FirstPageFacts",
    "OfflineFetchError",
    "RefusedFetchError",
    "UnmappedBlank",
    "UnmappedBlankRefused",
    "cached_blank_path",
    "compute_sha256",
    "default_cache_dir",
    "fetch_blank",
    "fetch_pack_blank",
    "fetch_unmapped_blank",
    "inspect_unmapped_blank",
    "load_unmapped_blank",
    "seed_blank",
    "unmapped_cache_dir",
]

# Environment override for the shared cache location (useful in CI and for
# agents running outside the repo checkout).
CACHE_DIR_ENV = "TAXFILL_BLANKS_CACHE"

# A desktop browser User-Agent: irs.gov (and some state DOR sites) reject
# the default "Python-urllib/3.x" agent with 403.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Transient answers are retried (re-plan JK2): HTTP 429 and 5xx, a timeout, and a connection that never
# completed (URLError / ConnectionError) get three attempts with a short backoff — about 2 s, then 6 s — and a
# Retry-After header is honoured up to 30 s. HTTP 401/403 are NOT retried: they are the host's policy refusal,
# which routes to the pack's digest-verified mirror. 404 is an answer, not a flake. The Wayback mirrors go
# through the same loop, so a rate-limited (429) snapshot gets the retries too. ``_sleep`` is the injection
# point: tests monkeypatch it so the retries are instant.
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = (2.0, 6.0)  # seconds before attempt 2, before attempt 3
_RETRY_AFTER_CAP = 30.0
_sleep = time.sleep

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_PLACEHOLDER = "..."  # pack-authoring placeholder; never verifiable
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")

_OFFICIAL_PATTERNS_HINT = (
    "official URL patterns: current-year forms https://www.irs.gov/pub/irs-pdf/<file>.pdf, "
    "prior-year revisions https://www.irs.gov/pub/irs-prior/<file>--<year>.pdf"
)


class FetchError(RuntimeError):
    """A blank-form download failed; the message says what to do next."""


class RefusedFetchError(FetchError):
    """The official host answered 401/403 (a bot wall) — the mirror / seed-blank remedies apply (JS1b)."""


class OfflineFetchError(FetchError):
    """The network is unreachable (no HTTP response at all).

    Callers that can proceed from a pre-populated cache (e.g. the form-pack
    test harness) catch this subclass to skip gracefully.
    """


# Blank hosts outside .gov / .mil / *.state.<xx>.us that a state tax agency ITSELF serves its forms from.
# A download from one is allowed ONLY with a pinned sha256: the reviewed digest, not the host name, then vouches
# for the bytes, and the fixed host name keeps the rule from opening a path to arbitrary hosts. Each entry says
# how it was verified (Phase J JS4d).
PINNED_ONLY_BLANK_HOSTS: dict[str, str] = {
    "klvg4oyd4j.execute-api.us-west-2.amazonaws.com": (
        "New Mexico Taxation and Revenue Department's document library: tax.newmexico.gov/forms-publications/ "
        "loads its forms table through prod.realfile.rtsclients.com/js/rf-tables.js, which fetches from this "
        "API (read 2026-09-28)"
    ),
}


def compute_sha256(path: str | Path) -> str:
    """SHA-256 hex digest of a file (chunked read; suitable for large PDFs)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_cache_dir() -> Path:
    """The shared blank-PDF cache directory.

    Resolution order:

    1. the ``TAXFILL_BLANKS_CACHE`` environment variable, when set;
    2. ``<repo root>/.cache/blanks`` — the repo root is found by walking up
       from this file to the first directory containing both ``formpacks/``
       and ``pyproject.toml`` (works for editable installs from a checkout);
    3. ``<workspace root>/.cache/blanks`` (site-packages installs) — the same
       user-owned root the workspace resolver picks, so everything taxfill
       writes lives under ONE findable directory. The old last resort was
       ``<cwd>/.cache/blanks``, which for an MCP server meant "wherever the
       client launched from": unfindable, and a crash on a read-only cwd.

    The directory is NOT created here; :func:`fetch_blank` creates it.
    """
    env = os.environ.get(CACHE_DIR_ENV)
    if env:
        return user_path(env)  # an MCP client's JSON `env` block passes "~" through unexpanded (Phase K JK28)
    for parent in Path(__file__).resolve().parents:
        if (parent / "formpacks").is_dir() and (parent / "pyproject.toml").is_file():
            return parent / ".cache" / "blanks"
    from taxfill_core.workspace import default_workspace_root

    return default_workspace_root() / ".cache" / "blanks"


def _validate_sha256(sha256: str) -> str:
    digest = sha256.strip().lower()
    if digest == _SHA256_PLACEHOLDER:
        raise ValueError(
            "sha256 is the authoring placeholder '...' — refusing to verify a download "
            "against it; fetch once without a digest (fetch_blank(url)), render page 1 "
            "of the downloaded PDF and READ the printed form year and title to confirm "
            "the revision, then set the pack's pdf_sha256 to compute_sha256(path) "
            "(equivalently: shasum -a 256 <file>)"
        )
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError(
            f"sha256 {sha256!r} is not a 64-character hex SHA-256 digest — compute it "
            f"with compute_sha256(path) (equivalently: shasum -a 256 <file>) and pass "
            f"that, or pass sha256=None to skip verification"
        )
    return digest


def _cache_path(cache_dir: Path, url: str) -> Path:
    """Deterministic per-URL cache filename: <12-hex url digest>_<basename>.

    The URL digest prefix keeps same-named files from different sources
    (e.g. a state DOR 'form540nr.pdf') from colliding, while staying stable
    across processes so concurrent agents share one entry per URL.
    """
    url_digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    basename = Path(urllib.parse.urlparse(url).path).name or "download.pdf"
    return cache_dir / f"{url_digest}_{_UNSAFE_NAME_RE.sub('_', basename)}"


def cached_blank_path(url: str, sha256: str, *, cache_dir: str | Path | None = None) -> Path | None:
    """The blank :func:`fetch_blank` cached for ``url``, if it is on disk and matches ``sha256``; else None.

    Never downloads — the offline lookup verify and the tests use to FIND a pinned blank (Phase J JEa; they had
    reached into the private ``_cache_path``). A stale or foreign file under the cache name counts as absent.
    """
    try:
        path = _cache_path(user_path(cache_dir) if cache_dir is not None else default_cache_dir(), url)
        if path.is_file() and compute_sha256(path) == sha256.strip().lower():
            return path
    except OSError:
        pass
    return None


def _is_transient(exc: BaseException) -> bool:
    """A failure worth another attempt: HTTP 429 / 5xx, or no HTTP answer at all (timeout, refused, DNS)."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or 500 <= exc.code <= 599
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, OSError))


def _retry_delay(attempt: int, exc: BaseException) -> float:
    """Seconds to wait after failed attempt number ``attempt`` (1-based); Retry-After wins, capped."""
    delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)) - 1]
    headers = getattr(exc, "headers", None)
    retry_after = headers.get("Retry-After") if headers is not None else None
    if retry_after is not None:
        try:
            seconds = float(retry_after)
        except ValueError:
            seconds = None  # the HTTP-date form: keep the default backoff
        if seconds is not None and math.isfinite(seconds):  # "nan" / "inf" parse as floats: keep the default too
            delay = min(max(seconds, 0.0), _RETRY_AFTER_CAP)
    return delay


def _http_failure(url: str, exc: urllib.error.HTTPError, attempts: int) -> FetchError:
    if exc.code == 404:
        return FetchError(
            f"HTTP 404 (not found) for {url} — the file name or revision is wrong, "
            f"or the IRS moved it; {_OFFICIAL_PATTERNS_HINT}; find the exact file "
            f"name on irs.gov and fix the pack's source_url"
        )
    if exc.code in (401, 403):
        return RefusedFetchError(
            f"HTTP {exc.code} ({exc.reason}) for {url} — the server refused the request; retry in a minute if it is "
            f"transient. A host that refuses every non-browser fetcher has two remedies: "
            f"(1) a pack's mirror_urls (an exact, digest-verified Wayback snapshot of this URL) are tried "
            f"automatically — fetch through the pack (fetch_pack_blank) or pass mirrors=; (2) seed the cache by "
            f"hand: open the URL in a browser, save the PDF, and run `taxfill seed-blank <saved.pdf> --url {url} "
            f"--sha256 <the pack's pdf_sha256>` — the file is digest-checked before it is cached"
        )
    tried = f" (still failing after {attempts} attempts)" if attempts > 1 else ""
    return FetchError(
        f"HTTP {exc.code} ({exc.reason}) for {url}{tried} — retry later; if it persists, verify "
        f"the URL in a browser and fix the pack's source_url ({_OFFICIAL_PATTERNS_HINT})"
    )


def _download(url: str, timeout: float, *, open_url=None) -> bytes:
    """GET ``url`` with a browser User-Agent; a transient failure is retried (``_RETRY_ATTEMPTS``, ``_sleep``).

    ``open_url`` replaces ``urllib.request.urlopen`` (the pack-less fetch passes its per-hop-checking opener).
    """
    # Only a network URL can fail transiently; a file:// miss is final on the first read.
    attempts = _RETRY_ATTEMPTS if urllib.parse.urlparse(url).scheme in ("http", "https") else 1
    for attempt in range(1, attempts + 1):
        # A fresh Request per attempt: urllib's redirect handler keeps its visit counts on the Request it followed.
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with (open_url or urllib.request.urlopen)(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if attempt < attempts and _is_transient(exc):
                _sleep(_retry_delay(attempt, exc))
                continue
            raise _http_failure(url, exc, attempt) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if attempt < attempts:
                _sleep(_retry_delay(attempt, exc))
                continue
            reason = getattr(exc, "reason", exc)
            tried = f" after {attempt} attempts" if attempt > 1 else ""
            raise OfflineFetchError(
                f"could not reach {url} ({reason}){tried} — the network looks unreachable; connect "
                f"to the internet and retry, or pre-populate the shared cache by copying an "
                f"already-verified blank into place (fetch_blank tells you the cache path via "
                f"its return value; default cache: {home_display(default_cache_dir())})"
            ) from exc
    raise AssertionError("unreachable")  # pragma: no cover


_MIRROR_RE = re.compile(r"https://web\.archive\.org/web/\d{14}id_/(.+)")


def _from_mirror(url: str, mirrors, expected_digest: str | None, timeout: float, refused: "RefusedFetchError") -> bytes:
    """The official host refused (401/403): try each exact Wayback snapshot of ``url``, digest-verified (JS1b)."""
    if not mirrors:
        raise refused
    if expected_digest is None:
        raise FetchError(f"{refused} — a mirror is used only digest-verified, so pass the pack's pdf_sha256") from refused
    tried = []
    for mirror in mirrors:
        match = _MIRROR_RE.fullmatch(mirror)
        if match is None or match.group(1) != url:
            raise ValueError(f"refusing mirror {mirror!r}: it must be https://web.archive.org/web/<ts>id_/{url}")
        try:
            data = _download(mirror, timeout)
        except FetchError as exc:
            tried.append(f"{mirror}: {exc}")
            continue
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_digest:
            raise FetchError(
                f"mirror {mirror} served sha256 {actual}, not the pinned {expected_digest} — refusing it (a mirror is "
                f"trusted only byte-for-byte); nothing was cached. {refused}"
            )
        return data
    raise FetchError(f"{refused}. Every mirror failed too: " + "; ".join(tried)) from refused


def fetch_pack_blank(pack, cache_dir: str | Path | None = None, force: bool = False, *, timeout: float = 60.0) -> Path:
    """:func:`fetch_blank` for a form pack: its source_url, its pdf_sha256 and its mirror_urls."""
    return fetch_blank(pack.source_url, sha256=pack.pdf_sha256, cache_dir=cache_dir, force=force, timeout=timeout,
                       mirrors=getattr(pack, "mirror_urls", ()) or ())


def seed_blank(pdf: str | Path, url: str, sha256: str, *, cache_dir: str | Path | None = None) -> Path:
    """Copy a hand-downloaded blank into the cache for ``url`` after checking it against ``sha256`` (JS1b).

    The escape hatch for a host that refuses every non-browser fetcher: save the PDF from a browser, then seed it.
    A digest mismatch raises and caches nothing, exactly like a mismatched download.
    """
    expected = _validate_sha256(sha256)
    pdf = user_path(pdf)
    if not pdf.is_file():
        # A message names the file as "~/..." (Phase K JK28): the CLI prints it into a shell agent's transcript.
        raise FileNotFoundError(f"no file at {home_display(pdf)} — save the blank from the official URL in a browser, "
                                f"then seed that file")
    data = pdf.read_bytes()
    if b"%PDF" not in data[:1024]:
        raise FetchError(f"{home_display(pdf)} is not a PDF — save the form itself, not the page around it")
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise FetchError(
            f"{home_display(pdf)} has sha256 {actual}, not the pack's {expected} — a different revision; nothing cached"
        )
    cache = user_path(cache_dir) if cache_dir is not None else default_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    final_path = _cache_path(cache, url)
    _atomic_write(final_path, data)
    return final_path


def _atomic_write(final_path: Path, data: bytes) -> None:
    """Write via a same-directory temp file + os.replace so readers never see partial data."""
    tmp_path = final_path.with_name(f"{final_path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, final_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def fetch_blank(
    url: str,
    sha256: str | None = None,
    cache_dir: str | Path | None = None,
    force: bool = False,
    *,
    timeout: float = 60.0,
    mirrors: "Sequence[str]" = (),
) -> Path:
    """Download a blank official PDF into the shared cache; return its path.

    Args:
        url: official source URL of the blank form (the pack's ``source_url``).
            ``https://`` for real fetches; ``file://`` is accepted for tests.
        sha256: expected SHA-256 hex digest (the pack's ``pdf_sha256``).
            ``None`` skips verification (authoring mode). The literal
            placeholder ``"..."`` is refused with instructions for computing
            the real digest.
        cache_dir: cache directory; default :func:`default_cache_dir`
            (``<repo>/.cache/blanks``, overridable via ``TAXFILL_BLANKS_CACHE``).
        force: re-download even when a cached copy exists. A cached copy that
            fails the ``sha256`` check is re-downloaded regardless.
        timeout: socket timeout in seconds.
        mirrors: exact Wayback snapshots of ``url`` (a pack's ``mirror_urls``), tried only when the official host
            answers 401/403, and only digest-verified — a mismatch fails closed and caches nothing.

    Returns:
        Path of the cached PDF (deterministic per URL, shared across agents).

    Raises:
        ValueError: malformed URL scheme or unusable ``sha256`` (including
            the ``"..."`` placeholder).
        OfflineFetchError: the network is unreachable and no valid cached
            copy exists — connect or pre-populate the cache.
        FetchError: HTTP errors, non-PDF responses, or a checksum mismatch
            (likely a NEW IRS revision — see the freshness-protocol message).
    """
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("https", "http", "file"):
        raise ValueError(
            f"unsupported URL scheme {scheme!r} in {url!r} — blank forms are fetched "
            f"from official https:// .gov URLs ({_OFFICIAL_PATTERNS_HINT}); "
            f"file:// is accepted for offline tests"
        )
    if scheme in ("https", "http"):
        # Outbound only to official US government hosts — shared rule with
        # knowledge.validate_gov_url (.gov/.mil/state-government *.state.<xx>.us; bare
        # .us is an OPEN registry and is refused). source_url is the ONLY field that
        # triggers a network request, so a maliciously-authored or typo'd pack (e.g.
        # loaded via TAXFILL_DATA_DIR) must not fetch — or SSRF to — an arbitrary host.
        from taxfill_core.knowledge import is_official_gov_host

        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host in PINNED_ONLY_BLANK_HOSTS and sha256 is None:
            raise ValueError(
                f"refusing to fetch {url!r} without a pinned sha256: {host!r} is not a government host — it is "
                f"{PINNED_ONLY_BLANK_HOSTS[host]} — so a blank from it is accepted only against the pack's reviewed "
                f"pdf_sha256"
            )
        if not is_official_gov_host(host) and host not in PINNED_ONLY_BLANK_HOSTS:
            raise ValueError(
                f"refusing to fetch {url!r}: blank forms are downloaded only from official US "
                f"government hosts (.gov, .mil, or *.state.<xx>.us), not {host!r} — a pack's "
                f"source_url must be an official government URL ({_OFFICIAL_PATTERNS_HINT})"
            )
    expected_digest = _validate_sha256(sha256) if sha256 is not None else None

    cache_dir = user_path(cache_dir) if cache_dir is not None else default_cache_dir()
    final_path = _cache_path(cache_dir, url)

    if final_path.is_file() and not force:
        if expected_digest is None or compute_sha256(final_path) == expected_digest:
            return final_path
        # Stale or corrupt cache entry: fall through and re-download.

    try:
        data = _download(url, timeout)
    except RefusedFetchError as refused:
        data = _from_mirror(url, mirrors, expected_digest, timeout, refused)
    if b"%PDF" not in data[:1024]:
        head = data[:40]
        raise FetchError(
            f"the content downloaded from {url} is not a PDF (starts with {head!r}) — "
            f"the URL likely serves an HTML error or redirect page; open it in a "
            f"browser, find the real PDF link, and fix the pack's source_url "
            f"({_OFFICIAL_PATTERNS_HINT})"
        )

    if expected_digest is not None:
        actual_digest = hashlib.sha256(data).hexdigest()
        if actual_digest != expected_digest:
            cache_dir.mkdir(parents=True, exist_ok=True)
            quarantine = final_path.with_name(final_path.name + ".unverified")
            _atomic_write(quarantine, data)
            raise FetchError(
                f"checksum mismatch for {url}: downloaded sha256 {actual_digest} != "
                f"expected {expected_digest} — the IRS may have published a NEW revision "
                f"of this form (freshness protocol, docs/dev/DEV_PLAN.md section 7). The "
                f"download is quarantined at {quarantine}; render its page 1, READ the "
                f"printed form year and title, and only if it is still the correct "
                f"revision update the pack's pdf_sha256 to {actual_digest}. A "
                f"wrong-revision pack is worse than no pack."
            )

    cache_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(final_path, data)
    return final_path


# ── the pack-less (unmapped) fetch — Phase K JK14 (2026-10-24) ───────────────────────────────────────────────────
#
# A form with no pack has no reviewed digest, so nothing vouches for its bytes but the official host and the form
# itself. The rules (docs/dev/ROADMAP.md, JK14; docs/dev/adr/ADR-0002-fallback-surface.md, refusal rules 2-9):
# https only and every redirect hop on an official host; a PINNED_ONLY host and a host answering 401/403 are
# refused (no Wayback mirror without a digest), with a pointer to the user-supplied ``local_blank``; every call
# downloads (the pack cache is keyed by URL alone and trusted with sha256=None, and several state URLs are rotating
# "current" slots), into a namespace of its own keyed by sha256 with a (url, sha256, fetched_at) record; and the
# form's first page must print the requested tax year (and, when given, title) — on a fresh download and on a copy
# already in the namespace alike. XFA-only and scanned blanks are refused. fetch_blank's pack path is unchanged.

UNMAPPED_SUBDIR = "unmapped"          # <blank cache>/unmapped/<sha256>.pdf (+ .json record)
LOCAL_BLANKS_SUBDIR = "unmapped_blanks"  # <workspace>/<year>/unmapped_blanks/<sha256>.pdf (+ .json record)

_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
# A year printed within this share of the tallest one's glyph height competes with it (ADR-0002 rule 7).
_RIVAL_YEAR_RATIO = 0.8
_TITLE_BLOCK = 1 / 3                  # the top third of the visible page
# A revision date: "Rev." (or "Revision"/"Revised") governing the year directly — at most a month name or a numeric
# month(/day) between them ("Rev. December 2025", "(Rev. 12-2025)"). Phase K JK14 (2026-10-24): it is matched up to
# the year, since a looser "rev within 24 characters" read VA 760 2025's "Rev. 04/26 WEB 2025" (a print code, then
# the title year) as a revision date once revision dates were classified before the year comparison.
_REVISION_RE = re.compile(
    r"(?<![a-z])rev(?:ision|ised)?(?:\.|\b)\s*(?:date\s*:?\s*)?"
    r"(?:[a-z]{3,9}\.?,?\s*|\d{1,2}\s*[/.-]\s*(?:\d{1,2}\s*[/.-]\s*)?)?$",
    re.IGNORECASE,
)
# Phase K JK14 (2026-10-24): the accepted year must be printed at TITLE size, or a body-text date ("Due April 15,
# 2026") wins whenever the real title year is drawn as an image or vector art (the NY IT-201/IT-203 logo year is
# vector art; the text year there is the body-size "For the year January 1, 2025" line). The rule: the year's glyph
# height must be at least _TITLE_SIZE_RATIO x the _TITLE_SIZE_QUANTILE glyph height of the OTHER digits and capitals
# in the title block (outside every printed year) — the year stands above the bulk of the block's type. Like with
# like: a lowercase glyph is shorter than a digit at the same type size, so a median over all text (the first rule
# tried) put a body-size year at 1.3-1.4x on a lowercase-heavy page. Picked from measurement over the 250 cached
# non-draft pack blanks: NY IT-201 sets about half its capitals at each of two body sizes, so the median flips
# between them by year (1.02 for 2025, 1.20 for 2023); CO DR 0104PN 2023 sets a third of them at title size or
# larger, so a 0.7 quantile reads its title year as body text. Every quantile from 0.6 to 0.67 separates the two:
# body-size years (the revision dates, NY's period lines) score at most 0.98; the smallest title year is MO-1040's
# "2025 Individual Income Tax Return" at 1.13, the next 1.35. 0.63 is the middle of that range, 1.05 of that gap.
_TITLE_SIZE_RATIO = 1.05
_TITLE_SIZE_QUANTILE = 0.63
# Characters the title match ignores: whitespace, line breaks, hyphens and dashes, soft hyphen, pdfium's
# generated hyphen (U+FFFE) and its STX marker for a hyphenated line break.
_TITLE_SKIP = frozenset(" \t\r\n -‐‑‒–—―­￾\x02")


class UnmappedBlankRefused(FetchError):
    """The pack-less fetch refused a blank. ``reason`` names the rule; the message says what to do next."""

    def __init__(self, reason: str, message: str, *, revision_year: int | None = None):
        super().__init__(message)
        self.reason = reason
        self.revision_year = revision_year  # set on a revision_dated refusal: the year of the "Rev." date


@dataclass(frozen=True)
class FirstPageFacts:
    """What the form's first page (the first page with a widget, else page 1) prints in its title block."""

    page: int
    printed_year: int
    title_found: bool | None  # None when no expected_title was given


@dataclass(frozen=True)
class UnmappedBlank:
    """A blank accepted by the pack-less fetch. ``sha256`` is recorded, never pinned."""

    path: Path
    sha256: str
    fetched_at: str
    source_url: str
    origin: str  # "download" or "local_blank"
    tax_year: int
    page_count: int
    kind: str  # "acroform", "acroform_xfa_hybrid", or "flat" (no widget: nothing to fill)
    first_page: FirstPageFacts
    pinned: bool = False

    def to_dict(self) -> dict:
        out = asdict(self)
        out["path"] = str(self.path)
        return out


def unmapped_cache_dir(cache_dir: str | Path | None = None) -> Path:
    """The pack-less fetch's own namespace inside the blank cache (never a pack's cache entry)."""
    return (user_path(cache_dir) if cache_dir is not None else default_cache_dir()) / UNMAPPED_SUBDIR


def _local_blank_dir(workspace_root: str | Path | None, tax_year: int) -> Path:
    """Where a user-supplied blank is kept: under the year's workspace, so `taxfill purge` removes it."""
    from taxfill_core.workspace import Workspace, default_workspace_root

    base = user_path(workspace_root) if workspace_root is not None else default_workspace_root()
    return Workspace(base, tax_year).root / LOCAL_BLANKS_SUBDIR


def _check_tax_year(tax_year: int) -> int:
    if isinstance(tax_year, bool) or not isinstance(tax_year, int) or not 1900 <= tax_year <= 2100:
        raise ValueError(f"tax_year must be a four-digit year such as 2025, got {tax_year!r}")
    return tax_year


def _check_unmapped_url(url: str, *, allow_pinned_only: bool) -> str:
    """https and an official host (a PINNED_ONLY host only where ``allow_pinned_only``); returns the host."""
    from taxfill_core.knowledge import is_official_gov_host

    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise UnmappedBlankRefused(
            "not_https",
            f"refusing {url!r}: a form with no pack is fetched only over https:// from the agency's own site — "
            f"copy the PDF link from the agency's forms page (it starts with https://) and pass that",
        )
    if host in PINNED_ONLY_BLANK_HOSTS and not allow_pinned_only:
        raise UnmappedBlankRefused(
            "pinned_only_host",
            f"refusing to download {url!r}: {host!r} is not a government host — it is "
            f"{PINNED_ONLY_BLANK_HOSTS[host]} — so taxfill downloads from it only against a pack's reviewed "
            f"sha256, and a form with no pack has none. Open the agency's forms page in a browser, save the PDF, and "
            f"pass the saved file as local_blank together with this source_url",
        )
    if not is_official_gov_host(host) and host not in PINNED_ONLY_BLANK_HOSTS:
        raise UnmappedBlankRefused(
            "not_official_host",
            f"refusing {url!r}: a form with no pack is accepted only from an official US government host "
            f"(.gov, .mil, or *.state.<xx>.us), not {host!r} — find the form on the tax agency's own forms page "
            f"and pass that URL",
        )
    return host


class _OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Checks every redirect hop BEFORE it is requested: https and an official host (ADR-0002 rule 2)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            _check_unmapped_url(newurl, allow_pinned_only=False)
        except UnmappedBlankRefused as exc:
            raise UnmappedBlankRefused(
                "redirect_off_official",
                f"{req.full_url} redirected to {newurl!r}, which was not requested: {exc} — a form with no pack "
                f"follows a redirect only to https on an official host. Open the URL in a browser; if it lands on "
                f"the agency's own PDF, pass that final URL, otherwise save the PDF and pass it as local_blank",
            ) from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _unmapped_open(request, timeout=None):
    """urlopen through the per-hop-checking redirect handler (tests monkeypatch this)."""
    return urllib.request.build_opener(_OfficialRedirectHandler).open(request, timeout=timeout)


def _unmapped_download(url: str, timeout: float) -> bytes:
    try:
        return _download(url, timeout, open_url=_unmapped_open)
    except RefusedFetchError as exc:
        code = getattr(exc.__cause__, "code", "401/403")
        raise UnmappedBlankRefused(
            "host_refused",
            f"the official host answered HTTP {code} for {url} — it refuses non-browser downloads. A pack falls "
            f"back to a Wayback snapshot verified against its pinned sha256; a form with no pack has no digest, so "
            f"no mirror is used. Open the URL in a browser, save the PDF, and pass the saved file as local_blank "
            f"together with this source_url",
        ) from exc
    except OfflineFetchError as exc:
        raise OfflineFetchError(
            f"could not reach {url} ({getattr(exc.__cause__, 'reason', exc.__cause__)}) — the network looks "
            f"unreachable; connect and retry, or save the PDF in a browser and pass it as local_blank. A form with "
            f"no pack is never served from the cache instead of a fresh download"
        ) from exc
    except UnmappedBlankRefused:
        raise
    except FetchError as exc:
        cause = exc.__cause__
        if isinstance(cause, urllib.error.HTTPError):
            raise UnmappedBlankRefused(
                "http_error",
                f"HTTP {cause.code} ({cause.reason}) for {url} — open the agency's forms page in a browser, copy the "
                f"form's PDF link and pass that; if the error persists, save the PDF and pass it as local_blank",
            ) from exc
        raise


def _open_pdf_bytes(data: bytes, what: str):
    """pypdf reader over ``data``; an empty user password is tried, any other password refuses (rule 11)."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnmappedBlankRefused(
                "locked",
                f"{what} needs a password to open, so its fields cannot be read — download the unlocked blank from "
                f"the agency's forms page",
            )
        reader.pages  # noqa: B018 — force the page tree to parse here, inside the try
    except UnmappedBlankRefused:
        raise
    except Exception as exc:  # pypdf raises many types on a damaged file
        raise UnmappedBlankRefused(
            "unreadable",
            f"{what} could not be read as a PDF ({type(exc).__name__}) — download it again from the agency's forms "
            f"page; if a browser opens it, save it from there and pass it as local_blank",
        ) from exc
    return reader


def _widget_pages(reader) -> list[int]:
    pages = []
    for number, page in enumerate(reader.pages, 1):
        if any(a.get_object().get("/Subtype") == "/Widget" for a in page.get("/Annots") or []):
            pages.append(number)
    return pages


def _has_visible_text(page) -> bool:
    """Whether the page draws any text that is not invisible (render mode 3: the layer OCR lays over a scan)."""
    import pypdfium2.raw as pdfium_c

    for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_TEXT]):
        if pdfium_c.FPDFTextObj_GetTextRenderMode(obj.raw) != pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE:
            return True
    return False


def _title_block(page) -> list[tuple[str, float]]:
    """``(char, glyph height)`` for every character in the top third of the visible page, in text order.

    "Top" is the top as displayed: a /Rotate page turns user space, and pdfium reports char boxes unrotated.
    """
    import pypdfium2.raw as pdfium_c

    x0, y0, x1, y1 = page.get_cropbox()
    width, height = (x1 - x0) or 1.0, (y1 - y0) or 1.0
    rotation = page.get_rotation() % 360
    textpage = page.get_textpage()
    out: list[tuple[str, float]] = []
    try:
        for i in range(textpage.count_chars()):
            left, bottom, right, top = textpage.get_charbox(i)
            cx, cy = (left + right) / 2, (bottom + top) / 2
            if rotation == 90:
                depth, glyph = (cx - x0) / width, right - left
            elif rotation == 180:
                depth, glyph = (cy - y0) / height, top - bottom
            elif rotation == 270:
                depth, glyph = (x1 - cx) / width, right - left
            else:
                depth, glyph = (y1 - cy) / height, top - bottom
            if 0.0 <= depth <= _TITLE_BLOCK:
                out.append((chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, i)), glyph))
    finally:
        textpage.close()
    return out


def _title_in(text: str, title: str) -> bool:
    """``title`` occurs in ``text`` as a whole token sequence, ignoring case, spaces, hyphens and line breaks."""
    kept = [(i, ch.lower()) for i, ch in enumerate(text) if ch not in _TITLE_SKIP]
    hay = "".join(ch for _, ch in kept)
    needle = "".join(ch.lower() for ch in title if ch not in _TITLE_SKIP)
    if not needle:
        return False
    start = hay.find(needle)
    while start >= 0:
        first, last = kept[start][0], kept[start + len(needle) - 1][0]
        before = text[first - 1] if first > 0 else " "
        after = text[last + 1] if last + 1 < len(text) else " "
        # whole tokens: "SD 100" must not match inside "SD 1000", nor "1040" inside "11040"
        if not (before.isalnum() and needle[0].isalnum()) and not (after.isalnum() and needle[-1].isalnum()):
            return True
        start = hay.find(needle, start + 1)
    return False


def _is_title_size(block: list[tuple[str, float]], year_spans: list[tuple[int, int]], size: float) -> bool:
    """Whether a year printed at glyph height ``size`` is title-size in ``block`` (_TITLE_SIZE_RATIO).

    A block whose only digits and capitals are its years has nothing to compare with: the year is the title.
    """
    in_year = {k for start, end in year_spans for k in range(start, end)}
    reference = sorted(h for k, (ch, h) in enumerate(block)
                       if k not in in_year and h > 0 and (ch.isdigit() or ch.isupper()))
    if not reference:
        return True
    return size >= _TITLE_SIZE_RATIO * reference[min(len(reference) - 1, int(_TITLE_SIZE_QUANTILE * len(reference)))]


def _printed_year(block: list[tuple[str, float]], *, page: int, tax_year: int, what: str) -> int:
    """The tax year printed tallest in the title block, at title size.

    Refuses: no year in the text [no_printed_year]; a tallest year that is a revision date, whatever ``tax_year`` is
    [revision_dated]; a tallest year at body-text size [no_printed_year]; a rival year at title size
    [ambiguous_printed_year]; another year [wrong_year].
    """
    text = "".join(ch for ch, _ in block)
    years = [(int(m.group(1)), max(block[k][1] for k in range(m.start(), m.end())), m.start())
             for m in _YEAR_RE.finditer(text)]
    if not years:
        raise UnmappedBlankRefused(
            "no_printed_year",
            f"page {page} of {what} prints no year in the text of its title block, so taxfill cannot confirm it is "
            f"the {tax_year} form (its year may be drawn as an image) — render page {page}, read the printed year, "
            f"and if it is {tax_year} fill the printed form by hand from the agency's instructions",
        )
    year, size, at = max(years, key=lambda y: y[1])
    # Phase K JK14 (2026-10-24): a revision date is classified BEFORE any year comparison, so it is refused the same
    # way for every tax_year — before, "Rev. December 2025" passed for 2025 and was refused for 2024.
    revision = _REVISION_RE.search(text[max(0, at - 32):at])
    if revision:
        printed = " ".join((revision.group(0) + str(year)).split())
        raise UnmappedBlankRefused(
            "revision_dated",
            f"page {page} of {what} prints a revision date ({printed!r}) and no tax year: it is a continuous-use "
            f"revision, and the tax years it serves cannot be read from the page — so taxfill cannot confirm it is "
            f"the form for tax year {tax_year}. Confirm in the form's instructions which tax years the {year} "
            f"revision serves; the pack-less fetch takes no override for a revision-dated form (Phase K JK14), so "
            f"if it serves {tax_year}, fill the printed form by hand from those instructions",
            revision_year=year,
        )
    if not _is_title_size(block, [(start, start + 4) for _, _, start in years], size):
        raise UnmappedBlankRefused(
            "no_printed_year",
            f"page {page} of {what} prints no year at title size in the text of its title block — the tallest year "
            f"there ({year}) is set in body-text type, a date such as a due date, and the form's own year is "
            f"probably drawn as an image or vector art, so taxfill cannot confirm it is the {tax_year} form. Render "
            f"page {page}, read the printed year, and if it is {tax_year} fill the printed form by hand from the "
            f"agency's instructions",
        )
    rivals = sorted({y for y, h, _ in years if y != year and h >= _RIVAL_YEAR_RATIO * size})
    if rivals:
        raise UnmappedBlankRefused(
            "ambiguous_printed_year",
            f"page {page} of {what} prints {year} and {', '.join(map(str, rivals))} at the same title size, so "
            f"taxfill cannot tell which tax year the form is for — render page {page}, confirm the year, and pass the "
            f"URL of the single-year {tax_year} revision from the agency's forms page",
        )
    if year != tax_year:
        raise UnmappedBlankRefused(
            "wrong_year",
            f"page {page} of {what} is the {year} form, not {tax_year}: its title block prints {year} in the largest "
            f"type. Find the {tax_year} revision on the agency's forms page (a prior-year archive URL usually carries "
            f"the year) and fetch that URL; a rotating 'current' URL may already serve another year",
        )
    return year


def inspect_unmapped_blank(
    data: bytes | str | Path,
    *,
    tax_year: int,
    expected_title: str | None = None,
    what: str = "the blank",
) -> tuple[int, str, FirstPageFacts]:
    """Run the pack-less page checks on a blank; return ``(page_count, kind, first_page)`` or raise a refusal.

    Refused (:class:`UnmappedBlankRefused`, ``reason`` in brackets): a password-locked file [locked], a catalog
    that sets /NeedsRendering [needs_rendering], an /XFA packet with no AcroForm widget [xfa_only], a first page with
    no visible text [scanned], and a title block whose tallest printed year is a revision date [revision_dated, for
    every ``tax_year``], is not at title size [no_printed_year] or is not ``tax_year`` [no_printed_year,
    ambiguous_printed_year, wrong_year], or that does not print ``expected_title`` [title_not_found].
    The first page is the first page carrying a widget, else page 1 (a packet can open with instructions).
    """
    import pypdfium2 as pdfium

    tax_year = _check_tax_year(tax_year)
    if not isinstance(data, bytes):
        data = Path(data).read_bytes()
    reader = _open_pdf_bytes(data, what)
    root = reader.trailer["/Root"].get_object()
    acroform = root.get("/AcroForm")
    acroform = acroform.get_object() if acroform is not None else None
    has_xfa = acroform is not None and acroform.get("/XFA") is not None
    if bool(root.get("/NeedsRendering", False)):
        raise UnmappedBlankRefused(
            "needs_rendering",
            f"{what} is a dynamic XFA form (its catalog sets /NeedsRendering): its pages are drawn only by Adobe "
            f"Reader, and an AcroForm filler has nothing to write into — look on the agency's forms page for a "
            f"print or non-XFA fillable version, or fill this one in Adobe Reader by hand",
        )
    widget_pages = _widget_pages(reader)
    if has_xfa and not widget_pages:
        raise UnmappedBlankRefused(
            "xfa_only",
            f"{what} is an XFA-only form (an XFA packet and no AcroForm widget): an AcroForm filler has nothing to "
            f"write into — look on the agency's forms page for a print or non-XFA fillable version, or fill this one "
            f"in Adobe Reader by hand",
        )
    page_count = len(reader.pages)
    first = widget_pages[0] if widget_pages else 1
    kind = "flat" if not widget_pages else "acroform_xfa_hybrid" if has_xfa else "acroform"
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise UnmappedBlankRefused(
            "unreadable",
            f"{what} could not be opened for its text ({exc}) — download it again from the agency's forms page",
        ) from exc
    try:
        page = doc[first - 1]
        if not _has_visible_text(page):
            raise UnmappedBlankRefused(
                "scanned",
                f"page {first} of {what} has no text layer (a scanned image, or only an invisible OCR layer): taxfill "
                f"reads the printed text to check the year and to anchor values, so it cannot use this blank — look "
                f"on the agency's forms page for a fillable or text version, or fill the printed form by hand",
            )
        block = _title_block(page)
    finally:
        doc.close()
    year = _printed_year(block, page=first, tax_year=tax_year, what=what)
    title_found = None
    if expected_title is not None:
        text = "".join(ch for ch, _ in block)
        bare = re.sub(r"^\s*form\s+", "", expected_title, flags=re.IGNORECASE)
        title_found = _title_in(text, expected_title) or (bool(bare.strip()) and _title_in(text, bare))
        if not title_found:
            raise UnmappedBlankRefused(
                "title_not_found",
                f"{expected_title!r} is not printed in the title block of page {first} of {what} — this is not the "
                f"form you asked for, or its printed name differs: render page {first}, read the form's printed "
                f"name, and pass it as expected_title (or find the right form on the agency's forms page)",
            )
    return page_count, kind, FirstPageFacts(page=first, printed_year=year, title_found=title_found)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _store(directory: Path, data: bytes, digest: str, entry: dict) -> Path:
    """Write ``<digest>.pdf`` and append ``entry`` to ``<digest>.json`` (both atomic). Never a pack cache entry."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.pdf"
    if not (path.is_file() and compute_sha256(path) == digest):
        _atomic_write(path, data)
    record_path = directory / f"{digest}.json"
    try:
        record = json.loads(record_path.read_text())
        if record.get("sha256") != digest or not isinstance(record.get("fetches"), list):
            raise ValueError
    except (OSError, ValueError):
        record = {"sha256": digest, "fetches": []}
    record["fetches"].append(entry)
    _atomic_write(record_path, (json.dumps(record, indent=1) + "\n").encode("utf-8"))
    return path


def fetch_unmapped_blank(
    url: str,
    *,
    tax_year: int,
    expected_title: str | None = None,
    local_blank: str | Path | None = None,
    cache_dir: str | Path | None = None,
    workspace_root: str | Path | None = None,
    timeout: float = 60.0,
) -> UnmappedBlank:
    """Fetch the blank of a form that has no pack, check it, and record it (Phase K JK14).

    Args:
        url: the form's official ``https://`` URL (the agency's own PDF link). Every redirect hop must be https on an
            official host too.
        tax_year: the year the form is wanted for; the form's first page must print it as its title-block year.
        expected_title: the form's printed name (e.g. "SD 100"); when given it must appear in the title block.
        local_blank: a PDF the user saved from ``url`` in a browser — the route for a PINNED_ONLY host or a host
            that refuses scripts. It passes the same checks, and the year/title check stands in for a pin. It is
            kept under the year's workspace (``workspace_root``), so ``taxfill purge`` removes it.
        cache_dir: the blank cache; downloads go to its ``unmapped/`` namespace, keyed by sha256.

    Always downloads (a URL can be a rotating "current" slot, and the pack cache trusts any file under a URL when no
    digest is given); never reads or writes a pack's cache entry. Raises :class:`UnmappedBlankRefused` (with a
    ``reason`` and a next step), :class:`OfflineFetchError`, or ValueError for a bad ``tax_year``.
    """
    tax_year = _check_tax_year(tax_year)
    if local_blank is not None:
        _check_unmapped_url(url, allow_pinned_only=True)
        path = user_path(local_blank)
        what = f"the local blank {home_display(path)}"
        if not path.is_file():
            raise FileNotFoundError(f"no file at {home_display(path)} — save the blank from {url} in a browser, then "
                                    f"pass the saved file as local_blank")
        data = path.read_bytes()
        # Phase K JK14 (2026-10-24), a decision: the header may sit anywhere in the first 1024 bytes, not only at
        # byte 0 (the JK14 brief said "must start with %PDF"). ADR-0002 rule 5 says a local blank "must carry %PDF
        # in its first 1024 bytes, as seed_blank checks" — the PDF format's own tolerance, which pypdf and pdfium
        # both honour (test_a_local_blank_header_may_follow_a_small_prefix), so a browser-saved file with a few
        # leading bytes still opens. The page checks below then run on it as on a download.
        if b"%PDF" not in data[:1024]:
            raise UnmappedBlankRefused(
                "not_pdf", f"{what} is not a PDF — save the form itself from {url}, not the web page around it",
            )
        origin, directory = "local_blank", _local_blank_dir(workspace_root, tax_year)
    else:
        _check_unmapped_url(url, allow_pinned_only=False)
        what = url
        data = _unmapped_download(url, timeout)
        if b"%PDF" not in data[:1024]:
            raise UnmappedBlankRefused(
                "not_pdf",
                f"the content downloaded from {url} is not a PDF (starts with {data[:40]!r}) — the URL serves a web "
                f"page; open it in a browser, find the form's PDF link, and pass that",
            )
        origin, directory = "download", unmapped_cache_dir(cache_dir)
    page_count, kind, first_page = inspect_unmapped_blank(
        data, tax_year=tax_year, expected_title=expected_title, what=what,
    )
    digest = hashlib.sha256(data).hexdigest()
    fetched_at = _utc_now()
    stored = _store(directory, data, digest, {
        "source_url": url, "sha256": digest, "fetched_at": fetched_at, "origin": origin, "tax_year": tax_year,
        "expected_title": expected_title, "page_count": page_count, "kind": kind, "first_page": asdict(first_page),
    })
    return UnmappedBlank(
        path=stored, sha256=digest, fetched_at=fetched_at, source_url=url, origin=origin, tax_year=tax_year,
        page_count=page_count, kind=kind, first_page=first_page,
    )


def load_unmapped_blank(
    sha256: str,
    *,
    tax_year: int,
    source_url: str | None = None,
    expected_title: str | None = None,
    cache_dir: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> UnmappedBlank:
    """A blank the pack-less fetch stored earlier, by its sha256 — re-checked, never trusted (Phase K JK14).

    Looks in the cache's ``unmapped/`` namespace, then under the year's workspace (a local blank). The file must
    still hash to ``sha256``, a ``source_url`` must match one of its records, and the page checks run again for
    ``tax_year``: a blank stored for one year is refused for another.
    """
    tax_year = _check_tax_year(tax_year)
    digest = _validate_sha256(sha256)
    for directory in (unmapped_cache_dir(cache_dir), _local_blank_dir(workspace_root, tax_year)):
        path = directory / f"{digest}.pdf"
        if path.is_file():
            break
    else:
        raise UnmappedBlankRefused(
            "not_stored",
            f"no stored blank has sha256 {digest} — fetch it again with fetch_unmapped_blank (or pass the saved file "
            f"as local_blank)",
        )
    what = f"the stored blank {digest[:16]}"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise UnmappedBlankRefused(
            "stored_copy_changed",
            f"{what} no longer hashes to {digest} (the file was changed on disk) — fetch it again with "
            f"fetch_unmapped_blank",
        )
    try:
        fetches = json.loads((directory / f"{digest}.json").read_text()).get("fetches") or []
    except (OSError, ValueError):
        fetches = []
    if source_url is not None:
        fetches = [f for f in fetches if f.get("source_url") == source_url]
    if not fetches:
        raise UnmappedBlankRefused(
            "record_mismatch",
            f"{what} has no record of a fetch" + (f" from {source_url}" if source_url else "")
            + " — fetch it again with fetch_unmapped_blank from the form's official URL",
        )
    page_count, kind, first_page = inspect_unmapped_blank(
        data, tax_year=tax_year, expected_title=expected_title, what=what,
    )
    last = fetches[-1]
    return UnmappedBlank(
        path=path, sha256=digest, fetched_at=str(last.get("fetched_at", "")), source_url=str(last.get("source_url")),
        origin=str(last.get("origin", "download")), tax_year=tax_year, page_count=page_count, kind=kind,
        first_page=first_page,
    )
