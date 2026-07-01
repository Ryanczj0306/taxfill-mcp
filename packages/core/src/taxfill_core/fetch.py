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
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

__all__ = [
    "FetchError",
    "OfflineFetchError",
    "compute_sha256",
    "default_cache_dir",
    "fetch_blank",
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

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_PLACEHOLDER = "..."  # pack-authoring placeholder; never verifiable
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")

_OFFICIAL_PATTERNS_HINT = (
    "official URL patterns: current-year forms https://www.irs.gov/pub/irs-pdf/<file>.pdf, "
    "prior-year revisions https://www.irs.gov/pub/irs-prior/<file>--<year>.pdf"
)


class FetchError(RuntimeError):
    """A blank-form download failed; the message says what to do next."""


class OfflineFetchError(FetchError):
    """The network is unreachable (no HTTP response at all).

    Callers that can proceed from a pre-populated cache (e.g. the form-pack
    test harness) catch this subclass to skip gracefully.
    """


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
    3. ``<cwd>/.cache/blanks`` as a last resort (site-packages installs).

    The directory is NOT created here; :func:`fetch_blank` creates it.
    """
    env = os.environ.get(CACHE_DIR_ENV)
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "formpacks").is_dir() and (parent / "pyproject.toml").is_file():
            return parent / ".cache" / "blanks"
    return Path.cwd() / ".cache" / "blanks"


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


def _download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FetchError(
                f"HTTP 404 (not found) for {url} — the file name or revision is wrong, "
                f"or the IRS moved it; {_OFFICIAL_PATTERNS_HINT}; find the exact file "
                f"name on irs.gov and fix the pack's source_url"
            ) from exc
        if exc.code in (401, 403):
            raise FetchError(
                f"HTTP {exc.code} ({exc.reason}) for {url} — the server refused the "
                f"request; retry in a minute, and confirm the URL opens in a browser "
                f"(blank forms come only from official .gov URLs)"
            ) from exc
        raise FetchError(
            f"HTTP {exc.code} ({exc.reason}) for {url} — retry; if it persists, verify "
            f"the URL in a browser and fix the pack's source_url ({_OFFICIAL_PATTERNS_HINT})"
        ) from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise OfflineFetchError(
            f"could not reach {url} ({reason}) — the network looks unreachable; connect "
            f"to the internet and retry, or pre-populate the shared cache by copying an "
            f"already-verified blank into place (fetch_blank tells you the cache path via "
            f"its return value; default cache: {default_cache_dir()})"
        ) from exc


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
        # Outbound only to official US government hosts (.gov/.mil/.us) — mirrors
        # knowledge.validate_gov_url. source_url is the ONLY field that triggers a network
        # request, so a maliciously-authored or typo'd pack (e.g. loaded via TAXFILL_DATA_DIR)
        # must not fetch — or SSRF to — an arbitrary host. This is the documented
        # "only outbound traffic is downloading blank forms from official .gov URLs" guarantee.
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if not any(host == tld or host.endswith("." + tld) for tld in ("gov", "mil", "us")):
            raise ValueError(
                f"refusing to fetch {url!r}: blank forms are downloaded only from official US "
                f"government hosts (.gov/.mil/.us), not {host!r} — a pack's source_url must be an "
                f"official government URL ({_OFFICIAL_PATTERNS_HINT})"
            )
    expected_digest = _validate_sha256(sha256) if sha256 is not None else None

    cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    final_path = _cache_path(cache_dir, url)

    if final_path.is_file() and not force:
        if expected_digest is None or compute_sha256(final_path) == expected_digest:
            return final_path
        # Stale or corrupt cache entry: fall through and re-download.

    data = _download(url, timeout)
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
                f"of this form (freshness protocol, docs/DEV_PLAN.md section 7). The "
                f"download is quarantined at {quarantine}; render its page 1, READ the "
                f"printed form year and title, and only if it is still the correct "
                f"revision update the pack's pdf_sha256 to {actual_digest}. A "
                f"wrong-revision pack is worse than no pack."
            )

    cache_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(final_path, data)
    return final_path
