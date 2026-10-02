# User guide

> **Not tax advice, not a tax preparer.** Everything taxfill produces is a **review draft**: you review every number,
> sign every form and file the return yourself, on paper (no e-filing, by design). MIT licensed, with no warranty.

**Contents:** [What it is](#what-it-is-and-is-not) · [Install and connect](#install-and-connect) ·
[How a session works](#how-a-session-works) · [What to prepare](#what-to-prepare) ·
[Your first return](#your-first-return-in-15-minutes) · [Privacy](#privacy-in-plain-words) ·
[Troubleshooting](#troubleshooting) · [FAQ](#faq)

## What it is (and is not)

**It is:**

- **Free and open source** (MIT).
- **Runs entirely on your computer.** No cloud, no accounts, no telemetry.
- A set of MCP tools that give any AI agent (Claude Desktop/Cowork, Claude Code, Copilot, Codex CLI, ...) a guided tax interview, deterministic PDF form filling, a mandatory verification gate, and a personalized print-sign-mail-pay checklist.
- A pile of **versioned form and jurisdiction knowledge** (field maps, math relations, mailing addresses, state rules) shipped as data, so agents stop rediscovering it every session.

**It is not:**

- A tax preparer or a tax-advice engine. The agent and the user decide positions; the server validates mechanics.
- An e-filing service. Output is a paper return you print, sign, and mail — by design.
- A guarantee of correctness. Every output is a draft for **your** review.

**Who it's for.** Tax prep with an LLM agent works well today only when an expert checks every step. taxfill-mcp turns that expertise into infrastructure: structured intake, deterministic filling, automated verification, and filing logistics that **any** MCP-capable agent can use, for anyone who has tax documents and an AI assistant.

## Install and connect

You need [`uv`](https://docs.astral.sh/uv/) (it bootstraps Python for you) and `git`.

```bash
git clone https://github.com/Ryanczj0306/taxfill-mcp
cd taxfill-mcp
uv sync                 # creates the venv, installs both packages
uv run taxfill tools    # smoke test: lists every tool (your agent starts the server itself)
```

Then point your agent at it — always with the **absolute path** to the checkout — and install the workflow skill.
The skill is what teaches the agent taxfill's rules (confirm every extracted value before filling, never invent a
number, the mandatory verify gate), so do not skip it:

- **Claude Code** — `--scope user` makes the server available in every folder (the default scope is only the
  current directory), and the skill goes in your personal skills folder:

  ```bash
  claude mcp add --scope user taxfill -- uv run --project /ABSOLUTE/PATH/TO/taxfill-mcp taxfill-mcp
  mkdir -p ~/.claude/skills/taxfill && cp skills/claude/SKILL.md ~/.claude/skills/taxfill/
  ```

- **Claude Desktop / Cowork** — open the config with Settings → Developer → Edit Config (the file is
  `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json`
  on Windows), add the server, and restart the app. Desktop apps often do not see your shell's `PATH`: if the server
  fails with `spawn uv ENOENT`, replace `"uv"` with the full path printed by `which uv`. Then add the skill: zip the
  `skills/claude` folder and upload it as a custom skill ([how](https://support.claude.com/en/articles/12512180-use-skills-in-claude); code execution must be enabled).

  ```json
  { "mcpServers": { "taxfill": {
      "command": "uv",
      "args": ["run", "--project", "/ABSOLUTE/PATH/TO/taxfill-mcp", "taxfill-mcp"] } } }
  ```

- **Codex CLI / Copilot** — point their MCP config at the same `uv run … taxfill-mcp` command, then copy the
  matching instructions to where the agent reads them: [`skills/codex/AGENTS.md`](../skills/codex/AGENTS.md) into
  the folder you run Codex from (or `~/.codex/AGENTS.md` for every folder), or
  [`skills/copilot/instructions.md`](../skills/copilot/instructions.md) to `.github/copilot-instructions.md` in the
  workspace you open.

Then ask your agent something like *"Help me prepare my 2025 federal return."* — it starts the interview.

**Coming with v0.1 (once published to PyPI):**

- **Claude Desktop / Cowork** — one-click MCPB bundle (`taxfill.mcpb`): download, double-click, done. The primary path for non-technical users.
- **Claude Code:** `claude mcp add --scope user taxfill -- uvx taxfill-mcp` (`uvx` bootstraps Python; no checkout needed).

A 60-second demo GIF lands with v0.1.

## How a session works

The agent walks you through nine steps. Progress lives in a resumable local workspace, so you can stop and pick up days later (real filings take time while you hunt for documents):

```
INTAKE → EXTRACT & CONFIRM → ESTIMATE & ROADMAP ↺ → RESIDENCY & SCOPE → POSITIONS → FILL → VERIFY → SUMMARY → FILE & PAY
```

1. **Intake** — a guided interview. The server tells the agent exactly what to ask and which documents to collect; you answer in chat and snap photos of your tax docs.
2. **Extract & confirm** — the agent reads each document (its vision does the reading; `extract_document` structures and validates the reading) into a table of values, each with a record of where it came from. You confirm the table before anything gets filled. Hard rule: **unknown values stay blank** — nothing is ever invented.
3. **Estimate & roadmap** — as soon as your first W-2/1099 is confirmed, you get a preliminary refund/owed **range** with its assumptions stated, plus a personalized roadmap (which forms, which documents are still missing). It is refreshed after every later step — with "what changed" — until it converges to the exact summary number. Always labeled ESTIMATE, never fake precision.
4. **Residency & scope** — computes your federal residency status (resident / nonresident / dual-status) and which states you owe a return to, producing the exact list of forms you need.
5. **Positions** — you and the agent decide elections, treaty articles, filing status (including married-filing-jointly vs separately), and credits. The agent records every decision and its legal authority in a `RECONCILIATION.md` — your audit trail.
6. **Fill** — deterministic, field-map-driven PDF filling. No hand-rolled scripts.
7. **Verify** — a mandatory gate: math checks, cross-form consistency, clipped-text scans, and a visual review of every rendered page. Loops until zero issues.
8. **Summary** — bottom line first, in plain language: *"Federal 2025: refund $1,250. Federal 2024: you owe $380, plus a late penalty the IRS will bill separately."* (a hypothetical nonresident student with one back year; demo numbers) You approve before anything is printed.
9. **File & pay** — a personalized checklist: how to pay, where to sign, how to assemble each envelope, where to mail it (certified mail walkthrough included), and what mail to expect afterward.

### Why agents need this

LLMs can already do high-quality tax reasoning. What they lack — and what taxfill provides — is everything around the reasoning:

1. **Guided intake** — users don't know what to provide; agents ask ad-hoc.
2. **A reliable execution layer** — hand-rolled PDF scripts vary in quality every session.
3. **Verification discipline** — math checks, cross-form consistency, and render reviews get re-invented (or skipped) each time.
4. **Persistent form knowledge** — field names, comb-cell limits, checkbox quirks, and mailing addresses should be versioned data, not rediscovered facts.
5. **Filing logistics** — payment, signatures, envelope assembly, and mailing are where users fail at the last mile.
6. **Trustworthy arithmetic** — nobody should trust LLM mental math on a tax return, and they shouldn't have to: every number comes from a deterministic calc engine over cited per-year data and is independently recomputed at verification time. Precision is the product.

## What to prepare

Snap a clear photo (or PDF) of each document you have — all four corners in frame, no glare. The interview tells you exactly which ones apply to you; a typical set:

- **Identity:** SSN or ITIN; your **current** mailing address (where you get mail *today*).
- **Income:** every **W-2**, and any **1099** (NEC for self-employment, INT/DIV for bank/brokerage, B for sales), **1098-T** (tuition), **K-1**.
- **If you're on a visa (F/J/H/L/…):** passport ID page, visa, **I-94** travel history, and **I-20** (F-1) or **DS-2019** (J-1).
- **For a refund or to pay electronically:** a check or your bank's routing + account numbers.
- **Back-filing:** which years you've filed before, and anything you already paid.

The agent confirms each extracted value with you before it touches a form, and anything missing is reported as a gap — never guessed.

For a complete fill-in checklist of everything to gather, use the [intake worksheet](INTAKE_WORKSHEET.md)
([中文版](INTAKE_WORKSHEET.zh-CN.md)).

## Your first return in ~15 minutes

An abbreviated, synthetic walkthrough (a hypothetical filer with demo numbers: simple W-2, single, 2023):

> **You:** I need to file my 2023 federal taxes. I have one W-2.
>
> **Agent:** *(calls `intake_checklist`)* Let's start. What's your full legal name and SSN? Are you a U.S. citizen or green-card holder? And your **current** mailing address — where you receive mail *today*, not where you lived in 2023?
>
> **You:** *(answers; uploads a photo of the W-2)*
>
> **Agent:** From your W-2 I read **wages $52,000** and **federal tax withheld $5,400** — can you confirm those two numbers? *(you confirm)* *(calls `estimate_refund`)* Preliminary **ESTIMATE: a refund of about $1,039** — assuming single, standard deduction, no other income or credits. I'll tighten it as we go.
>
> **Agent:** *(calls `calc`, `fill_form` for Form 1040, then `verify_form`)* Filled and verified — all math checks pass. *(calls `render_form`)* Here are your pages — please look them over. *(shows images)*
>
> **Agent:** *(calls `filing_summary`)* **Bottom line — Federal 2023: refund $1,039**, because your employer withheld more than you owe. The refund-claim deadline is around 2027-04-15. Approve and I'll prepare the mailing checklist?
>
> **You:** Approved.
>
> **Agent:** *(calls `file_and_pay`)* Print only the form pages (not the instructions), single-sided; sign and date the return in ink; attach your W-2; and mail to **Ogden, UT 84201-0002** (California, refund). Photograph the signed pages and keep a copy. Done — you review, sign, and mail it yourself.

## Privacy, in plain words

- **taxfill runs locally.** The engine, the server and the CLI run on your computer and send nothing about you
  anywhere. Your **AI assistant** is a different matter: it reads the documents and answers you give it (a cloud model
  unless you run a local one), under its provider's data policy — decide what to share with it accordingly.
- **The only internet access** is downloading blank tax forms from the tax agencies' own sites — or, when a state site
  blocks scripted downloads, an exact Internet Archive copy of that same URL — checksum-verified either way.
- **No telemetry, no accounts, no uploads.** The tool keeps no logs of its own.
- **Errors are redacted.** Identifier-shaped content (SSN/ITIN patterns, long digit runs) is masked before any error echoes a value — in the engine's own errors AND the CLI, because tool errors land in your agent's transcript.
- **Your data lives in one place you own:** `~/taxfill-workspace/<year>/` (override with `TAXFILL_WORKSPACE`; an existing `./taxfill-workspace` from an earlier release keeps working). The saved profile and source documents are under it. Filled PDFs go wherever the agent's `fill_form` `out_path` points — the skill files tell the agent to use the year's `drafts/` folder (`~/taxfill-workspace/<year>/drafts/`), so the purge below removes them too; if you asked for another folder, delete those files yourself.
- Any documents you save locally hold sensitive data at rest — keep OS disk encryption on (FileVault / BitLocker).
- The workspace can be wiped any time with a single `uv run --project /ABSOLUTE/PATH/TO/taxfill-mcp taxfill purge <year>` (once installed from PyPI, just `taxfill purge <year>`), which overwrites the file bytes before deleting (best-effort on copy-on-write filesystems/SSDs — see [SECURITY.md](../.github/SECURITY.md) for the honest caveat); also delete any files you saved yourself when you're done.
- Found a way any of this fails? [SECURITY.md](../.github/SECURITY.md) has the private reporting channel.

## Troubleshooting

- **`uv: command not found`** — install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or see the [uv docs](https://docs.astral.sh/uv/). It bootstraps Python; you don't install Python yourself.
- **Permission prompts on first run** — your OS may ask to allow network access (only for downloading blank forms from the tax agencies' own sites) and file access (the folder where filled PDFs are written). Both are expected.
- **The client doesn't see the `taxfill` tools** — make sure the MCP command uses the **absolute** path to the checkout (`uv run --project /ABS/PATH …`), then fully restart the client. `uv run taxfill tools` run in that folder should list the tools. On Claude Desktop, `spawn uv ENOENT` means the app cannot find `uv`: use the full path from `which uv` as the `command`.
- **Where are my filled PDFs?** — wherever the agent set `out_path` in `fill_form`; by default the skill files have it write them to `~/taxfill-workspace/<year>/drafts/`, which `taxfill purge <year>` also removes. Ask the agent for the exact path if you can't find them.
- **How do I resume later?** — progress can persist to a local workspace: the agent saves your profile and decisions (`workspace_save` / `workspace_record_position`) and resumes them in a later session with `workspace_load`, so you can stop and pick up days later. Wipe it any time with `uv run --project /ABSOLUTE/PATH/TO/taxfill-mcp taxfill purge <year>`.

## FAQ

**Is this legal?**
Yes. You are preparing and filing your own return — the same thing you'd do with pen and paper, with an AI assistant and verification tooling helping. taxfill is not a paid preparer and never signs anything; you do.

**What if I already filed?**
v0.1 targets original returns (including late back-filing). Amended returns ship too: Form 1040-X Rev. 2-2024 for TY2023–2024, Rev. 12-2025 for TY2025, and the Rev. 12-2026 draft for TY2026 (rehearsal-only until the final posts).

**What if I get audited?**
The agent records every position decision and its cited authority in a `RECONCILIATION.md` — a line-by-line audit trail of what was claimed and why, which is exactly what you want to have on hand. (The skill instructs the agent to maintain it as you go.)

**Does it e-file?**
No, by design. Output is a paper return: you print it, sign it, and mail it (the file & pay checklist walks you through certified mail). Paper filing keeps a human signature and review in the loop for every return.

**How much does it cost?**
Free. Open source, MIT licensed, runs on your own machine.

**What isn't supported yet?**
taxfill is pre-release: it is not on PyPI yet, so the one-line `uvx` install, the one-click `.mcpb` bundle and the
demo GIF are still to come. State form coverage for TY2024 and TY2025 is still filling in — check your state in
[COVERAGE.md](COVERAGE.md). Separate nonresident / part-year returns are mapped only for California (Form 540NR) and
New York (IT-203); where one return serves every filer (PA-40, for example), the residency boxes are mapped but most
nonresident apportionment schedules are not yet. Most TY2026 forms are mapped from the IRS early-release drafts and
fill in rehearsal mode only until the IRS posts the finals (the 2026 Form 1040-ES vouchers are final). Maintainers
track the remaining work in [dev/ROADMAP.md](dev/ROADMAP.md).
