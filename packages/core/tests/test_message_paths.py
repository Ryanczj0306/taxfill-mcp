"""Phase K JK27 (privacy): a refusal never echoes the install path of the data directory.

Error messages land in the agent's transcript. Before JK27 every "looked for <path>" message named the absolute
path of the data tree, which in an installed copy sits under the user's home folder. The loaders now show a path
relative to the data tree (``formpacks/federal/2025/<form>/pack.yaml``), or relative to an explicit ``base_dir``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from taxfill_core.datadir import data_root, display_path, formpacks_dir
from taxfill_core.discovery import get_form_map, load_form_pack
from taxfill_core.handfill import load_hand_fill_pack_for
from taxfill_core.knowledge import load_knowledge, load_state_knowledge, load_treaty

ROOTS = (str(data_root()), str(data_root().resolve()), str(Path.home()))


def _message(fn, *args, **kwargs) -> str:
    with pytest.raises((FileNotFoundError, ValueError)) as excinfo:
        fn(*args, **kwargs)
    return str(excinfo.value)


@pytest.mark.parametrize(("fn", "args", "shown"), [
    (load_form_pack, ("nope", 2025), "formpacks/federal/2025/nope/pack.yaml"),
    (get_form_map, ("nope", 2025), "formpacks/federal/2025/nope/pack.yaml"),
    (load_hand_fill_pack_for, ("nope", 2025, "states/ct"), "formpacks/states/ct/2025/nope/handfill.yaml"),
    (load_knowledge, ("federal", 1990), "knowledge/federal/1990.yaml"),
    (load_state_knowledge, ("ca", 1990), "knowledge/states/ca/1990.yaml"),
    (load_treaty, ("atlantis",), "knowledge/treaties/atlantis.yaml"),
])
def test_a_missing_pack_message_names_the_data_relative_path_only(fn, args, shown):
    message = _message(fn, *args)
    assert shown in message, message
    assert not any(root in message for root in ROOTS), message


def test_an_explicit_base_dir_is_shown_under_its_own_name(tmp_path):
    base = tmp_path / "custom_packs"
    base.mkdir()
    message = _message(load_form_pack, "nope", 2025, "federal", base_dir=base)
    assert "custom_packs/federal/2025/nope/pack.yaml" in message
    assert str(tmp_path) not in message


def test_display_path_outside_every_root_keeps_the_file_name_only(tmp_path):
    assert display_path(tmp_path / "x" / "pack.yaml") == "pack.yaml"
    assert display_path(formpacks_dir() / "federal" / "2025") == "formpacks/federal/2025"


def test_the_mcp_refusal_an_agent_sees_names_no_local_root():
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    from taxfill_mcp.server import mcp

    async def go():
        async with connect(mcp._mcp_server) as client:
            return await client.call_tool("get_form_map", {"form": "nope", "year": 2025, "jurisdiction": "federal"})
    result = asyncio.run(go())
    text = " ".join(getattr(c, "text", "") for c in result.content)
    assert result.isError and "formpacks/federal/2025/nope/pack.yaml" in text, text
    assert not any(root in text for root in ROOTS), text


# ── the refusals the JK27 final review found still naming a home-folder path ──────────────────────────────────


def test_list_forms_without_a_formpacks_tree_names_the_setting_not_the_path(tmp_path, monkeypatch):
    from taxfill_core.discovery import list_forms

    monkeypatch.setenv("TAXFILL_DATA_DIR", str(tmp_path))
    message = _message(list_forms, "federal", 2025)
    assert "formpacks directory not found: formpacks" in message and "TAXFILL_DATA_DIR" in message
    assert str(tmp_path) not in message and str(Path.home()) not in message


def test_get_sources_without_a_registry_names_the_setting_not_the_path(tmp_path, monkeypatch):
    from taxfill_core.sources import get_sources

    monkeypatch.setenv("TAXFILL_DATA_DIR", str(tmp_path))
    message = _message(get_sources, "credits", 2025)
    assert "knowledge/sources.yaml" in message and "TAXFILL_DATA_DIR" in message
    assert str(tmp_path) not in message and str(Path.home()) not in message


def test_a_home_path_is_shown_from_the_tilde():
    from taxfill_core.datadir import home_display

    assert home_display(Path.home() / "taxfill-workspace" / ".cache" / "blanks") == str(
        Path("~") / "taxfill-workspace" / ".cache" / "blanks")
    assert home_display("/opt/elsewhere/file.pdf") == "/opt/elsewhere/file.pdf"


def test_the_offline_fetch_hint_shows_the_cache_from_the_tilde(tmp_path, monkeypatch):
    import urllib.error

    from taxfill_core import fetch

    def unreachable(*args, **kwargs):
        raise urllib.error.URLError("network unreachable")

    monkeypatch.setattr(fetch.urllib.request, "urlopen", unreachable)
    monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
    monkeypatch.delenv("TAXFILL_BLANKS_CACHE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(fetch.OfflineFetchError) as excinfo:
        fetch.fetch_blank("https://www.irs.gov/pub/irs-pdf/f0000.pdf", cache_dir=tmp_path / "c")
    message = str(excinfo.value)
    assert "default cache:" in message and str(Path.home()) not in message.split("default cache:", 1)[1]
