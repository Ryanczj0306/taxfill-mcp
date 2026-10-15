# taxfill-mcp (server)

The MCP server that exposes the TaxFill engine as tools any MCP client can call.
It does the deterministic PDF/calc work; your agent does the interviewing and
judgment. 100% local — the only outbound traffic is downloading blank forms from
the tax agencies' own sites (or an exact, digest-checked Internet Archive copy when a state
site blocks scripts). Every output is a review draft: you review, sign, and file.

> **Release status.** TY2025 is the newest filing-grade tax year, and stays so until a later
> release re-pins the 2026 packs on the IRS's final 2026 forms. The 2026 packs are provisional:
> most are mapped from the IRS early-release drafts, so `fill_form` refuses them (the exception is
> the 2026 Form 1040-ES, whose vouchers are paid during 2026 and fill normally); 2026 projections
> come from `estimate_refund` and `compare_scenarios`. A form with no pack is refused today
> (`list_forms` shows which forms have one, except the print-only state forms that
> `hand_fill_worksheet` serves); a later release adds an unmapped draft for such a form, which is
> never filing-grade.

## Tools

`intake_checklist` · `list_document_kinds` · `extract_document` · `residency` ·
`state_scope` · `estimate_refund` · `compare_scenarios` · `list_forms` · `get_form_map` · `fetch_blank` ·
`fill_form` · `verify_form` · `verify_filing` · `render_form` (returns page
images) · `hand_fill_worksheet` (print-only state forms) · `calc`
(deterministic ops over cited per-year data) · `get_sources` · `workspace_save` ·
`workspace_load` · `workspace_record_position` · `workspace_reconcile` ·
`filing_summary` · `file_and_pay`

Your data stays on your machine: the resumable workspace (profiles, documents,
and the filled drafts the agent writes to `<year>/drafts/`) lives at `~/taxfill-workspace`
(override with the `TAXFILL_WORKSPACE` env var), and `taxfill purge <year>` wipes a year on
demand (`uvx --from taxfill-mcp taxfill purge <year>`).

## Run it

```bash
uvx --from taxfill-mcp taxfill tools   # smoke test: lists every tool
uvx taxfill-mcp                         # the stdio server itself (your MCP client normally starts it)
```

`uvx` (from [uv](https://docs.astral.sh/uv/)) bootstraps Python and the dependencies; no checkout is needed.

## Add to a client

**Claude Code:**

```bash
claude mcp add --scope user taxfill -- uvx taxfill-mcp
```

**Claude Desktop / Cowork** — add to the MCP servers config:

```json
{
  "mcpServers": {
    "taxfill": {
      "command": "uvx",
      "args": ["taxfill-mcp"]
    }
  }
}
```

**Copilot / Codex CLI** — point their MCP config at the same `uvx taxfill-mcp`
stdio command.

From a source checkout instead, replace `uvx taxfill-mcp` with
`uv run --project /ABSOLUTE/PATH/TO/taxfill-mcp taxfill-mcp`.

## A typical flow

`intake_checklist` → extract & confirm the user's documents → `estimate_refund`
→ `list_forms` / `get_form_map` → `fetch_blank` → `fill_form` →
`verify_form` / `verify_filing` (loop until `ok`) → `render_form` and
vision-review every page → `filing_summary` (user approves the bottom line) →
`file_and_pay`.
