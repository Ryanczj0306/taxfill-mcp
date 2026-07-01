---
name: taxfill
description: >-
  Prepare U.S. tax returns end to end with the taxfill MCP server: guided
  intake, deterministic fill, mandatory verify, render-and-review, bottom-line
  approval, and a print-and-mail checklist. Use when a user wants to prepare,
  back-file, or estimate a federal return (state support is growing). Paper
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
   `verify_filing` for multi-form returns). Loop until `ok: true`. Then
   `render_form` and **look at every page** — clipping/mis-placement only shows
   in the render (pitfall P-001).
4. **Bottom line first, and honest.** Give an `estimate_refund` range early
   (with its assumptions); never present an estimate as an exact number.
5. **Review draft only.** You do not file. The user reviews, signs, and mails
   paper. Say so. There is no e-file.
6. **Cite or refuse.** For any year newer than the shipped knowledge packs, or
   any benefit a pack doesn't cover, resolve it via `get_sources` (.gov only),
   cite it, and refuse to fill a line you cannot cite.

## The flow

```
intake_checklist → extract & confirm → estimate_refund (↺) → residency & scope
→ positions → fill_form → verify_form/verify_filing (↺ until ok) → render_form
(review every page) → filing_summary (user approves) → file_and_pay
```

Show the user which step they're on and that they can stop and resume anytime.

## Tools

| tool | use |
|---|---|
| `intake_checklist(profile?, tax_year?)` | next questions + required documents for the interview |
| `residency(visa_periods, days_by_year, target_year, is_lawful_permanent_resident?)` | NRA/RA/dual-status via the Substantial Presence Test (shows the day-count work) |
| `estimate_refund(profile, year, income)` | early refund/owed RANGE + composition + assumptions (labeled ESTIMATE) |
| `list_forms(jurisdiction?, year?)` / `get_form_map(form, year)` | discover packs; line→field map + relations |
| `fetch_blank(form, year)` | download the official blank (checksum-verified) |
| `fill_form(form, year, values, out_path)` | deterministic fill; rejects unknown lines + comb/length errors |
| `verify_form(form, year, pdf_path, expected?)` | assertions + relation math + recompute + clipping + checkbox audit |
| `verify_filing(items)` | cross-form identity + inter-form relations across the whole filing |
| `render_form(pdf_path, pages?)` | page PNGs returned as image content — vision-review every page |
| `calc(op, args)` | tax / standard_deduction / se_tax / additional_medicare_tax / niit — every result shows its work + citation |
| `get_sources(topic, year, jurisdiction?)` | ranked .gov sources + freshness channels |
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
6. `verify_form("f1040", 2023, "/tmp/1040.pdf", expected=values)` → loop until `ok`.
7. `render_form("/tmp/1040.pdf")` → review every page with the user.
8. `filing_summary([{form:"1040", tax_year:2023, bottom_line: <signed>, state:"...", direct_deposit:true}])` → user approves.
9. `file_and_pay([... same item ...])` → walk the print/sign/mail checklist.

### Recipe B — back-file a nonresident return (1040-NR + 8843, e.g. an F-1 student)

1. `residency(visa_periods, days_by_year, target_year)` → confirm nonresident (Form 1040-NR path). If the answer is dual-status or a First-Year-Choice election is possible, surface it.
2. Required forms: `f1040nr` + `f8843`, plus `sched_oi` (treaty), `sched_1`, `sched_c` if self-employed. Treaty positions (e.g. US-China Art. 20(c) on student-period wages) are decided with the user and recorded; eligibility is per visa **period**.
3. Fill each form (`fill_form`), then `verify_filing([{form:"f1040nr",...}, {form:"f8843",...}, {form:"sched_oi", form_key:"sched_oi", ...}, ...])` — cross-form identity + the `1k == sched_oi.1e` treaty chain must pass.
4. `render_form` each page; `filing_summary`; `file_and_pay` (1040-NR mails to Austin TX for a refund, Charlotte NC with a payment; 8843 attaches to the 1040-NR and is **not** signed separately).

### Recipe C — add a state return

State packs + `state_scope` ship in M5. Today: scope the federal return; for
state, use `get_sources(topic, year, "states/<xx>")` and tell the user state
filing is not yet automated. Note: California does **not** honor federal tax
treaties — a treaty-exempt amount federally is still taxable to CA.

## Prescriptive errors

Tool errors tell you exactly what to do — follow them literally:
- `"value '000-00-0000' exceeds comb MaxLen 9 — resubmit digits only"` → resend the SSN as 9 digits, no dashes.
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
