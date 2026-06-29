# TaxFill — Completion Roadmap (remaining work)

The design spec is [`docs/DEV_PLAN.md`](DEV_PLAN.md). This is the forward-looking
plan for what is **not yet done**, as of **2026-06-28**.

> **Status note (2026-06-28 rewrite).** A full claimed-vs-actual audit of the repo
> found the previous (2026-06-19) version of this file materially **understated
> completion**. Corrected below. In short: the project is **~85% done and v0.1 is
> functionally code-complete** — every engine/data workstream is finished and
> merged; what genuinely remains is (1) **launch execution** to ship v0.1 and
> (2) the **open-ended coverage breadth** (more state form packs + four new federal
> form types). There are **no remaining code blockers** for v0.1.

## Where we are (verified)

Done and on `main` (**1,307 tests, all green** — verified `pytest` run, exit 0):

- **M0 scaffold · M1 engine · M2 federal packs · M3 intake + knowledge · M4 MCP
  server (21 tools, stdio, image content) · M5 state support · M6 code/docs.**
- **MCP server — 21 tools, CI-gated** (`.github/workflows/ci.yml` asserts exactly
  21): list_forms, get_form_map, fetch_blank, fill_form, verify_form,
  verify_filing, render_form (vision Image), calc, residency, intake_checklist,
  list_document_kinds, extract_document, workspace_save, workspace_load,
  workspace_record_position, workspace_reconcile, state_scope, estimate_refund,
  get_sources, filing_summary, file_and_pay. Core = 19 modules (~9.2k LOC).
- **Phase B — single-user completeness: DONE.** `extract_document` (W-2,
  1099-NEC/INT/DIV/B, 1098-T, 1042-S, with per-field provenance) and the resumable
  workspace (`workspace_*` tools + `taxfill purge` CLI, generated RECONCILIATION.md
  / CHECKLIST.md) are implemented, merged, and tested.
- **Federal form packs — priority set DONE.** 33 packs across 2019–2024. M2 base
  set + Schedule SE/D/E + Form 8863 + Form 2555 all ship (2023), audited, golden;
  + Phase-D new form types **Form 4868** (extension) and **Form 1040-ES** (estimated-tax
  vouchers), both 2023, audited.
- **State credits — DONE for all 42 jurisdictions** (41 income-tax states + DC):
  every `knowledge/states/<st>/2023.yaml` carries a cited `credits` block (~174
  entries total); `state_scope` surfaces them as `benefits_candidates`.
- **Drift CI — DONE.** Scheduled cron job runs `scripts/check_drift.py` (form-blank
  SHA256 + source URLs + mailing addresses), 9 tests, SSL-tolerance fix merged.
- **Pack-authoring CLI — DONE.** `taxfill introspect <blank.pdf>` emits a pack
  skeleton (`packbuild.py` + `cli.py`), tested.

**Form packs that can be FILLED today (introspect→vision-map→adversarial-audit→
golden):** federal — f1040, f1040-NR, f8843, Schedule 1/2/3/A/B/C/OI/SE/D/E,
Form 8863, Form 2555. state — **18 states** (22 packs): CA (540 + 540NR +
Schedule CA 540/540NR), NY (IT-201 + IT-203), IL, PA, OH, GA, NC, MI, NJ, VA, AZ,
IN, MO, MD, **AL, CO, MN, WI**. **55 form packs total** (33 federal + 22 state).

> ⚠️ Four finished state packs (**AL, CO, MN, WI**) are currently **untracked in
> the working tree** — see Phase 0 below; commit them first.

**Quality bar (non-negotiable, applies to every item below):** no invented
numbers — every figure cited to a .gov/.us source or shipped with an explicit
`unverified` caveat; every form-pack field map adversarially **vision-audited**
before it ships; tests green; feature-branch → `--no-ff` merge.

---

## Phase 0 — Hygiene & truth-up (Effort: S — do first, hours)

Cheap, high-credibility cleanup that the audit surfaced. No new features.

- [ ] **Commit the 4 untracked state packs** (`formpacks/states/{al,co,mn,wi}/`)
      after a green `test_formpacks_states.py` round-trip. They are finished work
      sitting outside git — invisible to CI and at risk of loss.
- [x] **Reconcile the headline test count.** Verified via `pytest --collect-only`
      and a full run (**exit 0, no collection errors**): the suite is **1,307 tests,
      all green** (1,288 at audit + 3 eval scenarios k/l/m + 8 each for Form 4868 and
      Form 1040-ES). The earlier figures
      were stale/under-counted (old ROADMAP *1222*, README *~1076*, audit-sandbox
      *~903* — the sandbox couldn't run collection). README + this file now quote **1,291**.
- [x] **Update this ROADMAP to reflect reality** (this rewrite): state credits
      done, 18 states (not 14), 53 packs (not 49), Phase B done, drift CI done.

**Acceptance:** working tree clean (no untracked packs), README + this file quote
one verified test count, CI green.

---

## Phase A — Ship v0.1 (Effort: S–M, ~1–2 weeks; the real gate)

> Nothing is installable by a normal user until this lands. **No code blockers** —
> this is pure launch execution. The one external dependency is **maintainer PyPI
> credentials**. Runbooks already written: [`docs/PUBLISHING.md`](PUBLISHING.md),
> [`docs/ACCEPTANCE.md`](ACCEPTANCE.md), [`docs/DEMO.md`](DEMO.md).

- [ ] **A1 — Publish `taxfill-mcp` (+ `taxfill-core`) to PyPI.** **Verified
      PyPI-ready (2026-06-28):** data re-staged, both packages rebuilt (now include
      the AL/CO/MN/WI packs), `uvx twine check dist/*` PASSED, and the self-contained
      smoke test passed in a clean off-repo venv (21 tools + data bundled). Only the
      irreversible `uvx twine upload dist/*` remains. Enables `uvx taxfill-mcp`.
      **Manual/blocked: needs maintainer PyPI token.**
- [ ] **A2 — Tag the release.** `git tag v0.1.0` + GitHub release notes.
- [~] **A3 — Build the `.mcpb` one-click bundle.** **Manifest finalized (2026-06-28):**
      dropped the `$schema_note` draft marker, added `server.entry_point`, removed the
      now-unschema'd `permissions` block — `mcpb validate` **PASSES**. Only `mcpb pack`
      → `taxfill.mcpb` remains, and it is **publish-gated** (the bundle launches
      `uvx taxfill-mcp`, which only resolves after A1). Primary path for non-technical
      Claude Desktop users.
- [ ] **A4 — Record the 60-second demo GIF** per `docs/DEMO.md` (storyboard +
      6 beats already written) → `docs/media/demo.gif`; embed in README.
- [ ] **A5 — Run the 20-minute non-developer acceptance test** (`docs/ACCEPTANCE.md`)
      on a clean machine; fix whatever blocks a non-technical user.
- [ ] **A6 — Flip README** "not yet on PyPI / bundle coming" language to shipped.

**Acceptance:** `uvx taxfill-mcp` and the one-click `.mcpb` both work; a
non-developer reaches a filled sample form in <20 min following only the README.

---

## Phase C — Coverage breadth (Effort: XL — the long pole, parallelizable)

The dominant remaining body of work. Use the proven pipeline:
`scripts/introspect_pdf.py` (now the `taxfill introspect` CLI) → per-page
vision-mapping → `assemble_*` → adversarial vision audit → `test_formpacks_states.py`
golden round-trip.

### C1 — Remaining resident state form packs (24 jurisdictions)

18 of 42 income-tax jurisdictions are fillable. **24 remain** (23 states + DC),
all have knowledge packs but no fillable form pack yet:

`AR · CT · DC · DE · HI · IA · ID · KS · KY · LA · MA · ME · MS · MT · ND · NE ·
NM · OK · OR · RI · SC · UT · VT · WV`

- [ ] Roll out the **easy AcroForm states by population first**: KY → OR → LA →
      UT → KS → AR → OK → ID → NE → ME → MS → HI → NM-flat? → RI → MT → ND → DE →
      VT → DC. (~one feature branch per 3–5 states, `--no-ff` merge per tranche.)
- [ ] Per state: introspect → vision-map (≈6 agents) → assemble `pack.yaml`
      (relations from printed labels; `cross_form` line = federal AGI) → audit
      every page → re-audit → golden round-trip.

### C2 — Nonresident / part-year forms

Only **CA** (540NR + Schedule CA 540NR) and **NY** (IT-203) have them today.

- [ ] Add the separate nonresident/part-year return for each state that has one
      (IL Schedule NR, OH IT NRC, PA part-year, etc.) + the adjustment schedule.

### C3 — Hard states (need engine work, not just packs)

- [ ] **MA Form 1** — fetch-blocked AcroForm; needs a **downloader fix** (mass.gov
      fillable PDF the repo downloader can't retrieve).
- [ ] **IA / NM** — flat-or-XFA forms; reuse the federal XFA handling.
- [ ] **CT / SC** — print-only; need an **OCR-positioned overlay filler** engine
      (or a documented "print + hand-fill from computed values" fallback).

**Acceptance (each pack):** loads; golden round-trip clean (fill→verify→render all
pages); field map audited clean. **Effort: XL. Deps:** C1/C2 pipeline ready;
C3 hard states depend on new downloader + overlay-filler engine work.

---

## Phase D — Scale-out: new form types & tooling (Effort: L–XL)

### D1 — New federal form TYPES (2 of 4 done)

Each needs PDF → schema → vision-map → adversarial audit → tests, on the existing
pipeline (the `taxfill introspect` CLI seeds the field map).

- [x] **4868** (automatic extension) — **DONE (2026-06-29)**, 2023. 16 page-1
      widgets mapped (root `topmostSubform[0]`); relation `6 == max(0, 4 - 5)`
      (balance due); `mailing: null` (state-by-state table owned by the knowledge
      layer, like f1040); no signature block. Golden round-trip green + adversarial
      vision audit clean (every line placed correctly). `formpacks/federal/2023/f4868/`.
- [x] **1040-ES** (estimated-tax vouchers) — **DONE (2026-06-29)**, 2023. All four
      quarterly payment vouchers mapped (V1–3 on PDF page 11, V4 on page 9), 14
      fields each (amount + your & spouse name/SSN + address split). The Estimated
      Tax Worksheet and the "Record of Estimated Tax Payments" ledger are the filer's
      private computation ("Keep for Your Records"), so their ~70 widgets are not
      mapped. `mailing: null`; no signature block. Golden round-trip green +
      adversarial vision audit clean (each voucher's amount on the right quarter).
      `formpacks/federal/2023/f1040es/`.
- [ ] **1040-X** (amended return) — high demand, moderate field count.
- [ ] **W-7** (ITIN application) — hardest; likely needs new field types
      (photo/signature) in the filler.

### D2 — Breadth follow-ons

- [ ] More tax years for the state packs (federal already spans 2019–2024).
- [ ] Community pack-contribution pipeline (the `taxfill introspect` CLI is the
      seed; document the author→audit→PR flow).

**Acceptance:** each new form type audited + golden-tested; any computed line
backed by cited `calc` data. **Deps:** none for D1 (CLI ready); D2 builds on D1.

---

## Phase E — Test & eval hardening (Effort: S–M)

- [x] **Finish the §14 eval suite — DONE (2026-06-28).** `evals/test_scenarios.py`
      now implements all **13 scenarios (a–m)**, green: **(k)** MFJ two W-2s (joint
      standard deduction/brackets + both-signature checklist), **(l)** MFJ-vs-MFS
      comparison (engine computes both ways → `RefundEstimate.comparison` carries the
      recommendation, dollar delta, and joint-liability caveat), **(m)** NRA-spouse
      §6013(g) election (MFJ dropped → MFS, election + worldwide-income trade-off
      surfaced in both estimate and intake, authority via `get_sources`).
- [ ] Wire the true test count (1,307) into a CI badge / README line.

**Acceptance:** all 13 eval scenarios run green (**met**); one authoritative test count.

---

## Phased sequencing (recommended order)

1. **Phase 0** (hours) — commit untracked packs, fix test-count truth. Do today.
2. **Phase A** (1–2 wks) — ship v0.1. Highest leverage: flips the product from
   "from-source only" to installable. Only external dep is a PyPI token.
3. **Phase E** (parallel, low cost) — close the 3 eval scenarios; hardens tax logic
   before broad rollout.
4. **Phase C** (months, parallelizable) — the long pole. Roll out resident state
   packs by population using the `introspect` CLI; defer hard states (C3) until the
   downloader fix + overlay filler are built.
5. **Phase D** — new federal form types (✅ 4868 + ✅ 1040-ES done; remaining
   1040-X → W-7), then breadth follow-ons.

Phases A, E, and the start of C are largely independent and can run in parallel.
Within C, resident packs (C1) are the long pole; the now-working `introspect` CLI
is the force multiplier. C3 hard states and D1's W-7 are the only items needing
**new engine code** (downloader fix, overlay filler, new field types).
