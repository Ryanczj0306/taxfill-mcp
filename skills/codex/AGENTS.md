# TaxFill — agent instructions (Codex CLI)

Canonical workflow: [`../claude/SKILL.md`](../claude/SKILL.md). This is the
condensed mirror for Codex.

You operate the `taxfill` MCP server. You interview and decide positions; the
tools fill, verify, render, and compute. Connect the server with the stdio
command from `packages/mcp-server/README.md`.

**No MCP? Use the shell gateway.** If your runtime runs shell commands but does
not speak MCP, call the same tools through the bundled CLI — one command each:

    taxfill tools                       # discover tools + JSON arg schemas
    taxfill call <name> '<json-args>'   # invoke one; prints the tool's JSON result
    taxfill call render_form '{...}' --out-dir ./pages   # page images -> files

`taxfill call` dispatches through the same registry as the stdio server, so every
tool below is reachable either way; a tool that raises exits non-zero (JSON error
on stderr).

## Hard rules

1. Never invent a value — unknown stays a gap. Every number comes from a tool
   (`calc`, `estimate_refund`, `fill_form`), never your own arithmetic.
2. Confirm extracted document values with the user before filling.
3. `verify_form`/`verify_filing` after every fill — ALWAYS recompute the
   table-lookup lines via `calc` and pass them as `independent` (e.g.
   `{"16": 36036}`; keyed per form_key for `verify_filing`), or the
   independent-recompute section does not run — loop until `ok: true` with
   recompute checks > 0, then `render_form` and review every page (P-001).
4. `estimate_refund` is a labeled RANGE with assumptions, never fake precision.
5. Review draft only: the user signs and mails paper. No e-file.
6. Year/benefit not in the shipped packs → `get_sources`, cite .gov, or refuse.

## Flow

intake_checklist → extract_document & confirm → estimate_refund → residency &
state_scope → positions (workspace_record_position) → fill_form →
verify_form/verify_filing (↺) → render_form → filing_summary (approve) →
file_and_pay.

Retirement-account planning has two ops whose whole job is a trap: `calc("ira_pro_rata", …)`
reproduces Form 8606 Part I / IRC 408(d)(2) — all traditional + SEP + SIMPLE IRAs are ONE
contract, and the ratio's DENOMINATOR (line 9) adds the converted amount back, so a
traditional IRA holding pretax money makes every backdoor Roth mostly taxable. And
`calc("roth_conversion", …)` makes you name the path: a DIRECT 401(k)/403(b) → Roth IRA
rollover (Notice 2008-30) is fully taxable but pro-rata NEVER applies to it, which is the only
way to clear an old plan without poisoning future backdoor conversions; a traditional-IRA
conversion goes through pro-rata. It also returns bracket headroom and the §1411 NIIT crossing
(conversion income is never net investment income, but it raises the MAGI the threshold is
measured against). Never hand-compute either.

HSAs get filed, not just planned: `calc("hsa_deduction", …)` is Form 8889 / IRC 223 and it
enforces four traps. The limit is MONTHLY (223(b)(1)-(2), tested on the FIRST DAY of each
month), so a mid-year HDHP start takes the Line 3 Limitation Chart — pass `monthly_coverage`
when the tier changed. The LAST-MONTH RULE (223(b)(8)) is automatic: eligible on Dec 1 buys the
whole annual limit and starts a 13-MONTH testing period (Dec 1 → Dec 31 of the NEXT year) whose
failure recaptures the extra into income plus a 10% additional tax — quote
`at_risk_if_testing_period_fails` first. W-2 box 12 code W is employer money AND cafeteria-plan
payroll deferrals, already out of box 1: it goes in `employer_contributions`, where it REDUCES
the deduction; deducting it again is the most common HSA error. And a general-purpose health
FSA — INCLUDING the spouse's (Rev. Rul. 2004-45) — is disqualifying coverage, while
limited-purpose and post-deductible ones are not. Never hand-compute Form 8889.

Equity comp is where this repo's users lose the most money, and both halves are ops.
`calc("espp_disposition", …)` takes Form 3922 boxes 1-8 and returns the Form 8949 row. The two
dispositions are taxed COMPLETELY differently: QUALIFYING (sold more than 2 years after grant AND
more than 1 year after purchase, IRC 423(a)(1)) recognises the LESSER of the GRANT-date discount
(423(c)(2)) and the actual gain — so a sale at a loss recognises ZERO ordinary income;
DISQUALIFYING recognises the FULL spread at purchase regardless of the sale price, so selling below
the purchase-date FMV still produces that income plus a capital loss. THE BASIS CORRECTION is the
highest-dollar part: the 1099-B reports the discounted purchase price only, the correct basis is
that plus the ordinary income, and filing it unadjusted taxes the discount TWICE — the op gives you
the Form 8949 code B treatment that fixes it. Under a LOOKBACK the qualifying income is measured on
Form 3922 BOX 8, not box 5. Nothing is withheld on any of it (IRC 423(c), 421(b), 3121(a)(22)).

`calc("capital_loss_limitation", …)` is IRC 1211(b)/1212(b) plus Schedule D's Capital Loss Carryover
Worksheet, and it is the only thing in the repo that tracks a carryover. Short and long net
SEPARATELY first, the deduction caps at $3,000 ($1,500 MFS), and the rest carries forward
INDEFINITELY WITH ITS CHARACTER PRESERVED. Taxable income does not shrink the deduction — it shrinks
how much of the loss the year consumes (worksheet line 4), so a low-income year keeps a LARGER
carryover than "loss minus $3,000". Pass `following_years` to roll a multi-year chain; it threads the
carryovers itself.

`calc("foreign_tax_credit_election", …)` answers the question that comes BEFORE Form 1116: is the
form needed at all? Anyone holding a total-international index fund has foreign tax withheld — it
arrives in Form 1099-DIV box 7 (interest: 1099-INT box 6) — and IRC 904(j) lets the credit be claimed
as ONE line on Schedule 3 (Form 1040), Part I, line 1, with no Form 1116, whenever creditable foreign
taxes stay at or under $300 ($600 in the case of a JOINT RETURN; statutory, never indexed), every
dollar of foreign-source gross income is qualified passive income, and all of it is shown on a payee
statement (1099-DIV, 1099-INT, K-1 (1041), K-3 (1065), K-3 (1120-S) or a substitute). The op REFUSES
to guess the two judgment facts and refuses to infer the election itself, because each one silently
decides the answer, and estates and trusts are excluded outright by 904(j)(3)(D). ALWAYS say what the
election costs: 904(j)(1)(B) and (C) forfeit the 904(c) one-year-back / ten-year-forward carryover in
BOTH directions for that year, so pass `regular_tax` (Form 1116 line 20) and read
`credit_lost_to_regular_tax_cap` — foreign tax above regular tax is lost permanently. Only married
filing jointly is "a joint return": a qualifying surviving spouse gets $300, not $600. When the
election is unavailable, file `formpacks/federal/<year>/f1116` — one form PER CATEGORY OF INCOME, with
exactly one of boxes a-g ticked above Part I (box c, passive, is the 1099-DIV box 7 basket).

State returns run through the SAME pipeline with `jurisdiction="states/<xx>"`.
All 42 income-tax jurisdictions (41 states + DC) ship a resident return pack —
38 as fillable AcroForms, 4 as print-only hand-fill manifests (CT, HI, NM, SC)
via `hand_fill_worksheet`; `state_scope` tells you which returns are required.
`hand_fill_worksheet` also serves one FEDERAL filing — `fincen114`, the FBAR
(FinCEN Form 114): e-file only through FinCEN's BSA E-Filing System, no fillable
PDF exists, a printed Form 114 is NOT accepted, and it is filed with FinCEN
rather than the IRS so it never travels in the return envelope. Ask about
foreign accounts (intake `income_documents.foreign_accounts`) and run
`calc('foreign_asset_reporting', …)` — it answers Form 8938 AND the FBAR, and
returns `required: null` plus `must_ask` rather than guessing.
`calc("state_tax", …)` covers **every** jurisdiction for 2023, 2024 AND 2025 —
flat or graduated is the PACK's call, and the split moves by
year, so never assume and never do state tax arithmetic yourself. Note the year
mismatch: state KNOWLEDGE spans 2023-2025, but state FORM packs cover 2024/2025
for only **13 of the 42** jurisdictions — AR, NY, OR and PA (2024 + 2025), and
IL, MO, NC, ND, NJ, OH, RI, UT, VA (2024). For the other 29 a 2024/2025 state
return computes but cannot be filled. Never assume a year exists: call
`list_forms` with the jurisdiction and year and read what comes back.

## Tools

`intake_checklist`, `list_document_kinds`, `extract_document`, `residency`,
`state_scope`, `estimate_refund`, `compare_scenarios`, `list_forms`, `get_form_map`, `fetch_blank`,
`fill_form`, `verify_form`, `verify_filing`, `render_form`,
`hand_fill_worksheet`, `calc`, `get_sources`, `workspace_save`,
`workspace_load`, `workspace_record_position`, `workspace_reconcile`,
`filing_summary`, `file_and_pay`.

See SKILL.md for cookbook recipes (simple W-2; back-file 1040-NR/8843; add a
state return), the prescriptive-error handling, the freshness protocol, and
the no-MCP Python fallback via `taxfill_core`.
