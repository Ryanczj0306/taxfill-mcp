"""Document extraction — dev plan section 2 ("extract & confirm"), section 8 tool.

The agent reads a tax document (W-2, 1099, 1098-T, 1042-S, …) with its own vision
and passes the box→value reading here. This module does NOT do OCR; it is the
*structuring + validation* half of "extract & confirm":

* it knows the official box layout of each supported document (cited to the form
  on irs.gov), so it can label, type-check, and order the agent's reading;
* it attaches per-field **provenance** (the source file + page) to every value;
* it never invents a value — a box the agent did not read stays ``None`` and is
  reported as a gap; a value that fails its type is surfaced as ``invalid``, not
  silently dropped;
* it returns a confirm-table the user reviews before any figure is used.

The hard rule from section 2 is preserved end to end: *missing means blank, never
guessed.* The box layouts encoded here are the documented structure of the
official forms (not dollar amounts) and each spec cites its irs.gov form page.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.schemas.profile import Provenance

__all__ = [
    "FieldType",
    "BoxSpec",
    "DocSpec",
    "DOC_SPECS",
    "ExtractedField",
    "ExtractedDocument",
    "list_document_kinds",
    "extract_document",
]

FieldType = Literal["money", "int", "text", "code", "ein", "ssn", "tin", "state", "checkbox"]


class BoxSpec(BaseModel):
    """One documented box on an official form."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Stable box identifier, e.g. '1' or '12a' or 'employee_ssn'.")
    label: str = Field(description="Human label as printed on the form.")
    type: FieldType = "text"
    required: bool = Field(default=False, description="True for the boxes a return almost always needs from this doc.")


class DocSpec(BaseModel):
    """A supported document type: its title, its citation, and its box layout."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    title: str
    source_url: str = Field(description="Official .gov page documenting this form's layout.")
    boxes: list[BoxSpec]
    status_note: str | None = Field(
        default=None,
        description=(
            "A trap the RECIPIENT'S STATUS springs on this document — appended to every "
            "extraction's caveat, because the box values alone cannot carry it."
        ),
    )


def _b(key: str, label: str, type_: FieldType = "text", required: bool = False) -> BoxSpec:
    return BoxSpec(key=key, label=label, type=type_, required=required)


# ── Supported documents (box layout cited to the official irs.gov form page) ──
# Only the broadly-needed boxes are modelled; the agent may still pass others
# (they surface under `unexpected`), and more docs can be added the same way.
_SPECS: list[DocSpec] = [
    DocSpec(
        kind="W-2",
        title="Wage and Tax Statement",
        source_url="https://www.irs.gov/forms-pubs/about-form-w-2",
        boxes=[
            _b("employee_ssn", "Box a — Employee's SSN", "ssn", required=True),
            _b("employer_ein", "Box b — Employer EIN", "ein", required=True),
            _b("employer_name", "Box c — Employer name/address", "text"),
            _b("employee_name", "Box e — Employee name", "text"),
            _b("1", "Box 1 — Wages, tips, other compensation", "money", required=True),
            _b("2", "Box 2 — Federal income tax withheld", "money", required=True),
            _b("3", "Box 3 — Social Security wages", "money"),
            _b("4", "Box 4 — Social Security tax withheld", "money"),
            _b("5", "Box 5 — Medicare wages and tips", "money"),
            _b("6", "Box 6 — Medicare tax withheld", "money"),
            _b("7", "Box 7 — Social Security tips", "money"),
            _b("10", "Box 10 — Dependent care benefits", "money"),
            _b("11", "Box 11 — Nonqualified plans", "money"),
            _b("12a", "Box 12a — Code/amount", "code"),
            _b("12b", "Box 12b — Code/amount", "code"),
            _b("12c", "Box 12c — Code/amount", "code"),
            _b("12d", "Box 12d — Code/amount", "code"),
            _b("13_statutory", "Box 13 — Statutory employee", "checkbox"),
            _b("13_retirement", "Box 13 — Retirement plan", "checkbox"),
            _b("13_sick_pay", "Box 13 — Third-party sick pay", "checkbox"),
            _b("15_state", "Box 15 — State", "state"),
            _b("16", "Box 16 — State wages, tips, etc.", "money"),
            _b("17", "Box 17 — State income tax", "money"),
            _b("18", "Box 18 — Local wages, tips, etc.", "money"),
            _b("19", "Box 19 — Local income tax", "money"),
            _b("20", "Box 20 — Locality name", "text"),
        ],
    ),
    DocSpec(
        kind="1099-NEC",
        title="Nonemployee Compensation",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-nec",
        boxes=[
            _b("payer_tin", "Payer's TIN", "tin"),
            _b("recipient_tin", "Recipient's TIN", "tin", required=True),
            _b("payer_name", "Payer's name/address", "text"),
            _b("1", "Box 1 — Nonemployee compensation", "money", required=True),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("5", "Box 5 — State tax withheld", "money"),
            _b("6", "Box 6 — State/Payer's state no.", "text"),
            _b("7", "Box 7 — State income", "money"),
        ],
    ),
    DocSpec(
        kind="1099-INT",
        title="Interest Income",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-int",
        # N-8: the bank sends this form regardless of the payee's status, but
        # whether box 1 is INCOME AT ALL depends on that status.
        status_note=(
            "STATUS decides whether box 1 is income: US bank-deposit interest paid to a NONRESIDENT "
            "alien is generally NOT taxable (the deposit-interest exclusion, IRC 871(i)(2)(A)) and does "
            "not go on Form 1040-NR — and it BECOMES taxable the moment a §6013(g)/(h) election makes "
            "the payee a resident (the election, not the marriage, ends the exclusion). Confirm the "
            "payee's residency result before carrying box 1 to any return."
        ),
        boxes=[
            _b("payer_name", "Payer's name", "text"),
            _b("recipient_tin", "Recipient's TIN", "tin"),
            _b("1", "Box 1 — Interest income", "money", required=True),
            _b("2", "Box 2 — Early withdrawal penalty", "money"),
            _b("3", "Box 3 — Interest on U.S. Savings Bonds and Treasury obligations", "money"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("8", "Box 8 — Tax-exempt interest", "money"),
        ],
    ),
    DocSpec(
        kind="1099-DIV",
        title="Dividends and Distributions",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-div",
        boxes=[
            _b("payer_name", "Payer's name", "text"),
            _b("recipient_tin", "Recipient's TIN", "tin"),
            _b("1a", "Box 1a — Total ordinary dividends", "money", required=True),
            _b("1b", "Box 1b — Qualified dividends", "money"),
            _b("2a", "Box 2a — Total capital gain distr.", "money"),
            _b("3", "Box 3 — Nondividend distributions", "money"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("7", "Box 7 — Foreign tax paid", "money"),
        ],
    ),
    DocSpec(
        kind="1099-G",
        title="Certain Government Payments",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-g",
        boxes=[
            _b("payer_name", "Payer's name", "text"),
            _b("1", "Box 1 — Unemployment compensation", "money"),
            _b("2", "Box 2 — State or local income tax refunds/credits/offsets", "money"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("11", "Box 11 — State income tax withheld", "money"),
        ],
    ),
    DocSpec(
        kind="1099-MISC",
        title="Miscellaneous Information",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-misc",
        boxes=[
            _b("payer_name", "Payer's name", "text"),
            _b("recipient_tin", "Recipient's TIN", "tin"),
            _b("1", "Box 1 — Rents", "money"),
            _b("2", "Box 2 — Royalties", "money"),
            _b("3", "Box 3 — Other income", "money"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
        ],
    ),
    DocSpec(
        kind="1098-T",
        title="Tuition Statement",
        source_url="https://www.irs.gov/forms-pubs/about-form-1098-t",
        boxes=[
            _b("filer_name", "Filer's name (school)", "text"),
            _b("student_tin", "Student's TIN", "tin"),
            _b("1", "Box 1 — Payments received for qualified tuition and related expenses", "money", required=True),
            _b("4", "Box 4 — Adjustments made for a prior year", "money"),
            _b("5", "Box 5 — Scholarships or grants", "money"),
            _b("7", "Box 7 — Checkbox: amounts for an academic period beginning Jan–Mar next year", "checkbox"),
        ],
    ),
    DocSpec(
        kind="1098-E",
        title="Student Loan Interest Statement",
        source_url="https://www.irs.gov/forms-pubs/about-form-1098-e",
        boxes=[
            _b("lender_name", "Lender's name", "text"),
            _b("borrower_tin", "Borrower's TIN", "tin"),
            _b("1", "Box 1 — Student loan interest received by lender", "money", required=True),
        ],
    ),
    DocSpec(
        # NRA-critical: how treaty-exempt income and its withholding are reported.
        kind="1042-S",
        title="Foreign Person's U.S. Source Income Subject to Withholding",
        source_url="https://www.irs.gov/forms-pubs/about-form-1042-s",
        boxes=[
            _b("1", "Box 1 — Income code", "code", required=True),
            _b("2", "Box 2 — Gross income", "money", required=True),
            _b("3a", "Box 3a — Exemption code (chapter 3)", "code"),
            _b("3b", "Box 3b — Tax rate (chapter 3)", "text"),
            _b("4a", "Box 4a — Exemption code (chapter 4)", "code"),
            _b("7a", "Box 7a — Federal tax withheld", "money"),
            _b("12a", "Box 12a — Withholding agent's EIN", "ein"),
            _b("13b", "Box 13b — Recipient's U.S. TIN", "tin"),
            _b("13l", "Box 13l — Recipient's country code", "text"),
        ],
    ),
    DocSpec(
        kind="SSA-1099",
        title="Social Security Benefit Statement",
        source_url="https://www.ssa.gov/manage-benefits/get-tax-form-10991042s",
        boxes=[
            _b("2", "Box 2 — Beneficiary's Social Security number", "ssn", required=True),
            _b("3", "Box 3 — Benefits paid in the year", "money"),
            _b("4", "Box 4 — Benefits repaid to SSA in the year", "money"),
            _b("5", "Box 5 — Net benefits (box 3 minus box 4)", "money", required=True),
            _b("6", "Box 6 — Voluntary federal income tax withheld", "money"),
        ],
    ),
    DocSpec(
        kind="1099-R",
        title="Distributions From Pensions, Annuities, Retirement or Profit-Sharing Plans, IRAs, etc.",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-r",
        boxes=[
            _b("payer_tin", "Payer's TIN", "tin"),
            _b("recipient_tin", "Recipient's TIN", "tin", required=True),
            _b("1", "Box 1 — Gross distribution", "money", required=True),
            _b("2a", "Box 2a — Taxable amount", "money"),
            _b("2b_not_determined", "Box 2b — Taxable amount not determined", "checkbox"),
            _b("2b_total_distribution", "Box 2b — Total distribution", "checkbox"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("7", "Box 7 — Distribution code(s)", "code", required=True),
            _b("7_ira_sep_simple", "Box 7 — IRA/SEP/SIMPLE", "checkbox"),
        ],
    ),
    DocSpec(
        kind="1099-B",
        title="Proceeds From Broker and Barter Exchange Transactions",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-b",
        boxes=[
            _b("payer_tin", "Payer's TIN", "tin"),
            _b("recipient_tin", "Recipient's TIN", "tin", required=True),
            _b("1a", "Box 1a — Description of property", "text"),
            _b("1b", "Box 1b — Date acquired", "text"),
            _b("1c", "Box 1c — Date sold or disposed", "text"),
            _b("1d", "Box 1d — Proceeds", "money", required=True),
            _b("1e", "Box 1e — Cost or other basis", "money"),
            _b("1g", "Box 1g — Wash sale loss disallowed", "money"),
            _b("2_short_term", "Box 2 — Short-term gain or loss", "checkbox"),
            _b("2_long_term", "Box 2 — Long-term gain or loss", "checkbox"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("5", "Box 5 — Noncovered security", "checkbox"),
        ],
    ),
    DocSpec(
        # Phase I2. The two documents an HSA filing cannot be built without —
        # box layout transcribed from the real forms, read 2026-08-26:
        # f1099sa.pdf (Rev. April 2025) and f5498sa.pdf (Rev. December 2026).
        kind="1099-SA",
        title="Distributions From an HSA, Archer MSA, or Medicare Advantage MSA",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-sa",
        status_note=(
            "Box 1 is the Form 8889 LINE 14a figure, not taxable income: the trustee does not compute "
            "the taxable amount ('The payer isn't required to compute the taxable amount of any "
            "distribution'), so a distribution spent on qualified medical expenses is fully excluded "
            "while the same box 1 spent otherwise is income PLUS a 20% additional tax (IRC 223(f)(4)). "
            "Run calc op hsa_deduction with distributions_total / distributions_rolled_over / "
            "qualified_medical_expenses to split it. Receiving ANY distribution forces Form 8889 to be "
            "filed even when nothing is taxable. Box 3's code changes the reading: 1 normal, 2 excess "
            "contributions, 3 disability, 4 death (other than code 6), 5 prohibited transaction, 6 "
            "death distribution after the year of death to a nonspouse beneficiary. Box 2 earnings on "
            "a withdrawn excess are INCLUDED in box 1 and are 'Other income' in the year received even "
            "if spent on qualified care. Box 4 (FMV on the date of death) belongs to an inherited "
            "account: a NONSPOUSE beneficiary reports that FMV as income for the year the owner died."
        ),
        boxes=[
            _b("payer_tin", "PAYER'S TIN", "tin"),
            _b("recipient_tin", "RECIPIENT'S TIN", "tin", required=True),
            _b("payer_name", "TRUSTEE'S/PAYER'S name and address", "text"),
            _b("1", "Box 1 — Gross distribution", "money", required=True),
            _b("2", "Box 2 — Earnings on excess cont.", "money"),
            _b("3", "Box 3 — Distribution code", "code", required=True),
            _b("4", "Box 4 — FMV on date of death", "money"),
            _b("5_hsa", "Box 5 — HSA (account type checkbox)", "checkbox"),
            _b("5_archer_msa", "Box 5 — Archer MSA (account type checkbox)", "checkbox"),
            _b("5_ma_msa", "Box 5 — MA MSA (account type checkbox)", "checkbox"),
        ],
    ),
    DocSpec(
        kind="5498-SA",
        title="HSA, Archer MSA, or Medicare Advantage MSA Information",
        source_url="https://www.irs.gov/forms-pubs/about-form-5498-sa",
        status_note=(
            "BOX NUMBERS HERE ARE NOT WHAT THEY LOOK LIKE — read them off the paper. Box 1 is ARCHER "
            "MSA contributions only (Form 8853, not Form 8889); the HSA figure is BOX 2, 'Total "
            "contributions made in the calendar year', and box 2 sweeps in EVERYTHING: your own direct "
            "contributions, your employer's, your cafeteria-plan payroll deferrals, and qualified HSA "
            "funding distributions from an IRA. Form 8889 line 2 is box 2 MINUS the W-2 box 12 code W "
            "amount MINUS any funding distribution — putting box 2 straight on line 2 double-counts the "
            "payroll money and overstates the deduction. Box 3 runs FORWARD, not back: it is "
            "contributions made in the SUBSEQUENT year FOR this form's calendar year (the Jan 1-Apr 15 "
            "catch-up window), so this year's form cannot show a prior year's late contribution. Box 4 "
            "rollovers are NOT in boxes 1, 2 or 3 and are neither income nor deductible. Box 5 is the "
            "year-end fair market value — the figure the IRC 4973(a) cap on the 6% excess-contribution "
            "excise is measured against. The form is informational: 'Don't attach Form 5498-SA to your "
            "income tax return.'"
        ),
        boxes=[
            _b("trustee_tin", "TRUSTEE'S TIN", "tin"),
            _b("participant_tin", "PARTICIPANT'S TIN", "tin", required=True),
            _b("trustee_name", "TRUSTEE'S name and address", "text"),
            _b("1", "Box 1 — Employee's or self-employed person's Archer MSA contributions made in the calendar year and the subsequent year for the calendar year", "money"),
            _b("2", "Box 2 — Total contributions made in the calendar year", "money", required=True),
            _b("3", "Box 3 — Total HSA or Archer MSA contributions made in the subsequent year for the calendar year", "money"),
            _b("4", "Box 4 — Rollover contributions", "money"),
            _b("5", "Box 5 — Fair market value of HSA, Archer MSA, or MA MSA", "money"),
            _b("6_hsa", "Box 6 — HSA (account type checkbox)", "checkbox"),
            _b("6_archer_msa", "Box 6 — Archer MSA (account type checkbox)", "checkbox"),
            _b("6_ma_msa", "Box 6 — MA MSA (account type checkbox)", "checkbox"),
        ],
    ),
    DocSpec(
        # Phase I3. The two equity-compensation documents, box layout transcribed
        # from the real forms read 2026-08-26: f3922.pdf (Rev. April 2025) and
        # f3921.pdf (Rev. April 2025), plus their Instructions for Employee.
        kind="3922",
        title="Transfer of Stock Acquired Through an Employee Stock Purchase Plan Under Section 423(c)",
        source_url="https://www.irs.gov/forms-pubs/about-form-3922",
        status_note=(
            "NOTHING ON THIS FORM IS INCOME, AND NONE OF IT IS ON YOUR W-2 YET. 'No income is recognized "
            "when you exercise an option under an employee stock purchase plan' — the form exists so you "
            "can compute the SALE. Run calc op espp_disposition with box 1 (grant date), box 2 (exercise "
            "date), box 3 (grant-date FMV), box 4 (exercise-date FMV), box 5 (price paid), box 6 (shares) "
            "and box 8, plus the 1099-B sale date, price and box 1e. BOX 8 IS THE ONE PEOPLE MISS: it is "
            "the 'exercise price per share determined as if the option was exercised on the date shown in "
            "box 1', and it is filled in ONLY when the price was not fixed or determinable at grant, i.e. "
            "when the plan has a LOOKBACK. On a QUALIFYING disposition IRC 423(c)(2) measures the ordinary "
            "income against box 3 minus box 8, not box 3 minus box 5 — a different and usually larger "
            "number whenever the stock fell between grant and purchase. BOX 7 IS NOT THE SALE DATE: it is "
            "the date legal title was first transferred, which is what triggered this form; take the sale "
            "date from Form 1099-B box 1c. And the form's own reason for existing is a warning — the "
            "employer reports the discount here because the BROKER will not: the 1099-B basis is box 5 "
            "only, so filing it unadjusted taxes the discount twice."
        ),
        boxes=[
            _b("corporation_ein", "CORPORATION'S federal identification number", "ein"),
            _b("employee_tin", "EMPLOYEE'S identification number", "tin", required=True),
            _b("corporation_name", "CORPORATION'S name and address", "text"),
            _b("employee_name", "EMPLOYEE'S name", "text"),
            _b("account_number", "Account number (see instructions)", "text"),
            _b("1", "Box 1 — Date option granted", "text", required=True),
            _b("2", "Box 2 — Date option exercised", "text", required=True),
            _b("3", "Box 3 — Fair market value per share on grant date", "money", required=True),
            _b("4", "Box 4 — Fair market value per share on exercise date", "money", required=True),
            _b("5", "Box 5 — Exercise price paid per share", "money", required=True),
            # "money" rather than "int": an ESPP buys shares out of whole payroll
            # dollars, so box 6 is routinely fractional (Pub 525 Example 9 divides
            # $240 of deductions by a $20 price). "int" would reject that as a misread.
            _b("6", "Box 6 — No. of shares transferred", "money", required=True),
            _b("7", "Box 7 — Date legal title transferred", "text"),
            _b("8", "Box 8 — Exercise price per share determined as if the option was exercised on the date shown in box 1", "money"),
        ],
    ),
    DocSpec(
        kind="3921",
        title="Exercise of an Incentive Stock Option Under Section 422(b)",
        source_url="https://www.irs.gov/forms-pubs/about-form-3921",
        status_note=(
            "AN ISO IS NOT AN ESPP AND THE FORMULAS DO NOT TRANSFER. There is no built-in discount here — "
            "IRC 422(b)(4) requires the option price to be 'not less than the fair market value of the "
            "stock at the time such option is granted' — so box 3 vs box 4 is pure appreciation, not a "
            "bargain element. Two consequences the box values cannot carry. (1) AMT: 'When you exercise an "
            "ISO, you may have to include in alternative minimum taxable income a portion of the fair "
            "market value of the stock acquired through the exercise of the option' — (box 4 - box 3) x "
            "box 5 is a Form 6251 line 2i adjustment in the EXERCISE year even though nothing is on your "
            "W-2 and nothing was withheld, and your AMT basis then differs from your regular-tax basis "
            "forever after. No adjustment is required if you dispose of the stock in the same year you "
            "exercise (Pub 525). (2) On a disqualifying disposition the ordinary income is box 4 minus box "
            "3, but IRC 422(c)(2) CAPS it at the gain actually realised on a sale — a cap section 423 has "
            "no counterpart for, which is why calc op espp_disposition refuses to model ISOs. The regular "
            "tax basis is box 3 x box 5 plus any ordinary income recognised, and the 1099-B will report "
            "box 3 x box 5 alone."
        ),
        boxes=[
            _b("transferor_tin", "TRANSFEROR'S TIN", "tin"),
            _b("employee_tin", "EMPLOYEE'S TIN", "tin", required=True),
            _b("transferor_name", "TRANSFEROR'S name and address", "text"),
            _b("employee_name", "EMPLOYEE'S name", "text"),
            _b("account_number", "Account number (see instructions)", "text"),
            _b("1", "Box 1 — Date option granted", "text", required=True),
            _b("2", "Box 2 — Date option exercised", "text", required=True),
            _b("3", "Box 3 — Exercise price per share", "money", required=True),
            _b("4", "Box 4 — Fair market value per share on exercise date", "money", required=True),
            # "int" here, unlike Form 3922 box 6: an ISO is exercised for whole
            # shares, so a fractional reading is a misread worth surfacing.
            _b("5", "Box 5 — No. of shares transferred", "int", required=True),
            _b("6", "Box 6 — If other than TRANSFEROR, name, address, and TIN of corporation whose stock is being transferred", "text"),
        ],
    ),
    DocSpec(
        kind="1095-A",
        title="Health Insurance Marketplace Statement",
        source_url="https://www.irs.gov/forms-pubs/about-form-1095-a",
        boxes=[
            _b("marketplace_state", "Part I line 1 — Marketplace state", "state"),
            _b("policy_number", "Part I line 2 — Marketplace-assigned policy number", "text"),
            # Part III monthly rows (lines 21-32), columns A (premium) / B (SLCSP) / C (APTC).
            *[
                _b(f"{line}{col}", f"Part III line {line}{col.upper()} — {month} {label}", "money")
                for line, month in zip(
                    range(21, 33),
                    ("January", "February", "March", "April", "May", "June", "July",
                     "August", "September", "October", "November", "December"),
                )
                for col, label in (
                    ("a", "monthly enrollment premium"),
                    ("b", "SLCSP premium"),
                    ("c", "advance payment of PTC"),
                )
            ],
            _b("33a", "Line 33A — Annual premium total", "money", required=True),
            _b("33b", "Line 33B — Annual SLCSP premium total", "money", required=True),
            _b("33c", "Line 33C — Annual advance PTC total", "money", required=True),
        ],
    ),
    DocSpec(
        # The last common document extract_document did not support (ROADMAP
        # Phase B note). Part III layout transcribed from the 2025 Schedule K-1
        # (Form 1065), read page-by-page 2026-08-10.
        kind="K-1",
        title="Schedule K-1 (Form 1065) — Partner's Share of Income, Deductions, Credits, etc.",
        source_url="https://www.irs.gov/forms-pubs/about-schedule-k-1-form-1065",
        status_note=(
            "K-1 amounts can be LOSSES — enter them with a leading minus sign (a parenthesized "
            "reading is flagged invalid on purpose). Box 14 self-employment earnings drive SE tax "
            "(calc op se_tax); a checked box 16 means a Schedule K-3 with international items is "
            "attached and must be read too; boxes 11/13/15/17/18/20 carry CODE letters whose "
            "amounts live on an attached statement — record the codes and read the statement, "
            "never total them blind. K-1s commonly arrive on extension (September): confirm the "
            "filing is not waiting on one before calling the document inventory complete."
        ),
        boxes=[
            _b("partnership_ein", "Part I item A — Partnership's employer identification number", "ein", required=True),
            _b("partnership_name", "Part I item B — Partnership's name, address, city, state, and ZIP code", "text"),
            _b("partner_tin", "Part II item E — Partner's SSN or TIN", "tin", required=True),
            _b("partner_name", "Part II item F — Name and address of partner", "text"),
            _b("foreign_partner", "Part II item H1 — Foreign partner (vs domestic)", "checkbox"),
            _b("1", "Box 1 — Ordinary business income (loss)", "money"),
            _b("2", "Box 2 — Net rental real estate income (loss)", "money"),
            _b("3", "Box 3 — Other net rental income (loss)", "money"),
            _b("4a", "Box 4a — Guaranteed payments for services", "money"),
            _b("4b", "Box 4b — Guaranteed payments for capital", "money"),
            _b("4c", "Box 4c — Total guaranteed payments", "money"),
            _b("5", "Box 5 — Interest income", "money"),
            _b("6a", "Box 6a — Ordinary dividends", "money"),
            _b("6b", "Box 6b — Qualified dividends", "money"),
            _b("6c", "Box 6c — Dividend equivalents", "money"),
            _b("7", "Box 7 — Royalties", "money"),
            _b("8", "Box 8 — Net short-term capital gain (loss)", "money"),
            _b("9a", "Box 9a — Net long-term capital gain (loss)", "money"),
            _b("9b", "Box 9b — Collectibles (28%) gain (loss)", "money"),
            _b("9c", "Box 9c — Unrecaptured section 1250 gain", "money"),
            _b("10", "Box 10 — Net section 1231 gain (loss)", "money"),
            _b("11", "Box 11 — Other income (loss) (code letters; amounts on the attached statement)", "text"),
            _b("12", "Box 12 — Section 179 deduction", "money"),
            _b("13", "Box 13 — Other deductions (code letters; amounts on the attached statement)", "text"),
            _b("14", "Box 14 — Self-employment earnings (loss)", "money"),
            _b("15", "Box 15 — Credits (code letters; amounts on the attached statement)", "text"),
            _b("16", "Box 16 — Schedule K-3 is attached if checked", "checkbox"),
            _b("17", "Box 17 — Alternative minimum tax (AMT) items (code letters)", "text"),
            _b("18", "Box 18 — Tax-exempt income and nondeductible expenses (code letters)", "text"),
            _b("19", "Box 19 — Distributions", "money"),
            _b("20", "Box 20 — Other information (code letters)", "text"),
            _b("21", "Box 21 — Foreign taxes paid or accrued", "money"),
        ],
    ),
    # ── Phase I5. Document-extraction breadth (ROADMAP I5). Every box layout
    # below was read off the official form on irs.gov 2026-08-27, with the
    # form's own "Instructions for Payee/Recipient" and the filer instructions
    # read alongside it. Where a box's MEANING (not its dollar amount) moves
    # between revisions, the status_note says so, because a DocSpec carries one
    # layout and the filer's paper may be an older printing.
    DocSpec(
        # f1099k.pdf (Rev. December 2026) + i1099k.pdf (Rev. 12-2026), read
        # 2026-08-27, cross-checked against f1099k--2024.pdf (Rev. March 2024).
        kind="1099-K",
        title="Payment Card and Third Party Network Transactions",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-k",
        status_note=(
            "BOX 1a IS GROSS RECEIPTS, NOT INCOME, AND NOT EVEN NET RECEIPTS. The filer instructions "
            "define it as the total of reportable payment transactions 'without regard to any "
            "adjustments for credits, cash equivalents, discount amounts, fees, refunded amounts, "
            "shipping amounts, or any other amounts' — so a reseller's platform fees, refunds to "
            "buyers and shipping are all still inside box 1a and come off on Schedule C, and a "
            "personal-item resale at a LOSS still produces a box 1a. THE THRESHOLD IS A REPORTING "
            "RULE, NEVER A TAXABILITY RULE, and it has moved repeatedly — take it from the revision "
            "of the instructions that matches the filer's paper, never from memory. Instructions for "
            "Form 1099-K (Rev. 12-2026) state it as: a third party settlement organization must "
            "report only if, for the calendar year, 'the gross amount of total reportable payment "
            "transactions exceeds $20,000, and the total number of such transactions exceeds 200' "
            "(both conditions, AND). That de minimis binds TPSOs only — a merchant acquirer settling "
            "PAYMENT CARD transactions has no de minimis at all, so a card-accepting business gets a "
            "1099-K for any amount. Below the threshold NO form arrives and the income is still "
            "reportable: IRC 6050W displaces sections 6041/6041A for these payments and the de "
            "minimis threshold 'is disregarded' in deciding which section applies, so the payment "
            "does not fall back to a 1099-NEC or 1099-MISC either. Watch for DOUBLE COUNTING — the "
            "same gig receipts can appear on both a 1099-K and a 1099-NEC when more than one payer "
            "is involved; reconcile to the books, never add the forms. BOXES 6 AND 8 SWAPPED "
            "BETWEEN REVISIONS: on Rev. December 2026 box 6 is 'State income tax withheld' and box 8 "
            "is 'State', while on Rev. March 2024 (the printing a 2023-2025 filer holds) box 6 is "
            "'State' and box 8 is 'State income tax withheld' — this spec carries the CURRENT "
            "numbering, so on an older form read the captions and swap. BOXES 1c AND 1d ARE NEW for "
            "calendar year 2026 (P.L. 119-21, section 70201) and are absent from every earlier "
            "printing: box 1c cash tips is a SUBSET of box 1a, not an addition to it, and feeds the "
            "qualified-tips deduction in Part II of Schedule 1-A (Form 1040) — but only if box 1d "
            "says so. A box 1d Treasury Tipped Occupation Code of 000 with no other code means the "
            "cash tips are NOT qualified tips: 'do not use the amount reported in box 1c for the "
            "deduction'. Which is why box 1d is a code, not a number — coerced to an integer, 000 "
            "would become 0 and the disqualifier would read as an unfilled box."
        ),
        boxes=[
            _b("filer_tin", "FILER'S TIN", "tin"),
            _b("payee_tin", "PAYEE'S TIN", "tin", required=True),
            _b("filer_name", "FILER'S name and address", "text"),
            _b("payee_name", "PAYEE'S name and address", "text"),
            _b("pse_name", "PSE'S name and telephone number", "text"),
            _b("account_number", "Account number (see instructions)", "text"),
            _b("filer_is_pse", "Check to indicate if FILER is a (an) — Payment settlement entity (PSE)", "checkbox"),
            _b("filer_is_epf", "Check to indicate if FILER is a (an) — Electronic payment facilitator (EPF)/Other third party", "checkbox"),
            # These two decide whether the de minimis in the status_note applies
            # at all: it binds third party network transactions, not payment card.
            _b("txn_payment_card", "Check to indicate transactions reported are — Payment card", "checkbox"),
            _b("txn_third_party_network", "Check to indicate transactions reported are — Third party network", "checkbox"),
            _b("1a", "Box 1a — Gross amount of payment card/third party network transactions", "money", required=True),
            _b("1b", "Box 1b — Card Not Present transactions", "money"),
            _b("1c", "Box 1c — Cash tips", "money"),
            # "code", not "int": box 1d holds up to two Treasury Tipped Occupation
            # Codes and the code 000 is MEANINGFUL (it disqualifies box 1c from the
            # Schedule 1-A tips deduction). int coercion would turn "000" into 0.
            _b("1d_ttoc_1", "Box 1d — TTOC (Treasury Tipped Occupation Code) 1", "code"),
            _b("1d_ttoc_2", "Box 1d — TTOC (Treasury Tipped Occupation Code) 2", "code"),
            # Merchant category code: a 4-digit code, leading zeros load-bearing.
            _b("2", "Box 2 — Merchant category code", "code"),
            # "int": a count of transactions, so a fractional reading is a misread.
            _b("3", "Box 3 — Number of payment transactions", "int"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            *[
                _b(f"5{chr(ord('a') + i)}", f"Box 5{chr(ord('a') + i)} — {month}", "money")
                for i, month in enumerate(
                    ("January", "February", "March", "April", "May", "June", "July",
                     "August", "September", "October", "November", "December")
                )
            ],
            # Boxes 6-8 hold up to two states (two printed lines each); the first
            # line is modelled, as on the W-2. The TYPES are the guardrail against
            # the Rev. 3-2024 numbering: dollars read into box 8 fail the "state"
            # check and a two-letter state read into box 6 fails "money", so a
            # wrong-revision reading surfaces as `invalid` instead of a silent swap.
            _b("6", "Box 6 — State income tax withheld (first of two state lines)", "money"),
            _b("7", "Box 7 — State identification no. (first of two state lines)", "text"),
            _b("8", "Box 8 — State (first of two state lines)", "state"),
        ],
    ),
    DocSpec(
        # f1099q.pdf (Rev. April 2025) + i1099q.pdf (Rev. 4-2025), read 2026-08-27,
        # with the form's own Instructions for Recipient.
        kind="1099-Q",
        title="Payments From Qualified Education Programs (Under Sections 529 and 530)",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-q",
        status_note=(
            "THE TRUSTEE DID NOT DECIDE WHETHER ANY OF THIS IS TAXABLE, AND MOST OF THE TIME IT IS "
            "NOT: 'Nontaxable distributions from CESAs and QTPs are not required to be reported on "
            "your income tax return. You must determine the taxability of any distribution.' A "
            "distribution spent on qualified education expenses appears on no line of the 1040 at "
            "all — so a box 1 that ties to tuition paid produces NO entry, and copying box 1 onto an "
            "income line is the error this form causes. ONLY BOX 2 CAN EVER BE INCOME. Box 1 is the "
            "gross distribution and 'is the total of the amounts shown in boxes 2 and 3' (box 3 = box "
            "1 - box 2), so box 3 basis is the beneficiary's own after-tax money and is never taxed. "
            "BLANK BOXES 2 AND 3 ARE CORRECT ON A COVERDELL, NOT A GAP: for CESA distributions the "
            "trustee is not required to figure earnings and basis — 'If earnings and basis are not "
            "reported for Coverdell ESA distributions, leave boxes 2 and 3 blank. Do not enter zero. "
            "Instead, you must report the fair market value (FMV) as of the end of the year in box 7' "
            "— and you then compute earnings yourself with the Coverdell ESA — Taxable Distributions "
            "and Basis worksheet in Pub. 970. A zero in box 2 on a Coverdell is therefore suspect, "
            "because the instruction is to leave it EMPTY. BOX 7 IS NOT A MONEY BOX: it carries the "
            "year-end FMV labelled 'FMV' and/or an OPTIONAL distribution code the trustee 'may, but "
            "[is] not required to' report and 'may abbreviate as needed' (e.g. 'distr. code 1'), so "
            "readings like 'FMV 12,345' and 'distr. code 2' are both correct and it is typed text. "
            "The codes: 1 distributions (including transfers), 2 excess contributions plus earnings "
            "taxable in the calendar year, 3 excess contributions plus earnings taxable in the prior "
            "calendar year, 4 disability, 5 death, 6 prohibited transaction. WHAT MAKES BOX 2 "
            "TAXABLE IS NOT ON THIS FORM. Under a QTP it is income if there was '(a) more than one "
            "transfer or rollover within any 12-month period with respect to the same beneficiary, or "
            "(b) a change in the designated beneficiary and the new designated beneficiary is not a "
            "family member'; under a CESA if the beneficiary changed to a non-family-member or one "
            "over age 30 (special-needs beneficiaries excepted). An additional 10% tax may apply — "
            "Form 5329. Box 4a (trustee-to-trustee: QTP to QTP, QTP to an ABLE account, CESA to CESA, "
            "CESA to QTP) and box 4b (QTP to a Roth IRA, new on this revision) "
            "mark moves that are generally NOT income, and 'in certain transfers from a CESA the box "
            "will be blank' — so an unchecked box 4a does not prove a distribution was spent. Boxes "
            "5a/5b/5c say which program it was and therefore WHICH RULEBOOK applies (private QTP, "
            "state QTP, Coverdell ESA). A checked box 6 means the RECIPIENT IS NOT THE DESIGNATED "
            "BENEFICIARY (IRC 529(e)(1)) — the taxable earnings then belong to the person named on "
            "this form, not to the student. THERE IS NO WITHHOLDING BOX ON THIS FORM: 'Earnings are "
            "not subject to backup withholding', so nothing here is a payment against the tax."
        ),
        boxes=[
            _b("payer_tin", "PAYER'S/TRUSTEE'S TIN", "tin"),
            _b("recipient_tin", "RECIPIENT'S TIN", "tin", required=True),
            _b("payer_name", "PAYER'S/TRUSTEE'S name and address", "text"),
            _b("recipient_name", "RECIPIENT'S name", "text"),
            _b("account_number", "Account number (see instructions)", "text"),
            _b("1", "Box 1 — Gross distribution", "money", required=True),
            # NOT required: on a Coverdell the trustee is instructed to leave
            # boxes 2 and 3 blank and report the FMV in box 7 instead.
            _b("2", "Box 2 — Earnings", "money"),
            _b("3", "Box 3 — Basis", "money"),
            _b("4a", "Box 4a — Type of transfer: Trustee-to-trustee", "checkbox"),
            _b("4b", "Box 4b — Type of transfer: QTP to Roth IRA", "checkbox"),
            _b("5a", "Box 5a — Distribution is from: Private QTP", "checkbox"),
            _b("5b", "Box 5b — Distribution is from: State QTP", "checkbox"),
            _b("5c", "Box 5c — Distribution is from: Coverdell ESA", "checkbox"),
            _b("6", "Box 6 — Check if the recipient is not the designated beneficiary", "checkbox"),
            # "text", not "money": box 7 legitimately holds the year-end FMV
            # labelled "FMV" and/or an abbreviated distribution code, so a money
            # box would flag the trustee's own prescribed reading as invalid.
            _b("7", "Box 7 — If the fair market value (FMV) is shown below, see Pub. 970, Tax Benefits for Education, for how to figure earnings (the trustee may also report a distribution code 1-6 in this box)", "text"),
        ],
    ),
    DocSpec(
        # fw2g.pdf (Rev. January 2026) + iw2g.pdf, Instructions for Forms W-2G and
        # 5754 (Rev. January 2026), read 2026-08-27; cross-checked against
        # fw2g--2021.pdf (Rev. 1-2021), and IRC 165(d) read at uscode.house.gov.
        kind="W-2G",
        title="Certain Gambling Winnings",
        source_url="https://www.irs.gov/forms-pubs/about-form-w-2-g",
        status_note=(
            "BOX 1 IS INCOME IN FULL AND THE LOSSES DO NOT COME OFF IT. Winnings go to the 'Other "
            "income' line of Schedule 1 (Form 1040) gross; gambling losses are a separate ITEMIZED "
            "deduction (Schedule A), so a filer taking the standard deduction reports every dollar of "
            "box 1 and deducts NOTHING. There is no netting on this form and no netting on the return "
            "— box 1 is per-payment gross winnings, and a losing year with one big hit still produces "
            "taxable income. THE LOSS PERCENTAGE CHANGED, so key it to the tax year, not to the "
            "form: IRC 165(d)(1) as rewritten by P.L. 119-21 §70114(a) allows a deduction that '(A) "
            "shall be equal to 90 percent of the amount of such losses during such taxable year, and "
            "(B) shall be allowed only to the extent of the gains from such transactions during such "
            "taxable year' — and §70114(b) applies that 'to taxable "
            "years beginning after December 31, 2025'. So TY2026 onward deducts 90% of losses capped "
            "at winnings (the Rev. January 2026 Instructions to Winner say '90% of your gambling "
            "losses'), while TY2025 and earlier take the pre-amendment rule, 'Losses from wagering "
            "transactions shall be allowed only to the extent of the gains from such transactions' — "
            "100%, same cap. 165(d)(2) sweeps 'any deduction otherwise allowable under this chapter "
            "incurred in carrying on any wagering transaction' into 'losses', which is what reaches a "
            "professional gambler's expenses. THE REPORTING THRESHOLD MOVES EVERY YEAR NOW AND IS "
            "NOT A TAXABILITY TEST: the Instructions for Forms W-2G and 5754 (Rev. 1-2026) state that "
            "'for calendar years after 2025, the minimum threshold amount for reporting certain "
            "payments and backup withholding on certain information returns, including the Form W-2G, "
            "will be adjusted yearly for inflation. The minimum threshold amount for payments made in "
            "calendar year 2026 is $2,000' — take later years from Pub. 1099, never from memory, and "
            "remember that winnings under the threshold arrive with NO W-2G and are income anyway. "
            "BOX 4 CAN BE ZERO ON A LARGE WIN: regular gambling withholding is 24% under IRC 3402(q) "
            "and applies only when the winnings minus the wager exceed $5,000 (and, for the "
            "300-times-the-wager games, that ratio too); below that the payer withholds nothing "
            "unless the winner gave no TIN, when IRC 3406 backup withholding applies at the same 24%. "
            "On a NONCASH prize the rate is 24% of FMV less the wager if the winner pays the "
            "withholding, but 31.58% if the PAYER pays it. Box 7 exists because 'identical wagers' "
            "are added together for reporting and withholding — the box 1 figure may already "
            "aggregate several tickets, and for bingo/keno/slots a payer may aggregate a whole gaming "
            "day onto one form. A NONRESIDENT ALIEN SHOULD NOT HAVE THIS FORM AT ALL: 'Use Form "
            "1042-S to report gambling winnings paid to nonresident aliens and foreign corporations' "
            "— a W-2G issued to an NRA signals the payer mis-classified the winner's status, and the "
            "1042-S route carries different (treaty-sensitive) withholding. Boxes 13-18 'are provided "
            "for your convenience only and need not be completed for the IRS', so blank state boxes "
            "prove nothing about a state filing duty."
        ),
        boxes=[
            _b("payer_tin", "PAYER'S TIN", "tin"),
            _b("payer_name", "PAYER'S name and address", "text"),
            _b("winner_name", "WINNER'S name", "text"),
            _b("1", "Box 1 — Reportable winnings", "money", required=True),
            # No "date" FieldType in this module (see Form 3921/3922 boxes 1-2):
            # dates stay text so an as-printed reading is never mangled.
            _b("2", "Box 2 — Date won", "text", required=True),
            _b("3", "Box 3 — Type of wager", "text"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("5", "Box 5 — Transaction", "text"),
            _b("6", "Box 6 — Race", "text"),
            _b("7", "Box 7 — Winnings from identical wagers", "money"),
            _b("8", "Box 8 — Cashier", "text"),
            # "This is required information" (Instructions for Forms W-2G and 5754).
            _b("9", "Box 9 — WINNER'S TIN", "tin", required=True),
            _b("10", "Box 10 — Window", "text"),
            _b("11", "Box 11 — First identification no.", "text"),
            _b("12", "Box 12 — Second identification no.", "text"),
            # "text", not "state": box 13 holds the state abbreviation AND the
            # payer's state id number in one box ("Enter the abbreviated name of
            # the state and your state identification number"), as on 1099-NEC box 6.
            _b("13", "Box 13 — State/Payer's state identification no.", "text"),
            _b("14", "Box 14 — State winnings", "money"),
            _b("15", "Box 15 — State income tax withheld", "money"),
            _b("16", "Box 16 — Local winnings", "money"),
            _b("17", "Box 17 — Local income tax withheld", "money"),
            _b("18", "Box 18 — Name of locality", "text"),
        ],
    ),
    DocSpec(
        # f1095b.pdf (2025) + its own Instructions for Recipient, read 2026-08-27.
        # 1095-B and 1095-C are DIFFERENT forms with different line numbering and
        # are kept as separate kinds for exactly that reason — see the 1095-C spec.
        kind="1095-B",
        title="Health Coverage",
        source_url="https://www.irs.gov/forms-pubs/about-form-1095-b",
        status_note=(
            "'DO NOT ATTACH TO YOUR TAX RETURN. KEEP FOR YOUR RECORDS.' — the form's own header. "
            "Nothing here is income, a deduction or a credit; it is proof of minimum essential "
            "coverage, and its whole value to a federal return is NEGATIVE: coverage reported here "
            "can make a household INELIGIBLE for the premium tax credit ('If individuals in your tax "
            "family are eligible for certain types of minimum essential coverage, you may not be "
            "eligible for the premium tax credit'), so reconcile it against any Form 1095-A before "
            "running the PTC. WHERE IT CAN CHANGE A NUMBER IS A STATE RETURN: the month checkboxes in "
            "Part IV column (e) are the per-person coverage evidence a state individual-mandate "
            "return needs, so read the grid per PERSON and per MONTH, not per household. Which "
            "states impose one, and what a gap month costs, is a STATE-LAW question this spec does "
            "not answer — check the year's state knowledge rather than assuming; the one regime the "
            "repo documents today is DC's Health Care Shared Responsibility payment (Schedule HSR), "
            "noted as not modelled in knowledge/states/dc. THE THREE FORMS ARE NOT INTERCHANGEABLE and the same coverage appears on "
            "exactly one of them: Marketplace coverage 'will generally be reported on a Form 1095-A "
            "rather than a Form 1095-B', and employer-sponsored coverage 'may be reported on a Form "
            "1095-C (Part III) rather than a Form 1095-B'. A 1095-B with a blank Part II is NORMAL, "
            "not incomplete: 'This part may also be left blank, even if you had employer-sponsored "
            "health coverage. If this part is blank, you do not need to fill in the information or "
            "return it to your employer or other coverage provider.' LINE 8 IS THE ONE CODE THAT MATTERS and 'only one letter "
            "will be entered': A SHOP, B employer-sponsored coverage, C government-sponsored program, "
            "D individual market insurance, E multiemployer plan, F other designated minimum "
            "essential coverage, G individual coverage HRA. Column (d) means 'covered for at least 1 "
            "day in EVERY month of the year' — one day of a month counts the whole month, so (d) and "
            "a full row of (e) checks are not the same claim, and a person covered only part of the "
            "year has (d) blank and column (e) filled instead. Column (c) date of birth 'will be "
            "entered ... only if the SSN or other TIN is not entered in column (b)', so a blank (c) "
            "is expected. Only ONE 1095-B is furnished for everyone on the policy, and it lists six "
            "covered individuals per page (lines 23-28) with a Part IV Continuation Sheet for more — "
            "a seven-person household's form is INCOMPLETE until the continuation sheet is read too. "
            "Line 9 is printed 'Reserved' and is deliberately not modelled here."
        ),
        boxes=[
            _b("1", "Line 1 — Name of responsible individual", "text"),
            _b("2", "Line 2 — Social security number (SSN) or other TIN", "tin", required=True),
            _b("3", "Line 3 — Date of birth (if SSN or other TIN is not available)", "text"),
            _b("4", "Line 4 — Street address (including apartment no.)", "text"),
            _b("5", "Line 5 — City or town", "text"),
            _b("6", "Line 6 — State or province", "text"),
            _b("7", "Line 7 — Country and ZIP or foreign postal code", "text"),
            # "code": a single letter A-G, never a number.
            _b("8", "Line 8 — Enter letter identifying Origin of the Health Coverage", "code", required=True),
            _b("10", "Line 10 — Part II Employer name", "text"),
            _b("11", "Line 11 — Part II Employer identification number (EIN)", "ein"),
            _b("16", "Line 16 — Part III Issuer or other coverage provider name", "text"),
            _b("17", "Line 17 — Part III Issuer employer identification number (EIN)", "ein"),
            _b("18", "Line 18 — Part III Contact telephone number", "text"),
            # Part IV, lines 23-28 (six covered individuals per page; a seventh
            # goes on the Continuation Sheet). Column (e) is a twelve-checkbox
            # month grid per person — the payload for a state-mandate return.
            *[
                box
                for line in range(23, 29)
                for box in (
                    _b(f"{line}a", f"Part IV line {line} col (a) — Name of covered individual", "text"),
                    _b(f"{line}b", f"Part IV line {line} col (b) — SSN or other TIN", "tin"),
                    _b(f"{line}c", f"Part IV line {line} col (c) — DOB (if SSN or other TIN is not available)", "text"),
                    _b(f"{line}d", f"Part IV line {line} col (d) — Covered all 12 months", "checkbox"),
                    *[
                        _b(f"{line}e_{m.lower()}", f"Part IV line {line} col (e) — Months of coverage: {m}", "checkbox")
                        for m in ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
                    ],
                )
            ],
        ],
    ),
    DocSpec(
        # f1095c.pdf (2025) + i109495c.pdf, Instructions for Forms 1094-C and
        # 1095-C (2025), read 2026-08-27. A SEPARATE kind from 1095-B: the line
        # numbers collide but mean different things (line 14 here is the offer
        # code; on the 1095-B there is no line 14 at all, and line 8 there has no
        # counterpart here), so one shared spec would mislabel both forms.
        kind="1095-C",
        title="Employer-Provided Health Insurance Offer and Coverage",
        source_url="https://www.irs.gov/forms-pubs/about-form-1095-c",
        status_note=(
            "'DO NOT ATTACH TO YOUR TAX RETURN. KEEP FOR YOUR RECORDS.' — and yet PART II DECIDES "
            "WHETHER A PREMIUM TAX CREDIT IS ALLOWED AT ALL, which is why these codes, not the "
            "dollars, are what has to be read. Line 14 'relates to eligibility for coverage subsidized "
            "by the premium tax credit', and an offer of affordable minimum-value coverage kills the "
            "PTC for the months offered even if the employee declined it and bought on the "
            "Marketplace instead — the classic false refund. LINE 14, CODE SERIES 1, ONE CODE PER "
            "MONTH: 1A qualifying offer, 1B self only, 1C employee + dependents (NOT spouse), 1D "
            "employee + spouse (NOT dependents), 1E employee + spouse + dependents, 1F coverage NOT "
            "providing minimum value, 1G not a full-time employee for any month but enrolled in "
            "self-insured coverage, 1H NO OFFER OF COVERAGE, 1J/1K conditional spouse offers, and "
            "1L-1U the individual coverage HRA codes (1L/1M/1N/1T priced off the employee's RESIDENCE "
            "ZIP, 1O/1P/1Q/1U off the PRIMARY EMPLOYMENT SITE ZIP). 1I and 1V-1Z are 'Reserved for "
            "future use'. Code 1G is entered in the All 12 Months box or in all twelve monthly boxes, "
            "never in some of them. LINE 16, CODE SERIES 2, 'only one code from Code Series 2 per "
            "calendar month': 2A employee not employed during the month, 2B not a full-time employee, "
            "2C ENROLLED in the coverage offered, 2D in a section 4980H(b) Limited Non-Assessment "
            "Period, 2E multiemployer interim rule relief, 2F Form W-2 affordability safe harbor, 2G "
            "federal poverty line safe harbor, 2H rate of pay safe harbor (2I reserved). ONLY 2C "
            "MATTERS TO THE FILER: 'Other than a code 2C, which reflects your enrollment in your "
            "employer's coverage, none of this information affects your eligibility for the premium "
            "tax credit' — line 16 is otherwise the employer's own 4980H defence, not the employee's "
            "tax fact. LINE 15 IS NOT WHAT THE EMPLOYEE PAID: it is 'the monthly cost to you for the "
            "lowest cost self-only minimum essential coverage providing minimum value that your "
            "employer offered you', so a family-coverage election makes the real payroll deduction "
            "much larger — and line 15 'will show an amount only if code 1B, 1C, 1D, 1E, 1J, 1K, 1L, "
            "1M, 1N, 1O, 1P, 1Q, 1T, or 1U is entered on line 14', so a BLANK line 15 next to a 1A or "
            "1H is correct. A LINE 15 OF 0.00 IS A REAL VALUE, NOT AN EMPTY BOX: 'If you were offered "
            "coverage but there is no cost to you for the coverage, this line will report \"0.00\"'. "
            "THE AFFORDABILITY PERCENTAGE IS INDEXED — never hardcode it: references to 9.5% 'are "
            "applied based on the percentage as indexed for purposes of applying the affordability "
            "thresholds under section 36B' and the instructions give it as '8.39% for plan years "
            "beginning in 2024, and 9.02% for plan years beginning in 2025'; take any other year from "
            "that year's instructions. PART III IS OFTEN LEGITIMATELY BLANK: 'Complete Part III ONLY "
            "if the ALE Member offers employer-sponsored, self-insured health coverage' — under an "
            "INSURED group plan the coverage months arrive on a Form 1095-B instead, so an empty Part "
            "III is not a missing roster. Column (d) means covered 'for at least one day in every "
            "month of the year'. MULTIPLE EMPLOYERS MEAN MULTIPLE FORMS, each covering only its own "
            "months — a job change produces two 1095-Cs and both must be read. Part III prints "
            "THIRTEEN rows (lines 18-30) and 'if there are more than 13 covered individuals, "
            "additional copies of page 3 ... may be used', so a larger household needs a second "
            "extract_document call for the extra page."
        ),
        boxes=[
            _b("1", "Line 1 — Name of employee", "text"),
            _b("2", "Line 2 — Social security number (SSN)", "ssn", required=True),
            _b("3", "Line 3 — Street address (including apartment no.)", "text"),
            _b("4", "Line 4 — City or town", "text"),
            _b("5", "Line 5 — State or province", "text"),
            _b("6", "Line 6 — Country and ZIP or foreign postal code", "text"),
            _b("7", "Line 7 — Name of employer (Applicable Large Employer Member)", "text"),
            _b("8", "Line 8 — Employer identification number (EIN)", "ein", required=True),
            _b("10", "Line 10 — Contact telephone number", "text"),
            # "int": an age in whole years.
            _b("employee_age_jan_1", "Part II — Employee's Age on January 1", "int"),
            # "code", not "int": the form says "enter 2-digit number", so "01" must
            # survive as printed rather than being coerced to 1.
            _b("plan_start_month", "Part II — Plan Start Month (enter 2-digit number)", "code"),
            # Part II lines 14-17. Each line has an "All 12 Months" column PLUS a
            # box per month, and the two are alternatives, not duplicates: a code
            # in "All 12 Months" means the monthly boxes stay empty.
            *[
                _b(f"{line}_{col_key}", f"Part II line {line} ({line_label}) — {col_label}", type_)
                for line, line_label, type_ in (
                    ("14", "Offer of Coverage — enter required code", "code"),
                    ("15", "Employee Required Contribution", "money"),
                    ("16", "Section 4980H Safe Harbor and Other Relief — enter code, if applicable", "code"),
                    ("17", "ZIP Code", "text"),
                )
                for col_key, col_label in (
                    ("all_12_months", "All 12 Months"),
                    *[(m.lower(), m) for m in ("Jan", "Feb", "Mar", "Apr", "May", "June",
                                               "July", "Aug", "Sept", "Oct", "Nov", "Dec")],
                )
            ],
            _b("part_iii_self_insured", "Part III — If employer-provided, self-insured coverage, check the box", "checkbox"),
            # Part III, lines 18-30 — THIRTEEN printed rows (the 1095-B prints six).
            *[
                box
                for line in range(18, 31)
                for box in (
                    _b(f"{line}a", f"Part III line {line} col (a) — Name of covered individual", "text"),
                    _b(f"{line}b", f"Part III line {line} col (b) — SSN or other TIN", "tin"),
                    _b(f"{line}c", f"Part III line {line} col (c) — DOB (if SSN or other TIN is not available)", "text"),
                    _b(f"{line}d", f"Part III line {line} col (d) — Covered all 12 months", "checkbox"),
                    *[
                        _b(f"{line}e_{m.lower()}", f"Part III line {line} col (e) — Months of coverage: {m}", "checkbox")
                        for m in ("Jan", "Feb", "Mar", "Apr", "May", "June",
                                  "July", "Aug", "Sept", "Oct", "Nov", "Dec")
                    ],
                )
            ],
        ],
    ),
    DocSpec(
        # f5498.pdf (2026) + i1099r.pdf, Instructions for Forms 1099-R and 5498
        # (2026), read 2026-08-27. DISTINCT KIND from the "5498-SA" spec above:
        # same number family, different form, different box meanings (box 5 here
        # is the IRA's Dec-31 FMV; box 5 there is the HSA/MSA FMV, and box 2
        # there is the HSA contribution total that has no counterpart here).
        kind="5498",
        title="IRA Contribution Information",
        source_url="https://www.irs.gov/forms-pubs/about-form-5498",
        status_note=(
            "THIS IS THE IRA FORM, NOT THE HSA ONE. If the paper says 'HSA, Archer MSA, or Medicare "
            "Advantage MSA Information' you want kind 5498-SA, whose boxes mean different things. A "
            "TRUMP ACCOUNT SPLITS ACROSS TWO FORMS and only one of them is this one: 'For a Trump "
            "account, Form 5498 is only used after the account beneficiary's growth period. Form "
            "5498-TA is used during the account beneficiary's growth period' — and Form 5498-TA is "
            "not modelled here. The form is "
            "informational and is not attached to a return ('keep for your records'), but TWO OF ITS "
            "BOXES DRIVE REAL CALCULATIONS. BOX 5 IS THE PRO-RATA DENOMINATOR: it is 'the FMV of the "
            "account on December 31', the figure Form 8606 line 6 wants, so run calc op ira_pro_rata "
            "with the box 5 totals of EVERY traditional/SEP/SIMPLE IRA the person owns — one "
            "account's box 5 is not the denominator, the sum is. AND BOX 5 IS NOT ALWAYS A DEC-31 "
            "VALUE: 'if a decedent's name is shown, the amount reported may be the FMV on the date of "
            "death', which silently corrupts the ratio if fed in as a year-end balance. BOX 3 IS THE "
            "CONVERSION: 'the amount converted from traditional IRAs to Roth IRAs' — the calc op "
            "roth_conversion / Form 8606 Part II figure. It is NOT in box 2: box 2 is rollovers "
            "'other than conversions done through a rollover contribution from a traditional IRA to a "
            "Roth IRA, which are reported in box 3'. THE YEAR CONVENTIONS OF THE CONTRIBUTION BOXES "
            "DISAGREE WITH EACH OTHER — this is the trap that makes people double-count. Box 1 is "
            "traditional IRA contributions FOR this year 'you made in [this year] and through April "
            "15' of the NEXT year, so the January-April window lands on THIS form; box 10 is Roth "
            "contributions on the same for-the-year basis ('Do not deduct on your income tax "
            "return'); but boxes 8 (SEP) and 9 (SIMPLE) run the OPPOSITE way, by deposit date — made "
            "in this year 'including contributions made in [this year] for [last year], but not "
            "including contributions made in [next year] for [this year]'. So a SEP contribution for "
            "this year deposited next March appears on NEXT year's Form 5498, and matching box 8 to a "
            "Schedule 1 deduction year by year fails. Box 1 EXCLUDES boxes 2-4, 8-10, 13a and 14a, so "
            "the boxes never sum to 'what I put in'. Box 6 is endowment contracts only and must be "
            "SUBTRACTED: 'Subtract this amount from your allowable IRA contribution included in box 1 "
            "to compute your IRA deduction.' Box 7 only 'MAY show the kind of IRA', so unchecked "
            "boxes prove nothing about the account type. BOX 11 IS ABOUT NEXT YEAR AND ITS SILENCE IS "
            "NOT SAFETY: it flags an RMD due for the FOLLOWING year, and 'an RMD may be required even "
            "if the box is not checked'. Box 13a is a late (over-60-day) rollover or a postponed "
            "contribution for a prior year and 'is not reported in box 1 or box 2'; box 13b is the "
            "year it was credited to (blank when box 13a is a late rollover, which is how a "
            "prior-year contribution gets mis-dated) and box 13c its code — FD federally designated "
            "disaster, PO qualified plan loan offset rollover, SC self-certified late rollover, plus "
            "the combat-zone codes EO13239, EO12744, PL115-97 and EO13119/PL106-21. Box 14a is a "
            "repayment of a qualified reservist, disaster, birth-or-adoption, first-time-home, "
            "emergency-personal-expense, domestic-abuse or terminally-ill distribution, coded in box "
            "14b as QR, DD, BA, HP, EP, DA or TI. Boxes 15a/15b flag hard-to-value holdings (A "
            "non-tradable stock, B non-traded debt, C LLC interest, D real estate, E partnership or "
            "trust interest, F non-exchange option, G other asset with no readily available FMV, H "
            "more than two of A-G) — their presence means the box 5 FMV is an ESTIMATE, and a "
            "conversion priced off an estimate is a return-level risk."
        ),
        boxes=[
            _b("trustee_tin", "TRUSTEE'S/ISSUER'S TIN", "tin"),
            _b("participant_tin", "PARTICIPANT'S TIN", "tin", required=True),
            _b("trustee_name", "TRUSTEE'S/ISSUER'S name and address", "text"),
            _b("participant_name", "PARTICIPANT'S name", "text"),
            _b("account_number", "Account number (see instructions)", "text"),
            _b("1", "Box 1 — IRA contributions (other than amounts in boxes 2-4, 8-10, 13a, and 14a)", "money"),
            _b("2", "Box 2 — Rollover contributions", "money"),
            _b("3", "Box 3 — Roth IRA conversion amount", "money"),
            _b("4", "Box 4 — Recharacterized contributions", "money"),
            # Required: the trustee must value every IRA annually and report the
            # Dec-31 FMV, and it is the figure Form 8606 line 6 / ira_pro_rata needs.
            _b("5", "Box 5 — FMV of account", "money", required=True),
            _b("6", "Box 6 — Life insurance cost included in box 1", "money"),
            # The box 7 account-type set, treated like Form 1099-SA box 5.
            _b("7_ira", "Box 7 — IRA (account type checkbox)", "checkbox"),
            _b("7_sep", "Box 7 — SEP (account type checkbox)", "checkbox"),
            _b("7_simple", "Box 7 — SIMPLE (account type checkbox)", "checkbox"),
            _b("7_roth_ira", "Box 7 — Roth IRA (account type checkbox)", "checkbox"),
            _b("8", "Box 8 — SEP contributions", "money"),
            _b("9", "Box 9 — SIMPLE contributions", "money"),
            _b("10", "Box 10 — Roth IRA contributions", "money"),
            _b("11", "Box 11 — Check if RMD for the following year (printed with that year's digits, e.g. \"Check if RMD for 2027\" on the 2026 form)", "checkbox"),
            _b("12a", "Box 12a — RMD date", "text"),
            _b("12b", "Box 12b — RMD amount", "money"),
            _b("13a", "Box 13a — Postponed/late contrib.", "money"),
            # "int": the year a postponed contribution was credited to.
            _b("13b", "Box 13b — Year", "int"),
            _b("13c", "Box 13c — Code", "code"),
            _b("14a", "Box 14a — Repayments", "money"),
            _b("14b", "Box 14b — Code", "code"),
            _b("15a", "Box 15a — FMV of certain specified assets", "money"),
            # "code", plural on the form ("Code(s)"): more than one letter can appear.
            _b("15b", "Box 15b — Code(s)", "code"),
        ],
    ),
    # ── The other two Schedule K-1s (ROADMAP I5: "only the 1065 layout ships, so
    # an S-corp or trust K-1 has no structured path").
    #
    # NAMING: the existing spec keeps the bare kind "K-1" and stays the Form 1065
    # (partnership) layout, untouched, because every caller of it passes that
    # exact string. The two new siblings are keyed with the entity in the name.
    # Renaming the 1065 one to "K-1 (1065)" for symmetry would have broken those
    # callers, so the asymmetry is deliberate and is pinned by a test.
    #
    # This is not cosmetic: the SAME BOX NUMBER means different things on the
    # three forms. Box 14 is self-employment earnings on the 1065 K-1 but
    # "Schedule K-3 is attached" on the 1120-S K-1; box 16 is "Schedule K-3 is
    # attached" on the 1065 K-1 but "Items affecting shareholder basis" on the
    # 1120-S K-1. One shared spec would mislabel both.
    DocSpec(
        # f1120ssk.pdf (Schedule K-1 (Form 1120-S) 2025) + i1120ssk.pdf,
        # Instructions for Schedule K-1 (Form 1120-S) (2025), read 2026-08-27.
        kind="K-1 (1120-S)",
        title="Schedule K-1 (Form 1120-S) — Shareholder's Share of Income, Deductions, Credits, etc.",
        source_url="https://www.irs.gov/forms-pubs/about-schedule-k-1-form-1120-s",
        status_note=(
            "THIS IS THE S-CORPORATION K-1 AND IT IS NOT THE PARTNERSHIP ONE — kind 'K-1' is the Form "
            "1065 layout and the box numbers DISAGREE. On this form box 14 is 'Schedule K-3 is "
            "attached if checked' (on the 1065 K-1 that is box 16), and box 16 is 'Items affecting "
            "shareholder basis' (on the 1065 K-1 that is box 19, Distributions). Reading an 1120-S "
            "K-1 against the 1065 layout therefore silently converts a K-3 flag into "
            "self-employment earnings. THERE IS NO SELF-EMPLOYMENT BOX HERE AT ALL, BY DESIGN: 'Your "
            "share of S corporation income isn't self-employment income and it isn't subject to "
            "self-employment tax.' Do NOT run calc op se_tax on box 1 — that is the single most "
            "expensive error available on this form, and it is what a partnership-trained reading "
            "produces. The shareholder's labour is paid as W-2 WAGES instead, so a shareholder-employee "
            "with box 1 income and no W-2 raises a reasonable-compensation question this form cannot "
            "answer. "
            "There are also no guaranteed-payment boxes (the 1065 K-1's boxes 4a-4c) for the same "
            "reason. LOSSES ARE OFTEN NOT DEDUCTIBLE IN THE YEAR SHOWN, and the form warns of it: 'The "
            "amount of loss and deduction you may claim on your tax return may be less than the "
            "amount reported on Schedule K-1. It is the shareholder's responsibility to consider and "
            "apply any applicable limitations.' Three gates run in order — the IRC 1366(d) basis limit "
            "(stock plus loans YOU made to the corporation; use Form 7203, S Corporation Shareholder "
            "Stock and Debt Basis Limitations; disallowed amounts carry forward indefinitely), then "
            "at-risk (Form 6198), then passive activity. Box 16 code D distributions REDUCE that "
            "basis, and a distribution beyond basis is gain, which is why item I (loans from "
            "shareholder) and box 16 have to be read together rather than skipped as boilerplate. "
            "Enter losses with a leading MINUS SIGN — a parenthesized reading is flagged invalid on "
            "purpose. Boxes 13, 15, 16 and 17 carry CODE LETTERS whose amounts live on an attached "
            "statement: record the codes and read the statement, never total them blind. A checked box "
            "14 means a Schedule K-3 with international items is attached and must be read too. "
            "A checked box 18 ('More than one activity for at-risk purposes') or box 19 ('More than one "
            "activity for passive activity purposes') "
            "means the single figures on this face are AGGREGATES of separate activities that must be "
            "split per the attached statement before any limitation is applied. Gain or loss on "
            "selling the stock itself 'may be net investment income under section 1411' (Form 8960) "
            "and is not on this form. S-corp K-1s commonly arrive on extension (September): confirm "
            "the filing is not waiting on one before calling the document inventory complete."
        ),
        boxes=[
            _b("final_k1", "Header — Final K-1", "checkbox"),
            _b("amended_k1", "Header — Amended K-1", "checkbox"),
            _b("corporation_ein", "Part I item A — Corporation's employer identification number", "ein", required=True),
            _b("corporation_name", "Part I item B — Corporation's name, address, city, state, and ZIP code", "text"),
            _b("irs_center", "Part I item C — IRS Center where corporation filed return", "text"),
            # "money", not "int", for every share count on this form: fractional
            # shares are possible and an int box would reject a correct reading
            # (the Form 3922 box 6 precedent).
            _b("d_shares_beginning", "Part I item D — Corporation's total number of shares, beginning of tax year", "money"),
            _b("d_shares_end", "Part I item D — Corporation's total number of shares, end of tax year", "money"),
            _b("shareholder_tin", "Part II item E — Shareholder's identifying number", "tin", required=True),
            _b("shareholder_name", "Part II item F1 — Shareholder's name, address, city, state, and ZIP code", "text"),
            _b("f2_responsible_tin", "Part II item F2 — If the shareholder is a disregarded entity, trust, estate, or nominee: TIN of the person responsible for reporting", "tin"),
            _b("f2_responsible_name", "Part II item F2 — Name of the person responsible for reporting", "text"),
            _b("f3_entity_type", "Part II item F3 — What type of entity is this shareholder?", "text"),
            # "text": a percentage, as with Form 1042-S box 3b (tax rate).
            _b("g_allocation_percentage", "Part II item G — Current year allocation percentage", "text"),
            _b("h_shares_beginning", "Part II item H — Shareholder's number of shares, beginning of tax year", "money"),
            _b("h_shares_end", "Part II item H — Shareholder's number of shares, end of tax year", "money"),
            _b("i_loans_beginning", "Part II item I — Loans from shareholder, beginning of tax year", "money"),
            _b("i_loans_end", "Part II item I — Loans from shareholder, end of tax year", "money"),
            _b("1", "Box 1 — Ordinary business income (loss)", "money"),
            _b("2", "Box 2 — Net rental real estate income (loss)", "money"),
            _b("3", "Box 3 — Other net rental income (loss)", "money"),
            _b("4", "Box 4 — Interest income", "money"),
            _b("5a", "Box 5a — Ordinary dividends", "money"),
            _b("5b", "Box 5b — Qualified dividends", "money"),
            _b("6", "Box 6 — Royalties", "money"),
            _b("7", "Box 7 — Net short-term capital gain (loss)", "money"),
            _b("8a", "Box 8a — Net long-term capital gain (loss)", "money"),
            _b("8b", "Box 8b — Collectibles (28%) gain (loss)", "money"),
            _b("8c", "Box 8c — Unrecaptured section 1250 gain", "money"),
            _b("9", "Box 9 — Net section 1231 gain (loss)", "money"),
            _b("10", "Box 10 — Other income (loss) (code letters; amounts on the attached statement)", "text"),
            _b("11", "Box 11 — Section 179 deduction", "money"),
            _b("12", "Box 12 — Other deductions (code letters; amounts on the attached statement)", "text"),
            _b("13", "Box 13 — Credits (code letters; amounts on the attached statement)", "text"),
            _b("14", "Box 14 — Schedule K-3 is attached if checked", "checkbox"),
            _b("15", "Box 15 — Alternative minimum tax (AMT) items (code letters)", "text"),
            _b("16", "Box 16 — Items affecting shareholder basis (code letters; code D is distributions)", "text"),
            _b("17", "Box 17 — Other information (code letters)", "text"),
            _b("18", "Box 18 — More than one activity for at-risk purposes", "checkbox"),
            _b("19", "Box 19 — More than one activity for passive activity purposes", "checkbox"),
        ],
    ),
    DocSpec(
        # f1041sk1.pdf (Schedule K-1 (Form 1041) 2025), its own page-2 code map,
        # and i1041sk1.pdf (Instructions for Schedule K-1 (Form 1041) for a
        # Beneficiary Filing Form 1040 or 1040-SR), read 2026-08-27.
        kind="K-1 (1041)",
        title="Schedule K-1 (Form 1041) — Beneficiary's Share of Income, Deductions, Credits, etc.",
        source_url="https://www.irs.gov/instructions/i1041sk1",
        status_note=(
            "THIS IS THE ESTATE/TRUST K-1 AND ITS BOX NUMBERS SHARE ALMOST NOTHING WITH THE OTHER "
            "TWO — kind 'K-1' is the Form 1065 partnership layout and 'K-1 (1120-S)' the S "
            "corporation one. Here box 1 is INTEREST income (not ordinary business income, which is "
            "box 6), box 3/4a are the capital gains (boxes 8/9a on the 1065 K-1), and box 14 is "
            "'Other information' rather than self-employment earnings or a K-3 flag. THERE IS NO "
            "SCHEDULE K-3 CHECKBOX ON THIS FORM AT ALL: foreign taxes arrive as box 14 CODE B and go "
            "to Schedule 3 (Form 1040), line 1 or Schedule A, line 6 — this form is one of the payee "
            "statements that can qualify a filer for the IRC 904(j) de-minimis election, so run calc "
            "op foreign_tax_credit_election before starting Form 1116. USUALLY YOU DO NOT ATTACH IT, "
            "BUT SOMETIMES YOU MUST: 'Keep it for your records. Don't file it with your tax return, "
            "unless backup withholding was reported in box 13, code B' — and that code says 'attach a "
            "copy of Schedule K-1 (Form 1041) to your return'. TWO BOXES ARE PAYMENTS, NOT INCOME, "
            "and they are the ones most often missed because they sit inside a code box: box 13 code A "
            "'Credit for estimated taxes' goes on Form 1040 line 26 and code B 'Credit for backup "
            "withholding' on line 25c. Code A only exists because the fiduciary made an election — "
            "'Form 1041-T, Allocation of Estimated Tax Payments to Beneficiaries, must be timely "
            "filed by the fiduciary for the beneficiary to get the credit' — which is what item D "
            "records, so item D and box 13 must be read together. LOSSES GENERALLY DO NOT PASS "
            "THROUGH: read the printed captions, which say 'Net short-term capital gain' and 'Net "
            "long-term capital gain' with NO '(loss)' — unlike the 1065 and 1120-S K-1s. A trust's "
            "losses reach the beneficiary only on TERMINATION, through box 11, and only when item E "
            "('final Form 1041') is checked: 'Excess deductions on termination occur only during the "
            "last' tax year, and IRC 1212 lets 'the beneficiary succeeding to the property ... deduct "
            "any unused capital loss carryover'. The box 11 codes are the whole payload of a final-year "
            "K-1: A excess deductions - section 67(e) expenses (Schedule 1 (Form 1040), line 24k), B "
            "excess deductions - non-miscellaneous itemized deductions, C short-term capital loss "
            "carryover (Schedule D line 5), D long-term capital loss carryover (Schedule D line 12), "
            "E net operating loss carryover - regular tax (Schedule 1 line 8a), F net operating loss "
            "carryover - minimum tax (Form 6251 line 2f). Miss them and a terminating trust's "
            "deductions are lost for good. Other codes worth naming: box 9 directly apportioned "
            "deductions A depreciation, B depletion, C amortization; box 14 A tax-exempt interest "
            "(Form 1040 line 2a), E net investment income (Form 4952 line 4a), H adjustment for "
            "section 1411 net investment income (Form 8960 line 7), I section 199A information. Box "
            "10's estate tax deduction goes to Schedule A line 16, so it needs ITEMIZING to be worth "
            "anything. Boxes 5-8 land on Schedule E line 33 and the form itself warns that the face is "
            "not enough: 'A statement must be attached showing the beneficiary's share of income and "
            "directly apportioned deductions from each business, rental real estate, and other rental "
            "activity' — never total a code box blind. Item H distinguishes a DOMESTIC from a FOREIGN "
            "beneficiary, which changes the withholding and reporting regime entirely. Estate and "
            "trust K-1s are the latest-arriving documents in the calendar (a fiscal-year estate can "
            "issue one mid-year): confirm the filing is not waiting on one before calling the "
            "document inventory complete."
        ),
        boxes=[
            _b("final_k1", "Header — Final K-1", "checkbox"),
            _b("amended_k1", "Header — Amended K-1", "checkbox"),
            _b("estate_trust_ein", "Part I item A — Estate's or trust's employer identification number", "ein", required=True),
            _b("estate_trust_name", "Part I item B — Estate's or trust's name", "text"),
            _b("fiduciary_name", "Part I item C — Fiduciary's name, address, city, state, and ZIP code", "text"),
            _b("d_form_1041t_filed", "Part I item D — Check if Form 1041-T was filed", "checkbox"),
            _b("d_form_1041t_date", "Part I item D — Date Form 1041-T was filed", "text"),
            _b("e_final_form_1041", "Part I item E — Check if this is the final Form 1041 for the estate or trust", "checkbox"),
            _b("beneficiary_tin", "Part II item F — Beneficiary's identifying number", "tin", required=True),
            _b("beneficiary_name", "Part II item G — Beneficiary's name, address, city, state, and ZIP code", "text"),
            _b("h_domestic_beneficiary", "Part II item H — Domestic beneficiary", "checkbox"),
            _b("h_foreign_beneficiary", "Part II item H — Foreign beneficiary", "checkbox"),
            _b("1", "Box 1 — Interest income", "money"),
            _b("2a", "Box 2a — Ordinary dividends", "money"),
            _b("2b", "Box 2b — Qualified dividends", "money"),
            # The captions carry NO "(loss)" — that is the printed form, and the
            # reason is substantive (see status_note): losses pass through only on
            # termination, via box 11 codes C and D.
            _b("3", "Box 3 — Net short-term capital gain", "money"),
            _b("4a", "Box 4a — Net long-term capital gain", "money"),
            _b("4b", "Box 4b — 28% rate gain", "money"),
            _b("4c", "Box 4c — Unrecaptured section 1250 gain", "money"),
            _b("5", "Box 5 — Other portfolio and nonbusiness income", "money"),
            _b("6", "Box 6 — Ordinary business income", "money"),
            _b("7", "Box 7 — Net rental real estate income", "money"),
            _b("8", "Box 8 — Other rental income", "money"),
            _b("9", "Box 9 — Directly apportioned deductions (code letters; A depreciation, B depletion, C amortization)", "text"),
            _b("10", "Box 10 — Estate tax deduction", "money"),
            _b("11", "Box 11 — Final year deductions (code letters; amounts on the attached statement)", "text"),
            _b("12", "Box 12 — Alternative minimum tax adjustment (code letters)", "text"),
            _b("13", "Box 13 — Credits and credit recapture (code letters; A estimated taxes, B backup withholding)", "text"),
            _b("14", "Box 14 — Other information (code letters)", "text"),
        ],
    ),
]

DOC_SPECS: dict[str, DocSpec] = {s.kind: s for s in _SPECS}


class ExtractedField(BaseModel):
    """One box after structuring: typed value (or None), status, and provenance."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    type: FieldType
    value: Any = Field(default=None, description="Coerced value, or None when the box was not read.")
    raw: Any = Field(default=None, description="The exact reading the agent passed, before coercion.")
    status: Literal["ok", "missing", "invalid"] = "ok"
    provenance: Provenance


class ExtractedDocument(BaseModel):
    """A structured, provenance-tagged document reading for the confirm step."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    file: str
    page: int | None = None
    title: str
    citation: dict[str, str]
    fields: list[ExtractedField]
    gaps: list[str] = Field(default_factory=list, description="Required boxes not read (or read as invalid).")
    unexpected: list[str] = Field(default_factory=list, description="Keys the agent passed that aren't on this form.")
    caveat: str


_MONEY_RE = re.compile(r"[,$\s]")
_DIGITS_RE = re.compile(r"\D")


def _coerce(value: Any, type_: FieldType) -> tuple[Any, bool]:
    """Coerce a raw reading to its type. Returns (coerced, ok). Empty → (None, True)."""
    if value is None:
        return None, True
    if isinstance(value, str) and value.strip() == "":
        return None, True
    try:
        if type_ == "money":
            cleaned = _MONEY_RE.sub("", str(value))
            if cleaned in ("", "-", "+"):
                # A non-blank reading that is only currency punctuation ("-", "$", ",")
                # is a misread, not an empty box — flag invalid so it can't masquerade
                # as a confirmed blank and slip past the required-gap check.
                return value, False
            return str(Decimal(cleaned)), True
        if type_ == "int":
            cleaned = _MONEY_RE.sub("", str(value))
            if cleaned in ("", "-", "+"):
                return value, False
            dec = Decimal(cleaned)
            if dec != dec.to_integral_value():
                return value, False  # a fractional reading of an int box is a misread, not a truncation
            return int(dec), True
        if type_ in ("ein", "ssn", "tin"):
            digits = _DIGITS_RE.sub("", str(value))
            if type_ == "ssn" and len(digits) != 9:
                return str(value), False
            if type_ == "ein" and len(digits) != 9:
                return str(value), False
            if type_ == "tin" and len(digits) != 9:
                return str(value), False
            if type_ == "ein":
                return f"{digits[:2]}-{digits[2:]}", True
            return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}", True
        if type_ == "state":
            s = str(value).strip().upper()
            return s, len(s) == 2 and s.isalpha()
        if type_ == "checkbox":
            token = str(value).strip().lower()
            if token in ("x", "true", "yes", "y", "1", "checked", "on"):
                return True, True
            if token in ("false", "no", "n", "0", "off", "unchecked", "blank"):
                return False, True
            # An unrecognized reading is NOT silently treated as unchecked — that
            # would assert a value the agent never read. Surface it as invalid.
            return value, False
        return str(value), True
    except (InvalidOperation, ValueError):
        return value, False


def list_document_kinds() -> list[dict[str, Any]]:
    """The supported document kinds and their box layouts (for the agent to fill)."""
    return [
        {
            "kind": s.kind,
            "title": s.title,
            "source_url": s.source_url,
            "boxes": [{"key": b.key, "label": b.label, "type": b.type, "required": b.required} for b in s.boxes],
        }
        for s in _SPECS
    ]


def extract_document(
    path: str,
    kind: str,
    fields: dict[str, Any],
    page: int | None = None,
) -> ExtractedDocument:
    """Structure + validate an agent's reading of one tax document.

    Args:
        path: workspace-relative path to the source document (becomes provenance).
        kind: one of :data:`DOC_SPECS` (e.g. ``"W-2"``, ``"1099-INT"``, ``"1042-S"``).
        fields: the agent's box→reading map (box key → value); omit / None = not read.
        page: 1-based page of the document the reading came from, when known.

    Returns:
        An :class:`ExtractedDocument`: every documented box, typed and tagged with
        ``document`` provenance, plus the gaps (required boxes not read) and any
        unexpected keys. Nothing is inferred — unread boxes are ``None``.

    Raises:
        ValueError: if ``kind`` is not a supported document type.
    """
    spec = DOC_SPECS.get(kind)
    if spec is None:
        raise ValueError(
            f"unsupported document kind {kind!r}; supported: {sorted(DOC_SPECS)}. "
            "Use list_document_kinds() for each form's box layout."
        )
    if page is not None and page < 1:
        raise ValueError("page must be a 1-based page number (>= 1), or None when unknown")
    fields = fields or {}
    prov = Provenance.document(file=path, page=page)
    out_fields: list[ExtractedField] = []
    gaps: list[str] = []
    known_keys = {b.key for b in spec.boxes}

    for box in spec.boxes:
        raw = fields.get(box.key)
        coerced, ok = _coerce(raw, box.type)
        if coerced is None and (raw is None or (isinstance(raw, str) and raw.strip() == "")):
            status = "missing"
        elif not ok:
            status = "invalid"
        else:
            status = "ok"
        out_fields.append(
            ExtractedField(key=box.key, label=box.label, type=box.type, value=coerced, raw=raw, status=status, provenance=prov)
        )
        if box.required and status != "ok":
            gaps.append(box.key)

    unexpected = sorted(k for k in fields if k not in known_keys)
    caveat = (
        "Extraction structures what was read from the document — confirm every value against the "
        "paper form before it is used. Boxes not read are blank (None), never inferred; a value shown "
        "as 'invalid' did not match the expected type and must be corrected; required boxes that are "
        "blank are listed in 'gaps'."
    )
    if spec.status_note:
        caveat = f"{caveat} {spec.status_note}"
    return ExtractedDocument(
        kind=spec.kind,
        file=path,
        page=page,
        title=spec.title,
        citation={"source": spec.title + " (box layout)", "url": spec.source_url},
        fields=out_fields,
        gaps=gaps,
        unexpected=unexpected,
        caveat=caveat,
    )
