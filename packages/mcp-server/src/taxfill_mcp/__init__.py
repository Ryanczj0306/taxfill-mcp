"""taxfill-mcp — the MCP server package.

Single source of truth: ``docs/DEV_PLAN.md`` at the repo root. The server lives
in :mod:`taxfill_mcp.server` (FastMCP over the official ``mcp`` python-sdk);
``taxfill_mcp.server.main`` is the ``taxfill-mcp`` console entry point and runs
it over stdio. It exposes the tested ``taxfill_core`` engine as MCP tools
(dev plan section 8): intake_checklist, list_forms, get_form_map, fetch_blank,
fill_form, verify_form, verify_filing, render_form (image content), calc,
residency, estimate_refund, get_sources, filing_summary, file_and_pay.

Design commitments (unchanged from the dev plan):

- 100% local; no telemetry; the only outbound traffic is downloading blank
  forms from official .gov URLs.
- Paper print-and-mail by design — no e-filing.
- Not tax advice and not a tax preparer: every output is a review draft;
  the human reviews, signs, and files.
- ``taxfill purge <year>`` wipes a workspace when the user is done.

Status: v0.1 IN DEVELOPMENT — not yet published to PyPI.
"""

__version__ = "0.1.0"
