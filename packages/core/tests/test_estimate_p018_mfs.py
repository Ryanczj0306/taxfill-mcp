"""P-018 regression pins for the JF5a "J0 re-verify follow-ups" (Phase J JK3). All data synthetic.

Two married-filing-separately defects the 2026-09-24 re-verify recorded, both closed by
JF5a (estimate._election_state / _mfs_pair) and pinned here on a RECORDED election and a
CONFIRMED married-filing-separately status with bank-deposit interest — the shape the earlier
pins did not reach (they build the profile through a compare_scenarios scenario, or leave the
marital status open, or carry no deposit interest):

(a) The §6013(g)/(h) election ends the IRC 871(i)(2)(A) deposit-interest exclusion on a
    SEPARATE return too. Pub 519 ch. 1: "If you make this choice, you and your spouse are
    treated for income tax purposes as residents for your entire tax year" — and after the
    election year "you and your spouse can file joint or separate returns", both still
    residents. A recorded DECLINE keeps the exclusion (the control).
(b) The spouse's separate return in the two-return MFS pair follows the SPOUSE'S OWN
    residency, never the taxpayer's — Pub 519, Frequently Asked Questions: "If your spouse
    does not make this choice, you must file a separate return on Form 1040 or 1040-SR.
    Your spouse must file Form 1040-NR." — so a U.S.-citizen (or resident) spouse of a
    nonresident gets the standard deduction and the resident rates, and pays tax on deposit
    interest.

Every expected figure is re-derived through calc (standard_deduction, tax_from_taxable_income,
tax_with_preferential_rates) — never a hand-typed amount. The fixtures are the hypothetical
F-1-from-2020 student test_estimate.py uses (nonresident for 2023 by the substantial presence
test: 2020-2024 are exempt-individual years).
"""

from datetime import date

import pytest

from taxfill_core import intake
from taxfill_core.calc import standard_deduction, tax_from_taxable_income, tax_with_preferential_rates
from taxfill_core.estimate import IncomeSnapshot, RefundEstimate, _election_state, estimate_refund
from taxfill_core.schemas.profile import (
    Answer,
    Household,
    Identity,
    Immigration,
    Profile,
    Provenance,
    ResidencyFacts,
    Spouse,
    VisaPeriod,
)

US = Provenance.user_stated()
YEAR = 2023
MFS = "married_filing_separately"
MFJ = "married_filing_jointly"


def _ans(v):
    return Answer(value=v, provenance=US)


def _f1_student_facts(**extra) -> ResidencyFacts:
    return ResidencyFacts(days_in_us={y: _ans(d) for y, d in {2020: 130, 2021: 330, 2022: 330, 2023: 330}.items()},
                          **extra)


def _f1_timeline() -> Immigration:
    return Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2020, 8, 24), end=None, provenance=US)])


def _citizen_spouse() -> Spouse:
    return Spouse(us_person=_ans(True))


def _h1b_resident_spouse() -> Spouse:
    """A spouse who is NOT a declared U.S. person but whose OWN timeline and day counts classify
    resident (an H-1B worker present all year — no exempt-individual days, so the substantial
    presence test is met)."""
    return Spouse(
        us_person=_ans(False),
        immigration=Immigration(
            visa_timeline=[VisaPeriod(status="H-1B", start=date(2019, 1, 2), end=None, provenance=US)]
        ),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in {2021: 360, 2022: 360, 2023: 360}.items()}),
    )


def _nra_taxpayer(status: str | None, *, election: bool | None, spouse: Spouse | None) -> Profile:
    """The F-1 nonresident taxpayer, married, with an optional confirmed status and a recorded
    election answer (True elect / False decline / None not answered)."""
    extra = {} if election is None else {"section_6013_election": _ans(election)}
    return Profile(
        household=Household(
            marital_status=_ans("married"), filing_status=_ans(status) if status else None, spouse=spouse,
        ),
        identity=Identity(us_person=_ans(False)),
        immigration=_f1_timeline(),
        residency_facts=_f1_student_facts(**extra),
    )


def _labels(est: RefundEstimate) -> dict[str, int]:
    return {ln.label: ln.amount for ln in est.composition}


def _deposit_line(est: RefundEstimate):
    return next((ln for ln in est.composition if ln.slot == "deposit_interest_exclusion"), None)


def _spouse_line(est: RefundEstimate) -> int:
    return next(ln.amount for ln in est.composition if ln.slot == "spouse_mfs_return")


def _resident_return(wages: int, interest: int, withholding: int, status: str) -> int:
    """A resident's return through calc alone: the pack's standard deduction, ordinary rates."""
    taxable = max(0, wages + interest - standard_deduction(status, YEAR).amount)
    return withholding - tax_from_taxable_income(taxable, status, YEAR).tax


def _nonresident_return(wages: int, taxed_interest: int, withholding: int, status: str) -> int:
    """A Form 1040-NR return through calc alone: no standard deduction (and no itemized amount
    here), the deposit interest already left out by the caller, ordinary rates."""
    return withholding - tax_from_taxable_income(wages + taxed_interest, status, YEAR).tax


# ---------------------------------------------------------------------------
# (a) the election ends the deposit exclusion on a confirmed SEPARATE status
# ---------------------------------------------------------------------------

_TP_INCOME = dict(wages=40_000, federal_withholding=3_000, interest=900, bank_deposit_interest=900)


def test_p018_a_recorded_6013g_election_on_a_confirmed_mfs_status_taxes_the_deposit_interest():
    profile = _nra_taxpayer(MFS, election=True, spouse=_citizen_spouse())
    state = _election_state(profile, YEAR)
    assert state.election and not state.implied and state.kind == "g"   # a nonresident all year + a citizen
    assert state.own_classification == "nonresident"                    # the facts, without the election
    est = estimate_refund(profile, YEAR, IncomeSnapshot(**_TP_INCOME))
    assert est.low == est.high == est.point                             # one confirmed status
    assert _deposit_line(est) is None
    labels = _labels(est)
    assert labels["Total income"] == 40_900                             # the $900 is IN income
    assert labels["Less: standard deduction"] == -standard_deduction(MFS, YEAR).amount
    assert est.point == _resident_return(40_000, 900, 3_000, MFS)
    assert est.point != _nonresident_return(40_000, 0, 3_000, MFS)      # the defect's figure
    assert not any("1040-NR" in ln.label for ln in est.composition)
    note = next(a for a in est.assumptions if "was NOT excluded" in a)
    assert note.startswith("Under the §6013(g)/(h) election recorded on this profile the $900")
    assert "joint or separate alike" in note and "ELECTION, not the marriage" in note
    assert not any("was EXCLUDED from income" in a for a in est.assumptions)
    # Intake applies the recorded election on the same marriage rule (one rule, P-018).
    assert intake._election_in_effect(profile, YEAR)


def test_p018_the_mfs_figure_taxes_the_deposit_interest_exactly_as_the_mfj_figure_does():
    income = IncomeSnapshot(**_TP_INCOME)
    mfs = estimate_refund(_nra_taxpayer(MFS, election=True, spouse=_citizen_spouse()), YEAR, income)
    mfj = estimate_refund(_nra_taxpayer(MFJ, election=True, spouse=_citizen_spouse()), YEAR, income)
    for est in (mfs, mfj):
        assert _deposit_line(est) is None
        assert _labels(est)["Total income"] == 40_900
    assert mfj.point == _resident_return(40_000, 900, 3_000, MFJ)
    assert mfs.point == _resident_return(40_000, 900, 3_000, MFS)


def test_p018_a_recorded_election_on_mfs_with_a_spouse_snapshot_prices_both_returns_as_residents():
    # The two-return pair under the election: both returns are residents' — the taxpayer's
    # deposit interest taxed, the citizen spouse's standard deduction taken.
    income = IncomeSnapshot(**_TP_INCOME, spouse=IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    est = estimate_refund(_nra_taxpayer(MFS, election=True, spouse=_citizen_spouse()), YEAR, income)
    assert _deposit_line(est) is None
    assert _spouse_line(est) == _resident_return(60_000, 0, 6_000, MFS)
    assert est.point == _resident_return(40_000, 900, 3_000, MFS) + _resident_return(60_000, 0, 6_000, MFS)


def test_p018_control_a_recorded_decline_on_mfs_keeps_the_deposit_exclusion():
    # The control: the SAME profile with the election DECLINED is a nonresident's Form 1040-NR —
    # the $900 is excluded (IRC 871(i)(2)(A)) and there is no standard deduction.
    profile = _nra_taxpayer(MFS, election=False, spouse=_citizen_spouse())
    state = _election_state(profile, YEAR)
    assert not state.election and state.declined
    assert not intake._election_in_effect(profile, YEAR)
    est = estimate_refund(profile, YEAR, IncomeSnapshot(**_TP_INCOME))
    assert _deposit_line(est).amount == -900
    labels = _labels(est)
    assert "Less: standard deduction" not in labels
    assert labels["Taxable income"] == 40_000
    assert est.point == _nonresident_return(40_000, 0, 3_000, MFS)
    assert any(a.startswith("US bank-deposit interest of $900 was EXCLUDED from income") for a in est.assumptions)


def test_p018_the_mfs_election_and_decline_differ_by_exactly_the_deduction_and_the_deposit_interest():
    income = IncomeSnapshot(**_TP_INCOME)
    elected = estimate_refund(_nra_taxpayer(MFS, election=True, spouse=_citizen_spouse()), YEAR, income)
    declined = estimate_refund(_nra_taxpayer(MFS, election=False, spouse=_citizen_spouse()), YEAR, income)
    e, d = _labels(elected), _labels(declined)
    assert e["Taxable income"] - d["Taxable income"] == 900 - standard_deduction(MFS, YEAR).amount


# ---------------------------------------------------------------------------
# (b) the spouse's separate return follows the SPOUSE's own classification
# ---------------------------------------------------------------------------

_SPOUSE = dict(wages=60_000, federal_withholding=6_000, interest=1_000, bank_deposit_interest=1_000)


@pytest.mark.parametrize("spouse", [_citizen_spouse, _h1b_resident_spouse], ids=["us_citizen", "resident_by_spt"])
def test_p018_a_resident_spouse_of_a_nonresident_files_a_1040_in_the_mfs_pair(spouse):
    profile = _nra_taxpayer(MFS, election=None, spouse=spouse())
    assert not _election_state(profile, YEAR).election                 # no election: the taxpayer stays a nonresident
    income = IncomeSnapshot(wages=18_000, federal_withholding=1_400, spouse=IncomeSnapshot(**_SPOUSE))
    est = estimate_refund(profile, YEAR, income)
    got = _spouse_line(est)
    # The spouse's own Form 1040: the MFS standard deduction, the resident rates, the deposit interest taxed.
    expected = _resident_return(60_000, 1_000, 6_000, MFS)
    assert got == expected
    # The defect (before JF5a): the taxpayer's nonresident flag was borrowed onto the spouse's return
    # and cost it the standard deduction ONLY — the spouse's deposit exclusion already followed the
    # spouse's own facts, so the $1,000 was taxed. The engine must not give that figure: it is the
    # MFS standard deduction at 22% ($13,850 x 22% = $3,047, the re-verify's ~$3,050) below this one.
    borrowed = _nonresident_return(60_000, 1_000, 6_000, MFS)
    assert got != borrowed
    # The taxpayer's own return is still the nonresident's Form 1040-NR ($0 deduction).
    assert est.point == _nonresident_return(18_000, 0, 1_400, MFS) + expected
    note = next(a for a in est.assumptions if a.startswith("The spouse's separate return was computed under RESIDENT"))
    assert "not under your nonresident classification" in note
    assert not any(a.startswith("The spouse's separate return was computed under NONRESIDENT") for a in est.assumptions)


def test_p018_a_citizen_spouses_separate_return_keeps_the_preferential_rates():
    # Resident rules include the Qualified Dividends and Capital Gain Tax Worksheet — a nonresident's
    # 1040-NR estimate taxes investment income at ordinary rates; the citizen spouse's 1040 must not.
    profile = _nra_taxpayer(MFS, election=None, spouse=_citizen_spouse())
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400,
        spouse=IncomeSnapshot(wages=60_000, federal_withholding=6_000, dividends=8_000, qualified_dividends=8_000),
    )
    est = estimate_refund(profile, YEAR, income)
    taxable = 68_000 - standard_deduction(MFS, YEAR).amount
    expected = 6_000 - tax_with_preferential_rates(taxable, 8_000, 0, 0, MFS, YEAR).tax
    assert _spouse_line(est) == expected
    assert expected != 6_000 - tax_from_taxable_income(taxable, MFS, YEAR).tax   # the worksheet matters here
