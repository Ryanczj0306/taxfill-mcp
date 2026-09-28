"""Phase J JR2a: the net income attributable, the return statements, and the due-date fallback.
Hypothetical demo figures, and the regulations' and instructions' own examples."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from taxfill_core.calc import _return_due_date, ira_net_income_attributable
from taxfill_core.knowledge import form_line
from taxfill_core.statements import ira_line_4b_statement, recharacterization_statement, returned_contribution_statement


def test_jr2a_the_net_income_reproduces_the_regulation_examples():
    # Treas. Reg. 1.408-11 Example 1: $75 on $400 ($400 x ($7,600 - $6,400) / $6,400).
    ex1 = ira_net_income_attributable(400, "returned_contribution", opening_fmv=4_800, contributions_during=1_600,
                                      closing_fmv=7_600)
    assert ex1.net_income == Decimal("75.00") and ex1.total_to_move == Decimal("475.00")
    # Example 2 prints $187; the exact division is $186.89 — the test documents the difference.
    ex2 = ira_net_income_attributable(600, "returned_contribution", opening_fmv=11_000, contributions_during=1_200,
                                      closing_fmv=16_000)
    assert ex2.net_income == Decimal("186.89") and ex2.net_income_three_place == Decimal("186.60")
    assert ex2.three_place_difference == Decimal("-0.29")
    # Treas. Reg. 1.408A-5 A-2(c) Example 1: -$10,000 ($160,000 x ($225,000 - $240,000) / $240,000).
    loss = ira_net_income_attributable(160_000, "recharacterization", opening_fmv=80_000, contributions_during=160_000,
                                       closing_fmv=225_000)
    assert loss.net_income == Decimal("-10000.00") and "LOSS" in loss.work
    # Example 2: $5,000 on $50,000 and $4,000 on $40,000 of a $100,000 conversion worth $110,000.
    for amount, nia in ((50_000, "5000.00"), (40_000, "4000.00")):
        r = ira_net_income_attributable(amount, "recharacterization", opening_fmv=0, contributions_during=100_000,
                                        closing_fmv=110_000)
        assert r.net_income == Decimal(nia)
    whole = ira_net_income_attributable(4_000, "recharacterization", closing_fmv=4_200, whole_account=True)
    assert whole.net_income == Decimal("200.00") and whole.whole_account


_I8606_EX1 = ("you contributed $4,000 to a traditional IRA on May 27, 2025; recharacterized $3,000 of that contribution "
              "on February 24, 2026, by transferring $3,000 plus $300 of related earnings from your traditional IRA to a "
              "Roth IRA in a trustee-to-trustee transfer; and deducted the remaining traditional IRA contribution of "
              "$1,000 on your 2025 Form 1040.")
_I8606_EX2 = ("you contributed $4,000 to a new Roth IRA on June 17, 2025; recharacterized that contribution on December "
              "30, 2025, by transferring $4,200, the balance in the Roth IRA, to a traditional IRA in a trustee-to-trustee "
              "transfer; and deducted the traditional IRA contribution of $4,000 on your 2025 Form 1040.")


def _first_person(s: str) -> str:
    return "I" + s[3:].replace(" your ", " my ")


def test_jr2a_the_statements_reproduce_the_i8606_examples():
    one = recharacterization_statement(
        tax_year=2025, contributed=4_000, first_ira="traditional", contribution_date="2025-05-27", recharacterized=3_000,
        second_ira="Roth", recharacterization_date="2026-02-24", earnings=300, deducted=1_000)
    assert one.splitlines()[-1] == _first_person(_I8606_EX1)
    assert one.splitlines()[0] == "[NAME]  [SSN]"                       # no identity in calc output
    two = recharacterization_statement(
        tax_year=2025, contributed=4_000, first_ira="Roth", new_first_ira=True, contribution_date="2025-06-17",
        recharacterized=4_000, second_ira="traditional", recharacterization_date="2025-12-30", transferred_balance=4_200,
        deducted=4_000)
    assert two.splitlines()[-1] == _first_person(_I8606_EX2)
    assert form_line(2025, "f1040.ira_distributions") == "4a"           # where the $4,200 is reported that year


def test_jr2a_a_late_statement_carries_the_301_9100_2_header():
    late = recharacterization_statement(
        tax_year=2025, contributed=4_000, first_ira="Roth", contribution_date="2025-06-17", recharacterized=4_000,
        second_ira="traditional", recharacterization_date="2026-09-30", earnings=-150, late=True,
        conversion_note="No conversion is involved.")
    assert late.splitlines()[0] == "Filed pursuant to section 301.9100-2"
    assert "less $150 of related loss" in late and late.splitlines()[-1].startswith("(Optional)")
    returned = returned_contribution_statement(
        tax_year=2025, contributed=4_000, ira="traditional", contribution_date="2025-05-27", returned=1_000,
        earnings=73, return_date="2025-12-30", deducted=3_000)
    assert "$1,073 withdrawn ($1,000 contribution plus $73 of earnings)" in returned
    assert ira_line_4b_statement(2025, {"Rollover": 1_000, "HFD": 500}) == "Line 4b – $1,000 Rollover and $500 HFD."


def test_jr2a_the_due_date_comes_from_the_pack_or_a_labeled_fallback(planning_year, synthetic_provisional_pack):
    due, extended, source, assumed = _return_due_date(2025)
    assert (due, extended, assumed) == (date(2026, 4, 15), date(2026, 10, 15), False)
    # JT0b: the fallback on a pack whose deadlines block is stripped, whatever the planning pack ships.
    due, extended, source, assumed = _return_due_date(planning_year, synthetic_provisional_pack(["deadlines"]))
    assert (due, extended, assumed) == (date(planning_year + 1, 4, 15), date(planning_year + 1, 10, 15), True)
    assert "ASSUMED" in source
    due26, _, _, assumed26 = _return_due_date(2026)                    # JT2b: 2026 records it (a Thursday)
    assert (due26, assumed26) == (date(2027, 4, 15), False) and due26.weekday() == 3
    # IRC 7503 with DC Emancipation Day: April 15, 2022 was a Friday and April 16 a Saturday observed that Friday.
    from taxfill_core.calc import _roll_7503  # noqa: PLC0415
    assert _roll_7503(date(2022, 4, 15)) == date(2022, 4, 18)
    assert _roll_7503(date(2023, 4, 15)) == date(2023, 4, 18)          # Saturday; Monday the 17th observed the 16th
    assert _return_due_date(2026, override="2027-05-17")[0] == date(2027, 5, 17)
