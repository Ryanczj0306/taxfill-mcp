# MCPB bundle (`taxfill.mcpb`) — build recipe

The one-click **MCPB bundle** is the primary install path for non-technical
Claude Desktop / Cowork users: download `taxfill.mcpb`, double-click, done. It
is **publish-gated** — it depends on the server being installable as a published
package — so it is built as part of shipping v0.1, not before. This file is the
recipe so the build is a mechanical step at release time, not a rediscovery.

## Prerequisites (at release)

1. `taxfill-mcp` published to PyPI (so the bundle can launch it with `uvx`,
   which bootstraps Python on the user's machine).
2. The `mcpb` CLI: `npm i -g @anthropic-ai/mcpb` (see
   https://github.com/anthropics/mcpb for the current manifest schema).

## Build

```bash
cd bundle
mcpb init            # scaffold manifest.json (interactive) — fill in from the values below
mcpb validate        # check the manifest against the current schema
mcpb pack            # produces taxfill.mcpb
```

## Manifest values to use

- **name:** `taxfill` · **display_name:** `TaxFill` · **version:** matches the
  PyPI release · **license:** MIT
- **server:** launch the published server with uvx, e.g. command `uvx` with
  args `["taxfill-mcp"]` (Python server; uvx bootstraps the interpreter and deps).
- **tools:** the 14 tools the server exposes (see
  [`packages/mcp-server/src/taxfill_mcp/server.py`](../packages/mcp-server/src/taxfill_mcp/server.py)
  and the table in the top-level [README](../README.md)).
- **Permissions / network:** declare outbound network (only to download blank
  forms from official .gov URLs) and local file access (where filled PDFs are
  written). No telemetry, no accounts.
- Reuse the disclaimer from the top-level README: not tax advice, not a
  preparer, review-draft only, paper filing — no e-file.

## Until then

Use the from-source quickstart in the top-level [README](../README.md#quickstart)
(`uv run taxfill-mcp` + `claude mcp add … uv run --project … taxfill-mcp`).
