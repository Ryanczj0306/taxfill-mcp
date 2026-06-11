# TaxFill MCP — Development Plan (v2.1)

> **Repo language: English only** (code, docs, comments, commit messages). This plan is the spec; hand it to Claude Code and execute milestone by milestone.

## 1. Problem & Vision

LLM agents can already do high-quality tax prep with a skilled operator (proven in a real 2019–2023 back-filing session: 11 federal forms, treaty positions, zero errors after verification). What blocks normal users:

1. **No guided intake** — users don't know what info/documents to provide; agents ask ad-hoc.
2. **No reliable execution layer** — agents hand-roll PDF scripts; quality varies per session.
3. **No verification discipline** — assertions, cross-form consistency, clipping/render checks get re-invented.
4. **Form knowledge is rediscovered every session** — field names, comb limits, checkbox exports, mailing addresses, state thresholds should be versioned data.
5. **Filing logistics are an afterthought** — how to pay, what to sign, how to assemble envelopes, where to mail. Users fail at the last mile.
6. **Nobody trusts LLM arithmetic — and they shouldn't.** Precision is the product. Every number on a return must come from deterministic, citable computation over versioned per-year data (tax tables, schedules, credit phase-outs), be independently recomputed at verify time, and show its work. Model mental math never lands on a return.

**Vision:** `taxfill-mcp` = guided intake spec + deterministic calc/fill/verify tools + versioned form & jurisdiction knowledge (federal **and** state) + file-and-pay instructions, consumable by ANY MCP client (Claude Code/Cowork, Copilot, Codex CLI). The agent supplies judgment; the server supplies structure, math, and correctness.

**Non-goals (v1):** e-filing (paper print-and-mail only), being a tax-advice engine (agent + user decide positions; server validates mechanics), guaranteeing correctness (always a review draft; the human signs and files).

## 2. User flow (what the agent walks a user through)

```
INTAKE → EXTRACT & CONFIRM → ESTIMATE & ROADMAP ↺ → RESIDENCY & SCOPE → POSITIONS → FILL → VERIFY → SUMMARY → FILE & PAY
```

All progress lives in a **resumable workspace** (`taxfill-workspace/<year>/`: `profile.json`, `documents/`, `drafts/`, `RECONCILIATION.md`, `CHECKLIST.md`) — filing realistically spans days while users hunt for documents; any agent can resume from the workspace state.

1. **Intake (guided interview).** Server provides the question/document checklist; agent asks via its own UI (chat, AskUserQuestion, etc.). Photos/PDFs of tax docs accepted.
2. **Extract & confirm.** OCR/parse every document into structured fields with per-field provenance; show the user a source table; user confirms before anything is filled. *Hard rule: never invent a value — unknown stays blank and is reported as a gap.*
3. **Estimate & roadmap (recurring ↺).** As soon as the primary income documents are confirmed (typically right after the first W-2/1099), the server computes a preliminary bottom line: estimated refund/owed **as a range**, its composition (income → withholding → deductions/credits → treaty benefits), the personalized roadmap (which returns and forms, which documents are still missing, expected time to finish), and an explicit assumption list (e.g., *"assuming full-year CA resident — confirm move dates to tighten the range"*). Built on the same deterministic `calc` engine as the final return — never model arithmetic — and always labeled ESTIMATE. Refreshed after every later step so the user sees the current bottom line and what changed it; converges to the exact SUMMARY number.
4. **Residency & scope.** Server computes federal residency (NRA/RA/dual-status via Substantial Presence Test from I-94 history + exempt-individual years) and state filing footprint (which states, resident/part-year/nonresident) from where the user lived/worked. Output: the exact list of returns and forms needed.
5. **Positions.** Agent + user decide elections/treaty articles/credits; every decision and its authority is recorded in a generated `RECONCILIATION.md`.
6. **Fill.** Deterministic, field-map-driven PDF filling; every computed line produced by `calc`, never by the model.
7. **Verify (mandatory gate).** Assertions + math relations + independent recompute pass + cross-form consistency + clipping scan + rendered-page vision review. Loop until zero issues.
8. **Summary (bottom line first).** Before anything is printed: per-jurisdiction plain-language summary — *"Federal 2023: refund $161, direct-deposited to …1234. Federal 2022: you owe $407 (+ late penalties the IRS will bill separately, roughly $X–Y). California: no return required because …"* — with deadline status (including the 3-year refund statute of limitations). User approves the bottom line before the print step.
9. **File & pay.** Per-jurisdiction instructions: payment options, signature locations, print/assembly checklist, envelopes, mailing addresses, certified-mail walkthrough, record keeping, and what-happens-next expectations.

## 3. Architecture

```
taxfill/
├── packages/
│   ├── core/                      # pure Python lib (no MCP dependency)
│   │   ├── workspace.py           # resumable session state, drafts, audit artifacts
│   │   ├── intake.py              # interview spec → required questions/docs per profile
│   │   ├── residency.py           # SPT, exempt years, state residency classification
│   │   ├── formpack.py            # load/validate form packs
│   │   ├── filler.py              # AcroForm fill (pypdf), appearance regen
│   │   ├── verify.py              # assertions + relations + consistency + clipping
│   │   ├── render.py              # pdftoppm/pypdfium2 → PNG artifacts
│   │   ├── calc.py                # deterministic tax math: per-year tables/schedules/credits (data-driven), day counting, rounding, routing checksum
│   │   ├── estimate.py            # partial-profile refund estimator + roadmap (range, composition, assumptions)
│   │   ├── knowledge.py           # jurisdiction knowledge loader (thresholds, credits)
│   │   └── redact.py              # PII-safe logging
│   └── mcp-server/                # thin MCP wrapper (official python-sdk, stdio)
├── formpacks/
│   ├── federal/2023/f1040/pack.yaml
│   ├── federal/2022/f1040nr/  f8843/  sched_1/ sched_c/ sched_oi/ ...
│   └── states/ca/2023/form540nr/pack.yaml     # same schema as federal
├── knowledge/                     # jurisdiction knowledge as DATA
│   ├── federal/2023.yaml          # filing thresholds, payment options, mailing addresses
│   └── states/ca/2023.yaml        # thresholds, residency rules summary, credits, FTB URLs
├── skills/
│   ├── claude/SKILL.md            # workflow skill for Claude Code / Cowork
│   ├── codex/AGENTS.md
│   └── copilot/instructions.md
├── evals/                         # synthetic scenarios + expected line values
└── docs/
```

**Key principle:** the engine is jurisdiction- and form-agnostic. Federal and state forms use the same `pack.yaml` schema; state coverage grows by adding data packs, never by changing engine code.

## 4. Guided intake (interview spec)

`intake.py` defines a profile schema; `intake_checklist(partial_profile)` returns the *next* questions and required documents, so any agent can run the interview consistently.

Profile sections:

| section | examples |
|---|---|
| identity | name, SSN/ITIN, DOB, current **mailing address** (explicitly "where you receive mail TODAY, not where you lived that tax year") |
| immigration (if applicable) | **visa status timeline with exact date ranges** (mid-year changes matter: an F-1 → H1B transition year can still claim US-China Art. 20(c) $5,000 on income earned during the student period — eligibility is per-period, not per-year), first US entry, I-94 travel records (photo/CBP export), green-card steps |
| residency facts | days in US per year (computed from I-94 if provided), home country address |
| household | filing status facts, dependents |
| state footprint | where you **lived** (date ranges) and where you **worked** (date ranges, remote vs on-site) per tax year |
| income documents | W-2, 1099-NEC/INT/DIV/B, 1098-T, K-1 … (inventory with "have / missing / N-A") |
| banking | routing/account for refund or payment (checksum-validated) |
| prior filings | which years filed before, late-filing context |

Document checklist is generated from the profile (e.g., NRA student → I-20, passport ID page, visa, I-94 history, W-2, 1098-T). Each intake answer carries provenance: `user_stated`, `document(file, page)`, or `computed`.

**Disambiguation by design.** Intake questions that users predictably get wrong ship with built-in clarification. Example (from production): "mailing address" must be asked as *"the address where you receive mail TODAY — not where you lived during the tax year; the IRS sends bills and notices here"*, because users instinctively give their historical address. Historical addresses are collected separately under *state footprint* (they drive state scoping and Schedule C business address), never auto-copied into the return's address box. Treaty-relevant facts (visa periods, enrollment) are asked as date ranges, never as a single "what's your status" question.

## 5. Form Pack spec (`pack.yaml`) — federal and state

```yaml
form: 1040-NR
jurisdiction: federal            # or: states/ca
tax_year: 2022
source_url: https://www.irs.gov/pub/irs-prior/f1040nr--2022.pdf
pdf_sha256: "..."
acroform_root: "topmostSubform[0]"      # varies per form (Sched OI: form1040-NR[0])
fields:
  - line: "identifying_number"
    field: "Page1[0].f1_7[0]"
    type: text
    maxlen: 9
    comb: true
    format: ssn_digits_only             # dashes overflow comb cells — learned in production
  - line: "filing_status.single"
    field: "Page1[0].c1_1[0]"
    type: checkbox
    on_state: "/1"
  - line: "1a"
    field: "Page1[0].f1_28[0]"
    type: money
relations:                               # enforced by verifier
  - "1z == sum(1a..1h)"
  - "11 == 9 - 10"
  - "37 == max(0, 24 - 33)"
cross_form:
  - "1k == sched_oi.L1e"
  - "8 == sched_1.10"
identity_fields: [name, identifying_number, mailing_address]   # must match across the filing
signature: { page: 2, standalone_only: false }   # f8843: sign only when filed alone
mailing:
  no_payment: "Department of the Treasury, IRS, Austin, TX 73301-0215"
  with_payment: "IRS, P.O. Box 1303, Charlotte, NC 28201-1303"
  verify_url: "https://www.irs.gov/filing/..."
```

Blank PDFs (IRS and state DOR) are **downloaded at runtime** from official URLs and checksum-verified — never vendored in the repo.

## 6. State tax support

Three layers, all data-driven:

1. **State knowledge packs** (`knowledge/states/<st>/<year>.yaml`): filing requirement thresholds by status/income; residency classification rules (domicile, statutory resident, part-year, nonresident); **common credits & benefits** (e.g., CA renter's credit, CA EITC, NY household credit) each with eligibility predicates the agent can evaluate against the profile; reciprocity agreements; whether the state conforms to federal treaty positions (e.g., CA does NOT honor federal tax treaties — critical for NRA users); DOR payment portal + mailing addresses; no-income-tax states list (TX, WA, FL, …) so the answer can be "nothing to file."
2. **State form packs**: same `pack.yaml` schema (CA 540/540NR + Schedule CA first; then NY IT-201/IT-203, MA, IL, NJ).
3. **State scoping tool**: `state_scope(profile, year)` → for each state touched: `{state, filing_role: resident|part_year|nonresident|none, must_file: bool, reason, forms[], benefits_candidates[]}`. Multi-state income allocation remains agent+user judgment; the server provides rules text, validators, and the math checks.

v1 ships CA + the no-income-tax states (cheap wins, huge coverage); NY next.

## 7. Authoritative sources & freshness protocol

Tax law moves faster than any shipped knowledge pack. Example: the One Big Beautiful Bill Act (enacted July 2025) created new deductions effective for 2025+ returns — car-loan interest on US-assembled vehicles, tip/overtime deductions, etc. — whose exact caps, phase-outs, and form lines only exist in IRS guidance published months later. The repo therefore ships "where truth lives" as data, and the skill enforces a freshness protocol:

1. **`knowledge/sources.yaml`** — ranked registry of official sources, organized two ways:
   - **By topic (federal)** — every major area of individual tax law gets a sourced entry: filing basics (Pub 17/501), **itemized deductions** — charitable (Pub 526, Form 8283 appraisal rules), **mortgage interest** (Pub 936), SALT, medical (Pub 502), casualty; education (Pub 970, 8863); credits — CTC/EITC (Pub 596), energy (Form 5695 instructions), dependent care (Pub 503); investment income & basis (Pub 550/551, Schedule B/D); retirement (Pub 590-A/B); self-employment (Schedule C/SE instructions, Pub 463); nonresident & treaties (Pub 519, Treasury treaty tables/texts); AMT; estimated tax (Pub 505). Plus the change channels: each form's "What's New", IRS Newsroom, Internal Revenue Bulletin & annual Rev. Procs (inflation adjustments, tax tables), Congress.gov + Federal Register for enacted law, and `irs.gov/pub/irs-prior/` for exact prior-year revisions.
   - **By jurisdiction (state)** — one block **per supported state**: DOR/FTB forms & instructions pages, residency rules pages, state-specific credits/benefits pages (e.g., CA FTB renter's credit, CalEITC), treaty-conformity statements, payment portal, where-to-file. State blocks ship together with each state's knowledge pack (§6) and grow state by state.
   
   Each entry: `url`, `answers` (what questions it resolves), `cadence` (when it updates). Coverage rule: **no topic may exist in a knowledge pack or be used by a position decision without a sources.yaml entry backing it.**
2. **`effective_law_changes`** in `knowledge/<jurisdiction>/<year>.yaml` — enacted-law deltas relevant to that filing year, each with citation and status: `enacted` → `irs_guidance_pending` → `final_form_published`. Numbers without final IRS guidance are **never hardcoded**; the pack stores the lookup path instead.
3. **Skill freshness protocol (hard rule):** for any tax year newer than the newest shipped knowledge pack, or any benefit the user mentions that the pack doesn't cover, the agent MUST resolve it via `sources.yaml` URLs (web search restricted to .gov first), record the citation in `RECONCILIATION.md`, and refuse to fill any line whose authority it cannot cite. Blogs/Reddit are never authority — at most leads to a .gov citation.
4. **CI nightly:** re-fetch `sources.yaml` URLs and flag drift (moved pages, new form revisions) — same job that watches mailing addresses and PDF checksums.

## 8. MCP tool surface

| tool | purpose |
|---|---|
| `intake_checklist(profile?)` | next questions + required documents for the interview |
| `extract_document(path, kind_hint?)` | parse W-2/1099/1098/I-94/I-20/**IRS wage & income transcript**/etc. → structured fields + provenance; missing = null, never guessed |
| `residency(profile)` | federal NRA/RA/dual-status per SPT + exempt-individual years, with day-count work shown |
| `state_scope(profile, year)` | which states to file, role, forms, candidate benefits |
| `list_forms(jurisdiction?, year?)` / `get_form_map(form, year)` | discover packs; line→field map + relations |
| `fetch_blank(form, year)` | download official PDF, checksum-verify, return path |
| `fill_form(form, year, values, out_path)` | deterministic fill; comb/format handling; rejects unknown lines |
| `verify_form(path, expected?, baseline?)` | assertion diff, relation math, clipping scan, unanswered-required-checkbox audit, regression diff vs baseline |
| `verify_filing(paths[])` | cross-form identity + inter-form relations across the whole filing (federal + state) |
| `render_form(path, page?, crop?)` | PNGs returned as MCP **image content** so the calling agent vision-reviews every page |
| `calc(op, args)` | deterministic tax math engine: tax-from-taxable-income (per-year tax tables vs. schedules, honoring the IRS "use the table below $100k" rule), standard deduction, SE tax, EITC/CTC lookups and phase-outs, state tables, presence days from I-94, rounding per IRS rules, routing checksum — every result returns its inputs, the work shown, and the data-pack citation |
| `estimate_refund(profile, year)` | early bottom line from a *partial* profile: per-jurisdiction refund/owed **range**, composition breakdown, assumption list, and which missing documents/answers would change it; runs on the same deterministic `calc` engine, output always labeled ESTIMATE |
| `get_sources(topic, year, jurisdiction?)` | ranked official URLs + retrieval hints for the freshness protocol (§7) |
| `filing_summary(paths[])` | plain-language bottom line per jurisdiction (refund/owed, deadlines, statute-of-limitations status) for user approval before printing |
| `file_and_pay(filing_manifest)` | see §9 |

Server is **100% local**; only outbound traffic is fetching blank forms from official government URLs. No telemetry. Logs pass through `redact.py` (SSN/account masking). The workspace holds SSN-bearing documents at rest: README instructs users to keep OS disk encryption on (FileVault/BitLocker), and `taxfill purge <year>` wipes a workspace when done.

## 9. File & pay module (the last mile, first-class)

`file_and_pay(manifest)` takes the final set of returns (per jurisdiction, balance due / refund, paid-online flag) and emits a **personalized, human-readable checklist**:

- **Payment**: per jurisdiction — IRS Direct Pay / EFTPS / card processors / check or money order (payee, memo format `SSN + year + form`), state portals (e.g., CA WebPay); which mailing address changes when payment is enclosed vs paid online; "what to verify on the review screen before submitting" (tax year, amount, account type).
- **Print & sign**: which pages to print (form pages only, not instruction pages), single-sided, exact signature locations, which attached forms must NOT be separately signed (e.g., 8843 attached to 1040-NR), date fields.
- **Assemble**: envelope grouping (one return per envelope), attachment order by sequence number, W-2/1099 copies, what NOT to staple.
- **Mail**: addresses per jurisdiction with official verify-URLs, USPS walkthrough (Certified Mail, PS 3800, ask for postmark, costs), why PO-box addresses are USPS-only, tracking expectations.
- **Records**: photograph signed pages, keep receipts + payment confirmations, expected processing times, what mail to expect next (penalty bills for late filings, refund timing).
- **Deadlines**: due dates per year (incl. abroad automatic extension, Form 4868), **3-year refund statute of limitations** with the user's per-year expiry dates, late-filing/late-payment penalty expectations stated upfront so nothing arrives as a surprise.

Knowledge lives in `knowledge/*/<year>.yaml`; a nightly CI job re-fetches official "where to file" pages and fails loudly on drift.

## 10. Verification engine (ported from the prototype)

### Deterministic math: the no-LLM-arithmetic rule

The model never does arithmetic that lands on a return. Every number is produced by `calc` (data-driven, per-year tables with citations) at fill time and **independently recomputed by the verifier at check time** — two passes over the same versioned data, plus the human-readable work trail in `RECONCILIATION.md`, so any number can be re-confirmed at any point. Tax tables, bracket schedules, credit phase-outs, and state tables live in knowledge packs as data with source citations (§7), never hardcoded in engine code. Judgment values that cannot be recomputed (e.g., multi-state allocation percentages) must carry provenance and explicit user confirmation.

- **Assertion diff**: every filled field re-read from disk vs intended values (134-assertion clean run in the prototype).
- **Relation math** from packs, IRS rounding rules.
- **Recompute pass**: every computed line independently recomputed from its inputs via the data-pack tables and diffed against the filled value — relation math proves internal consistency; the recompute pass proves agreement with authoritative tables.
- **Clipping scan**: `len(value) × char_width(font) > rect_width` or `len > MaxLen` → flag; auto-size (`0 Tf`) treated safe. (Catches the SSN-comb-truncation class.)
- **Checkbox audit**: required Yes/No groups left fully `/Off` → flag (caught 8843 line 12, Sched OI item I).
- **Render + vision**: every page → PNG (≈170 dpi, halves for dense pages) returned to the agent for visual review.
- **Regression mode**: field-level diff vs baseline proves "only intended fields changed."
- pypdf specifics: set checkbox `/V` **and** widget `/AS`; XFA-derived root names differ per form; `update_page_form_field_values(auto_regenerate=False)`; comb fields take digits only.

### Known-pitfall registry (self-checking that compounds)

`knowledge/pitfalls.yaml`: every bug found in real use becomes (a) a permanent verifier rule, (b) a regression test, and (c) where applicable, an intake-question fix. The verify report explicitly lists each pitfall as PASS/FAIL so agents and users see the self-check happening. Seeded from production:

| id | incident | permanent countermeasure |
|---|---|---|
| P-001 | SSN truncated on 1040-NR: a dashed SSN (e.g. `000-00-0000`, 11 chars) written into a 9-cell comb field, last 2 digits clipped — invisible in field dumps, caught only by rendering | clipping scan on every filled field; `format: ssn_digits_only` on comb fields; render+vision pass mandatory before "done" |
| P-002 | User supplied historical address; bills would have gone to an old apartment | intake disambiguation (current-mailing vs historical); verifier warns when return address ≠ user-confirmed current address, or matches an address whose date range ended |
| P-003 | Required Yes/No checkboxes silently unanswered (8843 line 12, Sched OI item I) | required-checkbox audit: any required group fully `/Off` fails verification |
| P-004 | Treaty benefit nearly mis-scoped on a status-change year (F-1 → H1B still eligible for student-period income) | treaty eligibility evaluated per visa **period**, encoded in `knowledge/federal/<year>.yaml` treaty rules; covered by eval scenario |

Contributors must add a pitfall entry with every bug fix (enforced in PR template).

## 11. Skill layer

`skills/claude/SKILL.md` (mirrored to `AGENTS.md` / Copilot instructions) encodes the §2 workflow with hard rules: never invent data; user confirms extracted values before filling; verify gate is mandatory; everything framed as a review draft; the user signs and files. Includes a worked example (the F-1 back-filing story, anonymized).

**Designed for less-capable agents.** Assume the weakest agent that can emit JSON tool calls; it must still produce a verified return:

- **Tools do all PDF work.** Agents never hand-roll pypdf: `fetch_blank` downloads, `fill_form` fills, `verify_form` checks, `render_form` shows. The agent's only jobs are interviewing, deciding, and reading verify reports.
- **Cookbook recipes.** SKILL.md ships copy-paste tool-call sequences for each scenario ("simple W-2 federal return", "back-file 8843", "add a state return"), each step with expected output and the exact next call — a weak agent can follow it mechanically.
- **Prescriptive errors.** Every tool failure tells the agent what to do next (`"value '000-00-0000' exceeds comb MaxLen 9 — resubmit digits only"`, `"required checkbox group 'line12' unanswered — supply yes|no"`). Self-correction without intelligence.
- **No-MCP fallback appendix.** For environments that can run code but not MCP (bare Codex scripts, CI jobs): documented Python recipes using `packages/core` directly — download → introspect fields → fill → verify → render — so the same guarantees hold without a server. This appendix doubles as the manual for users whose agent can't follow instructions at all: they can paste the recipe verbatim.

## 12. UX principles (humanizing the experience)

Encoded as hard requirements in the skill and in tool output formats, not as vibes:

1. **Bottom line first — and early.** Users care about "refund or owe, how much, by when". `estimate_refund` puts a preliminary range on the table minutes after the first W-2 is confirmed (with assumptions stated), every milestone refreshes it with "what changed", and `filing_summary` delivers the exact number before printing. Users never wait until the end to learn whether they owe.
2. **Plain language with the math available.** Every number gets a one-sentence explanation ("you get $161 back because your employer withheld more than you owe"); the full line-by-line trail stays in `RECONCILIATION.md` for those who want it. Jargon (AGI, withholding, treaty) is explained on first use.
3. **User's language.** Interview and checklists in the user's language (the prototype ran entirely in Chinese); forms are filled in English as required; `CHECKLIST.md` bilingual on request.
4. **Visible progress.** The 9-step flow (§2) is shown as a checklist with the current step; each phase states an expected time ("intake ~10 min; you can stop and resume anytime").
5. **No surprises, no irreversible steps.** Confirmation gate before filling and before print; expectation-setting about what mail/bills will arrive (penalty bills after late filing are *announced in advance* so they don't read as scam letters or errors).
6. **Photograph guidance.** Tell users exactly what to shoot (full page, all four corners, glare-free) and confirm extraction per document so a bad photo is caught immediately, not at verify time.
7. **Anxiety-aware tone.** Taxes are scary; outputs state what is normal ("IRS will not confirm receipt; your certified-mail receipt is your proof"), what to keep, and when to worry (with the official phone/URL to check).

## 13. README & onboarding spec (non-technical users are the target reader)

The README is a deliverable with acceptance criteria, not an afterthought:

- **First screen:** what this is / is not (free, open-source, runs on your computer, you review and sign everything; not a tax preparer, no e-file), who it's for, 60-second demo GIF.
- **Zero-background quickstart, one path per client**, each a literal copy-paste sequence with screenshots:
  - *Claude Desktop / Cowork:* one-click **MCPB extension bundle** (`taxfill.mcpb`) — download, double-click, done. This is the primary non-technical path.
  - *Claude Code:* `claude mcp add taxfill -- uvx taxfill-mcp` (uvx bootstraps Python automatically — user never installs Python).
  - *Copilot / Codex CLI:* equivalent one-liners + where to paste the skill file.
- **"Your first return in 15 minutes":** an annotated real conversation transcript (anonymized) showing intake → photos → summary → printed checklist.
- **What to prepare:** document checklist with example photos.
- **Privacy in plain words:** "your documents never leave your computer; the only internet access is downloading blank forms from irs.gov; delete everything with `taxfill purge`."
- **Troubleshooting:** the five real failure modes (uv missing, permissions, client can't see the server, where output files live, how to resume).
- **FAQ:** is this legal; what if I already filed; what if I get audited (your RECONCILIATION.md is your audit trail); does it e-file (no, by design); cost (free).
- **Acceptance test for the README itself:** a person with no terminal experience must reach a filled sample form in under 20 minutes following only the README (this is an explicit M6 QA task with a non-developer tester).
- English canonical; community translations (`README.zh.md`, …) welcome.

## 14. Testing & evals

- Golden-file tests with synthetic taxpayers (no real PII) → field dumps vs golden YAML.
- Render snapshot tests (perceptual hash).
- Pack schema validation in CI; nightly checksum/address-drift job.
- Eval scenarios v1: (a) F-1 back-filing w/ treaty + 1099-NEC (the prototype case), (b) simple W-2 federal+CA resident, (c) part-year CA nonresident with remote work, (d) refund + direct deposit, (e) balance due paid online vs by check, (f) no-income-tax state ("nothing to file" answer), (g) **F-1 → H1B mid-year transition claiming Art. 20(c) on student-period wages**, (h) user who moved after the tax year (current vs historical address handling), (i) **post-2025 law change** (e.g., OBBBA car-loan-interest deduction on a 2026 filing): agent must resolve caps/eligibility via `get_sources` and cite IRS guidance — hallucinated numbers fail the eval, (j) **estimate accuracy & honesty**: for the simple W-2 scenario, the early estimate from W-2-only input must bracket the final computed refund and the range must tighten as intake completes; an estimate presented without its assumption list, or a point value presented as exact, fails the eval.
- Every pitfall in `knowledge/pitfalls.yaml` has a corresponding regression test; CI fails if a pitfall lacks one.

## 15. Milestones

- **M0 — Scaffold (1 day):** monorepo, uv/pyproject, pydantic pack & profile schemas, CI, MIT license + prominent disclaimer, CONTRIBUTING with pack-authoring guide.
- **M1 — Core engine (3 days):** formpack loader, filler, verifier (incl. independent recompute pass), render, calc (data-driven per-year tax tables/schedules + rounding + checksums), residency (SPT + exempt years). Unit + golden tests, incl. tax-table golden tests against IRS-published examples.
- **M2 — Federal packs (3 days):** f8843 (2019–2024), f1040nr + sched 1/C/OI (2022–2023), f1040 + sched 1/2/3/A/B/C (2023–2024).
- **M3 — Intake + knowledge (2 days):** profile schema, `intake_checklist`, `estimate_refund` + roadmap output, federal knowledge YAML (incl. tax tables/schedules as cited data), `sources.yaml` + `get_sources` + `effective_law_changes` registry, `file_and_pay` for federal.
- **M4 — MCP server (2 days):** wrap core (official `mcp` python-sdk, stdio); image content for renders; quickstarts: Claude Code (`claude mcp add`), Cowork, Copilot, Codex CLI.
- **M5 — State support v1 (3 days):** CA knowledge + 540/540NR packs, no-income-tax states, `state_scope`, state file_and_pay.
- **M6 — Skill + README + launch (3 days):** SKILL.md/AGENTS.md/Copilot with cookbook + freshness protocol; eval harness (all scenarios); **README per §13 incl. MCPB one-click bundle for Claude Desktop and the non-developer 20-minute acceptance test**; demo GIF; ship v0.1.
- **M7 — Scale-out:** pack-authoring CLI (`taxfill introspect blank.pdf` → pack skeleton), NY/MA/IL/NJ, more years, community pack pipeline, **amended returns (1040-X), extensions (4868), estimated-tax vouchers (1040-ES), ITIN (W-7)**.

## 16. Risks & mitigations

| risk | mitigation |
|---|---|
| wrong numbers → real penalties | no-LLM-arithmetic rule (all math from `calc` over cited data), mandatory verify gate incl. independent recompute pass, review-draft framing, human signs, evals, no auto-submit |
| users distrust AI math | every number shows its work + citation; verify report proves the independent recompute; early estimates are honest ranges with assumption lists, never fake precision |
| forms/addresses change yearly | per-year data packs; nightly drift CI fails loudly |
| state rules are messy (e.g., CA ignores treaties) | encode per-state quirks as data + tests; ship states incrementally; "must_file reason" always shown |
| PII leakage | local-only, redacted logs, zero telemetry, no uploads |
| liability / unauthorized practice | MIT + explicit "not tax advice, not a preparer; you review and file" in README, server banner, every checklist |
| PDF redistribution | fetch from official URLs + checksum, never vendor |

## 17. Naming & launch

Repo: `taxfill-mcp` (alts: `formpilot`, `openreturn`). Tagline: *“The execution layer for AI tax prep — agents think, taxfill fills, verifies, and gets it mailed.”* Launch demo: the real story — an agent back-filed five years of an international student's returns (federal), then the same engine scoped and skipped the state return with a documented reason.
