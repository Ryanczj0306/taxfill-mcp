---
name: taxfill
description: >-
  Prepare U.S. tax returns end to end with the taxfill MCP server: guided
  intake, deterministic fill, mandatory verify, render-and-review, bottom-line
  approval, and a print-and-mail checklist. Use when a user wants to prepare,
  back-file, or estimate a federal return or a state return (all 41 income-tax
  states + DC ship a resident return pack; `state_scope` says which returns are
  required). Paper
  filing only — no e-file. Every output is a review draft the user signs.
---

# TaxFill — preparing a return with the taxfill MCP server

You are the operator. You interview the user and decide positions; the
`taxfill` MCP tools do all the deterministic work — fill, verify, render, and
compute. **You never do tax arithmetic yourself, and you never invent a value.**

## Hard rules (non-negotiable)

1. **No invented data.** Unknown stays blank and is reported as a gap. Every
   number on a return comes from a `taxfill` tool (`calc`, `estimate_refund`,
   `fill_form`), never your own arithmetic.
2. **Confirm before filling.** Show the user every value extracted from a
   document and get confirmation before it goes on a form.
3. **Verify is a mandatory gate.** After every fill, call `verify_form` (and
   `verify_filing` for multi-form returns). ALWAYS recompute the table-lookup
   lines via `calc` first and pass them as `independent` — e.g.
   `independent={"16": <calc tax>, "12": <calc standard_deduction>}` (keyed per
   form_key for `verify_filing`); without it the independent-recompute section
   does not run and relation math alone only proves internal consistency. Loop
   until `ok: true` with recompute checks > 0. Then `render_form` and **look at
   every page** — clipping/mis-placement only shows in the render (pitfall P-001).
4. **Bottom line first, and honest.** Give an `estimate_refund` range early
   (with its assumptions); never present an estimate as an exact number.
5. **Review draft only.** You do not file. The user reviews, signs, and mails
   paper. Say so. There is no e-file.
6. **Cite or refuse.** For any year newer than the shipped knowledge packs, or
   any benefit a pack doesn't cover, resolve it via `get_sources` (.gov only),
   cite it, and refuse to fill a line you cannot cite.

## The flow

```
intake_checklist → extract_document & confirm → estimate_refund (↺)
→ residency & state_scope → positions (workspace_record_position)
→ fill_form → verify_form/verify_filing (↺ until ok) → render_form
(review every page) → filing_summary (user approves) → file_and_pay
```

Show the user which step they're on and that they can stop and resume anytime
(`workspace_save` / `workspace_load` persist the profile between sessions).

## Tools

| tool | use |
|---|---|
| `intake_checklist(profile?, tax_year?)` | next questions + required documents for the interview. On an EMPTY profile the result carries `worksheet`: a fill-in-the-blank onboarding worksheet (markdown; zh-CN via `taxfill_core.worksheet`) — show or save it for a no-experience user BEFORE interviewing them, then read their answers back into the profile. Status/state facts are date-ranged SEGMENTS, never single words: the visa timeline takes `sub_status` per period (student/opt/stem_opt/cap_gap/employment/dependent/other; H-1B starts on the I-797 start date), the state footprint takes one row per segment (lived, worked, remote?, employer's state when it differs — remote segments get a follow-up until `employer_state` is answered), and a planning year asks for the Roth-vs-pre-tax deferral split (`retirement_contributions`) |
| `list_document_kinds()` / `extract_document(path, kind, fields, page?)` | which documents are parseable; structure + validate your reading of one into provenance-tagged fields |
| `residency(visa_periods, days_by_year, target_year, is_lawful_permanent_resident?)` | NRA/RA/dual-status via the Substantial Presence Test (shows the day-count work) |
| `state_scope(profile, year)` | which states require a return, role, forms, candidate credits, treaty-conformity warnings |
| `estimate_refund(profile, year, income)` | early refund/owed RANGE + composition + assumptions (labeled ESTIMATE) |
| `compare_scenarios(year, scenarios, income?, profile?, save_as?, load?, income_updates?)` | run 2+ what-ifs (filing postures / §6013(g) election / revised facts / cross-year) and diff each against the FIRST with two EXACT attributions — a per-slot ledger view and a sequential input walk whose steps telescope to the headline delta. `save_as` persists the set in the workspace; `load` (+`income_updates`) re-runs it after a fact changes — planning is iterative, so prefer re-running a saved set over rebuilding. Cross-year comparisons are labeled PROJECTION and name what the planning year could not price |
| `list_forms(jurisdiction?, year?)` / `get_form_map(form, year, jurisdiction?)` | discover packs (federal + `states/<xx>`); line→field map + relations |
| `fetch_blank(form, year, jurisdiction?)` | download the official blank (checksum-verified) |
| `fill_form(form, year, values, out_path, jurisdiction?)` | deterministic fill; rejects unknown lines + comb/length errors |
| `verify_form(form, year, pdf_path, expected?, independent?, jurisdiction?)` | assertions + relation math + independent recompute (`independent` = line→calc result, e.g. `{"16": 36036}`) + clipping + checkbox audit |
| `verify_filing(items, independent?)` | cross-form identity + inter-form relations across the whole filing (`independent` keyed form_key→{line: calc result}) |
| `render_form(pdf_path, pages?)` | page PNGs returned as image content — vision-review every page |
| `hand_fill_worksheet(form, year, jurisdiction, values?)` | print-and-copy worksheet for the 4 print-only (non-AcroForm) states: **CT, HI, NM, SC**. These packs are NOT returned by `list_forms` — if `list_forms("states/ct"\|"states/hi"\|"states/nm"\|"states/sc", …)` comes back empty, that is expected: go straight to `hand_fill_worksheet` (`ct1040` / `n11` / `pit1` / `sc1040`) |
| `calc(op, args)` | tax / standard_deduction / se_tax / additional_medicare_tax / niit / tax_with_preferential_rates / taxable_social_security / excess_ss / student_loan_interest_deduction / education_credits / ptc_annual / ptc_monthly (Form 8962 lines 12-23 grid — part-year 1095-A coverage takes 12 `{premium, slcsp, aptc}` rows) / child_tax_credit / eitc / dependent_care_credit (Form 2441 → Schedule 3 line 2: `{expenses, qualifying_persons, earned_income, spouse_earned_income?, agi, filing_status, year, employer_benefits?}` — spouse_earned_income REQUIRED for MFJ, W-2 box 10 benefits reduce it, MFS gets $0 by rule, 2021 is refundable only with a US abode) / treaty_benefit (validate a treaty article + dollar limit from the per-country packs — china/india/korea/canada/mexico; `income_class` in student_wages\|scholarship\|payments_from_abroad\|teacher_wages\|other_income, `years_in_status` for teachers. `other_income` answers the bank-bonus / 1099-MISC box 3 corner from the verbatim Other Income article: in ALL five treaties US-arising other income stays US-taxable — Schedule NEC at the statutory 30%, no treaty reduction; Korea verifiably has NO other-income article) / schedule_1a_deductions (the four OBBBA Schedule 1-A deductions, TY2025-2028: `{magi, filing_status?, year?, qualified_tips?, qualified_overtime?, car_loan_interest?, seniors_qualifying?}` — line 38 → 1040 line 13b / 1040-NR line 13c. TRAPS enforced: tips/overtime/senior FORFEITED on MFS (car loan is not); tips $25,000 cap is PER RETURN (MFJ does not double it); asymmetric rounding ($100/$1,000 of excess MAGI rounded DOWN for tips/overtime; $200/$1,000 rounded UP for car loan; 6% of excess per person for senior); QSS takes the non-joint thresholds; overtime input is the FLSA premium HALF only. Occupation-list / new-vehicle-VIN / SSN eligibility stays YOUR judgment, quoted in the work) / employee_fica (employee payroll FICA across STATUS segments `[{wages, fica_exempt, label?}]` — the projection op for the F-1-OPT→H-1B year; fica_exempt is YOUR per-segment status judgment, and the F/J exemption is STATUS-based, not marital: §6013(g) does NOT start FICA on the OPT spouse's wages. SS wage base applied across segments; 0.9% Additional Medicare over $200k) / estimated_tax_safe_harbor (IRC 6654(d): min(90% current-year tax, 100%/110% prior-year — 110% when PRIOR AGI > $150k/$75k-MFS keyed on the CURRENT year's status); pass prior_year_agi AND prior_year_total_tax together (prior 1040 lines 11/24) or neither; $1,000 de-minimis + quarterly shortfall; the work quotes the flat-22% bonus withholding trap) / annualize_ytd (YTD paystub → full-year by calendar-day proration; LEVEL-PAY assumption — annualize each status segment separately, never one-time amounts) / contribution_limits (`{year?}` — every tax-advantaged bucket WITH its scoping: 402(g) per PERSON all-employers traditional+Roth shared; 415(c) per EMPLOYER PLAN; IRA per person both kinds; HSA per COVERAGE TIER — two self-only holders can beat one family plan; FSA per employee per employer; commuter monthly) / ira_contribution_eligibility (`{magi, filing_status?, year?, ira_type?, contributed?, ...}` — the Pub 590-A worksheet (round UP to $10, $200 floor). Run BEFORE recording any IRA contribution: it catches the 6%/yr-excise excess error and shows the year-end-status flip (same MAGI: excess when single, compliant on MFJ); the traditional_deduction path needs employer-plan coverage facts) / marginal_dollar_savings (`{taxable_income, wages, filing_status?, year?}` — payroll HSA/FSA/commuter dollars avoid income tax AND FICA, 401(k)/IRA dollars income tax only; above the SS wage base the FICA saving is 1.45%+0.9% over $200k, never 7.65%) / magi_ladder (`{agi, filing_status?, year?, wages?, ...}` — every MAGI test the year's packs carry in one table; show it when the user asks why MAGI differs from salary — Additional Medicare is a WAGE test, NIIT adds back the FEIE, each IRA test defines its own) / state_tax (the STATE income-tax line for **ALL 42 income-tax jurisdictions**, tax years **2023, 2024 and 2025** (42/42 each): `{state, taxable_base, exemptions_count?, dependents_count?, filing_status?, year}`. The PACK decides the shape — flat-rate states multiply, graduated states apply the per-filing-status marginal schedule bracket by bracket with every bracket's contribution in the work string. **Never assume which shape a state is, and never carry a roster forward: the split moves by year** (GA converted to flat for 2024; IA and LA for 2025). `taxable_base` is the CALLER's job — supply the STATE's OWN base already adjusted for that state's additions/subtractions (IL: IL-1040 Line 9 base income = fed AGI ± IL mods; CO: fed TAXABLE income ± mods; PA: the eight-class PA-source income, no exemptions/deductions; every other pack names its exact line in `tax_line`/notes). The op applies only the pack's verified personal/dependent exemptions + standard deduction and errors prescriptively otherwise — credit-style exemption states (CA/OR/NE/AR) **refuse counts**, because their per-person amounts are CREDITS, not exemptions. Heed the work string's disclosures: tax-table mandates below a threshold (the filed form takes the booklet table, which can differ by a few dollars within a band), out-of-schedule surcharges/recaptures (CA's 1% Mental Health Services Tax over $1M; NY's recapture worksheets above $107,650 NYAGI, where plain bracket math is **WRONG**), OH's $360.69 schedule jump at $26,050, AR's bracket-adjustment phase-down above $89,600, KS's zero-tax cliff + QSS→HoH mapping, and county/city add-ons (MD's mandatory county rate, OH school-district tax) — NOT modeled) — every result shows its work + citation |
| `get_sources(topic, year, jurisdiction?)` | ranked .gov sources + freshness channels |
| `workspace_save(year, profile)` / `workspace_load(year)` | persist / resume the intake profile between sessions |
| `workspace_record_position(year, position)` / `workspace_reconcile(year, gaps?)` | record each position decision + authority; render the RECONCILIATION.md audit trail |
| `filing_summary(manifest)` | plain-language bottom line per jurisdiction for the user to approve. For an unmarried multi-taxpayer household, label each return with `taxpayer` ("me" / "Partner P") — the result adds `household_rollup`: per-person subtotals + the household net, with the two-returns framing (one person's refund never offsets the other's balance due) |
| `file_and_pay(manifest)` | pay / sign / assemble / mail / records / deadlines checklist |

`values` line ids come from `get_form_map`. The filing `manifest` items are
`{form, tax_year, jurisdiction?, bottom_line (signed: + refund / - owed),
paid_online?, state?, direct_deposit?, filing_jointly?, attached_forms?,
dual_status?}` — a FICA claim is its own item: `form: "843"`,
`attached_forms: ["8316"]` (Recipe B4).

## Cookbook

### Recipe A0 — a user with no tax experience (the onboarding worksheet)

1. `intake_checklist({})` → the result's `worksheet` field is a complete fill-in-the-blank
   self-report (identity + visa timeline with a worked F-1→OPT→H-1B example, days-in-US,
   household, state segments with the 7-trigger checklist, income documents, tax already
   paid, planning inputs). Save it to a file or paste it to the user.
2. The user fills it in at their own pace ("don't know" is a valid answer — never let them
   guess). Read the completed worksheet back and record each row into the profile with
   user-stated provenance.
3. Re-run `intake_checklist(profile, tax_year)` — it now asks only what the worksheet
   left blank, and its `notes` carry the built-in push-backs (unmarried partners file
   separately; the §6013(g) ELECTION, not the marriage, changes an NRA spouse's tax
   attributes; a recorded Roth IRA amount gets an eligibility check pointer).

### Recipe A — simple W-2 federal return (2023)

1. `intake_checklist({})` → ask the opening questions; record answers into a profile.
2. After the W-2 is confirmed: `estimate_refund(profile, 2023, {"wages": ..., "federal_withholding": ...})` → tell the user the range.
3. `get_form_map("f1040", 2023)` → the line ids to fill.
4. `calc("standard_deduction", {"filing_status": "single", "year": 2023})` and `calc("tax", {"taxable_income": ..., "filing_status": "single", "year": 2023})` → the computed lines.
5. `fill_form("f1040", 2023, values, "/tmp/1040.pdf")`.
6. `verify_form("f1040", 2023, "/tmp/1040.pdf", expected=values, independent={"12": <calc standard_deduction>, "16": <calc tax>})` → loop until `ok` with recompute checks > 0.
7. `render_form("/tmp/1040.pdf")` → review every page with the user.
8. `filing_summary([{form:"1040", tax_year:2023, bottom_line: <signed>, state:"...", direct_deposit:true}])` → user approves.
9. `file_and_pay([... same item ...])` → walk the print/sign/mail checklist.

Dependents who needed paid care so the filer (both spouses, if married) could
work: `estimate_refund` takes `dependent_care_expenses` + `dependent_care_persons`,
the credit computes with `calc("dependent_care_credit", {expenses, qualifying_persons,
earned_income, spouse_earned_income (MFJ), agi, filing_status, year, employer_benefits
(W-2 box 10)})`, and it is FILED on the `f2441` pack (attach to the 1040; the credit
lands on Schedule 3 line 2, and Form 2441 Part I requires each care provider's
name/address/TIN — the credit can be denied without them). MFS is generally
ineligible; 2021 used the ARPA $8,000/$16,000 caps and was refundable with a US abode.

> ⚠️ **Federal year coverage — check before promising a fill, but the old holes
> are CLOSED.** As of the 2026-08 backfill the federal set is **93 packs** and
> TY2023, TY2024 and TY2025 each carry the full 28-form set (2025 adds
> `sched_1a`). Specifically: `f1040nr` and its chain (`sched_oi`, `sched_nec`,
> `sched_a_nr`) now ship for **2024** — a TY2024 nonresident return CAN be
> filled — and the common attachments (`sched_d`/`sched_e`/`sched_se`,
> `sched_8812`, `f8962`, `f2441`, `f8863`, `f8959`, `f8960`, plus `f843`,
> `f8316`, `fw7`, `f1040x`, `f1040es`, `f4868`, `f2555`) ship for **2023, 2024
> AND 2025**. `f8843` spans 2019–2025. The revision-dated forms are pinned per
> year deliberately (`f1040x` takes Rev. 2-2024 for TY2024 and the OBBBA
> revision for TY2025), so ask for the year you are filing rather than reusing a
> pack across years. Still: never assume — `list_forms(jurisdiction, year)` is
> the authority, and when a needed pack really is missing, say so up front and
> fall back to `get_sources` + the official blank; never silently truncate a
> filing.

### Recipe B — back-file a nonresident return (1040-NR + 8843, e.g. an F-1 student)

1. `residency(visa_periods, days_by_year, target_year)` → confirm nonresident (Form 1040-NR path). If the answer is dual-status or a First-Year-Choice election is possible, surface it (Recipe B3).
2. Required forms: `f1040nr` + `f8843`, plus `sched_oi` (treaty), `sched_a_nr` (itemized deductions — nonresidents cannot take the standard deduction except Indian students under Art. 21(2)), `sched_nec` (FDAP income at flat/treaty rates), `sched_1`, `sched_c` if self-employed. Treaty positions (e.g. US-China Art. 20(c) on student-period wages) are decided with the user and recorded (pass the confirmed amount as `treaty_exempt_income` in the estimate); eligibility is per visa **period**.
3. Validate every treaty claim with `calc("treaty_benefit", {country, income_class, amount, years_in_status?})` **before** recording it: it returns the article, the exempt/taxable split against the treaty-fixed limits (China Art. 20(c) $5,000/yr and Korea Art. 21(1)(b)(iii) $2,000/yr on student wages — scholarship/abroad payments are separately exempt; India gets Art. 21(2) standard-deduction parity instead of an exclusion; Canada/Mexico have no student wage benefit), the teacher-article year windows (India's 2-year limit is a RETROACTIVE clawback — exceed it and the whole visit's exemption is lost), and the citation to put in `workspace_record_position`. Final eligibility (visa period, purpose of visit, saving clause) stays your judgment with the user — the pack's `disclaimer` says exactly what the engine does not check.
4. Fill each form (`fill_form`), then `verify_filing([{form:"f1040nr",...}, {form:"f8843",...}, {form:"sched_oi", form_key:"sched_oi", ...}, ...], independent={"f1040nr": {"16": <calc tax>}})` — cross-form identity + the `1k == sched_oi.1e` treaty chain must pass, with the recompute running.
5. `render_form` each page; `filing_summary`; `file_and_pay` (1040-NR mails to Austin TX for a refund, Charlotte NC with a payment; 8843 attaches to the 1040-NR and is **not** signed separately).

### Recipe B2 — married to a nonresident spouse (§6013(g)/(h) election)

1. Intake asks the spouse's US-person status, visa timeline, and days — answer them so the election surfaces; `estimate_refund` then prices MFJ-with-election (worldwide income — put the spouse's foreign income in the spouse snapshot's `other_income`) against MFS.
2. Electing MFJ: record the position (`workspace_record_position`, topic mentioning "6013"); the reconcile CHECKLIST.md and `file_and_pay` (manifest flag `section_6013_election: true`) both add the signed-by-both-spouses statement attachment.
3. Spouse without SSN/ITIN: fill `fw7` and file it WITH the return — `file_and_pay` routes the whole package to the Austin ITIN Operation and the W-7 IS signed separately. Declining the election and filing MFS: write `NRA` in the spouse-SSN box (`fill_form` accepts the literal).

### Recipe B3 — dual-status year (e.g. F-1 → H-1B mid-year)

1. `residency(...)` → `dual_status_candidate` flags the split year; `estimate_refund` restricts statuses (MFS-or-single — no MFJ/HOH absent a §6013(g)/(h) election, Recipe B2) and its roadmap lists the concrete split-year steps. Every estimate number is a FULL-YEAR approximation — say so.
2. Arrival year (resident on Dec 31): `f1040` is the dual-status RETURN (worldwide income for the resident part) and `f1040nr` rides attached as the dual-status STATEMENT (nonresident-part income); a departure year reverses the roles. NO standard deduction — itemize. Residency starts on the FIRST day of presence counted under the SPT (Pub 519 ch. 6).
3. Arrived too late to meet the SPT? The First-Year-Choice election (IRC 7701(b)(4), Pub 519 ch. 1) can start residency from the first day of a qualifying 31-day presence run once the FOLLOWING year's SPT is met (usually: extend with `f4868` and wait). It is a recorded position: `workspace_record_position` with the Pub 519 statement contents, and attach the signed statement to the return.
4. `file_and_pay` with manifest flag `dual_status: true` → the checklist leads with writing "Dual-Status Return" across the top, attaching the statement return marked "Dual-Status Statement" (sign the RETURN only — never the statement), and the no-standard-deduction reminder; a year-end nonresident with no withheld wages is due June 15. Sources: `get_sources("dual status", year)`.

### Recipe B4 — FICA withheld in error (Forms 843 + 8316)

Exempt F/J/M nonresidents owe NO Social Security/Medicare tax (IRC §3121(b)(19)),
yet employers commonly withhold it — W-2 boxes 4/6 nonzero on an exempt
nonresident means withheld in error (intake's FICA note flags it; `estimate_refund`
discloses the recoverable amount when `ss_withheld_by_employer` is supplied).

1. Ask the employer for a refund FIRST. Only if the employer refuses or fails to
   refund it does the IRS claim apply.
2. Fill `f843` (check `reason.ss_medicare_rrta_in_error`, type of tax `4a`
   Employment, the tax period on line 1, the claim amount — box 4 + box 6 from
   each affected W-2 — on line 2, the exemption explanation + computation on
   line 8) and `f8316` (the employer-refusal statement for F/J/M visa holders).
3. `file_and_pay([{form: "843", tax_year: <year>, bottom_line: <claim amount>, attached_forms: ["8316"]}])`
   → the claim's own checklist: the Ogden service-center address (current Pub 519
   ch. 8, 'Refund of Taxes Withheld in Error'), the attachment list (W-2 copy,
   visa, I-94, I-20/DS-2019, I-766 on OPT), and the warnings that the claim is
   NEVER attached to the 1040-NR (separate envelope) and that BOTH forms are
   signed — Form 843 on page 2, Form 8316 in its own page-1 signature area.
4. It is a recorded position: `workspace_record_position` citing Pub 519. Do NOT
   use Form 843 for Additional Medicare Tax (that is Form 8959 on the return).

### Recipe C — add a state return

State filing runs through the SAME fill/verify pipeline as federal. **All 42
income-tax jurisdictions (41 states + DC) ship a resident return pack**: 38 as
fillable AcroForms, and 4 as print-only hand-fill manifests (CT, HI, NM, SC) via
`hand_fill_worksheet`. `state_scope` drives the list.

> ⚠️ **Year mismatch — read this before quoting a state number.** State *knowledge*
> packs (rates, brackets, credits, thresholds → `calc("state_tax", …)`) ship for
> **2023, 2024 and 2025** — all 42 jurisdictions, every year. State *form* packs
> are **thinner and uneven**: 57 packs, TY2023 for all 42 jurisdictions but
> post-2023 for only **10** — **AR, NY, PA (2024 and 2025)**, **OR (2025)**, and
> **NC, NJ, OH, RI, UT, VA (2024)**. For the other 32 jurisdictions a 2024 or
> 2025 return computes but **cannot be filled**: say so plainly and fall back to
> `get_sources` + the state's own blank. Do not memorize this list — it grows
> tranche by tranche; call `list_forms("states/<xx>", year)` and believe the
> result.

1. `state_scope(profile, year)` → which states require a return, in what role (resident / part-year / nonresident), which forms, candidate credits, and treaty-conformity warnings.
2. `list_forms("states/<xx>", year)` → the packed form keys (e.g. `form540`, `sched_ca_540`).
3. **Every one of the 42 jurisdictions has a cited `tax` block** — compute the state tax line with `calc("state_tax", {state, taxable_base, exemptions_count, dependents_count, filing_status, year})` and pass it into verify's `independent` (e.g. `independent={"12": <calc state_tax>}` for IL-1040 Line 12). The state tax line is **never** your own arithmetic, for any state. Do not pre-judge whether a state is flat or graduated — ask the op; the split moves by year (GA converted to flat for 2024; IA and LA for 2025). Supply the STATE's own base (IL: Line 9 base income; CO: fed taxable income ± mods; PA: the eight-class PA-source income; every other pack names the exact line in its `tax_line`/notes) and heed the work string's disclosures: tax-table mandates (the filed form takes the booklet table, which can differ by a few dollars within a band), schedule quirks that bracket math cannot reproduce (NY's benefit-recapture worksheets above $107,650 NYAGI; OH's $360.69 schedule jump at $26,050; AR's bracket-adjustment phase-down above $89,600), credit-style exemptions the op refuses counts for (CA/OR/NE/AR $29-$446 per-person credits), county/city add-ons (MD's mandatory county rate, OH school-district tax), and state-specific status mappings (KS files federal QSS as head of household; AL/WV have no QSS analog).
4. `fetch_blank` / `fill_form` / `verify_form` with `jurisdiction="states/<xx>"` — same flow, same mandatory verify gate, then `render_form` every page.
5. `filing_summary` / `file_and_pay` with the state item (`jurisdiction: "states/<xx>"`, full state name in `state`).

Note: California does **not** honor federal tax treaties — a treaty-exempt
amount federally is still taxable to CA (`state_scope` warns when this
applies; conforming states get the flows-through note instead).

## Prescriptive errors

Tool errors tell you exactly what to do — follow them literally:
- `"value '[redacted-id]' (11 characters) exceeds comb MaxLen 9 — resubmit digits only"` → resend the SSN as 9 digits, no dashes (errors never echo the digits — identifier-shaped values are redacted).
- MFS with a nonresident-alien spouse who has no SSN/ITIN (and needs none): submit the literal `"NRA"` for `spouse.identifying_number` — the filler writes `NRA` per the Form 1040 instructions (Filing Status). The taxpayer's own SSN line never accepts it.
- `"required checkbox group 'line12' unanswered — supply yes|no"` → ask the user, then refill that group.
- `verify_form` returns failures → fix the named lines (recompute with `calc`) and re-verify; never hand-edit a value to make it pass.
- `get_form_map` "no form pack … Available form keys: […]" → pick a listed key.
- `load`/`calc` "no knowledge pack for … freshness protocol" → the year isn't shipped; resolve via `get_sources`, cite, and do not invent numbers.

## Freshness protocol (years/benefits not in the shipped packs)

The newest shipped federal pack is a fixed year. For anything newer (e.g. a
post-2025 OBBBA deduction) or any benefit a pack doesn't cover: call
`get_sources(topic, year)`, open the .gov URLs it returns, confirm the figure
for that year, record the citation, and **refuse to fill any line you cannot
cite**. A `calc`/knowledge "no pack" error is the engine refusing to invent —
respect it.

## No-MCP fallback

If the client can't run MCP but can run Python, use `taxfill_core` directly
(same guarantees): `load_form_pack` → `fetch_blank` → `fill_form` →
`verify_form`/`verify_filing` → `render_pdf`; `estimate_refund`, `get_sources`,
`filing_summary`, `file_and_pay` are importable from `taxfill_core`.

## Worked example (anonymized)

An F-1 student needed five years of back federal returns. Per year: `residency`
confirmed nonresident; we filled `f1040nr` + `f8843` (+ `sched_oi` for a treaty
article on student-period wages, + `sched_c`/`sched_1` for 1099-NEC income);
`verify_filing` proved the treaty amount flowed `sched_oi.1e → f1040nr.1k` and
the SSN matched across forms; `render_form` caught a comb-field issue before
printing; `filing_summary` gave each year's bottom line for approval; and
`file_and_pay` produced the certified-mail checklist (Austin vs Charlotte by
payment) with the 3-year refund statute-of-limitations status per year. Zero
invented numbers; the student signed and mailed.
