"""filing_summary tests (dev plan section 2 step 8). Offline; uses shipped packs.

`today` is pinned for deterministic deadline/statute-of-limitations status.
"""

from datetime import date

import pytest

from taxfill_core.file_and_pay import FilingManifestItem
from taxfill_core.filing_summary import FilingSummary, filing_summary

TODAY = date(2026, 6, 17)


def _one(item):
    return filing_summary([item], today=TODAY).items[0]


def test_refund_headline_and_open_sol_window():
    it = _one(FilingManifestItem(form="1040", tax_year=2023, bottom_line=1600, direct_deposit=True))
    assert "refund $1,600" in it.headline.lower() and "direct deposit" in it.headline.lower()
    assert it.refund == 1600 and it.owed == 0
    assert "statute of limitations" in it.deadline_status.lower()
    assert "2027-04-15" in it.deadline_status  # 2023 due 2024-04-15 + 3y
    assert it.citations and all(".gov" in c.url for c in it.citations)


def test_owed_headline_and_past_due_penalty_note():
    it = _one(FilingManifestItem(form="1040", tax_year=2023, bottom_line=-407))
    assert "you owe $407" in it.headline.lower()
    assert it.owed == 407 and it.refund == 0
    # 2023 was due 2024-04-15; "today" 2026 is past due -> penalty/interest warning.
    assert "penalt" in it.deadline_status.lower() or "interest" in it.deadline_status.lower()


def test_expired_refund_statute_is_flagged():
    # 2019 return: due 2020-07-15, refund window closes ~2023-07-15 -> expired by 2026.
    it = _one(FilingManifestItem(form="1040", tax_year=2019, bottom_line=900))
    assert "closed" in it.deadline_status.lower() or "forfeit" in it.deadline_status.lower()


def test_plain_explanation_present_for_non_experts():
    it = _one(FilingManifestItem(form="1040", tax_year=2023, bottom_line=1600))
    assert it.plain_explanation and "withh" in it.plain_explanation.lower()


def test_approval_framing_is_review_draft():
    summary = filing_summary([FilingManifestItem(form="1040", tax_year=2023, bottom_line=100)], today=TODAY)
    assert "REVIEW DRAFT" in summary.label
    assert "sign" in summary.approval_prompt.lower() and "approve" in summary.approval_prompt.lower()


def test_supported_state_summary_uses_the_pack():
    it = _one(FilingManifestItem(form="540", tax_year=2023, jurisdiction="states/ca", bottom_line=-100))
    assert "CA 2023: you owe $100" in it.headline
    assert "2024-04-15" in it.deadline_status
    assert any("does not conform to federal tax treaties" in n.lower() for n in it.notes)


def test_unsupported_state_summary_points_to_dor():
    it = _one(FilingManifestItem(form="IT-201", tax_year=2023, jurisdiction="states/ny", bottom_line=-100))
    assert any("dor" in n.lower() for n in it.notes)


def test_back_filing_multiple_years():
    summary = filing_summary(
        [
            FilingManifestItem(form="1040", tax_year=2022, bottom_line=-407),
            FilingManifestItem(form="1040", tax_year=2023, bottom_line=1600),
        ],
        today=TODAY,
    )
    assert [it.tax_year for it in summary.items] == [2022, 2023]
    assert summary.items[0].owed == 407 and summary.items[1].refund == 1600


def test_empty_manifest_rejected():
    with pytest.raises(ValueError, match="at least one"):
        filing_summary([])
