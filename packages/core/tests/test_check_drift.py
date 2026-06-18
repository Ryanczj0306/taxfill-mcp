"""Offline tests for scripts/check_drift.py — the nightly freshness job's logic."""
from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

import pytest

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
