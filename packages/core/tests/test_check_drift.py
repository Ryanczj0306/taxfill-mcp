"""Offline tests for scripts/check_drift.py — the nightly freshness job's logic."""
from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("check_drift", REPO / "scripts" / "check_drift.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cd = _load()


def test_collect_source_urls_recurses():
    node = {"a": {"url": "u1"}, "b": [{"url": "u2"}, {"x": {"url": "u3"}}], "url": "u4"}
    out: list[str] = []
    cd._collect_source_urls(node, out)
    assert set(out) == {"u1", "u2", "u3", "u4"}


class _Resp:
    def __init__(self, code):
        self._code = code
    def getcode(self):
        return self._code
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_source_urls_all_reachable_is_no_drift(monkeypatch):
    monkeypatch.setattr(cd.urllib.request, "urlopen", lambda *a, **k: _Resp(200))
    assert cd.check_source_urls() == []


def test_source_url_404_is_drift_but_403_is_only_a_warning(monkeypatch):
    def raise_404(*a, **k):
        raise urllib.error.HTTPError("u", 404, "gone", {}, None)
    monkeypatch.setattr(cd.urllib.request, "urlopen", raise_404)
    assert cd.check_source_urls()  # non-empty: every URL drifted

    def raise_403(*a, **k):
        raise urllib.error.HTTPError("u", 403, "blocked", {}, None)
    monkeypatch.setattr(cd.urllib.request, "urlopen", raise_403)
    assert cd.check_source_urls() == []  # 403 = blocked bot, not drift


def test_revised_blank_is_drift(monkeypatch):
    # Force every downloaded blank's digest to differ from the recorded one.
    monkeypatch.setattr(cd, "_download", lambda url, timeout: b"x")
    monkeypatch.setattr(cd, "compute_sha256", lambda p: "0" * 64)
    drift = cd.check_form_blanks()
    assert drift and all("REVISED" in d or "revised" in d for d in drift)


def test_unreachable_blank_is_drift(monkeypatch):
    def boom(url, timeout):
        raise OSError("connection refused")
    monkeypatch.setattr(cd, "_download", boom)
    drift = cd.check_form_blanks()
    assert drift and all("unreachable" in d.lower() for d in drift)


def test_collect_mailing_urls_scopes_to_mailing_block():
    # Only URLs nested under a mailing_addresses key are collected; other cited
    # facts (deadlines, etc.) carry their own citation.url and are out of scope.
    node = {
        "mailing_addresses": {"citation": {"url": "M1"}, "verify": {"url": "M2"}},
        "deadlines": {"citation": {"url": "D1"}},
        "nested": [{"mailing_addresses": {"citation": {"url": "M3"}}}],
    }
    out: list[str] = []
    cd._collect_mailing_urls(node, out)
    assert set(out) == {"M1", "M2", "M3"}  # D1 excluded


def test_probe_urls_404_is_drift_but_403_is_only_a_warning(monkeypatch):
    url = "https://example.gov/where-to-file"
    monkeypatch.setattr(cd.urllib.request, "urlopen", lambda *a, **k: _Resp(200))
    assert cd._probe_urls([url], "x") == []

    def raise_404(*a, **k):
        raise urllib.error.HTTPError(url, 404, "gone", {}, None)
    monkeypatch.setattr(cd.urllib.request, "urlopen", raise_404)
    assert cd._probe_urls([url], "x")  # non-empty: drifted

    def raise_403(*a, **k):
        raise urllib.error.HTTPError(url, 403, "blocked", {}, None)
    monkeypatch.setattr(cd.urllib.request, "urlopen", raise_403)
    assert cd._probe_urls([url], "x") == []  # 403 = blocked bot, not drift


def test_js5_a_cookie_token_redirect_loop_is_retried_with_a_cookie_jar(monkeypatch, capsys):
    # PA myPATH / AR ATAP answer a cookieless first visit with "302 ./GetWlbToken" -> back to the portal, so plain
    # urllib gives up with HTTP 302 (the 2026-09-28 freshness red). With a cookie jar the handshake completes.
    url = "https://portal.example.gov"

    def loop_302(*a, **k):
        raise urllib.error.HTTPError(url, 302, "redirect loop", {}, None)
    monkeypatch.setattr(cd.urllib.request, "urlopen", loop_302)
    monkeypatch.setattr(cd, "_open_with_cookies", lambda req: _Resp(200))
    assert cd._probe_urls([url], "x") == []
    assert "after a cookie handshake" in capsys.readouterr().out

    # Still looping with cookies -> a real redirect failure -> drift, as before.
    monkeypatch.setattr(cd, "_open_with_cookies", loop_302)
    assert cd._probe_urls([url], "x")

    # A non-redirect error never takes the cookie path.
    def raise_404(*a, **k):
        raise urllib.error.HTTPError(url, 404, "gone", {}, None)

    def must_not_retry(req):
        raise AssertionError("a 404 is not retried")
    monkeypatch.setattr(cd.urllib.request, "urlopen", raise_404)
    monkeypatch.setattr(cd, "_open_with_cookies", must_not_retry)
    assert cd._probe_urls([url], "x")


def test_probe_urls_ssl_cert_error_is_a_warning_not_drift(monkeypatch):
    # State .gov sites (e.g. dor.ms.gov) often serve an incomplete cert chain;
    # urllib (stricter than browsers) raises SSLCertVerificationError. The page
    # is up — the cert just won't verify — so this is a warn, not a moved page.
    import ssl

    url = "https://dor.example.gov/individual-income-tax-faqs"

    def raise_ssl(*a, **k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED"))
    monkeypatch.setattr(cd.urllib.request, "urlopen", raise_ssl)
    assert cd._probe_urls([url], "x") == []  # SSL cert chain quirk = warn, not drift

    # A genuine connection failure (no SSL reason) is still drift.
    def raise_refused(*a, **k):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))
    monkeypatch.setattr(cd.urllib.request, "urlopen", raise_refused)
    assert cd._probe_urls([url], "x")  # non-empty: genuine unreachable = drift


def test_mailing_addresses_checked_and_reachable_is_no_drift(monkeypatch):
    # The real federal + per-state knowledge packs DO carry where-to-file URLs,
    # and when they all resolve there is no drift.
    federal = yaml.safe_load((REPO / "knowledge" / "federal" / "2023.yaml").read_text())
    found: list[str] = []
    cd._collect_mailing_urls(federal, found)
    assert any("irs.gov" in u for u in found)  # wiring: real where-to-file URL collected

    monkeypatch.setattr(cd.urllib.request, "urlopen", lambda *a, **k: _Resp(200))
    assert cd.check_mailing_addresses() == []


def test_not_drift_reason_classifies_transport_vs_move():
    # Regression: the SSL/403 tolerance must apply to the FORMPACK source_url check
    # too (it was in _probe_urls but not the pack loop — the recurring nightly red on
    # www.dor.ms.gov's incomplete cert chain). _download wraps the cause `from exc`.
    import ssl as _ssl
    import urllib.error as _ue

    from taxfill_core.fetch import FetchError, OfflineFetchError

    ssl_wrapped = OfflineFetchError("could not reach").with_traceback(None)
    ssl_wrapped.__cause__ = _ue.URLError(_ssl.SSLCertVerificationError("verify failed"))
    assert cd._not_drift_reason(ssl_wrapped) == "SSL cert"          # warn, not drift

    blocked = FetchError("refused")
    blocked.__cause__ = _ue.HTTPError("u", 403, "Forbidden", {}, None)
    assert cd._not_drift_reason(blocked) == "blocked HTTP 403"      # warn, not drift

    timed_out = TimeoutError("The read operation timed out")
    assert cd._not_drift_reason(timed_out) == "timeout"            # transient flake, not a move
    wrapped_timeout = OfflineFetchError("could not reach")
    wrapped_timeout.__cause__ = _ue.URLError(TimeoutError("timed out"))
    assert cd._not_drift_reason(wrapped_timeout) == "timeout"

    moved = FetchError("gone")
    moved.__cause__ = _ue.HTTPError("u", 404, "Not Found", {}, None)
    assert cd._not_drift_reason(moved) is None                      # genuine drift

    refused = OfflineFetchError("dns")
    refused.__cause__ = _ue.URLError(ConnectionRefusedError("refused"))
    assert cd._not_drift_reason(refused) is None                    # genuine drift


def test_a_reposted_draft_blank_is_a_reaudit_warning_not_drift(monkeypatch, tmp_path, capsys):
    # JT0a: the IRS re-posts drafts, so a draft pack's changed digest is a re-audit, not drift.
    pack_dir = tmp_path / "formpacks" / "federal" / "2026" / "ftest"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(yaml.safe_dump({
        "form": "TEST", "jurisdiction": "federal", "tax_year": 2026, "source_status": "draft",
        "draft_created": "8/19/26", "source_url": "https://www.irs.gov/pub/irs-dft/ftest--dft.pdf",
        "pdf_sha256": "a" * 64, "acroform_root": "topmostSubform[0]",
        "fields": [{"line": "name", "field": "Page1[0].f1_1[0]", "type": "text"}],
    }))
    monkeypatch.setattr(cd, "REPO", tmp_path)
    monkeypatch.setattr(cd, "_download", lambda url, timeout: b"x")
    monkeypatch.setattr(cd, "compute_sha256", lambda p: "0" * 64)
    assert cd.check_form_blanks() == []
    assert "draft re-posted: re-audit" in capsys.readouterr().out


def _refused_pack(tmp_path, monkeypatch, digest: str):
    """A pack whose official host answers 403, with a recorded Wayback mirror (JS1b)."""
    from taxfill_core.fetch import RefusedFetchError  # noqa: PLC0415
    url = "https://www.mass.gov/doc/2099-form-0-demo-return/download"
    pack_dir = tmp_path / "formpacks" / "states" / "ma" / "2099" / "form0"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(yaml.safe_dump({
        "form": "MA Form 0", "jurisdiction": "states/ma", "tax_year": 2099, "source_url": url,
        "mirror_urls": [f"https://web.archive.org/web/20990101000000id_/{url}"],
        "pdf_sha256": digest, "acroform_root": "",
        "fields": [{"line": "name", "field": "name", "type": "text"}],
    }))
    monkeypatch.setattr(cd, "REPO", tmp_path)

    def refused(u, timeout):
        try:
            raise urllib.error.HTTPError(u, 403, "Forbidden", {}, None)
        except urllib.error.HTTPError as exc:
            raise RefusedFetchError("403") from exc
    monkeypatch.setattr(cd, "_download", refused)
    return url


class _Capture:
    def __init__(self, url, data):
        self._url, self._data = url, data
    def geturl(self):
        return self._url
    def read(self):
        return self._data
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_js1b_a_refused_host_is_checked_through_its_newest_wayback_capture(monkeypatch, tmp_path, capsys):
    import hashlib  # noqa: PLC0415
    pinned, reissued = b"%PDF-1.6 pinned", b"%PDF-1.6 re-issued"
    url = _refused_pack(tmp_path, monkeypatch, hashlib.sha256(pinned).hexdigest())
    seen = []

    def wayback(request, timeout=None):
        seen.append(request.full_url)
        return _Capture(f"https://web.archive.org/web/20990920033523id_/{url}", served)
    monkeypatch.setattr(cd.urllib.request, "urlopen", wayback)
    served = pinned
    assert cd.check_form_blanks() == []
    assert "the newest Wayback capture (20990920033523) matches the pin" in capsys.readouterr().out
    assert seen and seen[0].startswith("https://web.archive.org/web/") and seen[0].endswith(f"id_/{url}")
    served = reissued
    drift = cd.check_form_blanks()
    assert len(drift) == 1 and "REVISED" in drift[0] and "20990920033523" in drift[0] and url in drift[0]


def test_js1b_an_unreadable_archive_leaves_the_refusal_a_warning(monkeypatch, tmp_path, capsys):
    _refused_pack(tmp_path, monkeypatch, "a" * 64)

    def archive_down(*a, **k):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(cd.urllib.request, "urlopen", archive_down)
    assert cd.check_form_blanks() == []
    assert "blocked HTTP 403 (not drift)" in capsys.readouterr().out


def test_js2b_the_source_probe_covers_the_state_registry(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(cd, "_probe_urls", lambda urls, label: seen.extend(urls) or [])
    cd.check_source_urls()
    states = yaml.safe_load((REPO / "knowledge" / "sources_states.yaml").read_text())
    wanted: list[str] = []
    cd._collect_source_urls(states, wanted)
    assert wanted and set(wanted) <= set(seen)
