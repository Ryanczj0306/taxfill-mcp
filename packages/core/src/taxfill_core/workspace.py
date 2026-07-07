"""Resumable on-disk workspace — dev plan section 2.

A filing spans days and tools; the workspace makes it durable and auditable
without any account or cloud. Everything lives under one directory the user owns:

    <root>/<year>/
      profile.json          the intake Profile (answers + provenance)
      positions.json        every decided position with its authority (the audit data)
      documents/            source docs the user provided (W-2s, 1099s, …)
      drafts/               filled PDFs produced for review
      RECONCILIATION.md     generated: every position and the source backing it
      CHECKLIST.md          generated: what is still open / unverified
      meta.json             tax year, created/updated timestamps

Two invariants carry the project ethos onto disk:

* **No position without authority.** :class:`Position` requires a citation; one
  recorded without a confirmed source is forced to ``status="unverified"`` and
  called out in both generated files — never silently treated as settled.
* **Purge on demand.** :meth:`Workspace.purge` overwrites every file's bytes
  before unlinking so a user can wipe a return's PII. This is best-effort: on
  copy-on-write filesystems (APFS/Btrfs/ZFS) and wear-leveled SSDs the original
  blocks may survive — see :meth:`Workspace.purge` for the honest guarantee.

Timestamps are caller-supplied (``now`` strings) so the module stays pure and the
MCP layer / CLI can pass the wall clock.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from taxfill_core.knowledge import Citation

__all__ = ["Position", "WorkspaceMeta", "Workspace"]


class Position(BaseModel):
    """One decided line/topic and the authority that backs it — a reconciliation row."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(description="What was decided, e.g. '1040 line 12 — standard deduction' or 'Treaty Art. 20(c)'.")
    value: str = Field(description="The figure or decision, as it will appear on the return.")
    citation: Citation | None = Field(default=None, description="The authoritative source. Absent => unverified.")
    rationale: str = Field(default="", description="Why this position (one or two sentences).")
    references: list[str] = Field(default_factory=list, description="Forms/lines this touches, e.g. ['f1040.12', 'sched_a'].")
    status: str = Field(default="decided", description="decided | open | unverified")

    @field_validator("status")
    @classmethod
    def _known_status(cls, v: str) -> str:
        if v not in ("decided", "open", "unverified"):
            raise ValueError(f"status must be decided|open|unverified, got {v!r}")
        return v

    def model_post_init(self, _ctx) -> None:
        # The ethos on disk: a position with no citation is never "decided".
        if self.citation is None and self.status == "decided":
            object.__setattr__(self, "status", "unverified")


class WorkspaceMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    tax_year: int
    created: str = ""
    updated: str = ""
    schema_version: int = 1


class Workspace:
    """A filing workspace for one tax year. Create/open, then save/record/generate/purge."""

    def __init__(self, base: Path, year: int):
        # Bound the year to an integer so str(year) can never carry a path separator
        # or '..' — the workspace dir name is then always a safe, local component.
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise ValueError(f"year must be an integer, got {year!r}")
        if not 1900 <= year <= 2100:
            raise ValueError(f"year out of range (1900–2100): {year}")
        self.year = year
        self.root = Path(base) / str(year)

    # ── lifecycle ──────────────────────────────────────────────────────────
    @classmethod
    def open(cls, base: str | Path, year: int, *, now: str = "") -> "Workspace":
        """Open the workspace for ``year`` under ``base``, creating the layout if new."""
        ws = cls(Path(base), year)
        first = not ws.root.exists()
        for sub in (ws.root, ws.documents_dir, ws.drafts_dir):
            sub.mkdir(parents=True, exist_ok=True)
        if first or not ws.meta_path.exists():
            ws._write_json(ws.meta_path, WorkspaceMeta(tax_year=year, created=now, updated=now).model_dump())
        return ws

    def exists(self) -> bool:
        return self.meta_path.exists()

    # ── paths ──────────────────────────────────────────────────────────────
    @property
    def meta_path(self) -> Path: return self.root / "meta.json"
    @property
    def profile_path(self) -> Path: return self.root / "profile.json"
    @property
    def positions_path(self) -> Path: return self.root / "positions.json"
    @property
    def documents_dir(self) -> Path: return self.root / "documents"
    @property
    def drafts_dir(self) -> Path: return self.root / "drafts"
    @property
    def reconciliation_path(self) -> Path: return self.root / "RECONCILIATION.md"
    @property
    def checklist_path(self) -> Path: return self.root / "CHECKLIST.md"

    # ── profile ──────────────────────────────────────────────────────────────
    def save_profile(self, profile: dict | BaseModel, *, now: str = "") -> None:
        data = profile.model_dump(mode="json") if isinstance(profile, BaseModel) else profile
        self._write_json(self.profile_path, data)
        self._touch(now)

    def load_profile(self) -> dict | None:
        if not self.profile_path.exists():
            return None
        return json.loads(self.profile_path.read_text())

    # ── positions (the audit trail) ─────────────────────────────────────────
    def positions(self) -> list[Position]:
        if not self.positions_path.exists():
            return []
        return [Position.model_validate(p) for p in json.loads(self.positions_path.read_text())]

    def record_position(self, position: Position | dict, *, now: str = "") -> Position:
        """Append (or replace by topic) a position and persist it."""
        pos = position if isinstance(position, Position) else Position.model_validate(position)
        existing = [p for p in self.positions() if p.topic != pos.topic]
        existing.append(pos)
        self._write_json(self.positions_path, [p.model_dump(mode="json") for p in existing])
        self._touch(now)
        return pos

    # ── generated artifacts ──────────────────────────────────────────────────
    def write_reconciliation(self, *, now: str = "") -> Path:
        """Generate RECONCILIATION.md from the recorded positions."""
        positions = self.positions()
        decided = [p for p in positions if p.status == "decided"]
        unverified = [p for p in positions if p.status == "unverified"]
        open_ = [p for p in positions if p.status == "open"]
        lines = [
            f"# Reconciliation — tax year {self.year}",
            "",
            "Every figure on the return and the authority that backs it. This is a **review "
            "draft** record, not tax advice. Confirm each source before signing.",
            "",
            f"_Generated{(' ' + now) if now else ''} from positions.json — do not edit by hand._",
            "",
            f"- Decided (cited): **{len(decided)}**  ·  Unverified: **{len(unverified)}**  ·  Open: **{len(open_)}**",
            "",
        ]

        def _table(title: str, rows: list[Position], note: str = "") -> None:
            lines.append(f"## {title}")
            if note:
                lines.append(note)
            if not rows:
                lines.append("\n_None._\n")
                return
            lines.append("")
            lines.append("| Topic | Value | Authority | Rationale | Refs |")
            lines.append("|---|---|---|---|---|")
            def _cell(s: str) -> str:
                return str(s).replace("|", "\\|").replace("\n", " ")

            for p in rows:
                auth = f"[{_cell(p.citation.source)}]({p.citation.url})" if p.citation else "**— none —**"
                refs = _cell(", ".join(p.references)) if p.references else ""
                lines.append(f"| {_cell(p.topic)} | {_cell(p.value)} | {auth} | {_cell(p.rationale)} | {refs} |")
            lines.append("")

        _table("Decided positions", decided)
        _table(
            "Unverified — confirm before filing", unverified,
            "These have no confirmed authority yet. Resolve each from an official source or remove it; "
            "the return is not ready while any remain.",
        )
        _table("Open questions", open_)
        self.reconciliation_path.write_text("\n".join(lines))
        self._touch(now)
        return self.reconciliation_path

    def write_checklist(self, *, gaps: list[str] | None = None, now: str = "") -> Path:
        """Generate CHECKLIST.md: open/unverified positions plus any caller-supplied gaps."""
        positions = self.positions()
        open_ = [p for p in positions if p.status in ("open", "unverified")]
        lines = [
            f"# Checklist — tax year {self.year}",
            "",
            f"_Generated{(' ' + now) if now else ''}. What still needs attention before filing._",
            "",
            "## Open / unverified positions",
        ]
        if open_:
            lines += [f"- [ ] **{p.topic}** — {p.status}: {p.value or p.rationale or 'needs an authoritative source'}" for p in open_]
        else:
            lines.append("- [x] All recorded positions are decided and cited.")
        # A recorded §6013(g)/(h) position means the joint election is in play: the
        # election is only VALID with a statement signed by both spouses attached to
        # the first joint return, so the checklist carries that last-mile item
        # whenever any position's topic mentions 6013 (whatever its status).
        if any("6013" in p.topic.lower() for p in positions):
            lines += [
                "",
                "## §6013(g)/(h) election — required attachment",
                "- [ ] Attach the ELECTION STATEMENT to the first joint return: a statement SIGNED BY BOTH "
                "SPOUSES declaring that one spouse was a nonresident alien and the other a U.S. citizen or "
                "resident on the last day of the tax year, and that both choose to be treated as U.S. "
                "residents for the entire year, with each spouse's full name, address, and SSN/ITIN "
                "(https://www.irs.gov/individuals/international-taxpayers/nonresident-spouse). A joint "
                "return with a nonresident-alien spouse is not valid without it.",
            ]
        lines += ["", "## Missing inputs"]
        if gaps:
            lines += [f"- [ ] {g}" for g in gaps]
        else:
            lines.append("- [x] No outstanding inputs recorded.")
        lines.append("")
        self.checklist_path.write_text("\n".join(lines))
        self._touch(now)
        return self.checklist_path

    # ── purge (privacy) ────────────────────────────────────────────────────
    def purge(self) -> int:
        """Best-effort secure wipe: overwrite every file's bytes, then remove the tree.

        Returns the number of files scrubbed. After this the year's directory is gone.

        Honest threat model: the in-place overwrite reliably removes the data on a
        traditional overwrite-in-place filesystem, but does NOT guarantee the
        original blocks are destroyed on copy-on-write filesystems (APFS, Btrfs,
        ZFS), SSDs with wear-leveling, or where snapshots / journaling / Time
        Machine retain prior versions. For a hard guarantee use full-disk
        encryption (so deletion is effectively crypto-erase) or vendor secure-erase.
        """
        if not self.root.exists():
            return 0
        scrubbed = 0
        for path in sorted(self.root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_file() or path.is_symlink():
                try:
                    size = path.stat().st_size if path.is_file() and not path.is_symlink() else 0
                    if size:
                        with open(path, "r+b", buffering=0) as fh:
                            fh.write(os.urandom(size))
                            fh.flush()
                            os.fsync(fh.fileno())
                except OSError:
                    pass
                path.unlink(missing_ok=True)
                scrubbed += 1
        shutil.rmtree(self.root, ignore_errors=True)
        return scrubbed

    # ── status ───────────────────────────────────────────────────────────────
    def status(self) -> dict:
        positions = self.positions()
        return {
            "year": self.year,
            "root": str(self.root),
            "exists": self.exists(),
            "has_profile": self.profile_path.exists(),
            "documents": sorted(p.name for p in self.documents_dir.glob("*")) if self.documents_dir.exists() else [],
            "drafts": sorted(p.name for p in self.drafts_dir.glob("*")) if self.drafts_dir.exists() else [],
            "positions": {
                "total": len(positions),
                "decided": sum(p.status == "decided" for p in positions),
                "unverified": sum(p.status == "unverified" for p in positions),
                "open": sum(p.status == "open" for p in positions),
            },
            "reconciliation": self.reconciliation_path.exists(),
        }

    # ── internals ──────────────────────────────────────────────────────────
    def _write_json(self, path: Path, data) -> None:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _touch(self, now: str) -> None:
        if not self.meta_path.exists():
            return
        meta = json.loads(self.meta_path.read_text())
        if now:
            meta["updated"] = now
        self._write_json(self.meta_path, meta)
