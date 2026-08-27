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

Done and on `main` (**4,404 tests, all green** — offline 4,056 + live-.gov 348, exit 0;
re-verified 2026-08-21 via `pytest -m "not network"` AND `pytest -m network`, exit 0
both — the network layer skips 2 (states/ms/2023/f80105, whose blank is uncached and
whose host fails certificate verification here)):

- **M0 scaffold · M1 engine · M2 federal packs · M3 intake + knowledge · M4 MCP
  server (23 tools, stdio, image content) · M5 state support · M6 code/docs.**
- **MCP server — 23 tools, CI-gated** (`.github/workflows/ci.yml` asserts exactly
  23): list_forms, get_form_map, fetch_blank, fill_form, verify_form,
  verify_filing, render_form (vision Image), calc, residency, intake_checklist,
  list_document_kinds, extract_document, workspace_save, workspace_load,
  workspace_record_position, workspace_reconcile, state_scope, estimate_refund,
  compare_scenarios,
  get_sources, filing_summary, file_and_pay, hand_fill_worksheet (print-only
  states). The `calc` tool carries 25 deterministic ops (tax, tax_with_preferential_rates, standard_deduction, se_tax, additional_medicare_tax, niit, taxable_social_security, excess_ss, student_loan_interest_deduction, education_credits, ptc_annual, ptc_monthly, child_tax_credit, eitc, dependent_care_credit, treaty_benefit, schedule_1a_deductions, employee_fica, estimated_tax_safe_harbor, annualize_ytd, contribution_limits, ira_contribution_eligibility, marginal_dollar_savings, magi_ladder, state_tax).
- **Phase B — single-user completeness: DONE.** `extract_document` (W-2,
  1099-NEC/MISC/INT/DIV/G/B/R, SSA-1099, 1095-A, 1098-T/E, 1042-S, and — since
  2026-08-10 — **Schedule K-1 (Form 1065)**, with per-field provenance) and the resumable
  workspace (`workspace_*` tools + `taxfill purge` CLI, generated RECONCILIATION.md
  / CHECKLIST.md) are implemented, merged, and tested.
- **Federal form packs — priority set DONE.** **102 packs across 2019–2025**
  (2019:1, 2020:1, 2021:1, 2022:5, 2023:31, 2024:31, 2025:32 — f1040nr +
  Schedule OI joined 2024 on 2026-08-10, and the 2026-08 batch backfilled the
  rest of the 2023 set into 2024/2025: identical-topology ports off the 2023
  packs, digests pinned to the year's blanks, vision-audited page by page). M2 base
  set + Schedule SE/D/E + Form 8863 + Form 2555 all ship (2023), audited, golden;
  + **all four Phase-D new form types** — **Form 4868** (extension), **Form 1040-ES**
  (estimated-tax vouchers), **Form 1040-X** (amended return, Rev. 2-2024), and
  **Form W-7** (ITIN application, Rev. 12-2024) — all audited.
- **Repo-wide pack gates — every rule now covers the packs it claims to.**
  `test_pack_invariants.py` (2026-08-21) sweeps all **150** packs, federal and
  state, for `cross_form` target resolution, the checkbox-`group` rules,
  identity page mirrors and year tokens in line keys;
  `test_readonly_widget_mapping.py` does the same for ReadOnly bindings (**1,140**
  across 10 packs, pinned per pack by count). The first two of those had been
  federal-only while CONVENTIONS.md called them binding — see Phase E for what
  shipped through the gap, and for the two live defects the widening found.
- **State form packs — 61 across three years** (TY2023 42 / TY2024 14 / TY2025 5).
  The 2026-08-21 tranche added 10 (AR 2024 + 2025, NC/NJ/OH/RI/UT/VA 2024,
  OR/PA 2025) and closed **every PORTABLE row** in D2's measured triage for both
  TY2024 and TY2025; the 2026-08-25 tranche added 4 (IL-1040, ND-1, OR-40,
  MO-1040 × 2024) and closed **every NEAR-PORT row** too — each with the moved
  fields re-derived from the printed face and an adversarial second-agent
  verify. Only the re-maps and URL-dead rows stay open.
- **State credits — DONE for all 42 jurisdictions** (41 income-tax states + DC):
  every `knowledge/states/<st>/2023.yaml` carries a cited `credits` block (~174
  entries total); `state_scope` surfaces them as `benefits_candidates`.
- **Drift CI — DONE** (restored 2026-08-10 after a spell as workflow_dispatch-only,
  i.e. never running). `freshness.yml` runs `scripts/check_drift.py` (form-blank
  SHA256 + source URLs + mailing addresses) AND the live-.gov golden round-trips
  weekly, in its own workflow so monitoring failures never repaint the code badge.
- **Pack-authoring CLI — DONE.** `taxfill introspect <blank.pdf>` emits a pack
  skeleton (`packbuild.py` + `cli.py`), tested.

**Form packs that can be FILLED today (introspect→vision-map→adversarial-audit→
golden):** federal — f1040, f1040-NR, f8843, Schedule 1/2/3/A/B/C/OI/SE/D/E/8812,
Schedule A (1040-NR), Schedule NEC, Forms 8863, 2555, 4868, 1040-ES, 1040-X, W-7,
8959, 8960, 8962, 2441, 843 (Rev. 12-2024), 8316. state — **all 42 income-tax
jurisdictions**: **38 via fillable AcroForm (61 packs across TY2023–TY2025)** — CA (540 + 540NR +
Schedule CA 540/540NR), NY (IT-201 + IT-203), IL, PA, OH, GA, NC, MI, NJ, VA, AZ,
IN, MO, MD, AL, CO, MN, WI, KY (740), OR (OR-40), LA (IT-540), KS (K-40),
AR (AR1000F), ID (40), NE (1040N), OK (511), ME (1040ME), MS (80-105),
RI (RI-1040), MT (Form 2), ND (ND-1), DE (PIT-RES), VT (IN-111), DC (D-40),
WV (IT-140), IA (IA 1040), MA (Form 1), UT (TC-40) — plus **4 via print/hand-fill
manifests**: CT (CT-1040), HI (N-11), NM (PIT-1), SC (SC1040).
**167 form packs total** — 163 `pack.yaml` (102 federal + 61 state) + 4
`handfill.yaml`. The state 61 breaks down **TY2023 42 / TY2024 14 / TY2025 5**.
> ⚠️ State form-pack year coverage is now **partial, no longer TY2023-only**:
> **13 of the 42 jurisdictions fill a post-2023 year** — AR (2024+2025),
> NY (2024+2025), PA (2024+2025), OR (2024+2025), and
> IL/MO/NC/ND/NJ/OH/RI/UT/VA (2024) — after the 2026-08-21 ten-pack and
> 2026-08-25 four-pack tranches. For the remaining **29**, state *knowledge*
> spans 2023–2025 while the only fillable pack is TY2023, so `calc.state_tax`
> still computes years those packs cannot fill. That asymmetry is now 29
> jurisdictions wide rather than 40 (see D2).

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

- [~] More tax years for the state packs — **KNOWLEDGE DONE (126/126), FORM PACKS 19/~92
      — every PORTABLE and NEAR-PORT row is now closed; what remains is re-maps
      and URL-discovery.**
      State *knowledge* now spans three COMPLETE years: **2023 42/42, 2024 42/42,
      2025 42/42** (RI 2025 closed the cohort 2026-08-07), every pack carrying the
      same 18 blocks incl. a typed `tax` block, auto-enrolled into the suite by the
      glob at `test_state_knowledge.py:26`. State *form* packs are **no longer
      TY2023-only**: 61 packs across TY2023 (42) / TY2024 (14) / TY2025 (5), so
      **13 of the 42 jurisdictions** can fill a post-2023 year — AR, NY, PA and OR
      for both 2024 and 2025; IL, MO, NC, ND, NJ, OH, RI, UT, VA for 2024. For the
      other **29**, a 2024/2025 return still computes but cannot be filled.
      Federal spans
      2019–2025 for forms and 2019–2026 for knowledge (the TY2025 OBBBA set, 13 packs
      incl. the new Schedule 1-A, + knowledge/federal/2025.yaml shipped 2026-07-25;
      the provisional 2026 planning pack shipped 2026-08-04).
      **Remaining:** (a) the rest of the 2024→2025 **state form pack** tranche — 46
      packs/year. The pipeline half is ready (2026-08-10):
      `scripts/scaffold_state_year.py` + `docs/CONTRIBUTING-PACKS.md`.
      ⚠️ **Correction (2026-08-11):** the "39 of 46 URLs derivable" figure was
      string derivation only and NEVER PROBED — it over-reported by ~2×. The
      script now has `--triage`, which downloads each candidate and diffs the
      blank's AcroForm against the base pack's field map. Measured, and with the
      shipped/open state of each class as of **2026-08-25**:
      * **TY2024** (42 AcroForm packs): **10 PORTABLE — ALL 10 SHIPPED** (NY IT-201,
        NY IT-203 and PA on 2026-08-10; AR, NC, NJ, OH, RI, UT, VA in the
        2026-08-21 tranche) and **4 NEAR-PORT — ALL 4 SHIPPED 2026-08-25**
        (IL-1040 with the EIC/CTC lines re-bound to the renamed Sch. IL-E/EITC
        fields, ND-1 with the header name boxes split four ways AND printed
        lines 10/11 swapping meanings under unmoved widget names — the exact
        trap the vision audit exists for, OR-40 with the three kicker widgets
        deleted on a non-kicker year, MO-1040 with the MO-A Part 3/5 ladder
        re-authored: 25 names dead, 36 new, ReadOnly re-measured 262 → 260 and
        every delta field adjudicated per P-007). Each near-port also passed an
        adversarial second-agent verify. Still OPEN for TY2024: 9 RE-MAP +
        12 URL-DEAD + 7 no-year-token.
      * **TY2025**: **5 PORTABLE — ALL 5 SHIPPED** (NY IT-201, NY IT-203 on
        2026-08-10; AR, OR, PA in the 2026-08-21 tranche). Still OPEN for TY2025:
        0 near-port + 11 RE-MAP + **19 URL-DEAD** + 7 no-year-token.
      So the ~15 cheap ports AND the 4 near-ports are DONE — the tranche's
      remaining shape is: **~20 vision re-maps** (every CA pack is a
      full re-map — CA renames its fields yearly) and **~26 URL-discovery tasks**
      before those can even be assessed. Note OR is the live proof that a class is
      per-year, not per-state: OR-40 was NEAR-PORT for 2024 (the DOR deleted the
      three kicker widgets rather than renumbering) and PORTABLE for 2025 (which
      re-inserted the kicker at line 32); both years now ship.
      Identical field NAMES still do not prove the state kept its line NUMBERING,
      so every port keeps the per-page vision audit — and this tranche is why that
      rule stands: the OH 2024 port found Ohio had newly set the AcroForm ReadOnly
      bit on both joint-filing-credit cells (`SchedC_L12`, `SchedC_L12_JFC`,
      /Ff 0 → 1), which is pinned in `STATE_COMPUTED_READONLY` rather than
      unmapped, because unmapping them would file a BLANK credit (P-007 class 4).
      Federal: **f1040nr + Schedule OI now ship for 2024** (identical-topology
      ports, vision-audited), closing the "f1040nr has no 2024 pack" gap.
      **Done 2026-08-10:** (b) `assemble_state_knowledge.py` now takes `--year` +
      `--input` (the 2023 /tmp input itself is gone for good — future cohorts commit
      or reference their fetch input); (c) the `effective_law_changes` schema
      (which had shipped in `knowledge.py` all along) gained `modeled`/`affects`,
      `state_scope` surfaces every UNMODELED change as a warning with its citation,
      and **RI 2025's Schedule HR1 OBBBA add-backs are the first data instance** —
      moved out of pack prose (remaining: instances for the other 133 packs as their
      years' law moves; the schema and surface now exist); (d) the per-state source
      registry: `knowledge/sources_states.yaml` (GENERATED from each state's newest
      pack's own verified citations by `scripts/assemble_state_sources.py`, byte-
      equality-tested, hand overrides in `sources.yaml` win) — all **42** income-tax
      jurisdictions now resolve `get_sources(topic, year, 'states/xx')` with
      state-shaped retrieval hints, unblocking state TY2026 planning packs.
- [x] Community pack-contribution pipeline — **DONE 2026-08-10**:
      [`docs/CONTRIBUTING-PACKS.md`](CONTRIBUTING-PACKS.md) documents the full
      author→audit→PR flow (fetch+digest, `taxfill introspect`, vision field-map,
      adversarial audit, golden test, gates-on-the-exact-tree), and
      `scripts/scaffold_state_year.py` turns a year tranche into a managed
      work-list — `--triage` downloads each derived candidate and classifies the
      port cost against the base pack's field map (PORTABLE / NEAR-PORT /
      RE-MAP / URL-DEAD / no-year-token), so the tranche starts from measured
      cost instead of an estimate (see D2 for the TY2024/TY2025 numbers). The
      2024/2025 state tranche is **partly delivered** — all 15 PORTABLE rows
      (5 on 2026-08-10, 10 on 2026-08-21) and all 4 NEAR-PORT rows (2026-08-25)
      have shipped, each through the full quality gate; the re-map / URL-dead
      remainder is still open.

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
- [x] Wire the true test count into a CI badge / README line — DONE (2026-07-01):
      live CI-status badge + a tests badge kept in sync with the verified count.
      **Re-done properly 2026-08-07:** the 2026-07-01 version was a *human* promise
      to keep the number in sync, and it broke four times — most visibly when the
      badge's alt text (2,178) came to disagree with its own shields.io URL (2,297)
      while the real figure was 2,824. The suites are glob-parametrized over the
      knowledge/formpack YAMLs, so the count moves whenever a pack lands and no
      amount of discipline holds it. Now derived, never typed:
      `scripts/sync_test_count.py` computes the counts from
      `pytest --collect-only` and either rewrites all four quoted sites
      (`--write`) or fails with an exact instruction (`--check`), and the
      **`test-count` CI job** runs `--check` on every push.
- [x] **Widen the two federal-only pack gates to every pack — DONE (2026-08-21).**
      `cross_form` target resolution and the checkbox-`group` invariant were both
      parametrized over `formpacks/federal/*/*/pack.yaml` while
      `formpacks/CONVENTIONS.md` called them binding on every pack, so **no state
      pack had ever been checked by either one** — 57 packs, 43 of the repo's 190
      `cross_form` rules, and 120 shared-field option sets, all unexamined. That
      gap is how three dangling `f1040.11` refs (or/2025, ny/2025 ×2) and two
      packs' worth of missing `group` ids (nc/*/d400, nj/2024) shipped. Both now
      sweep all 150 packs from the new `packages/core/tests/test_pack_invariants.py`
      (the federal-only copies are deleted, not duplicated), which also fixed a
      second blind spot: the yes/no half only understood the DOTTED option
      spelling, so it could not see `::` (22 state packs) or `_` (ny it203 ×3)
      pairs even with the glob widened. Two more repo-wide invariants landed in the
      same file because nothing anywhere asserted them — **identity page mirrors**
      (a `page<N>_*` banner mirror must have a source line, bind a DIFFERENT
      widget, and match its source's `type`/`comb`/`format`; ri1040 shipped 0 of
      its 12 for months) and **year tokens in line keys** (`tax_year - year` pinned
      per key family, which is what catches a stale port). Every table is
      self-clearing and every exemption is backed by execution rather than prose:
      the 21 shared-field debt rows are only safe because `fill_form` refuses a
      double answer, and that is proved per pack for all 120 sets.
- [x] **Two live defects the widened gates found — BOTH FIXED 2026-08-24** (they
      had been recorded as self-clearing rows, which is why the fix could not go
      quiet: each table emptied in the same change or the gate failed loudly):
      * `federal/2024/sched_oi` keyed Schedule OI item H as `h.2021 / h.2022 /
        h.2023` while the sha-pinned 2024 blank prints "**2022** …, **2023** …,
        and **2024**" — a 2023 pack ported without rolling the year labels, and
        the widgets did not move (`f1_23/f1_24/f1_25`). Silent in both
        directions: every day-count landed in the box printed for a *different*
        year, and a caller who correctly asked for `h.2024` got "unknown line
        key". Days of presence drive the substantial-presence test, so a
        one-year shift can flip resident/nonresident status. Same defect class
        as the `f1040.11` refs this tranche fixed — a key remembered from a
        prior year's face — but in the FEDERAL lane, which is why every
        state-side sweep missed it. **Fixed:** renamed to `h.2022/h.2023/h.2024`
        against the same widgets, re-verified on the filled render (each
        sentinel sits in the box printed with its own year);
        `KNOWN_STALE_PRINTED_YEAR_LABELS` is now empty.
      * `states/wv/2023/it140` mapped Schedule HEPTC-1's "Are you required to
        file a federal return?" as `heptc.required_federal_return.yes`/`.no` on
        TWO independent `/Btn` fields (`homesteadY_checkbox`,
        `homesteadN_checkbox`) with no `group` id, so nothing made them
        exclusive: `fill_form` wrote **both** `/Yes` with zero warnings.
        Reproduced against the pinned blank. The same pack got the neighbouring
        line-8 question right (one `/Btn` + `group: heptc.8`), so it was an
        internal inconsistency, not a house style — and the ONLY exploitable
        instance repo-wide. **Fixed:** both lines now carry
        `group: heptc.required_federal_return` (`required` deliberately left
        off — HEPTC-1 is a schedule most IT-140 filers do not attach);
        `KNOWN_UNGROUPED_YESNO_PAIRS` is now empty.
- [x] **Pack-owner follow-ups the tranche surfaced — ALL TAKEN 2026-08-24**
      (each was a pack edit, tracked as a self-clearing row so it could not go
      quiet; every corresponding gate row is now retired and the gates are
      green): `states/nj/2023/nj1040` got `group` ids on all 38 option lines of
      its 13 shared radio fields (retiring its
      `SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID` row) and the year-free line-69
      rename; `states/ut/2023/tc40` took the same rename plus the six declarable
      `max(…, 0)` floors its 2024 sibling carries (each re-adjudicated against
      the 2023 blank's own printed text); `states/ny/{2023,2024,2025}/it203` all
      renamed line 69 to `69_amount_applied_to_next_year_estimate` (the 2024/2025
      headers had documented the stale year as intentional, which the year-token
      convention rejects); `states/id/2023/form40` renamed `56.apply_to_2024` to
      `56.apply_to_next_year` — with those renames no shipped pack carries a
      "next-year" year token, so the four `(-1,)` `YEAR_BEARING_KEY_FAMILIES`
      rows are retired too; `sched_d` 2023/2024/2025 declared `group` ids on all
      four separate-widget Yes/No pairs (header QOF `required: true`; lines
      17/20/22 not required — the printed page-2 flow legitimately skips them),
      clearing its 12 `KNOWN_UNGROUPED_YESNO_PAIRS` rows; and the OH IT 1040
      page-13 OUPC got its cell-by-cell printed-face adjudication — the SEVEN
      visible filer-data cells (payer name/address block, first-3-of-last-name,
      "Taxpayer's SSN") are now MAPPED as `upc_*` in both years (they are
      genuine class-4 "ships blank": their `/AA /C` viewer scripts copy the
      page-1 return fields, which taxfill never runs), while the 37
      scan-line/check-digit cells, 12 hidden carriers and 4 DOR-owned cells stay
      deliberately unmapped (a wrong check digit corrupts DOR intake scanning —
      worse than an empty strip the DOR can key from the printed face); the
      `STATE_COMPUTED_READONLY` pins moved 5→12 (2023) and 6→13 (2024) with the
      per-cell record in the 2023 pack's OUPC PAGE-13 ADJUDICATION header.

- [ ] **A THIRD checkbox-topology blind spot, MEASURED 2026-08-26 (Phase I2).**
      The two P-008 gates between them still cannot see one shape.
      `test_every_yes_no_pair_shares_one_group_id` keys off the LINE SHAPE
      `<stem>.yes` + `<stem>.no`, and `test_pack_radio_options_share_one_group_and_distinct_states`
      only fires when two checkbox lines SHARE one AcroForm field. A set of
      options on SEPARATE single-widget `/Btn` fields whose tokens are *not*
      yes/no — Form 8889 line 1's `1.self_only` / `1.family`, for instance — is
      invisible to both, so its `group` id is house discipline rather than a gate
      result, and nothing would catch a pack that omitted it. Swept over all 160
      packs: **285 such option sets across 81 packs, of which 193 carry no shared
      `group` id.** That is why this is its own tranche and not a one-line widening
      — most of the 193 are legitimately NON-exclusive and must stay ungrouped
      (`age_blindness` you/spouse, `presidential_campaign` you/spouse,
      `sched_e` 28.a/28.b column sets, f1040's `standard_deduction` flags), so the
      rule needs the same per-entry printed-face adjudication table the P-007
      ReadOnly sweep needed. **Acceptance:** a repo-wide gate plus an adjudication
      table in which every ungrouped set is justified from its own printed row.
- [ ] **`maxlen` on the 11-wide plain SSN widget is pinned two different ways
      (found 2026-08-26).** `sched_b` / `sched_c` / `sched_8812` / `f2555` / `f8889`
      pin `maxlen: 11` (the widget's own `/MaxLen`); `f8606` / `f8960` pin `9`.
      `formpacks/CONVENTIONS.md` is explicit that maxlen tracks each widget's OWN
      `/MaxLen`, which makes 11 correct and 9 a harmless but untrue narrowing —
      harmless only because a 9-digit SSN never reaches the limit. Settle it one
      way repo-wide and say so in CONVENTIONS, so the next author does not have to
      pick.

**Acceptance:** all 13 eval scenarios run green (**met**); one authoritative test
count (**met**); every binding rule in `formpacks/CONVENTIONS.md` enforced by a
module whose discovery glob matches the rule's claimed scope (**met** — the table
at the top of CONVENTIONS.md now states which module covers which packs, so the
next reader can check the claim instead of trusting it).

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

- [x] **H1 — Visa sub-status + per-period tax attributes (N-1) — DONE 2026-08-10.**
      `VisaPeriod.sub_status` (`student / opt / stem_opt / cap_gap / employment /
      dependent / other`) + the DERIVED (never stored) `fica_exempt_hint()`
      citing IRC 3121(b)(19)/Pub 519 per period — exempt for every F-1 posture
      including OPT/STEM OPT/cap-gap, FICA from the boundary for employment
      statuses, agnostic-with-instructions otherwise; `residency`'s prefix rules
      unchanged; `_has_f1_period` prefers the vocabulary. Intake asks the
      timeline **segment by segment** with the worked F-1 → OPT → H-1B example,
      notes contiguity gaps and open-ended predecessors, and pins the H-1B start
      to the **I-797 start date**.
- [x] **H2 — Unmarried partner / multi-taxpayer household (N-2) — DONE
      2026-08-10.** `household.other_taxpayers[]` (`OtherTaxpayer`: relationship,
      own `us_person`, note) + the `no_other_taxpayers` sentinel (an empty list
      means "not asked", never "none"). Asked only for unmarried filers; delivers
      the three push-backs as intake NOTES: file SEPARATELY (two returns, no
      MFJ); an NRA partner is NOT claimable as a dependent (§152(b)(3)); the
      marry-in-year branch is PRICED via compare_scenarios
      (`us_resident_election: true`) instead of guessed. *(The household-level
      budget ROLL-UP shipped 2026-08-10: `FilingManifestItem.taxpayer` labels
      each return's owner and `filing_summary` emits `household_rollup` —
      per-person subtotals + the household net, framed as one budget across TWO
      taxpayers whose refunds/balances never offset each other at the IRS.)*
- [x] **H3 — Segmented state-footprint elicitation + onboarding worksheet
      (N-3, N-5) — DONE 2026-08-10.** The `state_footprint.lived_worked`
      question is segment-shaped (one row per date range: lived / worked /
      remote / employer state) with the mandatory 7-trigger checklist (mid-year
      move, cross-state remote, >30-day assignment, school ≠ internship state,
      W-2 Box 15 mismatch, out-of-US periods, no-tax-state segments still dated).
      `WorkPeriod.employer_state` + a follow-up question that chases it on every
      remote segment, and `state_scope` raises a convenience-of-the-employer
      warning (NEVER an asserted must_file; silent when the employer sits in a
      no-wage-tax state). *(Upgraded 2026-08-10: NY/PA carry verbatim-cited
      `convenience_rule` blocks for all three shipped years — TSB-M-06(5)I's
      bona-fide-employer-office factor test; 61 Pa. Code § 109.8 — and DE/NE for
      2025 (the 2025 PIT-SCW home-office sentence; NE's LB 1023-AMENDED rule,
      deliberately year-aware because the pre-2025 rule reached further). An
      employer state whose pack carries the block gets the state's actual cited
      rule; anywhere else stays the generic verify-at-DOR fallback.)* The worksheet is canonical ENGLISH in
      [`INTAKE_WORKSHEET.md`](INTAKE_WORKSHEET.md), shipped inside the wheel as
      `taxfill_core.worksheet` (zh-CN alongside, both sync-tested byte-for-byte)
      and emitted by `intake_checklist` on the start state. Also landed with the
      tranche: `retirement_contributions` (the N-11 Roth/pre-tax deferral split,
      asked for planning years only — closed years read W-2 box 12 — with the
      6%-excise pointer note on a recorded Roth IRA amount) and the N-14
      push-backs (the §6013 ELECTION-not-the-marriage note; Schedule 1-A Part
      III's premium-half / below-AGI-line work line). Eval r covers the full
      persona (unmarried two-NRA household, mid-year status change).
- [x] **H4 — Planning / projection mode — DONE 2026-08-09** (N-4, N-7b, N-8,
      N-12; ops 19-21). Shipped:
      * **The PROJECTION output contract**: `RefundEstimate.label` is now
        `PROJECTION` (never `ESTIMATE`) whenever the year's pack is
        provisional — with the headline prefix, the leading assumption, the
        `provisional` marker and the `missing_blocks` data that landed with
        the guard/spine work. `ESTIMATE` = partial data for a CLOSED year,
        converging to the filed number; `PROJECTION` can never converge —
        fill/verify refuse the year. Eval i4 asserts the contract both ways.
      * **`employee_fica`** — employee-side FICA across STATUS segments (the
        F-1-OPT→H-1B year): SS 6.2% across one annual wage-base pool, Medicare
        1.45% with no base, the 0.9% Additional Medicare withholding over
        $200,000 attributed to the crossing segment. The work quotes N-7b —
        the F/J exemption is STATUS-based, not marital; a §6013(g) election
        does NOT start FICA on the OPT spouse's wages — and the per-employer
        nuances (excess-SS recovery, Form 8959 reconciliation).
      * **`estimated_tax_safe_harbor`** — IRC 6654(d): min(90% current,
        100/110% prior), the 110% tier keyed on PRIOR-year AGI but the
        CURRENT year's status for the $75,000 MFS variant, the $1,000
        de-minimis, the 12-month-prior-return caveat, quarterly installments,
        and the N-12 trap quoted (bonuses withheld at the FLAT 22% —
        `supplemental_withholding` block — under-withhold for every
        higher-bracket filer). `PriorFilings` gained `prior_year_agi` /
        `prior_year_total_tax` (backward-compatible), and intake asks for
        them once a filed prior year exists.
      * **`annualize_ytd`** — YTD→full-year calendar-day proration; carries
        NO citation by design (it is disclosed ARITHMETIC, and the work says
        exactly when the level-pay assumption breaks).
      * **N-8 closed**: the 1099-INT DocSpec now appends a status note to
        every extraction — US bank-deposit interest paid to an NRA is
        generally NOT income (IRC 871(i)(2)(A)), and the §6013(g) ELECTION,
        not the marriage, ends the exclusion (the estimator's may-OVERTAX
        disclosure already existed).
      Knowledge: `estimated_tax_safe_harbor` + `supplemental_withholding`
      blocks and the employee-Medicare fields authored for 2025 AND 2026,
      every figure transcribed with verbatim quotes from Form 1040-ES
      (2025/2026) and Pub 15 (2025/2026) by four independent fetch agents
      before authoring. What remains agent-COMPOSED rather than engine-owned:
      per-segment wage projection is `annualize_ytd` per segment +
      `employee_fica` segments — the persisted, re-runnable scenario surface
      over these ops is H7.
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
- [x] **H6 — Schedule 1-A calc op — DONE 2026-08-09** (N-6; the calc op is
      `schedule_1a_deductions`, the 18th op). The item turned out HALF-BUILT:
      the `tax.obbba_schedule_1a` knowledge block (two-pass verified, with the
      asymmetric rounding as DATA) and the 54-field `sched_1a` form pack had
      shipped 2026-07-25 with the YAML itself noting "no calc op consumes it
      yet". Shipped: typed models (`ObbbaSchedule1aParams` + five sub-models —
      the models fit the SHIPPED YAML, no re-key; the senior 6% rate now loads
      as an exact Decimal via `_as_exact_decimal`, closing a float bug) and the
      op with all four parts. Traps golden-tested: the tips/overtime/senior
      **MFS forfeiture** (car-loan interest is NOT forfeited — its statute has
      no joint-filing rule); the tips **$25,000 per-RETURN cap** (a joint
      return does not double it); the **asymmetric rounding** (lines 11/19
      round the excess/$1,000 quotient DOWN, line 28 rounds it UP, line 34 is
      6% of excess per person); and **QSS takes the non-joint thresholds**
      (each statute keys on "a joint return" — the opposite of the rate
      schedules' QSS→MFJ mapping). 2026 declares the block deliberately absent
      until the 2026 Schedule 1-A publishes (statutory caps are fixed through
      2026, but the freshness protocol wants the form, not a paraphrase).
      *(was: scoped to also include §170(p) non-itemizer charity and the
      0.5%-AGI itemized-charity floor, and described the deductions as on
      "2026 returns". Corrected by the design review: both charity provisions
      are effective for tax years beginning AFTER 2025 — TY2026+, not TY2025 —
      and neither is a Schedule 1-A part (§170(p) is a Form 1040 line, the
      0.5% floor is a Schedule A computation), so they carve out to a separate
      2026-only knowledge item with no op until the 2026 forms publish; and
      the four deductions are on TY2025 returns, being filed NOW, which is
      what made H6 the only Phase H item that was also a live filing-path
      defect.)* Still open from the original H6 scope: **N-8**, the NRA
      bank-deposit-interest exclusion (§871(i)(2)(A)) — an extract_document /
      estimator note, tracked with H4's projection work.
- [x] **H7 — scenario comparison surface — DONE 2026-08-10** (N-9, N-15; the
      23rd MCP tool, `compare_scenarios`, + `taxfill_core.scenarios`).
      * Runs 2+ deterministic scenarios (filing posture forced per scenario — a
        confirmed status wins unconditionally in the candidate logic, which is
        what makes the §6013(g)-election MFJ what-if runnable on an NRA
        profile) and diffs each against the FIRST, with **two attributions,
        both EXACT and runtime-checked**: the per-slot ledger diff (the Stage-2
        spine invariant) and a **sequential input walk** whose steps telescope
        to the headline delta — every intermediate is a real computed bottom
        line, so "marry + election: +$1,105" decomposes into "MFJ brackets
        +$7,721; spouse income −$6,352; her interest −$264" the way the
        motivating session's hand-built table did. Order-dependence of the
        walk is inherent and disclosed, never hidden.
      * The election scenario auto-discloses the two traps the session had to
        derive: worldwide income becomes taxable (the scenario is only as
        complete as the income given), and the election does NOT start FICA
        (N-7b, stated unprompted).
      * **Persisted and re-runnable** (N-15's actual interaction): scenario
        sets store INPUTS-only in the year's workspace (`scenarios.json` —
        results recompute on every load, so pack corrections are picked up
        silently); `load="name"` + `income_updates` makes "the bonus landed,
        re-diff everything" ONE call. Covered by `taxfill purge`
        automatically (rglob-based wipe).
      * Cross-year what-ifs are labeled **PROJECTION** when any scenario runs
        on a provisional pack, and each outcome carries its missing_blocks —
        a silent cross-year diff was exactly the $2,126 credit-drop trap.
      * Tool count 22 → 23, flipped at every gate (EXPECTED_TOOLS + the
        exactly-N test, test_cli, ci.yml packaging, bundle/manifest.json —
        whose stale 17-op calc description got trued up to 25 in passing —
        README, ROADMAP, all three skills).
- [x] **H8 — tax-advantaged account knowledge — DONE 2026-08-10** (N-10, N-11,
      N-13; ops 22-25; N-12's withholding realism shipped earlier with H4).
      * **`contribution_limits` TOP-LEVEL knowledge block** (2025 + 2026) with
        the SCOPING as machine-readable Literals, because the scoping IS the
        answer: §402(g) per PERSON across all employers (traditional + Roth
        share it), §415(c) per EMPLOYER PLAN, IRA per person across both
        kinds, HSA per COVERAGE TIER (2×$4,400 self-only = $8,800 > the
        $8,750 family limit — encoded and tested), §125(i) per employee per
        employer, §132(f) monthly. Top-level on purpose — nested blocks evade
        the sources-coverage meta-test; a `contribution_limits` sources topic
        + BLOCK_TO_REQUIRED_TOPICS mapping back it. Every figure transcribed
        with verbatim quotes by seven fetch agents before authoring — which
        caught a live sourcing trap: **the irs-drop copy of Notice 2025-67 is
        DEFECTIVE** (its IRA section repeats the 2025 figures from Notice
        2024-80); the 2026 block cites the authoritative IRB 2025-49
        publication and warns against the drop copy in its citation.
      * **`ira_contribution_eligibility` (op 23) — the excess-contribution
        guard**: the Pub 590-A reduced-limit worksheet (round UP to $10, $200
        floor while partially phased), both the Roth-contribution and the
        traditional-DEDUCTION phase-out families (incl. the spousal-coverage
        range and the no-coverage-anywhere = no-phase-out rule), the
        MFS-lived-apart exception, and the 6%/yr excise on any excess — the
        live $194,600 error is now a machine verdict (allowed $0, excise
        $450/yr) with the year-end MFJ flip shown mechanically.
      * **`marginal_dollar_savings` (op 24)**: payroll HSA/FSA/commuter
        dollars avoid income tax AND FICA; 401(k)/deductible-IRA dollars
        income tax only; the FICA tier is computed (7.65% below the wage
        base, 1.45% between the base and $200k, 2.35% above), never assumed.
      * **`magi_ladder` (op 25)**: every MAGI test the year's packs carry in
        one table — NIIT (AGI+FEIE), Additional Medicare (a WAGE test AGI
        cannot move), student-loan interest (with the MFS hard bar),
        Schedule 1-A parts, Roth-IRA and deductible-IRA — each with its own
        definition, threshold and headroom; rows come only from shipped
        blocks, never guesses. The work narrates the full ladder (gross →
        box 1 → AGI → per-test MAGI).
      *(Deferred to H1-H3 by design: the **Roth-vs-pre-tax profile
      representation** — the ops take explicit arguments today, so the
      capability exists agent-composed; persisting the deferral split on the
      profile is intake/schema work and lands with that tranche.)*

- [x] **H9 — reward / other-income characterization + the NRA FDAP corner
      (field session 2026-08-10) — DONE 2026-08-10.** A real user asked whether
      a brokerage cash-management account's annual "engagement bonus" (a
      premium-card annual-fee reimbursement) is taxable. The engine could price
      the tax ONCE the characterization was known and could resolve the
      residency branch — but the characterization itself came entirely from the
      agent's head, which is the exact failure the freshness protocol exists to
      prevent. Shipped (every cited page fetched and content-verified before
      authoring):
      * **`sources.yaml` topic `other_income_and_rewards`** — Pub 525's Other
        Income chapter with the rebate-vs-income line (rewards earned by
        SPENDING are a purchase-price rebate, the Rev. Rul. 76-96 lineage; a
        bonus for OPENING or MAINTAINING an account is reportable other income,
        1099-MISC box 3 / 1099-INT) + Announcement 2002-18 (in-kind travel
        promotional benefits: no-enforcement UNLESS converted to cash or paid
        as compensation). "credit card rewards taxable", "bank account bonus
        income", "other income 1099-MISC" and "cash rebate income" now route
        here (they were clean misses).
      * **`sources.yaml` topic `nonresident_fdap`** — Pub 519 ch. 4 ("The 30%
        Tax"), the IRS FDAP page (30%-or-treaty on the GROSS amount, no
        deductions or netting), the ECI page (graduated rates after
        deductions — the split that decides page 1 vs Schedule NEC), the
        Schedule NEC instructions (30/15/10%/other rate columns), and Form
        1042-S. "FDAP", "effectively connected income", "nonresident FDAP
        income" (was → `nonresident_spouse_election`), "30% withholding
        nonresident" (was → `dual_status`) and "Form 1042-S" now route here.
      * **The H6-introduced regression is FIXED:** `get_sources("Schedule
        NEC")` routed to `obbba_schedule_1a_deductions` (the token "Schedule"
        pulled toward Schedule 1-A) — a WRONG-LAW pointer, the exact failure
        the H6 sources fix was written to prevent. It now routes to
        `nonresident_fdap`, and `test_sources.py` carries the extended
        neighbour-theft suite (the new topics must not steal
        `nonresident_and_treaties` / `nonresident_spouse_election` /
        `dual_status` / the OBBBA topic's canonical queries, and vice versa).
      * **`pitfalls.yaml` P-005** — the rebate-vs-income characterization as a
        permanent registry entry (year-invariant rules live there, not in a
        year pack; only the §871(a) 30% rate and any treaty "other income"
        article rate are figures). *(Closed 2026-08-10, same day: all five
        treaty packs now carry verbatim-verified `other_income` blocks and
        `treaty_benefit` gained the `other_income` income class — China
        Art. 21(3) / India Art. 23(3) / Canada Art. XXII(1) carve US-arising
        items back to source-state taxation, Mexico Art. 23 is
        source-state-only in form, Korea (1976) verifiably has NO other-income
        article — so US-arising other income gets NO treaty reduction under
        any shipped treaty.)* The P-005 regression suite is the routing test
        block in `test_sources.py` + the other_income tests in
        `test_treaties.py`.
      **Acceptance — met:** every query above resolves to its own topic, no
      neighbouring topic is stolen, and an agent asked "is this bonus taxable"
      reaches Pub 525 + Pub 519 ch. 4 without the operator supplying the law.

**Acceptance:** H1/H2 ship schema + intake changes with regression tests and an
eval scenario for the *unmarried two-NRA household, mid-year status change*
persona; H3 ships the segment loop + the worksheet surface with a no-experience
walkthrough in the skill; H4 ships golden-tested ops and a PROJECTION output
contract that can never be mistaken for a filed number; H5 follows the two-pass
verification rule for every figure; H6 ships golden-tested phase-out math for all
five Schedule 1-A parts including the MFS-forfeiture rules; H7 ships a diff whose
line items sum to the headline delta.

---

## Phase I — The high-income / equity-comp / visa-status profile (Effort: L)

> Found by the **2026-08-26 LIVE-USE audit**: the repo was driven end to end to
> compute a real TY2026 return for a single Texas filer (W-2 $206k = $125k base +
> $81k bonus, 401(k) $17k→$24.5k, HSA $4.4k, mega backdoor, an excess direct-Roth-IRA
> contribution needing recharacterization, a $20k old-plan balance being converted,
> ESPP, the $5,000 US-China Article 20(c) exemption, F-1/OPT → H1B mid-year, $5k
> investment income against a $1.5k capital loss). **Every figure the knowledge packs
> carry was correct and citable** — `rate_schedules`, `standard_deduction`, `niit`,
> `contribution_limits`, `capital_gains_brackets` all verified against Rev. Proc.
> 2025-32 / Notice 2025-67 / Rev. Proc. 2025-19 and used directly. But **six of the
> decisions the session actually turned on had to be computed OUTSIDE the engine.**
> That is the same failure signature `FIELD_NOTES.md` recorded for the Phase-H
> session, one user profile over: the data is there, the *decision surface* is not.

- [x] **I1 — The IRA-basis / pro-rata chain — DONE 2026-08-26.** Shipped:
      `calc.ira_pro_rata` + `calc.roth_conversion` (both paths, bracket headroom,
      the NIIT crossing), fillable `f8606` packs for 2023/2024/2025 (all
      vision-audited), pitfall **P-009**, a `get_sources` topic
      (`ira_basis_and_roth_conversions`), and 26 new calc tests. The work also
      caught three defects nothing else would have: a **QSS NIIT threshold** of
      $200,000 in `knowledge/federal/2026.yaml` where IRC 1411(b)(1) and the Form
      8960 instructions both say $250,000 (fixed, and pinned for every shipped
      year by a new sweep); a **`roth_conversion` bug** that took
      `other_distributions` into the pro-rata denominator and then silently
      dropped the resulting taxable line-15a income from every headline number
      (now refused prescriptively, pointing the caller at `ira_pro_rata`); and an
      **engine defect the 8606 pack exposed** — `verify._identity_checks` took the
      UNION of every pack's `identity_fields` and compared names against packs
      that merely MAPPED them, so Form 8606's printed-conditional address block
      ("Fill in Your Address Only if You Are Filing This Form by Itself"),
      correctly blank on the attached path, FAILed `verify_filing` on every normal
      8606 filing. A pack that maps without declaring is no longer compared when
      blank; a non-blank value still is. *(original scope below)*
- [x] **I1 scope as planned — the IRA-basis / pro-rata chain. The
      highest-consequence gap in the repo, and it is silent.** `pro_rata`, `form_8606` and `roth_conversion` return
      **zero source hits** today. Yet IRC 408(d)(2) — all traditional/SEP/SIMPLE IRA
      12/31 balances aggregate into one pool, so a conversion's taxable share is
      `pretax / (pretax + basis)` regardless of which dollars actually moved — is
      what decides, for every backdoor-Roth user, **where an old 401(k) may be
      rolled**. Measured in the live session: rolling a $30k pretax 401(k) into a
      traditional IRA costs **$1,440 in year 1 and $6,427 over ten years** versus
      rolling it into the new employer's 401(k), and the failure mode is invisible —
      no error, no warning, just a larger tax bill and a Form 8606 basis the filer
      must track for life. Build: **`calc.ira_pro_rata`** (per-account year-end
      balances + cumulative nondeductible basis + conversion amount → taxable
      amount, basis consumed, basis carried forward); **`calc.roth_conversion`**
      covering BOTH paths, which behave differently and are routinely conflated —
      (a) plan → Roth IRA *direct* rollover (Notice 2008-30: taxable = the pretax
      portion, and **pro-rata does not apply** because no IRA is involved), and
      (b) traditional IRA → Roth (pro-rata applies) — each surfacing bracket
      headroom and the NIIT threshold crossing (the live session's $20k conversion
      moved MAGI 187,500 → 207,500, crossing the $200,000 §1411 threshold and
      creating $133 of NIIT the filer had no way to anticipate, plus it landed
      $10,375 short of the 32% bracket — a margin no user can be expected to
      compute by hand); a fillable **`f8606`** pack for 2023/2024/2025 (Parts I/II/III
      — this is the form that carries basis across years, so without it the calc has
      nowhere to land); and pitfall **`P-009`** stating the trap with the measured
      numbers. **Acceptance:** 8606 vision-audited three years; the op reproduces the
      live session's worked example to the dollar; P-009 cited; the i14 scenario
      (I6) exercises the whole chain.
- [x] **I2 — HSA — DONE 2026-08-26.** Shipped: `calc.hsa_deduction` (Form 8889
      Parts I/II/III as IRC 223 writes them — the Line 3 Limitation Chart month by
      month, the last-month rule as 223(b)(8)'s greater-of WITH its 13-month testing
      period and recapture promoted to a result field, the 223(b)(7) Medicare zeroing,
      the 223(b)(5) family split between two spouses' HSAs, the age-55 catch-up's
      line 3 vs line 7 routing, the employer/cafeteria-plan offset, and IRC 4973
      excise), `f8889` packs for 2023/2024/2025 (vision-audited), 1099-SA and 5498-SA
      DocSpecs, and 42 tests including all three Publication 969 worked examples
      reproduced to the cent. Three defects the adversarial review caught and this
      change fixes: Form 8889 line 1's December override is **one-directional**
      (i8889 gives an override only for a family December, so a self-only December no
      longer flips a majority-family year to "Self-only"); the Additional Medicare
      tier began AT $200,000 instead of above it (Pub 15 withholds on wages "in excess
      of" the threshold); and `_F8889_VERIFIED_REVISIONS` claimed 2019-2025 while the
      citation body quotes 2021+ Schedule 1 / Schedule 2 destinations, so it is
      narrowed to 2021-2025. The repo's flat "payroll HSA dollars also avoid FICA"
      blurbs are corrected to the real tier ladder in the same pass. *(original scope
      below)*
- [x] **I2 scope as planned — HSA: the limit ships, the return does not.** `contribution_limits.hsa`
      carries the cited 2026 amounts ($4,400 / $8,750 / $1,000 catch-up, Rev. Proc.
      2025-19) but `hsa_deduction` has **zero source hits** and there is no
      **`f8889`** pack, so an HSA contribution can be planned and not filed. Build:
      f8889 (2023/2024/2025) + **`calc.hsa_deduction`** modelling the last-month rule
      and its testing period, the payroll-vs-personal split, and the
      general-purpose-health-FSA mutual exclusion (a live-session correction worth
      encoding: the payroll FICA saving is **Medicare-only 2.35%, not 7.65%**, for any
      filer already over the $184,500 SS wage base — i.e. exactly the population that
      maxes an HSA, so the naive 7.65% overstates the benefit by 3×). DocSpecs
      1099-SA + 5498-SA for the distribution side. **Acceptance:** 8889 audited; the
      op refuses an FSA+HSA combination; the over-wage-base FICA nuance is asserted
      by a test, not prose.
- [x] **I3 — Equity compensation — DONE 2026-08-26.** Shipped: `calc.espp_disposition`
      (IRC 423 — the qualifying/disqualifying split, the lesser-of on the GRANT-date
      price, the full purchase-date spread on a disqualifying sale even below that
      price, the Form 3922 box-8 lookback, and the BASIS CORRECTION brokers get
      systematically wrong, emitted as the Form 8949 Code-B row that files it);
      `calc.capital_loss_limitation` (IRC 1211(b)/1212(b) — the $3,000/$1,500 cap,
      Schedule D's Capital Loss Carryover Worksheet including its taxable-income
      limitation, and a multi-year chain that preserves short/long character);
      `f8949` packs for 2023/2024/2025, so a filer with stock sales can finally
      assemble a complete return; 3921 and 3922 DocSpecs; 41 tests transcribed from
      Pub 525's and Pub 550's own worked examples. `estimate.py`'s -3,000 clamp now
      cites the statute and names the op that tracks the carryover it does not.
      One review finding is worth recording for its SHAPE: an adversarial verifier
      found a real box-8 blind spot (a plan priced at 85% of the EXERCISE-date FMV on
      a risen stock understates the 423(c)(2) discount), a refusal was implemented
      for it — and then REVERTED, because the condition that catches it also
      describes Publication 525's own Example 10, which the IRS resolves the other
      way. Form 3922 box 8 is the only discriminator, so the shipped behaviour is the
      IRS default plus a promoted `input_assumptions` note naming BOTH readings and
      their dollar difference. *(original scope below)*
- [x] **I3 scope as planned — equity compensation, and the detail form Schedule D is missing.**
      `espp` and `wash_sale` return **zero source hits**, and there is **no `f8949`
      pack** — so although `sched_d` ships for three years, a filer with stock sales
      cannot actually assemble a return. Build: **`f8949`** (2023/2024/2025) including
      the basis-adjustment codes (Code B / Code O) that equity dispositions require;
      DocSpecs **3922** (ESPP) and **3921** (ISO); **`calc.espp_disposition`** —
      qualified vs disqualified holding periods, the lesser-of ordinary-income
      component under the lookback discount, and the **basis correction brokers get
      systematically wrong** (1099-B reports the discounted purchase price, not the
      adjusted basis, so a filer who trusts the form is taxed twice on the discount —
      a high-dollar, high-frequency error for exactly this user base); and
      **`calc.capital_loss_limitation`** — the $3,000/$1,500 annual cap plus
      indefinite carryforward with short/long character preserved per year
      (`estimate.py` clamps at -3,000 with a disclosure today and tracks **no**
      carryforward, so year 2 silently loses the excess). **Acceptance:** 8949 audited
      three years; the ESPP op reproduces a worked disqualified disposition
      *including* the 1099-B basis correction; a carryforward survives a multi-year
      round trip.
- [ ] **I4 — Visa-status filers: the largest penalty exposure in the repo.**
      Three holes, in descending stakes. (a) **`f8833`** closes a standing
      asymmetry: `calc.treaty_benefit` has shipped since G1 and computes the
      exemption, but the disclosure form IRC 6114 / Treas. Reg. §301.6114-1 requires
      **does not exist** — the engine tells a user to take a treaty position it
      cannot help them disclose (hit directly in the live session, where the
      Article 20(c) $5,000 was claimed). (b) **Form 8938** pack + an **FBAR
      (FinCEN 114) worksheet** — 8938 is an IRS form and packs normally; FBAR is
      FinCEN e-file-only, so it ships as a `hand_fill_worksheet` plus a `file_and_pay`
      checklist entry. Non-willful FBAR penalties run **$10,000+ per account per
      year**, the steepest exposure anywhere in this repo, and the F-1 → H1B
      population routinely holds home-country accounts. Both thresholds must be
      **elicited, not volunteered** — surfaced the way `state_scope` surfaces state
      filing duties. (c) **`f1116`** (foreign tax credit): every holder of a
      total-international index fund gets foreign tax in 1099-DIV box 7, and the
      de-minimis election (≤$300/$600, no form) versus the form is a real branch that
      nothing models. **Acceptance:** 8833 + 1116 audited; 8938/FBAR thresholds cited
      per year; an intake question that cannot be skipped silently.
- [ ] **I5 — Document extraction breadth.** 14 DocSpecs ship; the cheap, mechanical
      gaps are **1099-K** (gig/resale, and its moving reporting threshold),
      **1099-Q**, **W-2G**, **1095-B/C**, **5498**, and **K-1 for 1120S and 1041**
      (only the 1065 layout ships, so an S-corp or trust K-1 has no structured path).
      The 3921/3922 and 1099-SA/5498-SA specs belong to I3 and I2 respectively — do
      them there, and batch the remainder. **Acceptance:** every box layout read off
      the official form, round-trip tested.
- [ ] **I6 — Eval scenario i14: the live-use session itself.** Encode the
      2026-08-26 session as a scenario — it is what exposed I1–I5, and the repo's own
      precedent (FIELD_NOTES → Phase H) is that a real session is the best gap-finder
      it has. Locking it in means these gaps cannot silently reopen. **Acceptance:**
      i14 runs green and fails loudly if any of I1–I4 regresses.

**Sequencing within Phase I:** I1 → I2 (same filer, I1 has the higher consequence
and no dependencies) → I3 (its `f8949` is a prerequisite for a *complete* Schedule D
filing path, so it arguably outranks I2 — decide on whether the user base sells
stock) → I5 leftovers → I4 (highest stakes but the most research) → I6 last, since it
asserts everything above. **Deps:** none external. Phase A is orthogonal and should
not wait for any of this.

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
4. **Phase H** (the first real-user session, 2026-08-04). Rationale from
   [`FIELD_NOTES.md`](FIELD_NOTES.md): that session used 4 of the 22 tools and
   every number that decided the user's answer was computed *outside* the
   engine, over irs.gov figures the agent re-researched live.
   **ORDER CORRECTED 2026-08-07** by a 9-agent design review + three
   adversarial critics, each load-bearing claim re-reproduced against the code
   (the review also surfaced three FILING-grade correctness bugs that were
   fixed out of band as "Stage 0" — the bare-'OPT' residency flip, the silent
   planning-year credit drop, the state-footprint short-circuit — all of which
   outranked every planning item). *(was: **do H5→H8→H4→H7 before H1–H3** on
   the theory that the binding constraint is knowledge/data; refuted — H6 was
   half-built already and is a live filing-path defect, H8 is not "pure data +
   one op", and H1 hid a one-day correctness fix that is a prerequisite for
   the whole planning stack.)* The corrected order:
   * **[x] STAGE 2 — the shared ledger spine (DONE 2026-08-07).** H4-WI1,
     H7-W1 and H8-W5 all wanted to restructure `_bottom_line`'s composition,
     each declaring "depends: nothing" — a three-way collision. Restructured
     ONCE instead: every composition line carries `slot` (closed
     `_LEDGER_SLOTS` registry) / `role` (operand · explanatory · subtotal) /
     `effect` (signed contribution to the bottom line); `_bottom_line` returns
     a typed `BottomLineResult`; TWO invariants are enforced at RUNTIME on
     every computation — `sum(effect) == bottom` exactly in integers
     (`_reconcile`), and `StatusComparison.delta_lines` sum exactly to
     `delta` (`_delta_lines`, the attribution `_build_comparison` used to
     throw away — the table the real session rebuilt by hand). Plus
     `missing_blocks`: the machine-readable twin of the Stage-0
     "NOT ESTIMATED" prose, so H4/H7 can see which planning-year rows are
     MISSING rather than zero. Property-tested over 240 seeded randomized
     profiles spanning 2021 ARPA, spouse-split MFS, NRA and planning-year
     paths, with negative tests proving each guard bites.
   * **H6** Schedule 1-A calc op (data + form pack ALREADY ship for 2025; the
     op is the only missing piece, and TY2025 returns are being filed now —
     the one Phase H item that is also a live filing-path defect) →
   * **H4** projection mode + FICA-by-status-period + §6654 + withholding
     realism (new ledger slots on the spine) →
   * **H8** account-limit knowledge + MAGI ladder (data first; its ranking op
     waits for H4's FICA so there is one FICA implementation, not two) →
   * **H7** persisted, re-runnable scenario diff (inherits a reconciling diff
     from the spine regardless of order) →
   * then the remaining intake/schema work **H1–H3** (their correctness
     slices already shipped in Stage 0; what is left is genuinely
     elicitation).
   A hard-dated December 2026 TY2026 form-pack sprint is booked AROUND this
   sequence — the IRS publishes the 2026 forms Dec 2026–Jan 2027 and they must
   ship before the season opens; Phase H flexes, the sprint does not.
5. **Phase C** (months, parallelizable) — coverage breadth: C2 nonresident/
   part-year state forms, C3 hard states (MA fetch, IA/NM classification,
   CT/SC hand-fill, UT sourcing).
6. **Phase D** — D1 DONE; D2 = more tax years for state packs (all 15 PORTABLE
   and all 4 NEAR-PORT ports now shipped — 61 state packs over TY2023–TY2025;
   ~20 vision re-maps and ~26 URL-discovery rows remain) + the community
   pack-contribution pipeline (DONE).
7. **Phase I** (2026-08-26) — the high-income / equity-comp / visa-status
   profile. Recommended AHEAD of the D2/C2 remainder: every Phase I item is a
   short form pack or a single calc op, whereas the D2 remainder is ~20 full
   vision re-maps and the C2 remainder is 40 jurisdictions. More importantly
   Phase I closes *silent* defects on the profile the repo actually serves —
   I1's pro-rata trap costs a real filer $6,427 over ten years with no error
   message — while D2/C2 close *absences*, which announce themselves. Order:
   I1 → I2/I3 → I5 → I4 → I6.

Phases A, E, and the start of C are largely independent and can run in parallel.
Phase H is independent of C/D (different files) and can run alongside them.
Within C, resident packs (C1) are the long pole; the now-working `introspect` CLI
is the force multiplier. **C3 hard states are now the only items needing new engine
code** (a downloader fix for fetch-blocked AcroForms + an OCR-positioned overlay
filler for print-only forms) — every other remaining item runs on the existing
pipeline (W-7, once feared to need new field types, turned out to be a plain AcroForm).
