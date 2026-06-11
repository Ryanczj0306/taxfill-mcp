"""taxfill-mcp — the MCP server package (STUB).

Single source of truth: ``docs/DEV_PLAN.md`` at the repo root. The MCP tool
surface (``intake_checklist``, ``fill_form``, ``verify_form``,
``render_form``, ``file_and_pay``, ...) is specified in section 8 and is
delivered in milestone M4, when this package gains its dependency on the
official ``mcp`` Python SDK and a stdio server entry point.

Status: v0.1 is IN DEVELOPMENT — nothing is published to PyPI yet, and this
package currently exposes no tools. It exists so the workspace layout,
packaging, and CI are exercised from day one.

Design commitments (unchanged from the dev plan):

- 100% local; no telemetry; the only outbound traffic is downloading blank
  forms from official .gov URLs.
- Paper print-and-mail by design — no e-filing.
- Not tax advice and not a tax preparer: every output is a review draft;
  the human reviews, signs, and files.
- ``taxfill purge <year>`` wipes a workspace when the user is done.
"""

__version__ = "0.1.0.dev0"
