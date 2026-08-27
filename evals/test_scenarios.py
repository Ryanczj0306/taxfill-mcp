"""End-to-end eval scenarios — dev plan section 14.

Synthetic taxpayers (no real PII) run through the engine, asserting the
behaviours the dev plan calls out per scenario letter. These are integration
EVALS, not unit tests: they prove the M1-M4 stack does the right thing on
realistic cases, including the honest-estimate and no-invented-numbers rules.

All 23 scenarios (a–s, including the provisional-guard family i–i5) run now: the federal cases (a, d, e, g, h, i, j) on
the M1-M4 stack; the joint / separate / NRA-spouse cases (k, l, m) on the
filing-status-aware engine (MFJ math, the both-ways comparison, and the §6013(g)/(h)
election surface); the state cases (b, c, f) on M5 (CA packs + state_scope);
the family-with-children case (n) on the Phase F credit-aware estimator (CTC/ACTC
+ EITC from dependents' DOB/SSN facts); the US-citizen + NRA-spouse couple (o)
on the Tier-2 spouse-residency battery (intake election questions, the MFJ-with-
caveat estimate, and the signed election-statement assembly item), plus the
treaty-exempt-income (China Art. 20(c) student) estimator surface; the
dual-status corridor (p) on the G5 stack (the First-Year-Choice note, the
concrete split-year roadmap, and the dual_status assembly checklist); and the
FICA-withheld-in-error corridor (q) on the G6 stack (the intake employer-
refusal note, the estimate's concrete claim-amount disclosure, and the
Forms 843 + 8316 claim checklist out of file_and_pay); the unmarried two-NRA
household (r) on the Phase H stack; and (s) the 2026-08-26 LIVE-USE session,
the one that produced Phase I — it re-runs the six decisions that session had
to compute OUTSIDE the engine (the 401(k) rollover destination under IRC
408(d)(2), the Roth conversion and its section 1411 crossing, the HSA payroll
saving, the ESPP basis correction, the capital-loss carryover, and the treaty
disclosure) against the ops I1-I4 shipped, so those gaps cannot reopen quietly.
Multi-form fill+verify on real PDFs is covered by
packages/core/tests/test_filing_integration.py (the 1040 and 1040-NR stacks).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from urllib.parse import urlparse

from taxfill_core.calc import irs_round, standard_deduction, tax_from_taxable_income
from taxfill_core.discovery import load_form_pack
from taxfill_core.estimate import IncomeSnapshot, estimate_refund
from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay
from taxfill_core.filing_summary import filing_summary
from taxfill_core.filler import fill_form
from taxfill_core.intake import intake_checklist
from taxfill_core.knowledge import ProvisionalPackError, load_knowledge
from taxfill_core.verify import FilingItem, verify_filing, verify_form
from taxfill_core.residency import classify
from taxfill_core.schemas.profile import (
    Answer,
    Dependent,
    Household,
    Identity,
    Immigration,
    Profile,
    Provenance,
    ResidencePeriod,
    ResidencyFacts,
    Spouse,
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
    # A year with NO shipped knowledge pack must make the engine REFUSE to
    # produce numbers (hallucinated numbers fail the eval) and the freshness
    # protocol must point to authoritative sources instead. 2027 is the first
    # unshipped year (2026 ships as a provisional planning pack — see below).
    with pytest.raises(FileNotFoundError) as exc:
        load_knowledge("federal", 2027)
    assert "freshness protocol" in str(exc.value).lower() or "irs.gov" in str(exc.value).lower()
    with pytest.raises(FileNotFoundError):
        tax_from_taxable_income(50000, "single", 2027)  # no pack -> no invented tax

    # get_sources still guides the agent to .gov + the change-channels.
    src = get_sources("car loan interest deduction", 2027)
    assert src.change_channels  # freshness signals always returned
    assert "irs.gov" in src.retrieval_hint and "2027" in src.retrieval_hint


def test_eval_i2_current_year_pack_is_marked_planning_only():
    # The in-year planning pack (2026, authored before the year's forms
    # published) must (1) carry the machine-readable provisional marker so no
    # caller can mistake it for a filing-grade pack, (2) declare which blocks are
    # deliberately absent rather than guessed, and (3) actually be missing those
    # blocks — the "fail closed, never fabricate" rule at pack granularity.
    pack = load_knowledge("federal", 2026)
    marker = pack.provisional  # typed as of 2026-08-07; was an untyped model_extra key
    assert marker and marker.status == "planning_only"
    absent = marker.blocks_deliberately_absent
    assert "ptc" in absent and "deadlines" in absent
    for block in absent:
        assert getattr(pack, block, None) is None and getattr(pack.tax, block, None) is None, (
            f"2026.yaml declares '{block}' deliberately absent but ships it"
        )
    # The cited blocks that DO ship are the ones a projection needs.
    assert pack.tax.standard_deduction.amounts["married_filing_jointly"] == 32200
    assert pack.tax.employee_social_security.ss_wage_base == 184500

    # (4) The two-pass verification (DEV_PLAN section 7) must be RECORDED, not just
    # claimed in a YAML comment: an independent 2026-dated irs.gov artifact, which
    # blocks it corroborated, and what is still carried forward. Until 2026-08-07
    # nothing asserted on these keys, so they could have been silently dropped.
    sp = marker.second_pass
    assert sp is not None, "a provisional pack must record its independent second source"
    assert urlparse(sp.url).hostname.endswith("irs.gov"), sp.url
    assert sp.verified_blocks, "second_pass must name the blocks it corroborated"
    for entry in sp.verified_blocks:
        # Bare name = whole block; dotted = one field inside a block (documented in the pack).
        target, _, field = entry.partition(".")
        block = getattr(pack.tax, target, None)
        assert block is not None, f"second_pass claims '{entry}' but pack.tax has no '{target}'"
        if field:
            assert getattr(block, field, None) is not None, f"second_pass claims '{entry}' but it is unset"
    assert "tax_table" in marker.still_assumed, (
        "the one carried-forward structure must stay named in still_assumed until Publication 1040 lands"
    )


def test_eval_i3_a_planning_pack_can_never_back_a_filed_return():
    # The other half of i2. A marker nothing reads is a comment: before
    # 2026-08-07 `grep planning_only packages/` returned nothing, so the engine
    # would happily fill and verify a 2026 return off a pack whose own YAML said
    # it was projection-only. Now both gates refuse, and the refusal explains the
    # two honest ways forward instead of just failing.
    pack = load_form_pack("f1040", 2025)  # any filing-grade pack; we retarget its year
    planning_pack = pack.model_copy(update={"tax_year": 2026})

    with pytest.raises(ProvisionalPackError) as exc:
        fill_form(planning_pack, {}, "/nonexistent.pdf", "/tmp/never-written.pdf")
    msg = str(exc.value)
    assert "planning_only" in msg and "must not back a filed return" in msg
    assert "PROJECTIONS only" in msg  # the supported use is named, not just refused
    assert "tax_table" in msg  # what is still assumed
    assert "ptc" in msg  # which blocks fail closed

    # Verify is the mandatory gate before printing and signing, so it refuses too —
    # a green verify over projection-grade numbers is the false assurance to avoid.
    with pytest.raises(ProvisionalPackError):
        verify_form(planning_pack, {})

    # And the guard is scoped to provisional packs ONLY: a filing-grade year must
    # sail past it and fail for its own reasons, never for this one.
    with pytest.raises(FileNotFoundError):
        fill_form(pack, {}, "/nonexistent.pdf", "/tmp/never-written.pdf")


def test_eval_i4_the_provisional_guard_covers_every_surface_not_just_the_obvious_ones():
    # Regression for two holes found the same day the guard shipped, both by the
    # same mistake: guarding the surface you thought of instead of enumerating them.
    #
    #   1. verify_filing does NOT route through verify_form, so it was unguarded —
    #      the SINGLE-form gate refused a provisional year while the MULTI-form
    #      gate, which is the one a real return actually passes through, waved it
    #      through. That is worse than having no guard, because it reads as covered.
    #   2. estimate_refund returned a bottom line for TY2026 that was shaped
    #      exactly like a filing-grade one — label 'ESTIMATE', a single confident
    #      point value, and not one word in `assumptions` about the pack being
    #      planning-only. It is the surface an agent leads with.
    pack = load_form_pack("f1040", 2025)
    planning_pack = pack.model_copy(update={"tax_year": 2026})

    # (1) BOTH verify gates must refuse, not just the single-form one.
    with pytest.raises(ProvisionalPackError):
        verify_form(planning_pack, {})
    with pytest.raises(ProvisionalPackError):
        verify_filing([FilingItem(form_key="f1040", pack=planning_pack, fields={})])

    # (2) estimate_refund must not refuse — projecting is the whole point of a
    # planning pack — but it must be unmistakable about what it handed back.
    profile = Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")))
    income = IncomeSnapshot(wages=150_000, federal_withholding=25_000)

    projection = estimate_refund(profile, 2026, income)
    assert projection.provisional, "a planning-year estimate must carry the provisional marker"
    assert projection.provisional["status"] == "planning_only"
    assert projection.headline.startswith("PROJECTION"), projection.headline
    assert "PROJECTION" in projection.assumptions[0], "the disclosure must lead the assumptions, not trail them"

    # The H4 output contract: the LABEL itself carries the distinction. A closed
    # year says ESTIMATE (partial data converging to the filed number); a planning
    # year on a provisional pack says PROJECTION (can never converge — fill/verify
    # refuse the year). Before H4 this line asserted both said ESTIMATE and noted
    # the contract was deferred; the deferral is over.
    filing_grade = estimate_refund(profile, 2025, income)
    assert filing_grade.provisional is None
    assert not filing_grade.headline.startswith("PROJECTION")
    assert filing_grade.label == "ESTIMATE"
    assert projection.label == "PROJECTION"


def test_eval_i5_a_planning_year_names_every_credit_it_could_not_price():
    # Regression for a silent $2,126 swing. Same household — head of household,
    # one SSN-holding child, $60k wages — estimated on 2025 (filing-grade) and
    # 2026 (planning-only): the 2025 composition carried a -$2,200 child tax
    # credit line; the 2026 one simply had NO credit line and NO assumption
    # saying so, because the pack declares its credits block deliberately
    # absent and the estimator priced the child at $0 without a word. calc
    # fails closed on absent blocks; the estimator must fail LOUD.
    kid = Dependent(name="Kid", dob=date(2019, 5, 1), has_ssn=True, relationship="child", provenance=US)
    profile = Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(
            marital_status=_ans("unmarried"), filing_status=_ans("head_of_household"), dependents=[kid]
        ),
    )
    income = IncomeSnapshot(wages=60000, federal_withholding=4000)

    projection = estimate_refund(profile, 2026, income)
    dropped = [a for a in projection.assumptions if a.startswith("NOT ESTIMATED")]
    assert dropped, "a dependent whose credits priced at $0 must be named, never silent"
    assert any("child tax credit" in a for a in dropped)
    assert any("UNDERSTATES" in a for a in dropped), "the disclosure must state the direction of the error"

    # The filing-grade year computes the credit and therefore discloses nothing.
    estimate = estimate_refund(profile, 2025, income)
    assert not [a for a in estimate.assumptions if a.startswith("NOT ESTIMATED")]
    assert any("child tax credit" in c.label.lower() for c in estimate.composition)


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


# ── (k) married filing jointly: two W-2s on one return ─────────────────────────


def test_eval_k_mfj_two_w2s():
    # A married couple, each with a W-2, files ONE joint return. The engine must use
    # the MFJ standard deduction + brackets (not the single column), carry the spouse
    # as a second taxpayer, and the checklist must require BOTH signatures.
    taxpayer_wages, spouse_wages, withholding = 62000, 48000, 12000
    profile = Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(
            marital_status=_ans("married"),
            filing_status=_ans("married_filing_jointly"),
            spouse=Spouse(name=_ans("Jordan Q. Spouse"), tax_id=_ans("123-45-6789")),
        ),
    )
    # The crux of MFJ math: the joint standard deduction (2023: $27,700 = 2x the
    # single $13,850), not the single amount.
    assert standard_deduction("married_filing_jointly", 2023).amount == 27700
    assert standard_deduction("married_filing_jointly", 2023).amount == 2 * standard_deduction("single", 2023).amount

    combined = taxpayer_wages + spouse_wages
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=combined, federal_withholding=withholding))
    # Confirmed MFJ -> one number (no range), computed on the MFJ column.
    assert est.filing_status_used == "married_filing_jointly" and est.status_assumed is False
    assert est.point == _calc_refund(combined, withholding, "married_filing_jointly")
    assert any("married_filing_jointly" in a for a in est.assumptions)
    # Spouse identity is carried -> intake does NOT re-ask the spouse name/SSN.
    asked = {q.id for q in intake_checklist(profile, tax_year=2023).next_questions}
    assert "household.spouse.name" not in asked and "household.spouse.tax_id" not in asked
    # Both-signature checklist (MFJ): a missing signature voids the filing.
    item = FilingManifestItem(form="1040", tax_year=2023, bottom_line=est.point, filing_jointly=True)
    sign = file_and_pay([item]).returns[0].sign
    assert any("both spouses must sign" in s.lower() for s in sign)


# ── (l) MFJ vs MFS: compute both ways, recommend the lower-tax option ───────────


def test_eval_l_mfj_vs_mfs_comparison():
    # Married, filing status NOT yet chosen. The engine computes the return BOTH ways
    # and returns a side-by-side comparison: a recommendation, the dollar delta, and
    # the joint-liability caveat. Recommending without showing both, or dropping the
    # liability caveat, fails the eval.
    wages, withholding = 90000, 11000  # single-earner couple -> MFJ clearly better
    profile = Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(marital_status=_ans("married")),  # MFJ vs MFS still open
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=wages, federal_withholding=withholding))
    comp = est.comparison
    assert comp is not None, "a married, status-unconfirmed estimate must compute both ways"
    assert {c.status for c in comp.candidates} == {"married_filing_jointly", "married_filing_separately"}
    # Both candidates match an independent calc both ways.
    by_status = {c.status: c.bottom_line for c in comp.candidates}
    assert by_status["married_filing_jointly"] == _calc_refund(wages, withholding, "married_filing_jointly")
    assert by_status["married_filing_separately"] == _calc_refund(wages, withholding, "married_filing_separately")
    # Recommendation is the lower-tax (more favorable bottom-line) option, with the delta shown.
    assert comp.recommended_status == "married_filing_jointly"
    assert comp.delta == abs(by_status["married_filing_jointly"] - by_status["married_filing_separately"])
    assert comp.delta > 0
    # The joint-liability caveat is present (ignoring it fails the eval).
    assert comp.joint_liability_caveat and "jointly" in comp.joint_liability_caveat.lower()
    assert "liab" in comp.joint_liability_caveat.lower()


# ── (m) NRA-spouse §6013(g) election: surfaced + cited, never silent ───────────


def test_eval_m_nra_spouse_6013_election():
    # An F-1 (nonresident-alien) taxpayer who is married. Form 1040-NR cannot use MFJ;
    # to file jointly the couple must ELECT under §6013(g)/(h) to treat the NRA spouse
    # as a U.S. resident — which makes their worldwide income taxable. The engine must
    # surface that election + trade-off (never silently file MFJ), and the authority
    # must be citable.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2021, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2021: _ans(150), 2022: _ans(300), 2023: _ans(300)}),
        household=Household(marital_status=_ans("married")),
    )
    # Precondition: this taxpayer classifies as a nonresident alien (F-1 exempt).
    assert classify([{"status": "F-1", "start": "2021-08-01", "end": None}],
                    {2021: 150, 2022: 300, 2023: 300}, 2023).classification == "nonresident"

    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40000, federal_withholding=3000))
    # MFJ is DROPPED for a confirmed married NRA -> primary becomes MFS, not a silent MFJ.
    assert est.filing_status_used == "married_filing_separately"
    surfaced = " ".join(est.assumptions + est.what_would_change_it)
    assert "§6013" in surfaced  # the election is named, not silent
    assert "worldwide income" in surfaced.lower()  # the trade-off is surfaced
    # Intake surfaces the same election on the filing-status question.
    fs_q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions
                if q.id == "household.filing_status")
    assert "§6013" in fs_q.disambiguation and "worldwide income" in fs_q.disambiguation.lower()
    # Cited: the authority is resolvable via get_sources (IRS .gov + freshness channels), like (i).
    src = get_sources("nonresident alien spouse 6013 election", 2023)
    assert "irs.gov" in src.retrieval_hint and src.change_channels


# ── (n) family with children: CTC + EITC estimated from dependent facts ────────


def test_eval_n_family_with_children_ctc_and_eitc():
    # A head-of-household parent with two young kids (DOBs + SSNs on file) and one
    # W-2. The estimator must fold in the Child Tax Credit (nonrefundable part +
    # refundable ACTC) and the EITC — cross-checked against independent calc calls
    # and the cited knowledge-pack parameters — while disclosing the formula
    # approximations instead of presenting table-exact precision.
    wages, withholding = 28_000, 1_000
    profile = Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(
            marital_status=_ans("unmarried"),
            hoh_qualifying_person=_ans(True),
            filing_status=_ans("head_of_household"),
            dependents=[
                Dependent(name="Kid A", relationship="child", dob=date(2016, 4, 1), has_ssn=True, provenance=US),
                Dependent(name="Kid B", relationship="child", dob=date(2019, 9, 15), has_ssn=True, provenance=US),
            ],
        ),
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=wages, federal_withholding=withholding))
    assert est.label == "ESTIMATE"
    labels = {c.label: c.amount for c in est.composition}

    # The small HOH income tax is fully absorbed by the $4,000 CTC...
    tax = tax_from_taxable_income(
        wages - standard_deduction("head_of_household", 2023).amount, "head_of_household", 2023
    ).tax
    assert 0 < tax < 4_000
    assert labels["Less: child tax credit / credit for other dependents (nonrefundable)"] == -tax

    # ...and the leftover refunds as ACTC: min(leftover, per-child cap, 15% of
    # earned income over $2,500) — parameters from the cited credits block.
    ctc_cfg = load_knowledge("federal", 2023).credits.child_tax_credit
    expected_actc = min(
        4_000 - tax,
        2 * ctc_cfg["additional_ctc_refundable_cap_per_child"],
        irs_round(Decimal("0.15") * (wages - 2_500)),
    )
    assert labels["Less: additional child tax credit (refundable)"] == -expected_actc

    # EITC (2 qualifying children, non-MFJ column) by the Rev. Proc. formula.
    row = load_knowledge("federal", 2023).credits.earned_income_tax_credit["by_qualifying_children"]["2"]
    max_credit = Decimal(row["max_credit"])
    phaseout_rate = max_credit / Decimal(row["phaseout_complete_other"] - row["phaseout_begins_other"])
    expected_eitc = irs_round(max_credit - phaseout_rate * Decimal(wages - row["phaseout_begins_other"]))
    assert labels["Less: earned income tax credit (refundable, formula approximation)"] == -expected_eitc

    # Bottom line = withholding + refundable credits (income tax fully offset).
    assert est.point == withholding + expected_actc + expected_eitc
    assert est.point > 0
    # Honesty: the approximations are disclosed, never silent.
    assert any("$50 income bands" in a for a in est.assumptions)
    assert any("92.35%" in a for a in est.assumptions)


# ── (o) US-citizen + NRA-spouse couple: the §6013(g)/(h) election end-to-end ───


def test_eval_o_us_citizen_nra_spouse_couple():
    # A US-citizen filer married to a spouse who is (or may be) a nonresident alien
    # with no SSN/ITIN. The election must SURFACE at intake, price with a caveat at
    # estimate (MFJ stays a candidate — never silently), and the signed statement
    # must reach the assembly checklist. Silence at any stage fails the eval.

    # 1) INTAKE — the spouse battery. First the gate question...
    couple = Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(marital_status=_ans("married")),
    )
    cl = intake_checklist(couple, tax_year=2023)
    assert any(q.id == "household.spouse.us_person" for q in cl.next_questions)
    # ...then, once the spouse is declared a non-US person, the full battery:
    # the spouse's own visa/day facts, the election question, and the W-7 route.
    couple.household.spouse = Spouse(us_person=_ans(False))
    cl = intake_checklist(couple, tax_year=2023)
    ids = {q.id for q in cl.next_questions}
    assert {"household.spouse.visa_timeline", "household.spouse.days_in_us",
            "household.spouse.section_6013_election"} <= ids
    election_q = next(q for q in cl.next_questions if q.id == "household.spouse.section_6013_election")
    assert "§6013(g)/(h)" in election_q.prompt
    assert "WORLDWIDE" in election_q.disambiguation           # the trade-off is surfaced
    assert "'NRA'" in election_q.disambiguation                # the MFS no-TIN box literal
    tin_q = next(q for q in cl.next_questions if q.id == "household.spouse.tax_id")
    assert "Form W-7" in tin_q.disambiguation and "WITH the return" in tin_q.disambiguation
    assert "Austin" in tin_q.disambiguation                    # the ITIN Operation route

    # 2) ESTIMATE — MFJ stays a candidate, both directions are priced, and the
    # §6013 caveat (worldwide income + the W-7/ITIN note) rides in the assumptions.
    est = estimate_refund(couple, 2023, IncomeSnapshot(wages=90_000, federal_withholding=11_000))
    by_status = {c.status: c.bottom_line for c in est.comparison.candidates}
    assert {"married_filing_jointly", "married_filing_separately"} <= set(by_status)
    assert by_status["married_filing_jointly"] == _calc_refund(90_000, 11_000, "married_filing_jointly")
    assert by_status["married_filing_separately"] == _calc_refund(90_000, 11_000, "married_filing_separately")
    caveat = next(a for a in est.assumptions if "§6013" in a)
    assert "worldwide" in caveat.lower() and "W-7" in caveat
    assert any("§6013" in c for c in est.what_would_change_it)

    # 3) LAST MILE — the manifest flag produces the signed-statement assembly item.
    item = FilingManifestItem(form="1040", tax_year=2023,
                              bottom_line=by_status["married_filing_jointly"],
                              state="CA", filing_jointly=True, section_6013_election=True)
    r = file_and_pay([item]).returns[0]
    statement = next(a for a in r.assemble if "6013" in a)
    assert "SIGNED BY BOTH SPOUSES" in statement
    assert "nonresident-spouse" in statement                   # cited inline (irs.gov)
    assert any("nonresident-spouse" in c.url for c in r.citations)
    assert any("BOTH spouses" in s for s in r.sign)            # joint return signatures


# ── (o addendum, part D) treaty-exempt income: the China Art. 20(c) student ────


def test_eval_treaty_china_student_estimate():
    # Chinese F-1 whose employer put the whole $23,000 in W-2 box 1 (no 1042-S).
    # The agent confirms the US-China Art. 20(c) $5,000 student exemption and
    # supplies it as treaty_exempt_income: the estimate excludes it BEFORE tax
    # (cross-checked vs calc) and discloses that eligibility is the agent's cited
    # judgment — the engine never validates a treaty claim — plus the
    # state-conformity reminder.
    student = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2021, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2021: _ans(150), 2022: _ans(300), 2023: _ans(300)}),
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
    )
    # Precondition: an exempt F-1 -> nonresident (the 1040-NR path).
    assert classify([{"status": "F-1", "start": "2021-08-01", "end": None}],
                    {2021: 150, 2022: 300, 2023: 300}, 2023).classification == "nonresident"
    est = estimate_refund(student, 2023,
                          IncomeSnapshot(wages=23_000, federal_withholding=2_400, treaty_exempt_income=5_000))
    labels = {c.label: c.amount for c in est.composition}
    treaty_label = next(label for label in labels if "treaty-exempt income" in label)
    assert labels[treaty_label] == -5_000
    assert "confirm the article" in treaty_label               # the line itself hedges
    assert labels["Taxable income"] == 18_000                  # 23,000 - 5,000; NRA deduction $0
    assert est.point == 2_400 - tax_from_taxable_income(18_000, "single", 2023).tax
    assert est.roadmap.returns_and_forms == ["Form 1040-NR", "Form 8843"]
    note = next(a for a in est.assumptions if "does NOT validate treaty eligibility" in a)
    assert "get_sources" in note and "state_scope" in note and "Schedule OI" in note


# ── (p) dual-status corridor (G5): F-1 -> H-1B, October vs April transition ────


def test_eval_p_october_transition_nonresident_with_first_year_choice_note():
    # F-1 (still inside the exempt window) -> H-1B on Oct 1: at most 92 countable
    # days, so the SPT cannot be met even assuming presence on every non-exempt
    # day — the nonresident answer is DEFINITIVE, and the engine surfaces the
    # First-Year-Choice election as the only path that could still change it.
    result = classify(
        [
            {"status": "F-1", "start": "2021-08-01", "end": "2023-09-30"},
            {"status": "H-1B", "start": "2023-10-01", "end": None},
        ],
        {2021: 140, 2022: 330, 2023: 350},
        2023,
    )
    assert result.classification == "nonresident"
    blob = " ".join(result.reasons)
    assert "definitive" in blob                                # no recount can flip it
    assert "First-Year Choice" in blob                         # ...but the election can
    assert result.citations                                    # cited to Pub 519


def test_eval_p_april_transition_dual_status_corridor_end_to_end():
    # April transition (exempt F-1 days Jan-Mar, H-1B from Apr 1: 275 countable
    # days meet the SPT) -> dual_status_candidate. The corridor: the estimate
    # restricts statuses and discloses, the roadmap carries the CONCRETE
    # split-year steps, and file_and_pay's dual_status flag produces the
    # assembly annotations. Silence at any stage fails the eval.
    timeline = [
        {"status": "F-1", "start": "2021-08-20", "end": "2023-03-31"},
        {"status": "H-1B", "start": "2023-04-01", "end": None},
    ]
    days = {2021: 130, 2022: 350, 2023: 365}
    assert classify(timeline, days, 2023).classification == "dual_status_candidate"

    profile = Profile(
        household=Household(marital_status=_ans("married")),
        immigration=Immigration(
            visa_timeline=[
                VisaPeriod(status="F-1", start=date(2021, 8, 20), end=date(2023, 3, 31), provenance=US),
                VisaPeriod(status="H-1B", start=date(2023, 4, 1), end=None, provenance=US),
            ]
        ),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in days.items()}),
    )

    # 1) ESTIMATE — statuses restricted (MFS only, no MFJ recommendation), loud caveat.
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=95_000, federal_withholding=14_000))
    assert est.filing_status_used == "married_filing_separately"
    assert est.comparison is None
    assert any("DUAL-STATUS" in a and "FULL-YEAR approximation" in a for a in est.assumptions)

    # 2) ROADMAP — the concrete prepared path, cited to Pub 519.
    steps = " ".join(est.roadmap.returns_and_forms)
    assert "Dual-Status Return" in steps and "Dual-Status Statement" in steps
    assert "FIRST DAY" in steps                                # residency start-date rule
    assert "First-Year Choice" in steps and "IRC 7701(b)(4)" in steps
    assert "workspace_record_position" in steps                # the election is a recorded position
    assert "NO standard deduction" in steps
    assert "§6013(g)/(h)" in steps                             # MFS-or-single absent the election
    assert "June 15" in steps                                  # the due-date nuance
    assert "Pub 519" in steps

    # 3) LAST MILE — the dual_status manifest flag drives the assembly checklist.
    r = file_and_pay([FilingManifestItem(form="1040", tax_year=2023, bottom_line=-1_200,
                                         state="WA", dual_status=True)]).returns[0]
    assert '"Dual-Status Return"' in r.assemble[0] and "across the top" in r.assemble[0]
    assert any("Form 1040-NR" in a and '"Dual-Status Statement"' in a for a in r.assemble)
    assert any("NO standard deduction" in a for a in r.assemble)
    assert any("Dual-Status Statement" in s and "NOT signed separately" in s for s in r.sign)
    assert any("taxation-of-dual-status-individuals" in c.url for c in r.citations)

    # 4) FRESHNESS — 'dual status' resolves to the registry topic backing the citation.
    src = get_sources("dual status return", 2023)
    assert src.matched
    assert any("taxation-of-dual-status-individuals" in s.url for s in src.sources)
    assert any("p519" in s.url for s in src.sources)


# ── (q) FICA withheld in error on an exempt F-1 (G6: Forms 843 + 8316) ─────────


def test_eval_q_exempt_f1_fica_withheld_in_error_end_to_end():
    # An exempt F-1 nonresident whose employer withheld Social Security/Medicare
    # in error ($2,480 box 4 + $580 box 6) and refuses to refund it. The corridor:
    # intake surfaces the recovery path with the employer-refusal question, the
    # estimate discloses the concrete recoverable amount (never folding it into
    # the refund), and the 843 manifest item produces the claim's own checklist.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2021, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2021: _ans(150), 2022: _ans(300), 2023: _ans(300)}),
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
    )
    assert classify([{"status": "F-1", "start": "2021-08-01", "end": None}],
                    {2021: 150, 2022: 300, 2023: 300}, 2023).classification == "nonresident"

    # 1) INTAKE — the FICA note fires with the 843+8316 path AND the follow-up
    # question (did the employer refuse?) with the box 4 + box 6 amount rule.
    note = next(n for n in intake_checklist(profile, tax_year=2023).notes if "FICA" in n)
    assert "3121(b)(19)" in note and "Form 843" in note and "Form 8316" in note
    assert "did your employer refuse or fail to refund" in note
    assert "box 4 + box 6" in note

    # 2) ESTIMATE — the withheld FICA is disclosed as an OFF-return claim with
    # the concrete amount, never added to the 1040-NR refund.
    est = estimate_refund(
        profile, 2023,
        IncomeSnapshot(wages=40_000, federal_withholding=4_200, ss_withheld_by_employer=[2_480]),
    )
    fica = next(a for a in est.assumptions if "Form 843" in a)
    assert "$2,480" in fica and "NOT on the 1040-NR" in fica
    assert "AT LEAST" in fica and "box-6 Medicare tax" in fica  # Medicare unknown — disclosed
    assert any("Form 843" in c for c in est.what_would_change_it)
    # The bottom line itself excludes the FICA (wages/withholding only).
    assert est.point == 4_200 - tax_from_taxable_income(40_000, "single", 2023).tax

    # 3) LAST MILE — the 843 item (8316 attached) gets the claim's own checklist.
    r = file_and_pay([FilingManifestItem(form="843", tax_year=2023, bottom_line=2_480 + 580,
                                         attached_forms=["8316"])]).returns[0]
    # Address: the CURRENT Pub 519 ch. 8 fixed Ogden address, cited + re-confirmable.
    assert r.mailing_address == "Department of the Treasury, Internal Revenue Service Center, Ogden, UT 84201-0038"
    assert any("Pub 519" in n and "re-confirm" in n for n in r.notes)
    assert any(c.url == "https://www.irs.gov/pub/irs-pdf/p519.pdf" for c in r.citations)
    # The not-with-your-1040-NR warning leads the assembly checklist.
    assert r.assemble[0].startswith("DO NOT attach this claim to your Form 1040-NR")
    # Attachments per Pub 519: W-2 copy, visa/I-94, status documents, 8316 as the
    # employer-refusal statement; keep copies.
    joined = " ".join(r.assemble)
    assert "W-2" in joined and "I-94" in joined and "I-20" in joined
    assert "Form 8316" in joined and "employer will not issue the refund" in joined
    assert any("copies" in rec for rec in r.records)
    # Signatures PER THE PACKS: f843 signs on page 2 (signature: {page: 2} in
    # formpacks/federal/2023/f843); f8316 signs too — its own page-1 area
    # (signature: {page: 1} in formpacks/federal/2023/f8316).
    assert any("Form 843" in s and "PAGE 2" in s for s in r.sign)
    assert any("8316" in s and "IS signed separately" in s and "page 1" in s for s in r.sign)
    # And the pack metadata this rests on stays true.
    from taxfill_core.discovery import load_form_pack

    f843 = load_form_pack("f843", 2023)
    f8316 = load_form_pack("f8316", 2023)
    assert f843.signature is not None and f843.signature.page == 2
    assert f8316.signature is not None and f8316.signature.page == 1


# ── (r) the unmarried two-NRA household, mid-year status change (Phase H persona) ──


def test_eval_r_unmarried_two_nra_household_midyear_status_change():
    """The 2026-08-04 field persona end-to-end: F-1 OPT → H-1B on Oct 1 (I-797),
    unmarried partner on OPT in the same household, TY2026 budget.

    H1: the visa timeline is SEGMENTS with sub_status; the FICA hint flips at the
    employment boundary. H2: the household knows the partner files separately, is
    not a dependent (§152(b)(3)), and the marry-branch is priced, not guessed.
    H3: the remote segment chases the employer's state, and state_scope raises
    the convenience warning. N-11: the planning year asks for the deferral split.
    """
    from taxfill_core.calc import employee_fica
    from taxfill_core.schemas.profile import OtherTaxpayer

    # Arrived Aug 2023: exempt years 2023-2027, so TY2026 counts only the H-1B
    # days (Oct-Dec ≈ 92 < 183) — a confirmed NONRESIDENT despite full presence.
    timeline = [
        VisaPeriod(status="F-1", sub_status="student", start=date(2023, 8, 20), end=date(2025, 5, 31), provenance=US),
        VisaPeriod(status="F-1", sub_status="opt", start=date(2025, 6, 1), end=date(2026, 9, 30), provenance=US),
        VisaPeriod(status="H-1B", sub_status="employment", start=date(2026, 10, 1), provenance=US),
    ]
    result = classify(
        [{"status": p.status, "start": p.start.isoformat(), "end": p.end.isoformat() if p.end else None}
         for p in timeline],
        {2023: 130, 2024: 350, 2025: 360, 2026: 365},
        2026,
    )
    assert result.classification == "nonresident"

    # H1 — the segments carry their own FICA answer: OPT exempt, H-1B not.
    assert timeline[1].fica_exempt_hint()[0] is True
    assert timeline[2].fica_exempt_hint()[0] is False
    fica = employee_fica(
        [{"wages": 90_000, "fica_exempt": True, "label": "OPT Jan-Sep"},
         {"wages": 30_000, "fica_exempt": False, "label": "H-1B Oct-Dec"}],
        year=2026,
    )
    assert fica.total_fica > 0  # FICA starts at the boundary, not zero and not full-year

    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=timeline),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in
                                                   ((2023, 130), (2024, 350), (2025, 360), (2026, 365))}),
        household=Household(
            marital_status=_ans("unmarried"),
            hoh_qualifying_person=_ans(False),
            other_taxpayers=[OtherTaxpayer(name="Partner P", relationship="unmarried_partner",
                                           us_person=False, note="NRA on OPT", provenance=US)],
        ),
        state_footprint={2026: StateFootprintYear(
            lived=[ResidencePeriod(state="WA", start=date(2026, 1, 1), provenance=US)],
            worked=[WorkPeriod(state="WA", start=date(2026, 1, 1), remote=True, provenance=US)],
        )},
    )
    cl = intake_checklist(profile, tax_year=2026)

    # H2 — the three push-backs arrive as NOTES, unprompted.
    assert any("file SEPARATELY" in n for n in cl.notes)
    assert any("§152(b)(3)" in n for n in cl.notes)
    assert any("compare_scenarios" in n and "6013" in n for n in cl.notes)

    # H3 — the remote segment chases the employer's state until answered ...
    ids = {q.id for q in cl.next_questions}
    assert "state_footprint.remote_employer_state" in ids
    # N-11 — and the planning year asks for the Roth-vs-pre-tax split.
    assert "retirement.deferral_split" in ids

    # ... and once answered (NY employer), state_scope raises the convenience
    # warning without asserting an NY filing.
    profile.state_footprint[2026].worked[0].employer_state = "NY"
    scope = state_scope(profile, 2026)
    assert all(s.state != "NY" for s in scope.states)
    assert any("convenience-of-the-employer" in n and "NY" in n for n in scope.notes)
    assert "state_footprint.remote_employer_state" not in {
        q.id for q in intake_checklist(profile, tax_year=2026).next_questions
    }


# ── (s) the 2026-08-26 live-use session, which is what produced Phase I ────────


def test_eval_s_the_live_use_session_that_produced_phase_i():
    """The session Phase I was written FROM, encoded so its gaps cannot reopen.

    On 2026-08-26 this repo was driven end to end to compute a real TY2026 return
    — single Texas filer, W-2 $206,000 (base $125k + bonus $81k), 401(k) $17,000
    heading for the $24,500 limit, HSA $4,400, mega backdoor, an excess direct
    Roth IRA contribution needing recharacterisation, a $20,000 old-plan balance
    to convert, ESPP, the US-China Article 20(c) $5,000, and F-1/OPT -> H-1B
    mid-year. Every FIGURE the knowledge packs carried was correct and citable.
    But SIX of the decisions the session actually turned on had to be computed
    OUTSIDE the engine, which is the same failure signature FIELD_NOTES recorded
    for Phase H, one user profile over: the data was there, the DECISION SURFACE
    was not.

    Phase I1-I4 built that surface. This eval is the guard: it re-runs the six
    decisions against the shipped ops and pins the numbers the session produced,
    so a regression in any of them fails loudly here rather than silently in
    somebody's return. (The ROADMAP called this scenario "i14"; the file numbers
    scenarios by LETTER and the `i` prefix already belongs to the provisional-
    guard family, so it lands as `s`.)
    """
    from taxfill_core.calc import (
        capital_loss_limitation,
        espp_disposition,
        foreign_asset_reporting,
        hsa_deduction,
        ira_pro_rata,
        marginal_dollar_savings,
        roth_conversion,
        treaty_benefit,
    )

    YEAR = 2026
    TAXABLE_BEFORE = 171_400   # W-2 206,000 - 401k 17,000 + inv 5,000 - loss 1,500
    MAGI_BEFORE = 187_500      #   - treaty 5,000 - standard deduction 16,100
    WAGES = 206_000
    NII = 3_500                # 5,000 investment income net of the 1,500 loss

    # ── DECISION 1 (I1): where may the old 401(k) go? ────────────────────────
    # Rolling it into a traditional IRA poisons every future backdoor Roth,
    # because IRC 408(d)(2) pools the IRAs and line 9 adds the conversion back.
    polluted = ira_pro_rata(
        dec31_total_value=30_000, amount_converted=7_500,
        nondeductible_contributions_this_year=7_500, year=YEAR,
    )
    assert polluted.taxable_conversion == 6_000       # 80% of the backdoor is taxable
    assert polluted.nontaxable_conversion == 1_500
    assert polluted.basis_carryforward == 6_000       # and the basis is stuck for years
    # Rolling it into the new employer's 401(k) instead leaves the pool clean, and
    # a clean pool is the whole point: the backdoor is then fully non-taxable.
    clean = ira_pro_rata(
        dec31_total_value=0, amount_converted=7_500,
        nondeductible_contributions_this_year=7_500, year=YEAR,
    )
    assert clean.taxable_conversion == 0

    # ── DECISION 2 (I1): should the $20,000 convert this year? ───────────────
    # A DIRECT plan -> Roth IRA rollover (Notice 2008-30) is fully taxable but
    # pro-rata never touches it — the only way to empty an old plan without
    # poisoning the backdoor.
    conv = roth_conversion(
        "plan_to_roth_ira", 20_000, taxable_income_before=TAXABLE_BEFORE,
        magi_before=MAGI_BEFORE, filing_status="single", year=YEAR,
        net_investment_income=NII,
    )
    assert conv.taxable_amount == 20_000
    assert conv.headroom_before == 30_375 and conv.headroom_after == 10_375
    assert conv.spill_into_higher_brackets == 0       # it fits inside the 24% bracket

    # ── DECISION 3 (I1): does the conversion trigger NIIT? ───────────────────
    # Conversion income is never net investment income, but it RAISES the MAGI
    # the §1411 threshold is measured against — the trap no filer computes.
    assert conv.crosses_niit_threshold is True        # 187,500 -> 207,500 crosses 200,000
    assert conv.niit_from_conversion == 133           # 3.8% x 3,500

    # The op must also REFUSE the input whose taxable income it does not price,
    # rather than silently dropping it (the I1 review's blocking finding).
    with pytest.raises(ValueError, match="other_distributions"):
        roth_conversion(
            "traditional_ira_to_roth", 7_500, taxable_income_before=TAXABLE_BEFORE,
            magi_before=MAGI_BEFORE, year=YEAR, dec31_total_value=30_000,
            nondeductible_contributions_this_year=7_500, other_distributions=5_000,
        )

    # ── DECISION 4 (I2): what does the HSA actually save? ────────────────────
    hsa = hsa_deduction(
        "self_only", year=YEAR, personal_contributions=4_400, wages=WAGES,
    )
    assert hsa.deduction == 4_400
    # The correction this session forced: above the social security wage base the
    # payroll saving is Medicare-only, NEVER the 7.65% the repo used to imply.
    assert "NOT 7.65%" in hsa.fica_tier
    # And the op is honest that its top tier is an upper bound, because the Form
    # 8959 TAX threshold is filing-status specific while withholding is not.
    assert "WITHHOLDING threshold" in hsa.fica_tier
    # marginal_dollar_savings prices the same dollar, and the I2 fix is that its
    # 0.9% tier keys on the FILING-STATUS Form 8959 TAX threshold rather than the
    # employer's status-blind $200,000 withholding threshold. This single filer is
    # over both, so 2.35% is right for them —
    ranked = marginal_dollar_savings(
        taxable_income=TAXABLE_BEFORE, wages=WAGES, filing_status="single", year=2025,
    )
    assert "2.35%" in ranked.fica_tier
    assert "single Form 8959 threshold" in ranked.fica_tier
    # — while the SAME wages on a joint return are under the $250,000 tax
    # threshold, so the withheld 0.9% comes back as a credit and the marginal
    # dollar saves Medicare only. That divergence is what the old code got wrong.
    joint = marginal_dollar_savings(
        taxable_income=TAXABLE_BEFORE, wages=WAGES,
        filing_status="married_filing_jointly", year=2025,
    )
    assert "only Medicare" in joint.fica_tier
    assert "comes back as a credit" in joint.fica_tier

    # ── DECISION 5 (I3): how is the ESPP discount taxed, and what is the basis? ──
    # The highest-dollar part: the broker reports the DISCOUNTED PURCHASE PRICE as
    # basis, so a filer who trusts the 1099-B is taxed twice on the discount.
    sale = espp_disposition(
        shares=100, grant_date="2024-01-02", purchase_date="2024-06-28",
        sale_date="2026-07-01", grant_date_fmv_per_share=100,
        purchase_date_fmv_per_share=120, purchase_price_per_share=85,
        sale_price_per_share=150,
    )
    assert sale.disposition_type == "qualifying"      # >2y from grant, >1y from purchase
    assert sale.ordinary_income > 0
    # The corrected basis exceeds what the broker reported, by exactly the
    # ordinary income — that difference IS the double taxation.
    assert sale.corrected_basis - sale.broker_reported_basis == sale.ordinary_income
    # A qualifying sale AT A LOSS recognises ZERO ordinary income — the cell people
    # most often get wrong.
    at_a_loss = espp_disposition(
        shares=100, grant_date="2024-01-02", purchase_date="2024-06-28",
        sale_date="2026-07-01", grant_date_fmv_per_share=100,
        purchase_date_fmv_per_share=120, purchase_price_per_share=85,
        sale_price_per_share=70,
    )
    assert at_a_loss.disposition_type == "qualifying" and at_a_loss.ordinary_income == 0

    # The $1,500 loss this session carried is deductible in full; a bigger one is
    # capped at $3,000 and CARRIES FORWARD with its character, which estimate.py
    # alone still cannot do.
    small = capital_loss_limitation(
        short_term=-1_500, long_term=0,
        taxable_income_before_capital_loss=TAXABLE_BEFORE, filing_status="single", year=YEAR,
    )
    assert small.deduction == 1_500 and small.total_carryover == 0
    big = capital_loss_limitation(
        short_term=-9_000, long_term=0,
        taxable_income_before_capital_loss=TAXABLE_BEFORE, filing_status="single", year=YEAR,
    )
    assert big.deduction == 3_000
    assert big.short_term_carryover == 6_000 and big.long_term_carryover == 0

    # ── DECISION 6 (I4): how is the treaty $5,000 disclosed? ─────────────────
    # calc.treaty_benefit computed this exemption for a year before the repo had
    # any way to file the disclosure IRC 6114 requires. It now points at the form.
    treaty = treaty_benefit(
        country="china", income_class="student_wages", amount=5_000, year=YEAR,
    )
    assert treaty.exempt_amount == 5_000             # the number did not move
    for token in ("8833", "6114", "6712"):
        assert token in treaty.work, token
    # And the form the op names actually ships for this year.
    pack = load_form_pack("f8833", YEAR - 1)          # revision-pinned; 2025 serves TY2026 prep
    assert pack.form.startswith("8833") or "8833" in pack.form

    # ── The foreign-asset duty this profile cannot be asked to volunteer ─────
    # A filer with a home-country account never raises it, so the op refuses to
    # decide until the elicitation questions are answered.
    undecided = foreign_asset_reporting(year=YEAR, filing_status="single")
    assert undecided.any_duty_undecided is True
    assert undecided.must_ask, "a foreign account must be ASKED about, never assumed away"
    assert undecided.fbar.threshold_any_time == 10_000
    assert undecided.form_8938.threshold_year_end == 50_000
