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
    # H1: a confirmed nonresident alien files Form 1040-NR, which has no MFJ column.
    # The primary/recommended status must NOT be MFJ, and the §6013 caveat must appear.
    profile = Profile(
        household=Household(marital_status=_ans("married")),
        identity=Identity(us_person=_ans(False)),
        immigration=_nra_immigration(),
        residency_facts=_nra_residency(),
    )
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=90000, federal_withholding=9000))
    assert est.filing_status_used == "married_filing_separately"
    # MFJ is dropped entirely — not a candidate, not recommended.
    if est.comparison is not None:
        statuses = {c.status for c in est.comparison.candidates}
        assert "married_filing_jointly" not in statuses
        assert est.comparison.recommended_status != "married_filing_jointly"
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
    assert any("8a-9" in a for a in est.assumptions)


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
    assert est.comparison is None  # MFJ dropped -> one candidate, no MFJ recommendation
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
    assert "Pub 519 ch. 3" in note and "line 2b, Exception 3" in note
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
    assert any(a.startswith("NIIT under the §6013(g)/(h) election: the joint-return figure") for a in est.assumptions)


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
    # A recorded election with no confirmed status prices MFJ AND MFS under it; the MFS
    # candidate evaluates NIIT on the formerly-nonresident spouse too and says so.
    profile = _us_filer_married(_nra_spouse())
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    income = IncomeSnapshot(wages=200_000, federal_withholding=40_000, interest=20_000,
                            spouse=IncomeSnapshot(wages=10_000, dividends=15_000))
    est = estimate_refund(profile, 2023, income)
    note = next(a for a in est.assumptions if a.startswith("NIIT under the §6013(g)/(h) election"))
    assert "the joint-return figure evaluates" in note
    assert "separate return here evaluates" in note and "may be overstated" in note
    assert "1.1411-2(a)(2)(iii)(B)" in note and "and Without" not in note


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
    assert "which the recorded facts cannot show yet" in caveat              # worded on the facts recorded (JF5b)
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
    nr_single = 3_000 - tax_from_taxable_income(40_000, "single", 2023).tax
    # The year of a spouse's death with no confirmed status: the candidates are 'single'
    # only (JF1b.9), so the election is refused and the estimate says why.
    widowed = _nra_profile(marital="widowed", spouse_death_year=_ans(2023), spouse=Spouse(us_person=_ans(True)))
    widowed.residency_facts.section_6013_election = _ans(True)
    est = estimate_refund(widowed, 2023, income)
    assert est.filing_status_used == "single" and est.point == nr_single
    assert est.residency_caveat is None or "RESIDENT rules for both spouses" not in est.residency_caveat
    note = next(a for a in est.assumptions if "NOT applied" in a)
    assert "year of your spouse's death" in note and "considered married for the whole year" in note
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
    assert est.filing_status_used == "single" and _election_in_effect(profile, 2023) is False
    note = next(n for n in intake_checklist(profile, tax_year=2023).notes if "NOT applied" in n)
    assert "year of your spouse's death" in note and "not married for the year" not in note


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
    note = next(a for a in estimate_refund(both, 2023, IncomeSnapshot(wages=40_000, federal_withholding=3_000))
                .assumptions if a.startswith("The head-of-household figure"))
    assert "prices the confirmed status as given" in note and "living apart" not in note


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
    assert hoh.bottom_line > next(o.bottom_line for o in r.outcomes if o.name == "single")
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
