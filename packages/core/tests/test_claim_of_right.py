"""Phase J JP4 — calc op claim_of_right_repayment (pitfall P-025). Demo figures only."""
from __future__ import annotations

from taxfill_core.repayment import claim_of_right_repayment

EX40 = dict(repaid=5000, year=2025, prior_year=2024, taxable_income=49950, prior_taxable_income=15000)


def test_p025_pub_525_example_40_takes_the_deduction():
    # Pub 525 (2025) Example 40, with its printed taxes: "Your tax under method 1 is $5,156 ... Refigured tax for
    # 2025 ... $5,335" and "You pay less tax using method 1".
    r = claim_of_right_repayment(**EX40, tax_without_deduction=5903, tax_with_deduction=5156,
                                 prior_tax_as_filed=1571, prior_tax_refigured=1003)
    assert (r.method, r.tax_method_1, r.tax_method_2, r.credit) == ("deduction", 5156, 5335, 568)
    assert r.deduction_line == "16" and "Schedule A line 16" in r.work


def test_p025_the_tax_table_prices_the_same_example():
    # The 2024 figures are the 2024 Tax Table's ($1,571 / $1,003); the example's 2025 figures are not the 2025
    # table's ($5,909 / $5,159 for $49,950 / $44,950) — the op prices from the table unless overridden.
    r = claim_of_right_repayment(**EX40)
    assert (r.credit, r.tax_method_1, r.tax_method_2, r.method) == (568, 5159, 5341, "deduction")


def test_p025_three_thousand_or_less_takes_nothing():
    r = claim_of_right_repayment(**{**EX40, "repaid": 3000})
    assert r.method == "none" and r.tax_method_1 is None and "$3,000 or less" in r.work


def test_p025_the_credit_wins_when_last_years_rate_was_higher():
    # A demo repayment taxed at 32% last year, deducted at 12% this year: the credit is worth more.
    r = claim_of_right_repayment(10000, 2025, 2024, 40000, 200000)
    assert r.method == "credit" and r.tax_method_2 < r.tax_method_1
    assert r.credit_line == "13b" and "Schedule 3 line 13b" in r.work


def test_p025_business_income_and_the_payroll_taxes():
    biz = claim_of_right_repayment(**EX40, income_type="business")
    assert biz.method == "business_or_capital" and "Schedule C" in biz.work
    wages = claim_of_right_repayment(**EX40)
    assert any("Form 843" in n for n in wages.payroll_tax_notes)
    assert any("Form 1040-X for the prior year" in n for n in wages.payroll_tax_notes)


def test_p025_the_lines_are_read_per_year():
    lines = {y: claim_of_right_repayment(**{**EX40, "year": y, "prior_year": y - 1}).deduction_line
             for y in (2021, 2025, 2026)}
    assert lines[2021] == "16" and lines[2025] == "16" and lines[2026].startswith("17h")
    credit_lines = {y: claim_of_right_repayment(10000, y, y - 1, 40000, 200000).credit_line for y in (2020, 2022, 2024)}
    assert (credit_lines[2020], credit_lines[2022], credit_lines[2024]) == ("12d", "13d", "13b")
