"""Golden tests for the H4 projection trio: employee_fica, estimated_tax_safe_harbor,
annualize_ytd — plus the PROJECTION output contract and the PriorFilings fields.

Every FICA/safe-harbor vector is hand-computed from the Pub 15 / Form 1040-ES
figures the packs transcribe (verbatim-quote verified against the 2025 and 2026
editions before the blocks were authored). The traps pinned here are the ones
the one real planning session had to derive by hand:

  * N-7b — the F/J student FICA exemption is STATUS-based, not marital: a
    §6013(g) election does not start FICA on the OPT spouse's wages;
  * the 110% safe-harbor tier keys on the PRIOR year's AGI but the CURRENT
    year's filing status (the $75,000 MFS variant);
  * N-12 — bonuses are withheld at the flat 22% regardless of marginal rate.

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
    # The motivating persona: F-1 OPT (exempt individual) Jan-Sep, H-1B Oct-Dec.
    # FICA applies ONLY to the H-1B segment — that boundary is the single biggest
    # cash-flow fact of the transition year.
    r = employee_fica([
        {"label": "OPT (F-1, exempt individual)", "wages": 90_000, "fica_exempt": True},
        {"label": "H-1B from the I-797 start", "wages": 30_000, "fica_exempt": False},
    ], year=2026)
    assert r.social_security == Decimal("1860.00")  # 6.2% x 30,000
    assert r.medicare == Decimal("435.00")          # 1.45% x 30,000
    assert r.additional_medicare == Decimal("0.00")
    assert r.total_fica == Decimal("2295.00")
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
    # Prior AGI $194,600 > $150,000 -> 110% x $38,000 = $41,800; that beats the
    # 90% prong ($54,000), so the required payment is $41,800 — withholding
    # $40,000 leaves a $1,800 shortfall, $450/quarter.
    r = estimated_tax_safe_harbor(
        60_000, 40_000, "single", 2026, prior_year_agi=194_600, prior_year_total_tax=38_000
    )
    assert r.current_year_prong == 54_000
    assert r.prior_year_prong == 41_800 and r.prior_pct_applied == Decimal("1.10")
    assert r.required_annual_payment == 41_800
    assert r.estimated_payments_required is True
    assert r.shortfall == 1_800 and r.quarterly_payment == 450


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


def test_the_supplemental_wage_trap_is_quoted():
    # N-12: the work must teach that a bonus withheld at the flat 22% under-
    # withholds for a higher-bracket filer — this is where the April surprise
    # becomes visible BEFORE April.
    r = estimated_tax_safe_harbor(60_000, 40_000, "single", 2026)
    assert "22" in r.work and "FLAT" in r.work and "bonus" in r.work.lower()
    # And the farmers/fishermen substitution is quoted, never computed.
    assert "66 2/3%" in r.work


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
        prior_year_agi=Answer(value=194_600, provenance=US),
        prior_year_total_tax=Answer(value=38_000, provenance=US),
    )
    assert full.prior_year_agi.value == 194_600


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
