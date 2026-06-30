# taxfill-mcp

**The execution layer for AI tax prep — agents think, taxfill fills, verifies, and gets it mailed.**

![Status: pre-release](https://img.shields.io/badge/status-pre--release-orange)
![Spec: complete](https://img.shields.io/badge/spec-complete-blue)
![v0.1: in development](https://img.shields.io/badge/v0.1-in%20development-yellow)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

> **Project status: pre-release, runnable from source.** The core engine, the federal form packs (2019–2024), the guided-intake/knowledge layer, knowledge packs for all 50 states + DC, and the MCP server all work today and are covered by 1,343 tests. You can run it now from a source checkout (see [Quickstart](#quickstart)). It is **not yet on PyPI**, so the one-line `uvx` install and the one-click `.mcpb` bundle are still coming. The full spec — the single source of truth — lives at [`docs/DEV_PLAN.md`](docs/DEV_PLAN.md). Star/watch the repo to follow along.

> ### ⚠️ Disclaimer
> taxfill-mcp is **not tax advice** and **not a tax preparer**. Everything it produces is a **review draft**. You — the human — review every number, sign every form, and file every return yourself. It does **not** e-file (paper print-and-mail, by design). Provided as-is under the MIT license, **with no warranty** of any kind.

---

## What this is (and is not)

**It is:**

- **Free and open source** (MIT).
- **Runs entirely on your computer.** No cloud, no accounts, no telemetry.
- A set of MCP tools that give any AI agent (Claude Desktop/Cowork, Claude Code, Copilot, Codex CLI, ...) a guided tax interview, deterministic PDF form filling, a mandatory verification gate, and a personalized print-sign-mail-pay checklist.
- A pile of **versioned form and jurisdiction knowledge** (field maps, math relations, mailing addresses, state rules) shipped as data, so agents stop rediscovering it every session.

**It is not:**

- A tax preparer or a tax-advice engine. The agent and the user decide positions; the server validates mechanics.
- An e-filing service. Output is a paper return you print, sign, and mail — by design.
- A guarantee of correctness. Every output is a draft for **your** review.

### Who it's for

This project grew out of a real session: an LLM agent back-filed **5 years of an international student's federal returns — 11 forms, treaty positions, fully verified** — with a skilled operator driving. That worked once, with one expert at the keyboard. taxfill-mcp turns that one-off into infrastructure: structured intake, deterministic filling, automated verification, and filing logistics that **any** MCP-capable agent can use, for anyone who has tax documents and an AI assistant.

---

## How it works

The agent walks you through nine steps. Progress lives in a resumable local workspace, so you can stop and pick up days later (real filings take time while you hunt for documents):

```
INTAKE → EXTRACT & CONFIRM → ESTIMATE & ROADMAP ↺ → RESIDENCY & SCOPE → POSITIONS → FILL → VERIFY → SUMMARY → FILE & PAY
```

1. **Intake** — a guided interview. The server tells the agent exactly what to ask and which documents to collect; you answer in chat and snap photos of your tax docs.
2. **Extract & confirm** — the agent reads each document (today, with its own vision; an automated `extract_document` parser is on the roadmap) into a table of values, each with a record of where it came from. You confirm the table before anything gets filled. Hard rule: **unknown values stay blank** — nothing is ever invented.
3. **Estimate & roadmap** — as soon as your first W-2/1099 is confirmed, you get a preliminary refund/owed **range** with its assumptions stated, plus a personalized roadmap (which forms, which documents are still missing). It is refreshed after every later step — with "what changed" — until it converges to the exact summary number. Always labeled ESTIMATE, never fake precision.
4. **Residency & scope** — computes your federal residency status (resident / nonresident / dual-status) and which states you owe a return to, producing the exact list of forms you need.
5. **Positions** — you and the agent decide elections, treaty articles, filing status (including married-filing-jointly vs separately), and credits. The agent records every decision and its legal authority in a `RECONCILIATION.md` — your audit trail.
6. **Fill** — deterministic, field-map-driven PDF filling. No hand-rolled scripts.
7. **Verify** — a mandatory gate: math checks, cross-form consistency, clipped-text scans, and a visual review of every rendered page. Loops until zero issues.
8. **Summary** — bottom line first, in plain language: *"Federal 2023: refund $161. Federal 2022: you owe $407, plus a late penalty the IRS will bill separately."* You approve before anything is printed.
9. **File & pay** — a personalized checklist: how to pay, where to sign, how to assemble each envelope, where to mail it (certified mail walkthrough included), and what mail to expect afterward.

### Why agents need this

LLMs can already do high-quality tax reasoning. What they lack — and what taxfill provides — is everything around the reasoning:

1. **Guided intake** — users don't know what to provide; agents ask ad-hoc.
2. **A reliable execution layer** — hand-rolled PDF scripts vary in quality every session.
3. **Verification discipline** — math checks, cross-form consistency, and render reviews get re-invented (or skipped) each time.
4. **Persistent form knowledge** — field names, comb-cell limits, checkbox quirks, and mailing addresses should be versioned data, not rediscovered facts.
5. **Filing logistics** — payment, signatures, envelope assembly, and mailing are where users fail at the last mile.
6. **Trustworthy arithmetic** — nobody should trust LLM mental math on a tax return, and they shouldn't have to: every number comes from a deterministic calc engine over cited per-year data and is independently recomputed at verification time. Precision is the product.

---

## Quickstart

### Today — from a source checkout

You need [`uv`](https://docs.astral.sh/uv/) (it bootstraps Python for you) and `git`.

```bash
git clone https://github.com/Ryanczj0306/taxfill-mcp
cd taxfill-mcp
uv sync                 # creates the venv, installs both packages
uv run taxfill-mcp      # starts the stdio MCP server (Ctrl-C to stop)
```

Then point your agent at it (use the **absolute path** to the checkout):

- **Claude Code:**

  ```bash
  claude mcp add taxfill -- uv run --project /ABSOLUTE/PATH/TO/taxfill-mcp taxfill-mcp
  ```

- **Claude Desktop / Cowork** — add to the MCP servers config:

  ```json
  { "mcpServers": { "taxfill": {
      "command": "uv",
      "args": ["run", "--project", "/ABSOLUTE/PATH/TO/taxfill-mcp", "taxfill-mcp"] } } }
  ```

- **Copilot / Codex CLI** — point their MCP config at the same `uv run … taxfill-mcp` command, and paste the matching skill file ([`skills/codex/AGENTS.md`](skills/codex/AGENTS.md) or [`skills/copilot/instructions.md`](skills/copilot/instructions.md)) so the agent knows the workflow. Claude clients pick up [`skills/claude/SKILL.md`](skills/claude/SKILL.md).

### Coming with v0.1 (once published to PyPI)

- **Claude Desktop / Cowork** — one-click MCPB bundle (`taxfill.mcpb`): download, double-click, done. The primary path for non-technical users.
- **Claude Code:** `claude mcp add taxfill -- uvx taxfill-mcp` (`uvx` bootstraps Python; no checkout needed).

A 60-second demo GIF lands with v0.1.

---

## What to prepare

Snap a clear photo (or PDF) of each document you have — all four corners in frame, no glare. The interview tells you exactly which ones apply to you; a typical set:

- **Identity:** SSN or ITIN; your **current** mailing address (where you get mail *today*).
- **Income:** every **W-2**, and any **1099** (NEC for self-employment, INT/DIV for bank/brokerage, B for sales), **1098-T** (tuition), **K-1**.
- **If you're on a visa (F/J/H/L/…):** passport ID page, visa, **I-94** travel history, and **I-20** (F-1) or **DS-2019** (J-1).
- **For a refund or to pay electronically:** a check or your bank's routing + account numbers.
- **Back-filing:** which years you've filed before, and anything you already paid.

The agent confirms each extracted value with you before it touches a form, and anything missing is reported as a gap — never guessed.

## Your first return in ~15 minutes

An abbreviated, anonymized walkthrough (simple W-2, single filer, 2023):

> **You:** I need to file my 2023 federal taxes. I have one W-2.
>
> **Agent:** *(calls `intake_checklist`)* Let's start. What's your full legal name and SSN? Are you a U.S. citizen or green-card holder? And your **current** mailing address — where you receive mail *today*, not where you lived in 2023?
>
> **You:** *(answers; uploads a photo of the W-2)*
>
> **Agent:** From your W-2 I read **wages $52,000** and **federal tax withheld $5,400** — can you confirm those two numbers? *(you confirm)* *(calls `estimate_refund`)* Preliminary **ESTIMATE: a refund of about $1,200** — assuming single, standard deduction, no other income or credits. I'll tighten it as we go.
>
> **Agent:** *(calls `calc`, `fill_form` for Form 1040, then `verify_form`)* Filled and verified — all math checks pass. *(calls `render_form`)* Here are your pages — please look them over. *(shows images)*
>
> **Agent:** *(calls `filing_summary`)* **Bottom line — Federal 2023: refund $1,200**, because your employer withheld more than you owe. The refund-claim deadline is around 2027-04-15. Approve and I'll prepare the mailing checklist?
>
> **You:** Approved.
>
> **Agent:** *(calls `file_and_pay`)* Print the form pages single-sided, sign and date page 2, attach your W-2, and mail to **Ogden, UT 84201-0002** (California, refund). Photograph the signed pages and keep a copy. Done — you review, sign, and mail it yourself.

## Troubleshooting

- **`uv: command not found`** — install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or see the [uv docs](https://docs.astral.sh/uv/). It bootstraps Python; you don't install Python yourself.
- **Permission prompts on first run** — your OS may ask to allow network access (only for downloading blank forms from irs.gov) and file access (the folder where filled PDFs are written). Both are expected.
- **The client doesn't see the `taxfill` tools** — make sure the MCP command uses the **absolute** path to the checkout (`uv run --project /ABS/PATH …`), then fully restart the client. `uv run taxfill-mcp` should start without errors in that folder.
- **Where are my filled PDFs?** — wherever you (or the agent) set `out_path` in `fill_form`. Ask the agent to use a folder you can find, e.g. `~/Documents/taxes-2023/`.
- **How do I resume later?** — in v0.1 the progress lives in your conversation with the agent, so continue in the same chat. A persistent on-disk workspace (and a `taxfill purge` to wipe it) is on the roadmap.

---

## Architecture

```
taxfill/
├── packages/
│   ├── core/          # pure Python: workspace, intake, residency, fill, verify, render, calc
│   └── mcp-server/    # thin MCP wrapper (official python-sdk, stdio)
├── formpacks/         # per-form data: federal/2023/f1040, states/ca/2023/form540nr, ...
├── knowledge/         # jurisdiction knowledge as DATA: thresholds, credits, mailing addresses
├── skills/            # workflow skills for Claude / Codex / Copilot
├── evals/             # synthetic scenarios + expected line values
└── docs/
```

**Key principle:** the engine is jurisdiction- and form-agnostic. Federal and state forms use the same `pack.yaml` schema, so state coverage grows by **adding data packs, never by changing engine code**. Blank PDFs are downloaded at runtime from official .gov URLs and checksum-verified — never vendored in the repo.

---

## MCP tool surface

All 21 tools are available today (from source); the server registers exactly 21 (CI-asserted).

| Tool | Purpose |
|---|---|
| `intake_checklist` | Next interview questions + required documents |
| `extract_document` | Structure + validate your reading of a W-2/1099/1098/1042-S/etc. into provenance-tagged fields |
| `residency` | Federal NRA/RA/dual-status via the Substantial Presence Test, work shown |
| `state_scope` | Which states to file, in what role, with which forms and candidate benefits |
| `list_forms` / `get_form_map` | Discover form packs; line-to-field maps + math relations |
| `fetch_blank` | Download the official blank PDF, checksum-verify |
| `fill_form` | Deterministic fill; comb/format handling; rejects unknown lines |
| `verify_form` / `verify_filing` | Assertion diffs, relation math, clipping scan, checkbox audit, cross-form consistency |
| `render_form` | Page PNGs returned as MCP image content for agent vision review |
| `calc` | Tax tables, presence-day counting, rounding, routing-number checksum |
| `estimate_refund` | Early refund/owed range from a partial profile, with composition and assumption list — always labeled ESTIMATE |
| `get_sources` | Ranked official .gov sources per topic (freshness protocol) |
| `filing_summary` | Plain-language bottom line per jurisdiction before printing |
| `file_and_pay` | Personalized pay/print/sign/assemble/mail checklist |

---

## Privacy, in plain words

- **Everything runs locally.** Your documents and SSN never leave your computer.
- **The only internet access** is downloading blank tax forms from official .gov URLs (checksum-verified).
- **No telemetry, no accounts, no uploads.** Logs are PII-redacted (SSNs and account numbers masked).
- Any documents you save locally hold sensitive data at rest — keep OS disk encryption on (FileVault / BitLocker).
- A persistent on-disk workspace with a one-command `taxfill purge <year>` wipe is on the roadmap; in v0.1, delete any files you saved yourself when you're done.

---

## Roadmap

Milestones from the [dev plan](docs/DEV_PLAN.md) (§15):

- [x] **M0 — Scaffold:** monorepo, pack & profile schemas, CI, license + disclaimer, CONTRIBUTING
- [x] **M1 — Core engine:** formpack loader, filler, verifier, render, calc (data-driven tax tables, source-verified), residency (SPT + exempt years)
- [x] **M2 — Federal packs:** f8843 (2019–2024), f1040-NR + schedules (2022–2023), f1040 + schedules (2023–2024) — field-map + relation audits clean
- [x] **M3 — Intake + knowledge:** profile schema, intake checklist, estimate_refund + roadmap, federal knowledge **2019–2024** (irs.gov-cited), sources registry, filing summary, file & pay
- [x] **M4 — MCP server:** stdio server, 21 tools, image content for renders, client quickstarts
- [x] **M5 — State support v1:** California packs (540 + 540NR) + knowledge, all-50-state + DC knowledge packs with cited credits, no-income-tax states, state scoping
- [~] **M6 — Skill + README + launch:** ✅ agent skills with cookbook, ✅ eval harness, ✅ this README, ✅ self-contained packaging + drift CI; remaining: `.mcpb` bundle, demo GIF, PyPI publish
- [~] **M7 — Scale-out:** ✅ pack-authoring CLI (`taxfill introspect`), ✅ document extraction (`extract_document`), ✅ persistent workspace + `taxfill purge`, ✅ Schedule SE/D/E + Form 8863/2555 via the introspect pipeline, ✅ extensions (Form 4868), ✅ estimated-tax vouchers (Form 1040-ES), ✅ amended returns (Form 1040-X), ✅ ITIN application (Form W-7); remaining: more state form packs (NY/MA/IL/NJ…), more years

---

## FAQ

**Is this legal?**
Yes. You are preparing and filing your own return — the same thing you'd do with pen and paper, with an AI assistant and verification tooling helping. taxfill is not a paid preparer and never signs anything; you do.

**What if I already filed?**
v0.1 targets original returns (including late back-filing). Amended returns (Form 1040-X, Rev. 2-2024) now ship too.

**What if I get audited?**
The agent records every position decision and its cited authority in a `RECONCILIATION.md` — a line-by-line audit trail of what was claimed and why, which is exactly what you want to have on hand. (The skill instructs the agent to maintain it as you go.)

**Does it e-file?**
No, by design. Output is a paper return: you print it, sign it, and mail it (the file & pay checklist walks you through certified mail). Paper filing keeps a human signature and review in the loop for every return.

**How much does it cost?**
Free. Open source, MIT licensed, runs on your own machine.

---

## Contributing

Contributions are welcome — especially form packs and state knowledge. See [CONTRIBUTING.md](CONTRIBUTING.md) for the pack-authoring guide and the pitfall-registry rule: every bug fix must ship with a permanent verifier rule and a regression test.

## License

[MIT](LICENSE).

---

> ### ⚠️ Disclaimer (again, because it matters)
> taxfill-mcp is **not tax advice**, **not a tax preparer**, and does **not** e-file. Everything it produces is a **review draft**: you review every value, you sign, you file, and you are responsible for your return. Software is provided **as-is, with no warranty**, under the MIT license.
