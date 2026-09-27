"""Onboarding-worksheet tests (H3, N-3/N-5).

The worksheet ships INSIDE the package (docs/ is not in the wheel), so the
module constants are the runtime source and the docs files are their mirror —
the sync tests here make editing one side without the other fail CI, the same
pattern test_skills_sync.py uses for the agent-facing skills.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.intake import intake_checklist
from taxfill_core.schemas.profile import Identity, Profile
from taxfill_core.worksheet import WORKSHEET_LANGUAGES, intake_worksheet

REPO = Path(__file__).resolve().parents[3]
DOCS = {
    "en": REPO / "docs" / "INTAKE_WORKSHEET.md",
    "zh-CN": REPO / "docs" / "INTAKE_WORKSHEET.zh-CN.md",
}


@pytest.mark.parametrize("language", sorted(DOCS))
def test_docs_mirror_the_shipped_worksheet_byte_for_byte(language: str) -> None:
    assert intake_worksheet(language) == DOCS[language].read_text(encoding="utf-8"), (
        f"docs/{DOCS[language].name} and taxfill_core.worksheet drifted — edit both together "
        f"(the module is what a wheel install actually serves)"
    )


def test_every_language_constant_has_a_docs_mirror() -> None:
    assert set(WORKSHEET_LANGUAGES) == set(DOCS)


def test_unknown_language_errors_prescriptively() -> None:
    with pytest.raises(ValueError, match="zh-CN"):
        intake_worksheet("fr")


def test_worksheet_covers_the_h_tranche_surfaces() -> None:
    """The worksheet must ask for the facts the H1-H3 schema can now hold."""
    text = intake_worksheet()
    for marker in (
        "I-797",                  # H1: the H-1B start-date disambiguation
        "STEM OPT",               # H1: the sub_status vocabulary in user terms
        "two separate taxpayers", # H2: one worksheet per person
        "Remote?",                # H3: the remote column
        "Employer/school's state",# H3: the employer-state column
        "W-2 Box 15",             # H3: the mismatch trigger
        "Roth",                   # N-11: the deferral split
        "safe harbor",            # H4: the prior-year AGI/total-tax rows
        "don't know",             # rule 1: never guess
    ):
        assert marker in text, f"worksheet lost its {marker!r} surface"


def test_intake_checklist_hands_over_the_worksheet_exactly_once() -> None:
    # The start state (nothing started) carries it; any started section drops it.
    assert intake_checklist().worksheet == intake_worksheet()
    started = Profile(identity=Identity())
    assert intake_checklist(started).worksheet is None


def test_p018_the_prior_year_question_maps_onto_the_five_return_forms() -> None:
    # JF5b part 1: each worksheet box answers into one PriorFilings.return_forms value
    # ('1040', '1040-NR', 'dual_status', '1040_with_6013_election', 'not_filed').
    en = next(line for line in intake_worksheet().splitlines() if line.startswith("- Last year (____) you filed:"))
    assert en.count("□") == 5
    for box in ("□ 1040 (as a resident", "□ 1040-NR (as a nonresident)", "□ dual-status",
                "□ joint 1040 with the §6013(g)/(h) election", "□ didn't file"):
        assert box in en
    zh = next(line for line in intake_worksheet("zh-CN").splitlines() if line.startswith("- 上一年（____ 年）报的是"))
    assert zh.count("□") == 5
    for box in ("□ 1040（全年按居民报）", "□ 1040-NR（按非居民报）", "□ 双重身份申报", "□ 与配偶按 §6013(g)/(h) 选择合报的 1040", "□ 没报"):
        assert box in zh
    assert "this year counts from January 1" in intake_worksheet()
    assert "今年从 1 月 1 日起就算居民" in intake_worksheet("zh-CN")
