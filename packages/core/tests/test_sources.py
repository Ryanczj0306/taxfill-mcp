"""get_sources tests (dev plan section 7 freshness protocol). Reads the real registry."""

import pytest
from pydantic import ValidationError

from taxfill_core.sources import Source, SourcesResult, get_sources


def test_source_accepts_gov_https_url():
    src = Source(url="https://www.irs.gov/publications/p17", answers="x", cadence="annual")
    assert src.url == "https://www.irs.gov/publications/p17"


def test_source_rejects_non_gov_https_url():
    # A well-formed https url on a non-.gov host must be rejected on the HOST check.
    with pytest.raises(ValidationError, match=r"\.gov"):
        Source(url="https://blog.example.com/post", answers="x", cadence="annual")


def test_source_rejects_url_without_scheme():
    # A url lacking an http(s) scheme fails on the SCHEME check (names https://).
    with pytest.raises(ValidationError, match="https://"):
        Source(url="irs.gov/publications/p17", answers="x", cadence="annual")


def test_exact_topic_resolves_to_its_source():
    res = get_sources("filing_basics", 2023)
    assert res.matched is True
    assert any("p17" in s.url for s in res.sources)
    assert all(s.url.startswith("https://") for s in res.sources)


def test_natural_phrase_matches_topic_by_keywords():
    # "mortgage interest" should find itemized_mortgage_interest (Pub 936).
    res = get_sources("mortgage interest", 2023)
    assert res.matched is True
    assert any("p936" in s.url for s in res.sources)


def test_treaties_topic_returns_pub519_and_treasury():
    res = get_sources("nonresident_and_treaties", 2022)
    urls = " ".join(s.url for s in res.sources)
    assert "p519" in urls and "treasury.gov" in urls


def test_change_channels_always_returned():
    res = get_sources("education", 2024)
    assert res.matched is True
    urls = " ".join(s.url for s in res.change_channels)
    assert "newsroom" in urls and "irs-prior" in urls


def test_credit_queries_resolve_to_the_right_credit_not_eitc():
    # Regression: "credit" is a generic family word, so a shared "credit" token
    # must NOT promote the EITC entry for energy or CTC queries (the old bug).
    def topics(query, year=2023):
        return {s.topic for s in get_sources(query, year).sources}

    assert topics("energy credit") == {"credits_energy"}
    assert topics("child tax credit") == {"credits_ctc"}
    # EITC phrasing still resolves to its own block, not energy/CTC.
    for q in ("EITC", "earned income tax credit"):
        eitc = topics(q)
        assert "credits_eitc" in eitc, q
        assert "credits_energy" not in eitc and "credits_ctc" not in eitc, q


def test_feie_query_resolves_to_form_2555_and_pub54_not_eitc_or_dependent_care():
    # Regression: 'foreign earned income exclusion' used to return matched=True
    # with Pub 503 (dependent care) and Pub 596 (EITC) — promoted by nothing
    # but the generic bigram 'earned income'. It must resolve to the FEIE block.
    res = get_sources("foreign earned income exclusion", 2023)
    assert res.matched is True
    assert {s.topic for s in res.sources} == {"foreign_earned_income"}
    urls = " ".join(s.url for s in res.sources)
    assert "about-form-2555" in urls
    assert "about-publication-54" in urls
    # the old wrong authorities are absent
    assert "p503" not in urls and "p596" not in urls


def test_feie_keyword_variants_resolve_to_the_feie_block():
    for q in ("FEIE", "Form 2555", "foreign earned income", "physical presence test", "bona fide residence"):
        res = get_sources(q, 2023)
        assert res.matched is True, q
        assert {s.topic for s in res.sources} == {"foreign_earned_income"}, q


def test_generic_bigram_overlap_cannot_promote_an_unrelated_topic():
    # Coverage gate: a topic sharing well under half of a query's distinctive
    # tokens must be a clean miss (matched=False -> the cite-or-refuse fallback
    # fires), never a wrong matched=True citation. 'distributions' alone must
    # not promote the retirement block, nor 'foreign' the treaty/FEIE blocks.
    res = get_sources("foreign pension distributions", 2023)
    assert res.matched is False
    assert res.sources == []
    assert any("coverage rule" in n for n in res.notes)


def test_lone_generic_word_overlap_is_a_clean_miss():
    # A query that only shares a generic family word with the registry must be a
    # clean miss (matched=False) so the cite-or-refuse fallback fires — never a
    # wrong matched=True citation.
    res = get_sources("deduction", 2023)
    assert res.matched is False
    assert res.sources == []
    assert any("coverage rule" in n for n in res.notes)


def test_unknown_topic_is_not_matched_but_guides_the_caller():
    res = get_sources("cryptocurrency_staking", 2023)
    assert res.matched is False
    assert res.sources == []
    assert "filing_basics" in res.available_topics  # tells caller what IS covered
    assert res.change_channels  # still points at the freshness signals
    assert any("coverage rule" in n for n in res.notes)


def test_retrieval_hint_mentions_year_and_prior_archive():
    res = get_sources("education", 2021)
    assert "2021" in res.retrieval_hint
    assert "irs-prior" in res.retrieval_hint


def test_unsupported_state_jurisdiction_reports_no_registry_yet():
    res = get_sources("filing_basics", 2023, jurisdiction="states/ca")
    assert res.matched is False
    assert res.available_topics == []
    assert any("state" in n.lower() for n in res.notes)


def test_bad_jurisdiction_rejected():
    with pytest.raises(ValueError, match="jurisdiction"):
        get_sources("filing_basics", 2023, jurisdiction="CA")


def test_result_is_serializable():
    res = get_sources("filing_basics", 2023)
    assert isinstance(res, SourcesResult)
    SourcesResult.model_validate_json(res.model_dump_json())  # round-trips


# ── OBBBA / Schedule 1-A routing (Stage 0 correctness fix, 2026-08-07) ────────
# The tax.obbba_schedule_1a block shipped in the 2025 pack while this registry
# had no topic for it, so every query about the new deductions mis-routed to an
# unrelated publication: "qualified overtime" -> itemized_charitable (Pub 526),
# "car loan interest deduction" -> education (Pub 970), "no tax on tips" ->
# dual_status (Pub 519), "Schedule 1-A" -> investment_income (Pub 550). An
# agent following those pointers researches the WRONG law — worse than a miss.


def test_obbba_schedule_1a_queries_route_to_their_own_topic():
    for query in (
        "qualified overtime",
        "overtime deduction",
        "car loan interest deduction",
        "tips deduction",
        "no tax on tips",
        "senior deduction",
        "Schedule 1-A",
    ):
        r = get_sources(query, 2025)
        assert r.matched, query
        topics = {s.topic for s in r.sources}
        assert topics == {"obbba_schedule_1a_deductions"}, f"{query!r} routed to {topics}"


def test_obbba_topic_does_not_steal_the_neighbouring_topics_queries():
    # The words this topic adds (deduction, interest, tips...) overlap several
    # older topics; their canonical queries must keep resolving to themselves.
    for query, expected in (
        ("charitable contributions", "itemized_charitable"),
        ("student loan interest", "education"),
        ("dual status", "dual_status"),
        ("capital gains", "investment_income"),
        ("standard deduction", "standard_deduction"),
    ):
        r = get_sources(query, 2025)
        assert r.matched and {s.topic for s in r.sources} == {expected}, query


# ── Reward / other-income + NRA FDAP routing (H9, pitfall P-005) ───────────────
# Field session 2026-08-10: the characterization of a bank "engagement bonus"
# came entirely from the agent's head — every query below was a clean miss or,
# worse, a WRONG-LAW pointer: the H6 OBBBA topic made "Schedule NEC" (the
# 1040-NR FDAP schedule) route to the Schedule 1-A deduction page. These tests
# are the P-005 regression suite.


def test_reward_income_queries_route_to_other_income_and_rewards():
    for query in (
        "credit card rewards taxable",
        "bank account bonus income",
        "other income 1099-MISC",
        "cash rebate income",
    ):
        r = get_sources(query, 2025)
        assert r.matched, query
        topics = {s.topic for s in r.sources}
        assert topics == {"other_income_and_rewards"}, f"{query!r} routed to {topics}"


def test_nra_fdap_queries_route_to_nonresident_fdap():
    for query in (
        "Schedule NEC",            # the H6-introduced regression: used to hit obbba_schedule_1a_deductions
        "FDAP",
        "nonresident FDAP income", # used to mis-route to nonresident_spouse_election
        "effectively connected income",
        "30% withholding nonresident",  # used to mis-route to dual_status
        "Form 1042-S",
    ):
        r = get_sources(query, 2025)
        assert r.matched, query
        topics = {s.topic for s in r.sources}
        assert topics == {"nonresident_fdap"}, f"{query!r} routed to {topics}"


def test_h9_topics_do_not_steal_their_neighbours_queries():
    # The words these topics add (nonresident, treaty, interest, income,
    # schedule, rewards...) overlap several older topics; the canonical
    # queries must keep resolving to themselves — the SAME guarantee the
    # OBBBA neighbour-theft test pins, extended to the new arrivals.
    for query, expected in (
        ("nonresident and treaties", "nonresident_and_treaties"),
        ("nonresident spouse election", "nonresident_spouse_election"),
        ("dual status", "dual_status"),
        ("Schedule 1-A", "obbba_schedule_1a_deductions"),
        ("no tax on tips", "obbba_schedule_1a_deductions"),
        ("capital gains", "investment_income"),
        ("estimated tax", "estimated_tax"),
    ):
        r = get_sources(query, 2025)
        assert r.matched and {s.topic for s in r.sources} == {expected}, (
            f"{query!r} -> {sorted(s.topic for s in r.sources)}, expected {expected}"
        )
