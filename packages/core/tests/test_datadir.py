"""datadir resolver tests — the layer that makes an installed wheel self-contained."""
from __future__ import annotations

import importlib

import taxfill_core.datadir as dd


def test_env_override_wins(tmp_path, monkeypatch):
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "formpacks").mkdir()
    monkeypatch.setenv(dd.DATA_DIR_ENV, str(tmp_path))
    assert dd.data_root() == tmp_path
    assert dd.knowledge_dir() == tmp_path / "knowledge"
    assert dd.formpacks_dir() == tmp_path / "formpacks"


def test_checkout_resolution_finds_repo_root(monkeypatch):
    # With no override, a dev checkout resolves to the repo root holding both trees.
    monkeypatch.delenv(dd.DATA_DIR_ENV, raising=False)
    root = dd.data_root()
    assert (root / "knowledge").is_dir() and (root / "formpacks").is_dir()


def test_module_reimport_is_stable(monkeypatch):
    monkeypatch.delenv(dd.DATA_DIR_ENV, raising=False)
    importlib.reload(dd)
    assert (dd.data_root() / "knowledge").is_dir()
