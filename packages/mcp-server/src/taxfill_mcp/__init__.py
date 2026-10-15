"""taxfill-mcp — the MCP server package.

Source, design spec and docs: https://github.com/Ryanczj0306/taxfill-mcp

The server lives in :mod:`taxfill_mcp.server` (FastMCP over the official
``mcp`` python-sdk); ``taxfill_mcp.server.main`` is the ``taxfill-mcp`` console
entry point and runs it over stdio. It exposes the tested ``taxfill_core``
engine as MCP tools — intake, document extraction, residency, estimates, form
discovery, deterministic fill, mandatory verification, page rendering, cited
calc ops, the resumable workspace, the filing summary and the file-and-pay
checklist; ``taxfill tools`` lists every one.

Design commitments:

- 100% local; no telemetry; the only outbound traffic is downloading blank
  forms from the tax agencies' own sites (or an exact, digest-checked Internet
  Archive copy when a state site blocks scripts).
- Paper print-and-mail by design — no e-filing.
- Not tax advice and not a tax preparer: every output is a review draft;
  the human reviews, signs, and files.
- ``taxfill purge <year>`` wipes a workspace when the user is done.

Release status: TY2025 is the newest filing-grade tax year, and stays so until
a later release re-pins the 2026 packs on the IRS's final 2026 forms. The 2026
packs are provisional: ``fill_form`` refuses them (the 2026 Form 1040-ES, paid
during 2026, fills normally); ``estimate_refund`` and ``compare_scenarios``
project 2026. A form with no pack is refused today; a later release adds an unmapped draft for such a form, which is
never filing-grade.
"""

__version__ = "0.1.0"
