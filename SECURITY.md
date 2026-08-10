# Security policy

taxfill handles the most sensitive documents most people own — SSNs, wages,
addresses, bank accounts — so this file states plainly what the tool does with
them, what it promises, and where to report a problem.

## Reporting a vulnerability

Use **GitHub private vulnerability reporting** on this repository (Security →
"Report a vulnerability"). Please do not open a public issue for anything that
could expose user data. You should hear back within a week; fixes for anything
that leaks PII take priority over all feature work.

## Threat model (what taxfill is and is not)

- **100% local.** The engine, the MCP server and the CLI run on your machine.
  There are no accounts, no cloud, no telemetry, and no logs kept by the tool
  itself. The **only** outbound traffic is downloading blank official form
  PDFs from `.gov` URLs (`fetch_blank`), which sends nothing about you.
- **Your agent is part of the picture.** taxfill is driven by an AI agent over
  MCP or a shell. Anything a tool RETURNS — results, and especially error
  messages — lands in that agent's transcript, which the client may log or
  sync. That is why error text is treated as an exfiltration surface (below).
- **Paper only.** Nothing is e-filed and nothing is transmitted to the IRS or
  any state. Output is a PDF you review, sign and mail.

## Where your data lives

Everything taxfill writes lives under **one directory you own**:

| What | Where |
|---|---|
| The resumable workspace (profile.json with SSN/address, source documents, filled drafts, RECONCILIATION.md) | `~/taxfill-workspace/<year>/` — override with the `TAXFILL_WORKSPACE` env var; an existing `./taxfill-workspace` from an earlier release keeps working |
| Cached **blank** form PDFs (public documents, no PII) | `<repo>/.cache/blanks` from a checkout; `<workspace root>/.cache/blanks` from an installed wheel; override with `TAXFILL_BLANKS_CACHE` |

The server, the CLI and `taxfill purge` resolve the workspace through the same
function, so what one writes the others can always find.

## Deleting your data

`taxfill purge <year>` overwrites every file's bytes before unlinking, then
removes the year's directory. **The honest caveat:** on copy-on-write
filesystems (APFS, Btrfs, ZFS) and wear-leveled SSDs the original blocks can
survive the overwrite — treat purge as best-effort sanitization, and use full-
disk encryption if the threat you care about is physical access to the drive.

## PII in error messages

Error text travels farther than any other output, so:

- identifier-shaped content (SSN/ITIN patterns, 6+-digit runs) is **redacted**
  before an error echoes a submitted value — one shared implementation
  (`taxfill_core.redact`) serves the engine's own errors and the CLI, under
  test either way;
- pydantic validation errors over MCP report field paths and messages only,
  never input values;
- the verifier's check details never echo identifying values (tested).

Names and addresses are not pattern-redactable; the rule for those is simpler —
they are never echoed into an error at all. If you find a path where any of
this fails, that is exactly what the reporting channel above is for.

## Dependencies

Runtime dependencies are deliberately few (`pydantic`, `pypdf`, `pypdfium2`,
`PyYAML`, `mcp`) and pinned by `uv.lock`; the packaging CI job installs the
built wheel into a clean environment on every push.
