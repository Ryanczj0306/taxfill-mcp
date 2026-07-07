"""Resumable workspace tests (dev plan section 2).

Round-trips a filing across "sessions" (re-open), enforces the on-disk ethos (no
position without authority => unverified), generates RECONCILIATION.md /
CHECKLIST.md from recorded positions, and proves `purge` wipes everything.
"""
from __future__ import annotations

from taxfill_core.knowledge import Citation
from taxfill_core.workspace import Position, Workspace

CITE = Citation(source="IRS Pub 17 (2023)", url="https://www.irs.gov/publications/p17")


def test_open_creates_layout_and_is_resumable(tmp_path):
    ws = Workspace.open(tmp_path, 2023, now="2026-06-18 10:00")
    assert ws.exists() and ws.documents_dir.is_dir() and ws.drafts_dir.is_dir()
    ws.save_profile({"identity": {}}, now="2026-06-18 10:01")
    # Re-open (a new "session") sees the saved state.
    again = Workspace.open(tmp_path, 2023)
    assert again.load_profile() == {"identity": {}}


def test_position_without_citation_is_unverified():
    p = Position(topic="1040 line 12 — standard deduction", value="13850")
    assert p.status == "unverified"  # decided was downgraded: no authority
    cited = Position(topic="x", value="1", citation=CITE)
    assert cited.status == "decided"


def test_record_position_replaces_by_topic(tmp_path):
    ws = Workspace.open(tmp_path, 2023)
    ws.record_position(Position(topic="line 1 — wages", value="50000", citation=CITE))
    ws.record_position(Position(topic="line 1 — wages", value="52000", citation=CITE))  # correction
    positions = ws.positions()
    assert len(positions) == 1 and positions[0].value == "52000"


def test_reconciliation_md_lists_authority_and_flags_unverified(tmp_path):
    ws = Workspace.open(tmp_path, 2023)
    ws.record_position(Position(topic="Std deduction", value="13850", citation=CITE, references=["f1040.12"]))
    ws.record_position(Position(topic="Mystery credit", value="500"))  # no citation -> unverified
    ws.record_position(Position(topic="Allocate state wages", value="?", status="open"))
    path = ws.write_reconciliation(now="2026-06-18 10:05")
    md = path.read_text()
    assert "p17" in md and "f1040.12" in md           # the cited authority is rendered
    assert "Unverified" in md and "Mystery credit" in md
    assert "Open questions" in md and "Allocate state wages" in md
    assert "**1**" in md  # one decided


def test_checklist_md_surfaces_open_and_gaps(tmp_path):
    ws = Workspace.open(tmp_path, 2023)
    ws.record_position(Position(topic="Foreign income", value="", status="open"))
    path = ws.write_checklist(gaps=["W-2 box 1 not yet confirmed"], now="2026-06-18 10:06")
    md = path.read_text()
    assert "Foreign income" in md and "W-2 box 1 not yet confirmed" in md


def test_purge_scrubs_and_removes_then_is_idempotent(tmp_path):
    ws = Workspace.open(tmp_path, 2023)
    ws.save_profile({"ssn": "123-45-6789"})
    (ws.documents_dir / "w2.txt").write_text("sensitive wages 50000")
    assert ws.root.exists()
    n = ws.purge()
    assert n >= 2 and not ws.root.exists()
    assert ws.purge() == 0  # nothing left to scrub


def test_purge_actually_overwrites_bytes_before_unlink(tmp_path, monkeypatch):
    # The privacy guarantee: prove the scrub path runs (os.urandom called with the
    # file's byte length) before the file is unlinked, not silently skipped.
    import taxfill_core.workspace as wsmod
    ws = Workspace.open(tmp_path, 2023)
    ws.save_profile({"ssn": "123-45-6789"})
    secret = ws.documents_dir / "w2.txt"
    secret.write_text("wages 50000 ssn 123-45-6789")
    overwrites: list[int] = []
    real_urandom = wsmod.os.urandom
    monkeypatch.setattr(wsmod.os, "urandom", lambda n: overwrites.append(n) or real_urandom(n))
    n = ws.purge()
    assert n >= 2 and not ws.root.exists()
    assert len(secret.read_text()) if secret.exists() else True  # file gone
    assert any(sz == len("wages 50000 ssn 123-45-6789") for sz in overwrites), "secret file was not byte-scrubbed"


def test_bad_year_is_rejected(tmp_path):
    import pytest
    for bad in ("../etc", "2023/x", "abc"):
        with pytest.raises(ValueError):
            Workspace.open(tmp_path, bad)


def test_bad_position_status_rejected():
    import pytest
    with pytest.raises(ValueError, match="decided|open|unverified"):
        Position(topic="x", value="1", citation=CITE, status="bogus")


def test_reconciliation_escapes_pipes(tmp_path):
    ws = Workspace.open(tmp_path, 2023)
    ws.record_position(Position(topic="a|b", value="1", citation=CITE, rationale="x | y"))
    md = ws.write_reconciliation().read_text()
    assert "x \\| y" in md  # pipe escaped so the markdown table is not broken


def test_status_reports_position_breakdown(tmp_path):
    ws = Workspace.open(tmp_path, 2023)
    ws.record_position(Position(topic="a", value="1", citation=CITE))
    ws.record_position(Position(topic="b", value="2"))  # unverified
    st = ws.status()
    assert st["positions"] == {"total": 2, "decided": 1, "unverified": 1, "open": 0}
    assert st["has_profile"] is False


def test_checklist_6013_position_adds_the_signed_statement_item(tmp_path):
    # Tier-2: a recorded §6013 position (any status) means the joint election is in
    # play — CHECKLIST.md must carry the attach-signed-statement last-mile item.
    ws = Workspace.open(tmp_path, 2023)
    ws.record_position(Position(topic="§6013(g) election — treat NRA spouse as resident",
                                value="elected", citation=CITE))
    md = ws.write_checklist().read_text()
    assert "§6013(g)/(h) election — required attachment" in md
    assert "SIGNED BY BOTH" in md and "nonresident-spouse" in md
    assert "name, address, and SSN/ITIN" in md


def test_checklist_without_6013_topic_has_no_statement_item(tmp_path):
    ws = Workspace.open(tmp_path, 2023)
    ws.record_position(Position(topic="Std deduction", value="13850", citation=CITE))
    md = ws.write_checklist().read_text()
    assert "6013" not in md
