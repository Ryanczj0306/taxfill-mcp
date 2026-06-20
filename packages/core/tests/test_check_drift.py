"""Offline tests for scripts/check_drift.py — the nightly freshness job's logic."""
from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

import pytest
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
