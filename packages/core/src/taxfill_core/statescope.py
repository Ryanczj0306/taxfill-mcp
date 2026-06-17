"""State filing scope — dev plan section 6 (the state scoping tool).

``state_scope(profile, year)`` reads where the user lived and worked that year
(the profile's state footprint) and returns, for each state touched, whether a
return is required, in what role (resident / part-year / nonresident), which
forms, candidate benefits, and any warnings. No-income-tax states resolve to
"nothing to file". Multi-state income ALLOCATION stays agent+user judgment;
this tool provides the scoping, the rules, and the warnings.

Critically: a state that does not conform to federal tax treaties (California)
gets a loud warning when the filer has a treaty position — federally
treaty-exempt income is still taxable there.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.knowledge import Citation, StateKnowledge, load_state_knowledge
from taxfill_core.schemas.profile import Profile

__all__ = ["StateFiling", "StateScopeResult", "state_scope"]

FilingRole = Literal["resident", "part_year", "nonresident", "none"]


class StateFiling(BaseModel):
    """The scope answer for one state."""

    model_config = ConfigDict(extra="forbid")

    state: str
    income_tax: bool = Field(description="Whether the state levies a broad personal income tax.")
    filing_role: FilingRole
    must_file: bool
    forms: list[str] = Field(default_factory=list)
    reason: str
    benefits_candidates: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class StateScopeResult(BaseModel):
    """Per-state scope for one tax year."""

    model_config = ConfigDict(extra="forbid")

    year: int
    states: list[StateFiling] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _repo_knowledge_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "knowledge"


def _load_no_income_tax(base_dir):
    base = Path(base_dir) if base_dir is not None else _repo_knowledge_dir()
    path = base / "states" / "no_income_tax.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    out: dict[str, dict] = {}
    for entry in raw.get("none", []) or []:
        out[entry["state"].upper()] = {"kind": "none", **entry}
    for entry in raw.get("wages_only_exempt", []) or []:
        out[entry["state"].upper()] = {"kind": "wages_only", **entry}
    return out, raw.get("citation")


def _days_lived_in_year(periods, year: int) -> int:
    """Days a set of residence periods cover within the calendar year.

    Periods are clamped to the year, then MERGED into disjoint intervals before
    counting — so overlapping or duplicated intake periods (two interviews, a
    corrected move date) don't inflate the count and mislabel a part-year
    resident as a full-year resident. Adjacent days (one period ends, the next
    starts the next day) count as continuous coverage.
    """
    jan1, dec31 = date(year, 1, 1), date(year, 12, 31)
    clamped = []
    for p in periods:
        start = max(p.start, jan1)
        end = min(p.end or dec31, dec31)  # ongoing period -> through year end
        if end >= start:
            clamped.append((start, end))
    clamped.sort()
    days, cur_start, cur_end = 0, None, None
    for s, e in clamped:
        if cur_end is None or s > cur_end + timedelta(days=1):  # gap -> new interval
            if cur_end is not None:
                days += (cur_end - cur_start).days + 1
            cur_start, cur_end = s, e
        else:  # overlapping or adjacent -> extend
            cur_end = max(cur_end, e)
    if cur_end is not None:
        days += (cur_end - cur_start).days + 1
    return days


def _is_treaty_filer(profile: Profile) -> bool:
    ident = profile.identity
    us_person_false = ident is not None and ident.us_person is not None and ident.us_person.value is False
    has_visa = profile.immigration is not None and bool(profile.immigration.visa_timeline)
    return us_person_false or has_visa


def state_scope(profile: Profile, year: int, *, base_dir: str | Path | None = None) -> StateScopeResult:
    """Scope the state returns for one tax year from the profile's state footprint.

    Args:
        profile: the intake profile; ``state_footprint[year]`` (where the user
            lived/worked, with date ranges) drives scoping.
        year: tax year.
        base_dir: override the knowledge directory.

    Returns:
        A :class:`StateScopeResult`: one :class:`StateFiling` per state touched
        (resident/part-year/nonresident/none, must_file, forms, candidate
        benefits, warnings), plus notes. No state footprint yields an empty
        result with a note to collect it.
    """
    footprint = profile.state_footprint.get(year)
    notes: list[str] = []
    if footprint is None:
        return StateScopeResult(
            year=year,
            notes=[f"No state footprint for {year} — ask where the user lived and worked that year "
                   f"(date ranges); that drives which states require a return."],
        )

    lived_by_state: dict[str, list] = {}
    for p in footprint.lived:
        lived_by_state.setdefault(p.state.upper(), []).append(p)
    worked_states = {p.state.upper() for p in footprint.worked}
    touched = (set(lived_by_state) | worked_states) - {"ABROAD"}
    if not touched:
        notes.append("Footprint is entirely abroad — no U.S. state return indicated.")

    no_tax, no_tax_cite = _load_no_income_tax(base_dir)
    year_len = 366 if calendar.isleap(year) else 365
    treaty_filer = _is_treaty_filer(profile)

    out: list[StateFiling] = []
    for st in sorted(touched):
        lived_days = _days_lived_in_year(lived_by_state.get(st, []), year)
        full_year = lived_days >= year_len  # covered every day (vs reached via the edge slack)
        if lived_days >= year_len - 3:  # whole year (a few days' slack for date-edge rounding)
            role: FilingRole = "resident"
        elif lived_days > 0:
            role = "part_year"
        elif st in worked_states:
            role = "nonresident"
        else:
            role = "none"

        # No-income-tax states: nothing to file (with the narrow caveats flagged).
        if st in no_tax:
            info = no_tax[st]
            cites = [Citation(source=f"{st} Department of Revenue", url=info["dor"])] if info.get("dor", "").startswith("http") else []
            if info["kind"] == "none":
                reason = f"{st} levies no personal income tax — no state return required."
                warnings = []
            else:
                reason = f"{st} does not tax wages — generally no return required."
                warnings = [info["note"]] if info.get("note") else []
            out.append(StateFiling(
                state=st, income_tax=(info["kind"] != "none"), filing_role="none",
                must_file=False, forms=[], reason=reason, warnings=warnings, citations=cites,
            ))
            continue

        # Income-tax state: try the state knowledge pack for forms/credits/treaty conformity.
        try:
            sk: StateKnowledge | None = load_state_knowledge(st.lower(), year, base_dir)
        except FileNotFoundError:
            sk = None

        forms: list[str] = []
        benefits: list[str] = []
        warnings = []
        cites = []
        if sk is not None:
            forms_block = getattr(sk, "forms", None) or {}
            if role == "resident" and forms_block.get("resident"):
                forms = [forms_block["resident"]] + ([forms_block["schedule"]] if forms_block.get("schedule") else [])
            elif role in ("part_year", "nonresident") and forms_block.get("part_year_or_nonresident"):
                forms = [forms_block["part_year_or_nonresident"]] + ([forms_block["schedule"]] if forms_block.get("schedule") else [])
            for c in getattr(sk, "credits", None) or []:
                if isinstance(c, dict) and c.get("name"):
                    benefits.append(c["name"] + (f" — {c['eligibility']}" if c.get("eligibility") else ""))
            # Surface the credits caveat alongside the benefits (some CA credit
            # dollar limits could not be independently re-verified — see the pack).
            cv = getattr(sk, "credits_verification", None)
            if benefits and cv:
                warnings.append(f"Credit amounts/limits are not independently verified: {cv}")
            if not sk.conforms_to_federal_treaties and treaty_filer:
                warnings.append(
                    f"{st} does NOT conform to federal tax treaties: income exempt from federal tax under a "
                    f"treaty is STILL taxable by {st}. Do not carry a federal treaty exclusion onto the state return."
                )
            if sk.citation:
                cites.append(sk.citation)
        else:
            notes.append(f"No {st} knowledge pack for {year} yet — confirm the filing requirement, forms, and "
                         f"credits at the state DOR before filing.")

        must_file = role in ("resident", "part_year", "nonresident")
        resident_reason = (
            f"Lived in {st} all of {year} — file a resident return on income from all sources."
            if full_year else
            f"Lived in {st} essentially all of {year} (a few days short — confirm it was not a part-year "
            f"move) — likely a resident return on income from all sources."
        )
        reason = {
            "resident": resident_reason,
            "part_year": f"Lived in {st} part of {year} — file a part-year return on income while a resident (plus {st}-source income while not).",
            "nonresident": f"Worked in {st} in {year} without living there — file a nonresident return on {st}-source income.",
            "none": f"{st} appears in the footprint but with no residence or work days in {year}.",
        }[role]
        if not forms and must_file:
            forms = ["(see state DOR — resident vs nonresident form)"]
        out.append(StateFiling(
            state=st, income_tax=True, filing_role=role, must_file=must_file, forms=forms,
            reason=reason, benefits_candidates=benefits, warnings=warnings, citations=cites,
        ))

    notes.append("Multi-state income allocation (which dollars belong to which state) is your and the user's "
                 "judgment; this tool scopes the returns and supplies the rules/warnings, not the allocation.")
    return StateScopeResult(year=year, states=out, notes=notes)
