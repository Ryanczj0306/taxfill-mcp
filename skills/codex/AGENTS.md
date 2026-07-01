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
3. `verify_form`/`verify_filing` after every fill — loop until `ok: true` —
   then `render_form` and review every page (P-001).
4. `estimate_refund` is a labeled RANGE with assumptions, never fake precision.
5. Review draft only: the user signs and mails paper. No e-file.
6. Year/benefit not in the shipped packs → `get_sources`, cite .gov, or refuse.

## Flow

intake_checklist → extract & confirm → estimate_refund → residency → positions →
fill_form → verify_form/verify_filing (↺) → render_form → filing_summary
(approve) → file_and_pay.

## Tools

`intake_checklist`, `residency`, `estimate_refund`, `list_forms`,
`get_form_map`, `fetch_blank`, `fill_form`, `verify_form`, `verify_filing`,
`render_form`, `calc`, `get_sources`, `filing_summary`, `file_and_pay`.

See SKILL.md for cookbook recipes (simple W-2; back-file 1040-NR/8843), the
prescriptive-error handling, the freshness protocol, and the no-MCP Python
fallback via `taxfill_core`.
