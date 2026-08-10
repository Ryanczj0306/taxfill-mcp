# Tax situation self-report worksheet (English — canonical)

> **What this is.** A fill-in-the-blank worksheet a tax-inexperienced user can complete
> *before* (or during) the agent interview, so the agent gets date-ranged facts instead of
> one-word answers. Sourced from the 2026-08-04 real session (see
> [`FIELD_NOTES.md`](FIELD_NOTES.md) — gap N-1/N-2/N-3). Localizations:
> [`INTAKE_WORKSHEET.zh-CN.md`](INTAKE_WORKSHEET.zh-CN.md). Both are emitted at runtime by
> `intake_checklist` via `taxfill_core.worksheet` (this file is sync-tested against that
> module).

**Three rules that matter more than the tables:**

1. **If you don't know, write "don't know."** Never guess. A guessed number gets copied
   onto a real form, which is far more dangerous than a blank.
2. **Everything about status or address gets a DATE RANGE**, never a single word.
   "I'm in California" and "I moved from WA to CA on March 1" are two completely
   different tax returns.
3. **One worksheet per person.** Two unmarried people (even living together, sharing
   expenses) are **two separate taxpayers** under U.S. tax law — each files their own
   return; they cannot file jointly. Fill in one worksheet each.

---

## Part 0 · What are you here to do

- [ ] File taxes for a year (which year: ______)
- [ ] Back-file earlier years (which years: ______)
- [ ] **Budget / plan a future year's taxes** (which year: ______) ← this produces no
      mailable form, only numbers

Privacy: **budgeting needs NO SSN / ITIN, no bank account number, no street number.**
Provide those only when a form is actually being prepared for mailing — and even then,
leaving them blank to hand-write is recommended.

---

## Part 1 · Identity and visa timeline

Citizenship (passport country): ____________　　First date you ever entered the U.S.: __________

U.S. citizen or green-card holder?　□ Yes　□ No

**Visa timeline** — starting from your first U.S. entry, in order, missing nothing.
**A change of status, a change of school, starting OPT, an H-1B taking effect — each gets
its own row.**

| # | Status (be specific) | Start date | End date ("present" if ongoing) | What you were doing |
|---|---|---|---|---|
| 1 | e.g. F-1 (enrolled — bachelor's/master's/PhD) | 2021-08-20 | 2025-05-15 | studying |
| 2 | e.g. F-1 OPT (12-month work authorization) | 2025-06-01 | 2026-05-31 | working full-time |
| 3 | e.g. F-1 STEM OPT (24-month extension) | | | |
| 4 | e.g. cap-gap (bridge after H-1B selection) | | | |
| 5 | e.g. H-1B (start = the I-797 start date) | 2026-10-01 | present | working full-time |
| 6 | | | | |

**Why this much detail:** during F-1 (including OPT/STEM OPT), your U.S. days do **not**
count toward the Substantial Presence Test, and your wages are **not subject to Social
Security / Medicare (FICA, 7.65%)**; the day an H-1B takes effect, both flip at once.
So "F-1 to H-1B" as five words computes to nothing — the whole difference is in the dates.

Commonly confused points — please confirm as you go:
- OPT belongs to **F-1**; it is not a separate visa.
- H-1B keys on the **start date on the I-797 approval notice** — not the day you heard,
  and not your onboarding date.
- If you **left the U.S.** during any period (home visits, travel), Part 2 must say so.

## Part 2 · Days in the U.S.

| Year | Total days in the U.S. that year (an estimate is fine — mark it "approx.") |
|---|---|
| Target year (______) | |
| Prior year (______) | |
| Two years prior (______) | |

Total **calendar years** you have held F-1 / J-1 student status (a stay spanning a year
boundary counts as two, even one day): ______

> These numbers decide whether you are a nonresident (1040-NR), a resident (1040), or
> dual-status (both). The student exemption has a cap (generally 5 calendar years) —
> after that, F-1 days start counting.

## Part 3 · Household (as of December 31 of the target year)

On that day you were:　□ Unmarried　□ Married (date: __________)　□ Widowed

If you live with a partner but are **not married**:
- Their name/alias: __________　Their status (visa + whether on OPT): __________
- → **They fill in their own copy of this worksheet**; you each file your own return.
  You **cannot** claim them as a dependent (a nonresident generally fails the dependent
  residency requirement), and you cannot file jointly.

Any children / dependents to claim?　□ No　□ Yes (name, birth year, SSN/ITIN or not: ______)

Marrying (or married) during the target year?　□ No　□ Yes (date __________)
> This one moves real money: after marriage, if both spouses are nonresidents the default
> is separate 1040-NRs; but where eligible, the §6013(g)/(h) election lets both file
> jointly as residents (MFJ) — different standard deduction, different brackets.

## Part 4 · States (the part most often missed — and most often overpaid)

**Do not write just one state name.** Cut the target year, January 1 through December 31,
into **segments**, one row each:

| From | To | I lived in (state + city) | I worked in (state) | Remote? | Employer/school's state |
|---|---|---|---|---|---|
| 01-01 | | | | □ Y □ N | |
| | | | | □ Y □ N | |
| | 12-31 | | | □ Y □ N | |

Confirm each trigger (tick them — this is how things stop getting missed):
- [ ] **Moved across state lines** during the year? Move-out/move-in dates: __________
- [ ] Living in state A while **working remotely for a company in state B**?
      (This often triggers returns in BOTH states.)
- [ ] **Business travel / short assignment** in another state over ~30 days? Which state,
      how many days: __________
- [ ] School in one state, internship in another?
- [ ] The state you lived in and **W-2 Box 15 (State) disagree**?
- [ ] Any period **outside the U.S.**? From/to: __________
- [ ] No-income-tax states (WA / TX / FL / NV / SD / WY / AK / TN / NH) still get their
      real date ranges — because the **other** segment in a taxing state means you file
      that state.

## Part 5 · Income and tax documents

**One row per W-2** (one per employer; a job-change year usually has 2+):

| Employer | Work state | Period | Box 1 wages | Box 2 fed withheld | Box 4 Social Security | Box 6 Medicare | Box 15 state | Box 17 state withheld |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
| | | | | | | | | |

> **Boxes 4 / 6 matter especially**: if an employer withheld FICA in error during OPT,
> that money comes back via Form 843 + 8316; if withholding did NOT start once H-1B took
> effect, the payroll needs fixing. For budgeting, these two boxes directly set take-home.

Other income (amount if any; "none" if none; "don't know" if unsure):

| Type | Document | Amount | Notes |
|---|---|---|---|
| Bank interest | 1099-INT | | |
| Dividends | 1099-DIV | | |
| Stock / crypto sales | 1099-B | | cost basis, buy/sell dates |
| RSU / option vests or exercises | usually inside the W-2 | | vest dates, share counts |
| Freelance / gig work | 1099-NEC | | |
| Tuition | 1098-T | | do scholarships exceed tuition? |
| Student-loan interest | 1098-E | | |
| Scholarship / fellowship / RA-TA exempt portion | 1042-S | | income code, withholding rate |
| Marketplace health coverage (healthcare.gov / state exchange) | 1095-A | | **always disclose it** — omitting it freezes the refund |
| Foreign income / foreign accounts | | | |

## Part 6 · Tax already paid (required to compute owe-vs-refund)

- Federal withheld (so far / projected full-year): __________
- State withheld: __________
- Quarterly estimated payments you made (Form 1040-ES): __________ (dates + amounts)
- Last year (____) you filed:　□ 1040　□ 1040-NR　□ didn't file
- Last year's AGI: __________　Last year's total tax: __________
  > These two numbers drive the §6654 safe harbor (generally: prepay 100% of last year's
  > tax, or 90% of this year's, and there is no underpayment penalty). For budgeting this
  > is the "should I pay in more now?" test.

## Part 7 · Forward-looking facts (budgeting only)

- Target-year salary / hourly rate + expected bonus: __________
- 401(k) contribution rate or amount: __________　　□ Roth　□ Traditional (pre-tax)
- HSA contribution: __________
- Expected stock sales / RSU vests: __________
- Moving (across state lines)? __________
- Status changing (H-1B start date, green-card queue, departure)? __________

---

## After you fill this in

Paste the worksheet to the agent (or save it as a file for the agent to read). The agent
will:

1. Use `residency` to classify NRA / RA / dual-status from your **visa timeline + day
   counts**, showing its reasoning;
2. Use `state_scope` to list which states you file and in what role (resident /
   nonresident / part-year) from your **state segments**;
3. Use `calc` + `estimate_refund` to produce cited numbers (**always labeled ESTIMATE**);
4. List anything missing as a **gap — it will not guess for you**.

⚠️ This toolchain produces a **review draft, not tax advice**; it does not e-file for
you. You verify every number, sign, and mail it yourself.
