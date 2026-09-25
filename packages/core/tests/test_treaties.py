"""Treaty knowledge + treaty_benefit op tests (ROADMAP Phase G item G1).

Offline by design: tests load the real shipped packs (knowledge/treaties/)
from disk and build broken variants in memory. No real taxpayer data.

Golden values are transcribed from the VERIFIED research against the official
documents (all fetched live at research time; zero discrepancies on
re-derivation):

* US-China agreement + Technical Explanation:
  https://www.irs.gov/pub/irs-trty/china.pdf, chintech.pdf — Art. 20(c)
  $5,000/taxable year; Art. 19 three years IN THE AGGREGATE, prospective loss;
  Protocol 1 (1984-04-30) para. 2 saving-clause exception.
* US-India convention: https://www.irs.gov/pub/irs-trty/india.pdf — Art. 21(2)
  'same exemptions, reliefs or reductions' (deduction parity, NO dollar
  exclusion); Art. 22 two years with Pub 901 (Rev. 9-2024) p. 25 retroactive
  loss ('the exemption is lost for the entire visit').
* US-Korea convention: https://www.irs.gov/pub/irs-trty/korea.pdf — Art.
  21(1)(b)(iii) $2,000/yr, 5 taxable years, Art. 21(4) COMBINED 5-year cap;
  Art. 20 teachers 2 years, no clawback; Art. 21(2) $5,000/1yr and Art. 21(3)
  $10,000/1yr extra provisions.
* US-Canada convention: https://www.irs.gov/pub/irs-trty/canada.pdf — Art. XX
  foreign-payments-only for students (NO dollar exclusion), NO teacher
  article; Art. XV(2)(a) $10,000 all-or-nothing employment de-minimis.
* US-Mexico convention: https://www.irs.gov/pub/irs-trty/mexico.pdf — Art. 21
  foreign-source payments only, NO teacher article, NO employment dollar
  threshold (only the Art. 15(2) three-part 183-day test).
* Pub 901 (Rev. September 2024): https://www.irs.gov/pub/irs-pdf/p901.pdf
  cross-checks every number above.

Rule from docs/DEV_PLAN.md section 10: if the implementation disagrees with
any published value below, the implementation is wrong — fix it, never the
fixture.
"""

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.calc import TREATY_INCOME_CLASSES, treaty_benefit
from taxfill_core.knowledge import (
    TreatyKnowledge,
    is_official_gov_host,
    list_treaty_countries,
    load_treaty,
    normalize_treaty_country,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"

SHIPPED = ("canada", "china", "india", "korea", "mexico")


@pytest.fixture(scope="module")
def packs() -> dict[str, TreatyKnowledge]:
    return {c: load_treaty(c, base_dir=KNOWLEDGE_DIR) for c in SHIPPED}


# ---------------------------------------------------------------------------
# Loader round-trips + gov-host citations
# ---------------------------------------------------------------------------


def test_all_shipped_treaties_load_and_identify_themselves(packs):
    assert list_treaty_countries(KNOWLEDGE_DIR) == list(SHIPPED)
    for country, pack in packs.items():
        assert pack.country == country
        assert pack.treaty  # the treaty's identity (signing place/date) is present
        assert pack.disclaimer  # mandatory: what the engine does NOT check
        assert "saving-clause" in pack.disclaimer or "saving clause" in pack.disclaimer
        assert "visa" in pack.disclaimer


def test_every_citation_is_gov_hosted(packs):
    from urllib.parse import urlparse

    for country, pack in packs.items():
        citations = [pack.citation]
        if pack.student is not None:
            citations.append(pack.student.citation)
        if pack.teacher_researcher is not None:
            citations.append(pack.teacher_researcher.citation)
        if pack.employment_de_minimis is not None:
            citations.append(pack.employment_de_minimis.citation)
        citations.extend(p.citation for p in pack.extra_provisions)
        assert citations, country
        for c in citations:
            host = urlparse(c.url).hostname or ""
            assert is_official_gov_host(host), f"{country}: non-gov citation host {host!r}"
            assert c.source  # source names the treaty/article/Pub 901 pinpoint


def test_default_base_dir_resolves_source_checkout():
    assert load_treaty("china").country == "china"


def test_country_normalization_and_aliases():
    assert normalize_treaty_country("  South Korea ") == "korea"
    assert normalize_treaty_country("Republic of Korea") == "korea"
    assert normalize_treaty_country("PRC") == "china"
    assert normalize_treaty_country("People's Republic of China") == "china"
    assert load_treaty("South Korea", base_dir=KNOWLEDGE_DIR).country == "korea"
    assert load_treaty("CHINA", base_dir=KNOWLEDGE_DIR).country == "china"


def test_unknown_country_error_lists_shipped_countries():
    with pytest.raises(FileNotFoundError) as exc:
        load_treaty("germany", base_dir=KNOWLEDGE_DIR)
    msg = str(exc.value)
    for country in SHIPPED:
        assert country in msg
    assert "get_sources" in msg  # the freshness path, never invent a treaty amount


# ---------------------------------------------------------------------------
# Per-country goldens (values == the researched/verified numbers)
# ---------------------------------------------------------------------------


def test_china_goldens(packs):
    china = packs["china"]
    s = china.student
    assert s.article == "Art. 20 (Students and Trainees)"
    assert s.compensation_limit == 5000  # Art. 20(c), treaty-fixed
    assert s.compensation_limit_period == "per_taxable_year"
    assert s.compensation_limit_ref == "Art. 20(c)"
    assert s.payments_from_abroad_exempt is True  # Art. 20(a)
    assert s.scholarship_exempt is True  # Art. 20(b)
    assert "reasonably necessary" in s.time_limit_text  # no fixed year count
    assert s.saving_clause_exception is True
    assert "Protocol 1" in s.saving_clause_exception_text  # NOT a '1987 protocol'
    t = china.teacher_researcher
    assert t.article == "Art. 19 (Teachers, Professors and Researchers)"
    assert t.years == 3
    assert "aggregate" in t.years_basis  # cumulative, not consecutive
    assert t.retroactive_loss is False  # prospective only per the TE
    assert china.employment_de_minimis is None


def test_india_goldens(packs):
    india = packs["india"]
    s = india.student
    assert s.compensation_limit is None  # NO dollar exclusion for wages
    assert s.scholarship_exempt is False
    assert s.payments_from_abroad_exempt is True  # Art. 21(1)
    assert "same exemptions, reliefs or reductions" in s.special_rule  # Art. 21(2) verbatim
    assert "standard deduction" in s.special_rule
    assert "NOT a dollar exclusion" in s.special_rule
    t = india.teacher_researcher
    assert t.years == 2
    assert t.retroactive_loss is True
    assert "lost for the entire visit" in t.retroactive_loss_text  # Pub 901 (9-2024) p. 25
    assert t.saving_clause_exception is True  # Art. 1(4)(b)


def test_korea_goldens(packs):
    korea = packs["korea"]
    s = korea.student
    assert s.compensation_limit == 2000  # Art. 21(1)(b)(iii)
    assert s.compensation_limit_ref == "Art. 21(1)(b)(iii)"
    assert s.scholarship_exempt is True and s.payments_from_abroad_exempt is True
    assert "5 taxable years" in s.time_limit_text
    assert "COMBINED" in s.time_limit_text  # Art. 21(4): teacher + student <= 5 years total
    t = korea.teacher_researcher
    assert t.article == "Art. 20 (Teachers)"
    assert t.years == 2
    assert t.retroactive_loss is False
    assert "INVITED" in t.conditions
    extras = {p.name: p.text for p in korea.extra_provisions}
    assert set(extras) == {"trainee_employee", "government_program"}
    assert "$5,000" in extras["trainee_employee"] and "Art. 21(2)" in extras["trainee_employee"]
    assert "$10,000" in extras["government_program"] and "Art. 21(3)" in extras["government_program"]


def test_canada_shape(packs):
    canada = packs["canada"]
    s = canada.student
    assert s.article == "Art. XX (Students)"
    assert s.compensation_limit is None  # NO China/Korea-style exclusion
    assert s.payments_from_abroad_exempt is True
    assert "FULL-TIME" in s.payments_from_abroad_text
    assert s.scholarship_exempt is False
    assert canada.teacher_researcher is None  # verified: NO teacher article exists
    dm = canada.employment_de_minimis
    assert dm.article.startswith("Art. XV")
    assert dm.amount == 10000  # Art. XV(2)(a), per calendar year
    assert "183" in dm.alternative_test  # Art. XV(2)(b) + the Fifth-Protocol current rule
    assert "Fifth-Protocol" in dm.alternative_test  # the pre-2007-PDF caveat is preserved


def test_mexico_shape(packs):
    mexico = packs["mexico"]
    s = mexico.student
    assert s.compensation_limit is None
    assert s.payments_from_abroad_exempt is True
    assert "remitted from" in s.payments_from_abroad_text  # arise from / remitted from outside
    assert "SOLELY" in s.payments_from_abroad_text
    assert mexico.teacher_researcher is None  # verified: NO teacher article exists
    dm = mexico.employment_de_minimis
    assert dm.amount is None  # VERIFIED: no dollar threshold — the $16,000 rumor is false
    assert "$16,000" in dm.amount_text and "NOWHERE" in dm.amount_text
    assert "$3,000" in dm.amount_text  # the only dollar amount in the whole convention (Art. 18)
    assert "183" in dm.alternative_test and "ALL THREE" in dm.alternative_test


# ---------------------------------------------------------------------------
# Schema validation (broken variants built in memory)
# ---------------------------------------------------------------------------


def _raw(country: str) -> dict:
    return yaml.safe_load((KNOWLEDGE_DIR / "treaties" / f"{country}.yaml").read_text(encoding="utf-8"))


def test_non_gov_citation_url_is_rejected():
    raw = _raw("china")
    raw["student"]["citation"]["url"] = "https://www.taxblog.example.com/china-treaty"
    with pytest.raises(ValidationError, match="official US government host"):
        TreatyKnowledge.model_validate(raw)


def test_compensation_limit_requires_period_and_pinpoint():
    raw = _raw("china")
    del raw["student"]["compensation_limit_ref"]
    with pytest.raises(ValidationError, match="compensation_limit_ref"):
        TreatyKnowledge.model_validate(raw)


def test_retroactive_loss_requires_its_authority_text():
    raw = _raw("india")
    del raw["teacher_researcher"]["retroactive_loss_text"]
    with pytest.raises(ValidationError, match="retroactive_loss_text"):
        TreatyKnowledge.model_validate(raw)


def test_disclaimer_and_top_level_citation_are_mandatory():
    raw = _raw("mexico")
    del raw["disclaimer"]
    with pytest.raises(ValidationError, match="disclaimer"):
        TreatyKnowledge.model_validate(raw)
    raw = _raw("mexico")
    del raw["citation"]
    with pytest.raises(ValidationError, match="citation"):
        TreatyKnowledge.model_validate(raw)


def test_country_filename_mismatch_is_rejected(tmp_path):
    treaties = tmp_path / "treaties"
    treaties.mkdir()
    raw = _raw("china")
    (treaties / "korea.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="declares country 'china'"):
        load_treaty("korea", base_dir=tmp_path)


# ---------------------------------------------------------------------------
# treaty_benefit op — student wages
# ---------------------------------------------------------------------------


def test_income_classes_constant():
    assert TREATY_INCOME_CLASSES == ("student_wages", "scholarship", "payments_from_abroad", "teacher_wages", "other_income")


def test_china_student_wages_over_limit_split():
    r = treaty_benefit("china", "student_wages", 8000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.exempt_amount == 5000 and r.taxable_remainder == 3000
    assert r.article == "Art. 20 (Students and Trainees)"
    assert any("Art. 20(c)" in lim and "$5,000" in lim for lim in r.limits_applied)
    assert "VALIDATES" in r.work and "AGENT" in r.work  # eligibility judgment stays with the agent
    assert r.citation.url == "https://www.irs.gov/pub/irs-trty/china.pdf"


def test_china_student_wages_under_limit_fully_exempt():
    r = treaty_benefit("china", "student_wages", 4200, knowledge_dir=KNOWLEDGE_DIR)
    assert r.exempt_amount == 4200 and r.taxable_remainder == 0


def test_korea_student_wages_2000_limit():
    r = treaty_benefit("korea", "student_wages", 8000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.exempt_amount == 2000 and r.taxable_remainder == 6000
    assert any("Art. 21(1)(b)(iii)" in lim for lim in r.limits_applied)
    # The Art. 21(4) combined 5-year cap rides along in the work.
    assert "COMBINED" in r.work


def test_india_student_wages_zero_with_21_2_parity_explanation():
    r = treaty_benefit("india", "student_wages", 5000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.exempt_amount == 0 and r.taxable_remainder == 5000
    assert "Art. 21(2)" in r.work and "standard deduction" in r.work
    # The engine models the parity rule via itemized_deductions, not an exclusion.
    assert "itemized_deductions" in r.work
    assert "do NOT enter the wages as treaty_exempt_income" in r.work


def test_canada_student_wages_de_minimis_is_all_or_nothing():
    under = treaty_benefit("canada", "student_wages", 9000, knowledge_dir=KNOWLEDGE_DIR)
    assert under.exempt_amount == 9000 and under.taxable_remainder == 0
    assert under.article.startswith("Art. XV")
    assert "all-or-nothing" in under.work.lower()
    assert "TOTAL US employment remuneration" in under.work  # threshold condition spelled out
    over = treaty_benefit("canada", "student_wages", 12000, knowledge_dir=KNOWLEDGE_DIR)
    assert over.exempt_amount == 0 and over.taxable_remainder == 12000
    assert "183" in over.work  # the alternative test is a facts question left to the agent
    assert "cliff" in over.work


def test_mexico_student_wages_no_benefit_prescriptive():
    r = treaty_benefit("mexico", "student_wages", 5000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.exempt_amount == 0 and r.taxable_remainder == 5000
    assert "NO dollar" in r.work and "183" in r.work
    assert "$16,000" in r.work  # the rumored threshold is called out as nonexistent


# ---------------------------------------------------------------------------
# treaty_benefit op — scholarship / payments from abroad
# ---------------------------------------------------------------------------


def test_scholarship_china_korea_fully_exempt():
    for country, art in (("china", "Art. 20"), ("korea", "Art. 21(1)")):
        r = treaty_benefit(country, "scholarship", 10000, knowledge_dir=KNOWLEDGE_DIR)
        assert r.exempt_amount == 10000 and r.taxable_remainder == 0, country
        assert r.article.startswith(art)


def test_scholarship_india_zero_with_parity_note():
    r = treaty_benefit("india", "scholarship", 6000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.exempt_amount == 0
    assert "Art. 21(2)" in r.work  # parity rule, not an exclusion
    assert "payments_from_abroad" in r.work  # the foreign-source path is pointed to


def test_scholarship_canada_mexico_zero_points_to_abroad_class():
    for country in ("canada", "mexico"):
        r = treaty_benefit(country, "scholarship", 6000, knowledge_dir=KNOWLEDGE_DIR)
        assert r.exempt_amount == 0, country
        assert "payments_from_abroad" in r.work


def test_payments_from_abroad_exempt_for_all_five_with_conditions():
    for country, condition in (
        ("china", "Art. 20(a)"),
        ("india", "Art. 21(1)"),
        ("korea", "Art. 21(1)(b)(i)"),
        ("canada", "FULL-TIME"),
        ("mexico", "SOLELY"),
    ):
        r = treaty_benefit(country, "payments_from_abroad", 12000, knowledge_dir=KNOWLEDGE_DIR)
        assert r.exempt_amount == 12000 and r.taxable_remainder == 0, country
        assert condition in r.work, country


# ---------------------------------------------------------------------------
# treaty_benefit op — teacher wages (year windows + India retroactive loss)
# ---------------------------------------------------------------------------


def test_china_teacher_three_year_aggregate_window():
    within = treaty_benefit("china", "teacher_wages", 60000, years_in_status=3, knowledge_dir=KNOWLEDGE_DIR)
    assert within.exempt_amount == 60000 and within.taxable_remainder == 0
    assert "aggregate" in within.work
    beyond = treaty_benefit("china", "teacher_wages", 60000, years_in_status=4, knowledge_dir=KNOWLEDGE_DIR)
    assert beyond.exempt_amount == 0 and beyond.taxable_remainder == 60000
    assert "PROSPECTIVE" in beyond.work  # earlier years keep their exemption
    assert "RETROACTIVE LOSS:" not in beyond.work


def test_korea_teacher_two_years_from_arrival():
    within = treaty_benefit("korea", "teacher_wages", 50000, years_in_status=2, knowledge_dir=KNOWLEDGE_DIR)
    assert within.exempt_amount == 50000
    assert "INVITED" in within.work  # the invitation condition rides along
    beyond = treaty_benefit("korea", "teacher_wages", 50000, years_in_status=3, knowledge_dir=KNOWLEDGE_DIR)
    assert beyond.exempt_amount == 0
    assert "PROSPECTIVE" in beyond.work


def test_india_teacher_retroactive_loss_is_loud():
    beyond = treaty_benefit("india", "teacher_wages", 70000, years_in_status=3, knowledge_dir=KNOWLEDGE_DIR)
    assert beyond.exempt_amount == 0 and beyond.taxable_remainder == 70000
    assert "RETROACTIVE LOSS" in beyond.work
    assert "lost for the entire visit" in beyond.work  # Pub 901 p. 25 verbatim
    assert "AMENDED" in beyond.work  # earlier years' returns must be amended
    assert any("RETROACTIVE" in lim for lim in beyond.limits_applied)


def test_india_teacher_within_window_warns_about_the_clawback_risk():
    within = treaty_benefit("india", "teacher_wages", 70000, years_in_status=2, knowledge_dir=KNOWLEDGE_DIR)
    assert within.exempt_amount == 70000
    assert "RETROACTIVE LOSS RISK" in within.work  # pre-emptive warning while still exempt


def test_canada_mexico_teacher_no_such_benefit():
    for country in ("canada", "mexico"):
        r = treaty_benefit(country, "teacher_wages", 50000, years_in_status=1, knowledge_dir=KNOWLEDGE_DIR)
        assert r.exempt_amount == 0 and r.article is None, country
        assert "NO teacher/professor article" in r.work
        assert "Do not put teacher wages on Schedule OI" in r.work


def test_teacher_wages_requires_years_in_status():
    with pytest.raises(ValueError, match="years_in_status"):
        treaty_benefit("china", "teacher_wages", 50000, knowledge_dir=KNOWLEDGE_DIR)
    with pytest.raises(ValueError, match="years_in_status must be >= 1"):
        treaty_benefit("china", "teacher_wages", 50000, years_in_status=0, knowledge_dir=KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# treaty_benefit op — input validation + envelope invariants
# ---------------------------------------------------------------------------


def test_unknown_income_class_lists_the_four():
    with pytest.raises(ValueError) as exc:
        treaty_benefit("china", "wages", 5000, knowledge_dir=KNOWLEDGE_DIR)
    msg = str(exc.value)
    for cls in TREATY_INCOME_CLASSES:
        assert cls in msg


def test_unknown_country_propagates_the_prescriptive_error():
    with pytest.raises(FileNotFoundError, match="china"):
        treaty_benefit("germany", "student_wages", 5000, knowledge_dir=KNOWLEDGE_DIR)


def test_negative_amount_rejected():
    with pytest.raises(ValueError, match="amount must be >= 0"):
        treaty_benefit("china", "student_wages", -1, knowledge_dir=KNOWLEDGE_DIR)


def test_split_invariant_and_inputs_echo():
    periods = [{"status": "F-1", "start": "2018-08-24"}]
    r = treaty_benefit(
        "china", "student_wages", 7250.49, visa_periods=periods, year=2022, knowledge_dir=KNOWLEDGE_DIR
    )
    assert r.exempt_amount + r.taxable_remainder == 7250  # irs_round(7250.49)
    assert r.inputs["visa_periods"] == periods  # echoed for the per-period analysis (P-004)
    assert r.inputs["year"] == 2022
    assert "P-004" in r.work  # visa periods are echoed, not evaluated
    assert r.country == "china" and r.income_class == "student_wages"


def test_result_serializes_for_the_mcp_layer():
    r = treaty_benefit("korea", "student_wages", 3000, knowledge_dir=KNOWLEDGE_DIR)
    dumped = r.model_dump(mode="json")
    assert dumped["exempt_amount"] == 2000 and dumped["taxable_remainder"] == 1000
    assert dumped["citation"]["url"].startswith("https://www.irs.gov/")


# ── other_income (H9, P-005): the bank-bonus / 1099-MISC box 3 corner ──────────


def test_other_income_gives_no_shelter_in_any_shipped_treaty():
    # All five Other Income articles were transcribed verbatim from the irs.gov
    # treaty PDFs: China Art. 21(3), India Art. 23(3) and Canada Art. XXII(1)
    # carve US-arising items back to source-state taxation, Mexico Art. 23 is
    # source-state-only in form — US-arising other income stays US-taxable.
    from taxfill_core.calc import treaty_benefit

    for country, article_fragment in (
        ("china", "Art. 21"), ("india", "Art. 23"), ("canada", "Art. XXII"), ("mexico", "Art. 23"),
    ):
        r = treaty_benefit(country, "other_income", 695)
        assert r.exempt_amount == 0 and r.taxable_remainder == 695, country
        assert r.article and article_fragment in r.article
        assert "Schedule NEC" in r.work and "30%" in r.work
        assert "irs-trty" in r.citation.url


def test_korea_has_verifiably_no_other_income_article():
    # The 1976 convention's Table of Articles (1-32) contains no Other Income
    # article — article: null is VERIFIED ABSENCE, and Art. 4(1)'s general
    # source rule leaves US-arising other income US-taxable anyway.
    from taxfill_core.calc import treaty_benefit

    r = treaty_benefit("korea", "other_income", 100)
    assert r.article is None
    assert "NO Other Income article" in r.work and "Art. 4(1)" in r.work
    assert r.exempt_amount == 0


def test_other_income_is_a_rate_question_never_a_dollar_split():
    from taxfill_core.calc import treaty_benefit

    r = treaty_benefit("china", "other_income", 50_000)
    assert r.exempt_amount == 0  # never a split, whatever the amount
    assert any("ARTICLE question" in lim for lim in r.limits_applied)


# ── the DISCLOSURE half: treaty_benefit must point at Form 8833 (Phase I4) ────
#
# The asymmetry this closes: the op priced a treaty position since G1 while the
# repo had no pack for the form IRC 6114 / Treas. Reg. 301.6114-1 requires, and
# the work string said nothing about disclosure at all. These tests pin the
# pointer AND its most important nuance — that the reg WAIVES the disclosure for
# exactly this op's usual population, so the note must not read as an
# unconditional duty. Sources: IRC 6114 and 6712 (uscode.house.gov), 26 CFR
# 301.6114-1 and 301.7701(b)-7 (ecfr.gov), Form 8833 (Rev. 12-2022) and its
# instructions pp. 3-4 (irs.gov/pub/irs-pdf/f8833.pdf).


@pytest.mark.parametrize(
    ("country", "income_class", "kwargs"),
    [
        ("china", "student_wages", {}),
        ("china", "scholarship", {}),
        ("china", "payments_from_abroad", {}),
        ("china", "teacher_wages", {"years_in_status": 1}),
        ("china", "other_income", {}),
        ("india", "student_wages", {}),
        ("india", "teacher_wages", {"years_in_status": 5}),
        ("korea", "student_wages", {}),
        ("canada", "student_wages", {}),
        ("canada", "teacher_wages", {"years_in_status": 1}),
        ("mexico", "student_wages", {}),
        ("mexico", "other_income", {}),
    ],
)
def test_every_treaty_benefit_branch_names_form_8833_and_the_law(country, income_class, kwargs):
    """EVERY branch — not just the ones that exempt money — carries the pointer."""
    from taxfill_core.calc import treaty_benefit

    work = treaty_benefit(country, income_class, 7_000, knowledge_dir=KNOWLEDGE_DIR, **kwargs).work
    assert "Form 8833" in work
    assert "IRC 6114(a)" in work  # the requirement
    assert "IRC 6712(a)" in work and "$1,000" in work and "$10,000" in work  # the penalty
    assert "301.6114-1(d)(1)" in work  # what makes 8833 the vehicle
    assert "formpacks/federal/{2023,2024,2025}/f8833" in work  # the packs that now exist


def test_disclosure_note_leads_with_the_waiver_that_covers_students_and_teachers():
    # 301.6114-1(c)(1)(iv) waives reporting for a position that a treaty reduces
    # or modifies the taxation of income from dependent personal services or of
    # "income derived by artistes, athletes, students, trainees or teachers" —
    # printed as a bullet in the Form 8833 instructions (Rev. 12-2022) p. 3 under
    # "Exceptions from reporting". Telling a student they MUST file Form 8833 for
    # an Art. 20(c) claim is wrong law, so the waiver has to travel with the
    # requirement.
    from taxfill_core.calc import treaty_benefit

    work = treaty_benefit("china", "student_wages", 5_000, knowledge_dir=KNOWLEDGE_DIR).work
    assert "301.6114-1(c)(1)(iv)" in work
    assert "students, trainees or teachers" in work
    # (c)(2): waived for an individual at or under $10,000 of reportable items.
    assert "301.6114-1(c)(2)" in work and "$10,000 or less" in work
    assert "waived twice over" in work


def test_disclosure_note_names_the_two_positions_that_are_NOT_waived():
    # 301.6114-1(b)(8) (residency determined under the treaty) is specifically
    # required, with a $100,000 rather than $10,000 (c)(2) threshold; and
    # 301.7701(b)-7(b)/(c)(1)(i) require a "fully completed Form 8833" from a
    # dual-resident taxpayer with NO 301.6114-1(c) waiver reaching it.
    from taxfill_core.calc import treaty_benefit

    work = treaty_benefit("china", "teacher_wages", 40_000, years_in_status=1, knowledge_dir=KNOWLEDGE_DIR).work
    assert "301.6114-1(b)(8)" in work and "$100,000" in work
    assert "301.7701(b)-7(b) and (c)(1)(i)" in work
    assert "DUAL-RESIDENT TAXPAYER" in work


def test_other_income_says_there_is_no_position_to_disclose_before_the_duty():
    # No shipped treaty shelters US-arising other income, so that branch takes no
    # treaty-based return position at all and section 6114 is not triggered by it.
    from taxfill_core.calc import treaty_benefit

    work = treaty_benefit("china", "other_income", 695, knowledge_dir=KNOWLEDGE_DIR).work
    assert "NO treaty-based return position is taken on it" in work
    assert work.index("NO treaty-based return position is taken on it") < work.index("Form 8833")


def test_zero_exempt_is_not_treated_as_no_position_india_is_the_counterexample():
    # india/student_wages exempts $0 and STILL rests on a treaty position: Art.
    # 21(2)'s deduction parity overrides the Code's no-standard-deduction rule for
    # a nonresident. Keying the "nothing to disclose" sentence on exempt == 0
    # would therefore have told an India filer the opposite of the truth.
    from taxfill_core.calc import treaty_benefit

    r = treaty_benefit("india", "student_wages", 12_000, knowledge_dir=KNOWLEDGE_DIR)
    assert r.exempt_amount == 0
    assert "NO treaty-based return position is taken on it" not in r.work
    assert "Form 8833" in r.work


def test_the_disclosure_pointer_changed_no_computed_number():
    """Every treaty golden in this module still holds; the note is prose only."""
    from taxfill_core.calc import treaty_benefit

    cases = [
        # (country, income_class, amount, kwargs, exempt)
        ("china", "student_wages", 7_250, {}, 5_000),
        ("china", "student_wages", 4_000, {}, 4_000),
        ("china", "scholarship", 18_000, {}, 18_000),
        ("china", "payments_from_abroad", 9_000, {}, 9_000),
        ("china", "teacher_wages", 60_000, {"years_in_status": 3}, 60_000),
        ("china", "teacher_wages", 60_000, {"years_in_status": 4}, 0),
        ("china", "other_income", 695, {}, 0),
        ("india", "student_wages", 30_000, {}, 0),
        ("india", "teacher_wages", 50_000, {"years_in_status": 2}, 50_000),
        ("india", "teacher_wages", 50_000, {"years_in_status": 3}, 0),
        ("korea", "student_wages", 3_000, {}, 2_000),
        ("korea", "scholarship", 5_500, {}, 5_500),
        ("canada", "student_wages", 10_000, {}, 10_000),
        ("canada", "student_wages", 10_001, {}, 0),
        ("mexico", "student_wages", 8_000, {}, 0),
        ("mexico", "payments_from_abroad", 8_000, {}, 8_000),
    ]
    for country, income_class, amount, kwargs, exempt in cases:
        r = treaty_benefit(country, income_class, amount, knowledge_dir=KNOWLEDGE_DIR, **kwargs)
        assert r.exempt_amount == exempt, (country, income_class, amount, r.exempt_amount)
        assert r.taxable_remainder == amount - exempt, (country, income_class, amount)


# ---------------------------------------------------------------------------
# P-016 (Phase J JF1a): treaty_benefit's resident_alien decides WHERE a nonzero
# exempt amount is reported, never how much. A nonresident: Schedule OI item L and
# the Form 1040-NR treaty-exempt line. A resident alien (a saving-clause
# exception): in parentheses on Schedule 1's other-income line (Pub 519 ch. 9).
# Unknown: both, conditionally. Every line comes from the year's form_lines block.
# ---------------------------------------------------------------------------


def _reporting(work: str) -> str:
    start = work.index(" REPORTING (")
    return work[start:work.index("This op VALIDATES", start)]


@pytest.mark.parametrize(
    "year, sched1, nr",
    [(2020, "line 8 (", "line 1c"), (2025, "line 8z (", "line 1k"), (2019, "line 8 (", "line 22")],
)
def test_p016_the_reporting_line_follows_residency_and_the_years_face(year, sched1, nr):
    resident = _reporting(
        treaty_benefit("china", "scholarship", 6_000, year=year, resident_alien=True, knowledge_dir=KNOWLEDGE_DIR).work
    )
    assert f"Schedule 1 {sched1}Schedule 1 (Form 1040), other income)" in resident and "IN PARENTHESES" in resident
    assert "Exempt income" in resident and "Pub 519 ch. 9" in resident
    assert "1040-NR line" not in resident and "item L" not in resident
    nonresident = _reporting(
        treaty_benefit("china", "scholarship", 6_000, year=year, resident_alien=False, knowledge_dir=KNOWLEDGE_DIR).work
    )
    assert f"Form 1040-NR {nr}" in nonresident and "Schedule OI (Form 1040-NR) item L" in nonresident
    assert "Schedule 1 (Form 1040)" not in nonresident
    unknown = _reporting(treaty_benefit("china", "scholarship", 6_000, year=year, knowledge_dir=KNOWLEDGE_DIR).work)
    assert "pass resident_alien" in unknown
    assert f"Form 1040-NR {nr}" in unknown and f"Schedule 1 {sched1}" in unknown


def test_p016_a_2026_resident_line_carries_the_draft_suffix():
    work = treaty_benefit(
        "korea", "student_wages", 2_000, year=2026, resident_alien=True, knowledge_dir=KNOWLEDGE_DIR
    ).work
    assert "line 8z (2026 DRAFT form — re-verify at final)" in work


def test_p016_nothing_exempt_means_nothing_to_report_and_no_number_moves():
    for kwargs in ({"resident_alien": True}, {"resident_alien": False}, {}):
        zero = treaty_benefit("india", "student_wages", 5_000, knowledge_dir=KNOWLEDGE_DIR, **kwargs)
        assert zero.exempt_amount == 0 and "REPORTING" not in zero.work
        other = treaty_benefit("china", "other_income", 695, knowledge_dir=KNOWLEDGE_DIR, **kwargs)
        assert other.exempt_amount == 0 and "REPORTING" not in other.work
        split = treaty_benefit("china", "student_wages", 8_000, knowledge_dir=KNOWLEDGE_DIR, **kwargs)
        assert (split.exempt_amount, split.taxable_remainder) == (5_000, 3_000)
    r = treaty_benefit("china", "student_wages", 8_000, resident_alien=True, knowledge_dir=KNOWLEDGE_DIR)
    assert r.inputs["resident_alien"] is True


def test_p016_resident_alien_must_be_a_bool():
    with pytest.raises(ValueError, match="resident_alien must be true, false or omitted"):
        treaty_benefit("china", "student_wages", 8_000, resident_alien="yes", knowledge_dir=KNOWLEDGE_DIR)


def test_p016_every_treaty_use_site_says_the_destination_turns_on_residency():
    from taxfill_core import calc as calc_module
    from taxfill_core.estimate import IncomeSnapshot
    from taxfill_mcp.server import calc as calc_tool
    from taxfill_mcp.server import estimate_refund as estimate_tool

    skill = (REPO_ROOT / "skills" / "claude" / "SKILL.md").read_text()
    for raw in (
        calc_module.__doc__, treaty_benefit.__doc__, calc_tool.__doc__, estimate_tool.__doc__, skill,
        IncomeSnapshot.model_fields["treaty_exempt_income"].description,
    ):
        text = " ".join(raw.split())  # docstrings wrap mid-phrase
        assert "Schedule 1's other-income line" in text, raw[:80]
        assert "Schedule OI" in text
        assert "Form 1040-NR line 1k" not in text  # no typed, year-blind destination (P-015)
    for text in (treaty_benefit.__doc__, calc_tool.__doc__, skill):
        assert "resident_alien" in text


def test_p016_a_resident_is_told_when_the_applied_block_has_no_saving_clause_exception():
    # Canada Art. XV's $10,000 de-minimis block records NO saving-clause exception
    # (the irs.gov text's Art. XXIX(3) lists Art. XX, not Art. XV), so the resident
    # sentence must not point at an exception "quoted above" that the work never
    # quotes: it says a resident generally cannot claim it (Pub 519 ch. 9) and gives
    # the Form 1040 line only as conditional. The number itself does not move.
    r = treaty_benefit("canada", "student_wages", 5_000, year=2025, resident_alien=True, knowledge_dir=KNOWLEDGE_DIR)
    assert (r.exempt_amount, r.taxable_remainder) == (5_000, 0)
    reporting = _reporting(r.work)
    assert "(quoted above)" not in reporting and "Saving-clause exception applies" not in r.work
    assert "records NO saving-clause exception for Art. XV" in reporting
    assert "generally cannot claim this benefit" in reporting and "generally do not qualify" in reporting
    assert "only if a saving-clause exception you have confirmed" in reporting
    unknown = _reporting(
        treaty_benefit("canada", "student_wages", 5_000, year=2025, knowledge_dir=KNOWLEDGE_DIR).work
    )
    assert "records NO saving-clause exception for Art. XV" in unknown and "claiming a saving-clause" not in unknown
    # A block that does record an exception keeps the pointer, and its text IS above it.
    china = treaty_benefit("china", "scholarship", 6_000, year=2025, resident_alien=True, knowledge_dir=KNOWLEDGE_DIR)
    assert "Saving-clause exception applies" in china.work
    assert "the pack's saving-clause entry above" in _reporting(china.work)


def test_p016_a_dual_status_year_is_one_return_plus_a_statement():
    # Pub 519 (2025) ch. 6: resident at year end -> Form 1040 marked "Dual Status
    # Return" with "a statement to your return to show the income for the part of
    # the year you are a nonresident"; nonresident at year end -> Form 1040-NR. Not
    # one return per period.
    unknown = _reporting(treaty_benefit("china", "scholarship", 6_000, year=2025, knowledge_dir=KNOWLEDGE_DIR).work)
    assert "ONE return plus a statement (Pub 519 ch. 6)" in unknown
    assert "Dual Status Return" in unknown and "each period on its own return" not in unknown


def test_p016_the_parenthetical_entry_is_paired_with_the_information_return_inclusion():
    # Pub 519 ch. 9: "if the income has been reported as taxable income on a Form W-2,
    # Form 1042-S, Form 1099, or other information return, you should report it on the
    # appropriate line" and then enter the amount claimed in parentheses — the two
    # entries go together, so income never included is not subtracted as well.
    reporting = _reporting(
        treaty_benefit("china", "scholarship", 6_000, year=2025, resident_alien=True, knowledge_dir=KNOWLEDGE_DIR).work
    )
    assert "when a W-2, 1042-S, 1099 or other information return reported the income as taxable" in reporting
    assert "reported on its usual line AND the $6,000 claimed is entered IN PARENTHESES" in reporting
    assert "In certain cases, you don't need to report the income" in reporting
    assert "not also entered in parentheses, which would exclude it twice" in reporting


@pytest.mark.parametrize("year", [2018, 2027])
def test_p016_a_year_without_form_lines_keeps_the_split_and_names_the_line_in_words(year):
    # Treaty limits are treaty-fixed, so the op answers for any year; only the line
    # number is unknown there, and the work says so instead of raising or guessing.
    for kwargs in ({"resident_alien": True}, {"resident_alien": False}, {}):
        r = treaty_benefit("china", "scholarship", 6_000, year=year, knowledge_dir=KNOWLEDGE_DIR, **kwargs)
        assert r.exempt_amount == 6_000
        reporting = _reporting(r.work)
        assert f"no form_lines are recorded for {year}" in reporting
        assert not re.search(r"line \d", reporting)
    assert "Schedule 1's other-income line" in _reporting(
        treaty_benefit("china", "scholarship", 6_000, year=year, resident_alien=True, knowledge_dir=KNOWLEDGE_DIR).work
    )
    assert "the Form 1040-NR treaty-exempt line" in _reporting(
        treaty_benefit("china", "scholarship", 6_000, year=year, resident_alien=False, knowledge_dir=KNOWLEDGE_DIR).work
    )
