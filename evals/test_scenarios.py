"""End-to-end eval scenarios — dev plan section 14.

Synthetic taxpayers (no real PII) run through the engine, asserting the
behaviours the dev plan calls out per scenario letter. These are integration
EVALS, not unit tests: they prove the M1-M4 stack does the right thing on
realistic cases, including the honest-estimate and no-invented-numbers rules.

All fifteen scenarios (a–o) run now: the federal cases (a, d, e, g, h, i, j) on
the M1-M4 stack; the joint / separate / NRA-spouse cases (k, l, m) on the
filing-status-aware engine (MFJ math, the both-ways comparison, and the §6013(g)/(h)
election surface); the state cases (b, c, f) on M5 (CA packs + state_scope);
the family-with-children case (n) on the Phase F credit-aware estimator (CTC/ACTC
+ EITC from dependents' DOB/SSN facts); and the US-citizen + NRA-spouse couple (o)
on the Tier-2 spouse-residency battery (intake election questions, the MFJ-with-
caveat estimate, and the signed election-statement assembly item), plus the
treaty-exempt-income (China Art. 20(c) student) estimator surface.
Multi-form fill+verify on real PDFs is covered by
packages/core/tests/test_filing_integration.py (the 1040 and 1040-NR stacks).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from taxfill_core.calc import irs_round, standard_deduction, tax_from_taxable_income
from taxfill_core.estimate import IncomeSnapshot, estimate_refund
from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay
from taxfill_core.filing_summary import filing_summary
from taxfill_core.intake import intake_checklist
from taxfill_core.knowledge import load_knowledge
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
