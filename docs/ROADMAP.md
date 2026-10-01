# TaxFill — Completion Roadmap (remaining work)

The design spec is [`docs/DEV_PLAN.md`](DEV_PLAN.md). This is the forward-looking
plan for what is **not yet done**, as of **2026-09-24** (re-planned 2026-09-23 — see Phase J).

> **Status note (2026-09-24).** Done: Phases 0, B, C1, C3, D1, E (except two boxes),
> F, G (G1–G6; G4 finished 2026-07-24 with all 35 graduated/flat jurisdictions), H
> (except H5's 2026 Tax Table, externally blocked) and I (2026-08-27).
>
> Open: Phase A (user-gated), C2, the D2 remainder, two Phase E boxes, and **Phase J**
> — the 2026-09-11 "finish everything" order, re-planned 2026-09-23 into resumable,
> about-a-day tranches (J0 … JS7). The re-plan followed two things: the 2026-09-11
> session died at the monthly spend limit leaving 15 uncommitted, unverified files on
> main (snapshot: branch `wip/phase-j-partial`); and six read-only reviews found the
> federal defects Phase J now orders first. Phase J also adds a recharacterization
> tool, 1099-R code interpretation and the explanation statement. The federal TY2026
> set is authored drafts-first from the posted IRS 2026 drafts (JT0–JT5), ahead of the
> finals flip (JT6).
>
> **Known stale source:** the DC 2025 D-40 booklet cited by
> `knowledge/states/dc/2025.yaml` has returned 404 since 2026-08-24; DC OTR re-issued it
> as `2025_D40_Book_082026_v1.pdf`. DC 2025 figures are not re-verified until Phase J
> JS1a.

## Where we are (verified)

Done and on `main` (**8,111 tests** — offline 7,280 + live-.gov 831; derived
by `scripts/sync_test_count.py --write` at every Phase J commit). The offline layer is green in CI and locally
(Python 3.11, matching CI, since J0). The weekly network layer has been **RED since
2026-08-17** — 6 of 6 freshness runs failed through run 35621846216 (2026-09-21) — on
two sources: the MA Form 1 blank returns 403 and the DC 2025 booklet returns 404 (DC
OTR re-issued it). Phase J JT0c (2026-09-27) put both behind an expiring allowlist
(`scripts/freshness_quarantine.yaml`), so a NEW red opens a `freshness red` issue, and
JS1a/JS1b (2026-09-28) fixed both. The one row left is a new finding: JS1b's newest-capture
probe shows mass.gov re-issued the 2023 Form 1 in May 2026 as a rebuilt AcroForm (the re-map
is JS5's).

- **M0 scaffold · M1 engine · M2 federal packs · M3 intake + knowledge · M4 MCP
  server (23 tools, stdio, image content) · M5 state support · M6 code/docs.**
- **MCP server — 23 tools, CI-gated** (`.github/workflows/ci.yml` asserts exactly
  23): list_forms, get_form_map, fetch_blank, fill_form, verify_form,
  verify_filing, render_form (vision Image), calc, residency, intake_checklist,
  list_document_kinds, extract_document, workspace_save, workspace_load,
  workspace_record_position, workspace_reconcile, state_scope, estimate_refund,
  compare_scenarios,
  get_sources, filing_summary, file_and_pay, hand_fill_worksheet (print-only
  states). The `calc` tool carries **35** deterministic ops (`packages/mcp-server/tests/test_skills_sync.py` pins the count; Phase J adds 8 → 40 without adding an MCP tool): the 25 of Phase H (tax, tax_with_preferential_rates, standard_deduction, se_tax, additional_medicare_tax, niit, taxable_social_security, excess_ss, student_loan_interest_deduction, education_credits, ptc_annual, ptc_monthly, child_tax_credit, eitc, dependent_care_credit, treaty_benefit, schedule_1a_deductions, employee_fica, estimated_tax_safe_harbor, annualize_ytd, contribution_limits, ira_contribution_eligibility, marginal_dollar_savings, magi_ladder, state_tax) plus Phase I's ira_pro_rata, roth_conversion, hsa_deduction, espp_disposition, capital_loss_limitation, foreign_tax_credit_election and foreign_asset_reporting.
- **Phase B — single-user completeness: DONE.** `extract_document` (W-2,
  1099-NEC/MISC/INT/DIV/G/B/R, SSA-1099, 1095-A, 1098-T/E, 1042-S, and — since
  2026-08-10 — **Schedule K-1 (Form 1065)**, with per-field provenance — and, since Phases I2/I3/I5, 1099-SA, 5498-SA, 3921, 3922, 1099-K, 1099-Q, W-2G, 1095-B, 1095-C, 5498, K-1 (1120-S) and K-1 (1041), since JR2c the IRA custodian statement, and since JF8 Form 1098-VLI: **28 kinds** per `list_document_kinds()`) and the resumable
  workspace (`workspace_*` tools + `taxfill purge` CLI, generated RECONCILIATION.md
  / CHECKLIST.md) are implemented, merged, and tested.
- **Federal form packs — priority set DONE.** **111 packs across 2019–2025**
  (2019:1, 2020:1, 2021:1, 2022:5, 2023:34, 2024:34, 2025:35 — f1040nr +
  Schedule OI joined 2024 on 2026-08-10, and the 2026-08 batch backfilled the
  rest of the 2023 set into 2024/2025: identical-topology ports off the 2023
  packs, digests pinned to the year's blanks, vision-audited page by page). M2 base
  set + Schedule SE/D/E + Form 8863 + Form 2555 all ship (2023), audited, golden;
  + **all four Phase-D new form types** — **Form 4868** (extension), **Form 1040-ES**
  (estimated-tax vouchers), **Form 1040-X** (amended return, Rev. 2-2024), and
  **Form W-7** (ITIN application, Rev. 12-2024) — all audited.
- **Repo-wide pack gates — every rule now covers the packs it claims to.**
  `test_pack_invariants.py` (2026-08-21) sweeps all **172** packs, federal and
  state, for `cross_form` target resolution, the checkbox-`group` rules,
  identity page mirrors and year tokens in line keys;
  `test_readonly_widget_mapping.py` does the same for ReadOnly bindings (**1,390**
  across 11 packs, pinned per pack by count — J0 re-pinned AL-40 2023 580→568 and
  MO-1040 2023/2024 262→256 / 260→254 on unmapping their DOR instruction banners and
  an empty checkbox frame; 1,414 before). The first two of those had been
  federal-only while CONVENTIONS.md called them binding — see Phase E for what
  shipped through the gap, and for the two live defects the widening found.
- **State form packs — 74 across three years** (TY2023 42 / TY2024 19 / TY2025 13).
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
8959, 8960, 8962, 2441, 843 (Rev. 12-2024), 8316, 8606, 8889, 8949, 8833, 1116, 8938 (2023–2025), Schedule 1-A (2025), and FinCEN 114 as a hand-fill worksheet. state — **all 42 income-tax
jurisdictions**: **38 via fillable AcroForm (74 packs across TY2023–TY2025)** — CA (540 + 540NR +
Schedule CA 540/540NR), NY (IT-201 + IT-203), IL, PA, OH, GA, NC, MI, NJ, VA, AZ,
IN, MO, MD, AL, CO, MN, WI, KY (740), OR (OR-40), LA (IT-540), KS (K-40),
AR (AR1000F), ID (40), NE (1040N), OK (511), ME (1040ME), MS (80-105),
RI (RI-1040), MT (Form 2), ND (ND-1), DE (PIT-RES), VT (IN-111), DC (D-40),
WV (IT-140), IA (IA 1040), MA (Form 1), UT (TC-40) — plus **4 via print/hand-fill
manifests**: CT (CT-1040), HI (N-11), NM (PIT-1), SC (SC1040).
**235 form packs total** — 225 `pack.yaml` (151 federal + 74 state) + 10
`handfill.yaml`. The state 74 breaks down **TY2023 42 / TY2024 19 / TY2025 13**.
> ⚠️ State form-pack year coverage is now **partial, no longer TY2023-only**:
> **22 of the 42 jurisdictions fill a post-2023 year** — AR, AZ, DC, KY, MO, NC, NY, OR, PA
> and UT (2024+2025), and HI/ID/IL/LA/ND/NJ/NM/OH/RI/VA (2024) — after the 2026-08-21
> ten-pack and 2026-08-25 four-pack tranches and the JS3b ports (UT 2025,
> AZ 2024/2025, DC 2024/2025, KY 2024/2025, LA 2024, ID 2024). For the remaining **20**, state *knowledge*
> spans 2023–2025 while the only fillable pack is TY2023, so `calc.state_tax`
> still computes years those packs cannot fill. That asymmetry is now 20
> jurisdictions wide rather than 40 (see D2).

> ✅ The four formerly-untracked state packs (**AL, CO, MN, WI**) are now committed
> (Phase 0, 2026-06-28) and counted above.

**Quality bar (non-negotiable, applies to every item below):** no invented
numbers — every figure cited to a .gov/.us source or shipped with an explicit
`unverified` caveat; every form-pack field map adversarially **vision-audited**
before it ships; tests green. Since 2026-08-04 the real gate has been trunk-based: full
offline suite plus CI green, with an adversarial second-agent verify recorded in the
commit body. Whether to restore feature branches under branch protection is a user
decision (Phase J JD2.3).

---

## History

The completed phases — 0, E, F, G and I — moved VERBATIM to [`docs/HISTORY.md`](HISTORY.md) on 2026-09-28 (Phase J JD2), so this file carries the open work. Their cross-references ("see Phase G", tranche ids) resolve there. Phases C, D and H stay here: each still has a box open under a Phase J tranche.

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
      **2026-09-24:** the names taxfill-core / taxfill-mcp / taxfill are still unregistered
      on PyPI, but the PyPI-immutable descriptions are stale ('21 calculation ops', '22
      tools') and PUBLISHING.md's smoke assert is `== 22` — Phase J **JA1** fixes them
      before any upload; **JA2** is the user half.
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
- [ ] **A2 — Tag the release.** → Phase J **JA1** (agent half) / **JA2** (user half). `git tag v0.1.0` + GitHub release notes.
- [~] **A3 — Build the `.mcpb` one-click bundle.** → Phase J **JA1** (agent half) / **JA2** (user half). **Manifest finalized (2026-06-28):**
      dropped the `$schema_note` draft marker, added `server.entry_point`, removed the
      now-unschema'd `permissions` block — `mcpb validate` **PASSES**. Only `mcpb pack`
      → `taxfill.mcpb` remains, and it is **publish-gated** (the bundle launches
      `uvx taxfill-mcp`, which only resolves after A1). Primary path for non-technical
      Claude Desktop users.
- [ ] **A4 — Record the 60-second demo GIF** → Phase J **JA1** (agent half) / **JA2** (user half). per `docs/DEMO.md` (storyboard +
      6 beats already written) → `docs/media/demo.gif`; embed in README.
- [ ] **A5 — Run the 20-minute non-developer acceptance test** → Phase J **JA1** (agent half) / **JA2** (user half). (`docs/ACCEPTANCE.md`)
      on a clean machine; fix whatever blocks a non-technical user.
- [ ] **A6 — Flip README** → Phase J **JA1** (agent half) / **JA2** (user half). "not yet on PyPI / bundle coming" language to shipped.

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
      → Phase J **JS6** (9 discovery rows with url+sha256 recovered from the 2026-09-11 run).

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
      would want the **overlay filler**, which is BUILT but unshipped (branch
      `phase-j2-overlay`; its verifier false-passes wrong values) → Phase J **JS4a–d**.

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
      TY2023-only**: 74 packs across TY2023 (42) / TY2024 (19) / TY2025 (13), so
      **22 of the 42 jurisdictions** can fill a post-2023 year — AR, AZ, DC, KY, MO, NC, NY, OR, PA and UT
      for both 2024 and 2025; HI, ID, IL, LA, ND, NJ, NM, OH, RI, VA for 2024. For the
      other **20**, a 2024/2025 return still computes but cannot be filled.
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
        0 near-port + 11 RE-MAP + **19 URL-DEAD** + 7 no-year-token. **Correction
        2026-09-23:** UT 2025 TC-40 is PORTABLE against UT's newest shipped base (2024)
        and was never shipped → JS3b; the 2026-09-11 re-triage counts 73 open pack-years
        → JS3a/JS3b/JS5.
      * **Re-measured 2026-09-28 (Phase J JD1)** with `scripts/scaffold_state_year.py --triage`, against the
        2023 base and, for the 13 jurisdictions that ship 2024, also 2024 → 2025:
        * **TY2024:**
          - 10 PORTABLE and 4 NEAR-PORT, all 14 shipped.
          - 10 RE-MAP: the four CA packs, GA, MI, MT, VT, WI and WV.
          - 12 URL-DEAD: AL, AZ, CO, DC, DE, ID, KY, LA, MA, NE, OK, and CT's hand-fill blank.
          - 7 no-year-token: IA, IN, KS, MD, ME, MN, MS.
          - 3 NO-ACROFORM: the HI, NM and SC hand-fill blanks.
        * **TY2025:**
          - 6 PORTABLE, five shipped — **UT TC-40 is PORTABLE and unshipped** (against both the 2023 and the 2024 base) → JS3b (shipped 2026-09-28).
          - 12 RE-MAP: the four CA packs, GA, MI, MT, VT and WI, plus MO, OH and VA (RE-MAP against their 2024 bases too: 59, 24 and 10 fields gone).
          - 18 URL-DEAD: TY2024's 12, plus IL, NC, ND, NJ, RI and WV — the first five dead against their 2024 URLs as well.
          - 7 no-year-token; 3 NO-ACROFORM.
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
      moved out of pack prose (commit 3a78087 promoted 150 already-verified deltas on 2026-08-11; the remaining
      2024/2025 gaps → Phase J **JS2**; instances for other packs as their
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

## Phase H — Planning mode, household granularity, no-experience onboarding (Effort: L)

> From the planning-surface gap catalogue (N-1 to N-15) logged in [`FIELD_NOTES.md`](FIELD_NOTES.md)
> (separate hypothetical illustrations; demo facts): multi-period visa timelines, multi-taxpayer
> households and **planning-year budgets**. Unlike Phase G,
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
      III's premium-half / below-AGI-line work line). Eval r covers both shapes
      on separate hypothetical fixtures (a mid-year status change; an unmarried
      household with a nonresident partner).
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
        does NOT start FICA on an exempt F/J spouse's wages — and the per-employer
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
      * **N-8**: the 1099-INT extraction note shipped here (2026-08-09); the
        exclusion COMPUTATION (IncomeSnapshot.bank_deposit_interest, the payee
        rule for a spouse's MFS return, pitfall P-013) shipped in Phase J J0
        commit B (2912644).
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
      (`tax_table.row_bands` is still a carried-forward structure). The
      provisional filing guard has since **SHIPPED** (ProvisionalPackError; evals
      i3/i4 assert that fill_form, verify_form and verify_filing refuse the year);
      the 2026 Tax Table is Phase J JT2a (draft second pass) / JT6 (final re-pin).
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
      until the 2026 Schedule 1-A publishes (the draft posted 2026-06-16; the block ships in
      Phase J **JF8**) (statutory caps are fixed through
      2026, but the freshness protocol wants the form, not a paraphrase).
      *(was: scoped to also include §170(p) non-itemizer charity and the
      0.5%-AGI itemized-charity floor, and described the deductions as on
      "2026 returns". Corrected by the design review: both charity provisions
      are effective for tax years beginning AFTER 2025 — TY2026+, not TY2025 —
      and neither is a Schedule 1-A part (§170(p) is a Form 1040 line, the
      0.5% floor is a Schedule A computation), so they carve out to a separate
      2026-only knowledge item with no op until the 2026 forms publish (Phase J **JF9**); and
      the four deductions are on TY2025 returns, being filed NOW, which is
      what made H6 the only Phase H item that was also a live filing-path
      defect.)* N-8, the last item of the original H6 scope, closed in Phase
      J J0 commit B (P-013).
- [x] **H7 — scenario comparison surface — DONE 2026-08-10** (N-9, N-15; the
      23rd MCP tool, `compare_scenarios`, + `taxfill_core.scenarios`).
      * Runs 2+ deterministic scenarios (filing posture forced per scenario — a
        confirmed status wins unconditionally in the candidate logic, which is
        what makes the §6013(g)-election MFJ what-if runnable on an NRA
        profile) and diffs each against the FIRST, with **two attributions,
        both EXACT and runtime-checked**: the per-slot ledger diff (the Stage-2
        spine invariant) and a **sequential input walk** whose steps telescope
        to the headline delta — every intermediate is a real computed bottom
        line, so a "marry + election" scenario decomposes into one exact line
        per input change (the filing status first, then each income override
        in the order given), the table a hand analysis would otherwise have
        to build. Order-dependence of the walk is inherent and disclosed,
        never hidden.
      * The election scenario auto-discloses the two traps a hand analysis has
        to derive: worldwide income becomes taxable (the scenario is only as
        complete as the income given), and the election does NOT start FICA
        (N-7b, stated unprompted).
      * **Persisted and re-runnable** (N-15's actual interaction): scenario
        sets store INPUTS-only in the year's workspace (`scenarios.json` —
        results recompute on every load, so pack corrections are picked up
        silently); `load="name"` + `income_updates` makes "a corrected W-2
        arrived, re-diff everything" ONE call. Covered by `taxfill purge`
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
        MFS-lived-apart exception, and the 6%/yr excise on any excess — a
        direct Roth contribution above the phase-out (demo numbers: married
        filing separately, spouses living together, MAGI $150,000, $6,000
        contributed) is now a machine verdict (allowed $0, excise $360/yr),
        with the joint-return range at the same MAGI shown mechanically.
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
      — DONE 2026-08-10.** Gap: the rebate-vs-income characterization of
      account bonuses and card/bank rewards (Pub 525) and the NRA FDAP split
      had no routed authority. The engine could price the tax once the
      characterization was known and could resolve the residency branch, but
      the characterization itself had to be supplied by the agent, which is
      the failure the freshness protocol exists to prevent. Shipped (every
      cited page fetched and content-verified before authoring):
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
      neighbouring topic is stolen, and a query such as "is an account-opening
      bonus taxable" reaches Pub 525 + Pub 519 ch. 4 through `get_sources`.

**Acceptance:** H1/H2 ship schema + intake changes with regression tests and an
eval scenario on hypothetical fixtures (*a mid-year status change; an unmarried
household with a nonresident partner*); H3 ships the segment loop + the worksheet surface with a no-experience
walkthrough in the skill; H4 ships golden-tested ops and a PROJECTION output
contract that can never be mistaken for a filed number; H5 follows the two-pass
verification rule for every figure; H6 ships golden-tested phase-out math for all
five Schedule 1-A parts including the MFS-forfeiture rules; H7 ships a diff whose
line items sum to the headline delta.

---

## Phase J — Finish everything (ordered 2026-09-11; RE-PLANNED 2026-09-23)

> **Origin.** On 2026-09-11 the user ordered all remaining development finished. That session hit the monthly spend limit on 2026-09-12 and committed nothing. It left 15 unverified files on `main` (13 modified, 2 untracked, +824/−62) and two failing tests.
>
> **Privacy.** Each tranche below states only the mechanism it fixes; worked figures are hypothetical-persona demo numbers (the FIELD_NOTES privacy rule). Besides every bug found, the plan adds **a recharacterization tool, Form 1099-R code interpretation and the explanation statement**.
>
> On 2026-09-23 six read-only reviews re-checked every claim on a clean checkout of `a233031` and against primary .gov text. The lenses were engine defects, the recharacterization design, the decision surface, the Phase J salvage, TY2026 readiness, and docs/release/process. A critic pass then re-verified the plan itself. Bracketed ids such as `[DEF-01]` are the 2026-09-23 review's gap ids, and each item carries its evidence pointer inline. Figures in acceptance tests are *illustrative* (demo numbers).

**Ordering rules (in force until this phase closes):**
1. **J0 first.** The dirty tree blocks every commit.
2. **By user harm.** Filing-wrong defects come first, then silent omissions. After those come the retirement block and workaround-needed decision ops. Absences that announce themselves come last.
3. **Federal before state** (the user's standing rule). No JS tranche starts while a federal tranche is queued.
4. **Hard dates.** These tranches have latest-start dates:

   | Tranche | Latest start | Why dated |
   |---|---|---|
   | JT0a | 2026-10-12 | TY2026 drafts-first plumbing |
   | JP1a | 2026-10-14 | its value ends with the last 2026 paycheck |
   | JP2 | 2026-10-19 | its value ends with the last 2026 paycheck |
   | JT3a | 2026-10-26 | TY2026 Wave A packs |
   | JT5a | 2026-11-16 | TY2026 Wave B packs |

   On its date a dated tranche takes the next slot; it never interrupts a half-finished tranche. If two dates are due at once, the earlier date goes first. JT0b/c and JT3b–d follow their `a` tranche back to back. JT6 fires when `check_finals` reports a published final; by the 2025 precedent that is late Dec 2026 – Feb 2027 (an inference). Everything else flexes.
5. **Tranche contract.** One tranche at a time, finished completely before the next starts:
   - builder, then an adversarial second-agent verify, then fix;
   - full offline suite green (`uv run python -m pytest -m "not network"`), then `scripts/sync_test_count.py --write`;
   - CI green, then commit and push.

   Every tranche is sized at about a day (M) or less. Multi-pack tranches commit **per pack**, and JEb, JS5, JS6 and JS7 commit per pack family or per pack. So a spend-limit death costs at most one sub-tranche (about a day), and it resumes with the workflow-resume pattern.
6. **Invariants.**
   - The MCP tool count stays **23**; new capability arrives as calc ops.
   - Eight new calc ops take `test_skills_sync` from 32 to **40**, one bump per op as it lands: `elective_deferral_room` (JP2), `ira_net_income_attributable` (JR2a), `ira_recharacterization` (JR2b), `charitable_deduction` (JF9), `withholding_projection` (JP1c), `underpayment_penalty` (JP5a), `paystub_to_w2` (JP3b), `claim_of_right_repayment` (JP4).
   - Every durable rule lands in two places:
     - as a pitfall with a regression test citing its id (`test_pitfall_coverage`);
     - at its use sites (op work string, DocSpec note, intake text), not only in a registry. This is the knowledge-gap pattern.
   - **Line numbers:** from JF6a on, no new code may type a form line number; every destination renders through `form_line(pack, key)`.
   - **Pitfall ids** are assigned at commit time in tranche order. P-013 is N-8, and P-013 also takes LD-15's 871(k) corner. P-014 is the handfill "no" checkbox (J0 commit C) and P-015 is form-line-drift (JF6a). Tentative new ids: P-016 treaty-destination (JF1a), P-017 flat-rate-precondition (JF1a), P-018 residency-facts (JF5a/b), P-019 box1-standin (JF3), P-020 withholding-vs-liability (JP1a), P-021 recharacterization (JR2b), P-022 charitable-characterization (JF9), P-023 public-benefit-qualified-alien (JT1c), P-024 education-ssn-deadline (JT1e), P-025 claim-of-right (JP4). Assigned outside that list (the next free id, since P-019..P-025 stay reserved): P-026 nra-entry-space (JF1b.13).

**Old → new map.**

| 2026-09-11 item | Where it went |
|---|---|
| J1(a) verify scans mapped ReadOnly widgets | J0 commit A, **with** the regression fix it needs (J0.3) |
| J1(b) N-8 §871(i)(2)(A) deposit-interest exclusion | J0 commit B plus its missing tests; the dual-status corner goes to JF5b.3 |
| J2 overlay filler (CT/HI/NM/SC) | merged onto main by JS4a (2026-09-28, verifier fixed); the per-state packs ship as JS4c–d |
| J3 state 2024/2025 remainder (73 pack-years, not ~66) | JS3a/b (scaffold + cheap ports incl. UT 2025) + JS5 (re-maps / URL-dead); TY2024 leftovers fold into JS7 |
| J4 C2 nonresident / part-year | JS6 |
| J5 effective_law_changes sweep | JS2, re-scoped from 84 to 30 packs (15 adjudications) |
| J6 docs truth-up + push | J0.6 (header, this section, N-8/H5 status) + JD1 + JD2 |

**Execution order at a glance** (S = hours, M = a day, L = days, XL = a week or more; split rows commit separately):

| # | Tranche | Size | Why here | Deps | External / date |
|---|---|---|---|---|---|
| 1 | J0 Salvage the 2026-09-11 tree | M | blocks every commit; FBAR checkbox is filing-wrong | — | — |
| 2 | JF6a Form-line registry + guard | S–M | every later tranche renders lines through it | J0 | 2026 values are drafts |
| 3 | JF1a Wrong words on resident / retirement / payroll paths | S–M | filing-wrong (treaty line) + silent | JF6a | — |
| 4 | JF5a §6013 election keeps nonresident rules | M | filing-wrong | J0 | — |
| 5 | JF5b Prior-year residency + dual-status pricing | M | silent | JF5a | Pub 519 ch. 6 read (5b.3) |
| 6 | JF1b Small logic fixes | S–M | silent / docs | J0 | — |
| 7 | JF2 Wrong-law routing + document notes | M | silent | J0 | — |
| 8 | JF3 W-2 boxes 3/5/6 reach the estimator | M | silent | JF6a, JF1b | — |
| 9 | JF4 FICA tiers + safe-harbor inputs | M | silent | JF3 | — |
| 10 | JP1a employee_fica two layers + Step 4(c) | M | worthless after the last 2026 paycheck | JF1a, JF3, JF4 | **latest start 2026-10-14** |
| 11 | JP2 Multi-employer 402(g) room | M | same | J0 | **latest start 2026-10-19** |
| 12 | JR1 1099-R box 7 interpretation | M | retirement block; silent | JF2 | — |
| 13 | JR2a NIA op + statements + deadline fallback | M | retirement block | JR1, JF6a | — |
| 14 | JT0a Draft packs, rehearsal, second_passes | M | TY2026 plumbing | J0 | **latest start 2026-10-12** |
| 15 | JT0b Planning-year fixtures | M | | JT0a | — |
| 16 | JT0c Finals watch, red-quarantine, 1040-ES, 2026 header | M | | JT0a | — |
| 17 | JR2b `ira_recharacterization` | M–L | retirement block | JR2a | — |
| 18 | JR2c Custodian statements, manifest, rule reach | M | retirement block | JR2b | — |
| 19 | JF6b Rewire calc.py line literals | M | wrong lines for 2026 and 2019/2020 | JF6a | — |
| 20 | JF6c Rewire other sites + Schedule 1-A keys | M | | JF6b | — |
| 21 | JF7 Schedule 1-A reaches the estimator | M | silent (TY2025) | JF6c, JF1b | — |
| 22–24 | JR3a/b/c Retirement distributions; IRA pool; 72(t)/4973 | M each | silent | JR1, JR2b, JF6b | — |
| 25–28 | JT3a/b/c/d Wave A 2026 packs + f1040es | M–L, M, M, M | TY2026 | JT0a–c, JF6c | **JT3a latest start 2026-10-26** |
| 29 | JF8 Schedule 1-A 2026 + Form 1098-VLI | M | refused today | JT0b, JF6c, JF7 | re-verify at final |
| 30 | JF9 2026 charitable deduction + Pub 526 rules | M | silent (2026) | JT0b, JF7, JF2 | NRA eligibility unverified |
| 31–35 | JT1a–e 2026 knowledge needing schema changes | M each | absence | JT0b | Schedule 3-A instructions |
| 36–37 | JT2a/b 2026 knowledge that ports as-is | M, S–M | absence | JT0b | i1040sa (2026) for §68 mechanics |
| 38–40 | JT4a/b/c 2026 documents + dress rehearsal | M, S, M | extraction | see JT4 | — |
| 41–42 | JP1b/c Pub 15-T knowledge; `withholding_projection` | M, M–L | decision op | JP1a | — |
| 43–48 | JT5a–f Wave B 2026 packs | M…M–L each | TY2026 | JT3a | **JT5a latest start 2026-11-16**; JT5g waits on Schedule NEC/OI drafts |
| 49–50 | JP5a/b Underpayment penalty (Form 2210) | M each | decision op | JF4 | Q1-2027 §6621 rate |
| 51 | JD1 Docs truth-up | M | docs | JR2c, JF6c | — |
| 52 | JA1 Phase A, agent half | M | release; next slot the day the user is ready | J0 | — |
| 53–54 | JP3a/b Paystub → projected W-2 | M each | decision op | JP1c, JP2 | — |
| 55 | JP4 Claim of right | M | absence | JF2 | — |
| 56–57 | JR4a/b Form 5329 packs (incl. 2026 draft) | M–L, M | workaround | JR3c, JT0a | — |
| 58 | JP5c Form 2210 packs (incl. 2026 draft) | M–L | workaround | JP5b, JT0a | — |
| 59–60 | JEa/b Pack-gate leftovers, verify debt | M, L (per family) | latent silent | J0 | — |
| 61 | JD2 Process | M | process | JD1 | user OK for remote deletes / branch protection |
| — | JT6 Finals re-pin + flip + 2027 pack | L | — | JT1–JT5 | IRS finals (trigger) |
| — | JA2 Phase A, user half | — | — | JA1 | the user |
| 62+ | JS1a … JS7 (state) | S–M … XL (per pack) | federal-first | federal lanes | JS7: state 2026 blanks |

### Block 0 — Salvage

- [x] **J0 — Salvage and close the 2026-09-11 working tree — DONE 2026-09-24** (commits 7376aa3 A, 2912644 B, 7863049 C, and the docs commit; branch `phase-j2-overlay` parks J2; `wip/phase-j-partial` keeps the untouched snapshot) (M; deps: none; external: none)
  - **Why.** Main carries 15 files that no verifier ever checked, and two tests fail:
    - `test_estimate::test_fix2_…` pins a sentence N-8 removed on purpose (the test is wrong, the code is right);
    - `test_pitfall_coverage`: P-013 has no regression test.
    
    J1(a) as written is a regression, and J2's verifier false-passes. No file needs rewriting.
  - **J0.1 Snapshot** [G21, PJ-14].
    - Commit the whole tree as one commit on `wip/phase-j-partial`, then switch `main` back to `a233031`.
    - Where a file belongs to one deliverable, check it out whole from the snapshot.
    - `handfill.py` is the one mixed file: it holds the FBAR checkbox fix and J2's `worksheet_money_values`. Hand-apply it; there is no interactive staging here.
    - Apply the P-013 edit to `pitfalls.yaml` after commit A's P-007 edit.
    - Put the J2 files and hunks on `phase-j2-overlay`: overlay.py, schemas/handfill.py, the filler.py dispatch, `taxfill locate` in cli.py, server.py `_load_any_pack` routing, and handfill.py `worksheet_money_values`.
  - **J0.2 Housekeeping** [G24].
    - The `.venv` shebangs still point at the pre-move `~/Desktop` path, so `.venv/bin/pytest` fails with "bad interpreter". Local Python is 3.12.5; CI pins 3.11.
    - Run `rm -rf .venv && uv sync --python 3.11`, add `.python-version` = 3.11, and clear the stale `__pycache__`.
  - **J0.3 Commit A — verify scans mapped ReadOnly widgets (old J1a), plus the regression it introduced** [PJ-02; the export half of PJ-13].
    - AL-40 2023 maps DOR instruction banners (`Instructions`, `Instructions1`–`11`, `NonDriver`; al40/pack.yaml:62), and so do MO-1040 2023/2024 (`Texto7`–`9`, `MOAText`, `lblNRI`; mo1040 2023 pack.yaml:1651). A real one-line fill therefore now FAILs P-001 12 / 5 / 5 times, where HEAD gives ok=True.
    - The 826 round-trip tests miss it because their sentinel values overwrite the banners.
    - Fix the verifier: it scans a mapped ReadOnly widget only when this fill could have written it (its line is in `expected` / the merged values), or when its /V differs from the pinned blank's.
    - Fix the packs: unmap the banners, and re-pin `STATE_COMPUTED_READONLY` 580→568, 262→256 and 260→254 (the MO counts also drop MO-1040's empty `Text1` checkbox frame, which the widened scan FAILed on), each with its reason (test_readonly_widget_mapping.py:386-416).
    - Keep the GA 500 / WV IT-140 maxlen hints, export `bound_widget_names`, and mark P-007(b) closed.
  - **J0.4 Commit B — N-8 (old J1b) plus its tests** [PJ-03].
    - The code is correct against IRC 871(i)(1)-(3), Pub 519 ch. 3 and ch. 1, and the 2025 i1040NR line 2b Exceptions 1 and 3.
    - Rewrite test_estimate.py:1071 to assert the 871(i)(2)(A) disclosure and the absence of "OVERTAX".
    - Add the tests P-013 itself names:
      - test_estimate: the `deposit_interest_exclusion` slot; partial characterization; a resident control; uncharacterized interest taxed with a note; a confirmed-MFJ election taxed; the validator (`bank_deposit_interest > interest` raises); combined_with_spouse sums it;
      - test_intake: 4 tests;
      - test_sources: 3 routing tests plus the bank-bonus neighbour guard.
    - The 1099-INT status note (extract.py:134-140) names `IncomeSnapshot.bank_deposit_interest`.
    - Flip N-8 to DONE in H4/H6 and in FIELD_NOTES [G03].
  - **J0.5 Commit C — hand_fill_worksheet ticks "X" for "no"** [PJ-05]. At HEAD, any non-empty value ticks the box, including the **federal** FinCEN 114 (8 checkbox lines × 3 years) and the CT/NM/HI/SC packs. Ship the `_checkbox_checked` and `-0` rendering hunk with its tests.
  - **J0.6 Docs commit.**
    - This section, plus the header / "Where we are" truth-up and H5's guard marked shipped [G01, G02, G04, part of PJ-12].
    - An `unverified` entry in knowledge/states/dc/2025.yaml: "the cited 2025 D-40 booklet URL has returned 404 since 2026-08-24; DC OTR re-issued it as 2025_D40_Book_082026_v1.pdf; figures not re-verified → JS1a". No tool reads that list (grep: no consumer in taxfill_core), so the same line also goes into ROADMAP.
  - **Acceptance.**
    - `main` is clean and both branches exist.
    - `uv run python -m pytest -m "not network"` exits 0 from the rebuilt venv, with no "bad interpreter".
    - `sum(STATE_COMPUTED_READONLY) == 1,390` across 11 packs.
    - New repo-wide sweep: for every pack with a cached blank, a minimal one-text-line fill verifies with **zero** ReadOnly clipping FAILs.
    - test_handfill:
      - 'no' / False / '0' / 'off' leave the box blank; 'yes' / True / 1 / 'x' tick it;
      - 'maybe' raises, naming the line with the value redacted;
      - a computed '-0' renders '0';
      - an FBAR no-answer leaves its box blank.
    - sync_test_count is clean; CI is green; pushed.

### Block 1 — Federal filing-wrong and silent defects

- [x] **JF6a — Form-line registry, helper and guard — DONE 2026-09-24** (S–M; deps J0) — pitfall *form-line-drift* (P-015)
  - **Why.** Form line numbers are typed as literals: about 100 in calc.py alone, plus the estimate / intake / server / profile / workspace sites. They are already wrong for TY2025, for 2019/2020, and for 2026 per the posted drafts. The next tranches would add more (Schedule 1 line 8z, 1040 line 25c, 8959 Part V, Schedule SE line 8a), so the registry comes first. This is the knowledge-gap pattern: the figure ships, the year's form metadata does not. [DEF-05 + LD-17 + TY26-19]
  - **Build.**
    - A TOP-LEVEL `form_lines` block in knowledge/federal/{2019..2026}.yaml, registered in the sources-coverage mapping and typed in knowledge.py. Each entry carries `line_source: final | draft Created <date>` and the face URL.
    - Helper `form_line(pack, key)`: a key missing for a year raises; a draft entry renders with "(2026 DRAFT form — re-verify at final)".
    - Design choice, recorded: the numbers live in the knowledge pack, not a Python module. They are per-year published facts that need sources and the draft/second-pass discipline, and JT6 then lists the draft entries to re-verify.
    - This tranche reads each year's face only for the keys JF1a/JF3/JF4 need:
      - `sched1.other_income`: '8' for 2019/2020, '8z' from 2021. Faces read 2026-09-23: 2019/2020 print only "8 Other income. List type and amount"; 2021 first prints "8z … 9 Total other income. Add lines 8a through 8z".
      - `f1040nr.treaty_exempt`
      - `f8959.withholding_part`
      - the 1040 line that takes the Form 8959 Part V amount (25c on the 2026 draft)
      - `sched_se.ss_wages`
    - JF6b/JF6c add the rest, each reading the faces for the keys it adds.
  - **Guard.** A static test scans the calc.py / estimate.py / intake.py / server.py f-strings for `(Schedule [123]|Form 1040(-NR)?|8959|8889|Schedule 1-A)[^\n]{0,15}line \d` outside `form_line`. Today's literals are listed in a frozen debt list that JF6b/JF6c shrink to zero; an entry that no longer matches fails the test (self-clearing, like the P-007 tables).
  - **Acceptance.**
    - `form_line(2020, 'sched1.other_income') == '8'`; 2021 → '8z'; an unknown year raises; a 2026 draft entry carries the DRAFT suffix.
    - A new literal added anywhere fails the guard.
    - The pitfall has a citing test.

- [x] **JF1a — Wrong words on the resident, retirement and payroll paths — DONE 2026-09-25** (S–M; deps JF6a) — pitfalls *treaty-destination* (P-016), *flat-rate-precondition* (P-017). As built, the paper-refund note (item 5) covers every tax year, not only TY2025+: FS-2026-02 Topic A Q1 keys the phase-out on when the refund is ISSUED (after Sept. 30, 2025), and a 1040-NR refund also quotes Topic D Q1 for filers abroad.
  1. **Treaty reporting line** [DEF-04].
     - The treaty text always sends the filer to Schedule OI item L / Form 1040-NR line 1k (estimate.py:1856, :151-153; calc.py:47, :8449; server.py:355, :834).
     - Pub 519 (2025) ch. 9 says a resident alien enters it "in parentheses, on Schedule 1 (Form 1040), line 8z", with "Exempt income", the country and the article. Pub 519 (2020) says "in parentheses on line 8, Schedule 1 (Form 1040)" (read 2026-09-23). Form 8833 exception 2 covers students and trainees.
     - Branch on the classification:
       - resident → `form_line(year, 'sched1.other_income')`;
       - nonresident → the Schedule OI / `f1040nr.treaty_exempt` text;
       - dual-status candidate or unknown → both, framed conditionally.
     - `treaty_benefit` gains `resident_alien`.
  2. **Box 2a is gross for a traditional IRA** [RC-06]. `retirement_income_taxable` is documented as "1099-R box 2a" (estimate.py:140-141; server.py:831-832). For a traditional-IRA distribution or conversion, box 2a is the GROSS amount with 2b checked (i1099r 2026), so a filer with basis has AGI overstated by that basis. Re-document the field as the TAXABLE amount (Form 1040 line 4b/5b), point at `ira_pro_rata`, and state that codes N/R and G/H are 0.
  3. **The flat 22% is conditional** [LD-01 + DEF-13].
     - Four use sites say bonuses are withheld at the FLAT 22% and to "project 22% × bonus" (calc.py:3510-3518; knowledge.py:1231-1236; server.py:392; SKILL.md:71).
     - The rule is Treas. Reg. 31.3402(g)-1(a)(7)(i). The employer "may" use the flat rate only if:
       - (B) the supplemental wages "are either not paid concurrently with regular wages or are separately stated on the payroll records"; and
       - (C) "Income tax has been withheld from regular wages of the employee during the calendar year of the payment or the preceding calendar year". Pub 15 (2026) §7 reads this as "you" (the employer) having withheld.
       
       Otherwise (a)(6)(i) requires the aggregate procedure, and Pub 15 §7 item 2 says "use method 1b". (a)(2) makes 37% mandatory over $1,000,000.
     - Hire status is not the test. The two methods can differ by thousands of dollars on a large bonus.
     - Knowledge: add `flat_rate_conditions` (both quotes), `method_if_conditions_fail: aggregate` and `flat_rate_optional: true` to the 2026 `supplemental_withholding` block, and to 2025 after re-reading Pub 15 (2025).
     - Rewrite all four use sites to state the two conditions and the aggregate fallback. They point at no op until JP1c ships one.
  4. **Resident aliens on F-1 owe FICA** [LD-12, text + refusal]. employee_fica states only "F-1 OPT = NO FICA" (server.py:381; calc.py:3255-3262, :3302-3306). Pub 519 ch. 8 says it is withheld "if you are considered a resident alien … even though your nonimmigrant classification … remains the same".
     - Add that converse to the docstring, the work string and SKILL.md.
     - Add optional `residency_classification`: for 'resident', fica_exempt on an F/J segment is refused, quoting Pub 519.
  5. **Paper refund checks** [TY26-15, note part]. file_and_pay promises a paper refund check (file_and_pay.py:353). irs.gov/ModernPayments announces the "phase out of paper tax refund checks beginning Sept. 30, 2025, to the extent permitted by law". For TY2025+, a refund without direct deposit gets that note with the citation.
  - **Acceptance.**
    - Treaty:
      - resident-classified 2025 → contains "Schedule 1" and "8z", not "1040-NR line 1k";
      - resident-classified 2020 → "Schedule 1 line 8", not "8z";
      - the NRA assertion at test_estimate.py:1361 still passes.
    - The `retirement_income_taxable` description contains "TAXABLE" and "ira_pro_rata".
    - The safe-harbor work contains "31.3402(g)-1(a)(7)(i)", "separately stated" and "aggregate", and no longer contains the unconditional 22% sentence.
    - `employee_fica(residency_classification='resident')` with an F-1 segment `fica_exempt=True` raises, quoting Pub 519 ch. 8.
    - `file_and_pay` for a TY2025 refund with `direct_deposit=False` carries the ModernPayments note.
    - Both pitfalls have citing tests.

- [x] **JF5a — FILING-WRONG: the §6013 election keeps nonresident rules — DONE 2026-09-26** (M; deps J0) [PJ-04] — pitfall *residency-facts* (P-018). As built: the fact is `residency_facts.section_6013_election` on the TAXPAYER (a spouse copy is refused), applied on a household married for the year (never onto a single/HOH figure); a confirmed MFJ status of a nonresident is read as the election unless a DECLINE is recorded (a recorded `false` wins: MFJ leaves the candidates and a confirmed MFJ gets a contradiction note) or the precondition fails (neither spouse a citizen or resident on the recorded facts: IRC 6013(g)(3), not applied, priced without it); a recorded election whose facts point to 6013(h) is kind 'either' (a continuing 6013(g) election cannot be told apart until JF5b's prior-year fact); the 6013(g)(3) gate and intake share one trust rule (a nonresident answer resting on a missing lookback year is unknown); compare_scenarios' walk always ends on the scenario's own configuration and books a reading change to the step where it happens; a married filer's head of household is priced by route (nonresident spouse: 1040-NR spouse, no EITC, Pub 519 ch. 5; lived apart: a free deduction method, Pub 501), and a nonresident alien's HOH is never recommended in compare_scenarios (a confirmed one is priced as given with a Pub 519 ch. 5 caveat, JF1b.12); the 6013(g)(3) gate counts only a CERTAIN nonresident (residency.certain_nonresident); both J0 follow-ups shipped. The adversarial verify added: IRC 6013(g) and 6013(h) are two quoted texts (statement, duration, NIIT default 1.1411-2(a)(2)(iii) vs (iv)) chosen from each spouse's no-election residency; the two-return MFS pair prices both deduction methods under IRC 63(c)(6)(A); a spouse of unknown residency is bracketed under 1040-NR rules; compare_scenarios' `us_resident_election` is tri-state (omitted follows the recorded fact) and never recommends an election the facts rule out; the W-7 last mile, Form 8843 and the FICA refusal text ride the election; intake and the estimate apply a recorded election on the same marriage rule (an unanswered marital status with a confirmed joint status included), and a scenario that follows a recorded election onto a single/HOH status is named as not applied.
  - **Why.**
    - compare_scenarios' §6013(g)/(h) election flips only `identity.us_person` (scenarios.py:170-176), which `_classify_residency` ignores whenever a timeline and day counts exist (estimate.py:914-928, :1699-1701).
    - So a timeline-bearing NRA couple's election MFJ outcome keeps nonresident rules, including an itemized-only deduction of $0. Reproduced at HEAD on the test fixture: election −763 vs MFS −2,513.
    - test_compare_scenarios.py:30-31 uses a timeline-free profile, which is why no test sees it.
    - Pub 519 ch. 1: the couple are "treated for income tax purposes as residents for your entire tax year".
  - **Build.**
    - Add `residency_facts.section_6013_election: Answer[bool]`, set by the scenario.
    - When it is True, `_classify_residency` returns a resident-shaped result: standard deduction, NIIT evaluated, deposit exclusion off. The worldwide-income and FICA caveats stay.
    - Mirror the rule in the residency tool and intake output.
    - **J0 re-verify follow-ups (2026-09-24):** the election flag must switch the deposit exclusion off on an MFS status too (Pub 519 ch. 1: after the election year the couple "can file joint or separate returns", both still residents — today only the MFJ gate is modeled); and the spouse's two-return MFS `_bottom_line` must take the SPOUSE'S own classification as `nonresident` (today it borrows the taxpayer's for every rule except the deposit exclusion: a US-citizen spouse's 1040 gets no standard deduction and ordinary rates — ~$3,050 overstated in the verifier's repro, disclosed only through P-013's not-modeled list).
  - **Acceptance.**
    - On a timeline-bearing fixture, the election's MFJ "Less: standard deduction" equals the pack's MFJ figure for the year.
    - No 1040-NR label appears; NIIT is evaluated.
    - The pitfall has a citing test.

- [x] **JF5b — Prior-year residency fact; price the dual-status risk — DONE 2026-09-27** (M; deps JF5a) — As built: part 1 the prior-year return fact (`PriorFilings.return_forms[year-1]`, a CONTRADICTION/CHECK first, a may-flip nonresident bracketed on resident rules); part 2 the dual-status point under Pub 519 ch. 6 with the full-year-resident end only where a route is open, and the nonresident-period deposit split; part 3a the Treas. Reg. 1.1411-2(a)(2)(iii)/(iv) NIIT default on every election figure; part 3b the election as a CANDIDATE for a nonresident or dual-status taxpayer (symmetric with the reverse couple), route (ii) pointing at it, a dual-status spouse's own return under ch. 6, and a prior-year election return as a continuing IRC 6013(g) (the prior-year return alone never applies it; a confirmed joint status is still read as the election, JF5a). Deferred (not done): a prior `dual_status` departure return followed by residency (Treas. Reg. 301.7701(b)-4(e)(2)); the departure note's 10-day de minimis and foreign-tax-home wording; the compare walk's `bank_deposit_interest_nonresident_period` subset pair → JF1b.6; spouse-field coverage over list/Optional fields → JF1b.5; a confirmed head of household in a dual-status year priced as given → JF1b.12; a dual-status U.S. spouse's own separate-return NIIT under 6013(g); no NIIT note on compare_scenarios outcomes; a (iii)(A) tie where one spouse is a certain nonresident; the reverse dual couple (a citizen with a dual-status SPOUSE) whose joint candidate is still not an election figure; the spouse has no prior-year return fact. Also deferred from part 3b's verify: route (ii) under a confirmed non-joint status (the same-status resident figure is lawful only in a later year of a continuing 6013(g)); the continuing-election reading is named, not priced, when no answer is recorded; the residency MCP tool's section_6013_kind has no prior-year-election input; the part-3a positive-liability reading of "subject to tax under section 1411" is accepted and labeled.
  - *Part 1 as built (2026-09-27; items 1 and 6 — items 2-5 remain):* `PriorFilings.return_forms` (only `year-1` is read: `1040`/`dual_status` True, `1040-NR` False, `not_filed`/`1040_with_6013_election` unknown, the latter a labeled judgment); `classify(..., prior_year_resident)` — True + SPT met is resident from Jan 1 (arrival triggers and First-Year Choice pointers suppressed, departure note kept), True + SPT not met stays nonresident behind a first CONTRADICTION reason, never "definitive", and is never a certain nonresident; threaded through estimate/intake (taxpayer only; the spouse has no prior-filings fact) and the residency tool; intake asks `prior_filings.return_form`, the worksheet maps onto the five values; the estimate puts a CONTRADICTION or "may be WRONG" reason first and brackets the full-year resident reading (the spouse's may-flip brackets the spouse-resident MFS pair); a recorded prior 1040 the timeline makes impossible (a fully exempt prior year) gets a first CHECK THE PRIOR-YEAR RETURN judgment; only the start of the year is settled (a departure caveat names IRC 7701(b)(2)(B)). Deferred from its verify: a prior `dual_status` DEPARTURE return followed by residency again (Treas. Reg. 301.7701(b)-4(e)(2): a possible prior-year amendment), the departure note's 10-day de minimis and foreign-tax-home wording, `section_6013_kind` reading `return_forms` (a prior election return separates a continuing 6013(g) from a new 6013(h)) — all to part 2/3.
  - *Part 2 as built (2026-09-27; items 2 and 3 — items 4-5 remain):* a `dual_status_candidate` with no election prices Pub 519 ch. 6's restrictions for the POINT (`_bottom_line(dual_status=True)`: itemized or $0, never the standard deduction; no EITC (IRC 32(c)(1)(D)), no AOTC/LLC (25A(g)(7)); MFS rates married, single unmarried — a labeled inference; the preferential rates and NIIT kept, disclosed as a whole-year snapshot whose NIIT may be overstated, Treas. Reg. 1.1411-2(a)(2)(ii)); the RANGE adds the full-year-resident figure only where a route is open (`_dual_status_routes`: the prior-year fact not recorded '1040-NR', or the election open to a married filer — closed by a recorded decline; wrong timeline dates is always named, never opens it alone), so an unmarried filer with a prior 1040-NR gets the point alone; `_DUAL_STATUS_CAVEAT` is now `_dual_status_caveat` (point, approximation, range and route); no "Standard deduction assumed" on a dual-status figure; the EITC/education disclosures name what the resident figure claims; the roadmap step names the credit bars. Item 3: `IncomeSnapshot.bank_deposit_interest_nonresident_period` (a validated subset of `bank_deposit_interest`, summed in `combined_with_spouse`) is the only deposit interest excluded on a dual-status payee's return (IRC 871(i)(1)-(3), Treas. Reg. 1.871-13(a)(1); the spouse's separate return by the spouse's own year, JF5a's assumed-nonresident reading included) and is out of NII; `_dual_deposit_note` names the dollars excluded and taxed or, with no split, the amount taxed in full and what to record (us_person False or unanswered; the old "not established" note speaks only for an unclassified filer); intake asks `interest_character` of a dual-status owner and `income_documents.interest_period`; P-013 rule (f) and P-018 extended; HEAD-vs-tree battery of 39 profiles: every non-dual-status figure byte-identical, all 17 dual-status differences matched an independent calc recomputation. Not done here: a dual-status SPOUSE's separate return still prices resident rules for the point (nonresident in the range) — only its deposit interest splits. Deferred from its verify: a dual-status SPOUSE's own separate return is still priced on resident rules at the point (only its deposit interest splits) → part 3; route (ii)'s range end is the same status under resident rules, not the joint election figure → part 3 (item 5); a prior `1040_with_6013_election` as a continuing 6013(g) election → part 3; the compare walk's third subset/parent pair (`bank_deposit_interest_nonresident_period`) → JF1b.6; the spouse-field coverage test over list/Optional fields → JF1b.5; a confirmed head of household on a dual-status year priced as given → JF1b.12.
  - *Part 3a as built (2026-09-27; item 4 — item 5 and the part-2 deferrals remain for part 3b):* with a spouse snapshot every election figure prices the Treas. Reg. 1.1411-2(a)(2)(iii)(A)/(iv)(A) NIIT default (`estimate._price_niit`: each spouse's own snapshot under the MFS rules against $125,000; `_bottom_line(niit_override=…)`): 6013(g) — the joint point uses the default (the U.S. spouse's own NIIT, $0 for the spouse who is a nonresident without the election; a dual-status U.S. spouse bounded from $0) and the range adds the combined-income figure only when that default is above $0 (else the note says the second election is not available, (iii)(B)(2)/(B)(3)); 6013(h) — point min(combined, both full-year own figures), range min(combined, the other spouse's own), the i8960 first-year sentence dropped; 'either' (and a 6013(g) couple the facts cannot tell apart) — the combined figure stays, every reading in the range, the note names the fact that settles it; separate returns under the election price the nonresident spouse at NIIT $0 with the resident-rules figure in the range; no spouse snapshot — figures unchanged, the note names `income.spouse`; P-018, server doc and SKILL.md carry it; tests `test_p018_niit_default_*` (Examples A-D, each against independent `calc.niit` calls); HEAD-vs-tree battery of 27 profiles: all 15 without an election figure (or without a spouse snapshot or investment income) byte-identical in figures, all 12 election differences matched an independent recomputation. Deviation from the brief's test list: Example C's $1,292 is not in the 6013(h) range — the couple takes the lower (the orchestrator's min rule). Verify fixes: no default for a couple with no nonresident or arriving spouse on their own facts (a U.S. person or full-year resident never takes the (iii)/(iv) role); the pricing gate reads the priced NIIT amounts (a capped capital loss); the not-available text says the second election cannot be MADE this year and names a continuing earlier one. Accepted: the MFJ candidate of a citizen with a spouse who is nonresident on their own facts (no recorded election) is an election figure and takes the default. Deferred: a dual-status U.S. spouse's own separate-return NIIT under 6013(g) (part 3b); compare_scenarios outcomes carry no NIIT note (the figures use the default); a tie where one spouse is a certain nonresident; the positive-liability reading of "subject to tax under section 1411" is labeled.
  - *Part 3b as built (2026-09-27; item 5 and the part-2 deferrals — JF5b done):* (5a) a married taxpayer whose own no-election residency is nonresident or dual-status, with no status confirmed, no answer recorded and the election not unavailable (IRC 6013(g)(3)), keeps married-filing-jointly as a CANDIDATE (`_candidate_statuses(election_candidate=True)`) priced on resident rules for both spouses (`_outcome` forces `self_nra`/`self_dual` False) and treated as an election figure (NIIT default, deposit, FICA and NIIT notes worded as a candidate); the kind reads a no-answer candidate as a NEW choice (a dual-status arrival year with a U.S. spouse is 6013(h)); `_section_6013_candidate_caveat` names the precondition as not settled — with `household.spouse.us_person` and the spouse's visa timeline and days — when the spouse's residency is not on file; MFS stays the primary; the symmetry test swaps roles and incomes. (5b) the dual-status caveat's route (ii) is the joint candidate; the same status under resident rules stays in the range only through route (i) (`_DualRoutes.resident_figure_open`). (5c) a dual-status SPOUSE's own separate return is priced under ch. 6 at the point (`_mfs_pair(spouse_dual=…)`, the recorded decline's assumed reading included, and inside a head-of-household figure), the range pricing it for the whole year under resident rules (all deposit interest taxed) and under Form 1040-NR rules. (5d) `residency.section_6013_kind(prior_year_election=True)` is 'g' (IRC 6013(g)(3); 6013(h)(2)) in the estimator and intake; a continuing 6013(g) whose nonresident spouse arrives this year prices that spouse's NIIT from $0 to the full-year figure ((iv)(A)'s facts, a reading); with that prior-year return and no answer the election is NOT applied — `residency.prior_year_election_continues` is an assumption, a what-would-change-it entry and an intake note, and intake asks `household.section_6013_election` (the spouse battery's copy suppressed). (5e) HEAD-vs-tree battery of 41 profiles: all 25 outside 5a-5d byte-identical in figures (one reverse-couple NIIT note reworded as the candidate's), all 14 figure changes matched an independent calc recomputation, 2 more changed text only.
  1. **Prior-year residency fact** [DEF-14 + LD-11].
     - There is no structured prior-year-residency fact:
       - PriorFilings (schemas/profile.py:469-495) stores only filed_years;
       - `residency.classify` (residency.py:835-841) has no prior-year input; the rule is only prose (residency.py:1015-1016);
       - the onboarding worksheet asks the question (worksheet.py:175, :343), but nothing stores the answer.
     - Result, reproduced: a truncated F-1 history returns "This nonresident answer is definitive" for a filer who filed the prior year's Form 1040, and the standard deduction is dropped.
     - The law:
       - IRC 7701(b)(2)(A)(i) applies the partial-year rule only to an alien who "was not a resident of the United States at any time during the preceding calendar year";
       - Pub 519 ch. 1: such a filer "will be considered a U.S. resident at the beginning of the current year".
     - Build:
       - `PriorFilings.return_forms: dict[int, Answer[Literal['1040','1040-NR','dual_status','1040_with_6013_election','not_filed']]]`, with an intake question for us_person=False (the worksheet answers map here);
       - `classify(..., prior_year_resident: bool | None)`: True with the SPT met → resident from Jan 1, dual-status triggers suppressed. True with the SPT not met on the given timeline → a first-position CONTRADICTION reason, never "definitive": the timeline is probably incomplete, or the prior return may be on the wrong form (labeled judgment);
       - thread it through `estimate._classify_residency` and `intake._residency_classification`.
  2. **Price the dual-status risk** [DEF-15 + LD-11(c)]. A dual-status candidate takes the resident branch (estimate.py:1616 → :1229-1236) and gets the full standard deduction, while `_DUAL_STATUS_CAVEAT` (:759-766) says "NO standard deduction".
     - Low end: deduction forced to itemized or 0, MFJ/HOH dropped.
     - High end: the full-year-resident figure.
     - Reword the caveat to point at the range.
  3. **Dual-status deposit interest** [PJ-11; law unverified]. In a dual-status year, nonresident-period deposit interest gets neither the N-8 exclusion nor a disclosure (estimate.py:1701). Read Pub 519 ch. 6 first. At minimum ship a disclosure naming the amount; ship the exclusion only if the reading supports it.
  4. **NIIT default under the §6013 election** (found by JF5a's second adversarial verify, 2026-09-26: the law and edge lenses). Under the election the joint figure's NIIT assumes the optional chapter-2A election; the default is never priced. Treas. Reg. 1.1411-2(a)(2)(iii)(A) (6013(g)) / (iv)(A) (6013(h)): the spouses are "treated as married filing separately for purposes of section 1411" and under (iii) "the nonresident alien spouse will not be subject to tax under section 1411" ((iv): subject only on the resident-period income). (iii)(B)(2): the second election must be made "for the first taxable year beginning after December 31, 2013, in which the United States taxpayer is subject to tax under section 1411", judged "without regard to the effect of the section 6013(g) election".
     - Build: price the default (the U.S. spouse's own NII and MAGI against the MFS threshold; the nonresident spouse at $0 under (iii), resident-period income only under (iv)) on the joint AND the separate figures under the election, and bracket it with the elected figure in the range; say when the second election is not yet available.
     - JF5a ships only the note (estimate._section_6013_niit_note: the joint figure ASSUMES the second election; the default may be higher or lower; when it is available).
  5. **The election as a candidate for a nonresident TAXPAYER** (found by JF5a's third adversarial verify, 2026-09-26: the acceptance lens). With no recorded election and no confirmed status, a nonresident taxpayer married to a U.S. citizen gets MFS only (1040-NR), while the reverse couple (citizen taxpayer, nonresident spouse) gets MFJ as a candidate with the §6013 caveat. Price the election-MFJ figure as a candidate for the nonresident taxpayer too (resident rules, the (g)/(h) text by kind), with the same caveat, so both directions of the couple see the choice. When the precondition cannot be judged because the spouse's residency is not on file, the caveat should say so and name what to record.
  6. **A nonresident answer that may flip, on the pricing path** (found by JF5a's fourth adversarial verify, 2026-09-27: the trust lens; pre-existing). When the taxpayer's or the spouse's 'nonresident' answer rests on a missing lookback year that could flip it (`ClassificationResult.nonresident_may_flip`), estimate_refund prices Form 1040-NR rules with no sign of classify's "may be WRONG" warning. Surface that warning in the estimate (and on the spouse's separate return), and bracket the resident reading in the range.
  - **Acceptance.**
    - Truncated F-1 history + prior 1040 → not definitive; CONTRADICTION reason first.
    - Full history + prior 1040 → resident, no dual-status flag, standard deduction applied, `_fica_exemption_note` suppressed.
    - H-1B arrival 2026-03-01 (306 days) → the low end has deduction 0, the high end the standard deduction, and the assumption names the range.
    - Dual-status + `bank_deposit_interest > 0` → a disclosure naming the amount.
    - Citing tests for the residency-facts pitfall.

- [x] **JF1b — Small logic fixes — DONE 2026-09-27** (S–M; deps J0)
  - *Part A as built (2026-09-27; items 13 and 1-8 — items 9-12 are part B):* 13 the filler refuses 'NRA' on every SSN/comb line and names the pack's MFS entry-space line (pitfall P-026; verify keeps the literal on every SSN/comb line); 1 magi_ladder's 8959/NIIT rows read the raw status via `_surtax_threshold` (QSS $200,000 / $250,000); 2 the §6013 conditional caveat needs a married household (an unmarried visa filer gets a no-§6013 1040-NR caveat; the dual-status caveat names the election only on a marriage); 3 the passport's why follows the classification, tax_year threaded; 4 `ira_contribution_eligibility(roth_ira_dec31_value=)` applies the IRC 4973(a) cap and the work names the 408(d)(4) / Form 4868 / 301.9100-2 deadlines; 5 a structural IncomeSnapshot joint-view test; 6 `estimate.INCOME_LINKED_FIELDS` groups the walk's subset/parent (and dependent-care) overrides into one step; 7 no recount warning (and 'definitive' only) when the SPT's maximum countable total is under 183 or the current-year span under 31; 8 the partner note quotes the §6013 precondition. Open from part A: the traditional_deduction path still books a contribution over the phased-out DEDUCTION as a 4973 excess (IRC 4973(b) computes it "without regard to section 219(g)").
  - *Part B as built (2026-09-27; items 9-12):* 9 the year of a spouse's death is a married year for filing status (`_married_for_year`, Pub 501: "considered married for the whole year for filing status purposes") — MFJ/MFS candidates, the spouse snapshot on the joint figure, the election's marriage gate and the joint-route wording ("IF the choice is open in the year of your spouse's death"); 10 head of household is a CANDIDATE for a citizen or resident whose spouse is, or may be, a nonresident alien with no election recorded and none declined (Pub 501, Considered Unmarried), priced on the nonresident-spouse route (a spouse of unknown residency read as the nonresident it needs; the note says it exists only without the election), and that route's return carries `_bottom_line(married_7703=True)` — IRC 2(b)(2)(B) applies "For purposes of this subsection", so no education credit (25A(g)(6); the 2025 Form 8863 instructions' "You (or your spouse) were a nonresident alien"), no dependent care credit (21(e)(2)), no student loan interest deduction (221(e)(2)-(3)), the $1,500 capital-loss limit (1211(b)(1); Treas. Reg. 1.1211-1(b)(7)(i); Pub 550 "$1,500 if you are married and file a separate return"), no PTC (36B(c)(1)(C); the 8962 instructions' Exception 1 is the living-apart head of household only), the $125,000 NIIT (Treas. Reg. 1.1411-2(a)(2)(iii)(A)) and Additional Medicare (3101(b)(2)(B)) thresholds, and a $0 Social Security base amount (86(c)(1)(C), the MFS candidate's lived-together assumption), one assumption quoting each rule that changed the figure; intake's married filing-status question names head of household on the citizen side; 11 the IRC 3121(b)(19) FICA withheld-in-error note is built per person (the spouse's own snapshot and no-election classification) and only for an F/J/M/Q period overlapping the year; 12 a confirmed head of household of a nonresident (Pub 519 ch. 5) or dual-status (ch. 6: "You cannot use the head of household Tax Table column") filer is priced as the status the filer can use — married filing separately if married, else single — with the caveat naming the swap, compare_scenarios' note the same, and intake quoting the ch. 6 bar on a dual-status year. Pitfall P-018 extended. Deferred → JF2.5: the lived-apart route's capital-loss limit, the unrecorded lived-apart-all-year fact for IRC 86(c)(1)(C), and the separated-spouse EITC rule on the nonresident-spouse route.
  1. **QSS threshold** [DEF-11]. magi_ladder applies the MFJ-aliased $250,000 Form 8959 threshold to QSS (calc.py:4175-4182 via `_resolve_filing_status`); Form 8959 line 5 and knowledge/federal/2025.yaml:168 say $200,000. Use `_surtax_threshold` with the raw status, and move the NIIT row onto the same helper.
  2. **§6013 caveat gate** [DEF-16]. The §6013(g)/(h) caveat fires for unmarried single visa holders (estimate.py:2288-2302). Gate it on `_is_married`, and suppress it once JF5b's prior-year fact plus the SPT settle residency.
  3. **Document checklist wording** [DEF-19]. `_required_documents` frames every us_person=False filer as "a nonresident return", computed residents included (intake.py:1187-1204). Gate it on the residency classification and thread `tax_year` through.
  4. **Excess-contribution excise** [RC-11]. The excise ignores the IRC 4973(a) cap: it "shall not exceed 6 percent of the value of the account … (determined as of the close of the taxable year)" (Form 5329 line 25; calc.py:3855, :3884). The remedy text (calc.py:3901-3905) names no date. Add `roth_ira_dec31_value`, and name the deadlines: April 15 of year+1, or Oct 15 with an extension or via §301.9100-2 for a timely-filed return. JR2c adds the op pointer.
  5. **Spouse-field coverage** [LD-10]. combined_with_spouse lists its 18 summed fields by hand (estimate.py:239-247) with no structural test, and N-8 already had to add one by hand. Add a test over `IncomeSnapshot.model_fields`, with the household-level exclusions explicit, that fails naming any missing field.
  6. **Scenario walk vs subset validators** (J0 re-verify). compare_scenarios' one-override-at-a-time input walk raises a ValidationError at an intermediate step when a parent drops below its subset (`interest` before `bank_deposit_interest`, `dividends` before `qualified_dividends`). Apply subset/parent pairs together in the walk, and test both orders.
  7. **Residency: no recount warning on a capped count** (found 2026-09-24 by a verifier pass). When the non-exempt span caps the weighted SPT total below 183 (a cap-exempt H-1B from July 15 after an F-1: at most 170 countable days), `residency.classify` calls the nonresident answer "definitive" AND warns that the total "is close to the 183-day threshold — recount days present". No recount can raise a capped count; skip the warning when the count equals the non-exempt span and the answer is definitive.
  8. **Intake §6013 wording** (same pass). The unmarried-partner note in intake.py says a nonresident spouse joins a joint return "only via the §6013(g)/(h) election" without the election's precondition: one spouse must be a U.S. citizen or resident at year end (g), or become resident during the year (h); two NRAs who both stay nonresident cannot elect. Add the condition.
  9. **Year of a spouse's death: candidate statuses** (found by JF5a's second adversarial verify, 2026-09-26: the edge lens). Pub 501: "If your spouse died during the year, you are considered married for the whole year for filing status purposes." `_candidate_statuses` (widowed branch) offers only 'single' in the year of death and `spouse_split` uses `_is_married`, so the deceased spouse's snapshot is dropped from a joint figure. Build: thread `_married_for_year` into `_candidate_statuses` (MFJ/MFS in the year of death) and into `spouse_split`. JF5a only refuses the §6013 election on that 'single' figure and says why (estimate._election_not_applied_reason). When MFJ/MFS become candidates in the year of death, remove the `status is None` guards in `estimate._election_marriage_ok` and `intake._election_in_effect` together, so intake and the estimate keep one marriage rule.
  10. **Considered-unmarried head of household without a recorded decline** (found by JF5a's third adversarial verify, 2026-09-26: the regression lens). Pub 501, Considered Unmarried: "You are considered unmarried for head of household purposes if your spouse was a nonresident alien at any time during the year and you don't choose to treat your nonresident spouse as a resident alien." `_candidate_statuses` offers HOH to a citizen or resident with a nonresident spouse only after a recorded decline (JF5a); with the election unanswered and a qualifying person, HOH is never a candidate. Add it (priced as that return plus the spouse's separate one, as the no-joint path does), conditional on not electing. The same pass found the rest of the nonresident-spouse route's "married under IRC 7703" class, which JF5a gates only for the EITC: IRC 2(b)(2)(B) applies "for purposes of this subsection", so the HOH return still gets the AOTC/LLC (25A(g)(6)), the dependent care credit (21(e)(2)), the student loan interest deduction (221(e)(2)), the $3,000 capital-loss limit (1211(b): $1,500 for a married individual filing separately), the PTC (36B) and the $200,000 NIIT/Additional Medicare thresholds (Treas. Reg. 1.1411-2(a)(2)(iii)(A) and IRC 3101(b)(2)(B) set the married-filing-separately amounts). Carry one married-under-7703 flag on that return and gate each item, with a test per item.
  11. **FICA withheld in error on the SPOUSE** (same pass, the acceptance lens). estimate.py builds the IRC 3121(b)(19) withheld-in-error note from the taxpayer's `ss_withheld_by_employer` only; an F/J spouse's box-4 withholding gets no note, under the election or on the spouse's own 1040-NR. Build the note per person from each snapshot, keyed on that person's no-election classification.
  12. **A nonresident alien's confirmed head of household** (found by JF5a's fourth adversarial verify, 2026-09-27: the unavailable and regression lenses; pre-existing). Pub 519 ch. 5: "You cannot file as head of household if you are a nonresident alien at any time during the tax year." A confirmed head_of_household for a nonresident taxpayer is priced as given (HOH rates on Form 1040-NR). JF5a says so in the residency caveat and keeps such a scenario out of compare_scenarios' `recommended`; price the status the filer can use instead (married filing separately, or single), and let intake stop offering HOH on that path.
  13. **FILING-WRONG: the 'NRA' literal lands in the spouse-SSN box** (found by JF5a's fifth adversarial verify, 2026-09-27; pre-existing). The Instructions for Form 1040 (2023 and 2024: "If your spouse doesn't have and isn't required to have an SSN or ITIN, enter 'NRA' in the entry space below the filing status checkboxes"; 2025: "enter 'NRA' in the entry space") and Pub 501 put it in the MFS entry space, and "Be sure to enter your spouse's SSN or ITIN in the space for spouse's SSN" governs the SSN box. filler.py accepts 'NRA' on the spouse identifying-number comb (other `ssn_digits_only` and comb lines refuse it; plain text lines take it; the name match in `_accepts_nra` also admits `26.former_spouse_ssn` on the 2025 pack), and its acceptance comment and refusal text cite the instructions for that box (test_filler.py encodes it). Route the literal to the MFS entry space (`filing_status.spouse_or_qualifying_person_name` on the 2023/2024 packs, `filing_status.mfs_spouse_name` on 2025), leave the SSN comb blank, fix the comment and refusal text, and add tests filling 'NRA' into each year's entry-space key and refusing it on `26.former_spouse_ssn` (JF5a already corrected SKILL.md's wording and names this item).
  - **Acceptance.**
    - `magi_ladder(240000, QSS, 2025, wages=240000)` → the 8959 row shows $200,000, 'above'.
    - An unmarried single visa holder → no "6013" in assumptions or `what_would_change_it`; married with no residency facts → still present.
    - A resident F-1 profile → no "nonresident return" text.
    - A Dec-31 value below the excess → excise = 6% × value.
    - F-1 2022-08-18 → 2025-07-14 then H-1B 2025-07-15, TY2025 → 'nonresident', definitive, and no "recount" reason.
    - The intake unmarried-partner note names the §6013(g)/(h) precondition.
    - The spouse-field test fails when a field is dropped from the list.

- [x] **JF2 — Wrong-law routing and document notes — DONE 2026-09-27** (M; deps J0)
  - *As built (2026-09-27):* 1 eight topics in knowledge/sources.yaml — `ira_recharacterization_and_excess_contributions` (Treas. Reg. 1.408A-5, 1.408-11, 301.9100-2; IRC 408A(d)(6)-(7), 408(d)(4), 4973, 72(t)(2)(A)(ix); Pub 590-A; i5329; Form 5498 box 4), `form_1099r_distribution_codes`, `payroll_withholding` (Pub 15 section 7, Pub 15-T, Form W-4, Treas. Reg. 31.3402(g)-1), `wage_reporting_w2`, `excess_deferrals_402g` (IRC 402(g), Treas. Reg. 1.402(g)-1(e), Pub 525), `charitable_nonitemizer` (IRC 170(p), 170(b)(1)(I), the W-4 (2026) Deductions Worksheet, the TEOS deductibility-codes page — TEOS itself refuses scripted clients), `wage_repayment_claim_of_right` (Pub 525 Repayments, IRC 1341, Pub 15 section 13), `underpayment_penalty` (IRC 6654, i2210, Form 2210) — every URL fetched and every quote checked verbatim by script (the eCFR sections through its renderer API); Pub 526's membership-benefit rules on itemized_charitable; the J0 follow-up both ways (Pub 550 interest sentences on investment_income; the fdap text drops the "interest income" heading and names the 1099-INT/1042-S, "NRA interest" and "bank interest"); a HEAD-vs-tree sweep over 240 queries found and removed eight new wrong pointers the first drafts made ("401k contribution limit", "IRA contribution limit", "amended return" — now Form 1040-X on filing_basics — "estimated tax payments", "where to file", "early distribution penalty", "tips deduction", "charitable contributions"); 2 the 1099-R DocSpec reads the 2026 face (`BoxSpec.aliases`: 7a→7, 7b→7_ira_sep_simple, 8a→8, resolved before the unexpected check; two different readings of one box are invalid) with boxes 3, 5, 6, 7c, 7d, 8b, 9a, 9b, 10-19, payer name and account number, and a status note on the relabel and the recipient box-2b sentence; 3 the 1099-DIV DocSpec has boxes 5 and 12 and a status note (Pub 550 money market funds, IRC 871(k)(1)(A)/(C)(i) — a caller fact), the `interest`/`dividends` field notes, 871(k) in nonresident_fdap, pitfall P-013 rule (g); 4 nonresident_spouse_election says where each statement goes (6013(g): the first joint return, none in a later year; 6013(h): the year of the choice); 5 (a) the lived-apart head of household is capped at $1,500 too (IRC 1211(b)(1) does not refer to section 7703; Pub 501: "not for other purposes"), (b) `household.spouses_lived_apart_all_year` (IRC 86(c)(1)(C)(ii)) prices the $25,000 base amount on every separate return and intake asks it of a married separate filer with an SSA-1099. Deferred: (c) the separated-spouse EITC rule → Not scheduled (below).
  1. **Wrong-law pointers** [RC-10 + LD-03]. get_sources hands out confident wrong-law pointers (the P-005/P-006 class). Reproduced 2026-09-23:

     | Query | Routes to |
     |---|---|
     | "net income attributable" | self_employment |
     | "1099-R box 7 code N"; "Form 5498 box 4" | foreign_tax_credit |
     | "Treas. Reg. 1.408A-5" | FBAR |
     | "supplemental wage withholding bonus" | deadlines |
     | "paycheck withholding W-4 percentage method" | foreign_tax_credit |
     | "Publication 15-T" | FBAR |
     | "paystub W-2 box 1 box 3 box 5" | ira_basis_and_roth_conversions |

     Clean misses: recharacterization, Form 5329, excess deferrals, the non-itemizer charitable deduction, charitable membership benefits, wage repayment (claim of right).

     New topics (fetch every URL before authoring):
     - `ira_recharacterization_and_excess_contributions`: eCFR 1.408A-5, 1.408-11, 301.9100-2; IRC 408A(d)(6)-(7), 408(d)(4), 4973(a)/(f), 72(t)(2)(A)(ix); Pub 590-A; i8606; i5329.
     - `form_1099r_distribution_codes`: i1099r Table 1 and the box 7a cautions; the f1099r recipient text.
     - `payroll_withholding`: Pub 15, Pub 15-T, Form W-4 (2026), eCFR 31.3402(g)-1.
     - `wage_reporting_w2`: iw2w3 (2026).
     - `excess_deferrals_402g`.
     - `charitable_nonitemizer`: IRC 170(p) and 170(b)(1)(I), the W-4 (2026) Deductions Worksheet, the TEOS deductibility-codes page. One topic, which also serves TY2026.
     - `wage_repayment_claim_of_right`: Pub 525 Repayments, Pub 15 §13.
     - `underpayment_penalty`: IRC 6654, Form 2210 and its instructions, Pub 505.

     Keep the answers text free of tokens that pull toward neighbouring topics.
     - **J0 re-verify follow-up:** resident-generic interest queries ("interest income", "savings bond interest", "certificate of deposit", "deposit interest") now land on `nonresident_fdap`, and "1099-INT nonresident" / "nonresident alien bank interest" / "NRA interest" still route wrong. Add a verified Pub 550 interest sentence to `investment_income` and routing tests both ways (resident queries → investment_income; the three P-013 queries stay on nonresident_fdap).
  2. **1099-R 2026 layout** [RC-04 = TY26-23]. The 1099-R DocSpec is the 2025 layout: a 2026 form read with its own labels gives gaps ['7'] and unexpected ['5', '7a', '7b'] (extract.py:252-266). Box 5 is missing, although server.py:443 tells agents to pass it.
     - Add `BoxSpec.aliases` (7a→7, 7b→7_ira_sep_simple, 8a→8), resolved before the unexpected-key check.
     - Add boxes 3, 5, 6, 7c, 7d, 8, 8b, 9a, 9b, 10, 11 and 12–19, plus payer name and account number.
     - Add a status note with the 2026 relabel and the recipient box-2b sentence.
  3. **Fund payouts are dividends** [LD-15]. Pub 550: money-market fund amounts "should be reported as dividends, not as interest". For an NRA, IRC 871(k)(1)(A) exempts interest-related dividends from a RIC.
     - The 1099-DIV DocSpec (extract.py:159-173) has no status note and no boxes 5 or 12. Add both.
     - Add estimator field notes on `dividends` / `interest`.
     - Add the 871(k) URL to `nonresident_fdap` and extend P-013. Whether a given fund pays such dividends is a caller fact.
  4. **Nonresident-spouse source wording** (found by JF5a's second adversarial verify, 2026-09-26: the surface lens). knowledge/sources.yaml's nonresident-spouse `answers` text describes making the election only in 6013(g) terms ("signed statement by BOTH spouses attached to the first joint return"); the 6013(h) statement goes on "your joint return for the year of the choice" (Pub 519 ch. 1), and a later year of a continuing 6013(g) election attaches none. Reword the routing text for both choices, and check the neighbouring topics' answers are not captured by the new words (the neighbour-theft companion bug).
  5. **A married head of household's other married-separately rules** (JF1b part B deferrals, 2026-09-27). (a) The lived-apart route keeps the $3,000 capital-loss limit, but IRC 1211(b)(1) ("$1,500 in the case of a married individual filing a separate return") does not refer to section 7703, so 7703(b) does not unmarry that filer; Treas. Reg. 1.1211-1(b)(7)(i) reads "a husband or a wife who files a separate return", Pub 550 "$1,500 if you are married and file a separate return", and the Schedule D instructions "($1,500 if married filing separately)" — read Pub 501 and the 1040 instructions for the lived-apart head of household, decide the route's limit, and test it. (b) IRC 86(c)(1)(C) needs whether the spouses lived apart "at all times during the taxable year"; the fact is not recorded, so the MFS candidate and the nonresident-spouse head of household both price a $0 base amount — record it (a household fact, asked of a married separate filer with Social Security benefits) and price the $25,000 base amount when they lived apart all year. (c) The separated-spouse EITC rule (IRC 32(d)(2)(B)) on the nonresident-spouse route is still not modeled (disclosed).
  - **Acceptance.**
    - Each query above routes to its own topic.
    - Bidirectional neighbour-theft tests re-run the canonical queries of self_employment, foreign_tax_credit, FBAR, ira_basis_and_roth_conversions, deadlines, estimated_tax, contribution_limits, NIIT and HSA (e.g. "1099-DIV box 7" → foreign_tax_credit; "Form 8606" → ira_basis_and_roth_conversions).
    - A 2026 1099-R read with 7a/7b resolves with no gap; box 5 is a known box.
    - A 1099-DIV extraction carries the new note.

- [x] **JF3 — W-2 boxes 3/5/6 reach the estimator — DONE 2026-09-27** (M; deps JF6a, JF1b) — pitfall *box1-standin* (P-019)
  - *As built:* `IncomeSnapshot.medicare_wages` (box 5), `ss_wages` (boxes 3 + 7) and `medicare_tax_withheld` (box 6 per employer; needs box 5 — validator, and INCOME_LINKED_FIELDS moves the pair as one compare-walk step); None/empty means box 1 stands in, disclosed. Form 8959 prices box 5 (an exempt F/J student's $0 included); each person's Schedule SE subtracts its own boxes 3 + 7 (`_bottom_line(se_ss_wages=)`); the withholding reconciliation credits box 6 less the pack's employee Medicare rate x box 5 over the people who gave box 6 (a spouse with none never shrinks it) on the operand slot `additional_medicare_withholding`, labeled through form_line (`f8959.withholding_part`, `f1040.additional_medicare_withholding`); `_addmed_box_note` fires with the tax, with box 6, or when box 1 stood in and box 1 plus the year's 402(g) limit reaches the lowest threshold priced; the Schedule SE note only when box 1 stood in; the joint view sums each box with box 1 standing in for a spouse who gave none; compare_scenarios names a scenario that moves wages but not boxes 3/5; the estimate_refund docstring lists the fields. Deferred → Not scheduled: the 2019-2024 packs carry no employee Medicare rate and no 402(g) limit, so there the box-6 credit says NOT ESTIMATED and the stand-in note keys only on a priced Form 8959.
  1. **Box 5 for Form 8959** [DEF-01].
     - Form 8959 is priced on Box 1 (estimate.py:1430-1432), and IncomeSnapshot has no Box 5 field (extra='forbid').
     - The Box-1-for-Box-5 caveat (estimate.py:1909-1915) appears only when 8959 already computes a non-zero amount. So a 401(k) deferrer with Box 1 under the threshold and Box 5 over it loses the 0.9% silently. In the other direction, exempt F-1 wages are overstated.
     - The draft 2026 Form 8959 line 1 reads "Medicare wages and tips from Form W-2, box 5".
     - Add `medicare_wages`.
     - Record an `addmed_box1_fallback` note when wages plus the year's 402(g) limit reaches the threshold, and let the caveat fire even when 8959 computes $0.
     - The SE Part IV threshold reduction (calc.py:795) takes the Box 5 total.
     - `scenarios._apply_overrides` warns when `wages` changes but boxes 3/5 do not.
  2. **Box 3 for Schedule SE** [DEF-02]. Schedule SE is fed Box 1 (estimate.py:1111-1115, :1674-1677); the draft 2026 Schedule SE line 8a says "total of boxes 3 and 7". Add a per-person `ss_wages`, with the line label from `form_line`.
  3. **Box 6 withholding credit** [DEF-03 + LD-16]. With no box-6 input, Additional Medicare Tax withheld never credits.
     - Add `medicare_tax_withheld: list[int]`, one entry per employer.
     - Part V line 22 = max(0, Σ box 6 − 1.45% × Box 5), with the rate taken from the pack.
     - New operand slot `additional_medicare_withholding`, labeled from `form_line` (8959 Part V → the 1040 other-withholding line).
     - A validator requires `medicare_wages` whenever box 6 is given.
  - **Files.** estimate.py, scenarios.py, server.py (estimate_refund docstring :826-835), pitfalls.yaml, test_estimate.py, test_estimate_ledger.py.
  - **Acceptance** (*illustrative* figures).
    - MFJ 2026, wages 240,000, medicare_wages 262,000 → an `additional_medicare_tax` slot of 108 (0.9% × (262,000 − 250,000)); the point estimate is 108 lower.
    - Same snapshot without medicare_wages → a "box 5" assumption, even with no 8959 line.
    - F-1 exempt: medicare_wages 0, wages 250,000 → no 8959 line.
    - SE: se_net 50,000, wages 170,000, ss_wages 184,500 (2026) → SE social-security portion 0.
    - One employer: box 5 260,000, box 6 4,310 → withholding slot −540.
    - The 240-profile ledger property suite and the spouse-field test stay green; the pitfall has a citing test.

- [x] **JF4 — FICA tiers and the safe harbor read the right box — DONE 2026-09-27** (M; deps JF3)
  - *As built:* 1 `calc._payroll_boxes` gives marginal_dollar_savings, hsa_deduction and magi_ladder person-level `ss_wages` (boxes 3 + 7, against the wage base) and `medicare_wages` (box 5, against the 0.9% threshold); the one-figure `wages` stays as a deprecated alias that stands in for both and says so; marginal_dollar_savings keys the 0.9% on the filing-status Form 8959 threshold (it already did) and now on box 5; hsa_deduction gains `filing_status` — with it the tier is the Form 8959 TAX threshold, without it the old status-blind withholding threshold, still named an upper bound; magi_ladder's 8959 row measures `medicare_wages`. 2 estimated_tax_safe_harbor takes `excess_ss_credit` (withholding, IRC 31(b)(1)), `refundable_credits` (off the tax, 6654(f)(4)) and `additional_medicare_withheld` (off the tax, 6654(m) "to the extent not withheld"), and `prior_year_refundable_credits` (off the prior-year tax — the 2025 Instructions for Form 2210: "subtract from that total amount the refundable credits"), quotes 6654(g)(1)'s ratable deeming (a late W-4 bump covers earlier installments, a late 1040-ES payment does not), and names the prior-year lines through form_line — the new registry keys `f1040.agi` (8b in 2019, 11 in 2020-2024, 11a from 2025) and `f1040.total_tax` (16, then 24, 24a on the 2026 draft), each read off its face 2026-09-27; the old text told a 2026 filer to read line 11 of a 2025 return whose AGI is line 11a. `estimate.safe_harbor_inputs_from_estimate` reads the inputs off an estimate's ledger. The intake / profile / server prior-year line literals stay for JF6c.
  1. **Shared tier helper** [DEF-10]. marginal_dollar_savings, hsa_deduction and magi_ladder take an unspecified `wages` (calc.py:3948, :4008-4033, :5448, :5815-5863, :4112, :4175-4182). Box 1 picks the wrong tier by up to 6.2% / 0.9% per dollar, and hsa_deduction prices the liability on the status-blind withholding threshold (:5830).
     - Add `_payroll_fica_tier(ss_wages, medicare_wages, filing_status, year)` with person-level totals, and new kwargs.
     - Keep `wages` as a deprecated alias, with a disclosure of which box it assumed.
  2. **Safe-harbor inputs** [DEF-12 + LD-14]. estimated_tax_safe_harbor (calc.py:3405-3435; server.py:386-392) omits four statutory facts:
     - the excess-SS credit is "considered an amount withheld at source" (IRC 31(b)(1));
     - a §31 credit is deemed paid with "an equal part … deemed paid on each due date" (§6654(g)(1));
     - `tax` is net of non-§31 refundable credits (§6654(f)(4));
     - Additional Medicare Tax is included only "to the extent not withheld" (§6654(m)).
     
     Changes:
     - Add inputs `excess_ss_credit`, `additional_medicare_withheld` and `refundable_credits`.
     - Add a ratable-deeming work line: a Q4 W-4 bump cures earlier quarters, a late 1040-ES payment does not.
     - Build the prior-year line references with `form_line`.
     - Optional helper `safe_harbor_inputs_from_estimate(RefundEstimate)` that reads the ledger slots.
  - **Acceptance** (*illustrative* figures).
    - Head of household 2026, ss_wages 185,000 (at or above the $184,500 base): medicare_wages 215,000 → 0.0235; medicare_wages 190,000 → 0.0145.
    - hsa_deduction, MFJ, ss_wages = medicare_wages = 230,000 → 1.45%.
    - Safe harbor: projected tax 32,000, withholding 26,000, excess_ss_credit 900 → expected withholding 26,900.
    - refundable_credits 2,500 → current-year prong = 90% × 29,500.
    - The work cites 6654(g)(1).

### Block 2 — Paycheck-dated decision ops

- [x] **JP1a — employee_fica two layers, and the Step 4(c) solve — DONE 2026-09-27** (M; deps JF1a, JF3, JF4; **latest start 2026-10-14**) [DEF-09 + the rest of LD-12 + LD-14's 4(c)] — pitfall *withholding-vs-liability*
  - **Why.**
    - employee_fica pools ONE Social Security base and ONE Medicare accumulator across all segments, labels the person-level LIABILITY split as per-segment "withholding" (calc.py:3221-3225, :3293-3345), and rounds wages to whole dollars (:3317).
    - Withholding is per employer: each employer withholds Social Security up to the base, and the 0.9% applies only to "wages from the employer in excess of $200,000" (IRC 3102(f)(1); Pub 15 (2026) §9; knowledge/federal/2026.yaml:271-276).
    - Liability is per person, against the Form 8959 status threshold. The difference between the two is the hidden excess-SS credit.
  - *As built:* segments carry `employer` (none = one employer) and keep their cents; WITHHOLDING is per employer (its own wage base and IRC 3102(f)(1)'s $200,000 — segment rows, the `employers` rows, the totals); with `filing_status` the person's `liability` (one base; the 0.9% over the Form 8959 status threshold); `excess_ss_credit` (2+ employers) and `additional_medicare_reconciliation` (+ owed / − credited) name the differences; estimated_tax_safe_harbor's `remaining_pay_dates` returns `step_4c_per_check` (the shortfall over the remaining checks, rounded up), citing 6654(g)(1) and quoting the Form W-4 Step 4(c) line. Pitfall P-020.
  - **Build.**
    - Segments gain `employer`; wages stay in Decimal cents.
    - Two output layers: withholding per employer, and liability per person (when `filing_status` is given).
    - Add `excess_ss_credit` and `additional_medicare_reconciliation`, with unambiguous field names.
    - estimated_tax_safe_harbor gains optional `remaining_pay_dates`, and returns the Step 4(c) amount per remaining check that reaches the required payment under §6654(g)(1) ratable deeming. The projected withholding is still a caller input until JP1c.
  - **Acceptance** (*illustrative* figures).
    - Two concurrent employers, $150,000 + $90,000 (2026), head of household:
      - employer 2 withholds SS 5,580.00 and Additional Medicare 0;
      - person liability SS 11,439.00; excess_ss_credit 3,441;
      - head-of-household liability Additional Medicare 360.00.
    - $150,000.40 + $89,999.60 keeps the cents.
    - One employer, $230,000, MFJ → withheld 270.00, liability 0, reconciliation −270.
    - `test_wage_base_is_one_annual_pool_across_segments` still passes (segments without `employer` are one employer).
    - A shortfall of 2,400 over 6 remaining checks → 4(c) of 400 per check, citing 6654(g)(1).
    - The pitfall has a citing test.
- [x] **JP2 — Multi-employer 402(g) room — DONE 2026-09-27** (M; deps J0; **latest start 2026-10-19**) [LD-05]
  - *As built:* calc op `elective_deferral_room` (op count 32 → 33; MCP tools stay 23): the 402(g) room across every employer with the 414(v) catch-up by year-end age (50+, the higher amount at 60-63 — 414(v)(5)(A), (2)(B)(i)); per-check dollars and percent rounded DOWN (to the plan increment) so the last check never overshoots; an excess with its April 15 deadline (irs.gov: "not postponed by extending the filing"), the Pub 525 double tax and the individual's choice of plan (Treas. Reg. 1.402(g)-1(e)(2)(i)); the SECURE 2.0 Roth catch-up test (414(v)(7)(A); new pack field `roth_catch_up_wage_threshold`, 2026: $150,000 per Notice 2025-67); each plan's 415(c) room (catch-ups outside it, 414(v)(3)(A)(i)). contribution_limits' 402(g) string points at it; RetirementContributionsYear gains `deferrals_by_employer`; SKILL.md and the calc docstring list it (and now carry the JF4/JP1a arguments).
  - **Why.** contribution_limits takes only `year` (calc.py:3627-3630). Nothing computes the room left across employers, so a job-changer's new plan cannot see the old plan's deferrals.
  - **Build** `calc.elective_deferral_room`:
    - remaining §402(g) room, with the age catch-ups;
    - the per-check dollar amount and percent, rounded DOWN to the plan's increment, that lands at or under the cap by the year's last pay date;
    - any excess by employer, with the April 15 correction deadline, which "is not postponed by extending the filing", and the double-tax consequence (irs.gov excess-deferrals page);
    - the SECURE 2.0 Roth catch-up wage test;
    - §415(c) room per plan.
  - contribution_limits' 402(g) scoping string points at the new op, and RetirementContributionsYear gains a per-employer split.
  - **Acceptance** (*illustrative* figures; 2026 pack: limit 24,500, catch_up_50 8,000, catch_up_60_63 11,250).
    - $11,000 deferred at a prior employer, under 50 → $13,500 room.
    - Ages 50–59 → $21,500; ages 60–63 → $24,750 (11,250 instead of 8,000).
    - The per-check percent is rounded down and never overshoots.
    - An excess case shows the April 15 deadline; op count +1.

### Block 3 — The retirement block

- [x] **JR1 — Form 1099-R box 7 interpretation — DONE 2026-09-27** (M; deps JF2)
  - *As built:* `knowledge/forms/1099r_distribution_codes.yaml` — Table 1 of the 2019, 2023, 2024, 2025 and 2026 i1099r revisions, transcribed by word coordinates and read row by row against each page (29 codes, 30 with Y from 2025; `since`, `used_with`, `used_with_from` — Y pairs with 4/7/K, S with J, J with S, from 2025 — `title_until` for J/P/R's older wordings, {year}/{prior_year} title templates, account, return_effect; the loader asserts symmetry per revision; 2020-2022 take the 2019 = 2023 table) and the rule quotes (two codes; 8 with 1, 2 or 4; Q/T alone; the box 7b, recharacterization, direct-rollover, code Y, box 2b and box 7d sentences). `taxfill_core/distribution_codes.py`: `parse_box7`, `validate` (V0 unknown for the revision, V1-V5), `interpret`. extract_document (core and MCP, tool count 23) takes `tax_year`; `_VALIDATORS` add `findings` (severity / rule_id / boxes / message / citation — a flagged box stays 'ok', the message says "misread OR payer error: request a CORRECTED Form 1099-R") and `interpretation`; the caveat counts them. V6-V14 as listed (V7 is an error through 2024 and a warning from 2025, when a Roth SIMPLE IRA may check box 7b; V10 is an error for H and a warning for G); Form 5498 box 4 > 0 is info finding V15 (count the contribution once).
  1. **Code knowledge and interpreter** [RC-03].
     - Codes are stored as raw text (extract.py:263; `_coerce` 'code' is plain `str()`), so an impossible "NQ7" comes back 'ok' with no warning.
     - i1099r (2026) box 7a:
       - "a maximum of two alphanumeric codes";
       - "Only three numeric combinations are permitted … codes 8 and 1, 8 and 2, or 8 and 4";
       - "Do not combine code Q or T with any other codes".
     - Table 1 changes by revision: Y is new in 2025, and S went from 'None' (2024) to 'J' (2025). N/R/8/P/T meanings are year-relative.
     - New `knowledge/forms/1099r_distribution_codes.yaml`, year-invariant with revision markers:
       - built from the 2019/2023/2024/2025/2026 revisions;
       - per code: a title template with {year}/{prior_year}/{year_minus_5}, used_with and used_with_from, account, the box 2a/7b rules, return_effect, and a verbatim citation;
       - the loader asserts the used_with table is symmetric; ships via the stage_data rglob.
     - New `taxfill_core/distribution_codes.py`: `parse_box7`, `validate` → findings, `interpret` → Box7Interpretation.
  2. **Semantic validation in extract_document** [RC-05]. There is none beyond type coercion (extract.py:1295-1365; ExtractedDocument :1203-1216).
     - Add optional `tax_year` to the core function and the MCP tool (tool count stays 23).
     - Add a `_VALIDATORS` registry, `ExtractedDocument.findings` (severity / rule_id / boxes / message / citation) and `interpretation`.
     - A field's status stays 'ok' (a payer error is a real reading); the message says "misread OR payer error: request a CORRECTED Form 1099-R".
     - Rules V1–V14:
       - more than two codes;
       - a numeric pair outside the three permitted;
       - a pair not in used_with for the revision;
       - Q or T combined with anything;
       - Y without 4/7/K;
       - N/R with box 2a ≠ 0;
       - J/Q/T with the IRA box checked;
       - 2b checked with 2a filled on a non-IRA;
       - IRA box with codes 1/2/7 and 2b checked → pointer to ira_pro_rata;
       - G/H with 2a > 0;
       - P → amend the prior year;
       - 1/J/S → the 10%/25% tax and Form 5329;
       - 2a > box 1;
       - 7d without 7c.
  3. **Form 5498 box 4** [RC-13]. Box 4 is captured (extract.py:978) but never explained, so one contribution can be counted twice (the first trustee's box 1/10 plus the second trustee's box 4). Add the note and an info finding.
  - **Acceptance.**
    - A golden per-revision Table 1 transcription; symmetry holds for 2019/2024/2025/2026.
    - "NQ7" → error; "7 1" → error; "8 1" → ok; Q+B → error.
    - Y in 2024 → unknown code; "S J" is valid in 2025 and invalid in 2024.
    - N/R strings resolve against tax_year.
    - An N code with 2a ≠ 0 → an error finding, and the caveat reads "N findings (E errors)".
    - 5498 box 4 > 0 → an info finding; MCP e2e tool count is 23.
- [x] **JR2a — Net income attributable, the statements module, the deadline fallback — DONE 2026-09-27** (M; deps JR1, JF6a)
  - *As built:* calc op `ira_net_income_attributable` (op count 33 → 34): amount x (adjusted closing − adjusted opening) / adjusted opening, the opening balance counting every contribution in (the one being moved included) and the closing balance adding back every distribution out; exact division to cents with the three-place figure and its difference beside it; negative after a loss; the whole-account rule; reproduces 1.408-11 Ex. 1 ($75) and Ex. 2 ($186.89 exact vs the printed $187) and 1.408A-5 Ex. 1 (−$10,000) and Ex. 2 ($5,000 / $4,000). `taxfill_core/statements.py`: `recharacterization_statement` (both i8606 examples verbatim in the first person; [NAME]/[SSN] placeholders; "Filed pursuant to section 301.9100-2" heads a late one; the optional conversion sentence labeled optional), `returned_contribution_statement`, and `ira_line_4b_statement` (the 2025 line 4c instructions' "Line 4b – $1,000 Rollover and $500 HFD.", the line through form_line). New registry keys `f1040.ira_distributions` (4a) and `f1040.ira_taxable` (4b), 2019-2026, read off each face. `calc._return_due_date`: the pack's date when it has one, else IRC 6072(a)'s April 15 rolled by IRC 7503 (weekends, DC Emancipation Day) and labeled ASSUMED; the extended date is Treas. Reg. 1.6081-4(a)'s 6 months, rolled the same way; an override wins.
  1. **NIA op** [RC-01]. A grep for 1.408-11, 1.408A-5, "net income attributable", 408(d)(4) and 408A(d)(6) across packages/ and knowledge/ returns 0 hits.
     - New `calc.ira_net_income_attributable(purpose='recharacterization'|'returned_contribution', …)`.
     - Formula (Treas. Reg. 1.408A-5 A-2(c)(1); 1.408-11(a)(1)): "Contribution × (Adjusted Closing Balance − Adjusted Opening Balance) / Adjusted Opening Balance".
       - The opening balance includes the contribution being moved.
       - The closing balance adds back distributions and recharacterizations.
     - Implement the whole-account rule; a negative NIA is allowed (Pub 590-A).
     - Divide EXACTLY, and also report the three-place result and its dollar difference. This is a labeled choice: Pub 590-A says "at least three places", and three-place rounding misses the regulation's own examples.
     - No per-year figures, so no pack read.
  2. **Statements** [RC-09, generator half]. New `taxfill_core/statements.py`.
     - `recharacterization_statement(facts)`, in the element order of the i8606 examples.
       - [NAME]/[SSN] placeholders keep PII out of calc output.
       - "FILED PURSUANT TO § 301.9100-2" heads the statement when late.
       - The optional conversion sentence is labeled optional.
     - Also `returned_contribution_statement` and `ira_line_4c_statement`.
  3. **Deadline fallback** [RC-15]. The 2026 pack has no deadlines block (2026.yaml:80-91).
     - Shared helper `_return_due_date(year, pack)`: the pack when present; otherwise April 15 of year+1 (IRC 6072(a)) with the §7503 weekend / DC-holiday roll.
     - Label the fallback ASSUMED, accept an override, and carry the provisional stamp.
  - **Acceptance.**
    - NIA reproduces the regulation examples:
      - 1.408-11 Ex. 1: $75 on $400;
      - 1.408-11 Ex. 2: $186.89 exact (the regulation prints $187; the test documents the difference);
      - 1.408A-5 Ex. 1: −$10,000;
      - 1.408A-5 Ex. 2: $5,000 / $4,000.
    - Statement goldens reproduce both i8606 examples:
      - $4,000 contributed, $3,000 recharacterized with $300 of earnings, $1,000 deducted;
      - $4,000 → $4,200, the account balance, same-year line 4a.
    - The late path carries the §301.9100-2 header.
    - Due dates: TY2025 from the pack (2026-04-15 / 2026-10-15); TY2026 computed (2027-04-15, a Thursday) and labeled.
    - Op count +1.
- [x] **JR2b — The recharacterization op — DONE 2026-09-27** (M–L; deps JR2a) [RC-02 + TY26-27 + LD-18 + RC-12] — pitfall *recharacterization*
  - *As built:* `calc.ira_recharacterization` (op 35; P-021), with a signature designed from this spec (the review's §B was not kept): `direction, amount, contribution_year, contribution_date, contributed_total?, transfer_date?, source_kind?, deducted?`, the NIA inputs, `extension_filed?, return_filed_date?, due_date_override?`, the eligibility facts, `other_*_contributions?, elect_nondeductible?, roth_ira_dec31_value?, readings?, then_convert?`.
    - **Refusals:** a conversion, a rollover (A-4, with its SIMPLE exception quoted), SEP/SIMPLE employer money (A-5), an overlap with the deducted part ((B)(ii)), an amount above the contribution, a contribution date outside Jan 1 – the unextended due date (Pub 590-A), and a transfer dated before the contribution.
    - **Deadline status** comes from `_return_due_date`: `open` (no transfer date), `timely` (by the due date, or by the extended date with `extension_filed`), `late_301_9100_2` (no extension, a return filed by the due date: an amended return with the header) or `too_late`. With neither fact known, a transfer after the due date is refused with the question.
    - **Code N vs R** follows the transfer year (i1099r 2026 wording, box 7a from 2026), and with it Form 1040 line 4a vs the statement only.
    - **Target side:** Roth → traditional checks IRC 4973(b) (the combined per-person limit, without 219(g)); traditional → Roth checks Roth eligibility.
    - **Deduction** via ira_contribution_eligibility; `elect_nondeductible` quotes 408(o)(2)(B)(ii).
    - **Form 8606:** `line_1_add` counts contribution dollars only (A-3); `line_4_add` applies when the original contribution was dated Jan 1 – Apr 15 of year+1; `line_6_adjustment` is ±(amount + NIA) after year end, labeled a CHOICE (i8606 Line 6).
    - **Documents and notice:** the i8606 statement (via statements.py); four expected documents (the first trustee's 5498 box 1/10, the transfer-year 1099-R boxes 1 and 2a, and the second trustee's 5498 box 4) with the ±$1 reconciliation; the A-6(a) notice, filled.
    - **Alternatives:** `return_408d4` (additional tax 0, quoting 72(t)(2)(A)(ix), i5329 exception 21 AND the i8606 sentence it overrules) and `leave_in_place` (the capped 4973 excise).
    - **then_convert** runs roth_conversion with line_1_add as this-year basis (or as carryforward when the conversion is in a later year, labeled).
    - **Tests:** test_ira_recharacterization.py (13, including both i8606 worked examples reproduced to the dollar).
  - **Why.** `ira_contribution_eligibility` (FIELD_NOTES N-11) detects an over-the-phase-out Roth contribution, but nothing fixes it. Recharacterization is the fix, and no op models it.
  - **Build** `calc.ira_recharacterization`; the full signature is in the review (§B).
    - **Refusals:**
      - conversions made after 2017 (408A(d)(6)(B)(iii));
      - rollovers (A-4);
      - employer SEP/SIMPLE money (A-5);
      - deducted amounts ((B)(ii));
      - an amount above the contribution.
    - **NIA** via JR2a.
    - **Deadline status** via the shared helper: timely, late (§301.9100-2 plus an amended return), or too late.
    - **Code N vs R**, by the year of the transfer. This decides Form 1040 line 4a vs statement-only reporting (i8606 2025).
    - **Target-side limit check:**
      - Roth → traditional: is it still an excess under 4973(b)?
      - traditional → Roth: is the filer Roth-eligible?
    - **Deduction** via ira_contribution_eligibility, with `elect_nondeductible` (408(o)(2)(B)(ii)).
    - **Form 8606 inputs:**
      - `line_1_add` counts contribution dollars only; NIA is never basis (A-3);
      - `line_4_add` applies when the ORIGINAL contribution date is Jan 1 – Apr 15 of year+1;
      - `line_6_adjustment` is labeled a CHOICE.
    - **Documents:** the expected documents, and a ±$1 reconciliation of any 1099-R / 5498 readings passed in; the trustee notification checklist (A-6(a)).
    - **Alternatives:**
      - a 408(d)(4) return. The earnings owe no 10% tax per IRC 72(t)(2)(A)(ix) and i5329 exception 21. i8606 ("generally subject") conflicts; follow the statute and quote both in the pitfall so a re-read of i8606 cannot undo it;
      - leaving it in place, with the 6% excise capped per 4973(a).
    - **Optional `then_convert`**, delegating to roth_conversion; it refuses a conversion dated before the transfer.
  - **Interpretive choices for the user to confirm** (labeled in the op output):
    - the `line_6_adjustment` value for a recharacterization after year end;
    - "including extensions" read as applying only when an extension was actually filed; otherwise the Oct 15 date goes via §301.9100-2 plus an amended return;
    - exact division rather than three places.
  - **Acceptance.**
    - Every refusal has a test.
    - N/R timing → line 4a vs statement_only; the Jan–Apr line-4 rule holds; NIA is excluded from line 1.
    - The return_408d4 alternative shows additional tax 0, citing 72(t)(2)(A)(ix).
    - then_convert embeds roth_conversion with the line-1 basis.
    - Op count +1; the pitfall has citing tests.
- [x] **JR2c — Custodian statements, the filing manifest, rule reach — DONE 2026-09-27** (M; deps JR2b) [RC-09 manifest half + RC-16 + TY26-27]
  - *As built:*
    - **DocSpec `IRA custodian statement`** (27 kinds). Its boxes are statement_type (trade_confirmation | transfer_confirmation | year_end_fmv), custodian, account_type, account_number, transaction date/type, amount, from/to accounts, contribution_year, fmv_date and fmv.
      - The status note quotes the i1099r 2026 timing: the 5498 "with the IRS by May 31, 2027", the statement to each participant "by February 1, 2027".
      - Validators: V16 an unknown type, V17 a year-end value not as of Dec 31, V18 a confirmation without an amount or ISO date.
    - **`extract.dec31_total_value_from_statements(documents, tax_year)`** returns `Dec31Value`. It sums the traditional/SEP/SIMPLE Dec-31 values with each statement's provenance and lists the excluded ones (a Roth IRA, the wrong date, a confirmation, another kind) with the reason.
    - **The confirmation round trip:** ira_recharacterization reconciles a `{form: 'confirmation', box: 'amount'}` reading against the amount transferred.
    - **Manifest:** `FilingManifestItem.attached_statements`. file_and_pay's assemble list says ATTACH THE <STATEMENT>, and the sign list says it is not signed separately. ira_recharacterization's work names the entry.
    - **Rule reach:**
      - ira_contribution_eligibility's EXCESS line;
      - the intake Roth IRA note;
      - roth_conversion's docstring (a conversion is final, so recharacterize first);
      - the 1099-R note (N vs R) and the 5498 box 4 finding;
      - the codex and copilot skill files.
    - **Eval (u):** the `HOH_RECHARACTERIZE_BEFORE_CONVERTING` fixture (a hypothetical head-of-household filer; reusable by JT4c). The excess is found, a conversion is refused, the move is recharacterized, then converted with only the $210 of earnings taxable, and the manifest names the statement.
    - **Tests:** test_ira_custodian_statement.py (5).
  - **Custodian-statement DocSpec.** Form 5498 is due to the IRS "by May 31, 2027", after April 15. The Dec-31 FMV statement goes to participants "by February 1, 2027" (i1099r 2026). So a new `IRA custodian statement` DocSpec covers:
    - trade / transfer confirmations (date, amount, type, from/to account);
    - the year-end FMV statement, which feeds `dec31_total_value` for ira_pro_rata / roth_conversion with document provenance.
    
    The op notes the 5498 timing prominently.
  - **Manifest.** `FilingManifestItem.attached_statements`, so the filing checklist says what to attach.
  - **Rule reach.**
    - Pointers at the use sites: JF1b.4's EXCESS line, the intake Roth IRA note (intake.py:1142-1150), the roth_conversion docstring, and the 5498 and 1099-R notes.
    - Skills docs and op list updated.
    - A separate synthetic what-if eval on a hypothetical head-of-household filer covers "recharacterize before converting". JT4c's t4 rehearsal reuses that fixture.
  - **Acceptance.**
    - A confirmation round trip, and an FMV statement feeding `dec31_total_value` with provenance.
    - The manifest lists "recharacterization statement".
    - test_skills_sync matches the runtime op list.
- [x] **JR3a — Retirement distributions in the estimator — DONE 2026-09-27** (M; deps JR1, JR2b) [RC-07, part 1]
  - *As built:* `IncomeSnapshot.retirement_distributions: list[RetirementDistribution]`.
    - **Fields:** gross, taxable_amount (2a), the two 2b flags, codes, ira_sep_simple, rolled_over (the disposition), taxable_override, early_exception_amount, federal_withholding (informational), label.
    - **Pricing:** `_retirement_taxable` decides each item from its box 7 codes (`distribution_codes.parse_box7`).
      - The override wins, less any rollover.
      - P is excluded; the assumption quotes the year's own Table 1 title.
      - N, R and Q are $0. G and H take box 2a, $0 when blank.
      - Otherwise box 2a, less any rollover. An IRA's 2b-checked gross is flagged for ira_pro_rata, J for Roth basis, and a blank 2a uses the gross with a disclosure.
    - **Exclusivity:** `retirement_income_taxable` stays the manual figure, and both together is a ValueError.
    - **Joint view:** the lists are concatenated. A spouse's manual figure beside a list rides as an override item; two manual figures are summed.
    - **Docs:** server.py documents the list.
    - **Tests:**
      - test_estimate `test_jr3a_*`: Q/G/H/R/JP → 0; 7 with a rollover; the override; P's assumption; the refusal; the joint view;
      - `retirement_distributions` is classified as concatenated in the JF1b.5 spouse-field test.
  - Today IncomeSnapshot has one hand-fed integer (estimate.py:87-192, :228).
  - Add `retirement_distributions: list[RetirementDistribution]`: gross, 2a, the 2b flags, codes, IRA box, disposition, override, early_exception_amount, and withheld (informational).
  - Route each item through `distribution_codes.interpret`.
  - `retirement_income_taxable` stays as a manual override, refused when the list is also set.
  - **Acceptance:** Q → 0; G/H rollover → 0; J+P → excluded with an assumption; both inputs set → ValueError; the spouse-field test covers the new list.
- [x] **JR3b — Per-person IRA pool and pro-rata — DONE 2026-09-27** (M; deps JR3a) [RC-07, part 2]
  - *As built:* `IncomeSnapshot.ira_pool: IraPoolFacts` holds basis_carryforward (line 2, required; 0 = no basis), nondeductible_contributions_this_year (line 1), contributions_made_after_year_end (line 4) and dec31_total_value (line 6, required with basis).
    - **New field:** `RetirementDistribution.converted_to_roth`, which sends an item to Form 8606 line 8 rather than line 7.
    - **Pricing:** estimate_refund resolves EACH person's 2b-checked IRA items first (`_resolve_ira_pool`). Those are items with the IRA box and box 2b checked, no override, and no Q/N/R/P/G/H code.
      - The op is calc.ira_pro_rata. Zero basis means the items are fully taxable.
      - The result is split across the items and rides on each as `taxable_override` with a "(<who>'s Form 8606)" label, so the joint view concatenates without merging pools.
      - The joint view drops `ira_pool`; the JF1b.5 class is `_SPOUSE_NEVER_MERGED`.
    - **Refusals:** no pool gets a prescriptive ValueError naming the `{basis_carryforward: 0}` answer; basis without line 6 names `dec31_total_value`.
    - **Disclosure:** an assumption names each item priced through the person's own Form 8606.
    - **Tests** (test_estimate `test_jr3b_*`):
      - the illustrative recharacterize-then-convert case, taxable $250 = NIA + growth, not the $7,250 gross;
      - the required pool and the explicit zero;
      - an MFJ couple's pools priced apart.
  - Add `ira_pool: IraPoolFacts` per person.
  - Traditional-IRA items with 2b checked go through ira_pro_rata. `ira_pool` is then REQUIRED, with a prescriptive refusal; `{basis_carryforward: 0}` is the explicit no-basis answer.
  - Spouses' pools never merge (Form 8606 is filed per spouse).
  - **Acceptance** (*illustrative*): a code-N recharacterization plus a code-2 conversion, with the pool carrying the line-1 basis → taxable = NIA + growth, not the box-2a gross. An MFJ couple's pools stay separate.
- [x] **JR3c — The 72(t) and 4973 taxes — DONE 2026-09-27** (M; deps JR3a, JF6b) [RC-08]
  - *As built:*
    - **New operand slots:** `early_distribution_additional_tax` and `ira_excess_contribution_excise`, both in total tax and labeled from form_line.
    - **New keys, read 2026-09-27:**
      - f5329.early_distribution_tax (4), f5329.traditional_excess_tax (17), f5329.roth_excess_tax (25);
      - sched2.retirement_additional_tax (6 / 8 / 5 on the 2026 draft);
      - sched2.ira_excess_excise (6 / 8 / 18 on the 2026 draft Schedule 2, Form 5329 Created 7/31/26).
    - **72(t):** Form 5329 Part I prices each 1099-R's taxable part less its early_exception_amount at 10% for codes 1/J (72(t)(1)) and 25% for S (72(t)(6)).
      - Code 8 with J/1 owes 0 (72(t)(2)(A)(ix), disclosed); code P is not this year's.
    - **4973:** IncomeSnapshot gains `traditional_ira_excess` / `roth_ira_excess` (lines 16/24) and `*_ira_dec31_value`. The excise is 6% capped per person at the Dec-31 value, and the joint view applies each person's cap before summing.
      - An uncapped charge is disclosed.
    - **Docs:** server.py.
    - **Tests** (test_estimate `test_jr3c_*`):
      - code 1 $12,000 → $1,200 labeled "Form 5329 line 4 -> Schedule 2 line 8"; the exception amount; SIMPLE 25%; code 7 → none;
      - J8 → earnings taxable, 0 additional tax;
      - the cap (7,000 vs 5,000 → $300); the uncapped disclosure; 2026 → line 18; the joint caps;
      - every ledger reconciles.
  - The estimator has no 72(t) additional tax and no 4973 excise (grep: 0 hits; `_LEDGER_SLOTS` estimate.py:307-343).
    - IRC 72(t)(1) is "10 percent of the portion … includible in gross income"; (t)(6) makes it 25% in a SIMPLE IRA's first two years.
    - 4973(a) is 6%, capped at the account value.
  - New slots `early_distribution_additional_tax` and `ira_excess_contribution_excise`, labeled from `form_line`: Schedule 2 line 8 for 2025; lines 5 and 18 on the 2026 draft Schedule 2 and the 2026 draft Form 5329 (Created 7/31/26).
  - **Acceptance** (*illustrative*):
    - Code 1, $12,000, no basis, under 59½ → a $1,200 slot.
    - J+8 → earnings taxable, 0 additional tax.
    - The excise is capped at the Dec-31 value; the ledger reconciles.

### Block 4 — The TY2026 foundation (dated)

- [x] **JT0a — Draft packs, rehearsal mode, multiple second passes — DONE 2026-09-27** (M; deps J0; **latest start 2026-10-12**) [TY26-01 + TY26-03 + G32 + LD-08(3)]
  - **Why.** Every 2026 draft for the Wave A forms is posted at irs.gov/pub/irs-dft/. The IRS cover sheet says "there are never any changes to the last posted draft of the form and the final revision of the form"; drafts of instructions and publications do change. Three gates refuse drafts-first authoring today:
    - the URL-prefix test (test_formpacks_federal.py:208-217);
    - `assert_filing_grade` inside the golden test (filler.py:360; verify.py:2324/2427);
    - the sha256 pin, which breaks when IRS re-posts a draft (f1040--dft: Last-Modified 2026-09-17, Created 8/19/26).
  - *As built:* `FormPack.source_status` / `draft_created` with a validator (a draft needs its Created stamp; a final pack may not use irs-dft or carry the stamp); the URL test allows irs-dft only for a draft; core-only `fill_form(..., rehearsal=True)` / `verify_form(..., rehearsal=True)` accept only a draft pack, bypass the filing-grade guard and stamp every page with a FreeText "REHEARSAL — DRAFT FORM — NOT FOR FILING" (MCP never passes it, so MCP fill_form still refuses 2026); check_drift reports a re-posted draft as "draft re-posted: re-audit" (a warning); `test_no_draft_packs_in_a_filing_grade_year`; `Provisional.second_passes` (second_pass kept as a deprecated alias) with each pass's `source_status` / `draft_created`, `draft_only_blocks()` and `removal_blockers()` (absent blocks, draft-only blocks); CONTRIBUTING-PACKS "Drafts-first" and DEV_PLAN §5.
  - **Build.**
    - FormPack gains `source_status: final | draft` and `draft_created`; the URL test allows irs-dft only for draft packs.
    - A core-only `rehearsal=True` on fill_form / verify_form, never reachable through MCP. It bypasses the filing-grade guard only for draft packs and stamps "REHEARSAL — DRAFT FORM — NOT FOR FILING"; the golden test uses it.
    - check_drift reports a draft sha change as WARN ("draft re-posted: re-audit").
    - New invariant `test_no_draft_packs_in_a_filing_grade_year`.
    - `Provisional.second_passes: list[…]`, keeping `second_pass` as a deprecated alias. Each entry carries `source_status` and `draft_created`. Removing the marker is refused while a draft-only entry covers a block.
    - Document it in CONTRIBUTING-PACKS ("Drafts-first") and DEV_PLAN §5.
  - **Acceptance.**
    - A dummy draft pack passes the golden test in rehearsal mode; MCP fill_form still refuses 2026.
    - The invariant fails on a draft pack in a non-provisional year.
- [x] **JT0b — Planning-year fixtures — DONE 2026-09-27** (M; deps JT0a) [TY26-02]
  - *As built:* a root `conftest.py` with `planning_year` (the newest provisional federal year; skips when none) and `synthetic_provisional_pack` (`make(strip)` → a tmp knowledge copy whose planning pack has the named blocks removed and declared absent). Rewritten to behaviour: evals i2 (every declared-absent block is absent; the blocks a projection needs ship; second_passes resolve; removal_blockers names what keeps the marker on), i3 (the refusal names every absent block and what is still assumed), i4, i5 (a stripped `credits` block names the CTC NOT ESTIMATED); test_estimate_ledger's missing-blocks twin; test_schedule_1a's deliberately-absent refusal (a stripped `obbba_schedule_1a`); test_compare_scenarios' cross-year label. test_projection_ops' 2023 FICA refusal is a past-year pin (the 2023 pack predates the Medicare fields), not a planning-year one, and stays.
  - A `planning_year` conftest fixture returns the newest provisional federal year and skips when there is none.
  - A `synthetic_provisional_pack` fixture makes a tmp copy with named blocks stripped.
  - Rewrite the absent-block assertions to test behaviour, not today's contents of 2026.yaml: evals/test_scenarios.py:237, :261, :273-281, :307, :340-360; test_estimate_ledger.py:176-189; test_schedule_1a.py:174-176; test_compare_scenarios.py:84-89; test_projection_ops.py:197.
  - **Acceptance:** the suite is green, and it stays green when a 2026 block is added to a scratch copy.
- [x] **JT0c — Finals watch, red-quarantine, the 1040-ES voucher, the 2026 header — DONE 2026-09-27** (M; deps JT0a) [TY26-04 + G22(3) + TY26-22 + TY26-30]
  - *As built:*
    - **Finals watch:** `scripts/check_finals.py` plus its own workflow `.github/workflows/finals.yml`. It covers the draft packs of the newest provisional federal year (by IRS file stem) plus p1040, i1040gi and p501; all three answered 404 on 2026-09-27.
      - The cron is Mondays in Oct–Nov, then daily Dec 15–31, all of January and Feb 1–15.
      - The issue body re-lists the posted and missing finals. The script comments only when that list changes, and a non-404 HEAD fails the run as a "watch blind".
      - `--dry-run` prints the re-pin list and the gh commands. `--assume-posted` rehearses the issue while nothing is posted.
    - **Quarantine:** `scripts/freshness_quarantine.yaml` plus a loader. Every row carries `added`, `expires` (at most 200 days later), `fixed_by` and `why`; the two MA rows and the DC row expire 2027-03-31 and point at JS1b/JS1a.
      - A root-conftest hook marks a quarantined network test `xfail(raises=FetchError)`, so the quarantine never masks an assertion failure.
      - `check_drift.main` reports quarantined drift and fails on an expired row.
      - A freshness.yml `report` job opens or comments on a `freshness red` issue on any failure.
    - **1040-ES:** `FormPack.filing_grade_basis` (`year_knowledge` | `own_final_revision`) and `knowledge.assert_pack_filing_grade`. The basis is allowlisted to `OWN_FINAL_REVISION_FORMS = {("federal", "1040-ES")}` and needs a final pack on an irs-prior URL. fill_form, verify_form and verify_filing route through it.
    - **Sources:** a `draft_forms` change channel (irs.gov/draft-tax-forms) and six topics, every quote verified against its own URL on 2026-09-27:
      - federal_public_benefit: the draft Schedule 3-A (Created 6/24/26), 8 U.S.C. 1641(b)–(c) and 1611(a);
      - itemized_limitation_2026: IRC 68 as rewritten by P.L. 119-21 §70111, and the draft Schedule A line 18 ($384,350);
      - **form_1098vli**, planned as vehicle_loan_interest_statement: IRC 6050AA, the draft 1098-VLI (Created 8/20/26) and 163(h)(4)(B)(iii);
      - **w2_2026_codes_tp_tt**, planned as w2_2026_tips_overtime: the FINAL 2026 W-2 (Created 1/7/26) and iw2w3 2026, with codes TP/TT and box 14b;
      - trump_accounts: IRC 530A and i4547 (Rev. December 2025);
      - tax_tables: the draft Pub 1040 (2026), dated Aug 28, 2026.
    - **Renames:** the two planned keys were renamed because their key tokens outweighed any answers text. They took "tips", "overtime", "tips deduction", "car loan interest", "student loan interest" and "interest income" from their own topics.
    - **Routing fix:** `get_sources` now ignores a year token (`_YEAR_TOKEN`) in the query and in the key. Before, "2026 tax brackets" routed to the charitable non-itemizer entry.
      - Two companion text fixes: tax_rates_and_tables now says "tax brackets", and Pub 936 now carries its Form 1098 sentence, so "Form 1098" leaves `education` for `itemized_mortgage_interest`.
      - A HEAD-vs-tree sweep over 240 queries plus 49 probes changes only one route: "box 12 code D" moves from foreign_tax_credit to the W-2 box 12 topic, whose iw2w3 source defines code D.
    - **2026 header:** knowledge/federal/2026.yaml:1-67 now lists:
      - what is final (Rev. Proc. 2025-32, Notice 2025-67, Pub 15, 1040-ES, W-2/iw2w3);
      - the drafts with their Created dates (1040 8/19/26; Schedules 1, 1-A, 2, 3, 3-A, A, B, D and SE; Forms 8949, 8959, 8889 and 8606; Pub 1040);
      - what is not posted at all (i1040gi 2026, Pub 501 2026, the Schedule 1-A and 3-A instructions);
      - the four outstanding items;
      - `still_assumed`, which now names the draft Pub 1040.
    - **Tests:** test_freshness_quarantine.py (13 tests, including a subprocess pytest run), test_formpacks_federal `test_jt0c_*` (2) and test_sources `test_jt0c_*` (5).
  - **Why.** The finals watch is JT6's only trigger. freshness.yml has been red 6 of 6 weeks since 2026-08-17 (last: run 35621846216), so a signal routed there would be lost.
  - **Finals watch.** `scripts/check_finals.py` runs in its OWN workflow and opens or updates an issue labeled `ty2026-finals: re-pin now`.
    - It HEADs irs-prior/<form>--2026.pdf for every draft pack, plus p1040, i1040gi and p501; all returned 404 on 2026-09-23.
    - It runs weekly Oct–Nov and daily Dec 15 – Feb 15.
  - **Quarantine.** In freshness.yml, the two known MA tests and the DC drift row go into an explicit allowlist with an expiry date and a JS1 pointer, so any NEW red opens a `freshness red` issue.
  - **Sources.** A `draft_forms` change channel and topics federal_public_benefit, itemized_limitation_2026, vehicle_loan_interest_statement, w2_2026_tips_overtime, trump_accounts and tax_tables.
  - **1040-ES voucher.** The Q4 2026 voucher is due 2027-01-15, and the 2026 Form 1040-ES is FINAL (irs-prior/f1040es--2026.pdf). Add `filing_grade_basis: own_final_revision`, allowlisted to f1040es.
  - **2026 header.** Rewrite knowledge/federal/2026.yaml:1-50, which claims one blocker and unpublished forms, to the real outstanding list with draft and final sources.
  - **Acceptance.**
    - check_finals prints the re-pin list and files the issue in a dry run.
    - A new failing network test fails freshness while the allowlisted ones do not; an expired allowlist entry fails.
    - The 1040-ES allowlist test passes.
- [x] **JT3a–d — Wave A: the core W-2 / retirement / HSA 2026 federal packs, drafts-first — DONE 2026-09-27** (JT3a **latest start 2026-10-26**; deps JT0a–c, JF6c) [TY26-20]
  - **Sub-tranches.** The count in parentheses is how many 2025-pack field names are missing from the draft.
    - **JT3a** (M–L): f1040 (43 of 192), sched_1a (44/54; 225 fields). **DONE 2026-09-27** — *as built:*
      - **formpacks/federal/2026/f1040** (draft Created 8/19/26, sha e044e765…): 200 of 207 widgets (the 7 unmapped are the paid-preparer block).
        - New keys 12f, 24a–c and 32a–c; 12d keys roll to `…_jan_2_1962`; 13a is now Schedule 1-A line 44 and 13b QBI.
        - The new citizen / U.S. national / work-authorized question maps as two grouped radios, `citizen_or_work_authorized.{you,spouse}.{yes,no}` (not required: the 2026 instructions are not final).
        - 28.do_not_claim_actc is gone (the draft prints no box). The state box is 62.8pt, so maxlen 13 (the round trip's clipping scan caught the 2025 value of 14).
        - `signature.page` 3: the draft's page 1 is the IRS cover sheet.
        - The four ROADMAP relations plus 34/37 against 24c. Cross_form keeps the printed Schedule 1/2/3 legs, allowlisted in test_pack_invariants until JT3b/JT3c ship those packs (the 2022 precedent), and adds `13a == sched_1a.44`.
      - **formpacks/federal/2026/sched_1a** (draft Created 6/16/26, sha e22aec7f…): all 185 widgets.
        - Tables 4 (i–v), 6 (i–xiii: two printed tables sharing rows a–e), 16 (i–iii) and 18 (i–iv), keyed `<row>.<column>`.
        - 28a/28b gain grouped yes/no radios `original_use` and `us_final_assembly`.
        - Cross_form: `1 == f1040.11b`, `44 == f1040.13a`. The f1040nr legs join with the 2026 f1040nr pack (JT5c).
      - **Harness:**
        - The golden round trip runs a draft pack in rehearsal mode.
        - `list_forms` / `get_form_map` carry `source_status` and `draft_created`.
        - The renumbered-line guard adds 2026 f1040 24 and 32.
        - test_discovery: 113 federal packs, the 2026 ones all drafts.
      - **Tests** (test_formpacks_federal `test_jt3a_*`):
        - the printed-face keys and the 13a/13b trap, the face math on a consistent demo return (and a stale 33 caught);
        - the Schedule 1-A hookup read from the form_lines registry for 2025 and 2026;
        - the Schedule 1-A table and radio shape.
      - **Vision audit:** every page of both filled drafts, at 110 and 200 dpi, with each synthetic value checked against its printed line. It caught the state-box clip and found nothing else.
    - **JT3b** (M): sched_2 (19/63), f8959 (0/26, but its Parts are reordered), f8889 (0 missing). **DONE 2026-09-27** — *as built:*
      - **formpacks/federal/2026/sched_2** (draft Created 4/27/26, sha 0e3d4faa…): all 68 widgets, mapped from scratch — Part II is now Sections A/B/C.
        - The header carries the 2025→2026 line map. TRAP: 2026 line 5 is the IRA additional tax (2025 line 8) and 16a/16b/16c the old 5/6/7.
        - 13a–13o/13z are the old 17a–17o/17z; the old 17p/17q are 19a/19b; 18 is the NEW excess-contribution line; 11 is the SE Additional Medicare Tax and 17b the wages/RRTA part.
        - 13z.type is a two-row multiline box: maxlen 70 at the draft's 9pt DA (2025's 8pt gave 79).
        - Relations: 1z, 3, 14, 15, 16c, 17d, 19c, 20, 21. The Form 1040's `17 == sched_2.3` / `23 == sched_2.21` now resolve, so their allowlist rows are gone.
      - **formpacks/federal/2026/f8959** (draft Created 5/27/26, sha 8f663b2c…): the same 26 names in the same line order, but Parts II/IV swap.
        - RRTA is 8–11 and the wages+RRTA total is line 12 → Schedule 2 line 17b; SE is 13–18 → Schedule 2 line 11. The 2025 all-parts total (line 18) is gone.
        - Relations re-derived from the face (10, 11, 12, 15, 16, 17, 18 new); cross_form `12 == sched_2.17b`, `18 == sched_2.11`.
      - **formpacks/federal/2026/f8889** (draft Created 4/30/26, sha c94550b7…): a port of the 2025 pack. The topology is identical (the 1pt-narrower SSN box aside).
        - The face changes: the year, line 3's $4,400/$8,750, the 13c/13d Schedule 2 destinations, and the full 14b/14c/17b designators. Cross_form stays empty (additive legs).
      - **Tests** (test_formpacks_federal `test_jt3b_*`):
        - the Schedule 2 renumber; the 8959 Part reorder against the 2025 pack; the 8959 math on a demo wage+SE return; 8889 = the 2025 map;
        - NEW invariant: every form_lines registry entry names a line its same-year pack maps (220 entries over 2022-2026, 43 for 2026).
        - test_discovery 116; the filer-address fixture gains 3 empty rows.
      - **Vision audit:** all four pages, each synthetic value against its printed line. It caught nothing; the 8959 trap was caught from the face before the render.
    - **JT3c** (M): f8606 (18/45), sched_1 (1/73), sched_3 (2/36). **DONE 2026-09-27** — *as built:*
      - **Every 2026 draft's widget /DA is 9pt (2025: 8pt)**, and verify's clipping scan reads it, so each 2025 write-in budget shrinks by 1/9:
        - the 8z/24z two-row boxes take maxlen 70 (2025: 79);
        - Form 8606's 10.dec box (26.8pt) takes maxlen 5 — the round trip's clipping scan caught it.
      - **formpacks/federal/2026/f8606** (draft Created 4/21/26, sha 4d7e8fe4…): all 47 widgets, EVERY name changed.
        - The zero padding is gone (f1_01 → f1_1).
        - The one city/state/ZIP box is three boxes, keyed as on Form 1040, so lines 1–14 moved +2.
        - TRAP: the preparer block's f2_19/f2_20 swap meaning (2026: firm address, then firm EIN).
        - The umbrella Note now excludes Trump accounts. `signature.page` 3.
        - The relations and the dropped-relation decisions carry over.
      - **formpacks/federal/2026/sched_1** (draft Created 4/24/26, sha a017a1b7…): the 2025 map, with two changes:
        - line 14's storage-fees box moved (the row adds "and the intelligence community");
        - 24a sits under Line24_ReadOrder.
        - Line 22 (reserved, ReadOnly) stays mapped under a new RESERVED_LINE_KEEPS row.
      - **formpacks/federal/2026/sched_3** (draft Created 4/27/26, sha 5feb6f8d…):
        - 5a now cites "Form 5695, line 3"; 5b is reserved and ReadOnly and leaves line 8's sum. Both 5b and 6e stay unmapped under a new RESERVED_LINES_UNMAPPED row.
        - NEW 13e (Form 1062, line 14); 13z..15 rebind +1.
      - **With Schedules 1–3 shipped**, the last 2026 CROSS_FORM_TARGET_ALLOWLIST rows are gone: every 2026 Form 1040 leg resolves.
      - **Harness fix:** the reserved-line refusal test fills a draft in rehearsal mode.
      - **Tests:** test_jt3c_* (the 8606 rebind + preparer swap, Schedule 1's two rebinds + budgets, the Schedule 3 reserve/13e + the 1040's legs resolving); test_discovery 119; the filer-address fixture gains 3 rows.
        - The f8606 row differs from 2025 (the split box). Reviewed: it equals the Form 1040's reviewed set.
      - **Vision audit:** every page of the three, each value against its printed line. Nothing beyond the 10.dec width.
    - **JT3d** (M):
      - sched_b, sched_d and f8949 (0 missing each);
      - f8833: the current final is byte-identical to the 2025 pin → copy, source_status final;
      - **f1040es**: FINAL, but all 56 mapped names changed; uses `own_final_revision`.
      - **DONE 2026-09-27** — *as built:*
        - **The rehearsal decision** (the JT3a question): `filler.rehearsal_only(pack)` is True for a DRAFT pack and for a FINAL pack whose year is planning-only (basis year_knowledge); fill_form/verify_form(rehearsal=True) accept exactly those.
          - A pack on its own final revision (the 1040-ES) fills normally and refuses rehearsal, as does a final pack in a filing-grade year. MCP never passes rehearsal.
          - The golden round trip, the readonly sweep and the reserved-line refusal test all use the predicate.
        - **sched_b / sched_d / f8949** (drafts Created 4/7/26, 4/1/26, 4/1/26): identical topology (72 / 55 / 202 widgets; name, rect, /MaxLen, /AP); only the year text moves (and Schedule B's "country(ies)").
          - Ported with their 2025 maps, relations and cross_form. The same widgets stay unmapped as in 2025 (sched_d's shaded g cells, f8949's Totals (f) cells).
        - **f8833**: the live irs-pdf/f8833.pdf re-downloaded 2026-09-27 is byte-identical to the Rev. 12-2022 pin, so the 2025 pack is copied with tax_year 2026. It is a FINAL pack that is rehearsal-only until JT6.
        - **f1040es** (irs-prior/f1040es--2026.pdf, Created 2/12/26; 16 pages, 118 widgets): all 56 voucher bindings re-read by rect.
          - Vouchers 3/2/1 are on page 15 (f15_1/15/29 blocks) and voucher 4 on page 14 (f14_1..14). The 62 unmapped are the page-12 worksheet (27), the page-13 record (31) and 4 link buttons.
          - `filing_grade_basis: own_final_revision`, so it fills and verifies without rehearsal.
        - **Tests** (`test_jt3d_*`): the rehearsal predicate's four cases; the f8833 pin and its refusal of a normal fill; the 1040-ES position rebind; the three identical-topology maps. test_discovery 124 (11 drafts + 2 finals for 2026); the filer-address fixture gains 5 rows, each equal to its 2025 base.
        - **Per-form tables the new packs reached:** SCHED_D_SHADED_G_WIDGETS[2026] (the /Ff re-read: the same two cells); IDENTITY_MIRROR_COUNTS f8949 2026 = 2. The sched_d / sched_e / f1116 / f8833 pack-parametrized fill checks now pass the rehearsal predicate.
        - **Vision audit:** the 1040-ES voucher pages (14, 15), each value in its box. The other four are field-for-field equal to their audited 2025 packs (pinned by test), and their round trips ran against the 2026 blanks.
  - **Traps.** Key every field by its PRINTED line:
    - 1040 13a and 13b swap meaning. 2025: 13a = QBI, 13b = Schedule 1-A. 2026: 13a = Schedule 1-A line 44, 13b = QBI.
    - The 1040 gains 12f, 24a–c and 32a–c.
    - Form 8959's Part II becomes RRTA and self-employment moves to Part IV, under identical field names.
    - Schedule 2 is renumbered.
    - (Found in JT3a) A FINAL pack in a provisional year (the 2026 f8833 of JT3d) is neither filing-grade nor a draft, so `fill_form` refuses it and `rehearsal=True` refuses it too. The golden round trip needs a decision there: let rehearsal accept a final pack whose year is provisional, or have JT3d record why it is filing-grade.
  - **Relations and cross_form:**
    - f1040: '14 == 12e + 12f + 13a + 13b', '24c == 24a + 24b', '32c == 32a - 32b', '33 == 25d + 26 + 32c';
    - sched_1a: '44 == f1040.13a';
    - f8959: '12 == 7 + 11', '12 == sched_2.17b', '18 == sched_2.11';
    - f8889 → sched_2.13c/13d and sched_1.8f.
  - **Acceptance, per pack.**
    - Vision-audited page by page against the draft, with the trap list and the Created date in its header.
    - Golden round trip in rehearsal mode; cross_form targets resolve; `test_form_lines_resolve` passes for 2026.
    - test_discovery counts updated.
    - f1040es 2026 fills and verifies WITHOUT rehearsal.
- [x] **JF6b — Rewire calc.py's line literals — DONE 2026-09-27** (M; deps JF6a) [DEF-05 + DEF-06 calc part + DEF-08]
  - *As built:*
    - **44 new form_lines keys in every federal pack 2019-2026** (352 entries), read 2026-09-27 off each year's face — the 2026 values off the drafts. An absent line is recorded with its reason and a quote of what the face prints instead.
      - The keys:
        - f1040: wages / qualified dividends / pensions ± taxable / social security ± taxable / capital gain / deduction / taxable income / tax / ctc / eic / actc / sched_1a;
        - f1040nr.sched_1a;
        - Schedule 1: hsa_deduction / se_deduction / student_loan_interest / stock_options / hsa_distributions / hsa_testing_income;
        - Schedule 2: se_tax / additional_medicare (+ _se) / niit / hsa_distribution_tax / hsa_eligibility_tax / ftc_regular_tax_addition;
        - Schedule 3: foreign_tax_credit / dependent_care / excess_ss;
        - sched1a.total; f8959.total_tax; eleven f8889 lines.
      - Each `printed` quote is rebuilt from the face's pypdf text, which is what test_every_entry_quotes_its_face reads. That checker now sets a trailing label aside only when it IS the entry's designator, so "... line 13a 44" checks.
    - **Every calc.py literal renders through form_line.** The FORM_LINE_DEBT calc.py rows are gone, and so is the REBINDING_DEBT row: `_step_part`'s parameter is now `part_line`.
      - Static descriptions name the registry key.
      - `_capital_loss_1040_line` (a Python year table) is gone. A new `calc._face_line(year, key, form)` names a year past the shipped packs without guessing a number.
      - ira_pro_rata, capital_loss_limitation and espp_disposition now use knowledge_dir for form_lines; each had called `del knowledge_dir`.
    - **Real errors fixed:**
      - The 2021 Schedule 1 sends Form 8889 line 16 to 8e and line 20 to 8z; the op printed 8f.
      - From 2024 Form 1116 line 20 adds Schedule 2 line 1z, not line 2 (i1116 2019-2025 read).
      - ESPP income for a 2021 sale goes on 8j; for 2019/2020 on the unlettered other-income line.
      - The HSA and Additional Medicare 2026 text now says 13c/13d, 17b + 11 and NIIT 6.
      - Form 8959's withholding reconciliation is "Part V", not "Part IV".
      - The EIC line is 18a / 27 / 27a by year, and AGI is 11a for 2025.
    - **Tests** (test_form_lines `test_jf6b_*`):
      - JF6B_EXPECTED over 8 years;
      - the surtax, HSA, EIC, FTC and capital-loss work strings;
      - no calc.py debt left.
      - test_tax_calc's 2026 HSA assertion was flipped to 13c.
  - **Schedule 2 destinations.** calc.py:711/732/815 ("line 11"), :830/840/894 ("line 12") and :5349-5350/5411/5413/6071-6073/6099 ("Part II line 17c/17d").
    - The draft 2026 Schedule 2 (Created 4/27/26) prints NIIT on 6, Additional Medicare on SE income on 11, the HSA taxes on 13c/13d, and Additional Medicare on wages on 17b. Line 12 is now the §965 liability.
    - The draft 2026 Form 8959 sends line 12 → 17b and line 18 → 11.
    - The 2019/2020 finals print "8 Taxes from: a Form 8959 b Form 8960".
    - test_tax_calc.py:3442 asserts the wrong 2026 text; flip it.
  - **Form 1040 references.** Stale for TY2025: AGI "line 11" (now 11a), standard deduction "line 12" (12e), EIC "line 27" (27a) — calc.py:2325/2520/2530/2555/2677/2776/2810/3419-3421/3448/3501. Read the 2019 and 2021 EIC lines off their faces (the review did not).
  - **Form 8959 Part V.** The withholding reconciliation is cited as "Part IV" (calc.py:764-766, :816); it is Part V on the 2023, 2025 and 2026 faces. Read 2019–2022 before encoding.
  - **Capital-loss destination.** `calc._capital_loss_1040_line` is a Python year table ('7a' if year >= 2025 else '7'), which is exactly what the registry replaces. The guard's field rule carries its three uses (in `_schedule_d_citation`, `_capital_loss_one_year` and `capital_loss_limitation`) as debt rows. The 2019 face sends Schedule D line 21 to Form 1040 line 6 (f1040sd--2019.pdf, read 2026-09-24); nothing prints it wrong today because capital_loss_limitation refuses years before 2022. Replace the helper with a `form_line` key read off each year's face.
  - **Name clash.** calc.py's Schedule 1-A line model has a `form_line` field, and its line helper has a `form_line: str` parameter (calc.py:2937, :3088). Rename the parameter when calc.py imports `knowledge.form_line`. The guard's `test_form_line_in_the_guarded_modules_is_the_registry_helper` allows the class field and carries the parameter as its one `REBINDING_DEBT` row (self-clearing); it refuses every other def / assignment / import / parameter / except-as / match binding of `form_line` or `knowledge`.
  - **Not forced by the guard.** About 50 literals sit outside the ROADMAP regex's prefixes: Schedule D lines 6/7/14/15/16/21 (incl. "Schedule D line 8b/1b/9/2" in `capital_loss_limitation`), Form 8606, Form 1116, Form 8960 line 17, "Schedule SE line 6" (calc), "Schedule C line 31" (estimate) and "Schedule 8812 line 3". JF3's Schedule SE label (`sched_se.ss_wages`) is therefore NOT guard-enforced until the prefixes widen. Other known gaps: a named %-format, a literal split across a `join`, a letter appended after a trusted field, a capitalised "Line" or a newline before "line". JF6c: widen the prefix alternation (at least Schedule SE / D / C / 8812, Forms 8606 / 1116 / 8960) once JF6b/JF6c have shrunk the debt, and pin each gap it closes with a probe.
  - **Acceptance.**
    - Parametrized over 2019–2026: the additional_medicare_tax / niit / hsa_deduction work strings equal their `form_line` values. For 2026 that is 17b + 11, 6, and 13c/13d; for 2019/2020, 8a/8b.
    - `eitc(…, 2025).work` contains "27a"; "Part V" appears wherever the face says so.
    - The frozen debt list has no calc.py entries left.
- [x] **JF6c — Rewire the other sites and the Schedule 1-A keys — DONE 2026-09-27** (M; deps JF6b) [DEF-06 rest + DEF-07 + the line half of LD-08]
  - *As built:*
    - **Seven more keys in every federal pack, read 2026-09-27:**
      - `f1040nr.taxable_interest` (9a in 2019, then 2b);
      - `f1040nr.itemized` (37 / 12 / 12a in 2021 / 12 / 12a in 2026);
      - `f1040nr.agi` (35 / 11 / 11a from 2025);
      - the Schedule 1-A part totals `sched1a.tips` / `.overtime` / `.car_loan` / `.senior` (13/21/30/37 for 2025, 15/27/36/43 on the 2026 draft; absent before 2025).
    - **Rewired through form_line:**
      - the planning-year intake question (the prior year's `f1040.agi` / `f1040.total_tax`, so 2026 asks for "11a");
      - the 1040-NR deposit-interest texts in intake and estimate;
      - the 1040-NR itemized-only note;
      - the server.py calc docs, including the 1116 line 20 note, now "the Schedule 2 amount the year's instructions name".
    - **Rephrased as registry keys:** schemas/profile.py's prior-year fields and workspace.py's Position example.
    - **Schedule 1-A:** `schedule_1a_deductions` takes its part keys from the registry. The 2025 keys stay ['13','21','30','37'].
    - **Debt:** FORM_LINE_DEBT and REBINDING_DEBT are empty.
    - **New `test_form_lines_resolve`:** every key the guarded modules and statements.py pass to form_line resolves in every shipped year.
    - **2026 total tax:** `f1040.total_tax` for 2026 is now recorded ABSENT with the reason. The draft prints 24a "This is your total tax" and 24c = 24a + 24b, and which one §6654 reads is unverified until JT6; nothing reads it before tax year 2027.
  - intake.py:1172-1179 asks a planning-year user for "line 11" of the prior return. Also fix schemas/profile.py:477-492, server.py:211/344/386-392 and workspace.py:81, and the Form 1040-NR itemized "line 12" (estimate.py:1033/1223/1717), which becomes 12a in 2026.
  - schedule_1a_deductions hardcodes form_line keys 13/21/30/37 and "line 38 → 1040 13b / 1040-NR 13c" (calc.py:2937-2940, :2962-2965, :3129-3180; server.py:396). These key verify_form's recompute.
  - The draft 2026 Schedule 1-A (Created 6/16/26) totals on 15/27/36/43 → 44 → 1040/1040-NR 13a, with rounding lines 13/25/34. Data-drive the keys.
  - The 2026 total-tax line for the §6654 prior-year prong (24a vs 24c) is UNVERIFIED; leave it absent until JT6.
  - **Acceptance.**
    - The 2026 planning-year intake question contains "11a".
    - 2025 Schedule 1-A form_line keys stay ['13','21','30','37']; 2026 data has `sched1a.car_loan == '36'` and `f1040.sched_1a == '13a'`.
    - The frozen debt list is empty; `test_form_lines_resolve` passes for every year that has packs.
- [x] **JF7 — Schedule 1-A reaches the estimator — DONE 2026-09-27** (M; deps JF6c, JF1b) [LD-09]
  - *As built:*
    - **Inputs:** IncomeSnapshot gains `qualified_tips`, `qualified_overtime_premium` and `car_loan_interest` (summed on the joint view), plus `senior_taxpayer` / `senior_spouse`.
      - estimate_refund derives the senior flags from the profile: 65 by year end — born before January 2 of year - 64 — and a 9-digit SSN, never an ITIN. The caller can override them.
      - The spouse snapshot's own flag becomes the joint view's `senior_spouse`, counted on MFJ only.
    - **_bottom_line:** calls schedule_1a_deductions with MAGI = AGI (the Part I add-backs are not modeled, and the assumption says so). Its new EXPLANATORY slot `schedule_1a_deductions` sits between `deduction` and `taxable_income`, labeled "Form 1040 line <form_line f1040.sched_1a>" (or 1040-NR). Taxable income = AGI - deduction - Schedule 1-A.
    - **MFS:** the forfeiture flows through every candidate status via the op, and the assumption names it.
    - **Years without the block:** 2025-2028 without it → `MissingBlock('tax.obbba_schedule_1a', understates_refund)` plus NOT ESTIMATED. Before 2025 → "2025-2028 only", no block.
    - **Docs:** server.py's estimate_refund documents the fields.
    - **Tests:**
      - test_estimate `test_jf7_*` (5): the op-total equality, MFS forfeiture, the planning-year MissingBlock, pre-2025, and senior from DOB/SSN/ITIN;
      - the ledger property suite draws the new fields;
      - a compare_scenarios tips what-if attributes its delta.
  - **Why.** estimate_refund has no below-AGI input: nothing in estimate.py or scenarios.py references schedule_1a/obbba (IncomeSnapshot, estimate.py:100-198). Both workarounds are wrong:
    - `pre_agi_adjustments` lowers AGI, which moves every MAGI test;
    - `itemized_deductions` is max()'d against the standard deduction, wrong for a non-itemizer.
    
    TY2025 estimates for tipped, overtime, car-loan and senior filers overstate tax with no disclosure.
  - **Build.**
    - Add `qualified_tips`, `qualified_overtime_premium` and `car_loan_interest`; the seniors count comes from profile DOB and SSN.
    - `_bottom_line` calls schedule_1a_deductions with MAGI = AGI plus the modeled add-backs.
    - A `schedule_1a_deductions` slot between `deduction` and `taxable_income`, labeled from `form_line`.
    - The MFS forfeiture flows through the candidate statuses.
    - A year without the block, with an input engaged → `MissingBlock('tax.obbba_schedule_1a', direction='understates_refund')`.
  - **Acceptance.**
    - TY2025 single with the three inputs → taxable income lower by exactly the op's total.
    - The MFS candidate forfeits tips, overtime and senior but not car-loan interest.
    - 2026 with an input → the MissingBlock (until JF8).
    - The 240-profile property suite and the compare_scenarios tests are extended and green.
- [x] **JF8 — Schedule 1-A for 2026, and Form 1098-VLI — DONE 2026-09-27** (M; deps JT0b, JF6c, JF7)
  - *As built:*
    - **tax.obbba_schedule_1a for 2026:**
      - Pass 1 is the statute (IRC 224(b)/(h), 225(b)/(g), 163(h)(4)(A)-(D), 151(d)(5)(C), quoted in the block header, read 2026-09-27 at uscode.house.gov). Every figure is unindexed and equals 2025's (test-pinned).
      - Pass 2 is two `second_passes` entries: the FINAL W-4 (2026) Step 4(b) worksheet, and the DRAFT Schedule 1-A (Created 6/16/26) for the slopes, the rounding and "born before January 2, 1962". The pack's singular `second_pass` became the list.
      - Dropped from blocks_deliberately_absent and the 2026 header's outstanding list. Its effective_law_changes entry now cites the statute with `modeled: true`, fixing G28: it had carried a copy of the Pub 15 supplemental-wage citation.
      - A new invariant: no two FEDERAL law-change entries share a citation. State booklets are the declared exception, since one What's New page lists several changes.
    - **`senior_deduction.born_before`** (a date: 1961-01-02 for 2025, 1962-01-02 for 2026) is test-pinned to IRC 151(d)(5)(C)(ii)'s age-65 rule and to the printed requirement. The op's error, docstring, estimator note and server doc no longer carry a 1961 literal.
    - **Found and fixed:** schedule_1a_deductions' work printed the 2025 Part ranges ("lines 4-13", "14-21", "22-30", "31-37") and "VIN on line 22" for every year.
      - Both now derive from the year's form_lines Part totals: 2026 prints 4-15 / 16-27 / 28-36 / 37-43, VIN on 28. The loan date comes from the block too.
      - The JF6a guard missed these because "Schedule 1-A" was not within 15 characters of "line".
    - **Form 1098-VLI DocSpec** (28 kinds): source irs-pdf/f1098vli.pdf, the final Rev. December 2026 (the About page and irs.gov/Form1098VLI 404).
      - Boxes 1, 2a-2d, 3a/3b, 4, 5, 6, 7 plus the lender/payer TINs and the account number.
      - The status note quotes 163(h)(4)(B)(i)/(iii) and (D) for boxes 3a/2d/6/7, and box 5's "Do not deduct this amount".
      - Checks: V19 (a 17-character VIN), V20 (box 6/7 unchecked → not qualified), V21 (loan on/before 2024-12-31).
      - The form_1098vli sources topic gains the final form; route sweep 0/258 changed.
    - **Tests:**
      - test_schedule_1a `test_jf8_*`: statute = block = 2025; the born-before rule for 2025/2026; 2026 goldens for all four parts (including line 34's round-up); car-loan interest above the phase-out → $0 with the work; the 2025 work unchanged.
      - test_extract `test_jf8_1098vli_*`; test_knowledge's citation invariant.
      - test_estimate: the JF7 missing-block test moves to a synthetic planning pack, and 2026 now prices Schedule 1-A with no MissingBlock (line 13a in the label).
  1. **The 2026 block** [LD-08 + TY26-06 + G28].
     - `tax.obbba_schedule_1a` is declared absent for 2026 (2026.yaml:81), yet the figures are statutory and unindexed:
       - 163(h)(4)(C): $10,000 / $100,000 ($200,000 joint) / $200 per $1,000;
       - 224(b): $25,000 / $150,000 ($300,000);
       - 225(b): $12,500 ($25,000);
       - 151(d)(5)(C): $6,000 / 6% / $75,000 ($150,000).
     - They are printed on the draft 2026 Schedule 1-A and on the FINAL Form W-4 (2026) Step 4(b).
     - Author the block: pass 1 the statute; pass 2 the final W-4 plus the draft, recorded in second_passes.
     - Replace the "January 2, 1961" literals (calc.py:3008/3048; server.py:378) with `senior_born_before` data: 1961-01-02 for 2025; for 2026 "born before January 2, 1962".
     - Drop the block from blocks_deliberately_absent, and set its effective_law_changes entry to `modeled: true`.
     - Replace the copy-pasted Pub 15 citation at 2026.yaml:519-548 (G28), and add an invariant that no two effective_law_changes entries share an identical citation.source unless declared.
     - Add a line to the Dec checklist: re-verify against the final form.
  2. **Form 1098-VLI DocSpec** [TY26-25]. The form is dated December 2026 (irs-pdf/f1098vli.pdf).
     - Boxes: 1, 2a–2d (year / make / model / VIN), 3a/3b, 4, 5, 6 (original use), 7 (US final assembly).
     - The status note maps boxes 6, 7 and 3a to the Schedule 1-A eligibility keys; the DocSpec feeds schedule_1a_deductions.
  - **Acceptance.**
    - 2026 figures equal the statute and the 2025 block.
    - 2026 goldens for all four parts, including line 34's "increase the result to the next higher whole number".
    - Car-loan interest above the phase-out → $0 with the work shown, not a refusal.
    - JF7's MissingBlock disappears for 2026; eval i2 passes via the planning_year fixture.
    - A 1098-VLI round trip.
- [x] **JF9 — The 2026 charitable deduction and its characterization rules — DONE 2026-09-27** (M; deps JT0b, JF7, JF2) [LD-06 + DEF-18 + TY26-17 + LD-07] — pitfall *charitable-characterization* = **P-022**
  - *As built:*
    - **Sources read 2026-09-27:**
      - IRC 170(p) and 170(b)(1)(I) (uscode.house.gov, with the §70424(b)/§70425(c) "after December 31, 2025" notes; its prelim text drops 170(p)'s "$" before 1,000);
      - the TEOS deductibility-code table; Rev. Proc. 2025-32 §4.33(2) ($13.90 / $69.50 / $139);
      - Pub 526 (2025)'s "$75 or less" membership text; IRC 6115(a); 170(f)(8)(A)/(C); 170(f)(17);
      - IRS INFO 2010-0172 (the plaque sentence; an information letter, labeled not a ruling);
      - the final W-4 (2026) lines 12 and 6d; the draft 1040 line 12f and 1040-NR line 12b.
    - **Knowledge:**
      - A top-level `charitable_contributions` 2026 block (typed CharitableContributionsParams): the cap by status, cash only, eligible TEOS PC/POF/FED, excluded SO/SONFI/SOUNK and DAFs, the 0.005 floor, the three Rev. Proc. figures (quoted so the cents survive YAML), $75 / $75 / $250.
      - It maps to JF2's charitable_nonitemizer topic in the sources-coverage rule, and its effective_law_changes entry is `modeled: true`.
      - form_lines `f1040.charitable_nonitemizer` in EVERY year, as the resolve rule requires: 10b in 2020 (the CARES Act adjustment) and 12b in 2021 (the CAA 2021 deduction), neither IRC 170(p); absent in 2019 and 2022-2025; 12f on the 2026 draft.
      - `f1040nr.charitable_nonitemizer` 12b for 2026 only.
    - **Op `calc.charitable_deduction`** (36 ops):
      - Per-gift deductible amounts under the P-022 rules. Recognition only keeps the full amount; a membership of $75 or less is disregarded; token items and benefits within 2% or $139 are insubstantial; otherwise the benefit's value comes off, and a payment over $75 whose benefit value is not stated is refused (the 6115 statement).
      - The 170(f)(8) and 170(f)(17) duties; 170(p) payee eligibility (a "depends" TEOS code needs `donee_170b1a`); the cap; the 0.5% floor; the better path.
      - Refuses a year before 2026. Server docs and all three skills carry it.
    - **Estimator:** `charitable_cash_nonitemizer` (summed on the joint view) and slot `nonitemizer_charitable_deduction`.
      - The method choice is itemized vs standard + the capped 170(p) amount, and taxable income drops by it (Form 1040 line from form_lines).
      - Disclosures: itemizing won (the input is unused, and the itemized figure must already net the floor); 2025 ignored; a planning pack without the block → MissingBlock + NOT ESTIMATED; a 1040-NR / dual-status return → NOT ESTIMATED.
    - **Tests** (test_charitable_deduction `test_p022_*`): the block's figures, the pre-2026 refusal, the cap and payee exclusions, the "depends" determination, every characterization rule, the membership refusal, the substantiation duties, the floor and the better path, the estimator's $600 / $1,400→$1,000 / itemize-wins / 2025 / planning-pack cases.
  1. **The deduction.**
     - Nothing models IRC 170(p) (P.L. 119-21 §70424, "taxable years beginning after December 31, 2025"): "not in excess of $1,000 ($2,000 in the case of a joint return)", cash "to an organization described in section 170(b)(1)(A) and not- (1) … 509(a)(3), or (2) … donor advised fund". Draft 2026 Form 1040 line 12f; draft 1040-NR line 12b.
     - Nor the 0.5% itemizer floor (170(b)(1)(I)).
     - **Knowledge:** a top-level `charitable_contributions` 2026 block:
       - the caps and the cash-only rule;
       - excluded payees: TEOS codes SO / SONFI / SOUNK, and DAFs;
       - the 0.005 floor;
       - insubstantial-benefit figures $13.90 / $69.50 / $139 (Rev. Proc. 2025-32 §4.33);
       - the $75 membership disregard, the $250 contemporaneous written acknowledgment, the $75 quid-pro-quo threshold;
       - form_lines 12f / 12b (draft).
       
       Pass 2 is the final W-4 (2026) Deductions Worksheet lines 12 and 6d.
     - **Op:** `calc.charitable_deduction(year, filing_status, gifts[…])`. It returns per-gift deductible amounts, the substantiation duties, the 170(p) amount, the floor-reduced itemized amount, and which path wins against the standard deduction. It refuses before 2026.
     - **Estimator:** field `charitable_cash_nonitemizer` and slot `nonitemizer_charitable_deduction`, applied only when the standard deduction wins. A year without the block → MissingBlock plus NOT ESTIMATED.
  2. **Characterization rules.** The pitfall quotes each one, and the op's work string repeats them:
     - Pub 526's $75 membership-benefit disregard ("in return for an annual payment of $75 or less");
     - IRC 6115 for payments over $75;
     - the 170(f)(8)(A) acknowledgment for gifts of $250 or more;
     - donor recognition is not a return benefit (IRS INFO 2010-0172, labeled non-precedential);
     - the payee-entity check via TEOS.
  - **Acceptance** (*illustrative*).
    - 2026 single: $600 of qualifying cash → taxable income $600 lower; $1,400 → capped at $1,000.
    - 2025 → the input is ignored, with a disclosure.
    - A membership payment over $75 with no statement of the benefit's value → refused, prescribing that statement.
    - `recognition_only` → zero benefit; a gift of $250 or more flags the acknowledgment.
    - SO / SONFI / SOUNK / DAF payees are excluded from 170(p).
    - NRA path: NOT ESTIMATED until the 2026 1040-NR instructions settle eligibility (IRC 873 not read).
    - Op count +1; the pitfall has citing tests.
- [x] **JT1a — PTC 2026: the cliff returns — DONE 2026-09-27** (M; deps JT0b) [TY26-12]
  - *As built:*
    - **Schema:** `no_400_pct_cliff: false` REQUIRES a bounded top band (and `true` an open one), and an empty `repayment_limitation` means no limitation at any FPL.
    - **tax.ptc for 2026:**
      - Rev. Proc. 2025-25 §3.01's six bands: 2.10% up to 9.96%, the top band "not more than 400%" = fpl_pct_less_than 401 on the integer line 5.
      - The 2025 HHS Poverty Guidelines (FR Doc. 2025-01377): $15,650 + $5,500, AK $19,550 + $6,880, HI $17,990 + $6,330.
      - `repayment_limitation: []` (Rev. Proc. 2025-32 §2.04: OBBBA §71305 removes 36B(f)(2)(B)).
      - The draft Form 8962 (Created 4/21/26) is a draft second pass for the cliff (line 6 "Did you enter 401%?" / "You are not eligible") and the reserved lines 28-29. The posted draft i8962 still prints the 2024 guidelines ("For 2025, the 2024 federal poverty lines are used"), so it is not a source.
      - ptc leaves blocks_deliberately_absent, with a modeled effective_law_changes entry.
    - **Op:** over the bounded table no band applies. ptc_annual and ptc_monthly return PTC $0 with a null figure and contribution, and the settle text quotes §2.04 for the uncapped repayment.
    - **Found and fixed:** the 401 test truncated first. Worksheet 2 compares the UNTRUNCATED income with 400% of the FPL, so 400.006% is 401. Harmless while 400 and 401 priced the same; the 2026 cliff turns on it.
    - **Docs:** the server doc and the op docstring said 2023-2024 and "NO eligibility cliff".
    - **Tests** (test_tax_calc `test_jt1a_*`): the 2026 table and FPL; 399 / 400 / 401% (1,781 / 1,765 / $0); the untruncated 401 in 2025 and 2026; the uncapped repayment below 200% and over 400%; the monthly method over the cliff; the schema pairing both ways.
  - **Why.**
    - Rev. Proc. 2025-25's 2026 table has no open top band ("At least 300% but not more than 400% 9.96%").
    - Rev. Proc. 2025-32 §2.04: §71305 "removes § 36B(f)(2)(B)".
    - The draft Form 8962 line 6 asks "Did you enter 401%?".
    - The engine requires an open last band (knowledge.py:854-858); `no_400_pct_cliff` has no reader (:838); and calc.py:1866's settle text is wrong for 2026.
  - **Build.**
    - Allow a bounded last band: FPL above 400% → PTC $0 and full repayment.
    - `repayment_limitation: []` means no limitation at any FPL.
    - Author 2026 `ptc`: Rev. Proc. 2025-25 plus the 2025 HHS guidelines, with the draft 8962 as pass 2.
  - **Acceptance:** tests at 399 / 400 / 401% FPL, plus an uncapped repayment.
- [x] **JT1b — Dependent care 2026 — DONE 2026-09-27** (M; deps JT0b) [TY26-11]
  - *As built:*
    - **Schema:** `DependentCarePhaseDown.applies_to` (all | joint | non_joint) and `DependentCareParams.legs_for(status)`. The contiguity and no-overlap checks run separately over the joint and the non-joint slide; the op filters the legs by filing status.
    - **tax.dependent_care for 2026:**
      - Read off IRC 21(a)(2) as amended by P.L. 119-21 §70405 (quoted in the block): .50 → .35 over $15,000 per $2,000; then .35 → .20 over $150,000 per $4,000 joint / over $75,000 per $2,000 otherwise.
      - IRC 21(c)'s $3,000 / $6,000 and 21(d)(2)'s $250 / $500 are unchanged. IRC 129(a)(2)(A) (§70404) gives $7,500 ($3,750 MFS), the draft Form 2441 (Created 4/30/26) line 21.
      - Pass 2 is the draft 2026 i2441's "2026 Phaseout Schedule". dependent_care leaves blocks_deliberately_absent, with a modeled effective_law_changes entry.
    - **Docs:** the op docstrings and the server doc now carry the 2026 slide.
    - **Tests** (test_tax_calc `test_jt1b_*`): EVERY row of the draft schedule, both columns, at each row's "over + 1" and "not over" AGI (joint, HoH, single); the block and exclusion; 2025 unchanged; joint .35 vs single .27 at $90,000.
  - **Why.** The draft i2441 line 8 table's second phase-down leg depends on filing status: joint from $150,000 in $4,000 steps, others from $75,000 in $2,000 steps. The rate "ranges from 50% to 20%", and line 21 is $7,500 ($3,750 MFS). DependentCarePhaseDown (knowledge.py:908-950) and calc.py:2697-2714 have no status key.
  - **Build:** `applies_to: all | joint | non_joint`, then author 2026.
  - **Acceptance:** goldens for every row of the draft table.
- [x] **JT1c — The Schedule 3-A gate (federal public benefit) — DONE 2026-09-27** (M; deps JT0b) [TY26-18] — pitfall *public-benefit-qualified-alien* = **P-023**
  - *As built:*
    - **Sources read 2026-09-27:**
      - the draft Schedule 3-A (Created 6/24/26): lines 1a-8, and its caution — the schedule is completed "only if you are claiming the earned income credit (EIC), additional child tax credit (ACTC), refundable American opportunity credit, or refundable adoption credit";
      - the rule behind it, **REG-119882-25** (91 FR 53812, Aug. 20, 2026; comments closed 2026-10-05, hearing 2026-10-14), a PROPOSED rule, every quote checked against the published Federal Register text: proposed Treas. Reg. 1.23-2, 1.24-3, 1.25A-7 and 1.32-4 — the refunded portion is the SUM of the four credits over "the tax imposed on the taxpayer by subtitle A of the Code (reduced by credits allowable under subparts A, B, D, and G …)"; status is judged "on the date the taxpayer files the taxpayer's return"; one qualifying spouse is enough on a joint return; withholding stays refundable (1.23-2(f)(8)); it is "proposed to apply for taxable years ending on or after the date these regulations are published as final regulations";
      - 8 U.S.C. 1641(b)-(c). **Correction to the spec above:** 1641(c)(4) DOES name a nonimmigrant status — "an alien who has been granted nonimmigrant status under section 101(a)(15)(T)" — so the sources.yaml answer that said no nonimmigrant category is listed was wrong and is fixed. The proposed definition cites 1641(b) only, while 1641(c) says "For purposes of this chapter, the term 'qualified alien' includes" its categories: kept as an open reading.
      - The Schedule 3-A instructions are not posted (irs-dft/i1040s3a--dft.pdf 404; the posted i1040gi draft is still the 2025 one).
    - **Knowledge:** a top-level `federal_public_benefit` 2026 block (typed FederalPublicBenefitParams): rule_status (only `proposed` validates — a final rule belongs in the point), the applicability, the four credits by ledger slot, the refunded-portion, joint-return, filing-date and definition quotes, the schedule's lines, the eight 1641(b) categories and the two 1641(c) ones apart. A federal pack from 2026 with a credits block and no federal_public_benefit block is refused at load. It maps to the federal_public_benefit sources topic, which gains the Federal Register entry.
    - **Profile:** `identity.qualified_alien_status` and `household.spouse.qualified_alien_status` — us_citizen, us_national, the 1641(b) ids, battered_alien, t_nonimmigrant, none_of_these.
    - **Estimator:** each return's Schedule 3-A figure (BottomLineResult.federal_public_benefit; the two-return MFS pair keeps the spouse's own) is the affected credits over the total tax less the Section B wage part of the Additional Medicare Tax. Each person's answer: the recorded status, else us_person True (a citizen or green-card holder), else the latest visa status (T → 1641(c)(4), a reading; any other nonimmigrant class → on neither list), else unknown. With no one on the return qualifying, the LOW end holds the amount back and the point keeps it; the note quotes the rule, and an unrecorded answer adds a what-would-change item. Server docs and SKILL.md carry it. No intake question: the estimator asks only when the amount is non-zero.
    - **Tests** (test_public_benefit `test_p023_*`, on a knowledge copy whose 2026 pack borrows the 2025 credits block until JT1d): the block's quotes and the profile ids; the load refusal and the rule_status gate; an H-1B household with ACTC + EIC (the low end drops exactly the refunded portion and keeps the withholding refund); an LPR household and a recorded refugee unchanged; the 1641(c) readings; one qualifying spouse on a joint return; the unrecorded answer; the Section B wage tax left out of the liability; nothing before 2026.
  - **Left for JT6:** re-read the final Schedule 3-A and its instructions (the qualified-alien definition they adopt), and the final rule if it publishes — a final rule moves the forfeiture into the point.
- [x] **JT1d — Credits 2026 — DONE 2026-09-27** (M; deps JT1c) [TY26-08]
  - *As built:*
    - **Sources read 2026-09-27:** Rev. Proc. 2025-32 §4.05 ($2,200; the refundable $1,700) and §4.06 (the EITC table, the $12,200 investment-income limit); IRC 24(h)(2)-(7) and the new 24(i) (the $2,200 indexed after 2025, increases "rounded to the next lowest multiple of $100"); IRC 32(b)(1); the draft Schedule 8812 (Form 1040) 2026 (Created 4/24/26) and its draft instructions, which print the same CTC figures, the $2,500 earned-income floor and the joint-return SSN rule.
    - **Knowledge:** a top-level 2026 `credits` block — child_tax_credit (2,200 / 1,700 / the $500 ODC, the $400,000 / $200,000 thresholds, the 24(h)(7) SSN rule quoted), foreign_tax_credit (the 904(j) $300 / $600, cited to the statute since the 2026 Form 1116 instructions are not posted) and earned_income_tax_credit (the §4.06 table). `credits` leaves blocks_deliberately_absent; a law entry cites IRC 24 (modeled). The JT1c rule holds: the pack carries federal_public_benefit beside it.
    - **Second pass:** the CTC figures match the draft Schedule 8812 (a draft pass). The EITC figures match the draft Pub 1040 (2026), Tax and Earned Income Credit Tables (Aug 28, 2026): every one of its 11,176 EIC Table cells reproduces from the block with the IRC 32(b)(1) percentages. The tests also check IRC 32(b)(1)'s own arithmetic (each maximum = earned income amount x credit percentage; each completed phaseout = threshold + maximum / phaseout percentage, within $1). JT6 re-reads the final table.
    - **Found doing that pass:** the engine's `eitc` op prices by a ratio (maximum / earned income amount), not the table's percentages, and misses 327 of the 2026 cells by $1 — and 1.6% to 10.4% of each final 2019-2025 table's cells (2025: 647 of 10,928). Fixed in its own commit after JT1e ("the EITC is the EIC Table").
    - **Tests:** test_tax_calc `test_jt1d_*` (every figure, the 32(b) arithmetic per row, the 2026 child_tax_credit and eitc ops); test_estimate `test_jt1d_the_2026_estimate_prices_the_family_credits`. test_public_benefit now runs on the shipped 2026 pack (its borrowed-credits fixture is gone).
    - eval i5 and the ledger tests keep stripping the block through the JT0b fixture (synthetic_provisional_pack(["credits"])), so they test the absent-block path whatever ships.
- [x] **JT1e — Education credits 2026 — DONE 2026-09-27** (M; deps JT1c) [TY26-10] — pitfall *education-ssn-deadline* = **P-024**
  - *As built:*
    - **Sources read 2026-09-27:** IRC 25A(b)(1), (c)(1), (d)(1), (g)(1) and (i) (uscode.house.gov), with P.L. 119-21 §70606(c) ("shall apply to taxable years beginning after December 31, 2025"); the draft Form 8863 (2026) (Created 4/28/26) — "A valid social security number (SSN) is now required to claim an education credit", lines 2 and 13 "$180,000 … $90,000" — and its draft instructions (What's New, Table 1, the identification requirement).
    - **Two readings recorded:** the statute says "such individual's social security number"; the draft instructions say "only one spouse is required to have a valid SSN" on a joint return. The block records the instructions' reading (`one_spouse_suffices_on_joint_return: true`) with both quoted; JT6 re-reads the final instructions.
    - **Knowledge:** the 2026 `tax.education_credits` block (the statutory, unindexed amounts and MAGI range, cited to IRC 25A) with the new `ssn_requirement` (EducationSsnRequirement). A federal education block from 2026 without it is refused at load. education_credits leaves blocks_deliberately_absent.
    - **Calc:** op education_credits names the rule in its work for a year that carries it (eligibility stays the caller's judgment).
    - **Estimator:** `education_ssn_taxpayer` / `education_ssn_spouse` (derived from the profile's tax IDs: an SSN, an ITIN (starts with 9), or not recorded) and `aotc_students_ssn_ok` per student. No credit on an ITIN (both spouses' on a joint return) or to an ITIN-only dependent student; NOT ESTIMATED when the filer's or a student's answer is not recorded. The joint view pads the per-student answers and keeps each person's flag, like the senior flags; the field-coverage test classifies all three.
    - **Tests** (test_education_2026 `test_p024_*`): the block's quotes; the load refusal; the op's 2026 phase-out and rule text; an SSN vs an ITIN filer; an ITIN-only student → no AOTC; an unknown status → NOT ESTIMATED; one spouse's SSN is enough on a joint return; 2025 keeps no gate.
    - "Valid for employment" is not on the profile (an SSN card's legend), so it is disclosed, not tested.
- [x] **JT1d+ — The EITC is the EIC Table (2019-2026) — DONE 2026-09-27** (found by the JT1d second pass)
  - **Why.** calc op `eitc` and the estimator priced the credit by a ratio (maximum / earned income amount in, maximum / phase-out range out). A filer copies the printed EIC Table's figure, and the ratio missed 1.6% to 10.4% of each year's cells by $1 (2025: 647 of 10,928).
  - **The table's construction, read off ~80,000 printed cells (2026-09-27):**
    - each $50 band is priced at its midpoint with the IRC 32(b)(1) percentages (2021: IRC 32(n)(3), 15.3% with no qualifying child);
    - the phase-in is capped at the printed maximum;
    - past the threshold, the phase-out is taken from the printed maximum in the 2024-2026 tables and from the unrounded one (credit rate x earned income amount) in the 2019-2023 tables;
    - a band that holds the earned income amount or the threshold prints the maximum.
    
    With that, every cell of the 2019-2025 final tables (Instructions for Form 1040) and of the draft 2026 table (Pub 1040 (2026), Aug 28, 2026) reproduces.
  - **Built:**
    - Each year's EITC rows carry credit_rate / phaseout_rate, with an `eic_table` block (band width, phase-out base, what was verified, the table's URL).
    - `calc.eic_table_amount` / `eic_table_credit` implement EIC Worksheet A: the table on earned income, and the smaller of that and the table on AGI when AGI differs and is at or over the threshold. The op and the estimator use them; the label reads "EIC Table". A pack without the rule keeps the ratio, disclosed.
  - **Tests:**
    - test_tax_calc `test_the_eitc_is_the_eic_table` (printed cells the ratio missed, and the kink bands);
    - `test_every_year_carries_the_eic_table_rule`;
    - `test_worksheet_a_takes_the_smaller_of_the_two_lookups`;
    - the network `test_every_cell_of_the_printed_eic_table`, all eight years (it re-downloads the 2026 draft, so the final's table is checked the day it posts).
    - The old tests now pin the printed values.
- [x] **JT2a — Tax Table, SALT/itemized, student loan, Social Security — DONE 2026-09-27** (M; deps JT0b) [TY26-05, TY26-07, TY26-09, TY26-13]
  - *As built (sources read 2026-09-27):*
    - **Tax Table.** The draft Pub 1040 (2026) (Aug 28, 2026) agrees with the engine on all 8,248 cells (2,062 rows x 4; the spec's 8,240 was a miscount). Recorded as a draft second pass on tax_table.row_bands, with its citation updated. Goldens at every row-width edge ($5 / $10 / $25 / $50) and at $99,950.
    - **SALT.** tax.salt_cap from IRC 164(b)(7) (P.L. 119-21 §70120): $40,400 / $20,200 MFS, over $505,000 / $252,500 reduced 30%, floor $10,000 ($5,000 MFS). Checked against the draft Schedule A (Created 5/12/26) line 5e. Data, as in 2025; a law entry.
    - **The discipline test** (test_jt2a_every_prior_year_block_is_present_or_declared_absent): a planning pack carries each block the year before carried, or declares it absent. It found only salt_cap.
    - **Itemized 2026.** tax.itemized_limitation from IRC 68 as rewritten by P.L. 119-21 §70111 (2/37 of the lesser of the deductions or the taxable income over the 37% bracket start), with the draft line 18 screen, "$384,350". The worksheet stays a lookup path (i1040sa (2026) not posted). The estimator DISCLOSES the screen when an itemizer's AGI less the Schedule 1-A deductions is over it, and does not price the reduction. Its law entry is irs_guidance_pending, modeled false. The 0.5% floor rides in charitable_contributions (JF9). The block is named `itemized_limitation`, not `itemized_2026`: a key does not carry its year.
    - **Student loan interest.** Rev. Proc. 2025-32 §4.29: $85,000-$100,000 / $175,000-$205,000 (the joint range is $30,000 wide).
    - **Taxable Social Security.** IRC 86(c)'s statutory amounts, checked against the draft Pub 915 (2026) (Aug 17, 2026). Recorded as a draft pass.
    - taxable_social_security and student_loan_interest leave blocks_deliberately_absent; what remains is filing_thresholds, payment_options, mailing_addresses and deadlines (JT2b, JT6).
  - **Tests:** test_tax_calc `test_jt2a_*` (the Tax Table edges, the blocks and passes, the discipline test, the 2026 student-loan and Social Security ops); test_estimate `test_jt2a_the_2026_itemized_limitation_is_disclosed_at_the_screen`.
- [x] **JT2b — Deadlines, payment options, with-payment addresses — DONE 2026-09-27** (S–M; deps JT0b) [TY26-14 + the rest of TY26-15]
  - *As built (read 2026-09-27):*
    - **Deadlines** from the draft Form 4868 (2026) (Created 5/13/26): "For a 2026 calendar-year return, this is April 15, 2027, for most people"; abroad "by June 15, 2027"; the 1040-NR no-wage due date "June 15, 2027"; the six-month limit "(October 15, 2027, for most calendar-year taxpayers)". April 15, 2027 is a Thursday, so no shift. The refund window is IRC 6511(a), as in 2025.
    - **Payment options** from the draft Form 1040-V (2026) (Created 5/21/26): "United States Treasury", the "2026 Form 1040" memo, Direct Pay, EFTPS and card. The 2026 draft drops 2025's $1,000-per-day cash sentence, so the block gives only the PayCash page.
    - **Addresses:** the draft 1040-V's three with-payment rows (Charlotte P.O. Box 1214; Louisville P.O. Box 931000 for the other states and DC; Charlotte P.O. Box 1303 for the foreign/territory row). The no-payment addresses and both Form 1040-NR addresses print only in the 2026 instructions, which are not posted (the irs-dft i1040gi and i1040nr still serve the 2025 drafts), so they are None — never carried from 2025.
    - The knowledge schema admits a None address only in a planning pack (a filing-grade pack is refused), and file_and_pay says which address is unpublished instead of returning a bare None. The ITIN Operation and standalone-8843 entries carry over (the W-7 and 8843 pages are not year-specific).
    - deadlines, payment_options and mailing_addresses leave blocks_deliberately_absent; only filing_thresholds remains (JT6).
  - **Tests** (test_file_and_pay `test_jt2b_*`): a 2026 balance due in California resolves Louisville and 2027-04-15 / 2027-06-15; Texas resolves Charlotte 1214; a refund and a 1040-NR get the "not published yet" note and the 2030-04-15 refund window; a filing-grade pack with an unstated address is refused.
  - **External:** filing_thresholds and the no-payment / 1040-NR addresses wait for the 2026 i1040gi, i1040nr and Pub 501 (JT6).
- [x] **JT4a — The 2026 W-2 and structured W-2 facts — DONE 2026-09-27** (M; deps JF3, JF2) [TY26-24 + DEF-17]
  - *As built (read 2026-09-27):*
    - **Source:** the FINAL Instructions for Forms W-2 and W-3 (2026) (Jan 29, 2026; irs-prior/iw2w3--2026.pdf). What's New: "Box 14 has been split into box 14a and box 14b", plus new box 12 codes TA (IRC 128 Trump account employer contributions), TP (cash tips) and TT (qualified overtime, "only the "half" portion").
    - **Knowledge:** knowledge/forms/w2_box12_codes.yaml has all 33 codes, titled from the instructions' index, verbatim. `since` is 2026 for TA/TP/TT, and each code has a route. The IRC 402(g) group is D, E, F, S (402(g)(3)(A)-(D)) plus the designated Roth AA/BB (402A(c)(1): "any elective deferral"). 457(b) (G, EE) is separate. The box 14 and 14b rules are quoted. Loader: taxfill_core/w2_codes.py.
    - **Extract:** the W-2 DocSpec gains 14a (alias "14", the pre-2026 box) and 14b. Validator V22 flags a box 12 entry that is unreadable or not a code for the tax year (TT on a 2025 W-2). V23 flags box 14b before 2026. V24 flags 14b without TP, TP without 14b, and a "000" occupation. V25 gives each routed code's destination as an info finding.
    - **Estimator:** IncomeSnapshot.w2s (W2Facts: boxes 1-7, 10, 12, 14b) feeds a before-validator. It DERIVES wages, ss_wages (3 + 7), medicare_wages, the per-employer box 4 / box 6 lists, dependent_care_benefits (box 10) and qualified_overtime_premium (code TT). An aggregate given as well must agree, or the snapshot is refused. federal_withholding may exceed the box 2 total (estimated payments) but not fall below it.
      - Box 10 reaches dependent_care_credit's employer_benefits; the old "NOT tracked" disclosure now names the amount or asks for it.
      - The assumptions flag a per-person 402(g) excess across employers (the year's contribution_limits figure) and code W next to pre_agi_adjustments (the double-count trap).
      - The joint view concatenates w2s and sums the benefits, and the field-coverage classes include both.
    - **Not derived:** qualified_tips from code TP. TP is all cash tips, qualified only in a listed occupation (box 14b; "000" marks a nonqualifying one), so the caller confirms it. V25 names the route.
  - **Tests** (test_w2_2026 `test_jt4a_*`): the code table; derived = hand-fed aggregates and the same estimate; each mismatch raises; box 10 reduces the 2025 Form 2441 limit to the op's figure; TT and the joint view; the 402(g) and code-W disclosures; the W-2 reading's V22-V25 and the box 14 alias.
- [x] **JT4b — 1099-B boxes — DONE 2026-09-27** (S; deps J0) [TY26-26]
  - *As built (read 2026-09-27):* the Form 1099-B (2026) (irs-prior/f1099b--2026.pdf, Created 8/26/25) and its Instructions for Recipient, and the Instructions for Form 8949 (2025).
    - The DocSpec gains the applicable Form 8949 checkbox, 1f, 2-Ordinary, 3 (collectibles / QOF), 6 (gross / net proceeds), 7, 12 and 13.
    - Validator V26 (info) routes each reading. Box 12 and box 2 give Form 8949 box A/D (basis reported to the IRS) or B/E (not reported, or box 12 unchecked). Exception 1's direct entry on Schedule D line 1a / 8a applies when basis was reported, box 1f/1g shows no adjustment, and neither Ordinary nor box 3 is checked — quoted.
    - V27 flags both term boxes checked, box 12 with box 5, box 12 without a term box, box 7's loss bar, and a printed applicable checkbox that disagrees with boxes 2 and 12.
  - **Tests** (test_extract `test_jt4b_*`): a box-12 reading carries the routing note; unreported basis goes to B/E; an adjustment, Ordinary or a collectible forces Form 8949; the V27 contradictions.
- [x] **JT4c — Dress-rehearsal evals, scenarios t–t4 — DONE 2026-09-27** (M; deps JT3a–d, JT4a, JT4b, JF1a, JF8, JF9, JR2c, JR3c, JT2b) [TY26-29]
  - *As built:* packages/core/tests/test_dress_rehearsal_2026.py. Four SYNTHETIC TY2026 households with demo amounts, each run extract -> calc -> fill (rehearsal, the 2026 draft packs) -> verify_filing(rehearsal=True) -> filing_summary -> file_and_pay. The blanks come from the local cache; an empty cache SKIPS, like the readonly sweeps.
    - **t — two concurrent employers:**
      - two 2026 W-2 readings, each routing code D to the one 402(g) limit (V25), with elective_deferral_room across both;
      - a 1098-VLI (V19-V21 clean) through Schedule 1-A Part IV, and a 1099-INT;
      - estimate_refund from the structured W-2s equals the return. f1040 + sched_1a verify, with 13a == sched_1a.44 and 1 == f1040.11b PASS;
      - file_and_pay gives 2027-04-15 and the Louisville with-payment address.
    - **t2 — a resident J-1 researcher:** "J-1 researcher" classifies resident for 2026 (2 exempt years). China Art. 19 survives the saving clause. The exemption goes negative on Schedule 1 line 8z ("Exempt income, China, Art. 19") with 8 == sched_1.10 PASS; direct deposit.
    - **t3 — a joint return:**
      - one spouse's code TT (Schedule 1-A Part III), the other's code W beside a 5498-SA (Form 8889 family coverage, hsa_deduction) with the code-W guard firing;
      - an index-fund 1099-DIV (Schedule B, QDCG tax);
      - a covered long-term 1099-B loss routed by box 12 to Schedule D line 8a (Exception 1);
      - f1040 + sched_1 + sched_1a + f8889 + sched_b + sched_d verify, with four cross-form chains PASS; BOTH spouses sign.
    - **t4 — head of household with a child:** the code N and code 2 1099-Rs, ira_recharacterization then convert (Form 8606 lines 1-18, an exact 0.875 on line 10), a $600 170(p) gift on line 12f, the CTC on line 19. The recharacterization statement is in the assembly, and the unpublished 2026 refund address note appears.
  - **Engine change:** verify_filing gains `rehearsal` (core only), mirroring verify_form — every pack must be rehearsable (draft or planning-year final).
  - **Found for JT6:** a negative money entry renders as "-60000"; Pub 519's resident treaty exemption asks for the amount "in parentheses" on Schedule 1's other-income line. The packs' convention (a negative value) holds for the math. Whether the printed field should read "(60,000)" needs the final 2026 face and instructions.
  - All four flip to final mode at JT6.
- [ ] **JT5a–g — Wave B: the rest of the federal set for 2026** (JT5a **latest start 2026-11-16**; deps JT3a; each sub-tranche commits per pack) [TY26-21]
  - **JT5a** (M): copies f843, fw7, f8316 (current finals byte-identical to their 2025 pins) and fincen114; near-ports sched_se, f4868, f8960. **DONE 2026-09-27:**
    - **Copies:** the live irs-pdf f843 / fw7 / f8316, re-downloaded 2026-09-27, hash to their 2025 pins, so the 2026 packs keep URL and sha and change only tax_year. They are finals in a planning year, so rehearsal-only. FinCEN 114's 2026 handfill.yaml is the year-invariant worksheet.
    - **Near-ports onto the drafts:**
      - Schedule SE (Created 4/27/26): the same 27 widgets but two that lost their ReadOrder wrapper; new printed figures only (the $184,500 wage base, the optional-method amounts). Its Schedule 2 line 4 and Schedule 1 line 15 legs were re-read and stand.
      - Form 4868 (Created 5/13/26): 18 widgets — the NEW line 10 disaster checkbox (c1_3) is mapped as `10.disaster`.
      - Form 8960 (Created 6/1/26): an identical topology, but its Schedule 2 leg MOVES to the renumbered 2026 line 6 (2025: 12).
    - The port rule's calc.py grep found no Schedule SE / 8960 / 4868 literal that moved (no line renumbered). test_discovery 130 federal. Tests: test_formpacks_federal `test_jt5a_*` plus the golden round trips and readonly sweeps (the drafts are cached).
  - **JT5b** (M): sched_8812, f2555, f8863. **DONE 2026-09-27:**
    - Schedule 8812 (Created 4/24/26; this draft has no cover sheet): the same 41 widgets. Line 1 now reads Form 1040 line 11b, so the leg is `1 == f1040.11b`. The 1040-NR legs wait for JT5c's pack.
    - Form 2555 (Created 9/18/26): the same 160 widgets; wording only.
    - Form 8863 (Created 4/28/26): the 2025 set with the "f2-5" typo fixed (f2_5), the P-024 SSN notice (no widget), and the line 29 / Schedule 3 line 3 legs re-read and standing.
    - The port rule's grep: every Schedule 8812 / 8863 / 2555 line calc.py prints keeps its 2026 number. test_discovery 133 federal. Tests: `test_jt5b_*` plus the golden round trips and readonly sweeps (drafts cached).
  - **JT5c** (M–L): f1040nr (new 12b, 13a, 24a–c, 32b), sched_a_nr, f8843. **DONE 2026-09-27:**
    - **Form 1040-NR** (Created 8/19/26): 177 widgets (2025: 171), 170 mapped (the 7 preparer widgets stay unmapped). Everything is re-read off the draft:
      - Page 1 gains one radio (c1_7, "are you a U.S. citizen, U.S. national, or an alien lawfully authorized to work in the U.S.?", keyed `citizen_or_work_authorized`). Every later page-1 checkbox moves up one; every page-1 text widget keeps its name.
      - Page 2: new 12b (the non-itemizer charitable deduction), 24a–c (24b = Form 1062 line 15) and 32a–c (32b = Schedule 3-A). The 2025 decline-ACTC box is gone.
      - TRAP: 13a/13b/13c reorder — 13a is Schedule 1-A line 44, 13b QBI, 13c estate/trust exemptions (2025: QBI, exemptions, Schedule 1-A line 38).
      - The relations follow the printed arithmetic (14 adds 12a–13c; 33 adds 32c; 34/37 compare with 24c).
      - The state box is 9pt on the draft, so its clipping cap drops 15 → 13.
      - `mailing: null`: the 2026 instructions, where the addresses print, are not posted (JT2b).
      - The 1k leg names Schedule OI, whose 2026 draft has not posted; test_pack_invariants allowlists (2026, sched_oi, 1e) until JT5g.
    - **Schedule A (Form 1040-NR)** (Created 5/18/26): hand-mapped, 26 widgets; `1b == min(1a, 40400)`, `9 == f1040nr.12a`.
    - **Form 8843** (Created 5/11/26): 17 text leaves lose their zero padding. Every printed year column moves up one: 4a.2026/2025/2024, and 7.<y>/11.<y> for 2020–2025. The year-offset invariant caught 4a left at 2025–2023 on the first pass.
    - **Legs:** the 2026 sched_1a gains `1 == f1040nr.11b` / `44 == f1040nr.13a`, sched_3 `8 == f1040nr.20` / `15 == f1040nr.31`, and sched_8812 its three f1040nr legs back.
    - **Port rule:** the engine's 1040-NR line text already goes through form_lines (f1040nr.itemized 12a, f1040nr.sched_1a 13a, read in JT3a/JF9), so no literal moved.
    - The filer-address fixture gains the JT5a–c rows, each equal to its 2025 row. test_discovery 136 federal.
    - **Tests:** `test_jt5c_*` (test_formpacks_federal), and a nonresident dress rehearsal in test_dress_rehearsal_2026 (1040-NR + Schedule A (1040-NR) + 8843; the line 16 recompute; the unposted-address note).
  - **JT5d** (M–L): sched_a, sched_c, sched_e. **DONE 2026-09-28:**
    - **Schedule A** (Created 5/12/26): 47 widgets (2025: 33), all mapped by hand off the face.
      - 8d is live again ("Mortgage insurance premiums"); 8e adds 8a–8d.
      - TRAP: every line from 13 on moves. 13 is NEW (line 6 of the Charitable Contribution Limitation Worksheet), 14 the carryover, 15 = 13 + 14, 16 casualty, 17a–17k + 17z other itemized (17a gains a "winnings on Schedule C or E" box), 18 the total, 19 elect-to-itemize.
      - Line 18 carries the IRC 68 screen ("more than $384,350?", a /1 No, /2 Yes radio), so 18 is not a relation. Legs `2 == f1040.11b` and `18 == f1040.12e` (the 2025 pack had none).
    - **Schedule C** (Created 5/15/26): 109 widgets, all mapped.
      - Box E splits into street/apt/city/state/ZIP.
      - TRAP: 16b is the NEW "Vehicle loan" line and 2025's 16b "Other" is 16c; 28 adds 16c.
      - The G/I/J checkbox kids went /Yes /No → /1 /2.
    - **Schedule E** (Created 5/6/26): 205 widgets, 193 mapped, derived from the draft's own table containers.
      - 1a splits into five address boxes per property.
      - TRAP: 13 splits into 13a "Vehicle loan" and 13b "Other"; the 13 header row is shaded.
      - Part V moves to a new page 3 with its own name/SSN header (IDENTITY_MIRROR_COUNTS 4).
      - The 12 unmapped widgets are all ReadOnly: the nine Totals cells, as in 2025, plus the 13 header row.
    - **The designator sweep** (every numeric key's widget vs the printed label beside it, 2023–2026) found ONE real defect, fixed in its own commit: the 2025 Schedule C bound 27a/27b to each other's box. The 2025 revision swapped the printed order, the name-diff template carried the 2024 keys, and the relation read `27a == 48` although line 48 prints "Enter here and on line 27b". Every other hit is a table column (row "11" vs key "11a") or the f8833 right-column box.
    - The K-1 (1041) note now says the estate-tax line is 17e on the 2026 draft. test_discovery 139 federal. Tests: `test_jt5d_*`.
  - **JT5e** (M–L): f8962, f2441, f1116, f8938 (Rev. 12-2026). **DONE 2026-09-28:**
    - **Form 8962** (Created 4/21/26): 143 widgets, 141 mapped.
      - NEW line-6 radio ("Did you enter 401% on line 5?", the cliff is back).
      - TRAP: lines 28/29 print "Reserved for future use" (the repayment cap is gone), so their keys do not exist (RESERVED_LINES_UNMAPPED), and the Schedule 2 line 1a leg moves from 29 to 27.
    - **Form 2441** (Created 4/30/26): 72 widgets, all mapped.
      - TRAP: the Part I provider table is transposed (providers are columns, rows 1a–1e); the keys survive and every other widget keeps its 2025 name.
      - Line 8's decimal table is gone from the face; line 21 prints $7,500 / $3,750.
    - **Form 1116** (Created 7/1/26): 130 widgets (2025: 118), all mapped.
      - Part II moves to page 2 and gains (p)(1)/(p)(2) and (u)(1)/(u)(2) PTEP columns.
      - TRAP: the column letters shift. The U.S.-dollar columns are (r)–(w) (2025: (q)–(u)), and the keys follow the print.
      - Line 18 adds Schedule 1-A line 43. foreign_tax_credit_election now returns the 2026 pack path.
    - **Form 8938** (Rev. 12-2026, Created 9/2/26): the same 131 widgets in the same reading order (checked position by position); 18 names lose their zero padding; wording only.
    - The designator sweep over the four is clean. The filer-address fixture gains the rows (each equals its 2025 row); test_discovery 143. The Schedule E 2026 line-13 header cells from JT5d gain their RESERVED_LINES_UNMAPPED row. Tests: `test_jt5e_*`.
  - **JT5f** (M): f1040x (Rev. 12-2026), and sched_3a (new). **DONE 2026-09-28:**
    - **Form 1040-X** (Rev. 12-2026, Created 8/19/26): a wholesale redesign that tracks the 2026 Form 1040 — 194 widgets, 191 mapped (line 9's three reserved cells stay unmapped, RESERVED_LINES_UNMAPPED).
      - New on the face: the special-processing row, main-home-in-U.S., split Presidential Election boxes, and Other Information (the NRA-spouse election, digital assets, citizen/work-authorized).
      - New lines 2a–2c, 11a–11c (Form 1062), 17a–17c (Schedule 3-A) and direct deposit 22a–22d; the 8885 box is gone.
      - TRAP: Part I renumbers — 2025 25/27 are 2026 24/25.
      - Relations are column C only, re-read.
    - **Schedule 3-A** (Created 6/24/26): NEW form key `sched_3a` (KNOWN_FORM_KEYS), 16 widgets, root form1[0].
      - Relations `5 == 3 - 4` and line 6 = max(0, 2 − 5).
      - Legs in from Form 1040 32a/31/24a, 1040-NR 24a and Schedule 2 line 20. The carry out to line 32b is conditional (line 6 or 8), so it is not encoded; the f1040/f1040nr headers say so.
    - **The Schedule 3-A draft is malformed:** its /AcroForm /Fields is `[]`, the 16 widgets sit only in the page /Annots, and the parent nodes carry no /Kids, so pypdf saw no form. `filler._repair_empty_field_array` rebuilds /Fields and re-links /Kids from the widgets' parent chains. It runs only when /Fields is empty (a well-formed blank is untouched), with a unit test in test_filler.
    - The 1040-X ZIP and foreign-postal-code boxes (70 pt at the draft's 9pt) take maxlen 10 / 15.
    - The filer-address fixture gains both rows; test_discovery 145. Tests: `test_jt5f_*`.
  - **JT5g** (external): sched_nec and sched_oi, once their 2026 drafts post. The f1040nrn/nro drafts are still 2025; they are on the check_finals watchlist.
  - **Acceptance:** as JT3.
  - **Port rule (found in JF8):** calc.py prints ~330 worksheet and form line literals for forms outside the form_lines registry (Schedule SE, Form 8962, Form 8863, the QDCG and Social Security worksheets, ...), each true for the year it was read. Each Wave B port greps calc.py for its form's literals and moves any that differ onto form_lines.

### Block 5 — Remaining decision ops

- [x] **JP1b — Pub 15-T 2026 knowledge — DONE 2026-09-27** (M; deps JF1a) [LD-02, knowledge half]
  - *As built:* a top-level 2026 `payroll_withholding` block (typed PayrollWithholdingParams) transcribed from Publication 15-T (2026) (irs-prior/p15t--2026.pdf, read 2026-09-27):
    - Worksheet 1A line 1g ($12,900 MFJ / $8,600 otherwise; 0 with the Step 2 box) and line 1k's $4,300 per pre-2020 allowance;
    - Table 3's pay periods;
    - the STANDARD and Step 2 checkbox annual tables for MFJ, single-or-MFS (one table, built on the single schedule) and HoH — each row has columns A-E, exact cents, rows validated contiguous;
    - the nonresident alien add-ons (Table 2 for a 2020-or-later W-4: $16,100 a year; Table 1 before 2020: $11,800), per payroll period;
    - the rounding rule, quoted.
  - **Second-pass tests** (test_payroll_withholding `test_jp1b_*`): every STANDARD row equals the pack's rate schedule shifted by (standard deduction - line 1g), carrying the tax to its floor; every checkbox row equals the half-width bracket shifted by half the standard deduction, carrying half the tax (rounded half up). All three statuses x both tables pass. A gap in a table is refused.
  - **Left for JP1c:** Pub 15's partial-period rule, applied where pay dates are counted.
- [x] **JP1c — The withholding projection op — DONE 2026-09-27** (M–L; deps JP1a, JP1b) [LD-02, op half + missing Pub 15-T §6 + the rest of LD-12]
  - *As built:* `calc.withholding_projection` (taxfill_core/withholding.py; op 37; server docs, dispatch, all three skills), per employer:
    - **Regular checks:** Pub 15-T (2026) Worksheet 1A from the knowledge block (JP1b), counted by PAY DATE through employment_end — explicit dates, or weekly / biweekly / semimonthly / monthly schedules. A pre-2020 W-4 takes $4,300 per allowance and no head-of-household table. The nonresident alien add-on uses Table 2 (or Table 1 for a pre-2020 W-4 first paid before 2020), noted as never on the W-2. A partial first period's wages are withheld as a full payroll period. The dollar rounding (Pub 15-T's option) is used consistently.
    - **Supplemental wages** (the pack's P-017 block, Treas. Reg. 31.3402(g)-1): the excess of the year's supplemental wages over $1,000,000 is withheld at 37%. The flat 22% is open only when (a)(7)(i)(B) and (C) both hold. It is FORCED aggregate when either fails, both methods as a range when both hold (the employer's option) or a fact is unknown, and an INTERPRETIVE choice when the bonus rides the first withheld regular check. The aggregate procedure withholds on (the concurrent or most recent regular wages + the bonus) less the regular withholding.
    - **Employee-requested methods** (Pub 15-T section 6): cumulative wages — refused without the written request and the same payroll period since January. Part-year employment — refused without the written request under penalties of perjury, the calendar-year basis and the anticipated days, and refused over "no more than 245 days". The divisor counts the idle periods since the last employment.
    - **FICA per employer:** box 4 at 6.2% to the employer's own wage base, and box 6 at 1.45% plus 0.9% over the employer's own $200,000 (IRC 3102(f)(1)). employee_fica reconciles the person.
    - **Outputs:** per-check rows, box 2 low/high, boxes 3-6, and `w2s` that feed estimate_refund's IncomeSnapshot.w2s (JT4a). JF1a's P-017 text now points at the op instead of "no op computes it yet".
  - **Tests** (test_withholding_projection `test_jp1c_*`):
    - Pub 15 (2026) Example 2's wage-bracket figures ($65 / $179 / $419) reproduced within $1, and Example 3's 22% x $1,000 = $220;
    - (i) a bonus before any withheld regular check this or last year → aggregate forced;
    - (ii) after a withheld check and separately stated → the range;
    - (iii) concurrent and not separately stated → aggregate;
    - (iv) with the first check → interpretive;
    - an unknown fact → a range; 37% over $1M; the NRA add-on; a partial first period; employment_end;
    - the part-year refusal at 246 days, and its lower total; the cumulative gate;
    - per-employer box 4 / box 6, and the w2s feeding IncomeSnapshot.
  - **Not built:** the wage bracket method's own tables (the percentage method is what automated payroll uses; the examples show the difference stays within $1), and the residency_classification auto-fill into employee_fica (fica_exempt stays the caller's per-employer judgment, as in employee_fica).
- [x] **JP5a — Underpayment penalty, regular method — DONE 2026-09-28** (M; deps JF4) [critic: missing]
  - *As built:* calc op 38 `underpayment_penalty` (taxfill_core/penalty.py). It follows the statute's own mechanics, all quoted from uscode.house.gov:
    - IRC 6654(b)(1)–(3): the underpayment, its period, and the FIFO "order in which such installments are required to be paid" — which is how Form 2210 Section A's line 14 compounds arrears;
    - 6654(g)(1): ratable withholding, or all actual dates;
    - the 6654(e)(1) $1,000 and 6654(h) January-31 exceptions.
  - The per-year calendar is a new `tax.estimated_tax_penalty` block (due dates, period end, day count, rate periods).
    - 2025: the Instructions for Form 2210 (2025) Penalty Worksheet's four periods, each × 0.07.
    - 2026: the IRS quarterly table — Q2 6%, Q3 7%, Q4 7%, and Q1 2027 None, so the op fails closed.
    - IRC 6621(b)(2)(B) is why period 4 keeps the Q1 rate through April 15 ("shall also apply during the first 15 days of the 4th month").
    - sources.yaml's underpayment_penalty topic gains the IRS quarterly-rate page ("quarterly interest rates" now routes there instead of missing onto nonresident_fdap).
  - **Tests** (test_underpayment_penalty.py) reproduce the instructions' own worked facts:
    - Example 3's line-1b allocation and Example 4's "15"/"61" days ($204.05 total);
    - Example 2's "56 days";
    - Table 2's Chart of Total Days (76/92/92/105; 15/92/92/105; 15/92/105; 90);
    - the 2026 6% quarter and the Q1-2027 refusal; the exceptions.
  - Op count 38.
- [x] **JP5b — The annualized income installment method (Schedule AI) — DONE 2026-09-28** (M; deps JP5a)
  - *As built:* `underpayment_penalty(..., annualized={...})` computes Schedule AI Parts I and II column by column. The constants are a new `estimated_tax_penalty.schedule_ai` block, read off each face:
    - Form 2210 (2025) final: 4 / 2.4 / 1.5 / 1; 22.5 / 45 / 67.5 / 90%; line 29 $44,025–$176,100; lines 32/34.
    - Draft Form 2210 (2026) (Created 4/16/26), labeled draft: the same factors, line 29 $46,125–$184,500, and the NEW line 9b "Additional deductions". The 2025 face has no such line, so the Schedule 1-A deductions come off line 13 per the 2025 line-14 instruction.
  - Line 27 = min(line 23, line 26) feeds line 10. The same payments are priced against the regular 25% installments too (`regular_method_penalty`).
  - **Tests:** a Q4-weighted demo year pays less under Schedule AI and the op reports both; the SE factors against each year's prorated base; the input guards.
- [x] **JP3a — Employment schema and paystub DocSpec — DONE 2026-09-28** (M; deps JP1c) [LD-04, part 1]
  - *As built:* `Profile.employment: dict[year, list[EmploymentRecord]]`. Each record: employer, start/end (checked in order), pay frequency, first pay date, gross per period, the JP1c `W4Facts`, and `PayrollDeductions` per period split by tax character — pre-tax 401(k), IRC 125 premiums, HSA through the plan (code W), health FSA, dependent care FSA (box 10), 132(f); post-tax Roth, after-tax, loan.
  - The `paystub` DocSpec (29 kinds): source iw2w3.pdf. Its status note quotes the W-2 instructions' "Calendar year basis" and box 1's elective-deferral exclusion. Validators: V28 (a YTD figure below its own current figure) and V29 (a pay date outside the tax year).
  - **Tests** (test_paystub.py): a synthetic stub extracts with its caveat; the validators; a workspace save/load round trip keeps the schema; the date guard.
- [x] **JP3b — Paystub → projected W-2 — DONE 2026-09-28** (M; deps JP3a, JP2) [LD-04, part 2]
  - *As built:* calc op 39 `paystub_to_w2` (taxfill_core/paystub.py). It takes the stub's YTD actuals plus the checks still to be PAID by December 31, counted by pay date.
    - The first check after December 31 is reported as next year's (a biweekly January 1 check).
    - An ended job adds nothing; nothing is annualized.
    - Box 1 = gross − pre-tax 401(k) − the cafeteria-plan reductions. Boxes 3/5 exclude only the latter, box 3 is capped at the wage base, and boxes 4/6 use this employer's own rates (the 0.9% over $200,000).
    - Box 10 and box 12 D/AA/W. The output `w2` feeds `estimate_refund`'s `income.w2s`.
  - annualize_ytd's work now says never to annualize an ended job. The README calc row, SKILL.md bullets, DEV_PLAN §18 and the bundle manifest move to 39 ops.
  - **Tests** (test_paystub_to_w2.py): a mid-year stub reproduces the hand-computed W-2; an ended job; the January 1 check; the wage-base cap; a stub from another year refuses.
- [x] **JP4 — Wage repayment: claim of right (§1341) — DONE 2026-09-28** (M; deps JF2) [LD-13] — pitfall *claim-of-right* = **P-025**
  - *As built:* calc op 40 `claim_of_right_repayment` (taxfill_core/repayment.py), quoting IRC 1341(a)–(b) (uscode.house.gov) and Pub 525 (2025) Repayments.
    - Method 1 (the deduction) vs Method 2 (this year's tax less the prior year's decrease); the lesser tax wins.
    - At $3,000 or less, nothing is deductible and no credit applies.
    - A business or capital repayment goes on its own schedule; the claim-of-right premise is required.
    - The payroll-tax notes: FICA back from the employer or on Form 843; Additional Medicare Tax only on a prior-year Form 1040-X.
  - The destinations are two new form_lines keys, read off every 2019–2026 face (all 16 pass test_every_entry_quotes_its_face against the downloaded PDFs):
    - `scheda.claim_of_right`: line 16 through 2025, 17h on the 2026 draft.
    - `sched3.section_1341_credit`: 13 box d in 2019 and 12d in 2020 (both write-ins per that year's Form 1040 instructions), 13d in 2021–2023, 13b from 2024.
  - **Tests** (test_claim_of_right.py, `test_p025_*`):
    - Pub 525 Example 40 with its printed taxes: $5,156 vs $5,335, deduct.
    - The same from the Tax Table ($5,159 vs $5,341) — the example's 2025 taxes are not the 2025 table's.
    - $3,000 or less; the credit winning when last year's rate was higher; business routing and payroll notes; the lines per year.
  - Op count 40.
- [x] **JR4a — Form 5329, 2025 pack — DONE 2026-09-28** (M–L; deps JR3c) [RC-14]
  - *As built:* formpacks/federal/2025/f5329 — all 75 widgets of f5329--2025.pdf (Created 6/12/25, 3 pages, no ReadOnly), bound by y-coordinate and checked on a sentinel render of every page.
    - The line-2 exception-number box is its own text key, `2.exception_number` ("01–23 ... If more than one exception applies, enter 99").
    - 19 relations: every printed Add/Subtract row, the Part II 10%, and line 55.
    - Deliberately NOT declared, with the reason on each row: line 4 (the printed SIMPLE-IRA 25% Caution); the six 6% lines (the Dec-31 value is off-form); 54a/54b (the "RC" reasonable-cause waiver changes the entry).
    - No cross_form: Schedule 2 line 8 is "the combined tax" of a separate form per spouse. The address block and signature apply only when the form is filed by itself (the f8606 shape).
  - **The recompute from JR3c's rules:** `taxfill_core.estimate.form5329_lines(snapshot, year)` returns one person's lines 1–4 and 16–17 / 24–25 from the estimator's own code. Pass it to `verify_form(..., independent=...)`.
    - The corrective earnings (box 7 code 8 with J/1) go on line 1 AND line 2, per the i5329 Line 15/23 instructions ("Report this amount on line 2 and enter exception number 21").
    - Its tax lines are keyed by the bare designator (`form_line_entry(...).line`): `form_line` renders a draft year's line with its marker text, which is no key a pack maps.
  - New key `f5329` in KNOWN_FORM_KEYS and CONVENTIONS (37 keys); the filer-address fixture row equals f8606 2025's; federal packs 146.
  - **Tests** (test_form5329.py, `test_jr4a_*`):
    - the helper vs the estimator's slots; the SIMPLE rate, the exception amount and the cap;
    - the golden round trip with "21" on line 2 (verify ok, and every recomputed line PASSes);
    - a line 4 that taxed the corrective earnings, caught only by the recompute;
    - the per-person / standalone-signature shape; the bare keys on a draft year.
- [x] **JR4b — Form 5329: 2023/2024 ports and the 2026 draft pack — DONE 2026-09-28** (M; deps JR4a, JT0a)
  - *As built:* three packs, each bound from its own rects and checked on a sentinel render of every page.
    - **2024** (75 widgets): the 2025 names, but 31 rects moved. TRAP: the preparer f3_11/f3_12 swap (2024: f3_11 is the firm address, f3_12 the EIN).
    - **2023** (73 widgets, two pages): Part IX is the pre-2024 layout — 52 / 53 / 54, the line-55 10%-rate box (`55.reduced_rate`) and 55, with the rate split in the Line 55 Worksheet. So there is no `55 == 54a + 54b`, and line 54 carries no relation (the 2023 "RC" waiver enters the reduced shortfall on line 54). Exceptions run 01–21.
    - **2026 draft** (Created 7/31/26, 85 widgets, `source_status: draft`, re-pinned at JT6):
      - the city/state/ZIP box split into three (page 1 moves +2);
      - Schedule 2 line 5 for Parts I/II/XI and line 18 for III–X;
      - NEW Parts X (Trump-account excess contributions, 56–61) and XI (their distributed earnings, 62–63). Line 61's 6% has no "smaller of ... or the value" clause, and 63 is 100% of 62, so both are declared;
      - the preparer block renumbered.
  - Federal packs 149; filer-address fixture rows (2023/2024 = the 2025 row; 2026 = the 2026 f8606 set).
  - **Tests** (test_form5329.py, `test_jr4b_*`):
    - the 2024 swap; the 2023 Part IX shape; the 2026 renumbering and the Trump-account relations;
    - a per-pack golden with exception 21 for each of 2023, 2024 and 2026 (the draft in rehearsal mode), every recomputed line PASSing.
- [x] **JP5c — Form 2210 packs — DONE 2026-09-28** (M–L; deps JP5b, JT0a)
  - *As built:* new form key f2210 (38 keys), two packs, each bound from its widget groups and checked on a sentinel render of every page.
    - **2025:** 167 of 199 widgets. The 32 ReadOnly cells are the six shaded Section A cells, 22(a)/25(a), and the 1-point dummies on Schedule AI's printed rows 2, 5, 20, 29, 32 and 34.
    - **2026 draft** (Created 4/16/26, 171 of 203): Schedule AI line 9 becomes 9a plus a NEW 9b "Additional deductions" (every widget below moves +4), and line 29's limits move to the $184,500 wage base.
    - Keys: Part I bare; Part III `10.a`–`18.c` and `19`; Schedule AI `ai.<line>.<column>`.
  - **The relation grammar now admits dotted ids** (verify `_TOKEN_RE`: a LINE may carry `.segment`s; floats still match first, and `1a..1h` still splits). That is what lets Form 2210 declare 104 printed relations. The printed factors are float literals (`* 4.0`), so a bare `4` never reads as line 4.
    - Not declared: line 10 (box C), and Schedule AI 24 and 31 — true only when Schedule AI is used, while a regular-method filing leaves it blank.
    - Cross-form: only `1 == f1040nr.22`. The Form 1040 leg is false on the section 965 exclusion; `19 -> line 38` is false when only page 1 is filed.
  - **The recompute:** `penalty.form2210_lines(result)` works Section A the way the face prints it (line 11 per payment window) and raises if a line 17 disagrees with the 6654(b)(3) ledger. Line 19 is the whole-dollar penalty, and with Schedule AI it adds every face line.
    - JP5b's Schedule AI columns gain `face_lines`, and lines 33 and 35 are now rounded as lines of their own (36 = 33 + 35, as printed).
  - The 18 packs / handfills that recorded the old grammar wall carry a dated note → **JEc**.
  - **Tests** (test_form2210.py, `test_jp5c_*`):
    - Section A vs the ledger (Instructions Example 3);
    - goldens for the regular method, Schedule AI (box C, SE tax) and the 2026 draft with 9b in rehearsal mode, every relation and recomputed line PASSing;
    - non-compounding arrears caught only by the recompute; the shaded cells unmapped;
    - test_verify: dotted ids, floats and ranges.

### Block 6 — Docs, release, debt

- [x] **JD1 — Docs truth-up, the rest of old J6 — DONE 2026-09-28** (M; deps JR2c, JF6c)
  - *As built:*
    1. **README:** all 23 tools, and a calc row naming the 38 ops. estimate_refund is ESTIMATE / PROJECTION; M2 reads 145 packs (2026:34); the 1040-X FAQ carries its three revisions. `test_readme_sync.py` derives every count from the runtime: tools, ops, the M2 per-year pack counts and the bundle manifest.
    2. **DEV_PLAN §18 "Deviations as built":** the two labels, weekly freshness, the 28-kind DocSpec set, no perceptual-hash tests, the routing checksum living in the profile schema, and the live registries as the authority.
    3. **SKILL.md:** a "calc ops" section with one bullet per op (38); Recipe P (planning-year projection) and Recipe R (IRA basis / backdoor / recharacterization); the coverage callout (145 packs; 34/34/35, plus TY2026's 34 drafts). The estimate_refund docstring states both labels. `scripts/sync_bundle_manifest.py` rewrites bundle/manifest.json's calc entry from the dispatch chain; the Codex and Copilot skills mirror the label and point at Recipes P and R.
    4. **CONVENTIONS:** lists all 36 keys, pinned equal to KNOWN_FORM_KEYS by a test, and adds a hand-fill section (the four print-only states and FinCEN 114).
    5. **CONTRIBUTING:** the pitfall gate as it really works, no snapshot tests, weekly freshness, the dev commands and the test-count sync.
    6. **FIELD_NOTES:** a status row for every N-item, plus later findings (H9, Phase I, Phase J) — hypothetical personas, mechanisms only.
    7. **Test docstrings** (23 tools; every op, 38) and the resolved MS note.
    8. **D2** re-measured (the 2026-09-28 rows in the D2 entry): UT 2025 is PORTABLE and unshipped (JS3b).
- [ ] **JA1 — Phase A, the agent half** (M; deps J0; takes the next slot the day the user says they are ready to publish; supersedes A1–A6's open boxes)
  1. **Immutable descriptions** [G16]. The PyPI-immutable descriptions say "21 calculation ops" (taxfill-core), "22 tools" (taxfill-mcp) and "21 deterministic ops" (packages/mcp-server README), and nothing tests them. The runtime has 32 ops and 23 tools. Use count-free wording, and add test_release_surfaces.py.
  2. **PUBLISHING runbook** [G17].
     - Its smoke test asserts 22 tools (:83); ci.yml:111 says 23.
     - The `.dev0` step is obsolete: all four version sites read 0.1.0. Reintroduce 0.1.0.dev0 on main.
     - bundle/README cites a snippet that does not exist → write scripts/gen_manifest_tools.py plus an equality test.
     - Add the mcp<2 decision (2.2.0 is the latest release; 1.30.0 the latest 1.x) and a CHANGELOG step.
  3. **Sample W-2** [G19]. ACCEPTANCE and DEMO use "the bundled SAMPLE W-2", which does not exist. Generate docs/samples/w2_2023_synthetic.{png,pdf} with scripts/make_sample_w2.py: SSN 999-88-xxxx, a SAMPLE watermark, and the README walkthrough figures.
  4. **CI packaging set** [G26]. The smoke check hard-codes a pre-Phase-G set (ci.yml:104-105). Derive the counts from the repo and compare against data_root() / list_forms().
  5. **.mcpb runtime** [G18; unverified]. The bundle launches `uvx`. Prototype mcpb v0.4 `server.type: "uv"`, test it on a machine without uv, else document uv as step 0. Add `mcpb validate` to CI.
  6. **Release workflow** [G20, agent part]. release.yml with Trusted Publishing on tag v*: build, twine check, clean-venv smoke, publish core then mcp, GitHub release from CHANGELOG. Add CHANGELOG.md, and re-stage `_data` before building.
  - **Acceptance:** `twine check` PASSED ×4; the clean-venv smoke shows 23 tools and the derived pack counts; test_release_surfaces and the manifest equality test are green; the sample W-2 extracts.
- [ ] **JA2 — Phase A, the user half** (external: the user) [G20]
  - The user:
    - creates a PyPI account with 2FA and a Trusted Publisher (or pending publisher) for taxfill-core and taxfill-mcp, bound to release.yml — or provides a token (both names were free on PyPI and TestPyPI on 2026-09-23);
    - decides mcp<2;
    - approves and pushes the v0.1.0 tag (the irreversible upload);
    - records the demo GIF;
    - recruits a non-developer ACCEPTANCE tester;
    - makes any branch-protection change.
  - Then an agent does A6.
- [x] **JEa — SSN maxlen and reserved lines — DONE 2026-09-28** (M; deps J0) [G30 + PJ-13 rest]
  - *As built:*
    - **maxlen tracks the widget.** 41 federal SSN fields (identifying_number in f8606 / f8960 / f8962 / sched_2 / sched_a / sched_oi / sched_3a, and f8962 30b–33b; 2022–2026) move 9 → 11, their widget /MaxLen. NY IT-203 2025 line 35 moves 10 → 4: its widget holds 4, the one pack that let through more than its box.
      - New network-marked test_pack_maxlen.py over every pack: a pack maxlen may never exceed the widget's; a tighter one needs a `TIGHTER_THAN_WIDGET` row with the measured box (11 state rows, self-clearing).
    - **`PackField.reserved`**: set on exactly the 19 RESERVED_LINE_KEEPS rows (a test holds the two equal). fill_form warns when a value lands on one; scripts/audit_pack.py leaves them blank.
    - **CONVENTIONS** "Reserved, shaded and ReadOnly widgets" gains the `reserved` flag, the "never map a DOR banner or caption" rule (with the J0.3 AL-40 / MO-1040 cases) and the maxlen rule.
    - **J0 verifier follow-ups:**
      - freshness.yml runs test_verify_readonly_sweep.py after the network round trips warm the cache;
      - unmapped the class-1 captions — AL-40 2023 txtMultiScheduleD/E; MO-1040 2023/2024's 28 printlid.* lids, ProtectBarcode, vendorid, amendedTXT, line51txt, 1040_30Text (STATE_COMPUTED_READONLY al40 568→566, mo1040 256→223 / 254→221);
      - adjudicated the nonzero ReadOnly defaults: GA 500's TP/SP_S1L4 (4000) and TP/SP_S1L2_P3 (17500) are constants → unmapped (193→189). The 17 others are class 4 (JS-assigned, filing-status-dependent, a /C script, a /Ch default), pinned in `NONZERO_READONLY_DEFAULTS` with a network test that fails on any unadjudicated one;
      - verify enforces a bound pack maxlen on a scanned widget with no /MaxLen of its own (`_bound_maxlen_checks`; blank-owned widgets are dropped first, so J0.3's regression cannot return);
      - the width heuristic counts wrapped lines for a multiline widget (/Ff bit 13) against the rows its height holds;
      - `fetch.cached_blank_path(url, sha256)` is public, and verify and the new tests use it;
      - the stale "verify skips ReadOnly widgets" prose is reworded (sched_d / sched_e 2023–2025, OH IT-1040 2023/2024, test_formpacks_federal, test_pack_invariants), and P-007 records (b) as closed.
  - **Tests:**
    - test_pack_maxlen.py (223 network cases);
    - test_filler reserved warning; the reserved-flag equality;
    - NONZERO_READONLY_DEFAULTS;
    - test_verify multiline and bound-maxlen;
    - test_fetch cached_blank_path;
    - the two sweep controls re-based on the multiline rule.
- [x] **JEb — Checkbox topology — DONE 2026-09-28** (L; deps J0) [G31]
  - *As built:* re-measured on 212 packs — 377 option sets on separate fields with non-yes/no tokens, 240 without one shared group id (147 families by form and stem). Each family was read off its printed row (row text beside the widgets, and a crop where the text layer was garbled).
  - **Grouped — the face makes them alternatives** (82 lines, 11 packs):
    - ID Form 40 / KS K-40 / NE 1040N filing status;
    - KS / NE residency (type of return);
    - KS "Amended Return (Mark ONE)";
    - the ID / MD / MO 2023–2024 / IN account types;
    - MD's "All taxpayers must select one method";
    - AZ 140's per-dependent under-17 / 17-or-over boxes (14 dependents);
    - CA 540 / 540NR's "FTB 5805 attached / FTB 5805F attached" and the Tax Table / Tax Rate Schedule method;
    - MO-NRI's Missouri / Non-Missouri home of record per person;
    - GA 500's paper / electronic voucher boxes.
  - **Adjudicated — 120 families** in `SEPARATE_OPTION_SETS_ADJUDICATED` (test_pack_invariants.py), keyed (family, stem) so a row covers every year. Each is `INDEPENDENT:` (e.g. "Check applicable boxes", one box per spouse, W-7's "you must also check and complete box h") or `PARTIAL:` (a grouped subset beside independent boxes: filing status + the NRA-spouse election, the dependent credit pair + the lived-with boxes).
  - **Gates:** `test_separate_widget_option_sets_are_adjudicated` over every pack; `test_every_option_set_row_still_describes_an_ungrouped_set` (self-clearing, INDEPENDENT/PARTIAL wording required). P-008 and CONVENTIONS updated; the Phase E box is closed.
- [x] **JEc — Declare the relations the dotted-id grammar now allows — DONE 2026-09-28** (M; deps JP5c; added 2026-09-28 by JP5c, outside the original 62-tranche table)
  - *As built:* each candidate re-read against its face.
    - **sched_d 2023–2026:** the column (h) head, "Subtract column (e) from column (d) and combine the result with column (g)", for all eight rows. Rows 1a/8a have no (g): the shaded cells are unmapped. 9 relations per pack.
    - **sched_oi 2022–2025:** item L "(e) Total" = the three column (d) rows. The 2025 Instructions for Form 1040-NR (item L) provide no continuation statement, so the total is the three printed rows.
    - **f8949 2023–2026:** the per-row identity and "2 Totals. Add the amounts in columns (d), (e), (g), and (h)" — 36 relations (14 rows a Part) in 2023/2024, 30 (11 rows) in 2025/2026.
    - **sched_nec 2023–2025:** 13a–13e, "Add lines 1a through 12 in columns (a) through (d)", each sub-column summing the rows mapped in it.
    - **MT Form 2 (2023)** stays out, with the reason recorded: its per-column arithmetic spans ~600 dotted money lines over 11 pages and belongs with the JS5 MT re-map. The FinCEN 114 handfills keep their underscore keys (the note states why).
  - Every dated JP5c note is replaced by the declaration or the reason.
  - **Tests:** test_dotted_relations.py — per family and year, a consistent fill PASSes and one wrong cell FAILs exactly its relation (Instructions for Form 8949 (2025) Column (h) example: $6,000 − $2,000 + ($1,000) = $3,000).
- [x] **JEd — Viewer guards and hidden widgets — DONE 2026-10-01** (M; found by the JS5 OH IT 1040 2025 port's adversarial verify; added outside the original 62-tranche table) — pitfall *viewer-guard* = **P-027**
  - *Found.* OH IT 1040's MFS spouse SSN widget ships with the annotation Hidden flag and is shown only by the form's JavaScript, so a filled MFS return carried the SSN in the file and nowhere on paper. A sweep of every cached blank then found 141 mapped widgets flagged Hidden or NoView across AL 40 (72, every page-1 data widget), DE PIT-RES (28, the amended-return lines), GA 500 (21, the voucher), MO-1040 (8-9), NY IT-201 (1) and OH (1) — and two viewer guards: AL 40's page-covering yellow "WARNING: PLEASE USE A DIFFERENT PDF VIEWER" pushbutton (viewable and printable, hidden only by the script, so `render_form` of a filled AL 40 had only ever shown that warning) and the white NoView + Print "print lids" on every page of AL 40 (42) and MO-1040 (31), which a viewer that honours the flags prints over the return.
  - *As built.* `fill_form` runs a flag pass after writing: every written widget gets Hidden and NoView cleared and Print set; every viewer guard (a widget covering ≥ 85% of its page that is a pushbutton or a ReadOnly text panel, `filler.is_viewer_guard`) is set Hidden and listed in `FillResult.guards_hidden` (the MCP tool returns it). `verify_form` reads the filled PDF's flags back as pitfall check P-027 (`verify.widget_flag_problems`): a written widget still Hidden / NoView / without Print, or a guard still viewable or printable, FAILs the report. The golden round trips assert P-027 on every pack. CONVENTIONS "Viewer guards and hidden widgets".
  - **Tests:** test_viewer_guards.py (synthetic hidden widgets and guards through fill → flags → verify, the negative on a re-hidden widget; network: AL 40 hides 41 guards and its page 1 renders the form, MO-1040 hides 32, OH's spouse SSN prints).
  - **P-028 (same tranche, found by the GA 500 2025 placement verify):** GA 500's voucher ships "Paper Return" pre-checked, and the return-medium boxes are separate fields sharing a `group`; selecting "Electronically Filed" left both ticked. `fill_form` now writes `/Off` to the separate-field siblings of a selected group member (an unanswered group stays as shipped). The 2026-10-01 sweep found 21 pre-checked mapped checkbox widgets (GA, KY 740 ×3, MO-1040 ×2, WV IT-140); GA's is the only one on a separate-field group.
- [~] **JD2 — Process: derived counts, suite speed, branches, ROADMAP shape — AGENT HALF DONE 2026-09-28** (M; deps JD1)
  - *As built:*
    - **(1)** scripts/sync_doc_counts.py derives the tool / op / DocSpec / pack counts and rewrites 16 anchors: README, SKILL.md, DEV_PLAN, both package READMEs, PUBLISHING.md's smoke assert, and the two PyPI descriptions. It found the descriptions still at "21 calculation ops" / "22 tools" and the server README at "21 deterministic ops" (JA1.1's list).
      - `--check` runs in CI and in test_readme_sync. scripts/sync_test_count.py stays the test-count entrypoint.
    - **(2)** load_pack memoizes on (path, mtime, size) and hands every caller a deep copy (parse 65 ms vs copy 3 ms on MO-1040). list_forms narrows its glob to `<jurisdiction>/<year>/`.
      - list_forms('federal', 2025): 3.0 s → 13 ms warm (0.38 s cold), with a perf guard.
      - pytest-xdist is a dev dependency, and CI runs the offline suite with `-n auto`: locally 9.5 min on `-n 10`, beside another suite (single-process ~25 min).
    - **(5)** the completed phases (0, E, F, G, I) moved verbatim to docs/HISTORY.md, and every open box names its Phase J tranche (26 boxes, test_every_open_roadmap_box_names_its_tranche). Closed on the way: Phase E's SSN-maxlen box (JEa); A2–A6 now point at JA1/JA2.
    - **(4, local half)** the 17 merged local branches are pruned (`git branch -d`).
    - **(4) done 2026-09-28.** The parked `phase-j2-overlay` is recorded as merged (8945e30, `-s ours`; its code landed by hand in JS4a) and deleted, with the user's OK. `git fetch --prune` shows the 10 remote duplicates are already gone, so `git branch -r --no-merged origin/main` is empty. No stray worktree is left.
  - **Waiting on the user:**
    - (3) the real merge gate / branch protection.
  1. **Derived counts** [G15]. New `scripts/sync_doc_counts.py`, keeping the sync_test_count entrypoint: tools, ops, DocSpecs, packs, hand-fill packs and the ReadOnly total. It rewrites anchors, runs `--check` in CI, and regex-asserts the pyproject descriptions.
  2. **Suite speed** [G25]. About 5.6 min locally and 10.2 min in CI (run 33118033631); two property tests take 48.8 s and 45.3 s; list_forms parses 172 packs per call (~3.1 s; discovery.py:142-147).
     - Pre-filter by path and memoize load_pack on (path, mtime).
     - Run pytest-xdist `-n auto` in CI, keeping the property tests seed-deterministic.
  3. **The real merge gate** [G07]. Record the real gate, or enable branch protection — the user's decision.
  4. **Git hygiene** [G27]. Prune the 17 merged local branches, the 10 remote duplicates (all patch-equivalent to main) and the /private/tmp worktree. Remote deletes need the user's OK.
  5. **ROADMAP shape** [G33]. Split it into OPEN WORK and docs/HISTORY.md, and add a CI check that every open box names its tranche.
  - **Acceptance.**
    - `sync_doc_counts --check` runs in CI.
    - `list_forms('federal', 2025)` < 0.3 s (perf guard).
    - The CI offline job takes < 6 min.
    - `git branch -r --no-merged origin/main` is empty.

### External trigger

- [ ] **JT6 — Finals re-pin, filing-grade flip, 2027 planning pack** (L; fires on check_finals) [TY26-28 + TY26-16]
  - **Per flagged form.** Diff its AcroForm names against the draft pack (the IRS says they are identical), re-render and re-audit, re-pin source_url and sha, and set `source_status: final`.
  - **Knowledge.**
    - Re-verify every draft-backed block against the final instructions, flipping its second_passes entries.
      - Including tax.obbba_schedule_1a (JF8): re-read the final Schedule 1-A and its instructions (the statutory figures cannot move; the face's slopes, rounding and birth date can).
    - Settle the 2026 total-tax line (24a vs 24c).
    - Re-verify the Schedule 3-A qualified-alien mapping.
    - Author filing_thresholds and the no-payment addresses from i1040gi / Pub 501 (2026).
  - **Flip.** Remove the provisional marker; JT0a's invariant enforces that no draft pack remains. A Wave B pack without a final moves to a draft branch instead of holding the flip.
  - **Next year.** Author knowledge/federal/2027.yaml, provisional, from the 2027 inflation Rev. Proc. (not on irs-drop as of 2026-09-23). Scenarios t–t4 flip to final mode.
  - **Target.** The TY2026 dress-rehearsal scenarios (t–t4) fill and verify on the finals **within 5 business days of the last required final**.
    - By the 2025 precedent the form finals and Pub 1040 arrive by mid-January 2027 (f1040 created 2026-01-02; p1040 modified 2026-01-15), and i1040gi arrives last, around late February (2025 edition created 2026-02-25). This is an inference, not a guarantee.
    - An earlier flip, with filing_thresholds and the no-payment addresses left as disclosed absences (file_and_pay pointing at the irs.gov where-to-file page), is a plan choice for the user; it needs a small post-provisional `filing_grade_absent_blocks` list.
  - **External:** the IRS finals and the 2027 Rev. Proc.

### Block 7 — State (federal-first; starts after the federal lanes)

- [x] **JS1a — DC 2025 re-verification — DONE 2026-09-28** (S–M) [G22]
  - *As built:* fetched the re-issued `2025_D40_Book_082026_v1.pdf` (105 pages, modified 2026-08-20; the old URL still 404s). Every quoted booklet passage and figure in knowledge/states/dc/2025.yaml was re-found in it:
    - the OBBBA non-conformity text;
    - DC's own standard deduction ($15,000 / $22,500 / $30,000; additional $1,600 / $2,000);
    - EITC at 100% (childless maximum $649, investment limit $11,950);
    - Schedule H $1,425 and Schedule ELC $1,200;
    - the Line 7 "Other" additions, the April 15, 2026 deadline and both PO boxes;
    - the rate schedule and the two spot-checked tax-table rows ($1,302, $3,595).
  - The 15 citation URLs point at the re-issue, and sources_states.yaml is regenerated. J0.6's STALE SOURCE `unverified` line and JT0c's DC drift quarantine row are removed; the quarantine test now uses a synthetic drift row.
- [x] **JS1b — MA mirror and a seed command — DONE 2026-09-28** (M) [G23]
  - MA Form 1's Wayback cache-seed existed only on the maintainer's disk, and CI and fresh installs got a 403 that said "retry in a minute".
  - Add pack `mirror_urls` with the exact `web.archive.org/web/<ts>id_/<official>` snapshot, tried on 401/403 and ALWAYS digest-verified.
  - Add `taxfill seed-blank`, and name both remedies in the 403 message.
  - **Acceptance:** a mocked 403 exercises the fallback; a digest mismatch fails closed; the network layer is green; the allowlist is empty.
  - *As built:*
    - **Schema:** `FormPack.mirror_urls`. Each entry must be `https://web.archive.org/web/<14 digits>id_/` + this pack's own `source_url`, and a pack with mirrors needs a real `pdf_sha256`.
    - **Fetch:** a 401/403 raises `RefusedFetchError`; `fetch_blank(..., mirrors=)` then tries each mirror. Without a digest a mirror is never used. A mirror that serves other bytes fails closed and caches nothing, not even a quarantine copy. Verified bytes are cached under the OFFICIAL URL's cache name. `fetch_pack_blank(pack)` passes a pack's URL, digest and mirrors; the server's `fetch_blank`/`fill_form`, `scripts/audit_pack.py` and every network test that fetches a pack's blank go through it. The 403 message names both remedies.
    - **CLI:** `taxfill seed-blank <pdf> (--pack <pack.yaml> | --url U --sha256 D) [--cache-dir]` digest-checks a browser-saved blank before caching it (exit 1 on a mismatch or a non-PDF, 2 on missing arguments).
    - **MA pin:** the id_ redirect (`web/<year>id_/<url>`) names each capture while the CDX API is down. Of the four captures, only 20241214140401 hashes to the pinned `86233c2d…` (DOR's 2024-01-17 revision). A live run from an empty cache: 403, mirror, digest match, cached in 0.7 s.
    - **Finding → JS5.** The other captures are DOR re-issues of the SAME URL:
      - 2025-04-14 (`613a1a0d…`): the same 172 fields; only line 39's cross-reference is corrected ("line 51 … line 55" → "line 52 … line 56").
      - 2026-05-22 (`5cbb5655…`, captured 2026-09-20): a rebuilt AcroForm, 360 fields, every name changed.
      The 403 hid both from the drift job, which only warned on a refusal. `check_drift` now digest-checks the NEWEST Wayback capture of a refused host that has `mirror_urls` (`_newest_capture`; only a digest comes back, nothing is cached). It reports MA as REVISED, and that is the one quarantine row left: `fixed_by: JS5`, expires 2027-03-31. The pinned revision is still an official TY2023 Form 1 and stays reachable byte-for-byte, so re-pinning to the re-issue is a full re-map, done with MA's JS5 discovery.
    - **Quarantine:** both MA `network_test` rows are deleted, and a test asserts no `network_test` row remains. The drift row's URL may be cited by a form pack as well as a knowledge pack.
    - **Docs:** CONVENTIONS "Source URL and checksum" (how to find and pin a snapshot); CONTRIBUTING-PACKS triage table; the README shell section.
    - Tests: `test_fetch.py` (6: the fallback, fail-closed, no digest / off-URL mirror refused, the 403 message, `fetch_pack_blank`, `seed_blank`), `test_cli_seed_blank.py` (3), `test_formpack.py` (the mirror shape), `test_check_drift.py` (2: the newest-capture probe matches or reports REVISED; an unreadable archive leaves the warning).
- [x] **JS2 — State law-change sweep (old J5, re-scoped) — DONE 2026-09-28** (M) [PJ-17 + G05(c)]
  - 30 of the 84 2024/2025 packs lacked `effective_law_changes`; 15 had law-change prose (ar24, ar25, ca24, ct24, mi25, ms24, ms25, nd24, nm24, ny24, sc24, sc25, wi25, wv24, wv25).
  - Adjudicate those 15 from the booklets they cite. Record an explicit empty list with "checked <date>, source <url>" for the other 15.
  - **Acceptance:** a gate test that the key is present on all 84 packs (and on every future state year pack).
  - *As built:*
    - **Schema:** `StateKnowledge.law_changes_checked` (`LawChangesChecked`: `checked` date, `finding`, a .gov `citation`). The gate `test_state_law_change_sweep.py` requires the key on every TY2024+ state pack, requires a checked record when the list is empty, and requires the record's URL to be one the pack cites elsewhere. `KnowledgePack` had declared `effective_law_changes` twice (the second, undescribed, won); the duplicate is gone. `assemble_state_sources.py` maps the new block to `law_changes`.
    - **Method.** Every document each pack cites was fetched. Each quoted run in an entry, and in a checked record, was re-found in the fetched text by a normalizing quote checker; 0 misses on all 30. Where the year's booklet has a What's New / Special Information / Legislative Changes section, it was read in full and compared with the prior year's list, so carry-overs are not recorded as new. Where it has none (CT, DE, NJ, NM, SC, VT, CO), the form's line list and the instruction headings were diffed against the prior year, and the tax blocks compared.
    - **Result: 30 packs, 52 entries; 7 packs carry an empty list** (ar25, de25, nd24, nj24, nj25, nm24, ri24). All 30 carry a checked record. Rate changes are `modeled: true` (ar24, ct24's bottom two bands, ks24's SB 1 restructure, mi24's return to 4.25%, ms24/ms25, sc24/sc25, wi25's Act 15 bracket, wv25's §11-21-4i cut, co25's return to 4.4%); everything the engine does not compute is `modeled: false`, so `state_scope` warns.
    - **Two sources the packs lacked were added, fetched and verified:**
      - NY's personal-income-tax detail page for 2024 (`/legal/2024/pit-corp-changes.htm`; the pack cited only the index);
      - PA's Working Pennsylvanians Tax Credit page. The credit came in the November 2025 budget, after the April 2025 PA-40 instructions were printed.
    - **Defects found and fixed in the prose:**
      - WV 2024 claimed a "retroactive 2024 rate cut" and quoted §11-21-4g as applying from January 1, 2024. The statute (fetched) says 2023, and the 2024 rates are 2023's.
      - WV 2025's three rate notes were a blind year-substitution: 2024's rates and constants, a misquoted statute, and "not TY2025, not TY2025". They now cite §11-21-4i (2024 Second Special Session SB 2033), whose 2025 rates the tax block already carried.
    - **Found, not fixed here → JS2b:** the WV 2024/2025 packs' other source rows were copied from 2023 with only the directory year changed. Four URLs per pack 404 (`…/PIT/2024/it140.2023.pdf` and the like), their labels say "2023", and several line references are 2023's. Examples: 2024 Schedule M's increasing modifications are lines 53-60 (total 61), not 51-58; HEPTC goes to line 19, not 18. The 2025 booklet itself is inconsistent here: IT-140 lines 2/3 cite "line 61 / line 52 of Schedule M" while its Schedule M prints 59/50.
    - SC 2025 records a live question, not an answer: SC conforms to the IRC through December 31, 2024, and its August 2025 instructions predate the July 2025 federal act. Line 1 is federal taxable income, and the booklet does not say how the new federal deductions are treated.
- [x] **JS2b — Year-currency repair: WV 2024/2025, VT 2024, HI 2024 — DONE 2026-09-28** (S–M) [JS2 finding]
  - JS2 found packs rolled forward from 2023 with only part of their text updated.
  - *As built:* each repair re-read the year's own document, fetched 2026-09-28.
    - **WV 2024 and 2025:**
      - Four URLs per pack 404'd (`…/PIT/2024/it140.2023.pdf` and the like). 2024 now cites its own `it140.2024.pdf`, `schedule-HEPTC1.2024`, `schedule-M.2024` and `schedule-A.2024`. 2025 cites its Schedule M and A; its IT-140 and HEPTC-1 live only inside the booklet, which is cited instead.
      - The credit figures were 2023's (3x and 1.5x the 2023 poverty guideline). Now:
        - Family Tax Credit Table 1: 100% at $15,060 / $20,440 / $25,820 / $31,200 for 2024, and $15,650 / $21,150 / $26,650 / $32,150 for 2025, with the full one-person phase-out;
        - HEPTC: $45,180-$93,600 (+$16,140) for 2024, and $46,950-$96,450 (+$16,500) for 2025;
        - SCTC: $22,590-$46,800 (+$8,070) for 2024, and $23,475-$48,225 (+$8,250) for 2025.
      - Line references: SCTC goes to IT-140 line 18 and HEPTC to line 19 (were 17/18). 2024 Schedule M increasing modifications are lines 53-60, totalled on line 61 (subtractions on 52). Page references: starting point p.24, Who Must File p.17, Schedule A Part II instructions p.32. The treaty note cites the year's own instructions, and the due dates are April 15, 2025 / 2026.
      - The "payable to WV Tax Division" claim is printed nowhere. `check_payee` keeps the addressee, and a `check_payee_note` quotes the Line 24 instruction.
      - The 2025 booklet's own inconsistency (IT-140 lines 2/3 cite Schedule M lines 61/52, while the 2025 Schedule M prints 59/50) is recorded in `unverified`.
    - **VT 2024:**
      - The credits cited the 2023 IN-112 documents. They now cite the 2024 ones, with birth years 2019-2024 and IN-111 line 26c (the new Child Care Contribution line moved it from 25c). The child tax credit example is fixed ($720 covers $138,001-$139,000 only).
      - The renter credit now uses the 2024 eligibility and due dates (April 15 / Oct. 15, 2025). The filing requirement is reworded for 2024, the IN-116 voucher and the IN-113 instructions are 2024's, and the Form IN-111 link points at `IN-111-2024.pdf` (was `/document/2023-form-111`).
    - **HI 2024:** the renter credit's label said "Rev. 2023" and cited the 2023 N-11 instructions; the linked 2024 Schedule X is "(REV. 2024)" and its line 12 names Form N-11 line 29.
    - **The drift job never probed state citations:** `check_source_urls` read only `knowledge/sources.yaml`. It now also probes the generated `sources_states.yaml`, which is how WV's dead URLs would have surfaced.
    - **Gate** `test_state_pack_year_currency.py`, on every TY2024+ state pack:
      - no citation file from an earlier year: WV's pattern (the pack's year in the directory, an earlier year in the file name), or any earlier-year file outside law and bulletin URLs. Three rows are adjudicated: MN's December bracket press releases and SC's TC-60, whose 2024 revision still 404s.
      - none of the carried-over phrasings found.
      - It fails on the pre-repair packs (vt24, wv24, wv25) and passes after.
- [x] **JS3a — Scaffold starts from the newest base — DONE 2026-09-28** (M) [G05 + PJ-15 (1)]
  - `scaffold_state_year.py` gains:
    - `--base newest`;
    - `--rows <json>`, seeded from the 16 recovered discovery rows (url + sha256 in the wf_babce8da-141 journal);
    - a cache-first triage (today network-only, :72-101);
    - year+1 upload-folder and revision-token derivation (AL, CT and DC tokens are stale today).
  - **Acceptance:** the offline triage reproduces the recorded rows; UT 2025 triages PORTABLE against UT 2024.
  - *As built:*
    - **Base and rows.** `--base newest` gives each form its newest shipped year below the target (UT 2025 → UT 2024). `scripts/state_discovery_rows.json` holds the 16 journal rows (AL, AZ, CO, DC, DE, ID, KY, LA × 2024/2025) with their pinned digests, public fields only. `--rows` substitutes a row's URL for the derivation and reports `recorded_verdict` / `reproduces`.
    - **Triage.** It is cache-first: the triage cache, then the shared blank cache for a pinned digest. A cached or downloaded file that is not the pin is `DIGEST-MISMATCH`, never trusted. `--offline` never opens a URL; an uncached candidate is `NOT-CACHED`.
    - **Derivation rules:**
      - 4-digit years move with their base+1 upload folder in one pass, so AL's `uploads/2024/01/23f40.pdf` → `uploads/2026/01/25f40.pdf`;
      - CT's MMYY suffix `_1223` → `_1224`;
      - `%20` separates a year rather than joining its digits (KY's `Form%20740%202023.pdf`);
      - a revision date in the file name (DC `01222024` / `011525`, ID `08-23-2023`; month and day range-checked, so `SC1040_2023` is not one) makes the row `revision-dated (needs a recorded row)` instead of a wrong candidate.
      - An underscore rule for MD/ME (`23_forms`) derived only dead URLs and was dropped.
    - **Downloads** use the browser User-Agent `taxfill_core.fetch` uses: CO's host answers 403 to the old agent. An incomplete TLS chain (tax.idaho.gov) is retried through curl. Either way the bytes are classified, and digest-checked for a recorded row.
    - **Acceptance, run 2026-09-28.** Online, 16/16 recorded rows reproduce; offline, from the warmed cache, 8/8 per year. UT 2025 is PORTABLE against UT 2024, and the network test `test_ut_2025_triages_portable_against_ut_2024` pins it. The 2025 newest-base work-list (JS3b's input) is: 5 already shipped (ar1000f, or40, pa40, ny it201/it203); PORTABLE az140, d40 and tc40; NEAR-PORT al40 (34 fields) and ky form740 (4); 16 RE-MAP; the rest URL-DEAD, no-year-token or print-only. In newest mode a form with a target-year pack is reported `shipped` and not triaged; a fixed `--base` keeps the old census.
    - Tests: `test_scaffold_state_year.py` — 12 offline (derivations, revision dates, newest base, shipped forms, rows + cache-first + digest mismatch + offline, the rows file is public data) and 2 network (UT, and all 16 rows reproduce).
- [x] **JS3b — Cheap state ports — DONE 2026-09-28** (M–L, per pack) [G05 + PJ-15 (2)–(3)] — 11 pack-years shipped: UT 2025, AZ 24/25, DC 24/25, KY 24/25, LA 2024, ID 2024. AL 40 24/25 moved to JS5 (measured below).
  - UT 2025 TC-40 is PORTABLE and unshipped: files.tax.utah.gov/tax/forms/2025/tc-40.pdf returns 200, sha256 0eac22fb…37cdf, and all 106 mapped UT-2024 fields exist in it.
  - Then the rows marked PORTABLE / NEAR-PORT, TY2025 first: AZ 24/25, DC 24/25, KY 24 (PORTABLE) / 25 (NEAR-PORT, 4 fields), LA 24, AL 24 (NEAR-PORT, 3), ID 24 (NEAR-PORT, 2).
  - **Acceptance, per pack:** re-downloaded with a digest pin, vision-audited, golden round trip.
  - *Progress:*
    - **UT 2025 TC-40 — SHIPPED 2026-09-28** (`formpacks/states/ut/2025/tc40`).
      - The pin matches three independent downloads (`0eac22fb…37cdf`), and the printed identity is 40501 / "2025".
      - All 111 widgets are identical to 2024 (page, /Rect, /MaxLen, /Ff, /FT, /AP states). There are zero ReadOnly widgets and the same script-slot census, and the scripts are byte-identical and format-only.
      - Pages 2-3 of the 2025 file have no text layer, so they were rendered and compared: zero renumbering.
      - Face deltas: 4.5%, $2,111, $18,213 / $27,320 / $36,426, the line-14 Schedule A 5e-less-5b/5c caption, fund codes 18 and 19, and the year captions. The UT 2025 knowledge pack already matched all of them.
      - The sentinel audit ran 104/104 with 0 fails, and all three pages were read. Every UT network gate passes: golden round trip, ReadOnly audit, maxlen, verify sweep.
      - UT 2023, 2024 and 2025 now declare the Part 4 contributions total; it waited only on the dotted-id grammar (JP5c). `test_dotted_relations.py` checks it both ways.
      - The line-4 cross_form moved to `f1040.11a`: the 2025 Form 1040 prints AGI on line 11a. The pack-invariant gate caught the carried-over `f1040.11`.
    - **AZ Form 140 2024 and 2025 — SHIPPED 2026-09-28** (`formpacks/states/az/{2024,2025}/az140`).
      - URLs come from the discovery rows (AZDOR's `document/` path; the scaffold's derivation 404s). Each pin matches four downloads: the discovery pair, the triage and a direct re-fetch. Printed identity: ADOR 10413 (24) / (25).
      - Against the 2023 base the 430 widgets keep every name, /MaxLen, /Ff, /FT and /AP state, but 154 moved /Rect by a few points to about 20 pt as captions re-wrapped (pages 1, 2, 3, 5 and 6). Only two changed size, both taller, so no capacity-based maxlen shrank.
      - Every row was re-read: the page 1-2 line lists extract identically, and pages 5-6 (no row text layer) were rendered and compared letter by letter (A-T, A-W). The sentinel audit then placed all 391 lines on their rows, all six 2024 pages read, 0 fails.
      - 2025 is widget-identical to 2024.
      - Face deltas: the page-3 charitable increase is 31% → 33% (2024) → 34% (2025), matching the knowledge packs; Form 301 cross-references moved to lines 30/60; row V gained an "MCTCP worksheet" pointer. 2025's cross_form is `f1040.11a`.
      - Every AZ network gate passes.
      - The four shared radio questions (filing status, itemized/standard, political party, account type) now carry `group:` ids in all three AZ packs, which clears az/2023's `SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID` debt row.
    - **DC D-40 2024 and 2025 — SHIPPED 2026-09-28** (`formpacks/states/dc/{2024,2025}/d40`).
      - Each pin matches three copies: the discovery row, the triage cache and a fresh re-fetch. Printed identity: page-1 barcode 2404001100002 / 2504001100002, footer "Revised 01/2025" / "Revised 11/2025".
      - Both years add ONE widget over the 2023 base, the Line 27 oval for the new monthly-EITC election ("Do you choose to receive your DC EITC refund in 12 monthly payments instead of one total payment?"; for tax years from 2024 the payout is a choice, not automatic). It maps to `27.monthly_eitc_payments`: `EITC Opt in` → `/Choice1` in 2024, `LUMPSUM PYT` → `/SSN_1` in 2025.
      - The printed numbering did not move: the 2023 pack already keyed `D40_Line_26d/26e` to lines 27d/27e.
      - 2025 moved the MediaBox to [9 9 621 801] and every widget by (+13, +13), so the page-relative placement is unchanged; the audit renders confirm it. The account-number box went to /MaxLen 17.
      - Face deltas: the 27c multiplier is ×.70 (2024) → ×1.00 (2025), and both knowledge packs already carry it (70% with the new election; 100% for 2025, election kept). 2025's cross_form is `f1040.11a`.
      - The sentinel audit ran 100/100 with 0 fails in both years, and all six pages were read. Every DC network gate passes.
    - `sync_doc_counts.py` now also derives the post-2023 jurisdiction counts and the SKILL.md / README / ROADMAP state lists, so a port no longer leaves them stale. After DC it also anchors the README per-year TY2024/TY2025 counts, the M5 "N of the 42 … now fill" list (the AZ port had left it at 13) and the ROADMAP banner's "(2024+2025)" list.
    - **KY Form 740 2024 and 2025 — SHIPPED 2026-09-28** (`formpacks/states/ky/{2024,2025}/form740`).
      - Each pin matches three copies: the discovery row, the triage cache and a fresh re-fetch. Printed identity: 240001 / 250001 42A740 (10-24) / (10-25), "FORM 740 (2024)" / "(2025)" on pages 2-3.
      - 2024 keeps every 2023 widget (page, /Rect, /MaxLen, /Ff, /FT, /AP states). It adds ONE: the line-34a "Check if Form 2210-K attached" box, which the 2023 face printed with no widget, mapped as `34a.form_2210k`. The PDF gains a blank, widget-less fourth page (rendered). Face deltas: $41,496 / $3,160 / 4%, already in the knowledge pack.
      - 2025 (NEAR-PORT, 4). `740CityStateZip` is split into `740City` / `740State` (/MaxLen 2) / `740Zip`, mapped as mailing_address.city / .state / .zip. The ZIP box has no /MaxLen, so its pack maxlen 10 (ZIP+4) is sized to the 54.7 pt box: the first audit flagged the overflow. The three signature boxes are no longer widgets (signed by hand), so their lines are dropped. 69 widgets moved by at most 7.2 pt; renders confirmed every row. Face deltas: line 5 "line 11a" (cross_form `5_b == f1040.11a`), $42,760 / $3,270, still 4%, already in the knowledge pack.
      - All three KY years now carry group ids on the five shared-/Btn questions, retiring ky/2023's `SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID` row.
      - The 2023 NOTE claiming the grammar could not reference column lines was stale after JP5c and was never flagged. It is now declared: 7.a, 9.a/9.b and 14.a/14.b as printed, and 19 = 18 A + B (checked against the 2023 and 2024 packets). Line 7 column B stays out because its line-5 key `5_b` (dot-free so cross_form can name it) does not tokenize in the relation grammar. 11 stays out because a zero is plausible under the deduction. `test_dotted_relations.py` checks all three years both ways.
      - Sentinel audits 108/108 (2024) and 107/107 (2025), 0 fails. All pages were read. Every KY network gate passes for 2023-2025.
    - **LA IT-540 2024 — SHIPPED 2026-09-28** (`formpacks/states/la/2024/it540`). PORTABLE in the triage (no mapped name vanished), but a real re-layout:
      - The booklet is renamed IT-540-WEB-BC. The pin matches three copies. Printed identity: "2024 LOUISIANA RESIDENT", barcodes 62530..62533, "Calendar year return due 5/15/2025". Still 17 PDF pages, with the same four return pages mapped.
      - Return page 1's date row now holds four 8-cell combs. The DOBs moved (SDOB 186 pt), and two NEW boxes are mapped: "Decedent's Date of Death" and "Spouse's Date of Death".
      - Return page 4 gained an "Email Address" row (mapped), and the signature dates moved up 24 pt. Its 2-D-barcode machinery (NoBarcode, ArchiveDataBarP1, two pushbuttons) is left unmapped.
      - Eleven mapped boxes gained a /MaxLen, and each pack maxlen now tracks it (suffixes 4 -> 3, unit type 5 -> 6).
      - Every text /DA went from Helvetica Bold 10 to Courier Bold 12. So the ZIP box (54.5 pt, 7 characters) caps at 5, and the dependent-name columns clip long names, which is what surfaced JS3c.
      - The date boxes (2023's two and 2024's four) are now `comb: true`: the cells print M M D D Y Y Y Y, and "01/15/2024" would put slashes in the cells.
      - The LA 2023 header's "109 field entries" is corrected to 148 (2024: 151).
      - Face deltas: the years and line 34 "Schedule D, Line 20" (was 22). Sentinel audit 147/147 with 0 fails, all four return pages read. Every LA network gate passes.
    - **ID Form 40 2024 — SHIPPED 2026-09-28** (`formpacks/states/id/2024/form40`).
      - The pin matches three copies. Printed identity: "Form 40 2024", footer "EFO00089 09-04-2024 Page 1/2 of 2".
      - NEAR-PORT: the two missing fields are the direct-deposit boxes, now split into one widget per digit (9 routing + 17 account cells). They map as `57.routing_number.1..9` / `57.account_number.1..17`, maxlen 1 each, the AR 1000F per-digit shape. Every other mapped widget keeps its page and /Rect.
      - StateAbbrv / PreparerState lost their /MaxLen, and the pack's maxlen 2 still binds (JEa).
      - Face deltas: the years, the $14,600 / $21,900 / $29,200 standard deductions (already in the knowledge pack with the 5.695% rate), and a printed floor on line 19 (already undeclared).
      - Sentinel audit 145/145 with 0 fails, both pages read. The full network gate set (799) passes.
    - **AL 40 2024 / 2025 → JS5.** The triage calls them NEAR-PORT (3 / 34 fields gone), but the census of the 2,260 mapped fields says partial re-map:
      - 2024 splits page 15 in two (every later page shifts +1). 166 mapped widgets moved more than 20 pt and 34 more by 5-20 pt. Schedule OC gains carry-forward and limitation columns (40 new widgets), and CHECKOFF18/19 and SCHOCLINE9PR are gone.
      - 2025 adds four more pages (2,846 widgets) and drops 34 mapped fields.
      - A 41-45-page sentinel read of a 2,260-line pack is JS5 work, not a cheap port.
- [x] **JS3c — Courier-aware clipping check — DONE 2026-09-28** (M; added 2026-09-28 by JS3b, outside the original 62-tranche table)
  - *Found by the LA 2024 port.* Its blank moved every text widget from "/HeBo 10" to "/CoBo 12". The audit's renders showed the dependent-name columns clipping "Test Taxpayer 27" at both edges while verify reported 0 fails. The P-001 width estimate used the 0.5-em Helvetica average for every font, but Courier advances exactly 0.6 em a glyph. 31 state packs map Courier text widgets (AL alone 2,074), so verify under-reported clipping on all of them by a sixth.
  - *As built:* `read_text_widgets` resolves each widget's /DA font through the AcroForm /DR /BaseFont, sets `TextWidget.monospace`, and falls back to Acrobat's /Cour /CoBo /CoOb /CoBO aliases when unresolvable. `clipping_scan` uses 0.6 for a Courier face, on the single-line width and the multiline row budget, and names the metric in its message.
  - *What the exact metric found* (network goldens: 51 overflows over 9 packs):
    - **Real capacity limits, fixed in the packs.** A 10-character MM/DD/YYYY date does not fit the IN (Date1/Date2), KS ("date signed" x2) or MD (Text Box 101/103) signature-date boxes: they cap at 8, "MM/DD/YY". KS's school-district and historic-site boxes hold 5, not the 6 their Helvetica-era TIGHTER_THAN_WIDGET rows claimed. MT's EHRC line 21 is the one whole-number digit of a 0.00-1.00 Credit Multiplier, so maxlen 2 -> 1. The KS / MD / WV TIGHTER_THAN_WIDGET rows are re-measured in Courier.
    - **Unrealistic test data, fixed in the generator.** `synthetic_values` put 16-character "Test Taxpayer N" into first-name boxes, "Test N" into suffix, count and code boxes, and a 10-character date into boxes the pack caps shorter. It now writes realistic lengths: suffix "JR", unit type "APT", first-four-letters "TEST", names "Tess N", free text "TN", and a two-digit year under a date cap.
  - *Also fixed:* two JS3a network tests went red when JS3b shipped UT 2025 (newest mode stops triaging a shipped form), because the per-state gates never ran them. They now replay the recorded base (2023; UT against a fixed 2024) and pin the newest-mode "shipped" report.
  - **Tests:** `test_js3c_*` in test_verify.py — Courier vs Helvetica on the same value, the multiline budget, /DR resolution where a resolved /BaseFont beats the alias name. Every network gate passes.
- [x] **JS4a — Overlay verifier fixed and tested — DONE 2026-09-28** (M; was on `phase-j2-overlay`) [PJ-01 + PJ-06]
  - *As built:* the parked branch's overlay filler (overlay.py, the `overlay:` schema, `taxfill locate`, and the fill_form / verify_form / fetch_blank routing — still 23 tools) is merged onto main by hand; filler, cli and server had moved on for a month.
    - **verify_overlay now reads the DECLARED box.** It keeps only glyphs drawn in the stamp font (unembedded base-14 Helvetica, found through each character's pdfium text object; the CT, HI and SC blanks embed every font they print). It requires exact equality, left to right, and a blank line's box must hold nothing. Unknown keys are refused.
    - The PJ-01 negatives (stamped 14,000 / 10 / 1,200 against expected 4,000 / 0 / 200) FAIL, and the failure names the value that is actually stamped. The fail-safe limit is recorded: a blank's own unembedded-Helvetica text inside a box reads as stamped.
    - `fill_form(rehearsal=True)` refuses a hand-fill pack. server.py imports overlay lazily, and a subprocess test pins that.
  - **Tests:** test_overlay.py (12, on a synthetic blank printed in embedded Vera) covers the round trip and every alignment, the PJ-01 negatives, blank-box, wrong-coordinate and beyond-the-page failures, the shrink / overflow / non-WinAnsi / comb warnings, the widths table vs pypdf's Core-14 metrics, `locate_labels` whole-word hits within 1 pt, and the fail-safe. test_overlay_tools.py (5) covers fill_form → verify_form through the tools, the 23-tool count, the no-coordinates refusal, and `taxfill locate`. CONVENTIONS.md gains the overlay-coordinates section.
  - Found for JS4d: the NM PIT-1 manifest's `source_url` is an AWS API-gateway host (NM TRD's file service), which fetch's official-host rule refuses, so the NM blank cannot be fetched or located until it has an official URL or a seeded copy.
- [x] **JS4b — verify_filing routing, FBAR "blank", DOR guidance — DONE 2026-09-28** (M) [PJ-08 + PJ-10]
  - *As built:*
    - **verify_filing** takes a stamped print-only form in the same list, with `expected` (the fill_form values). It gets the OVERLAY verdict under an `overlay` section, and the filing is ok only when every item is. The limits say the stamped forms took no part in the cross-form identity / cross_form checks, since there are no fields to read back. Guards: `independent` keys are split per item kind, and a stray form_key is still refused. A filing with no AcroForm item is refused, pointing at per-form verify_form.
    - **The FBAR**: a new `efile_only` manifest flag (set on all four fincen114 years, validated to require `instructions` and forbid overlay blocks) makes fetch_blank and fill_form refuse it, pointing at the BSA E-Filing System. hand_fill_worksheet still serves the value-gathering sheet.
    - **The agencies' printing rules**, read 2026-09-28 and recorded verbatim in a new `printing_guidance` list (quote / source / url). CT: the form face, "Complete return in blue or black ink only." HI: the machine-read N-11, "Enter One Letter Or Number In Each Box" / "Do NOT print outside the boxes", so its overlay stamps combs. NM: "Type or print using blue or black ink.", computer-generated forms must meet "the printing and legibility requirements of the software company", and the comma is the only punctuation allowed. SC: no ink, font or machine-print rule, only the foreign-address line.
    - None publishes a minimum type size. The new `min_font_size` field (the overlay's shrink floor when set) stays unset on all four. stamp_overlay returns the rules with every stamp.
  - **Tests:** test_overlay_tools.py (JS4b): a real f8843 filed with a stamped CT-1040-shaped form (ok, a PJ-01-style wrong value FAILs, `expected` required, stray key refused), the FBAR refusals x4 years, the efile_only schema rules. test_overlay.py: the rules and the min_font_size floor in the stamp result, and a network test that re-reads every quote verbatim from its source (the NM booklet sits on the AWS gateway host fetch refuses, so its quotes rest on the 2026-09-28 read).
- [x] **JS4c — CT-1040 2023 pilot — DONE 2026-09-28** (M–L) [PJ-07]
  - *As built:* every line of formpacks/states/ct/2023/ct1040/handfill.yaml carries an `overlay` block, so fill_form stamps the whole return (181 lines, 184 placements).
    - Each box was measured from the blank's own vector rectangles and, for per-character cells, its underline strokes. A workflow did the first pass: 4 page authors and 4 adversarial verifiers, each stamping sentinels, verifying and reading its page at scale 3, plus a second 2+2 pass for the added lines. The main loop then re-extracted every cell edge, re-stamped and read all four pages.
    - **Engine, found by the pilot:** CT prints uneven per-character cells (the SSN 3-2-4 around printed dashes, MM-DD-YYYY dates, phones 3-3-4, Line 54's digits either side of a pre-printed point). A uniform `comb` missed them by up to 5 pt. `OverlayBox.cells` + `cell_w` now centre each character in its measured cell and drop separators, validated to sit inside the declared box.
    - `overlay` may also be a list, so the SSN is stamped, and verified, in all four page headers.
    - **Manifest, found by the pilot:**
      - Line 52's name and two-letter code are separate boxes (52a / 52a.code).
      - Each property row has two date boxes (60-62 .date_1 / .date_2).
      - Line 66 stamps only the digits after its pre-printed point.
      - The read found 25 printed entries the manifest had never listed: the fiscal-year dates, the deceased boxes, suffixes, country code, residence town and ZIP, the MFS spouse name, and page 2's signature dates, phones, email, paid-preparer block and third-party designee. All are lines now; the signatures stay hand-written.
      - The verifiers' two catches were fixed: tax_year.begin's box stops before the pre-printed "2023", so a full date FAILs instead of overprinting, and the preparer FEIN cells sit inside their white box.
  - **Tests:** test_ct1040_overlay.py covers every line's coordinates, the SSN on all four pages, and a demo return plus a full fiscal-year / preparer / designee return stamping on the real blank with no warning. Both pass the OVERLAY verdict on all 184 placements, a wrong line 1 FAILs exactly lines 1, 3 and 5, and all four pages render. test_overlay.py covers cells layout / validation and repeated placements (a missing header copy FAILs). test_overlay_tools.py covers the real ct1040 through fill_form → verify_form.
- [x] **JS4d — SC, NM, HI overlays — DONE 2026-09-28** (L, per pack) — all four print-only state returns now stamp.
  - SC line numbers are not isolated words in the text layer, so anchor on captions.
  - **Acceptance, per pack:** as JS4c.
  - *Progress:*
    - **SC1040 2023 — DONE 2026-09-28.** 162 lines, 164 placements. SC's entry areas are ruled table cells, measured from the ruling lines and captions by a 3-author / 3-verifier workflow, then re-stamped and read in the main loop.
      - The same read found 51 printed entries the manifest had never listed: deceased boxes, fiscal-year dates, the spouse suffix, the four-row dependents table, the b / h / j type blanks, the p / q dates of birth, subsistence days, the Line 33 exception code, the signature date, the preparer-discussion Yes / No and the paid-preparer block. The SSN also repeats in the page 2-3 headers.
      - Lines 4 and 32 were "left manual" because their dotted addends "cannot appear in a compute expression". That stopped being true with JP5c, and the stamped demo return showed the result: Line 4 blank, so Line 5 wrong. Both now compute, the same stale-grammar-note class JEc cleared elsewhere.
      - test_sc1040_overlay.py covers every line's coordinates, the computes, and a demo and a full return stamping on the real blank with no warning, verifying on all 164 placements, with a wrong value FAILing.
    - **NM PIT-1 2023 — DONE 2026-09-28.** 117 lines, 118 placements, from a 2-author / 2-verifier workflow plus the main-loop read.
      - NM TRD serves the blank from an AWS API-gateway host, which fetch's official-host rule refused, so the pack could not even fetch its blank. Verified from the source: tax.newmexico.gov/forms-publications/ loads its forms table through prod.realfile.rtsclients.com/js/rf-tables.js, which fetches from that host. fetch now takes it, and ONLY with a pinned sha256, via `fetch.PINNED_ONLY_BLANK_HOSTS` (one entry, with that provenance). A look-alike gateway host is still refused.
      - The read found 20 unlisted entries, and 3c / 3d were combined labels over separate City / State / ZIP and Country / Province cells.
      - test_pit1_overlay.py: the demo and full returns (including a loss on line 9) stamp clean and verify on all 118 placements. test_fetch covers the pinned-only rule.
    - **HI N-11 2023 — DONE 2026-09-28.** 169 lines (was 38), 177 placements, from a 4-author / 4-verifier workflow plus the main-loop read of every page.
      - The manifest stopped at line 24. The read listed the other 131 printed entries: the fiscal-year and date-of-death cells, the four return-type ovals, M.I. / suffix / first-four-letters boxes, care-of and foreign address, the exemption ovals and counts, the six-row dependents table, lines 25-55 with their ovals, the designee, election fund, signature and paid-preparer blocks. The name line and both SSNs repeat in the page 2-4 headers.
      - N-11 is machine-read, so the engine learned three things (CONVENTIONS "Machine-read forms"). `mark: fill` paints an oval in the printed shape: straight sides and round ends, because an inscribed ellipse left the four shoulders pink. `minus` shades the printed minus for a loss, and a negative in digit cells without one is refused. Money in `cells` fills from the right. The verdict reads painted marks from a render.
      - Verifier catches, all fixed: pdfium's stroked-path bounds carry the full 0.75pt stroke on each side, so 28 painted ovals spilled about 0.35pt past the outline. The main loop found the other 13 the verifiers missed, and all 41 now use the outline's outer edge measured from the path points. The minus boxes painted the whole pink square, where the face's Example darkens only the minus glyph. The DHS count filled from the left. The preparer's self-employed X touched its frame, four activity / product entries started against their caption's colon, and dependent row 6 was needlessly indented.
      - Computes: line 22 no longer sums 21a-21f. Its face points to the itemized-deduction limitation (Instructions page 19), and a standard-deduction filer must leave it blank, where the sum stamped "0". Line 42 now computes max(0, 41 - 36), which covers a negative line 36 the way the Instructions (page 22) do.
      - test_n11_overlay.py: every line's coordinates, the 41 painted ovals and the 8 minus boxes, the computes, and a demo return plus a full loss-year return stamping clean and verifying on all 177 placements. A wrong sign and an unpainted oval FAIL. test_overlay.py covers the oval shape, right-filled cells, the minus box and the mark validation.
- [ ] **JS5 — State 2024/2025 re-maps and URL discovery (rest of old J3)** (XL, per pack) [PJ-15 (4)–(5)]
  - Open at the 2026-09-11 count: 73 pack-years, minus JS3b.
    - 2024: 32 (RE-MAP 10, URL-DEAD 11, no-token 7, print-only 4).
    - 2025: 41 (PORTABLE 1, RE-MAP 12, URL-DEAD 17, no-token 7, print-only 4).
  - TY2025 before TY2024. Every CA pack is a full re-map.
  - **AL 40 2024 and 2025** (from JS3b, measured 2026-09-28; see the JS3b progress note): re-place the Schedule OC rows and map its new carry-forward / limitation columns, re-read all 41 (2024) / 45 (2025) pages, and resolve the 3 / 34 vanished fields.
  - Resume discovery for the 20 never-started states plus OK, MA and NE in resumable pools of 3–4 workers. The remaining TY2024 rows fold into JS7.
  - **MA 2023 Form 1 re-map** (JS1b finding): mass.gov now serves the 2026-05-22 re-issue, a rebuilt 360-field AcroForm. Re-map the pack onto it (its named ovals may also clear the 11 unmappable `Checkcash`/`Checktp1` kids), re-pin `pdf_sha256` and `mirror_urls` to a matching capture, and delete the MA drift row in `scripts/freshness_quarantine.yaml`.
  - **Acceptance, per pack:** digest pin, vision audit, golden round trip, triage row updated.
  - *Progress (2026-09-30):*
    - **Re-triage** (`--base newest`, cached candidates re-hashed): TY2025 has 37 open pack-years, TY2024 27. The triage now reports `SAME-AS-BASE` when a derived URL serves the base year's own blank: NM TRD's gateway names a file by the GUID in its path, so the derived "2024pit-1.pdf" / "2025pit-1.pdf" were the 2023 PIT-1. NM's real files come from its own library search: the 2024 PIT-1 has its own GUID, and 2025 posts only inside the 136-page "2025 PIT Packet".
    - **Print-only layouts vs 2023** (word positions and a render diff): HI N-11 2024 is unchanged; HI 2025 drops the two amended-return lines on page 4 (51/52), renumbers 53-55 to 51-53 and rebuilds the preparer block; SC1040 changes page 1; CT-1040 shifts pages 1-2; NM PIT-1 2024 moves page 2.
    - **HI N-11 2024 — DONE 2026-09-30.** The 2024 blank keeps every printed word within 0.5 pt of 2023, and a render diff differs only where text changed, so all 177 overlay boxes carry over (test_n11_2024_overlay.py pins box-for-box equality). Face deltas: line 15 $8,082, line 23's standard deduction $4,400 / $8,800 / $6,424 (Act 45 SLH 2024, already in the 2024 knowledge pack), N-325 on line 27, and the line 38 / 39 / 46 years. The printing rules were re-read verbatim in the 2024 face and Instructions; test_overlay.py's quote re-read now covers every year's manifest, not only 2023's.
    - **NM PIT-1 2024 — DONE 2026-10-01.** The real 2024 file is a different GUID in NM TRD's library (found through the library's own search API; the derived name under the 2023 GUID still served the 2023 blank). Page 1 is unchanged (513 of 514 path objects identical; all 71 boxes carried), page 2 moved below line 28: line 29's caption wraps and its box doubled in height (re-measured), and the 37 boxes from line 30 down moved exactly −11.33 pt, each matched to its own ruling lines. 118 boxes: 80 carried, 37 moved, 1 re-measured; the HSD box is re-keyed `hca_share` after the face's rename. Face deltas: the 4a/4b "Claimant's" captions, line 15's PIT-ADJ line 28, line 29's entity-level / composite wording, the years. The printing rules were re-read verbatim in the 2024 Instructions; the demo return's line 18 is the 2024 PIT-TRT lookup. Built and adversarially verified by the wave-P agents (PASS, one low finding fixed), then stamped and read again at integration (test_pit1_2024_overlay.py).
    - **GA Form 500 2025 — DONE 2026-10-01** (`formpacks/states/ga/2025/ga500`, a RE-MAP of GA 2023). The 2025 web PDF drops the on-screen calculator (222 `b.*` keys and 42 `cdr*` controls, none mapped) — 676 widgets / 559 names (2023: 965 / 848). Of the 532 widgets the 2023 pack maps: 293 SAME, 195 MOVED, 10 CHANGED, 4 moved page, 30 GONE (the exemptions 6a-6c and lines 11a-11c / 14a-14c now print as single lines or "Reserved"; Schedule 3's 10b / 11a / 11b, Schedule 4 Part I line 5 reserved); 8 NEW widgets (the dates of birth, the single-line 11 / 14 / 46 and S3L11 cells, L7C, the Schedule 4 name copies, the page-header SSN copy). Face deltas: line 11 is one $12,000 / $24,000 standard-deduction line, 14 is "Line 7c × $4,000", 16 is "Multiply Line 15c by 5.19%", Schedule 3's line 9 time-ratio wording and its S / I boxes swapped, IND-CR 202 prints 50%. STATE_COMPUTED_READONLY 189 → 181, four NONZERO_READONLY_DEFAULTS rows (TAXTYPE 09, YY 2025, the two $35,000 military caps). 550/550 sentinels confirmed on 28 rendered pages; two adversarial verifiers (semantics PASS, placement PASS) and a fixer (8 fixed, 4 rejected with evidence) and a narrow re-verify (PASS). The two "repo-level" open points the verifiers raised became JEd (P-027: the hidden 525-TV cells and Schedule 3 ticks now print; P-028: the pre-ticked "Paper Return" clears). Knowledge mismatches reported for JS2c: IND-CR 202 reads 50% on the face (the 2025 knowledge pack says 30%), line 19 is the "Eligible Itemizer" credit, the 525-TV PO Box 740323 is absent.
    - **MO-1040 2025 — DONE 2026-10-01** (`formpacks/states/mo/2025/mo1040`, a RE-MAP of MO 2024). The 2025 bundle keeps 32 pages but re-orders them (MO-A 7-9 → 6-8, MO-PTS 22-23 → 9-10, MO-CRP 24-28 → 11-15, MO-TC 19-20 → 16-17, ...); 1,148 widgets / 981 fields (2024: 1,191 / 1,028). 59 mapped keys gone (lines 22a/22b, the MO-CR "other" rows, the AGI worksheet 9-15 rows and the 41 Form 5766 fields), 13 new (MO-A line 19 totals, the MO-CR Schedule 1-2 rows, ...), the AGI worksheet rows re-keyed to the printed 9-11, 20 group ids over 79 checkbox lines each quoting the face. Face deltas: standard deductions $15,750 / $23,625 / $31,500, line 22 "Reserved", the Tax Chart's $1,313 steps and 4.7% top rate, MO-A Part 1's new lines 18-19, Part 3's $47,633 cap. STATE_COMPUTED_READONLY 221 → 227 with the delta; NONZERO_READONLY_DEFAULTS rows for line32Y / line32S / moa_pt4_4. 805/805 lines proven, all 32 pages read; two adversarial verifiers (PASS / PASS), a fixer (4 fixed: the MO-TC code-table census, `comb: true` on the 59 digit-cell widgets, the two "CHECK to fill" caption cells unmapped, the E10 extension-copy note). The eleven Hidden mapped widgets the pack lists now print under P-027. Knowledge mismatches for JS2c: the 2025 pack's claim that MO-TC / MO-PTS lines were renumbered from 2024 (both faces print 42 / 43), its MO-A Part 2 threshold wording, the MO-WFTC investment-income question the face prints. Follow-up: the MO-1040 2024 pack still maps the two "CHECK to fill Line 32Y/32S" caption cells (1040_32Text2/3) that 2025 unmapped.
    - **NC D-400 2025 — DONE 2026-10-01** (`formpacks/states/nc/2025/d400`, PORTABLE off NC 2024). NCDOR renamed the landing slug (web-fill → web-filled version); the 97 widgets keep every name, /Rect, /MaxLen, flag and on-state (the only content diff is the deceased-year picker's options rolling to 2023 / 2024). Face deltas: the years, "Web-Fill 9-25", line 15's rate 4.5% → 4.25% ("If zero or less, enter a zero"); no line renumbered — every printed add / subtract instruction re-read. cross_form `6 == f1040.11a`. 82/82 sentinels confirmed on both form pages; two adversarial verifiers (PASS / PASS, three low findings: the 55-not-56 /MaxLen count, the combo flags, the check-mark glyph wording — all fixed from the fixer's own measurements).
    - **MN Form M1 2025 — DONE 2026-10-01** (`formpacks/states/mn/2025/m1`, NEAR-PORT off MN 2023; the URL carries an upload-month folder, so the digest is the identity). 81 widgets, all mapped (2023: 74): line 14 became 14a / 14b (14a with four "check appropriate boxes" schedule boxes incl. the new Schedule NIIT, 14b the advance child tax credit repayment), the header gains County, the federal-return block gains boxes E / F (Social Security benefits), the signature block gains the NIIT-filing and MNsure boxes; relation `15 == 13 + 14a + 14b`, cross_form `1 == f1040.11a`; filing-status and account-type group ids. Face deltas: line 7 cites M1M line 40 / M1MB 22, line 16 M1C line 19, the party-code legend adds Independence-Alliance 18; the only dollar figure on the face is the $5 campaign-fund designation. 76/76 sentinels confirmed on both pages; two adversarial verifiers (PASS / PASS) and a fixer (five banner corrections from its own measurements). Knowledge note for JS2c: the 2025 M1 face says "line 11 of federal Form 1040" where the knowledge pack cites line 11a (the TY2025 Form 1040 prints AGI on 11a; the DOR's own caption lags).
- [ ] **JS6 — Nonresident / part-year state returns (old J4 = C2)** (XL, per pack) [PJ-16]
  - 9 discovery rows were recovered (wf_fe623a11-933).
  - Pack the AcroForm rows at TY2023 first, each re-checked against its recorded sha256: AL 40NR, AR1000NR, AZ 140NR, AZ 140PY, CO DR 0104PN, DE PIT-NON.
  - The three CT forms go through JS4 or hand-fill manifests.
  - **Acceptance, per pack:** as JS5, plus a part-year allocation golden.
- [ ] **JS7 — TY2026 state sprint** (XL, per pack; external: states' 2026 blanks, Dec 2026 – Feb 2027)
  - Re-triage from each state's NEWEST shipped base (`--base newest`), after the federal JT6.
  - **Acceptance, per pack:** as JS5; the re-triage table is committed.

**Not scheduled** (backlog; disclosed as not modeled):
- AMT / Form 6251.
- ISO, §83(b) and RSU vesting. JP1c's supplemental path covers RSU-vest withholding for TY2027 planning.
- Wash sales.
- The separated-spouse EITC rule (IRC 32(d)(2)(B)) on the nonresident-spouse head-of-household route (JF2.5(c)): it needs a last-6-months principal-abode fact — the one the lived-apart route also rests on — that the profile does not record. Disclosed in the head-of-household route note.
- Past-year (2019-2024) employee Medicare rate and 402(g) limit (JF3): the packs carry neither, so the Form 8959 box-6 credit is NOT ESTIMATED there and the box-1-for-box-5 note keys only on a priced Form 8959; add them with each year's Pub 15 / COLA-notice citation when a past-year return needs them.
- DEV_PLAN's I-94 / I-20 / IRS-transcript DocSpecs and perceptual-hash snapshots; JD1 records them as deviations.

**Acceptance (phase):**
- J0 leaves main clean and green.
- Every 2026-09-23 review defect is fixed with a regression test, pitfall-cited wherever the rule is durable.
- No form line number is typed outside `form_lines` (the JF6a guard).
- The recharacterization flow runs end to end: from a 1099-R, 5498 or custodian statement to the Form 8606 inputs, the 1040 lines and the attached statement.
- The TY2026 dress-rehearsal scenarios (t–t4) fill and verify on the finals within 5 business days of the last required final.
- Every open box elsewhere in this ROADMAP is closed or named in a tranche: A1–A6 → JA1/JA2; C2 → JS6; D2 → JS3a/b, JS5, JS7; Phase E ×2 → JEa/JEb; H5's Tax Table → JT2a/JT6.

## Phased sequencing (recommended order)

1. **Done:** Phase 0, E (except two boxes, now JEa/JEb), F, G, H (except H5's 2026 Tax Table, now JT2a/JT6), I, and persona-review Tiers 1+2.

2. **Phase J (re-planned 2026-09-23) is the whole forward plan.** Execution order:

   J0 → JF6a → JF1a → JF5a → JF5b → JF1b → JF2 → JF3 → JF4 → JP1a → JP2 → JR1 → JR2a → JT0a → JT0b → JT0c → JR2b → JR2c → JF6b → JF6c → JF7 → JR3a → JR3b → JR3c → JT3a → JT3b → JT3c → JT3d → JF8 → JF9 → JT1a → JT1b → JT1c → JT1d → JT1e → JT2a → JT2b → JT4a → JT4b → JT4c → JP1b → JP1c → JT5a … JT5f → JP5a → JP5b → JD1 → JA1 → JP3a → JP3b → JP4 → JR4a → JR4b → JP5c → JEa → JEb → JD2 → *(JT6 when its trigger fires)* → JS1a → JS1b → JS2 → JS2b → JS3a → JS3b → JS3c → JS4a … JS4d → JS5 → JS6 → JS7.

   **Hard dates** (latest start; a dated tranche takes the next free slot and never interrupts one in progress):

   | Tranche | Latest start |
   |---|---|
   | JT0a | 2026-10-12 |
   | JP1a | 2026-10-14 |
   | JP2 | 2026-10-19 |
   | JT3a | 2026-10-26 |
   | JT5a | 2026-11-16 |

   Why this order:
   * **J0 first.** The 2026-09-11 working tree blocks every commit. J0 also:
     - carries the regression fix that verify's ReadOnly scan needs;
     - ships the federal FBAR checkbox fix;
     - records that the DC 2025 booklet was re-issued.
   * **JF6a second.** A year-keyed form-line registry and guard, so no later tranche types a line number. Schedule 1 "line 8z" is already wrong for 2019/2020, which print "line 8".
   * **JF1a → JF5a → JF5b → JF1b → JF2 → JF3 → JF4: filing-wrong defects first, then silent ones.**
     - Filing-wrong: the resident treaty line (JF1a), and the §6013 election that keeps nonresident rules (JF5a).
     - Silent: the missing prior-year residency fact, and Box 1 standing in for boxes 3/5/6.
     - Wrong-law routing, and the safe harbor ignoring §31 credits.
   * **JP1a/JP2 early and dated.** Per-employer FICA, the W-4 Step 4(c) solve and 402(g) room are only worth anything before the year's last paychecks.
   * **JR1 → JR2a/b/c → JR3a/b/c: the retirement block.** The recharacterization tool, 1099-R code interpretation and the statement.
     - JR1/JR2a run early: a recharacterization must be completed by the return's due date (including extensions), so the NIA op is most useful well before then.
     - The estimator wiring (JR3) matters once the January 2027 forms arrive.
   * **JT0 → JT3 → JF8/JF9 → JT1/JT2 → JT4 → JT5: TY2026, drafts-first.** The IRS 2026 drafts are already posted, so authoring starts now instead of in Dec–Jan. JF6b/JF6c and JF7 finish the line-number cleanup and the Schedule 1-A estimator input before any 2026 pack or block depends on them.
   * **JP1b/c, JP5a/b, JP3, JP4: the remaining decision ops.** The full Pub 15-T projection, the Form 2210 penalty (regular and annualized), paystub → W-2, and claim of right.
   * **JD1/JA1: docs truth-up and the agent half of Phase A.** JA1 takes the next slot the day the user is ready to publish.
   * **JR4, JP5c, JEa/b, JD2: packs and debt.** Form 5329 and Form 2210 packs (including their 2026 drafts), pack-gate debt, and process.
   * **JS1a–JS7: state work, after the federal lanes** (the standing "federal before state" rule). TY2024/2025 state returns are past their original due dates, and the TY2026 state sprint re-triages from the newest base anyway.

3. **Phase A = JA1 (agent) + JA2 (user).** A parallel lane gated only by the user:
   * PyPI credentials or a trusted publisher;
   * the tag push;
   * the mcp<2 decision;
   * the demo GIF;
   * an acceptance tester.

   JA1 must land before any upload, because two PyPI-immutable descriptions carry wrong counts today.

4. **Phases C/D remainders now live in JS3a–JS7:**
   * C2 → JS6;
   * D2's re-map and URL-dead rows → JS3b and JS5;
   * the 2024 leftovers → JS7.

**Tranche size.** Every tranche is at most about a day of work (M). Multi-pack tranches commit per pack. So a spend-limit death costs at most one sub-tranche.

**Parallelism.** The default is one tranche at a time, because the spend limit kills wide fleets. When budget allows, these touch disjoint files and may run alongside the JF/JR tranches:
* JT0a–c;
* JA1;
* JEa/b.

JT6 pre-empts everything when `check_finals` reports the finals. By the 2025 precedent that is late Dec 2026 – Feb 2027 (an inference).

**No remaining item needs a new heavyweight dependency:**
* the overlay filler exists (branch `phase-j2-overlay` → JS4a–d);
* MA's fetch block has a recorded, digest-verified mirror (JS1b, done 2026-09-28);
* TY2026 authoring runs on drafts-first packs (JT0a).

**The external gates are:**
* **the user:** JA2; the branch-protection decision (JD2.3); remote branch deletes (JD2.4); the labeled interpretive choices in JR2b and JP1c; the JT6 flip policy; any DC exception before 2026-10-15;
* **the IRS:**
  - the 2026 finals and the 2027 inflation Rev. Proc. (JT6);
  - the Schedule 3-A and Schedule A 2026 instructions (JT1c, JT2a);
  - the Schedule NEC/OI drafts (JT5g);
  - the §6621 rate for Q1 2027 (JP5a);
* **the states:** their 2026 blanks (JS7).
