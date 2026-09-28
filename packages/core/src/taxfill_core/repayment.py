"""Repaying income taxed in an earlier year: the claim-of-right rules (Phase J JP4, pitfall P-025).

IRC 1341(a): when "an item was included in gross income for a prior taxable year (or years) because it appeared
that the taxpayer had an unrestricted right to such item", a deduction is allowable this year because it was
established that the taxpayer did not have that right, and "the amount of such deduction exceeds $3,000", then
the tax "shall be the lesser of" (4) "the tax for the taxable year computed with such deduction" or (5) "the tax
for the taxable year computed without such deduction, minus ... the decrease in tax ... for the prior taxable year
... which would result solely from the exclusion of such item". Pub 525 (2025), Repayments, turns that into
Method 1 (the deduction) and Method 2 (the credit) and says "Use the method (deduction or credit) that results in
less tax"; at $3,000 or less a repaid wage "aren't able to deduct it" at all (no miscellaneous itemized
deductions after 2017). IRC 1341(b)(1) makes an excess credit a payment, which is why the credit sits in Schedule 3's
refundable section.

The payroll taxes are not this op's: prior-year wages keep their FICA on the prior year, and Pub 525 says to "ask
your employer to refund the excess amount" (Form 843 if refused), and that Additional Medicare Tax comes back only
through "Form 1040-X for the prior year".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.knowledge import form_line

IncomeType = Literal["wages", "unemployment", "other_nonbusiness", "business", "capital_gain"]
_PUB525 = "https://www.irs.gov/pub/irs-prior/p525--2025.pdf"


class ClaimOfRightResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    prior_year: int
    repaid: int
    method: Literal["none", "deduction", "credit", "business_or_capital"] = Field(
        description="What the filer takes: nothing (<= $3,000), the Method 1 deduction, the Method 2 credit, or the "
                    "repayment on the form the income was reported on (business / capital).")
    tax_method_1: int | None = Field(default=None, description="This year's tax with the deduction.")
    tax_method_2: int | None = Field(default=None, description="This year's tax without it, less the credit.")
    credit: int | None = Field(default=None, description="The decrease in the prior year's tax (Method 2 step 3).")
    deduction_line: str | None = None
    credit_line: str | None = None
    payroll_tax_notes: list[str]
    work: str
    citation: dict[str, str]


def _tax(taxable: int, status: str, year: int, knowledge_dir) -> int:
    from taxfill_core.calc import tax_from_taxable_income  # noqa: PLC0415

    return tax_from_taxable_income(max(0, taxable), status, year, knowledge_dir=knowledge_dir).tax


def claim_of_right_repayment(
    repaid: int | str,
    year: int,
    prior_year: int,
    taxable_income: int | str,
    prior_taxable_income: int | str,
    filing_status: str = "single",
    *,
    prior_filing_status: str | None = None,
    income_type: IncomeType = "wages",
    included_under_claim_of_right: bool = True,
    taxable_income_with_deduction: int | str | None = None,
    tax_without_deduction: int | str | None = None,
    tax_with_deduction: int | str | None = None,
    prior_tax_as_filed: int | str | None = None,
    prior_tax_refigured: int | str | None = None,
    knowledge_dir: str | Path | None = None,
) -> ClaimOfRightResult:
    """Deduction or credit for income repaid in ``year`` that was taxed in ``prior_year`` (Pub 525 Methods 1 and 2).

    Args:
        taxable_income: this year's taxable income WITHOUT the repayment deduction.
        prior_taxable_income: the prior year's taxable income as filed (WITH the repaid item).
        taxable_income_with_deduction: this year's taxable income with the deduction — default taxable_income less
            the repayment, which assumes the filer itemizes (the deduction is an other itemized deduction).
        tax_without_deduction / tax_with_deduction / prior_tax_as_filed / prior_tax_refigured: the four taxes, to
            override the ordinary Tax Table computation (qualified dividends, capital gains, credits).
    """
    def as_int(v: Any, what: str) -> int:
        try:
            return int(str(v).replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"{what} must be whole dollars, got {v!r}") from exc

    amount = as_int(repaid, "repaid")
    if amount <= 0:
        raise ValueError("repaid must be a positive amount")
    if prior_year >= year:
        raise ValueError(f"prior_year {prior_year} must be before the year of repayment {year}")
    ti = as_int(taxable_income, "taxable_income")
    prior_ti = as_int(prior_taxable_income, "prior_taxable_income")
    prior_status = prior_filing_status or filing_status
    fica = [
        "Social security and Medicare tax on the prior-year wages stays on that year: Pub 525 — \"ask your employer "
        "to refund the excess amount to you. If the employer refuses to refund the taxes, ask for a statement "
        "indicating the amount of the overcollection to support your claim. File a claim for refund using Form 843.\"",
        "Additional Medicare Tax is recovered only on the prior year's return: \"you must file Form 1040-X for the "
        "prior year in which the wages or compensation was originally received\" (Pub 525).",
    ]
    cite = {"source": "IRC 1341(a)-(b); Pub 525 (2025), Repayments, Methods 1 and 2", "url": _PUB525}
    base = dict(year=year, prior_year=prior_year, repaid=amount, citation=cite,
                payroll_tax_notes=fica if income_type == "wages" else [])
    if income_type in ("business", "capital_gain"):
        where = ("as a business expense on Schedule C or Schedule F" if income_type == "business"
                 else "as a capital loss as explained in the Instructions for Schedule D")
        return ClaimOfRightResult(method="business_or_capital", work=(
            f"Pub 525: \"In most cases, you deduct the repayment on the same form or schedule on which you previously "
            f"reported it as income\" — deduct the {amount:,} {where}. This op prices only the itemized deduction and "
            f"the IRC 1341 credit."), **base)
    if amount <= 3000:
        return ClaimOfRightResult(method="none", work=(
            f"{amount:,} repaid is $3,000 or less: \"For tax years beginning after 2017, you can no longer claim any "
            f"miscellaneous itemized deductions; so, if the amount repaid was $3,000 or less, you aren't able to "
            f"deduct it from your income in the year you repaid it\" (Pub 525), and IRC 1341(a)(3) requires the "
            f"deduction to exceed $3,000 — no deduction and no credit. \"Consider the total amount being repaid on the "
            f"return\", not each repayment separately."), **base)
    if not included_under_claim_of_right:
        return ClaimOfRightResult(method="none", work=(
            "IRC 1341(a)(1) applies only to an item included \"because it appeared that the taxpayer had an "
            "unrestricted right to such item\" — with that premise false, neither the deduction nor the credit "
            "applies under these rules; see Pub 525 for the other repayment cases."), **base)

    ti_with = as_int(taxable_income_with_deduction, "taxable_income_with_deduction") \
        if taxable_income_with_deduction is not None else ti - amount
    t_without = as_int(tax_without_deduction, "tax_without_deduction") if tax_without_deduction is not None \
        else _tax(ti, filing_status, year, knowledge_dir)
    t_with = as_int(tax_with_deduction, "tax_with_deduction") if tax_with_deduction is not None \
        else _tax(ti_with, filing_status, year, knowledge_dir)
    p_filed = as_int(prior_tax_as_filed, "prior_tax_as_filed") if prior_tax_as_filed is not None \
        else _tax(prior_ti, prior_status, prior_year, knowledge_dir)
    p_refig = as_int(prior_tax_refigured, "prior_tax_refigured") if prior_tax_refigured is not None \
        else _tax(prior_ti - amount, prior_status, prior_year, knowledge_dir)
    credit = p_filed - p_refig
    method_2 = t_without - credit
    use = "deduction" if t_with <= method_2 else "credit"
    ded_line = form_line(year, "scheda.claim_of_right", base_dir=knowledge_dir)
    cr_line = form_line(year, "sched3.section_1341_credit", base_dir=knowledge_dir)
    work = (
        f"Repaid {amount:,} in {year}, taxed in {prior_year} under a claim of right (IRC 1341(a)). Method 1: this "
        f"year's taxable income with the deduction {ti_with:,} -> tax {t_with:,}"
        + ("" if taxable_income_with_deduction is not None else
           " (taxable income less the repayment — the deduction is an other itemized deduction, so this assumes "
           "the filer itemizes)")
        + f". Method 2: tax without the deduction {t_without:,}, less the decrease in {prior_year} tax {p_filed:,} "
          f"- {p_refig:,} = {credit:,}, = {method_2:,}. Pub 525: \"Use the method (deduction or credit) that results in "
          f"less tax\" -> {'Method 1, the deduction' if use == 'deduction' else 'Method 2, the credit'}: "
        + (f"Schedule A line {ded_line}." if use == "deduction" else
           f"Schedule 3 line {cr_line} (a payment: IRC 1341(b)(1) treats a decrease above this year's tax as a "
           f"payment).")
    )
    return ClaimOfRightResult(method=use, tax_method_1=t_with, tax_method_2=method_2, credit=credit,
                              deduction_line=ded_line, credit_line=cr_line, work=work, **base)
