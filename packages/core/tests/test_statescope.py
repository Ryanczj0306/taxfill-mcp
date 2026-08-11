"""state_scope tests (dev plan section 6). Offline; reads knowledge/states/."""

from datetime import date

from taxfill_core.schemas.profile import (
    Answer,
    Identity,
    Immigration,
    Profile,
    Provenance,
    ResidencePeriod,
    StateFootprintYear,
    VisaPeriod,
    WorkPeriod,
)
from taxfill_core.statescope import StateScopeResult, state_scope

US = Provenance.user_stated()


def _ans(v):
    return Answer(value=v, provenance=US)


def _rp(state, start, end):
    return ResidencePeriod(state=state, start=start, end=end, provenance=US)


def _wp(state, start, end, remote=None):
    return WorkPeriod(state=state, start=start, end=end, remote=remote, provenance=US)


def _profile(year=2023, lived=(), worked=()):
    return Profile(state_footprint={year: StateFootprintYear(lived=list(lived), worked=list(worked))})


def _by_state(result: StateScopeResult):
    return {s.state: s for s in result.states}


def test_no_income_tax_state_is_nothing_to_file():
    r = state_scope(_profile(lived=[_rp("TX", date(2023, 1, 1), date(2023, 12, 31))]), 2023)
    tx = _by_state(r)["TX"]
    assert tx.must_file is False and tx.filing_role == "none" and tx.forms == []
    assert tx.income_tax is False and "no personal income tax" in tx.reason.lower()


def test_wages_only_exempt_state_flags_the_caveat():
    # Washington: no wage tax, but a capital-gains caveat must be surfaced, not skipped.
    r = state_scope(_profile(lived=[_rp("WA", date(2023, 1, 1), date(2023, 12, 31))]), 2023)
    wa = _by_state(r)["WA"]
    assert wa.must_file is False
    assert any("capital-gains" in w.lower() or "capital gains" in w.lower() for w in wa.warnings)


def test_full_year_residence_is_resident():
    r = state_scope(_profile(lived=[_rp("CA", date(2023, 1, 1), date(2023, 12, 31))]), 2023)
    ca = _by_state(r)["CA"]
    assert ca.filing_role == "resident" and ca.must_file is True and ca.income_tax is True


def test_partial_year_residence_is_part_year():
    r = state_scope(_profile(lived=[_rp("CA", date(2023, 1, 1), date(2023, 6, 30))]), 2023)
    assert _by_state(r)["CA"].filing_role == "part_year"


def test_worked_not_lived_is_nonresident():
    # Lived in WA (no tax), worked in CA -> CA nonresident return on CA-source income.
    r = state_scope(_profile(
        lived=[_rp("WA", date(2023, 1, 1), date(2023, 12, 31))],
        worked=[_wp("CA", date(2023, 1, 1), date(2023, 12, 31))],
    ), 2023)
    by = _by_state(r)
    assert by["CA"].filing_role == "nonresident" and by["CA"].must_file is True
    assert by["WA"].must_file is False


def test_move_between_states_scopes_both():
    r = state_scope(_profile(lived=[
        _rp("CA", date(2023, 1, 1), date(2023, 6, 30)),
        _rp("WA", date(2023, 7, 1), date(2023, 12, 31)),
    ]), 2023)
    by = _by_state(r)
    assert by["CA"].filing_role == "part_year" and by["CA"].must_file is True
    assert by["WA"].must_file is False  # no income tax


def test_abroad_only_footprint_no_state_return():
    r = state_scope(_profile(lived=[_rp("ABROAD", date(2023, 1, 1), date(2023, 12, 31))]), 2023)
    assert r.states == []
    assert any("abroad" in n.lower() for n in r.notes)


def test_no_footprint_asks_for_it():
    r = state_scope(Profile(), 2023)
    assert r.states == []
    assert any("state footprint" in n.lower() for n in r.notes)


def test_allocation_caveat_always_present_when_states_touched():
    r = state_scope(_profile(lived=[_rp("CA", date(2023, 1, 1), date(2023, 12, 31))]), 2023)
    assert any("allocation" in n.lower() for n in r.notes)


# ── CA knowledge pack integration ──────────────────────────────────────────────


def test_ca_resident_resolves_540_and_credits_from_pack():
    ca = _by_state(state_scope(_profile(lived=[_rp("CA", date(2023, 1, 1), date(2023, 12, 31))]), 2023))["CA"]
    assert ca.forms[0] == "540" and "Schedule CA" in ca.forms
    assert any("renter" in b.lower() for b in ca.benefits_candidates)
    assert any("caleitc" in b.lower() or "earned income" in b.lower() for b in ca.benefits_candidates)
    assert any("ftb.ca.gov" in c.url for c in ca.citations)


def test_ca_part_year_resolves_540nr():
    ca = _by_state(state_scope(_profile(lived=[_rp("CA", date(2023, 1, 1), date(2023, 6, 30))]), 2023))["CA"]
    assert ca.forms[0] == "540NR"


def test_ca_treaty_nonconformity_warns_only_for_treaty_filers():
    footprint = [_rp("CA", date(2023, 1, 1), date(2023, 12, 31))]
    # Nonresident-alien filer (us_person False) -> the treaty-non-conformity warning fires.
    nra = Profile(identity=Identity(us_person=_ans(False)),
                  state_footprint={2023: StateFootprintYear(lived=footprint)})
    nra_ca = _by_state(state_scope(nra, 2023))["CA"]
    assert any("does not conform to federal tax treaties" in w.lower() or "still taxable" in w.lower() for w in nra_ca.warnings)
    # A U.S. citizen has no treaty position -> no such warning.
    cit = Profile(identity=Identity(us_person=_ans(True)),
                  state_footprint={2023: StateFootprintYear(lived=footprint)})
    cit_ca = _by_state(state_scope(cit, 2023))["CA"]
    assert not any("treaties" in w.lower() for w in cit_ca.warnings)


def test_ca_treaty_warning_on_nonresident_540nr_path():
    # The real treaty case: an NRA working in CA but domiciled elsewhere files 540NR.
    nra = Profile(
        identity=Identity(us_person=_ans(False)),
        state_footprint={2023: StateFootprintYear(
            lived=[_rp("TX", date(2023, 1, 1), date(2023, 12, 31))],
            worked=[_wp("CA", date(2023, 1, 1), date(2023, 12, 31))],
        )},
    )
    ca = _by_state(state_scope(nra, 2023))["CA"]
    assert ca.filing_role == "nonresident" and ca.forms[0] == "540NR"
    assert any("treaties" in w.lower() for w in ca.warnings)


def test_treaty_filer_detected_via_visa_timeline_when_us_person_unset():
    # Common F-1 intake state: us_person not yet answered, but a visa period exists.
    nra = Profile(
        identity=Identity(),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2021, 8, 1), provenance=US)]),
        state_footprint={2023: StateFootprintYear(lived=[_rp("CA", date(2023, 1, 1), date(2023, 12, 31))])},
    )
    ca = _by_state(state_scope(nra, 2023))["CA"]
    assert any("treaties" in w.lower() for w in ca.warnings)


def test_conforming_state_emits_positive_treaty_line_for_treaty_filers():
    # Regression: VA conforms (conforms_to_federal_treaties: true + a researched
    # treaty_note) but state_scope said NOTHING about treaties, so an agent could
    # not tell "evaluated: conforms" from "never evaluated". A treaty filer in a
    # conforming state must get the positive flows-through line + the pack note.
    footprint = [_rp("VA", date(2023, 1, 1), date(2023, 12, 31))]
    nra = Profile(identity=Identity(us_person=_ans(False)),
                  state_footprint={2023: StateFootprintYear(lived=footprint)})
    va = _by_state(state_scope(nra, 2023))["VA"]
    conforming = [w for w in va.warnings if "conforms to federal treaty treatment" in w]
    assert conforming, va.warnings
    line = conforming[0]
    assert "excluded from VA income" in line
    assert "do not add it back" in line.lower()
    # the pack's researched treaty_note (with its own caveats) reaches the user
    assert "State note:" in line and "federal adjusted gross income" in line
    # and it must never read as a non-conformity warning
    assert "does NOT conform" not in line


def test_conforming_state_treaty_line_only_for_treaty_filers():
    # A U.S. citizen has no treaty position — VA stays silent about treaties.
    footprint = [_rp("VA", date(2023, 1, 1), date(2023, 12, 31))]
    cit = Profile(identity=Identity(us_person=_ans(True)),
                  state_footprint={2023: StateFootprintYear(lived=footprint)})
    va = _by_state(state_scope(cit, 2023))["VA"]
    assert not any("treaty" in w.lower() for w in va.warnings)


def test_treaty_filer_conforming_vs_nonconforming_contrast():
    # The same NRA profile gets the positive line in VA and the loud warning in CA.
    def scope(st):
        p = Profile(identity=Identity(us_person=_ans(False)),
                    state_footprint={2023: StateFootprintYear(
                        lived=[_rp(st, date(2023, 1, 1), date(2023, 12, 31))])})
        return _by_state(state_scope(p, 2023))[st]

    va, ca = scope("VA"), scope("CA")
    assert any("conforms to federal treaty treatment" in w for w in va.warnings)
    assert any("does NOT conform to federal tax treaties" in w for w in ca.warnings)
    assert not any("does NOT conform" in w for w in va.warnings)
    assert not any("conforms to federal treaty treatment" in w for w in ca.warnings)


def test_nonconforming_treaty_warning_includes_the_pack_note():
    # The CA pack's researched treaty_note must reach the user with the warning.
    nra = Profile(identity=Identity(us_person=_ans(False)),
                  state_footprint={2023: StateFootprintYear(
                      lived=[_rp("CA", date(2023, 1, 1), date(2023, 12, 31))])})
    ca = _by_state(state_scope(nra, 2023))["CA"]
    warning = next(w for w in ca.warnings if "does NOT conform" in w)
    assert "State note:" in warning


def test_ca_credits_caveat_is_surfaced():
    # The unverified credit-limit caveat must reach the user alongside benefits.
    ca = _by_state(state_scope(_profile(lived=[_rp("CA", date(2023, 1, 1), date(2023, 12, 31))]), 2023))["CA"]
    assert ca.benefits_candidates
    assert any("not independently verified" in w.lower() for w in ca.warnings)


def test_overlapping_periods_do_not_inflate_to_resident():
    # Two overlapping/duplicate part-year periods (corrected move date) must NOT
    # sum past the full-year threshold (the merge fix). ~Jan-Jul = part_year.
    r = state_scope(_profile(lived=[
        _rp("CA", date(2023, 1, 1), date(2023, 7, 15)),
        _rp("CA", date(2023, 1, 10), date(2023, 7, 20)),  # overlaps the first
    ]), 2023)
    assert _by_state(r)["CA"].filing_role == "part_year"


def test_same_state_lived_and_worked_yields_single_resident_entry():
    r = state_scope(_profile(
        lived=[_rp("CA", date(2023, 1, 1), date(2023, 12, 31))],
        worked=[_wp("CA", date(2023, 1, 1), date(2023, 12, 31))],
    ), 2023)
    ca_entries = [s for s in r.states if s.state == "CA"]
    assert len(ca_entries) == 1 and ca_entries[0].filing_role == "resident"


def test_leap_year_full_year_residence_is_resident():
    # 2024 is a leap year (366 days) — full-year coverage must still be resident.
    r = state_scope(_profile(year=2024, lived=[_rp("CA", date(2024, 1, 1), date(2024, 12, 31))]), 2024)
    assert _by_state(r)["CA"].filing_role == "resident"


def test_income_tax_state_without_pack_still_must_file(tmp_path):
    # An income-tax state with no shipped pack: still a resident return, placeholder
    # form, and a note. Use an empty knowledge dir so this stays valid as more state
    # packs ship (NY itself is now packed).
    r = state_scope(_profile(lived=[_rp("NY", date(2023, 1, 1), date(2023, 12, 31))]), 2023, base_dir=tmp_path)
    ny = _by_state(r)["NY"]
    assert ny.must_file is True and ny.filing_role == "resident" and ny.income_tax is True
    assert ny.forms == ["(see state DOR — resident vs nonresident form)"]
    assert any("knowledge pack" in n.lower() for n in r.notes)


# ── H3: the remote-work employer-state trap (convenience-of-the-employer) ──────


def _wp_emp(state, start, end, employer_state, remote=True):
    return WorkPeriod(state=state, start=start, end=end, remote=remote,
                      employer_state=employer_state, provenance=US)


def test_remote_employer_state_raises_the_convenience_warning_without_asserting_a_filing():
    # Lived+worked WA (no income tax) for an employer sitting in NY: NY may source
    # the wages under its convenience rule, but no pack carries that rule yet — so
    # the result warns loudly and does NOT assert an NY filing.
    r = state_scope(_profile(
        year=2025,
        lived=[_rp("WA", date(2025, 1, 1), date(2025, 12, 31))],
        worked=[_wp_emp("WA", date(2025, 1, 1), date(2025, 12, 31), "NY")],
    ), 2025)
    assert all(s.state != "NY" for s in r.states)  # never asserted as must_file
    note = next(n for n in r.notes if "convenience-of-the-employer" in n)
    assert "NY" in note and "NONRESIDENT NY return" in note
    # (NY now carries the CITED rule — the generic verify-at-DOR fallback is
    # covered by test_nebraska_rule_is_year_aware's 2024 branch.)


def test_convenience_warning_attaches_to_the_employer_state_when_it_is_already_scoped():
    # Part-year NY resident who then works remotely from CA for the NY employer:
    # NY already has a filing entry — the warning belongs ON it, not in the notes.
    r = state_scope(_profile(
        year=2025,
        lived=[_rp("NY", date(2025, 1, 1), date(2025, 5, 31)),
               _rp("CA", date(2025, 6, 1), date(2025, 12, 31))],
        worked=[_wp_emp("CA", date(2025, 6, 1), date(2025, 12, 31), "NY")],
    ), 2025)
    ny = _by_state(r)["NY"]
    assert any("convenience-of-the-employer" in w for w in ny.warnings)
    assert not any("convenience-of-the-employer" in n for n in r.notes)


def test_employer_in_a_no_tax_state_is_silent():
    # Employer sits in TX: nothing to source into — no warning, no noise.
    r = state_scope(_profile(
        year=2025,
        lived=[_rp("CA", date(2025, 1, 1), date(2025, 12, 31))],
        worked=[_wp_emp("CA", date(2025, 1, 1), date(2025, 12, 31), "TX")],
    ), 2025)
    assert not any("convenience" in n for n in r.notes)
    assert not any("convenience" in w for s in r.states for w in s.warnings)


def test_employer_in_the_worked_state_is_silent():
    r = state_scope(_profile(
        year=2025,
        lived=[_rp("CA", date(2025, 1, 1), date(2025, 12, 31))],
        worked=[_wp_emp("CA", date(2025, 1, 1), date(2025, 12, 31), "CA")],
    ), 2025)
    assert not any("convenience" in n for n in r.notes)
    assert not any("convenience" in w for s in r.states for w in s.warnings)


# ── DEV_PLAN §7.2: effective_law_changes surface (D2c) ─────────────────────────


def test_unmodeled_law_change_is_surfaced_as_a_warning_with_its_citation():
    # RI 2025 carries the first data instance repo-wide: the Schedule HR1
    # OBBBA add-backs, modeled: false — the engine does not compute them, so
    # the scope answer must say so instead of leaving the delta in pack prose.
    r = state_scope(_profile(
        year=2025,
        lived=[_rp("RI", date(2025, 1, 1), date(2025, 12, 31))],
        worked=[_wp("RI", date(2025, 1, 1), date(2025, 12, 31))],
    ), 2025)
    ri = _by_state(r)["RI"]
    w = [w for w in ri.warnings if "Law change NOT modeled" in w]
    assert len(w) == 1
    assert "163(j)" in w[0] and "Schedule HR1" in w[0] and "Resolve via" in w[0]
    assert any("tax.ri.gov" in c.url for c in ri.citations)


def test_law_change_model_defaults_are_the_safe_ones():
    from taxfill_core.knowledge import EffectiveLawChange

    c = EffectiveLawChange(
        description="d", status="enacted",
        citation={"source": "s", "url": "https://www.irs.gov/newsroom"},
    )
    # modeled defaults FALSE: an unannotated change is surfaced, never silently
    # assumed to be inside the engine's math.
    assert c.modeled is False and c.affects == []


# ── The convenience rule as CITED data (Batch 2: NY/PA all years, DE/NE 2025) ──


def test_ny_employer_upgrades_the_generic_warning_to_the_cited_rule():
    r = state_scope(_profile(
        year=2025,
        lived=[_rp("WA", date(2025, 1, 1), date(2025, 12, 31))],
        worked=[_wp_emp("WA", date(2025, 1, 1), date(2025, 12, 31), "NY")],
    ), 2025)
    w = next(n for n in r.notes if "Remote-work trap" in n)
    assert "HAS a convenience-of-the-employer sourcing rule" in w
    assert "TSB-M-06(5)I" in w and "bona fide employer office" in w
    assert "m06_5i.pdf" in w  # the citation rides in the note text
    assert "no researched convenience rule" not in w


def test_nebraska_rule_is_year_aware():
    # LB 1023 AMENDED Nebraska's rule effective TY2025 — the 2025 pack carries
    # the amended rule; 2024 deliberately carries none (the old rule reached
    # further and its text was not re-verified), so 2024 falls back to the
    # generic verify-at-DOR warning. Writing one year-invariant NE rule would
    # have stated superseded law for one year or the other.
    fp_kwargs = dict(lived=[_rp("WA", date(2025, 1, 1), date(2025, 12, 31))])
    r25 = state_scope(_profile(year=2025, worked=[_wp_emp("WA", date(2025, 1, 1), date(2025, 12, 31), "NE")], **fp_kwargs), 2025)
    w25 = next(n for n in r25.notes if "Remote-work trap" in n)
    assert "LB 1023" in w25 and "seven days" in w25

    fp24 = dict(lived=[_rp("WA", date(2024, 1, 1), date(2024, 12, 31))])
    r24 = state_scope(_profile(year=2024, worked=[_wp_emp("WA", date(2024, 1, 1), date(2024, 12, 31), "NE")], **fp24), 2024)
    w24 = next(n for n in r24.notes if "Remote-work trap" in n)
    assert "no researched convenience rule" in w24


def test_cited_rule_attaches_to_an_existing_filing_with_its_citation():
    # Part-year NY resident later working remotely from CA for the NY employer:
    # the warning and the TSB-M citation land ON the NY filing entry.
    r = state_scope(_profile(
        year=2025,
        lived=[_rp("NY", date(2025, 1, 1), date(2025, 5, 31)),
               _rp("CA", date(2025, 6, 1), date(2025, 12, 31))],
        worked=[_wp_emp("CA", date(2025, 6, 1), date(2025, 12, 31), "NY")],
    ), 2025)
    ny = _by_state(r)["NY"]
    assert any("HAS a convenience-of-the-employer" in w for w in ny.warnings)
    assert any("m06_5i" in c.url for c in ny.citations)


def test_delaware_and_pennsylvania_rules_are_loaded():
    from taxfill_core.knowledge import load_state_knowledge

    de = load_state_knowledge("de", 2025).convenience_rule
    assert de is not None and "requirement of employment" in de.exceptions
    for year in (2023, 2024, 2025):
        pa = load_state_knowledge("pa", year).convenience_rule
        assert pa is not None and "of necessity" in pa.summary


# Repo root for the data-instance tests below.
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


# ── effective_law_changes: the shipped DATA instances (D2c, 2026-08-11) ────────
# The schema shipped long before any pack used it; 2026-08-10 promoted RI 2025's
# Schedule HR1, and 2026-08-11 promoted every other pack whose own prose already
# carried verified law-delta research. These tests pin the invariants that make
# the block trustworthy rather than decorative.


def _all_state_packs_with_changes():
    from taxfill_core.knowledge import load_state_knowledge

    out = []
    for d in sorted((REPO / "knowledge" / "states").iterdir()):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            if not p.stem.isdigit():
                continue
            pack = load_state_knowledge(d.name, int(p.stem), base_dir=REPO / "knowledge")
            if pack.effective_law_changes:
                out.append((d.name, int(p.stem), pack))
    return out


def _every_url_in(node) -> set[str]:
    """Every URL anywhere in a pack's YAML — credits/notes carry their own citations,
    nested arbitrarily deep, so this walks rather than enumerating known blocks."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "url" and isinstance(value, str):
                found.add(value.strip())
            else:
                found |= _every_url_in(value)
    elif isinstance(node, list):
        for item in node:
            found |= _every_url_in(item)
    return found


def test_law_change_instances_ship_and_are_cited_from_within_the_pack():
    """The promotion was a TRANSCRIPTION: each change's citation must be a URL the
    pack already carried, so no entry can smuggle in a source nobody verified."""
    import yaml as _yaml

    packs = _all_state_packs_with_changes()
    assert len(packs) >= 40, (
        f"only {len(packs)} state packs carry effective_law_changes — the 2026-08-11 promotion "
        f"covered every pack whose prose described a real delta; a big drop means blocks were lost"
    )
    for state, year, _pack in packs:
        path = REPO / "knowledge" / "states" / state / f"{year}.yaml"
        raw = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pack_urls = _every_url_in({k: v for k, v in raw.items() if k != "effective_law_changes"})
        for i, change in enumerate(raw.get("effective_law_changes") or []):
            where = f"{state}/{year}[{i}]"
            assert (change.get("description") or "").strip(), f"{where}: empty description"
            url = ((change.get("citation") or {}).get("url") or "").strip()
            assert url.startswith("http"), f"{where}: uncited change"
            assert url in pack_urls, (
                f"{where}: law-change citation {url} appears nowhere else in the pack — the "
                f"promotion must transcribe a source the pack already verified, never introduce one"
            )


def test_not_yet_final_changes_carry_a_lookup_path():
    """The schema's own contract: a figure without final published guidance is never
    hardcoded — the entry records where to resolve it instead. (A
    final_form_published change needs no lookup_path: its citation IS the path.)"""
    for state, year, pack in _all_state_packs_with_changes():
        for change in pack.effective_law_changes:
            if change.status != "final_form_published":
                assert (change.lookup_path or "").strip(), (
                    f"{state}/{year}: status={change.status} with no lookup_path — a not-yet-final "
                    f"figure must record where to resolve it rather than be treated as settled"
                )


def test_state_scope_surfaces_unmodeled_changes_and_stays_quiet_about_modeled_ones():
    """The consumer contract: modeled changes are already in the math (silence is
    correct); unmodeled ones must reach the user as a warning."""
    from datetime import date

    from taxfill_core.schemas.profile import Profile, Provenance, ResidencePeriod, StateFootprintYear
    from taxfill_core.statescope import state_scope

    us = Provenance.user_stated()
    checked_modeled = checked_unmodeled = 0
    for state, year, pack in _all_state_packs_with_changes():
        if state in {"tx", "fl", "wa", "nv", "sd", "wy", "ak", "tn", "nh"}:
            continue
        profile = Profile(state_footprint={year: StateFootprintYear(
            lived=[ResidencePeriod(state=state.upper(), start=date(year, 1, 1),
                                   end=date(year, 12, 31), provenance=us)],
            no_us_work=True,
        )})
        filings = {f.state: f for f in state_scope(profile, year).states}
        entry = filings.get(state.upper())
        if entry is None:
            continue
        warned = " ".join(entry.warnings)
        for change in pack.effective_law_changes:
            head = change.description.strip()[:40]
            if change.modeled:
                assert head not in warned, (
                    f"{state}/{year}: a MODELED change is being warned about — the math already "
                    f"includes it, so the warning is noise"
                )
                checked_modeled += 1
            else:
                assert "Law change NOT modeled" in warned, (
                    f"{state}/{year}: an UNMODELED change never reached the scope warnings"
                )
                checked_unmodeled += 1
    assert checked_unmodeled >= 10 and checked_modeled >= 1, (
        f"coverage too thin to be meaningful (modeled={checked_modeled}, unmodeled={checked_unmodeled})"
    )
