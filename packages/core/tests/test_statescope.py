"""state_scope tests (dev plan section 6). Offline; reads knowledge/states/."""

from datetime import date

from taxfill_core.schemas.profile import (
    Answer,
    Identity,
    Profile,
    Provenance,
    ResidencePeriod,
    StateFootprintYear,
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
