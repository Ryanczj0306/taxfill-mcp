# TaxFill — Copilot instructions

Canonical workflow: [`../claude/SKILL.md`](../claude/SKILL.md). Condensed mirror
for GitHub Copilot.

You operate the `taxfill` MCP server (connect via the stdio command in
`packages/mcp-server/README.md`). You interview and decide positions; the tools
do the deterministic fill/verify/render/compute.

**Hard rules:** never invent a value (unknown = gap); every number comes from a
tool, not your arithmetic; confirm extracted values before filling;
`verify_form`/`verify_filing` until `ok` — always pass `independent` with the
key lines recomputed via `calc` (e.g. `{"16": 36036}`; keyed per form_key for
`verify_filing`) so the independent recompute actually runs (recompute checks
> 0) — then `render_form` and review every page; `estimate_refund` is a
labeled range with assumptions; review draft only
(user signs and mails paper — no e-file); for a year/benefit not in the shipped
packs, resolve via `get_sources` (.gov) and cite, or refuse.

**Flow:** intake_checklist → extract_document & confirm → estimate_refund →
residency & state_scope → positions (workspace_record_position) → fill_form →
verify_form/verify_filing (↺) → render_form → filing_summary (approve) →
file_and_pay.

**Retirement conversions:** `calc("ira_pro_rata", …)` is Form 8606 Part I / IRC 408(d)(2) — all
traditional + SEP + SIMPLE IRAs are ONE contract and the ratio's denominator (line 9) adds the
converted amount back, so pretax money in any traditional IRA makes a backdoor Roth mostly
taxable. `calc("roth_conversion", …)` makes you name the path: a DIRECT 401(k)/403(b) → Roth IRA
rollover (Notice 2008-30) is fully taxable but pro-rata never touches it — the only clean way to
empty an old plan — while a traditional-IRA conversion goes through pro-rata. It also returns
bracket headroom and the §1411 NIIT crossing. Never compute either yourself.

**HSAs:** `calc("hsa_deduction", …)` is Form 8889 / IRC 223. The limit is MONTHLY (223(b)(1)-(2), first-day-of-month test) — pass `monthly_coverage` for a mid-year change. The
LAST-MONTH RULE (223(b)(8)) is automatic: eligible Dec 1 buys the full annual limit and starts a
13-month testing period whose failure is income + a 10% additional tax. W-2 box 12 code W is
employer money AND cafeteria-plan payroll deferrals, already out of box 1 — it goes in
`employer_contributions` and REDUCES the deduction; deducting it again is the classic error. A
general-purpose health FSA, including the SPOUSE's (Rev. Rul. 2004-45), disqualifies you.

**Equity comp:** `calc("espp_disposition", …)` turns Form 3922 boxes 1-8 into the Form 8949 row. A
QUALIFYING disposition (more than 2 years after grant AND more than 1 year after purchase) recognises
the LESSER of the GRANT-date discount and the actual gain — zero ordinary income on a sale at a loss;
a DISQUALIFYING one recognises the FULL purchase-date spread regardless of the sale price. The
1099-B reports only the discounted purchase price, so the correct basis is that plus the ordinary
income and the op returns the code-B adjustment that stops the discount being taxed twice. Under a
lookback the qualifying income uses Form 3922 BOX 8, not box 5. Nothing is withheld on it.

**Capital losses:** `calc("capital_loss_limitation", …)` is IRC 1211(b)/1212(b) and Schedule D's
Capital Loss Carryover Worksheet — the $3,000/$1,500 cap plus an indefinite carryover that KEEPS its
short/long character. Taxable income limits how much of the loss the year consumes, not the
deduction, so a low-income year carries MORE forward. `following_years` rolls the chain and threads
the carryovers for you.

**Foreign tax credit:** `calc("foreign_tax_credit_election", …)` decides whether Form 1116 is needed
at all. Foreign tax withheld on an international fund's dividends (Form 1099-DIV box 7) can be claimed
as ONE line on Schedule 3, Part I, line 1 under IRC 904(j) — no Form 1116 — when creditable foreign
taxes are at or under $300 ($600 on a JOINT return; statutory, never indexed), ALL foreign-source
gross income is qualified passive income, and all of it is on a payee statement. The op refuses to
guess those judgments or the election itself; estates and trusts cannot elect. Quote the cost: the
904(c) carryback/carryforward is forfeited in both directions for the election year, and foreign tax
above `regular_tax` is lost for good. A qualifying surviving spouse gets $300, not $600 — only MFJ is
"a joint return". Otherwise file `formpacks/federal/<year>/f1116`, one form per category of income.

**State returns** use the same pipeline with `jurisdiction="states/<xx>"`. All 42
income-tax jurisdictions (41 states + DC) ship a resident return pack — 38 as
fillable AcroForms, 4 as print-only hand-fill manifests (CT, HI, NM, SC) via
`hand_fill_worksheet`; `state_scope` says which returns are required.
`hand_fill_worksheet` also covers one FEDERAL filing, `fincen114` (the FBAR /
FinCEN Form 114): e-file only via FinCEN's BSA E-Filing System, no fillable PDF,
a printed Form 114 is not accepted, and it is filed with FinCEN — never in the
tax-return envelope. Ask about foreign accounts, then run
`calc('foreign_asset_reporting', …)`, which answers Form 8938 and the FBAR
together and says `must_ask` instead of guessing.
`calc("state_tax", …)` covers every jurisdiction for 2023, 2024 AND 2025 —
flat vs graduated is the pack's call and moves by year, so never
assume and never compute a state tax line yourself. State KNOWLEDGE spans
2023-2025; state FORM packs cover 2024/2025 for only **13 of the 42**
jurisdictions (AR/NY/OR/PA 2024+2025, IL/MO/NC/ND/NJ/OH/RI/UT/VA 2024), so for
the other 29 a 2024/2025 return computes but cannot be filled — check
`list_forms` for the jurisdiction and year instead of assuming.

**Tools:** intake_checklist, list_document_kinds, extract_document, residency,
state_scope, estimate_refund, compare_scenarios, list_forms, get_form_map, fetch_blank, fill_form,
verify_form, verify_filing, render_form, hand_fill_worksheet, calc,
get_sources, workspace_save, workspace_load, workspace_record_position,
workspace_reconcile, filing_summary, file_and_pay.

See SKILL.md for cookbook recipes, prescriptive-error handling, the freshness
protocol, and the no-MCP Python fallback (`taxfill_core`).
