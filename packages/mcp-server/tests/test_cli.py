"""`taxfill` CLI tests — status / reconcile / purge + the tools/call gateway."""
from __future__ import annotations

import base64
import io
import json

import taxfill_mcp.cli as cli
from taxfill_core.knowledge import Citation
from taxfill_core.workspace import Position, Workspace
from taxfill_mcp.cli import main

CITE = Citation(source="IRS Pub 17", url="https://www.irs.gov/publications/p17")


def test_status_reconcile_purge_roundtrip(tmp_path, capsys):
    root = str(tmp_path)
    ws = Workspace.open(root, 2023)
    ws.record_position(Position(topic="wages", value="50000", citation=CITE))

    assert main(["--root", root, "status", "2023"]) == 0
    assert "positions: 1" in capsys.readouterr().out

    assert main(["--root", root, "reconcile", "2023"]) == 0
    assert ws.reconciliation_path.exists() and ws.checklist_path.exists()
    capsys.readouterr()

    # purge with --yes wipes it; a second purge is a no-op.
    assert main(["--root", root, "purge", "2023", "--yes"]) == 0
    assert "Purged" in capsys.readouterr().out
    assert not ws.root.exists()
    assert main(["--root", root, "purge", "2023", "--yes"]) == 0


def test_status_on_missing_workspace_is_clean(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "status", "2099"]) == 0
    assert "No workspace" in capsys.readouterr().out


def test_purge_aborts_on_wrong_confirmation(tmp_path, capsys, monkeypatch):
    root = str(tmp_path)
    ws = Workspace.open(root, 2023)
    ws.save_profile({"x": 1})
    monkeypatch.setattr("builtins.input", lambda *_: "nope")
    assert main(["--root", root, "purge", "2023"]) == 1   # wrong confirmation -> abort
    assert ws.root.exists()                                # nothing deleted
    monkeypatch.setattr("builtins.input", lambda *_: "2023")
    assert main(["--root", root, "purge", "2023"]) == 0
    assert not ws.root.exists()


def test_reconcile_missing_workspace_errors(tmp_path):
    assert main(["--root", str(tmp_path), "reconcile", "2099"]) == 1


def test_introspect_missing_pdf_errors(tmp_path):
    assert main([
        "introspect", str(tmp_path / "nope.pdf"), "--form", "X",
        "--year", "2023", "--source-url", "https://www.irs.gov/x.pdf",
    ]) == 1


# ── tools / call gateway (shell access to the MCP tool surface) ────────────────

def test_tools_json_lists_the_full_surface(capsys):
    assert main(["tools", "--json"]) == 0
    tools = json.loads(capsys.readouterr().out)
    names = {t["name"] for t in tools}
    assert len(tools) == 22                                   # matches the CI-asserted count
    assert {"list_forms", "fill_form", "render_form"} <= names
    fill = next(t for t in tools if t["name"] == "fill_form")
    assert set(fill["inputSchema"]["required"]) >= {"form", "year", "values", "out_path"}


def test_tools_human_readable(capsys):
    assert main(["tools"]) == 0
    out = capsys.readouterr().out
    assert "22 tools" in out and "fill_form —" in out


def test_call_list_return_is_unwrapped(capsys):
    # list_document_kinds returns a list; FastMCP wraps it as {"result": [...]}, the CLI unwraps.
    assert main(["call", "list_document_kinds"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert isinstance(result, list)
    assert any(k["kind"] == "W-2" for k in result)


def test_call_with_positional_json_args(capsys):
    assert main(["call", "list_forms", '{"jurisdiction": "federal", "year": 2023}']) == 0
    forms = json.loads(capsys.readouterr().out)
    assert isinstance(forms, list) and len(forms) > 0


def test_call_reads_args_from_stdin(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"jurisdiction": "federal", "year": 2023}'))
    assert main(["call", "list_forms", "--stdin"]) == 0
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_call_unknown_tool_lists_available(capsys):
    assert main(["call", "no_such_tool"]) == 2
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "unknown tool" and "list_forms" in err["available"]


def test_call_invalid_json_args_exit_2(capsys):
    assert main(["call", "list_forms", "{not valid"]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "invalid JSON arguments"


def test_call_tool_error_exit_1(capsys):
    # fill_form with no args -> the tool raises a validation error -> exit 1, error on stderr.
    assert main(["call", "fill_form", "{}"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]


def test_call_image_output_written_to_disk(tmp_path, capsys, monkeypatch):
    """Image content blocks (render_form) are written to --out-dir and their paths returned."""
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE").decode()

    class _Img:
        type = "image"
        mimeType = "image/png"
        data = png

    class _Tool:
        name = "render_form"
        description = "render"
        inputSchema: dict = {}

    class _FakeMcp:
        async def list_tools(self):
            return [_Tool()]

        async def call_tool(self, name, args):
            return ([_Img()], None)

    monkeypatch.setattr(cli, "_server_mcp", lambda: _FakeMcp())
    assert main(["call", "render_form", "{}", "--out-dir", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["images"] == [str(tmp_path / "render_form_00.png")]
    assert (tmp_path / "render_form_00.png").read_bytes() == b"\x89PNG\r\n\x1a\nFAKE"
