"""The TY2025 state packs carry no never-read blocks (Phase K JK22, 2026-10-24).

JK22 dropped from every knowledge/states/<st>/2025.yaml what no tool reads: the ``residency``, ``filing_requirement``
and ``starts_from`` blocks, each credit's ``amount`` and ``income_limit_2025``, and the header comment diary (its
provenance is in git history; a one-line header points there). The proof was the JK21 golden diff
(scripts/golden_snapshots.py --check): every snapshot stayed byte-identical with each kind dropped, get_sources too,
because the citations of the dropped blocks live on in the pack's ``sources`` table (test_state_sources_table.py,
``JK22_DROPPED``).

What stays is read: a credit's ``name`` and ``eligibility`` (state_scope's benefits lines), ``credits_verification``
(state_scope's caveat), and every other block. The TY2023 and TY2024 packs are frozen and keep their blocks.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
STATES = REPO_ROOT / "knowledge" / "states"
YEAR = 2025
PACKS = sorted(STATES.glob(f"*/{YEAR}.yaml"))
DROPPED_BLOCKS = ("residency", "filing_requirement", "starts_from")
DROPPED_CREDIT_FIELDS = ("amount", f"income_limit_{YEAR}")
HEADER = re.compile(
    r"# Provenance: see git history \(git show 7a90a06:knowledge/states/(?P<st>[a-z]{2})/2025\.yaml\); "
    r"sources: the `sources` table"
)


def test_every_ty2025_pack_is_covered():
    assert len(PACKS) >= 42


@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.parent.name)
def test_no_never_read_block_comes_back(path: Path):
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    back = [key for key in DROPPED_BLOCKS if key in raw]
    assert not back, (
        f"{path.parent.name} {YEAR}: {back} — no tool reads these blocks (Phase K JK22 dropped them); put a citation "
        f"in the `sources` table and the rule where a tool reads it (forms, tax.notes, credits eligibility) instead"
    )
    fields = [f"{c.get('name')}: {k}" for c in raw.get("credits") or [] for k in DROPPED_CREDIT_FIELDS if k in c]
    assert not fields, f"{path.parent.name} {YEAR}: credit fields no tool reads (Phase K JK22 dropped them): {fields}"


@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.parent.name)
def test_the_header_is_one_provenance_line(path: Path):
    lines = path.read_text(encoding="utf-8").split("\n")
    match = HEADER.fullmatch(lines[0])
    assert match and match["st"] == path.parent.name, (
        f"{path.parent.name} {YEAR}: line 1 must be the one-line provenance header, got {lines[0][:100]!r}"
    )
    assert lines[1].startswith("jurisdiction:"), (
        f"{path.parent.name} {YEAR}: a header comment diary came back above `jurisdiction:` — provenance goes in the "
        f"commit message, citations in the `sources` table"
    )


def test_the_credit_lines_state_scope_reads_survive():
    # Credit eligibility prose is read (statescope.py, the benefits lines) and waits for JK26: every TY2025 credit
    # keeps its name, its eligibility and its citation.
    missing = [
        f"{path.parent.name}: {c.get('name')!r} lacks {key}"
        for path in PACKS
        for c in yaml.safe_load(path.read_text(encoding="utf-8")).get("credits") or []
        for key in ("name", "eligibility", "citation")
        if not c.get(key)
    ]
    assert not missing, missing
