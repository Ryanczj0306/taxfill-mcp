"""fetch_blank tests (dev plan sections 5, 7, 11).

Everything here runs OFFLINE via file:// URLs or a monkeypatched urlopen,
except the single @pytest.mark.network test at the bottom, which performs
one real download from irs.gov and skips gracefully when unreachable.
Blank PDFs are never committed: fixtures are synthetic bytes in tmp_path.
"""

from __future__ import annotations

import hashlib
import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from taxfill_core.fetch import (
    CACHE_DIR_ENV,
    FetchError,
    OfflineFetchError,
    compute_sha256,
    default_cache_dir,
    fetch_blank,
)

PDF_BYTES = b"%PDF-1.7\n% synthetic taxfill fixture, not a real form\n%%EOF\n"
PDF_BYTES_V2 = b"%PDF-1.7\n% synthetic taxfill fixture REVISION TWO\n%%EOF\n"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    src = tmp_path / "source" / "f0000.pdf"
    src.parent.mkdir(parents=True)
    src.write_bytes(PDF_BYTES)
    return src


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "cache"


# --- download, cache, atomicity ------------------------------------------------


def test_fetch_downloads_to_cache_and_returns_path(source: Path, cache: Path):
    path = fetch_blank(source.as_uri(), cache_dir=cache)
    assert path.parent == cache
    assert path.read_bytes() == PDF_BYTES
    assert path.name.endswith("_f0000.pdf")  # deterministic per-URL name


def test_fetch_is_deterministic_per_url(source: Path, cache: Path):
    first = fetch_blank(source.as_uri(), cache_dir=cache)
    second = fetch_blank(source.as_uri(), cache_dir=cache)
    assert first == second


def test_cache_hit_skips_the_network_entirely(source: Path, cache: Path, monkeypatch):
    cached = fetch_blank(source.as_uri(), cache_dir=cache)
    url = source.as_uri()
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network touched on cache hit")),
    )
    assert fetch_blank(url, cache_dir=cache) == cached
    # And with the matching digest pinned, still no network needed (the
    # harness relies on this to run from a pre-populated cache offline).
    assert fetch_blank(url, sha256=compute_sha256(cached), cache_dir=cache) == cached


def test_force_redownloads(source: Path, cache: Path):
    path = fetch_blank(source.as_uri(), cache_dir=cache)
    source.write_bytes(PDF_BYTES_V2)
    assert fetch_blank(source.as_uri(), cache_dir=cache).read_bytes() == PDF_BYTES  # cache hit
    assert fetch_blank(source.as_uri(), cache_dir=cache, force=True) == path
    assert path.read_bytes() == PDF_BYTES_V2


def test_stale_cache_entry_is_redownloaded_when_digest_pinned(source: Path, cache: Path):
    path = fetch_blank(source.as_uri(), cache_dir=cache)
    path.write_bytes(PDF_BYTES_V2)  # simulate a stale/corrupt cache entry
    refreshed = fetch_blank(
        source.as_uri(), sha256=hashlib.sha256(PDF_BYTES).hexdigest(), cache_dir=cache
    )
    assert refreshed == path
    assert refreshed.read_bytes() == PDF_BYTES


def test_no_tmp_files_left_behind(source: Path, cache: Path):
    fetch_blank(source.as_uri(), cache_dir=cache)
    leftovers = [p for p in cache.iterdir() if ".tmp-" in p.name]
    assert leftovers == []


# --- sha256 verification ---------------------------------------------------------


def test_sha256_match_passes(source: Path, cache: Path):
    digest = hashlib.sha256(PDF_BYTES).hexdigest()
    path = fetch_blank(source.as_uri(), sha256=digest, cache_dir=cache)
    assert compute_sha256(path) == digest


def test_sha256_accepts_uppercase_digest(source: Path, cache: Path):
    digest = hashlib.sha256(PDF_BYTES).hexdigest().upper()
    assert fetch_blank(source.as_uri(), sha256=digest, cache_dir=cache).is_file()


def test_sha256_mismatch_quarantines_and_explains_freshness(source: Path, cache: Path):
    wrong = "0" * 64
    with pytest.raises(FetchError) as exc:
        fetch_blank(source.as_uri(), sha256=wrong, cache_dir=cache)
    message = str(exc.value)
    assert wrong in message  # expected digest
    assert hashlib.sha256(PDF_BYTES).hexdigest() in message  # actual digest
    assert "revision" in message  # freshness protocol
    assert "page 1" in message  # render-and-read instruction
    # The bad download never lands under the verified cache name…
    verified = [p for p in cache.iterdir() if p.suffix == ".pdf" and ".unverified" not in p.name]
    assert verified == []
    # …but IS quarantined so the author can render page 1 and read the year.
    quarantined = [p for p in cache.iterdir() if p.name.endswith(".unverified")]
    assert len(quarantined) == 1 and quarantined[0].read_bytes() == PDF_BYTES


def test_placeholder_sha256_is_refused_prescriptively(source: Path, cache: Path):
    with pytest.raises(ValueError) as exc:
        fetch_blank(source.as_uri(), sha256="...", cache_dir=cache)
    message = str(exc.value)
    assert "placeholder" in message
    assert "compute_sha256" in message
    assert not cache.exists()  # refused before any download


def test_malformed_sha256_is_refused(source: Path, cache: Path):
    with pytest.raises(ValueError, match=r"not a 64-character hex"):
        fetch_blank(source.as_uri(), sha256="abc123", cache_dir=cache)


def test_compute_sha256_matches_hashlib(tmp_path: Path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"taxfill" * 100_000)  # multi-chunk read path
    assert compute_sha256(blob) == hashlib.sha256(b"taxfill" * 100_000).hexdigest()


# --- prescriptive failure modes ---------------------------------------------------


def test_unsupported_scheme_is_rejected(cache: Path):
    with pytest.raises(ValueError, match=r"unsupported URL scheme 'ftp'"):
        fetch_blank("ftp://example.gov/f0000.pdf", cache_dir=cache)


def test_non_pdf_content_is_rejected(tmp_path: Path, cache: Path):
    page = tmp_path / "f0000.pdf"
    page.write_bytes(b"<html><body>404 not found</body></html>")
    with pytest.raises(FetchError, match=r"not a PDF.*source_url"):
        fetch_blank(page.as_uri(), cache_dir=cache)
    assert not cache.exists()  # nothing cached


def test_offline_error_is_prescriptive(cache: Path, monkeypatch):
    def offline(*args, **kwargs):
        raise urllib.error.URLError(OSError("Network is unreachable"))

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(OfflineFetchError) as exc:
        fetch_blank("https://www.irs.gov/pub/irs-pdf/f8843.pdf", cache_dir=cache)
    message = str(exc.value)
    assert "unreachable" in message
    assert "pre-populate" in message  # the offline escape hatch


def test_http_404_points_at_official_url_patterns(cache: Path, monkeypatch):
    def not_found(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://www.irs.gov/pub/irs-prior/f8843--1999.pdf", 404, "Not Found", None, io.BytesIO()
        )

    monkeypatch.setattr(urllib.request, "urlopen", not_found)
    with pytest.raises(FetchError) as exc:
        fetch_blank("https://www.irs.gov/pub/irs-prior/f8843--1999.pdf", cache_dir=cache)
    message = str(exc.value)
    assert "404" in message
    assert "irs-prior/<file>--<year>.pdf" in message
    assert "source_url" in message
    assert not isinstance(exc.value, OfflineFetchError)  # 404 is NOT an offline condition


def test_http_403_suggests_retry(cache: Path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://www.irs.gov/pub/irs-pdf/f8843.pdf", 403, "Forbidden", None, io.BytesIO()
        )

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    with pytest.raises(FetchError, match=r"403.*retry"):
        fetch_blank("https://www.irs.gov/pub/irs-pdf/f8843.pdf", cache_dir=cache)


def test_cached_copy_survives_offline(source: Path, cache: Path, monkeypatch):
    digest = hashlib.sha256(PDF_BYTES).hexdigest()
    cached = fetch_blank(source.as_uri(), sha256=digest, cache_dir=cache)
    url = source.as_uri()

    def offline(*args, **kwargs):
        raise urllib.error.URLError(OSError("Network is unreachable"))

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    assert fetch_blank(url, sha256=digest, cache_dir=cache) == cached


# --- default cache directory ------------------------------------------------------


def test_default_cache_dir_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "elsewhere"))
    assert default_cache_dir() == tmp_path / "elsewhere"


def test_default_cache_dir_is_repo_dot_cache_blanks(monkeypatch):
    monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
    repo_root = Path(__file__).resolve().parents[3]
    assert default_cache_dir() == repo_root / ".cache" / "blanks"


# --- the one real-network test ------------------------------------------------------


@pytest.mark.network
def test_fetch_blank_downloads_a_real_irs_form(tmp_path: Path):
    """One real download from the official URL pattern (skips offline)."""
    url = "https://www.irs.gov/pub/irs-pdf/f8843.pdf"
    try:
        path = fetch_blank(url, cache_dir=tmp_path, force=True)
    except OfflineFetchError as exc:
        pytest.skip(f"network unreachable: {exc}")
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 20_000  # a real multi-page IRS form, not an error stub
    assert compute_sha256(path) == hashlib.sha256(data).hexdigest()
