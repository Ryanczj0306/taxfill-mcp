# TaxFill — Completion Roadmap (remaining work)

The design spec is [`docs/DEV_PLAN.md`](DEV_PLAN.md). This is the forward-looking
plan for what is **not yet done**, as of **2026-07-09**.

> **Status note (2026-07-07 update).** Since the 2026-06-28 truth-up: Phase F
> (estimator/domain completeness, F1–F10) shipped; a 5-persona real-filer review
> (MFJ family / NRA student / RA + dual-status / NRA-spouse §6013(g)(h) couple /
> naive UX; 46 adversarially-verified findings) drove two fix waves — Tier 1
> (25 wrong-law/UX point fixes: NRA standard deduction, verify's independent
> recompute over MCP, W-7/8843 logistics, intake dead-ends) and Tier 2 (the four
> broken paths: §6013 election end-to-end, Schedule 8812 + CTC/EITC calc ops,
> Schedule A (1040-NR) + Schedule NEC, treaty_exempt_income). What remains is
> (1) **launch execution** (Phase A — unchanged, user-gated), (2) coverage
> breadth (Phases C/D), and (3) the **Phase G subsystems** below — **BUILT
> 2026-07-09** (G1/G2/G3/G5/G6 done; G4 first tranche = the 8 flat-rate
> states, graduated states remain): treaty knowledge base (5 countries),
> Form 2441 engine + pack, monthly 8962, dual-status corridor, FICA 843/8316
> flow, state_tax calc op.

## Where we are (verified)

Done and on `main` (**2,816 tests, all green** — offline 2,711 + live-.gov 105, exit 0;
re-verified 2026-08-07 via `pytest -m "not network"`, exit 0):

- **M0 scaffold · M1 engine · M2 federal packs · M3 intake + knowledge · M4 MCP
  server (22 tools, stdio, image content) · M5 state support · M6 code/docs.**
- **MCP server — 22 tools, CI-gated** (`.github/workflows/ci.yml` asserts exactly
  22): list_forms, get_form_map, fetch_blank, fill_form, verify_form,
  verify_filing, render_form (vision Image), calc, residency, intake_checklist,
  list_document_kinds, extract_document, workspace_save, workspace_load,
  workspace_record_position, workspace_reconcile, state_scope, estimate_refund,
  get_sources, filing_summary, file_and_pay, hand_fill_worksheet (print-only
  states). The `calc` tool carries 17 deterministic ops (tax, tax_with_preferential_rates, standard_deduction, se_tax, additional_medicare_tax, niit, taxable_social_security, excess_ss, student_loan_interest_deduction, education_credits, ptc_annual, ptc_monthly, child_tax_credit, eitc, dependent_care_credit, treaty_benefit, state_tax).
- **Phase B — single-user completeness: DONE.** `extract_document` (W-2,
  1099-NEC/MISC/INT/DIV/G/B/R, SSA-1099, 1095-A, 1098-T/E, 1042-S, with per-field
  provenance — K-1 is the one common document still unsupported) and the resumable
  workspace (`workspace_*` tools + `taxfill purge` CLI, generated RECONCILIATION.md
  / CHECKLIST.md) are implemented, merged, and tested.
- **Federal form packs — priority set DONE.** **57 packs across 2019–2025**
  (2019:1, 2020:1, 2021:1, 2022:5, 2023:28, 2024:8, 2025:13). M2 base
  set + Schedule SE/D/E + Form 8863 + Form 2555 all ship (2023), audited, golden;
  + **all four Phase-D new form types** — **Form 4868** (extension), **Form 1040-ES**
  (estimated-tax vouchers), **Form 1040-X** (amended return, Rev. 2-2024), and
  **Form W-7** (ITIN application, Rev. 12-2024) — all audited.
- **State credits — DONE for all 42 jurisdictions** (41 income-tax states + DC):
  every `knowledge/states/<st>/2023.yaml` carries a cited `credits` block (~174
  entries total); `state_scope` surfaces them as `benefits_candidates`.
- **Drift CI — DONE.** Scheduled cron job runs `scripts/check_drift.py` (form-blank
  SHA256 + source URLs + mailing addresses), 9 tests, SSL-tolerance fix merged.
- **Pack-authoring CLI — DONE.** `taxfill introspect <blank.pdf>` emits a pack
  skeleton (`packbuild.py` + `cli.py`), tested.

**Form packs that can be FILLED today (introspect→vision-map→adversarial-audit→
golden):** federal — f1040, f1040-NR, f8843, Schedule 1/2/3/A/B/C/OI/SE/D/E/8812,
Schedule A (1040-NR), Schedule NEC, Forms 8863, 2555, 4868, 1040-ES, 1040-X, W-7,
8959, 8960, 8962, 2441, 843 (Rev. 12-2024), 8316. state — **all 42 income-tax
jurisdictions**: **38 via fillable AcroForm (42 packs)** — CA (540 + 540NR +
Schedule CA 540/540NR), NY (IT-201 + IT-203), IL, PA, OH, GA, NC, MI, NJ, VA, AZ,
IN, MO, MD, AL, CO, MN, WI, KY (740), OR (OR-40), LA (IT-540), KS (K-40),
AR (AR1000F), ID (40), NE (1040N), OK (511), ME (1040ME), MS (80-105),
RI (RI-1040), MT (Form 2), ND (ND-1), DE (PIT-RES), VT (IN-111), DC (D-40),
WV (IT-140), IA (IA 1040), MA (Form 1), UT (TC-40) — plus **4 via print/hand-fill
manifests**: CT (CT-1040), HI (N-11), NM (PIT-1), SC (SC1040).
**103 form packs total** — 99 `pack.yaml` (57 federal + 42 state) + 4 `handfill.yaml`.
> ⚠️ Every **state** form pack is **TY2023 only**. State *knowledge* now spans
> 2023–2025, so `calc.state_tax` computes years that no pack can fill — the single
> largest coverage asymmetry in the repo (see D2).

> ✅ The four formerly-untracked state packs (**AL, CO, MN, WI**) are now committed
> (Phase 0, 2026-06-28) and counted above.

**Quality bar (non-negotiable, applies to every item below):** no invented
numbers — every figure cited to a .gov/.us source or shipped with an explicit
`unverified` caveat; every form-pack field map adversarially **vision-audited**
before it ships; tests green; feature-branch → `--no-ff` merge.

---

## Phase 0 — Hygiene & truth-up (Effort: S — do first, hours)

Cheap, high-credibility cleanup that the audit surfaced. No new features.

- [x] **Commit the 4 formerly-untracked state packs** (`formpacks/states/{al,co,mn,wi}/`)
      — DONE (2026-06-28) after a green `test_formpacks_states.py` round-trip; merged
      via `feat/state-rollout-al-co-mn-wi`. Working tree is now clean.
- [x] **Reconcile the headline test count.** Verified via `pytest --collect-only`
      and a full run (**exit 0, no collection errors**): the suite was **1,401 tests,
      all green** at the time of this 2026-06-28 truth-up (1,288 at audit + 3 eval
      scenarios k/l/m + 8 each for Forms 4868, 1040-ES, 1040-X, and W-7). The earlier
      figures were stale/under-counted (old ROADMAP *1222*, README *~1076*,
      audit-sandbox *~903*). The count has since grown with each phase (see the
      header); the README tests badge is kept in sync with the verified number.
- [x] **Update this ROADMAP to reflect reality** (this rewrite): state credits
      done, 35 states (not 14), 74 packs (not 49), Phase B done, drift CI done.

**Acceptance:** working tree clean (no untracked packs), README + this file quote
one verified test count, CI green.

---

## Phase A — Ship v0.1 (Effort: S–M, ~1–2 weeks; the real gate)

> Nothing is installable by a normal user until this lands. **No code blockers** —
> this is pure launch execution. The one external dependency is **maintainer PyPI
> credentials**. Runbooks already written: [`docs/PUBLISHING.md`](PUBLISHING.md),
> [`docs/ACCEPTANCE.md`](ACCEPTANCE.md), [`docs/DEMO.md`](DEMO.md).

- [ ] **A1 — Publish `taxfill-mcp` (+ `taxfill-core`) to PyPI.** **Verified
      PyPI-ready (re-verified 2026-06-29):** data re-staged and both packages rebuilt
      so the wheel now bundles **all 19 federal 2023 packs** (incl. the new f4868 /
      f1040es / f1040x / fw7) **and** the AL/CO/MN/WI state packs; `uvx twine check
      dist/*` PASSED; the self-contained off-repo smoke test passed (22 tools + the 4
      new federal packs load from the installed wheel). **Re-run `stage_data.py` + `uv
      build` immediately before upload** (dist/ is gitignored, so a stale wheel never
      shows in the tree). Only the irreversible `uvx twine upload dist/*` remains.
      **Manual/blocked: needs maintainer PyPI token.**
      **⚠️ Release blocker found + fixed 2026-08-04 by the first CI run in weeks:**
      the MCP python-sdk released **2.0.0**, which REMOVED the high-level FastMCP
      API from the `mcp` distribution (extracted upstream to a standalone
      `fastmcp` package — the 2.0 wheel contains no fastmcp module), so the
      unbounded `mcp>=1.2` dependency resolved to 2.0 in a clean venv and the
      installed wheel died on `from mcp.server.fastmcp import FastMCP, Image`.
      Dependency is now capped `mcp>=1.2,<2` (uv.lock already held 1.28, which is
      why every local run stayed green — only the packaging job's clean-venv
      install exposed it). **Follow-up before/at publish:** decide whether v0.1
      ships on 1.x (cap stays) or migrates to the standalone `fastmcp` package /
      mcp 2.x low-level server API; either way re-run the packaging smoke test.
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

### C1 — Resident state form packs — **COMPLETE, all 42 jurisdictions (2026-07-24)**

**42 of 42** income-tax jurisdictions ship a resident return pack — the easy
fillable-AcroForm rollout finished 2026-07-01 (six C1 tranches, 17 states; WV
IT-140 was the last), and the final 7 former C3 hard states shipped 2026-07-24
(MA via Wayback cache-seed; IA via Iowa's own fillable variant; UT via the
files.tax.utah.gov year path; CT/SC/NM/HI as hand-fill manifests):

`CT · HI · IA · MA · NM · SC · UT` — all shipped (see C3 below for how each blocker fell)

- [x] Tranche 1 (2026-06-30) — **KY (740), OR (OR-40), LA (IT-540)**.
- [x] Tranche 2 (2026-06-30) — **KS (K-40), AR (AR1000F)**.
- [x] Tranche 3 (2026-06-30) — **ID (40), NE (1040N), OK (511)**. (NE line-43 use-tax
      sub-fields and an OK 511/538-S shared-control collision were caught by the
      adversarial audit and fixed before merge.)
- [x] Tranche 4 (2026-06-30) — **ME (1040ME), MS (80-105), RI (RI-1040)**.
- [x] Tranche 5 (2026-06-30) — **MT (Form 2), ND (ND-1), DE (PIT-RES), VT (IN-111),
      DC (D-40)**. (MT is the largest state pack: 780 mapped widgets over 11 pages.
      A misnamed MT "Other additions" widget /T and two 529-deposit field types were
      corrected via the adversarial audit + hand-review before merge.)
- [x] Tranche 6 (2026-07-01) — **WV (IT-140)** — the 45-page PIT packet scoped to the
      resident IT-140 return + its schedules (Schedule A nonresident-only, WV4868, and
      the tax-table/instruction pages excluded); 391 widgets, golden green + audit clean.
- The 7 remaining states (CT, HI, IA, MA, NM, SC, UT) are all **C3 hard states** — see
  the (investigated) C3 section below for the specific blocker + options per state.
- [x] **UT (TC-40) — RESOLVED (2026-07-24):** year-labeled artifacts DO exist: files.tax.utah.gov/tax/forms/<year>/tc-40.pdf serves 2023 (and 2024; /current/ = 2025) — the tax.utah.gov redirect strips the filename, which is why they looked missing. 2023 pack shipped (core TC-40 pages of the 9-page fillable packet, WV precedent). *(was: deferred / sourcing blocker:* Utah serves a year-agnostic
      `tc-40.pdf`; the `…/forms/2023/tc-40.pdf` path actually returns the **2025**
      revision (confirmed by rendering — line 17 shows the 2025 phase-out thresholds,
      line 2c "born in 2025"). A true 2023 TC-40 blank isn't available at a stable URL,
      so UT was NOT shipped as a 2023 pack (would mis-label the form). Revisit when a
      2023 artifact is locatable, or fold UT into a future 2024/2025 state tranche (D2).
- [x] Per state: introspect → vision-map → assemble `pack.yaml` → audit every
      page → golden round-trip — pipeline COMPLETE for all 42 jurisdictions
      (2026-07-24).

### C2 — Nonresident / part-year forms

Only **CA** (540NR + Schedule CA 540NR) and **NY** (IT-203) have them today.

- [ ] Add the separate nonresident/part-year return for each state that has one
      (IL Schedule NR, OH IT NRC, PA part-year, etc.) + the adjustment schedule.

### C3 — Hard states (need engine work, not just packs)

**Investigated 2026-07-01.** Each hard state needs a heavyweight NEW subsystem or
dependency — an architecture call for the maintainer, not a quick fix:

- [x] **MA Form 1 — SHIPPED (2026-07-24) via option (b') Wayback cache-seed:** the
      Wayback Machine archives the exact official mass.gov URL's AcroForm artifact
      (172 widgets, digest-pinned); seeded into `.cache/blanks/` at the deterministic
      name — `fetch_blank` is cache-first and will digest-verify if mass.gov ever
      unblocks. 156 lines mapped, sentinel-audited. DOR's own AcroForm defect (the
      taxpayer/spouse oval pairs named '0'/'1' share one field each) documented in
      the pack header. *(was:* the mass.gov PDF *is* a fillable AcroForm, but the download is
      **bot-blocked at the edge (Akamai)**: `fetch_blank` gets **HTTP 403** and even
      `curl` with a full desktop-browser header set (UA + Accept + Accept-Language +
      Accept-Encoding) is refused with a 3 KB challenge page. This is TLS/JS-challenge
      fingerprinting, NOT a missing-header problem — a header tweak to `fetch.py` will
      not fix it. Options: (a) a **headless-browser fetch path** (Playwright/Chromium,
      ~300 MB — heavy for a stdlib MCP); (b) a **manual cache-seed** flow (a human opens
      the URL in a browser once and drops the PDF into `.cache/blanks/`, then the normal
      pipeline runs); (c) an official non-challenged mirror if one exists. Once the blank
      is in hand, MA is an ordinary AcroForm pack.
- [x] **IA / NM — CLASSIFIED AND SHIPPED (2026-07-24):** IA was never hard —
      revenue.iowa.gov publishes a FILLABLE AcroForm variant of every year's IA 1040
      behind its Form Options gateway (2023 media/2747, plain names, no XFA); full
      5-page pack incl. embedded Schedule 1 shipped, sentinel-audited. NM PIT-1 is
      deliberately print-only in every year (TRD pushes TAP e-file) — shipped as a
      complete hand-fill manifest. *(was:* classify first (both candidate URLs 404'd during this pass — need
      the current official URLs). NOTE: the engine's "XFA handling" only covers
      **XFA-*derived* AcroForms** — forms that ship real AcroForm widgets with
      hierarchical `topmostSubform[0].PageN[0]…` names (federal 1040, and RI-1040 which
      shipped fine). It does NOT render **pure/dynamic XFA** (XFA-only, no AcroForm
      widget layer). If IA/NM are XFA-derived AcroForms they go through the normal
      pipeline; if pure-XFA or flat print-only they need (c) below.
- [x] **CT / SC / HI — COMPLETE (2026-07-24):** CT-1040 and SC1040 hand-fill packs
      shipped on the HI pattern — complete printed-line manifests (all pages/schedules,
      face-printed arithmetic as compute exprs, table lookups as notes, printed mailing
      addresses). *(was [~]:* print-only (no AcroForm, no XFA — HI N-11 2023 confirmed flat:
      0 fillable widgets). **The lighter "print + hand-fill from computed values" fallback
      is BUILT (2026-07-01)** and shipped for **HI (N-11)**: a `render_mode: hand_fill`
      pack is a line manifest (`handfill.yaml`), and `hand_fill_worksheet` (MCP tool #22,
      engine `taxfill_core.handfill`, reusing the verifier's expression evaluator) computes
      every derivable line and emits an ordered line→value worksheet to hand-write onto the
      printed blank — no OCR, no new dependency, no risk to the AcroForm pipeline.
      **Remaining:** add hand-fill packs for **CT (CT-1040)** and **SC (SC1040)** on the
      same pattern (read the form, list lines + compute exprs). A true fillable experience
      would still want the heavier **OCR-positioned overlay filler** (stamp text at located
      field coordinates) — deferred.

**Acceptance (each pack):** loads; golden round-trip clean (fill→verify→render all
pages); field map audited clean. **Effort: XL. Deps:** C1/C2 pipeline ready;
C3 hard states depend on new downloader + overlay-filler engine work.

---

## Phase D — Scale-out: new form types & tooling (Effort: L–XL)

### D1 — New federal form TYPES (4 of 4 — DONE)

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
- [x] **1040-X** (amended return) — **DONE (2026-06-29)**, tax year 2023 via the
      **Rev. February 2024** revision (the one that amends 2021–2023; the current
      irs-pdf Rev. 12-2025 has 2025 OBBBA lines and is wrong for 2023). ~115 fields:
      header + filing-status radio + the A/B/C column model (correct amount = bare
      line id, column A = `<line>.original`, B = `<line>.net_change`), dependents,
      explanation, signature/preparer. On-face column-C math encoded as relations
      (`3 == 1 - 2`, `11 == 8 + 10`, `20 == max(0, 11 - 19)`, …). Golden round-trip
      green + adversarial vision audit clean. `formpacks/federal/2023/f1040x/`.
- [x] **W-7** (ITIN application) — **DONE (2026-06-29)**, tax year 2023 via the
      Rev. December 2024 revision. The "needs new field types (photo/signature)"
      worry did **not** materialize: W-7 is a plain single-page AcroForm (the ID
      documents are attached separately, not PDF fields). 65 widgets mapped:
      application-type / gender / ID-document / prior-ITIN / delegate radios,
      reasons a–h, name(s), mailing + foreign address, comb date-of-birth /
      exp-date / entry-date, citizenship/visa, 6f ITIN/IRSN comb segments,
      acceptance-agent block. Golden round-trip green + adversarial vision audit
      clean. `formpacks/federal/2023/fw7/`.

### D2 — Breadth follow-ons

- [~] More tax years for the state packs — **KNOWLEDGE DONE, FORM PACKS NOT STARTED.**
      State *knowledge* now spans three years: 2023 42/42, 2024 42/42, 2025 41/42
      (**RI 2025 is the only hole**), every pack carrying the same 18 blocks incl. a
      typed `tax` block, auto-enrolled into the suite by the glob at
      `test_state_knowledge.py:26`. State *form* packs remain **TY2023 only** — so a
      2024/2025 state return computes but cannot be filled. Federal spans 2019–2025
      for forms and 2019–2026 for knowledge (the TY2025 OBBBA set, 13 packs incl. the
      new Schedule 1-A, + knowledge/federal/2025.yaml shipped 2026-07-25; the
      provisional 2026 planning pack shipped 2026-08-04).
      **Remaining:** (a) RI 2025; (b) a 2024→2025 **state form pack** tranche — 46
      packs/year, and the pipeline is NOT ready to make it cheap: `fetch_blank` takes
      a literal URL+digest, only 34 of 46 state URLs carry a substitutable year token,
      MA needs a Wayback cache-seed every year, and there is no generic assembler;
      (c) `assemble_state_knowledge.py` is still 2023-hardcoded and reads `/tmp/*.json`
      inputs that no longer exist, so the 2024/2025 cohorts are **not reproducible from
      the repo** (`assemble_state_credits.py` gained a `[YEAR]` argument 2026-08-07);
      (d) DEV_PLAN §7.2 `effective_law_changes` blocks — **0 of 125** state packs and
      **0 of 8** federal packs carry one.
- [ ] Community pack-contribution pipeline (the `taxfill introspect` CLI is the
      seed; document the author→audit→PR flow).

**Acceptance:** each new form type audited + golden-tested; any computed line
backed by cited `calc` data. **Deps:** none for D1 (CLI ready); D2 builds on D1.

---

## Phase F — Estimator & tax-domain completeness (Effort: L–XL, itemized)

> Found by the 2026-07-01 tax-domain audit; **BUILT 2026-07-06** (research: two-pass
> web verification of every parameter against IRS primary sources, zero discrepancies;
> engine: knowledge blocks 2019-2024 + calc ops + estimator integration + form packs,
> each adversarially audited). Remaining sub-items are listed inline.

- [x] **F1 — Qualified dividends / LTCG preferential rates — DONE.** `calc.tax_with_preferential_rates` (QDCGT worksheet, 0/15/20 stacking, per-year breakpoints 2019-2024), signed `capital_gain_long/short` + `qualified_dividends` snapshot fields, 1099-B/DIV extraction, estimator integration. *(was:* The
      biggest silent mis-tax for investors: `IncomeSnapshot` needs `qualified_dividends`
      + `capital_gain_long/short` fields, knowledge needs the per-year 0%/15%/20%
      breakpoints (Rev. Proc. 2022-38 §3.03 for 2023 — the rp-22-38.pdf URL is already
      cited in the pack), calc needs the worksheet, and extraction needs a 1099-B
      DocSpec. extract already captures 1099-DIV box 1b/2a but the amounts have
      nowhere to go today.
- [x] **F2 — CTC/ODC/EITC in the estimate — DONE.** DOB+SSN-based qualifying-child tests, $50-per-$1,000 ceil phaseout, ACTC 15% refundability, 2021 ARPA two-tier fully-refundable handling, EITC formula (disclosed $50-band approximation) with investment-income gate. *(was:* `knowledge/federal/2023.yaml` already
      ships cited CTC/ACTC/ODC/EITC parameters that NOTHING consumes; the estimate's
      "before unclaimed credits" range could compute them. Prereq: dependent date-of-
      birth (age tests) in the profile schema + earned-income definition. EITC needs
      the phase-in/out math; CTC needs the $50-per-$1,000 MAGI step + ACTC 15% earned-
      income refundability cap.
- [x] **F3 — Excess Social Security withholding credit — DONE.** `calc.excess_ss` (multiple-employers rule), cited per-year employee-SS params, `ss_withheld_by_employer` snapshot field. *(was:* Two
      employers over the wage base is common and pure arithmetic: needs a cited
      employee-rate param (6.2%) + `excess_ss` calc op + per-employer withholding
      inputs. W-2 boxes 3/4 are already extracted and the line is already fillable.
- [x] **F4 — Retirement income — DONE.** SSA-1099 + 1099-R DocSpecs, `calc.taxable_social_security` (worksheet incl. both MFS paths), snapshot fields + estimator wiring. *(was: SSA-1099 / 1099-R DocSpecs + the taxable-Social-
      Security worksheet** ($25k/$32k/$34k/$44k bases) as a calc op + estimate field.
- [x] **F5 — Premium Tax Credit reconciliation — DONE (2023/2024).** 1095-A DocSpec, fillable f8962 pack (141 fields, vision-audited), `calc.ptc_annual` (FPL tables, integer Table-2 lookup, Table-5 repayment caps), estimator net-credit/repayment. Pre-2023 years raise prescriptively (pre-IRA tables not shipped). *(was:* The one
      omission that can flip a refund into a balance due. Minimum first step: an
      intake question + assumption line (DONE — disclosed); full build = 1095-A
      DocSpec + f8962 pack + FPL/applicable-percentage knowledge.
- [x] **F6 — Education credits — DONE.** `calc.education_credits` (AOTC per-student + 40% refundable, LLC per-return, per-year phaseouts incl. pre-2021 LLC indexing); AOTC in the estimate; LLC via the calc op. *(was: parameters + calc*, connecting the
      already-extracted 1098-T and the already-fillable Form 8863.
- [x] **F7 — Above-the-line adjustments — DONE.** `calc.student_loan_interest_deduction` (per-year MAGI phaseouts, MFS=0) + `pre_agi_adjustments` confirmed-amounts field. *(was:* (student-loan interest w/ MAGI phase-out;
      generic confirmed-adjustments field for IRA/HSA/educator).
- [x] **F8 — Signed amounts — DONE.** `self_employment_net` and capital fields signed; -3,000/-1,500 capital-loss clamp with carryover disclosure. *(was: capital losses and SE losses.* All
      `IncomeSnapshot` fields are `ge=0` today, so losses cannot be represented.
- [x] **F9 — Form packs for 8959/8960/8962 — DONE** (26/38/141 fields, independent adversarial vision audits clean; the audit caught and removed a text-line relation on 8962). **AMT (Form 6251) remains out of scope** — disclosed in the estimate's assumptions. *(was: packs for 8959/8960* (fillable attachments; the amounts already
      land on Schedule 2 lines 11/12) and, low priority, **AMT (Form 6251)**.
- [x] **F10 — True two-return MFS comparison — DONE.** `IncomeSnapshot.spouse` sub-snapshot: MFJ combines, MFS computes two returns and sums; the worst-case bound (disclosed) remains only the no-spouse-data fallback. *(was:* (per-spouse income splits; today's MFS
      figure is a disclosed worst-case bound with combined income on one return).

---

## Phase E — Test & eval hardening (Effort: S–M)

- [x] **Finish the §14 eval suite — DONE (2026-06-28).** `evals/test_scenarios.py`
      now implements all **13 scenarios (a–m)**, green: **(k)** MFJ two W-2s (joint
      standard deduction/brackets + both-signature checklist), **(l)** MFJ-vs-MFS
      comparison (engine computes both ways → `RefundEstimate.comparison` carries the
      recommendation, dollar delta, and joint-liability caveat), **(m)** NRA-spouse
      §6013(g) election (MFJ dropped → MFS, election + worldwide-income trade-off
      surfaced in both estimate and intake, authority via `get_sources`).
- [x] Wire the true test count into a CI badge / README line — DONE (2026-07-01): live CI-status badge + a tests badge kept in sync with the verified count.

**Acceptance:** all 13 eval scenarios run green (**met**); one authoritative test count.

---

## Phase G — Persona-review subsystems (Tier 3; Effort: L–XL each, independent)

> The 2026-07-06 five-persona review surfaced six gaps that need a **new
> subsystem or dependency**, not a point fix. Tier 1+2 already shipped the
> stopgaps: every item below is currently a **disclosed limitation** (an
> estimate assumption, a prescriptive error, or a get_sources pointer), so
> nothing fails silently — these build the real capability. Items are
> independent and can be scheduled in any order; suggested priority ranks by
> (population hit × dollar impact).

- [x] **G1 — DONE (2026-07-09).** knowledge/treaties/{china,india,korea,canada,mexico}.yaml (two-pass verified vs treaty texts + Pub 901 (9-2024), zero discrepancies) + `treaty_benefit` calc op (per-class validation incl. India Art. 21(2) parity + Art. 22 retroactive loss, Canada Art. XV $10,000 cliff, Mexico no-benefit) + estimator cross-check of treaty_exempt_income vs the country limit. *(was: Per-country treaty knowledge base (L–XL; highest value for the
      NRA persona).** Today `treaty_exempt_income` carries an agent-confirmed
      amount (trust-the-agent semantics) and `get_sources` points at Pub 901/519.
      Build: a `knowledge/treaties/` data layer — per country: article, income
      class (student/teacher/researcher wages, scholarships), dollar/time limits,
      saving-clause exceptions, eligibility predicates (visa category + period) —
      cited to the treaty text + technical explanation on irs.gov; a calc op
      `treaty_benefit(country, visa_periods, income_class, year)`; estimator/
      Schedule OI integration (auto-fill articles/amounts). Start with the top
      student countries (China, India, Korea, Canada, Mexico). The per-period
      eligibility rule (pitfall P-004) already has engine groundwork in
      residency.py.
- [x] **G2 — DONE (2026-07-09).** dependent_care knowledge blocks 2019-2024 (incl. 2021 ARPA 50%/8k/16k dual phase-down + refundability), `dependent_care_credit` calc op, f2441 pack (75 fields, vision-audited clean), estimator fields + intake question. *(was:* The persona
      review showed its absence can flip an MFJ-vs-MFS recommendation. Build:
      knowledge params (35%→20% AGI slide, $3,000/$6,000 caps, earned-income
      limits), a calc op, a 2441 form pack (AcroForm, standard pipeline),
      estimator field (care expenses + care-provider count), intake question.
- [x] **G3 — DONE (2026-07-09).** `ptc_monthly` calc op (12-row grid, line-8b monthly contribution, shared settle tail with ptc_annual — annual behavior byte-identical), e2e dispatch + goldens. *(was:* `ptc_annual` covers full-year
      coverage; part-year/changing coverage (the common 1095-A case) needs the
      lines 12–23 monthly grid: a `ptc_monthly` calc op taking 12 rows of
      premium/SLCSP/APTC (the 1095-A DocSpec already extracts them), plus
      estimator wiring. The f8962 pack already maps the monthly grid fields.
- [x] **G4 — DONE (2026-07-24).** **First tranche (2026-07-09): the 8 flat-rate states** (IL/PA/IN/MI/NC/CO/KY/AZ — typed StateTaxParams blocks, verifier-corrected data incl. AZ line 38-41 exemptions, `state_tax` calc op wired into Recipe C's verify-independent step). **Second tranche engine (2026-07-16):** `StateTaxParams` per-filing-status `brackets` (exactly one of flat_rate/brackets; zero-rate floors for the OH/MS shape; contiguity enforced), `calc.state_tax` marginal-bracket math with per-bracket work lines + `rate_structure`/`marginal_rate`, `base` gained `state_taxable_income` (WI-style income-dependent deductions). **Second tranche data (2026-07-24): all 27 graduated states shipped** (AL AR CA DC DE GA ID KS LA MD ME MN MO MS MT ND NE NJ NY OH OK OR RI VA VT WI WV) after the mandatory two-pass verification — pass 1 = the salvaged 2026-07-16 research, pass 2 = per-state verification of every figure against the official 2023 instructions (booklet PDFs / live DOR pages; VT via the Wayback copy + the NFC withholding bulletin after tax.vermont.gov 403'd everything). Verdicts: 12 clean / 15 corrected — the corrections: 11 packs' `base` re-adjudicated `state_gross_income`→`federal_agi` (the form starts from a printed federal-AGI line; IL precedent — state_gross_income is reserved for PA/NJ/MS-style own-income systems), 8 credit-exemption states' vector counts zeroed (CA $144/$446, OR $236, NE $157, AR $29 credits; LA/MS exemptions folded into floor/deduction), WV `standard_deduction` all-zeros → null. Assembled by `scripts/assemble_state_tax_blocks.py` (two gates: typed round-trip with exact-Decimal rates; every vector recomputed through the real engine — 128 vectors, incl. booklet tax-table rows and VT's official worked example). Known modeled-divergence disclosures (quoted in every work string): OH's $360.69 schedule jump, NY's >$107,650 recapture worksheets, AR's >$89,600 bracket-adjustment phase-down, KS's $2,500/$5,000 zero-tax cliff + QSS→HoH mapping, LA/MS dependent-exemption mechanics, tax-table mandates. 133 new tests (128 goldens + 5 behavior). *(was:* State returns fill/verify
      today but the tax LINES are model arithmetic — no state calc op exists and
      rates live only in pack comments. Build per adopted state: a knowledge
      `tax` block (rates/brackets/exemptions, cited), a `state_tax` calc op
      keyed by jurisdiction, and relation coverage. Start with the flat-rate
      states (IL 4.95%, PA 3.07%, ...) where one op covers the whole return,
      then CA/NY brackets.
- [x] **G5 — DONE (2026-07-09).** Concrete dual-status roadmap steps (return+statement mechanics, First-Year-Choice election via workspace positions, no-standard-deduction, due-date nuance), file_and_pay `dual_status` manifest flag (top-annotation + statement assembly), sources.yaml dual_status topic, eval scenario (p), SKILL Recipe B3. *(was:* residency correctly flags
      `dual_status_candidate` and the estimator now restricts statuses and
      discloses, but there is no prepared path for the actual split-year
      filing (1040 + 1040-NR statement, first-year choice election text,
      residency start-date math). Build: a dual-status guide surface (roadmap
      steps + statement checklist in file_and_pay), first-year-choice election
      support in workspace positions, and eval scenarios for the two common
      shapes (F-1→H-1B October; arrival-year election).
- [x] **G6 — DONE (2026-07-09).** f843 (Rev. 12-2024, 85 fields) + f8316 (Rev. 1-2006) packs vision-audited clean; file_and_pay 843-claim path (Pub 519 verified LIVE: fixed Ogden UT 84201-0038 address — the old where-you-filed rule is gone), intake employer-refusal follow-up, eval scenario (q), SKILL Recipe B4. *(was:* Exempt F/J students
      with erroneous Social Security/Medicare withholding get an intake note +
      estimate disclosure today. Build: Form 843 + 8316 packs (plain AcroForms),
      a file_and_pay path (separate mailing, NOT with the 1040-NR), and an
      intake follow-up that computes the refund amount from W-2 boxes 4/6.

**Acceptance (each item):** the current disclosure is REPLACED by the working
capability; knowledge cited to primary sources (two-pass verification for
year-varying numbers); calc ops golden-tested; packs vision-audited; an eval
scenario exercises the persona that motivated it.

---

## Phase H — Planning mode, household granularity, no-experience onboarding (Effort: L)

> From the **first real-user session** (2026-08-04), logged in
> [`FIELD_NOTES.md`](FIELD_NOTES.md): an unmarried two-NRA household (F-1 OPT →
> H-1B mid-year, partner on OPT) asking for a **TY2026 budget**. Unlike Phase G,
> these are not disclosed limitations — they are places where the product either
> asks the wrong-shaped question or fails closed. The data model is mostly right;
> the elicitation and the forward-looking direction are missing.

- [ ] **H1 — Visa sub-status + per-period tax attributes (N-1).** `VisaPeriod`
      gains a controlled `sub_status` (`student / opt / stem_opt / cap_gap /
      employment / dependent / other`) and a derived, cited `fica_exempt` per
      period; `residency`'s prefix categorization keeps working unchanged (OPT is
      F-1 for the exempt-individual rules) but FICA and per-segment income
      questions stop being re-inferred from strings at each call site. Intake
      collects the timeline **segment by segment** with a worked
      F-1 → OPT → H-1B example, enforces contiguity, and asks for the H-1B start
      as the **I-797 start date** (not the offer or onboarding date).
- [ ] **H2 — Unmarried partner / multi-taxpayer household (N-2).**
      `household.other_taxpayers[]` (relationship `unmarried_partner` / other,
      own status + optional profile ref). Delivers: explicit "you file
      separately, here are two returns" guidance; a guard against claiming an NRA
      partner as a dependent (the citizen/national/resident requirement); a
      household-level budget roll-up over two profiles; and a "if you marry in
      <year>" branch that hands off to the existing §6013(g)/(h) election path.
- [ ] **H3 — Segmented state-footprint elicitation + onboarding worksheet
      (N-3, N-5).** Replace the single `state_footprint.lived_worked` question
      (`intake.py:661`) with a segment loop (lived / worked / remote / employer
      state per date range) plus a mandatory trigger checklist (mid-year move,
      cross-state remote, >30-day assignment, school ≠ internship state, W-2
      Box 15 mismatch, out-of-US periods, and no-tax-state segments still needing
      dates). Promote [`INTAKE_WORKSHEET.zh-CN.md`](INTAKE_WORKSHEET.zh-CN.md) to
      a canonical English surface emitted by `intake_checklist` (localizations
      alongside), so a zero-experience user has something to fill in.
- [ ] **H4 — Planning / projection mode (N-4).** A forward-looking path distinct
      from `estimate_refund`'s ESTIMATE-for-a-closed-year semantics: label
      **PROJECTION**, annualize from YTD paystub figures, project wages per
      status segment. New calc ops: **employee FICA by status period** (7.65%
      on/off at a status boundary, SS wage-base cap) and **withholding adequacy /
      §6654 safe harbor** (90% current vs 100/110% prior year) — the latter needs
      `PriorFilings` to gain prior-year AGI + total tax
      (`schemas/profile.py:338` currently holds only `filed_years` /
      `late_filing_context`).
- [~] **H5 — first tranche DONE 2026-08-04:** `knowledge/federal/2026.yaml` ships
      as a `provisional: planning_only` pack — rate schedules (Rev. Proc. 2025-32
      §4.01), standard deduction (§4.14), capital-gains brackets (§4.03), SE +
      employee social security ($184,500 wage base, Pub 15 (2026)), and the
      statutory surtaxes. **Two-pass verified** against Form 1040-ES (2026)
      (Cat. No. 11340T): all four rate schedules and the standard-deduction chart
      match line for line. Blocks whose 2026 authority does not exist yet
      (`ptc`, `taxable_social_security`, `student_loan_interest`,
      `education_credits`, `dependent_care`, all M3 logistics) are **declared
      absent** in the marker and enforced by
      `test_eval_i2_current_year_pack_is_marked_planning_only`; the
      "refuse to invent" eval moved to 2027. Remaining: the 2026 Tax Table
      (`tax_table.row_bands` is still a carried-forward structure), and a
      **guard that stops `fill_form`/`verify_form` from backing a filed return
      with a provisional pack** — today only the YAML comments say so
      (confirmed absent 2026-08-07: `grep provisional` in `filler.py` / `verify.py`
      / `server.py` returns nothing, so the marker is read by exactly one eval).
      *(was: **Current-year knowledge packs (prerequisite for H4).*
      `knowledge/federal/2026.yaml` (and the year after, each year) authored under
      the DEV_PLAN §7 freshness protocol — the annual inflation Rev. Proc. plus
      the OBBBA-era amounts — so planning during the year works at all. Today
      `calc {year: 2026}` fails closed and `list_forms {year: 2026}` is empty
      (correct, but it makes mid-year planning impossible). Note the packs land
      **before** the year's forms exist, so the pack must be usable for math with
      no form pack present.*)
- [ ] **H6 — Schedule 1-A + the OBBBA deduction family (N-6, N-8).** 2026 returns
      carry four new deductions (tips / overtime / car-loan interest / senior) on
      Schedule 1-A — which **attaches to Form 1040-NR as well** (line 38 → 1040-NR
      line 13c) — plus §170(p) non-itemizer charity ($1,000/$2,000) and the new
      0.5%-AGI floor on itemized charity. Build: a `sched_1a` knowledge block
      (caps $25,000 / $12,500-$25,000 / $10,000 / $6,000; MAGI thresholds
      $150k-$300k / $100k-$200k / $75k-$150k; and the **asymmetric** rounding —
      Part III reduces $100 per whole $1,000 rounded DOWN, Part IV $200 per $1,000
      rounded UP, Part V a flat 6% of the excess), a calc op, and the pack. Encode
      two traps that swing real money: the tips/overtime/senior deductions are
      **forfeited by a married taxpayer who does not file jointly**, and NRA
      bank-deposit interest is excluded under §871(i)(2)(A) until a §6013(g)
      election makes the payee a resident.
- [ ] **H7 — scenario comparison surface (N-9, N-15).** Planning questions arrive
      as "compare A vs B vs C" (unmarried / married-MFS / married + §6013(g)), and
      the engine has every primitive but no way to run and diff a set. Build a
      `compare_scenarios` surface over the projection path that returns per-scenario
      bottom lines plus the itemized deltas that explain the difference — the
      deltas must sum exactly to the headline number, which is the acceptance
      criterion for this item. It must be **persisted and re-runnable**
      against the workspace profile, not a one-shot call: the motivating session
      revised four facts mid-flight and each revision re-ran every scenario.
- [ ] **H8 — tax-advantaged account knowledge (N-10, N-11, N-12, N-13).** The
      highest-frequency in-year question after "what will I owe" is "where do I put
      money to owe less". Build:
      * a `contribution_limits` knowledge block, cited, that records not just the
        amounts but the **scoping** of each: §402(g) $24,500 per PERSON across all
        employers with traditional + Roth sharing it; §415(c) $72,000 per EMPLOYER
        PLAN; HSA $4,400/$8,750 per COVERAGE TIER (so two unmarried self-only
        HDHPs beat the family limit); §125(i) $3,400 per employee per employer;
        §132(f) $340+$340 monthly; IRA $7,500 per person across traditional + Roth.
      * a **marginal-dollar ranking** op: what one more dollar saves in each
        bucket, knowing that payroll HSA/FSA/commuter dollars also avoid FICA
        while 401(k) dollars do not, and that above the SS wage base the FICA
        saving is 1.45% + 0.9%, not 7.65%.
      * **Roth-vs-pre-tax representation** on the profile (a deferral is a split,
        not a scalar) because the pre-tax share moves AGI and cascades into every
        phase-out.
      * an **eligibility/excess-contribution guard**: the session caught a live
        Roth IRA contribution by a single filer whose MAGI was above the
        $153,000–$168,000 phase-out; 6% excise per year) that flips to compliant
        on a year-end MFJ filing status. A tool holding the profile and the limits
        should raise this without being asked.
      * a **MAGI ladder** output (gross → W-2 box 1 → AGI → each test's MAGI with
        its own threshold), since at least six different phase-out tests fired in
        one session and users cannot see why their MAGI differs from their salary.
      * withholding realism: the flat **22% supplemental-wage rate** (Pub 15) vs a
        32% marginal rate is a predictable April shortfall on any bonus.

**Acceptance:** H1/H2 ship schema + intake changes with regression tests and an
eval scenario for the *unmarried two-NRA household, mid-year status change*
persona; H3 ships the segment loop + the worksheet surface with a no-experience
walkthrough in the skill; H4 ships golden-tested ops and a PROJECTION output
contract that can never be mistaken for a filed number; H5 follows the two-pass
verification rule for every figure; H6 ships golden-tested phase-out math for all
five Schedule 1-A parts including the MFS-forfeiture rules; H7 ships a diff whose
line items sum to the headline delta.

---

## Phased sequencing (recommended order)

1. **Phase 0** — DONE. **Phase E** — DONE. **Phase F** — DONE (2026-07-06).
   Persona-review Tiers 1+2 — DONE (2026-07-07).
2. **Phase A** (1–2 wks) — ship v0.1. Highest leverage: flips the product from
   "from-source only" to installable. Only external dep is a PyPI token; the
   demo GIF and the 20-min acceptance run are the other human steps.
3. **Phase G** (per-item, independent) — the persona-review subsystems above.
   Suggested order: G1 treaty KB → G2 Form 2441 → G3 monthly 8962 → G6 FICA
   843 → G5 dual-status corridor → G4 state calc (open-ended). Each replaces a
   disclosed limitation, so nothing blocks Phase A.
4. **Phase H** (the first real-user session, 2026-08-04) — **do H5→H8→H4→H7
   before H1–H3.** Rationale from [`FIELD_NOTES.md`](FIELD_NOTES.md): that
   session used 4 of the 22 tools and every number that decided the user's
   answer was computed *outside* the engine, over irs.gov figures the agent
   re-researched live. So the binding constraint is **knowledge/data, not engine
   code** — which is the cheap half. Order:
   **H5** current-year pack (first tranche DONE) → **H8** account-limit knowledge
   + MAGI ladder (pure data + one op; every 2026 figure already verified in the
   session) → **H4** projection mode + withholding/safe-harbor → **H7**
   persisted, re-runnable scenario diff → **H6** Schedule 1-A engine → then the
   intake/schema work **H1–H3**, which is the largest code change and the least
   blocking (the profile model already *can* express the periods; it is the
   elicitation that is thin).
5. **Phase C** (months, parallelizable) — coverage breadth: C2 nonresident/
   part-year state forms, C3 hard states (MA fetch, IA/NM classification,
   CT/SC hand-fill, UT sourcing).
6. **Phase D** — D1 DONE; D2 = more tax years for state packs + the community
   pack-contribution pipeline.

Phases A, E, and the start of C are largely independent and can run in parallel.
Phase H is independent of C/D (different files) and can run alongside them.
Within C, resident packs (C1) are the long pole; the now-working `introspect` CLI
is the force multiplier. **C3 hard states are now the only items needing new engine
code** (a downloader fix for fetch-blocked AcroForms + an OCR-positioned overlay
filler for print-only forms) — every other remaining item runs on the existing
pipeline (W-7, once feared to need new field types, turned out to be a plain AcroForm).
