# taxfill-mcp (server)

The MCP server that exposes the TaxFill engine as tools any MCP client can call.
It does the deterministic PDF/calc work; your agent does the interviewing and
judgment. 100% local — the only outbound traffic is downloading blank forms from
official `.gov` URLs. Every output is a review draft: you review, sign, and file.

> v0.1 is in development and not yet published to PyPI, so the quickstarts below
> run it **from a source checkout** with `uv`.

## Tools (dev plan §8)

`intake_checklist` · `list_forms` · `get_form_map` · `fetch_blank` · `fill_form` ·
`verify_form` · `verify_filing` · `render_form` (returns page images) · `calc` ·
`residency` · `estimate_refund` · `get_sources` · `filing_summary` · `file_and_pay`

## Run it

```bash
# from the repo root
uv run taxfill-mcp        # starts the stdio server
```

## Add to a client

**Claude Code:**

```bash
claude mcp add taxfill -- uv run --project /ABSOLUTE/PATH/TO/taxfill-mcp taxfill-mcp
```

**Claude Desktop / Cowork** — add to the MCP servers config:

```json
{
  "mcpServers": {
    "taxfill": {
      "command": "uv",
      "args": ["run", "--project", "/ABSOLUTE/PATH/TO/taxfill-mcp", "taxfill-mcp"]
    }
  }
}
```

**Copilot / Codex CLI** — point their MCP config at the same `uv run … taxfill-mcp`
stdio command.

Once published, the one-liner becomes `uvx taxfill-mcp` (no checkout needed).

## A typical flow

`intake_checklist` → extract & confirm the user's documents → `estimate_refund`
→ `list_forms` / `get_form_map` → `fetch_blank` → `fill_form` →
`verify_form` / `verify_filing` (loop until `ok`) → `render_form` and
vision-review every page → `filing_summary` (user approves the bottom line) →
`file_and_pay`.
