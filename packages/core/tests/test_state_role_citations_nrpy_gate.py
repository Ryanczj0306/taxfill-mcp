"""The completeness gate over every part-year / nonresident role citation (Phase K JK28 final review, 2026-10-23).

The four NR/PY modules (test_state_role_citations_nrpy_r1/_r2/_r3/_t1) pin each TY2025 state's own documents and
corrected entries from per-state tables, so a pack missing from every table was checked by none of them, and their
generic rules differed in strictness. This module reads no table: it globs every state knowledge pack of TY2025 or
later that names a part-year or nonresident form (``forms.part_year_or_nonresident``) and holds each to one rule set,
the strictest every shipped pack meets today:

* both roles carry ``forms.citations.part_year`` and ``forms.citations.nonresident``, every entry a valid .gov
  citation;
* each role has at least one citation that quotes the document with a page pinpoint;
* state_scope adds each role's list to that role's filer, adds neither list to a full-year resident, and adds no
  citation that only the other role's list carries.

The per-state modules keep their tables (EXPECTED, KEY_DOCS, STATES, ROLE_DOCUMENT) and the corrected-entry tests.
A new year's pack that names a role form without citing it fails here, whether or not anyone adds it to a table.
"""
from __future__ import annotations

import re
from datetime import date
from functools import cache
from pathlib import Path

import pytest
import yaml

from taxfill_core.knowledge import Citation, validate_gov_url
from taxfill_core.schemas.profile import Profile, Provenance, ResidencePeriod, StateFootprintYear, WorkPeriod
from taxfill_core.statescope import StateFiling, state_scope

REPO = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO / "knowledge"
US = Provenance.user_stated()
ROLES = ("part_year", "nonresident")
FIRST_YEAR = 2025  # the role citations shipped with TY2025 (Virginia since JK27, the other 41 since JK28)
OTHER = "WA"  # the other side of the move / the home state: no income tax, so it adds no citation of its own
_QUOTE = re.compile(r"['\"‘“]")
_PINPOINT = re.compile(r"\bpp?\. ?\d|\bpage \d|\bSide \d|\bline \d", re.IGNORECASE)


def _role_packs() -> list[tuple[str, int]]:
    found = []
    for path in sorted((KNOWLEDGE / "states").glob("*/*.yaml")):
        if not path.stem.isdigit() or int(path.stem) < FIRST_YEAR:
            continue
        forms = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("forms") or {}
        if forms.get("part_year_or_nonresident"):
            found.append((path.parent.name, int(path.stem)))
    return found


ROLE_PACKS = _role_packs()


@cache
def _role_citations(st: str, year: int) -> dict[str, tuple[Citation, ...]]:
    raw = yaml.safe_load((KNOWLEDGE / "states" / st / f"{year}.yaml").read_text(encoding="utf-8"))
    cites = (raw.get("forms") or {}).get("citations") or {}
    return {role: tuple(Citation.model_validate(c) for c in cites.get(role) or []) for role in ROLES}


def _filing(st: str, year: int, role: str) -> StateFiling:
    code = st.upper()
    if role == "part_year":  # lived in the state until June 30, then moved away
        lived = [ResidencePeriod(state=code, start=date(year, 1, 1), end=date(year, 6, 30), provenance=US),
                 ResidencePeriod(state=OTHER, start=date(year, 7, 1), end=date(year, 12, 31), provenance=US)]
        worked: list[WorkPeriod] = []
    elif role == "nonresident":  # lived elsewhere all year, worked in the state
        lived = [ResidencePeriod(state=OTHER, start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)]
        worked = [WorkPeriod(state=code, start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)]
    else:
        lived = [ResidencePeriod(state=code, start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)]
        worked = []
    profile = Profile(state_footprint={year: StateFootprintYear(lived=lived, worked=worked)})
    return {s.state: s for s in state_scope(profile, year, base_dir=KNOWLEDGE).states}[code]


def test_the_glob_finds_every_shipped_role_pack():
    # 41 states + DC for TY2025; the floor fails if the glob (or the forms key it reads) silently stops matching.
    assert len([p for p in ROLE_PACKS if p[1] == 2025]) >= 42, ROLE_PACKS


@pytest.mark.parametrize(("st", "year"), ROLE_PACKS, ids=lambda v: str(v))
def test_both_roles_cite_gov_documents_with_a_quoted_pinpoint(st: str, year: int):
    cites = _role_citations(st, year)
    for role in ROLES:
        assert cites[role], f"{st} {year}: forms.part_year_or_nonresident is set but forms.citations.{role} is empty"
        for c in cites[role]:
            assert validate_gov_url(c.url) == c.url, f"{st} {year} {role}: {c.url}"
        assert any(_QUOTE.search(c.source) and _PINPOINT.search(c.source) for c in cites[role]), (
            f"{st} {year} {role}: no citation quotes its document with a page pinpoint"
        )


@pytest.mark.parametrize(("st", "year"), ROLE_PACKS, ids=lambda v: str(v))
def test_state_scope_adds_each_role_list_to_that_role_only(st: str, year: int):
    cites = _role_citations(st, year)
    resident = _filing(st, year, "resident")
    assert resident.filing_role == "resident"
    for role in ROLES:
        other = next(r for r in ROLES if r != role)
        entry = _filing(st, year, role)
        assert entry.filing_role == role
        missing = [c.url for c in cites[role] if c not in entry.citations]
        assert not missing, f"{st} {year} {role}: state_scope entry lacks {missing}"
        foreign = [c.url for c in cites[other] if c not in cites[role] and c in entry.citations]
        assert not foreign, f"{st} {year} {role}: state_scope added the {other} citations {foreign}"
        leaked = [c.url for c in cites[role] if c in resident.citations]
        assert not leaked, f"{st} {year}: a full-year resident got the {role} citations {leaked}"
