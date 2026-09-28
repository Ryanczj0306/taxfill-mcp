"""estimate_refund tests (dev plan sections 2/12, eval (j)). All data synthetic.

The estimate must only orchestrate calc, so each numeric assertion is checked
against an independent calc call — never a hand-computed magic number.
"""

from datetime import date

import pytest

from taxfill_core.calc import standard_deduction, tax_from_taxable_income
from taxfill_core.estimate import IncomeSnapshot, RefundEstimate, estimate_refund
from taxfill_core.schemas.profile import (
    Answer,
    Dependent,
    Household,
    Identity,
    Immigration,
    IncomeDocument,
    Profile,
    Provenance,
    ResidencyFacts,
    VisaPeriod,
)

US = Provenance.user_stated()


def _ans(v):
    return Answer(value=v, provenance=US)


def _single(filing_status="single"):
    return Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans(filing_status)))


def _independent_refund(wages, withholding, status, year=2023):
    taxable = max(0, wages - standard_deduction(status, year).amount)
    tax = tax_from_taxable_income(taxable, status, year).tax
    return withholding - tax


def test_label_is_always_estimate():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.label == "ESTIMATE"
    assert isinstance(est, RefundEstimate)


def test_w2_only_known_status_matches_independent_calc():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    expected = _independent_refund(50000, 6000, "single")
    assert est.point == expected
    assert est.low == est.high == expected  # status known -> single number


def test_w2_only_estimate_brackets_the_final_number():
    # eval (j): the early W-2-only estimate must bracket the final computed refund.
    income = IncomeSnapshot(wages=50000, federal_withholding=6000)
    est = estimate_refund(_single(), 2023, income)
    final = _independent_refund(50000, 6000, "single")
    assert est.low <= final <= est.high


def test_unknown_status_widens_range_and_confirming_it_tightens():
    income = IncomeSnapshot(wages=90000, federal_withholding=9000)
    # Married but MFJ-vs-MFS not chosen: range spans both.
    undecided = Profile(household=Household(marital_status=_ans("married")))
    wide = estimate_refund(undecided, 2023, income)
    assert wide.status_assumed is True
    assert wide.low < wide.high  # genuine range across MFJ/MFS
    # The true MFJ outcome is inside the range.
    mfj_final = _independent_refund(90000, 9000, "married_filing_jointly")
    assert wide.low <= mfj_final <= wide.high
    # Confirming the status collapses the range.
    decided = Profile(household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_jointly")))
    narrow = estimate_refund(decided, 2023, income)
    assert narrow.status_assumed is False
    assert narrow.low == narrow.high == mfj_final


def test_self_employment_tax_is_included_and_halved_in_agi():
    from taxfill_core.calc import se_tax

    income = IncomeSnapshot(self_employment_net=48000, federal_withholding=0)
    est = estimate_refund(_single(), 2023, income)
    se = se_tax(48000, 2023)
    labels = {c.label: c.amount for c in est.composition}
    assert labels["Plus: self-employment tax"] == se.se_tax
    assert labels["Less: ½ self-employment tax (adjustment)"] == -se.deduction_half
    # AGI reflects the half-SE adjustment.
    assert labels["Adjusted gross income (AGI)"] == 48000 - se.deduction_half


def test_composition_ties_out_to_the_bottom_line():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, interest=500, federal_withholding=6000))
    labels = {c.label: c.amount for c in est.composition}
    assert labels["Total income"] == 50500
    # taxable = AGI - deduction; bottom line = withholding - total tax
    assert labels["Taxable income"] == max(0, labels["Adjusted gross income (AGI)"] + labels["Less: standard deduction"])
    assert est.point == labels["Estimated refund (+) or amount owed (-)"]


def test_assumptions_and_caveats_are_present():
    profile = _single()
    profile.income_documents = [IncomeDocument(kind="1099-INT", status="missing", provenance=US)]
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert any("Before unclaimed credits" in a for a in est.assumptions)
    assert any("credits" in c.lower() for c in est.what_would_change_it)
    assert any("1099-INT" in c for c in est.what_would_change_it)  # missing doc flagged


def test_citations_are_gov_and_present():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.citations
    assert all(c.url.startswith("https://") and ".gov" in c.url for c in est.citations)


def test_owing_headline_when_underwithheld():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=90000, federal_withholding=1000))
    assert est.point < 0
    assert "owing" in est.headline.lower() or "owe" in est.headline.lower()


def test_mfj_vs_mfs_comparison_surfaces_both_amounts_delta_recommendation_and_caveat():
    # eval (l): the comparison must show BOTH amounts + the dollar delta + a
    # recommendation + the joint-liability caveat.
    income = IncomeSnapshot(wages=90000, federal_withholding=9000)
    undecided = Profile(household=Household(marital_status=_ans("married")))
    est = estimate_refund(undecided, 2023, income)
    comp = est.comparison
    assert comp is not None
    statuses = {c.status for c in comp.candidates}
    assert {"married_filing_jointly", "married_filing_separately"} <= statuses
    # Both amounts independently verified against calc (no magic numbers).
    by_status = {c.status: c.bottom_line for c in comp.candidates}
    assert by_status["married_filing_jointly"] == _independent_refund(90000, 9000, "married_filing_jointly")
    assert by_status["married_filing_separately"] == _independent_refund(90000, 9000, "married_filing_separately")
    # Recommendation = the most-favorable signed bottom line; delta = abs(best - worst).
    values = list(by_status.values())
    assert comp.recommended_status == max(by_status, key=by_status.get)
    assert comp.delta == abs(max(values) - min(values))
    # Joint-liability caveat present whenever both MFJ and MFS are candidates.
    assert comp.joint_liability_caveat is not None
    assert "jointly" in comp.joint_liability_caveat.lower() and "liab" in comp.joint_liability_caveat.lower()


def test_no_comparison_when_single_candidate_status():
    # A confirmed status computes exactly one candidate -> no side-by-side comparison.
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.comparison is None


def test_roadmap_present_with_returns_and_missing_documents():
    profile = _single()
    profile.income_documents = [
        IncomeDocument(kind="W-2", status="have", provenance=US),
        IncomeDocument(kind="1099-INT", status="missing", provenance=US),
    ]
    # us_person True -> best-effort Form 1040; missing docs surfaced as honest gaps.
    profile.identity = None  # exercise the no-identity branch (still produces a roadmap)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.roadmap is not None
    assert "1099-INT" in est.roadmap.missing_documents
    assert "W-2" not in est.roadmap.missing_documents  # already in hand
    assert est.roadmap.estimated_time  # a coarse, honest string


def test_roadmap_returns_form_1040_for_us_person():
    from taxfill_core.schemas.profile import Identity

    profile = _single()
    profile.identity = Identity(us_person=_ans(True))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.roadmap.returns_and_forms == ["Form 1040"]


def _unmarried(hoh_qualifying=None, dependents=None):
    hh = Household(marital_status=_ans("unmarried"))
    if hoh_qualifying is not None:
        hh.hoh_qualifying_person = _ans(hoh_qualifying)
    if dependents:
        hh.dependents = dependents
    return Profile(household=hh)


def test_hoh_is_not_headline_when_qualifying_person_unconfirmed():
    # M3-EST-5: with a dependent but the HOH qualifying-person test NOT confirmed,
    # single is the conservative headline; HoH stays a candidate so the range brackets it.
    profile = _unmarried(dependents=[Dependent(name="Kid", relationship="child", provenance=US)])
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.filing_status_used == "single"
    assert est.comparison is not None
    assert {c.status for c in est.comparison.candidates} == {"single", "head_of_household"}


def test_hoh_is_headline_when_qualifying_person_confirmed():
    # When hoh_qualifying_person is confirmed True, head_of_household is the primary/headline.
    profile = _unmarried(hoh_qualifying=True, dependents=[Dependent(name="Kid", relationship="child", provenance=US)])
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.filing_status_used == "head_of_household"


def test_estimate_raises_for_year_with_no_knowledge_pack():
    # Freshness-protocol propagation: a year with no shipped pack surfaces the
    # loader's FileNotFoundError rather than inventing numbers.
    with pytest.raises(FileNotFoundError):
        estimate_refund(_single(), 1999, IncomeSnapshot(wages=50000, federal_withholding=6000))


# A confirmed-nonresident visa timeline (a sample F-1 arriving in 2020: years 2020-2024
# are exempt, so every day counted for the 2023 target year is excluded and the SPT fails
# -> nonresident). Same shape as test_residency's test_sample_f1_exempt_years_classify_nonresident.
def _nra_immigration():
    return Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2020, 8, 24), end=None, provenance=US)])


def _nra_residency():
    return ResidencyFacts(
        days_in_us={y: _ans(d) for y, d in {2020: 130, 2021: 330, 2022: 330, 2023: 330}.items()}
    )


def test_nonresident_married_does_not_recommend_mfj_and_flags_section_6013():
    # H1: a confirmed nonresident alien files Form 1040-NR, which has no MFJ column, so the
    # PRIMARY (headline) status is married-filing-separately. P-018 / JF5b part 3b: the joint
    # return the §6013(g)/(h) election opens stays a CANDIDATE — priced on resident rules and
    # named as the election's figure, never as a 1040-NR joint return.
    profile = Profile(
        household=Household(marital_status=_ans("married")),
        identity=Identity(us_person=_ans(False)),
        immigration=_nra_immigration(),
        residency_facts=_nra_residency(),
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=90000, federal_withholding=9000))
    assert est.filing_status_used == "married_filing_separately"
    mfj = next(c for c in est.comparison.candidates if c.status == "married_filing_jointly")
    assert mfj.bottom_line == _independent_refund(90_000, 9_000, "married_filing_jointly")   # resident rules
    assert "Married-filing-jointly is shown as a CANDIDATE" in est.residency_caveat
    assert "the figure IF you and your spouse make the election" in est.residency_caveat
    # §6013(g)/(h) caveat surfaced in BOTH assumptions and what-would-change-it.
    assert any("6013" in a for a in est.assumptions)
    assert any("6013" in c for c in est.what_would_change_it)


def test_nonresident_unmarried_with_dependent_does_not_offer_hoh():
    # H1: an unmarried nonresident alien cannot use head_of_household on Form 1040-NR,
    # even with a dependent — single is the only candidate.
    profile = Profile(
        household=Household(
            marital_status=_ans("unmarried"),
            dependents=[Dependent(name="Kid", relationship="child", provenance=US)],
        ),
        identity=Identity(us_person=_ans(False)),
        immigration=_nra_immigration(),
        residency_facts=_nra_residency(),
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.filing_status_used == "single"
    statuses = {c.status for c in est.comparison.candidates} if est.comparison else {"single"}
    assert "head_of_household" not in statuses


def test_widowed_qss_not_primary_when_maintained_home_explicitly_false():
    # M1: a widowed filer who answered the QSS gating fact FALSE must not get QSS as
    # primary even with a dependent — single is the conservative headline.
    profile = Profile(
        household=Household(
            marital_status=_ans("widowed"),
            maintained_home_for_dependent_child=_ans(False),
            dependents=[Dependent(name="Kid", relationship="child", provenance=US)],
        )
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.filing_status_used != "qualifying_surviving_spouse"
    assert est.filing_status_used == "single"


def test_widowed_qss_is_primary_when_maintained_home_confirmed_true():
    # M1: confirmed-True on the QSS gating fact makes qualifying_surviving_spouse the
    # primary (mirrors the HOH confirmed-for-primary pattern) — WITHIN the death-year
    # window (spouse died 2022 -> valid for tax years 2023 and 2024).
    profile = Profile(
        household=Household(
            marital_status=_ans("widowed"),
            spouse_death_year=_ans(2022),
            maintained_home_for_dependent_child=_ans(True),
        )
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.filing_status_used == "qualifying_surviving_spouse"


def test_widowed_qss_denied_outside_death_year_window():
    # QSS is available only for the two tax years AFTER death. Spouse died 2018, so tax year
    # 2023 is out of window (5 years) — single, not QSS, even with maintained_home True.
    profile = Profile(
        household=Household(
            marital_status=_ans("widowed"),
            spouse_death_year=_ans(2018),
            maintained_home_for_dependent_child=_ans(True),
        )
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=90000, federal_withholding=10000))
    assert est.filing_status_used == "single"


def test_roadmap_nonresident_branch_returns_1040nr_and_8843():
    # Residency-driven roadmap: a computable NONRESIDENT classification yields the
    # 1040-NR + 8843 forms (closes the residency roadmap branch).
    profile = Profile(
        household=Household(marital_status=_ans("unmarried")),
        immigration=_nra_immigration(),
        residency_facts=_nra_residency(),
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.roadmap.returns_and_forms == ["Form 1040-NR", "Form 8843"]


def test_roadmap_dual_status_branch_carries_the_concrete_split_year_steps():
    # Residency-driven roadmap: a DUAL-STATUS classification (F-1 transition still inside
    # the exempt window) yields the CONCRETE prepared path (G5), not a vague both-may-apply
    # line: return-vs-statement roles, the residency start-date rule, the First-Year-Choice
    # election as a recorded position, the no-standard-deduction/status restrictions, and
    # the due-date nuance — each step cited to Pub 519.
    # Mirrors test_residency test_transition_within_exempt_window_flags_dual_status.
    profile = Profile(
        household=Household(marital_status=_ans("unmarried")),
        immigration=Immigration(
            visa_timeline=[
                VisaPeriod(status="F-1", start=date(2021, 8, 10), end=date(2024, 6, 30), provenance=US),
                VisaPeriod(status="H-1B", start=date(2024, 7, 1), end=None, provenance=US),
            ]
        ),
        residency_facts=ResidencyFacts(
            days_in_us={y: _ans(d) for y, d in {2021: 140, 2022: 340, 2023: 340, 2024: 360}.items()}
        ),
    )
    est = estimate_refund(profile, 2024, IncomeSnapshot(wages=50000, federal_withholding=6000))
    steps = est.roadmap.returns_and_forms
    # Both forms still lead the roadmap, now with their return-vs-statement roles.
    assert steps[0].startswith("Form 1040 ") and "Dual-Status Return" in steps[0]
    assert steps[1].startswith("Form 1040-NR ") and "Dual-Status Statement" in steps[1]
    assert "DEPARTURE year" in steps[1] and "roles reverse" in steps[1]
    assert steps[2].startswith("Form 8843")
    joined = " ".join(steps)
    # Residency start-date rule; the First-Year-Choice election as a recorded position.
    assert "FIRST DAY" in joined and "Residency start" in joined
    assert "First-Year Choice" in joined and "IRC 7701(b)(4)" in joined
    assert "31 consecutive days" in joined and "75%" in joined and "FOLLOWING year" in joined
    assert "workspace_record_position" in joined
    # Restrictions: no standard deduction; MFS-or-single absent the §6013 election.
    assert "NO standard deduction" in joined
    assert "married-filing-separately" in joined and "§6013(g)/(h)" in joined
    # Due-date nuance (June 15 for a no-withheld-wages departure year).
    assert "June 15" in joined and "April 15" in joined
    # Citation convention: roadmap items are plain strings, so each step carries
    # its Pub 519 chapter inline.
    assert all("Pub 519" in s for s in steps if not s.startswith("Form 8843"))


def test_golden_2023_single_published_tax_table_value():
    # GOLDEN anchored to a PUBLISHED 2023 figure as a literal (NOT recomputed via calc):
    # single filer, $50,000 wages - $13,850 std deduction -> $36,150 taxable.
    # The published 2023 Tax Table tax for the row 'at least $36,150 but less than
    # $36,200' (single column) is $4,121 (IRS 2023 Form 1040 Tax Table).
    PUBLISHED_2023_TAX = 4121  # literal from the published table — do not compute here
    # Sanity-anchor the deduction the scenario depends on (a published 2023 figure too).
    assert standard_deduction("single", 2023).amount == 13850
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50000, federal_withholding=6000))
    assert est.point == 6000 - PUBLISHED_2023_TAX


# ---------------------------------------------------------------------------
# High-income surtaxes in the estimate (Forms 8959 / 8960)
# ---------------------------------------------------------------------------

def _comp_amount(est: RefundEstimate, needle: str):
    lines = [line for line in est.composition if needle in line.label]
    return lines[0].amount if lines else None


def test_estimate_includes_additional_medicare_for_high_wages():
    from taxfill_core.calc import additional_medicare_tax

    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=300_000, federal_withholding=70_000))
    expected = additional_medicare_tax(300_000, "single", 2023).additional_medicare_tax
    assert expected > 0
    assert _comp_amount(est, "Form 8959") == expected
    # The bottom line reflects it: withholding - (income tax + surtax).
    taxable = 300_000 - standard_deduction("single", 2023).amount
    income_tax = tax_from_taxable_income(taxable, "single", 2023).tax
    assert est.point == 70_000 - (income_tax + expected)
    assert any("Form 8959" in a for a in est.assumptions)


def test_estimate_includes_niit_on_investment_income():
    from taxfill_core.calc import niit as _niit

    est = estimate_refund(
        _single(), 2023, IncomeSnapshot(wages=200_000, dividends=60_000, federal_withholding=60_000)
    )
    agi = 260_000
    expected_niit = _niit(60_000, agi, "single", 2023).niit
    assert expected_niit > 0
    assert _comp_amount(est, "Form 8960") == expected_niit
    # Wages 200,000 = exactly the 8959 threshold -> no Additional Medicare line.
    assert _comp_amount(est, "Form 8959") is None
    assert any("Form 8960" in a for a in est.assumptions)


def test_estimate_surtaxes_silent_for_ordinary_incomes():
    est = estimate_refund(_single(), 2023, IncomeSnapshot(wages=50_000, federal_withholding=6_000))
    assert _comp_amount(est, "Form 8959") is None
    assert _comp_amount(est, "Form 8960") is None
    assert not any("Form 8959" in a or "Form 8960" in a for a in est.assumptions)


def test_estimate_skips_niit_for_confirmed_nonresident():
    # Form 8960 does not apply to nonresident aliens; Additional Medicare Tax does.
    profile = Profile(
        household=Household(marital_status=_ans("unmarried")),
        identity=Identity(us_person=_ans(False)),
        immigration=_nra_immigration(),
        residency_facts=_nra_residency(),
    )
    est = estimate_refund(
        profile, 2023, IncomeSnapshot(wages=250_000, dividends=80_000, federal_withholding=80_000)
    )
    assert _comp_amount(est, "Form 8960") is None      # NIIT skipped for the NRA
    assert _comp_amount(est, "Form 8959") is not None  # AddMed still applies to wages


def test_estimate_se_tax_nets_w2_wages_against_the_ss_base():
    # Schedule SE lines 8a-9 threaded: high wages + side gig -> SE tax computed on
    # the remaining base, checked against an independent calc call.
    from taxfill_core.calc import se_tax

    est = estimate_refund(
        _single(), 2023, IncomeSnapshot(wages=170_000, self_employment_net=30_000, federal_withholding=40_000)
    )
    with_wages = se_tax(30_000, 2023, w2_ss_wages=170_000)
    without = se_tax(30_000, 2023)
    assert with_wages.se_tax < without.se_tax  # the base is consumed -> smaller SE tax
    labels = {c.label: c.amount for c in est.composition}
    assert labels["Plus: self-employment tax"] == with_wages.se_tax
    # JF3 (P-019): box 1 stood in for boxes 3 + 7, and the note says so, naming the line via form_line.
    from taxfill_core.knowledge import form_line  # noqa: PLC0415
    note = next(a for a in est.assumptions if "ss_wages was not given" in a)
    assert f"Schedule SE line {form_line(2023, 'sched_se.ss_wages')}" in note


def test_estimate_mfs_worst_case_disclosed_and_withholding_line_negative():
    income = IncomeSnapshot(wages=90_000, federal_withholding=9_000)
    undecided = Profile(household=Household(marital_status=_ans("married")))
    est = estimate_refund(undecided, 2023, income)
    assert any("worst-case" in a for a in est.assumptions)          # MFS combined-income bound disclosed
    labels = {c.label: c.amount for c in est.composition}
    assert labels["Less: federal tax withheld / payments"] == -9_000  # sign matches other "Less:" lines
    assert any("Not modeled in this estimate" in a for a in est.assumptions)


def test_estimate_skips_surtaxes_when_knowledge_pack_predates_the_blocks(tmp_path):
    # Review regression: the schema keeps the surtax blocks OPTIONAL for older packs;
    # the estimator must skip them (not crash) when a custom knowledge dir lacks them.
    import re
    import shutil
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "knowledge"
    legacy = tmp_path / "knowledge"
    (legacy / "federal").mkdir(parents=True)
    text = (src / "federal" / "2023.yaml").read_text()
    # Excise the two surtax blocks (from the marker comment through the niit thresholds).
    text = re.sub(r"\n  # High-income surtaxes.*?qualifying_surviving_spouse: 250000\n", "\n", text, flags=re.S)
    (legacy / "federal" / "2023.yaml").write_text(text)
    shutil.copytree(src / "states", legacy / "states")

    est = estimate_refund(_single(), 2023,
                          IncomeSnapshot(wages=300_000, federal_withholding=70_000),
                          knowledge_dir=legacy)
    assert _comp_amount(est, "Form 8959") is None  # skipped, not crashed
    assert est.point is not None


# ---------------------------------------------------------------------------
# Phase F estimator pipeline: capital gains/losses, taxable SS, SLI, preferential
# rates, CTC/ODC/ACTC, EITC, education credits, PTC, excess SS, MFS true split.
# Every number is cross-checked against an independent calc call or the cited
# knowledge-pack parameters (no magic numbers).
# ---------------------------------------------------------------------------

from decimal import Decimal  # noqa: E402

from taxfill_core.calc import (  # noqa: E402
    excess_ss,
    irs_round,
    ptc_annual,
    student_loan_interest_deduction,
    tax_with_preferential_rates,
    taxable_social_security,
)
from taxfill_core.knowledge import load_knowledge  # noqa: E402


def _labels(est: RefundEstimate) -> dict[str, int]:
    return {c.label: c.amount for c in est.composition}


def _kid(name: str, dob, has_ssn=True):
    return Dependent(name=name, relationship="child", dob=dob, has_ssn=has_ssn, provenance=US)


def _mfj_family(*dependents):
    return Profile(
        household=Household(
            marital_status=_ans("married"),
            filing_status=_ans("married_filing_jointly"),
            dependents=list(dependents),
        )
    )


def _single_parent(*dependents):
    # Filing status confirmed 'single' so exactly one candidate is computed.
    return Profile(
        household=Household(
            marital_status=_ans("unmarried"),
            filing_status=_ans("single"),
            dependents=list(dependents),
        )
    )


def test_ctc_two_qualifying_children_mfj():
    # Two kids with DOBs + SSNs -> $4,000 CTC, fully absorbed nonrefundably.
    profile = _mfj_family(_kid("A", date(2015, 3, 1)), _kid("B", date(2018, 7, 4)))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=95_000, federal_withholding=8_000))
    labels = _labels(est)
    assert labels["Less: child tax credit / credit for other dependents (nonrefundable)"] == -4_000
    # Bottom line cross-checked against independent calc calls.
    taxable = 95_000 - standard_deduction("married_filing_jointly", 2023).amount
    tax = tax_from_taxable_income(taxable, "married_filing_jointly", 2023).tax
    assert tax > 4_000  # the income tax absorbs the whole credit -> no ACTC
    assert "Less: additional child tax credit (refundable)" not in labels
    assert est.point == 8_000 - (tax - 4_000)


def test_ctc_phaseout_50_per_1000_rounds_the_fraction_up():
    import math

    profile = _mfj_family(_kid("A", date(2015, 3, 1)), _kid("B", date(2018, 7, 4)))
    cfg = load_knowledge("federal", 2023).credits.child_tax_credit
    threshold = cfg["magi_phaseout_threshold"]["married_filing_jointly"]

    def _ctc_line(wages):
        est = estimate_refund(profile, 2023, IncomeSnapshot(wages=wages, federal_withholding=120_000))
        return _labels(est)["Less: child tax credit / credit for other dependents (nonrefundable)"]

    # At exactly $410,000 MAGI: $10,000 excess -> 10 units -> $500 reduction.
    assert _ctc_line(threshold + 10_000) == -(4_000 - 50 * math.ceil(10_000 / 1_000))
    assert _ctc_line(threshold + 10_000) == -3_500
    # One dollar more: the $1 FRACTION rounds UP to an 11th $1,000 unit -> $550.
    assert _ctc_line(threshold + 10_001) == -(4_000 - 50 * math.ceil(10_001 / 1_000))
    assert _ctc_line(threshold + 10_001) == -3_450


def test_odc_for_itin_dependent():
    # Known DOB but no work-eligible SSN (ITIN) -> the $500 ODC, never the CTC.
    profile = _single_parent(_kid("Kid", date(2016, 5, 1), has_ssn=False))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=4_000))
    labels = _labels(est)
    assert labels["Less: child tax credit / credit for other dependents (nonrefundable)"] == -500
    taxable = 40_000 - standard_deduction("single", 2023).amount
    tax = tax_from_taxable_income(taxable, "single", 2023).tax
    assert est.point == 4_000 - (tax - 500)


def test_dependent_without_dob_excluded_with_assumption():
    profile = _single_parent(Dependent(name="Kid", relationship="child", has_ssn=True, provenance=US))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50_000, federal_withholding=6_000))
    labels = _labels(est)
    assert not any("child tax credit" in label for label in labels)  # excluded from CTC and ODC
    assert est.point == _independent_refund(50_000, 6_000, "single")  # no credit folded in
    assert any("date of birth" in a for a in est.assumptions)  # the user is told how to fix it


_EITC_LABEL = "Less: earned income tax credit (refundable, formula approximation)"


def test_eitc_single_one_child_phase_in_plateau_and_phase_out():
    cfg = load_knowledge("federal", 2023).credits.earned_income_tax_credit
    row = cfg["by_qualifying_children"]["1"]
    profile = _single_parent(_kid("Kid", date(2015, 1, 1)))

    # Earned $20,000: above the earned-income amount, below the phase-out begin ->
    # the plateau pays exactly the maximum credit.
    assert row["earned_income_amount"] < 20_000 < row["phaseout_begins_other"]
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=20_000))
    assert _labels(est)[_EITC_LABEL] == -row["max_credit"]

    # Earned $30,000: in the phase-out band -> the hand formula from the cited
    # Rev. Proc. parameters (rate = max_credit / (complete - begin)).
    max_credit = Decimal(row["max_credit"])
    rate = max_credit / Decimal(row["phaseout_complete_other"] - row["phaseout_begins_other"])
    expected = irs_round(max_credit - rate * Decimal(30_000 - row["phaseout_begins_other"]))
    est2 = estimate_refund(profile, 2023, IncomeSnapshot(wages=30_000))
    assert _labels(est2)[_EITC_LABEL] == -expected
    assert 0 < expected < row["max_credit"]
    # The formula approximation and the $50-band caveat are disclosed.
    assert any("$50 income bands" in a for a in est2.assumptions)


def test_eitc_blocked_by_investment_income():
    cfg = load_knowledge("federal", 2023).credits.earned_income_tax_credit
    over_limit = cfg["investment_income_limit"] + 1
    profile = _single_parent(_kid("Kid", date(2015, 1, 1)))
    est = estimate_refund(
        profile, 2023, IncomeSnapshot(wages=20_000, interest=over_limit)
    )
    assert _EITC_LABEL not in _labels(est)
    # Same earnings without the investment income DID get the credit (guard the gate).
    est_ok = estimate_refund(profile, 2023, IncomeSnapshot(wages=20_000))
    assert _EITC_LABEL in _labels(est_ok)


def test_capital_loss_limited_to_3000_and_1500_for_mfs():
    est = estimate_refund(
        _single(), 2023, IncomeSnapshot(wages=60_000, capital_gain_long=-8_000, federal_withholding=7_000)
    )
    labels = _labels(est)
    assert labels["Capital loss (limited to $3,000 — the annual capital-loss cap)"] == -3_000
    assert labels["Total income"] == 60_000 - 3_000
    assert est.point == _independent_refund(60_000 - 3_000, 7_000, "single")
    assert any("carries FORWARD" in a for a in est.assumptions)  # carryover honesty

    mfs = Profile(
        household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_separately"))
    )
    est2 = estimate_refund(mfs, 2023, IncomeSnapshot(wages=60_000, capital_gain_long=-8_000, federal_withholding=7_000))
    assert _labels(est2)["Capital loss (limited to $1,500 — the annual capital-loss cap)"] == -1_500


def test_qualified_dividends_taxed_via_preferential_worksheet():
    est = estimate_refund(
        _single(), 2023,
        IncomeSnapshot(wages=100_000, dividends=20_000, qualified_dividends=20_000, federal_withholding=20_000),
    )
    taxable = 120_000 - standard_deduction("single", 2023).amount
    expected = tax_with_preferential_rates(taxable, 20_000, 0, 0, "single", 2023).tax
    label = "Income tax (qualified dividends / net capital gain at preferential rates)"
    assert _labels(est)[label] == expected
    # The worksheet must beat the all-ordinary computation for this filer.
    assert expected < tax_from_taxable_income(taxable, "single", 2023).tax
    assert any("preferential rates" in a for a in est.assumptions)


def test_taxable_social_security_via_worksheet():
    est = estimate_refund(
        _single(), 2023,
        IncomeSnapshot(retirement_income_taxable=30_000, social_security_benefits=24_000, federal_withholding=3_000),
    )
    expected = taxable_social_security(24_000, 30_000, 0, filing_status="single", year=2023).taxable_benefits
    labels = _labels(est)
    assert expected > 0
    assert labels["Taxable Social Security benefits (worksheet)"] == expected
    assert labels["Total income"] == 30_000 + expected
    assert est.point == _independent_refund(30_000 + expected, 3_000, "single")
    assert any("tax-exempt interest" in a for a in est.assumptions)  # assumed $0, disclosed


def test_student_loan_interest_deduction_with_phaseout():
    est = estimate_refund(
        _single(), 2023, IncomeSnapshot(wages=80_000, student_loan_interest_paid=2_500, federal_withholding=10_000)
    )
    # MAGI for section 221 = AGI without the SLI deduction = 80,000 here.
    expected = student_loan_interest_deduction(2_500, 80_000, "single", 2023).deduction
    assert 0 < expected < 2_500  # genuinely inside the 2023 single phase-out band
    labels = _labels(est)
    assert labels["Less: student loan interest deduction"] == -expected
    assert labels["Adjusted gross income (AGI)"] == 80_000 - expected
    assert est.point == _independent_refund(80_000 - expected, 10_000, "single")


def test_excess_ss_credit_needs_two_employers():
    est = estimate_refund(
        _single(), 2023,
        IncomeSnapshot(wages=180_000, federal_withholding=40_000, ss_withheld_by_employer=[6_500, 5_500]),
    )
    expected = excess_ss([6_500, 5_500], 2023).credit
    assert expected > 0
    assert _labels(est)["Less: excess Social Security withholding credit (Schedule 3)"] == -expected

    # A single employer's over-withholding is an employer error, never a return credit.
    est1 = estimate_refund(
        _single(), 2023,
        IncomeSnapshot(wages=180_000, federal_withholding=40_000, ss_withheld_by_employer=[12_000]),
    )
    assert "Less: excess Social Security withholding credit (Schedule 3)" not in _labels(est1)


def test_ptc_net_credit_and_repayment_cases():
    # Net PTC: low income, APTC below the computed credit.
    est = estimate_refund(
        _single(), 2023,
        IncomeSnapshot(wages=25_000, aca_premiums=6_000, aca_slcsp=5_500, aca_aptc=3_000),
    )
    res = ptc_annual(25_000, 1, 6_000, 5_500, 3_000, filing_status="single", year=2023, state="other")
    assert res.net_ptc > 0
    assert _labels(est)["Less: net premium tax credit (Form 8962)"] == -res.net_ptc
    assert any("Form 8962 ANNUAL method" in a for a in est.assumptions)  # AK/HI + approximations disclosed
    # The disclosure points part-year/month-varying coverage at the monthly calc op (G3).
    assert any("ptc_monthly" in a and "12-23" in a for a in est.assumptions)

    # Repayment: higher income, APTC above the computed credit (Table 5 cap applies).
    est2 = estimate_refund(
        _single(), 2023,
        IncomeSnapshot(wages=45_000, federal_withholding=4_000, aca_premiums=4_000, aca_slcsp=4_000, aca_aptc=4_000),
    )
    res2 = ptc_annual(45_000, 1, 4_000, 4_000, 4_000, filing_status="single", year=2023, state="other")
    assert res2.repayment > 0
    labels2 = _labels(est2)
    assert labels2["Plus: excess advance premium tax credit repayment (Form 8962)"] == res2.repayment
    tax = tax_from_taxable_income(45_000 - standard_deduction("single", 2023).amount, "single", 2023).tax
    assert labels2["Total tax"] == tax + res2.repayment  # the repayment lands in total tax


def test_ptc_inputs_without_a_ptc_block_are_skipped_with_assumption():
    # 2022 ships no Form 8962 parameters: skip the computation, disclose the gap.
    est = estimate_refund(
        _single(), 2022,
        IncomeSnapshot(wages=25_000, aca_premiums=6_000, aca_slcsp=5_500, aca_aptc=3_000),
    )
    labels = _labels(est)
    assert "Less: net premium tax credit (Form 8962)" not in labels
    assert "Plus: excess advance premium tax credit repayment (Form 8962)" not in labels
    assert any("NOT computed for 2022" in a for a in est.assumptions)


def test_arpa_2021_ctc_fully_refundable_3600_under_6():
    profile = _single_parent(_kid("Kid", date(2017, 6, 1)))  # age 4 at the end of 2021
    est = estimate_refund(profile, 2021, IncomeSnapshot(wages=30_000, federal_withholding=2_000))
    labels = _labels(est)
    # The whole $3,600 is refundable: no nonrefundable CTC line, no 15% ACTC math.
    assert labels["Less: child tax credit (2021 — fully refundable)"] == -3_600
    assert "Less: child tax credit / credit for other dependents (nonrefundable)" not in labels
    assert "Less: additional child tax credit (refundable)" not in labels
    # Bottom line ties out: withholding + RCTC + EITC - income tax (independent calc).
    taxable = 30_000 - standard_deduction("single", 2021).amount
    tax = tax_from_taxable_income(taxable, "single", 2021).tax
    eitc = -labels[_EITC_LABEL]
    row = load_knowledge("federal", 2021).credits.earned_income_tax_credit["by_qualifying_children"]["1"]
    max_credit = Decimal(row["max_credit"])
    rate = max_credit / Decimal(row["phaseout_complete_other"] - row["phaseout_begins_other"])
    assert eitc == irs_round(max_credit - rate * Decimal(30_000 - row["phaseout_begins_other"]))
    assert est.point == 2_000 + 3_600 + eitc - tax
    # Advance-payment reconciliation honesty (Letter 6419).
    assert any("Letter 6419" in a for a in est.assumptions)


def test_spouse_split_gives_true_two_return_mfs_comparison():
    income = IncomeSnapshot(
        wages=90_000, federal_withholding=9_000,
        spouse=IncomeSnapshot(wages=20_000, federal_withholding=1_500),
    )
    undecided = Profile(household=Household(marital_status=_ans("married")))
    est = estimate_refund(undecided, 2023, income)
    by_status = {c.status: c.bottom_line for c in est.comparison.candidates}
    self_mfs = _independent_refund(90_000, 9_000, "married_filing_separately")
    spouse_mfs = _independent_refund(20_000, 1_500, "married_filing_separately")
    # The MFS candidate is the SUM of two separately computed MFS returns...
    assert by_status["married_filing_separately"] == self_mfs + spouse_mfs
    # ...and MFJ combines both spouses on one return.
    assert by_status["married_filing_jointly"] == _independent_refund(110_000, 10_500, "married_filing_jointly")
    # The worst-case wording is gone; the true-comparison disclosure replaces it.
    assert not any("worst-case" in a for a in est.assumptions)
    assert any("TRUE two-return comparison" in a for a in est.assumptions)

    # With MFS confirmed, the composition itself carries the spouse's return.
    decided = Profile(
        household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_separately"))
    )
    est2 = estimate_refund(decided, 2023, income)
    labels2 = _labels(est2)
    assert labels2["Spouse's MFS return (computed separately)"] == spouse_mfs
    assert est2.point == self_mfs + spouse_mfs


def test_no_spouse_data_keeps_the_worst_case_fallback():
    # Without per-spouse amounts the MFS candidate stays the all-on-one-return bound,
    # and the estimate says so (regression guard for the F10 split gating).
    income = IncomeSnapshot(wages=90_000, federal_withholding=9_000)
    est = estimate_refund(Profile(household=Household(marital_status=_ans("married"))), 2023, income)
    assert any("worst-case" in a for a in est.assumptions)
    assert not any("TRUE two-return comparison" in a for a in est.assumptions)


# ---------------------------------------------------------------------------
# Final-review regressions: per-person excess-SS and Schedule SE on the MFJ
# spouse split, the MFS/below-100%-FPL PTC gates, the EITC net-capital-gain
# investment-income gate, NRA education credits, and the spouse-snapshot-
# ignored disclosure. Repro numbers come from the adversarial review findings;
# every expected value is re-derived through calc (no magic numbers).
# ---------------------------------------------------------------------------

_XSS_LABEL = "Less: excess Social Security withholding credit (Schedule 3)"


def _mfj_confirmed():
    return Profile(
        household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_jointly"))
    )


def test_mfj_spouse_split_excess_ss_is_per_person():
    # Review repro: each spouse has ONE employer at the 2023 per-person max ($9,932.40).
    # The credit is $0 per person (a single employer can never over-withhold on the
    # return), NOT the $9,932 the concatenated two-spouse list would mint.
    from taxfill_core.calc import additional_medicare_tax
    income = IncomeSnapshot(
        wages=160_200, federal_withholding=30_000, ss_withheld_by_employer=[9_932],
        spouse=IncomeSnapshot(wages=160_200, federal_withholding=30_000, ss_withheld_by_employer=[9_932]),
    )
    est = estimate_refund(_mfj_confirmed(), 2023, income)
    assert _XSS_LABEL not in _labels(est)
    assert excess_ss([9_932], 2023).credit == 0  # the per-person contract the split must honor
    # Correct bottom line, re-derived: MFJ tax on combined wages + Form 8959 (combined
    # Medicare wages exceed the joint threshold) against combined withholding.
    taxable = 320_400 - standard_deduction("married_filing_jointly", 2023).amount
    tax = tax_from_taxable_income(taxable, "married_filing_jointly", 2023).tax
    addmed = additional_medicare_tax(320_400, "married_filing_jointly", 2023).additional_medicare_tax
    assert est.point == 60_000 - (tax + addmed)


def test_mfj_spouse_split_excess_ss_sums_each_spouses_own_credit():
    # Each spouse independently has 2+ employers: the per-person credits are summed.
    income = IncomeSnapshot(
        wages=170_000, federal_withholding=30_000, ss_withheld_by_employer=[6_500, 5_500],
        spouse=IncomeSnapshot(wages=170_000, federal_withholding=30_000, ss_withheld_by_employer=[6_000, 6_000]),
    )
    est = estimate_refund(_mfj_confirmed(), 2023, income)
    expected = excess_ss([6_500, 5_500], 2023).credit + excess_ss([6_000, 6_000], 2023).credit
    assert expected > 0
    assert _labels(est)[_XSS_LABEL] == -expected


def test_married_combined_ss_entries_disclosed_as_one_person():
    # Married WITHOUT a spouse split: 2+ box-4 entries are treated as one person's
    # employers, and the estimate must say so (joint returns compute per spouse).
    income = IncomeSnapshot(wages=180_000, federal_withholding=40_000, ss_withheld_by_employer=[6_500, 5_500])
    est = estimate_refund(Profile(household=Household(marital_status=_ans("married"))), 2023, income)
    assert any("ONE person's employers" in a for a in est.assumptions)
    # A single filer with the same entries is genuinely one person — no disclosure.
    est_single = estimate_refund(_single(), 2023, income)
    assert not any("ONE person's employers" in a for a in est_single.assumptions)


def test_mfj_spouse_split_se_tax_is_per_person():
    # Review repro: A has 200k wages and no SE; B has 100k SE and NO wages. B's own
    # Schedule SE gets the FULL wage base — A's wages must not absorb it.
    from taxfill_core.calc import se_tax
    income = IncomeSnapshot(
        wages=200_000, federal_withholding=40_000,
        spouse=IncomeSnapshot(self_employment_net=100_000),
    )
    est = estimate_refund(_mfj_confirmed(), 2023, income)
    labels = _labels(est)
    expected = se_tax(100_000, 2023)  # B alone: w2_ss_wages=0
    assert labels["Plus: self-employment tax"] == expected.se_tax
    assert labels["Less: ½ self-employment tax (adjustment)"] == -expected.deduction_half
    # Sanity: the combined-snapshot computation (the old bug) would be much smaller.
    assert se_tax(100_000, 2023, w2_ss_wages=200_000).se_tax < expected.se_tax


def test_mfj_spouse_split_se_tax_sums_both_spouses_schedules():
    # Both spouses self-employed at 150k: TWO per-person Schedule SEs, each with its
    # own wage base — not one Schedule SE on 300k.
    from taxfill_core.calc import se_tax
    income = IncomeSnapshot(
        self_employment_net=150_000, federal_withholding=30_000,
        spouse=IncomeSnapshot(self_employment_net=150_000, federal_withholding=30_000),
    )
    est = estimate_refund(_mfj_confirmed(), 2023, income)
    per_person = se_tax(150_000, 2023)
    labels = _labels(est)
    assert labels["Plus: self-employment tax"] == 2 * per_person.se_tax
    assert labels["Less: ½ self-employment tax (adjustment)"] == -2 * per_person.deduction_half
    assert 2 * per_person.se_tax > se_tax(300_000, 2023).se_tax  # combined would understate


def _mfs_confirmed():
    return Profile(
        household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_separately"))
    )


def test_mfs_candidate_gets_no_ptc_by_rule():
    # Review repro: MFS + 1095-A with no APTC. IRC 36B(c)(1)(C) denies the PTC, so
    # there is no credit line and the bottom line is plain withholding - tax.
    income = IncomeSnapshot(wages=30_000, federal_withholding=2_000,
                            aca_premiums=8_000, aca_slcsp=7_500, aca_aptc=0)
    est = estimate_refund(_mfs_confirmed(), 2023, income)
    labels = _labels(est)
    assert "Less: net premium tax credit (Form 8962)" not in labels
    assert est.point == _independent_refund(30_000, 2_000, "married_filing_separately")
    assert any("36B(c)(1)(C)" in a for a in est.assumptions)


def test_mfs_candidate_repays_aptc_up_to_the_table_5_cap():
    # Same MFS filer with APTC 6,000: the whole APTC is excess (PTC 0 by rule) and the
    # repayment is the Table 5 'other'-column cap — cross-checked via ptc_annual's
    # new default (household income = AGI = 30,000, household size 1).
    income = IncomeSnapshot(wages=30_000, federal_withholding=2_000,
                            aca_premiums=8_000, aca_slcsp=7_500, aca_aptc=6_000)
    est = estimate_refund(_mfs_confirmed(), 2023, income)
    res = ptc_annual(30_000, 1, 8_000, 7_500, 6_000, filing_status="married_filing_separately", year=2023)
    assert res.ptc == 0 and res.net_ptc == 0 and 0 < res.repayment < 6_000
    labels = _labels(est)
    assert labels["Plus: excess advance premium tax credit repayment (Form 8962)"] == res.repayment
    assert est.point == 2_000 - (tax_from_taxable_income(
        30_000 - standard_deduction("married_filing_separately", 2023).amount,
        "married_filing_separately", 2023).tax + res.repayment)
    assert any("36B(c)(1)(C)" in a for a in est.assumptions)


def test_eitc_investment_gate_uses_net_capital_gain():
    # Review repro: st -12,000 + lt +12,500 = net +500, far under the 2023 $11,000
    # limit — the gate must use the loss-limited NET figure (Pub 596 Worksheet 1),
    # never the gross positive legs summed (12,500 wrongly denied the whole credit).
    profile = _single_parent(_kid("Kid", date(2015, 1, 1)))
    est = estimate_refund(profile, 2023, IncomeSnapshot(
        wages=18_000, capital_gain_short=-12_000, capital_gain_long=12_500))
    control = estimate_refund(profile, 2023, IncomeSnapshot(wages=18_000, capital_gain_long=500))
    assert _EITC_LABEL in _labels(est)
    # Identical AGI and net gain -> identical EITC and identical bottom line.
    assert _labels(est)[_EITC_LABEL] == _labels(control)[_EITC_LABEL]
    assert est.point == control.point


def test_nonresident_gets_no_education_credits():
    # Review repro: an F-1 classified nonresident cannot claim Form 8863 credits
    # (no residency election modeled) — neither the nonrefundable part nor the
    # refundable 40% AOTC — and the estimate says why.
    profile = Profile(
        household=Household(marital_status=_ans("unmarried")),
        identity=Identity(us_person=_ans(False)),
        immigration=_nra_immigration(),
        residency_facts=_nra_residency(),
    )
    income = IncomeSnapshot(wages=40_000, federal_withholding=4_000, aotc_qualified_expenses=[4_000])
    est = estimate_refund(profile, 2023, income)
    labels = _labels(est)
    assert "Less: education credits (nonrefundable part)" not in labels
    assert "Less: American opportunity credit (refundable 40%)" not in labels
    # FIX-1 (intentional change): a 1040-NR filer gets NO standard deduction, so the
    # cross-check is withholding minus the tax on the FULL wages (itemized $0).
    assert est.point == 4_000 - tax_from_taxable_income(40_000, "single", 2023).tax
    assert any("residency election" in a for a in est.assumptions)
    # Control: the same income for a resident single filer DOES get both parts.
    est_res = estimate_refund(_single(), 2023, income)
    assert "Less: education credits (nonrefundable part)" in _labels(est_res)
    assert "Less: American opportunity credit (refundable 40%)" in _labels(est_res)


def test_spouse_snapshot_without_confirmed_marriage_is_loudly_disclosed():
    # Review repro: nothing confirmed + a spouse snapshot. Married is never inferred
    # from income data, so the spouse's amounts are EXCLUDED — but never silently:
    # a loud assumption and a what-would-change-it entry must disclose it.
    profile = Profile(household=Household())
    income = IncomeSnapshot(
        wages=60_000, federal_withholding=5_000,
        spouse=IncomeSnapshot(wages=80_000, federal_withholding=6_000),
    )
    est = estimate_refund(profile, 2023, income)
    assert est.point == _independent_refund(60_000, 5_000, "single")  # primary only
    assert any(
        "IMPORTANT" in a and "spouse" in a and "NOT included" in a for a in est.assumptions
    )
    assert any(
        "spouse" in c and "marital status" in c for c in est.what_would_change_it
    )
    # Confirming 'married' actually enables the split (the disclosure disappears).
    est_married = estimate_refund(Profile(household=Household(marital_status=_ans("married"))), 2023, income)
    assert not any("NOT included in this estimate" in a for a in est_married.assumptions)
    assert any("TRUE two-return comparison" in a for a in est_married.assumptions)


def test_estimate_surfaces_below_100_fpl_ptc_caveats():
    # Below-100%-FPL 1095-A filer, no APTC: no PTC line (the safe harbor cannot
    # apply) and the eligibility caveat is an assumption, not buried in calc work.
    income = IncomeSnapshot(wages=13_000, aca_premiums=6_000, aca_slcsp=5_000, aca_aptc=0)
    est = estimate_refund(_single(), 2023, income)
    labels = _labels(est)
    assert "Less: net premium tax credit (Form 8962)" not in labels
    assert any("below 100%" in a and "safe harbor" in a for a in est.assumptions)
    # With APTC the credit is computed (safe-harbor assumption) and disclosed as such.
    income2 = IncomeSnapshot(wages=13_000, aca_premiums=6_000, aca_slcsp=5_000, aca_aptc=3_000)
    est2 = estimate_refund(_single(), 2023, income2)
    res = ptc_annual(13_000, 1, 6_000, 5_000, 3_000, filing_status="single", year=2023)
    assert res.net_ptc > 0
    assert _labels(est2)["Less: net premium tax credit (Form 8962)"] == -res.net_ptc
    assert any("below 100%" in a and "safe harbor" in a for a in est2.assumptions)


# ---------------------------------------------------------------------------
# Tier-1 persona-review regressions (FIX-1..FIX-7): nonresident deduction law,
# NRA investment-income rates, dual-status status restrictions, the has_ssn=None
# CTC demotion, vanishing 1098-E, §6013 worldwide-income input caveat, and
# FICA-withheld-in-error disclosure. Repro numbers come from the confirmed
# findings; every expected value is re-derived through calc (no magic numbers).
# ---------------------------------------------------------------------------

_NRA_DEDUCTION_LABEL = "Less: itemized deductions (1040-NR — nonresidents cannot take the standard deduction)"


def _nra_profile(marital="unmarried", **household_kwargs):
    return Profile(
        household=Household(marital_status=_ans(marital), **household_kwargs),
        identity=Identity(us_person=_ans(False)),
        immigration=_nra_immigration(),
        residency_facts=_nra_residency(),
    )


def test_fix1_nonresident_deduction_is_itemized_only():
    # FIX-1 repro: F-1 nonresident, wages 18,000, withholding 1,400, state tax
    # withheld 650 itemized. The 1040-NR deduction is the itemized 650 — NEVER
    # max(650, standard deduction) — flipping the sign from refund to owed.
    est = estimate_refund(
        _nra_profile(), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, itemized_deductions=650),
    )
    labels = _labels(est)
    assert "Less: standard deduction" not in labels          # no standard-deduction line
    assert labels[_NRA_DEDUCTION_LABEL] == -650               # the supplied itemized only
    assert labels["Taxable income"] == 18_000 - 650
    tax = tax_from_taxable_income(18_000 - 650, "single", 2023).tax
    assert est.point == 1_400 - tax
    assert est.point < 0  # the persona OWES (~$465) — the old code showed a fake refund
    # The itemized-only rule AND the India Art. 21(2) exception are both disclosed.
    assert any("cannot take the standard deduction" in a for a in est.assumptions)
    assert any("Art. 21(2)" in a and "India" in a for a in est.assumptions)


def test_fix1_nonresident_without_itemized_gets_zero_deduction():
    # FIX-1 repro (ra-dual-status persona numbers): wages 95,000 / withholding 14,000.
    # No itemized supplied -> deduction $0, never the standard deduction.
    est = estimate_refund(
        _nra_profile(), 2023, IncomeSnapshot(wages=95_000, federal_withholding=14_000)
    )
    labels = _labels(est)
    assert "Less: standard deduction" not in labels
    assert labels[_NRA_DEDUCTION_LABEL] == 0
    assert est.point == 14_000 - tax_from_taxable_income(95_000, "single", 2023).tax
    assert est.point < 0  # owes (~$2,213), not the old +$834 "refund"
    # The wrong-law 'Standard deduction assumed' disclosure must NOT appear.
    assert not any(a.startswith("Standard deduction assumed") for a in est.assumptions)
    assert any("$0 of itemized deductions" in a for a in est.assumptions)


def test_fix2_nonresident_investment_income_uses_ordinary_rates_and_discloses_fdap():
    # FIX-2 repro: NRA + qualified dividends. The resident QDCGT worksheet must NOT
    # run (FDAP income is flat 30%/treaty-rate law, not preferential rates), and the
    # ECI/FDAP + 871(i)(2)(A) deposit-interest disclosures must appear. The interest
    # here is entered WITHOUT deposit character, so it is taxed and the disclosure
    # names the amount — the old amount-less "may OVERTAX" hedge is gone (P-013 (d)).
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400,
        dividends=2_000, qualified_dividends=2_000, interest=2_000,
    )
    est = estimate_refund(_nra_profile(), 2023, income)
    labels = _labels(est)
    pref_label = "Income tax (qualified dividends / net capital gain at preferential rates)"
    assert pref_label not in labels
    taxable = 18_000 + 2_000 + 2_000  # deduction $0 (no itemized, 1040-NR)
    assert labels["Income tax"] == tax_from_taxable_income(taxable, "single", 2023).tax
    assert any("FDAP" in a and "Schedule NEC" in a for a in est.assumptions)
    assert any(
        "871(i)(2)(A)" in a and "$2,000 of interest was entered WITHOUT deposit character" in a
        for a in est.assumptions
    )
    assert not any("OVERTAX" in a for a in est.assumptions)
    assert not any("Qualified Dividends and Capital Gain Tax Worksheet" in a for a in est.assumptions)
    # Control: the same income for a resident single filer DOES use the worksheet.
    est_res = estimate_refund(_single(), 2023, income)
    assert pref_label in _labels(est_res)
    assert not any("FDAP" in a for a in est_res.assumptions)


def _dual_status_profile(marital="married", **household_kwargs):
    # The ra-dual-status finding's repro timeline: F-1 -> H-1B during 2023, still
    # inside the exempt window -> residency classifies dual_status_candidate.
    return Profile(
        household=Household(marital_status=_ans(marital), **household_kwargs),
        immigration=Immigration(
            visa_timeline=[
                VisaPeriod(status="F-1", start=date(2021, 8, 24), end=date(2023, 3, 31), provenance=US),
                VisaPeriod(status="H-1B", start=date(2023, 4, 1), end=None, provenance=US),
            ]
        ),
        residency_facts=ResidencyFacts(
            days_in_us={y: _ans(d) for y, d in {2021: 130, 2022: 350, 2023: 365}.items()}
        ),
    )


def test_fix3_dual_status_candidate_married_drops_mfj_and_discloses_split_year():
    # FIX-3 repro: a married dual-status candidate must NOT be steered to MFJ with a
    # dollar delta; the split-year restrictions must be a loud assumption.
    from taxfill_core.residency import classify

    assert classify(
        [
            {"status": "F-1", "start": "2021-08-24", "end": "2023-03-31"},
            {"status": "H-1B", "start": "2023-04-01", "end": None},
        ],
        {2021: 130, 2022: 350, 2023: 365},
        2023,
    ).classification == "dual_status_candidate"

    est = estimate_refund(
        _dual_status_profile(), 2023, IncomeSnapshot(wages=95_000, federal_withholding=14_000)
    )
    assert est.filing_status_used == "married_filing_separately"
    # JF5b part 3b: the joint return exists only under the §6013(g)/(h) election — a candidate
    # on resident rules, never the no-election headline.
    assert [c.status for c in est.comparison.candidates] == ["married_filing_separately", "married_filing_jointly"]
    assert "Married-filing-jointly is shown as a CANDIDATE" in est.residency_caveat
    surfaced = " ".join(est.assumptions + est.what_would_change_it)
    assert "DUAL-STATUS" in surfaced
    assert "§6013" in surfaced and "worldwide income" in surfaced.lower()
    assert "NO standard deduction" in surfaced
    assert "FULL-YEAR approximation" in surfaced          # numbers are full-year math
    assert "Form 1040 + Form 1040-NR" in surfaced          # the real split-year return
    # Surfaced in BOTH assumptions and what_would_change_it.
    assert any("DUAL-STATUS" in a for a in est.assumptions)
    assert any("DUAL-STATUS" in c for c in est.what_would_change_it)


def test_fix3_dual_status_candidate_unmarried_does_not_offer_hoh():
    profile = _dual_status_profile(
        marital="unmarried",
        dependents=[Dependent(name="Kid", relationship="child", provenance=US)],
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=50_000, federal_withholding=6_000))
    assert est.filing_status_used == "single"
    statuses = {c.status for c in est.comparison.candidates} if est.comparison else {"single"}
    assert "head_of_household" not in statuses
    assert any("DUAL-STATUS" in a for a in est.assumptions)


def test_fix4_dependent_with_unconfirmed_ssn_is_demoted_loudly():
    # FIX-4 repro: two under-17 kids with DOBs but has_ssn NEVER ASKED (None).
    # The conservative $500-ODC math stays, but the demotion is disclosed with the
    # count and the dollar path in BOTH assumptions and what_would_change_it.
    cfg = load_knowledge("federal", 2023).credits.child_tax_credit
    per_child, odc = cfg["per_qualifying_child"], cfg["credit_for_other_dependents"]
    income = IncomeSnapshot(wages=100_000, federal_withholding=7_000)
    est = estimate_refund(
        _mfj_family(_kid("A", date(2015, 3, 1), has_ssn=None), _kid("B", date(2018, 7, 4), has_ssn=None)),
        2023, income,
    )
    labels = _labels(est)
    assert labels["Less: child tax credit / credit for other dependents (nonrefundable)"] == -2 * odc
    demotion = [a for a in est.assumptions if "ONLY because SSN status was not confirmed" in a]
    assert len(demotion) == 1
    assert "2 dependent(s)" in demotion[0]
    assert f"${odc:,}" in demotion[0] and f"${per_child:,}" in demotion[0]  # the dollar path
    assert f"${(per_child - odc) * 2:,}" in demotion[0]                     # the total delta
    assert "has_ssn" in demotion[0]
    assert any("ONLY because SSN status was not confirmed" in c for c in est.what_would_change_it)
    # Control: confirmed SSNs -> full CTC and NO demotion disclosure.
    est_ok = estimate_refund(
        _mfj_family(_kid("A", date(2015, 3, 1)), _kid("B", date(2018, 7, 4))), 2023, income
    )
    assert _labels(est_ok)[
        "Less: child tax credit / credit for other dependents (nonrefundable)"
    ] == -2 * per_child
    assert not any("ONLY because SSN status was not confirmed" in a for a in est_ok.assumptions)


def test_fix5_student_loan_interest_phased_out_to_zero_is_disclosed():
    # FIX-5 repro: $1,200 of 1098-E interest at MAGI $232,850 MFJ -> the deduction is
    # fully phased out. The line disappears from the composition, but the WHY must not.
    assert student_loan_interest_deduction(1_200, 232_850, "married_filing_jointly", 2023).deduction == 0
    est = estimate_refund(
        _mfj_confirmed(), 2023,
        IncomeSnapshot(wages=232_850, student_loan_interest_paid=1_200, federal_withholding=40_000),
    )
    assert "Less: student loan interest deduction" not in _labels(est)
    note = [a for a in est.assumptions if "student-loan interest (1098-E)" in a]
    assert len(note) == 1
    assert "$1,200" in note[0] and "$0" in note[0] and "phase-out" in note[0]
    assert "pre_agi_adjustments" in note[0]  # the do-not-double-enter guard
    # Control: inside the phase-out band the deduction line is present and NO $0 note.
    est_ok = estimate_refund(
        _single(), 2023,
        IncomeSnapshot(wages=80_000, student_loan_interest_paid=2_500, federal_withholding=10_000),
    )
    assert "Less: student loan interest deduction" in _labels(est_ok)
    assert not any("student-loan interest (1098-E)" in a for a in est_ok.assumptions)


def test_fix5_student_loan_interest_mfs_zero_is_disclosed():
    # The MFS-by-rule $0 is equally disclosed (IRC 221 bars MFS entirely).
    est = estimate_refund(
        _mfs_confirmed(), 2023,
        IncomeSnapshot(wages=60_000, student_loan_interest_paid=1_200, federal_withholding=8_000),
    )
    assert "Less: student loan interest deduction" not in _labels(est)
    note = [a for a in est.assumptions if "student-loan interest (1098-E)" in a]
    assert len(note) == 1
    assert "married-filing-separately" in note[0] and "$1,200" in note[0]


def test_fix6_section_6013_caveat_requires_spouse_worldwide_income_in_inputs():
    # FIX-6 (tier-1 disclosure): whenever the §6013 caveat fires, it must say the
    # elected-MFJ figure is only valid with the NRA spouse's foreign income in the
    # inputs (spouse snapshot's other_income) — else the MFJ delta is overstated.
    est = estimate_refund(
        _nra_profile(marital="married"), 2023,
        IncomeSnapshot(wages=90_000, federal_withholding=9_000),
    )
    caveats = [a for a in est.assumptions if "§6013" in a]
    assert caveats and all("other_income" in c for c in caveats)
    assert any("overstates the MFJ advantage" in c for c in caveats)
    assert any("other_income" in c for c in est.what_would_change_it)
    # The conditional (residency-not-yet-computed) caveat carries the same warning.
    pending = Profile(
        household=Household(marital_status=_ans("married")),
        identity=Identity(us_person=_ans(False)),
    )
    est2 = estimate_refund(pending, 2023, IncomeSnapshot(wages=90_000, federal_withholding=9_000))
    caveats2 = [a for a in est2.assumptions if "§6013" in a]
    assert caveats2 and all("other_income" in c for c in caveats2)


def test_fix7_nonresident_fica_withheld_disclosed_as_off_return_recovery():
    # FIX-7 repro: exempt F-1 with $1,116 of Social Security tax withheld in error.
    # The estimate must say it is recovered via employer / Form 843 + 8316 — NOT on
    # the 1040-NR — in both assumptions and what_would_change_it.
    est = estimate_refund(
        _nra_profile(), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, ss_withheld_by_employer=[1_116]),
    )
    notes = [a for a in est.assumptions if "Form 843" in a]
    assert len(notes) == 1
    assert "$1,116" in notes[0] and "Form 8316" in notes[0] and "FICA-EXEMPT" in notes[0]
    assert "NOT on the 1040-NR" in notes[0]
    assert any("Form 843" in c for c in est.what_would_change_it)
    # Control: the same W-2 for a resident filer gets no FICA-in-error note.
    est_res = estimate_refund(
        _single(), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, ss_withheld_by_employer=[1_116]),
    )
    assert not any("Form 843" in a for a in est_res.assumptions)


# ---------------------------------------------------------------------------
# Tier-2: the NRA-SPOUSE direction of the §6013(g)/(h) caveat (the Tier-1
# branches fired only when the PRIMARY filer was the nonresident — the common
# citizen/RA-filer + NRA-spouse direction priced MFJ silently), and the
# treaty-exempt income field (1042-S box 2 / Schedule OI). Expected values are
# re-derived through calc (no magic numbers).
# ---------------------------------------------------------------------------

from taxfill_core.schemas.profile import Spouse  # noqa: E402


def _us_filer_married(spouse: Spouse | None = None) -> Profile:
    return Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(marital_status=_ans("married"), spouse=spouse),
    )


def test_nra_spouse_direction_fires_6013_caveat_and_keeps_mfj_candidate():
    # THE bug under test: a us_person filer with a declared non-US-person spouse
    # used to get MFJ headlined with ZERO §6013 caveat.
    est = estimate_refund(
        _us_filer_married(Spouse(us_person=_ans(False))), 2023,
        IncomeSnapshot(wages=90_000, federal_withholding=9_000),
    )
    statuses = {c.status for c in est.comparison.candidates}
    assert "married_filing_jointly" in statuses  # MFJ STAYS a candidate (election direction)
    caveats = [a for a in est.assumptions if "§6013" in a]
    assert len(caveats) == 1
    c = caveats[0]
    assert "WORLDWIDE" in c and "other_income" in c and "overstates the MFJ advantage" in c
    assert "signed by BOTH spouses" in c            # the statement requirement is named
    assert "may be a nonresident alien" in c        # conditional — no spouse facts yet
    # No spouse tax_id on file -> the W-7/ITIN last mile rides along.
    assert "Form W-7" in c and "WITH the return" in c and "Austin" in c and "'NRA'" in c
    # Surfaced in BOTH assumptions and what_would_change_it.
    assert any("§6013" in ch for ch in est.what_would_change_it)


def test_nra_spouse_confirmed_by_own_facts_asserts_the_caveat():
    # us_person never asked, but the spouse's OWN facts (F-2 exempt family) classify
    # nonresident — detection must key on the facts, not only the declared flag.
    spouse = Spouse(
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-2", start=date(2022, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in {2021: 0, 2022: 140, 2023: 330}.items()}),
    )
    est = estimate_refund(_us_filer_married(spouse), 2023, IncomeSnapshot(wages=90_000, federal_withholding=9_000))
    caveats = [a for a in est.assumptions if "§6013" in a]
    assert len(caveats) == 1
    assert caveats[0].startswith("Your spouse's own residency result is NONRESIDENT alien")
    assert "may be a nonresident alien" not in caveats[0]


def test_nra_spouse_with_tin_gets_no_w7_note():
    est = estimate_refund(
        _us_filer_married(Spouse(us_person=_ans(False), tax_id=_ans("999-88-7777"))), 2023,
        IncomeSnapshot(wages=90_000, federal_withholding=9_000),
    )
    caveats = [a for a in est.assumptions if "§6013" in a]
    assert caveats and "Form W-7" not in caveats[0]
    # The 'NRA' box literal is a no-TIN marker, not a TIN: the W-7 note stays.
    est_nra = estimate_refund(
        _us_filer_married(Spouse(us_person=_ans(False), tax_id=_ans("NRA"))), 2023,
        IncomeSnapshot(wages=90_000, federal_withholding=9_000),
    )
    assert any("Form W-7" in a for a in est_nra.assumptions if "§6013" in a)


def test_both_us_person_couple_control_has_no_6013_caveat():
    est = estimate_refund(
        _us_filer_married(Spouse(us_person=_ans(True))), 2023,
        IncomeSnapshot(wages=90_000, federal_withholding=9_000),
    )
    assert not any("6013" in a for a in est.assumptions)
    assert not any("6013" in c for c in est.what_would_change_it)


def test_spouse_resident_by_own_facts_has_no_6013_caveat():
    # H-4 present 365 days x3: the spouse's own facts classify RESIDENT — a joint
    # return needs no election, so no caveat (classify runs only because facts exist).
    spouse = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-4", start=date(2021, 1, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(365) for y in (2021, 2022, 2023)}),
    )
    est = estimate_refund(_us_filer_married(spouse), 2023, IncomeSnapshot(wages=90_000, federal_withholding=9_000))
    assert not any("6013" in a for a in est.assumptions)


_TREATY_LABEL = "Less: treaty-exempt income (tax treaty — confirm the article and your state's conformity)"


def test_treaty_exempt_income_reduces_the_nra_taxable_base():
    # Part-D repro: NRA F-1, wages 18,000, treaty-exempt 5,000 -> taxable base
    # 13,000, cross-checked against an independent calc call.
    est = estimate_refund(
        _nra_profile(), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, treaty_exempt_income=5_000),
    )
    labels = _labels(est)
    assert labels[_TREATY_LABEL] == -5_000
    assert labels["Total income"] == 18_000             # gross — the exclusion is its own line
    assert labels["Adjusted gross income (AGI)"] == 13_000
    assert labels["Taxable income"] == 13_000           # NRA deduction $0 (itemized-only)
    assert est.point == 1_400 - tax_from_taxable_income(13_000, "single", 2023).tax
    # Trust-the-agent semantics + the state-conformity reminder are disclosed.
    treaty_notes = [a for a in est.assumptions if "does NOT validate treaty eligibility" in a]
    assert len(treaty_notes) == 1
    note = treaty_notes[0]
    assert "itemized_deductions" in note and "get_sources" in note   # like-itemized trust semantics
    assert "Schedule OI" in note and "1040-NR line 1k" in note
    assert "state_scope" in note                                      # conformity reminder
    assert not any("CLAMPED" in a for a in est.assumptions)


def test_treaty_exempt_income_clamped_to_income_floor_and_disclosed():
    est = estimate_refund(
        _nra_profile(), 2023,
        IncomeSnapshot(wages=3_000, federal_withholding=300, treaty_exempt_income=5_000),
    )
    labels = _labels(est)
    assert labels[_TREATY_LABEL] == -3_000   # clamped: income components never go negative overall
    assert labels["Taxable income"] == 0
    assert est.point == 300                  # tax 0 -> the whole withholding back
    assert any("CLAMPED" in a for a in est.assumptions)


def test_treaty_exempt_income_combines_with_spouse():
    income = IncomeSnapshot(
        wages=50_000, federal_withholding=5_000, treaty_exempt_income=5_000,
        spouse=IncomeSnapshot(wages=20_000, federal_withholding=1_500, treaty_exempt_income=3_000),
    )
    est = estimate_refund(_mfj_confirmed(), 2023, income)
    labels = _labels(est)
    assert labels[_TREATY_LABEL] == -8_000   # summed across the couple (combined_with_spouse)
    # Resident MFJ: the standard deduction still applies after the exclusion.
    assert est.point == _independent_refund(70_000 - 8_000, 6_500, "married_filing_jointly")
    assert any("does NOT validate treaty eligibility" in a for a in est.assumptions)


# ---------------------------------------------------------------------------
# P-016 (Phase J JF1a): WHERE the treaty-exempt amount is reported turns on the
# residency classification. A nonresident uses Schedule OI item L and the Form
# 1040-NR treaty-exempt line; a resident alien keeping a treaty benefit through a
# saving-clause exception files Form 1040, and Pub 519 ch. 9 has the amount entered
# in parentheses on Schedule 1's other-income line — "8" on the 2019/2020 faces,
# "8z" from 2021. Hypothetical demo fixture: an F-1 student whose exempt-individual
# years ran out, present all year since.
# ---------------------------------------------------------------------------


def _resident_f1_profile(target_year: int) -> Profile:
    first = target_year - 7
    days = {y: 130 if y == first else 365 for y in range(first, target_year + 1)}
    return Profile(
        household=Household(marital_status=_ans("unmarried")),
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(
            visa_timeline=[VisaPeriod(status="F-1", start=date(first, 8, 20), end=None, provenance=US)]
        ),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in days.items()}),
    )


def _treaty_note(est: RefundEstimate) -> str:
    notes = [a for a in est.assumptions if "does NOT validate treaty eligibility" in a]
    assert len(notes) == 1
    return notes[0]


_TREATY_INCOME = IncomeSnapshot(wages=40_000, federal_withholding=4_000, treaty_exempt_income=5_000)


def test_p016_resident_alien_2025_reports_on_schedule_1_line_8z_not_the_1040nr():
    from taxfill_core.residency import classify  # the fixture really is resident-classified

    profile = _resident_f1_profile(2025)
    days = {y: a.value for y, a in profile.residency_facts.days_in_us.items()}
    assert classify(profile.immigration.visa_timeline, days, 2025).classification == "resident"
    note = _treaty_note(estimate_refund(profile, 2025, _TREATY_INCOME))
    assert "Schedule 1 line 8z (Schedule 1 (Form 1040)" in note and "IN PARENTHESES" in note
    assert "Schedule 1" in note and "8z" in note  # the acceptance words
    assert "Exempt income" in note and "Pub 519 ch. 9" in note and "saving-clause" in note
    assert "1040-NR line 1k" not in note
    assert "Schedule OI item L" not in note  # named only as NOT this return's schedule


def test_p016_resident_alien_2020_gets_the_undivided_line_8_not_8z():
    note = _treaty_note(estimate_refund(_resident_f1_profile(2020), 2020, _TREATY_INCOME))
    assert "Schedule 1 line 8 (" in note  # the 2020 face prints the undivided line 8
    assert "8z" not in note
    assert "1040-NR line 1c" not in note


def test_p016_a_declared_us_person_without_a_timeline_is_routed_like_a_resident():
    profile = Profile(
        household=Household(marital_status=_ans("unmarried")), identity=Identity(us_person=_ans(True))
    )
    note = _treaty_note(estimate_refund(profile, 2023, _TREATY_INCOME))
    assert "Schedule 1 line 8z (" in note
    assert "1040-NR line 1k" not in note
    # A declared US person may be a CITIZEN, whom the saving clause keeps taxable: the
    # return is "Form 1040", not "a resident alien's", and the caveat is quoted.
    assert "the return is Form 1040" in note and "resident alien's Form 1040" not in note
    assert "If the filer is a US CITIZEN" in note
    assert "right of the United States to tax its citizens and residents" in note


def test_p016_the_parenthetical_is_paired_with_the_information_return_inclusion():
    # Pub 519 ch. 9 ties the two entries together: income an information return
    # reported as taxable stays on its usual line, and the amount claimed is entered in
    # parentheses — the offset this estimate models (income in full, exemption subtracted).
    note = _treaty_note(estimate_refund(_resident_f1_profile(2025), 2025, _TREATY_INCOME))
    assert "when a W-2, 1042-S, 1099 or other information return reported the income as taxable" in note
    assert "the parenthetical offsets that inclusion, as this estimate models it" in note
    assert "not also entered in parentheses" in note


def test_p016_unknown_residency_and_dual_status_get_both_destinations_conditionally():
    unclassified = Profile(
        household=Household(marital_status=_ans("unmarried")), identity=Identity(us_person=_ans(False))
    )
    for profile, why in (
        (unclassified, "residency is not established"),
        (_dual_status_profile(marital="unmarried"), "dual-status candidate year"),
    ):
        note = _treaty_note(estimate_refund(profile, 2023, _TREATY_INCOME))
        assert why in note
        assert "as a NONRESIDENT" in note and "Form 1040-NR line 1k" in note and "Schedule OI item L" in note
        assert "as a RESIDENT alien" in note and "Schedule 1 line 8z (" in note


def test_p016_nonresident_keeps_schedule_oi_and_the_1040nr_line_for_the_year():
    # The 2023 assertion above stays; 2020's face prints the 1040-NR line as 1c.
    for year, line in ((2023, "1k"), (2020, "1c")):
        note = _treaty_note(
            estimate_refund(
                _nra_profile(), year,
                IncomeSnapshot(wages=18_000, federal_withholding=1_400, treaty_exempt_income=5_000),
            )
        )
        assert "Schedule OI item L" in note and f"Form 1040-NR line {line}" in note
        assert "Schedule 1 (Form 1040)" not in note


def test_p016_the_field_descriptions_carry_the_rule_without_a_typed_line():
    treaty = IncomeSnapshot.model_fields["treaty_exempt_income"].description
    assert "Schedule OI" in treaty and "Schedule 1's other-income line" in treaty and "P-016" in treaty
    assert "line 1k" not in treaty and "8z" not in treaty


def test_retirement_income_taxable_is_the_taxable_amount_not_box_2a():
    # JF1a item 2: for a traditional-IRA distribution or conversion box 2a is the GROSS
    # amount with 2b checked (i1099r 2026), so a filer with basis must not enter it.
    desc = IncomeSnapshot.model_fields["retirement_income_taxable"].description
    assert "TAXABLE" in desc and "ira_pro_rata" in desc
    assert "GROSS" in desc and "2b" in desc
    for code in ("codes N and R", "H (a", "code G"):
        assert code in desc
    # The code-G exceptions, where box 2a IS the taxable amount (i1099r 2026): a direct
    # rollover to a Roth IRA, an in-plan Roth rollover, designated Roth employer contributions.
    assert "roth_conversion" in desc and "in-plan Roth rollover" in desc
    assert "designated Roth matching/nonelective contributions" in desc


# ---------------------------------------------------------------------------
# Phase G (item G1): the estimate cross-checks treaty_exempt_income against the
# per-country treaty knowledge (calc.treaty_benefit) when the profile carries a
# citizenship country with a shipped pack. Advisory only — never a hard block.
# ---------------------------------------------------------------------------


def _nra_profile_with_country(country: str):
    p = _nra_profile()
    return p.model_copy(
        update={"identity": Identity(us_person=_ans(False), citizenship_country=_ans(country))}
    )


def test_treaty_over_limit_fires_the_country_cross_check():
    # China Art. 20(c): $5,000/yr on student wages — $8,000 entered must be flagged
    # (scholarship/abroad components can make it legitimate, so it is an assumption).
    est = estimate_refund(
        _nra_profile_with_country("China"), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, treaty_exempt_income=8_000),
    )
    cross = [a for a in est.assumptions if "EXCEEDS" in a]
    assert len(cross) == 1
    note = cross[0]
    assert "$8,000" in note and "$5,000" in note and "Art. 20(c)" in note
    assert "scholarship" in note.lower()  # confirm-the-breakdown guidance
    assert "treaty_benefit" in note      # points at the calc op for each component
    # NOT a hard block: the exclusion still applies exactly as supplied.
    assert _labels(est)[_TREATY_LABEL] == -8_000
    # The generic trust-the-agent disclosure still rides along.
    assert any("does NOT validate treaty eligibility" in a for a in est.assumptions)


def test_treaty_within_limit_stays_quiet():
    est = estimate_refund(
        _nra_profile_with_country("China"), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, treaty_exempt_income=5_000),
    )
    assert not any("EXCEEDS" in a for a in est.assumptions)
    assert _labels(est)[_TREATY_LABEL] == -5_000


def test_treaty_cross_check_korea_uses_its_own_2000_limit():
    est = estimate_refund(
        _nra_profile_with_country("South Korea"), 2023,  # alias normalization exercised too
        IncomeSnapshot(wages=12_000, federal_withholding=900, treaty_exempt_income=2_500),
    )
    cross = [a for a in est.assumptions if "EXCEEDS" in a]
    assert len(cross) == 1
    assert "$2,000" in cross[0] and "Art. 21(1)(b)(iii)" in cross[0]


def test_treaty_cross_check_india_flags_no_wage_exclusion():
    # India has NO student dollar exclusion — any wages entered as treaty-exempt get
    # the Art. 21(2) deduction-parity explanation, still without hard-blocking
    # (payments from abroad are legitimately exempt under Art. 21(1)).
    est = estimate_refund(
        _nra_profile_with_country("India"), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, treaty_exempt_income=3_000),
    )
    cross = [a for a in est.assumptions if "NOT supported as student WAGES" in a]
    assert len(cross) == 1
    assert "Art. 21(2)" in cross[0] and "standard deduction" in cross[0]
    assert _labels(est)[_TREATY_LABEL] == -3_000


def test_treaty_unknown_country_keeps_the_generic_disclosure_only():
    est = estimate_refund(
        _nra_profile_with_country("Germany"), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, treaty_exempt_income=8_000),
    )
    assert any("does NOT validate treaty eligibility" in a for a in est.assumptions)
    assert not any("EXCEEDS" in a for a in est.assumptions)
    assert not any("NOT supported as student WAGES" in a for a in est.assumptions)


def test_treaty_no_citizenship_on_file_keeps_todays_behavior():
    est = estimate_refund(
        _nra_profile(), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, treaty_exempt_income=8_000),
    )
    assert any("does NOT validate treaty eligibility" in a for a in est.assumptions)
    assert not any("EXCEEDS" in a for a in est.assumptions)


# ---------------------------------------------------------------------------
# Phase G item G2: the dependent-care credit in the estimator (Form 2441),
# cross-checked against the standalone calc op — never magic numbers — plus
# the G6 FICA claim-amount extension.
# ---------------------------------------------------------------------------

from taxfill_core.calc import dependent_care_credit  # noqa: E402

_DC_LABEL = "Less: child and dependent care credit (Form 2441, nonrefundable)"
_DC_2021_LABEL = "Less: child and dependent care credit (2021 — refundable, Form 2441)"


def _hoh_parent(*dependents):
    return Profile(household=Household(
        marital_status=_ans("unmarried"), hoh_qualifying_person=_ans(True),
        filing_status=_ans("head_of_household"), dependents=list(dependents),
    ))


def test_dependent_care_credit_matches_calc_and_is_disclosed():
    profile = _hoh_parent(_kid("Kid", date(2018, 1, 1)))
    est = estimate_refund(
        profile, 2023,
        IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                       dependent_care_expenses=4_000, dependent_care_persons=1),
    )
    labels = _labels(est)
    dc = dependent_care_credit(
        4_000, 1, 60_000, agi=labels["Adjusted gross income (AGI)"],
        filing_status="head_of_household", year=2023,
    )
    assert dc.credit == 600  # 20% x $3,000 cap (AGI over $43,000)
    assert labels[_DC_LABEL] == -dc.credit
    # The honesty disclosures ride along: provider TIN + the untracked box 10.
    note = next(a for a in est.assumptions if "Form 2441" in a and "TIN" in a)
    assert "box 10" in note and "REDUCE" in note
    assert any("i2441--2023" in c.url for c in est.citations)


def test_dependent_care_2021_refundable_joins_the_payments():
    # 2021 ARPA: the credit refunds (abode test assumed + disclosed) — it must
    # appear as a payments line, not capped by the income tax.
    profile = Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")))
    est = estimate_refund(
        profile, 2021,
        IncomeSnapshot(wages=20_000, federal_withholding=500,
                       dependent_care_expenses=9_000, dependent_care_persons=1),
    )
    labels = _labels(est)
    dc = dependent_care_credit(9_000, 1, 20_000, agi=20_000, filing_status="single", year=2021)
    assert dc.refundable is True and dc.credit == 4_000  # 50% x $8,000 ARPA cap
    assert labels[_DC_2021_LABEL] == -dc.credit
    assert _DC_LABEL not in labels
    # The refundable amount exceeds the income tax — proof it wasn't tax-capped.
    assert dc.credit > labels["Income tax"]
    assert any("REFUNDABLE" in a and "abode" in a for a in est.assumptions)


def test_dependent_care_mfs_candidate_zero_is_disclosed_never_silent():
    est = estimate_refund(
        Profile(household=Household(marital_status=_ans("married"))), 2023,
        IncomeSnapshot(wages=80_000, federal_withholding=9_000,
                       dependent_care_expenses=5_000, dependent_care_persons=2),
    )
    # Both candidates computed: MFJ carries the credit, MFS discloses the gate.
    assert any("INELIGIBLE" in a and "married-filing-separately" in a for a in est.assumptions)
    # The MFJ combined-earned-income approximation is disclosed too.
    assert any("BOTH spouses have earned income" in a for a in est.assumptions)


def test_dependent_care_mfj_spouse_split_uses_per_spouse_earned_income():
    # With the spouse snapshot, the LOWER-earning spouse's earned income binds —
    # exactly what the calc op computes with per-spouse figures.
    profile = Profile(household=Household(
        marital_status=_ans("married"), filing_status=_ans("married_filing_jointly"),
        spouse=Spouse(name=_ans("Spouse Q."), tax_id=_ans("123-45-6789")),
    ))
    est = estimate_refund(
        profile, 2023,
        IncomeSnapshot(wages=70_000, federal_withholding=8_000,
                       dependent_care_expenses=6_000, dependent_care_persons=2,
                       spouse=IncomeSnapshot(wages=1_500)),
    )
    labels = _labels(est)
    dc = dependent_care_credit(
        6_000, 2, 70_000, spouse_earned_income=1_500,
        agi=labels["Adjusted gross income (AGI)"],
        filing_status="married_filing_jointly", year=2023,
    )
    assert dc.allowed_expenses == 1_500  # the low-earning spouse binds
    assert labels[_DC_LABEL] == -dc.credit
    # The combined-earned approximation disclosure must NOT fire on the split path.
    assert not any("BOTH spouses have earned income" in a for a in est.assumptions)


def test_dependent_care_expenses_without_persons_rejected_prescriptively():
    with pytest.raises(Exception, match="dependent_care_persons"):
        IncomeSnapshot(wages=50_000, dependent_care_expenses=3_000)


def test_dependent_care_inputs_without_pack_block_disclosed(tmp_path):
    # A pack stripped of tax.dependent_care must disclose the uncomputed credit,
    # never silently drop the supplied expenses.
    import shutil
    from pathlib import Path

    import yaml

    src = Path(__file__).resolve().parents[3] / "knowledge" / "federal" / "2023.yaml"
    raw = yaml.safe_load(src.read_text())
    del raw["tax"]["dependent_care"]
    fed = tmp_path / "federal"
    fed.mkdir()
    (fed / "2023.yaml").write_text(yaml.dump(raw, sort_keys=False))
    shutil.copytree(src.parents[1] / "treaties", tmp_path / "treaties")
    est = estimate_refund(
        _single(), 2023,
        IncomeSnapshot(wages=50_000, federal_withholding=6_000,
                       dependent_care_expenses=3_000, dependent_care_persons=1),
        knowledge_dir=tmp_path,
    )
    assert _DC_LABEL not in _labels(est)
    assert any("NOT computed" in a and "Form 2441" in a for a in est.assumptions)


def test_g6_fica_note_names_the_concrete_claim_amount_and_medicare_gap():
    # G6(c): the FICA disclosure carries the CONCRETE recoverable amount (box 4
    # sum) and discloses that box-6 Medicare is unknown to this snapshot.
    est = estimate_refund(
        _nra_profile(), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400,
                       ss_withheld_by_employer=[1_116, 500]),
    )
    note = next(a for a in est.assumptions if "Form 843" in a)
    assert "AT LEAST" in note and "$1,616" in note              # the box-4 sum
    assert "box-6 Medicare tax" in note and "not tracked" in note
    assert "box 4 + box 6" in note                              # the actual claim amount
    assert any("box 4 + box 6" in c for c in est.what_would_change_it)


def test_canada_de_minimis_cliff_checked_against_total_wages():
    # Final-review fix: Canada Art. XV's $10,000 rule is an ALL-OR-NOTHING cliff on
    # TOTAL US employment remuneration — a partial claim under the threshold must
    # still warn when total wages exceed it.
    profile = _single()
    profile.identity = Identity(citizenship_country=_ans("Canada"))
    est = estimate_refund(
        profile, 2023, IncomeSnapshot(wages=30_000, treaty_exempt_income=8_000, federal_withholding=3_000)
    )
    assert any("ALL-OR-NOTHING" in a and "10,000" in a for a in est.assumptions)
    # Under the cliff with total wages under $10k: no cliff warning.
    ok = estimate_refund(
        profile, 2023, IncomeSnapshot(wages=9_000, treaty_exempt_income=8_000, federal_withholding=500)
    )
    assert not any("ALL-OR-NOTHING" in a for a in ok.assumptions)
    # China control: total wages over $5k is FINE when the claimed amount is within
    # the per-amount limit (China's limit caps the exempt portion, not total wages).
    profile_cn = _single()
    profile_cn.identity = Identity(citizenship_country=_ans("China"))
    cn = estimate_refund(
        profile_cn, 2023, IncomeSnapshot(wages=30_000, treaty_exempt_income=5_000, federal_withholding=3_000)
    )
    assert not any("ALL-OR-NOTHING" in a for a in cn.assumptions)


def test_dependent_care_squeezed_to_zero_is_disclosed():
    # Final-review fix: a computed 2441 credit fully squeezed out by earlier
    # nonrefundable credits must be disclosed, never silently dropped.
    profile = Profile(household=Household(marital_status=_ans("unmarried"),
                                          filing_status=_ans("head_of_household")))
    est = estimate_refund(
        profile, 2023,
        IncomeSnapshot(wages=28_000, federal_withholding=800,
                       dependent_care_expenses=3_000, dependent_care_persons=1,
                       aotc_qualified_expenses=[4_000]),
    )
    assert any("consumed the entire income tax" in a for a in est.assumptions)


def test_dependent_care_zero_earned_spouse_is_disclosed():
    # Final-review fix: the MFJ split with a zero-earned spouse yields a $0 credit —
    # the deemed $250/$500 rule that could restore it must be surfaced.
    profile = Profile(household=Household(marital_status=_ans("married"),
                                          filing_status=_ans("married_filing_jointly")))
    est = estimate_refund(
        profile, 2023,
        IncomeSnapshot(wages=90_000, federal_withholding=10_000,
                       dependent_care_expenses=3_000, dependent_care_persons=1,
                       spouse=IncomeSnapshot()),
    )
    assert any("NO earned income" in a and "deemed" in a for a in est.assumptions)


# ── N-8 / pitfall P-013: the §871(i)(2)(A) bank-deposit-interest exclusion ──────
# The estimator used to tax a nonresident's whole 1099-INT and append an amount-
# less "may OVERTAX" hedge. It now MODELS the exclusion for the characterized
# subset (IncomeSnapshot.bank_deposit_interest) and names the amount in every
# disclosure. Law read on the .gov texts: IRC 871(i)(1)-(3) (uscode.house.gov),
# Pub 519 ch. 3 "Interest Income" and ch. 1 "Nonresident Spouse Treated as a
# Resident", Instructions for Form 1040-NR (2025) line 2b Exceptions 1 and 3.

_DEPOSIT_LABEL = "Less: US bank-deposit interest excluded (IRC 871(i)(2)(A) — not income to a nonresident)"


def _deposit_line(est: RefundEstimate):
    return next((ln for ln in est.composition if ln.slot == "deposit_interest_exclusion"), None)


def test_p013_characterized_deposit_interest_is_excluded_for_a_nonresident():
    # P-013: characterized deposit interest comes off a nonresident's income.
    income = IncomeSnapshot(wages=18_000, federal_withholding=1_400, interest=900, bank_deposit_interest=900)
    est = estimate_refund(_nra_profile(), 2023, income)
    # The registered explanatory ledger slot carries the exclusion (effect 0 — it
    # moves the bottom line only through Total income, like the treaty exclusion).
    line = _deposit_line(est)
    assert line is not None and line.label == _DEPOSIT_LABEL
    assert line.amount == -900 and line.role == "explanatory" and line.effect == 0
    labels = _labels(est)
    assert labels["Total income"] == 18_000          # off BEFORE total income (1040-NR line 2b, Exception 3)
    assert labels["Taxable income"] == 18_000        # 1040-NR: $0 itemized, never the standard deduction
    tax = tax_from_taxable_income(18_000, "single", 2023).tax
    assert labels["Income tax"] == tax and est.point == 1_400 - tax
    assert sum(ln.effect for ln in est.composition) == est.point
    # The same snapshot WITHOUT the character taxes the $900 — the exclusion is
    # worth exactly the tax on it.
    taxed = estimate_refund(_nra_profile(), 2023, income.model_copy(update={"bank_deposit_interest": 0}))
    assert _labels(taxed)["Total income"] == 18_900
    assert est.point - taxed.point == tax_from_taxable_income(18_900, "single", 2023).tax - tax > 0
    # The disclosure names the amount and every pinpoint the exclusion rests on.
    note = next(a for a in est.assumptions if "was EXCLUDED from income" in a)
    assert "$900" in note
    assert "871(i)(1)" in note and "871(i)(2)(A)" in note and "871(i)(3)" in note
    assert "interest on deposits, if such interest is not effectively connected" in note
    assert "Pub 519 ch. 3" in note and "Exception 3 under line 2b" in note   # f1040nr.taxable_interest (JF6c)
    assert "§6013(g)/(h) election" in note and "the election, not the marriage" in note   # rule (c) rides along
    # Only deposit interest was entered, so neither the uncharacterized-interest note
    # nor the FDAP "NOT modeled" note fires, and the old hedge is gone for good.
    assert not any("WITHOUT deposit character" in a for a in est.assumptions)
    assert not any(a.startswith("Nonresident investment income is NOT modeled") for a in est.assumptions)
    assert not any("OVERTAX" in a for a in est.assumptions)


def test_p013_partial_characterization_excludes_only_the_deposit_part():
    # P-013: $900 characterized, $300 not (say, brokerage sweep interest): only the
    # $900 comes off, and the $300 is taxed AND said to be — rule (b), never a guess.
    est = estimate_refund(
        _nra_profile(), 2023,
        IncomeSnapshot(wages=18_000, federal_withholding=1_400, interest=1_200, bank_deposit_interest=900),
    )
    assert _deposit_line(est).amount == -900
    labels = _labels(est)
    assert labels["Total income"] == 18_300
    assert est.point == 1_400 - tax_from_taxable_income(18_300, "single", 2023).tax
    assert any("$900 was EXCLUDED from income" in a for a in est.assumptions)
    rest = next(a for a in est.assumptions if "WITHOUT deposit character" in a)
    assert rest.startswith("$300 of interest")
    assert "taxed as effectively connected ordinary income" in rest
    assert "rerun with that portion in bank_deposit_interest" in rest
    assert "871(h)" in rest and "Schedule NEC" in rest   # the non-deposit path is named, not modeled
    # The uncharacterized remainder is investment income the estimate does not model.
    assert any(a.startswith("Nonresident investment income is NOT modeled") for a in est.assumptions)


def test_p013_resident_control_taxes_all_interest_whatever_its_character():
    # P-013 control: a resident's interest is all taxable, so the field changes
    # NOTHING — no ledger line, no disclosure, the same bottom line as without it.
    income = IncomeSnapshot(wages=18_000, federal_withholding=1_400, interest=900, bank_deposit_interest=900)
    est = estimate_refund(_single(), 2023, income)
    plain = estimate_refund(_single(), 2023, income.model_copy(update={"bank_deposit_interest": 0}))
    assert _deposit_line(est) is None
    assert _labels(est)["Total income"] == 18_900
    assert est.point == plain.point == _independent_refund(18_900, 1_400, "single")
    assert [ln.model_dump() for ln in est.composition] == [ln.model_dump() for ln in plain.composition]
    assert not any("871(i)" in a or "bank_deposit_interest" in a for a in est.assumptions)


def test_p013_uncharacterized_interest_is_taxed_with_the_note():
    # P-013 rule (b): no character entered, so nothing is excluded on the guess that a
    # student's interest is probably from a bank — it is taxed, and the note says how to move it.
    est = estimate_refund(_nra_profile(), 2023, IncomeSnapshot(wages=18_000, federal_withholding=1_400, interest=900))
    assert _deposit_line(est) is None
    assert _labels(est)["Total income"] == 18_900
    assert est.point == 1_400 - tax_from_taxable_income(18_900, "single", 2023).tax
    note = next(a for a in est.assumptions if "WITHOUT deposit character" in a)
    assert note.startswith("$900 of interest")
    assert "IRC 871(i)(2)(A) excludes it" in note and "rerun with that portion in bank_deposit_interest" in note
    assert not any("was EXCLUDED from income" in a for a in est.assumptions)
    assert not any("OVERTAX" in a for a in est.assumptions)


def test_p013_confirmed_mfj_election_taxes_deposit_interest_and_says_why():
    # P-013 rule (c): a nonresident reaches MFJ only through the §6013(g)/(h) election, which treats
    # both spouses as residents for the whole year (Pub 519 ch. 1): the exclusion is
    # OFF and the disclosure says the ELECTION — not the marriage — ended it.
    income = IncomeSnapshot(wages=18_000, federal_withholding=1_400, interest=1_200, bank_deposit_interest=900)
    mfj = estimate_refund(
        _nra_profile(marital="married", filing_status=_ans("married_filing_jointly")), 2023, income
    )
    assert _deposit_line(mfj) is None
    assert _labels(mfj)["Total income"] == 19_200
    election = next(a for a in mfj.assumptions if "was NOT excluded" in a)
    assert "$900 of bank_deposit_interest" in election
    assert "treated for income tax purposes as residents for your entire tax year" in election
    assert "Pub 519 ch. 1" in election and "ELECTION, not the marriage" in election
    assert not any("was EXCLUDED from income" in a for a in mfj.assumptions)
    # The uncharacterized $300 gets the ELECTION variant of its note: under the
    # election character no longer matters, so "871(i)(2)(A) excludes it — rerun"
    # would contradict the disclosure above (the defect this test caught).
    rest = next(a for a in mfj.assumptions if a.startswith("$300 of interest"))
    assert "joint-return figure" in rest and "whatever its character" in rest
    assert "rerun with that portion" not in rest
    assert not any("rerun with that portion in bank_deposit_interest" in a for a in mfj.assumptions)
    # Control — the MARRIAGE alone ends nothing: the same couple, confirmed MFS on
    # Form 1040-NR, keeps the exclusion.
    mfs = estimate_refund(
        _nra_profile(marital="married", filing_status=_ans("married_filing_separately")), 2023, income
    )
    assert _deposit_line(mfs).amount == -900
    assert _labels(mfs)["Total income"] == 18_300
    assert any("$900 was EXCLUDED from income" in a for a in mfs.assumptions)
    assert not any("was NOT excluded" in a for a in mfs.assumptions)


def test_p013_the_scenario_election_path_taxes_deposit_interest_too():
    # compare_scenarios sets the election as the residency fact
    # residency_facts.section_6013_election (P-018), so the elected figure runs under
    # RESIDENT rules and the deposit interest is taxed whatever its character; the MFJ
    # gate in _bottom_line stays as the last line of defense (P-013).
    from taxfill_core.scenarios import compare_scenarios

    profile = _nra_profile(marital="married")
    specs = [
        {"name": "MFS on 1040-NR", "filing_status": "married_filing_separately"},
        {"name": "MFJ + election", "filing_status": "married_filing_jointly", "us_resident_election": True},
    ]
    deposit = IncomeSnapshot(wages=18_000, federal_withholding=1_400, interest=900, bank_deposit_interest=900)
    plain = deposit.model_copy(update={"bank_deposit_interest": 0})
    with_char = {o.name: o.bottom_line for o in compare_scenarios(profile, 2023, deposit, specs).outcomes}
    without = {o.name: o.bottom_line for o in compare_scenarios(profile, 2023, plain, specs).outcomes}
    assert with_char["MFS on 1040-NR"] > without["MFS on 1040-NR"]   # excluded on the 1040-NR
    assert with_char["MFJ + election"] == without["MFJ + election"]  # character irrelevant under the election


def test_p013_bank_deposit_interest_cannot_exceed_interest():
    # P-013: a SUBSET of `interest`, like qualified_dividends of dividends — enter the
    # deposit portion in BOTH fields; more than the total is a contradiction.
    with pytest.raises(ValueError, match=r"bank_deposit_interest \(501\) cannot exceed interest \(500\)"):
        IncomeSnapshot(interest=500, bank_deposit_interest=501)
    with pytest.raises(ValueError, match="bank_deposit_interest"):
        IncomeSnapshot(interest=500, bank_deposit_interest=-1)
    assert IncomeSnapshot(interest=500, bank_deposit_interest=500).bank_deposit_interest == 500
    assert IncomeSnapshot(interest=500).bank_deposit_interest == 0   # optional: default 0
    # The field description carries the three pinpoints an agent needs to fill it.
    desc = IncomeSnapshot.model_fields["bank_deposit_interest"].description
    assert "871(i)(3)" in desc and "871(i)(1)-(2)(A)" in desc
    assert "Pub 519 ch. 3" in desc and "Exception 3" in desc and "§6013(g)/(h)" in desc


def test_p013_combined_with_spouse_sums_deposit_interest():
    # P-013: the spouse combine must carry the new field (it is summed by hand).
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400, interest=1_000, bank_deposit_interest=800,
        spouse=IncomeSnapshot(wages=9_000, federal_withholding=600, interest=700, bank_deposit_interest=700),
    )
    combined = income.combined_with_spouse()
    assert combined.interest == 1_700 and combined.bank_deposit_interest == 1_500
    # The true two-return MFS path excludes the NONRESIDENT primary's deposit interest.
    # This spouse has no facts on file, so their own residency is unknown: the spouse's
    # $700 is taxed on their separate return and the disclosure says why (the exclusion
    # belongs to the payee and is never borrowed from the taxpayer).
    est = estimate_refund(_nra_profile(marital="married"), 2023, income)
    assert _deposit_line(est).amount == -800                      # the primary's own return
    assert _labels(est)["Total income"] == 18_200
    assert any("$800 was EXCLUDED from income" in a for a in est.assumptions)
    assert any("spouse's $700 of bank_deposit_interest was NOT excluded" in a for a in est.assumptions)
    assert any(a.startswith("$200 of interest was entered WITHOUT deposit character") for a in est.assumptions)
    # The joint (election) return sums both and taxes all of it.
    mfj = estimate_refund(_nra_profile(marital="married", filing_status=_ans("married_filing_jointly")), 2023, income)
    assert _deposit_line(mfj) is None
    assert _labels(mfj)["Total income"] == 18_000 + 9_000 + 1_700
    assert any("$1,500 of bank_deposit_interest was NOT excluded" in a for a in mfj.assumptions)


def _nra_spouse():
    return Spouse(us_person=_ans(False), immigration=_nra_immigration(), residency_facts=_nra_residency())


def test_p013_a_nonresident_spouse_keeps_their_own_exclusion():
    # P-013: when the spouse's OWN facts classify nonresident, the spouse's separate
    # return excludes their characterized deposit interest too, and every disclosure
    # names the household amounts — including the spouse's uncharacterized $200.
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400, interest=1_000, bank_deposit_interest=800,
        spouse=IncomeSnapshot(wages=9_000, federal_withholding=600, interest=900, bank_deposit_interest=700),
    )
    est = estimate_refund(_nra_profile(marital="married", spouse=_nra_spouse()), 2023, income)
    assert _deposit_line(est).amount == -800
    assert any("$1,500 was EXCLUDED from income" in a for a in est.assumptions)
    assert any(a.startswith("$400 of interest was entered WITHOUT deposit character") for a in est.assumptions)
    assert not any("spouse's $700 of bank_deposit_interest was NOT excluded" in a for a in est.assumptions)
    # The spouse's exclusion is worth exactly the tax on it on the spouse's own return.
    plain = income.model_copy(update={"spouse": income.spouse.model_copy(update={"bank_deposit_interest": 0})})
    taxed = estimate_refund(_nra_profile(marital="married", spouse=_nra_spouse()), 2023, plain)
    assert est.point > taxed.point


def test_p013_a_us_citizen_spouse_is_taxed_on_their_deposit_interest():
    # P-013 (the J0.4 verifier's blocking repro): the spouse's MFS return used to BORROW
    # the nonresident taxpayer's classification, so a US-citizen spouse's characterized
    # deposit interest was excluded — a $440 understatement on a Form 1040 where it is
    # taxable. The character must not matter for a citizen payee.
    profile = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True)))
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400,
        spouse=IncomeSnapshot(wages=60_000, federal_withholding=6_000, interest=2_000, bank_deposit_interest=2_000),
    )
    est = estimate_refund(profile, 2023, income)
    uncharacterized = estimate_refund(
        profile, 2023, income.model_copy(update={"spouse": income.spouse.model_copy(update={"bank_deposit_interest": 0})})
    )
    assert est.point == uncharacterized.point                 # the citizen's interest is taxed either way
    assert not any("was EXCLUDED from income" in a for a in est.assumptions)
    assert any("spouse's $2,000 of bank_deposit_interest was NOT excluded" in a for a in est.assumptions)


def test_p013_an_unconfirmed_marriage_never_inflates_the_disclosed_amount():
    # P-013 rule (d): the disclosed amount is the one actually excluded. An unconfirmed
    # marriage ignores the spouse snapshot, so only the primary's $800 is named.
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400, interest=1_000, bank_deposit_interest=800,
        spouse=IncomeSnapshot(wages=9_000, interest=700, bank_deposit_interest=700),
    )
    est = estimate_refund(_nra_profile(), 2023, income)
    assert _deposit_line(est).amount == -800
    assert any("$800 was EXCLUDED from income" in a for a in est.assumptions)
    assert not any("$1,500" in a for a in est.assumptions)
    assert any(a.startswith("$200 of interest was entered WITHOUT deposit character") for a in est.assumptions)


def test_p013_p018_the_fdap_note_follows_the_returns_computed_under_nonresident_rules():
    # P-013's J0 guard said the FDAP note must cover every return COMPUTED under the
    # nonresident rules. P-018 (the J0 re-verify follow-up) stopped the US-citizen
    # spouse's separate return from borrowing the taxpayer's nonresident flag, so that
    # return is a Form 1040 — its qualified dividends take the preferential rates, and
    # the FDAP note (which describes a 1040-NR) no longer speaks for it.
    profile = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True)))
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400,
        spouse=IncomeSnapshot(wages=60_000, federal_withholding=6_000, dividends=5_000, qualified_dividends=5_000),
    )
    est = estimate_refund(profile, 2023, income)
    assert not any(a.startswith("Nonresident investment income is NOT modeled") for a in est.assumptions)
    # ... while a nonresident spouse's own 1040-NR still carries it.
    nra_spouse = estimate_refund(_nra_profile(marital="married", spouse=_nra_spouse()), 2023, income)
    assert any(a.startswith("Nonresident investment income is NOT modeled") for a in nra_spouse.assumptions)


def test_p013_a_spouse_of_unknown_residency_is_taxed_with_the_note():
    # P-013 rule (e): a spouse who declares they are not a US person but has no facts
    # that classify them ('conditional') is NOT assumed nonresident.
    profile = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(False)))
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400,
        spouse=IncomeSnapshot(wages=9_000, federal_withholding=600, interest=700, bank_deposit_interest=700),
    )
    est = estimate_refund(profile, 2023, income)
    plain = estimate_refund(
        profile, 2023, income.model_copy(update={"spouse": income.spouse.model_copy(update={"bank_deposit_interest": 0})})
    )
    assert est.point == plain.point
    assert any("spouse's $700 of bank_deposit_interest was NOT excluded" in a for a in est.assumptions)


def test_p013_the_election_figure_carries_no_mfs_spouse_note():
    # P-013: the spouse-taxed note is about the spouse's SEPARATE return; a confirmed-MFJ
    # (election) estimate has no such return, so the note must not appear there.
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400, interest=1_000, bank_deposit_interest=800,
        spouse=IncomeSnapshot(wages=9_000, federal_withholding=600, interest=700, bank_deposit_interest=700),
    )
    mfj = estimate_refund(_nra_profile(marital="married", filing_status=_ans("married_filing_jointly")), 2023, income)
    assert not any("spouse's $" in a and "bank_deposit_interest was NOT excluded" in a for a in mfj.assumptions)


def test_p013_an_unconfirmed_marriage_ignores_even_a_nonresident_spouse():
    # P-013 rule (d): the marriage gate, not the spouse's facts, decides whether the
    # spouse snapshot counts — an unconfirmed marriage never names the spouse's amount.
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400, interest=1_000, bank_deposit_interest=800,
        spouse=IncomeSnapshot(wages=9_000, interest=700, bank_deposit_interest=700),
    )
    est = estimate_refund(_nra_profile(spouse=_nra_spouse()), 2023, income)
    assert any("$800 was EXCLUDED from income" in a for a in est.assumptions)
    assert not any("$1,500" in a for a in est.assumptions)


def test_p013_a_declared_non_us_person_without_facts_is_taxed_with_the_note():
    # P-013 rule (b) for the primary: not a US person, but no facts classify them, so the
    # characterized amount is taxed — and SAID to be, never silently inert.
    profile = Profile(
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
        identity=Identity(us_person=_ans(False)),
    )
    income = IncomeSnapshot(wages=18_000, federal_withholding=1_400, interest=900, bank_deposit_interest=900)
    est = estimate_refund(profile, 2023, income)
    assert _deposit_line(est) is None
    assert any(
        a.startswith("$900 of bank_deposit_interest was taxed as ordinary interest") for a in est.assumptions
    )


def test_p013_the_1099_int_docspec_note_names_the_characterizing_field():
    # P-013 / N-8's extraction half: the 1099-INT note must hand the agent the FIELD that
    # carries the deposit character, and that field must exist on the snapshot —
    # otherwise the agent gets a figure the engine taxes and a warning it may be wrong.
    from taxfill_core.extract import DOC_SPECS

    note = DOC_SPECS["1099-INT"].status_note
    assert "IncomeSnapshot.bank_deposit_interest" in note and "IncomeSnapshot.interest" in note
    assert "bank_deposit_interest" in IncomeSnapshot.model_fields
    assert "871(i)(2)(A)" in note and "the election, not the marriage" in note
    assert "Box 3" in note   # Treasury / savings-bond interest is never a deposit


# ---------------------------------------------------------------------------
# P-018 (Phase J JF5a): the §6013(g)/(h) election is a RESIDENCY fact. Pub 519 ch. 1:
# "If you make this choice, you and your spouse are treated for income tax purposes
# as residents for your entire tax year" — so the elected figure takes resident rules
# (the standard deduction, NIIT, no 871(i)(2)(A) exclusion) on a joint AND a separate
# status, whatever the visa timeline says, while FICA keeps following the day counts
# (IRC 6013(g)(1): chapters 1 and 24 only). And each spouse's separate return follows
# that spouse's OWN classification. Hypothetical demo fixtures: the F-1-from-2020
# timeline above (nonresident for 2023 by the substantial presence test).
# ---------------------------------------------------------------------------

from taxfill_core.calc import niit  # noqa: E402
from taxfill_core.scenarios import ScenarioSpec, _scenario_profile, compare_scenarios  # noqa: E402

_ELECT_MFJ = {"name": "MFJ + election", "filing_status": "married_filing_jointly", "us_resident_election": True}
_MFS_NR = {"name": "MFS on 1040-NR", "filing_status": "married_filing_separately"}
_ELECT_MFS = {"name": "MFS + election", "filing_status": "married_filing_separately", "us_resident_election": True}


def _elected(profile: Profile, spec: dict) -> Profile:
    """The hypothetical profile a scenario runs on (never persisted)."""
    return _scenario_profile(profile, ScenarioSpec.model_validate(spec))


def test_p018_the_roadmap_repro_election_takes_resident_rules_on_a_timeline_fixture():
    # The ROADMAP's JF5a repro, reproduced at 17e7d5c: on this timeline fixture the
    # "election" scenario was -763 (a joint return under 1040-NR rules, deduction $0)
    # against MFS -2,513. The election makes the couple residents, so the joint figure
    # takes the pack's MFJ standard deduction.
    profile = _nra_profile(marital="married")
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000)
    r = compare_scenarios(profile, 2023, income, [_MFS_NR, _ELECT_MFJ])
    outcomes = {o.name: o.bottom_line for o in r.outcomes}
    assert outcomes["MFS on 1040-NR"] == -2_513       # unchanged: the nonresident's own 1040-NR
    mfj_sd = standard_deduction("married_filing_jointly", 2023).amount
    expected = 6_000 - tax_from_taxable_income(60_000 - mfj_sd, "married_filing_jointly", 2023).tax
    assert outcomes["MFJ + election"] == expected != -763
    est = estimate_refund(_elected(profile, _ELECT_MFJ), 2023, income)
    assert est.point == expected
    assert _labels(est)["Less: standard deduction"] == -mfj_sd   # the pack's MFJ figure (27,700)
    assert not any("1040-NR" in ln.label for ln in est.composition)
    assert est.roadmap.returns_and_forms[0] == "Form 1040"
    assert not any("1040-NR" in f for f in est.roadmap.returns_and_forms)
    assert any("How To Make the Choice" in f or "signed by both" in f for f in est.roadmap.returns_and_forms)
    # The caveat says the figure ran UNDER the election, and the worldwide-income and
    # FICA caveats stay.
    caveat = next(a for a in est.assumptions if a.startswith("A §6013(g)/(h) election is recorded"))
    assert "treated for income tax purposes as residents for your entire tax year" in caveat
    assert "WORLDWIDE" in caveat and "chapter 24" in caveat and "3121(b)(19)" in caveat
    assert caveat in est.what_would_change_it
    # The scenario sets the residency fact; it never rewrites the citizenship fact.
    elected = _elected(profile, _ELECT_MFJ)
    assert elected.residency_facts.section_6013_election.value is True
    assert elected.identity.us_person.value is False


def test_p018_niit_is_evaluated_under_the_election_and_skipped_without_it():
    profile = _nra_profile(marital="married")
    income = IncomeSnapshot(wages=240_000, federal_withholding=40_000, interest=30_000)
    elected = estimate_refund(_elected(profile, _ELECT_MFJ), 2023, income)
    niit_line = next(ln for ln in elected.composition if ln.slot == "niit")
    agi = _labels(elected)["Adjusted gross income (AGI)"]
    assert niit_line.amount == niit(30_000, agi, "married_filing_jointly", 2023).niit > 0
    note = next(a for a in elected.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))
    assert "1.1411-2(a)(2)(iii)(B)" in note and "$250,000" in note and "$125,000" in note
    assert "Form 8960, Part I" in note
    # JF5b part 3a: with no spouse snapshot the income cannot be split into each spouse's own
    # figures, so the elected figure stays and the note names what would price the default
    # (the spouse-snapshot case: test_p018_niit_default_the_nonresident_taxpayer_with_a_spouse_snapshot).
    assert "is not priced here" in note and "enter the spouse's own amounts in income.spouse" in note
    # Control: the same filer on Form 1040-NR (no election) owes no NIIT.
    nr = estimate_refund(_elected(profile, _MFS_NR), 2023, income)
    assert not any(ln.slot == "niit" for ln in nr.composition)
    assert not any(a.startswith("NIIT under") for a in nr.assumptions)


def test_p018_the_election_on_a_separate_status_ends_the_deposit_exclusion_too():
    # J0 re-verify follow-up: after the election year "you and your spouse can file joint
    # or separate returns in later years" (Pub 519 ch. 1) — both still residents, so an
    # MFS figure under the election taxes deposit interest and takes the MFS standard
    # deduction. Only the MFJ gate was modeled before.
    profile = _nra_profile(marital="married")
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000, interest=900, bank_deposit_interest=900)
    nr = estimate_refund(_elected(profile, _MFS_NR), 2023, income)
    assert _deposit_line(nr).amount == -900                 # control: 1040-NR MFS keeps it
    el = estimate_refund(_elected(profile, _ELECT_MFS), 2023, income)
    assert _deposit_line(el) is None
    mfs_sd = standard_deduction("married_filing_separately", 2023).amount
    assert _labels(el)["Less: standard deduction"] == -mfs_sd
    assert el.point == 3_000 - tax_from_taxable_income(40_900 - mfs_sd, "married_filing_separately", 2023).tax
    note = next(a for a in el.assumptions if "was NOT excluded" in a)
    assert note.startswith("Under the §6013(g)/(h) election recorded on this profile the $900")
    assert "joint or separate alike" in note and "ELECTION, not the marriage" in note
    assert not any("was EXCLUDED from income" in a for a in el.assumptions)
    caveat = next(a for a in el.assumptions if a.startswith("A §6013(g)/(h) election is recorded"))
    assert "LATER year of a continuing election" in caveat
    r = compare_scenarios(profile, 2023, income, [_MFS_NR, _ELECT_MFS])
    assert {o.name: o.bottom_line for o in r.outcomes}["MFS + election"] == el.point


def test_p018_a_confirmed_joint_status_of_a_nonresident_is_read_as_the_election():
    # A joint return with a nonresident alien exists only under the election (Pub 519,
    # FAQ), so a confirmed MFJ status is never priced under 1040-NR rules — and the
    # estimate asks for the fact to be recorded.
    profile = _nra_profile(marital="married", filing_status=_ans("married_filing_jointly"))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    mfj_sd = standard_deduction("married_filing_jointly", 2023).amount
    assert _labels(est)["Less: standard deduction"] == -mfj_sd
    assert not any("1040-NR" in ln.label for ln in est.composition)
    caveat = next(a for a in est.assumptions if a.startswith("Your filing status is married-filing-jointly"))
    assert "record it as residency_facts.section_6013_election: true" in caveat
    assert "Generally, you cannot file as married filing jointly" in caveat
    # The old "Showing married-filing-separately instead" caveat contradicted a confirmed MFJ.
    assert not any("Showing married-filing-separately instead" in a for a in est.assumptions)


def test_p018_fica_keeps_following_the_day_counts_under_the_election():
    # IRC 6013(g)(1) reaches chapter 1 and chapter 24 only; FICA is chapter 21, so the
    # exempt F-1's withheld-in-error note survives the election.
    profile = _nra_profile(marital="married")
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000, ss_withheld_by_employer=[2_480])
    est = estimate_refund(_elected(profile, _ELECT_MFJ), 2023, income)
    fica = next(a for a in est.assumptions if "Form 843" in a)
    assert "$2,480" in fica and "NOT on the Form 1040" in fica
    assert "chapter 24 (relating to wage withholding)" in fica and "chapter 21" in fica
    assert any("Form 843" in c for c in est.what_would_change_it)


def test_p018_a_us_citizen_spouse_separate_return_takes_the_standard_deduction():
    # J0 re-verify follow-up: the spouse's two-return MFS _bottom_line borrowed the
    # taxpayer's nonresident flag — a US-citizen spouse's Form 1040 got no standard
    # deduction ($3,047 overstated here: $13,850 x 22%). It follows the spouse's own
    # classification now.
    profile = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True)))
    income = IncomeSnapshot(
        wages=18_000, federal_withholding=1_400,
        spouse=IncomeSnapshot(wages=60_000, federal_withholding=6_000),
    )
    est = estimate_refund(profile, 2023, income)
    spouse_line = next(ln for ln in est.composition if ln.slot == "spouse_mfs_return")
    assert spouse_line.amount == _independent_refund(60_000, 6_000, "married_filing_separately")
    own = 1_400 - tax_from_taxable_income(18_000, "married_filing_separately", 2023).tax   # 1040-NR, $0 deduction
    assert est.point == own + spouse_line.amount
    note = next(a for a in est.assumptions if a.startswith("The spouse's separate return was computed under RESIDENT"))
    assert "declared U.S. citizen" in note


def test_p018_a_resident_taxpayers_nonresident_spouse_files_a_1040nr_with_the_exclusion():
    # The reverse direction P-013 listed as not modeled: the spouse's OWN facts classify
    # nonresident, so the spouse's separate return is a 1040-NR ($0 deduction, the
    # deposit exclusion) while the joint candidate taxes everything under the election.
    income = IncomeSnapshot(
        wages=90_000, federal_withholding=9_000,
        spouse=IncomeSnapshot(wages=9_000, federal_withholding=600, interest=1_000, bank_deposit_interest=700),
    )
    est = estimate_refund(_us_filer_married(_nra_spouse()), 2023, income)
    assert {c.status for c in est.comparison.candidates} == {"married_filing_jointly", "married_filing_separately"}
    mfs = next(c for c in est.comparison.candidates if c.status == "married_filing_separately")
    spouse_1040nr = 600 - tax_from_taxable_income(9_300, "married_filing_separately", 2023).tax
    own_1040 = _independent_refund(90_000, 9_000, "married_filing_separately")
    assert mfs.bottom_line == own_1040 + spouse_1040nr
    excluded = next(a for a in est.assumptions if "was EXCLUDED from income" in a)
    assert excluded.startswith("US bank-deposit interest of $700 was EXCLUDED from income on the spouse's separate")
    assert any(a.startswith("On the spouse's separate (married-filing-separately) return, $300 of interest")
               for a in est.assumptions)
    assert any(a.startswith("On the joint-return figure the $700 of bank_deposit_interest was NOT excluded")
               for a in est.assumptions)
    assert any(a.startswith("The spouse's separate return was computed under NONRESIDENT rules")
               for a in est.assumptions)
    assert any(a.startswith("Nonresident investment income is NOT modeled") for a in est.assumptions)
    # The joint candidate is the election posture, so its NIIT evaluation names the
    # chapter 2A second election (Treas. Reg. 1.1411-2(a)(2)(iii)(B)).
    # With a spouse snapshot and NIIT $0 on every reading, the note says so (JF5b part 3a).
    # No election is recorded, so the note names the joint figure as the CANDIDATE (JF5b part 3b).
    assert any(a.startswith("NIIT under the §6013(g)/(h) election — on the married-filing-jointly CANDIDATE, the "
                            "figure IF you make it") and "NIIT is $0 on every reading" in a
               for a in est.assumptions)


def test_p018_the_election_needs_a_citizen_or_resident_spouse_and_a_marriage():
    # Two nonresidents on the recorded facts: the election is not available, and the
    # caveat says so (Pub 519 ch. 1's precondition, quoted).
    profile = _nra_profile(marital="married", spouse=_nra_spouse())
    profile.residency_facts.section_6013_election = _ans(True)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
    caveat = next(a for a in est.assumptions if a.startswith("A §6013(g)/(h) election is recorded"))
    assert "one spouse is a U.S. citizen or a resident alien" in caveat
    assert "NEITHER spouse is a U.S. citizen or resident" in caveat and "NOT available" in caveat
    assert "is suspended for any tax year (after the tax year you made the choice)" in caveat
    # A recorded flag without a confirmed marriage is not applied, and the estimate says so.
    single = _nra_profile()
    single.residency_facts.section_6013_election = _ans(True)
    est_single = estimate_refund(single, 2023, IncomeSnapshot(wages=18_000, federal_withholding=1_400))
    assert est_single.point == 1_400 - tax_from_taxable_income(18_000, "single", 2023).tax   # 1040-NR rules
    assert any("NOT applied" in a and "section_6013_election" in a for a in est_single.assumptions)


def test_p018_the_confirmed_joint_reading_names_a_declined_election_and_a_dual_status_year():
    # A confirmed MFJ status of a nonresident is priced under the election even when the
    # marital status is unanswered (MFJ is itself a statement of marriage) ...
    no_marital = Profile(
        household=Household(filing_status=_ans("married_filing_jointly")),
        identity=Identity(us_person=_ans(False)),
        immigration=_nra_immigration(),
        residency_facts=_nra_residency(),
    )
    est = estimate_refund(no_marital, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    mfj_sd = standard_deduction("married_filing_jointly", 2023).amount
    assert _labels(est)["Less: standard deduction"] == -mfj_sd
    assert not any("1040-NR" in ln.label for ln in est.composition)
    # ... but a recorded DECLINE is the user's explicit fact and beats that reading: the
    # joint status is priced married-filing-separately WITHOUT the election (never a joint
    # figure under nonresident rules), with the contradiction named FIRST.
    declined = _nra_profile(marital="married", filing_status=_ans("married_filing_jointly"))
    declined.residency_facts.section_6013_election = _ans(False)
    est_declined = estimate_refund(declined, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    assert est_declined.filing_status_used == "married_filing_separately"
    assert est_declined.point == 6_000 - tax_from_taxable_income(60_000, "married_filing_separately", 2023).tax
    first = est_declined.assumptions[0]
    assert first.startswith("CONTRADICTION") and "recorded as FALSE (declined)" in first
    assert "Generally, you cannot file as married filing jointly if either spouse was a nonresident alien" in first
    assert "record it as residency_facts.section_6013_election: true" not in first
    # A dual-status year is named as one (the reading covers it too; Pub 519 ch. 1: under
    # the election the chapter 6 dual-status restrictions do not apply).
    dual = _dual_status_profile(filing_status=_ans("married_filing_jointly"))
    est_dual = estimate_refund(dual, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    caveat = next(a for a in est_dual.assumptions if a.startswith("Your filing status is married-filing-jointly"))
    assert "a dual-status year" in caveat
    assert _labels(est_dual)["Less: standard deduction"] == -mfj_sd


def test_p018_a_recorded_election_for_a_citizen_and_nonresident_spouse_prices_both_as_residents():
    # The election recorded by a US-citizen taxpayer married to a nonresident spouse: the
    # spouse's separate return (a later year of a continuing election) is a resident's
    # Form 1040 too — standard deduction, deposit interest taxed.
    profile = _us_filer_married(_nra_spouse())
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    income = IncomeSnapshot(
        wages=90_000, federal_withholding=9_000,
        spouse=IncomeSnapshot(wages=30_000, federal_withholding=2_500, interest=700, bank_deposit_interest=700),
    )
    est = estimate_refund(profile, 2023, income)
    mfs = next(c for c in est.comparison.candidates if c.status == "married_filing_separately")
    spouse_1040 = 2_500 - tax_from_taxable_income(
        30_700 - standard_deduction("married_filing_separately", 2023).amount, "married_filing_separately", 2023
    ).tax
    assert mfs.bottom_line == _independent_refund(90_000, 9_000, "married_filing_separately") + spouse_1040
    # Without the election the same spouse files a 1040-NR ($0 deduction, $700 excluded).
    without = estimate_refund(_us_filer_married(_nra_spouse()), 2023, income)
    mfs_without = next(c for c in without.comparison.candidates if c.status == "married_filing_separately")
    spouse_1040nr = 2_500 - tax_from_taxable_income(30_000, "married_filing_separately", 2023).tax
    assert mfs_without.bottom_line == _independent_refund(90_000, 9_000, "married_filing_separately") + spouse_1040nr
    assert not any("was EXCLUDED from income" in a for a in est.assumptions)
    assert not any(a.startswith("The spouse's separate return was computed under NONRESIDENT") for a in est.assumptions)
    caveat = next(a for a in est.assumptions if a.startswith("A §6013(g)/(h) election is recorded"))
    assert "NOT available" not in caveat          # the citizen taxpayer satisfies the precondition


# ---------------------------------------------------------------------------
# P-018, the adversarial-verify round (2026-09-25): IRC 6013(h) is its own choice,
# IRC 63(c)(6)(A) binds the two separate returns, the year of a spouse's death keeps
# the election, and every disclosure matches what the figure did. Hypothetical demo
# fixtures only.
# ---------------------------------------------------------------------------

from taxfill_core import residency as residency_module  # noqa: E402


def _h1b_arrival_2025(**household_kwargs) -> Profile:
    # A hypothetical H-1B arriving 2025-06-02 (213 days): the SPT is met with a
    # nonresident part before the residency starting date -> a dual-status ARRIVAL year.
    return Profile(
        household=Household(marital_status=_ans("married"), **household_kwargs),
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-1B", start=date(2025, 6, 2), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(0), 2024: _ans(0), 2025: _ans(213)}),
    )


def test_p018_a_dual_status_year_with_a_citizen_spouse_is_the_6013h_choice():
    # Both spouses are U.S. residents or citizens on Dec 31 and the taxpayer was a
    # nonresident on Jan 1: Pub 519 ch. 1, Choosing Resident Alien Status (IRC 6013(h)) —
    # a different statement, one year only, and 1.1411-2(a)(2)(iv) for NIIT.
    profile = _h1b_arrival_2025(filing_status=_ans("married_filing_jointly"), spouse=Spouse(us_person=_ans(True)))
    income = IncomeSnapshot(wages=190_000, federal_withholding=30_000, interest=20_000,
                            spouse=IncomeSnapshot(wages=90_000, federal_withholding=15_000))
    est = estimate_refund(profile, 2025, income)
    caveat = est.residency_caveat
    assert caveat is not None and caveat in est.assumptions
    blob = caveat + " " + " ".join(est.roadmap.returns_and_forms)
    assert "you both qualify to make the choice" in blob                  # the (h) declaration
    assert "enter the name of the\ndual-status spouse(s)" not in blob     # (sanity: quotes are single-line)
    assert "dual-status spouse(s) in the entry space" in blob
    assert "on the last day of your tax year, and that you choose" not in blob   # never the (g) one
    assert "can file joint or separate returns in later years" not in blob
    assert "Neither you nor your spouse can make this choice for any later tax year" in caveat
    assert "only make this choice for 1 year" in caveat
    niit_note = next(a for a in est.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))
    assert "1.1411-2(a)(2)(iv)(B)" in niit_note and "only with respect to income received for the portion" in niit_note
    assert "the nonresident alien spouse will not be subject" not in niit_note     # (iii)(A) is 6013(g)'s
    # JF5b part 3a: the Form 8960 instructions' first-year sentence is 6013(g)'s ((iii)(B)(2)) —
    # (iv)(B)(2) has no such condition — and the (iv)(A) default is priced: your own $760
    # (only your resident-period income counts, which is not recorded: from $0) and the
    # citizen spouse's $0, against the combined $760.
    assert "The election must be made for the first tax year" not in niit_note
    assert "Priced here for IRC 6013(h)" in niit_note and "a default between $0 and $760" in niit_note
    assert niit(20_000, 210_000, "married_filing_separately", 2025).niit == 760
    assert niit(20_000, 300_000, "married_filing_jointly", 2025).niit == 760
    assert (est.low, est.high) == (est.point, est.point + 760)
    assert residency_module.section_6013_kind("dual_status_candidate", "us") == "h"
    # A full-year nonresident with the same citizen spouse is the 6013(g) choice.
    g = estimate_refund(_nra_profile(marital="married", filing_status=_ans("married_filing_jointly"),
                                     spouse=Spouse(us_person=_ans(True))), 2023,
                        IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    assert "on the last day of your tax year, and that you choose" in g.residency_caveat
    assert "you both qualify to make the choice" not in g.residency_caveat
    assert "IRC 6013(g)(3)" in g.residency_caveat        # a continuing election's own test


def test_p018_irc_63c6a_the_two_separate_returns_share_one_deduction_method():
    # IRC 63(c)(6): "(A) a married individual filing a separate return where either spouse
    # itemizes deductions, ... the standard deduction shall be zero"; Pub 501: "You both
    # must use the same method of claiming deductions" / "the method that gives you the
    # lower total tax". The citizen spouse's standard deduction is not free when the
    # nonresident spouse itemizes on Form 1040-NR.
    profile = _nra_profile(marital="married", filing_status=_ans("married_filing_separately"),
                           spouse=Spouse(us_person=_ans(True)))
    mfs = "married_filing_separately"
    sd = standard_deduction(mfs, 2023).amount

    def _pair(wages: int, nra_itemized: int, spouse_wages: int) -> tuple[int, int, int]:
        income = IncomeSnapshot(wages=wages, federal_withholding=4_000, itemized_deductions=nra_itemized,
                                spouse=IncomeSnapshot(wages=spouse_wages, federal_withholding=6_000))
        est = estimate_refund(profile, 2023, income)
        both_itemize = (4_000 - tax_from_taxable_income(wages - nra_itemized, mfs, 2023).tax) + (
            6_000 - tax_from_taxable_income(spouse_wages, mfs, 2023).tax)
        neither = (4_000 - tax_from_taxable_income(wages, mfs, 2023).tax) + (
            6_000 - tax_from_taxable_income(spouse_wages - sd, mfs, 2023).tax)
        return est, both_itemize, neither

    est, both_itemize, neither = _pair(40_000, 3_000, 60_000)
    assert neither > both_itemize and est.point == neither            # forgo $3,000 to keep $13,850
    note = next(a for a in est.assumptions if a.startswith("Married filing separately (two returns)"))
    assert "NEITHER ITEMIZES" in note and "63(c)(6)" in note and "You both must use the same method" in note
    # Itemizing is an election (IRC 63(e)(1)), which is what lets the 1040-NR claim none.
    assert "IRC 63(e)(1)" in note and "no itemized deduction shall be allowed for the taxable year" in note
    assert "claims none of them" in next(a for a in est.assumptions if a.startswith("Nonresident aliens cannot"))
    # A 24%-bracket nonresident with $20,000 itemized against a 12%-bracket spouse: itemizing wins.
    est, both_itemize, neither = _pair(120_000, 20_000, 30_000)   # under the $125,000 MFS 8959 line
    assert both_itemize > neither and est.point == both_itemize       # itemizing wins -> the SD is zero
    note = next(a for a in est.assumptions if a.startswith("Married filing separately (two returns)"))
    assert "BOTH ITEMIZE" in note
    spouse_note = next(a for a in est.assumptions if a.startswith("The spouse's separate return was computed under RESIDENT"))
    assert "the couple itemizes, so the standard deduction is zero" in spouse_note
    # Two resident returns: one spouse's itemizing no longer leaves the other the SD too.
    residents = _us_filer_married(Spouse(us_person=_ans(True)))
    residents.household.filing_status = _ans(mfs)
    r = estimate_refund(residents, 2023, IncomeSnapshot(
        wages=90_000, federal_withholding=9_000, itemized_deductions=20_000,
        spouse=IncomeSnapshot(wages=30_000, federal_withholding=2_500)))
    both_sd = _independent_refund(90_000, 9_000, mfs) + _independent_refund(30_000, 2_500, mfs)
    itemize = (9_000 - tax_from_taxable_income(70_000, mfs, 2023).tax) + (
        2_500 - tax_from_taxable_income(30_000, mfs, 2023).tax)
    assert r.point == max(both_sd, itemize)
    illegal = (9_000 - tax_from_taxable_income(70_000, mfs, 2023).tax) + _independent_refund(30_000, 2_500, mfs)
    assert r.point < illegal                                          # the old per-person max()
    # Two nonresident returns have no standard deduction to lose (IRC 63(c)(6)(B)): nothing
    # is weighed, and each Form 1040-NR keeps its own itemized deductions.
    both = _nra_profile(marital="married", filing_status=_ans(mfs), spouse=_nra_spouse())
    b = estimate_refund(both, 2023, IncomeSnapshot(
        wages=40_000, federal_withholding=4_000, itemized_deductions=3_000,
        spouse=IncomeSnapshot(wages=20_000, federal_withholding=2_000, itemized_deductions=1_000)))
    assert not any(a.startswith("Married filing separately (two returns)") for a in b.assumptions)
    assert b.point == (4_000 - tax_from_taxable_income(37_000, mfs, 2023).tax) + (
        2_000 - tax_from_taxable_income(19_000, mfs, 2023).tax)


def test_p018_a_spouse_of_unknown_residency_is_priced_both_ways():
    # The spouse's separate return never borrows the taxpayer's nonresident flag; with
    # the spouse's own residency unknown the point is a resident's Form 1040 and the
    # range's low end is the Form 1040-NR reading.
    profile = _nra_profile(marital="married", filing_status=_ans("married_filing_separately"),
                           spouse=Spouse(us_person=_ans(False)))
    income = IncomeSnapshot(wages=18_000, federal_withholding=1_400,
                            spouse=IncomeSnapshot(wages=30_000, federal_withholding=2_500))
    est = estimate_refund(profile, 2023, income)
    mfs = "married_filing_separately"
    own = 1_400 - tax_from_taxable_income(18_000, mfs, 2023).tax
    resident_spouse = _independent_refund(30_000, 2_500, mfs)
    nra_spouse = 2_500 - tax_from_taxable_income(30_000, mfs, 2023).tax
    assert est.point == own + resident_spouse
    assert est.low == own + nra_spouse < est.point
    note = next(a for a in est.assumptions if a.startswith("The spouse's own residency is not settled"))
    assert "never by borrowing your classification" in note and f"${-(own + nra_spouse):,}" in note


def test_p018_p013_a_contradictory_joint_status_never_says_excluded():
    # An explicit 'unmarried' with a confirmed MFJ status is not read as the election,
    # and the MFJ gate taxes the deposit interest — so the text must say NOT excluded
    # (P-013 rule (c): the disclosure matches the number).
    profile = _nra_profile(marital="unmarried", filing_status=_ans("married_filing_jointly"))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000, interest=1_200,
                                                        bank_deposit_interest=800))
    assert _deposit_line(est) is None and _labels(est)["Total income"] == 41_200
    assert not any("was EXCLUDED from income" in a for a in est.assumptions)
    assert any(a.startswith("On the joint-return figure the $800 of bank_deposit_interest was NOT excluded")
               for a in est.assumptions)
    assert not any("rerun with that portion in bank_deposit_interest" in a for a in est.assumptions)
    assert any(a.startswith("$400 of interest was entered without deposit character and was taxed on the joint")
               for a in est.assumptions)


def test_p018_the_w7_last_mile_rides_the_election():
    # Eval (o): the W-7 note must ride the §6013 caveat — recording the election (SKILL.md
    # Recipe B2) must not silence it. Pub 519 FAQ: "your nonresident spouse needs an SSN or ITIN".
    profile = _us_filer_married(Spouse(us_person=_ans(False)))
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=90_000, federal_withholding=9_000))
    assert "Form W-7 is filed WITH the return" in est.residency_caveat
    assert "your nonresident spouse needs an SSN or ITIN" in est.residency_caveat
    assert est.residency_caveat in est.what_would_change_it
    with_tin = _us_filer_married(Spouse(us_person=_ans(False), tax_id=_ans("900-70-0000")))
    with_tin.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    assert "W-7" not in estimate_refund(with_tin, 2023, IncomeSnapshot(wages=90_000)).residency_caveat
    # A US-citizen spouse is never sent to W-7.
    citizen = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True)))
    citizen.residency_facts.section_6013_election = _ans(True)
    assert "W-7" not in estimate_refund(citizen, 2023, IncomeSnapshot(wages=60_000)).residency_caveat


def test_p018_the_year_of_a_spouses_death_keeps_the_election():
    # Pub 501: "If your spouse died during the year, you are considered married for the
    # whole year for filing status purposes"; Pub 519, Ending the Choice: death ends it
    # "beginning with the first tax year following the year the spouse died".
    def _widowed(death_year: int) -> Profile:
        profile = _nra_profile(marital="widowed", spouse_death_year=_ans(death_year),
                               filing_status=_ans("married_filing_jointly"), spouse=Spouse(us_person=_ans(True)))
        profile.residency_facts.section_6013_election = _ans(True)
        return profile

    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000, interest=900, bank_deposit_interest=900)
    est = estimate_refund(_widowed(2023), 2023, income)
    mfj_sd = standard_deduction("married_filing_jointly", 2023).amount
    assert _labels(est)["Less: standard deduction"] == -mfj_sd
    assert est.point == 3_000 - tax_from_taxable_income(40_900 - mfj_sd, "married_filing_jointly", 2023).tax
    assert not any("NOT applied" in a for a in est.assumptions)
    assert not any("was EXCLUDED from income" in a for a in est.assumptions)
    assert est.residency_caveat.startswith("A §6013(g)/(h) election is recorded")
    # Two years later the choice has ended: the recorded fact is not applied, and says so.
    later = estimate_refund(_widowed(2021), 2023, income)
    assert any("NOT applied" in a and "widowed during the year" in a for a in later.assumptions)


def test_p018_two_nonresidents_on_a_joint_status_are_told_no_joint_return():
    # The implied reading cannot ask to record an election the facts rule out.
    profile = _nra_profile(marital="married", filing_status=_ans("married_filing_jointly"), spouse=_nra_spouse())
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
    caveat = est.residency_caveat
    assert "record it as residency_facts.section_6013_election: true" not in caveat
    assert ("change the filing status to married-filing-separately — each of you who meets the nonresident "
            "filing requirements files Form 1040-NR") in caveat
    assert "NOT available" in caveat and "rerun without it" not in caveat


def test_p018_a_recorded_election_on_an_unanswered_marital_status_is_one_story():
    # Recorded True, marital status unanswered, MFJ confirmed: the election IS applied
    # (MFJ states the marriage), so no "NOT applied" note and no "record it" request.
    profile = Profile(household=Household(filing_status=_ans("married_filing_jointly")),
                      identity=Identity(us_person=_ans(False)), immigration=_nra_immigration(),
                      residency_facts=_nra_residency())
    profile.residency_facts.section_6013_election = _ans(True)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    assert _labels(est)["Less: standard deduction"] == -standard_deduction("married_filing_jointly", 2023).amount
    assert not any("NOT applied" in a for a in est.assumptions)
    assert "record it as residency_facts" not in est.residency_caveat
    assert "confirm the marital status" in est.residency_caveat


def test_p018_form_8843_stays_on_the_roadmap_under_the_election():
    # Form 8843 (2025), Who Must File: an alien individual "must file Form 8843 to explain
    # the basis of your claim that you can exclude days of presence ... because you: •
    # Were an exempt individual" — the election does not change the day count.
    profile = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True)))
    profile.residency_facts.section_6013_election = _ans(True)
    forms = estimate_refund(profile, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000)).roadmap
    assert forms.returns_and_forms[0] == "Form 1040"
    assert any(f.startswith("Form 8843") and "Were an exempt individual" in f for f in forms.returns_and_forms)
    assert not any("1040-NR" in f for f in forms.returns_and_forms)
    # An H-1B arrival (no exempt days) has nothing for Form 8843 to explain.
    h1b = _h1b_arrival_2025(spouse=Spouse(us_person=_ans(True)))
    h1b.residency_facts.section_6013_election = _ans(True)
    assert not any(f.startswith("Form 8843") for f in estimate_refund(
        h1b, 2025, IncomeSnapshot(wages=60_000)).roadmap.returns_and_forms)


def test_p018_the_niit_note_covers_the_joint_and_the_separate_figure():
    # A recorded election with no confirmed status prices MFJ AND MFS under it. JF5b part 3a:
    # with each spouse's own amounts on file, the joint figure's NIIT is the (iii)(A) default
    # (your own $760 against $125,000; the combined $245,000 is under $250,000), and the
    # separate returns price the spouse who is a nonresident without the election at $0.
    profile = _us_filer_married(_nra_spouse())
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    income = IncomeSnapshot(wages=200_000, federal_withholding=40_000, interest=20_000,
                            spouse=IncomeSnapshot(wages=10_000, dividends=15_000))
    est = estimate_refund(profile, 2023, income)
    note = next(a for a in est.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))
    default = niit(20_000, 220_000, "married_filing_separately", 2023).niit
    assert default == 760 and niit(35_000, 245_000, "married_filing_jointly", 2023).niit == 0
    assert next(ln.amount for ln in est.composition if ln.slot == "niit") == default
    assert "the joint-return figure's NIIT is the DEFAULT" in note and "a default of $760" in note
    assert "And on each separate return here, your spouse — the spouse who is a nonresident without the " \
        "election — owes NIIT $0" in note
    assert "Your separate return owes NIIT $760 on either reading" in note
    assert "1.1411-2(a)(2)(iii)(B)" in note and "and Without" not in note
    # One combined snapshot cannot be split: the unpriced note names income.spouse.
    combined = estimate_refund(profile, 2023, IncomeSnapshot(wages=210_000, federal_withholding=40_000,
                                                             interest=20_000, dividends=15_000))
    unpriced = next(a for a in combined.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))
    assert "the joint-return figure evaluates" in unpriced and "is not priced here" in unpriced
    assert "separate return here evaluates" in unpriced and "may be overstated" in unpriced
    assert unpriced.count("income.spouse") == 2


def test_p018_declining_leaves_head_of_household_open():
    # Pub 501, Considered Unmarried: "You are considered unmarried for head of household
    # purposes if your spouse was a nonresident alien at any time during the year and you
    # don't choose to treat your nonresident spouse as a resident alien."
    declined = _nra_profile(marital="married", filing_status=_ans("married_filing_jointly"))
    declined.residency_facts.section_6013_election = _ans(False)
    caveat = estimate_refund(declined, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000)).residency_caveat
    assert "means no joint return" in caveat and "head of household with another qualifying person" in caveat
    assert "declining means married-filing-separately" not in caveat


def test_p018_the_nonresident_spouse_note_quotes_pub_519_verbatim():
    income = IncomeSnapshot(wages=90_000, federal_withholding=9_000,
                            spouse=IncomeSnapshot(wages=9_000, federal_withholding=600))
    est = estimate_refund(_us_filer_married(_nra_spouse()), 2023, income)
    note = next(a for a in est.assumptions if a.startswith("The spouse's separate return was computed under NONRESIDENT"))
    assert '"Your spouse must file Form 1040-NR"' in note


# ---------------------------------------------------------------------------
# P-018, the second verify round (2026-09-26): a recorded DECLINE is the user's
# explicit fact; an election whose precondition the recorded facts fail is not
# applied (IRC 6013(g)(3)); a recorded election in a dual-status year may be a
# continuing 6013(g) one; the marriage gate never lands the election on a figure
# with no spouse. Hypothetical demo fixtures only.
# ---------------------------------------------------------------------------

_MFS = "married_filing_separately"
_FAQ = "Generally, you cannot file as married filing jointly if either spouse was a nonresident alien"


def _declined(profile: Profile) -> Profile:
    profile.residency_facts = (profile.residency_facts or ResidencyFacts()).model_copy(
        update={"section_6013_election": _ans(False)})
    return profile


def test_p018_a_recorded_decline_drops_the_joint_candidate():
    # Pub 519 FAQ: "If your spouse does not make this choice, you must file a separate
    # return on Form 1040 or 1040-SR. Your spouse must file Form 1040-NR."
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=20_000, federal_withholding=1_000))
    control = estimate_refund(_us_filer_married(_nra_spouse()), 2023, income)
    assert control.filing_status_used == "married_filing_jointly"      # without the fact, MFJ is a candidate
    est = estimate_refund(_declined(_us_filer_married(_nra_spouse())), 2023, income)
    assert est.filing_status_used == _MFS
    assert est.comparison is None or "married_filing_jointly" not in {c.status for c in est.comparison.candidates}
    assert est.low == est.high == est.point
    assert est.point == next(c.bottom_line for c in control.comparison.candidates if c.status == _MFS)
    caveat = est.residency_caveat
    assert "recorded as FALSE (declined)" in caveat and "not a candidate here" in caveat and _FAQ in caveat
    assert not any("shown as a candidate" in a or "If you weigh that election" in a for a in est.assumptions)
    # Pub 501, Considered Unmarried: head of household stays open to the citizen spouse.
    kid = Dependent(name="Demo Kid", relationship="child", provenance=US)
    with_kid = _declined(_us_filer_married(_nra_spouse()))
    with_kid.household.dependents = [kid]
    hoh = estimate_refund(with_kid, 2023, income)
    assert hoh.filing_status_used == _MFS
    assert {c.status for c in hoh.comparison.candidates} == {_MFS, "head_of_household"}
    assert any(a.startswith("The head-of-household figure is your own head-of-household return PLUS")
               for a in hoh.assumptions)


def test_p018_a_recorded_decline_with_a_spouse_of_unknown_residency_says_how_mfj_reopens():
    est = estimate_refund(_declined(_us_filer_married(Spouse(us_person=_ans(False)))), 2023,
                          IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    assert est.filing_status_used == _MFS
    assert "is (or may be) a nonresident alien" in est.residency_caveat
    assert "no election is needed and a joint return is open" in est.residency_caveat


def test_p018_a_decline_beats_a_confirmed_joint_status_in_either_direction():
    # The citizen taxpayer's side: a confirmed MFJ with a declined election and a
    # nonresident spouse is priced as the two separate returns, contradiction first.
    profile = _declined(_us_filer_married(_nra_spouse()))
    profile.household.filing_status = _ans("married_filing_jointly")
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=20_000, federal_withholding=1_000))
    est = estimate_refund(profile, 2023, income)
    spouse_1040nr = 1_000 - tax_from_taxable_income(20_000, _MFS, 2023).tax
    assert est.filing_status_used == _MFS
    assert est.point == _independent_refund(60_000, 6_000, _MFS) + spouse_1040nr
    assert est.assumptions[0].startswith("CONTRADICTION") and _FAQ in est.assumptions[0]
    assert "Correct one of the two facts" in est.assumptions[0]
    assert est.what_would_change_it[0] == est.assumptions[0]


def test_p018_an_election_neither_spouse_can_use_is_not_applied():
    # IRC 6013(g)(3): "any such election shall not apply for any taxable year if neither
    # spouse is a citizen or resident of the United States at any time during such year".
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000, interest=900, bank_deposit_interest=900,
                            spouse=IncomeSnapshot(wages=20_000, federal_withholding=2_000))
    both_nr = (3_000 - tax_from_taxable_income(40_000, _MFS, 2023).tax) + (
        2_000 - tax_from_taxable_income(20_000, _MFS, 2023).tax)
    recorded = _nra_profile(marital="married", spouse=_nra_spouse())
    recorded.residency_facts.section_6013_election = _ans(True)
    est = estimate_refund(recorded, 2023, income)
    assert est.filing_status_used == _MFS and est.point == both_nr        # two Form 1040-NRs
    assert est.roadmap.returns_and_forms[0] == "Form 1040-NR"
    assert any("$900 was EXCLUDED from income" in a for a in est.assumptions)
    caveat = est.residency_caveat
    assert caveat.startswith("A §6013(g)/(h) election is recorded") and "NOT applied" in caveat
    assert ("shall not apply for any taxable year if neither spouse is a citizen or resident of the United States "
            "at any time during such year") in caveat and "Suspending the Choice" in caveat
    assert "on facts not recorded here" in caveat and "prior_filings.return_forms" in caveat  # JF5b wording
    # The joint status of the same couple is not a filing option: priced MFS, named first.
    implied = _nra_profile(marital="married", spouse=_nra_spouse(), filing_status=_ans("married_filing_jointly"))
    blocked = estimate_refund(implied, 2023, income)
    assert blocked.filing_status_used == _MFS and blocked.point == both_nr
    assert blocked.assumptions[0].startswith("CONTRADICTION — the confirmed status married-filing-jointly is not a")
    # A spouse of unknown residency cannot be judged: the election applies as recorded.
    unknown = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(False)))
    unknown.residency_facts.section_6013_election = _ans(True)
    applied = estimate_refund(unknown, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
    assert applied.roadmap.returns_and_forms[0] == "Form 1040"
    assert "one spouse is a U.S. citizen or a resident alien" in applied.residency_caveat


def test_p018_a_recorded_election_in_a_dual_status_year_may_be_a_continuing_6013g():
    # A recorded True cannot tell a new 6013(h) choice from an earlier 6013(g) election
    # still in effect (IRC 6013(g)(3); Pub 519's Note: "If you previously made that choice
    # and it is still in effect, you do not need to make the choice explained here").
    assert residency_module.section_6013_kind("dual_status_candidate", "us", recorded=True) == "either"
    assert residency_module.section_6013_kind("dual_status_candidate", "us") == "h"
    profile = _h1b_arrival_2025(spouse=Spouse(us_person=_ans(True)))
    profile.residency_facts.section_6013_election = _ans(True)
    income = IncomeSnapshot(wages=90_000, federal_withholding=12_000,
                            spouse=IncomeSnapshot(wages=40_000, federal_withholding=4_000))
    est = estimate_refund(profile, 2025, income)
    caveat = est.residency_caveat
    assert "If you previously made that choice and it is still in effect" in caveat
    assert "UNLESS an IRC 6013(g) election made in an earlier year remains in effect" in caveat
    assert "under IRC 6013(h) there is none" not in caveat
    mfs = next(c.bottom_line for c in est.comparison.candidates if c.status == _MFS)
    assert est.low <= mfs <= est.high                                  # 'either' keeps the MFS figure
    assert "No new statement when an earlier IRC 6013(g) election remains" in residency_module.SECTION_6013H_STATEMENT


def test_p018_a_confirmed_mfs_status_is_a_marriage_and_unanswered_is_not_unmarried():
    # Pub 501: "You can choose married filing separately as your filing status if you are married."
    profile = Profile(household=Household(filing_status=_ans(_MFS), spouse=Spouse(us_person=_ans(True))),
                      identity=Identity(us_person=_ans(False)), immigration=_nra_immigration(),
                      residency_facts=_nra_residency())
    profile.residency_facts.section_6013_election = _ans(True)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    assert _labels(est)["Less: standard deduction"] == -standard_deduction(_MFS, 2023).amount
    assert "confirm the marital status" in est.residency_caveat
    bare = Profile(identity=Identity(us_person=_ans(False)), immigration=_nra_immigration(),
                   residency_facts=_nra_residency())
    bare.residency_facts.section_6013_election = _ans(True)
    note = next(a for a in estimate_refund(bare, 2023, IncomeSnapshot(wages=18_000)).assumptions if "NOT applied" in a)
    assert "marital_status is not answered" in note and "not married for the year" not in note


def test_p018_the_election_never_lands_on_a_figure_with_no_spouse():
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000)
    # JF1b.9: the year of a spouse's death is a married year for filing status (Pub 501), so the
    # recorded election applies on the joint candidate — never on a single figure.
    widowed = _nra_profile(marital="widowed", spouse_death_year=_ans(2023), spouse=Spouse(us_person=_ans(True)))
    widowed.residency_facts.section_6013_election = _ans(True)
    est = estimate_refund(widowed, 2023, income)
    assert est.filing_status_used == "married_filing_jointly" and "single" not in {
        c.status for c in (est.comparison.candidates if est.comparison else [])}
    assert est.point == 3_000 - tax_from_taxable_income(
        40_000 - standard_deduction("married_filing_jointly", 2023).amount, "married_filing_jointly", 2023).tax
    assert "RESIDENT rules for both spouses" in est.residency_caveat
    # A confirmed head of household exists only without the election (Pub 501).
    hoh = _nra_profile(marital="married", filing_status=_ans("head_of_household"), spouse=Spouse(us_person=_ans(True)))
    hoh.residency_facts.section_6013_election = _ans(True)
    note = next(a for a in estimate_refund(hoh, 2023, income).assumptions if "NOT applied" in a)
    assert "exists only WITHOUT the election" in note
    assert "neither spouse can make this choice in any later tax year" in note


def test_p018_the_deposit_note_quotes_the_choice_that_applies():
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000, interest=900, bank_deposit_interest=900)
    h = estimate_refund(_h1b_arrival_2025(filing_status=_ans("married_filing_jointly"),
                                          spouse=Spouse(us_person=_ans(True))), 2025, income)
    h_note = next(a for a in h.assumptions if "$900 of bank_deposit_interest was NOT excluded" in a)
    assert "You and your spouse are treated as U.S. residents for the entire year for income tax purposes" in h_note
    assert "for your entire tax year" not in h_note
    g = estimate_refund(_nra_profile(marital="married", filing_status=_ans("married_filing_jointly"),
                                     spouse=Spouse(us_person=_ans(True))), 2023, income)
    g_note = next(a for a in g.assumptions if "$900 of bank_deposit_interest was NOT excluded" in a)
    assert "treated for income tax purposes as residents for your entire tax year" in g_note


def test_p018_the_niit_note_says_what_the_joint_figure_assumes():
    # Treas. Reg. 1.1411-2(a)(2)(iii)(B)(2): the second election is made for the first year
    # the U.S. spouse is subject to NIIT, "without regard to the effect of the section
    # 6013(g) election". The default is not priced, so the note must say so plainly.
    profile = _us_filer_married(_nra_spouse())
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    profile.household.filing_status = _ans("married_filing_jointly")
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=200_000, federal_withholding=40_000, interest=20_000))
    note = next(a for a in est.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))
    assert "ASSUMES the optional SECOND election" in note and "HIGHER or LOWER" in note
    assert "without regard to the effect of the section 6013(g) election" in note
    assert "income.spouse" in note   # JF5b part 3a: what would let the default be priced


# ---------------------------------------------------------------------------
# P-018, the third verify round (2026-09-26): the IRC 6013(g)(3) gate shares intake's
# trust rule; a decline by two nonresidents is never told to "record the election as
# true"; the Suspending-the-Choice quote keeps its condition; compare_scenarios' walk
# always ends on the scenario's own configuration; a married head-of-household
# scenario prices both returns. Hypothetical demo fixtures only.
# ---------------------------------------------------------------------------


def _two_nonresidents(**household_kwargs) -> Profile:
    profile = _nra_profile(marital="married", spouse=_nra_spouse(), **household_kwargs)
    return profile


def test_p018_a_decline_by_two_nonresidents_is_never_told_to_elect():
    # IRC 6013(g)(3): the election "shall not apply for any taxable year if neither spouse is
    # a citizen or resident of the United States at any time during such year".
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000,
                            spouse=IncomeSnapshot(wages=20_000, federal_withholding=2_000))
    for status in (None, _ans("married_filing_jointly")):
        profile = _declined(_two_nonresidents(filing_status=status))
        caveat = estimate_refund(profile, 2023, income).residency_caveat
        assert "not available in any case" in caveat and "shall not apply for any taxable year" in caveat
        assert "record the election as true" not in caveat
        assert "U.S. citizen or resident spouse files" not in caveat        # SECTION_6013_DECLINE's citizen side
    r = compare_scenarios(_declined(_two_nonresidents()), 2023, income, [
        {"name": "MFS", "filing_status": _MFS},
        {"name": "MFJ-no", "filing_status": "married_filing_jointly", "us_resident_election": False},
    ])
    blocked = next(a for a in r.assumptions if a.startswith("Scenario 'MFJ-no' is married-filing-jointly"))
    assert "run it with us_resident_election true" not in blocked and "not available either" in blocked


def test_p018_the_gate_never_asserts_a_nonresident_resting_on_missing_day_counts():
    # The spouse's nonresident answer counts 2021 and 2022 (covered by the H-4 timeline) as 0
    # days: residency.classify itself warns it "may be WRONG", and intake treats it as unknown.
    # So the IRC 6013(g)(3) gate cannot judge it, and the recorded election applies (B3).
    from taxfill_core.intake import _election_in_effect  # noqa: PLC0415
    spouse = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-4", start=date(2021, 1, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(150)}),
    )
    profile = _nra_profile(marital="married", spouse=spouse)
    profile.residency_facts.section_6013_election = _ans(True)
    assert residency_module.nonresident_rests_on_missing_lookback(
        spouse.immigration.visa_timeline, {2023: 150}, 2023)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
    assert est.residency_caveat.startswith("A §6013(g)/(h) election is recorded")
    assert "On the facts recorded here NEITHER spouse" not in est.residency_caveat    # not asserted unmet
    assert "NOT applied" not in est.residency_caveat
    assert _election_in_effect(profile, 2023) is True                    # intake agrees


def test_p018_the_suspending_quote_keeps_its_condition():
    text = residency_module.SECTION_6013_SUSPENDED
    assert ("This means each spouse must file a separate return as a nonresident alien for that year if either "
            "meets the filing requirements for nonresident aliens discussed in chapter 7") in text
    assert "each spouse on Form 1040-NR" not in text


def _citizen_with_f1_spouse(recorded: bool | None = None) -> Profile:
    profile = _us_filer_married(_nra_spouse())
    if recorded is not None:
        profile.residency_facts = ResidencyFacts(section_6013_election=_ans(recorded))
    return profile


_POSTURES = [
    {"name": "MFJ-omit", "filing_status": "married_filing_jointly"},
    {"name": "MFJ-true", "filing_status": "married_filing_jointly", "us_resident_election": True},
    {"name": "MFJ-false", "filing_status": "married_filing_jointly", "us_resident_election": False},
    {"name": "MFS-omit", "filing_status": _MFS},
    {"name": "MFS-true", "filing_status": _MFS, "us_resident_election": True},
]


@pytest.mark.parametrize("recorded", [None, True, False])
@pytest.mark.parametrize("profile_of", [_citizen_with_f1_spouse, None], ids=["citizen+F-1", "F-1+citizen"])
def test_p018_the_walk_telescopes_between_every_election_posture(recorded, profile_of):
    # The round-3 crash: [MFS omitted, MFJ false] and [MFJ omitted, MFS true] raised
    # "the attribution walk ended at X but the scenario computes Y". Every posture as the
    # baseline, against every other one, in both directions of the couple.
    def _profile():
        if profile_of is not None:
            return profile_of(recorded)
        p = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True)))
        if recorded is not None:
            p.residency_facts.section_6013_election = _ans(recorded)
        return p

    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000, interest=1_000, bank_deposit_interest=1_000,
                            spouse=IncomeSnapshot(wages=30_000, federal_withholding=2_500))
    for base in _POSTURES:
        specs = [base] + [p for p in _POSTURES if p is not base]
        r = compare_scenarios(_profile(), 2023, income, specs)
        for d in r.deltas:
            assert sum(s.delta for s in d.input_attribution) == d.delta
        assert r.recommended not in ("MFJ-false",)


def test_p018_a_married_head_of_household_scenario_prices_both_returns():
    # Pub 501, Considered Unmarried: the citizen spouse of a nonresident may file head of
    # household, and the spouse still files their own return — the scenario must price the
    # same two returns estimate_refund does, never the taxpayer's return alone.
    profile = _declined(_us_filer_married(_nra_spouse()))
    profile.household.dependents = [Dependent(name="Demo Kid", relationship="child", provenance=US)]
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=20_000, federal_withholding=5_000))
    est = estimate_refund(profile, 2023, income)
    hoh_candidate = next(c.bottom_line for c in est.comparison.candidates if c.status == "head_of_household")
    r = compare_scenarios(profile, 2023, income, [
        {"name": "MFS", "filing_status": _MFS},
        {"name": "HOH", "filing_status": "head_of_household"},
    ])
    outs = {o.name: o.bottom_line for o in r.outcomes}
    assert outs["HOH"] == hoh_candidate
    assert r.recommended == ("HOH" if outs["HOH"] > outs["MFS"] else "MFS")


def test_p018_a_no_joint_head_of_household_pair_prices_an_unknown_spouse_as_nonresident():
    # On the no-joint path head of household exists only BECAUSE the spouse is a nonresident
    # alien (Pub 501), so a spouse of unknown residency is priced on Form 1040-NR rules there.
    profile = _declined(_us_filer_married(Spouse(us_person=_ans(False))))
    profile.household.dependents = [Dependent(name="Demo Kid", relationship="child", provenance=US)]
    profile.household.filing_status = _ans("head_of_household")
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=20_000, federal_withholding=1_000))
    est = estimate_refund(profile, 2023, income)
    spouse_line = next(ln for ln in est.composition if ln.slot == "spouse_mfs_return")
    nra_spouse_return = 1_000 - tax_from_taxable_income(20_000, _MFS, 2023).tax     # no standard deduction
    assert spouse_line.amount == nra_spouse_return


# ---------------------------------------------------------------------------
# P-018, the fourth verify round (2026-09-27). Hypothetical demo fixtures only.
# ---------------------------------------------------------------------------


def _h4_spouse(days_2023: int) -> Spouse:
    return Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-4", start=date(2021, 1, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(days_2023)}),
    )


def test_p018_a_missing_lookback_year_that_cannot_flip_the_answer_leaves_it_certain():
    # 20 days in 2023 fail the 31-day prong, so no presence in the missing 2021/2022 could make
    # the spouse resident: residency.classify says the answer "does not turn on those years", and
    # the IRC 6013(g)(3) gate treats the couple as two nonresidents (not applied, anywhere).
    from taxfill_core.intake import _election_in_effect, _election_unavailable  # noqa: PLC0415
    profile = _nra_profile(marital="married", spouse=_h4_spouse(20))
    profile.residency_facts.section_6013_election = _ans(True)
    assert residency_module.certain_nonresident(profile.household.spouse.immigration.visa_timeline, {2023: 20}, 2023)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
    assert "NOT applied" in est.residency_caveat and "shall not apply for any taxable year" in est.residency_caveat
    assert _election_unavailable(profile, 2023) is True and _election_in_effect(profile, 2023) is False
    # 150 days could flip it (the round-3 fixture): not certain, so applied as recorded.
    flip = _nra_profile(marital="married", spouse=_h4_spouse(150))
    assert not residency_module.certain_nonresident(flip.household.spouse.immigration.visa_timeline, {2023: 150}, 2023)
    assert residency_module.classify(flip.household.spouse.immigration.visa_timeline, {2023: 150},
                                     2023).nonresident_may_flip is True


def test_p018_a_lived_apart_head_of_household_takes_the_standard_deduction_while_the_spouse_itemizes():
    # Pub 501: "The head of household filing status allows you to choose the standard deduction
    # even if your spouse chooses to itemize deductions."
    profile = _us_filer_married(Spouse(us_person=_ans(True)))
    profile.household.filing_status = _ans("head_of_household")
    profile.household.dependents = [Dependent(name="Demo Kid", relationship="child", provenance=US)]
    income = IncomeSnapshot(wages=90_000, federal_withholding=10_000, itemized_deductions=10_000,
                            spouse=IncomeSnapshot(wages=35_000, federal_withholding=3_000, itemized_deductions=20_000))
    est = estimate_refund(profile, 2023, income)
    own_std = standard_deduction("head_of_household", 2023).amount
    own_line = next(ln for ln in est.composition if ln.slot == "deduction")
    assert own_line.amount == -own_std                                  # the HOH filer's standard deduction
    spouse_line = next(ln for ln in est.composition if ln.slot == "spouse_mfs_return")
    assert spouse_line.amount == 3_000 - tax_from_taxable_income(35_000 - 20_000, _MFS, 2023).tax  # itemizes
    note = next(a for a in est.assumptions if a.startswith("The head-of-household figure is your own"))
    assert "allows you to choose the standard deduction even if your spouse chooses to itemize" in note


def test_p018_the_nonresident_spouse_route_to_head_of_household_computes_no_eitc():
    # Pub 519 ch. 5: "Even if you are considered unmarried for head of household purposes because
    # you are married to a nonresident alien, you may still be considered married for purposes of
    # the earned income credit (EIC)."
    profile = _declined(_us_filer_married(_nra_spouse()))
    profile.household.dependents = [
        Dependent(name="Demo Kid", relationship="child", dob=date(2016, 5, 1), has_ssn=True, provenance=US)
    ]
    income = IncomeSnapshot(wages=22_000, federal_withholding=800,
                            spouse=IncomeSnapshot(wages=9_000, federal_withholding=300))
    profile.household.filing_status = _ans("head_of_household")
    est = estimate_refund(profile, 2023, income)
    assert not any(ln.slot == "eitc" for ln in est.composition)
    # The control: the same citizen's HOH through living apart (a U.S.-person spouse) keeps it.
    control = _us_filer_married(Spouse(us_person=_ans(True)))
    control.household.dependents = profile.household.dependents
    control.household.filing_status = _ans("head_of_household")
    assert any(ln.slot == "eitc" for ln in estimate_refund(control, 2023, income).composition)
    note = next(a for a in est.assumptions if a.startswith("The head-of-household figure is your own"))
    assert "you may still be considered married for purposes of the earned income credit (EIC)" in note


def test_p018_a_head_of_household_spouse_of_unknown_residency_is_bracketed_both_ways():
    profile = _declined(_us_filer_married(Spouse(us_person=_ans(False))))
    profile.household.dependents = [Dependent(name="Demo Kid", relationship="child", provenance=US)]
    profile.household.filing_status = _ans("head_of_household")
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=20_000, federal_withholding=1_000))
    est = estimate_refund(profile, 2023, income)
    note = next(a for a in est.assumptions if a.startswith("The head-of-household figure is your own"))
    assert "on Form 1040-NR rules" in note and "the range also prices the spouse's return on resident rules" in note
    assert est.low < est.high


def test_p018_the_walk_reads_the_election_after_a_year_step():
    # A cross-year walk: the F-1 taxpayer is a nonresident in 2024 (a joint status reads the
    # election) and a resident by the SPT in 2025 (no election needed) — the YEAR step carries
    # that change and says so, instead of a later step claiming it.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2020, 8, 20), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in {
            2020: 130, 2021: 330, 2022: 330, 2023: 330, 2024: 330, 2025: 330}.items()}),
        household=Household(marital_status=_ans("married"), spouse=Spouse(us_person=_ans(True))),
    )
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=30_000, federal_withholding=2_500))
    r = compare_scenarios(profile, 2024, income, [
        {"name": "MFJ-24", "filing_status": "married_filing_jointly", "year": 2024},
        {"name": "MFJ-25", "filing_status": "married_filing_jointly", "year": 2025},
    ])
    steps = r.deltas[0].input_attribution
    assert [s.changed for s in steps] == ["year: 2024 -> 2025 (with it, the us_resident_election reading: True -> False)"]
    # An explicit true on a head-of-household baseline never leaks an election into the walk.
    r = compare_scenarios(profile, 2024, income, [
        {"name": "HOH-true", "filing_status": "head_of_household", "us_resident_election": True},
        {"name": "MFS", "filing_status": _MFS},
    ])
    assert not any("reading" in s.changed for s in r.deltas[0].input_attribution)
    assert r.recommended == "MFS"          # a nonresident alien cannot file as head of household


def test_p018_the_decline_text_keeps_the_filing_requirement_condition():
    assert ("the nonresident spouse, if required to file (Pub 519 ch. 7: \"Nonresident aliens who are required to "
            "file an income tax return should use Form 1040-NR\")") in residency_module.SECTION_6013_DECLINE


def test_p018_confirmed_head_of_household_caveats_fit_the_status():
    # A citizen's confirmed HOH with a nonresident spouse: no 'MFJ is shown as a candidate'.
    citizen = _us_filer_married(_nra_spouse())
    citizen.household.filing_status = _ans("head_of_household")
    caveat = estimate_refund(citizen, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000)).residency_caveat
    assert "shown as a candidate" not in caveat and "only valid by electing" in caveat
    # A nonresident taxpayer's confirmed HOH: Pub 519 ch. 5 says the status is not open.
    nra = _nra_profile(marital="married", filing_status=_ans("head_of_household"))
    caveat = estimate_refund(nra, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000)).residency_caveat
    assert "You cannot file as head of household if you are a nonresident alien" in caveat


def test_p018_intake_and_the_estimate_agree_in_the_year_of_a_spouses_death():
    from taxfill_core.intake import _election_in_effect, intake_checklist  # noqa: PLC0415
    profile = _nra_profile(marital="widowed", spouse=Spouse(us_person=_ans(True)), spouse_death_year=_ans(2023))
    profile.residency_facts.section_6013_election = _ans(True)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
    # JF1b.9: the year of death is married for filing status — both apply the recorded election.
    assert est.filing_status_used == "married_filing_jointly" and _election_in_effect(profile, 2023) is True
    assert not any("NOT applied" in n for n in intake_checklist(profile, tax_year=2023).notes)


# ---------------------------------------------------------------------------
# P-018, the fifth verify round (2026-09-27). Hypothetical demo fixtures only.
# ---------------------------------------------------------------------------


def _kid_with_ssn():
    return Dependent(name="Demo Kid", relationship="child", dob=date(2016, 5, 1), has_ssn=True, provenance=US)


def test_p018_no_eitc_on_the_nonresident_spouse_route_without_a_spouse_snapshot():
    # A nonresident spouse with no U.S. income usually has no snapshot at all: the Pub 519 ch. 5
    # EIC rule must not turn on whether a $0 snapshot was supplied.
    profile = _declined(_us_filer_married(_nra_spouse()))
    profile.household.dependents = [_kid_with_ssn()]
    income = IncomeSnapshot(wages=22_000, federal_withholding=800)
    candidate = estimate_refund(profile, 2023, income)
    assert "head_of_household" in {c.status for c in candidate.comparison.candidates}
    profile.household.filing_status = _ans("head_of_household")
    est = estimate_refund(profile, 2023, income)
    assert not any(ln.slot == "eitc" for ln in est.composition)
    note = next(a for a in est.assumptions if a.startswith("The head-of-household figure is your own"))
    assert "no spouse income snapshot was given" in note and "may still be considered married" in note
    base = _declined(_us_filer_married(_nra_spouse()))
    base.household.dependents = [_kid_with_ssn()]
    r = compare_scenarios(base, 2023, income, [
        {"name": "MFS", "filing_status": _MFS}, {"name": "HOH", "filing_status": "head_of_household"}])
    assert next(o.bottom_line for o in r.outcomes if o.name == "HOH") == est.point


def test_p018_the_no_joint_candidates_price_an_unknown_spouse_on_one_reading():
    # A recorded decline rests on a nonresident in the couple; the citizen taxpayer is not it, so
    # the spouse of unknown residency is the nonresident for MFS and HOH alike, and the range
    # prices the resident reading.
    profile = _declined(_us_filer_married(Spouse(us_person=_ans(False))))
    profile.household.dependents = [_kid_with_ssn()]
    income = IncomeSnapshot(wages=22_000, federal_withholding=800,
                            spouse=IncomeSnapshot(wages=9_000, federal_withholding=300))
    est = estimate_refund(profile, 2023, income)
    cands = {c.status: c.bottom_line for c in est.comparison.candidates}
    assert est.comparison.recommended_status == max(cands, key=cands.get) == "head_of_household"
    assert est.filing_status_used == _MFS                                 # the headline is the first candidate
    spouse_nr = 300 - tax_from_taxable_income(9_000, _MFS, 2023).tax     # Form 1040-NR: no standard deduction
    assert next(ln for ln in est.composition if ln.slot == "spouse_mfs_return").amount == spouse_nr
    note = next(a for a in est.assumptions if a.startswith("The spouse's own residency is not settled"))
    assert "NONRESIDENT rules (Form 1040-NR) for the point estimate — the reading the recorded decline rests on" in note


def test_p018_a_lived_apart_head_of_household_with_no_qualifying_child_computes_no_eitc():
    # Pub 501: "You may be considered unmarried for the purpose of using head of household status
    # but not for other purposes, such as claiming the EIC"; the separated-spouse rule needs a child.
    profile = _us_filer_married(Spouse(us_person=_ans(True)))
    profile.household.hoh_qualifying_person = _ans(True)
    profile.household.filing_status = _ans("head_of_household")
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=11_000, federal_withholding=300,
                                                        spouse=IncomeSnapshot(wages=30_000, federal_withholding=2_500)))
    assert not any(ln.slot == "eitc" for ln in est.composition)
    assert any("not for other purposes, such as claiming the EIC" in a for a in est.assumptions)


def test_p018_a_baseline_false_flag_never_walks_through_an_election_neither_end_has():
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=30_000, federal_withholding=2_500))
    profile = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True)))
    r = compare_scenarios(profile, 2023, income, [
        {"name": "MFJ-false", "filing_status": "married_filing_jointly", "us_resident_election": False},
        {"name": "MFS", "filing_status": _MFS},
    ])
    steps = r.deltas[0].input_attribution
    assert not any(s.changed.startswith("us_resident_election:") for s in steps)
    assert sum(s.delta for s in steps) == r.deltas[0].delta


def test_p018_a_missing_current_year_count_is_never_certain():
    periods = [{"status": "F-1", "start": date(2020, 8, 24)}]
    assert not residency_module.certain_nonresident(periods, {2020: 130, 2021: 330, 2022: 330}, 2023)
    assert residency_module.certain_nonresident(periods, {2020: 130, 2021: 330, 2022: 330, 2023: 330}, 2023)


def test_p018_the_head_of_household_bar_keeps_the_married_nonresident_caveat():
    # Prepended, never replacing: a nonresident married to a citizen still reads the §6013 text,
    # and two nonresidents still read the IRC 6013(g)(3) text.
    to_citizen = _nra_profile(marital="married", filing_status=_ans("head_of_household"),
                              spouse=Spouse(us_person=_ans(True)))
    caveat = estimate_refund(to_citizen, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000)).residency_caveat
    assert caveat.startswith("A nonresident alien cannot file as head of household") and "§6013(g)/(h)" in caveat
    both = _two_nonresidents(filing_status=_ans("head_of_household"))
    caveat = estimate_refund(both, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000)).residency_caveat
    assert "shall not apply for any taxable year" in caveat
    # JF1b.12: the barred status is not priced — the figure is the status the filer can use.
    est = estimate_refund(both, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
    assert est.filing_status_used == "married_filing_separately"
    assert "prices married filing separately instead of the confirmed head_of_household" in est.residency_caveat
    assert not any(a.startswith("The head-of-household figure") for a in est.assumptions)


def test_p018_compare_keys_the_head_of_household_bar_on_the_priced_classification():
    # A declared U.S. person whose visa facts classify nonresident is priced as a nonresident, so
    # the HOH scenario is not recommended — the comparison never contradicts its own caveat.
    profile = _nra_profile(marital="unmarried")
    profile.identity = Identity(us_person=_ans(True))
    profile.household.dependents = [_kid_with_ssn()]
    r = compare_scenarios(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000), [
        {"name": "single", "filing_status": "single"}, {"name": "HOH", "filing_status": "head_of_household"}])
    hoh = next(o for o in r.outcomes if o.name == "HOH")
    assert "cannot file as head of household" in hoh.residency_caveat
    # JF1b.12: the HOH scenario is priced as single (the status the filer can use).
    assert hoh.bottom_line == next(o.bottom_line for o in r.outcomes if o.name == "single")
    assert r.recommended == "single"


# ---------------------------------------------------------------------------
# P-018, the sixth verify round (2026-09-27). Hypothetical demo fixtures only.
# ---------------------------------------------------------------------------


def test_p018_skill_md_names_the_nra_entry_space_key_each_pack_maps():
    # Instructions for Form 1040 (Filing Status): "enter 'NRA' in the entry space below the filing
    # status checkboxes" — the key SKILL.md names must exist in that year's pack.
    from pathlib import Path  # noqa: PLC0415
    root = Path(__file__).resolve().parents[3]
    skill = (root / "skills/claude/SKILL.md").read_text()
    for year, key in ((2023, "filing_status.spouse_or_qualifying_person_name"),
                      (2024, "filing_status.spouse_or_qualifying_person_name"),
                      (2025, "filing_status.mfs_spouse_name")):
        assert f'line: "{key}"' in (root / f"formpacks/federal/{year}/f1040/pack.yaml").read_text()
        assert key in skill
    assert "map no MFS entry space" not in skill


def test_p018_no_assumed_nonresident_spouse_when_the_taxpayers_own_residency_is_unknown():
    # us_person False with no facts: nothing shows the taxpayer is not the nonresident the decline
    # rests on, so the spouse of unknown residency keeps the resident reading (no guess).
    profile = _declined(Profile(identity=Identity(us_person=_ans(False)),
                                household=Household(marital_status=_ans("married"), spouse=Spouse(us_person=_ans(False)))))
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000,
                            spouse=IncomeSnapshot(wages=9_000, federal_withholding=300))
    est = estimate_refund(profile, 2023, income)
    assert not any("the recorded decline rests on a nonresident alien in the couple and you are" in a
                   for a in est.assumptions)


def test_p018_a_dual_status_spouse_is_named_as_such_on_the_assumed_reading():
    spouse = Spouse(us_person=_ans(False), immigration=Immigration(
        visa_timeline=[VisaPeriod(status="H-1B", start=date(2023, 3, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2021: _ans(0), 2022: _ans(0), 2023: _ans(300)}))
    profile = _declined(_us_filer_married(spouse))
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=40_000, federal_withholding=4_000, interest=900,
                                                  bank_deposit_interest=900))
    text = " ".join(estimate_refund(profile, 2023, income).assumptions)
    assert "the spouse's own facts show a dual-status year" in text
    assert "the spouse of unknown residency" not in text and "residency is not on file" not in text


def test_p018_the_head_of_household_pair_discloses_the_spouses_deposit_exclusion():
    # P-013 rule (c): the text matches the number — the spouse's 1040-NR return inside the HOH
    # figure excludes the deposit interest, so the disclosure names it.
    profile = _declined(_us_filer_married(_nra_spouse()))
    profile.household.dependents = [_kid_with_ssn()]
    profile.household.filing_status = _ans("head_of_household")
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=9_000, federal_withholding=300, interest=700,
                                                  bank_deposit_interest=700))
    est = estimate_refund(profile, 2023, income)
    assert any(a.startswith("US bank-deposit interest of $700 was EXCLUDED") for a in est.assumptions)


def test_p018_the_lived_apart_eitc_child_gate_starts_in_2021():
    # Before the IRC 32(d)(2) separated-spouse rule (TY2021), a lived-apart head of household was
    # unmarried for the EITC under IRC 7703(b), so the qualifying-child gate does not apply.
    profile = _us_filer_married(Spouse(us_person=_ans(True)))
    profile.household.hoh_qualifying_person = _ans(True)
    profile.household.filing_status = _ans("head_of_household")
    income = IncomeSnapshot(wages=11_000, federal_withholding=300,
                            spouse=IncomeSnapshot(wages=30_000, federal_withholding=2_500))
    assert any(ln.slot == "eitc" for ln in estimate_refund(profile, 2020, income).composition)
    assert not any(ln.slot == "eitc" for ln in estimate_refund(profile, 2023, income).composition)


def test_p018_the_year_of_death_reason_is_the_6013g3_one_when_unavailable():
    profile = _nra_profile(marital="widowed", spouse=_nra_spouse(), spouse_death_year=_ans(2023))
    profile.residency_facts.section_6013_election = _ans(True)
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
    note = next(a for a in est.assumptions if "it was NOT applied" in a)
    assert "shall not apply for any taxable year" in note and "confirm married_filing_jointly" not in note


# ---------------------------------------------------------------------------
# P-018 / JF5b part 1: the prior-year residency fact (PriorFilings.return_forms) and a
# nonresident answer that may flip, on the pricing path. Treas. Reg. 301.7701(b)-4(e)(1):
# a resident "during any part of the preceding calendar year" who "is a United States
# resident for any part of the current year will be considered to be taxable as a resident
# at the beginning of the current year". Hypothetical timelines and amounts only.
# ---------------------------------------------------------------------------

from taxfill_core.schemas.profile import PriorFilings  # noqa: E402


def _prior(forms: dict[int, str]) -> PriorFilings:
    return PriorFilings(return_forms={y: _ans(f) for y, f in forms.items()})


def _visa_profile(periods, days, *, prior=None, marital="unmarried", **household_kwargs) -> Profile:
    return Profile(
        identity=Identity(us_person=_ans(False)),
        household=Household(marital_status=_ans(marital), **household_kwargs),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status=s, start=start, end=end, provenance=US) for s, start, end in periods
        ]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in days.items()}),
        prior_filings=_prior(prior) if prior is not None else None,
    )


_TRUNCATED_F1 = [("F-1", date(2021, 8, 20), date(2025, 9, 30)), ("H-1B", date(2025, 10, 1), None)]
_FULL_F1 = [("F-1", date(2019, 8, 20), date(2025, 9, 30)), ("H-1B", date(2025, 10, 1), None)]
_SWITCH_APRIL = [("F-1", date(2021, 8, 20), date(2025, 3, 31)), ("H-1B", date(2025, 4, 1), None)]
_DAYS_2021 = {2025: 365, 2024: 366, 2023: 365, 2022: 365, 2021: 130}
_DAYS_2019 = {**_DAYS_2021, 2021: 365, 2020: 366, 2019: 130}
_WAGES = IncomeSnapshot(wages=60_000, federal_withholding=8_000, ss_withheld_by_employer=[3_720])


def _resident_single(wages: int, withheld: int, year: int = 2025) -> int:
    return withheld - tax_from_taxable_income(wages - standard_deduction("single", year).amount, "single", year).tax


def _nonresident_single(wages: int, withheld: int, year: int = 2025) -> int:
    return withheld - tax_from_taxable_income(wages, "single", year).tax


def test_p018_truncated_f1_with_a_prior_1040_puts_the_contradiction_first():
    today = estimate_refund(_visa_profile(_TRUNCATED_F1, _DAYS_2021), 2025, _WAGES)
    est = estimate_refund(_visa_profile(_TRUNCATED_F1, _DAYS_2021, prior={2024: "1040"}), 2025, _WAGES)
    assert est.point == today.point == _nonresident_single(60_000, 8_000)       # still priced as the 1040-NR
    first = est.assumptions[0]
    assert first.startswith("CONTRADICTION — a judgment about whether the recorded facts are complete")
    assert est.what_would_change_it[0] == first
    assert "NOT definitive" in first and not any("is definitive" in a for a in est.assumptions)
    assert "makes 2024 itself a FULLY exempt-individual year" in first
    # The resident reading of the same inputs is bracketed: from January 1, as a prior-year resident.
    resident = _resident_single(60_000, 8_000)
    assert est.high == resident and est.low == est.point
    assert f"single: +${resident:,}" in first and "you would then be a resident from January 1" in first
    # Without the fact nothing changes (the defect's shape: no contradiction, no range).
    assert today.low == today.high == today.point
    assert not any(a.startswith("CONTRADICTION") for a in today.assumptions)


def test_p018_full_history_with_a_prior_1040_is_a_full_year_resident():
    est = estimate_refund(_visa_profile(_FULL_F1, _DAYS_2019, prior={2024: "1040"}), 2025, _WAGES)
    assert est.point == est.low == est.high == _resident_single(60_000, 8_000)
    assert "Less: standard deduction" in _labels(est)                        # the standard deduction applied
    assert est.residency_caveat is None or "DUAL-STATUS" not in est.residency_caveat
    assert not any("DUAL-STATUS" in a for a in est.assumptions)
    assert not any("FICA-EXEMPT" in a for a in est.assumptions)             # no withheld-in-error note
    assert est.roadmap.returns_and_forms == ["Form 1040"]
    assert any(a.startswith("Residency: a resident from January 1 of 2025") for a in est.assumptions)


def test_p018_a_prior_1040_removes_the_dual_status_flag_and_prices_a_full_year_resident():
    flagged = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021), 2025, _WAGES)
    assert "DUAL-STATUS" in flagged.residency_caveat
    est = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021, prior={2024: "1040"}), 2025, _WAGES)
    assert est.residency_caveat is None
    assert not any("DUAL-STATUS" in a for a in est.assumptions)
    assert "Less: standard deduction" in _labels(est) and est.point == _resident_single(60_000, 8_000)
    assert est.roadmap.returns_and_forms == ["Form 1040"]
    # 2024 is an exempt F-1 year on this timeline, so the FICA note appears only conditionally (the CHECK).
    fica = [a for a in est.assumptions if "FICA-EXEMPT" in a]
    assert fica and all(a.startswith("If the CHECK THE PRIOR-YEAR RETURN note's reading (b) holds") for a in fica)
    note = next(a for a in est.assumptions if a.startswith("Residency: a resident from January 1 of 2025"))
    assert "'1040' (prior_filings.return_forms)" in note and "Treas. Reg. 301.7701(b)-4(e)(1)" in note
    # This timeline makes 2024 an exempt F-1 year, so the recorded 1040 is flagged first (a judgment).
    assert est.assumptions[0].startswith("CHECK THE PRIOR-YEAR RETURN")
    # A dual_status prior return reads the same way ("during any part of the preceding calendar year").
    dual = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021, prior={2024: "dual_status"}), 2025, _WAGES)
    assert dual.residency_caveat is None and dual.point == est.point


def test_p018_the_prior_year_fact_reads_only_the_preceding_year():
    base = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021), 2025, _WAGES).model_dump()
    for prior in ({2023: "1040"}, {2023: "1040-NR"}, {}):
        other = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021, prior=prior), 2025, _WAGES).model_dump()
        assert other == base, prior
    # A recorded 'not_filed' leaves the figures unchanged; the text only names what is recorded.
    nf = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021, prior={2024: "not_filed"}), 2025, _WAGES)
    assert (nf.point, nf.low, nf.high) == (base["point"], base["low"], base["high"])
    assert "recorded as 'not_filed', which does not settle 2024's residency" in nf.residency_caveat
    # The PRECEDING year's Form 1040-NR is read (JF5b part 2): it closes the prior-year route to
    # the full-year-resident figure, so this unmarried filer's range collapses onto the same
    # dual-status point, which an unknown prior year keeps bracketed.
    nr = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021, prior={2024: "1040-NR"}), 2025, _WAGES)
    assert nr.point == base["point"] and nr.low == nr.high == nr.point
    assert base["high"] > base["point"] == base["low"]


def test_p018_a_prior_year_election_return_is_not_read_as_residency():
    base = estimate_refund(_visa_profile(_TRUNCATED_F1, _DAYS_2021), 2025, _WAGES)
    est = estimate_refund(
        _visa_profile(_TRUNCATED_F1, _DAYS_2021, prior={2024: "1040_with_6013_election"}), 2025, _WAGES)
    assert (est.low, est.high, est.point) == (base.low, base.high, base.point)
    assert not any(a.startswith("CONTRADICTION") for a in est.assumptions)
    note = next(a for a in est.assumptions if a.startswith("Your 2024 return is recorded as a joint Form 1040"))
    assert "a judgment" in note and "record the days in the U.S. for 2024, 2023 and 2022" in note


def test_p018_a_nonresident_answer_that_may_flip_brackets_the_resident_reading():
    periods = [("H-1B", date(2023, 1, 1), None)]
    income = IncomeSnapshot(wages=60_000, federal_withholding=8_000)
    est = estimate_refund(_visa_profile(periods, {2025: 120}), 2025, income)
    nra, resident = _nonresident_single(60_000, 8_000), _resident_single(60_000, 8_000)
    assert est.point == nra and (est.low, est.high) == (min(nra, resident), max(nra, resident))
    first = est.assumptions[0]
    assert first.startswith("IMPORTANT — this nonresident result may be WRONG") and est.what_would_change_it[0] == first
    assert "provide day counts for 2023, 2024" in first                     # the missing years and what to record
    assert "if real presence in 2023 and 2024 meets the substantial presence test" in first
    assert "so this full-year figure is the favorable bound" in first and f"single: +${resident:,}" in first
    assert "prior_filings.return_forms" in first                            # the unknown prior year, named
    # Supplying the years settles it: no warning, no bracket.
    settled = estimate_refund(_visa_profile(periods, {2025: 120, 2024: 0, 2023: 0}), 2025, income)
    assert settled.low == settled.high == settled.point == nra
    assert not any("may be WRONG" in a for a in settled.assumptions)


def _citizen_married_to(spouse_periods, spouse_days) -> Profile:
    spouse = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status=s, start=start, end=end, provenance=US) for s, start, end in spouse_periods
        ]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in spouse_days.items()}),
    )
    return _us_filer_married(spouse)


def test_p018_a_spouse_answer_that_may_flip_brackets_the_spouse_resident_reading():
    income = IncomeSnapshot(wages=90_000, federal_withholding=12_000,
                            spouse=IncomeSnapshot(wages=30_000, federal_withholding=3_000))
    periods = [("H-1B", date(2023, 1, 1), None)]
    est = estimate_refund(_citizen_married_to(periods, {2025: 120}), 2025, income)
    std = standard_deduction(_MFS, 2025).amount
    self_mfs = 12_000 - tax_from_taxable_income(90_000 - std, _MFS, 2025).tax
    spouse_nr = 3_000 - tax_from_taxable_income(30_000, _MFS, 2025).tax
    spouse_res = 3_000 - tax_from_taxable_income(30_000 - std, _MFS, 2025).tax
    mfs = next(c for c in est.comparison.candidates if c.status == _MFS)
    assert mfs.bottom_line == self_mfs + spouse_nr                           # the point: the spouse's 1040-NR
    assert est.low <= self_mfs + spouse_res <= est.high                      # the spouse-resident reading
    note = next(a for a in est.assumptions if a.startswith("The SPOUSE's own nonresident classification may be WRONG"))
    assert "2023 and 2024" in note and "favorable bound" in note
    assert f"{'+' if self_mfs + spouse_res >= 0 else '-'}${abs(self_mfs + spouse_res):,}" in note
    assert note in est.what_would_change_it
    # Not double-bracketed: the unknown-spouse bracket does not fire on a classified spouse.
    assert not any("The spouse's own residency is not settled" in a for a in est.assumptions)
    settled = estimate_refund(_citizen_married_to(periods, {2025: 120, 2024: 0, 2023: 0}), 2025, income)
    assert not any("SPOUSE's own nonresident classification may be WRONG" in a for a in settled.assumptions)


def test_p018_a_prior_year_resident_is_never_a_certain_nonresident_at_the_election_gate():
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000, spouse=IncomeSnapshot(wages=20_000))
    blocked = _nra_profile(marital="married", spouse=_nra_spouse())
    blocked.residency_facts.section_6013_election = _ans(True)
    assert "NOT applied" in estimate_refund(blocked, 2023, income).residency_caveat   # both certain nonresidents
    carried = _nra_profile(marital="married", spouse=_nra_spouse())
    carried.residency_facts.section_6013_election = _ans(True)
    carried.prior_filings = _prior({2022: "1040"})
    est = estimate_refund(carried, 2023, income)
    assert "NOT applied" not in est.residency_caveat and est.roadmap.returns_and_forms[0] == "Form 1040"
    assert est.assumptions[0].startswith("CONTRADICTION")                   # the taxpayer's answer, named first


# JF5b part 1, the adversarial verify's fixes (2026-09-27). Hypothetical timelines only.

def test_p018_a_prior_1040_the_timeline_cannot_support_is_checked_first():
    # An F-1 student in an exempt 2024 who filed a Form 1040 by mistake: resident from January 1
    # stays the classification (the recorded fact), but the flag names why the facts disagree.
    est = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021, prior={2024: "1040"}), 2025, _WAGES)
    first = est.assumptions[0]
    assert first.startswith("CHECK THE PRIOR-YEAR RETURN — a judgment about the recorded facts")
    assert "makes 2024 itself a FULLY exempt-individual year" in first
    assert "which splits 2025 (a dual-status year) unless that is January 1" in first
    # A consistent full history carries no such flag.
    full = estimate_refund(_visa_profile(_FULL_F1, _DAYS_2019, prior={2024: "1040"}), 2025, _WAGES)
    assert not any(a.startswith("CHECK THE PRIOR-YEAR RETURN") for a in full.assumptions)


def test_p018_a_prior_year_resident_departing_mid_year_is_told_the_ending_date_rule():
    # IRC 7701(b)(2)(B): only the START of the year is settled by the prior-year residency.
    periods = [("F-1", date(2019, 8, 20), date(2023, 12, 31)), ("H-1B", date(2024, 1, 1), date(2025, 9, 30))]
    est = estimate_refund(_visa_profile(periods, _DAYS_2019, prior={2024: "1040"}), 2025, _WAGES)
    note = next(a for a in est.assumptions if a.startswith("Residency: a resident from January 1 of 2025"))
    assert "no arrival split" in note and "no nonresident part" not in note
    assert "only if IRC 7701(b)(2)(B) and Treas. Reg. 301.7701(b)-4(b)(2) are met" in note
    assert "the last day of physical presence in 2025" in note


def test_p018_the_contradiction_bracket_is_the_incomplete_timeline_reading_only():
    est = estimate_refund(_visa_profile(_TRUNCATED_F1, _DAYS_2021, prior={2024: "1040"}), 2025, _WAGES)
    first = est.assumptions[0]
    assert "the timeline is incomplete (reading (1) above)" in first
    assert "readings (1) and (2)" not in first and "under readings (2) and (3) the Form 1040-NR point stands" in first
    # The FICA withheld-in-error note is conditional on the nonresident answer standing.
    fica = next(a for a in est.assumptions if "FICA-EXEMPT" in a)
    assert fica.startswith("If the nonresident answer stands (see the first note): ")


# ---------------------------------------------------------------------------
# P-018 / P-013 rule (f) — JF5b part 2: the dual-status year. Pub 519 (2025) ch. 6,
# Restrictions for Dual-Status Taxpayers: "You cannot use the standard deduction allowed on
# Form 1040 or 1040-SR. However, you can itemize any allowable deductions." The point prices
# the restrictions; the range's other end is the full-year-resident figure where a route could
# make it lawful. Treas. Reg. 1.871-13(a)(1) splits the deposit interest at the residency
# starting date. Every expected value is an independent calc recomputation. Hypothetical data.
# ---------------------------------------------------------------------------

from taxfill_core.calc import education_credits  # noqa: E402

_H1B_2025 = [("H-1B", date(2025, 3, 1), None)]
_H1B_2025_DAYS = {2025: 306, 2024: 0, 2023: 0}


def _dual_2025(**kwargs) -> Profile:
    return _visa_profile(_H1B_2025, _H1B_2025_DAYS, **kwargs)


def _signed(value: int) -> str:
    return f"{'+' if value >= 0 else '-'}${abs(value):,}"


def _tax(taxable: int, status: str, year: int) -> int:
    return tax_from_taxable_income(max(0, taxable), status, year).tax


def _sd(status: str, year: int) -> int:
    return standard_deduction(status, year).amount


def test_p018_dual_status_acceptance_h1b_arrival_2026_prices_the_range():
    # The ROADMAP acceptance: H-1B arrival 2026-03-01 (306 days) -> the low end has deduction 0,
    # the high end the standard deduction, and the assumption names the range.
    from taxfill_core.residency import classify

    days = {2026: 306, 2025: 0, 2024: 0}
    assert classify([{"status": "H-1B", "start": "2026-03-01", "end": None}], days, 2026).classification == (
        "dual_status_candidate")
    est = estimate_refund(
        _visa_profile([("H-1B", date(2026, 3, 1), None)], days), 2026,
        IncomeSnapshot(wages=60_000, federal_withholding=8_000),
    )
    low_end = 8_000 - _tax(60_000, "single", 2026)
    high_end = 8_000 - _tax(60_000 - _sd("single", 2026), "single", 2026)
    assert (est.point, est.low, est.high) == (low_end, low_end, high_end) and low_end < high_end
    deduction = next(line for line in est.composition if line.slot == "deduction")
    assert deduction.amount == 0 and "dual-status year — no standard deduction: Pub 519 ch. 6" in deduction.label
    caveat = est.residency_caveat
    assert caveat in est.assumptions and caveat in est.what_would_change_it
    assert "The range ALSO prices the full-year-resident figure" in caveat and f"single: {_signed(high_end)}" in caveat
    assert "(i) you were a U.S. resident during 2025" in caveat and "record the return you filed for 2025" in caveat
    assert "(iii) the dates on the visa timeline are wrong" in caveat and "(ii)" not in caveat   # unmarried
    assert not any(a.startswith("Standard deduction assumed") for a in est.assumptions)
    assert any("the residency reading named in these notes may keep a range of its own" in a for a in est.assumptions)


def test_p018_dual_status_caveat_names_the_restrictions_and_the_approximation():
    est = estimate_refund(_dual_2025(), 2025, IncomeSnapshot(wages=60_000, federal_withholding=8_000))
    caveat = est.residency_caveat
    # JF1b.2: an unmarried filer's caveat never names the election (it needs a spouse).
    assert "DUAL-STATUS" in caveat and "6013" not in caveat
    assert "NO standard deduction" in caveat and "However, you can itemize any allowable deductions." in caveat
    assert "no joint return and no head of household" in caveat
    assert "single rates — an inference: ch. 6 names the rate column only for a married filer" in caveat
    assert "IRC 32(c)(1)(D), 25A(g)(7), 22(f)" in caveat and "credit for the elderly or the disabled" in caveat
    assert "FULL-YEAR approximation" in caveat and "Form 1040 + Form 1040-NR" in caveat
    assert "is subject to the flat 30% rate or lower treaty rate" in caveat
    assert "NIIT" not in caveat   # no investment income: nothing to overstate
    # The roadmap's dual-status step names the credit bars too.
    step = next(f for f in est.roadmap.returns_and_forms if f.startswith("Dual-status restrictions"))
    assert "NO earned income credit, education credits (AOTC/LLC) or credit for the elderly or the disabled" in step
    # A married filer: the married-filing-separately column, quoted.
    married = estimate_refund(
        _dual_2025(marital="married"), 2025, IncomeSnapshot(wages=60_000, federal_withholding=8_000))
    assert married.filing_status_used == "married_filing_separately"
    assert "\"must use the Tax Table column or Tax Computation Worksheet for married filing separately\"" in (
        married.residency_caveat)
    assert "no §6013(g)/(h) election is recorded" in married.residency_caveat


def test_p018_dual_status_unmarried_with_a_prior_1040nr_has_no_route_to_the_standard_deduction():
    income = IncomeSnapshot(wages=60_000, federal_withholding=8_000)
    est = estimate_refund(_dual_2025(prior={2024: "1040-NR"}), 2025, income)
    point = 8_000 - _tax(60_000, "single", 2025)
    assert est.low == est.high == est.point == point
    caveat = est.residency_caveat
    assert "No route to the standard deduction is open on these facts, so the range is this figure alone" in caveat
    assert "your 2024 return is recorded as '1040-NR'" in caveat
    assert "\"If you are single at the end of the year, you cannot make this choice.\"" in caveat
    assert "The range ALSO prices" not in caveat
    # Married: the election route stays open — JF5b part 3b prices it as the married-filing-jointly
    # CANDIDATE (the election's joint figure, resident rules), and route (ii) points at it; with
    # route (i) closed the same MFS status under resident rules has no route and leaves the range.
    married = estimate_refund(_dual_2025(prior={2024: "1040-NR"}, marital="married"), 2025, income)
    mfj = "married_filing_jointly"
    assert married.point == married.low == 8_000 - _tax(60_000, "married_filing_separately", 2025)
    assert married.high == 8_000 - _tax(60_000 - _sd(mfj, 2025), mfj, 2025)
    assert next(c.bottom_line for c in married.comparison.candidates if c.status == mfj) == married.high
    caveat = married.residency_caveat
    assert "No route to the standard deduction on THIS return is open on these facts" in caveat
    assert "The one route to resident rules is (ii) you are married at the end of the year" in caveat
    assert f"that is the married-filing-jointly CANDIDATE, the election's joint figure ({_signed(married.high)}" in caveat
    assert "the same status under resident rules, not the joint figure" not in caveat
    assert "(i) you were a U.S. resident" not in caveat and "(i) your 2024 return" not in caveat
    # A recorded DECLINE closes the election route: the range collapses and the note says why.
    declined = _dual_2025(prior={2024: "1040-NR"}, marital="married")
    declined.residency_facts.section_6013_election = _ans(False)
    closed = estimate_refund(declined, 2025, income)
    assert closed.low == closed.high == closed.point == married.point
    assert "the §6013(g)/(h) election is recorded as DECLINED" in closed.residency_caveat


def test_p018_dual_status_unanswered_marital_status_keeps_the_election_route_conditional():
    profile = _dual_2025(prior={2024: "1040-NR"})
    profile.household = Household()
    est = estimate_refund(profile, 2025, IncomeSnapshot(wages=60_000, federal_withholding=8_000))
    assert est.high == 8_000 - _tax(60_000 - _sd("single", 2025), "single", 2025) > est.point
    assert "(ii) IF you are married at the end of the year (household.marital_status is not answered)" in (
        est.residency_caveat)
    # The year of a spouse's death is not ruled out either (Pub 501: "considered married for the
    # whole year for filing status purposes"), and never asserted.
    # JF1b.9: the year of death is married for filing status, so MFS is the point and the
    # election's joint figure is the candidate (the route stays conditional).
    widowed = _dual_2025(prior={2024: "1040-NR"}, marital="widowed", spouse_death_year=_ans(2025))
    est = estimate_refund(widowed, 2025, IncomeSnapshot(wages=60_000, federal_withholding=8_000))
    assert est.filing_status_used == "married_filing_separately"
    assert est.high == 8_000 - _tax(60_000 - _sd("married_filing_jointly", 2025), "married_filing_jointly", 2025)
    assert "(ii) IF the choice is open in the year of your spouse's death" in est.residency_caveat


def test_p018_dual_status_bars_the_eitc_and_the_education_credits():
    # Probe A2's shape: before JF5b part 2 this point claimed the EITC and a refundable AOTC.
    income = IncomeSnapshot(wages=12_000, federal_withholding=500, aotc_qualified_expenses=[4_000])
    est = estimate_refund(_dual_2025(), 2025, income)
    assert est.point == est.low == 500 - _tax(12_000, "single", 2025)
    assert not {line.slot for line in est.composition} & {"eitc", "aotc_refundable", "education_credits_nonrefundable"}
    # The other end: the same inputs for a full-year resident (a U.S. citizen's single figure).
    resident = estimate_refund(_single(), 2025, income)
    assert est.high == resident.point
    eitc = -next(line.amount for line in resident.composition if line.slot == "eitc")
    aotc = education_credits([4_000], 0, magi=12_000, filing_status="single", year=2025).aotc_refundable
    assert -next(line.amount for line in resident.composition if line.slot == "aotc_refundable") == aotc > 0
    note = next(a for a in est.assumptions if a.startswith(
        "Education expenses were provided but NO education credit was estimated on the dual-status figure"))
    assert "IRC 25A(g)(7)" in note and "for any portion of the taxable year" in note
    assert "NO earned income credit on the dual-status figure: IRC 32(c)(1)(D)" in note
    assert f"The full-year-resident figure in the range claims ${eitc:,} of earned income credit and ${aotc:,} of " \
           "education credits" in note
    # With no route open the amounts are still named, as a comparison only.
    closed = estimate_refund(_dual_2025(prior={2024: "1040-NR"}), 2025, income)
    note = next(a for a in closed.assumptions if "NO earned income credit" in a)
    assert "computed for comparison only — no route to that figure is open on these facts" in note


def test_p018_dual_status_married_pair_prices_each_return_by_its_own_rules():
    # The taxpayer's dual-status MFS return takes no standard deduction; the U.S.-citizen spouse's
    # separate return keeps it. Route (ii) is the election's JOINT figure — the married-filing-
    # jointly candidate (JF5b part 3b) — and with route (i) closed by the recorded 1040-NR the
    # same MFS pair under resident rules has no route, so the range is the point to the candidate.
    mfs, mfj = "married_filing_separately", "married_filing_jointly"
    profile = _dual_2025(marital="married", prior={2024: "1040-NR"}, spouse=Spouse(us_person=_ans(True)))
    income = IncomeSnapshot(wages=70_000, federal_withholding=9_000,
                            spouse=IncomeSnapshot(wages=25_000, federal_withholding=2_500))
    est = estimate_refund(profile, 2025, income)
    spouse_return = 2_500 - _tax(25_000 - _sd(mfs, 2025), mfs, 2025)
    joint = 11_500 - _tax(95_000 - _sd(mfj, 2025), mfj, 2025)
    assert est.point == est.low == 9_000 - _tax(70_000, mfs, 2025) + spouse_return
    assert est.high == joint
    assert next(line.amount for line in est.composition if line.slot == "spouse_mfs_return") == spouse_return
    # With itemized deductions the couple's one method is weighed (IRC 63(c)(6)(A)): the
    # dual-status return has no standard deduction to lose, the spouse's does.
    item = IncomeSnapshot(wages=70_000, federal_withholding=9_000, itemized_deductions=9_000,
                          spouse=IncomeSnapshot(wages=25_000, federal_withholding=2_500, itemized_deductions=2_000))
    est = estimate_refund(profile, 2025, item)
    both_itemize = (9_000 - _tax(61_000, mfs, 2025)) + (2_500 - _tax(23_000, mfs, 2025))
    spouse_standard = (9_000 - _tax(70_000, mfs, 2025)) + (2_500 - _tax(25_000 - _sd(mfs, 2025), mfs, 2025))
    assert est.point == max(both_itemize, spouse_standard)
    assert est.high == 11_500 - _tax(95_000 - max(11_000, _sd(mfj, 2025)), mfj, 2025)


def test_p018_dual_status_itemized_deductions_are_used_on_the_point():
    income = IncomeSnapshot(wages=50_000, federal_withholding=6_000, itemized_deductions=4_000)
    est = estimate_refund(_dual_2025(), 2025, income)
    assert est.point == 6_000 - _tax(46_000, "single", 2025)
    assert "— $4,000 of itemized deductions used" in est.residency_caveat
    assert est.high == 6_000 - _tax(50_000 - _sd("single", 2025), "single", 2025)   # max(itemized, standard)


def test_p013_dual_status_deposit_split_excludes_only_the_nonresident_period():
    # _dual_status_profile: F-1 -> H-1B on 2023-04-01, identity.us_person unanswered.
    income = IncomeSnapshot(wages=90_000, federal_withholding=12_000, interest=1_200, bank_deposit_interest=1_200,
                            bank_deposit_interest_nonresident_period=400)
    est = estimate_refund(_dual_status_profile(marital="unmarried"), 2023, income)
    line = _deposit_line(est)
    assert line.amount == -400 and "received before the residency starting date" in line.label
    assert "Treas. Reg. 1.871-13(a)(1)" in line.label and line.effect == 0
    assert _labels(est)["Total income"] == 90_800
    assert est.point == est.low == 12_000 - _tax(90_800, "single", 2023)
    # The full-year-resident end taxes all of it (and takes the standard deduction).
    assert est.high == 12_000 - _tax(91_200 - _sd("single", 2023), "single", 2023)
    note = next(a for a in est.assumptions if a.startswith("US bank-deposit interest of $400 received before"))
    assert "and the other $800 of bank_deposit_interest was taxed as resident-period interest" in note
    assert "871(i)(2)(A)" in note and "\"under two different sets of rules" in note
    assert "unless specifically exempt under the Internal Revenue Code or a tax treaty provision" in note
    assert "never a proration" in note and "does not apply to alien individuals treated as residents" in note
    assert "The full-year-resident figure in the range taxes all of it." in note
    assert not any("was EXCLUDED from income:" in a for a in est.assumptions)   # never the full-year note


def test_p013_dual_status_without_a_split_names_the_amount_taxed_in_full():
    income = IncomeSnapshot(wages=90_000, federal_withholding=12_000, interest=1_500, bank_deposit_interest=1_200)
    unanswered = _dual_status_profile(marital="unmarried")
    declared = _dual_status_profile(marital="unmarried")
    declared.identity = Identity(us_person=_ans(False))
    for profile in (unanswered, declared):
        est = estimate_refund(profile, 2023, income)
        assert _deposit_line(est) is None and _labels(est)["Total income"] == 91_500
        assert est.point == 12_000 - _tax(91_500, "single", 2023)
        note = next(a for a in est.assumptions if a.startswith("$1,200 of bank_deposit_interest was taxed IN FULL"))
        assert "the part received before that date — the nonresident part — is excluded" in note
        assert "in bank_deposit_interest_nonresident_period and rerun" in note
        assert "A §6013(g)/(h) election ENDS it" in note
        assert "$300 of interest was entered WITHOUT deposit character" in note
        # The old wording belongs to an unclassified filer only.
        assert not any("not established" in a or "confirmed NONRESIDENT" in a for a in est.assumptions)


def test_p013_dual_status_under_the_election_excludes_nothing():
    profile = _dual_status_profile(marital="married", spouse=Spouse(us_person=_ans(True)))
    profile.residency_facts.section_6013_election = _ans(True)
    income = IncomeSnapshot(wages=90_000, federal_withholding=12_000, interest=1_200, bank_deposit_interest=1_200,
                            bank_deposit_interest_nonresident_period=400)
    est = estimate_refund(profile, 2023, income)
    assert _deposit_line(est) is None and _labels(est)["Total income"] == 91_200
    assert any("$1,200 of bank_deposit_interest was NOT excluded on any figure here" in a for a in est.assumptions)
    assert not any("received before the residency starting date was EXCLUDED" in a for a in est.assumptions)
    assert "DUAL-STATUS" not in (est.residency_caveat or "")


def test_p013_dual_status_split_is_not_net_investment_income():
    # Treas. Reg. 1.1411-2(a)(2)(ii) counts resident-period income only; the excluded part is
    # not income at all — and the whole-year rest may still overstate the NIIT (disclosed).
    income = IncomeSnapshot(wages=250_000, federal_withholding=60_000, interest=20_000, bank_deposit_interest=20_000,
                            bank_deposit_interest_nonresident_period=5_000, dividends=10_000)
    est = estimate_refund(_dual_status_profile(marital="unmarried"), 2023, income)
    niit_line = next(line for line in est.composition if line.slot == "niit")
    assert niit_line.amount == niit(25_000, 275_000, "single", 2023).niit
    assert niit_line.amount != niit(30_000, 275_000, "single", 2023).niit
    assert "NIIT is figured on the whole year's investment income" in est.residency_caveat
    assert "Treas. Reg. 1.1411-2(a)(2)(ii)" in est.residency_caveat and "may be OVERSTATED" in est.residency_caveat


def _citizen_with_dual_spouse(**household_kwargs) -> Profile:
    spouse = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status=s, start=start, end=end, provenance=US) for s, start, end in _SWITCH_APRIL
        ]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in _DAYS_2021.items()}),
    )
    return Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(marital_status=_ans("married"), spouse=spouse, **household_kwargs),
    )


_DUAL_SPOUSE_INCOME = IncomeSnapshot(
    wages=70_000, federal_withholding=9_000,
    spouse=IncomeSnapshot(wages=25_000, federal_withholding=2_500, interest=600, bank_deposit_interest=600,
                          bank_deposit_interest_nonresident_period=250),
)


def test_p018_dual_status_spouse_excludes_only_the_spouses_own_subset():
    # P-013 rule (e) + (f): the SPOUSE's own dual-status year splits the spouse's deposit interest
    # on the spouse's separate return. JF5b part 3b: that return is priced under Pub 519 ch. 6 at the
    # point (no standard deduction, MFS rates); the range prices the full-year resident reading (the
    # standard deduction, all deposit interest taxed) and the full-year nonresident one.
    mfs = "married_filing_separately"
    est = estimate_refund(_citizen_with_dual_spouse(filing_status=_ans(mfs)), 2025, _DUAL_SPOUSE_INCOME)
    mine = 9_000 - _tax(70_000 - _sd(mfs, 2025), mfs, 2025)
    spouse_dual = 2_500 - _tax(25_600 - 250, mfs, 2025)
    spouse_resident = 2_500 - _tax(25_600 - _sd(mfs, 2025), mfs, 2025)
    spouse_nonresident = 2_500 - _tax(25_600 - 250, mfs, 2025)
    assert next(line.amount for line in est.composition if line.slot == "spouse_mfs_return") == spouse_dual
    assert est.point == est.low == mine + spouse_dual == mine + spouse_nonresident
    assert est.high == mine + spouse_resident
    note = next(a for a in est.assumptions if a.startswith(
        "On the spouse's separate return (the spouse's own facts show a dual-status year), US bank-deposit interest "
        "of $250 received before the residency starting date was EXCLUDED"))
    assert "the other $350 of bank_deposit_interest was taxed as resident-period interest" in note
    assert "The range's full-year-resident reading of the spouse's return taxes all of it." in note
    assert not any("$600 of bank_deposit_interest was NOT excluded" in a for a in est.assumptions)
    # With the joint candidate on the table the note says the joint figure taxes it.
    joint = estimate_refund(_citizen_with_dual_spouse(), 2025, _DUAL_SPOUSE_INCOME)
    note = next(a for a in joint.assumptions if a.startswith("On the spouse's separate return (the spouse's own"))
    assert "The joint-return figure taxes it" in note


def test_p018_dual_status_spouse_on_the_assumed_nonresident_reading_excludes_only_its_subset():
    # JF5a's spouse_nra_assumed dual-status reading (a recorded decline): the spouse's return runs
    # on Form 1040-NR rules for the point, but only the nonresident-period subset is excluded.
    mfs = "married_filing_separately"
    profile = _citizen_with_dual_spouse()
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(False))
    est = estimate_refund(profile, 2025, _DUAL_SPOUSE_INCOME)
    mine = 9_000 - _tax(70_000 - _sd(mfs, 2025), mfs, 2025)
    # JF5b part 3b: the point is the spouse's dual-status return (the same dollars as a 1040-NR here:
    # no standard deduction, ordinary rates, only the $250 excluded); the full-year resident reading
    # in the range takes the standard deduction and taxes all the deposit interest.
    assert est.point == est.low == mine + 2_500 - _tax(25_600 - 250, mfs, 2025)
    assert est.high == mine + 2_500 - _tax(25_600 - _sd(mfs, 2025), mfs, 2025)
    assert not any("$600 was EXCLUDED from income" in a for a in est.assumptions)
    assert any(a.startswith("On the spouse's separate return (the spouse's own facts show a dual-status year), US "
                            "bank-deposit interest of $250") for a in est.assumptions)


def test_p013_dual_status_period_is_a_subset_of_deposit_interest():
    with pytest.raises(ValueError, match=r"bank_deposit_interest_nonresident_period \(301\) cannot exceed "
                                         r"bank_deposit_interest \(300\)"):
        IncomeSnapshot(interest=500, bank_deposit_interest=300, bank_deposit_interest_nonresident_period=301)
    with pytest.raises(ValueError, match="bank_deposit_interest_nonresident_period"):
        IncomeSnapshot(interest=500, bank_deposit_interest=300, bank_deposit_interest_nonresident_period=-1)
    assert IncomeSnapshot(interest=500).bank_deposit_interest_nonresident_period == 0
    desc = IncomeSnapshot.model_fields["bank_deposit_interest_nonresident_period"].description
    assert "1.871-13(a)(1)" in desc and "871(i)(1)-(2)(A)" in desc and "never a proration" in desc
    assert "bank_deposit_interest_nonresident_period" in IncomeSnapshot.model_fields["bank_deposit_interest"].description
    # A full-year nonresident excludes all of bank_deposit_interest; a resident excludes nothing.
    income = IncomeSnapshot(wages=18_000, federal_withholding=1_400, interest=900, bank_deposit_interest=900,
                            bank_deposit_interest_nonresident_period=300)
    assert _deposit_line(estimate_refund(_nra_profile(), 2023, income)).amount == -900
    assert _deposit_line(estimate_refund(_single(), 2023, income)) is None


def test_p013_combined_with_spouse_sums_every_amount_field():
    # The spouse-field coverage: every whole-dollar amount on the snapshot is summed on the joint
    # view — the new dual-status subset included — except the household-level dependent_care_persons
    # (the MAX), with the lists concatenated and itemized_deductions summed when either is set.
    household_level = {"dependent_care_persons"}
    ints = [f for f, info in IncomeSnapshot.model_fields.items() if info.annotation is int]
    assert "bank_deposit_interest_nonresident_period" in ints
    one = IncomeSnapshot(**{f: 1 for f in ints})
    two = IncomeSnapshot(**{f: 2 for f in ints}, spouse=None)
    combined = one.model_copy(update={"spouse": two}).combined_with_spouse()
    missing = [f for f in ints if f not in household_level and getattr(combined, f) != 3]
    assert missing == [], f"combined_with_spouse does not sum {missing}"
    assert combined.dependent_care_persons == 2


# JF1b.5 (LD-10): EVERY IncomeSnapshot field is classified here by how the joint view
# (combined_with_spouse) treats it, and each class is checked by behavior. A new field
# fails until it is classified; a classified field the joint view drops fails by name.
_SPOUSE_SUMMED = frozenset({
    "wages", "federal_withholding", "interest", "bank_deposit_interest",
    "bank_deposit_interest_nonresident_period", "dividends", "qualified_dividends",
    "capital_gain_long", "capital_gain_short", "self_employment_net",
    "retirement_income_taxable", "social_security_benefits", "other_income",
    "treaty_exempt_income", "student_loan_interest_paid", "pre_agi_adjustments",
    "dependent_care_expenses", "aca_premiums", "aca_slcsp", "aca_aptc",
    "qualified_tips", "qualified_overtime_premium", "car_loan_interest",   # JF7
    "charitable_cash_nonitemizer",   # JF9: capped per RETURN after the sum
})
# JF7: each person's Schedule 1-A senior flag — the joint view takes the taxpayer's as its own and the
# spouse snapshot's own flag as senior_spouse (never summed).
_SPOUSE_PERSON_FLAGS = frozenset({"senior_taxpayer", "senior_spouse"})
# JR3b: each person's IRA pool is priced on their own snapshot and never reaches the joint view.
_SPOUSE_NEVER_MERGED = frozenset({"ira_pool", "traditional_ira_dec31_value", "roth_ira_dec31_value"})
# JR3c: each person's IRA excess, capped at that person's Dec 31 value, then summed.
_SPOUSE_CAPPED_SUMMED = frozenset({"traditional_ira_excess", "roth_ira_excess"})
_SPOUSE_CONCATENATED = frozenset({"ss_withheld_by_employer", "aotc_qualified_expenses", "medicare_tax_withheld",
                                  "retirement_distributions"})   # JR3a (test_jr3a_the_joint_view_keeps_each_spouses_1099rs)
_SPOUSE_BOX_SUMMED = frozenset({"medicare_wages", "ss_wages"})  # summed, box 1 standing in for a missing one (JF3)
_SPOUSE_OPTIONAL_SUMMED = frozenset({"itemized_deductions"})  # None unless either spouse itemizes
_HOUSEHOLD_LEVEL = frozenset({"dependent_care_persons"})  # the same persons: the MAX, never doubled
_SPOUSE_FIELD = frozenset({"spouse"})  # the nesting itself: the joint view has none


def _spouse_pair() -> tuple[IncomeSnapshot, IncomeSnapshot]:
    """Two snapshots with a DISTINCT value in every field (so a swapped or dropped field shows),
    inside the subset validators (interest >= deposit >= nonresident-period deposit; dividends >=
    qualified; dependent-care expenses need a person)."""
    ints = sorted(_SPOUSE_SUMMED | _HOUSEHOLD_LEVEL)
    one = {f: 1_000 + i for i, f in enumerate(ints)}
    two = {f: 5_000 + 3 * i for i, f in enumerate(ints)}
    for vals, base in ((one, 90_000), (two, 190_000)):
        vals.update(interest=base, bank_deposit_interest=base - 1_000,
                    bank_deposit_interest_nonresident_period=base - 2_000,
                    dividends=base - 3_000, qualified_dividends=base - 4_000)
    one["dependent_care_persons"], two["dependent_care_persons"] = 1, 2
    primary = IncomeSnapshot(**one, ss_withheld_by_employer=[11, 12], aotc_qualified_expenses=[31],
                             itemized_deductions=700, medicare_wages=95_000, ss_wages=94_000,
                             medicare_tax_withheld=[1_400, 60])
    spouse = IncomeSnapshot(**two, ss_withheld_by_employer=[21], aotc_qualified_expenses=[41, 42],
                            itemized_deductions=None, medicare_wages=195_000, ss_wages=None,
                            medicare_tax_withheld=[2_900])
    return primary, spouse


def _spouse_coverage_gaps(combine) -> list[str]:
    """The fields ``combine`` (a joint-view function) mishandles, by class."""
    primary, spouse = _spouse_pair()
    joint = combine(primary.model_copy(update={"spouse": spouse}))
    gaps = [f for f in sorted(_SPOUSE_SUMMED) if getattr(joint, f) != getattr(primary, f) + getattr(spouse, f)]
    gaps += [f for f in sorted(_SPOUSE_CONCATENATED) if getattr(joint, f) != [*getattr(primary, f), *getattr(spouse, f)]]
    if joint.dependent_care_persons != max(primary.dependent_care_persons, spouse.dependent_care_persons):
        gaps.append("dependent_care_persons")
    if joint.spouse is not None:
        gaps.append("spouse")
    pooled = combine(primary.model_copy(update={"ira_pool": IraPoolFacts(basis_carryforward=1),
                                                "spouse": spouse.model_copy(update={"ira_pool": IraPoolFacts(basis_carryforward=2)})}))
    if pooled.ira_pool is not None:
        gaps.append("ira_pool")
    capped = combine(primary.model_copy(update={
        "traditional_ira_excess": 900, "traditional_ira_dec31_value": 400, "roth_ira_excess": 50,
        "spouse": spouse.model_copy(update={"traditional_ira_excess": 70, "roth_ira_excess": 30,
                                            "roth_ira_dec31_value": 10})}))
    if (capped.traditional_ira_excess, capped.roth_ira_excess) != (470, 60):
        gaps += sorted(_SPOUSE_CAPPED_SUMMED)
    if capped.traditional_ira_dec31_value is not None or capped.roth_ira_dec31_value is not None:
        gaps += ["traditional_ira_dec31_value", "roth_ira_dec31_value"]
    flagged = combine(primary.model_copy(update={"senior_taxpayer": True,
                                                 "spouse": spouse.model_copy(update={"senior_taxpayer": False})}))
    flagged2 = combine(primary.model_copy(update={"senior_taxpayer": False,
                                                  "spouse": spouse.model_copy(update={"senior_taxpayer": True})}))
    if (flagged.senior_taxpayer, flagged.senior_spouse, flagged2.senior_taxpayer, flagged2.senior_spouse) != (
            True, False, False, True):
        gaps += sorted(_SPOUSE_PERSON_FLAGS)
    # The W-2 boxes (JF3): summed, a spouse's missing box standing in as their box 1; None when neither.
    if joint.medicare_wages != primary.medicare_wages + spouse.medicare_wages:
        gaps.append("medicare_wages")
    if joint.ss_wages != primary.ss_wages + spouse.wages:
        gaps.append("ss_wages")
    none_either = combine(primary.model_copy(update={
        "ss_wages": None, "spouse": spouse.model_copy(update={"ss_wages": None})}))
    if none_either.ss_wages is not None:
        gaps.append("ss_wages")
    # itemized_deductions: summed when either spouse itemizes, None when neither does.
    both = combine(primary.model_copy(update={"spouse": spouse.model_copy(update={"itemized_deductions": 50})}))
    neither = combine(primary.model_copy(update={
        "itemized_deductions": None, "spouse": spouse.model_copy(update={"itemized_deductions": None})}))
    if joint.itemized_deductions != 700 or both.itemized_deductions != 750 or neither.itemized_deductions is not None:
        gaps.append("itemized_deductions")
    return gaps


def test_jf1b5_every_income_snapshot_field_is_classified_for_the_joint_view():
    classes = (_SPOUSE_SUMMED, _SPOUSE_CONCATENATED, _SPOUSE_OPTIONAL_SUMMED, _HOUSEHOLD_LEVEL, _SPOUSE_FIELD,
               _SPOUSE_BOX_SUMMED, _SPOUSE_PERSON_FLAGS, _SPOUSE_NEVER_MERGED, _SPOUSE_CAPPED_SUMMED)
    classified = frozenset().union(*classes)
    assert sum(len(c) for c in classes) == len(classified), "a field is in two classes"
    fields = set(IncomeSnapshot.model_fields)
    unclassified = sorted(fields - classified)
    assert unclassified == [], (
        f"IncomeSnapshot field(s) {unclassified} are not classified for the joint view: add each to "
        f"combined_with_spouse (summed, concatenated, or the household MAX) and to the matching class here"
    )
    stale = sorted(classified - fields)
    assert stale == [], f"classified field(s) {stale} are no longer on IncomeSnapshot — remove them here"


def test_jf1b5_combined_with_spouse_handles_every_classified_field():
    gaps = _spouse_coverage_gaps(IncomeSnapshot.combined_with_spouse)
    assert gaps == [], f"combined_with_spouse mishandles {gaps} (see the classes above)"


def test_jf1b5_the_coverage_check_names_a_dropped_field():
    # The acceptance: a field dropped from the joint view fails by name — here the joint view
    # with aca_aptc (a summed field) and the second list (a concatenated one) left as the primary's.
    def dropping(snapshot: IncomeSnapshot) -> IncomeSnapshot:
        joint = snapshot.combined_with_spouse()
        return joint.model_copy(update={
            "aca_aptc": snapshot.aca_aptc, "aotc_qualified_expenses": snapshot.aotc_qualified_expenses})

    assert _spouse_coverage_gaps(dropping) == ["aca_aptc", "aotc_qualified_expenses"]


# JF5b part 2, the adversarial verify's fixes (2026-09-27). Hypothetical data.

def test_p018_a_married_dual_status_filer_on_a_single_figure_is_told_the_mfs_column():
    # Pub 519 ch. 6, Tax rates: "You cannot use the Tax Table column or Tax Computation Worksheet
    # for married filing jointly or single" — the column follows the marriage, not the status priced.
    est = estimate_refund(_dual_2025(marital="married", filing_status=_ans("single")), 2025, _WAGES)
    caveat = est.residency_caveat
    assert "You cannot use the Tax Table column or Tax Computation Worksheet for married filing jointly or single" in caveat
    assert "because it is the confirmed status" in caveat and "an inference" not in caveat
    unmarried = estimate_refund(_dual_2025(), 2025, _WAGES).residency_caveat
    assert "single rates — an inference" in unmarried


def test_p018_a_dual_status_confirmed_head_of_household_quotes_the_ch6_bar():
    est = estimate_refund(_dual_2025(filing_status=_ans("head_of_household")), 2025, _WAGES)
    assert "You cannot use the head of household Tax Table column or Tax Computation Worksheet." in est.residency_caveat


def test_p018_route_one_never_asks_for_a_prior_return_already_recorded():
    est = estimate_refund(_dual_2025(prior={2024: "not_filed"}), 2025, _WAGES)
    caveat = est.residency_caveat
    assert "recorded as 'not_filed', which does not settle 2024's residency (not filing says nothing" in caveat
    assert "record the return you filed for 2024 in prior_filings.return_forms" not in caveat


def test_p018_the_dual_status_range_spans_every_candidates_resident_figure():
    # A dual-status widow in the qualifying-surviving-spouse window (candidates single + QSS): the
    # range's high end is the resident QSS figure, not only the primary's resident figure.
    widow = dict(marital="widowed", spouse_death_year=_ans(2024), dependents=[_kid_with_ssn()])
    est = estimate_refund(_dual_2025(**widow), 2025, _WAGES)
    assert {c.status for c in est.comparison.candidates} == {"single", "qualifying_surviving_spouse"}
    # The full-year-resident figures, read off the same facts made resident from January 1 (route (i)).
    resident = estimate_refund(_dual_2025(**widow, prior={2024: "1040"}), 2025, _WAGES)
    resident_qss = next(c.bottom_line for c in resident.comparison.candidates
                        if c.status == "qualifying_surviving_spouse")
    assert est.high == resident_qss > max(c.bottom_line for c in est.comparison.candidates)


def test_p013_a_negative_deposit_answer_is_never_read_as_deposit():
    from taxfill_core.intake import _records_deposit_interest  # noqa: PLC0415
    for kind in ("1099-INT non-deposit", "1099-INT not deposit", "1099-INT no deposit", "1099-INT not a deposit"):
        assert _records_deposit_interest(kind) is False, kind
    assert _records_deposit_interest("1099-INT DEPOSIT") is True


def test_p018_dual_status_rates_with_an_unanswered_marital_status_name_both_columns():
    profile = _dual_2025()
    profile.household = Household()
    caveat = estimate_refund(profile, 2025, _WAGES).residency_caveat
    assert "single rates IF you are unmarried" in caveat and "for married filing separately" in caveat


def test_p018_the_dual_status_resident_end_says_head_of_household_is_not_priced():
    est = estimate_refund(_dual_2025(dependents=[_kid_with_ssn()]), 2025, _WAGES)
    assert "head of household, which a full-year resident with a qualifying person may use, is not priced" in (
        est.residency_caveat)


# ---------------------------------------------------------------------------
# P-018, JF5b part 3a (2026-09-27): the NIIT DEFAULT under the §6013(g)/(h) election.
# Treas. Reg. 1.1411-2(a)(2)(iii)(A) (6013(g)): "the spouses will be treated as married
# filing separately for purposes of section 1411" and "the nonresident alien spouse will
# not be subject to tax under section 1411"; (iii)(B)(2): the second (chapter 2A) election
# must be made "for the first taxable year beginning after December 31, 2013, in which the
# United States taxpayer is subject to tax under section 1411", judged "without regard to
# the effect of the section 6013(g) election". (iv)(A) (6013(h)): "each spouse will be
# treated as married filing separately for the entire year", the arriving spouse "only with
# respect to income received for the portion of the year for which he or she is treated as
# a United States resident"; (iv)(B)(2) sets no first-year condition. The brief's
# hypothetical Examples A-D; every NIIT amount is re-derived through calc.niit.
# ---------------------------------------------------------------------------

_MFJ_ = "married_filing_jointly"
_MFS_ = "married_filing_separately"


def _elected_couple(confirmed: str | None = _MFJ_) -> Profile:
    """A U.S.-citizen taxpayer, a nonresident spouse (F-1 from 2020: nonresident in 2023), the election recorded."""
    profile = _us_filer_married(_nra_spouse())
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    if confirmed is not None:
        profile.household.filing_status = _ans(confirmed)
    return profile


def _niit_note(est: RefundEstimate) -> str:
    return next(a for a in est.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))


def _niit_line(est: RefundEstimate) -> int:
    return next((ln.amount for ln in est.composition if ln.slot == "niit"), 0)


def test_p018_niit_default_example_a_the_default_is_the_point_and_the_elected_figure_bounds_it():
    # Example A (6013(g)): Alex, the U.S. citizen, owes NIIT on his own figures; the couple's
    # combined figure against $250,000 owes none. The default is always open, so it is the
    # point; the second election's $0 is reachable only in the first year Alex is subject.
    income = IncomeSnapshot(wages=110_000, federal_withholding=20_000, interest=5_000, dividends=15_000,
                            spouse=IncomeSnapshot(other_income=60_000, dividends=40_000))
    est = estimate_refund(_elected_couple(), 2023, income)
    default = niit(20_000, 130_000, _MFS_, 2023).niit
    elected = niit(60_000, 230_000, _MFJ_, 2023).niit
    assert (default, elected) == (190, 0)
    assert _labels(est)["Adjusted gross income (AGI)"] == 230_000
    assert _niit_line(est) == default
    mfj_sd = standard_deduction(_MFJ_, 2023).amount
    assert est.point == 20_000 - tax_from_taxable_income(230_000 - mfj_sd, _MFJ_, 2023).tax - default
    assert (est.low, est.high) == (est.point, est.point + default - elected)
    note = _niit_note(est)
    assert "You — the U.S. citizen or resident spouse — owe $190" in note and "a default of $190" in note
    assert "The joint figure uses the default ($190)" in note
    assert "The range also prices the combined-income figure the second election gives ($0" in note
    assert "for the first taxable year beginning after December 31, 2013, in which the United States taxpayer" in note
    assert "a fact this profile does not record" in note
    assert "is not priced here" not in note


def test_p018_niit_default_example_b_the_second_election_is_not_available():
    # Example B (6013(g)): Alex's own MAGI is under $125,000, so he is not subject on his own
    # figures and this is not "the first taxable year ... in which the United States taxpayer
    # is subject to tax under section 1411" — the joint NIIT is $0, never the combined $1,596.
    income = IncomeSnapshot(wages=90_000, federal_withholding=12_000, interest=2_000,
                            spouse=IncomeSnapshot(dividends=200_000))
    est = estimate_refund(_elected_couple(), 2023, income)
    assert niit(2_000, 92_000, _MFS_, 2023).niit == 0
    elected = niit(202_000, 292_000, _MFJ_, 2023).niit
    assert elected == 1_596
    assert _niit_line(est) == 0 and not any(ln.slot == "niit" for ln in est.composition)
    mfj_sd = standard_deduction(_MFJ_, 2023).amount
    assert est.point == 12_000 - tax_from_taxable_income(292_000 - mfj_sd, _MFJ_, 2023).tax
    assert est.low == est.high == est.point            # no bracket: the $1,596 cannot be reached
    note = _niit_note(est)
    assert "the second election is NOT available this year" in note
    assert "without regard to the effect of the section 6013(g) election" in note
    assert "such original election will have no effect for that year and all future years" in note
    assert "($1,596: the couple's combined net investment income" in note and "is not in the range" in note


def test_p018_niit_default_example_c_6013h_takes_the_lower_and_names_the_resident_period_gap():
    # Example C (6013(h)): Dana arrives in 2025 (the taxpayer; a confirmed MFJ is the election),
    # Casey is a U.S. citizen. The combined figure is $1,292; the default is Casey's own $380 and
    # $0 for Dana (her full-year own MAGI is under $125,000 too). No first-year condition, so the
    # couple takes the lower: $380.
    profile = _h1b_arrival_2025(filing_status=_ans(_MFJ_), spouse=Spouse(us_person=_ans(True)))
    income = IncomeSnapshot(wages=70_000, federal_withholding=15_000, interest=4_000, capital_gain_long=20_000,
                            dividends=30_000,
                            spouse=IncomeSnapshot(wages=150_000, federal_withholding=25_000, interest=10_000))
    est = estimate_refund(profile, 2025, income)
    elected = niit(64_000, 284_000, _MFJ_, 2025).niit
    casey = niit(10_000, 160_000, _MFS_, 2025).niit
    dana_full_year = niit(54_000, 124_000, _MFS_, 2025).niit
    assert (elected, casey, dana_full_year) == (1_292, 380, 0)
    assert _labels(est)["Adjusted gross income (AGI)"] == 284_000
    assert _niit_line(est) == min(elected, casey + dana_full_year) == 380
    assert est.low == est.high == est.point
    note = _niit_note(est)
    assert "Priced here for IRC 6013(h)" in note and "a split this estimate does not record" in note
    assert "the joint figure uses $380, the lower of the combined-income figure the second election gives ($1,292" in note
    assert "may elect to have their section 6013(h) election apply for purposes of chapter 2A" in note
    # The Form 8960 instructions' first-year sentence is 6013(g)'s ((iii)(B)(2)); (iv)(B)(2) has none.
    assert "The election must be made for the first tax year" not in note
    assert "the nonresident alien spouse will not be subject" not in note


def test_p018_niit_default_example_c_bounds_when_the_arriving_spouse_owes_on_the_full_year():
    # The same couple with Dana's wages $90,000: her full-year own figure owes NIIT, but only her
    # resident-period income counts and the snapshot has no period split — so the default runs
    # from Casey's $380 (Dana $0) to both full-year figures, and the point is the lower of that
    # high end and the combined figure; the range prices the low end too.
    profile = _h1b_arrival_2025(filing_status=_ans(_MFJ_), spouse=Spouse(us_person=_ans(True)))
    income = IncomeSnapshot(wages=90_000, federal_withholding=15_000, interest=4_000, capital_gain_long=20_000,
                            dividends=30_000,
                            spouse=IncomeSnapshot(wages=150_000, federal_withholding=25_000, interest=10_000))
    est = estimate_refund(profile, 2025, income)
    elected = niit(64_000, 304_000, _MFJ_, 2025).niit
    casey = niit(10_000, 160_000, _MFS_, 2025).niit
    dana_full_year = niit(54_000, 144_000, _MFS_, 2025).niit
    assert (elected, casey, dana_full_year) == (2_052, 380, 722)
    point_niit = min(elected, casey + dana_full_year)
    assert _niit_line(est) == point_niit == 1_102
    assert (est.low, est.high) == (est.point, est.point + point_niit - min(elected, casey))
    note = _niit_note(est)
    assert "between $0 and your full-year $722: a default between $380 and $1,102" in note
    assert "the range also prices $380 (with the default's low end)" in note


def test_p018_niit_default_example_d_the_nonresident_spouse_separate_return_owes_none():
    # Example D: a later year of a continuing 6013(g) election, filed separately. Blair (the
    # spouse, a nonresident without the election) is priced at NIIT $0 — (iii)(A) — and the
    # range prices the resident-rules $570 (the unsettled continuing-election reading).
    profile = _elected_couple(_MFS_)
    income = IncomeSnapshot(wages=80_000, federal_withholding=10_000, spouse=IncomeSnapshot(interest=140_000))
    est = estimate_refund(profile, 2023, income)
    resident_rules = niit(140_000, 140_000, _MFS_, 2023).niit
    assert resident_rules == 570
    mfs_sd = standard_deduction(_MFS_, 2023).amount
    yours = _independent_refund(80_000, 10_000, _MFS_)
    blairs = -tax_from_taxable_income(140_000 - mfs_sd, _MFS_, 2023).tax
    assert est.point == yours + blairs                     # Blair's NIIT: $0
    assert (est.low, est.high) == (est.point - resident_rules, est.point)
    note = _niit_note(est)
    assert "your spouse — the spouse who is a nonresident without the election — owes NIIT $0" in note
    assert "the nonresident alien spouse will not be subject to tax under section 1411" in note
    assert "(NIIT $570 on their own figures against $125,000)" in note
    assert "do not settle what a continuing election does in a year the couple files separately" in note


def test_p018_niit_default_the_nonresident_taxpayer_with_a_spouse_snapshot():
    # The roles swapped (the taxpayer is the nonresident without the election): with the
    # spouse's own amounts on file (none), the U.S. spouse owes no NIIT on their own figures,
    # so the joint NIIT is $0 — not the combined figure the second election would give.
    profile = _nra_profile(marital="married")
    income = IncomeSnapshot(wages=240_000, federal_withholding=40_000, interest=30_000, spouse=IncomeSnapshot())
    est = estimate_refund(_elected(profile, _ELECT_MFJ), 2023, income)
    elected = niit(30_000, 270_000, _MFJ_, 2023).niit
    assert elected > 0 and niit(0, 0, _MFS_, 2023).niit == 0
    assert _niit_line(est) == 0
    assert est.low == est.high == est.point
    note = _niit_note(est)
    assert "Your spouse — the U.S. citizen or resident spouse — owes $0" in note and "and you $0" in note
    assert "the second election is NOT available this year" in note


def test_p018_niit_default_either_keeps_the_elected_point_and_covers_both_readings():
    # A recorded election in a dual-status year is 'either' (an earlier 6013(g) election may
    # still be in effect): the point keeps the combined figure, the range covers the (iii)
    # and the (iv) readings, and the note names the fact that settles it.
    profile = _h1b_arrival_2025(spouse=Spouse(us_person=_ans(True)), filing_status=_ans(_MFJ_))
    profile.residency_facts.section_6013_election = _ans(True)
    income = IncomeSnapshot(wages=90_000, federal_withholding=15_000, interest=4_000, capital_gain_long=20_000,
                            dividends=30_000,
                            spouse=IncomeSnapshot(wages=150_000, federal_withholding=25_000, interest=10_000))
    est = estimate_refund(profile, 2025, income)
    elected = niit(64_000, 304_000, _MFJ_, 2025).niit
    spouse_own = niit(10_000, 160_000, _MFS_, 2025).niit
    assert _niit_line(est) == elected == 2_052
    # (iii) reading: the citizen spouse's own $380 and $0 for you; (iv): $380 up to $1,102.
    assert (est.low, est.high) == (est.point, est.point + elected - min(spouse_own, 380))
    note = _niit_note(est)
    assert "Which paragraph governs is not settled on these facts" in note
    assert "The joint figure keeps the combined-income figure the second election gives ($2,052" in note
    assert "prior_filings.return_forms" in note
    assert "NIIT from $380 to $2,052" in note


def test_p018_niit_default_prices_the_joint_candidate_of_a_nonresident_spouse_too():
    # No recorded election: the joint candidate of a citizen with a nonresident spouse exists
    # only under IRC 6013(g), so its NIIT is the default too — the spouse's own facts classify
    # nonresident, so their separate return stays a 1040-NR's (no NIIT) either way.
    income = IncomeSnapshot(wages=200_000, federal_withholding=40_000, interest=20_000,
                            spouse=IncomeSnapshot(wages=40_000, dividends=15_000))
    est = estimate_refund(_us_filer_married(_nra_spouse()), 2023, income)
    default = niit(20_000, 220_000, _MFS_, 2023).niit
    elected = niit(35_000, 275_000, _MFJ_, 2023).niit
    assert (default, elected) == (760, 950)
    mfj = next(c for c in est.comparison.candidates if c.status == _MFJ_)
    assert est.filing_status_used == _MFJ_ and mfj.bottom_line == est.point
    assert _niit_line(est) == default
    assert est.low <= est.point + default - elected <= est.high     # the second election's figure bounds it
    assert "the U.S. citizen or resident spouse — owe $760" in _niit_note(est)


def test_p018_niit_default_a_dual_status_us_spouse_under_6013g_is_bounded():
    # Pub 519's Bob-and-Sharon shape: you arrive in 2025 (dual-status) and your spouse stays a
    # nonresident all year — IRC 6013(g). Only your resident-period income counts ((a)(2)(ii),
    # a reading), which is not recorded, so your default runs from $0 to your full-year figure.
    nra_spouse_2025 = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2024, 8, 20), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(0), 2024: _ans(130), 2025: _ans(330)}),
    )
    profile = _h1b_arrival_2025(filing_status=_ans(_MFJ_), spouse=nra_spouse_2025)
    income = IncomeSnapshot(wages=150_000, federal_withholding=30_000, interest=10_000,
                            spouse=IncomeSnapshot(dividends=40_000))
    est = estimate_refund(profile, 2025, income)
    yours = niit(10_000, 160_000, _MFS_, 2025).niit
    elected = niit(50_000, 200_000, _MFJ_, 2025).niit
    assert (yours, elected) == (380, 0)
    assert _niit_line(est) == yours
    assert (est.low, est.high) == (est.point, est.point + yours)
    note = _niit_note(est)
    assert "You are in a dual-status year" in note and "may be as low as $0" in note


# JF5b part 3a, the adversarial verify's fixes (2026-09-27). Hypothetical data.

def test_p018_no_niit_default_for_a_couple_with_no_nonresident_in_it():
    # A continuing election recorded after both spouses became U.S. persons: Treas. Reg.
    # 1.1411-2(a)(2)(iii)(A)/(iv)(A) reach only a couple with a nonresident (or arriving) spouse.
    profile = _us_filer_married(Spouse(us_person=_ans(True)))
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    profile.household.filing_status = _ans("married_filing_jointly")
    income = IncomeSnapshot(wages=200_000, federal_withholding=40_000, interest=20_000,
                            spouse=IncomeSnapshot(wages=120_000, federal_withholding=20_000, interest=10_000))
    est = estimate_refund(profile, 2023, income)
    niit_line = next(ln.amount for ln in est.composition if ln.slot == "niit")
    assert niit_line == niit(30_000, 350_000, "married_filing_jointly", 2023).niit   # the ordinary joint figure
    assert est.low == est.high == est.point
    note = next(a for a in est.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))
    assert "neither default paragraph applies" in note and "$0" not in note


def test_p018_the_niit_default_gate_reads_the_priced_amounts_not_raw_income():
    # Each snapshot's interest is offset by its own capital loss (raw sum 0), but the loss is
    # capped on the returns — the joint figure owes NIIT, so the default must be priced.
    profile = _us_filer_married(_nra_spouse())
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    profile.household.filing_status = _ans("married_filing_jointly")
    income = IncomeSnapshot(wages=300_000, federal_withholding=60_000, interest=2_000, capital_gain_short=-2_000,
                            spouse=IncomeSnapshot(wages=10_000, federal_withholding=1_000, interest=2_000,
                                                  capital_gain_short=-2_000))
    est = estimate_refund(profile, 2023, income)
    own = niit(2_000 - 1_500, 300_000 + 500, "married_filing_separately", 2023).niit     # the U.S. spouse alone
    combined = niit(4_000 - 3_000, 310_000 + 1_000, "married_filing_jointly", 2023).niit
    niit_line = next(ln.amount for ln in est.composition if ln.slot == "niit")
    assert niit_line == own and own != combined
    assert any(a.startswith("NIIT under the §6013(g)/(h) election") for a in est.assumptions)


# ---------------------------------------------------------------------------
# P-018, JF5b part 3b (2026-09-27): the election as a CANDIDATE for a nonresident or dual-status
# TAXPAYER; the dual-status route (ii) points at it; a dual-status SPOUSE's own return under Pub
# 519 ch. 6; a prior-year election return as a continuing IRC 6013(g) election. Pub 519 ch. 1:
# "If, at the end of your tax year, you are married and one spouse is a U.S. citizen or a resident
# alien and the other spouse is a nonresident alien, you can choose to treat the nonresident spouse
# as a U.S. resident." IRC 6013(g)(3): "An election under this subsection shall apply to the
# taxable year for which made and to all subsequent taxable years until terminated". Every
# expected value is an independent calc recomputation. Hypothetical data.
# ---------------------------------------------------------------------------


def _candidates(est: RefundEstimate) -> dict[str, int]:
    return {c.status: c.bottom_line for c in est.comparison.candidates}


def test_p018_the_election_is_a_candidate_for_a_nonresident_taxpayer_symmetric_with_the_reverse_couple():
    # A nonresident taxpayer (F-1 from 2020: nonresident in 2023) married to a U.S. citizen, and the
    # same couple with the roles and incomes swapped: the same candidate set and the same values.
    nra_side = IncomeSnapshot(wages=40_000, federal_withholding=5_000)
    citizen_side = IncomeSnapshot(wages=110_000, federal_withholding=16_000, interest=30_000)
    direct = estimate_refund(
        _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True))), 2023,
        nra_side.model_copy(update={"spouse": citizen_side}))
    swapped = estimate_refund(
        _us_filer_married(_nra_spouse()), 2023, citizen_side.model_copy(update={"spouse": nra_side}))
    assert _candidates(direct) == _candidates(swapped)
    assert (direct.low, direct.high) == (swapped.low, swapped.high)
    # The no-election posture stays the nonresident's primary; MFJ is the election's candidate.
    assert direct.filing_status_used == _MFS_ and [c.status for c in direct.comparison.candidates] == [_MFS_, _MFJ_]
    # MFJ under RESIDENT rules for both (standard deduction, NIIT default (iii)(A): the citizen's own
    # $570 against $125,000; the combined figure against $250,000 is $0 and bounds the range).
    default = niit(30_000, 140_000, _MFS_, 2023).niit
    assert (default, niit(30_000, 180_000, _MFJ_, 2023).niit) == (570, 0)
    joint = 21_000 - tax_from_taxable_income(180_000 - standard_deduction(_MFJ_, 2023).amount, _MFJ_, 2023).tax
    assert _candidates(direct)[_MFJ_] == joint - default
    assert direct.high == joint                                   # the second election's figure
    # MFS: the nonresident's Form 1040-NR (no standard deduction) + the citizen's own return.
    nra_return = 5_000 - tax_from_taxable_income(40_000, _MFS_, 2023).tax
    citizen_return = 16_000 - tax_from_taxable_income(
        140_000 - standard_deduction(_MFS_, 2023).amount, _MFS_, 2023).tax - default
    assert _candidates(direct)[_MFS_] == direct.point == direct.low == nra_return + citizen_return
    caveat = direct.residency_caveat
    assert caveat in direct.assumptions and caveat in direct.what_would_change_it
    assert caveat.startswith("Your own residency result is NONRESIDENT alien, and no §6013(g)/(h) election is recorded")
    assert "Married-filing-jointly is shown as a CANDIDATE" in caveat and "IF you and your spouse make" in caveat
    assert "IRC 6013(g) — Pub 519 ch. 1, Nonresident Spouse Treated as a Resident" in caveat   # kind 'g'
    assert "The election does NOT reach FICA" in caveat and "How to make the IRC 6013(g) choice" in caveat
    assert "yours included" in caveat and "overstates the MFJ advantage" in caveat
    note = next(a for a in direct.assumptions if a.startswith("NIIT under the §6013(g)/(h) election — on the "
                                                                "married-filing-jointly CANDIDATE"))
    assert "Your spouse — the U.S. citizen or resident spouse — owes $570" in note
    assert "You — the U.S. citizen or resident spouse — owe $570" in next(
        a for a in swapped.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))


def test_p018_the_candidate_names_what_to_record_when_the_spouse_residency_is_not_on_file():
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000)
    est = estimate_refund(_nra_profile(marital="married"), 2023, income)
    assert _candidates(est)[_MFJ_] == _independent_refund(60_000, 6_000, _MFJ_)
    caveat = est.residency_caveat
    assert "Whether you can make it is NOT settled on these facts" in caveat
    assert "household.spouse.us_person" in caveat and "household.spouse.immigration.visa_timeline" in caveat
    assert "household.spouse.residency_facts.days_in_us" in caveat
    assert "the election is not available at all (IRC 6013(g)(3))" in caveat
    # A dual-status taxpayer can choose either way; which choice turns on the spouse's year end.
    dual = estimate_refund(_h1b_arrival_2025(), 2025, income)
    assert [c.status for c in dual.comparison.candidates] == [_MFS_, _MFJ_]
    assert "Which choice it is turns on your spouse's residency at the end of the year" in dual.residency_caveat
    # The candidate never shows where the facts rule the election out or it is declined.
    two_nra = estimate_refund(_nra_profile(marital="married", spouse=_nra_spouse()), 2023, income)
    assert two_nra.comparison is None and two_nra.filing_status_used == _MFS_
    declined = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True)))
    declined.residency_facts.section_6013_election = _ans(False)
    assert estimate_refund(declined, 2023, income).comparison is None
    # Nor on a confirmed status (the recorded posture wins) or an unmarried filer.
    confirmed = _nra_profile(marital="married", filing_status=_ans(_MFS_))
    assert estimate_refund(confirmed, 2023, income).comparison is None
    assert estimate_refund(_nra_profile(), 2023, income).comparison is None


def test_p018_a_dual_status_taxpayers_candidate_is_the_6013h_choice_and_route_ii_points_at_it():
    # H-1B arrival 2025, a U.S.-citizen spouse, nothing recorded for 2024: the candidate is the
    # NEW IRC 6013(h) choice (no answer recorded), and the dual-status caveat keeps route (i) for
    # the same-status resident figure while route (ii) names the joint candidate.
    profile = _h1b_arrival_2025(spouse=Spouse(us_person=_ans(True)))
    income = IncomeSnapshot(wages=70_000, federal_withholding=9_000,
                            spouse=IncomeSnapshot(wages=25_000, federal_withholding=2_500))
    est = estimate_refund(profile, 2025, income)
    joint = 11_500 - _tax(95_000 - _sd(_MFJ_, 2025), _MFJ_, 2025)
    spouse_return = 2_500 - _tax(25_000 - _sd(_MFS_, 2025), _MFS_, 2025)
    mfs_point = 9_000 - _tax(70_000, _MFS_, 2025) + spouse_return
    mfs_resident = 9_000 - _tax(70_000 - _sd(_MFS_, 2025), _MFS_, 2025) + spouse_return
    assert _candidates(est) == {_MFS_: mfs_point, _MFJ_: joint}
    assert (est.point, est.low, est.high) == (mfs_point, mfs_point, max(joint, mfs_resident))
    caveat = est.residency_caveat
    assert "IRC 6013(h), the year a nonresident alien becomes a resident" in caveat
    assert "If on the last day of the year one of you is a nonresident alien" not in caveat   # not 'either'
    assert f"{_MFS_}: {_signed(mfs_resident)}" in caveat and "(i) you were a U.S. resident during 2024" in caveat
    assert "The other route is priced as its own figure: (ii) you are married at the end of the year" in caveat
    assert f"that is the married-filing-jointly CANDIDATE, the election's joint figure ({_signed(joint)}" in caveat
    assert "the same status under resident rules, not the joint figure" not in caveat


def test_p018_a_dual_status_spouse_return_is_priced_under_chapter_6_at_the_point():
    # The spouse's own dual-status year (no election): the spouse's separate return takes no standard
    # deduction and MFS rates at the point (the spouse's itemized deductions used), and the range
    # prices it for the whole year under resident rules and under Form 1040-NR rules.
    income = IncomeSnapshot(
        wages=70_000, federal_withholding=9_000,
        spouse=IncomeSnapshot(wages=25_000, federal_withholding=2_500, itemized_deductions=3_000))
    est = estimate_refund(_citizen_with_dual_spouse(filing_status=_ans(_MFS_)), 2025, income)
    mine_itemize = 9_000 - _tax(70_000 - 0, _MFS_, 2025)        # IRC 63(c)(6)(A): the couple itemizes
    mine_standard = 9_000 - _tax(70_000 - _sd(_MFS_, 2025), _MFS_, 2025)
    spouse_dual_itemize = 2_500 - _tax(22_000, _MFS_, 2025)
    spouse_dual_standard = 2_500 - _tax(25_000, _MFS_, 2025)  # 'standard' pair mode: a dual return claims none
    point = max(mine_itemize + spouse_dual_itemize, mine_standard + spouse_dual_standard)
    assert est.point == point
    resident = max(mine_itemize + 2_500 - _tax(22_000, _MFS_, 2025),
                   mine_standard + 2_500 - _tax(25_000 - _sd(_MFS_, 2025), _MFS_, 2025))
    assert est.high == resident and est.low == point
    note = next(a for a in est.assumptions if a.startswith("The spouse's separate return was computed under Pub 519 "
                                                             "ch. 6's DUAL-STATUS restrictions for the point"))
    assert "NO standard deduction" in note and "married-filing-separately rates" in note
    assert "is subject to the flat 30% rate or lower treaty rate" in note
    ranges = next(a for a in est.assumptions if a.startswith("The spouse's own facts show a DUAL-STATUS year"))
    assert f"married-filing-separately would then total {_signed(resident)}" in ranges
    assert "under NONRESIDENT rules (Form 1040-NR" in ranges
    deduction = next(a for a in est.assumptions if a.startswith("Married filing separately (two returns)"))
    assert "a dual-status year has no standard deduction" in deduction or "BOTH ITEMIZE" in deduction


def test_p018_a_prior_year_election_return_makes_a_recorded_election_a_continuing_6013g():
    # IRC 6013(g)(3) and 6013(h)(2): with the 2024 return a joint Form 1040 under the election, a
    # recorded 2025 election in the taxpayer's arrival year is 6013(g) — continuing — never a new
    # 6013(h): separate returns stay open, and the 6013(g) text is the one quoted.
    profile = _h1b_arrival_2025(spouse=Spouse(us_person=_ans(True)))
    profile.residency_facts.section_6013_election = _ans(True)
    profile.prior_filings = _prior({2024: "1040_with_6013_election"})
    income = IncomeSnapshot(wages=90_000, federal_withholding=15_000, interest=54_000,
                            spouse=IncomeSnapshot(wages=150_000, federal_withholding=25_000, interest=10_000))
    est = estimate_refund(profile, 2025, income)
    caveat = est.residency_caveat
    assert "IRC 6013(g) — Pub 519 ch. 1, Nonresident Spouse Treated as a Resident" in caveat
    assert "Choosing Resident Alien Status" not in caveat
    assert set(_candidates(est)) == {_MFJ_, _MFS_}
    assert "under IRC 6013(g) it is the posture of a LATER year of a continuing election" in caveat
    # NIIT: the U.S. spouse's own $380; the arriving taxpayer subject on resident-period income only
    # (Treas. Reg. 1.1411-2(a)(2)(iv)(A)'s facts), not recorded — from $0 to the full-year $722.
    spouse_own = niit(10_000, 160_000, _MFS_, 2025).niit
    mine_own = niit(54_000, 144_000, _MFS_, 2025).niit
    elected = niit(64_000, 304_000, _MFJ_, 2025).niit
    assert (spouse_own, mine_own, elected) == (380, 722, 2_052)
    joint_before_niit = 40_000 - _tax(304_000 - _sd(_MFJ_, 2025), _MFJ_, 2025)
    assert _candidates(est)[_MFJ_] == est.point == joint_before_niit - (spouse_own + mine_own)
    assert est.high >= joint_before_niit - spouse_own                       # the default's low end is priced
    note = next(a for a in est.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))
    assert "a default between $380 and $1,102" in note and "fit this later year of a continuing 6013(g)" in note
    assert "range also prices that return's NIIT at $0" in note
    # Without the prior-year return the same facts stay 'either' (an earlier election MAY continue).
    profile.prior_filings = None
    assert "Choosing Resident Alien Status" in estimate_refund(profile, 2025, income).residency_caveat


def test_p018_a_prior_year_election_return_with_no_answer_is_not_applied_and_asks_for_it():
    profile = _h1b_arrival_2025(spouse=Spouse(us_person=_ans(True)))
    profile.prior_filings = _prior({2024: "1040_with_6013_election"})
    income = IncomeSnapshot(wages=70_000, federal_withholding=9_000,
                            spouse=IncomeSnapshot(wages=25_000, federal_withholding=2_500))
    est = estimate_refund(profile, 2025, income)
    # Not applied: the point is the dual-status MFS return; the joint figure is the candidate, kind 'g'.
    assert est.filing_status_used == _MFS_ and "DUAL-STATUS" in est.residency_caveat
    assert _candidates(est)[_MFJ_] == 11_500 - _tax(95_000 - _sd(_MFJ_, 2025), _MFJ_, 2025)
    assert "IRC 6013(g) — Pub 519 ch. 1, Nonresident Spouse Treated as a Resident" in est.residency_caveat
    note = next(a for a in est.assumptions if "no election is recorded for 2025 — so this is NOT applied here" in a)
    assert note in est.what_would_change_it
    assert "IRC 6013(g)(3): \"An election under this subsection shall apply to the taxable year for which made" in note
    assert "Once made, the choice to be treated as a resident applies to all later years unless suspended" in note
    assert "Record residency_facts.section_6013_election for 2025: true if the election is still in effect" in note
    # A recorded answer (either way) replaces the note; so does an unmarried household.
    for value in (True, False):
        answered = profile.model_copy(deep=True)
        answered.residency_facts.section_6013_election = _ans(value)
        assert not any("no election is recorded for 2025" in a for a in estimate_refund(answered, 2025, income).assumptions)
    unmarried = profile.model_copy(deep=True)
    unmarried.household.marital_status = _ans("unmarried")
    assert not any("no election is recorded for 2025" in a for a in estimate_refund(unmarried, 2025, income).assumptions)


def test_p018_a_dual_status_spouse_inside_a_head_of_household_figure_keeps_chapter_6_rules():
    # After a recorded decline a citizen with a qualifying child keeps head of household (Pub 501,
    # Considered Unmarried); the spouse's separate return inside it follows the spouse's own year
    # — Pub 519 ch. 6 — as on the MFS pair, and only the full-year resident reading of the MFS
    # pair loses the $250 nonresident-period exclusion.
    profile = _citizen_with_dual_spouse(dependents=[_kid_with_ssn()])
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(False))
    est = estimate_refund(profile, 2025, _DUAL_SPOUSE_INCOME)
    assert [c.status for c in est.comparison.candidates] == [_MFS_, "head_of_household"]
    hoh = next(a for a in est.assumptions if a.startswith("The head-of-household figure is your own"))
    assert "PLUS the spouse's separate return on Pub 519 ch. 6's dual-status rules" in hoh
    assert "on Form 1040-NR rules" not in hoh
    spouse_dual = 2_500 - _tax(25_600 - 250, _MFS_, 2025)
    spouse_resident = 2_500 - _tax(25_600 - _sd(_MFS_, 2025), _MFS_, 2025)
    assert est.high - est.point == spouse_resident - spouse_dual


# JF5b part 3b, the adversarial verify's fixes (2026-09-27). Hypothetical data.

def test_p018_the_dual_status_range_never_reprices_the_joint_candidate_without_its_niit_default():
    # A dual-status taxpayer and a spouse abroad with large investment income: the MFJ candidate is
    # priced with the (iii)(A) default; the barred second-election figure never becomes the low end.
    spouse = Spouse(us_person=_ans(False), immigration=Immigration(visa_timeline=[]),
                    residency_facts=ResidencyFacts(days_in_us={2025: _ans(0), 2024: _ans(0), 2023: _ans(0)}))
    profile = _h1b_arrival_2025(spouse=spouse)
    income = IncomeSnapshot(wages=70_000, federal_withholding=9_000,
                            spouse=IncomeSnapshot(wages=0, federal_withholding=0, dividends=300_000))
    est = estimate_refund(profile, 2025, income)
    if est.comparison is not None and _MFJ_ in _candidates(est):
        assert est.low == min(_candidates(est).values())


def test_p018_a_confirmed_joint_status_with_a_prior_election_return_is_read_as_it_continuing():
    profile = _nra_profile(marital="married", spouse=Spouse(us_person=_ans(True)), filing_status=_ans(_MFJ_))
    profile.prior_filings = _prior({2022: "1040_with_6013_election"})
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=5_000))
    text = " ".join(est.assumptions)
    assert "read as that election continuing" in text and "NOT applied" not in text


def test_p018_no_continuation_note_when_the_election_is_suspended_this_year():
    profile = _nra_profile(marital="married", spouse=_nra_spouse())
    profile.prior_filings = _prior({2022: "1040_with_6013_election"})
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=5_000))
    assert not any("continues until terminated" in a or "true if the election is still in effect" in a
                   for a in est.assumptions)
    assert any("shall not apply for any taxable year" in a for a in est.assumptions)


def test_p018_a_confirmed_joint_status_niit_note_is_not_called_a_candidate():
    profile = _us_filer_married(_nra_spouse())
    profile.household.filing_status = _ans(_MFJ_)
    est = estimate_refund(profile, 2023, IncomeSnapshot(
        wages=200_000, federal_withholding=40_000, interest=20_000,
        spouse=IncomeSnapshot(wages=9_000, federal_withholding=600, interest=1_000)))
    note = next(a for a in est.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))
    assert "CANDIDATE" not in note


# ── JF1b.2: the §6013 caveat needs a married household. Hypothetical profiles. ──


def _six013_texts(est: RefundEstimate) -> list[str]:
    return [t for t in [*est.assumptions, *est.what_would_change_it] if "6013" in t]


def test_jf1b2_an_unmarried_visa_holder_with_no_residency_facts_reads_no_6013():
    for household in (Household(marital_status=_ans("unmarried")),
                      Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
                      Household(filing_status=_ans("single")),
                      None):
        profile = Profile(identity=Identity(us_person=_ans(False)), household=household)
        est = estimate_refund(profile, 2025, _WAGES)
        assert _six013_texts(est) == [], household
        # The residency warning stays — without the election the filer cannot make.
        caveat = next(a for a in est.assumptions if a.startswith("If your residency result is nonresident alien"))
        assert "Nonresident aliens cannot claim the standard deduction" in caveat
        assert "You cannot file as head of household if you are a nonresident alien" in caveat


def test_jf1b2_a_married_visa_holder_with_no_residency_facts_still_reads_the_election():
    for household in (Household(marital_status=_ans("married")),
                      Household(filing_status=_ans("married_filing_separately"))):
        est = estimate_refund(Profile(identity=Identity(us_person=_ans(False)), household=household), 2025, _WAGES)
        texts = _six013_texts(est)
        assert texts and any("electing under §6013(g)/(h)" in t for t in texts), household


def test_jf1b2_an_unmarried_nonresident_or_dual_status_filer_reads_no_6013():
    nonresident = _visa_profile([("F-1", date(2023, 8, 20), None)], {2025: 365, 2024: 366, 2023: 130})
    assert _six013_texts(estimate_refund(nonresident, 2025, _WAGES)) == []
    dual = _visa_profile(_SWITCH_APRIL, _DAYS_2021)
    est = estimate_refund(dual, 2025, _WAGES)
    assert est.residency_caveat is not None and "DUAL-STATUS" in est.residency_caveat
    assert _six013_texts(est) == []
    # A prior-year Form 1040-NR closes route (i): the no-route reason names the missing marriage,
    # not the election.
    closed = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021, prior={2024: "1040-NR"}), 2025, _WAGES)
    assert _six013_texts(closed) == []
    assert "you are not married at the end of the year on these facts, so no joint-return choice" in (
        closed.residency_caveat or "")
    # A married filer's dual-status caveat still names the election.
    married = estimate_refund(_visa_profile(_SWITCH_APRIL, _DAYS_2021, marital="married"), 2025, _WAGES)
    assert "no §6013(g)/(h) election is recorded" in (married.residency_caveat or "")


def test_jf1b2_a_prior_year_resident_meeting_the_spt_gets_no_taxpayer_direction_caveat():
    # JF5b's prior-year fact + the SPT settle the TAXPAYER as a resident: no "if your residency
    # result is nonresident" caveat for the taxpayer; a nonresident SPOUSE still gets the
    # spouse-direction caveat.
    h1b = [("H-1B", date(2024, 6, 1), None)]
    alone = _visa_profile(h1b, {2025: 365, 2024: 214}, prior={2024: "1040"}, marital="married")
    est = estimate_refund(alone, 2025, _WAGES)
    assert _six013_texts(est) == []
    with_spouse = _visa_profile(h1b, {2025: 365, 2024: 214}, prior={2024: "1040"}, marital="married",
                                spouse=Spouse(us_person=_ans(False)))
    texts = _six013_texts(estimate_refund(with_spouse, 2025, _WAGES))
    assert texts and all(t.startswith("Your spouse may be a nonresident alien") for t in texts)


# JF1b.12 (2026-09-27): a nonresident's or a dual-status filer's confirmed head of household is
# priced as the status the filer can use. Hypothetical data.

def test_jf1b12_a_nonresidents_confirmed_head_of_household_is_priced_as_single():
    profile = _nra_profile(filing_status=_ans("head_of_household"))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
    assert est.filing_status_used == "single"
    assert est.point == 3_000 - tax_from_taxable_income(40_000, "single", 2023).tax   # 1040-NR: no standard deduction
    assert "You cannot file as head of household if you are a nonresident alien" in est.residency_caveat


def test_jf1b12_a_dual_status_confirmed_head_of_household_is_priced_as_single():
    est = estimate_refund(_dual_2025(filing_status=_ans("head_of_household")), 2025, _WAGES)
    assert est.filing_status_used == "single"
    assert "You cannot use the head of household Tax Table column" in est.residency_caveat


# JF1b.11 (2026-09-27): the FICA withheld-in-error note follows each person's own snapshot and
# F/J/M/Q status — IRC 3121(b)(19). Hypothetical data.

def test_jf1b11_an_f1_spouses_withheld_fica_gets_its_own_note():
    profile = _us_filer_married(_nra_spouse())
    income = IncomeSnapshot(wages=90_000, federal_withholding=9_000,
                            spouse=IncomeSnapshot(wages=20_000, federal_withholding=1_000,
                                                  ss_withheld_by_employer=[1_240]))
    est = estimate_refund(profile, 2023, income)
    note = next(a for a in est.assumptions if a.startswith("Your spouse's $1,240 of Social Security tax"))
    assert "IRC 3121(b)(19)" in note and "Form 843 + Form 8316" in note
    assert note in est.what_would_change_it


def test_jf1b11_an_h1b_nonresident_gets_no_fica_exemption_note():
    # 3121(b)(19) covers F, J, M and Q nonimmigrants only: an H-1B nonresident owes FICA.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        household=Household(marital_status=_ans("unmarried")),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-1B", start=date(2023, 10, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(92), 2022: _ans(0), 2021: _ans(0)}),
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=20_000, federal_withholding=2_000,
                                                        ss_withheld_by_employer=[1_240]))
    assert not any("FICA-EXEMPT" in a for a in est.assumptions)


# JF1b.9 (2026-09-27): Pub 501, "If your spouse died during the year, you are considered married for
# the whole year for filing status purposes." Hypothetical data.

def test_jf1b9_the_year_of_a_spouses_death_offers_the_joint_return_and_keeps_the_spouse_snapshot():
    profile = _us_filer_married(Spouse(us_person=_ans(True)))
    profile.household.marital_status = _ans("widowed")
    profile.household.spouse_death_year = _ans(2023)
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=20_000, federal_withholding=2_000))
    est = estimate_refund(profile, 2023, income)
    assert [c.status for c in est.comparison.candidates] == ["married_filing_jointly", "married_filing_separately"]
    joint = 8_000 - tax_from_taxable_income(
        80_000 - standard_deduction("married_filing_jointly", 2023).amount, "married_filing_jointly", 2023).tax
    assert est.point == joint                                   # the deceased spouse's income is on the joint figure
    # Outside the year of death, a widow(er) is not married (single, or QSS in its window).
    later = estimate_refund(profile, 2024, income)
    assert "married_filing_jointly" not in {c.status for c in (later.comparison.candidates if later.comparison else [])}


# ---------------------------------------------------------------------------
# JF1b.10 (P-018): head of household for a citizen or resident whose spouse is a
# nonresident alien — a CANDIDATE with no election recorded, and on that route the
# filer is still married outside IRC 2(b) (a married individual's separate return).
# Hypothetical demo fixtures only.
# ---------------------------------------------------------------------------

_M7703 = "Head of household on the nonresident-spouse route makes you unmarried ONLY for the filing status"


def _parent_married_to(spouse: Spouse, *, confirmed_hoh: bool = False) -> Profile:
    profile = _us_filer_married(spouse)
    profile.household.dependents = [_kid_with_ssn()]
    if confirmed_hoh:
        profile.household.filing_status = _ans("head_of_household")
    return profile


def _hoh_routes(income: IncomeSnapshot, year: int = 2023) -> tuple[RefundEstimate, RefundEstimate]:
    """(the nonresident-spouse route, the lived-apart route) — the same confirmed head of household."""
    return (
        estimate_refund(_parent_married_to(_nra_spouse(), confirmed_hoh=True), year, income),
        estimate_refund(_parent_married_to(Spouse(us_person=_ans(True)), confirmed_hoh=True), year, income),
    )


def _slot(est: RefundEstimate, slot: str) -> int | None:
    return next((ln.amount for ln in est.composition if ln.slot == slot), None)


def _m7703_note(est: RefundEstimate) -> str:
    return next(a for a in est.assumptions if a.startswith(_M7703))


def test_jf1b10_head_of_household_is_a_candidate_with_no_election_recorded():
    # Pub 501, Considered Unmarried: "You are considered unmarried for head of household purposes if
    # your spouse was a nonresident alien at any time during the year and you don't choose to treat
    # your nonresident spouse as a resident alien."
    income = IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                            spouse=IncomeSnapshot(wages=9_000, federal_withholding=300))
    for spouse in (_nra_spouse(), Spouse(us_person=_ans(False))):   # a nonresident, and one of unknown residency
        est = estimate_refund(_parent_married_to(spouse), 2023, income)
        statuses = [c.status for c in est.comparison.candidates]
        assert statuses == ["married_filing_jointly", _MFS, "head_of_household"]
        note = next(a for a in est.assumptions if a.startswith("The head-of-household figure is your own"))
        assert "on Form 1040-NR rules" in note and "rests on your spouse being a nonresident alien" in note
        assert "exists only if you and your spouse do NOT make it" in note
    # The HOH figure: your own head-of-household return (Tax Table midpoint, CTC) plus the spouse's
    # separate Form 1040-NR (no standard deduction).
    est = estimate_refund(_parent_married_to(_nra_spouse()), 2023, income)
    hoh = next(c for c in est.comparison.candidates if c.status == "head_of_household")
    own = 6_000 - (tax_from_taxable_income(60_000 - standard_deduction("head_of_household", 2023).amount,
                                           "head_of_household", 2023).tax - 2_000)
    spouse = 300 - tax_from_taxable_income(9_000, _MFS, 2023).tax
    assert hoh.bottom_line == own + spouse
    # No candidate without a nonresident in view, under a recorded election, or with no qualifying person.
    us = estimate_refund(_parent_married_to(Spouse(us_person=_ans(True))), 2023, income)
    assert "head_of_household" not in {c.status for c in us.comparison.candidates}
    elected = _parent_married_to(_nra_spouse())
    elected.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    under = estimate_refund(elected, 2023, income)
    assert "head_of_household" not in {c.status for c in (under.comparison.candidates if under.comparison else [])}
    no_qp = _parent_married_to(_nra_spouse())
    no_qp.household.hoh_qualifying_person = _ans(False)
    assert "head_of_household" not in {c.status for c in estimate_refund(no_qp, 2023, income).comparison.candidates}


def test_jf1b10_the_nonresident_spouse_route_claims_no_education_credit():
    # IRC 25A(g)(6): "If the taxpayer is a married individual (within the meaning of section 7703),
    # this section shall apply only if the taxpayer and the taxpayer's spouse file a joint return".
    nra, apart = _hoh_routes(IncomeSnapshot(wages=60_000, federal_withholding=6_000, aotc_qualified_expenses=[4_000]))
    assert _slot(apart, "education_credits_nonrefundable") or _slot(apart, "aotc_refundable")
    assert _slot(nra, "education_credits_nonrefundable") is None and _slot(nra, "aotc_refundable") is None
    assert "IRC 25A(g)(6)" in _m7703_note(nra)
    assert not any(a.startswith(_M7703) for a in apart.assumptions)


def test_jf1b10_the_nonresident_spouse_route_claims_no_dependent_care_credit():
    # IRC 21(e)(2): "If the taxpayer is married at the close of the taxable year, the credit shall be
    # allowed under subsection (a) only if the taxpayer and his spouse file a joint return".
    nra, apart = _hoh_routes(IncomeSnapshot(wages=60_000, federal_withholding=6_000,
                                            dependent_care_expenses=3_000, dependent_care_persons=1))
    assert _slot(apart, "dependent_care_credit_nonrefundable")
    assert _slot(nra, "dependent_care_credit_nonrefundable") is None
    assert "IRC 21(e)(2)" in _m7703_note(nra)


def test_jf1b10_the_nonresident_spouse_route_takes_no_student_loan_interest_deduction():
    # IRC 221(e)(2)-(3): married at year end, the deduction needs a joint return; "Marital status
    # shall be determined in accordance with section 7703."
    nra, apart = _hoh_routes(IncomeSnapshot(wages=60_000, federal_withholding=6_000, student_loan_interest_paid=1_000))
    assert _slot(apart, "student_loan_interest_deduction") == -1_000
    assert _slot(nra, "student_loan_interest_deduction") is None
    assert "IRC 221(e)(2)" in _m7703_note(nra)
    assert not any("gives a $0 deduction on the married-filing-separately candidate" in a for a in nra.assumptions)


def test_jf1b10_the_nonresident_spouse_route_caps_a_capital_loss_at_1500():
    # IRC 1211(b)(1): "$3,000 ($1,500 in the case of a married individual filing a separate return)".
    nra, apart = _hoh_routes(IncomeSnapshot(wages=60_000, federal_withholding=6_000, capital_gain_short=-2_500))
    assert _slot(nra, "capital_loss") == -1_500
    assert "IRC 1211(b)(1)" in _m7703_note(nra) and "1.1211-1(b)(7)(i)" in _m7703_note(nra)
    # JF2.5: the lived-apart route is capped too — 1211 does not refer to section 7703.
    assert _slot(apart, "capital_loss") == -1_500
    assert not any(a.startswith(_M7703) for a in apart.assumptions)
    # A loss within $1,500 is the same on both routes, and no note claims the cap bound.
    small, _ = _hoh_routes(IncomeSnapshot(wages=60_000, federal_withholding=6_000, capital_gain_short=-1_000))
    assert _slot(small, "capital_loss") == -1_000
    assert not any(a.startswith(_M7703) for a in small.assumptions)


def test_jf1b10_the_nonresident_spouse_route_gets_no_premium_tax_credit():
    # IRC 36B(c)(1)(C): married "(within the meaning of section 7703)", the taxpayer is an applicable
    # taxpayer only on a joint return — the advance payments are repaid (Table 5 'other' column).
    income = IncomeSnapshot(wages=40_000, federal_withholding=3_000,
                            aca_premiums=6_000, aca_slcsp=7_000, aca_aptc=3_000)
    nra, apart = _hoh_routes(income)
    assert _slot(nra, "net_ptc") is None and _slot(nra, "aptc_repayment")
    assert (_slot(apart, "net_ptc") or 0) > 0 or (_slot(apart, "aptc_repayment") or 0) < _slot(nra, "aptc_repayment")
    assert "IRC 36B(c)(1)(C)" in _m7703_note(nra)


def test_jf1b10_the_nonresident_spouse_route_uses_the_separate_niit_threshold():
    # Treas. Reg. 1.1411-2(a)(2)(iii)(A): "the spouses will be treated as married filing separately for
    # purposes of section 1411" — the $125,000 threshold of (d)(1)(ii).
    nra, apart = _hoh_routes(IncomeSnapshot(wages=100_000, federal_withholding=20_000, interest=50_000))
    assert _slot(apart, "niit") is None                                   # $150,000 MAGI is under $200,000
    assert _slot(nra, "niit") == round(0.038 * (150_000 - 125_000))
    assert "1.1411-2(a)(2)(iii)(A)" in _m7703_note(nra)


def test_jf1b10_the_nonresident_spouse_route_uses_the_separate_additional_medicare_threshold():
    # IRC 3101(b)(2)(B): "in the case of a married taxpayer (as defined in section 7703) filing a separate
    # return, ½ of the dollar amount determined under subparagraph (A)".
    nra, apart = _hoh_routes(IncomeSnapshot(wages=150_000, federal_withholding=30_000))
    assert _slot(apart, "additional_medicare_tax") is None
    assert _slot(nra, "additional_medicare_tax") == round(0.009 * (150_000 - 125_000))
    assert "IRC 3101(b)(2)(B)" in _m7703_note(nra)


def test_jf1b10_the_nonresident_spouse_route_uses_a_zero_social_security_base_amount():
    # IRC 86(c)(1)(C): "zero in the case of a taxpayer who— (i) is married as of the close of the taxable
    # year (within the meaning of section 7703) but does not file a joint return for such year, and (ii)
    # does not live apart from his spouse at all times during the taxable year".
    nra, apart = _hoh_routes(IncomeSnapshot(wages=10_000, federal_withholding=500, social_security_benefits=20_000))
    assert _slot(apart, "taxable_social_security") is None                # $20,000 provisional income < $25,000
    # Base and adjusted base both $0: the lesser of 85% of the benefits and 85% of the $20,000 provisional income.
    assert _slot(nra, "taxable_social_security") == 17_000
    note = _m7703_note(nra)
    assert "IRC 86(c)(1)(C)" in note and "did not live apart at all times" in note


def test_jf1b10_intake_names_head_of_household_for_the_citizen_side():
    from taxfill_core.intake import intake_checklist  # noqa: PLC0415
    profile = _parent_married_to(_nra_spouse())
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions if q.id == "household.filing_status")
    assert "head of household if you have another qualifying person" in q.prompt and "without the election" in q.prompt
    # A U.S.-person spouse: the plain joint-or-separate question.
    us = _parent_married_to(Spouse(us_person=_ans(True)))
    q = next(q for q in intake_checklist(us, tax_year=2023).next_questions if q.id == "household.filing_status")
    assert q.prompt == "Do you want to file jointly with your spouse or separately?"


def test_jf1b12_intake_quotes_the_dual_status_head_of_household_bar():
    from taxfill_core.intake import intake_checklist  # noqa: PLC0415
    profile = _visa_profile(_SWITCH_APRIL, _DAYS_2021)
    profile.household.dependents = [_kid_with_ssn()]
    q = next(q for q in intake_checklist(profile, tax_year=2025).next_questions
             if q.id == "household.hoh_qualifying_person")
    assert "You cannot use the head of household Tax Table column or Tax Computation Worksheet." in q.disambiguation
    profile.household.hoh_qualifying_person = _ans(True)
    q = next(q for q in intake_checklist(profile, tax_year=2025).next_questions if q.id == "household.filing_status")
    assert "in a dual-status year you file as single" in q.prompt



# ---------------------------------------------------------------------------
# JF2.5 (JF1b part B deferrals): a married head of household's other
# married-separately rules. Hypothetical demo fixtures only.
# ---------------------------------------------------------------------------

_APART_1211 = "The head-of-household figure (through living apart) limits the net capital loss"


def test_jf2_5_the_lived_apart_head_of_household_is_still_married_for_the_capital_loss_limit():
    # IRC 1211(b)(1) has no section 7703 reference, so 7703(b) does not unmarry the filer for it —
    # Pub 501: "You may be considered unmarried for the purpose of using head of household status but
    # not for other purposes".
    _, apart = _hoh_routes(IncomeSnapshot(wages=60_000, federal_withholding=6_000, capital_gain_short=-2_500))
    assert _slot(apart, "capital_loss") == -1_500
    note = next(a for a in apart.assumptions if a.startswith(_APART_1211))
    assert "does not refer to section 7703" in note and "but not for other purposes" in note
    assert "($1,500 if married filing separately)" in note
    # An unmarried head of household keeps the $3,000.
    single_hoh = estimate_refund(_hoh_parent(_kid_with_ssn()), 2023,
                                 IncomeSnapshot(wages=60_000, federal_withholding=6_000, capital_gain_short=-2_500))
    assert _slot(single_hoh, "capital_loss") == -2_500
    assert not any(a.startswith(_APART_1211) for a in single_hoh.assumptions)


def test_jf2_5_the_lived_apart_all_year_fact_sets_the_social_security_base_amount():
    # IRC 86(c)(1)(C): a $0 base amount for a married taxpayer not filing jointly who "does not live apart
    # from his spouse at all times during the taxable year"; living apart all year, the $25,000 of (A).
    income = IncomeSnapshot(wages=10_000, federal_withholding=500, social_security_benefits=20_000)
    together = estimate_refund(_parent_married_to(_nra_spouse(), confirmed_hoh=True), 2023, income)
    assert _slot(together, "taxable_social_security") == 17_000
    assert "household.spouses_lived_apart_all_year" in _m7703_note(together)
    profile = _parent_married_to(_nra_spouse(), confirmed_hoh=True)
    profile.household.spouses_lived_apart_all_year = _ans(True)
    apart = estimate_refund(profile, 2023, income)
    assert _slot(apart, "taxable_social_security") is None                 # $20,000 provisional < $25,000
    assert not any(a.startswith(_M7703) and "86(c)(1)(C)" in a for a in apart.assumptions)
    # The married-filing-separately pair: the same fact reaches both returns, and the note follows it.
    mfs = _us_filer_married(Spouse(us_person=_ans(True)))
    mfs.household.filing_status = _ans("married_filing_separately")
    pair = IncomeSnapshot(wages=10_000, federal_withholding=500, social_security_benefits=20_000,
                          spouse=IncomeSnapshot(wages=10_000, federal_withholding=500, social_security_benefits=20_000))
    lived_together = estimate_refund(mfs, 2023, pair)
    assert any("assumes the spouses did NOT live apart at all times" in a for a in lived_together.assumptions)
    mfs.household.spouses_lived_apart_all_year = _ans(True)
    lived_apart = estimate_refund(mfs, 2023, pair)
    assert any("uses the $25,000 base amount (IRC 86(c)(1)(A))" in a for a in lived_apart.assumptions)
    assert _slot(lived_apart, "taxable_social_security") is None
    assert lived_apart.point > lived_together.point


def test_jf2_5_intake_asks_the_lived_apart_fact_of_a_separate_filer_with_social_security():
    from taxfill_core.intake import intake_checklist  # noqa: PLC0415
    profile = _us_filer_married(Spouse(us_person=_ans(True)))
    profile.income_documents = [IncomeDocument(kind="SSA-1099", status="have", provenance=US)]
    ids = {q.id for q in intake_checklist(profile, tax_year=2023).next_questions}
    assert "household.spouses_lived_apart_all_year" in ids
    profile.household.filing_status = _ans("married_filing_jointly")     # a joint return never uses it
    assert "household.spouses_lived_apart_all_year" not in {
        q.id for q in intake_checklist(profile, tax_year=2023).next_questions}
    profile.household.filing_status = _ans("married_filing_separately")
    profile.household.spouses_lived_apart_all_year = _ans(False)
    assert "household.spouses_lived_apart_all_year" not in {
        q.id for q in intake_checklist(profile, tax_year=2023).next_questions}
    no_benefits = _us_filer_married(Spouse(us_person=_ans(True)))
    assert "household.spouses_lived_apart_all_year" not in {
        q.id for q in intake_checklist(no_benefits, tax_year=2023).next_questions}


# ---------------------------------------------------------------------------
# JF3 (pitfall P-019, box1-standin): W-2 boxes 3, 5 and 6 reach the estimator.
# Hypothetical demo fixtures only.
# ---------------------------------------------------------------------------

_BOX5 = "Box 1 wages stood in for box 5"


def _joint_couple() -> Profile:
    return Profile(household=Household(marital_status=_ans("married"),
                                       filing_status=_ans("married_filing_jointly")))


def _single_filer() -> Profile:
    return Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")))


def test_p019_form_8959_prices_box_5_not_box_1():
    # A 401(k) deferrer: box 1 under the $250,000 joint threshold, box 5 over it.
    base = IncomeSnapshot(wages=240_000, federal_withholding=40_000)
    no_box5 = estimate_refund(_joint_couple(), 2026, base)
    with_box5 = estimate_refund(_joint_couple(), 2026, base.model_copy(update={"medicare_wages": 262_000}))
    assert _slot(no_box5, "additional_medicare_tax") is None
    assert _slot(with_box5, "additional_medicare_tax") == round(0.009 * (262_000 - 250_000)) == 108
    assert no_box5.point - with_box5.point == 108
    # Without box 5, the stand-in is disclosed even though no Form 8959 line prints: box 1 plus the
    # year's 402(g) limit reaches the threshold.
    note = next(a for a in no_box5.assumptions if a.startswith("Additional Medicare Tax (Form 8959)"))
    assert _BOX5 in note and "402(g) deferral limit reaches it" in note and "is $0 on these amounts" in note
    assert not any(_BOX5 in a for a in with_box5.assumptions)


def test_p019_an_exempt_student_with_box_5_of_zero_owes_no_additional_medicare_tax():
    est = estimate_refund(_single_filer(), 2025,
                          IncomeSnapshot(wages=250_000, federal_withholding=50_000, medicare_wages=0))
    assert _slot(est, "additional_medicare_tax") is None
    box1 = estimate_refund(_single_filer(), 2025, IncomeSnapshot(wages=250_000, federal_withholding=50_000))
    assert _slot(box1, "additional_medicare_tax") == round(0.009 * 50_000)


def test_p019_schedule_se_subtracts_boxes_3_and_7():
    # 2026: the $184,500 wage base is used up by social security wages, so no SE social security tax.
    income = IncomeSnapshot(wages=170_000, federal_withholding=30_000, self_employment_net=50_000,
                            ss_wages=184_500)
    est = estimate_refund(_single_filer(), 2026, income)
    se_net_earnings = 50_000 * 0.9235
    assert _slot(est, "se_tax") == round(se_net_earnings * 0.029)          # the Medicare portion alone
    assert not any("ss_wages was not given" in a for a in est.assumptions)
    standin = estimate_refund(_single_filer(), 2026, income.model_copy(update={"ss_wages": None}))
    assert _slot(standin, "se_tax") > _slot(est, "se_tax")
    assert any("box 1 wages stood in for them because ss_wages was not given" in a for a in standin.assumptions)


def test_p019_box_6_above_the_regular_rate_is_credited():
    income = IncomeSnapshot(wages=260_000, federal_withholding=60_000, medicare_wages=260_000,
                            medicare_tax_withheld=[4_310])
    est = estimate_refund(_single_filer(), 2025, income)
    # 4,310 - 1.45% x 260,000 (3,770) = 540, the same 540 Form 8959 charges on the $60,000 over $200,000.
    assert _slot(est, "additional_medicare_withholding") == -540
    assert _slot(est, "additional_medicare_tax") == 540
    line = next(ln for ln in est.composition if ln.slot == "additional_medicare_withholding")
    from taxfill_core.knowledge import form_line  # noqa: PLC0415
    assert f"Form 8959 Part {form_line(2025, 'f8959.withholding_part')}" in line.label
    assert f"Form 1040 line {form_line(2025, 'f1040.additional_medicare_withholding')}" in line.label
    assert est.point == estimate_refund(_single_filer(), 2025, income.model_copy(
        update={"medicare_tax_withheld": []})).point + 540
    # A year whose pack has no employee Medicare rate says so, never a silent $0.
    old = estimate_refund(_single_filer(), 2023, income)
    assert _slot(old, "additional_medicare_withholding") is None
    assert any(a.startswith("NOT ESTIMATED — Additional Medicare Tax withholding") for a in old.assumptions)
    with pytest.raises(ValueError, match="requires medicare_wages"):
        IncomeSnapshot(wages=10_000, medicare_tax_withheld=[200])


def test_p019_the_joint_view_credits_box_6_only_for_the_spouse_who_gave_it():
    income = IncomeSnapshot(wages=260_000, federal_withholding=60_000, medicare_wages=260_000,
                            medicare_tax_withheld=[4_310],
                            spouse=IncomeSnapshot(wages=90_000, federal_withholding=12_000))
    est = estimate_refund(_joint_couple(), 2025, income)
    assert _slot(est, "additional_medicare_withholding") == -540      # the spouse's box 5 never enters it
    joint = income.combined_with_spouse()
    assert joint.medicare_wages == 260_000 + 90_000 and joint.medicare_tax_withheld == [4_310]
    note = next(a for a in est.assumptions if a.startswith("Additional Medicare Tax (Form 8959)"))
    assert "Box 1 wages stood in for box 5 for your spouse" in note


def test_p019_a_scenario_that_moves_wages_but_not_the_boxes_is_named():
    from taxfill_core.scenarios import compare_scenarios  # noqa: PLC0415
    income = IncomeSnapshot(wages=150_000, federal_withholding=25_000, medicare_wages=170_000)
    out = compare_scenarios(_single_filer(), 2025, income, [
        {"name": "base", "filing_status": "single"},
        {"name": "raise", "filing_status": "single", "income_overrides": {"wages": 160_000}},
        {"name": "both", "filing_status": "single",
         "income_overrides": {"wages": 160_000, "medicare_wages": 180_000}},
    ])
    named = [a for a in out.assumptions if "changes wages (W-2 box 1) but not medicare_wages" in a]
    assert len(named) == 1 and "'raise'" in named[0]


# ── JF7 (LD-09): Schedule 1-A reaches the estimator ─────────────────────────


def _s1a(**kw) -> IncomeSnapshot:
    return IncomeSnapshot(wages=60_000, federal_withholding=6_000, **kw)


def _slot(est_or_result, slot: str) -> int | None:
    lines = est_or_result.composition if hasattr(est_or_result, "composition") else est_or_result.lines
    return next((ln.amount for ln in lines if ln.slot == slot), None)


def test_jf7_schedule_1a_lowers_taxable_income_by_exactly_the_ops_total():
    from taxfill_core.calc import schedule_1a_deductions
    with_s1a = estimate_refund(Profile(), 2025, _s1a(qualified_tips=5_000, qualified_overtime_premium=3_000,
                                                      car_loan_interest=2_000))
    without = estimate_refund(Profile(), 2025, _s1a())
    op = schedule_1a_deductions(magi=60_000, filing_status="single", year=2025, qualified_tips=5_000,
                                qualified_overtime=3_000, car_loan_interest=2_000)
    assert _slot(without, "taxable_income") - _slot(with_s1a, "taxable_income") == op.total_deduction == 10_000
    line = next(ln for ln in with_s1a.composition if ln.slot == "schedule_1a_deductions")
    assert line.amount == -10_000 and "Form 1040 line 13b" in line.label      # read off the 2025 face
    assert with_s1a.point > without.point                                       # AGI and its MAGI tests unmoved
    assert _slot(with_s1a, "agi") == _slot(without, "agi")
    assert any("schedule_1a_deductions" in a and "MAGI is taken as AGI" in a for a in with_s1a.assumptions)


def test_jf7_the_mfs_candidate_forfeits_tips_overtime_and_senior_but_not_car_loan_interest():
    from taxfill_core.estimate import _bottom_line
    income = _s1a(qualified_tips=5_000, qualified_overtime_premium=3_000, car_loan_interest=2_000,
                  senior_taxpayer=True)
    mfs = _bottom_line(income, "married_filing_separately", 2025, None)
    mfj = _bottom_line(income, "married_filing_jointly", 2025, None)
    assert _slot(mfs, "schedule_1a_deductions") == -2_000        # car-loan interest only
    assert _slot(mfj, "schedule_1a_deductions") == -16_000       # tips + overtime + car loan + senior $6,000
    married = Profile(household=Household(marital_status=_ans("married")))
    est = estimate_refund(married, 2025, income)
    assert est.comparison is not None
    assert any("FORFEITED" in a and "car-loan interest is not" in a for a in est.assumptions)


def test_jf7_a_planning_year_without_the_block_names_it_missing(planning_year, synthetic_provisional_pack):
    # JT0b: a scratch planning pack that declares the block absent (2026 itself ships it since JF8).
    kdir = synthetic_provisional_pack(["obbba_schedule_1a"])
    est = estimate_refund(Profile(), planning_year, _s1a(qualified_tips=5_000), knowledge_dir=kdir)
    assert [(m.block, m.direction) for m in est.missing_blocks if m.block == "tax.obbba_schedule_1a"] == [
        ("tax.obbba_schedule_1a", "understates_refund")]
    assert any("NOT ESTIMATED" in a and "Schedule 1-A" in a for a in est.assumptions)
    assert _slot(est, "schedule_1a_deductions") is None


def test_jf8_the_2026_estimate_prices_schedule_1a_and_names_nothing_missing():
    est = estimate_refund(Profile(), 2026, _s1a(qualified_tips=5_000, car_loan_interest=1_200))
    assert _slot(est, "schedule_1a_deductions") == -6_200
    assert not [m for m in est.missing_blocks if m.block == "tax.obbba_schedule_1a"]
    label = next(ln.label for ln in est.composition if ln.slot == "schedule_1a_deductions")
    assert "line 13a" in label   # the 2026 draft Form 1040 line (13b in 2025)


def test_jf7_a_year_before_the_law_takes_none_and_says_why():
    est = estimate_refund(Profile(), 2024, _s1a(qualified_tips=5_000))
    assert _slot(est, "schedule_1a_deductions") is None
    assert not [m for m in est.missing_blocks if m.block == "tax.obbba_schedule_1a"]
    assert any("2025-2028 only" in a for a in est.assumptions)


def test_jf7_the_senior_deduction_comes_from_the_profiles_birth_date_and_ssn():
    def who(dob, tax_id):
        return Profile(identity=Identity(dob=_ans(dob), tax_id=_ans(tax_id) if tax_id else None))
    senior = estimate_refund(who(date(1958, 3, 1), "123-45-6789"), 2025, _s1a())
    assert _slot(senior, "schedule_1a_deductions") == -6_000                     # Part V, MAGI under $75,000
    for profile in (who(date(1958, 3, 1), "912-34-5678"),                        # an ITIN: no SSN
                    who(date(1961, 1, 2), "123-45-6789"),                        # not 65 by the end of 2025
                    who(date(1958, 3, 1), None)):                                # no tax ID recorded
        assert _slot(estimate_refund(profile, 2025, _s1a()), "schedule_1a_deductions") is None
    assert _slot(estimate_refund(who(date(1961, 1, 1), "123-45-6789"), 2025, _s1a()), "schedule_1a_deductions") == -6_000


# ── JR3a (RC-07 part 1): each 1099-R priced from its box 7 codes ─────────────

from taxfill_core.estimate import RetirementDistribution  # noqa: E402


def _with_1099r(*items, **kw) -> IncomeSnapshot:
    return IncomeSnapshot(wages=50_000, federal_withholding=5_000, retirement_distributions=list(items), **kw)


def test_jr3a_the_codes_price_each_1099r():
    cases = [
        (RetirementDistribution(gross=5_000, taxable_amount=5_000, codes="Q"), 0),         # qualified Roth
        (RetirementDistribution(gross=20_000, taxable_amount=0, codes="G"), 0),            # direct rollover
        (RetirementDistribution(gross=20_000, taxable_amount=0, codes="H"), 0),            # Roth plan -> Roth IRA
        (RetirementDistribution(gross=3_300, taxable_amount=0, codes="R"), 0),             # recharacterization
        (RetirementDistribution(gross=900, taxable_amount=150, codes="JP"), 0),            # taxable in the PRIOR year
        (RetirementDistribution(gross=8_000, taxable_amount=8_000, codes="7"), 8_000),
        (RetirementDistribution(gross=8_000, taxable_amount=8_000, codes="7", rolled_over=3_000), 5_000),
        (RetirementDistribution(gross=8_000, taxable_amount=8_000, codes="7", ira_sep_simple=True,
                                taxable_not_determined=True, taxable_override=1_200), 1_200),
    ]
    for item, taxable in cases:
        assert _with_1099r(item).total_income() - 50_000 == taxable, item.codes


def test_jr3a_prior_year_code_p_is_excluded_with_an_assumption():
    est = estimate_refund(Profile(), 2025, _with_1099r(
        RetirementDistribution(gross=900, taxable_amount=150, codes="JP", label="Roth IRA at a demo custodian")))
    note = next(a for a in est.assumptions if "code P" in a)
    assert "Roth IRA at a demo custodian" in note and "EXCLUDED" in note
    assert "taxable in 2024 or a previous year" in note                                 # the 2025 Table 1 title
    # An IRA's 2b-checked gross is priced through its owner's Form 8606 (JR3b) — and said so.
    ira = estimate_refund(Profile(), 2025, _with_1099r(RetirementDistribution(
        gross=6_000, taxable_amount=6_000, codes="7", ira_sep_simple=True, taxable_not_determined=True),
        ira_pool=IraPoolFacts(basis_carryforward=0)))
    assert any("Form 8606 Part I" in a and "own IRA pool" in a for a in ira.assumptions)


def test_jr3a_the_list_and_the_manual_figure_are_one_or_the_other():
    with pytest.raises(ValueError, match="not both"):
        IncomeSnapshot(retirement_income_taxable=1_000,
                       retirement_distributions=[RetirementDistribution(gross=1_000, taxable_amount=1_000, codes="7")])


def test_jr3a_the_joint_view_keeps_each_spouses_1099rs():
    mine = RetirementDistribution(gross=4_000, taxable_amount=4_000, codes="7")
    theirs = RetirementDistribution(gross=9_000, taxable_amount=0, codes="G")
    joint = IncomeSnapshot(retirement_distributions=[mine],
                           spouse=IncomeSnapshot(retirement_distributions=[theirs])).combined_with_spouse()
    assert joint.retirement_distributions == [mine, theirs] and joint.total_income() == 4_000
    mixed = IncomeSnapshot(retirement_distributions=[mine],
                           spouse=IncomeSnapshot(retirement_income_taxable=2_500)).combined_with_spouse()
    assert mixed.retirement_income_taxable == 0 and mixed.total_income() == 6_500     # the manual figure rides along
    manual = IncomeSnapshot(retirement_income_taxable=1_000,
                            spouse=IncomeSnapshot(retirement_income_taxable=2_500)).combined_with_spouse()
    assert manual.retirement_income_taxable == 3_500 and manual.retirement_distributions == []


# ── JR3b (RC-07 part 2): the per-person IRA pool ─────────────────────────────

from taxfill_core.estimate import IraPoolFacts  # noqa: E402


def _conversion(gross: int, label: str = "") -> RetirementDistribution:
    return RetirementDistribution(gross=gross, taxable_amount=gross, codes="2", ira_sep_simple=True,
                                  taxable_not_determined=True, converted_to_roth=True, label=label)


def _total_income(est) -> int:
    return next(ln.amount for ln in est.composition if ln.slot == "total_income")


def test_jr3b_recharacterize_then_convert_is_taxed_on_the_earnings_not_the_gross():
    """Illustrative: a Roth contribution recharacterized to a traditional IRA (code N, $7,000 of line-1 basis)
    and then converted ($7,250) — the taxable conversion is the $250 of net income and growth."""
    income = _with_1099r(
        RetirementDistribution(gross=7_100, taxable_amount=0, codes="N", label="recharacterization"),
        _conversion(7_250, "conversion"),
        ira_pool=IraPoolFacts(basis_carryforward=0, nondeductible_contributions_this_year=7_000, dec31_total_value=0))
    assert _total_income(estimate_refund(Profile(), 2025, income)) == 50_250


def test_jr3b_the_pool_is_required_and_zero_basis_is_the_explicit_answer():
    bare = _with_1099r(_conversion(6_000))
    with pytest.raises(ValueError, match="pass ira_pool for the taxpayer"):
        estimate_refund(Profile(), 2025, bare)
    no_basis = bare.model_copy(update={"ira_pool": IraPoolFacts(basis_carryforward=0)})
    assert _total_income(estimate_refund(Profile(), 2025, no_basis)) == 56_000
    with pytest.raises(ValueError, match="dec31_total_value"):
        estimate_refund(Profile(), 2025, bare.model_copy(update={"ira_pool": IraPoolFacts(basis_carryforward=500)}))


def test_jr3b_a_couples_pools_never_merge():
    mine = _with_1099r(_conversion(10_000), ira_pool=IraPoolFacts(basis_carryforward=10_000, dec31_total_value=0))
    theirs = IncomeSnapshot(retirement_distributions=[_conversion(10_000)], ira_pool=IraPoolFacts(basis_carryforward=0))
    married = Profile(household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_jointly")))
    est = estimate_refund(married, 2025, mine.model_copy(update={"spouse": theirs}))
    # The taxpayer's $10,000 is all basis (0 taxable); the spouse's is all pretax (10,000 taxable). A merged
    # pool would have taxed half of each.
    assert _total_income(est) == 50_000 + 10_000
    assert mine.model_copy(update={"spouse": theirs}).combined_with_spouse().ira_pool is None


# ── JR3c (RC-08): the 72(t) additional tax and the 4973 excise ───────────────


def _ledger(est) -> dict[str, int]:
    assert sum(ln.effect for ln in est.composition) == est.point           # the ledger reconciles
    return {ln.slot: ln.amount for ln in est.composition}


def test_jr3c_an_early_distribution_owes_the_10_percent_additional_tax():
    est = estimate_refund(Profile(), 2025, _with_1099r(RetirementDistribution(gross=12_000, taxable_amount=12_000,
                                                                              codes="1")))
    assert _ledger(est)["early_distribution_additional_tax"] == 1_200     # IRC 72(t)(1)
    line = next(ln.label for ln in est.composition if ln.slot == "early_distribution_additional_tax")
    assert "Form 5329 line 4 -> Schedule 2 line 8" in line                 # read off the 2025 faces
    excepted = estimate_refund(Profile(), 2025, _with_1099r(RetirementDistribution(
        gross=12_000, taxable_amount=12_000, codes="1", early_exception_amount=5_000)))
    assert _ledger(excepted)["early_distribution_additional_tax"] == 700
    simple = estimate_refund(Profile(), 2025, _with_1099r(RetirementDistribution(
        gross=4_000, taxable_amount=4_000, codes="S", ira_sep_simple=True)))
    assert _ledger(simple)["early_distribution_additional_tax"] == 1_000  # 72(t)(6): 25% in the first 2 years
    normal = estimate_refund(Profile(), 2025, _with_1099r(RetirementDistribution(gross=12_000, taxable_amount=12_000,
                                                                                 codes="7")))
    assert "early_distribution_additional_tax" not in _ledger(normal)


def test_jr3c_a_corrective_distributions_earnings_owe_no_additional_tax():
    est = estimate_refund(Profile(), 2025, _with_1099r(RetirementDistribution(gross=7_300, taxable_amount=300,
                                                                              codes="J8")))
    ledger = _ledger(est)
    assert "early_distribution_additional_tax" not in ledger
    assert ledger["total_income"] == 50_300                                  # the earnings stay taxable
    assert any("72(t)(2)(A)(ix)" in a for a in est.assumptions)


def test_jr3c_the_excess_contribution_excise_is_capped_at_the_year_end_value():
    capped = estimate_refund(Profile(), 2025, IncomeSnapshot(wages=50_000, roth_ira_excess=7_000,
                                                             roth_ira_dec31_value=5_000))
    assert _ledger(capped)["ira_excess_contribution_excise"] == 300          # 6% of min(7,000, 5,000)
    line = next(ln.label for ln in capped.composition if ln.slot == "ira_excess_contribution_excise")
    assert "Form 5329 lines 17/25 -> Schedule 2 line 8" in line
    uncapped = estimate_refund(Profile(), 2025, IncomeSnapshot(wages=50_000, traditional_ira_excess=2_000))
    assert _ledger(uncapped)["ira_excess_contribution_excise"] == 120
    assert any("4973(a) caps it" in a for a in uncapped.assumptions)
    draft = estimate_refund(Profile(), 2026, IncomeSnapshot(wages=50_000, roth_ira_excess=1_000))
    assert "Schedule 2 line 18" in next(ln.label for ln in draft.composition if ln.slot == "ira_excess_contribution_excise")


def test_jr3c_the_joint_view_caps_each_persons_excess_before_summing():
    joint = IncomeSnapshot(roth_ira_excess=7_000, roth_ira_dec31_value=1_000,
                           spouse=IncomeSnapshot(roth_ira_excess=2_000)).combined_with_spouse()
    assert joint.roth_ira_excess == 3_000 and joint.roth_ira_dec31_value is None
