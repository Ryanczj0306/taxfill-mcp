"""calc.state_tax's dependents refusal names only the dependent treatments that hold in the requested year.

A dependents_count passed for a state whose pack ships no per-dependent amount is refused with examples of how other
states handle dependents. Before 2026-10-16 the examples were one fixed string, ending "IL's unverified Schedule
IL-E/EIC amount" — true for 2023 only: the 2023 IL pack's note reads "Dependent exemptions (Line 10d, via Schedule
IL-E/EIC) are NOT shipped", while the 2024 and 2025 packs ship the amount the Schedule IL-E/EITC prints at Step 2,
Line 1 ("Multiply the total number of dependents you are claiming by $2,775." on the R-12/24 schedule; "$2,850." on
R-12/25), so an IL dependent is applied in those years, never refused. Each example is now named only for a year whose
pack for that state ships no 'dependent' amount and whose tax.notes say so (JK27).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.calc import state_tax
from taxfill_core.knowledge import load_state_knowledge

REPO = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO / "knowledge"
IL_EXAMPLE = "IL's unverified Schedule IL-E/EIC amount"


def _refusal(code: str, year: int) -> str:
    with pytest.raises(ValueError, match="dependents_count was supplied but the pack ships no 'dependent'") as err:
        state_tax(code, 50_000, year=year, dependents_count=1, knowledge_dir=KNOWLEDGE)
    return str(err.value)


def test_2023_refusal_keeps_all_three_examples():
    assert _refusal("az", 2023).endswith(
        "handle dependents per the pack's tax.notes (e.g. AZ's Line 49 dependent CREDIT, NC's AGI-tiered child "
        "deduction, IL's unverified Schedule IL-E/EIC amount)."
    )


@pytest.mark.parametrize("year", (2024, 2025))
def test_2024_and_2025_refusals_do_not_call_the_il_amount_unverified(year: int):
    for code in ("az", "co", "nc"):
        message = _refusal(code, year)
        assert IL_EXAMPLE not in message and "IL-E/EIC" not in message, (code, year)
        assert message.endswith(
            "handle dependents per the pack's tax.notes (e.g. AZ's Line 49 dependent CREDIT, NC's AGI-tiered child "
            "deduction)."
        ), (code, year)
    # ... because IL itself applies a dependent in those years (the Schedule IL-E/EITC Step 2 Line 1 amount).
    il = state_tax("il", 60_000, year=year, exemptions_count=1, dependents_count=1, knowledge_dir=KNOWLEDGE)
    amount = {2024: "$2,775", 2025: "$2,850"}[year]
    assert f"1 dependent exemption(s) x {amount} = {amount}.00" in il.work


@pytest.mark.parametrize("year", (2023, 2024, 2025))
def test_il_example_follows_the_il_pack_of_the_same_year(year: int):
    # Derived, not hard-coded: the IL example appears exactly when that year's IL pack ships no dependent amount.
    il_ships_dependent = "dependent" in load_state_knowledge("il", year, base_dir=KNOWLEDGE).tax.exemptions
    assert (IL_EXAMPLE in _refusal("az", year)) is (not il_ships_dependent)


def test_examples_are_omitted_when_their_packs_are_absent(tmp_path: Path):
    # A knowledge tree holding only the refusing state's pack names no other state's treatment.
    (tmp_path / "states" / "co").mkdir(parents=True)
    src = KNOWLEDGE / "states" / "co" / "2025.yaml"
    (tmp_path / "states" / "co" / "2025.yaml").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError) as err:
        state_tax("co", 50_000, year=2025, dependents_count=1, knowledge_dir=tmp_path)
    assert str(err.value).endswith("handle dependents per the pack's tax.notes.")
