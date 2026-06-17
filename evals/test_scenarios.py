"""End-to-end eval scenarios — dev plan section 14.

Synthetic taxpayers (no real PII) run through the engine, asserting the
behaviours the dev plan calls out per scenario letter. These are integration
EVALS, not unit tests: they prove the M1-M4 stack does the right thing on
realistic cases, including the honest-estimate and no-invented-numbers rules.

Federal scenarios (a, d, e, g, h, i, j) run now. State scenarios (b, c, f) need
M5 (CA packs + state_scope) and are explicit xfail/skip markers so the gap is
visible, never silently missing. Multi-form fill+verify on real PDFs is covered
by packages/core/tests/test_filing_integration.py (the 1040 and 1040-NR stacks).
"""
from __future__ import annotations

from datetime import date

import pytest

from taxfill_core.calc import standard_deduction, tax_from_taxable_income
from taxfill_core.estimate import IncomeSnapshot, estimate_refund
from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay
from taxfill_core.filing_summary import filing_summary
from taxfill_core.intake import intake_checklist
from taxfill_core.knowledge import load_knowledge
from taxfill_core.residency import classify
from taxfill_core.schemas.profile import (
    Answer,
    Household,
    Identity,
    Immigration,
    Profile,
    Provenance,
    ResidencePeriod,
    ResidencyFacts,
    StateFootprintYear,
    VisaPeriod,
    WorkPeriod,
)
from taxfill_core.sources import get_sources
from taxfill_core.statescope import state_scope

US = Provenance.user_stated()
TODAY = date(2026, 6, 17)


def _ans(v):
    return Answer(value=v, provenance=US)


def _calc_refund(wages, withholding, status, year=2023):
    taxable = max(0, wages - standard_deduction(status, year).amount)
    return withholding - tax_from_taxable_income(taxable, status, year).tax


# ── (j) estimate accuracy & honesty (simple W-2) ───────────────────────────────


def test_eval_j_estimate_brackets_and_tightens():
    income = IncomeSnapshot(wages=50000, federal_withholding=6000)
    final = _calc_refund(50000, 6000, "single")  # the eventual computed refund

    # Early: only a W-2, filing status not yet chosen (married, MFJ-vs-MFS open).
    early = estimate_refund(Profile(household=Household(marital_status=_ans("married"))), 2023, income)
    assert early.label == "ESTIMATE"
    assert early.assumptions, "an estimate without its assumption list fails the eval"
    assert early.low < early.high, "a point value presented as exact fails the eval"

    # Confirmed single: the range tightens to one number that equals the calc refund.
    confirmed = estimate_refund(
        Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single"))), 2023, income
    )
    assert confirmed.low == confirmed.high == confirmed.point == final
    # Tightening: the confirmed band is no wider than the early one.
    assert (confirmed.high - confirmed.low) <= (early.high - early.low)


# ── (d) refund + direct deposit ────────────────────────────────────────────────


def test_eval_d_refund_direct_deposit():
    item = FilingManifestItem(form="1040", tax_year=2023, bottom_line=1600, state="California", direct_deposit=True)
    summ = filing_summary([item], today=TODAY).items[0]
    assert summ.refund == 1600 and "refund $1,600" in summ.headline.lower()
    assert "direct deposit" in summ.headline.lower()
    fp = file_and_pay([item]).returns[0]
    assert "Ogden, UT 84201-0002" in fp.mailing_address  # CA refund -> no-payment address
    assert any("routing and account" in p for p in fp.payment)


# ── (e) balance due: paid online vs by check ───────────────────────────────────


def test_eval_e_balance_due_paid_online_vs_check():
    base = dict(form="1040", tax_year=2023, bottom_line=-800, state="California")
    by_check = file_and_pay([FilingManifestItem(**base)]).returns[0]
    assert any('"United States Treasury"' in p for p in by_check.payment)
    assert "Cincinnati, OH 45280-2501" in by_check.mailing_address  # with-payment address

    paid_online = file_and_pay([FilingManifestItem(**base, paid_online=True)]).returns[0]
    assert any("already paid" in p.lower() for p in paid_online.payment)
    assert "Ogden, UT 84201-0002" in paid_online.mailing_address  # no check enclosed -> no-payment address


# ── (g) F-1 -> H-1B mid-year transition (treaty per period) ────────────────────


def test_eval_g_f1_to_h1b_midyear():
    # Status change during the year: residency must reason about both periods.
    result = classify(
        [
            {"status": "F-1", "start": "2019-08-01", "end": "2023-09-30"},
            {"status": "H-1B", "start": "2023-10-01", "end": None},
        ],
        {2019: 140, 2020: 300, 2021: 300, 2022: 300, 2023: 330},
        2023,
    )
    blob = (result.work + " " + " ".join(result.reasons)).lower()
    assert result.classification == "nonresident"  # F-1 still exempt; H-1B days alone don't meet SPT
    # The engine reasons about the mid-year split: F-1 exempt period excluded, the
    # non-exempt (post-F-1) part counted day-by-day.
    assert "f-1" in blob and "exempt" in blob and "non-exempt" in blob
    assert result.citations, "residency determination must cite authority"
    # Intake captures visa facts as date-range PERIODS, so per-period (student) treaty
    # eligibility survives the status change — the P-004 countermeasure surface.
    nra = Profile(identity=Identity(us_person=_ans(False)))
    visa_q = next(q for q in intake_checklist(nra).next_questions if q.id == "immigration.visa_timeline")
    assert "F-1" in visa_q.disambiguation and "treaty" in visa_q.disambiguation.lower()


# ── (a) F-1 back-filing, federal (the prototype / flagship) ────────────────────


def test_eval_a_f1_backfile_federal():
    # NRA student with self-employment income: nonresident -> Form 1040-NR path,
    # bottom line + 1040-NR mailing/deadlines all resolve and cite sources.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2021, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2021: _ans(150), 2022: _ans(300), 2023: _ans(300)}),
        household=Household(marital_status=_ans("unmarried")),
    )
    residency = classify(
        [{"status": "F-1", "start": "2021-08-01", "end": None}],
        {2021: 150, 2022: 300, 2023: 300},
        2023,
    )
    assert residency.classification == "nonresident"  # F-1 exempt -> NRA -> 1040-NR

    est = estimate_refund(profile, 2023, IncomeSnapshot(self_employment_net=20000, federal_withholding=0))
    assert est.label == "ESTIMATE" and est.point <= 0  # SE income, no withholding -> owes
    assert any("self-employment" in c.label.lower() for c in est.composition)

    nr = FilingManifestItem(form="1040-NR", tax_year=2023, bottom_line=est.point)
    fp = file_and_pay([nr]).returns[0]
    # Owes -> the 1040-NR WITH-payment address (Charlotte); a refund would use Austin.
    assert "Charlotte, NC 28201-1303" in fp.mailing_address
    assert any('"United States Treasury"' in p for p in fp.payment)
    summ = filing_summary([nr], today=TODAY).items[0]
    assert summ.citations  # bottom line is cited


# ── (h) user who moved after the tax year (current vs historical address) ──────


def test_eval_h_moved_after_tax_year():
    # Lived in CA during 2023, now receives mail in WA. Intake must ask for the
    # CURRENT mailing address (P-002) and collect the historical address separately.
    profile = Profile(
        identity=Identity(us_person=_ans(True)),
        state_footprint={2023: StateFootprintYear(
            lived=[ResidencePeriod(state="CA", start=date(2023, 1, 1), end=date(2023, 12, 31), provenance=US)]
        )},
    )
    cl = intake_checklist(profile, tax_year=2023)
    addr_q = next(q for q in cl.next_questions if q.id == "identity.mailing_address")
    assert "TODAY" in addr_q.disambiguation and "lived during the tax year" in addr_q.disambiguation
    # The historical state is recorded under state_footprint, never auto-used as the address.
    assert profile.identity.mailing_address is None


# ── (i) post-2025 law change: resolve via sources, never fabricate ─────────────


def test_eval_i_post_2025_refuses_to_invent():
    # A 2026 filing (OBBBA-era) has no shipped knowledge pack. The engine must
    # REFUSE to produce numbers (hallucinated numbers fail the eval) and the
    # freshness protocol must point to authoritative sources instead.
    with pytest.raises(FileNotFoundError) as exc:
        load_knowledge("federal", 2026)
    assert "freshness protocol" in str(exc.value).lower() or "irs.gov" in str(exc.value).lower()
    with pytest.raises(FileNotFoundError):
        tax_from_taxable_income(50000, "single", 2026)  # no pack -> no invented tax

    # get_sources still guides the agent to .gov + the change-channels.
    src = get_sources("car loan interest deduction", 2026)
    assert src.change_channels  # freshness signals always returned
    assert "irs.gov" in src.retrieval_hint and "2026" in src.retrieval_hint


# ── (b, c, f) state scenarios — M5 ─────────────────────────────────────────────


def test_eval_b_w2_federal_and_ca_resident():
    # (b) Simple W-2, full-year California resident: federal refund estimate +
    # a CA resident return (Form 540) is required.
    profile = Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
        state_footprint={2023: StateFootprintYear(
            lived=[ResidencePeriod(state="CA", start=date(2023, 1, 1), end=date(2023, 12, 31), provenance=US)]
        )},
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.point == _calc_refund(50000, 6000, "single")  # federal bottom line
    ca = next(s for s in state_scope(profile, 2023).states if s.state == "CA")
    assert ca.filing_role == "resident" and ca.must_file is True and ca.forms[0] == "540"


def test_eval_c_part_year_ca_remote():
    # (c) Moved out of CA mid-year, then lived/worked remotely from WA (no income
    # tax): CA part-year return (540NR); WA nothing to file. Allocation = judgment.
    profile = Profile(
        identity=Identity(us_person=_ans(True)),
        state_footprint={2023: StateFootprintYear(
            lived=[
                ResidencePeriod(state="CA", start=date(2023, 1, 1), end=date(2023, 5, 31), provenance=US),
                ResidencePeriod(state="WA", start=date(2023, 6, 1), end=date(2023, 12, 31), provenance=US),
            ],
            worked=[WorkPeriod(state="WA", start=date(2023, 6, 1), end=date(2023, 12, 31), remote=True, provenance=US)],
        )},
    )
    scope = state_scope(profile, 2023)
    by = {s.state: s for s in scope.states}
    assert by["CA"].filing_role == "part_year" and by["CA"].forms[0] == "540NR"
    assert by["WA"].must_file is False  # no income tax
    assert any("allocation" in n.lower() for n in scope.notes)


def test_eval_f_no_income_tax_state():
    # (f) Lived in Texas all year -> no state return required ("nothing to file").
    profile = Profile(state_footprint={2023: StateFootprintYear(
        lived=[ResidencePeriod(state="TX", start=date(2023, 1, 1), end=date(2023, 12, 31), provenance=US)]
    )})
    tx = next(s for s in state_scope(profile, 2023).states if s.state == "TX")
    assert tx.must_file is False and tx.filing_role == "none"
    assert "no personal income tax" in tx.reason.lower()
