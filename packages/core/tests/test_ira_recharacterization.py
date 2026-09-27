"""Phase J JR2b: calc.ira_recharacterization — the fix for an ineligible IRA contribution (P-021).

The two worked cases are the Instructions for Form 8606 (2025) examples, figures and all; every other
figure is a hypothetical demo amount."""
from __future__ import annotations

from decimal import Decimal

import pytest

from taxfill_core.calc import ira_recharacterization

# i8606 (2025) Example 1: $4,000 to a new traditional IRA on May 27, 2025; on February 24, 2026, $3,000 of it
# (value $4,400) moves with $300 of related earnings to a Roth IRA; the remaining $1,000 is deducted.
_TRAD_EXAMPLE = dict(
    direction="traditional_to_roth", amount=3000, contributed_total=4000, contribution_year=2025,
    contribution_date="2025-05-27", transfer_date="2026-02-24", deducted=1000,
    opening_fmv=0, contributions_during=4000, closing_fmv=4400, magi=100_000, filing_status="single",
)
# i8606 (2025) Example 2: $4,000 to a new Roth IRA on June 17, 2025, moved whole ($4,200) on December 30, 2025,
# and deducted in full (single, covered by an employer plan, MAGI allows the full deduction).
_ROTH_EXAMPLE = dict(
    direction="roth_to_traditional", amount=4000, contribution_year=2025, contribution_date="2025-06-17",
    transfer_date="2025-12-30", contributions_during=4000, closing_fmv=4200, whole_account=True,
    magi=60_000, filing_status="single", covered_by_employer_plan=True,
)


# ── the refusals ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("source_kind", "message"), [
    ("conversion", "408A\\(d\\)\\(6\\)\\(B\\)\\(iii\\)"),
    ("rollover", "A-4"),
    ("sep", "A-5"),
    ("simple", "A-5"),
])
def test_p021_what_cannot_be_recharacterized_is_refused(source_kind, message):
    with pytest.raises(ValueError, match=message):
        ira_recharacterization(**{**_ROTH_EXAMPLE, "source_kind": source_kind})


def test_p021_a_deducted_amount_and_an_amount_above_the_contribution_are_refused():
    with pytest.raises(ValueError, match="408A\\(d\\)\\(6\\)\\(B\\)\\(ii\\)"):
        ira_recharacterization(**{**_TRAD_EXAMPLE, "deducted": 2000})       # $3,000 of $4,000 with $2,000 deducted
    with pytest.raises(ValueError, match="more than the"):
        ira_recharacterization(**{**_TRAD_EXAMPLE, "amount": 4500})
    with pytest.raises(ValueError, match="never deducted"):
        ira_recharacterization(**{**_ROTH_EXAMPLE, "deducted": 100})
    with pytest.raises(ValueError, match="not including extensions"):
        ira_recharacterization(**{**_ROTH_EXAMPLE, "contribution_date": "2026-05-01"})
    with pytest.raises(ValueError, match="before contribution_date"):
        ira_recharacterization(**{**_ROTH_EXAMPLE, "transfer_date": "2025-06-01"})


# ── the i8606 examples ───────────────────────────────────────────────────────


def test_p021_the_i8606_traditional_example_code_r_and_statement_only():
    r = ira_recharacterization(**_TRAD_EXAMPLE)
    assert r.net_income.net_income == Decimal("300.00") and r.total_to_transfer == Decimal("3300.00")
    assert r.deadline_status == "timely" and not r.amended_return_required
    assert (r.form_1099r_code, r.line_4a_reporting) == ("R", "statement_only")      # moved in 2026, for 2025
    assert r.form_8606["line_1_add"] == 0                                             # the moved part is Roth
    assert r.form_8606["line_6_adjustment"] == Decimal("-3300.00") and r.form_8606["line_6_adjustment_is_a_choice"]
    assert r.statement.endswith(
        "I contributed $4,000 to a traditional IRA on May 27, 2025; recharacterized $3,000 of that contribution on "
        "February 24, 2026, by transferring $3,000 plus $300 of related earnings from my traditional IRA to a Roth IRA "
        "in a trustee-to-trustee transfer; and deducted the remaining traditional IRA contribution of $1,000 on my "
        "2025 Form 1040.")
    assert "report it ONLY in the statement" in r.work and "code R in box 7a" in r.work
    assert r.target_check["roth_excess"] == 0


def test_p021_the_i8606_roth_example_code_n_and_line_4a():
    r = ira_recharacterization(**_ROTH_EXAMPLE)
    assert r.net_income.whole_account and r.total_to_transfer == Decimal("4200.00")
    assert (r.form_1099r_code, r.line_4a_reporting) == ("N", "line_4a")               # moved within 2025
    assert "include $4,200.00 on the 2025 Form 1040 line 4a" in r.work
    assert r.deduction["deductible"] == 4000 and r.form_8606["line_1_add"] == 0
    assert r.form_8606["line_6_adjustment"] == 0                                        # same-year: Dec 31 already has it
    assert "by transferring $4,200, the balance in the Roth IRA, to a traditional IRA" in r.statement
    assert "and deducted the traditional IRA contribution of $4,000 on my 2025 Form 1040." in r.statement


# ── the Form 8606 inputs ─────────────────────────────────────────────────────


def test_p021_net_income_is_never_basis_and_the_january_april_rule_sets_line_4():
    base = dict(direction="roth_to_traditional", amount=6000, contribution_year=2025, transfer_date="2026-03-20",
                contributions_during=6000, closing_fmv=6450, elect_nondeductible=True)
    late_contrib = ira_recharacterization(**base, contribution_date="2026-02-10")      # for 2025, made in 2026
    assert late_contrib.net_income.net_income == Decimal("450.00")
    assert late_contrib.form_8606["line_1_add"] == Decimal("6000.00")                  # not 6,450: A-3
    assert late_contrib.form_8606["line_4_add"] == Decimal("6000.00")
    in_year = ira_recharacterization(**base, contribution_date="2025-09-02")
    assert in_year.form_8606["line_1_add"] == Decimal("6000.00") and in_year.form_8606["line_4_add"] == 0
    assert "408(o)(2)(B)(ii)" in in_year.deduction["work"]
    with pytest.raises(ValueError, match="elect_nondeductible"):
        ira_recharacterization(**{**base, "elect_nondeductible": False}, contribution_date="2025-09-02")


# ── the deadline ─────────────────────────────────────────────────────────────


def test_p021_the_deadline_status_after_the_due_date():
    after_due = {**_TRAD_EXAMPLE, "transfer_date": "2026-08-03"}
    with pytest.raises(ValueError, match="extension_filed"):
        ira_recharacterization(**after_due)
    assert ira_recharacterization(**after_due, extension_filed=True).deadline_status == "timely"
    late = ira_recharacterization(**after_due, extension_filed=False, return_filed_date="2026-04-01")
    assert late.deadline_status == "late_301_9100_2" and late.amended_return_required
    assert late.statement.startswith("Filed pursuant to section 301.9100-2")
    assert ira_recharacterization(**after_due, extension_filed=False, return_filed_date="2026-05-01").deadline_status \
        == "too_late"
    gone = ira_recharacterization(**{**_TRAD_EXAMPLE, "transfer_date": "2026-11-02"})
    assert gone.deadline_status == "too_late" and gone.statement is None and gone.form_1099r_code is None
    assert not gone.alternatives["return_408d4"]["available"]
    assert any("including extensions" in c for c in late.choices)
    planning = ira_recharacterization(**{**_TRAD_EXAMPLE, "transfer_date": None})
    assert planning.deadline_status == "open" and "code N" in planning.work and "code R" in planning.work


# ── the second IRA's side ────────────────────────────────────────────────────


def test_p021_the_target_side_limit_check():
    over = ira_recharacterization(**{**_ROTH_EXAMPLE, "other_traditional_contributions": 5000})
    assert over.target_check["combined_excess_after"] == Decimal("2000.00")            # 9,000 against 7,000 (2025)
    assert "recharacterization cannot cure" in over.work
    ineligible = ira_recharacterization(**{**_TRAD_EXAMPLE, "magi": 170_000})          # above the 2025 Roth range
    assert ineligible.target_check["roth_excess"] == 3000 and "EXCESS Roth contribution" in ineligible.work
    with pytest.raises(ValueError, match="needs magi"):
        ira_recharacterization(**{**_TRAD_EXAMPLE, "magi": None})


# ── alternatives, documents, then_convert ───────────────────────────────────


def test_p021_the_408d4_alternative_owes_no_additional_tax():
    r = ira_recharacterization(**{**_ROTH_EXAMPLE, "magi": 200_000, "covered_by_employer_plan": False})
    ret = r.alternatives["return_408d4"]
    assert ret["available"] and ret["additional_tax"] == 0 and ret["earnings_taxable"] == Decimal("200.00")
    assert "72(t)(2)(A)(ix)" in ret["why_no_additional_tax"] and "exception 21" in ret["why_no_additional_tax"]
    assert "generally subject to the additional 10% tax" in ret["why_no_additional_tax"]   # quoted, then overruled
    assert ret["earnings_line"] == "2025 Form 1040 line 4b"
    stay = r.alternatives["leave_in_place"]
    assert stay["roth_excess"] == 4000 and stay["excise_per_year"] == 240                  # 6% of 4,000


def test_p021_documents_reconcile_to_the_dollar():
    readings = [{"form": "1099-R", "box": "1", "amount": "4200.40"}, {"form": "5498", "box": "4", "amount": 4199},
                {"form": "5498", "box": "10", "amount": 4000}, {"form": "1099-R", "box": "2a", "amount": 4200}]
    r = ira_recharacterization(**_ROTH_EXAMPLE, readings=readings)
    ok = {(x["form"], x["box"]): x["ok"] for x in r.reconciliation}
    assert ok == {("1099-R", "1"): True, ("5498", "4"): True, ("5498", "10"): True, ("1099-R", "2a"): False}
    assert "RECONCILIATION" in r.work
    assert len(r.trustee_notification) == 5 and "cannot be revoked after the transfer" in r.trustee_notification[0]
    with pytest.raises(ValueError, match="not an expected box"):
        ira_recharacterization(**_ROTH_EXAMPLE, readings=[{"form": "1099-R", "box": "4", "amount": 1}])


def test_p021_then_convert_embeds_roth_conversion_with_the_line_1_basis():
    base = dict(direction="roth_to_traditional", amount=7000, contribution_year=2025, contribution_date="2025-07-01",
                transfer_date="2025-11-03", contributions_during=7000, closing_fmv=7100, elect_nondeductible=True)
    convert = {"date": "2025-11-10", "amount": 7100, "taxable_income_before": 150_000, "magi_before": 180_000,
               "dec31_total_value": 0}
    r = ira_recharacterization(**base, then_convert=convert)
    assert r.then_convert is not None
    assert r.then_convert.nontaxable_amount == 7000 and r.then_convert.taxable_amount == 100   # basis 7,000 of 7,100
    with pytest.raises(ValueError, match="on or after transfer_date"):
        ira_recharacterization(**base, then_convert={**convert, "date": "2025-10-01"})
    with pytest.raises(ValueError, match="roth_to_traditional"):
        ira_recharacterization(**_TRAD_EXAMPLE, then_convert=convert)
