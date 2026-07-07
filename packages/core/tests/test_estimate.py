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


# A confirmed-nonresident visa timeline (prototype F-1: years N..N+4 are exempt, so
# every counted day is excluded and the SPT fails -> nonresident). Mirrors test_residency
# PROTOTYPE_F1 / test_prototype_exempt_years_classify_nonresident for the 2023 target year.
def _nra_immigration():
    return Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2019, 8, 20), end=None, provenance=US)])


def _nra_residency():
    return ResidencyFacts(
        days_in_us={y: _ans(d) for y, d in {2019: 134, 2020: 330, 2021: 330, 2022: 330, 2023: 330}.items()}
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


def test_roadmap_dual_status_branch_returns_both_forms():
    # Residency-driven roadmap: a DUAL-STATUS classification (F-1 transition still inside
    # the exempt window) yields both 1040 and 1040-NR (closes the dual-status branch).
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
    assert est.roadmap.returns_and_forms == [
        "Form 1040",
        "Form 1040-NR (dual-status: both may apply for the split year)",
        "Form 8843",
    ]


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
    # ECI/FDAP + 871(i) deposit-interest caveats must be disclosed.
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
    assert any("871(i)" in a and "OVERTAX" in a for a in est.assumptions)
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
                VisaPeriod(status="F-1", start=date(2021, 8, 20), end=date(2023, 3, 31), provenance=US),
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
            {"status": "F-1", "start": "2021-08-20", "end": "2023-03-31"},
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
