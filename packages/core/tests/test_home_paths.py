"""Phase K JK28 (privacy and paths): every path an agent or a shell user supplies may be "~/...".

Tool and CLI arguments arrive unexpanded: a JSON tool call, a quoted shell word, ``--root=~/x`` and an MCP client's
``env`` block all pass ``~`` through literally. Before JK28 ``fill_form(out_path="~/taxes/f1040.pdf")`` wrote into a
folder named ``~`` under the server's working directory, and verify_form / render_form could not find the file.

The decision (docs/USER_GUIDE.md, "Privacy, in plain words"): RESULTS keep absolute paths — fetch_blank's cache path,
fill_form's ``out_path``, the workspace paths — because an agent hands them to its own file tools, and many of those
take only absolute paths (Claude Code's Read, Edit and Write tools say so). REFUSALS that only mention a path show the
home folder as ``~`` (``datadir.home_display``). ``extract_document``'s ``path`` is provenance, never opened, so it is
stored exactly as given.

HOME points at a temp dir in every test; demo values only.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

# Imported here, at collection and under the REAL home folder, not first inside a test under the patched HOME: each
# module computes its default workspace root at import time (server.WORKSPACE_ROOT, cli.DEFAULT_ROOT), and a first
# import under a test's temporary HOME froze that root to the temp folder, so test_workspace's "the server and the
# CLI resolve the same root" check failed whenever these tests ran first in the same process (JK28 final review).
import taxfill_mcp.cli  # noqa: F401
import taxfill_mcp.server  # noqa: F401
from taxfill_core.schemas.formpack import FormPack


@pytest.fixture()
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # what expanduser reads on Windows
    monkeypatch.chdir(tmp_path)  # a literal "~" folder would land here, beside "home"
    return home


@pytest.fixture()
def pack() -> FormPack:
    return FormPack.model_validate({
        "form": "DEMO-1",
        "jurisdiction": "federal",
        "tax_year": 2023,
        "source_url": "https://www.irs.gov/pub/irs-prior/demo.pdf",
        "pdf_sha256": "...",
        "acroform_root": "",
        "fields": [
            {"line": "1", "field": "f1", "type": "money"},
            {"line": "2", "field": "f2", "type": "money"},
            {"line": "3", "field": "f3", "type": "money"},
            {"line": "name", "field": "fname", "type": "text"},
        ],
        "relations": ["3 == 1 + 2"],
    })


@pytest.fixture()
def blank(home) -> Path:
    from pdf_fixtures import make_acroform_pdf

    return make_acroform_pdf(home / "blanks" / "demo.pdf",
                             [{"name": n, "kind": "text"} for n in ("f1", "f2", "f3", "fname")])


VALUES = {"1": 1200, "2": 300, "3": 1500, "name": "Demo Filer"}


def _no_literal_tilde(tmp_path: Path) -> None:
    assert not (tmp_path / "~").exists(), "a '~' folder was created in the working directory"


# ── the helper and the three path settings ──────────────────────────────────────────────────────────────────────


def test_user_path_expands_a_leading_tilde_only(home):
    from taxfill_core.datadir import home_display, user_path

    assert user_path("~/taxes/f1040.pdf") == home / "taxes" / "f1040.pdf"
    assert user_path("/srv/taxes/f1040.pdf") == Path("/srv/taxes/f1040.pdf")
    # A relative path comes back absolute against the working directory (Phase K JK28 final review): results name
    # absolute paths, and a "~" that does not lead stays literal.
    assert user_path("drafts/f1040.pdf") == Path.cwd() / "drafts" / "f1040.pdf"
    assert user_path("a/~/b.pdf") == Path.cwd() / "a" / "~" / "b.pdf"
    assert home_display(home / "taxes" / "f1040.pdf") == str(Path("~") / "taxes" / "f1040.pdf")


def test_home_display_reads_a_tilde_path_from_a_folder_under_home(home, monkeypatch):
    # The CLI hands home_display the --root it was given, "~/taxes" unexpanded. Resolved as typed from a working
    # directory inside the home folder, that printed "~/projects/~/taxes".
    from taxfill_core.datadir import home_display

    (home / "projects").mkdir()
    monkeypatch.chdir(home / "projects")
    assert home_display("~/taxes") == str(Path("~") / "taxes")
    assert home_display(home / "taxes") == str(Path("~") / "taxes")


def test_the_three_path_settings_take_a_tilde(home, monkeypatch):
    # An MCP client's JSON `env` block is never shell-expanded.
    from taxfill_core.datadir import data_root
    from taxfill_core.fetch import default_cache_dir
    from taxfill_core.workspace import default_workspace_root

    monkeypatch.setenv("TAXFILL_WORKSPACE", "~/taxes")
    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", "~/blank-cache")
    monkeypatch.setenv("TAXFILL_DATA_DIR", "~/taxfill-data")
    assert default_workspace_root() == home / "taxes"
    assert default_cache_dir() == home / "blank-cache"
    assert data_root() == home / "taxfill-data"


# ── the core functions the tools call ───────────────────────────────────────────────────────────────────────────


def test_core_fill_verify_render_take_tilde_paths(home, pack, blank, tmp_path):
    from taxfill_core.filler import fill_form
    from taxfill_core.render import render_pdf
    from taxfill_core.verify import FilingItem, read_pdf_fields, verify_filing, verify_form

    fill_form(pack, VALUES, "~/blanks/demo.pdf", "~/drafts/demo.pdf")
    out = home / "drafts" / "demo.pdf"
    assert out.is_file()
    assert read_pdf_fields("~/drafts/demo.pdf")["f1"] == "1200"
    report = verify_form(pack, "~/drafts/demo.pdf", expected=VALUES)
    assert report.ok, [c.detail for s in (report.assertions, report.relations, report.clipping) for c in s]
    filing = verify_filing([FilingItem(form_key="demo", pack=pack, pdf_path="~/drafts/demo.pdf")])
    assert filing.ok and [c.status for c in filing.relations] == ["PASS"]
    pages = render_pdf("~/drafts/demo.pdf", "~/pages")
    assert pages and all(Path(p.path).parent == home / "pages" for p in pages)
    _no_literal_tilde(tmp_path)


def test_core_workspace_and_seed_blank_take_tilde_paths(home, tmp_path):
    from taxfill_core.fetch import cached_blank_path, seed_blank
    from taxfill_core.workspace import Workspace

    ws = Workspace.open("~/taxes", 2025)
    assert ws.root == home / "taxes" / "2025" and ws.root.is_dir()
    data = b"%PDF-1.7\n% synthetic taxfill fixture, not a real form\n%%EOF\n"
    (home / "saved.pdf").write_bytes(data)
    url, digest = "https://www.mass.gov/doc/2099-demo/download", hashlib.sha256(data).hexdigest()
    seed_blank("~/saved.pdf", url, digest, cache_dir="~/blank-cache")
    assert cached_blank_path(url, digest, cache_dir=home / "blank-cache") is not None
    _no_literal_tilde(tmp_path)


def _refusal(fn, *args) -> str:
    with pytest.raises((FileNotFoundError, ValueError)) as caught:
        fn(*args)
    return str(caught.value)


@pytest.mark.parametrize("given", ["~/missing.pdf", "HOME/missing.pdf"])
def test_a_refusal_shows_the_home_folder_as_tilde(home, pack, given):
    from taxfill_core.fetch import seed_blank
    from taxfill_core.filler import fill_form
    from taxfill_core.overlay import page_geometry
    from taxfill_core.render import render_pdf
    from taxfill_core.verify import read_pdf_fields, read_text_widgets

    path = given.replace("HOME", str(home))  # the same file, typed with "~" or as an absolute path
    shown = str(Path("~") / "missing.pdf")
    messages = {
        "read_pdf_fields": _refusal(read_pdf_fields, path),
        "read_text_widgets": _refusal(read_text_widgets, path),
        "render_pdf": _refusal(render_pdf, path, home / "pages"),
        "fill_form": _refusal(fill_form, pack, VALUES, path, home / "out.pdf"),
        "page_geometry": _refusal(page_geometry, path, 1),
        "seed_blank": _refusal(seed_blank, path, "https://www.mass.gov/x", "0" * 64),
    }
    for where, message in messages.items():
        assert shown in message, (where, message)
        assert str(home) not in message, (where, message)


@pytest.mark.parametrize("given", ["~/adir.pdf", "HOME/adir.pdf"])
def test_an_out_path_that_is_a_folder_is_refused_with_tilde_and_a_next_step(home, pack, blank, given):
    """Phase K JK28 final review (2026-10-23): a folder (or an unwritable one) as out_path raised Python's raw
    IsADirectoryError, which printed the absolute home path and no next step."""
    from taxfill_core.filler import fill_form

    (home / "adir.pdf").mkdir()
    out = given.replace("HOME", str(home))
    with pytest.raises(IsADirectoryError) as caught:
        fill_form(pack, VALUES, blank, out)
    message = str(caught.value)
    assert str(Path("~") / "adir.pdf") in message and str(home) not in message, message
    assert "pass a file path, not a folder" in message, message


def test_an_unwritable_out_folder_is_refused_with_tilde(home, pack, blank):
    from taxfill_core.filler import fill_form

    locked = home / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(PermissionError) as caught:
            fill_form(pack, VALUES, blank, "~/locked/out.pdf")
    finally:
        locked.chmod(0o700)
    message = str(caught.value)
    assert str(Path("~") / "locked" / "out.pdf") in message and str(home) not in message, message
    assert "in a folder you can write to" in message, message


def test_the_writer_fill_form_and_stamp_overlay_share_refuses_a_folder_with_tilde(home):
    from taxfill_core.datadir import write_output

    (home / "stamped.pdf").mkdir()
    with pytest.raises(IsADirectoryError) as caught:
        write_output(home / "stamped.pdf", lambda fh: fh.write(b"%PDF"))
    assert str(Path("~") / "stamped.pdf") in str(caught.value) and str(home) not in str(caught.value)


@pytest.mark.parametrize("given", ["~/notes.pdf", "HOME/notes.pdf"])
def test_a_non_pdf_refusal_finds_the_file_and_shows_tilde(home, given):
    from taxfill_core.overlay import page_geometry
    from taxfill_core.render import render_pdf

    (home / "notes.pdf").write_text("not a pdf")
    path = given.replace("HOME", str(home))
    for fn, args in ((render_pdf, (path, home / "pages")), (page_geometry, (path, 1))):
        with pytest.raises(ValueError) as caught:  # found, then refused: not FileNotFoundError
            fn(*args)
        message = str(caught.value)
        assert "could not be opened as a PDF" in message, message
        assert str(Path("~") / "notes.pdf") in message and str(home) not in message, message


# ── the MCP tools ───────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def server(monkeypatch, pack, blank):
    """The MCP tool module, with the synthetic pack and blank standing in for a real form (offline)."""
    import taxfill_mcp.server as server

    monkeypatch.setattr(server, "_load_any_pack", lambda form, year, jurisdiction="federal": pack)
    monkeypatch.setattr(server, "_fetch_pack_blank", lambda _pack: blank)
    return server


def test_mcp_fill_verify_render_take_tilde_paths_and_fill_returns_the_absolute_path(home, server, tmp_path):
    filled = server.fill_form("demo", 2023, VALUES, "~/drafts/demo.pdf")
    out = home / "drafts" / "demo.pdf"
    assert out.is_file()
    assert filled["out_path"] == str(out)  # absolute: the agent's own file tools take it as is
    assert server.verify_form("demo", 2023, "~/drafts/demo.pdf", expected=VALUES)["ok"] is True
    report = server.verify_filing([{"form": "demo", "year": 2023, "pdf_path": "~/drafts/demo.pdf"}])
    assert report["ok"] is True and report["sections"]["relations"]["checked"] == 1
    images = server.render_form("~/drafts/demo.pdf", pages=[1])
    assert len(images) == 1
    _no_literal_tilde(tmp_path)


def test_mcp_workspace_tools_and_compare_scenarios_take_a_tilde_root(home, tmp_path):
    import taxfill_mcp.server as server

    root = home / "taxes" / "2025"
    status = server.workspace_save(2025, {"filer": "demo"}, root="~/taxes")
    assert (root / "profile.json").is_file() and status["root"] == str(root)
    assert server.workspace_load(2025, root="~/taxes")["profile"] == {"filer": "demo"}
    server.workspace_record_position(2025, {  # the tool docstring's own example position
        "topic": "1040 line 12 — standard deduction", "value": "13850",
        "citation": {"source": "Rev. Proc. 2022-38, Section 3.15", "url": "https://www.irs.gov/pub/irs-drop/rp-22-38.pdf"},
    }, root="~/taxes")
    reconciled = server.workspace_reconcile(2025, root="~/taxes")
    assert reconciled["reconciliation_path"] == str(root / "RECONCILIATION.md")
    server.compare_scenarios(2025, scenarios=[{"name": "single", "filing_status": "single"},
                                              {"name": "head of household", "filing_status": "head_of_household"}],
                             income={"wages": 50_000, "federal_withholding": 5_000}, save_as="demo-set", root="~/taxes")
    assert (root / "scenarios.json").is_file()
    _no_literal_tilde(tmp_path)


def test_results_name_absolute_paths_under_a_relative_root_or_env(home, tmp_path, monkeypatch):
    """Phase K JK28 final review (2026-10-23): a relative `root`, TAXFILL_WORKSPACE, TAXFILL_BLANKS_CACHE or the
    legacy ./taxfill-workspace came back relative, and a relative path is read against the MCP server's working
    directory, not the agent's."""
    import taxfill_mcp.server as server
    from taxfill_core.fetch import default_cache_dir
    from taxfill_core.workspace import default_workspace_root

    status = server.workspace_save(2025, {"filer": "demo"}, root="rel-taxes")
    assert status["root"] == str(tmp_path / "rel-taxes" / "2025"), status["root"]
    reconciled = server.workspace_reconcile(2025, root="rel-taxes")
    assert reconciled["reconciliation_path"] == str(tmp_path / "rel-taxes" / "2025" / "RECONCILIATION.md")
    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", "rel-cache")
    assert default_cache_dir() == tmp_path / "rel-cache"
    monkeypatch.setenv("TAXFILL_WORKSPACE", "rel-ws")
    assert default_workspace_root() == tmp_path / "rel-ws"
    monkeypatch.delenv("TAXFILL_WORKSPACE")
    (tmp_path / "taxfill-workspace").mkdir()  # the legacy ./taxfill-workspace
    assert default_workspace_root() == tmp_path / "taxfill-workspace"


def test_mcp_extract_document_keeps_the_provenance_path_as_given(home):
    # extract_document never opens the file: `path` is a provenance label, so "~/W-2.pdf" stays "~/W-2.pdf"
    # (expanding it would only put the home folder into the saved profile).
    import taxfill_mcp.server as server

    out = server.extract_document("~/documents/W-2.pdf", "W-2", {"1": "50000"})
    assert {f["provenance"]["file"] for f in out["fields"]} == {"~/documents/W-2.pdf"}


@pytest.mark.parametrize("given", ["~/missing.pdf", "HOME/missing.pdf"])
def test_mcp_refusal_over_the_protocol_shows_tilde(home, server, given):
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    pdf_path = given.replace("HOME", str(home))

    async def go():
        async with connect(server.mcp._mcp_server) as client:
            return await client.call_tool("verify_form", {"form": "demo", "year": 2023, "pdf_path": pdf_path})
    result = asyncio.run(go())
    text = " ".join(getattr(c, "text", "") for c in result.content)
    assert result.isError and str(Path("~") / "missing.pdf") in text, text
    assert str(home) not in text, text


def test_every_mcp_path_argument_is_one_this_module_covers():
    # The audit, pinned: a new tool argument that takes a path must be added here (and expand "~").
    from taxfill_mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    pathlike = {
        (t.name, name)
        for t in tools
        for name in (t.inputSchema or {}).get("properties", {})
        if {"path", "root", "dir", "file"} & set(name.lower().split("_"))
    }
    assert pathlike == {
        ("fill_form", "out_path"), ("verify_form", "pdf_path"), ("render_form", "pdf_path"),
        ("extract_document", "path"), ("workspace_save", "root"), ("workspace_load", "root"),
        ("workspace_record_position", "root"), ("workspace_reconcile", "root"), ("compare_scenarios", "root"),
    }  # plus verify_filing's items[].pdf_path, inside its `items` objects; fetch_blank and hand_fill_worksheet take none


# ── the CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_cli_root_takes_a_tilde_in_both_spellings(home, capsys, tmp_path):
    from taxfill_core.workspace import Workspace
    from taxfill_mcp.cli import main

    Workspace.open(home / "taxes", 2025).save_profile({"filer": "demo"})
    assert main(["--root", "~/taxes", "status", "2025"]) == 0
    assert "profile: yes" in capsys.readouterr().out
    assert main(["--root=~/taxes", "reconcile", "2025"]) == 0
    assert (home / "taxes" / "2025" / "RECONCILIATION.md").is_file()
    capsys.readouterr()
    assert main(["--root", "~/taxes", "purge", "2025", "--yes"]) == 0
    assert not (home / "taxes" / "2025").exists()
    capsys.readouterr()
    assert main(["--root", str(home / "taxes"), "status", "2099"]) == 0
    message = capsys.readouterr().out
    assert "under '~/taxes'" in message.replace("\\", "/") and str(home) not in message
    _no_literal_tilde(tmp_path)


def test_cli_pdf_arguments_take_a_tilde(home, blank, capsys, tmp_path):
    from taxfill_mcp.cli import main

    assert main(["introspect", "~/blanks/demo.pdf", "--form", "DEMO-1", "--year", "2023",
                 "--source-url", "https://www.irs.gov/pub/irs-prior/demo.pdf", "--out", "~/skeleton"]) == 0
    assert (home / "skeleton" / "pack.skeleton.yaml").is_file()
    assert main(["locate", "~/blanks/demo.pdf", "--page", "1", "fixture", "--json"]) == 0
    capsys.readouterr()
    data = blank.read_bytes()
    url, digest = "https://www.mass.gov/doc/2099-demo/download", hashlib.sha256(data).hexdigest()
    assert main(["seed-blank", "~/blanks/demo.pdf", "--url", url, "--sha256", digest, "--cache-dir", "~/cache"]) == 0
    assert any((home / "cache").iterdir())
    capsys.readouterr()
    assert main(["call", "render_form", json.dumps({"pdf_path": "~/blanks/demo.pdf", "pages": [1]}),
                 "--out-dir", "~/pages"]) == 0
    images = json.loads(capsys.readouterr().out)["images"]
    assert images and all(Path(p).parent == home / "pages" for p in images)
    _no_literal_tilde(tmp_path)


@pytest.mark.parametrize("given", ["~/packs/pack.yaml", "HOME/packs/pack.yaml"])
@pytest.mark.parametrize("content", [None, "- not\n- a mapping\n", "form: [unclosed\n", "form: DEMO-1\n"],
                         ids=["missing", "not-a-mapping", "not-yaml", "not-a-pack"])
def test_cli_seed_blank_refuses_a_bad_pack_and_shows_tilde(home, blank, capsys, content, given):
    """A missing, unparsable or invalid --pack is refused in one line that names it as "~/...", not with a traceback
    whose FileNotFoundError would print the expanded home path."""
    from taxfill_mcp.cli import main

    if content is not None:
        (home / "packs").mkdir()
        (home / "packs" / "pack.yaml").write_text(content, encoding="utf-8")
    pack = given.replace("HOME", str(home))
    assert main(["seed-blank", "~/blanks/demo.pdf", "--pack", pack, "--cache-dir", "~/cache"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("not seeded: ") and str(Path("~") / "packs" / "pack.yaml") in err, err
    assert str(home) not in err, err
    assert not (home / "cache").exists()
    # What is wrong, and what to do next (Phase K JK28 final review, 2026-10-23).
    expected = {
        None: "no readable pack at",
        "- not\n- a mapping\n": "the file is not a YAML mapping of key: value pairs",
        "form: [unclosed\n": "YAML syntax error at line 2, column 1",
        "form: DEMO-1\n": "jurisdiction: Field required",
    }[content]
    assert expected in err, err
    if content is not None:
        assert "fix that pack.yaml, or pass --url and --sha256 instead of --pack" in err, err


def test_cli_seed_blank_os_error_shows_tilde(home, blank, capsys, monkeypatch):
    """An OS error while caching (an unwritable cache folder) names its file as "~/..." too."""
    import taxfill_core.fetch as fetch
    from taxfill_mcp.cli import main

    def unwritable(final_path, data):
        raise PermissionError(13, "Permission denied", str(final_path))

    monkeypatch.setattr(fetch, "_atomic_write", unwritable)
    data = blank.read_bytes()
    url, digest = "https://www.mass.gov/doc/2099-demo/download", hashlib.sha256(data).hexdigest()
    assert main(["seed-blank", "~/blanks/demo.pdf", "--url", url, "--sha256", digest, "--cache-dir", "~/cache"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("not seeded: Permission denied: " + str(Path("~") / "cache")), err
    assert str(home) not in err, err


@pytest.mark.parametrize("given", ["~/nope.pdf", "HOME/nope.pdf"])
@pytest.mark.parametrize("command", [
    ["introspect", "PDF", "--form", "X", "--year", "2023", "--source-url", "https://www.irs.gov/x.pdf"],
    ["locate", "PDF", "--page", "1", "5"],
])
def test_cli_missing_pdf_refusal_shows_tilde(home, capsys, command, given):
    from taxfill_mcp.cli import main

    pdf = given.replace("HOME", str(home))
    assert main([pdf if arg == "PDF" else arg for arg in command]) == 1
    err = capsys.readouterr().err
    assert "No such PDF: " + str(Path("~") / "nope.pdf") in err and str(home) not in err
