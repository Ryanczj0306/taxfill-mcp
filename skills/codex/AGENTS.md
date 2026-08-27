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

State returns run through the SAME pipeline with `jurisdiction="states/<xx>"`.
All 42 income-tax jurisdictions (41 states + DC) ship a resident return pack —
38 as fillable AcroForms, 4 as print-only hand-fill manifests (CT, HI, NM, SC)
via `hand_fill_worksheet`; `state_scope` tells you which returns are required.
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
