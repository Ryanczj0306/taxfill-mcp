"""`taxfill` CLI tests — status / reconcile / purge over a temp workspace."""
from __future__ import annotations

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
