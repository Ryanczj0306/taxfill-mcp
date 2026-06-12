# taxfill-mcp

**The execution layer for AI tax prep — agents think, taxfill fills, verifies, and gets it mailed.**

![Status: pre-release](https://img.shields.io/badge/status-pre--release-orange)
![Spec: complete](https://img.shields.io/badge/spec-complete-blue)
![v0.1: in development](https://img.shields.io/badge/v0.1-in%20development-yellow)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

> **Project status: nothing is published yet.** The design spec is complete and v0.1 is under active development. Nothing has shipped to PyPI, and the install commands below are **planned, not yet working**. The full spec — the single source of truth — lives at [`docs/DEV_PLAN.md`](docs/DEV_PLAN.md). Star/watch the repo to follow along.

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
2. **Extract & confirm** — every document is parsed into structured fields with a record of where each value came from. You confirm the table before anything gets filled. Hard rule: **unknown values stay blank** — nothing is ever invented.
3. **Estimate & roadmap** — as soon as your first W-2/1099 is confirmed, you get a preliminary refund/owed **range** with its assumptions stated, plus a personalized roadmap (which forms, which documents are still missing). It is refreshed after every later step — with "what changed" — until it converges to the exact summary number. Always labeled ESTIMATE, never fake precision.
4. **Residency & scope** — computes your federal residency status (resident / nonresident / dual-status) and which states you owe a return to, producing the exact list of forms you need.
5. **Positions** — you and the agent decide elections, treaty articles, and credits. Every decision and its legal authority is written down in `RECONCILIATION.md`.
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

## Quickstart (planned — coming with v0.1)

> **None of these work yet.** This is the install UX we are building toward; nothing is on PyPI and no bundle has been published.

- **Claude Desktop / Cowork** — one-click MCPB extension bundle (`taxfill.mcpb`): download, double-click, done. The primary path for non-technical users.
- **Claude Code:**

  ```bash
  claude mcp add taxfill -- uvx taxfill-mcp
  ```

  (`uvx` bootstraps Python automatically — you never install Python yourself.)
- **Copilot / Codex CLI** — equivalent one-liners plus a drop-in skill/instructions file.

A 60-second demo GIF and an annotated "your first return in 15 minutes" transcript are coming with v0.1.

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

## MCP tool surface (planned for v0.1)

| Tool | Purpose |
|---|---|
| `intake_checklist` | Next interview questions + required documents |
| `extract_document` | Parse W-2/1099/1098/I-94/etc. into fields with provenance; missing = null, never guessed |
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
- Your workspace holds sensitive documents at rest — keep OS disk encryption on (FileVault / BitLocker).
- When you're done, `taxfill purge <year>` wipes the workspace.

---

## Roadmap

Milestones from the [dev plan](docs/DEV_PLAN.md) (§15):

- [x] **M0 — Scaffold:** monorepo, pack & profile schemas, CI, license + disclaimer, CONTRIBUTING
- [x] **M1 — Core engine:** formpack loader, filler, verifier, render, calc (data-driven 2023 tax tables, source-verified), residency (SPT + exempt years)
- [ ] **M2 — Federal packs:** f8843 (2019–2024), f1040-NR + schedules (2022–2023), f1040 + schedules (2023–2024)
- [ ] **M3 — Intake + knowledge:** profile schema, intake checklist, estimate_refund + roadmap, federal knowledge, sources registry, file & pay
- [ ] **M4 — MCP server:** stdio server, image content for renders, client quickstarts
- [ ] **M5 — State support v1:** California packs + knowledge, no-income-tax states, state scoping
- [ ] **M6 — Skill + README + launch:** agent skills with cookbook, eval harness, MCPB bundle, ship v0.1
- [ ] **M7 — Scale-out:** pack-authoring CLI, NY/MA/IL/NJ, more years, amended returns (1040-X), extensions (4868), estimated tax (1040-ES), ITIN (W-7)

---

## FAQ

**Is this legal?**
Yes. You are preparing and filing your own return — the same thing you'd do with pen and paper, with an AI assistant and verification tooling helping. taxfill is not a paid preparer and never signs anything; you do.

**What if I already filed?**
v0.1 targets original returns (including late back-filing). Amended returns (Form 1040-X) are on the roadmap (M7).

**What if I get audited?**
Every position decision and its cited authority is recorded in a generated `RECONCILIATION.md` — a line-by-line audit trail of what was claimed and why, which is exactly what you want to have on hand.

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
