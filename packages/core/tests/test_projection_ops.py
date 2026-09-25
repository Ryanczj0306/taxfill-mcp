"""Golden tests for the H4 projection trio: employee_fica, estimated_tax_safe_harbor,
annualize_ytd — plus the PROJECTION output contract and the PriorFilings fields.

Every FICA/safe-harbor vector is hand-computed from the Pub 15 / Form 1040-ES
figures the packs transcribe (verbatim-quote verified against the 2025 and 2026
editions before the blocks were authored). The traps pinned here are the ones
a mid-year planning question hits:

  * N-7b — the F/J student FICA exemption is STATUS-based, not marital: a
    §6013(g) election does not start FICA on an exempt F/J spouse's wages —
    and it is a NONRESIDENT exemption: a resident alien owes FICA on the same
    F/J wages (Pub 519 ch. 8), which residency_classification enforces;
  * the 110% safe-harbor tier keys on the PRIOR year's AGI but the CURRENT
    year's filing status (the $75,000 MFS variant);
  * N-12 / P-017 — the flat 22% on bonuses is the employer's OPTION, only when
    Treas. Reg. 31.3402(g)-1(a)(7)(i)(B) and (C) hold; otherwise the aggregate
    procedure is required.

All data is synthetic. Offline.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from taxfill_core.calc import annualize_ytd, employee_fica, estimated_tax_safe_harbor
from taxfill_core.schemas.profile import Answer, PriorFilings, Provenance

US = Provenance.user_stated()


# ── employee_fica ──────────────────────────────────────────────────────────────


def test_fica_switches_on_at_the_status_boundary():
    # Demo numbers (a mechanical fixture): F-1 OPT (exempt individual)
    # Jan 1-Jul 14, a cap-exempt H-1B Jul 15-Dec 31, at $8,000/month with July
    # split by days (14 OPT / 17 H-1B of 31): OPT 6 x 8,000 + 3,613 = 51,613,
    # H-1B 5 x 8,000 + 4,387 = 44,387. FICA applies ONLY to the H-1B segment —
    # that boundary is the single biggest cash-flow fact of the transition year.
    r = employee_fica([
        {"label": "OPT (F-1, exempt individual)", "wages": 51_613, "fica_exempt": True},
        {"label": "H-1B (cap-exempt) from Jul 15", "wages": 44_387, "fica_exempt": False},
    ], year=2025)
    assert r.social_security == Decimal("2751.99")  # 6.2% x 44,387 = 2,751.994
    assert r.medicare == Decimal("643.61")          # 1.45% x 44,387 = 643.6115
    assert r.additional_medicare == Decimal("0.00")
    assert r.total_fica == Decimal("3395.60")
    exempt = r.segments[0]
    assert exempt.total == Decimal("0.00") and exempt.exempt_reason is not None


def test_the_exemption_is_status_based_not_marital():
    # N-7b, quoted in the work so the agent states it unprompted: a §6013(g)
    # election changes the FILING posture, never the FICA status.
    r = employee_fica([{"label": "OPT", "wages": 50_000, "fica_exempt": True}], year=2025)
    assert "STATUS-based" in r.work and "§6013(g)" in r.work
    assert "does NOT start FICA" in r.work


def test_wage_base_is_one_annual_pool_across_segments():
    # 2026 base $184,500: segment A consumes 150,000; B is taxed on 34,500 only.
    r = employee_fica([
        {"label": "A", "wages": 150_000, "fica_exempt": False},
        {"label": "B", "wages": 100_000, "fica_exempt": False},
    ], year=2026)
    assert r.social_security == Decimal("11439.00")  # the exact per-person max
    assert r.segments[0].social_security == Decimal("9300.00")
    assert r.segments[1].social_security == Decimal("2139.00")
    # Medicare has no base; the 0.9% starts at $200,000 cumulative — all of it
    # lands on the segment that crosses the trigger.
    assert r.segments[1].additional_medicare == Decimal("450.00")  # 0.9% x 50,000
    assert "excess_ss" in r.work  # the per-employer nuance is disclosed


# ── the converse: the F/J/M/Q exemption belongs to a NONRESIDENT (Pub 519 ch. 8) ──

_PUB519_CONVERSE = "even though your nonimmigrant classification"


def test_the_work_quotes_the_resident_alien_converse():
    r = employee_fica([{"label": "OPT", "wages": 50_000, "fica_exempt": True}], year=2025)
    assert "NONRESIDENT exemption" in r.work and _PUB519_CONVERSE in r.work
    assert "Pub 519 ch. 8" in r.segments[0].exempt_reason


@pytest.mark.parametrize(
    "segment",
    [
        {"label": "F-1 OPT", "wages": 30_000, "fica_exempt": True},
        {"label": "on-campus job", "visa_status": "F-1", "wages": 30_000, "fica_exempt": True},
        {"label": "research", "visa_status": "J-1 researcher", "wages": 30_000, "fica_exempt": True},
        {"label": "anything", "wages": 30_000, "fica_exempt": True, "exempt_basis": "fjmq_nonresident"},
    ],
)
def test_a_resident_aliens_fjmq_exempt_segment_is_refused_quoting_pub_519(segment):
    with pytest.raises(ValueError, match="residency_classification is 'resident'") as exc:
        employee_fica([segment], year=2025, residency_classification="resident")
    assert _PUB519_CONVERSE in str(exc.value) and "Pub 519 ch. 8" in str(exc.value)
    assert "student_employed_by_school" in str(exc.value)  # the other exemption is named


def test_a_resident_keeps_a_different_exemption_and_owes_fica_on_the_rest():
    # Demo numbers: a resident-alien F-1 student employed by the school it attends
    # (Pub 519's tip), plus an off-campus internship that owes FICA.
    r = employee_fica([
        {"label": "RA at the university", "visa_status": "F-1", "wages": 20_000, "fica_exempt": True,
         "exempt_basis": "student_employed_by_school"},
        {"label": "summer internship", "visa_status": "F-1", "wages": 10_000, "fica_exempt": False},
    ], year=2025, residency_classification="resident")
    assert "regularly attending classes" in r.segments[0].exempt_reason
    assert r.social_security == Decimal("620.00") and r.medicare == Decimal("145.00")
    assert r.inputs["residency_classification"] == "resident"


def test_nonresident_and_unclassified_keep_todays_exemption():
    for cls in ("nonresident", None):
        r = employee_fica(
            [{"label": "F-1 OPT", "wages": 51_613, "fica_exempt": True}], year=2025, residency_classification=cls
        )
        assert r.total_fica == Decimal("0.00")


def test_a_residents_unnamed_exempt_segment_is_flagged_not_refused():
    r = employee_fica(
        [{"label": "segment A", "wages": 5_000, "fica_exempt": True}], year=2025, residency_classification="resident"
    )
    reason = r.segments[0].exempt_reason
    assert "CHECK: residency_classification is 'resident'" in reason and _PUB519_CONVERSE in reason
    # The nonresident lead-in would contradict the CHECK for a resident.
    assert "owes no FICA" not in reason and "exempt-individual nonresident" not in reason


@pytest.mark.parametrize("label", ["Q1 wages", "M&T Bank payroll", "J1 Ventures LLC", "FY2025 bonus"])
def test_a_label_that_only_looks_like_a_status_is_flagged_not_refused(label):
    # With no visa_status, a label counts as F/J/M/Q only in its visa shape (F-1, J-1,
    # OPT ...): "Q1 wages" is a quarter, "M&T" a bank — never refused as a visa.
    r = employee_fica(
        [{"label": label, "wages": 5_000, "fica_exempt": True}], year=2025, residency_classification="resident"
    )
    assert "CHECK: residency_classification is 'resident'" in r.segments[0].exempt_reason


def test_a_refusal_read_off_the_label_says_so():
    with pytest.raises(ValueError, match=r"label 'J-1 postdoc', read as an F/J/M/Q status — pass visa_status"):
        employee_fica(
            [{"label": "J-1 postdoc", "wages": 5_000, "fica_exempt": True}], year=2025,
            residency_classification="resident",
        )
    # An explicit non-F/J/M/Q visa_status overrides the label's reading.
    r = employee_fica(
        [{"label": "F-1 OPT", "visa_status": "H-1B", "wages": 5_000, "fica_exempt": True}], year=2025,
        residency_classification="resident",
    )
    assert "CHECK" in r.segments[0].exempt_reason


def test_a_dual_status_year_says_to_split_at_the_residency_start():
    r = employee_fica(
        [{"label": "F-1 OPT", "wages": 20_000, "fica_exempt": True}], year=2025,
        residency_classification="dual_status_candidate",
    )
    assert "Dual-status year" in r.work and "residency starting date" in r.work


def test_residency_inputs_are_validated():
    with pytest.raises(ValueError, match="residency_classification must be one of"):
        employee_fica([{"wages": 1_000, "fica_exempt": False}], year=2025, residency_classification="US")
    with pytest.raises(ValueError, match="exempt_basis must be one of"):
        employee_fica([{"wages": 1_000, "fica_exempt": True, "exempt_basis": "treaty"}], year=2025)
    with pytest.raises(ValueError, match="exempt_basis must be one of"):
        employee_fica([{"wages": 1_000, "fica_exempt": True, "exempt_basis": ["x"]}], year=2025)


def test_mcp_dispatch_passes_residency_classification():
    from taxfill_mcp.server import calc

    with pytest.raises(ValueError, match="Pub 519 ch. 8"):
        calc("employee_fica", {
            "wage_segments": [{"label": "F-1 OPT", "wages": 1_000, "fica_exempt": True}],
            "year": 2025, "residency_classification": "resident",
        })


def test_fica_prescriptive_errors():
    with pytest.raises(ValueError, match="non-empty"):
        employee_fica([], year=2025)
    with pytest.raises(ValueError, match="fica_exempt"):
        employee_fica([{"wages": 1000}], year=2025)
    # Years whose packs predate the medicare fields fail closed with the fix named.
    with pytest.raises(ValueError, match="Pub 15"):
        employee_fica([{"wages": 1000, "fica_exempt": False}], year=2023)


# ── estimated_tax_safe_harbor ──────────────────────────────────────────────────


def test_the_110_percent_tier_and_the_shortfall():
    # A joint return: prior AGI $226,000 > $150,000 -> 110% x $36,000 = $39,600;
    # that beats the 90% prong ($54,000), so the required payment is $39,600 —
    # withholding $38,000 leaves a $1,600 shortfall, $400/quarter.
    r = estimated_tax_safe_harbor(
        60_000, 38_000, "married_filing_jointly", 2026, prior_year_agi=226_000, prior_year_total_tax=36_000
    )
    assert r.current_year_prong == 54_000
    assert r.prior_year_prong == 39_600 and r.prior_pct_applied == Decimal("1.10")
    assert r.required_annual_payment == 39_600
    assert r.estimated_payments_required is True
    assert r.shortfall == 1_600 and r.quarterly_payment == 400


def test_the_100_percent_tier_below_the_threshold():
    r = estimated_tax_safe_harbor(
        30_000, 20_000, "single", 2025, prior_year_agi=120_000, prior_year_total_tax=18_000
    )
    assert r.prior_pct_applied == Decimal("1.00") and r.prior_year_prong == 18_000
    assert r.required_annual_payment == 18_000  # min(27,000, 18,000)


def test_mfs_uses_the_75k_threshold_keyed_on_the_current_years_status():
    # Prior AGI $80,000 would be BELOW the general $150,000 threshold — but the
    # CURRENT year's status is MFS, so the $75,000 variant applies -> 110%.
    r = estimated_tax_safe_harbor(
        10_000, 9_200, "married_filing_separately", 2025,
        prior_year_agi=80_000, prior_year_total_tax=9_000,
    )
    assert r.prior_pct_applied == Decimal("1.10")
    # De minimis: expected balance $800 < $1,000 -> no estimated payments due.
    assert r.estimated_payments_required is False and r.shortfall == 0


def test_without_prior_figures_only_the_90_prong_runs_and_says_so():
    r = estimated_tax_safe_harbor(60_000, 50_000, "single", 2026)
    assert r.prior_year_prong is None and r.prior_pct_applied is None
    assert r.required_annual_payment == 54_000
    assert "NOT evaluated" in r.work and "often SMALLER" in r.work


def test_prior_figures_are_both_or_neither():
    with pytest.raises(ValueError, match="BOTH"):
        estimated_tax_safe_harbor(60_000, 40_000, "single", 2026, prior_year_agi=100_000)
    with pytest.raises(ValueError, match="BOTH"):
        estimated_tax_safe_harbor(60_000, 40_000, "single", 2026, prior_year_total_tax=30_000)


@pytest.mark.parametrize("year", [2025, 2026])
def test_p017_the_supplemental_wage_trap_is_quoted_with_its_precondition(year):
    # N-12 + P-017: the work still teaches that a bonus withheld at the flat 22%
    # under-withholds for a higher-bracket filer — but only as the employer's
    # OPTION under Treas. Reg. 31.3402(g)-1(a)(7)(i), with the aggregate fallback
    # and the $1,000,000 mandatory rate, never as an unconditional rule.
    r = estimated_tax_safe_harbor(60_000, 40_000, "single", year)
    for phrase in (
        "31.3402(g)-1(a)(7)(i)", "separately stated", "aggregate", "AGGREGATE", "OPTION",
        "Income tax has been withheld from regular wages", "use method 1b", "(a)(6)(i)",
        "$1,000,000", "37%", "Hire status is not the test", "pay stub", "22%", "bonus",
    ):
        assert phrase in r.work, phrase
    for gone in ("regardless of your marginal rate", "Project expected_withholding as 22% x bonus"):
        assert gone not in r.work, gone
    assert f"Pub 15 ({year})" in r.work
    # And the farmers/fishermen substitution is quoted, never computed.
    assert "66 2/3%" in r.work


@pytest.mark.parametrize("year", [2025, 2026])
def test_p017_the_pack_carries_the_conditions_verbatim(year):
    from taxfill_core.knowledge import load_knowledge

    sw = load_knowledge("federal", year).tax.supplemental_withholding
    assert sw.flat_rate == Decimal("0.22") and sw.flat_rate_optional is True
    assert sw.method_if_conditions_fail == "aggregate"
    quotes = {c.paragraph: " ".join(c.quote.split()) for c in sw.flat_rate_conditions}
    assert quotes["31.3402(g)-1(a)(7)(i)(B)"] == (
        "The supplemental wages are either not paid concurrently with regular wages or are separately "
        "stated on the payroll records of the employer"
    )
    assert quotes["31.3402(g)-1(a)(7)(i)(C)"] == (
        "Income tax has been withheld from regular wages of the employee during the calendar year of "
        "the payment or the preceding calendar year"
    )
    assert sw.conditions_citation.url == "https://www.ecfr.gov/current/title-26/section-31.3402(g)-1"
    assert "(a)(7) of this section may not be used" in " ".join(sw.aggregate_rule.split())
    assert "exceeds $1,000,000" in " ".join(sw.mandatory_rate_rule.split())


def test_p017_the_schema_refuses_the_flat_rate_without_its_conditions():
    from pydantic import ValidationError

    from taxfill_core.knowledge import load_knowledge, SupplementalWithholdingParams

    good = load_knowledge("federal", 2026).tax.supplemental_withholding.model_dump(mode="json")
    only_b = {**good, "flat_rate_conditions": [good["flat_rate_conditions"][0]]}
    with pytest.raises(ValidationError, match=r"missing \['31.3402\(g\)-1\(a\)\(7\)\(i\)\(C\)'\]"):
        SupplementalWithholdingParams.model_validate(only_b)
    wrong_pin = {**good, "flat_rate_conditions": [
        {"paragraph": "31.3402(g)-1(a)(6)(i)", "quote": "x"}, *good["flat_rate_conditions"]
    ]}
    with pytest.raises(ValidationError, match="must pinpoint"):
        SupplementalWithholdingParams.model_validate(wrong_pin)
    with pytest.raises(ValidationError):
        SupplementalWithholdingParams.model_validate({**good, "flat_rate_optional": False})
    bare = {k: good[k] for k in ("citation", "flat_rate", "high_rate", "high_threshold")}
    with pytest.raises(ValidationError, match="flat_rate_conditions"):
        SupplementalWithholdingParams.model_validate(bare)  # the pre-JF1a shape no longer loads


def test_safe_harbor_fails_closed_for_years_without_the_block():
    with pytest.raises(ValueError, match="estimated_tax_safe_harbor block"):
        estimated_tax_safe_harbor(60_000, 40_000, "single", 2023)


# ── annualize_ytd ──────────────────────────────────────────────────────────────


def test_annualize_prorates_by_calendar_days():
    # 2026-08-31 is day 243 of 365: 80,000 x 365/243 = 120,164.6 -> 120,165.
    r = annualize_ytd(80_000, "2026-08-31", 2026)
    assert (r.days_elapsed, r.days_in_year, r.annualized) == (243, 365, 120_165)
    assert "LEVEL PAY" in r.work and "bonus" in r.work.lower()


def test_annualize_handles_leap_years_and_rejects_wrong_year_dates():
    r = annualize_ytd(10_000, "2024-12-31", 2024)
    assert r.days_in_year == 366 and r.annualized == 10_000  # full year = identity
    with pytest.raises(ValueError, match="not in year"):
        annualize_ytd(80_000, "2025-08-31", 2026)


# ── the PriorFilings fields and the PROJECTION contract ────────────────────────


def test_prior_filings_gains_the_safe_harbor_fields_and_stays_backward_compatible():
    # Old profiles (no new keys) still load; the new fields carry provenance.
    old_shape = PriorFilings.model_validate({"filed_years": {"value": [2025], "provenance": US.model_dump()}})
    assert old_shape.prior_year_agi is None and old_shape.prior_year_total_tax is None
    full = PriorFilings(
        filed_years=Answer(value=[2025], provenance=US),
        prior_year_agi=Answer(value=226_000, provenance=US),
        prior_year_total_tax=Answer(value=36_000, provenance=US),
    )
    assert full.prior_year_agi.value == 226_000


def test_intake_asks_for_the_safe_harbor_figures_once_a_filed_year_exists():
    from taxfill_core.intake import intake_checklist
    from taxfill_core.schemas.profile import Profile

    p = Profile(prior_filings=PriorFilings(filed_years=Answer(value=[2025], provenance=US)))
    ids = [q.id for q in intake_checklist(p, tax_year=2026).next_questions]
    assert "prior_filings.safe_harbor_figures" in ids
    # Answered -> the question stops.
    p.prior_filings.prior_year_agi = Answer(value=100_000, provenance=US)
    p.prior_filings.prior_year_total_tax = Answer(value=12_000, provenance=US)
    ids = [q.id for q in intake_checklist(p, tax_year=2026).next_questions]
    assert "prior_filings.safe_harbor_figures" not in ids


def test_mcp_dispatch_and_the_provisional_stamp():
    # A 2026 (planning-pack) FICA projection carries the provisional stamp; the
    # same call on 2025 (filing-grade) does not. annualize_ytd takes no year pack
    # and is never stamped.
    from taxfill_mcp.server import calc

    out26 = calc("employee_fica", {"wage_segments": [{"wages": 1000, "fica_exempt": False}], "year": 2026})
    assert "provisional" in out26
    out25 = calc("employee_fica", {"wage_segments": [{"wages": 1000, "fica_exempt": False}], "year": 2025})
    assert "provisional" not in out25
    out = calc("annualize_ytd", {"ytd_amount": 50_000, "through": "2026-06-30", "year": 2026})
    assert out["annualized"] > 50_000 and "provisional" not in out


def test_1099int_extraction_carries_the_nra_deposit_interest_note():
    # N-8: extract_document happily structured a 1099-INT with no hint that the
    # payee's STATUS decides whether box 1 is income at all. The note names the
    # exclusion (IRC 871(i)(2)(A)) and the real trigger — the §6013(g) ELECTION,
    # not the marriage, ends it.
    from taxfill_core.extract import extract_document

    doc = extract_document("docs/1099int.jpg", "1099-INT", {"1": "1250"})
    assert "871(i)(2)(A)" in doc.caveat
    assert "the election, not the marriage" in doc.caveat
    # Other kinds are untouched.
    w2 = extract_document("docs/w2.jpg", "W-2", {"1": "50000"})
    assert "871" not in w2.caveat


def test_p017_and_the_fica_converse_reach_every_use_site():
    # The knowledge-gap pattern: a rule only in the registry still gets missed, so the
    # op docstrings, the server tool doc and SKILL.md carry it too.
    from pathlib import Path

    from taxfill_core import calc as calc_module
    from taxfill_core.knowledge import SupplementalWithholdingParams
    from taxfill_mcp.server import calc as calc_tool

    skill = (Path(__file__).resolve().parents[3] / "skills" / "claude" / "SKILL.md").read_text()
    for text in (
        estimated_tax_safe_harbor.__doc__, calc_module.__doc__, SupplementalWithholdingParams.__doc__,
        calc_tool.__doc__, skill,
    ):
        assert "31.3402(g)-1(a)(7)(i)" in text
        assert "aggregate" in text.lower()
        assert "flat-22% supplemental-wage trap" not in text and "flat-22% bonus withholding trap" not in text
        assert "22% x bonus" not in text
    for text in (employee_fica.__doc__, calc_module.__doc__, calc_tool.__doc__, skill):
        assert "resident alien" in text and "Pub 519 ch. 8" in text
    # SKILL.md's Recipe B4 narrows the converse to the F/J/M/Q ground: a resident's
    # wages can still be exempt as a student employed by the school it attends.
    b4 = " ".join(skill[skill.index("### Recipe B4"):].split())
    assert "NOT withheld in error ON THE F/J/M/Q GROUND" in b4
    assert "enrolled and regularly attending classes at a school" in b4 and "totalization agreement" in b4
    assert "residency_classification" in calc_tool.__doc__ and "residency_classification" in skill
