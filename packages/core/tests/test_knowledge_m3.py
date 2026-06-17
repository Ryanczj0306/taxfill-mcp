"""M3 knowledge-block tests: filing thresholds, payments, addresses, deadlines, credits.

Offline: loads the real shipped knowledge/federal/2023.yaml. Every figure was
fetched + cited from irs.gov; the strongest check here is that filing thresholds
reconcile exactly with the independently-sourced standard_deduction block.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.knowledge import FilingThresholds, KnowledgePack, load_knowledge
from taxfill_core.sources import get_sources

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"

US_STATES_PLUS_DC = 51  # 50 states + District of Columbia

# Top-level pack keys that are metadata (not topic blocks needing a source) and
# the freshness ledger itself (backed by sources.yaml change_channels, not by a
# by_topic entry).
NON_TOPIC_BLOCKS = frozenset({"jurisdiction", "tax_year", "effective_law_changes"})

# Coverage rule (dev plan section 7, line 154): every top-level TOPIC BLOCK a
# federal pack ships must be backed by sources.yaml by_topic entries. Block
# names are identical across years, so new year packs that mirror 2023.yaml's
# block names pass automatically. The `tax` block bundles several areas (rate
# schedules, tax table, standard deduction, SE tax) and the `credits` block
# bundles CTC + EITC, so those map to several required by_topic keys.
BLOCK_TO_REQUIRED_TOPICS = {
    "tax": ("tax_rates_and_tables", "standard_deduction", "self_employment"),
    "filing_thresholds": ("filing_thresholds",),
    "payment_options": ("payment_options",),
    "mailing_addresses": ("mailing_addresses",),
    "deadlines": ("deadlines",),
    "credits": ("credits_ctc", "credits_eitc"),
}


@pytest.fixture(scope="module")
def pack() -> KnowledgePack:
    return load_knowledge("federal", 2023, base_dir=KNOWLEDGE_DIR)


def test_all_m3_blocks_present(pack: KnowledgePack):
    assert pack.filing_thresholds and pack.payment_options and pack.mailing_addresses
    assert pack.deadlines and pack.credits


def test_every_block_is_cited_to_a_gov_url(pack: KnowledgePack):
    for block in (pack.filing_thresholds, pack.payment_options, pack.mailing_addresses, pack.deadlines, pack.credits):
        assert block.citation.url.startswith("https://")
        assert ".gov" in block.citation.url


def test_filing_thresholds_reconcile_with_standard_deduction(pack: KnowledgePack):
    ft = pack.filing_thresholds.amounts
    sd = pack.tax.standard_deduction.amounts
    add = pack.tax.standard_deduction.additional_aged_or_blind
    # Non-elderly gross-income threshold == that status's standard deduction.
    assert ft["single"]["under_65"] == sd["single"]
    assert ft["married_filing_jointly"]["both_under_65"] == sd["married_filing_jointly"]
    assert ft["head_of_household"]["under_65"] == sd["head_of_household"]
    # Each 65+ person adds the additional standard deduction.
    assert ft["single"]["age_65_or_older"] == sd["single"] + add.unmarried
    assert ft["head_of_household"]["age_65_or_older"] == sd["head_of_household"] + add.unmarried
    assert ft["married_filing_jointly"]["one_spouse_65_or_older"] == sd["married_filing_jointly"] + add.married
    assert ft["married_filing_jointly"]["both_spouses_65_or_older"] == sd["married_filing_jointly"] + 2 * add.married
    # MFS is the documented exception: $5 at any age.
    assert ft["married_filing_separately"]["any_age"] == 5
    # QSS uses the MFJ column.
    assert ft["qualifying_surviving_spouse"]["under_65"] == sd["married_filing_jointly"]


def test_filing_thresholds_require_all_base_statuses():
    cite = {"source": "x", "url": "https://www.irs.gov/x"}
    with pytest.raises(ValidationError, match="must cover all statuses"):
        FilingThresholds(citation=cite, amounts={"single": {"under_65": 13850}})


def test_payment_check_payee_is_2023_wording(pack: KnowledgePack):
    assert pack.payment_options.check.payee == "United States Treasury"
    assert "1040-V" in pack.payment_options.check.memo
    # Direct Pay / EFTPS are free; a card channel charges a fee.
    by_fee = {p.fee for p in pack.payment_options.electronic}
    assert by_fee == {True, False}
    assert any(not p.fee for p in pack.payment_options.electronic)


def test_mailing_addresses_resolve_by_state_and_cover_every_state(pack: KnowledgePack):
    ma = pack.mailing_addresses
    ca = ma.f1040_for_state("California")
    assert "Ogden" in ca.no_payment and "Cincinnati" in ca.with_payment
    # Case-insensitive.
    assert ma.f1040_for_state("california") == ca
    # Unknown state is a clear error, not a silent wrong address.
    with pytest.raises(KeyError):
        ma.f1040_for_state("Atlantis")
    # All 50 states + DC appear exactly once across the domestic groups.
    seen: list[str] = []
    for group in ma.f1040_groups:
        seen.extend(group.states)
    domestic = [s for s in seen if "," not in s and "Foreign" not in s and "territory" not in s]
    assert len(domestic) == len(set(domestic)) == US_STATES_PLUS_DC


def test_1040nr_addresses_match_the_formpack_convention(pack: KnowledgePack):
    nr = pack.mailing_addresses.f1040nr
    assert "Austin, TX 73301-0215" in nr.no_payment
    assert "P.O. Box 1303" in nr.with_payment and "Charlotte, NC 28201-1303" in nr.with_payment


def test_deadlines_and_refund_statute(pack: KnowledgePack):
    d = pack.deadlines
    assert d.filing_due_date == "2024-04-15"
    sol = d.refund_statute_of_limitations
    assert sol.years_from_filing == 3 and sol.years_from_payment == 2


def test_credits_key_parameters(pack: KnowledgePack):
    ctc = pack.credits.child_tax_credit
    assert ctc["per_qualifying_child"] == 2000
    assert ctc["additional_ctc_refundable_cap_per_child"] == 1600
    assert ctc["magi_phaseout_threshold"]["married_filing_jointly"] == 400000
    assert ctc["magi_phaseout_threshold"]["single"] == 200000
    eitc = pack.credits.earned_income_tax_credit
    assert eitc["investment_income_limit"] == 11000
    assert eitc["by_qualifying_children"]["3+"]["max_credit"] == 7430
    assert eitc["by_qualifying_children"]["0"]["max_credit"] == 600


# ---------------------------------------------------------------------------
# Coverage meta-test (dev plan section 7, line 154): every top-level TOPIC
# BLOCK shipped by a federal pack must be backed by a sources.yaml by_topic
# entry. Driven by block NAMES (identical across years), so each new year pack
# that mirrors 2023.yaml's block names is covered automatically.
# ---------------------------------------------------------------------------

FEDERAL_PACK_FILES = sorted((KNOWLEDGE_DIR / "federal").glob("[0-9][0-9][0-9][0-9].yaml"))


def _backing_topics(topic_key: str, year: int) -> set[str]:
    """The by_topic keys get_sources resolves a topic key to (empty if a miss)."""
    res = get_sources(topic_key, year, base_dir=KNOWLEDGE_DIR)
    return {s.topic for s in res.sources if s.topic} if res.matched else set()


def test_every_federal_pack_block_has_a_backing_source():
    assert FEDERAL_PACK_FILES, "no federal knowledge packs found to check"
    available = set(get_sources("filing_basics", 2023, base_dir=KNOWLEDGE_DIR).available_topics)
    for pack_path in FEDERAL_PACK_FILES:
        year = int(pack_path.stem)
        raw = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        blocks = [k for k in raw if k not in NON_TOPIC_BLOCKS]
        for block in blocks:
            assert block in BLOCK_TO_REQUIRED_TOPICS, (
                f"{pack_path.name}: top-level block '{block}' has no entry in BLOCK_TO_REQUIRED_TOPICS — "
                f"add a sources.yaml by_topic entry for it and map it here (coverage rule, dev plan section 7)"
            )
            for topic_key in BLOCK_TO_REQUIRED_TOPICS[block]:
                assert topic_key in available, (
                    f"{pack_path.name}: block '{block}' needs sources.yaml by_topic '{topic_key}', "
                    f"which is missing from the federal registry (coverage rule, dev plan section 7)"
                )
                # The registry entry must actually resolve via get_sources to a .gov URL.
                assert topic_key in _backing_topics(topic_key, year), (
                    f"sources.yaml by_topic '{topic_key}' does not resolve via get_sources"
                )


def test_change_channels_cover_section7_freshness_signals():
    # Section 7 enumerates the change channels a pack relies on for figures that
    # post-date it: newsroom, prior-year archive, the IRB/Rev. Procs, Congress.gov
    # (enacted law), and the Federal Register (Treasury/IRS rulemaking).
    res = get_sources("filing_basics", 2024, base_dir=KNOWLEDGE_DIR)
    urls = " ".join(c.url for c in res.change_channels)
    for needle in ("newsroom", "irs-prior", "/irb", "congress.gov", "federalregister.gov"):
        assert needle in urls, f"change_channels missing the section-7 source '{needle}'"
    assert all(c.url.startswith("https://") and ".gov" in c.url for c in res.change_channels)
