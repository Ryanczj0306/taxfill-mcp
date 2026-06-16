"""get_sources tests (dev plan section 7 freshness protocol). Reads the real registry."""

import pytest

from taxfill_core.sources import SourcesResult, get_sources


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
