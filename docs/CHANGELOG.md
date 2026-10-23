# Changelog

Every release of TaxFill: the `taxfill-core` and `taxfill-mcp` packages on PyPI, which share one version, and the
`taxfill.mcpb` bundle attached to the GitHub release. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/); versions follow
[PEP 440](https://peps.python.org/pep-0440/).

How this file is used (maintainers: [PUBLISHING.md](dev/PUBLISHING.md) step 1):

- The release commit gives the release its own section, `## [<version>] - <YYYY-MM-DD>`. Pushing the tag
  `v<version>` runs `.github/workflows/release.yml`, which publishes that section as the GitHub release notes
  (`scripts/release_notes.py`). The workflow stops before any upload if the section is missing or has no date.
- The coverage bullets between the GENERATED markers are rewritten by `scripts/sync_doc_counts.py --write` (CI's
  `--check` fails when they drift) until the section's heading carries a date. A dated section is never rewritten.

## [Unreleased]

Nothing yet. Until v0.1.0 is tagged, new changes go into the 0.1.0 section below.

## [0.1.0] - Unreleased

The first release. TaxFill is a local MCP server that helps an AI agent prepare a paper U.S. federal and state
income-tax return for the person's review: it fills the official PDFs from confirmed inputs, verifies every figure,
and gives a sign-and-mail checklist. Not tax advice, not a tax preparer: every output is a review draft that the
person checks, signs and files.

### Coverage

<!-- BEGIN GENERATED release counts: scripts/sync_doc_counts.py --write rewrites this block until the section heading is dated -->
- **23 MCP tools** over stdio, among them `calc` with **40 deterministic ops** over cited per-year tax data; `taxfill call` runs the same tools from a shell for agents without MCP.
- **29 tax-document kinds** that `extract_document` structures and validates (W-2, the 1099s, the 1098s, 1042-S, the K-1s, …).
- **151 federal form packs**: TY2019 1 · TY2020 1 · TY2021 1 · TY2022 5 · TY2023 35 · TY2024 35 · TY2025 37; planning year TY2026 36.
- **130 fillable state packs** (TY2023 48 · TY2024 41 · TY2025 41) plus **13 print-and-hand-fill state worksheets** (CT, HI, NM and SC for 2023–2025; WV for 2025). Of the 42 income-tax jurisdictions, a state return fills for all 42 in TY2023, 41 in TY2024 and all 42 in TY2025.
- **A FinCEN Form 114 (FBAR) worksheet** for 2023–2026, for keying into FinCEN's BSA E-Filing System.
- **Tax knowledge**: federal 2019–2026 (2026 is planning-only); state, all 42 income-tax jurisdictions for 2023, 2024 and 2025.
<!-- END GENERATED release counts -->

### Added

- **Two packages and a bundle.** `taxfill-core` is the engine (intake, residency, calc, fill, verify, render,
  workspace) with the knowledge and form-pack data inside the wheel. `taxfill-mcp` is the stdio MCP server
  (`uvx taxfill-mcp`) plus the `taxfill` CLI. `taxfill.mcpb` is a bundle for Claude Desktop that installs the
  published server on first launch; it uses the experimental uv runtime of the MCPB format (manifest 0.4), which
  is untested in Claude Desktop so far (see "Not in this release").
- **TY2025 is the newest filing-grade tax year.** The TY2026 packs are provisional: most are mapped from the IRS
  early-release drafts, and `fill_form` refuses them: 2026 is not yet a filing year. Projections for 2026
  come from `estimate_refund` and `compare_scenarios`; a rehearsal fill of a 2026 draft form is available only
  through the `taxfill-core` Python API, not through the MCP server or the `taxfill` CLI. The exception is the
  2026 Form 1040-ES, whose vouchers are paid during 2026 and fill normally.
- **The session, end to end:** a guided interview (`intake_checklist`, with a fill-in onboarding worksheet),
  document reading the person confirms (`extract_document`), an early refund estimate or planning-year projection
  (`estimate_refund`) and what-if comparisons (`compare_scenarios`), federal residency by the Substantial Presence
  Test (`residency`) and which states need a return (`state_scope`), a deterministic fill (`fill_form`), a
  mandatory verify gate (`verify_form`, `verify_filing`, and `render_form` page images for a visual check), and a
  plain-language bottom line with a pay / sign / assemble / mail checklist (`filing_summary`, `file_and_pay`).
- **Amended returns.** Form 1040-X packs for TY2023 to TY2025 map the current revision (December 2025), the one an
  amendment filed now uses. `file_and_pay` and `filing_summary` give an amended return its own checklist: the Form
  1040-X Where To File address, payment, the corrected return behind it and the claim window from the current
  instructions; Georgia's Form 500X rules; and, for any other state, a pointer to its revenue department instead of
  the original return's address and due date.
- **Print-only state forms**: `hand_fill_worksheet` lists every line to hand-write, and `fill_form` stamps the
  values onto the official blank.
- **A resumable local workspace** (`workspace_save`, `workspace_load`): each position taken is recorded with its
  authority (`workspace_record_position`) and written out as `RECONCILIATION.md` with a `CHECKLIST.md`
  (`workspace_reconcile`); `taxfill purge <year>` overwrites and deletes a year's workspace.
- **Blank forms are downloaded at runtime** from the tax agencies' own sites (or an exact, digest-checked Internet
  Archive copy when a state site blocks scripts) and checksum-verified; no blank PDF is stored in the packages.
- **Filled PDFs carry no XFA layer.** A filled form keeps the official AcroForm fields with their appearances
  and drops the XFA layer that hybrid IRS forms carry, so Adobe Acrobat and Reader draw the filled fields rather
  than the form's empty XFA data.
- **Page headers are filled and checked.** Where a form repeats the filer's name and SSN at the top of later pages,
  the pack declares how each header is built from the page-1 lines. `fill_form` fills the headers you leave out
  (listed in `mirrored`), shortening a name that does not fit as the pack allows or leaving it to hand-write with a
  warning, and `verify_form` checks every header against page 1. 56 packs declare them, among them California's
  Form 540, whose Sides 2-6 headers had printed blank.
- **State exemption credits are computed.** `calc` `state_tax` takes the credit counts and federal AGI and returns
  each exemption credit as its own field, with the AGI rules applied: California for 2023-2025, and Arkansas,
  Delaware, Iowa, Nebraska and Oregon for 2025.
- **Part-year and nonresident filers get their own forms.** Every state's 2025 knowledge cites the part-year and
  nonresident form and its instructions, so `state_scope` points those filers at the right documents.
- **`~/` paths are accepted** in every tool argument, CLI path and `TAXFILL_*` setting. Results keep full paths;
  refusals that only name a path show your home folder as `~`.
- **Ink-signature lines stay blank.** A box that sits on a signature line is not fillable where the instructions
  require a signature (Kansas, Kentucky, Illinois); Missouri's is, because its form accepts a typed name.
- **Checks that depend on a checkbox.** Iowa's line 12 check is skipped when the Income Tax Reduction Worksheet box
  is checked, and `verify_form` lists every skipped check instead of counting it as passed.
- **Form W-2 code titles follow the W-2's own year**, and code II is accepted from 2024 W-2s on.
- **SSN digits clear the printed dashes.** On the 2023-2026 Form 1040 and 1040-X, `fill_form` aligns the SSN boxes
  with the separators printed in them (`combs_aligned`).

### Not in this release

- **No e-file.** Returns are printed, signed and mailed. The FBAR worksheet's values are keyed into FinCEN's own
  system by the person.
- **A form with no pack is refused** (`list_forms` shows which forms have one, except the print-only state forms
  that `hand_fill_worksheet` serves). A later release adds an unmapped draft for such a form, which is never
  filing-grade.
- **State amended returns are pointers.** No state amended form has a pack, and only Georgia's knowledge carries
  its amended-return rules; for every other state the checklist names the revenue department's site.
- **No TY2026 final forms.** The 2026 packs stay unfilable for filing until a later release re-pins them on the
  IRS's final 2026 forms.
- **No proven one-click install yet.** `taxfill.mcpb` uses the MCPB format's experimental uv runtime (manifest
  0.4). On a Claude Desktop build without that runtime, install uv first
  (https://docs.astral.sh/uv/getting-started/installation/); a build that only knows an older manifest version
  may refuse the bundle, and then `uvx taxfill-mcp` (with uv installed) is the way to connect.
- **MCP Python SDK 1.x only.** `taxfill-mcp` depends on `mcp>=1.2,<2`; the server is not yet ported to the 2.x API.

[Unreleased]: https://github.com/Ryanczj0306/taxfill-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Ryanczj0306/taxfill-mcp/releases/tag/v0.1.0
