"""Phase I4 (foreign-asset half): Form 8938, the FBAR worksheet, and the thresholds.

Offline by design. Every GOLDEN figure below is a LITERAL amount transcribed from
the primary source named beside it — Treas. Reg. 1.6038D-2(a)(1)-(4), the
Instructions for Form 8938 (Rev. November 2021) "Types of Reporting Thresholds",
31 CFR 1010.306(c), 31 U.S.C. 5321(a)(5), 31 CFR 1010.821 Table 1, IRC 6038D(d)
and 6662(j)(3) — NOT a value recomputed by the engine. If the engine disagrees
with a golden figure, the engine (or the pack) is wrong, never the fixture
(dev plan section 10).

The thresholds are STATUTORY and NOT inflation-indexed, so the year-invariance
sweep here is a real check rather than a formality: it fails the moment someone
"updates" one year's figures and leaves the others behind.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from taxfill_core.calc import foreign_asset_reporting
from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack_for
from taxfill_core.intake import intake_checklist
from taxfill_core.knowledge import load_knowledge
from taxfill_core.schemas.formpack import load_pack
from taxfill_core.schemas.profile import IncomeDocument, Profile, Provenance
from taxfill_core.sources import get_sources

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
SHIPPED_YEARS = tuple(int(p.stem) for p in sorted((KNOWLEDGE_DIR / "federal").glob("[0-9][0-9][0-9][0-9].yaml")))
PACK_YEARS = (2023, 2024, 2025)
US = Provenance(kind="user_stated")

# Treas. Reg. 1.6038D-2(a): (a)(1) $50,000/$75,000 general rule, (a)(2)
# $100,000/$150,000 married filing a JOINT annual return, (a)(3)
# $200,000/$300,000 for a section 911(d)(1) qualified individual, (a)(4)
# $400,000/$600,000 for such an individual filing jointly. The instructions add
# the two the regulation leaves implicit (MFS and specified domestic entity).
GOLDEN_8938 = {
    "in_us": {
        "single": (50_000, 75_000),
        "married_filing_jointly": (100_000, 150_000),
        "married_filing_separately": (50_000, 75_000),
        "head_of_household": (50_000, 75_000),
        "qualifying_surviving_spouse": (50_000, 75_000),
    },
    "abroad": {
        "single": (200_000, 300_000),
        "married_filing_jointly": (400_000, 600_000),
        "married_filing_separately": (200_000, 300_000),
        "head_of_household": (200_000, 300_000),
        "qualifying_surviving_spouse": (200_000, 300_000),
    },
}
GOLDEN_ENTITY = (50_000, 75_000)
GOLDEN_FBAR_THRESHOLD = 10_000  # 31 CFR 1010.306(c)


# ══ the knowledge block ══════════════════════════════════════════════════════


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_every_shipped_year_carries_the_block(year: int):
    """Year parity. The figures are statutory and unindexed, so there is no year
    a filer could work on that should be missing them — including the back-file
    years, where the exposure is identical."""
    far = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).foreign_account_reporting
    assert far is not None, f"knowledge/federal/{year}.yaml has no foreign_account_reporting block"


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_form_8938_thresholds_match_the_regulation(year: int):
    t = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).foreign_account_reporting.form_8938.thresholds
    for where, buckets in GOLDEN_8938.items():
        got = getattr(t, where)
        for status, (year_end, any_time) in buckets.items():
            assert (got[status].year_end, got[status].any_time) == (year_end, any_time), (
                f"{year} {where}/{status}: pack has "
                f"({got[status].year_end}, {got[status].any_time}), Treas. Reg. 1.6038D-2(a) says "
                f"({year_end}, {any_time})"
            )
    assert (t.specified_domestic_entity.year_end, t.specified_domestic_entity.any_time) == GOLDEN_ENTITY


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_qss_takes_the_unmarried_amounts_not_the_joint_ones(year: int):
    """The trap this block exists to close.

    ``calc._resolve_filing_status`` maps qualifying_surviving_spouse onto the
    married-filing-jointly COLUMN because a QSS uses the joint RATE schedule.
    Applying that here would DOUBLE a QSS filer's Form 8938 threshold and let a
    real filing obligation go unreported. Treas. Reg. 1.6038D-2(a)(2)/(a)(4) are
    keyed to filers who "file a joint annual return"; a QSS does not.
    """
    t = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).foreign_account_reporting.form_8938.thresholds
    for where in ("in_us", "abroad"):
        b = getattr(t, where)
        assert b["qualifying_surviving_spouse"] == b["single"], f"{year} {where}: QSS must match single"
        assert b["qualifying_surviving_spouse"] != b["married_filing_jointly"], (
            f"{year} {where}: QSS must NOT take the joint amounts"
        )


def test_thresholds_are_identical_across_every_shipped_year():
    """Not indexed, so any year-over-year difference is a defect, not an update."""
    seen = {}
    for year in SHIPPED_YEARS:
        far = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).foreign_account_reporting
        seen[year] = (
            far.form_8938.thresholds.model_dump(mode="json"),
            far.fbar.aggregate_threshold,
            far.form_8938.penalties.maximum_per_year,
            far.fbar.penalties.non_willful_adjusted_maximum,
        )
        assert far.form_8938.inflation_indexed is False
        assert far.fbar.inflation_indexed is False
    first = seen[SHIPPED_YEARS[0]]
    for year, value in seen.items():
        assert value == first, f"{year} diverges from {SHIPPED_YEARS[0]}: statutory figures must not drift"


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_fbar_threshold_shape_and_channel(year: int):
    f = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).foreign_account_reporting.fbar
    assert f.aggregate_threshold == GOLDEN_FBAR_THRESHOLD
    # The three facts about the $10,000 that get misread.
    assert f.threshold_is_aggregate is True
    assert f.threshold_is_maximum_value is True
    assert f.threshold_varies_by_filing_status is False
    # The measuring period differs from Form 8938's, and that is load-bearing for
    # a fiscal-year filer.
    assert f.measured_over == "calendar_year"
    # E-file only; a printed Form 114 is refused, which is WHY there is no pack.
    assert f.efile_only is True and f.printed_form_not_accepted is True
    # The regulation's own printed due date is stale — pinned so nobody "fixes"
    # the deadline by reading 31 CFR 1010.306(c).
    assert f.regulation_due_date_is_stale is True
    assert f.due_date_month_day == "04-15" and f.automatic_extension_month_day == "10-15"
    assert f.extension_request_required is False


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_penalty_figures_and_units(year: int):
    far = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).foreign_account_reporting
    p8, pf = far.form_8938.penalties, far.fbar.penalties
    # IRC 6038D(d)(1)-(2) and 6662(j)(3).
    assert p8.failure_to_file == 10_000
    assert p8.continuing_failure_per_30_days == 10_000
    assert p8.continuing_failure_grace_days_after_notice == 90
    assert p8.continuing_failure_additional_cap == 50_000
    assert p8.maximum_per_year == 60_000
    assert float(p8.accuracy_related_rate_undisclosed_foreign_asset) == 0.40
    assert float(p8.fraud_rate) == 0.75
    # 31 U.S.C. 5321(a)(5) + 31 CFR 1010.821 Table 1 (assessed on/after 2025-01-17).
    assert pf.non_willful_statutory_maximum == 10_000
    assert pf.non_willful_adjusted_maximum == 16_536
    assert pf.willful_statutory_minimum_maximum == 100_000
    assert pf.willful_adjusted_minimum_maximum == 165_353
    assert float(pf.willful_alternative_share_of_balance) == 0.50
    assert pf.adjusted_by_assessment_date_not_tax_year is True
    # Bittner v. United States, 598 U.S. 85 (2023): non-willful is PER REPORT.
    # Pub 5569 (3-2022) predates it and says only "per violation".
    assert pf.non_willful_unit == "per_report"
    assert pf.willful_unit == "per_account"
    assert "598 U.S. 85" in pf.bittner_citation.source or "Bittner" in pf.bittner_citation.source


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_every_citation_is_an_official_gov_url(year: int):
    far = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).foreign_account_reporting
    urls = [
        far.citation.url,
        far.form_8938.citation.url, far.form_8938.statute_url, far.form_8938.instructions_url,
        far.form_8938.penalties.citation.url,
        far.fbar.citation.url, far.fbar.statute_url, far.fbar.regulation_url, far.fbar.efile_url,
        far.fbar.penalties.citation.url, far.fbar.penalties.inflation_adjustment_url,
        far.fbar.penalties.bittner_citation.url,
    ]
    for u in urls:
        assert u.startswith("https://") and ".gov" in u, u


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_scope_differences_are_not_a_superset_either_way(year: int):
    """Neither filing subsumes the other, and the op/skills text says so — pinned
    against the IRS comparison table's own rows."""
    s = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR).foreign_account_reporting.scope_differences
    joined = " ".join(s.fbar_only).lower()
    assert "signature authority" in joined and "branch of a u.s. financial institution" in joined
    joined8 = " ".join(s.form_8938_only).lower()
    assert "partnership interest" in joined8 and "hedge fund" in joined8
    assert any("real estate held directly" in x.lower() for x in s.neither)
    assert s.fbar_only and s.form_8938_only  # a superset in either direction would empty one list


def test_block_is_top_level_in_the_yaml_not_nested():
    """Nesting under `tax` or `credits` would evade the section-7 sources-coverage
    meta-test (test_knowledge_m3.py walks TOP-LEVEL keys only)."""
    for year in SHIPPED_YEARS:
        raw = yaml.safe_load((KNOWLEDGE_DIR / "federal" / f"{year}.yaml").read_text(encoding="utf-8"))
        assert "foreign_account_reporting" in raw, year
        assert "foreign_account_reporting" not in (raw.get("tax") or {})
        assert "foreign_account_reporting" not in (raw.get("credits") or {})


# ══ calc.foreign_asset_reporting ═════════════════════════════════════════════


@pytest.mark.parametrize("status,year_end,any_time", [
    ("single", 50_000, 75_000),
    ("married_filing_jointly", 100_000, 150_000),
    ("married_filing_separately", 50_000, 75_000),
    ("head_of_household", 50_000, 75_000),
    ("qualifying_surviving_spouse", 50_000, 75_000),
])
def test_op_applies_the_in_us_ladder_by_status(status, year_end, any_time):
    r = foreign_asset_reporting(year=2025, filing_status=status, us_person=True, lives_abroad=False,
                               specified_asset_value_year_end=0, specified_asset_value_max=0,
                               foreign_account_value_max_aggregate=0)
    assert (r.form_8938.threshold_year_end, r.form_8938.threshold_any_time) == (year_end, any_time)


def test_op_never_gives_a_qss_the_joint_threshold():
    """A QSS with $60,000 at year end MUST file; on the joint ladder it would not."""
    qss = foreign_asset_reporting(year=2025, filing_status="qualifying_surviving_spouse", us_person=True,
                                  lives_abroad=False, specified_asset_value_year_end=60_000,
                                  specified_asset_value_max=60_000, foreign_account_value_max_aggregate=0)
    mfj = foreign_asset_reporting(year=2025, filing_status="married_filing_jointly", us_person=True,
                                  lives_abroad=False, specified_asset_value_year_end=60_000,
                                  specified_asset_value_max=60_000, foreign_account_value_max_aggregate=0)
    assert qss.form_8938.required is True
    assert mfj.form_8938.required is False


def test_either_8938_test_alone_triggers_the_filing():
    """Treas. Reg. 1.6038D-2(a) joins the two tests with 'or', so a filer who
    empties the account before December 31 still files."""
    r = foreign_asset_reporting(year=2025, us_person=True, lives_abroad=False,
                               specified_asset_value_year_end=0,          # nothing left on the last day
                               specified_asset_value_max=80_000,           # but $80k mid-year
                               foreign_account_value_max_aggregate=0)
    assert r.form_8938.required is True
    assert r.form_8938.tripped_by == ["any_time"]


def test_thresholds_are_exceeded_not_met():
    """"exceeds" / "more than" — a value EQUAL to the threshold does not file."""
    at = foreign_asset_reporting(year=2025, us_person=True, lives_abroad=False,
                                 specified_asset_value_year_end=50_000, specified_asset_value_max=75_000,
                                 foreign_account_value_max_aggregate=10_000)
    assert at.form_8938.required is False and at.fbar.required is False
    over = foreign_asset_reporting(year=2025, us_person=True, lives_abroad=False,
                                   specified_asset_value_year_end=50_001, specified_asset_value_max=75_000,
                                   foreign_account_value_max_aggregate=10_001)
    assert over.form_8938.required is True and over.fbar.required is True


def test_fbar_threshold_ignores_filing_status():
    for status in ("single", "married_filing_jointly", "married_filing_separately",
                   "head_of_household", "qualifying_surviving_spouse"):
        r = foreign_asset_reporting(year=2025, filing_status=status, us_person=True, lives_abroad=False,
                                   specified_asset_value_year_end=0, specified_asset_value_max=0,
                                   foreign_account_value_max_aggregate=10_500)
        assert r.fbar.threshold_any_time == 10_000
        assert r.fbar.required is True, f"{status}: MFJ does not double the FBAR $10,000"


def test_missing_value_is_undecided_never_a_silent_no():
    """The most expensive wrong answer in the repo is a quiet 'no'."""
    r = foreign_asset_reporting(year=2025, us_person=True, lives_abroad=False,
                               specified_asset_value_max=40_000)  # no year-end value, no account value
    assert r.form_8938.required is None
    assert r.fbar.required is None
    assert r.any_duty_undecided is True
    assert r.must_ask, "an undecided duty must name the fact to elicit"
    assert any("last day of the tax year" in q for q in r.must_ask)


def test_unknown_abroad_status_answers_when_both_ladders_agree():
    below = foreign_asset_reporting(year=2025, us_person=True,
                                    specified_asset_value_year_end=10_000, specified_asset_value_max=20_000,
                                    foreign_account_value_max_aggregate=0)
    assert below.form_8938.required is False and not below.form_8938.must_ask
    above = foreign_asset_reporting(year=2025, us_person=True,
                                    specified_asset_value_year_end=900_000, specified_asset_value_max=900_000,
                                    foreign_account_value_max_aggregate=0)
    assert above.form_8938.required is True and not above.form_8938.must_ask


def test_unknown_abroad_status_is_undecided_when_the_ladders_disagree():
    r = foreign_asset_reporting(year=2025, us_person=True,
                               specified_asset_value_year_end=120_000, specified_asset_value_max=130_000,
                               foreign_account_value_max_aggregate=0)
    assert r.form_8938.required is None
    assert r.form_8938.tripped_by == [], "no test may read as 'tripped' while the ladder is unknown"
    ask = " ".join(r.must_ask)
    assert "911(d)(1)" in ask and "330 full days" in ask
    assert "in-US -> REQUIRED" in ask and "qualified individual -> not required" in ask


def test_nonresident_alien_gets_no_for_both_with_the_two_exceptions_named():
    r = foreign_asset_reporting(year=2025, us_person=False,
                               specified_asset_value_year_end=999_999, specified_asset_value_max=999_999,
                               foreign_account_value_max_aggregate=999_999)
    assert r.form_8938.required is False and r.fbar.required is False
    work = r.work
    assert "8938" in work and "FBAR" in work


def test_us_person_unknown_leaves_both_undecided():
    r = foreign_asset_reporting(year=2025, specified_asset_value_year_end=1, specified_asset_value_max=1,
                               foreign_account_value_max_aggregate=1)
    assert r.form_8938.required is None and r.fbar.required is None
    assert len(r.must_ask) == 2


def test_signature_authority_without_the_value_test_is_undecided_not_no():
    """The case where the two answers legitimately differ: 31 CFR 1010.350(a)
    reaches signature authority, Form 8938 generally does not."""
    r = foreign_asset_reporting(year=2025, us_person=True, lives_abroad=False,
                               specified_asset_value_year_end=0, specified_asset_value_max=0,
                               foreign_account_value_max_aggregate=5_000,
                               has_foreign_account_signature_authority=True)
    assert r.form_8938.required is False
    assert r.fbar.required is None
    assert any("signature or other authority" in q for q in r.must_ask)


def test_specified_domestic_entity_uses_its_own_bucket():
    r = foreign_asset_reporting(year=2025, filing_status="married_filing_jointly", us_person=True,
                               filer_type="specified_domestic_entity",
                               specified_asset_value_year_end=60_000, specified_asset_value_max=60_000,
                               foreign_account_value_max_aggregate=0)
    # $50k/$75k regardless of the (irrelevant) filing status passed.
    assert (r.form_8938.threshold_year_end, r.form_8938.threshold_any_time) == GOLDEN_ENTITY
    assert r.form_8938.required is True


def test_op_refuses_impossible_and_unknown_inputs():
    with pytest.raises(ValueError, match="cannot be negative"):
        foreign_asset_reporting(year=2025, us_person=True, lives_abroad=False,
                                specified_asset_value_year_end=-1, specified_asset_value_max=0,
                                foreign_account_value_max_aggregate=0)
    with pytest.raises(ValueError, match="below specified_asset_value_year_end"):
        foreign_asset_reporting(year=2025, us_person=True, lives_abroad=False,
                                specified_asset_value_year_end=100, specified_asset_value_max=50,
                                foreign_account_value_max_aggregate=0)
    with pytest.raises(ValueError, match="unknown filing_status"):
        foreign_asset_reporting(year=2025, filing_status="mfj", us_person=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown filer_type"):
        foreign_asset_reporting(year=2025, filer_type="individual", us_person=True)


def test_op_answers_both_duties_and_says_neither_substitutes():
    r = foreign_asset_reporting(year=2025, us_person=True, lives_abroad=False,
                               specified_asset_value_year_end=0, specified_asset_value_max=0,
                               foreign_account_value_max_aggregate=50_000)
    # Under the 8938 ladder but over the FBAR one — the modal home-country case.
    assert r.form_8938.required is False and r.fbar.required is True
    assert "not part of the tax return" in r.work.lower() or "NOT\nparty" in r.work
    assert "does not satisfy the other" in r.work
    assert "16,536" in r.fbar.penalty_exposure and "PER REPORT" in r.fbar.penalty_exposure
    assert "60,000" in r.form_8938.penalty_exposure and "40%" in r.form_8938.penalty_exposure
    assert "BSA E-Filing System" in r.fbar.filed_with
    assert "October 15" in r.fbar.due


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_op_works_for_every_shipped_year(year: int):
    r = foreign_asset_reporting(year=year, us_person=True, lives_abroad=False,
                               specified_asset_value_year_end=60_000, specified_asset_value_max=60_000,
                               foreign_account_value_max_aggregate=60_000)
    assert r.form_8938.required is True and r.fbar.required is True


def test_op_refuses_a_year_with_no_block(tmp_path):
    """Fail closed and prescriptively, the house pattern."""
    (tmp_path / "federal").mkdir()
    src = (KNOWLEDGE_DIR / "federal" / "2025.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(src)
    raw.pop("foreign_account_reporting")
    (tmp_path / "federal" / "2025.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="no foreign_account_reporting block"):
        foreign_asset_reporting(year=2025, us_person=True, knowledge_dir=tmp_path)


# ══ get_sources routing ══════════════════════════════════════════════════════

_TOPIC = "foreign_asset_and_fbar_reporting"


@pytest.mark.parametrize("query", [
    "FBAR", "Form 8938", "FinCEN Form 114", "foreign bank account", "foreign financial account",
    "specified foreign financial assets", "report foreign accounts", "6038D",
    "foreign asset disclosure", "foreign account reporting", "foreign account penalty",
    "do I have to report my foreign account", "unreported foreign bank account",
])
def test_foreign_reporting_queries_route_to_the_new_topic(query: str):
    """Before this topic existed these were six clean misses and four WRONG-LAW
    pointers: "foreign bank account" landed on Pub 525's bank-BONUS doctrine
    (other_income_and_rewards) and the three "foreign financial asset" phrasings
    on Pub 550 (investment_income). Neither says a word about a filing duty whose
    non-willful penalty starts at five figures."""
    r = get_sources(query, 2025, base_dir=KNOWLEDGE_DIR)
    assert r.matched, query
    assert {s.topic for s in r.sources} == {_TOPIC}, f"{query!r} routed to {sorted({s.topic for s in r.sources})}"


@pytest.mark.parametrize("query,expected", [
    # NEIGHBOUR THEFT is this repo's companion bug to a missing topic, and the
    # first spelling of this topic (`foreign_account_reporting`, with "account"
    # in the KEY, which get_sources scores at 30 points) stole P-005's own pinned
    # "bank account bonus income" query. The key was renamed to fix it; these pin
    # the neighbours that must not move again.
    ("bank account bonus income", "other_income_and_rewards"),
    ("credit card rewards taxable", "other_income_and_rewards"),
    ("cash rebate income", "other_income_and_rewards"),
    ("foreign tax credit", "foreign_tax_credit"),
    ("capital gains basis", "investment_income"),
    ("foreign earned income exclusion", "foreign_earned_income"),
    ("Schedule NEC", "nonresident_fdap"),
    ("qualified parking", "commuter_and_fringe_benefits"),
    ("underpayment penalty", "estimated_tax"),
])
def test_new_topic_does_not_steal_its_neighbours(query: str, expected: str):
    r = get_sources(query, 2025, base_dir=KNOWLEDGE_DIR)
    assert {s.topic for s in r.sources} == {expected}, (
        f"{query!r} routed to {sorted({s.topic for s in r.sources})}, expected {expected!r}"
    )


def test_topic_cites_both_agencies_and_the_regulations():
    r = get_sources("FBAR", 2025, base_dir=KNOWLEDGE_DIR)
    hosts = " ".join(s.url for s in r.sources)
    assert "fincen.gov" in hosts, "FinCEN's own FBAR instructions must be in the registry"
    assert "irs.gov" in hosts
    assert "ecfr.gov/current/title-31/section-1010.350" in hosts
    assert "ecfr.gov/current/title-26/section-1.6038D-2" in hosts
    assert "uscode.house.gov" in hosts


# ══ the intake elicitation ═══════════════════════════════════════════════════


def test_foreign_account_question_is_asked_unprompted():
    """A filer never volunteers this: the account produced no US tax document and
    often no taxable income, so nothing in a refund-shaped interview surfaces it."""
    p = Profile(income_documents=[IncomeDocument(kind="W-2", status="have", provenance=US)])
    q = next(x for x in intake_checklist(p, tax_year=2025).next_questions
             if x.id == "income_documents.foreign_accounts")
    assert "OUTSIDE the United States" in q.prompt
    assert "signing authority" in q.prompt          # the FBAR-only case
    assert "HIGHEST balance" in q.prompt            # not the year-end balance
    assert "$10,000" in q.why and "8938" in q.why
    assert "16,536" in q.why                        # the real, inflation-adjusted exposure
    assert q.disambiguation is not None
    assert "AGGREGATE" in q.disambiguation and "does NOT double" in q.disambiguation


@pytest.mark.parametrize("kind", [
    "foreign account statement", "FBAR", "FinCEN 114", "Form 8938",
    "HDFC savings — foreign bank statement", "overseas account statement",
])
def test_question_stops_once_the_answer_is_recorded_however_spelled(kind: str):
    p = Profile(income_documents=[
        IncomeDocument(kind="W-2", status="have", provenance=US),
        IncomeDocument(kind=kind, status="not_applicable", provenance=US),
    ])
    ids = {x.id for x in intake_checklist(p, tax_year=2025).next_questions}
    assert "income_documents.foreign_accounts" not in ids, f"{kind!r} did not record the answer"


def test_recorded_no_stays_silent_but_a_yes_produces_the_note():
    no = Profile(income_documents=[
        IncomeDocument(kind="foreign account statement", status="not_applicable", provenance=US)])
    assert not [n for n in intake_checklist(no, tax_year=2025).notes if "foreign financial account" in n]

    yes = Profile(income_documents=[
        IncomeDocument(kind="foreign account statement", status="have", provenance=US)])
    note = next(n for n in intake_checklist(yes, tax_year=2025).notes if "foreign financial account" in n)
    assert "foreign_asset_reporting" in note                 # the op to run
    assert "hand_fill_worksheet('fincen114', 2025, 'federal')" in note
    assert "NOT part of the tax return envelope" in note
    assert "April 15 2026" in note and "October 15" in note  # the deadline and the auto extension
    assert "$10,000" in note and "$50,000" in note
    assert "QUALIFYING SURVIVING SPOUSE takes the $50,000/$75,000" in note
    assert "get_sources('FBAR')" in note


# ══ the FBAR hand-fill worksheet ═════════════════════════════════════════════


@pytest.mark.parametrize("year", PACK_YEARS)
def test_fbar_worksheet_is_federal_and_never_says_print_and_mail(year: int):
    pack = load_hand_fill_pack_for("fincen114", year, "federal")
    assert pack.jurisdiction == "federal" and pack.tax_year == year
    assert pack.form == "FinCEN Form 114"
    assert pack.mailing is None, "nothing is mailed anywhere — there is no address to give"
    ws = hand_fill_worksheet(pack, {})
    # The class default ("Print the blank at print_url and hand-write each value
    # onto its line") is WRONG here: irs.gov refuses a printed Form 114 outright.
    assert ws.instructions.startswith("DO NOT PRINT AND MAIL THIS FORM")
    assert "hand-write" not in ws.instructions
    assert "BSA E-Filing System" in ws.instructions
    assert "NOT part of your tax return" in ws.instructions
    assert "$10,000" in ws.instructions
    assert "AUTOMATIC" in ws.instructions and "October 15" in ws.instructions
    assert pack.signature_note is not None and "no ink signature" in pack.signature_note
    assert "114a" in pack.signature_note and "FIVE YEARS" in pack.signature_note


@pytest.mark.parametrize("year", PACK_YEARS)
def test_fbar_worksheet_computes_the_aggregate_threshold_test(year: int):
    """The point of the worksheet. Two accounts under $10,000 each whose maxima
    sum over it are both reportable — the aggregate is what the regulation tests."""
    pack = load_hand_fill_pack_for("fincen114", year, "federal")
    ws = hand_fill_worksheet(pack, {"account1_15": 6_000, "account2_15": 4_500})
    by = {ln.line: (ln.value, ln.source) for ln in ws.lines}
    assert by["aggregate_maximum_value"] == ("10,500", "computed")
    # It must come LAST: hand_fill_worksheet resolves in printed order and a
    # compute can only see EARLIER lines, so a threshold total placed first
    # silently computes 0.
    assert ws.lines[-1].line == "aggregate_maximum_value"
    note = next(ln.note for ln in pack.lines if ln.line == "aggregate_maximum_value")
    assert "EXCEEDS $10,000" in note and "not per account" in note
    assert "SIGNATURE OR OTHER AUTHORITY" in note  # sigauth accounts are in the aggregate too


@pytest.mark.parametrize("year", PACK_YEARS)
def test_fbar_worksheet_carries_the_items_a_filer_must_have_ready(year: int):
    pack = load_hand_fill_pack_for("fincen114", year, "federal")
    keys = {ln.line for ln in pack.lines}
    assert len(keys) == len(pack.lines), "duplicate line key — computes would collide"
    # Part I identity, all three separately-owned account slots, the joint block,
    # the signature-authority block, and the electronic signature.
    for k in ("1", "2", "3", "5", "6", "7", "9", "13", "14a", "count_14a", "14b", "count_14b",
              "account1_15", "account1_17", "account1_18", "account2_15", "account3_15",
              "joint_15", "joint_24", "joint_26", "sigauth_15", "sigauth_34", "sigauth_43",
              "44", "45", "46"):
        assert k in keys, f"missing {k}"
    # Part V (consolidated, entity-only) and the preparer section are out of scope
    # on purpose and must not appear half-done.
    assert not any(k.startswith("part5") or k.startswith("preparer") for k in keys)


# ══ the Form 8938 packs ══════════════════════════════════════════════════════


@pytest.mark.parametrize("year", PACK_YEARS)
def test_f8938_pack_shape(year: int):
    pack = load_pack(REPO_ROOT / "formpacks" / "federal" / str(year) / "f8938" / "pack.yaml")
    assert pack.form == "8938" and pack.jurisdiction == "federal" and pack.tax_year == year
    # All three years pin the SAME revision artifact — Form 8938 is revision-dated
    # (Rev. 11-2021) and carries no printed tax year.
    assert pack.source_url == "https://www.irs.gov/pub/irs-prior/f8938--2021.pdf"
    assert pack.pdf_sha256 == "841fe09a3999c44080ef33f0e476aed45acc8c9e60f034ffdb7f27cf969601ef"
    assert pack.acroform_root == "topmostSubform[0]"
    assert len(pack.fields) == 131  # every widget on the blank is mapped
    kinds = {t: sum(1 for f in pack.fields if f.type == t) for t in ("text", "money", "checkbox")}
    assert kinds == {"text": 74, "money": 19, "checkbox": 38}
    # The form face carries no arithmetic and no cross-form equality.
    assert pack.relations == [] and pack.cross_form == []
    assert pack.identity_fields == ["name", "identifying_number"]
    # Attachment-only: "Attach to your tax return.", Attachment Sequence No. 938.
    assert pack.signature is None and pack.mailing is None


@pytest.mark.parametrize("year", PACK_YEARS)
def test_f8938_every_option_set_is_grouped_except_the_check_all_that_apply_rows(year: int):
    """Every checkbox on this blank is its OWN terminal /Btn field — the topology
    where nothing in the PDF or the engine makes an option set exclusive, so a
    missing `group` lets fill_form answer one question both Yes and No."""
    pack = load_pack(REPO_ROOT / "formpacks" / "federal" / str(year) / "f8938" / "pack.yaml")
    ungrouped = {f.line for f in pack.fields if f.type == "checkbox" and not f.group}
    # Printed "Check all that apply" (22a-d) and the two unrelated booleans that
    # share printed row 31c/31d: multiple boxes are LEGAL, so an at-most-one
    # audit would false-FAIL a correct return (the f843 line-4/5 pattern).
    assert ungrouped == {"22a", "22b", "22c", "22d", "31c", "31d"}
    groups: dict[str, list[str]] = {}
    for f in pack.fields:
        if f.type == "checkbox" and f.group:
            groups.setdefault(f.group, []).append(f.line)
    assert set(groups) == {
        "additional_statements", "line3", "line9", "line12", "line20", "line24",
        "line32", "line33", "35c", "36a.information_for", "36b", "36c",
    }
    assert len(groups["line3"]) == 4 and len(groups["line20"]) == 2
    assert len(groups["36b"]) == 5 and len(groups["line32"]) == 4
    # P-003: the two questions every filer must answer are required groups.
    required = {f.group for f in pack.fields if f.type == "checkbox" and f.required}
    assert required == {"line3", "line20"}
    # No two options of one group may reuse an on_state.
    for g, lines in groups.items():
        states = [f.on_state for f in pack.fields if f.group == g]
        assert len(states) == len(set(states)), f"group {g} reuses an on_state"


@pytest.mark.parametrize("year", PACK_YEARS)
def test_f8938_part_iii_grid_is_keyed_by_printed_row_and_column(year: int):
    """The row-key convention: <printed row>.<printed column letter>, the same
    spelling sched_d uses for `1b.d` and sched_e for `3.a`. Columns (a) and (b)
    are PRINTED TEXT with no widget, so they have no line keys at all."""
    pack = load_pack(REPO_ROOT / "formpacks" / "federal" / str(year) / "f8938" / "pack.yaml")
    keys = {f.line for f in pack.fields}
    by = {f.line: f for f in pack.fields}
    for row in ("13", "14"):
        for letter in "abcdefg":
            assert f"{row}{letter}.c" in keys and by[f"{row}{letter}.c"].type == "money"
            assert f"{row}{letter}.d" in keys and by[f"{row}{letter}.d"].type == "text"
            assert f"{row}{letter}.e" in keys and by[f"{row}{letter}.e"].type == "text"
            assert f"{row}{letter}.a" not in keys and f"{row}{letter}.b" not in keys
    assert sum(1 for k in keys if k.startswith(("13", "14")) and "." in k) == 42
    # No ReadOnly widget is bound anywhere on this form (measured: /Ff is only
    # ever 0 or 8388608 on the blank), so P-007 has nothing to adjudicate.
    assert all(f.comb is False for f in pack.fields)
    # The only /MaxLen boxes on the form, with their real widget lengths.
    maxlens = {f.line: f.maxlen for f in pack.fields if f.maxlen is not None}
    assert maxlens == {
        "calendar_year": 2, "tax_year_begin.year": 2, "tax_year_end.year": 2,
        "identifying_number": 11, "4b": 11,
        "26b.part1": 6, "26b.part2": 5, "26b.part3": 2, "26b.part4": 3,
        "35b.part1": 6, "35b.part2": 5, "35b.part3": 2, "35b.part4": 3,
    }


# ══ the file_and_pay envelope note ═══════════════════════════════════════════


def test_attaching_8938_warns_that_the_fbar_is_not_in_this_envelope():
    """The envelope trap: a filer who just attached Form 8938 believes the
    foreign-account job is finished, and the FBAR is a different filing to a
    different agency on a much lower threshold."""
    from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay

    r = file_and_pay([FilingManifestItem(form="1040", tax_year=2025, bottom_line=-1200,
                                         state="CA", attached_forms=["8938"])])
    note = next(n for ret in r.returns for n in ret.notes if "FBAR" in n)
    assert "NOT, and CANNOT BE, in this envelope" in note
    assert "bsaefiling.fincen.treas.gov" in note
    assert "April 15, 2026" in note and "October 15, 2026" in note
    assert "SIGNATURE AUTHORITY" in note
    assert "foreign_asset_reporting" in note and "hand_fill_worksheet('fincen114', 2025, 'federal')" in note


def test_the_envelope_note_is_not_volunteered_without_an_8938():
    from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay

    r = file_and_pay([FilingManifestItem(form="1040", tax_year=2025, bottom_line=0, state="CA")])
    assert not [n for ret in r.returns for n in ret.notes if "FBAR" in n]


@pytest.mark.parametrize("spelling", ["8938", "Form 8938", "form-8938", "F8938"])
def test_the_envelope_note_matches_however_8938_was_spelled(spelling: str):
    from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay

    r = file_and_pay([FilingManifestItem(form="1040-NR", tax_year=2024, bottom_line=100,
                                         state="NY", attached_forms=[spelling])])
    assert [n for ret in r.returns for n in ret.notes if "FBAR" in n], spelling


# ══ discoverability of a hand-fill-only form ══════════════════════════════════


def test_get_form_map_points_at_hand_fill_worksheet_for_a_handfill_only_form():
    """``list_forms`` globs pack.yaml, so a hand-fill pack is invisible to it.
    Without the pointer the error tells an agent the FBAR does not exist — and
    for the FBAR there is no fillable PDF anywhere to find instead."""
    from taxfill_core.discovery import get_form_map, load_form_pack

    for loader in (get_form_map, load_form_pack):
        with pytest.raises(FileNotFoundError) as exc:
            loader("fincen114", 2025, "federal")
        msg = str(exc.value)
        assert "DOES ship" in msg and "HAND-FILL pack" in msg
        assert "hand_fill_worksheet('fincen114', 2025, 'federal')" in msg
    # The hint fires for the print-only STATE packs too — the pre-existing half
    # of the same gap.
    with pytest.raises(FileNotFoundError) as exc:
        get_form_map("ct1040", 2023, "states/ct")
    assert "hand_fill_worksheet('ct1040', 2023, 'states/ct')" in str(exc.value)
    # A form that really does not exist gets no misleading hint.
    with pytest.raises(FileNotFoundError) as exc:
        get_form_map("does_not_exist", 2025, "federal")
    assert "hand_fill_worksheet" not in str(exc.value)


def test_undecidable_values_ask_about_the_value_not_about_living_abroad():
    """Misdirected elicitation is a defect, not a stylistic issue.

    With no year-end figure NEITHER ladder can be decided, so ``lives_abroad`` is
    not the missing fact — asking the IRC 911(d)(1) question there sends the
    interview after an answer that changes nothing. (The first draft did exactly
    that; caught by running the op, not by reading it.)
    """
    r = foreign_asset_reporting(year=2025, us_person=True, specified_asset_value_max=40_000)
    assert r.form_8938.required is None
    asked = " ".join(r.must_ask)
    assert "911(d)(1)" not in asked
    assert "last day of the tax year" in asked
    assert "lives_abroad is not what is missing" in r.work


# ══ P-012: the two defects this tranche's own review found ═══════════════════


@pytest.mark.parametrize("kind", [
    "Chase checking acct 1145 statement",   # a DOMESTIC bank account
    "1099-INT acct 1140023",                # a domestic 1099 carrying an account number
    "1099-DIV 1099-B combined 1140",
])
def test_p012_a_domestic_account_number_containing_114_does_not_record_the_answer(kind: str):
    """P-012, defect 1. ``kind`` is free text an agent writes, so it routinely
    carries an ACCOUNT NUMBER — and matching the bare three digits "114" (the
    FinCEN form number) made a US bank's account number read as a recorded
    foreign-account answer. Reproduced before the fix: the question was
    SUPPRESSED, silencing the steepest-penalty question in the interview, while
    ``_foreign_account_note`` simultaneously fired and told the filer to e-file an
    FBAR for a domestic account. Only spellings that name the FORM match now.
    """
    p = Profile(income_documents=[IncomeDocument(kind=kind, status="have", provenance=US)])
    checklist = intake_checklist(p, tax_year=2025)
    ids = {x.id for x in checklist.next_questions}
    assert "income_documents.foreign_accounts" in ids, (
        f"{kind!r} suppressed the foreign-account question — a domestic document must never "
        f"count as the recorded answer"
    )
    assert not [n for n in checklist.notes if "foreign financial account" in n], (
        f"{kind!r} produced the foreign-account note — a domestic account must never be told to "
        f"file an FBAR"
    )


@pytest.mark.parametrize("kind", ["FinCEN 114", "Form 114", "FBAR", "Form 8938"])
def test_p012_the_form_spellings_still_record_the_answer(kind: str):
    """The other side of the same fix: tightening the token must not lose the
    spellings that really do name the form, or the question never stops.
    """
    p = Profile(income_documents=[IncomeDocument(kind=kind, status="not_applicable", provenance=US)])
    ids = {x.id for x in intake_checklist(p, tax_year=2025).next_questions}
    assert "income_documents.foreign_accounts" not in ids, f"{kind!r} no longer records the answer"


@pytest.mark.parametrize("year", PACK_YEARS)
def test_p012_the_op_discloses_the_no_return_precondition(year: int):
    """P-012, defect 2. Treas. Reg. 1.6038D-2(a)(7)(i) — read on the eCFR text,
    not recalled — says a specified person "is not required to file Form 8938 ...
    if the specified person is not required to file an annual return with the
    Internal Revenue Service". The op cannot test that (it never sees the
    filer's gross income), so a REQUIRED verdict is conditional and the work
    string has to say so; nothing else in the repo carried the rule. The FBAR is
    NOT subject to it — a different filing, with its own duty.
    """
    r = foreign_asset_reporting(
        year=year, us_person=True, lives_abroad=False,
        specified_asset_value_year_end=600_000, specified_asset_value_max=600_000,
        foreign_account_value_max_aggregate=600_000,
    )
    assert r.form_8938.required is True and r.fbar.required is True
    assert "1.6038D-2(a)(7)(i)" in r.work
    assert "not required to file an annual return" in r.work
    assert "the FBAR is unaffected" in r.work


@pytest.mark.parametrize("year", SHIPPED_YEARS)
def test_p012_the_filing_status_claim_is_not_hung_on_a_repurposed_quote(year: int):
    """P-012, defect 3 (found by opening the page, not by re-reading the YAML).

    The FBAR's $10,000 really does not vary by filing status — but the note used
    to prove it by quoting irs.gov's "Income tax filing status, such as
    married-filing-jointly and married-filing-separately, has no effect", and
    READ IN PLACE on the IRS FBAR page that sentence is about qualification for
    the JOINTLY-OWNED-ACCOUNTS spousal exception: it follows "...your spouse
    reports the jointly owned accounts on a timely-filed signed FBAR". A true
    claim resting on a pinpoint that does not support it is exactly the kind of
    citation this repo rejects from contributors, so the note now argues from the
    ABSENCE of any status variant in 31 CFR 1010.306(c) / 1010.350, and keeps the
    quote only for what it does say.
    """
    pack = load_knowledge("federal", year, base_dir=KNOWLEDGE_DIR)
    note = pack.foreign_account_reporting.fbar.threshold_note
    assert "1010.306(c) states one flat figure" in note
    assert "NOT a threshold statement" in note
    assert "spousal exception" in note.lower() or "JOINTLY-OWNED-ACCOUNTS" in note
    # The claim itself must survive the correction.
    assert pack.foreign_account_reporting.fbar.threshold_varies_by_filing_status is False
    assert pack.foreign_account_reporting.fbar.aggregate_threshold == 10_000


@pytest.mark.parametrize("year", PACK_YEARS)
def test_p012_the_fbar_worksheet_carries_the_same_correction(year: int):
    """The worksheet banner made the same repurposed-quote claim and takes the
    same fix, so the two cannot drift back apart."""
    text = (REPO_ROOT / "formpacks" / "federal" / str(year) / "fincen114" / "handfill.yaml").read_text()
    assert "DO NOT cite irs.gov" in text
    assert "1010.306(c) gives one flat figure" in text


def test_p012_the_schema_validator_cites_the_regulations_silence_not_the_quote():
    """The same repurposed quote also stood as the schema validator's own
    authority. It is the message an author sees when a pack claims the FBAR
    threshold varies by status, so it is exactly where the right pinpoint
    matters — a wrong citation in an error message teaches the wrong law.
    """
    from taxfill_core.knowledge import ForeignAccountReportingParams

    raw = yaml.safe_load((KNOWLEDGE_DIR / "federal" / "2025.yaml").read_text())["foreign_account_reporting"]
    raw["fbar"]["threshold_varies_by_filing_status"] = True
    with pytest.raises(Exception) as exc:
        ForeignAccountReportingParams.model_validate(raw)
    msg = str(exc.value)
    assert "1010.306(c) states one flat figure" in msg
    assert "regulation's SILENCE" in msg
    assert "SPOUSAL" in msg and "P-012" in msg
