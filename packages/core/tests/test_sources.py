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


def test_treaties_topic_also_carries_the_disclosure_half(  # Phase I4
):
    """A treaty position has a DISCLOSURE duty; the topic must name where it lives.

    calc.treaty_benefit priced the exemption from G1 onward while nothing in the
    registry said where the IRC 6114 duty, the Form 8833 that discharges it, or
    the Treas. Reg. 301.6114-1(c) WAIVERS are written — so an agent could tell a
    filer to attach a form the regulation waives, or omit one the regulation
    requires.
    """
    res = get_sources("nonresident_and_treaties", 2025)
    urls = " ".join(s.url for s in res.sources)
    answers = " ".join(s.answers for s in res.sources)
    assert "f8833.pdf" in urls                    # the form + its instructions
    assert "301.6114-1" in urls                   # the (b) list and the (c) waivers
    assert "Exceptions from reporting" in answers  # the waiver bullets by name
    assert "6712" in answers                      # the penalty for not disclosing


def test_the_disclosure_sources_do_not_steal_the_neighbouring_queries():
    """The words these two entries add must not pull neighbours into this topic.

    They contribute "disclosure", "residency", "nonresident", "waiver",
    "penalty", "trainee", "teacher", "attachment" — every one of which also
    appears in a neighbouring international topic, which is exactly how the H6
    and H9 mis-routings happened.
    """
    for query, expected in (
        ("dual status year filing", "dual_status"),
        ("foreign earned income exclusion", "foreign_earned_income"),
        ("nonresident FDAP income", "nonresident_fdap"),
        ("Schedule NEC", "nonresident_fdap"),
        ("nonresident spouse election", "nonresident_spouse_election"),
    ):
        r = get_sources(query, 2025)
        assert r.matched, query
        topics = {src.topic for src in r.sources}
        assert topics == {expected}, f"{query!r} routed to {topics}"


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


def test_registry_less_state_jurisdiction_reports_no_registry():
    # A no-income-tax state ships no knowledge pack, so it has no generated
    # registry block either — the caller is told to resolve at the DOR.
    # (Income-tax states DO have blocks now — see the D2d tests below; this
    # test used to pin states/ca as empty, which was the gap itself.)
    res = get_sources("filing_basics", 2023, jurisdiction="states/tx")
    assert res.matched is False
    assert res.available_topics == []
    assert any("state" in n.lower() for n in res.notes)


def test_income_tax_state_topic_mismatch_lists_available_topics():
    res = get_sources("quantum levy", 2023, jurisdiction="states/ca")
    assert res.matched is False
    assert "forms_and_instructions" in res.available_topics
    assert any("available_topics" in n for n in res.notes)


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
# P-005: characterizing a bank account bonus had no routed authority — every
# query below was a clean miss or, worse, a WRONG-LAW pointer: the H6 OBBBA
# topic made "Schedule NEC" (the 1040-NR FDAP schedule) route to the Schedule
# 1-A deduction page. These tests are the P-005 regression suite.


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


# ── The per-state registry (D2d: sources.yaml shipped `states: {}` while 126
# state packs were live — the freshness protocol was federal-only, blocking any
# state TY2026 planning pack). knowledge/sources_states.yaml is GENERATED from
# the packs' own verified citations; these tests pin coverage + freshness.


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[3]


def test_every_state_with_a_knowledge_pack_has_a_registry_block():
    root = _repo_root()
    packed = {d.name for d in (root / "knowledge" / "states").iterdir()
              if d.is_dir() and any(p.stem.isdigit() for p in d.glob("*.yaml"))}
    covered = set()
    for st in sorted(packed):
        r = get_sources("forms and instructions", 2026, f"states/{st}")
        if r.available_topics:
            covered.add(st)
    missing = sorted(packed - covered)
    assert not missing, f"states with packs but no source registry block: {missing}"
    assert len(covered) >= 42


def test_state_lookup_resolves_to_that_states_own_authority():
    r = get_sources("tax rates and brackets", 2026, "states/ri")
    assert r.matched
    assert {s.topic for s in r.sources} == {"tax_rates_and_brackets"}
    assert all("tax.ri.gov" in s.url for s in r.sources)
    # The change channels carry the pack's primary authority + the IRS state directory.
    urls = " ".join(c.url for c in r.change_channels)
    assert "tax.ri.gov" in urls and "state-government-websites" in urls


def test_state_retrieval_hint_is_state_shaped():
    r = get_sources("forms and instructions", 2026, "states/ca")
    assert "DOR" in r.retrieval_hint and "irs-prior" not in r.retrieval_hint
    assert "Refuse to fill" in r.retrieval_hint


def test_generated_state_registry_is_current():
    # The same byte-equality guard the badge/skills use: regenerating from the
    # packs must reproduce the committed file, so a pack edit that changes
    # citations cannot silently strand the registry.
    import subprocess
    import sys

    root = _repo_root()
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "assemble_state_sources.py"), "--check"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── Commuter / transportation fringe routing (P-006) ──────────────────────────
# P-006: the packs shipped the §132(f) monthly CAPS but no eligibility
# authority, and "qualified parking" mis-routed to
# obbba_schedule_1a_deductions — the token "qualified" pulling toward the OBBBA
# topic, the same wrong-law failure Schedule NEC had. These are the P-006
# regression tests.


def test_commuter_queries_route_to_their_own_topic():
    for query in (
        "commuter benefits",
        "qualified parking",       # was -> obbba_schedule_1a_deductions (wrong law)
        "transit pass",            # was a clean miss
        "transportation fringe benefits",
        "commuter highway vehicle",
        # The not-covered side is the same authority: an agent asking whether
        # vehicle energy or tolls can ride the benefit must land on the page
        # whose exhaustive three-item list answers "no", not on a clean miss.
        "electric vehicle charging",
        "EV charging reimbursement",
        "tolls and mileage commuting",
    ):
        r = get_sources(query, 2026)
        assert r.matched, query
        topics = {s.topic for s in r.sources}
        assert topics == {"commuter_and_fringe_benefits"}, f"{query!r} routed to {topics}"


def test_the_commuter_topic_carries_eligibility_authority_not_just_limits():
    """The gap that made this topic necessary: an agent must reach the text that
    says WHAT QUALIFIES, not only the year's dollar caps."""
    r = get_sources("qualified parking", 2026)
    blob = " ".join(s.answers for s in r.sources)
    assert "on or near your business premises" in blob
    assert "doesn't include parking at or near your employee's home" in blob
    assert "incur and substantiate expenses" in blob  # the bona fide arrangement rule
    assert any("p15b" in s.url for s in r.sources) and any("1-132-9" in s.url for s in r.sources)


def test_commuter_topic_does_not_steal_its_neighbours_queries():
    for query, expected in (
        ("Schedule 1-A", "obbba_schedule_1a_deductions"),
        ("no tax on tips", "obbba_schedule_1a_deductions"),
        ("contribution limits", "contribution_limits"),
        ("credit card rewards taxable", "other_income_and_rewards"),
        ("Schedule NEC", "nonresident_fdap"),
        ("retirement", "retirement"),
    ):
        r = get_sources(query, 2026)
        assert r.matched and {s.topic for s in r.sources} == {expected}, (
            f"{query!r} -> {sorted(s.topic for s in r.sources)}, expected {expected}"
        )


def test_ira_basis_queries_route_to_their_own_topic():
    """Pitfall P-009: the routing half of the IRA pro-rata gap.

    Before this topic existed, "Form 8606", "pro rata rule" and "nondeductible
    IRA basis" were clean misses, and "nondeductible contributions" routed to
    Pub 526 + Form 8283 — CHARITABLE-contribution substantiation, a wrong-law
    pointer of exactly the P-005 "Schedule NEC" / P-006 "qualified parking" kind.
    """
    for query in (
        "Form 8606",                    # was a clean miss
        "pro rata rule",                # was a clean miss
        "nondeductible IRA basis",      # was a clean miss
        "nondeductible contributions",  # was -> itemized_charitable (WRONG LAW)
        "backdoor Roth",
        "Roth conversion",
        "rollover 401k to Roth IRA",
        "IRA aggregation",
    ):
        r = get_sources(query, 2026)
        assert r.matched, query
        topics = {s.topic for s in r.sources}
        assert topics == {"ira_basis_and_roth_conversions"}, f"{query!r} routed to {topics}"


def test_the_ira_basis_topic_carries_both_conversion_paths():
    """The characterization half: an agent must reach the DENOMINATOR rule and the
    plan-to-Roth-IRA path, not only the year's contribution limits."""
    r = get_sources("backdoor Roth", 2026)
    blob = " ".join(s.answers for s in r.sources)
    assert "line 9 = 6 + 7 + 8" in blob                 # the denominator adds the conversion back
    assert "each distribution is partly nontaxable and partly taxable" in blob
    assert "included in gross income any amount that would be includible" in blob
    assert "No recharacterizations of conversions made in 2018 or later" in blob
    urls = {s.url for s in r.sources}
    assert any("f8606" in u for u in urls) and any("n-08-30" in u for u in urls)
    assert any("n-14-54" in u for u in urls) and any("p590b" in u for u in urls)


def test_ira_basis_topic_does_not_steal_its_neighbours_queries():
    # "foreign pension distributions" is the live regression: the first draft of
    # this topic swallowed it (its answers text said "Pension Protection Act"),
    # turning a deliberate clean miss into a wrong matched=True citation.
    miss = get_sources("foreign pension distributions", 2026)
    assert miss.matched is False and miss.sources == []
    for query, expected in (
        ("contribution limits", "contribution_limits"),
        ("IRA deduction phase out", "contribution_limits"),
        ("qualified parking", "commuter_and_fringe_benefits"),
        ("credit card rewards taxable", "other_income_and_rewards"),
        ("Schedule NEC", "nonresident_fdap"),
        ("no tax on tips", "obbba_schedule_1a_deductions"),
        ("retirement", "retirement"),
    ):
        r = get_sources(query, 2026)
        assert r.matched and {s.topic for s in r.sources} == {expected}, (
            f"{query!r} -> {sorted(s.topic for s in r.sources)}, expected {expected}"
        )


# ── Foreign tax credit / IRC 904(j) routing (P-011) ──────────────────────────
# The widest wrong-law hole found so far, on the single most common
# international fact in a resident return: foreign tax withheld on a
# total-international index fund (Form 1099-DIV box 7). Five of the eight
# natural queries below routed to the WRONG LAW and three were clean misses —
# see knowledge/pitfalls.yaml P-011 for the reproduction.


def test_foreign_tax_credit_queries_route_to_their_own_topic():
    """Pitfall P-011: the routing half of the foreign-tax-credit gap.

    Before this topic existed (probed against the 2023 registry):
      "foreign tax credit"     -> foreign_earned_income (Form 2555, the
                                  EXCLUSION — the ALTERNATIVE treatment, so the
                                  pointer sends an agent to exclude income it
                                  should be crediting tax on);
      "foreign taxes withheld" -> nonresident_fdap (the 30% the US withholds
                                  FROM a nonresident — the mirror image);
      "1099-DIV box 7"         -> ira_basis_and_roth_conversions (P-009's own
                                  new topic swallowing it);
      "904(j)"                 -> tax_rates_and_tables (the section 1 rate
                                  schedules);
      "de minimis election"    -> commuter_and_fringe_benefits (the de minimis
                                  FRINGE);
      "Form 1116", "passive category income" and "foreign tax credit without
      filing Form 1116" -> clean misses.
    """
    for query in (
        "foreign tax credit",                           # was -> foreign_earned_income (WRONG LAW)
        "foreign taxes withheld",                       # was -> nonresident_fdap (WRONG LAW)
        "1099-DIV box 7",                               # was -> ira_basis_and_roth_conversions (WRONG LAW)
        "904(j)",                                       # was -> tax_rates_and_tables (WRONG LAW)
        "de minimis election",                          # was -> commuter_and_fringe_benefits (WRONG LAW)
        "Form 1116",                                    # was a clean miss
        "passive category income",                      # was a clean miss
        "foreign tax credit without filing Form 1116",  # was a clean miss
        "credit for taxes paid to a foreign country",
        "carryover of foreign taxes",
    ):
        for year in (2023, 2026):
            r = get_sources(query, year)
            assert r.matched, f"{query!r} ({year}) is a miss"
            topics = {s.topic for s in r.sources}
            assert topics == {"foreign_tax_credit"}, f"{query!r} ({year}) routed to {topics}"


def test_the_foreign_tax_credit_topic_carries_the_election_and_its_cost():
    """The characterization half: an agent must reach the ELECTION, its dollar
    test, its two-way carryover forfeiture and the estates/trusts exclusion —
    not just the form's line map."""
    r = get_sources("foreign tax credit", 2023)
    blob = " ".join(s.answers for s in r.sources)
    # the statutory dollar test, verbatim from 904(j)(2)(B)
    assert "does not exceed $300 ($600 in the case of a joint return)" in blob
    # what the election COSTS — never presented as free
    assert "forbids carrying tax to or from any other year" in blob
    assert "You can't carry over to or from any other year" in blob
    # the entity exclusion and the payee-statement definition
    assert "excludes estates and trusts" in blob
    assert "section 6724(d)(2)" in blob
    # the 1099 shortcut that makes Part II fillable for the target user
    assert "Enter '1099 taxes' in Part II, column (l)" in blob
    # creditability is not waived: 901/903 and the 901(k) holding period
    assert "901(k)" in blob and "tax paid in lieu of a tax on income" in blob
    urls = {s.url for s in r.sources}
    assert any("section904" in u for u in urls) and any("section901" in u for u in urls)
    assert any("f1116" in u for u in urls) and any("i1116" in u for u in urls)
    assert any("p514" in u for u in urls)


def test_foreign_tax_credit_topic_does_not_steal_its_neighbours_queries():
    """The credit and the EXCLUSION are alternative treatments of foreign income,
    so the new topic sits right next to foreign_earned_income and the two must
    stay apart — plus every other neighbour pinned by P-005/P-006/P-009."""
    # "foreign pension distributions" is P-009's deliberate clean miss; a topic
    # this full of the word "foreign" must not turn it into a wrong match.
    miss = get_sources("foreign pension distributions", 2026)
    assert miss.matched is False and miss.sources == []
    for query, expected in (
        ("foreign earned income exclusion", "foreign_earned_income"),
        ("Form 2555", "foreign_earned_income"),
        ("physical presence test", "foreign_earned_income"),
        ("Schedule NEC", "nonresident_fdap"),
        ("qualified parking", "commuter_and_fringe_benefits"),
        ("nondeductible contributions", "ira_basis_and_roth_conversions"),
        ("Form 8606", "ira_basis_and_roth_conversions"),
        ("credit card rewards taxable", "other_income_and_rewards"),
        ("no tax on tips", "obbba_schedule_1a_deductions"),
    ):
        r = get_sources(query, 2026)
        assert r.matched and {s.topic for s in r.sources} == {expected}, (
            f"{query!r} -> {sorted(s.topic for s in r.sources)}, expected {expected}"
        )


# ── N-8 / pitfall P-013: the nonresident bank-deposit-interest exclusion ───────
# Before N-8, nothing in any topic named the §871(i)(2)(A) exclusion, so the
# queries an agent asks about a nonresident's 1099-INT reached the WRONG LAW:
# "bank deposit interest nonresident" -> other_income_and_rewards (the BANK-BONUS
# topic), "871(i)" -> foreign_tax_credit, "871(i) deposit interest" ->
# foreign_asset_and_fbar_reporting. nonresident_fdap now carries the IRC 871
# statute and the Pub 519 ch. 3 / ch. 1 sentences that route them home.


def test_p013_deposit_interest_queries_route_to_nonresident_fdap():
    # P-013: the routing half — each query used to reach the wrong law.
    for query in (
        "bank deposit interest nonresident",  # was -> other_income_and_rewards (WRONG LAW)
        "871(i)",                             # was -> foreign_tax_credit (WRONG LAW)
        "871(i) deposit interest",            # was -> foreign_asset_and_fbar_reporting (WRONG LAW)
    ):
        for year in (2023, 2025, 2026):
            r = get_sources(query, year)
            assert r.matched, f"{query!r} ({year}) is a miss"
            topics = {s.topic for s in r.sources}
            assert topics == {"nonresident_fdap"}, f"{query!r} ({year}) routed to {topics}"
            urls = {s.url for s in r.sources}
            assert any("section871" in u and u.startswith("https://uscode.house.gov/") for u in urls)
            assert "https://www.irs.gov/publications/p519" in urls


def test_p013_the_fdap_topic_carries_the_exclusion_and_what_ends_it():
    """P-013, the characterization half: the statute's own words, the deposit definition,
    and the ELECTION (not the marriage) that ends the exclusion."""
    r = get_sources("871(i) deposit interest", 2025)
    blob = " ".join(s.answers for s in r.sources)
    # 871(i)(2)(A) verbatim (uscode.house.gov)
    assert "interest on deposits, if such interest is not effectively connected with the conduct of a trade or business within the United States" in blob
    assert "871(i)(3)" in blob and "insurance company under an agreement to pay interest" in blob
    # Pub 519 ch. 3 — the exclusion from gross income
    assert "Exclusions From Gross Income" in blob and "EXCLUDED from income" in blob
    # Pub 519 ch. 1 — the election, verbatim, and rule (c)
    assert "treated for income tax purposes as residents for your entire tax year" in blob
    assert "the election, not the marriage" in blob
    # rule (a): character, not payer — ECI deposit interest and bond interest stay taxed
    assert "871(b)" in blob and "bond or brokerage interest is not a deposit" in blob


def test_p013_the_deposit_interest_entries_do_not_steal_the_neighbours_queries():
    """P-013 neighbour theft (the knowledge-gap companion bug): the words N-8 added —
    bank, deposit, interest, insurance, election — sit in several neighbouring
    topics, the bank-BONUS topic above all. Each canonical query must still
    resolve to its own topic."""
    for query, expected in (
        ("bank account bonus income", "other_income_and_rewards"),
        ("bank bonus taxable", "other_income_and_rewards"),
        ("credit card rewards taxable", "other_income_and_rewards"),
        ("foreign tax credit", "foreign_tax_credit"),
        ("FBAR", "foreign_asset_and_fbar_reporting"),
        ("Form 8938", "foreign_asset_and_fbar_reporting"),
        ("nonresident spouse election", "nonresident_spouse_election"),
        ("dual status", "dual_status"),
        ("mortgage interest", "itemized_mortgage_interest"),
    ):
        for year in (2023, 2026):
            r = get_sources(query, year)
            assert r.matched and {s.topic for s in r.sources} == {expected}, (
                f"{query!r} ({year}) -> {sorted(s.topic for s in r.sources)}, expected {expected}"
            )


def test_p013_the_election_sentence_does_not_steal_the_spouse_election_queries():
    """P-013 neighbour theft, the ELECTION side. nonresident_fdap has to say what ends
    the exclusion (Pub 519 ch. 1's joint-return choice), and the first J0.4 draft said
    it with the tokens the nonresident_spouse_election topic wins on: the ch. 1
    heading "Nonresident Spouse Treated as a Resident", "§6013(g)/(h)", "nonresident
    alien" and extra "nonresident"s. That draft routed each query below to
    nonresident_fdap, which dropped the IRS page that says HOW to make the choice (the
    statement both spouses sign, the ITIN). A later pointer, "(topic
    nonresident_spouse_election)", stole "spouse election" in the same way."""
    for query in (
        "spouse treated as resident",
        "nonresident spouse treated as a resident",  # the Pub 519 ch. 1 heading itself
        "6013(g)",
        "6013(h)",
        "married to a nonresident alien",
        "married nonresident alien",
        "spouse election",
    ):
        for year in (2023, 2026):
            r = get_sources(query, year)
            assert r.matched and {s.topic for s in r.sources} == {"nonresident_spouse_election"}, (
                f"{query!r} ({year}) -> {sorted(s.topic for s in r.sources)}"
            )
    # Before N-8, "married to nonresident" tied the two topics. More "nonresident"
    # tokens in the fdap text break that tie against the spouse topic, and nothing
    # warns when they do. So the query must still reach the election page.
    r = get_sources("married to nonresident", 2025)
    assert "nonresident_spouse_election" in {s.topic for s in r.sources}
    # The fdap topic still says what ends the exclusion. It says it in words the
    # election topic does not score on.
    blob = " ".join(s.answers for s in get_sources("871(i) deposit interest", 2025).sources)
    assert "the election, not the marriage" in blob
    assert "Nonresident Spouse Treated as a Resident" not in blob and "6013" not in blob


# ── Phase J JF2.1 / JF2.4: wrong-law routing (the P-005/P-006 class) ─────────
# Reproduced 2026-09-23 against the registry: each query below reached the WRONG
# LAW or was a clean miss. The eight topics added for them, and the J0 re-verify
# follow-up on interest queries, are pinned here both ways.

_JF2_ROUTES = (
    ("net income attributable", "ira_recharacterization_and_excess_contributions"),  # was self_employment
    ("Treas. Reg. 1.408A-5", "ira_recharacterization_and_excess_contributions"),     # was FBAR
    ("Form 5498 box 4", "ira_recharacterization_and_excess_contributions"),          # was foreign_tax_credit
    ("recharacterization", "ira_recharacterization_and_excess_contributions"),       # was a clean miss
    ("Form 5329", "ira_recharacterization_and_excess_contributions"),                # was a clean miss
    ("1099-R box 7 code N", "form_1099r_distribution_codes"),                        # was foreign_tax_credit
    ("supplemental wage withholding bonus", "payroll_withholding"),                  # was deadlines
    ("paycheck withholding W-4 percentage method", "payroll_withholding"),           # was foreign_tax_credit
    ("Publication 15-T", "payroll_withholding"),                                     # was FBAR
    ("paystub W-2 box 1 box 3 box 5", "wage_reporting_w2"),                          # was ira_basis_and_roth_conversions
    ("excess deferrals", "excess_deferrals_402g"),
    ("non-itemizer charitable deduction", "charitable_nonitemizer"),                 # was a clean miss
    ("charitable membership benefits", "itemized_charitable"),                       # was a clean miss
    ("wage repayment", "wage_repayment_claim_of_right"),
    ("claim of right", "wage_repayment_claim_of_right"),                             # was foreign_tax_credit
    ("underpayment penalty", "underpayment_penalty"),
    ("Form 2210", "underpayment_penalty"),
)


def test_jf2_wrong_law_queries_route_to_their_own_topic():
    for query, expected in _JF2_ROUTES:
        for year in (2025, 2026):
            r = get_sources(query, year)
            assert r.matched and {s.topic for s in r.sources} == {expected}, (
                f"{query!r} ({year}) -> {sorted(s.topic for s in r.sources)}, expected {expected}"
            )


def test_jf2_interest_queries_route_both_ways():
    """The J0 re-verify follow-up: the N-8 deposit-interest text pulled the resident-generic interest
    queries onto nonresident_fdap, while the nonresident ones reached other topics."""
    for query in ("interest income", "savings bond interest", "certificate of deposit", "deposit interest"):
        r = get_sources(query, 2025)
        assert {s.topic for s in r.sources} == {"investment_income"}, query
    for query in ("1099-INT nonresident", "nonresident alien bank interest", "NRA interest",
                  "bank deposit interest nonresident", "871(i)", "871(i) deposit interest"):
        r = get_sources(query, 2025)
        assert {s.topic for s in r.sources} == {"nonresident_fdap"}, query
    blob = " ".join(s.answers for s in get_sources("interest income", 2025).sources)
    assert "Taxable interest includes interest you receive from bank accounts" in blob   # Pub 550, verbatim
    assert "should be reported as dividends, not as interest" in blob


def test_jf2_new_topics_carry_their_law():
    def blob(query):
        r = get_sources(query, 2025)
        return " ".join(s.answers for s in r.sources), {s.url for s in r.sources}

    text, urls = blob("recharacterization")
    assert "https://www.ecfr.gov/current/title-26/section-1.408-11" in urls
    assert "attributable to withdrawal of net income attributable to a contribution" in text    # IRC 72(t)(2)(A)(ix)
    assert "shall not exceed 6 percent of the value of the account or annuity" in text          # IRC 4973(a)
    assert "the section 301.9100-2 relief" in text
    text, _ = blob("claim of right")
    assert "it appeared that the taxpayer had an unrestricted right to such item" in text       # IRC 1341
    assert "You can't make an adjustment for income tax withholding" in text                  # Pub 15 section 13
    text, _ = blob("non-itemizer charitable deduction")
    assert "enter cash contributions up to $1,000" in text and "0.5 percent of the taxpayer's contribution base" in text
    text, _ = blob("underpayment penalty")
    assert "is less than $1,000" in text and "The IRS will generally figure your penalty for you" in text
    text, _ = blob("excess deferrals")
    assert "by April 15 of the following year" in text and "Not later than the first April 15" in text
    text, _ = blob("supplemental wage withholding bonus")
    assert "The withholding rate on supplemental wages remains 22%" in text


def test_jf2_new_topics_do_not_steal_their_neighbours_queries():
    """Neighbour theft (the knowledge-gap companion bug), including the regressions the first draft of
    these topics caused and a HEAD-vs-tree sweep over 226 queries found (2026-09-27)."""
    for query, expected in (
        ("self-employment tax", "self_employment"),
        ("foreign tax credit", "foreign_tax_credit"),
        ("1099-DIV box 7", "foreign_tax_credit"),
        ("FBAR", "foreign_asset_and_fbar_reporting"),
        ("Form 8606", "ira_basis_and_roth_conversions"),
        ("Roth conversion", "ira_basis_and_roth_conversions"),
        ("backdoor Roth", "ira_basis_and_roth_conversions"),
        ("estimated tax", "estimated_tax"),
        ("estimated tax payments", "estimated_tax"),          # the Form 2210 quote took it
        ("contribution limits", "contribution_limits"),
        ("401k contribution limit", "contribution_limits"),   # the TEOS text took it
        ("IRA contribution limit", "retirement"),             # the 1099-R code N quote took it
        ("HSA", "contribution_limits"),
        ("net investment income tax", "investment_income"),
        ("early distribution penalty", "retirement"),
        ("tips deduction", "obbba_schedule_1a_deductions"),   # the W-2 box 1 quote tied it
        ("charitable contributions", "itemized_charitable"),  # the TEOS text took it
        ("amended return", "filing_basics"),                  # the Pub 590-A quote took it
        ("where to file", "mailing_addresses"),
        ("extension", "deadlines"),
    ):
        r = get_sources(query, 2025)
        assert r.matched and {s.topic for s in r.sources} == {expected}, (
            f"{query!r} -> {sorted(s.topic for s in r.sources)}, expected {expected}"
        )


def test_jf2_the_spouse_election_topic_says_where_each_statement_goes():
    """JF2.4: the 6013(g) statement goes on the first joint return, the 6013(h) statement on the joint
    return for the year of the choice, and a later year of a continuing 6013(g) election attaches none."""
    r = get_sources("spouse election", 2025)
    assert {s.topic for s in r.sources} == {"nonresident_spouse_election"}
    text = " ".join(s.answers for s in r.sources)
    assert "to your joint return for the first tax year for which the choice applies" in text
    assert "to your joint return for the year of the choice" in text
    assert "a later year of a continuing 6013(g) election attaches none" in text
    assert "https://www.irs.gov/publications/p519" in {s.url for s in r.sources}


# ── Phase J JT0c: the TY2026 topics and the draft_forms change channel ─────

_JT0C_ROUTES = (
    ("federal public benefit", "federal_public_benefit"),
    ("qualified alien", "federal_public_benefit"),                      # was foreign_asset_and_fbar_reporting
    ("itemized limitation", "itemized_limitation_2026"),                # was the four itemized_* topics
    ("Pease limitation", "itemized_limitation_2026"),                   # was foreign_tax_credit
    ("Form 1098-VLI", "form_1098vli"),                                  # was education
    ("vehicle loan interest statement", "form_1098vli"),                # was obbba_schedule_1a_deductions
    ("box 12 code TP", "w2_2026_codes_tp_tt"),                          # was form_1099r_distribution_codes
    ("Treasury Tipped Occupation Code", "w2_2026_codes_tp_tt"),         # was a clean miss
    ("Trump account", "trump_accounts"),                                # was foreign_asset_and_fbar_reporting
    ("Form 4547", "trump_accounts"),                                    # was a clean miss
    ("EIC table", "tax_tables"),
    ("tax table", "tax_tables"),
)


def test_jt0c_the_2026_topics_route_to_themselves():
    for query, expected in _JT0C_ROUTES:
        r = get_sources(query, 2026)
        assert r.matched and {s.topic for s in r.sources} == {expected}, (
            f"{query!r} -> {sorted(s.topic for s in r.sources)}, expected {expected}"
        )


def test_jt0c_the_2026_topics_carry_their_law_verbatim():
    def blob(query):
        r = get_sources(query, 2026)
        return " ".join(s.answers for s in r.sources), {s.url for s in r.sources}

    text, urls = blob("federal public benefit")
    assert "Are you or your spouse a U.S. citizen, U.S. national, or qualified alien? See instructions." in text
    assert "lawfully admitted for permanent residence" in text and "is not eligible for any Federal public benefit" in text
    assert "https://www.irs.gov/pub/irs-dft/f1040s3a--dft.pdf" in urls
    text, _ = blob("itemized limitation")
    assert "shall be reduced by 2/37 of the lesser of" in text and "more than $384,350?" in text
    text, _ = blob("Form 1098-VLI")
    assert "aggregating $600 or more for any calendar year on a specified" in text
    assert "on the return of tax for the taxable year" in text                 # IRC 163(h)(4)(B)(iii), the VIN rule
    text, urls = blob("box 12 code TP")
    assert "New box 12, code TT, will be used to report the total amount of qualified overtime compensation." in text
    assert "https://www.irs.gov/pub/irs-prior/iw2w3--2026.pdf" in urls           # the 2026 instructions are FINAL
    text, _ = blob("Trump account")
    assert "shall not exceed $5,000" in text and "Is born after December 31, 2024, and before January 1, 2029" in text
    text, urls = blob("tax table")
    assert "First, they find the $25,300–25,350 taxable income line." in text
    assert "https://www.irs.gov/pub/irs-dft/p1040--dft.pdf" in urls


def test_jt0c_the_2026_topics_do_not_steal_their_neighbours_queries():
    """The planned keys w2_2026_tips_overtime and vehicle_loan_interest_statement took these (their key
    tokens outweigh any answers text), so they ship as w2_2026_codes_tp_tt and form_1098vli."""
    for query, expected in (
        ("tips", "obbba_schedule_1a_deductions"),
        ("tips deduction", "obbba_schedule_1a_deductions"),
        ("tax on tips", "obbba_schedule_1a_deductions"),
        ("overtime", "obbba_schedule_1a_deductions"),
        ("car loan interest", "obbba_schedule_1a_deductions"),
        ("student loan interest", "education"),
        ("interest income", "investment_income"),
        ("mortgage interest", "itemized_mortgage_interest"),
        ("Form 1098", "itemized_mortgage_interest"),                    # was education; the Pub 936 sentence
        ("earned income credit", "credits_eitc"),
        ("Form W-2", "wage_reporting_w2"),
        ("Form 1040-X", "filing_basics"),
    ):
        r = get_sources(query, 2026)
        assert r.matched and {s.topic for s in r.sources} == {expected}, (
            f"{query!r} -> {sorted(s.topic for s in r.sources)}, expected {expected}"
        )
    broad = {s.topic for s in get_sources("itemized deductions", 2026).sources}
    assert {"itemized_charitable", "itemized_medical", "itemized_mortgage_interest", "itemized_salt"} <= broad


def test_jt0c_a_year_is_never_a_routing_signal():
    """The year is get_sources' argument. Before JT0c "2026 tax brackets" routed to the charitable
    non-itemizer entry (which quotes a 2026 date) and a year-named key took every "2026 ..." query."""
    assert {s.topic for s in get_sources("2026 tax brackets", 2026).sources} == {"tax_rates_and_tables"}
    assert {s.topic for s in get_sources("2026 standard deduction", 2026).sources} == {"standard_deduction"}
    assert {s.topic for s in get_sources("W-2 2026", 2026).sources} == {"wage_reporting_w2"}
    assert not get_sources("2026", 2026).matched


def test_jt0c_the_draft_forms_change_channel():
    channels = get_sources("filing_basics", 2026).change_channels
    draft = [c for c in channels if c.url == "https://www.irs.gov/draft-tax-forms"]
    assert draft and "there are never any changes to the last posted draft of the form" in draft[0].answers
