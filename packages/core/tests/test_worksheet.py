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
