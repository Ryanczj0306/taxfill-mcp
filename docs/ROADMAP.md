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
> main (snapshot: branch `wip/phase-j-partial`); and six read-only reviews of the
> engine, the decision surface and TY2026 readiness found the federal
> defects Phase J now orders first. Phase J also adds a recharacterization tool, 1099-R
> tool, 1099-R code interpretation and the explanation statement. The federal TY2026
> set is authored drafts-first from the posted IRS 2026 drafts (JT0–JT5), ahead of the
> finals flip (JT6).
>
> **Known stale source:** the DC 2025 D-40 booklet cited by
> `knowledge/states/dc/2025.yaml` has returned 404 since 2026-08-24; DC OTR re-issued it
> as `2025_D40_Book_082026_v1.pdf`. DC 2025 figures are not re-verified until Phase J
> JS1a.

## Where we are (verified)

Done and on `main` (**5,349 tests** — offline 4,969 + live-.gov 380; derived
by `scripts/sync_test_count.py --write` at every Phase J commit). The offline layer is green in CI and locally
(Python 3.11, matching CI, since J0). The weekly network layer has been **RED since
2026-08-17** — 6 of 6 freshness runs failed through run 35621846216 (2026-09-21) — on
two sources: the MA Form 1 blank returns 403 and the DC 2025 booklet returns 404 (DC
OTR re-issued it). Phase J JT0c quarantines both behind an expiring allowlist so new
reds surface; JS1a/JS1b fix them:

- **M0 scaffold · M1 engine · M2 federal packs · M3 intake + knowledge · M4 MCP
  server (23 tools, stdio, image content) · M5 state support · M6 code/docs.**
- **MCP server — 23 tools, CI-gated** (`.github/workflows/ci.yml` asserts exactly
  23): list_forms, get_form_map, fetch_blank, fill_form, verify_form,
  verify_filing, render_form (vision Image), calc, residency, intake_checklist,
  list_document_kinds, extract_document, workspace_save, workspace_load,
  workspace_record_position, workspace_reconcile, state_scope, estimate_refund,
  compare_scenarios,
  get_sources, filing_summary, file_and_pay, hand_fill_worksheet (print-only
  states). The `calc` tool carries **32** deterministic ops (`packages/mcp-server/tests/test_skills_sync.py` pins the count; Phase J adds 8 → 40 without adding an MCP tool): the 25 of Phase H (tax, tax_with_preferential_rates, standard_deduction, se_tax, additional_medicare_tax, niit, taxable_social_security, excess_ss, student_loan_interest_deduction, education_credits, ptc_annual, ptc_monthly, child_tax_credit, eitc, dependent_care_credit, treaty_benefit, schedule_1a_deductions, employee_fica, estimated_tax_safe_harbor, annualize_ytd, contribution_limits, ira_contribution_eligibility, marginal_dollar_savings, magi_ladder, state_tax) plus Phase I's ira_pro_rata, roth_conversion, hsa_deduction, espp_disposition, capital_loss_limitation, foreign_tax_credit_election and foreign_asset_reporting.
- **Phase B — single-user completeness: DONE.** `extract_document` (W-2,
  1099-NEC/MISC/INT/DIV/G/B/R, SSA-1099, 1095-A, 1098-T/E, 1042-S, and — since
  2026-08-10 — **Schedule K-1 (Form 1065)**, with per-field provenance — and, since Phases I2/I3/I5, 1099-SA, 5498-SA, 3921, 3922, 1099-K, 1099-Q, W-2G, 1095-B, 1095-C, 5498, K-1 (1120-S) and K-1 (1041): **26 kinds** per `list_document_kinds()`) and the resumable
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
8959, 8960, 8962, 2441, 843 (Rev. 12-2024), 8316, 8606, 8889, 8949, 8833, 1116, 8938 (2023–2025), Schedule 1-A (2025), and FinCEN 114 as a hand-fill worksheet. state — **all 42 income-tax
jurisdictions**: **38 via fillable AcroForm (61 packs across TY2023–TY2025)** — CA (540 + 540NR +
Schedule CA 540/540NR), NY (IT-201 + IT-203), IL, PA, OH, GA, NC, MI, NJ, VA, AZ,
IN, MO, MD, AL, CO, MN, WI, KY (740), OR (OR-40), LA (IT-540), KS (K-40),
AR (AR1000F), ID (40), NE (1040N), OK (511), ME (1040ME), MS (80-105),
RI (RI-1040), MT (Form 2), ND (ND-1), DE (PIT-RES), VT (IN-111), DC (D-40),
WV (IT-140), IA (IA 1040), MA (Form 1), UT (TC-40) — plus **4 via print/hand-fill
manifests**: CT (CT-1040), HI (N-11), NM (PIT-1), SC (SC1040).
**179 form packs total** — 172 `pack.yaml` (111 federal + 61 state) + 7
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
before it ships; tests green. Since 2026-08-04 the real gate has been trunk-based: full
offline suite plus CI green, with an adversarial second-agent verify recorded in the
commit body. Whether to restore feature branches under branch protection is a user
decision (Phase J JD2.3).

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
        0 near-port + 11 RE-MAP + **19 URL-DEAD** + 7 no-year-token. **Correction
        2026-09-23:** UT 2025 TC-40 is PORTABLE against UT's newest shipped base (2024)
        and was never shipped → JS3b; the 2026-09-11 re-triage counts 73 open pack-years
        → JS3a/JS3b/JS5.
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

- [ ] **A THIRD checkbox-topology blind spot, MEASURED 2026-08-26 (Phase I2).** → Phase J **JEb**.
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
      (found 2026-08-26).** → Phase J **JEa**. `sched_b` / `sched_c` / `sched_8812` / `f2555` / `f8889`
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

> From the planning-surface gap catalogue (N-1 to N-15), logged in
> [`FIELD_NOTES.md`](FIELD_NOTES.md): multi-period visa timelines (hypothetical
> illustrations), multi-taxpayer households and **planning-year budgets**. Unlike Phase G,
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
      shape on hypothetical fixtures (a mid-year status change; an unmarried household).
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
        line, so a demo "marry + election: +$1,963" decomposes into "MFJ brackets
        +$5,309; spouse income −$3,192; spouse's interest −$154" the way the
        hand analysis would build the table. Order-dependence of the
        to build. Order-dependence of the walk is inherent and disclosed,
      * The election scenario auto-discloses the two traps a hand analysis has to
        to derive: worldwide income becomes taxable (the scenario is only as
        complete as the income given), and the election does NOT start FICA
        (N-7b, stated unprompted).
      * **Persisted and re-runnable** (N-15's actual interaction): scenario
        sets store INPUTS-only in the year's workspace (`scenarios.json` —
        results recompute on every load, so pack corrections are picked up
        silently); `load="name"` + `income_updates` makes "a corrected W-2 arrived,
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
        what-if excess (demo MAGI $191,200, $7,000 contributed) is now a machine verdict (allowed $0, excise
        $420/yr) with the year-end MFJ flip shown mechanically.
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
      (Pub 525 rebate-vs-income) — DONE 2026-08-10.** Gap: nothing answered whether
      an account bonus or a card/bank reward (for example an
      annual-fee reimbursement) is taxable. The engine could price
      characterization was known and could resolve the residency branch, but
      residency branch — but the characterization itself had to come from the
      the failure the freshness protocol exists to prevent. Shipped (every
      cited page fetched and content-verified before authoring):
      (text revised)
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
      neighbouring topic is stolen, and an agent asked "is an account-opening bonus taxable"
      bonus taxable" reaches Pub 525 + Pub 519 ch. 4 through `get_sources`.

**Acceptance:** H1/H2 ship schema + intake changes with regression tests and an
eval scenario for a hypothetical *mid-year status change and unmarried household*
household with a nonresident partner*); H3 ships the segment loop + the worksheet surface with a no-experience
walkthrough in the skill; H4 ships golden-tested ops and a PROJECTION output
contract that can never be mistaken for a filed number; H5 follows the two-pass
verification rule for every figure; H6 ships golden-tested phase-out math for all
five Schedule 1-A parts including the MFS-forfeiture rules; H7 ships a diff whose
line items sum to the headline delta.

---

## Phase I — Retirement-account, HSA, equity-comp and treaty-disclosure decision surfaces (Effort: L)

> Found by the **Phase I planning audit**: the repo was driven end to end to
> compute a TY2026 projection for a hypothetical demo filer (W-2 $216k = $150k base +
> $50k RSUs + $16k bonus, 401(k) $23k, HSA $3.6k, a backdoor Roth, a what-if direct-Roth-IRA
> contribution needing recharacterization, an $18k old-plan balance being converted,
> ESPP, a $2,000 treaty student-wage exemption (a separate demo fixture), $2.6k
> investment income against an $800 capital loss). **Every figure the knowledge packs
> knowledge packs (`rate_schedules`, `standard_deduction`, `niit`, `contribution_limits`,
(text revised)
> `capital_gains_brackets`; Rev. Proc. 2025-32 / Notice 2025-67 / Rev. Proc. 2025-19); what
> decisions the walkthrough turned on had to be computed OUTSIDE the engine.**
> was missing is the *decision surface*, the same failure signature `FIELD_NOTES.md`
> gap catalogue, one profile over: the data is there, the *decision surface* is not.

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
      rolled**. Illustrative (demo numbers): rolling an $18,000 pretax 401(k) into a
      traditional IRA costs **$1,210 in year 1 and $4,158 over ten years** versus
      the new employer's 401(k), and the failure mode is invisible —
      no error, no warning, just a larger tax bill and a Form 8606 basis the filer
      must track for life. Build: **`calc.ira_pro_rata`** (per-account year-end
      balances + cumulative nondeductible basis + conversion amount → taxable
      amount, basis consumed, basis carried forward); **`calc.roth_conversion`**
      covering BOTH paths, which behave differently and are routinely conflated —
      (a) plan → Roth IRA *direct* rollover (Notice 2008-30: taxable = the pretax
      portion, and **pro-rata does not apply** because no IRA is involved), and
      (b) traditional IRA → Roth (pro-rata applies) — each surfacing bracket
      headroom and the NIIT threshold crossing (a demo $18,000 direct conversion
      moves MAGI 191,200 → 209,200, crossing the $200,000 §1411 threshold and
      creating $68 of NIIT the filer has no way to anticipate, plus it lands
      $8,675 short of the 32% bracket — a margin no user can be expected to
      22% bracket into 24% — a split no user can be expected to compute by hand); a fillable **`f8606`** pack for 2023/2024/2025 (Parts I/II/III
      — this is the form that carries basis across years, so without it the calc has
      nowhere to land); and pitfall **`P-009`** stating the trap with the measured
      numbers. **Acceptance:** 8606 vision-audited three years; the op reproduces the
      demo worked example to the dollar; P-009 cited; the i14 scenario
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
      general-purpose-health-FSA mutual exclusion (a correction worth
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
- [x] **I4 — Visa-status filers — DONE 2026-08-27.** Shipped: **`f8833`** x3, which
      closes the standing asymmetry — `calc.treaty_benefit` has computed treaty
      exemptions since Phase G1 while the IRC 6114 / Reg 301.6114-1 disclosure the
      position REQUIRES did not exist, so the engine advised a position it could not
      help a filer disclose (and §6712 penalises the omission); the op's work string
      now names the form, the requirement, the waivers and the penalty on every
      branch, with no computed number touched. **`f1116`** x3 plus
      `calc.foreign_tax_credit_election` for the §904(j) branch that decides whether
      the form is needed at all. **`f8938`** x3 plus `calc.foreign_asset_reporting`
      and **FinCEN Form 114 as a hand-fill worksheet** (the FBAR is e-filed to FinCEN,
      not attached to the return — so a fillable pack would be the wrong shape), with
      every threshold read off Treas. Reg. §1.6038D-2 and 31 CFR 1010.350 and
      independently re-verified at integration: all four §1.6038D-2 buckets, MFS and
      HoH taking the unmarried thresholds, and the FBAR boundary EXCEEDING $10,000
      rather than reaching it. The op refuses to decide until its elicitation
      questions are answered (`any_duty_undecided` + `must_ask`), because a filer
      never raises a foreign account unprompted. Pitfalls P-011 and P-012.
      One correction worth its shape: the §904(j) op subtracted the Form 1116 line-12
      reduction before the $300/$600 test and called that "the order the Instructions
      set" — the quoted sentence sits under "If you make this election, the following
      rules apply", among the CONSEQUENCES of electing, and sets no order. The
      behaviour stands on 904(j)(2)'s word "creditable", but it is taxpayer-favourable,
      so the claim is withdrawn and the op now reports BOTH bases and says when they
      disagree. *(original scope below)*
- [x] **I4 scope as planned — visa-status filers: the largest penalty exposure in the repo.**
      Three holes, in descending stakes. (a) **`f8833`** closes a standing
      asymmetry: `calc.treaty_benefit` has shipped since G1 and computes the
      exemption, but the disclosure form IRC 6114 / Treas. Reg. §301.6114-1 requires
      **does not exist** — the engine tells a user to take a treaty position it
      cannot help them disclose (for example, when a treaty student
      exemption is claimed). (b) **Form 8938** pack + an **FBAR
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
- [x] **I5 — Document extraction breadth — DONE 2026-08-27.** Shipped all eight
      remaining DocSpecs — **1099-K**, **1099-Q**, **W-2G**, **1095-B**, **1095-C**,
      **5498**, **K-1 (1120-S)** and **K-1 (1041)** — taking `extract_document` from
      **18 kinds to 26** (the "14" below was written before I2/I3 added 1099-SA,
      5498-SA, 3921 and 3922). Every box layout was transcribed from the official PDF
      on irs.gov with the form's own recipient/filer instructions open beside it, and
      an audit re-derives every word of every label from the form text (0 unsourced
      words across ~780 boxes). Nothing reached the MCP surface by hand: DocSpecs
      travel through the generic `list_document_kinds` / `extract_document`, verified
      by round-tripping a W-2G through the real server, so **no `server.py` or skills
      edit was needed** and no count gate moved.
      **What the forms turned out to disagree about — the reason this was not
      mechanical.** *1099-K:* boxes **6 and 8 SWAPPED** between Rev. 3-2024 (which
      every TY2023-25 filer holds) and Rev. 12-2026; the spec carries the current
      numbering and the box TYPES (`money` on 6, `state` on 8) make a wrong-revision
      reading fail loudly instead of silently filing withholding as a state code.
      Boxes **1c/1d are new for CY2026** (P.L. 119-21 §70201, cash tips + Treasury
      Tipped Occupation Code), and TTOC **000 disqualifies** box 1c from the Schedule
      1-A tips deduction — so box 1d is a `code`, because `int` would turn 000 into 0
      and read the disqualifier as an empty box. The threshold is quoted from the
      instructions' own revision ($20,000 **and** 200 transactions, TPSOs only) and
      framed as a REPORTING rule: under it no form arrives, IRC 6050W still displaces
      §§6041/6041A, and the income is reportable anyway. *W-2G:* the loss deduction
      is now **90%**, not 100% — IRC 165(d)(1) as rewritten by **P.L. 119-21 §70114(a)**,
      effective "taxable years beginning after December 31, 2025" (§70114(b)), read in
      the Code itself — so the percentage is keyed to the TAX YEAR, not to the form;
      and the reporting threshold became **inflation-indexed** ($2,000 for CY2026).
      *1099-Q:* box 7 is dual-use (year-end FMV **or** an abbreviated distribution
      code), so it is `text`; and a Coverdell's boxes 2/3 are **correctly blank**
      ("Do not enter zero"), so neither may be `required`. *5498:* box 1/box 10 run
      FOR-the-year through April 15 while boxes 8/9 run by DEPOSIT date — opposite
      conventions on one form; box 5 is the `ira_pro_rata` denominator but is the
      date-of-death value on a decedent's form. *1095-C:* Part II's code series are
      the payload (only **2C** on line 16 touches the filer's PTC), line 15 is the
      lowest-cost self-only figure whose **0.00 is a real value**, and the
      affordability percentage is indexed (8.39% for 2024, 9.02% for 2025) so it is
      never hardcoded.
      **Naming decision (K-1 family), and its blast radius.** The bare kind **`K-1`
      stays the Form 1065 layout, untouched** — its only callers pass that exact
      string — and the siblings are keyed **`K-1 (1120-S)`** and **`K-1 (1041)`**.
      Renaming for symmetry was rejected because it would break those callers; the
      asymmetry is deliberate and pinned by a test. This is not cosmetic: the SAME
      BOX NUMBER means different things across the three forms — box 14 is
      self-employment earnings (1065), the Schedule K-3 flag (1120-S) and "Other
      information" (1041); box 16 is the K-3 flag (1065) but shareholder-basis items
      (1120-S). An S-corp K-1 read against the 1065 layout converts a K-3 checkbox
      into SE earnings, which is why the 1120-S note says outright not to run
      `se_tax` on box 1 ("Your share of S corporation income isn't self-employment
      income"). Blast radius of the addition: **zero deletions** in either file —
      purely additive, 3 pre-existing `K-1` tests untouched and still green.
      *(original scope below)*
- [x] **I5 scope as planned — document extraction breadth.** 14 DocSpecs ship; the
      cheap, mechanical gaps are **1099-K** (gig/resale, and its moving reporting
      threshold), **1099-Q**, **W-2G**, **1095-B/C**, **5498**, and **K-1 for 1120S
      and 1041** (only the 1065 layout ships, so an S-corp or trust K-1 has no
      structured path). The 3921/3922 and 1099-SA/5498-SA specs belong to I3 and I2
      respectively — do them there, and batch the remainder. **Acceptance:** every
      box layout read off the official form, round-trip tested.
- [x] **I6 — the six Phase I decisions, encoded — DONE 2026-08-27.** It lands as eval
      scenario **`s`**, not "i14": this plan invented that label, but
      `evals/test_scenarios.py` numbers scenarios by LETTER and the `i` prefix
      already belongs to the provisional-guard family (i, i2-i5). Scenario `s`
      re-runs the SIX Phase I decisions that had been computed outside the
      engine, against the ops I1-I4 shipped, and pins the numbers the engine
      produces: the 401(k) rollover destination under IRC 408(d)(2) (a polluted
      makes 72% of the backdoor taxable and sticks $5,040 of basis; a clean one is
      fully non-taxable), the $18,000 direct plan-to-Roth conversion with its bracket
      headroom 26,675 -> 8,675 and the section 1411 crossing that costs $68, the
      Medicare-only tier, the ESPP basis correction
      (corrected basis minus broker basis equals the ordinary income exactly — that
      difference IS the double taxation) plus the qualifying-sale-at-a-loss cell that
      recognises zero ordinary income, the $3,000 cap with a character-preserving
      carryover, and the treaty $2,000 whose disclosure the engine can finally name.
      $2,000). It also pins the two guards the reviews added: `roth_conversion` REFUSING the
      input whose income it does not price, and `foreign_asset_reporting` refusing to
      decide until its elicitation questions are answered. The file's own scenario
      census ("sixteen scenarios (a–p)") was stale by three and is corrected.
      *(original scope below)*
- [x] **I6 scope as planned — an eval for the six Phase I decisions.** Encode the
      six decisions as a scenario — they are what exposed I1–I5, and the repo's own
      precedent (FIELD_NOTES → Phase H) is that an end-to-end drive is the best gap-finder
      decisions as an eval scenario so these gaps cannot silently reopen.
      **Acceptance:** i14 runs green and fails loudly if any of I1–I4 regresses.

**Sequencing within Phase I:** I1 → I2 (I1 has the higher consequence
and no dependencies) → I3 (its `f8949` is a prerequisite for a *complete* Schedule D
filing path, so it arguably outranks I2 — decide on whether the user base sells
stock) → I5 leftovers → I4 (highest stakes but the most research) → I6 last, since it
asserts everything above. **Deps:** none external. Phase A is orthogonal and should
not wait for any of this.

---

## Phase J — Finish everything (ordered 2026-09-11; RE-PLANNED 2026-09-23)

> **Origin.** On 2026-09-11 the user ordered all remaining development finished. That session hit the monthly spend limit on 2026-09-12 and committed nothing. It left 15 unverified files on `main` (13 modified, 2 untracked, +824/−62) and two failing tests.
>
> **Privacy.** Each tranche below states only the mechanism it fixes; worked figures are hypothetical-persona demo numbers (the FIELD_NOTES privacy rule). Besides every bug found, the plan adds **a recharacterization tool, Form 1099-R code interpretation and the explanation statement**.
>
> Six read-only reviews re-checked every claim on a clean checkout of `a233031` and against primary .gov text. The lenses were engine defects, the recharacterization design, the decision surface, the Phase J salvage, TY2026 readiness, and docs/release/process. A critic pass then re-verified the plan itself. Bracketed ids such as `[DEF-01]` are the 2026-09-23 review's gap ids, and each item carries its evidence pointer inline. Figures in acceptance tests are *illustrative* (demo numbers).

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
   - **Pitfall ids** are assigned at commit time in tranche order. P-013 is N-8, and P-013 also takes LD-15's 871(k) corner. P-014 is the handfill "no" checkbox (J0 commit C) and P-015 is form-line-drift (JF6a). Tentative new ids: P-016 treaty-destination (JF1a), P-017 flat-rate-precondition (JF1a), P-018 residency-facts (JF5a/b), P-019 box1-standin (JF3), P-020 withholding-vs-liability (JP1a), P-021 recharacterization (JR2b), P-022 charitable-characterization (JF9), P-023 public-benefit-qualified-alien (JT1c), P-024 education-ssn-deadline (JT1e), P-025 claim-of-right (JP4).

**Old → new map.**

| 2026-09-11 item | Where it went |
|---|---|
| J1(a) verify scans mapped ReadOnly widgets | J0 commit A, **with** the regression fix it needs (J0.3) |
| J1(b) N-8 §871(i)(2)(A) deposit-interest exclusion | J0 commit B plus its missing tests; the dual-status corner goes to JF5b.3 |
| J2 overlay filler (CT/HI/NM/SC) | parked on branch `phase-j2-overlay` at J0; ships as JS4a–d |
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

- [ ] **JF1a — Wrong words on the resident, retirement and payroll paths** (S–M; deps JF6a) — pitfalls *treaty-destination*, *flat-rate-precondition*
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

- [ ] **JF5a — FILING-WRONG: the §6013 election keeps nonresident rules** (M; deps J0) [PJ-04] — pitfall *residency-facts*
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

- [ ] **JF5b — Prior-year residency fact; price the dual-status risk** (M; deps JF5a)
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
  - **Acceptance.**
    - Truncated F-1 history + prior 1040 → not definitive; CONTRADICTION reason first.
    - Full history + prior 1040 → resident, no dual-status flag, standard deduction applied, `_fica_exemption_note` suppressed.
    - H-1B arrival 2026-03-01 (306 days) → the low end has deduction 0, the high end the standard deduction, and the assumption names the range.
    - Dual-status + `bank_deposit_interest > 0` → a disclosure naming the amount.
    - Citing tests for the residency-facts pitfall.

- [ ] **JF1b — Small logic fixes** (S–M; deps J0)
  1. **QSS threshold** [DEF-11]. magi_ladder applies the MFJ-aliased $250,000 Form 8959 threshold to QSS (calc.py:4175-4182 via `_resolve_filing_status`); Form 8959 line 5 and knowledge/federal/2025.yaml:168 say $200,000. Use `_surtax_threshold` with the raw status, and move the NIIT row onto the same helper.
  2. **§6013 caveat gate** [DEF-16]. The §6013(g)/(h) caveat fires for unmarried single visa holders (estimate.py:2288-2302). Gate it on `_is_married`, and suppress it once JF5b's prior-year fact plus the SPT settle residency.
  3. **Document checklist wording** [DEF-19]. `_required_documents` frames every us_person=False filer as "a nonresident return", computed residents included (intake.py:1187-1204). Gate it on the residency classification and thread `tax_year` through.
  4. **Excess-contribution excise** [RC-11]. The excise ignores the IRC 4973(a) cap: it "shall not exceed 6 percent of the value of the account … (determined as of the close of the taxable year)" (Form 5329 line 25; calc.py:3855, :3884). The remedy text (calc.py:3901-3905) names no date. Add `roth_ira_dec31_value`, and name the deadlines: April 15 of year+1, or Oct 15 with an extension or via §301.9100-2 for a timely-filed return. JR2c adds the op pointer.
  5. **Spouse-field coverage** [LD-10]. combined_with_spouse lists its 18 summed fields by hand (estimate.py:239-247) with no structural test, and N-8 already had to add one by hand. Add a test over `IncomeSnapshot.model_fields`, with the household-level exclusions explicit, that fails naming any missing field.
  6. **Scenario walk vs subset validators** (J0 re-verify). compare_scenarios' one-override-at-a-time input walk raises a ValidationError at an intermediate step when a parent drops below its subset (`interest` before `bank_deposit_interest`, `dividends` before `qualified_dividends`). Apply subset/parent pairs together in the walk, and test both orders.
  - **Acceptance.**
    - `magi_ladder(240000, QSS, 2025, wages=240000)` → the 8959 row shows $200,000, 'above'.
    - An unmarried single visa holder → no "6013" in assumptions or `what_would_change_it`; married with no residency facts → still present.
    - A resident F-1 profile → no "nonresident return" text.
    - A Dec-31 value below the excess → excise = 6% × value.
    - The spouse-field test fails when a field is dropped from the list.

- [ ] **JF2 — Wrong-law routing and document notes** (M; deps J0)
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
  - **Acceptance.**
    - Each query above routes to its own topic.
    - Bidirectional neighbour-theft tests re-run the canonical queries of self_employment, foreign_tax_credit, FBAR, ira_basis_and_roth_conversions, deadlines, estimated_tax, contribution_limits, NIIT and HSA (e.g. "1099-DIV box 7" → foreign_tax_credit; "Form 8606" → ira_basis_and_roth_conversions).
    - A 2026 1099-R read with 7a/7b resolves with no gap; box 5 is a known box.
    - A 1099-DIV extraction carries the new note.

- [ ] **JF3 — W-2 boxes 3/5/6 reach the estimator** (M; deps JF6a, JF1b) — pitfall *box1-standin*
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

- [ ] **JF4 — FICA tiers and the safe harbor read the right box** (M; deps JF3)
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

- [ ] **JP1a — employee_fica two layers, and the Step 4(c) solve** (M; deps JF1a, JF3, JF4; **latest start 2026-10-14**) [DEF-09 + the rest of LD-12 + LD-14's 4(c)] — pitfall *withholding-vs-liability*
  - **Why.**
    - employee_fica pools ONE Social Security base and ONE Medicare accumulator across all segments, labels the person-level LIABILITY split as per-segment "withholding" (calc.py:3221-3225, :3293-3345), and rounds wages to whole dollars (:3317).
    - Withholding is per employer: each employer withholds Social Security up to the base, and the 0.9% applies only to "wages from the employer in excess of $200,000" (IRC 3102(f)(1); Pub 15 (2026) §9; knowledge/federal/2026.yaml:271-276).
    - Liability is per person, against the Form 8959 status threshold. The difference between the two is the hidden excess-SS credit.
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
- [ ] **JP2 — Multi-employer 402(g) room** (M; deps J0; **latest start 2026-10-19**) [LD-05]
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

- [ ] **JR1 — Form 1099-R box 7 interpretation** (M; deps JF2)
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
- [ ] **JR2a — Net income attributable, the statements module, the deadline fallback** (M; deps JR1, JF6a)
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
- [ ] **JR2b — The recharacterization op** (M–L; deps JR2a) [RC-02 + TY26-27 + LD-18 + RC-12] — pitfall *recharacterization*
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
- [ ] **JR2c — Custodian statements, the filing manifest, rule reach** (M; deps JR2b) [RC-09 manifest half + RC-16 + TY26-27]
  - **Custodian-statement DocSpec.** Form 5498 is due to the IRS "by May 31, 2027", after April 15. The Dec-31 FMV statement goes to participants "by February 1, 2027" (i1099r 2026). So a new `IRA custodian statement` DocSpec covers:
    - trade / transfer confirmations (date, amount, type, from/to account);
    - the year-end FMV statement, which feeds `dec31_total_value` for ira_pro_rata / roth_conversion with document provenance.
    
    The op notes the 5498 timing prominently.
  - **Manifest.** `FilingManifestItem.attached_statements`, so the filing checklist says what to attach.
  - **Rule reach.**
    - Pointers at the use sites: JF1b.4's EXCESS line, the intake Roth IRA note (intake.py:1142-1150), the roth_conversion docstring, and the 5498 and 1099-R notes.
    - Skills docs and op list updated.
    - A separate synthetic what-if eval covers "recharacterize before converting".
  - **Acceptance.**
    - A confirmation round trip, and an FMV statement feeding `dec31_total_value` with provenance.
    - The manifest lists "recharacterization statement".
    - test_skills_sync matches the runtime op list.
- [ ] **JR3a — Retirement distributions in the estimator** (M; deps JR1, JR2b) [RC-07, part 1]
  - Today IncomeSnapshot has one hand-fed integer (estimate.py:87-192, :228).
  - Add `retirement_distributions: list[RetirementDistribution]`: gross, 2a, the 2b flags, codes, IRA box, disposition, override, early_exception_amount, and withheld (informational).
  - Route each item through `distribution_codes.interpret`.
  - `retirement_income_taxable` stays as a manual override, refused when the list is also set.
  - **Acceptance:** Q → 0; G/H rollover → 0; J+P → excluded with an assumption; both inputs set → ValueError; the spouse-field test covers the new list.
- [ ] **JR3b — Per-person IRA pool and pro-rata** (M; deps JR3a) [RC-07, part 2]
  - Add `ira_pool: IraPoolFacts` per person.
  - Traditional-IRA items with 2b checked go through ira_pro_rata. `ira_pool` is then REQUIRED, with a prescriptive refusal; `{basis_carryforward: 0}` is the explicit no-basis answer.
  - Spouses' pools never merge (Form 8606 is filed per spouse).
  - **Acceptance** (*illustrative*): a code-N recharacterization plus a code-2 conversion, with the pool carrying the line-1 basis → taxable = NIA + growth, not the box-2a gross. An MFJ couple's pools stay separate.
- [ ] **JR3c — The 72(t) and 4973 taxes** (M; deps JR3a, JF6b) [RC-08]
  - The estimator has no 72(t) additional tax and no 4973 excise (grep: 0 hits; `_LEDGER_SLOTS` estimate.py:307-343).
    - IRC 72(t)(1) is "10 percent of the portion … includible in gross income"; (t)(6) makes it 25% in a SIMPLE IRA's first two years.
    - 4973(a) is 6%, capped at the account value.
  - New slots `early_distribution_additional_tax` and `ira_excess_contribution_excise`, labeled from `form_line`: Schedule 2 line 8 for 2025; lines 5 and 18 on the 2026 draft Schedule 2 and the 2026 draft Form 5329 (Created 7/31/26).
  - **Acceptance** (*illustrative*):
    - Code 1, $12,000, no basis, under 59½ → a $1,200 slot.
    - J+8 → earnings taxable, 0 additional tax.
    - The excise is capped at the Dec-31 value; the ledger reconciles.

### Block 4 — The TY2026 foundation (dated)

- [ ] **JT0a — Draft packs, rehearsal mode, multiple second passes** (M; deps J0; **latest start 2026-10-12**) [TY26-01 + TY26-03 + G32 + LD-08(3)]
  - **Why.** Every 2026 draft for the Wave A forms is posted at irs.gov/pub/irs-dft/. The IRS cover sheet says "there are never any changes to the last posted draft of the form and the final revision of the form"; drafts of instructions and publications do change. Three gates refuse drafts-first authoring today:
    - the URL-prefix test (test_formpacks_federal.py:208-217);
    - `assert_filing_grade` inside the golden test (filler.py:360; verify.py:2324/2427);
    - the sha256 pin, which breaks when IRS re-posts a draft (f1040--dft: Last-Modified 2026-09-17, Created 8/19/26).
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
- [ ] **JT0b — Planning-year fixtures** (M; deps JT0a) [TY26-02]
  - A `planning_year` conftest fixture returns the newest provisional federal year and skips when there is none.
  - A `synthetic_provisional_pack` fixture makes a tmp copy with named blocks stripped.
  - Rewrite the absent-block assertions to test behaviour, not today's contents of 2026.yaml: evals/test_scenarios.py:237, :261, :273-281, :307, :340-360; test_estimate_ledger.py:176-189; test_schedule_1a.py:174-176; test_compare_scenarios.py:84-89; test_projection_ops.py:197.
  - **Acceptance:** the suite is green, and it stays green when a 2026 block is added to a scratch copy.
- [ ] **JT0c — Finals watch, red-quarantine, the 1040-ES voucher, the 2026 header** (M; deps JT0a) [TY26-04 + G22(3) + TY26-22 + TY26-30]
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
- [ ] **JT3a–d — Wave A: the core W-2 / retirement / HSA 2026 federal packs, drafts-first** (JT3a **latest start 2026-10-26**; deps JT0a–c, JF6c) [TY26-20]
  - **Sub-tranches.** The count in parentheses is how many 2025-pack field names are missing from the draft.
    - **JT3a** (M–L): f1040 (43 of 192), sched_1a (44/54; 225 fields).
    - **JT3b** (M): sched_2 (19/63), f8959 (0/26, but its Parts are reordered), f8889 (0 missing).
    - **JT3c** (M): f8606 (18/45), sched_1 (1/73), sched_3 (2/36).
    - **JT3d** (M):
      - sched_b, sched_d and f8949 (0 missing each);
      - f8833: the current final is byte-identical to the 2025 pin → copy, source_status final;
      - **f1040es**: FINAL, but all 56 mapped names changed; uses `own_final_revision`.
  - **Traps.** Key every field by its PRINTED line:
    - 1040 13a and 13b swap meaning. 2025: 13a = QBI, 13b = Schedule 1-A. 2026: 13a = Schedule 1-A line 44, 13b = QBI.
    - The 1040 gains 12f, 24a–c and 32a–c.
    - Form 8959's Part II becomes RRTA and self-employment moves to Part IV, under identical field names.
    - Schedule 2 is renumbered.
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
- [ ] **JF6b — Rewire calc.py's line literals** (M; deps JF6a) [DEF-05 + DEF-06 calc part + DEF-08]
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
- [ ] **JF6c — Rewire the other sites and the Schedule 1-A keys** (M; deps JF6b) [DEF-06 rest + DEF-07 + the line half of LD-08]
  - intake.py:1172-1179 asks a planning-year user for "line 11" of the prior return. Also fix schemas/profile.py:477-492, server.py:211/344/386-392 and workspace.py:81, and the Form 1040-NR itemized "line 12" (estimate.py:1033/1223/1717), which becomes 12a in 2026.
  - schedule_1a_deductions hardcodes form_line keys 13/21/30/37 and "line 38 → 1040 13b / 1040-NR 13c" (calc.py:2937-2940, :2962-2965, :3129-3180; server.py:396). These key verify_form's recompute.
  - The draft 2026 Schedule 1-A (Created 6/16/26) totals on 15/27/36/43 → 44 → 1040/1040-NR 13a, with rounding lines 13/25/34. Data-drive the keys.
  - The 2026 total-tax line for the §6654 prior-year prong (24a vs 24c) is UNVERIFIED; leave it absent until JT6.
  - **Acceptance.**
    - The 2026 planning-year intake question contains "11a".
    - 2025 Schedule 1-A form_line keys stay ['13','21','30','37']; 2026 data has `sched1a.car_loan == '36'` and `f1040.sched_1a == '13a'`.
    - The frozen debt list is empty; `test_form_lines_resolve` passes for every year that has packs.
- [ ] **JF7 — Schedule 1-A reaches the estimator** (M; deps JF6c, JF1b) [LD-09]
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
- [ ] **JF8 — Schedule 1-A for 2026, and Form 1098-VLI** (M; deps JT0b, JF6c, JF7)
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
- [ ] **JF9 — The 2026 charitable deduction and its characterization rules** (M; deps JT0b, JF7, JF2) [LD-06 + DEF-18 + TY26-17 + LD-07] — pitfall *charitable-characterization*
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
- [ ] **JT1a — PTC 2026: the cliff returns** (M; deps JT0b) [TY26-12]
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
- [ ] **JT1b — Dependent care 2026** (M; deps JT0b) [TY26-11]
  - **Why.** The draft i2441 line 8 table's second phase-down leg depends on filing status: joint from $150,000 in $4,000 steps, others from $75,000 in $2,000 steps. The rate "ranges from 50% to 20%", and line 21 is $7,500 ($3,750 MFS). DependentCarePhaseDown (knowledge.py:908-950) and calc.py:2697-2714 have no status key.
  - **Build:** `applies_to: all | joint | non_joint`, then author 2026.
  - **Acceptance:** goldens for every row of the draft table.
- [ ] **JT1c — The Schedule 3-A gate (federal public benefit)** (M; deps JT0b) [TY26-18] — pitfall *public-benefit-qualified-alien*
  - **Why.** The draft Schedule 3-A (Created 6/24/26) moves the refunded EIC / ACTC / refundable AOTC / adoption credit to 1040 line 32b unless the filer or spouse is "a U.S. citizen, U.S. national, or qualified alien".
  - **Definition, read now.** 8 U.S.C. 1641(b) (uscode.house.gov, read 2026-09-23) defines "qualified alien" as:
    - (1) lawfully admitted for permanent residence;
    - (2) asylee;
    - (3) refugee;
    - (4) parolee for at least 1 year;
    - (5) deportation withheld;
    - (6) conditional entrant;
    - (7) Cuban/Haitian entrant;
    - (8) Compact of Free Association resident.
    
    (c) adds certain battered aliens. No nonimmigrant category is listed. Whether the Schedule 3-A instructions adopt §1641 is UNVERIFIED (not posted).
  - **Build.**
    - A `federal_public_benefit` block: the form flow plus the §1641(b)–(c) list, with the mapping labeled "provisional — Schedule 3-A instructions not posted".
    - Profile fact `identity.qualified_alien_status`.
    - F / J / M / H / L / O and similar nonimmigrant statuses map to "not listed in 1641(b) (provisional)".
    - The estimator prices the forfeited refunded portion as the LOW end of the range, not a blanket NOT ESTIMATED.
  - **Acceptance.**
    - An H-1B household with ACTC → the low end drops the refunded portion; an LPR household → unchanged.
    - A test refuses a 2026 credits block that has no `federal_public_benefit` block.
    - The pitfall has citing tests; re-verified at JT6.
- [ ] **JT1d — Credits 2026** (M; deps JT1c) [TY26-08]
  - From Rev. Proc. 2025-32 §§4.05–4.06:
    - CTC $2,200, refundable portion $1,700;
    - the EITC table, including the $664 no-child maximum and the $12,200 investment-income limit;
    - the FTC de minimis $300/$600 (IRC 904(j)).
  - Pass 2: the draft i1040s8 and the draft Pub 1040 (2026).
  - **Acceptance:** eval i5 and the ledger tests pass through the JT0b fixtures.
- [ ] **JT1e — Education credits 2026** (M; deps JT1c) [TY26-10] — pitfall *education-ssn-deadline*
  - MAGI limits $180,000 / $90,000 (draft i8863).
  - The new rule: filer and student "must have been issued valid SSNs before the due date of your 2026 return, including extensions". Add `ssn_requirement`.
  - The estimator gates AOTC/LLC on SSN-vs-ITIN facts, NOT ESTIMATED when unknown.
  - **Acceptance:** an ITIN-only student → no AOTC; an unknown status → NOT ESTIMATED; the pitfall has citing tests.
- [ ] **JT2a — Tax Table, SALT/itemized, student loan, Social Security** (M; deps JT0b) [TY26-05, TY26-07, TY26-09, TY26-13]
  - **Tax Table.** The draft Pub 1040 (2026) (Aug 28, 2026) matches the engine on all 8,240 cells. Record it as a draft second pass, and add goldens at the 25/50 band edges.
  - **SALT.** salt_cap is missing and NOT declared absent (2025.yaml:557 ships it). The draft Schedule A line 5e: $40,400 ($20,200 MFS), threshold $505,000 ($252,500). Add an absent-list discipline test.
  - **Itemized 2026.** `itemized_2026` with the 0.5% floor and the §68 threshold (draft line 18: $384,350). Its worksheet mechanics stay a lookup_path until i1040sa (2026) posts (404 on 2026-09-23).
  - **Student loan interest.** Rev. Proc. 2025-32 §4.29: $85,000 / $175,000 → $100,000 / $205,000.
  - **Taxable Social Security.** IRC 86(c) plus the draft Pub 915.
  - **Acceptance:** the goldens and the discipline test pass.
- [ ] **JT2b — Deadlines, payment options, with-payment addresses** (S–M; deps JT0b) [TY26-14 + the rest of TY26-15]
  - Deadlines from the draft 4868 (2026): "April 15, 2027 … June 15, 2027 … October 15, 2027". JR2a's helper then reads the block.
  - Payment options and with-payment addresses from the draft 1040-V (2026), one per state group (e.g. "P.O. Box 1214 Charlotte, NC 28201-1214", shared by several states).
  - **Acceptance:** file_and_pay on a synthetic TY2026 manifest returns 2027-04-15 and the address (today it returns `deadlines: []`, `mailing_address: None`).
  - **External:** filing_thresholds and the no-payment addresses wait for the 2026 i1040gi / Pub 501 (JT6).
- [ ] **JT4a — The 2026 W-2 and structured W-2 facts** (M; deps JF3, JF2) [TY26-24 + DEF-17]
  - **Why.** The 2026 W-2 splits box 14 into 14a/14b and adds box 12 codes TA / TP / TT (iw2w3 2026). The DocSpec has 12a–12d as raw codes and no box 14 (extract.py:81-110).
  - **Build.**
    - Add 14a/14b, a box-12 code table, and revision aliases.
    - Routing: TP → Schedule 1-A Part II, TT → Part III, W → 8889 line 9, D/E/G/AA/BB → 402(g).
    - `IncomeSnapshot.w2s: list[W2Facts]` (boxes 1–7, 10, 12), with a validator that derives or checks the aggregates.
    - Box 10 feeds the dependent-care employer benefits (estimate.py:2045-2047 admits they are untracked).
    - A box-12-W double-count guard, and a 402(g) excess assumption.
  - **Acceptance:** a W2Facts mismatch raises; derived aggregates equal hand-fed ones; box 10 reduces the 2441 expense limit (closed-year test).
- [ ] **JT4b — 1099-B boxes** (S; deps J0) [TY26-26]
  - Add 1f, 2-ordinary, 3, 6, 7 and 12 (extract.py:268-285). Box 12 (basis reported to IRS) decides Form 8949 box A or B, or direct entry on Schedule D.
  - **Acceptance:** a box-12 reading carries the routing note.
- [ ] **JT4c — Dress-rehearsal evals, scenarios t–t4** (M; deps JT3a–d, JT4a, JT4b, JF1a, JF8, JF9, JR2c, JR3c, JT2b) [TY26-29]
  - A SYNTHETIC TY2026 dress rehearsal with demo amounts, built only from its own stated facts. It covers the mechanics:
    - two W-2s from concurrent employers, code D at each plus DD;
    - a 1099-INT and an index-fund 1099-DIV (qualified and non-qualified);
    - a covered 1099-B sale with box 12;
    - a code-N and a code-2 1099-R on a separate what-if fixture;
    - a 5498-SA on a family-coverage fixture;
    - a 170(p) gift on a separate what-if fixture;
    - a treaty teacher/researcher exemption surviving the saving clause on the Schedule 1 other-income line.
  - Path, for each: extract → calc → fill (rehearsal) → verify_filing → filing_summary → file_and_pay (2027-04-15 plus the with-payment address). All four flip to final mode at JT6.
  - **Acceptance:** green in rehearsal mode.
- [ ] **JT5a–g — Wave B: the rest of the federal set for 2026** (JT5a **latest start 2026-11-16**; deps JT3a; each sub-tranche commits per pack) [TY26-21]
  - **JT5a** (M): copies f843, fw7, f8316 (current finals byte-identical to their 2025 pins) and fincen114; near-ports sched_se, f4868, f8960.
  - **JT5b** (M): sched_8812, f2555, f8863.
  - **JT5c** (M–L): f1040nr (new 12b, 13a, 24a–c, 32b), sched_a_nr, f8843.
  - **JT5d** (M–L): sched_a, sched_c, sched_e.
  - **JT5e** (M–L): f8962, f2441, f1116, f8938 (Rev. 12-2026).
  - **JT5f** (M): f1040x (Rev. 12-2026), and sched_3a (new).
  - **JT5g** (external): sched_nec and sched_oi, once their 2026 drafts post. The f1040nrn/nro drafts are still 2025; they are on the check_finals watchlist.
  - **Acceptance:** as JT3.

### Block 5 — Remaining decision ops

- [ ] **JP1b — Pub 15-T 2026 knowledge** (M; deps JF1a) [LD-02, knowledge half]
  - **Why.** There is no Pub 15-T knowledge; `federal_withholding` is a single integer (estimate.py:101).
  - **Build.** A top-level `payroll_withholding` 2026 block, typed `PayrollWithholdingParams` and transcribed from Pub 15-T (2026):
    - Worksheet 1A line 1g: $12,900 MFJ / $8,600 otherwise; $4,300 per pre-2020 allowance;
    - pay periods;
    - the STANDARD and Step-2-checkbox annual tables for MFJ, single/MFS and HoH;
    - the NRA add-on: $16,100, or $11,800 on a pre-2020 W-4;
    - the partial-period rule (Pub 15 §8) and the rounding rule.
  - **Second-pass test:** every STANDARD row equals the pack's rate_schedules shifted by (standard deduction − line 1g), and every checkbox row equals the half-width brackets. The table itself is transcribed, not computed.
  - **Acceptance:** the derivation test passes for all three statuses and both tables.
- [ ] **JP1c — The withholding projection op** (M–L; deps JP1a, JP1b) [LD-02, op half + missing Pub 15-T §6 + the rest of LD-12]
  - **Build** `calc.withholding_projection`, per employer:
    - inputs: W-4 facts, pay frequency and dates (counted by PAY DATE), employment end, and supplemental events carrying the reg's two facts (paid concurrently / separately stated; income tax withheld on regular wages this or last year);
    - flat rate REFUSED when either condition fails; both methods returned as a range when a fact is unknown;
    - 37% over $1M;
    - 0.9% per employer;
    - residency_classification auto-filled into employee_fica.
  - **Employee-requestable methods** (Pub 15-T (2026) §6), each with its gate:
    - "cumulative wages" (a written request; same payroll period since Jan 1);
    - "part-year employment" (written, under penalties of perjury, calendar-year basis, and "no more than 245 days in all terms of continuous employment").
  - **Outputs:** projected W-2 boxes 2 / 4 / 6, inputs ready for estimate_refund, and a projected-withholding figure that feeds JP1a's 4(c) solve. JF1a's use sites gain the op pointer.
  - **Acceptance.** Tests keyed on facts, not hire status:
    - (i) bonus before any withheld regular check this or last year → aggregate forced;
    - (ii) bonus after a withheld regular check, separately stated → both methods, as a range;
    - (iii) concurrent and not separately stated → aggregate;
    - (iv) concurrent with the FIRST regular check and separately stated → labeled interpretive choice.
    
    Also: sampled Pub 15-T (2026) wage-bracket rows reproduced within $1; Pub 15 §7 Example 3 (22% × $1,000 = $220); the NRA add-on; a partial first period; the part-year method refused at more than 245 days. Op count +1.
- [ ] **JP5a — Underpayment penalty, regular method** (M; deps JF4) [critic: missing]
  - **Why.** No op or knowledge covers Form 2210 (grep of calc.py and knowledge/federal 2025–2026). It is the only way to price the choice between accepting the penalty, bumping the W-4, and paying 1040-ES.
  - **Law.** IRC 6654(a) adds an amount "determined by applying (1) the underpayment rate established under section 6621 … (2) to the amount of the underpayment, (3) for the period of the underpayment". The draft Form 2210 (2026) was Created 4/16/26; the draft Pub 505 (2026) is posted.
  - **Build** `calc.underpayment_penalty`: required installments from JF4's safe-harbor inputs; withholding deemed ratable per §6654(g)(1) unless actual dates are elected; per-quarter §6621 rates from a new knowledge list.
  - A quarter whose rate is not yet in the pack fails closed. The Q1-2027 rate is announced later — external.
  - **Acceptance:** a Pub 505 / 2210-instructions worked example is reproduced; a missing-rate quarter refuses; op count +1.
- [ ] **JP5b — The annualized income installment method (Schedule AI)** (M; deps JP5a)
  - IRC 6654(d)(2)(A): "if the individual establishes that the annualized income installment is less than the amount determined under paragraph (1)- (i) the amount of such required installment shall be the annualized income installment".
  - Implement the draft Form 2210 (2026) Schedule AI periods and factors, read off the draft face, labeled draft.
  - **Acceptance:** a Q4-weighted income case has a lower penalty under AI than under the regular method, and the op reports both.
- [ ] **JP3a — Employment schema and paystub DocSpec** (M; deps JP1c) [LD-04, part 1]
  - `Profile.employment`, per year: employer label, start/end, pay frequency, first pay date, W-4, per-period pre-tax amounts (401(k), §125, HSA cafeteria, FSA, §132(f)) and post-tax amounts (Roth, after-tax, loan).
  - A `paystub` DocSpec. source_url = iw2w3.pdf; the note says it is not an IRS form and YTD figures are authoritative only through the pay date.
  - **Acceptance:** a synthetic stub extracts; a workspace save/load round trip keeps the schema.
- [ ] **JP3b — Paystub → projected W-2** (M; deps JP3a, JP2) [LD-04, part 2]
  - **Build** `calc.paystub_to_w2`:
    - box 1 = gross − 401(k) pretax − §125 − HSA cafeteria − FSA − §132(f);
    - box 3 = gross − §125 − HSA − FSA − §132(f), capped per employer ("The total of boxes 3 and 7 cannot exceed $184,500");
    - box 5 = the same, uncapped;
    - box 12: D / AA / W / C;
    - remaining checks counted by PAY DATE ≤ Dec 31 (the W-2 "Calendar year basis");
    - nothing annualized after employment_end.
  - annualize_ytd's work gains "never annualize an ended job".
  - **Acceptance:** a synthetic YTD stub reproduces a known W-2; an ended job is not annualized; a check paid Jan 1 lands on next year's W-2. Op count +1.
- [ ] **JP4 — Wage repayment: claim of right (§1341)** (M; deps JF2) [LD-13] — pitfall *claim-of-right*
  - **Law.**
    - Pub 525: "if the amount repaid was $3,000 or less, you aren't able to deduct it". Above $3,000, deduct on Schedule A line 16 or take the §1341 credit, "Use the method … that results in less tax".
    - Pub 15 §13: prior-year wages "remain taxable … for that year"; Form 1040-X is used only for Additional Medicare Tax; FICA comes back through the employer's 941-X / W-2c.
  - **Build** `calc.claim_of_right_repayment`.
  - **Acceptance:** Pub 525 Example 40 ($5,000 → method 1 $5,156 vs method 2 $5,335); ≤ $3,000 → $0. Op count +1; the pitfall has citing tests.
- [ ] **JR4a — Form 5329, 2025 pack** (M–L; deps JR3c) [RC-14]
  - New form key f5329 (added to KNOWN_FORM_KEYS). Built by the standard vision-audited process, with verify recomputing from JR3c's rules.
  - **Acceptance:** golden round trip; the Part I line 2 exception-21 entry exercised.
- [ ] **JR4b — Form 5329: 2023/2024 ports and the 2026 draft pack** (M; deps JR4a, JT0a)
  - The 2026 draft (Created 7/31/26) routes to Schedule 2 lines 5 and 18. Ship it as `source_status: draft`, re-pinned at JT6.
  - **Acceptance:** per-pack goldens (the 2026 one in rehearsal mode).
- [ ] **JP5c — Form 2210 packs** (M–L; deps JP5b, JT0a)
  - New form key f2210: a 2025 pack, plus the 2026 draft pack (Created 4/16/26) in draft mode.
  - **Acceptance:** per-pack goldens; the verify recompute matches JP5a/b.

### Block 6 — Docs, release, debt

- [ ] **JD1 — Docs truth-up, the rest of old J6** (M; deps JR2c, JF6c)
  1. **README** [G08]. The tool table lists 16 of 23 tools. The calc row names non-ops (`routing_checksum` → "unknown calc op") and omits 20 real ones. It says "always labeled ESTIMATE", but planning years are labeled PROJECTION (estimate.py:501). The M7 line is stale. Generate the table, and add a test that every runtime tool name appears in README.
  2. **DEV_PLAN** [G09]. Add "Deviations as built":
     - the PROJECTION label;
     - freshness runs weekly, not nightly;
     - the DocSpec set is list_document_kinds (I-94, I-20 and the transcript were never built; the paystub arrives in JP3a);
     - there are no perceptual-hash tests;
     - the registries are the live lists.
  3. **SKILL.md and the estimate_refund docstring** [G10]. Both say ESTIMATE only, and SKILL.md cites a "28-form set" (actually 34/34/35).
     - Add Recipe P (planning-year projection) and Recipe R (IRA basis / backdoor / recharacterization).
     - One bullet per calc op.
     - Regenerate bundle/manifest.json tools; mirror to the codex and copilot skills.
  4. **CONVENTIONS** [G11]. The form_key list shows 16 of 35 keys: defer to KNOWN_FORM_KEYS with an equality test, and add a hand-fill section. The overlay section waits for JS4.
  5. **CONTRIBUTING** [G12]. The pitfall gate exists; there are no snapshot tests; freshness is weekly; the dev command is `uv run python -m pytest -m "not network"`.
  6. **FIELD_NOTES** [G13]. A status line per N-item, and hypothetical-persona entries for the H9, Phase I and Phase J findings (mechanisms only, demo numbers).
  7. **Test docstrings** [G14]:
     - test_skills_sync.py:3 still says "22-tool" and :97 "30 ops";
     - test_readonly_widget_mapping.py:41-43 still says "1,140 / 10", and :381-385 carries the resolved MS note.
  8. **D2 triage table** [G05]. Re-measure it, and record UT 2025 as PORTABLE and unshipped (JS3b).
  9. **Privacy** [G29]. Docs, tests and evals use hypothetical fixtures with demo numbers, per FIELD_NOTES' own rule.
  - **Acceptance:** every count equals the runtime; the README tool-name test and the CONVENTIONS/KNOWN_FORM_KEYS test pass; the new FIELD_NOTES entries use hypothetical personas and demo numbers only.
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
- [ ] **JEa — SSN maxlen and reserved lines** (M; deps J0) [G30 + PJ-13 rest]
  - `identifying_number` has maxlen 9 on f8606 and f8960 (2023–2025), where the widget /MaxLen is 11 (f8606 2025 `f1_02[0]`; f8960 2025 `f1_2[0]`), against CONVENTIONS.md:228. Set 11, and add a network-marked invariant that pack maxlen == widget /MaxLen.
  - Add `PackField.reserved`, a fill_form warning, and an audit_pack skip.
  - Add a CONVENTIONS "ReadOnly and reserved widgets" rule, including "never map DOR instruction banners" (J0.3's root cause).
  - **J0 verifier follow-ups (2026-09-24):**
    - run `test_verify_readonly_sweep.py` in the freshness job after the network round trips warm the blank cache (CI's offline job skips all its per-pack cases);
    - unmap the same-shape class-1 captions AL-40 2023 and MO-1040 2023/2024 still carry (they fit their boxes, so never FAIL): AL `txtMultiScheduleD/E`; MO the 28 `printlid.*` lids, `ProtectBarcode`, `amendedTXT`, `1040_30Text`, `line51txt`, `vendorid` — re-pin STATE_COMPUTED_READONLY;
    - adjudicate mapped ReadOnly widgets whose blank holds a non-zero number (class 1 printed constant vs class 4 calculator default): GA 500 `TP/SP_S1L4` 4000, `S1L2_P3` 17500, `S1L7_P3` 35000; MO `line32Y/S`, `moa_wks6`, `moa_pt4_4`, `moa_pt3_4`, `moa_pt5_2`; WV `it140_6`;
    - enforce the bound pack `maxlen` in `clipping_scan` for a ReadOnly widget with no `/MaxLen` (GA 500 `STATE1`, WV `it140_totex5` are filler-enforced only today);
    - the width heuristic ignores the multiline flag (/Ff bit 13), so a long explanation in an editable multiline box can false-FAIL;
    - give fetch.py a public `cached_blank_path(url, sha256)` (verify imports the private `_cache_path`);
    - reword the stale "verify skips ReadOnly widgets" prose in the federal sched_d / sched_e 2023–2025 pack headers, the OH it1040_oh 2023/2024 headers, test_formpacks_federal.py:267 and test_pack_invariants.py:758.
  - **Acceptance:** the maxlen invariant is green; fill_form warns on a reserved line.
- [ ] **JEb — Checkbox topology** (L, commits per pack family; deps J0) [G31]
  - Option sets on separate single-widget fields whose tokens are not yes/no are invisible to both P-008 gates. Measured 2026-08-26 on 160 packs: 285 such sets across 81 packs, 193 without a shared group id. Re-measure on 172.
  - Add `test_separate_widget_option_sets_are_adjudicated` with a self-clearing table justified from the printed rows.
  - **Acceptance:** green, with every exemption adjudicated; closes the Phase E box.
- [ ] **JD2 — Process: derived counts, suite speed, branches, ROADMAP shape** (M; deps JD1)
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
    - Settle the 2026 total-tax line (24a vs 24c).
    - Re-verify the Schedule 3-A qualified-alien mapping.
    - Author filing_thresholds and the no-payment addresses from i1040gi / Pub 501 (2026).
  - **Flip.** Remove the provisional marker; JT0a's invariant enforces that no draft pack remains. A Wave B pack without a final moves to a draft branch instead of holding the flip.
  - **Next year.** Author knowledge/federal/2027.yaml, provisional, from the 2027 inflation Rev. Proc. (not on irs-drop as of 2026-09-23). Scenarios t–t4 flip to final mode.
  - **Target.** The TY2026 dress-rehearsal scenario (t) fills and verifies on the finals **within 5 business days of the last required final**.
    - By the 2025 precedent the form finals and Pub 1040 arrive by mid-January 2027 (f1040 created 2026-01-02; p1040 modified 2026-01-15), and i1040gi arrives last, around late February (2025 edition created 2026-02-25). This is an inference, not a guarantee.
    - An earlier flip, with filing_thresholds and the no-payment addresses left as disclosed absences (file_and_pay pointing at the irs.gov where-to-file page), is a plan choice for the user; it needs a small post-provisional `filing_grade_absent_blocks` list.
  - **External:** the IRS finals and the 2027 Rev. Proc.

### Block 7 — State (federal-first; starts after the federal lanes)

- [ ] **JS1a — DC 2025 re-verification** (S–M) [G22]
  - The cited DC 2025 booklet (~20 citations in knowledge/states/dc/2025.yaml, 6 in sources_states.yaml:532-609) has returned 404 since 2026-08-24; DC OTR links a re-issued `2025_D40_Book_082026_v1.pdf`.
  - Diff every quoted passage (rates, standard deduction, mailing addresses, OBBBA decoupling), update the URLs, regenerate sources_states.yaml (byte-equality test), and remove J0.6's `unverified` line and JT0c's allowlist row.
  - **Acceptance:** the drift job is green for DC; the allowlist row is gone.
- [ ] **JS1b — MA mirror and a seed command** (M) [G23]
  - MA Form 1's Wayback cache-seed exists only on the maintainer's disk, and CI and fresh installs get a 403 that says "retry in a minute".
  - Add pack `mirror_urls` with the exact `web.archive.org/web/<ts>id_/<official>` snapshot, tried on 401/403 and ALWAYS digest-verified.
  - Add `taxfill seed-blank`, and name both remedies in the 403 message.
  - **Acceptance:** a mocked 403 exercises the fallback; a digest mismatch fails closed; the network layer is green; the allowlist is empty.
- [ ] **JS2 — State law-change sweep (old J5, re-scoped)** (M) [PJ-17 + G05(c)]
  - 30 of the 84 2024/2025 packs lack `effective_law_changes`; 15 have law-change prose (ar24, ar25, ca24, ct24, mi25, ms24, ms25, nd24, nm24, ny24, sc24, sc25, wi25, wv24, wv25).
  - Adjudicate those 15 from the booklets they cite. Record an explicit empty list with "checked <date>, source <url>" for the other 15.
  - **Acceptance:** a gate test that the key is present on all 84 packs (and on every future state year pack).
- [ ] **JS3a — Scaffold starts from the newest base** (M) [G05 + PJ-15 (1)]
  - `scaffold_state_year.py` gains:
    - `--base newest`;
    - `--rows <json>`, seeded from the 16 recovered discovery rows (url + sha256 in the wf_babce8da-141 journal);
    - a cache-first triage (today network-only, :72-101);
    - year+1 upload-folder and revision-token derivation (AL, CT and DC tokens are stale today).
  - **Acceptance:** the offline triage reproduces the recorded rows; UT 2025 triages PORTABLE against UT 2024.
- [ ] **JS3b — Cheap state ports** (M–L, per pack) [G05 + PJ-15 (2)–(3)]
  - UT 2025 TC-40 is PORTABLE and unshipped: files.tax.utah.gov/tax/forms/2025/tc-40.pdf returns 200, sha256 0eac22fb…37cdf, and all 106 mapped UT-2024 fields exist in it.
  - Then the rows marked PORTABLE / NEAR-PORT, TY2025 first: AZ 24/25, DC 24/25, KY 24 (PORTABLE) / 25 (NEAR-PORT, 4 fields), LA 24, AL 24 (NEAR-PORT, 3), ID 24 (NEAR-PORT, 2).
  - **Acceptance, per pack:** re-downloaded with a digest pin, vision-audited, golden round trip.
- [ ] **JS4a — Overlay verifier fixed and tested** (M; on `phase-j2-overlay`) [PJ-01 + PJ-06]
  - **FILING-WRONG once merged.** verify_overlay substring-matches over the expected text's layout (overlay.py:596-610), so a PDF stamped 14,000 / 10 / 1,200 verifies ok against expected 4,000 / 0 / 200.
    - Look up text in the DECLARED box.
    - Isolate the stamped glyphs (font filter, or subtract the pinned blank's own text).
    - Require exact equality.
    - A blank line's box must hold no stamped glyphs; unknown keys are refused.
  - **Tests.** The 721 lines have zero tests. test_overlay.py on a synthetic flat PDF:
    - the round trip and every alignment;
    - the shrink / overflow / non-WinAnsi warnings;
    - bad page / key / coordinates;
    - the widths table vs the pypdf metrics;
    - locate_labels within ±1 pt, and whole-word matching;
    - the PJ-01 negatives.
    
    Plus CLI and server tests (tool count 23), a CONVENTIONS overlay section, and a lazy import in server.py.
  - **Acceptance:** the PJ-01 negatives FAIL; test_overlay is green.
- [ ] **JS4b — verify_filing routing, FBAR "blank", DOR guidance** (M) [PJ-08 + PJ-10]
  - verify_filing loads only FormPacks, so a stamped CT-1040 raises FileNotFoundError. Route hand-fill items through verify_overlay.
  - fetch_blank serves the FBAR's *instructions* PDF as a "blank" (fincen114/handfill.yaml:205); refuse e-file-only packs, pointing at the BSA E-Filing System.
  - Read the CT DRS / SC DOR / NM TRD / HI DoTax guidance on machine-printed entries, record it verbatim in each handfill.yaml, and encode any font-size minimum.
  - **Acceptance:** verify_filing verifies a manifest with a stamped CT-1040; fetch_blank('fincen114') refuses; the DOR rules are recorded.
- [ ] **JS4c — CT-1040 2023 pilot** (M–L) [PJ-07]
  - Overlay blocks for all 4 pages from `taxfill locate` anchors. The page-1 right column is x=405, w≈132, and ends before the pre-printed ".00" (smoke-verified).
  - Render and vision-check every page; merge the branch once JS4a–b are green.
  - **Acceptance:** golden stamp → verify_overlay ok → render.
- [ ] **JS4d — SC, NM, HI overlays** (L, per pack)
  - SC line numbers are not isolated words in the text layer, so anchor on captions.
  - **Acceptance, per pack:** as JS4c.
- [ ] **JS5 — State 2024/2025 re-maps and URL discovery (rest of old J3)** (XL, per pack) [PJ-15 (4)–(5)]
  - Open at the 2026-09-11 count: 73 pack-years, minus JS3b.
    - 2024: 32 (RE-MAP 10, URL-DEAD 11, no-token 7, print-only 4).
    - 2025: 41 (PORTABLE 1, RE-MAP 12, URL-DEAD 17, no-token 7, print-only 4).
  - TY2025 before TY2024. Every CA pack is a full re-map.
  - Resume discovery for the 20 never-started states plus OK, MA and NE in resumable pools of 3–4 workers. The remaining TY2024 rows fold into JS7.
  - **Acceptance, per pack:** digest pin, vision audit, golden round trip, triage row updated.
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
- DEV_PLAN's I-94 / I-20 / IRS-transcript DocSpecs and perceptual-hash snapshots; JD1 records them as deviations.

**Acceptance (phase):**
- J0 leaves main clean and green.
- Every 2026-09-23 review defect is fixed with a regression test, pitfall-cited wherever the rule is durable.
- No form line number is typed outside `form_lines` (the JF6a guard).
- The recharacterization flow runs end to end: from a 1099-R, 5498 or custodian statement to the Form 8606 inputs, the 1040 lines and the attached statement.
- The TY2026 dress-rehearsal scenario (t) fills and verifies on the finals within 5 business days of the last required final.
- Every open box elsewhere in this ROADMAP is closed or named in a tranche: A1–A6 → JA1/JA2; C2 → JS6; D2 → JS3a/b, JS5, JS7; Phase E ×2 → JEa/JEb; H5's Tax Table → JT2a/JT6.

## Phased sequencing (recommended order)

1. **Done:** Phase 0, E (except two boxes, now JEa/JEb), F, G, H (except H5's 2026 Tax Table, now JT2a/JT6), I, and persona-review Tiers 1+2.

2. **Phase J (re-planned 2026-09-23) is the whole forward plan.** Execution order:

   J0 → JF6a → JF1a → JF5a → JF5b → JF1b → JF2 → JF3 → JF4 → JP1a → JP2 → JR1 → JR2a → JT0a → JT0b → JT0c → JR2b → JR2c → JF6b → JF6c → JF7 → JR3a → JR3b → JR3c → JT3a → JT3b → JT3c → JT3d → JF8 → JF9 → JT1a → JT1b → JT1c → JT1d → JT1e → JT2a → JT2b → JT4a → JT4b → JT4c → JP1b → JP1c → JT5a … JT5f → JP5a → JP5b → JD1 → JA1 → JP3a → JP3b → JP4 → JR4a → JR4b → JP5c → JEa → JEb → JD2 → *(JT6 when its trigger fires)* → JS1a → JS1b → JS2 → JS3a → JS3b → JS4a … JS4d → JS5 → JS6 → JS7.

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
* MA's fetch block gets a recorded, digest-verified mirror (JS1b);
* TY2026 authoring runs on drafts-first packs (JT0a).

**The external gates are:**
* **the user:** JA2; the branch-protection decision (JD2.3); remote branch deletes (JD2.4); the labeled interpretive choices in JR2b and JP1c; the JT6 flip policy; any DC exception before 2026-10-15;
* **the IRS:**
  - the 2026 finals and the 2027 inflation Rev. Proc. (JT6);
  - the Schedule 3-A and Schedule A 2026 instructions (JT1c, JT2a);
  - the Schedule NEC/OI drafts (JT5g);
  - the §6621 rate for Q1 2027 (JP5a);
* **the states:** their 2026 blanks (JS7).
