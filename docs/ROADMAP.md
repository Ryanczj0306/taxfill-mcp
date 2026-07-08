# TaxFill — Completion Roadmap (remaining work)

The design spec is [`docs/DEV_PLAN.md`](DEV_PLAN.md). This is the forward-looking
plan for what is **not yet done**, as of **2026-07-07**.

> **Status note (2026-07-07 update).** Since the 2026-06-28 truth-up: Phase F
> (estimator/domain completeness, F1–F10) shipped; a 5-persona real-filer review
> (MFJ family / NRA student / RA + dual-status / NRA-spouse §6013(g)(h) couple /
> naive UX; 46 adversarially-verified findings) drove two fix waves — Tier 1
> (25 wrong-law/UX point fixes: NRA standard deduction, verify's independent
> recompute over MCP, W-7/8843 logistics, intake dead-ends) and Tier 2 (the four
> broken paths: §6013 election end-to-end, Schedule 8812 + CTC/EITC calc ops,
> Schedule A (1040-NR) + Schedule NEC, treaty_exempt_income). What remains is
> (1) **launch execution** (Phase A — unchanged, user-gated), (2) coverage
> breadth (Phases C/D), and (3) the **Phase G subsystems** below (the persona
> review's Tier 3 — every gap is DISCLOSED in product output until built).

## Where we are (verified)

Done and on `main` (**1,827 tests, all green** — offline 1,741 + live-.gov 86, exit 0):

- **M0 scaffold · M1 engine · M2 federal packs · M3 intake + knowledge · M4 MCP
  server (22 tools, stdio, image content) · M5 state support · M6 code/docs.**
- **MCP server — 22 tools, CI-gated** (`.github/workflows/ci.yml` asserts exactly
  22): list_forms, get_form_map, fetch_blank, fill_form, verify_form,
  verify_filing, render_form (vision Image), calc, residency, intake_checklist,
  list_document_kinds, extract_document, workspace_save, workspace_load,
  workspace_record_position, workspace_reconcile, state_scope, estimate_refund,
  get_sources, filing_summary, file_and_pay, hand_fill_worksheet (print-only
  states). The `calc` tool carries 13 deterministic ops (tax, standard_deduction, se_tax, additional_medicare_tax, niit, tax_with_preferential_rates, taxable_social_security, excess_ss, student_loan_interest_deduction, education_credits, ptc_annual, child_tax_credit, eitc).
- **Phase B — single-user completeness: DONE.** `extract_document` (W-2,
  1099-NEC/MISC/INT/DIV/G/B/R, SSA-1099, 1095-A, 1098-T/E, 1042-S, with per-field
  provenance — K-1 is the one common document still unsupported) and the resumable
  workspace (`workspace_*` tools + `taxfill purge` CLI, generated RECONCILIATION.md
  / CHECKLIST.md) are implemented, merged, and tested.
- **Federal form packs — priority set DONE.** 35 packs across 2019–2024. M2 base
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
8959, 8960, 8962. state — **35 states** (39 packs): CA (540 + 540NR +
Schedule CA 540/540NR), NY (IT-201 + IT-203), IL, PA, OH, GA, NC, MI, NJ, VA, AZ,
IN, MO, MD, AL, CO, MN, WI, KY (740), OR (OR-40), LA (IT-540), KS (K-40),
AR (AR1000F), ID (40), NE (1040N), OK (511), **ME (1040ME), MS (80-105),
RI (RI-1040), MT (Form 2), ND (ND-1), DE (PIT-RES), VT (IN-111), DC (D-40),
**WV (IT-140)**. **80 form packs total** (41 federal + 39 state).

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
      and a full run (**exit 0, no collection errors**): the suite is **1,401 tests,
      all green** (1,288 at audit + 3 eval scenarios k/l/m + 8 each for Forms 4868,
      1040-ES, 1040-X, and W-7). The earlier figures
      were stale/under-counted (old ROADMAP *1222*, README *~1076*, audit-sandbox
      *~903* — the sandbox couldn't run collection). README + this file now quote **1,401**.
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

### C1 — Remaining resident state form packs (7 jurisdictions) — **easy rollout COMPLETE**

**35 of 42** income-tax jurisdictions are now fillable — **every easy fillable-AcroForm
state has shipped** (six C1 tranches, 17 states, via the introspect→vision-map→
adversarial-audit→golden pipeline; WV IT-140 was the last). The **7 that remain are ALL
C3 hard states** — none can be done on the AcroForm pipeline; each needs the engine work
in C3 below:

`CT · HI · IA · MA · NM · SC · UT`

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
- [ ] **UT (TC-40) — deferred / sourcing blocker:** Utah serves a year-agnostic
      `tc-40.pdf`; the `…/forms/2023/tc-40.pdf` path actually returns the **2025**
      revision (confirmed by rendering — line 17 shows the 2025 phase-out thresholds,
      line 2c "born in 2025"). A true 2023 TC-40 blank isn't available at a stable URL,
      so UT was NOT shipped as a 2023 pack (would mis-label the form). Revisit when a
      2023 artifact is locatable, or fold UT into a future 2024/2025 state tranche (D2).
- [ ] Per state: introspect → vision-map (≈6 agents) → assemble `pack.yaml`
      (relations from printed labels; `cross_form` line = federal AGI) → audit
      every page → re-audit → golden round-trip.

### C2 — Nonresident / part-year forms

Only **CA** (540NR + Schedule CA 540NR) and **NY** (IT-203) have them today.

- [ ] Add the separate nonresident/part-year return for each state that has one
      (IL Schedule NR, OH IT NRC, PA part-year, etc.) + the adjustment schedule.

### C3 — Hard states (need engine work, not just packs)

**Investigated 2026-07-01.** Each hard state needs a heavyweight NEW subsystem or
dependency — an architecture call for the maintainer, not a quick fix:

- [ ] **MA Form 1** — the mass.gov PDF *is* a fillable AcroForm, but the download is
      **bot-blocked at the edge (Akamai)**: `fetch_blank` gets **HTTP 403** and even
      `curl` with a full desktop-browser header set (UA + Accept + Accept-Language +
      Accept-Encoding) is refused with a 3 KB challenge page. This is TLS/JS-challenge
      fingerprinting, NOT a missing-header problem — a header tweak to `fetch.py` will
      not fix it. Options: (a) a **headless-browser fetch path** (Playwright/Chromium,
      ~300 MB — heavy for a stdlib MCP); (b) a **manual cache-seed** flow (a human opens
      the URL in a browser once and drops the PDF into `.cache/blanks/`, then the normal
      pipeline runs); (c) an official non-challenged mirror if one exists. Once the blank
      is in hand, MA is an ordinary AcroForm pack.
- [ ] **IA / NM** — classify first (both candidate URLs 404'd during this pass — need
      the current official URLs). NOTE: the engine's "XFA handling" only covers
      **XFA-*derived* AcroForms** — forms that ship real AcroForm widgets with
      hierarchical `topmostSubform[0].PageN[0]…` names (federal 1040, and RI-1040 which
      shipped fine). It does NOT render **pure/dynamic XFA** (XFA-only, no AcroForm
      widget layer). If IA/NM are XFA-derived AcroForms they go through the normal
      pipeline; if pure-XFA or flat print-only they need (c) below.
- [~] **CT / SC / HI** — print-only (no AcroForm, no XFA — HI N-11 2023 confirmed flat:
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

- [ ] More tax years for the state packs (federal already spans 2019–2024).
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

- [ ] **G1 — Per-country treaty knowledge base (L–XL; highest value for the
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
- [ ] **G2 — Form 2441 (child & dependent care credit) (M–L).** The persona
      review showed its absence can flip an MFJ-vs-MFS recommendation. Build:
      knowledge params (35%→20% AGI slide, $3,000/$6,000 caps, earned-income
      limits), a calc op, a 2441 form pack (AcroForm, standard pipeline),
      estimator field (care expenses + care-provider count), intake question.
- [ ] **G3 — Form 8962 monthly method (M).** `ptc_annual` covers full-year
      coverage; part-year/changing coverage (the common 1095-A case) needs the
      lines 12–23 monthly grid: a `ptc_monthly` calc op taking 12 rows of
      premium/SLCSP/APTC (the 1095-A DocSpec already extracts them), plus
      estimator wiring. The f8962 pack already maps the monthly grid fields.
- [ ] **G4 — State tax calc ops (L–XL, per state).** State returns fill/verify
      today but the tax LINES are model arithmetic — no state calc op exists and
      rates live only in pack comments. Build per adopted state: a knowledge
      `tax` block (rates/brackets/exemptions, cited), a `state_tax` calc op
      keyed by jurisdiction, and relation coverage. Start with the flat-rate
      states (IL 4.95%, PA 3.07%, ...) where one op covers the whole return,
      then CA/NY brackets.
- [ ] **G5 — Dual-status return corridor (L).** residency correctly flags
      `dual_status_candidate` and the estimator now restricts statuses and
      discloses, but there is no prepared path for the actual split-year
      filing (1040 + 1040-NR statement, first-year choice election text,
      residency start-date math). Build: a dual-status guide surface (roadmap
      steps + statement checklist in file_and_pay), first-year-choice election
      support in workspace positions, and eval scenarios for the two common
      shapes (F-1→H-1B October; arrival-year election).
- [ ] **G6 — FICA-refund flow (Form 843 + 8316) (M).** Exempt F/J students
      with erroneous Social Security/Medicare withholding get an intake note +
      estimate disclosure today. Build: Form 843 + 8316 packs (plain AcroForms),
      a file_and_pay path (separate mailing, NOT with the 1040-NR), and an
      intake follow-up that computes the refund amount from W-2 boxes 4/6.

**Acceptance (each item):** the current disclosure is REPLACED by the working
capability; knowledge cited to primary sources (two-pass verification for
year-varying numbers); calc ops golden-tested; packs vision-audited; an eval
scenario exercises the persona that motivated it.

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
4. **Phase C** (months, parallelizable) — coverage breadth: C2 nonresident/
   part-year state forms, C3 hard states (MA fetch, IA/NM classification,
   CT/SC hand-fill, UT sourcing).
5. **Phase D** — D1 DONE; D2 = more tax years for state packs + the community
   pack-contribution pipeline.

Phases A, E, and the start of C are largely independent and can run in parallel.
Within C, resident packs (C1) are the long pole; the now-working `introspect` CLI
is the force multiplier. **C3 hard states are now the only items needing new engine
code** (a downloader fix for fetch-blocked AcroForms + an OCR-positioned overlay
filler for print-only forms) — every other remaining item runs on the existing
pipeline (W-7, once feared to need new field types, turned out to be a plain AcroForm).
