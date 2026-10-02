# taxfill-mcp

**Your AI assistant prepares a paper U.S. tax return: taxfill fills the official PDFs, verifies every number, and tells you exactly how to sign and mail it.**

![Status: pre-release](https://img.shields.io/badge/status-pre--release-orange)
![CI](https://github.com/Ryanczj0306/taxfill-mcp/actions/workflows/ci.yml/badge.svg)
![Tests: 8,674 passing](https://img.shields.io/badge/tests-8%2C674%20passing-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

> [!WARNING]
> taxfill-mcp is **not tax advice** and **not a tax preparer**. Everything it produces is a **review draft**: you check
> every number, sign every form, and file the return yourself. It does **not** e-file (paper print-and-mail, by design).
> MIT licensed, provided as-is **with no warranty**.

## What it does

The AI interviews and reasons with you; taxfill does the arithmetic, PDF field mechanics, consistency checks and filing logistics.

- **Guided interview to filled forms.** Your MCP agent (Claude Code, Claude Desktop/Cowork, Copilot, Codex CLI) asks
  the right questions, reads your W-2s and 1099s, and fills the official IRS and state PDFs. Unknown values stay blank; nothing is invented.
- **Math you don't have to trust an LLM for.** Every number comes from a deterministic calc engine over cited, per-year
  tax data and is recomputed independently at verify time. The mandatory verify gate checks math, cross-form consistency, clipped text, and every rendered page.
- **The last mile, done.** A plain-language bottom line, then a personal pay / print / sign / mail checklist.
- **Private and free.** taxfill runs on your computer and sends nothing about you anywhere: no cloud, no accounts, no
  telemetry. Its only download is blank forms from the tax agencies' own sites (or an exact Internet Archive copy when a state
  site blocks scripts), checksum-verified. Your AI assistant does see the documents and answers you give it, under its
  provider's data policy; taxfill masks SSN-shaped values in its own error messages.

## Quickstart

> **Pre-release:** runs from a source checkout. It is **not on PyPI yet**, so `uvx taxfill-mcp` and the one-click
> `.mcpb` bundle are not available yet. Known gaps: [FAQ](docs/USER_GUIDE.md#faq).

You need [`uv`](https://docs.astral.sh/uv/) (it installs Python for you) and `git`.

```bash
git clone https://github.com/Ryanczj0306/taxfill-mcp
cd taxfill-mcp
uv sync                 # creates the venv, installs both packages
uv run taxfill tools    # smoke test: lists every tool (your agent starts the server itself)
```

Then connect your agent, using the **absolute path** to the checkout, and install the workflow skill so the agent
follows taxfill's rules (you confirm every value before filling; the verify gate is mandatory):

- **Claude Code** — add the server for every project, then install the skill:
  ```bash
  claude mcp add --scope user taxfill -- uv run --project /ABSOLUTE/PATH/TO/taxfill-mcp taxfill-mcp
  mkdir -p ~/.claude/skills/taxfill && cp skills/claude/SKILL.md ~/.claude/skills/taxfill/
  ```

- **Claude Desktop / Cowork** — merge this into the `mcpServers` object of `claude_desktop_config.json` (Settings →
  Developer → Edit Config) and restart the app; then, with code execution enabled, upload a ZIP of the `skills/claude`
  folder as a skill ([how](https://support.claude.com/en/articles/12512180-use-skills-in-claude)):
  ```json
  { "mcpServers": { "taxfill": {
      "command": "uv",
      "args": ["run", "--project", "/ABSOLUTE/PATH/TO/taxfill-mcp", "taxfill-mcp"] } } }
  ```

- **Codex CLI / Copilot** — put the same `uv run … taxfill-mcp` command in their MCP config, and copy the matching
  instructions where the agent reads them: [`skills/codex/AGENTS.md`](skills/codex/AGENTS.md) into the folder you run
  Codex from (or `~/.codex/AGENTS.md`), or [`skills/copilot/instructions.md`](skills/copilot/instructions.md) to
  `.github/copilot-instructions.md` in your workspace.

Then ask your agent: *"Help me prepare my 2025 federal return."* Filling in the
[intake worksheet](docs/INTAKE_WORKSHEET.md) first makes the interview faster.

Tools not showing up? Check that the path is absolute and fully restart the client; if Claude Desktop reports
`spawn uv ENOENT`, set `"command"` to the full path printed by `which uv`. More: [troubleshooting](docs/USER_GUIDE.md#troubleshooting).

## How a session works

```
INTAKE → EXTRACT & CONFIRM → ESTIMATE & ROADMAP → RESIDENCY & SCOPE → POSITIONS → FILL → VERIFY → SUMMARY → FILE & PAY
```

You confirm every extracted value before filling and approve the summary before printing. Each position you take is
recorded with its authority in `RECONCILIATION.md`, your audit trail. Progress is saved in a local workspace
(`~/taxfill-workspace/<year>/`), so you can resume days later.

## What it covers

| | Coverage |
|---|---|
| **Federal forms** | Form 1040 with its schedules and attachments for TY2023–2025, Form 1040-NR from TY2022, Form 8843 from TY2019 — 151 packs, including TY2026 planning drafts |
| **Federal tax law** | 2019–2026 (2026 is planning-only) |
| **State forms** | Resident returns for 41 of the 42 income-tax jurisdictions in TY2025, 23 in TY2024, all 42 in TY2023; separate nonresident returns for CA and NY — [check your state](docs/COVERAGE.md#state-forms) |
| **Print-and-hand-fill** | 13 state-return worksheets for years whose form is not a fillable PDF (CT, HI, NM, SC; WV for 2025) — the values are stamped onto the official blank |
| **FBAR** | A FinCEN Form 114 worksheet, for keying into FinCEN's BSA E-Filing System (the FBAR is e-filed, never mailed with the return) |
| **State tax law** | All 50 states + DC, 2023–2025 |
| **Documents read** | 29 tax-document kinds (W-2, 1099s, 1098s, 1042-S, …) |

Most TY2026 forms are mapped from the IRS early-release drafts and fill in rehearsal mode only until the final forms
post (the 2026 Form 1040-ES vouchers are final).
Full form-by-year matrix: [docs/COVERAGE.md](docs/COVERAGE.md).

## Read more

| If you want to… | Read |
|---|---|
| Gather your documents first | [Intake worksheet](docs/INTAKE_WORKSHEET.md) · [中文版](docs/INTAKE_WORKSHEET.zh-CN.md) |
| See the nine steps, a sample return, troubleshooting, privacy, FAQ | [User guide](docs/USER_GUIDE.md) |
| Look up the 23 MCP tools, the 40 calc ops, or the `taxfill` CLI for non-MCP agents | [Tools reference](docs/TOOLS.md) |
| Browse all docs, including maintainer docs | [Docs index](docs/README.md) · [`docs/dev/`](docs/dev/) |
| Contribute a form pack or state knowledge | [CONTRIBUTING](.github/CONTRIBUTING.md) · [Pack-authoring guide](docs/dev/CONTRIBUTING-PACKS.md) |
| Report a security or privacy issue privately | [SECURITY](.github/SECURITY.md) |

**Repo layout:** `packages/core` (pure-Python engine) · `packages/mcp-server` (thin MCP wrapper plus the `taxfill` CLI) ·
`formpacks/` (per-form field maps as YAML) · `knowledge/` (per-year tax law as cited YAML) · `skills/` (agent instructions) ·
`scripts/` (maintainer tooling). Coverage grows by adding data packs, not engine code; blank PDFs are fetched at runtime, never stored here.

## License

[MIT](LICENSE). Provided as-is, with no warranty. Not tax advice; you review, sign and file your own return.
