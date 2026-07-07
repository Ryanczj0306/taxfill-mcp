---
name: taxfill
description: >-
  Prepare U.S. tax returns end to end with the taxfill MCP server: guided
  intake, deterministic fill, mandatory verify, render-and-review, bottom-line
  approval, and a print-and-mail checklist. Use when a user wants to prepare,
  back-file, or estimate a federal return or a state return (34 states + DC
  have fillable packs; `state_scope` says which returns are required). Paper
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
| `intake_checklist(profile?, tax_year?)` | next questions + required documents for the interview |
| `list_document_kinds()` / `extract_document(path, kind, fields, page?)` | which documents are parseable; structure + validate your reading of one into provenance-tagged fields |
| `residency(visa_periods, days_by_year, target_year, is_lawful_permanent_resident?)` | NRA/RA/dual-status via the Substantial Presence Test (shows the day-count work) |
| `state_scope(profile, year)` | which states require a return, role, forms, candidate credits, treaty-conformity warnings |
| `estimate_refund(profile, year, income)` | early refund/owed RANGE + composition + assumptions (labeled ESTIMATE) |
| `list_forms(jurisdiction?, year?)` / `get_form_map(form, year, jurisdiction?)` | discover packs (federal + `states/<xx>`); line→field map + relations |
| `fetch_blank(form, year, jurisdiction?)` | download the official blank (checksum-verified) |
| `fill_form(form, year, values, out_path, jurisdiction?)` | deterministic fill; rejects unknown lines + comb/length errors |
| `verify_form(form, year, pdf_path, expected?, independent?, jurisdiction?)` | assertions + relation math + independent recompute (`independent` = line→calc result, e.g. `{"16": 36036}`) + clipping + checkbox audit |
| `verify_filing(items, independent?)` | cross-form identity + inter-form relations across the whole filing (`independent` keyed form_key→{line: calc result}) |
| `render_form(pdf_path, pages?)` | page PNGs returned as image content — vision-review every page |
| `hand_fill_worksheet(form, year, jurisdiction, values?)` | print-and-copy worksheet for non-AcroForm packs (e.g. Hawaii) |
| `calc(op, args)` | tax / standard_deduction / se_tax / additional_medicare_tax / niit / tax_with_preferential_rates / taxable_social_security / excess_ss / student_loan_interest_deduction / education_credits / ptc_annual — every result shows its work + citation |
| `get_sources(topic, year, jurisdiction?)` | ranked .gov sources + freshness channels |
| `workspace_save(year, profile)` / `workspace_load(year)` | persist / resume the intake profile between sessions |
| `workspace_record_position(year, position)` / `workspace_reconcile(year, gaps?)` | record each position decision + authority; render the RECONCILIATION.md audit trail |
| `filing_summary(manifest)` | plain-language bottom line per jurisdiction for the user to approve |
| `file_and_pay(manifest)` | pay / sign / assemble / mail / records / deadlines checklist |

`values` line ids come from `get_form_map`. The filing `manifest` items are
`{form, tax_year, jurisdiction?, bottom_line (signed: + refund / - owed),
paid_online?, state?, direct_deposit?, filing_jointly?}`.

## Cookbook

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

### Recipe B — back-file a nonresident return (1040-NR + 8843, e.g. an F-1 student)

1. `residency(visa_periods, days_by_year, target_year)` → confirm nonresident (Form 1040-NR path). If the answer is dual-status or a First-Year-Choice election is possible, surface it.
2. Required forms: `f1040nr` + `f8843`, plus `sched_oi` (treaty), `sched_1`, `sched_c` if self-employed. Treaty positions (e.g. US-China Art. 20(c) on student-period wages) are decided with the user and recorded; eligibility is per visa **period**.
3. Fill each form (`fill_form`), then `verify_filing([{form:"f1040nr",...}, {form:"f8843",...}, {form:"sched_oi", form_key:"sched_oi", ...}, ...], independent={"f1040nr": {"16": <calc tax>}})` — cross-form identity + the `1k == sched_oi.1e` treaty chain must pass, with the recompute running.
4. `render_form` each page; `filing_summary`; `file_and_pay` (1040-NR mails to Austin TX for a refund, Charlotte NC with a payment; 8843 attaches to the 1040-NR and is **not** signed separately).

### Recipe C — add a state return

State filing runs through the SAME fill/verify pipeline as federal: 34 states
+ DC ship fillable packs (Hawaii via `hand_fill_worksheet`), and `state_scope`
drives the list.

1. `state_scope(profile, year)` → which states require a return, in what role (resident / part-year / nonresident), which forms, candidate credits, and treaty-conformity warnings.
2. `list_forms("states/<xx>", year)` → the packed form keys (e.g. `form540`, `sched_ca_540`).
3. `fetch_blank` / `fill_form` / `verify_form` with `jurisdiction="states/<xx>"` — same flow, same mandatory verify gate, then `render_form` every page.
4. `filing_summary` / `file_and_pay` with the state item (`jurisdiction: "states/<xx>"`, full state name in `state`).

Note: California does **not** honor federal tax treaties — a treaty-exempt
amount federally is still taxable to CA (`state_scope` warns when this
applies; conforming states get the flows-through note instead).

## Prescriptive errors

Tool errors tell you exactly what to do — follow them literally:
- `"value '000-00-0000' exceeds comb MaxLen 9 — resubmit digits only"` → resend the SSN as 9 digits, no dashes.
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
