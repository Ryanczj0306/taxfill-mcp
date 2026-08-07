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

**State returns** use the same pipeline with `jurisdiction="states/<xx>"`. All 42
income-tax jurisdictions (41 states + DC) ship a resident return pack — 38 as
fillable AcroForms, 4 as print-only hand-fill manifests (CT, HI, NM, SC) via
`hand_fill_worksheet`; `state_scope` says which returns are required.
`calc("state_tax", …)` covers every jurisdiction for 2023/2024 and 41 for 2025
(RI pending) — flat vs graduated is the pack's call and moves by year, so never
assume and never compute a state tax line yourself. State KNOWLEDGE spans
2023-2025; state FORM packs are **2023 only**.

**Tools:** intake_checklist, list_document_kinds, extract_document, residency,
state_scope, estimate_refund, list_forms, get_form_map, fetch_blank, fill_form,
verify_form, verify_filing, render_form, hand_fill_worksheet, calc,
get_sources, workspace_save, workspace_load, workspace_record_position,
workspace_reconcile, filing_summary, file_and_pay.

See SKILL.md for cookbook recipes, prescriptive-error handling, the freshness
protocol, and the no-MCP Python fallback (`taxfill_core`).
