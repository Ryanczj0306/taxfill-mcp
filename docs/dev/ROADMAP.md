# TaxFill — Completion Roadmap (remaining work)

The design spec is [`docs/dev/DEV_PLAN.md`](DEV_PLAN.md). This is the forward-looking
plan for what is **not yet done**, as of **2026-10-09** (re-planned 2026-10-09 — see Phase K; the 2026-09-23 re-plan is Phase J).

> **Status note (2026-10-09).** Re-planned **pointer-first** (Phase K, approved by the user 2026-10-09).
> Every federal and engine Phase J tranche is done except JT5g / JT6 (gated on the IRS), JA1 / JA2 (the
> release), JEe and JD2.3 (the user's).
> The state backfill (JS5 / JS6) lands what its recovery wave re-creates of 23 packs (JK0) and then stops,
> except on demand. Next: the release (JK2–JK7), TY2026 readiness (JK8–JK11, JT6, JS7a), the no-pack
> fallback fill path (JK13–JK19) and the knowledge-layer slim (JK20–JK26).
>
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

Done and on `main` (**9,347 tests** — offline 8,078 + live-.gov 1269; derived
by `scripts/sync_test_count.py --write` at every Phase J commit). The offline layer is green in CI and locally
(Python 3.11, matching CI, since J0). The weekly network layer has been **RED since
2026-08-17** — 6 of 6 freshness runs failed through run 35621846216 (2026-09-21) — on
two sources: the MA Form 1 blank returns 403 and the DC 2025 booklet returns 404 (DC
OTR re-issued it). Phase J JT0c (2026-09-27) put both behind an expiring allowlist
(`scripts/freshness_quarantine.yaml`), so a NEW red opens a `freshness red` issue, and
JS1a/JS1b (2026-09-28) fixed both. The last row — JS1b's newest-capture probe showed mass.gov
re-issued the 2023 Form 1 in May 2026 as a rebuilt AcroForm — retired 2026-10-02 when JS5
re-mapped the pack onto the re-issue. The 2026-10-12 run was red again on two new causes — the MN 2025 M1
booklet moved, and mass.gov and its Wayback mirror refuse GitHub-hosted runners — which JK2 (2026-10-15)
fixed or quarantined: the MN citations re-pointed, fetch retries and a CI blank cache added, and the ten MA
network tests quarantined until 2027-01-11.

> **Status (2026-10-15):** JK2 landed (978fc2f): the MN booklet citations re-pointed, fetch and finals-watch retries,
> a CI blank cache and the ten MA quarantine rows. The scheduled runs of 2026-10-19 and 10-26 are the proof; issue #3
> closes after the first green one. The code CI (ci.yml) is green.

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
- **State form packs — 130 across three years** (TY2023 48 / TY2024 41 / TY2025 41).
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
jurisdictions**: **38 via fillable AcroForm (130 packs across TY2023–TY2025)** — CA (540 + 540NR +
Schedule CA 540/540NR), NY (IT-201 + IT-203), IL, PA, OH, GA, NC, MI, NJ, VA, AZ,
IN, MO, MD, AL, CO, MN, WI, KY (740), OR (OR-40), LA (IT-540), KS (K-40),
AR (AR1000F), ID (40), NE (1040N), OK (511), ME (1040ME), MS (80-105),
RI (RI-1040), MT (Form 2), ND (ND-1), DE (PIT-RES), VT (IN-111), DC (D-40),
WV (IT-140), IA (IA 1040), MA (Form 1), UT (TC-40) — plus **4 via print/hand-fill
manifests**: CT (CT-1040), HI (N-11), NM (PIT-1), SC (SC1040).
**298 form packs total** — 281 `pack.yaml` (151 federal + 130 state) + 17
`handfill.yaml`. The state 130 breaks down **TY2023 48 / TY2024 41 / TY2025 41**.
> ⚠️ State form-pack year coverage is now **partial, no longer TY2023-only**:
> **42 of the 42 jurisdictions fill a post-2023 year** —
> TY2024 for **41** (AL, AR, AZ, CA, CO, CT, DC, DE, GA, HI, IA, ID, IL, IN, KS, KY, LA, MD, ME, MI, MN, MO, MS, MT, NC, ND, NE, NJ, NM, NY, OH, OK, OR, PA, RI, SC, UT, VA, VT, WI, WV) and TY2025 for **42** (AL, AR, AZ, CA, CO, CT, DC, DE, GA, HI, IA, ID, IL, IN, KS, KY, LA, MA, MD, ME, MI, MN, MO, MS, MT, NC, ND, NE, NJ, NM, NY, OH, OK, OR, PA, RI, SC, UT, VA, VT, WI, WV) — after the 2026-08-21
> ten-pack and 2026-08-25 four-pack tranches and the JS3b ports (UT 2025,
> AZ 2024/2025, DC 2024/2025, KY 2024/2025, LA 2024, ID 2024). For the remaining **0**, state *knowledge*
> spans 2023–2025 while the only fillable pack is TY2023, so `calc.state_tax`
> still computes years those packs cannot fill. That asymmetry is now 0
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

**Next (2026-10-15):** Phase K, below. JK0 (the recovery wave) is done; next the release (RC by
2026-10-23; the upload waits on the user's JA2 steps), then TY2026 readiness, then the no-pack fallback,
then the knowledge slim. The synced counts above are current (every JK0 integration re-ran
scripts/sync_doc_counts.py); the unanchored ones are JK1's: the calc op count is 40
(packages/mcp-server/tests/test_skills_sync.py:54), not the 35 quoted above.

---

## History

The completed phases — 0, E, F, G and I — moved VERBATIM to [`docs/HISTORY.md`](HISTORY.md) (now `docs/dev/HISTORY.md`) on 2026-09-28 (Phase J JD2), so this file carries the open work. Their cross-references ("see Phase G", tranche ids) resolve there. Phases C, D and H stay here: each still has a box open under a Phase J tranche. In the commit that lands the 2026-10-09 re-plan (Phase K JK1), the completed Phase J tranches follow them verbatim, under "Phase J — completed tranches"; their ids resolve there too.

## Phase K — Pointer-first re-plan (approved 2026-10-09)

> **Decision (the user, 2026-10-09; the rebuilt draft reviewed and committed 2026-10-15; record: [ADR-0001](adr/ADR-0001-pointer-first.md)).** TaxFill points an agent at the right official form, rule and figure. Packs stay for **high-volume, current-year forms only**: a PDF field name → printed line map cannot be derived safely at use time (the ME 1040ME 2023 pack had lines 21-23 rotated one box, and every relation still passed). Calc ops and relation verify stay. The new order:
> 0. let the running recovery wave finish re-creating and integrating its 23 packs (sunk cost: 6 had a pack on disk, 17 survived only as replay logs; KG1 applied to each — **done 2026-10-15, all 23 landed**), then **stop** TY2024-and-earlier state backfill and the rest of JS6 except on demand (see the on-demand rule under Deferred);
> 1. **release** (Phase A: PyPI, tag, `.mcpb`, demo, acceptance; user-held steps stay the user's);
> 2. **TY2026 readiness**: federal finals Dec-Feb (JT5g/JT6); JS7 cut down to the high-volume states (JS7a), with the rest using the fallback;
> 3. a **no-pack fallback fill path** for the long tail: introspect the official blank, anchor fields to printed labels, fill and verify at use time, label confidence honestly, and never claim filing-grade;
> 4. **slim the knowledge layer** to pointers, verbatim quotes and the figures calc ops read. Narrative duplicates official text and drifts: JS2c logged 25 mismatches, all in narrative or figures calc does not apply (ROADMAP JS2c; the applied figures are calc.py:10985-11019; `tax_line` and every `tax.notes` entry are still emitted in calc output at :11037-11042, so JK23/JK26 cover them);
> 5. the Not-scheduled backlog stays unchanged.
>
> This section supersedes Phase J's ordering rules 3-4 and its "Phased sequencing" for every open item. Rule 5 (the tranche contract) still applies. Synthesized from three read-only plans and two judges (2026-10-09, against 063f293).

**Commit rule (JK1).** The new docs/dev/ROADMAP.md lands in **one commit** with (a) the "Phase J — completed tranches" block appended to docs/dev/HISTORY.md and (b) docs/dev/adr/ADR-0001-pointer-first.md. Without (a) every DONE write-up leaves the repo and the pointer lines point at nothing; without (b) the Phase K header link is dead (test_doc_links.py).

**Tranche ids.** New tranches are spelled `JK<n>`. `test_every_open_roadmap_box_names_its_tranche` (packages/mcp-server/tests/test_readme_sync.py:98-117) only accepts `\bJ[A-Z]{1,2}(?:\d+[a-z]?|[a-z])\b` (:101), so `JK0` passes and a bare `K0` does not. Kept ids: JA1, JA2, JD2 (.3 only), JEe, JS2c, JT5g, JT6. JS7 becomes JS7a, with JS7b deferred. `JK0a` (a suffix letter) also passes.

**Guardrails** (each tranche below cites them):

| id | Guardrail |
|---|---|
| KG1 | Sunk cost is not a reason to ship. A recovery-wave pack that fails any JS5 gate (digest pin, vision audit, golden round trip, repo pack gates) is **dropped and listed**, not patched under time pressure. |
| KG2 | No silent wrong numbers. A known wrong-output defect outranks new coverage: the ME 1040ME 2023 lines 21-23 mis-bind (JK0a, fixed 2026-10-14), and the JF5a follow-ups (~$3,050 overstated in a repro; JK3 found both already fixed in dfe7dd8 and pinned them 2026-10-15). |
| KG3 | Honest health signal. The release is not cut while freshness is red, unless the red is quarantined with a written reason (scripts/freshness_quarantine.yaml). |
| KG4 | Every dated tranche has an automated trigger. Today JT5g and JS7 have none, and the finals cron stops 02-15 (.github/workflows/finals.yml:21). |
| KG5 | Unmapped output is **never** filing-grade. The fallback's `unmapped_draft` grade and its page stamp are unconditional: no flag, prompt or knowledge-pack state can lift them. The stamp is drawn into each page's content stream (flattened), not added as an annotation: today's rehearsal stamp is a pypdf FreeText annotation with no /F Print flag (filler.py:785-793; pypdf sets PRINT only on Highlight, annotations/_markup_annotations.py:302), so it does not print and any viewer can delete it. `provisional_marker` returns None for a jurisdiction with no pack (knowledge.py:2702-2712), so the grade must not depend on it. |
| KG6 | Safe before broad. Anchoring is benchmarked blind against ≥30 shipped packs before any confidence above "low" is emitted. "high" is allowed only where measured precision is ≥99%, and the ME 1040ME 2023 rotation is a mandatory case. The benchmark reports a per-form "any mis-anchored field" rate beside per-field precision, and the response says "anchored (unverified line map)", never a bare "high". The ground truth (the shipped packs' line maps) may itself hold rotations, so the ME case and every benchmark disagreement are adjudicated by a vision check before they count. If the benchmark fails, the fallback ships inspect + worksheet only (no PDF fill). |
| KG7 | No model arithmetic presented as computed. A fallback value no calc op produced is labeled "agent-computed, unverified". ReadOnly widgets and calculated widgets (an /AA /C calculate or /F format action, ReadOnly or not) are never filled; they are listed as "hand-write these". |
| KG8 | Output freeze **2026-12-01 → 2027-04-15**: no knowledge-schema change, and no change to the output shape of the pack path or of any knowledge consumer. Fixes to wrong values are still allowed. **Allowed:** additive, opt-in tool parameters and response fields that only the unmapped path uses (e.g. `form="unmapped"`, `source_url`, `grade`), provided the JK21 golden diff of every pack-path response is byte-identical. JK16/JK17 should still merge by 2026-11-30 where they can. |
| KG9 | User-held steps stay the user's: the PyPI publisher/token, the mcp<2 decision, the v0.1.0 tag and upload, the demo GIF, the acceptance tester, branch protection (JD2.3), the JT6 early-flip policy, the RI DOB rendering, and the DC exception named at docs/dev/ROADMAP.md:2507 ("any DC exception before 2026-10-15"; what it is was not found in the repo — the user confirms it or lets it lapse). |
| KG10 | Public repo: demo personas only. This covers the sample W-2, the journey goldens, benchmark fixtures and pilot forms. |
| KG11 | Refuse what cannot be anchored. In unmapped mode `fill_form` refuses any value whose target widget is anchored `none`, and `low` unless the user confirms that field on the rendered page (a per-field override recorded in the response). Refused fields come back as "hand-write these". |

**Collision order** for Dec 2026 – Mar 2027: JT6 > JS7a (+ JK10 label-adjacency guard) > the fallback (JK16-JK18) > the knowledge layer. Release support (JK7, JK12) takes the next free slot. A dated tranche never interrupts one in progress.

**Calendar** (latest starts; the RC date is under agent control, the upload date is the user's):

| Date | What |
|---|---|
| 2026-10-12 | weekly freshness run (freshness.yml:30); expected red on MA until JK2 |
| 2026-10-14 / 10-15 | **done:** JK0, JK0a, JK2, JK3, JK4, JA1 |
| 2026-10-15 | TY2025 extension deadline. v0.1 cannot meet it because JA2 is user-held, so its TY2025 audience is late filers, amended returns and rehearsal users |
| 2026-10-16 | JK1 (lands with the user's OK on this re-plan), JS2c close-out |
| 2026-10-21 / 10-23 | JK5 dry run / **release candidate ready**; the upload waits only on JA2 |
| 2026-11-02 … 11-30 | JK6, JK13-JK17, JK21 (by 11-05), JK20 (by 11-09), JK9 (by 11-16), JK8 (by 11-23; daily cron from 12-15), JK24 (by 11-24), JK10, JEe, JK22-JK23 (pre-freeze, zero-output) |
| 2026-12-01 | KG8 freeze begins; JK25 lands before this or not at all for TY2026 |
| 2026-12-15 | JK11 user decisions; first state 2026 blanks expected |
| 2027-01-05 | JT5g falls back into JT6 if no IRS NEC/OI draft has posted |
| 2027-02-01 | JK12 v0.2 (TY2026 season) |
| 2027-03-15 | finals cron ends (JK8); manual check for i1040gi and the 2027 Rev. Proc. |
| 2027-04-16 | KG8 ends; JK26 may start |

**At a glance** (S = hours, M = a day, L = days, XL = a week or more):

| # | Tranche | Size | Deps | External | Latest start |
|---|---|---|---|---|---|
| 0 | JK0 Recovery wave re-creates + integrates 23 packs | per pack | — | — | **done 2026-10-15** |
| 0a | JK0a ME 1040ME 2023 lines 21-23 re-bind (P-032) | S | — | — | **done 2026-10-14** |
| 1 | JS2c close-out | S | JK0 | — | 2026-10-16 |
| 2 | JK1 ROADMAP truth-up + backfill freeze | S | JK0, JS2c | other workflow idle | 2026-10-16 |
| 3 | JK2 Honest health signal (MA red, finals retry) | S–M | — | the 10-19 / 10-26 scheduled runs | **done 2026-10-15** |
| 4 | JK3 JF5a MFS follow-ups, verify first | S | — | — | **done 2026-10-15** |
| 5 | JK4 CI runner + action pins | S | — | — | **done 2026-10-15** |
| 6 | JA1 Phase A agent half (trimmed) | M–L | — | — | **done 2026-10-15** |
| 7 | JK5 Release-candidate dry run | M | JK1 (the rest done) | — | 2026-10-21 |
| 8 | JK6 Five journey goldens | M | JA1.3 | — | 2026-11-02 |
| 9 | JA2 Phase A user half (+ JD2.3) | user | JK5 | the user | user's call (RC 2026-10-23) |
| 10 | JK7 A6 flip + `.mcpb` on the release | S | JA2 upload | PyPI upload | upload + 1 day |
| 11 | JK13 Fallback surface + guardrail ADR | S | — | user may weigh in | 2026-11-02 |
| 12 | JK14 Introspect + pack-less fetch | M | JK13 | — | 2026-11-09 |
| 13 | JK15 Anchor + blind benchmark | L | JK14 | — | 2026-11-16 |
| 14 | JK21 Golden-diff harness over every tool | M | — | — | 2026-11-05 |
| 15 | JK20 Hoist citations into `sources` | M | JK0, JS2c, JK21 | — | 2026-11-09 |
| 16 | JK22 Drop never-read TY2025 blocks (zero-output) | M | JK20, JK21 | — | 2026-11-16 (must land by 11-30) |
| 17 | JK16 Pack-less fill | L | JK14, JK15 | — | 2026-11-23 |
| 18 | JK8 Watch coverage | M | JK2, JK9 (state rows) | — | 2026-11-23 |
| 19 | JK9 Tier-1 state triage table | S–M | JK0 | IRS SOI state data | 2026-11-16 |
| 20 | JK10 Label-adjacency guard (base pack + every port) | M | — | — | 2026-11-30 |
| 21 | JEe Text width vs widget padding | M | JK0 | the user: RI DOB choice | 2026-11-30 |
| 22 | JK17 Pack-less verify + grade label | M | JK16 | — | 2026-11-30 |
| 23 | JK23 Quote-verbatim checker (report mode) | M | — | — | 2026-11-30 |
| 24 | JK24 Schema v2 models + dual loader | M | JK20, JK21 | — | 2026-11-24 (else 2027-04-16) |
| 25 | JK25 2026 scaffold emits v2 (optional) | S | JK24, JK23 | — | lands by 2026-12-01 or skipped |
| 26 | JK18 Fallback skill text + evals | S–M | JK17, JK6 | — | 2026-12-07 |
| 27 | JK11 User decisions for JT6 | user | — | the user | 2026-12-15 |
| 28 | JT5g Schedule NEC / OI 2026 | M | JK8 | IRS drafts | drafts + 3 business days |
| 29 | JT6 Finals re-pin + flip + 2027 pack | L–XL | JK8, JK11 | IRS finals, 2027 Rev. Proc. | the day check_finals fires |
| 30 | JS7a TY2026 high-volume states | XL | JK9, JK10, JT6's f1040 re-pin | states' 2026 blanks | each blank's posting date |
| 31 | JK19 Fallback pilot on 5 long-tail forms | M | JK18 | — | 2027-01-11 |
| 32 | JK12 v0.2 release | S | JT6, first JS7a batch (fallback only if JK15 passed and the JK19 report exists) | the user pushes the tag | 2027-02-01 |
| 33 | JK26 TY2025 knowledge migration to v2 | XL | JK21-JK24, KG8 ends | — | 2027-04-16 (not before) |

### K-P0 — Land the sunk cost, then stop

- [x] **JK0 — The recovery wave re-creates and integrates 23 packs from its replay logs — DONE 2026-10-15** (three relaunches across two spend-limit stops)
  - All 23 landed, each through JS5's per-pack acceptance and an independent post-integration check: al24, al40nr23, az140nr23, az140py23, ca540_24, ca540nr_24, caschca540_24, caschca540nr_24, co24, de24, depitnon23, ia24, in24, ks24, md24, me24, mi24, mt24, mt25, ne24, ok24, vt24, wv24. None was dropped under KG1; the checks found only wording problems in ROADMAP bullets and banners (fixed as new commits).
  - Outcome: TY2025 state forms for **42/42** jurisdictions; TY2024 for **41/42** (MA is the deliberate exception: its current bytes have no Wayback capture and mass.gov refuses scripts); JS6 adds AL 40NR, AZ 140NR, AZ 140PY and DE PIT-NON 2023, leaving the three CT forms (deferred).
  - What the verifiers found beyond the packs: **P-027b** (filler: a NoView + Print pushbutton over half the visible page is a print lid — AL 40NR 2023's NOL-85A pages printed with the form body covered; 0 of 53,554 shipped widgets change verdict), the **MT Form 2 2025 line-10 zero floor** (a correct return with credits above the tax failed verify), and nine JS2c knowledge corrections (AL AZ CO DE IA MD MT VT WV). A relaunch bug (a chain whose verifiers all died counted as ready) was caught before it committed anything.
- [x] **JK0a — ME 1040ME 2023 lines 21-23: bind by printed row (P-032) — DONE 2026-10-14** (585eb77) — the 2023 pack binds lines 21-23 by position like the 2024 and 2025 ports; P-032 is in the pitfall registry, CONVENTIONS.md gains the bind-by-printed-row rule, and test_me1040_lines_21_23.py pins the (key, widget) map offline and reads the printed number beside each widget on every year's blank.
- **JS2c** (kept; its box is in Block 7). JK0's nine knowledge corrections landed 2026-10-15 (AL AZ CO DE IA MD MT VT WV, each re-checked against the cited booklet). Left: the MN 2025 line-11 caption (decision: no change, recorded). JK1 closes the box.
- [ ] **JK1 — ROADMAP truth-up and the backfill freeze** (S; deps JK0 committed and the other workflow idle; latest start 2026-10-16)
  - **Land the swap under the commit rule above:** the new ROADMAP, the "Phase J — completed tranches" block appended to docs/dev/HISTORY.md, and docs/dev/adr/ADR-0001-pointer-first.md, in one commit.
  - Re-derive every "Where we are" count from disk (sync_doc_counts / sync_test_count, then by hand for the unanchored ones: "35 ops" vs 40 pinned at packages/mcp-server/tests/test_skills_sync.py:54; the federal "111 packs"), using what JK0 actually landed.
  - Close the JS5, JS6, C2 and D2 boxes as "deferred (on demand, Phase K re-plan)", listing what is left. Move their DONE progress notes verbatim to HISTORY.md.
  - Already annotated in place on 2026-10-09 and **kept as they are** (historical text stays verbatim; nothing is removed): the "TY2024 leftovers fold into JS7" text (JS5's discovery bullet, the old→new map row J3, Phase J acceptance, Phased sequencing item 4), JT5g's "on the check_finals watchlist" (a correction sub-bullet), the JT5a "latest start 2026-11-16", and "the overlay filler exists (branch `phase-j2-overlay`)".
  - **Acceptance:** test_readme_sync green, with no open box lacking a J-style id. HISTORY.md holds no open box. Every [x] J-tranche id named in a ROADMAP "Done — moved verbatim" pointer line appears as a `- [x] **<id>` line in docs/dev/HISTORY.md. docs/dev/adr/ADR-0001-pointer-first.md exists and test_doc_links.py is green. Every row of the 2026-10-09 item ledger is placed in a tranche, deferred or dropped.

### K-R — Release v0.1 (priority 1; RC ready 2026-10-23)

- [x] **JK2 — Honest health signal before release — DONE 2026-10-15** (978fc2f) — the 2026-10-12 freshness run had two causes: the MN 2025 M1 booklet moved (its 14 citations re-pointed) and mass.gov plus its Wayback mirror refuse GitHub-hosted runners (the ten MA Form 1 network tests). `fetch._download` and `check_finals.head_status` now retry transient failures; freshness.yml caches the runner's blanks; the ten MA tests are quarantined until 2027-01-11, deleted after two green weekly runs. Acceptance pending only on the clock: the 2026-10-19 and 10-26 scheduled runs, then issue #3 closes.
- [x] **JK3 — JF5a's MFS follow-ups: verify first, then fix — DONE 2026-10-15** (e92812c) — both were already fixed in dfe7dd8 (JF5a, 2026-09-27); at its parent the same demo profiles showed the defects (-1,583 vs -29; a 3,047 spouse-return gap). test_estimate_p018_mfs.py pins both; a 102-profile comparison changed no figure.
- [x] **JK4 — Pin the CI runners and actions — DONE 2026-10-15** (c9e89ad) — ubuntu-24.04 in all eight jobs, actions/checkout and astral-sh/setup-uv pinned by commit SHA (setup-uv moved to the node24 v10.3.0), uv pinned to 0.13.0, and .github/dependabot.yml proposes the action bumps weekly.
- **JA1 — DONE 2026-10-15** in three parts (f2a3ec4 surfaces + runbook + derived smoke; 0cc6675 the TY2025 demo-persona W-2 and walkthrough; fe600f2 release.yml with Trusted Publishing, the .mcpb uv runtime, CHANGELOG), each through an adversarial verify and re-verify; its box moved to HISTORY.md with the other completed Phase J tranches. The Phase K changes it carried out:
  - JA1.2 drops `gen_manifest_tools.py` (scripts/sync_bundle_manifest.py and its test cover it).
  - JA1.3 targets **TY2025**: a demo-persona W-2 (SSN 999-88-xxxx, SAMPLE watermark), and ACCEPTANCE.md / DEMO.md move off 2023.
  - **Before any upload**, flip the pre-release wording in everything that ships inside a wheel or on its PyPI page, because both are immutable once v0.1.0 is uploaded: packages/mcp-server/README.md:9, :59 (the PyPI long_description, packages/mcp-server/pyproject.toml:7); packages/mcp-server/src/taxfill_mcp/__init__.py:20; packages/core/src/taxfill_core/__init__.py:5. Make the PyPI `description` count-free (packages/mcp-server/pyproject.toml:4 says "(23 tools)"; JA1.1/JA1.6 wanted count-free wording).
  - The release text says three things: TY2025 is the filing-grade year until JT6 flips TY2026; the 2026 packs are provisional; a form with no pack is refused today, and later gets an unmapped draft (KG5).
- [ ] **JK5 — Release-candidate dry run** (M; deps JK0, JK0a, JK1-JK4, JA1; latest start 2026-10-21)
  - Cut from a pushed, CI-green commit after the JK0 wave stops committing.
  - **Acceptance:** both wheels build. `uvx twine check dist/*` passes. The clean-venv smoke shows 23 tools and the derived pack counts. `mcpb validate` passes. An agent runs ACCEPTANCE.md end to end on the TY2025 demo persona (Form 1040 + one high-volume state). The A6 diff (JK7's file list) and the release notes are pre-drafted on a branch. `grep -rn -i "not on PyPI yet\|not yet published\|coming with v0.1\|IN DEVELOPMENT" packages` (PUBLISHING.md:146's grep, widened) is empty on the RC. This is a developer dry run, not the non-developer test.
- [ ] **JK6 — Five journey goldens** (M; deps JA1.3; latest start 2026-11-02) (KG10)
  - Scripted TY2025 runs through the MCP tools, demo personas only:
    1. a W-2 employee in a big state;
    2. an F-1 nonresident-alien student;
    3. a part-year mover;
    4. a city-tax filer (OH municipal / school district, MI city, NYC, PA local EIT);
    5. an amended prior-year return.
  - Each step records its path: **pack / fallback / pointer / refusal**. Journeys 3-5 assert the honest pointer or refusal today and are upgraded when JK16-JK18 land.
  - **Acceptance:** all five run in CI e2e. ACCEPTANCE.md walks journey 1. They become the test that no fallback output says filing-grade.
- **JA2** (kept; user-held, KG9). See the JA2 box in Block 6. The RC is ready 2026-10-23. Recommendation for the mcp<2 decision: ship v0.1 on the locked 1.x (uv.lock 1.28.0; latest 1.x 1.30.0, latest 2.x 2.3.0 on 2026-10-09) and plan 2.x afterwards. **JD2.3** (branch protection or a recorded real gate) is the user's, before the tag push or recorded as not adopted.
- [ ] **JK7 — A6: flip the repo-only pre-release wording after the upload** (S; deps the JA2 upload; latest start the day after)
  - Repo-only surfaces (the wheel- and PyPI-shipped ones flip in JA1, before the upload): README.md:5, :31-32; docs/USER_GUIDE.md:71, :182; docs/TOOLS.md:3 ("from source") and its `uv run taxfill` CLI note (:43-47; PUBLISHING.md:37 names it); .github/CONTRIBUTING.md:7-8, :141; the root pyproject.toml:4 comment; packages/mcp-server/bundle/README.md:56-59. Also embed docs/media/demo.gif (DEMO.md:6 says the README references it; it does not).
  - **Acceptance:** `uvx taxfill-mcp` works in a clean venv. `taxfill.mcpb` is attached to the GitHub release. PUBLISHING.md:146's grep, run over packages/ as well, is empty.

### K-T — TY2026 readiness (priority 2)

- [ ] **JK8 — Watches as triggers** (M; deps JK2's retry, JK9 for the state rows; latest start 2026-11-23, live before the 12-15 daily cron) (KG4)
  - Extend the finals cron from 02-15 (finals.yml:21) to **03-15**. The i1040gi precedent is 2026-02-25.
  - Watch by name: the irs-dft f1040nrn/f1040nro drafts (JT5g's trigger, still dated 2025-05-13 on 2026-10-09); the 2027 inflation Rev. Proc.; the five non-draft 2026 packs (f1040es, f8316, f843, f8833, fw7).
  - Add a state-blank watch for the JK9 tier-1 list (JS7a's trigger).
  - **Acceptance:** a dry run lists every new target. A planted 200 opens the issue. The cron covers October to 03-15. A manual check is booked for 2027-03-15.
- [ ] **JK9 — Tier-1 state triage table (replaces JS7's "re-triage every state")** (S–M; deps JK0; latest start 2026-11-16, so JK8's state rows are live by 11-23; external: IRS SOI state data)
  - Rank income-tax states by individual-return count from a cited IRS SOI table (the user's criterion: high volume). Pick about 12. The plans proposed CA, NY, IL, PA, OH, MI, GA, NC, NJ, VA, MA; the table decides.
  - **Recommendation for the user to accept or reject** (not part of the 2026-10-09 decision): weight the ranking toward where nonresident-alien students cluster. Without the user's yes, the ranking is volume only.
  - Per state, record:
    - the resident form;
    - the NR/PY form;
    - the amend route (a checkbox on the same form, or a separate X form such as IT-201-X or IL-1040-X);
    - whether the 2025 pack maps the amended checkbox (MO's `amendedTXT` is unmapped, JEa).
  - Pre-scaffold each state from its newest base (`--base newest`).
  - **Acceptance:** the table is committed with its volume citation, and the scaffolds are staged.
- [ ] **JK10 — Label-adjacency guard on the base pack and every port** (M; latest start 2026-11-30)
  - The real failures are in the **base** pack, not in a widget that moved between years: the ME 1040ME 2023 widget names are rotated against their printed captions and the 2024 and 2025 blanks carry the same names on the same rows (measured by the ME 1040ME 2024 port's verifier, 2026-10-04); AL Form 40 2023's keys were one number high and the relations matched (docs/dev/ROADMAP.md:2391, P-031). A name or /Rect diff between years reports these as unchanged and carries the mis-bind forward; today's triage diffs names only (scripts/scaffold_state_year.py:170-177).
  - Primary check: for every mapped widget, read the printed line number beside it and require it to equal the pack's line key. Generalise the existing per-form tests (packages/core/tests/test_al40_line_designators.py, P-031; the ME test from JK0a, P-032) into one gate. Run it on the base pack and on every port.
  - Secondary signal: `scaffold_state_year.py --triage` also diffs each widget's /Rect against the prior-year blank (`extract_fields` reads rects, packages/core/src/taxfill_core/packbuild.py:67-94); a moved widget forces a re-map.
  - **Acceptance:** two real base-pack rotations are caught: the ME 1040ME 2023 3-cycle (on 063f293's pack) and the AL 40 2023 one-high shift (on its pre-P-031 keys). It runs on every JS7a port and every on-demand port, and on the base pack each port starts from.
- **JEe** (kept; latest start 2026-11-30, before the 2026 maps are made; deps JK0 so the sweep covers the integrated packs). The user decides the RI dependent-DOB rendering (KG9).
- [ ] **JK11 — The user's JT6 decisions, ahead of the finals** (user; latest 2026-12-15) (KG9)
  - (a) Early flip with disclosed absences (`filing_grade_absent_blocks`) or a full flip only. (b) Whether a negative entry prints "(60,000)" where Pub 519 asks for parentheses (JT4c's finding, HISTORY.md).
  - **Acceptance:** both decisions are recorded in JT6.
- **JT5g** (kept): triggered by JK8. If no IRS 2026 Schedule NEC/OI draft has posted by **2027-01-05**, both packs are built from the finals inside JT6.
- **JT6** (kept; absorbs H5's Tax Table re-pin): deps JK8, JK11. Target: t-t4 on finals within 5 business days of the last required final.
- [ ] **JS7a — TY2026 state sprint, high-volume states only (replaces JS7's scope)** (XL, per pack; deps JK9, JK10, and JT6's f1040 re-pin for the federal base lines rather than all of JT6; external: each state's 2026 blank, Dec 2026 – Feb 2027)
  - **Per pack:** JS5's acceptance, the JK10 label-adjacency guard (on its base pack and the port), and the amended checkbox mapped where the state amends on the same form.
  - NR/PY packs only where a lineage exists and the state is tier-1 (CA 540NR + Schedule CA (540NR), NY IT-203).
  - Born v2 only if JK25 landed by 2026-12-01; otherwise v1. JS7a is never blocked on the knowledge layer.
  - **Acceptance:** each tier-1 resident pack ships within ~10 business days of its blank. The triage table row is updated.
- **JS7b** — every other state's TY2026 return: deferred (on demand, Phase K re-plan). Calc figures ship if the knowledge pack exists. The form goes through the fallback (JK13-JK18) as an unmapped draft and is never filing-grade. A pack is built on demand (the on-demand rule) or when volume justifies one. Exception: a state whose blanks come only from a pinned-only host cannot use the unpinned fallback fetch — today NM (fetch.py:88-95, refused at :335-340) — so it gets a refusal with a pointer, or a user-supplied local blank (JK14).
- [ ] **JK12 — v0.2 for the TY2026 season** (S; deps JT6, the first JS7a batch, and JK13-JK18 if ready; latest start 2027-02-01; external: the user pushes the tag)
  - The fallback's PDF fill ships in v0.2 only if JK15 passed and the JK19 pilot report exists; otherwise v0.2 ships inspect + worksheet only, or no fallback.
  - **Acceptance:** tag, PyPI and `.mcpb` are published. The CHANGELOG lists which forms are filing-grade and the fallback's LIMITS. The release notes say which tax year is filing-grade.

### K-F — No-pack fallback fill path (priority 3)

Every building block exists as a core or CLI authoring tool (fetch with sha256=None, extract_fields, sentinel_sweep, locate_labels, clipping_scan, widget_flag_problems). Rendering already runs at use time: `render_form(pdf_path)` is a shipped MCP tool that renders any PDF with no pack (packages/mcp-server/src/taxfill_mcp/server.py:410-424), so it serves the vision check as is. The others do not: every fill, verify and fetch tool starts from `_load_any_pack` (server.py:181-195). Prior art for label anchoring: packages/core/tests/test_al40_line_designators.py (P-031) reads the printed number beside every numbered page-1 widget, and JK0a's ME test does the same for P-032. The only no-pack guidance today is the skill's "fall back to `get_sources` + the official blank" (skills/claude/SKILL.md:180-182, :291-292).

- [ ] **JK13 — Surface and guardrail ADR** (S; **no deps**: it must not wait on the user-held release; latest start 2026-11-02)
  - Decide the MCP surface. Recommendation: ride the existing tools, `fetch_blank` / `fill_form` / `verify_form` / `get_form_map` with `form="unmapped"` + `source_url`, keeping **23 tools**. The overlay precedent is server.py:181-195 / test_overlay_tools.py:54. The cost is that pack and unmapped results share a schema, so `grade: "unmapped_draft"` must appear in **every** response, not only the summary.
  - The alternative is a 24th tool, which edits every hard-coded "23": ci.yml:115, test_cli.py:69/:78, test_server_e2e.py:19/:397, bundle/manifest.json, test_overlay_tools.py:54, docs/dev/PUBLISHING.md:89 and :135, docs/TOOLS.md:3, and packages/mcp-server/pyproject.toml:4 (the PyPI description; immutable once uploaded, which is why JA1 makes it count-free).
  - Riding the existing tools changes their input schema and response shape; KG8 allows it only as additive, opt-in, unmapped-only parameters and fields with the pack path byte-identical (JK21).
  - Write down the refusal rules: XFA-only or scanned pages; page-1 year or title not matching the request; a non-official host; ReadOnly or pushbutton targets.
  - **Acceptance:** ADR-0002 is committed under docs/dev/adr/ (ADR-0001 records this re-plan), and KG5-KG7 and KG11 are written into it.
- [ ] **JK14 — Introspect + pack-less fetch** (M; deps JK13; latest start 2026-11-09)
  - `extract_fields` reads /TU, the /Ff bits (ReadOnly, multiline, comb, pushbutton), /Ch + /Opt, the /DA size and /Q. Today every non-/Btn field is typed "text" (packbuild.py:88).
  - It also reads each widget's /AA actions: a /C (calculate) or /F (format) action marks the field as calculated, ReadOnly or not (KG7).
  - Fetch: official host only; sha256 recorded, not pinned; the page-1 printed year and title are read and checked; XFA-only and scanned blanks are detected and refused.
  - Today's fetch rules stand and are stated, not bypassed: a PINNED_ONLY host is refused without a pinned sha256 (fetch.py:88-95, :335-340; today NM's document API), and a Wayback mirror is used only digest-verified (fetch.py:224-225), so a host that answers 403 (mass.gov) cannot be served unpinned. For those the fallback returns a refusal with a pointer, or accepts a **user-supplied local blank** whose page-1 year/title check stands in for the pin.
  - Cache: with sha256=None today's fetch returns any cached file for the URL without re-downloading (fetch.py:352-354), and several state URLs are rotating "current" slots (IL-1040, OK 511; docs/dev/ROADMAP.md:2378, :2388). A pack-less fetch therefore force-refreshes (or records a digest per (url, fetched_at)), and the page-1 year/title check runs on a cached copy as well as on a fresh download.
  - **Acceptance:** unit tests per field type, checked against the 2025 pack blanks, including /AA detection on a 2025 pack blank with calculated totals. A wrong-year blank is refused, including a wrong-year blank already in the cache. A PINNED_ONLY host and a 403 host without a digest are refused with a pointer.
- [ ] **JK15 — Anchor + blind benchmark** (L; deps JK14; latest start 2026-11-16) (KG6)
  - Dump every text run with its box. Pair each widget with its nearest printed label (left or above, same row) plus the line-number token. Cross-check with /TU. Emit a per-field anchor confidence: high, med, low or none.
  - Run blind on **≥30 shipped packs**, federal and state, and compare each with the pack's line map. The ME 1040ME 2023 3-cycle (063f293's pack) and the AL 40 2023 one-high shift are mandatory cases and must be flagged; every disagreement with a pack is adjudicated by a vision check before the pack counts as ground truth.
  - **Acceptance:** the accuracy table is committed, with per-field precision **and** a per-form "any mis-anchored field" rate. "high" is emitted only where measured per-field precision is ≥99%, and the response wording is "anchored (unverified line map)". If precision is lower, JK16 is skipped and the fallback ships inspect + worksheet only.
- [ ] **JK16 — Pack-less fill** (L; deps JK14, JK15; latest start 2026-11-23)
  - Keyed by qualified field name. It refuses ReadOnly, pushbutton, viewer-guard and calculated (/AA) widgets and returns them as "hand-write these" (KG7). It refuses any value whose target widget is anchored `none`, and `low` unless the user confirmed that field on the rendered page (KG11). It enforces /MaxLen and the comb bit. Whole-dollar rendering applies only to fields the caller marks as money.
  - Every page gets the stamp "UNMAPPED DRAFT — NOT FILING-GRADE", **drawn into the page content stream** (flattened), not an annotation. The rehearsal stamp it was to reuse (packages/core/src/taxfill_core/filler.py:785-793) is a pypdf FreeText annotation with no /F Print flag (filler.py sets F_PRINT only on written widgets, :525-528), so it does not print and can be deleted in a viewer; check and fix the rehearsal stamp the same way. A values worksheet comes with it.
  - The response carries `status: "unverified_draft"` and an explicit next step (verify_form, then render_form on every page) until JK17's verify has run on that output.
  - **Acceptance:** e2e on 3 demo forms. The stamp cannot be turned off. The print path is rasterised and the stamp is OCR-read on every page. A planted unanchorable widget and a calculated-total widget are refused and listed as "hand-write these".
- [ ] **JK17 — Pack-less verify + grade label** (M; deps JK16; latest start 2026-11-30) (KG5)
  - Checks: a round trip of exactly the written names; regression_diff against the fetched blank (nothing else changed); clipping_scan; widget_flag_problems (P-027); optional agent-declared relations, keyed on the agent's own anchors and labeled so.
  - Returns an explicit LIMITS list on the OVERLAY_VERDICT_LIMITS model (packages/core/src/taxfill_core/overlay.py:219-230): no line map, no relations of record, no identity or cross_form checks, no P-003, and no revision pin.
  - The `unmapped_draft` grade is unconditional, including for jurisdictions with no knowledge pack.
  - Verify fails when any page lacks the content-stream stamp. A pass returns a `verified_at` token bound to the output file's sha256; any later change to the file voids it.
  - **Acceptance:** no code path returns filing-grade for an unmapped form. `ok: true` never implies filing-grade. A stamp-stripped page fails verify.
- [ ] **JK18 — Fallback skill text + evals** (S–M; deps JK17, JK6; latest start 2026-12-07)
  - Replace the no-pack guidance in all three synced skill files (packages/mcp-server/tests/test_skills_sync.py:31-35): skills/claude/SKILL.md:180-182 and :291-292, skills/codex/AGENTS.md:136 ("cannot be filled"), and skills/copilot/instructions.md:96. The agent says up front that no pack exists, renders and vision-checks every page, keeps the draft label, and labels any line it computed itself.
  - **Acceptance:** the skill sync tests are green for all three files. Evals pass, including the refusal when a user asks "is this ready to file?", and an assertion that the agent never says "done" or "complete" before verify_form has run on that output's sha256. Journey goldens 3-5 are upgraded from refusal to a labeled draft.
- [ ] **JK19 — Pilot 5 long-tail forms** (M; deps JK18; latest start 2027-01-11)
  - Candidates: a city return, a rare federal schedule, a CT nonresident form, one TY2023 state form, and one non-tier-1 TY2025 state form from an official host. MA Form 1 2024 is the **refusal case**: mass.gov answers 403 and a mirror is served only digest-verified (fetch.py:224-225), so the pilot checks that the fallback refuses it with a pointer (or takes a user-supplied blank). Publish per-form results.
  - **Acceptance:** a pilot report exists. No form is promoted to filing-grade without a real pack. Any change to the stamp or label policy needs the pilot data and a user decision.

### K-K — Slim the knowledge layer (priority 4)

What the code reads: calc applies roughly 4% of state bytes and ~11% of federal leaf bytes. About 1.2 MB of state prose is read by nothing at runtime. All 25 JS2c mismatches sat in narrative, pointer labels or non-applied figures (2026-10-09 survey of main @ 063f293). Before 12-01 only **zero-output** work happens. The schema migration of TY2025 waits until after 2027-04-15 (KG8).

- [ ] **JK21 — Golden-diff harness** (M; latest start 2026-11-05)
  - Snapshot the output of every MCP tool that reads state knowledge (state_tax via calc.py, state_scope via statescope.py, file_and_pay, filing_summary, and get_sources through sources_states.yaml, sources.py:107-112) over every jurisdiction and year. The residency tool is not included: it calls `_classify` only (server.py:1041-1078) and residency.py reads no state knowledge.
  - Add the missing TY2025 pins now: the OH $342.00 / $2,394.32 discontinuity (knowledge/states/oh/2025.yaml:293-303; no test pins "342.00" today), AZ Line 49 and the IL IL-E/EIC caveats for 2025. The existing pins test TY2023 only (packages/core/tests/test_state_knowledge.py:411-414 asserts OH 2023's "360.69"; :298 is AZ 2023; :319-324 is IL 2023).
  - **Acceptance:** the harness runs in CI. It is the gate for JK20, JK22, JK24 and JK26.
- [ ] **JK20 — Hoist citations into a `sources` table** (M; deps JK0, JS2c, JK21; latest start 2026-11-09, after JK21's 11-05)
  - scripts/assemble_state_sources.py:37-50 reads `sources` ids, so a citation outlives the block that carried it. Regenerate sources_states.yaml.
  - **Acceptance:** the test_sources.py:330 byte-equality holds. get_sources' state coverage does not shrink. The JK21 diff is otherwise byte-identical.
- [ ] **JK22 — Drop never-read blocks from the TY2025 state packs** (M; deps JK20, JK21; latest start 2026-11-16, **must land by 2026-11-30**, else it resumes 2027-04-16)
  - Drop: residency, filing_requirement, starts_from, credit amounts/limits, and the TY2025 YAML header comments (~107 KB: 106,611 bytes of `^#` lines in knowledge/states/*/2025.yaml; 214 KB is the TY2023-2025 total; their provenance moves to git history). Only what the JK21 diff proves unread. Credit eligibility prose is read by state_scope (statescope.py:201-203), so it waits for JK26.
  - **Acceptance:** the JK21 diff is byte-identical, apart from get_sources, which must not shrink. The suite is green.
- [ ] **JK23 — Quote-verbatim checker** (M; latest start 2026-11-30)
  - Check quoted spans against cached source text keyed by url + sha256 (the check_drift.py pattern). Run it in **report mode** over the quotes in tax.notes and form_lines. Mismatches go to JS2c.
  - **Acceptance:** CI runs it in report mode, and a seeded paraphrase is reported.
- [ ] **JK24 — Schema v2 models + dual-version loader** (M; deps JK20, JK21; latest start 2026-11-24; if not merged by 2026-11-30 it slips to 2027-04-16, KG8)
  - Quote/SourceRef models, generalising FormLineEntry (packages/core/src/taxfill_core/knowledge.py:2094). StateKnowledge v2 (typed sources, base_line, caveats, treaty, pointer-only credits, law_changes with quotes, logistics, gaps; a ~400-char quote cap). TY2023/2024 are frozen as v1; the single-version loader at knowledge.py:3143-3190 (`load_state_knowledge`) becomes dual-version. No dual loader exists today.
  - **Acceptance:** both shapes load, and the JK21 diff is byte-identical. No consumer changes.
- [ ] **JK25 — The 2026 state scaffold emits v2** (S; deps JK24, JK23; lands **by 2026-12-01 or is skipped for TY2026**)
  - **Acceptance:** a v2 scaffold validates and passes JK23. If it is late, JS7a ships v1 and migrates with JK26.
- [ ] **JK26 — Migrate TY2025 to v2** (XL; deps JK21-JK24 and the end of KG8; **starts no earlier than 2027-04-16**; done before TY2027 state work, ~2027-10)
  - Triage the 486 TY2025 tax.notes into base_line, typed caveats or dropped diaries, with a two-verifier wave and a per-state diff the user can review. tax.notes is "Cited disclosures/quirks the calc op must surface" (knowledge.py:2978-2981) and state_tax prints every one (calc.py:11037), so the user's "keep every figure a calc op reads" includes the disclosures the op must surface: every note naming a not-modeled add-on, surcharge, recapture or form-computed amount survives as a typed caveat that state_tax still prints. The OH $342.00 discontinuity, AZ Line 49 and the IL IL-E/EIC caveats must survive, guarded by the TY2025 pins JK21 adds (the existing pins, test_state_knowledge.py:411-414, :298, :319-324, are TY2023).
  - Rewrite the consumers: calc.py:11021-11040, statescope.py:196-254, file_and_pay.py:938-966, filing_summary.py:270-280. Rewrite the narrative-pinning tests (test_state_knowledge.py:96-131, :219, :298, :324, :397, :414, :431; test_statescope.py:108-220; the test_state_law_change_sweep.py:36 count). JK23 becomes enforcing.
  - **Acceptance:** the state_tax golden is defined as the tax figure plus the set of calc-surfaced caveats, and every one is unchanged (the work string's wording may change). state_scope still names each credit with its line and link. The registry loses no URL.

### Deferred (on demand, Phase K re-plan)

**On-demand rule.** A deferred pack (any TY2024-or-earlier state form, any JS6/C2 NR/PY form outside tier 1, any JS7b state) is opened only on an explicit request from the user or a filed GitHub issue naming the form and the tax year. Amendment eligibility alone is never a request. The request gets its own JK-style tranche id in this file. The pack must pass JS5's per-pack acceptance, the JK10 label-adjacency guard and KG1 before it ships. Until it lands, the fallback serves the form as a labeled draft (or refuses it, per JK14's host rules).

- **JS5 remainder:** MA Form 1 2024 (no Wayback capture of the current bytes; the fallback refuses it too, JK19); any JK0 pack dropped under KG1 or missing the 2026-10-23 cut-off; the remaining ~20 old-year re-maps and ~26 URL-discovery tasks. The fallback (JK13-JK18) covers them, where JK14's host rules allow, until a user asks for a pack.
- **JS6 remainder:** the three CT nonresident / part-year forms (overlay or hand-fill), any JS6 row JK0 drops, and the part-year allocation golden (it ships with the first on-demand NR/PY pack).
- **C2:** folded into the JS6 deferral. Tier-1 NR/PY forms with a lineage are in JS7a.
- **D2:** closed after JK0; any further old year is on demand.
- **JS7b:** non-tier-1 TY2026 states.
- **A part-year income allocation calc op** (no such op is found in calc.py). Until it exists, the fallback labels allocation lines as agent-computed.
- **Local-collector pointer table and NYC rate-schedule op:** proposed by the user-journey plan and not adopted, because the user asked to slim the knowledge layer and not grow it. Journey 4 relies on the fallback plus get_sources.
- **mcp 2.x migration:** follows the user's JA2 decision. Do it after v0.1 and before v0.2 if the 1.x line stops getting fixes.
- **Federal knowledge trim** (comments, filing_thresholds prose, effective_law_changes prose, tax.salt_cap): federal is already ~93% read.
- **Not scheduled** (priority 5): unchanged; see the end of Phase J.

### Dropped

- Folding the TY2024 leftovers into JS7 (old→new map row J3; JS5's discovery bullet; Phased sequencing item 4). Replaced by the backfill freeze.
- JS5's "resume discovery for the 20 never-started states plus OK, MA and NE": its old-year purpose is gone.
- JA1.2's `scripts/gen_manifest_tools.py`: moot, because scripts/sync_bundle_manifest.py and its test exist (bundle/README.md:18-20).
- JA1's stale sub-claims ("asserts 22 tools (:83)", "the runtime has 32 ops", "2.2.0 is the latest"): PUBLISHING.md:89 is `== 23`, the op count is 40, and upstream is 2.3.0 / 1.30.0.
- JS7's "re-triage every state": replaced by JK9 + JS7a + the fallback.

**Acceptance (phase):**
- v0.1 is installable from PyPI and as a `.mcpb`. A non-developer passes ACCEPTANCE on TY2025.
- TY2026 federal forms are filing-grade within 5 business days of the last required final. Every tier-1 state ships within ~10 business days of its blank.
- An unmapped form fills only as a stamped (content-stream), labeled draft, refuses unanchorable fields, and has a measured anchor precision behind every "anchored".
- Between 2026-12-01 and 2027-04-15 no pack-path or knowledge-consumer output shape changes (KG8; additive unmapped-only fields excepted). After JK26, state narrative is quotes that a checker holds to the source.
- No open box in this file lacks a J-style id. Every item in the 2026-10-09 ledger has a home.

---

## Phase A — Ship v0.1 (Effort: S–M, ~1–2 weeks; the real gate)

> Nothing is installable by a normal user until this lands. **No code blockers** —
> this is pure launch execution. The one external dependency is **maintainer PyPI
> credentials**. Runbooks already written: [`docs/dev/PUBLISHING.md`](PUBLISHING.md),
> [`docs/dev/ACCEPTANCE.md`](ACCEPTANCE.md), [`docs/dev/DEMO.md`](DEMO.md).

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
      **Phase K (2026-10-09):** JA1 → JK5 (release-candidate dry run, RC 2026-10-23) → JA2 (the user) →
      JK7 (A6). Recommendation for the mcp<2 decision: ship v0.1 on the locked 1.x (uv.lock 1.28.0).
- [ ] **A2 — Tag the release.** → Phase J **JA1** (agent half) / **JA2** (user half). `git tag v0.1.0` + GitHub release notes.
      **Phase K (2026-10-09):** JK5 → JA2 → JK7.
- [~] **A3 — Build the `.mcpb` one-click bundle.** → Phase J **JA1** (agent half) / **JA2** (user half). **Manifest finalized (2026-06-28):**
      dropped the `$schema_note` draft marker, added `server.entry_point`, removed the
      now-unschema'd `permissions` block — `mcpb validate` **PASSES**. Only `mcpb pack`
      → `taxfill.mcpb` remains, and it is **publish-gated** (the bundle launches
      `uvx taxfill-mcp`, which only resolves after A1). Primary path for non-technical
      Claude Desktop users.
      **Phase K (2026-10-09):** JK5 → JA2 → JK7.
- [ ] **A4 — Record the 60-second demo GIF** → Phase J **JA1** (agent half) / **JA2** (user half). per `docs/dev/DEMO.md` (storyboard +
      6 beats already written) → `docs/media/demo.gif`; embed in README.
      **Phase K (2026-10-09):** JK5 → JA2 → JK7.
- [ ] **A5 — Run the 20-minute non-developer acceptance test** → Phase J **JA1** (agent half) / **JA2** (user half). (`docs/dev/ACCEPTANCE.md`)
      on a clean machine; fix whatever blocks a non-technical user.
      **Phase K (2026-10-09):** JK5 → JA2 → JK7.
- [ ] **A6 — Flip README** → Phase J **JA1** (agent half) / **JA2** (user half). "not yet on PyPI / bundle coming" language to shipped.
      **Phase K (2026-10-09):** JA1 flips the PyPI-shipped READMEs before the upload; JK7 flips the repo-only surfaces after it.

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

*(Phase K note 2026-10-09: stale since 2026-10-02 — CO DR 0104PN 2023 and AR1000NR 2023 ship too, and the Phase K JK0 recovery wave is re-creating AL 40NR, AZ 140NR, AZ 140PY and DE PIT-NON 2023.)*

- [ ] Add the separate nonresident/part-year return for each state that has one
      (IL Schedule NR, OH IT NRC, PA part-year, etc.) + the adjustment schedule.
      → Phase J **JS6** (9 discovery rows with url+sha256 recovered from the 2026-09-11 run).
      → **deferred (on demand, Phase K re-plan)** once Phase K JK0 lands; JK1 closes this box. Long-tail
      NR/PY forms use the no-pack fallback (JK13–JK18); tier-1 NR/PY forms with a pack lineage are in JS7a.

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
      TY2023-only**: 130 packs across TY2023 (48) / TY2024 (41) / TY2025 (41), so
      **42 of the 42 jurisdictions** can fill a post-2023 year —
      TY2024 for **41** (AL, AR, AZ, CA, CO, CT, DC, DE, GA, HI, IA, ID, IL, IN, KS, KY, LA, MD, ME, MI, MN, MO, MS, MT, NC, ND, NE, NJ, NM, NY, OH, OK, OR, PA, RI, SC, UT, VA, VT, WI, WV) and TY2025 for **42** (AL, AR, AZ, CA, CO, CT, DC, DE, GA, HI, IA, ID, IL, IN, KS, KY, LA, MA, MD, ME, MI, MN, MO, MS, MT, NC, ND, NE, NJ, NM, NY, OH, OK, OR, PA, RI, SC, UT, VA, VT, WI, WV). For the
      other **0**, a 2024/2025 return still computes but cannot be filled.
      Federal spans
      2019–2025 for forms and 2019–2026 for knowledge (the TY2025 OBBBA set, 13 packs
      incl. the new Schedule 1-A, + knowledge/federal/2025.yaml shipped 2026-07-25;
      the provisional 2026 planning pack shipped 2026-08-04).
      **Remaining:** (a) the rest of the 2024→2025 **state form pack** tranche — 46
      packs/year. The pipeline half is ready (2026-08-10):
      `scripts/scaffold_state_year.py` + `docs/dev/CONTRIBUTING-PACKS.md`.
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
      **Phase K (2026-10-09):** the TY2024 (and MT 2025) packs the recovery wave re-creates land in **JK0**;
      every other old-year re-map / URL-discovery row is **deferred (on demand, Phase K re-plan)**, and
      JK1 closes this box.
- [x] Community pack-contribution pipeline — **DONE 2026-08-10**:
      [`docs/dev/CONTRIBUTING-PACKS.md`](CONTRIBUTING-PACKS.md) documents the full
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
      [`INTAKE_WORKSHEET.md`](../INTAKE_WORKSHEET.md), shipped inside the wheel as
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
      **Phase K:** the 2026 Tax Table final re-pin is part of JT6 (K-T lane).
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
        exactly-N test, test_cli, ci.yml packaging, packages/mcp-server/bundle/manifest.json —
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

> **2026-10-09:** Phase K replaces ordering rules 3–4 and the "Phased sequencing" section for every open
> item; rule 5 (the tranche contract) still applies. The completed tranches below moved verbatim to
> [HISTORY.md](HISTORY.md) in the same commit that lands this ROADMAP (Phase K JK1); each block keeps its open
> tranches and a pointer line.

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
| J3 state 2024/2025 remainder (73 pack-years, not ~66) | JS3a/b (scaffold + cheap ports incl. UT 2025) + JS5 (re-maps / URL-dead); TY2024 leftovers fold into JS7 (dropped 2026-10-09: Phase K stops old-year backfill) |
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

- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* J0.

### Block 1 — Federal filing-wrong and silent defects

- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JF6a, JF1a, JF5a, JF5b, JF1b, JF2, JF3, JF4.

### Block 2 — Paycheck-dated decision ops

- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JP1a, JP2.

### Block 3 — The retirement block

- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JR1, JR2a, JR2b, JR2c, JR3a, JR3b, JR3c.

### Block 4 — The TY2026 foundation (dated)

- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JT0a, JT0b, JT0c, JT3a–d, JF6b, JF6c, JF7, JF8, JF9, JT1a, JT1b, JT1c, JT1d, JT1e, JT1d+, JT2a, JT2b, JT4a, JT4b, JT4c.
- [ ] **JT5a–g — Wave B: the rest of the federal set for 2026** (JT5a **latest start 2026-11-16**; deps JT3a; each sub-tranche commits per pack) [TY26-21]
  - *(Phase K note 2026-10-09: JT5a–f are done and moved to HISTORY.md; only JT5g is open, triggered by JK8. The "JT5a latest start 2026-11-16" above is historical.)*
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
    - **Correction 2026-10-09:** the f1040nrn/nro drafts are not on the check_finals watchlist — the dry run watched 34 URLs, neither stem. → Phase K **JK8** adds the watch; if no draft posts by 2027-01-05, both packs are built from the finals inside JT6.
  - **Acceptance:** as JT3.
  - **Port rule (found in JF8):** calc.py prints ~330 worksheet and form line literals for forms outside the form_lines registry (Schedule SE, Form 8962, Form 8863, the QDCG and Social Security worksheets, ...), each true for the year it was read. Each Wave B port greps calc.py for its form's literals and moves any that differ onto form_lines.

### Block 5 — Remaining decision ops

- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JP1b, JP1c, JP5a, JP5b, JP3a, JP3b, JP4, JR4a, JR4b, JP5c.

### Block 6 — Docs, release, debt

- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JD1, JA1.
- [ ] **JA2 — Phase A, the user half** (external: the user) [G20]
  - The user:
    - creates a PyPI account with 2FA and a Trusted Publisher (or pending publisher) for taxfill-core and taxfill-mcp, bound to release.yml — or provides a token (both names were free on PyPI and TestPyPI on 2026-09-23);
    - decides mcp<2;
    - approves and pushes the v0.1.0 tag (the irreversible upload);
    - records the demo GIF;
    - recruits a non-developer ACCEPTANCE tester;
    - makes any branch-protection change.
  - Then an agent does A6.
  - **Phase K:** the RC is ready 2026-10-23 (JK5); JD2.3 before the tag push; A6 = JK7 (Phase K KG9: every step above stays the user's).
- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JK4, JK2, JEa, JEb, JEc, JEd.
- [ ] **JEe — Text width vs the widget's inner padding** (M; found by the JS5 RI-1040 2025 port's fixer, 2026-10-02)
  - *Found.* verify's width check passes a value when `len × advance × size <= rect width` (Courier 0.6 em). Render
    probes on RI-1040 2025 show the last glyph clipped when the value fills the rect exactly — the widget's inner
    padding (about 2 pt: border plus the viewer's inset) is not counted. An exact-fill value therefore passes verify
    and still prints cut off.
  - *Plan.* Subtract the padding the widget actually draws (its /MK border width plus PDF viewers' standard 1-2 pt
    inset) before the width test; re-run the repo-wide maxlen and verify sweeps; tighten every pack maxlen that only
    fit at exact width (TIGHTER_THAN_WIDGET rows where a widget /MaxLen exists). RI's dependent date-of-birth boxes
    (no 8-digit MMDDYYYY renders whole) need a product decision in the same pass: MMDDYY, a smaller font, or a
    documented clip.
  - **Phase K:** K-T lane, latest start 2026-11-30 (before the 2026 maps are made); the sweep covers the JK0 packs; the RI DOB rendering is the user's call.
- [~] **JD2 — Process: derived counts, suite speed, branches, ROADMAP shape — AGENT HALF DONE 2026-09-28** (M; deps JD1)
  - *As built:*
    - **(1)** scripts/sync_doc_counts.py derives the tool / op / DocSpec / pack counts and rewrites 16 anchors: README, SKILL.md, DEV_PLAN, both package READMEs, PUBLISHING.md's smoke assert, and the two PyPI descriptions. It found the descriptions still at "21 calculation ops" / "22 tools" and the server README at "21 deterministic ops" (JA1.1's list).
      - `--check` runs in CI and in test_readme_sync. scripts/sync_test_count.py stays the test-count entrypoint.
    - **(2)** load_pack memoizes on (path, mtime, size) and hands every caller a deep copy (parse 65 ms vs copy 3 ms on MO-1040). list_forms narrows its glob to `<jurisdiction>/<year>/`.
      - list_forms('federal', 2025): 3.0 s → 13 ms warm (0.38 s cold), with a perf guard.
      - pytest-xdist is a dev dependency, and CI runs the offline suite with `-n auto`: locally 9.5 min on `-n 10`, beside another suite (single-process ~25 min).
    - **(5)** the completed phases (0, E, F, G, I) moved verbatim to docs/HISTORY.md (now docs/dev/HISTORY.md), and every open box names its Phase J tranche (26 boxes, test_every_open_roadmap_box_names_its_tranche). Closed on the way: Phase E's SSN-maxlen box (JEa); A2–A6 now point at JA1/JA2.
    - **(4, local half)** the 17 merged local branches are pruned (`git branch -d`).
    - **(4) done 2026-09-28.** The parked `phase-j2-overlay` is recorded as merged (8945e30, `-s ours`; its code landed by hand in JS4a) and deleted, with the user's OK. `git fetch --prune` shows the 10 remote duplicates are already gone, so `git branch -r --no-merged origin/main` is empty. No stray worktree is left.
  - **Waiting on the user:**
    - (3) the real merge gate / branch protection.
    - **Phase K:** JD2.3 stays user-held (KG9): before the JA2 tag push, or recorded as not adopted.
  1. **Derived counts** [G15]. New `scripts/sync_doc_counts.py`, keeping the sync_test_count entrypoint: tools, ops, DocSpecs, packs, hand-fill packs and the ReadOnly total. It rewrites anchors, runs `--check` in CI, and regex-asserts the pyproject descriptions.
  2. **Suite speed** [G25]. About 5.6 min locally and 10.2 min in CI (run 33118033631); two property tests take 48.8 s and 45.3 s; list_forms parses 172 packs per call (~3.1 s; discovery.py:142-147).
     - Pre-filter by path and memoize load_pack on (path, mtime).
     - Run pytest-xdist `-n auto` in CI, keeping the property tests seed-deterministic.
  3. **The real merge gate** [G07]. Record the real gate, or enable branch protection — the user's decision.
  4. **Git hygiene** [G27]. Prune the 17 merged local branches, the 10 remote duplicates (all patch-equivalent to main) and a stale temporary worktree. Remote deletes need the user's OK.
  5. **ROADMAP shape** [G33]. Split it into OPEN WORK and docs/HISTORY.md (now docs/dev/HISTORY.md), and add a CI check that every open box names its tranche.
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
  - **Phase K (2026-10-09):** deps JK8 (the watch, cron extended to 03-15) and JK11 (the user's early-flip and "(60,000)" decisions; the latter is JT4c's finding, now in HISTORY.md). Absorbs H5's Tax Table re-pin and JT1c's Schedule 3-A re-verify. JT5g folds in if its drafts never post. JS7a waits only on the f1040 re-pin.

### Block 7 — State (federal-first; starts after the federal lanes)

- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JS1a, JS1b, JS2, JS2b.
- [~] **JS2c — Knowledge corrections the JS5 ports surfaced** (S–M, per pack; added 2026-10-01). Every port's verifiers compare the figures and captions the face prints with the year's knowledge pack and report mismatches; each is re-read at the pack's own cited source before it is changed.
  - *Done 2026-10-01 (GA, OH, MO):* GA 2025's IND-CR 202 rate is 50% (the 2025 IT-511 booklet and the IND-CR 202 face both print "Georgia allowable rate 50%"; the pack said 30%, the 2024 rate), line 19 is the "Georgia Eligible Itemizer Tax Credit" (the booklet's own name), and the 525-TV voucher's PO Box 740323 address is recorded under payment; OH 2025's `payment.web_pay_url` is tax.ohio.gov/pay (printed twice on the face; OH|TAX is the portal) and the Ohio Nonresident Statement checkbox is no longer described as new (the 2023 and 2024 faces print the same row; what ended is form IT NRS); MO 2025 no longer claims the MO-TC / MO-PTS lines were renumbered from 2024 (both faces print 42 / 43); LA 2025's child-care credit is carried to Line 21 (the +1 renumbering; the pack said 2024's Line 20) and its header no longer says lines 6A / 6B were removed (6A survives as the age designation, 6B as the dependents count). `sources_states.yaml` regenerated.
  - *Done 2026-10-01 (DE, VT):* DE 2025 said a NEW line 39 (capital gains tax payments) pushed the settle-up lines down by one and that the 2025 numbers were "one higher than 2024's" — the 2024 blank (Revision 20240821) already prints the same numbering, and line 39 is 2023's line 38: the +1 against 2023 came with the 2024 revision's inserted line 16 (Active Labor Organization Dues), restated in the header, the tax block, the law-changes note and the citation; the payment ZIP+4 is 19899-0508 as the form's own mailing boxes print it (the Instructions' Step 5 table drops the leading zero). VT 2025's base-guidance note cited federal Form 1040 "Line 11" where the 2025 IN-111 face prints "Line 11a"; and neither VT pack described two IN-111 face items that date from the TY2024 form — the Line 21 Child Care Contribution (Act 76 of 2023, 32 V.S.A. chapter 246: 0.11% of Vermont self-employment income per the 2025 worksheet, the 2024 half-year exclusion gone, no cap — quoted from the 2025 IN-111 Instructions p. 8, GB-1326 and § 10553) and the FARMER / FISHERMAN box (26 U.S.C. § 6654(i)(2), Instructions p. 6; the booklet says only to check it), now in both years' `tax.notes`; `knowledge/sources_states.yaml` regenerated.
  - *Done 2026-10-01 (CT):* the CT-1040 2025 port found three face items the 2025 knowledge pack never described — Line 20d Historic Homes Rehabilitation Tax Credit (the DECD voucher amount, summed into the Line 21 refundable total; no statute, cap or computation printed), the Line 48d ABLE subtraction (the lesser of the year's contributions or $5,000 / $10,000 joint and qualifying surviving spouse) and the page-1 Access Health CT box (an authorization to transmit demographic information, no tax effect) — now a credit entry and two `tax.notes`, quoted verbatim from the 2025 CT-1040 Instructions (Rev. 12/25, pp. 2, 4, 10), with Line 1's "Line 11a" and Line 13's "Schedule CT-IT Credit, Part 1, Line 10" citations.
  - *Done 2026-10-01 (WI):* the WI Form 1 2025 port's verifier found the knowledge pack named the new line 15 blind worker transportation services credit without its printed rate — now quoted ("Qualifying expenses .00 x 50% = 15"; "credit for 50% of the expenses paid. The credit may not exceed $1,500 ($3,000 of expenses) per qualifying person") — and omitted line 25's ".00 x .33" penalty factor ("Multiply the amount filled in by .33 (33%)") and that the face's "line 11" federal AGI citation is the TY2025 Form 1040's line 11a; three `tax.notes` entries.
  - *Done 2026-10-01 (CT 2024):* the same two items the CT-1040 2024 port found missing from the 2024 pack — Line 20d Historic Homes Rehabilitation Tax Credit (new on the 2024 face) and the Line 48d ABLE subtraction — plus the page-1 Access Health CT authorization and Line 13's "Part 1, Line 10" citation, quoted verbatim from the 2024 CT-1040 Instructions (Rev. 01/25, pp. 2, 4, 10; the text matches 2025's).
  - *Done 2026-10-01 (WV):* the WV IT-140 2025 manifest's verifier found six `citation.source` strings in wv/2025 that still read "2024 personal income tax Forms & Instructions" while their url is the 2025 booklet (wording only — every figure agrees), and the rounding tip cited at "p.14" where the 2025 booklet prints the Tips on Filing a Paper Return on printed page 16 (PDF page 18); both fixed.
  - *Done 2026-10-01 (CA):* the Schedule CA (540) 2025 port's verifiers noted three figures the 2025 face prints that ca/2025 never recorded (absent, not contradicted) — Part II line 5e's state-and-local-tax cap "the smaller of line 5d or $40,000 ($20,000 if married filing separately)" (2023: $10,000 / $5,000), line 3's 7.5% medical floor and line 24's 2% miscellaneous floor — plus lines 2 / 23's "line 11b" federal citation; one `tax.notes` entry quoting the face.
  - *Done 2026-10-01 (IL):* il/2025's `treaty_note` and `starts_from` attributed the Instructions' Step 2 Line 1 wording ("Adjusted gross income — Enter the adjusted gross income from your federal return") to the form itself; the 2025 face prints "Federal adjusted gross income from your federal Form 1040 or 1040-SR, Line 11a" — both now quoted with their sources.
  - *Done 2026-10-02 (MO, MD, MN, NM):* leftovers from the JS5 verifiers' queue, each quoted from the year's own blank. mo/2025 still claimed a 2024→2025 credit-line renumbering in `tax.notes` and the `effective_law_changes` comment (the 2024 MO-1040 already printed 42 MO-TC / 43 MO-PTS / 44 MO-WFTC — the header was fixed 10-01, these two places were not); its MO-A Part 2 trigger now quotes the face ("exceeded $40,000 ($20,000 if married filing separately) or you were required to complete a federal worksheet to calculate Federal Schedule A, Line 5e", no AGI figure), and the MO-WFTC investment-income question ($4,400) closes its `unverified` item. md/2025 records Form 502 line 1e ("investment income is more than $11,950", the 2025 federal EIC limit). mn/2025's `starts_from` quotes the M1 face's "from line 11" beside the 2025 Form 1040's line 11a. The NM 2023 PIT-1 manifest note lists all five brackets (it omitted 4.9%).
  - *Done 2026-10-02 (RI):* ri/2025 named "line 11" for federal AGI in `treaty_note`, `starts_from` and the state-tax base note; the 2025 face prints "line 11a". The EITC and property-tax-relief credits said page 1; the face prints 14c / 14d on page 2 (Schedule EIC line 41: "Enter here and on RI-1040, page 2, line 14d"; the Instructions quoted in the citation still say "page 1", now noted beside it).
  - *Done 2026-10-02 (MA):* ma/2023, 2024 and 2025 gave the line 2c age-65 exemption as $1,700. The visible face prints "× $ 700 = 2c" in all three years (renders checked); the text layer reads "$1,700" only because a separate "1," text object is invisible, and an earlier extraction copied it. Amount, citations and notes now say $700 (not applied by calc.state_tax, so no computed figure changes).
  - *Done 2026-10-15 (CO):* co/2024 called the 2024 DR 0104 Book's multiplication worksheet an "over-$100,000 worksheet" in eight places; the Book (printed page 38) heads it "Worksheet for taxable incomes over $50,000" and ends the table at $49,900-$50,000 -> $2,123, and co/2025 no longer lists the $50,000 cutoff as a 2024→2025 change (header and `tax.notes`). The 4.25% rate and the TABOR tiers re-read correct; no figure changes.
  - *Done 2026-10-15 (AZ):* az/2023 described the exemptions, standard deduction, 31% charitable increase and Dependent Tax Credit only as the resident Form 140 applies them; a `tax.notes` entry now gives the Form 140NR rule — each is prorated by the line-27 Arizona income ratio (line 51 "Prorated Exemptions", the standard-deduction "CAUTION: You must prorate", page-3 line 9C, the line-59 credit apportionment; the 2.5% rate is not) — quoted from the 2023 Form 140NR Instructions (pp. 9, 19, 20), now in `all_citations`. The 140NR figures ($2,100 / $1,500 / $2,300, 31%, 2.5%, both PO Boxes) re-read correct; no figure changes.
  - *Done 2026-10-15 (AL):* al/2024 called wages "Form 40 line 5" in `treaty_note` and `starts_from`; the 2024 face prints line 5a "Alabama Income Tax Withheld (from Schedule W-2, line 18, column G)" and line 5b "Wages, salaries, tips, etc. (from Schedule W-2, line 18, column I plus J)" (render checked; booklet p.7 agrees), now said there and in the printed-form citation. al/2023 never recorded the Act 2022-294 retirement exclusion (Schedule RS line 10, up to $6,000 per taxpayer 65 or older, What's New p.2) or the Schedule AATC $4,795.00 constant (lines 7/16/25/34, the face's "80% of the average annual cost of attendance"); both are now `tax.notes`, the exclusion also an `effective_law_changes` entry (modeled: false), quoted from the 2023 Schedule RS / OC Instructions and the 23f40nr package. No figure changes.
  - *Done 2026-10-15 (IA):* ia/2024 placed the low-income-exemption / EITC-only checkbox "between Steps 4 and 5" and sent the EITC-only refund through "lines 25, 30, 31, and 32", paraphrasing Expanded Instructions p.44; the 2024 IA 1040 face prints the box under the Step 5 heading above line 5 (page 2, 41-001b) and splits line 31 into 31a overpayment and 31b "AMENDED RETURN ONLY. Previous refunds." (page 3, 41-001c; Instructions p.53), so the credit notes now quote both and the fillable media/4090 joins `all_citations`. The $40 / $20 / $40 credits, April 30, 2025 and PO Box 9187 re-read correct; no figure changes.
  - *Done 2026-10-15 (DE):* de/2024's mailing addresses sent a balance due to "Line 45" and a refund to "Line 46" with the payment ZIP "19899-508" — copied from the 2024 PIT-RES Instructions' Step 5 table, which still prints the 2023 numbering; the 2024 PIT-RES face (Rev. 20240821, printed page 3) prints "PAYMENT ENCLOSED (LINE 46)" / "REFUND (LINE 47)" and "PO Box 508, Wilmington, DE 19899-0508", now cited with the table's error noted. de/2023's payment ZIP is likewise 19899-0508 (2023 PIT-NON face, printed page 1, and Where to File, p.11), and its check payee now records the PIT-NON face / Line 59 spelling "Delaware Division of Revenue" beside the PIT-RES booklet's "DE Division of Revenue", with a new `payment.citation`.
  - *Done 2026-10-15 (MD):* md/2024 never recorded the Form 502 line-1e EIC investment-income threshold; the 2024 face (page 2) prints "Place a "Y" in this box if the amount of your investment income is more than $11,600" (2023 face: $11,000) and Resident Booklet Instruction 11 Line 1e (printed page 5) adds "You DO NOT qualify for the earned income tax credit", now quoted in the state EIC's `income_limit_2024` in the 2025 pack's style. The Form 1040 line 11 start and the $1,000 65-or-over / blind exemption re-read correct; no figure changes.
  - *Done 2026-10-15 (MT):* mt/2025 never recorded the Montana Medical Savings Account limit or the Schedule 2EC computation. The 2025 Form 2 (page 3) prints Schedule I Part II line 2 "Total contributions for the year (up to $4,600 per taxpayer)" (Instructions p.22: "limited to $4,600 for each taxpayer in 2025"), now a `tax.notes` entry. The Elderly Homeowner/Renter Credit `amount` now walks Schedule 2EC: the $12,600 standard exclusion pre-printed on line 19, the Household Income Reduction Table, the 15% rent factor, the $1,150 cap and the Credit Multiplier Table (Instructions pp.40-41). Its `unverified` bullet is narrowed to Worksheet C. The rates, $5,660/$11,320, 10% EIC, $1,150 and $45,000 re-read correct; no figure changes.
  - *Done 2026-10-15 (VT):* vt/2024's `tax.notes` still carried three 2023 figures: "$4,850 per exemption", a QW standard deduction of "$14,050" and "$1,150 per standard-deduction box ... born before Jan. 2, 1959". The 2024 IN-111 face (Rev. 10/24, p.1) prints "MULTIPLY Line 5d by $5,100" and ($14,850) under both Married/CU Filing Jointly and Qualifying Widow(er), and the Instructions (p.7, Line 4) print "$1,200 for each standard deduction box" for those "born before Jan. 2, 1960" with the 1-4 box chart; the notes now quote both. The structured keys, header and citation source already had the 2024 figures; no figure changes.
  - *Done 2026-10-15 (WV):* wv/2024 said the three new refundable property tax credits (motor vehicle, disabled veteran real property, small business) affect the Tax Credit Recap Schedule and placed them on booklet p.19; the 2024 IT-140 face claims them on line 21 boxes A/B/C ("WV Property Tax Adjustment Tax Credits (claim each separately below. Enter sum on line 21)"), totalled on line 23 with the other refundable credits, while RECAP line 27 sends only non-refundable credits to line 9 — `affects`, `lookup_path` (Property Tax Credits p.20, line 21 instructions p.25) and the citation now quote the face, and the credits-not-modeled note names lines 20 and 21. The fillable face's RECAP line 18 "Child and Development Care Credit" is a misprint of the same §11-21-26 credit (booklet RECAP W and the statute say "Dependent"); no change. wv/2025's widowed-spouse disabled veteran entry repeats the RECAP attribution — open.
  - *Open:* MN 2025's M1 face prints "line 11 of federal Form 1040" where the M1 Instructions (quoted in the pack) say 11a — the DOR's caption lags its own instructions; no change. The MO-A Part 2 threshold wording and the MO-WFTC investment-income question, and NM's 2023 manifest note that omitted the 4.9% bracket, stay open until their packs are re-read.
  - **Phase K:** close after JK0 (latest start 2026-10-16). The *Open* bullet's MO-A, MO-WFTC and NM items are recorded done in the 2026-10-02 (MO, MD, MN, NM) entry above; what is left is the MN caption (no change) and whatever JK0's verifiers report. From JK23 on, the quote checker's report feeds this box.
- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JS3a, JS3b, JS3c, JS4a, JS4b, JS4c, JS4d, JS4h.
- [ ] **JS5 — State 2024/2025 re-maps and URL discovery (rest of old J3)** (XL, per pack) [PJ-15 (4)–(5)]
  - **Phase K (2026-10-09):** the 23 recovery-wave packs (6 with a pack on disk, 17 re-created from replay logs) land through **JK0** (in flight), each under KG1. The remainder — MA Form 1 2024, the ~20 re-maps, the ~26 URL-discovery tasks — is then **deferred (on demand, Phase K re-plan)**, and JK1 closes this box. The "fold into JS7" and "resume discovery for the 20 never-started states" bullets are dropped. AL 40 2025 and the MA 2023 re-map are done (progress below); AL 40 2024 is in JK0.
  - Open at the 2026-09-11 count: 73 pack-years, minus JS3b.
    - 2024: 32 (RE-MAP 10, URL-DEAD 11, no-token 7, print-only 4).
    - 2025: 41 (PORTABLE 1, RE-MAP 12, URL-DEAD 17, no-token 7, print-only 4).
  - TY2025 before TY2024. Every CA pack is a full re-map.
  - **AL 40 2024 and 2025** (from JS3b, measured 2026-09-28; see the JS3b progress note): re-place the Schedule OC rows and map its new carry-forward / limitation columns, re-read all 41 (2024) / 45 (2025) pages, and resolve the 3 / 34 vanished fields.
  - Resume discovery for the 20 never-started states plus OK, MA and NE in resumable pools of 3–4 workers. The remaining TY2024 rows fold into JS7.
    - *(Dropped 2026-10-09, Phase K: no further old-year discovery, and no TY2024 fold into JS7; see Phase K, Dropped.)*
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
    - **OH IT 1040 2025 — DONE 2026-10-01** (`formpacks/states/oh/2025/it1040_oh`, a RE-MAP of OH 2024; the same 13-page bundle, `/ModDate` 2025-12-16). Of the 442 mapped fields: 346 SAME, 54 MOVED, 18 CHANGED, 24 GONE, 18 NEW (17 mapped). IT 1040 page 2 renumbered — the 2024 line 17 (amended amount previously paid) folded into line 15, so 2024's 18-27 are 17-26 and every key follows the printed line; the Schedule of Adjustments gains line 25 (pregnancy resource center contributions, 2024's 25-46 → 26-47) and the Schedule of Credits line 24 (transformational mixed-use development, 24-46 → 25-47), every key re-captioned from the face; the withholding schedule loses a W-2G row and a 1099-NEC row and gains Part F (1099-G). Group ids on the three shared-field radio sets; relations re-read (13, 17, schedA_12, schedC_40/47, plus 8c and 25g from the fixer); cross_form `1 == f1040.11a`. `Date_Gen` (new, set by the viewer's clock) is deliberately unmapped with the P-007 departure stated. STATE_COMPUTED_READONLY 13 → 10, an EXTRA_IDENTITY_MIRRORS row for the page-header SSN, 15 TIGHTER_THAN_WIDGET rows for the Schedule J dates of birth (10 glyphs in a 75 pt Courier box), the preparer name capped at the 21 glyphs its box holds. 441/441 keys confirmed, 13/13 pages read; two adversarial verifiers (semantics FAIL → fixed; placement PASS), a fixer (8 fixed, 3 rejected with evidence), a narrow re-verify (PASS). The verifiers' finding that the MFS spouse SSN ships Hidden and never printed became JEd / P-027. Knowledge mismatches for JS2c: `payment.web_pay_url` (the face prints tax.ohio.gov/pay), and the "Ohio Nonresident Statement checkbox is new for 2025" claim (the 2023 and 2024 faces print the same row; what ended is form IT NRS).
    - **HI N-11 2025 — DONE 2026-10-01** (`formpacks/states/hi/2025/n11`, off the 2024 manifest). Pages 1-3's entry paths are unchanged (126 of 127 boxes carry over) but the page 2-4 header captions were re-set 1-11 pt wider, so the name box starts after the new caption end (the verifier's one medium finding, fixed and re-measured). Page 4 is rebuilt: the two AMENDED RETURN ONLY lines (51, 52) and their minus squares are gone, lines 53-55 are renumbered 51-53 (every box in that block moved exactly +48 pt and was re-read on the 2025 paths), and the paid-preparer grid is re-laid out with PTIN / FEIN / Telephone captions (3 boxes re-measured). 166 lines / 174 boxes (2024: 169 / 177): 141 carried, 30 moved, 3 re-measured. Face deltas: line 15 $8,636 (Act 58 SLH 2025), the line 38 / 39 / 46 years; the standard deduction, the $1,144 exemption and the line-27 forms list are unchanged. The Instructions' line-22 limitation moved to page 20 (the face still prints "page 19" — the note follows the Instructions). Built, adversarially verified (FAIL → fixed → re-verify PASS with no findings), stamped and read again at integration (test_n11_2025_overlay.py).
    - **Engine: `source_pages` (2026-10-01).** NM publishes its 2025 PIT-1 only inside the 136-page PIT packet (pages 57-58) and WV its 2025 IT-140 only inside the forms-and-instructions booklet (pages 3-4, no fillable edition at all). A hand-fill manifest may now pin the booklet and name the form's pages in `source_pages`; `fill_form` stamps and writes only those pages (the manifest's page numbers count within them), `verify_form` reads that output, the worksheet says which pages to print, and a page beyond the booklet's count is refused. test_overlay.py covers the extraction, the verify, the worksheet text and the two refusals. NM 2025 and WV 2025 are the first users (both to build).
    - **VA Form 760 2025 — DONE 2026-10-01** (`formpacks/states/va/2025/va760`, a RE-MAP of VA 2024 in name only). The 115 widgets keep every /Ff, /DA and /MaxLen; the triage's 10 "gone" names are renames at identical rects — the seven LOSS ovals (Check Box2-8 → "Loss 1" ... "loss 17"), the spouse's middle initial and first-four-letters boxes, and SSN 2 — re-bound and re-read; 60 widgets moved under 3 pt. Face deltas: "File by May 1, 2026", "Rev. 04/26", the line 19-21 years, a serial comma on line 8; line numbering 1-36 / 17a / 19a-b unchanged; the $11,950 / $23,900 filing thresholds and the $930 exemption unchanged. cross_form `1 == f1040.11a`; the SSN combs and the four 8-cell date boxes now declare `comb: true` (the SSNs with `format: ssn_digits_only`); an `account_type` group id on the shared Account Type radio. 114/114 sentinels confirmed on both pages; two adversarial verifiers (semantics FAIL on a false engine-behaviour claim in the banner → fixed; placement PASS), a narrow re-verify (PASS, no findings).
    - **SC1040 2025 — DONE 2026-10-01** (`formpacks/states/sc/2025/sc1040`, off the 2023 manifest). The 2025 blank ("Rev. 4/21/25") keeps every entry cell within 0.01 pt of 2023 — 163 of 164 boxes carry over box-for-box (pages 2-3 entirely); the one re-measured box is the combat-zone name, whose page-1 rule moved with the re-worded return-type captions (four captions gained bold prefixes). Face deltas: the years, line s's subsistence allowance $16/day (2023: $8), the "REFUNDS OR ZERO TAX DUE" mailing caption; no line added, dropped or renumbered (1-37, a-w, 22a-22e). The dependent exemption and under-6 deduction stamp $4,930 (the 2025 Instructions' worksheets); the Instructions file is now `SC1040Instr_2025.pdf`. Built, adversarially verified (FAIL on an Instructions-heading citation → fixed → re-verify PASS), stamped and read again at integration (test_sc1040_2025_overlay.py: 164/164 placements verify on both demo returns). Knowledge gap, not a mismatch: the SC 2025 pack records no subsistence-allowance figure.
    - **LA IT-540 2025 — DONE 2026-10-01** (`formpacks/states/la/2025/it540`, a RE-MAP of LA 2024). Louisiana's 2025 reform rewrote page 1: the exemption block (6, 6A blind / QSS, 6B-6F) is repealed and replaced by "6A AGE DESIGNATION" (taxpayer / spouse 65 or older), a NEW line 8 standard deduction ($12,500 status 1 / 3, $25,000 status 2 / 4 / 5) is inserted, and every later line is renumbered +1 while the widget names stayed (8A-8D → 9A-9D ... 46 → 47) — the exact trap the designator sweep exists for; "ITIN" boxes appear beside both SSNs; the dependents table gains rows 7-8. 517 widgets (2024: 519): 80 SAME, 51 MOVED, 10 CHANGED, 10 GONE, 17 NEW. 155 lines keyed to the 2025 printed numbers (9a-9d, 10-22, 23a / 23b, 24-38, 47), relations re-read (9d, 18, 22, 24, 31, 36, 38, 47), cross_form `7 == f1040.11a`, a YEAR_BEARING_KEY_FAMILIES row for the R-19000A box. 155/155 sentinels confirmed on the four return pages; two adversarial verifiers (semantics FAIL, placement FAIL — three Courier-box budgets: last names 19 → 16 glyphs in 119 pt, unit type 6 → 5), a fixer (7 fixed, 0 rejected) and a narrow re-verify (PASS). Knowledge for JS2c: `credits[3]` says the credit is carried to Line 20 — the 2025 face prints Line 21 (the +1 renumbering).
    - **CA Form 540 2025 — DONE 2026-10-01** (`formpacks/states/ca/2025/form540`, a full RE-MAP of CA 2023: FTB prefixed every name "540_form_" and renumbered after each insertion, so all 167 bound names were gone and every binding was placed by position and printed label, then confirmed on the renders). 184 widgets / 169 fields (2023: 180); 176 lines, 18 relations re-read from the face (incl. the new 47, 95-97 and 115 arithmetic), cross_form `13 == f1040.11a`. The filing status is now a five-kid radio with long export names; the account-type and use-tax / health-care / designee answers are separate boxes under one group each. Face deltas: exemption credits $153 / $475, standard deduction $5,706 / $11,412, the $252,203 AGI threshold, line 62 renamed "Behavioral Health Services Tax", line 74 now the Program 4.0 film credit, four contribution funds dropped and four added (relation 110 sums the 18 printed codes), new Organ Donor Election and paid-preparer boxes. 176/176 bindings confirmed on all six sides; two adversarial verifiers (semantics PASS, placement PASS with one medium: the apt / PMB boxes' 14-glyph budget overflows an all-digit entry — re-measured to 13 from the fixer's own renders), a fixer (5 fixed, 1 rejected) and a narrow re-verify (PASS, no findings). The scaffold test's "CA 540 2025 is still open work" expectation flips to "shipped".
    - **SC1040 2024 — DONE 2026-10-01** (`formpacks/states/sc/2024/sc1040`, off the 2023 manifest, built beside the 2025 sibling). "Rev. 7/8/24", serials 3075124x; the entry grid is identical to 2023 and 2025 (cells within 0.05 pt, paths within 0.01 pt): 163 of 164 boxes carry over, the combat-zone name re-measured on this blank's underscore string (164.89; the 2025 blank draws a rule instead, 163.85 — each measured on its own face). Face deltas: the years, the four bold return-type prefixes (as 2025), line s $16/day, the "REFUNDS OR ZERO TAX DUE" caption; no line added, dropped or renumbered; the Instructions are `SC1040Instr_2024.pdf` (September 2024) and the demo returns stamp its $4,790 dependent exemption. Three returns stamped and read (the demo, the full, and an every-line return with every box ticked and every cell filled); the verifier PASSED with three low findings (an inferred phrase in a note, a path-count wording), fixed. test_sc1040_2024_overlay.py: 164/164 placements verify.
    - **NM PIT-1 2025 — DONE 2026-10-01** (`formpacks/states/nm/2025/pit1`, off the 2024 manifest; the first `source_pages` manifest). TRD publishes the 2025 PIT-1 only inside the 136-page "2025 PIT Packet_Final.pdf" (pages 57-58, scanlines *250180100* / *250190100*; `/AcroForm` with an empty `/Fields`, no `/Annots` — a flat scannable form), so the manifest pins the packet (sha256 42754604…6be982) with `source_pages: [57, 58]`: `fill_form` stamps a two-page output holding just the return and the worksheet tells the filer to print only those pages. 116 boxes on 115 lines (2024: 118 / 117): 40 carried, 51 moved by the blank's own rules (page 1 lines 18a-22 +0.50 pt; page 2 in bands of -0.48 / -0.81 / -1.15 / -1.87 / -2.59 pt, lines 30 and 35 re-centred in taller boxes), 25 re-measured on the re-set header (1a-3d, box 5, 6a) and the redrawn 14/15/17/18 boxes. Face deltas: line 16 is "Reserved for Future Use / DO NOT USE" and 16a is gone (both dropped; line 17 = max(0, 9 + 10 + 11 - 12 - 13 - 14 - 15) as the face prints), 1a asks for the name as it appears on the state-issued driver's license or ID, HCA. 1 names the Health Care Authority (HCA) or BeWell (2024: NMHIE), the 2024 footer's due-date sentence is gone; the Instructions are quoted from the packet itself (pages 7-56, printed PIT-1-1..39) and the knowledge pack agrees (six brackets, line 16 reserved, T-7's printed $4,087 / $14,622 beside the statutory $4,089 / $14,624); the demo's line 18 = 2,042 is T-4's 56,400-56,500 MFJ row. The verifier PASSED with two low findings (the test's full return left ten marks unpainted; the banner gave the rect shifts without the larger label shifts), both fixed — the network test now stamps the demo, a marks return and the full return and verifies 116 placements on each. test_pit1_2025_overlay.py: 3 tests (census vs 2024, computes + the packet-page worksheet note, stamp/verify/render on the pinned packet).
    - **VT IN-111 2025 — DONE 2026-10-01** (`formpacks/states/vt/2025/in111`, re-mapped from the 2023 pack). "Rev. 10/25", scanlines *251111100* / *251111200*; 109 → 99 widgets (89 names): SAME 35 / MOVED 19 / CHANGED 4 / PAGE 1 / GONE 33, 28 new. The P-001 trap of the year: Line21/Line22/Line29/Line30/Line31 KEEP their widget names while the face (since the TY2024 revision — the port's base was the 2023 pack) inserted a new line 21 (Child Care Contributions for Self-Employed individuals) and renumbered 2023's 21-31 to 22-32, so every page-2 money line was re-bound by its printed line (Line30 moved 231 pt into the tax-due box; Line31 is now interest/penalty; new Line32 with a page-1 echo kid is the amount due). Line 15 split into 15.whole / 15.decimal around a printed decimal point; the fifteen signature-date cells became five single "Date (MMDDYYYY)" boxes (maxlen 8, tighter than the widget's 10); the four contribution funds were re-ordered (24a Veterans, 24b Green Up, 24c Nongame, 24d Children's Trust; widget `Lind24a` is the DOR's own misspelling); the new FARMER / FISHERMAN box is mapped; Line 1 cites federal Form 1040 line 11a → cross_form `1 == f1040.11a`; 8 relations re-derived from this face (3, 6, 19, 23, 24e, 25, 26f, 32). Face figures re-read: standard deduction 7,650 / 15,300 / 7,650 / 11,450 / 15,300, exemption $5,300, 26c cites IN-112 Part II lines 13 / 17, 26e Schedule K-1VT line 30 — all equal the knowledge pack. Two verifiers PASSED (nine low findings — three banner sentences that over-stated measured shifts, two inherited maxlens (physical_address.street / foreign_country) that the 203.7-pt Courier-12 boxes cannot hold → tightened to 28 with TIGHTER_THAN_WIDGET rows and a 28-glyph render probe, and the knowledge pack's "Line 11" → "Line 11a"), all fixed; the MMDDYYYY boxes accept any 8 characters (no date format hint exists in the engine — left as a noted gap). audit_pack.py 85/85 written, verify_fails []; four alternative fills read the radio kids.
    - **CA Form 540NR 2025 — DONE 2026-10-01** (`formpacks/states/ca/2025/form540nr`, re-mapped from the 2023 pack; the first TY2025 nonresident / part-year pack, built because the CA resident chain needs the same census). ftb.ca.gov/forms/2025/2025-540nr.pdf, "333 3131253" Side 1 … "3136253" Side 6 (2023: …33); 183 widgets / 169 names — every 2023 name GONE (all prefixed `540NR_form_` and renumbered after insertions and removals), so all 166 surviving lines were re-bound by position + printed label (152 within 3 pt; the Side 6 designee / preparer rows moved 35.6-37.1 pt under the new "Print paid preparer's name / phone" row; Side 4 codes moved as codes were dropped). Topology: the filing status is ONE radio with caption-named kids; the account-type radios became checkbox pairs (keys .checking / .savings with groups); the health-coverage question gained a Yes kid (`health_care_info.yes/.no`, the 540NR's own 2023 lineage — the Form 540 pack says `health_care_coverage`, each form keeps its 2023 names); designee `third_party_designee.yes/.no`; new `paid_preparer.name/.phone`; Side 4 contribution codes 410 / 425 / 440 / 444 gone, 431 / 447 / 448 / 449 new (bound by printed code, /TU cross-checked). Face deltas: exemption credits $153 / $475, the line 39 AGI threshold $252,203 (all equal to knowledge/states/ca/2025.yaml), line 13 cites federal line 11b → cross_form `13 == f1040.11a` and `13 == f1040nr.11a`, line 72 "Behavioral Health Services Tax", line 84 is now the refundable Program 4.0 film credit (2023: excess SDI — same number, different amount), the "the Franchise Tax Board" health sentence; relation `62 == 50 + 55 + 58 + 59 + 60 + 61` added from the printed "Add line 50 and line 55 through line 61" (printed in 2023 too, omitted then); 175 lines, 18 relations. maxlen: SSNs 11, account numbers 19, phones 10, apt/PMB 13 (13 digits render, the 14th clips), 7.count 1 (the face asks one digit; the widget allows 11 — TIGHTER_THAN_WIDGET). Two verifiers PASSED (five low findings: three banner sentences from the generator, the 7.count comment, and the key-spelling note above), the fixer resolved all five in the generator and regenerated; audit_pack.py 175/175 bindings, all six sides read as twelve crops.
    - **DE PIT-RES 2025 — DONE 2026-10-01** (`formpacks/states/de/2025/pit_res`, re-mapped from the 2023 pack). revenuefiles.delaware.gov/2025/PITForms_Instructions/PIT-RES_2025-01_PaperInteractiveIPM.pdf, "Revision 20260407", footers DFPITRES2025019999V1 … 049999V1; 4 pages (2023: 3), 198 widgets / 183 fields: SAME 20 / MOVED 77 / PAGE 56 / CHANGED 1 / GONE 22, 31 new. The trap: the 2024 revision inserted printed line 16 ACTIVE LABOR ORGANIZATION DUES and renumbered every later printed line AND widget name by +1, so a surviving name no longer means what it did (ln16ColA is now labor dues, not the 2023 subtotal; ln47ColB is NET REFUND) — every money line 16-59 was re-bound to the widget of its printed line from a position + label table, 20-24 moved to page 2, the amended section is page 4 (48-62). New: the pages-2-4 NAME / TAXPAYER ID header is one field with three kids (`header.name` / `header.taxpayer_id`); 16a/16b, 42a, 55a, 59b; renamed 19→20 election, 20→21 age/blind, 26a/26b→27a/27b, 27→28, 28→29 firefighter, 47-61→48-62. ReadOnly money cells 22 (2023: 16; lines 4, 9, 10, 12, 17, 19, 22, 26, 33, 41, 42 A+B, each with /AA /C and a 23-entry /CO), all mapped (STATE_COMPUTED_READONLY 22); /DA "/OpenSans-Bold 8 Tf" on every text widget; on_states re-dumped (filingStatusRadio /4 /0 /1 /2 /3 = statuses 1-5 by position); SEPARATE_OPTION_SETS_ADJUDICATED rows for 21 and 27b. Face deltas: 27a/27b × $110 (the printed "0" beside 27b gone), 32 "Add Line 27a through Line 31", 41 / 42 both A+B, 44 "applied to 2026 estimated tax", 45 $800, mailing boxes PO Box 508 (19899-0508) / 8710 / 8711; cross_form `1b == f1040.11a`; 12 relations from this face incl. the fixer's `23b == 12b - 22b` ("Subtract Line 22 from Line 12", unconditional). The 28 page-4 amended widgets ship `/F = 6` (Hidden|Print) until the DOR's checkAmended() script runs — exactly the JEd / P-027 class, so fill_form now un-hides what it writes and the pack's UNRESOLVED paragraph records the resolution. Two verifiers PASSED (six + two findings; the one medium was this Hidden class), the fixer resolved six (names-vs-cells wording for 42a / 55a / 59b, the /CO order, the phone /MaxLen sentence, the 28-of-30 count, the 23b relation), rejected three with evidence (the engine item above and the two knowledge items, fixed in JS2c c444631), and the narrow re-verify PASSED. audit_pack.py 180/180 written; four alternative fills read every radio kid.
    - **CT-1040 2025 — DONE 2026-10-01** (`formpacks/states/ct/2025/ct1040`, off the 2023 manifest, measured on the 2025 blank). portal.ct.gov/-/media/drs/forms/2025/income/ct-1040_1225.pdf, "(Rev. 12/25)", scanlines "1040 1225W 0N 9999", no AcroForm; 184 boxes → 187 on 184 lines: 74 carried verbatim (page 3 lines 31-48 + Schedule 2, all of page 4, the page 2-4 SSN headers — movebox SAME, confirmed on render), 113 re-measured from the 2025 geometry (10 land on the exact 2023 numbers; 98 moved — the page-1 header block +16 pt, the attachment squares +19, lines 1-15 -4 / -5, 16 -2; page 2 rows -19 … +9; page 3 48a-c +15.2 … +16.6). Lines 181 → 184: added `health_coverage.interest` (the new "Do you need health coverage?" Access Health CT box), 20d (Historic Home Rehabilitation Credit, Line 21 adds it), 48d (ABLE), and the printed "specify" boxes beside 37 / 49 the 2023 manifest never listed; dropped `signature.email` (the box is gone) and `48.account` (the CHET account entry is gone); 25b / 25c switched from comb to cells (uneven strokes). Face deltas re-read: Line 1 cites federal Form 1040 "Line 11a", Line 13 Schedule CT-IT Credit Part 1 "Line 10" (2023: 11), "Due date: April 15, 2026", 48 "CHET contributions made in 2025", 70g "Connecticut Baby Bond Trust" (was CHET Baby Scholars); the notes re-read in the 2025 Instructions (Rev. 12/25): Tax Calculation Schedule pp. 19-23 with Table C's 2% phase-out add-back, Property Tax Credit ceilings $49,500 / $70,500 / $35,250 / $54,500, the "blue or black ink only" sentence verbatim on page 1. The verifier PASSED with one low finding (the banner over-stated what the full return stamps) — fixed by a third EVERY return that stamps the 36 lines FULL left blank, read on eight crops, totals pinned. The three face items the knowledge pack lacked (20d, 48d, the Access Health CT box) are the JS2c CT entry. test_ct1040_2025_overlay.py: demo, full and every-line returns, 187/187 placements verify.
    - **MS Form 80-105 2025 — DONE 2026-10-01** (`formpacks/states/ms/2025/f80105`, PORTABLE off MS 2023). dor.ms.gov/…/80105258 1.pdf, "Form 80-105-25-8-N-000 (Rev. 09/25)", scanlines 80105258N000; 166 widgets / 159 names in both years and every one of the 155 names the 2023 pack binds is SAME in name, page, /FT, /Rect, /MaxLen, /Ff, /DA and /AP states — 0 new, 0 gone; no line renumbered or recaptioned (layoutdiff: 100% of words within 2 pt on all three pages). What the DOR did change is the viewer side: 69 page-1 fields (59 text, 10 /Btn) were re-authored from terminal widgets into parent + kid shape with their /AA actions unchanged on the parent — the builder's annotation-level diff reported phantom dropped actions, the exact trap CONVENTIONS names, and the semantic verifier's one medium finding; the fixer re-measured with a /Parent-walking comparison (0 field-level action differences) and rewrote the paragraph. Deliberate deviation from the base: the plain page-2 / page-3 header SSN boxes (Page2SSN / Page3SSN) are now mapped as identity mirrors (`identifying_number_page2` / `_page3`; the 2023 pack shipped a blank SSN header on pages 2-3), IDENTITY_MIRROR_COUNTS 2; the printed per-column arithmetic is declared with dotted ids (16.a/b, 49.a/b, 65.a/b, 66.a/b, 13.a/b — the 2023 pack's "evaluator rejects dotted ids" note is obsolete since JP5c). Face figures re-read: $12,000 / $8,000 / $6,000 filing-status exemptions, line 10 × $1,500, line 55 $15,000. Fixer: 6 fixed (the topology paragraph, an unreproducible TLS claim removed, `preparer.address` 25 → 17 and `preparer.city` 21 → 11 from render probes that showed the old budgets clipping at the dividers — TIGHTER_THAN_WIDGET rows, MMDDYYYY keystroke-filter comments on the four date lines), 3 rejected with evidence (routing / account boxes hold their full /MaxLen left-aligned without a comb bit; `name.last` 21 is verify's 0.6-em estimate, not a clip); narrow re-verify PASSED. 157/157 sentinels on the renders.
    - **WI Form 1 2025 — DONE 2026-10-01** (`formpacks/states/wi/2025/wi_form1`, re-mapped from the 2023 pack). revenue.wi.gov/TaxForms2025/2025-Form1f.pdf, stamps I-010i / I-010bi, 5 pages (2023: 4); 181 → 209 widgets (174 → 197 names): of the 170 mapped base fields SAME 88 / MOVED 53 / PAGE 2 / GONE 27, 52 new widgets, all mapped. The trap: 25 surviving widget NAMES now sit on a different printed line — the face inserted line 15 "Blind worker transportation services credit / Qualifying expenses × 50%", collapsed line 14 into one "Include Schedule WI-2441" box, renumbered 2023's 15-31 to 16-32 and 32-45 to 33-46, moved the homestead and veterans credits (33, 34) from page 3 to page 2, and moved the donations block to a NEW page 5 "Schedule 3 – Financial Donations" (1a-1h + total 2; Form 1 line 24 = its total) beside a new Part II anatomical-gift registration (filer / spouse Yes, Sex M / F, eight date-of-birth cells) — so every page-2 / page-3 line was re-bound by widget position + printed label (the names 15a / 15b now bind the NEW line 15, the old inputs became 16a / 16b). Line 17 (working families tax credit) prints a box but has NO widget on the DOR's blank, so it is not fillable (the knowledge pack's "no amount allowable on Form 1" agrees). Group ids on filing status (5), tax district (3) and the designee (2) retire the 2023 SHARED_FIELD debt; 17 ReadOnly header mirrors incl. the new page-5 names (IDENTITY_MIRROR_COUNTS 17, STATE_COMPUTED_READONLY 17); relations from this face incl. the fixer's `37 == 28 + … + 36` and the printed factors `15 == line15_qualifying_expenses * 0.5`, `25 == line25_penalty_base * 0.33`, `sch1_9 == sch1_7 * 0.05`; cross_form `1 == f1040.11a` (the face still prints "line 11"). Face figures unchanged: $700 / $250, × .33, .05, .03 / $16,000 / $480; donation funds renamed (Badger Chapter, Military family relief, Second Harvest). Two verifiers PASSED (six low: the omitted printed arithmetic, the date3 cell's wording, the over-stated layout claim, and the DOR's STALE widget tooltips — 2024 captions on 2025 widgets, now listed in the banner as not-evidence); fixer 5 fixed / 0 rejected. 193/193 sentinels on the renders. Knowledge notes for JS2c: the blind worker credit's printed 50% rate and caps, the line 25 .33 factor, the "line 11" AGI citation.
    - **CT-1040 2024 — DONE 2026-10-01** (`formpacks/states/ct/2024/ct1040`, built from the 2023 manifest beside the 2025 sibling, measured on the 2024 blank). portal.ct.gov/-/media/drs/forms/2024/income/ct-1040_1224.pdf, "(Rev. 12/24)", scanlines "1040 1224W 0N 9999", no AcroForm; 184 lines / 187 boxes: vs 2023, 84 numerically identical (74 carried + 10 re-measured to the 2023 numbers), 98 moved or changed (every page-1 / page-2 box on the 2024 geometry; page 3 48a-c, 49, 50), 2 dropped (`signature.email`, `48.account`), 5 added (`health_coverage.interest`, 20d, 37.specify, 48d, 49.specify); vs the 2025 sibling, 186 of 187 boxes identical — only the health-coverage square differs (2024: an 8.55 × 7.96 pt square at x 144 under a differently worded "Are you interested in learning more about the health coverage options available through Access Health CT?" paragraph; 2025: 7 × 7 at x 125.41), and the 2-D barcode modules are the only other differing paths on any page. Face: Line 1 cites federal "Line 11" (2025: 11a), Line 13 Schedule CT-IT Credit Part 1 "Line 10", NEW 20d Historic Home Rehabilitation Credit (Line 21 adds it) and 48d ABLE (Line 50 sums it), 70g still "CHET Baby Scholars", "Due date: April 15, 2025"; the notes re-read in the 2024 Instructions (Rev. 01/25): Table C 2% phase-out add-back, Property Tax Credit Table p. 26, ceilings $49,500 / $70,500 / $35,250 / $54,500. The verifier PASSED with three low findings (a sibling test that could only run once CT 2025 was present — it now passes in the repo; the doc counts; the knowledge gaps 20d / 48d, the JS2c CT 2024 entry); the fixer rejected all three with evidence. test_ct1040_2024_overlay.py: demo, full and every-line returns, 187/187 placements verify, plus the 2024-vs-2025 box-for-box test. All four print-only states now stamp TY2023, TY2024 and TY2025 (12 manifests).
    - **WV IT-140 2025 — DONE 2026-10-01** (`formpacks/states/wv/2025/it140/handfill.yaml`, a NEW hand-fill manifest — WV's 2023 and 2024 packs are AcroForms, but the 2025 return exists only as pages 3-4 of the 56-page "Personal Income Tax Forms and Instructions" booklet, AES-encrypted with the empty user password, no AcroForm, 0 annotations; `source_pages: [3, 4]`). tax.wv.gov/Documents/PIT/2025/it140.PersonalIncomeTaxFormsAndInstructions.2025.pdf, "IT-140 W", scanlines *P40202501W* / *P40202502W*, no REV code. 114 boxes on 112 lines, every one measured from the booklet pages' own rules, gray caption cells and text layer (layoutdiff: no printed word within 2 pt of the 2023 AcroForm). Against the 2023 pack's page 1-2 fields: added the four line-12 IT-210 boxes (REQUEST WAIVER / QUALIFIED FARMER / REQUEST ANNUALIZED / REQUEST SHORT METHOD) with its money box, the new line 21 "WV Property Tax Adjustment Tax Credits" A / B / C + sum, the signature dates and telephone, the preparer date / printed name / firm, 6.count; dropped the three-cell extended due date (one MM/DD/YYYY box now), the old waiver box, the not-efile box and the preparer signature; re-keyed by the face's renumbering (2023 12-19 → 13-20, 20-26 → 22-28, 24a/b/c → 26a/b/c). Face deltas: page 1 line 2 / 3 cite "line 61 / line 52 of Schedule M" while the same booklet's Schedule M prints its totals as 59 / 50 (a booklet-internal inconsistency, recorded in the notes); the TAX DEPT USE ONLY block and footnote typos gone; mailing addresses unchanged (refund PO Box 1071, balance due PO Box 3694). The booklet's "TIPS ON FILING A PAPER RETURN" (printed page 16) say NEVER USE COMMAS in dollar amounts and leave lines with no entry blank, "Do not fill in with zeros" — the first form to need the JS4h engine options: `money_style: plain` and `blank_zero_computes: true`, both tips quoted under printing_guidance. Verifier FAIL → three medium (the notes' Instructions page citations 24 → 25, the Schedule M page, the commas / zeros deviation that became JS4h) + three low; fixer 4 fixed / 2 rejected with evidence (the REQUEST WAIVER cell measured to the rules' ink, the knowledge items below); narrow re-verify PASSED with nothing open. test_it140_2025_overlay.py: the census, the computes under the tips (line 21 blank with no credit, -8300 with its minus), and a network stamp / verify / render on the pinned booklet with the independent recompute. Knowledge notes for JS2c: six wv/2025 citation.source strings say "2024 … Forms & Instructions" while their url is the 2025 booklet; the rounding tip is cited at p. 14 where the 2025 booklet prints it on 16 (PDF 18).
    - **ID Form 40 2025 — DONE 2026-10-01** (`formpacks/states/id/2025/form40`, re-mapped from the 2024 pack). tax.idaho.gov/wp-content/uploads/forms/EFO00089/EFO00089_03-02-2026.pdf, "Form 40 2025", footers "EFO00089 03-02-2026 Page N of 3"; the 11-page bundle (pages 1-3 the return, page 4 widget-less, pages 5-11 the instruction worksheets printing "Page 8 of 52" … "Page 14 of 52"); 187 widgets: of the 150 base bindings MOVED 59 / PAGE 46 / GONE 45, 61 new. The return grew to three pages (Tax Calculation 12-20 on page 2, Payments 42-61 and the signature block on page 3). Traps: the widget names IncomeL18 / TxCompL19 are SWAPPED between lines 18 and 19 (bound by position); 2024's line 21 "Tax amount from line 20" is gone and 22-42 renumbered 21-41 under the SAME widget names — every printed-number key re-bound one line lower; the name rows split into first / middle initial / last / suffix (new `name.middle_initial`, `name.suffix`, spouse likewise); NEW 42 Parental Choice Tax Credit; "Grocery Credit" → "Food Tax Credit"; the 180-days box was re-authored as two overlapping /Tx widgets, so `signature.authorize_discussion` is now a text line taking "X" (an API change from 2024's checkbox, noted in the banner); direct-deposit cells renamed Route 2..10 / Acct 2..18, mapped by x-order (verified strictly ascending). Face figures: standard deductions $15,750 / $23,625 / $31,500 (2024: $14,600 / $21,900 / $29,200), line 31's preprinted $10 permanent building fund tax; line 7 still prints "line 11" → cross_form `7 == f1040.11a`. Relations 9, 25, 41 plus the fixer's `50 == 42 + … + 49` and `61 == 58 + 59 - 60` from the printed instructions. Two verifiers PASSED (five low: the omitted line-50 / 61 sums, a booklet-page attribution off by one, an over-stated ".00" claim, `preparer.state` maxlen 6 → 2 after a clipped render); fixer 4 fixed / 0 rejected. 154 fields; audit_pack.py 154/154 lines (one option per group) confirmed on the renders.
    - **CA Schedule CA (540) 2025 — DONE 2026-10-01** (`formpacks/states/ca/2025/sched_ca_540`, re-mapped from the 2023 pack). ftb.ca.gov/forms/2025/2025-540-ca.pdf, footers 7731253 … 7736253 (2023: …233), six sides; 247 GONE / 255 NEW — every 2023 id is now `540ca_form - NNNN` and keeps its printed row except around three inserted rows: Side 1 line 1h gained a type box (`1h_desc`), Section B 2b and Section C 19c gained "Date of original divorce or separation agreement" boxes (`B2b_date` / `C19c_date`, maxlen 7 — the 2025 Instructions ask for the month and year), Side 2 NEW line 8v "Digital assets received as ordinary income not reported elsewhere" (8z renumbered 2034 → 2037, the rows below 24 pt lower), Side 3 9b1-9b3 re-named, lines 20 / 21 / 23 moved 37 pt; keys 7_A/_B/_C → 7a_A/_B/_C after the printed "7a". Two NEW ReadOnly boxes on the printed "Reserved for future use" rows (Section C 22, Part II 8d) are P-007 class 3 and deliberately unmapped — the banner records that line 26's "Add line 11 through line 23" ranges over 22 but no relation is declared, as in 2023. Face deltas re-read: 1f cites Form 8839 line 31, line 10's new wording, Part II 2 / 23 cite federal "line 11b", Part II 5e "Enter the smaller of line 5d or $40,000 ($20,000 if married filing separately) in column A" (2023: $10,000 / $5,000), 29 thresholds $252,203 / $378,310 / $504,411 and 30 standard deduction $5,706 / $11,412 (all equal to knowledge/states/ca/2025.yaml). /Ff re-measured per side with a parent-walking dump (Side 1 and lines 8a-8d keep DoNotSpellCheck; Sides 3-5 dropped it; Side 6 split). 253 fields (240 money, 12 text, 1 checkbox); the filer-address row is empty (name and SSN only, as the reviewed 2023 row). Three verifiers PASSED (semantics; placement Sides 1-3; placement Sides 4-6) with twelve low findings — an over-stated /Ff claim, a 5e misquote ("/RDP" is not printed), three rewordings, scratch-path provenance in the banner, the divorce-date format, the line-22 rationale, the knowledge absences — fixer 7 fixed / 0 rejected, comment-only. 253/253 sentinels confirmed on the 170-dpi renders of all six sides.
    - **MS Form 80-105 2024 — DONE 2026-10-01** (`formpacks/states/ms/2024/f80105`, PORTABLE off MS 2023, text taken from the verified 2025 sibling). dor.ms.gov/…/80105248.pdf, "Form 80-105-24-8-N-000 (Rev. 09/24)", scanlines 80105248N000; 166 widgets = 159 names in all three years — every one of the 155 names the 2023 pack binds is SAME, and the field-level attribute diff walking /Parent is EMPTY (the 2024 blank keeps the 2023 terminal field shape; the parent + kid re-authoring is 2025's), no ReadOnly widget, no document JS. Face deltas: only the revision stamp, the scanlines and the year (layoutdiff 100% of words within 2 pt, median ≤ 0.07 pt); printed figures re-read ($12,000 / $8,000 / $6,000 exemptions, line 10 × $1,500, line 55 $15,000). As the 2025 pack: the page-2 / page-3 header SSN boxes are identity mirrors (IDENTITY_MIRROR_COUNTS 2 — the 2023 pack shipped them blank), the per-column arithmetic is declared with dotted ids, `preparer.address` 25 → 17 and `preparer.city` 21 → 11 from clip probes rendered on THIS blank (TIGHTER_THAN_WIDGET rows), MMDDYYYY filter comments on the four date lines. Two verifiers PASSED with two low findings (the banner cited the 2025 sibling as a path absent from the build tree; the routing / account boxes print one plain underline each, not per-character cells), both fixed; 157/157 sentinels on the renders. The 2023 pack keeps its two preparer over-budgets (not touched).
    - **IL-1040 2025 — DONE 2026-10-01** (`formpacks/states/il/2025/il1040`, re-mapped from the 2024 pack). tax.illinois.gov/…/currentyear/individual/il-1040.pdf — a rotating path that will serve TY2026 around Dec 2026 - Jan 2027 and then fail closed on the pinned digest (the taxarchive 2025 path 404s today; no mirror_urls, the host answers 200), and one that already re-served this same R-12/25 form as a different byte stream earlier in 2026 — the banner records the Wayback digests; "IL-1040 Front / Back (R-12/25)", barcodes *60012251W* / *60012252W*. The 2024 pack bound 96 widgets: GONE 53 / MOVED 41 / SAME 2; the 2025 blank has 109 widgets / 102 names, 64 new — the DOR re-authored the names (step1-A-*, option sets, caption-named 34a-d / 42 boxes, bank cells, phones, preparer / designee) at the same printed boxes, so 53 fields were re-bound by position + printed label; the Help banner's ReadOnly widget is gone (zero ReadOnly); /MaxLen dropped on SSNs, DOBs, ZIP, PTIN, FEIN and phones (maxlen kept at the printed counts), kept on area codes, Routing 9 / Account 17 (comb), fiscal boxes, money. Face deltas: Line 1 cites federal "Line 11a" → cross_form `1 == f1040.11a`; the header asks for a full date of birth (keys `tp_date_of_birth` / `spouse_date_of_birth` replace the year-of-birth keys); line 42 recaptioned for Get Covered Illinois with NEW "Self / Spouse / Dependent(s)" boxes (`42_household_needs_insurance::*`, an INDEPENDENT option set); printed figures unchanged (10b / 10c × $1,000, line 12 4.95%). Group ids on the four shared-field option sets; the fixer added `10 == 10a + 10b + 10c + 10d` (printed unconditionally, omitted by the 2023 / 2024 packs without reason). The `A_filing_status::*` prefix stays although the face letters the item "B" (a cross-year key; declared in the banner). Two verifiers PASSED with ten low findings (banner measurements and wording, the nursing-home caption, the URL re-save history, the line-10 relation, the key-prefix letter, a knowledge attribution); fixer 5 fixed / 2 rejected with evidence. 107/107 lines confirmed on the renders.
    - **NJ-1040 2023 / 2024 line 6 re-keyed — DONE 2026-10-02** (pitfall P-030). The NJ 2025 port's render found the 2023 and 2024 packs keying line 6's two widgets by order: the first oval ("Self") is printed solid with no widget, so `exemption_6_regular_self` sat on the Spouse/CU Partner oval and `_spouse_cu` on Domestic Partner. Both packs now bind Check Box39 to `exemption_6_regular_spouse_cu` and Check Box40 to `exemption_6_regular_domestic_partner` (no key for the pre-printed oval), as the 2025 port does; test_nj1040_line6_ovals.py reads the label printed right of each widget on every year's blank, and CONVENTIONS.md gains the bind-by-label rule.
    - **NJ-1040 2025 — DONE 2026-10-02** (`formpacks/states/nj/2025/nj1040`, PORTABLE off NJ 2024 by name, re-read row by row). nj.gov/treasury/taxation/pdf/current/1040.pdf — a year-agnostic path (every 2026 Wayback capture is this blank, every 2025 one the 2024 blank), so the banner records the re-point for when TY2026 posts. 844 widgets / 814 fields: 734 of the 813 mapped names MOVED when page 1 re-flowed around the new Digital Assets row (added as `digital_assets::yes/no`), 79 SAME, none gone; the blank's line 60 ones/cents cells echo line 61 (a DOR defect, documented). Line 6's two ovals are keyed by their printed labels, which led to the 2023/2024 fix above (P-030). Three one-digit cells whose comb widgets say /MaxLen 2 are tightened to 1 (TIGHTER_THAN_WIDGET rows), and the 2023 and 2024 packs, which carried the same 2 on the same rects, are tightened alongside.
    - **CA Schedule CA (540NR) 2025 — DONE 2026-10-02** (`formpacks/states/ca/2025/sched_ca_540nr`, re-mapped from the 2023 pack). ftb.ca.gov/forms/2025/2025-540nr-ca.pdf, stamps 7741253 … 7745253, five sides; 411 GONE / 421 NEW — every id is now `540NR CA - NNNN` and renumbered (the six residency checkboxes became two radio fields, Myself / Spouse), so every binding was placed by position and the printed row label, then confirmed on the renders. New rows mapped: Section A 1h type box, Section B 2b divorce date, 8v digital assets (A-E), Section C 19c date; Section A line 7 is now 7a. The two ReadOnly "Reserved for future use" boxes (Section C 22, Part III 8d) stay unmapped (documented in the banner). This completes the four TY2025 California packs.
    - **MD Form 502 2025 — DONE 2026-10-02** (`formpacks/states/md/2025/md502`, re-mapped from the 2023 pack). marylandcomptroller.gov/…/forms/2025/502.pdf, "COM/RAD-009 10/25", 4 pages; 185 widgets / 172 fields: GONE 23 / MOVED 132 / SAME 12, 26 new. Filing status, deduction method and account type are now one multi-kid field each (export values named for the option), and page 3 reuses widget NAMES on different printed lines (Text Box 90, 88, 77, 93, 102, Check Box 45), so every binding was rebuilt by position and printed label. Face: new 17c itemized phase-out, 20a/21b (Form 502CG capital gain, × .02), 39 Veterans Trust Fund, 42 MW506NRS withholding, 51a homebuyer withdrawal penalty; old 39-50 renumber to 40-52 and direct deposit to 53a-d. Knowledge finding for JS2c: the face prints the line 1e investment-income threshold as $11,950.
    - **ND-1 2025 — DONE 2026-10-02** (`formpacks/states/nd/2025/nd1`, PORTABLE off ND 2024). tax.nd.gov/…/2025-iit/28702-form-nd-1-2025.pdf, "SFN 28702 (12-2025)" — re-issued mid-season (ModDate 2026-02-11; a Wayback capture of 2026-03-11 is byte-identical). Each page paints the earlier face as a form XObject under the corrected one (line 1a "line 11" beneath "line 11a"), so face quotes come from the visible stream only. 92 widgets keep every name, flag, /MaxLen and on-state; 83 moved by at most 7.3 pt. Line 1a now binds `f1040.11a`; the three signature/preparer date boxes are tightened to 8 characters.
    - **RI-1040 2025 — DONE 2026-10-02** (`formpacks/states/ri/2025/ri1040`, PORTABLE off RI 2024). tax.ri.gov/…/2026-01/2025_1040WE_w.pdf (Cloudflare-cached; fetched twice, byte-identical); 323 widgets / 329 fields keep every name and rect, and the 22 CHANGED are /MaxLen removals, so each affected maxlen was re-measured by rendering probe fills (names 26, licences 14, relationships 10, party name 10 — the 2023 and 2024 packs carried 12 on the same widget and are tightened alongside). Relations added from the face: 21 = 20 × 0.25, 29 = min(23, 27, 28), Schedule W 16 = the sum of 1-15. The dependent DOB boxes clip the 8th digit (see JEe).
    - **IA 1040 2025 — DONE 2026-10-02** (`formpacks/states/ia/2025/ia1040`, re-mapped from the 2023 pack). revenue.iowa.gov/media/4401/download (the gateway page's "Fillable" file), footers 41-001a … 41-001f; now six pages, 253 widgets / 236 names, every one mapped: of the 217 fields the 2023 pack maps, 22 SAME / 80 MOVED / 96 on another page / 19 GONE, plus 39 new. Step 4 line 1 became 1a-1f (1f the Enhanced Deduction for Seniors from federal Schedule 1-A), the dependents table gained a fourth row, page 1 gained two date-of-birth boxes and a HOH/QSS child row, and the pages re-cut (Schedule 1 is page 5). The line-21 contribution boxes narrowed to 15 pt and hold 2 digits (maxlen 2, TIGHTER_THAN_WIDGET); on page 4 the DOR placed both header widgets ~10 pt right of their printed boxes (a blank defect, documented).
    - **NE Form 1040N 2025 — DONE 2026-10-02** (`formpacks/states/ne/2025/f1040n`, re-mapped from the 2023 pack). revenue.nebraska.gov/…/2025/f_1040N.pdf, stamp 8-417-2025 — revised in place (a January 2026 Wayback capture has a different widget set; February 2026 on matches the pin). A new three-page layout: 102 of 143 mapped widgets gone, 137 new, lines renumbered from 18 on (old 28-30 → 34-39, incl. the PTET credit), filing status now radio fields. The 2025 1040N is also the amended return (no separate 1040XN): an "Amended Return" flag and four amended-only Yes/No questions, plus the new foreign-adversarial-company question, are mapped. Relation added: 58 = 58 state + 58 local.
    - **MA Form 1 2023 re-mapped onto the re-issue — DONE 2026-10-02** (`formpacks/states/ma/2023/form1`). mass.gov's 2026-05-22 re-issue (sha256 5cbb5655…, mirror = the exact Wayback capture 20260920033523) names every field after its caption and nests them as dotted /T chains (176 widgets = 160 terminal fields; get_fields lists 360 names); several names carry another year's words, so position and printed label decided every row (144 re-bound one for one). The old pack's eleven unmappable nested ovals (Checkcash / Checktp1) are now standalone fields and all mapped (amended-return, veteran, deceased, under-18, noncustodial-parent boxes); the three signature widgets are gone (signed by hand). The banner keeps the 2024-01-17 revision's digest and mirror as history; the MA drift row in scripts/freshness_quarantine.yaml is deleted.
    - **OK Form 511 2025 — DONE 2026-10-02** (`formpacks/states/ok/2025/form511`, re-mapped from the 2023 pack). oklahoma.gov/…/individuals/current/511-Pkt.pdf — a rotating "current" slot (it will serve TY2026 later; the banner names the past-year path to re-point to); 52-page packet, widgets on pages 42-51. Of the 2023 bindings 270 MOVED, 16 GONE, 4 changed page, 18 new: a new Part Three line 29 renumbers every later return line by one, and Schedules 511-A/B/C each gained lines.
    - **ME Form 1040ME 2025 — DONE 2026-10-02** (`formpacks/states/me/2025/f1040me`, re-mapped from the 2023 pack). maine.gov/…/inline-files/25_1040ME_fillable.pdf, barcodes *2502100* … *2502111*; 122 widgets / 110 fields (2023: 129 / 114): 24 unchanged, 62 moved, 10 changed only /MaxLen, 14 gone, 10 new, all mapped. The refund-deposit block moved to page 3 as 34c-34e (Checking / Savings now separate single-state fields, grouped), net overpayment is line 33, the penalty is page-2 line 32 and the amount due a single line 35; the health-care-coverage block is gone from the face. Free-text boxes without a /MaxLen budget one glyph per 5.6 pt of measured width (realistic Arial 10 text clipped at verify's 5 pt).
    - **IN Form IT-40 2025 — DONE 2026-10-02** (`formpacks/states/in/2025/it40`, re-mapped from the 2023 pack). forms.in.gov/Download.aspx?id=16914 ("2025 IT-40 Income Tax Form | 09/25"), "(R24 / 9-25)", 2 pages. 64 of the 72 mapped widgets were renamed in place ("1" → "Line 1", the SSN and county boxes, fiscal-year fields) and re-bound pair by pair on the render; 8 kept their names and moved. Filing status became one three-kid radio field.
    - **AL Form 40 2023 re-keyed — DONE 2026-10-02** (pitfall P-031; found by the AL 2025 port's semantic verifier). Page 1's keys from line 5 on followed a superseded face, one number high (key "22" on printed 21, "34_total_donations" on printed 33 — the overpayment applied to next year's estimated tax), and the relations matched the shifted keys, so verify never flagged it. Re-keyed to 5a, 5b, 20a, 20b, 21-34 as in the 2025 port; the UltraForms barcode helpers UF_InfoA-K are unmapped (ReadOnly count 566 → 555); test_al40_line_designators.py reads the printed number beside every numbered page-1 widget. The same pass made P-027 measure viewer guards against the CropBox (AL 40's cropped worksheet pages printed blank).
    - **AL Form 40 2025 — DONE 2026-10-02** (`formpacks/states/al/2025/al40`, from the 2023 pack: a partial re-map of the 45-page booklet). 2,826 fields; Schedule OC re-placed with its new Part W Innovate Alabama carry-forward / limitation table and Parts Z-AD, a second Schedule RS, the Vehicle Loan Interest spreadsheet and worksheet; page-1 keys by the printed numbers (which exposed the 2023 defect above); FITDW4d now the refundable adoption credit (Form 2439 moved to 4e); the UltraForms barcode helpers and DOR banners unmapped. Placement was verified in four page ranges; the one open finding (the cropped worksheet pages printed blank) was the P-027 CropBox fix.
    - **MI-1040 2025 — DONE 2026-10-02** (`formpacks/states/mi/2025/mi1040`, re-mapped from the 2023 pack — no 2024 pack exists). The Treasury forms page links the MI-1040 with a cache-key query string (the bare path serves the same bytes); "(Rev. 06-25)", 3 pages, encrypted with an empty user password as in 2023. 95 → 103 widgets, 72 of 85 mapped names gone, every one renamed to its printed line ("9a" → "Line 9a Number", the residency boxes → "Line 8a-8c" — DOR typos kept as spelled); all 96 data widgets mapped. Nothing on the form computes (format/keystroke scripts only).
    - **KS K-40 2025 — DONE 2026-10-02** (`formpacks/states/ks/2025/k40`, re-mapped from the 2023 pack). ksrevenue.gov/pdf/k-4025.pdf ("Original and Amended - 2025", revised 8-5-25), 2 pages, scan lines 114525 / 114225, no "(Rev." stamp; 130 widgets (71 of 134 base widgets gone, 67 new). Many labels sit in a non-embedded Arial whose extracted text reads 29 code points low, so every face quote was shifted back and confirmed on a render.
    - **MA Form 1 2025 — DONE 2026-10-02** (`formpacks/states/ma/2025/form1`, built beside the 2023 re-issue re-map, in the same caption-named field style). mass.gov/…/2025-form-1-…/download (sha256 0bb62498…), mirror_urls = the exact Wayback capture 20260911192930 (mass.gov answers scripts with 403). Lines 50-55 renumber against 2023 (direct deposit 54_*, interest/penalty 55a-55c, a custodial-parent box); every row placed by position and printed label. MA 2024 stays open: its current bytes have no Wayback capture, so a pinned pack could not be fetched by fetch_blank.
    - **CO DR 0104 2025 — DONE 2026-10-02** (`formpacks/states/co/2025/dr0104`, a full re-map of the 2023 pack). tax.colorado.gov/…/DR0104_2025.pdf (403 to non-browser agents), "DR 0104 (10/03/25)", now 8 pages and 152 widgets / 124 fields (2023: 4 / 98 / 90) — every 2023 name gone (the opaque TextNN ids became descriptive names such as "Form Question 1" … "47"), the residency checkboxes became radio widgets on separate fields; every line re-bound under its printed label and confirmed on a sentinel render. With CO, every TY2025 jurisdiction but MT ships.
    - **MN Form M1 2024 — DONE 2026-10-02** (`formpacks/states/mn/2024/m1`, PORTABLE off MN 2023; the TY2024 tail starts here). revenue.state.mn.us/…/2026-01/m1-24.pdf (an upload-month folder, so the digest is the identity), scan lines *241111* / *241121*; 64 of 74 widgets SAME, 10 moved, none gone; the four new widgets are the ones the 2025 pack maps, keyed as there. Censused against both neighbours: the 2024 blank sits next to 2023 (line 14 is still one line).
    - **GA Form 500 2024 — DONE 2026-10-04** (`formpacks/states/ga/2024/ga500`, the 2025 pack carried back one year; TY2024 now has 25 jurisdictions). apps.dor.ga.gov/FillableForms/webpdf/examples/2024GA500.pdf (sha256 56251bd4…, Last-Modified 06 Jan 2025), "Georgia Form 500 (Rev. 08/01/24)", 2024 (Approved web version); IND-CR 212 prints Rev. 08/01/24 v2 and the 525-TV Rev. 08/14/24; 28 pages, AcroForm, no XFA. 942 widgets / 825 names; against the 2023 pack 316 SAME, 177 moved, 28 gone, 9 changed, 2 changed page, 8 new (two dates of birth, the ReadOnly line-11 / line-14 / Schedule 3 line-11 amounts and counts); against the 2025 pack 477 SAME, 30 moved, so the port starts from 2025. Prose reverted to the 2024 face (5.39% rate, Georgia Resident Itemizer Tax Credit, IND-CR 202 at 30%, line 6 dates of birth, Schedule 1 date-of-birth rows); the cross_form leg is f1040.11. 546 line keys; 506 sentinels audited on renders. Verify PASS, then four findings were fixed: indcr213.2 (CRP13L2, the face's own 2021 / five-year rule makes it impossible this year), indcr_summary.5 (SUML5, "Reserved") and the two uncaptioned IND-CR 212 license numbers were dropped as keys (the summary line-13 relation lost its line 5), and the seven no-Print-flag /Ch pickers now name their printing companion key; s3.9_time_ratio and s3.10_deduction.georgia are unmapped (the 2024 face prints neither option). The reverify PASSed. Open, disclosed in the pack: the 2023 and 2025 packs still carry the four dropped keys and the two over-printing options (a cross-year call); the unmapped /G kid of CB_DEDUCTION_TYPE still shows an empty box once line 10 is filled (a filler behaviour, as in 2025); the 525-TV address boxes hold far fewer glyphs than their /MaxLen 50 (the clipping scan catches an overflow). The MA 2023 separate-option-sets gate failure seen in the tree is already fixed on main.
    - **WI Form 1 2024 — DONE 2026-10-04** (`formpacks/states/wi/2024/wi_form1`, the 2025 pack carried back one year; TY2024 now has 26 jurisdictions). revenue.wi.gov/TaxForms2024/2024-Form1f.pdf (sha256 dee31c2b…, ModDate 2024-11-11), "2024 I-010 Form 1, Wisconsin income tax (fillable)", stamps I-010i / I-010ai / I-010bi, 5 pages (2023: 4), AcroForm. 209 widgets / 197 names, the same topology as the 2025 blank (192 SAME + 1 changed: widget 33 /MaxLen 4, 2025: 5; page-5 SSN second widgets 2-3 pt left); against the 2023 pack 88 SAME, 53 moved, 2 changed page, 27 gone, 52 new. 202 line keys over 193 fields (205 of 209 widgets; line 17 has no widget), 17 identity mirrors, `cross_form` 1 == f1040.11 (the TY2024 Form 1040 prints AGI on line 11). Prose reverted to the 2024 face; four stale /TU strings (22, 25penalties, schdist, Line16aaa) listed in the banner. Verify PASS on provenance, widget dump, all five pages and every relation; four low findings were fixed: the banner's face-figures claim narrowed to what the knowledge pack carries ($700/$250, .03/$16,000/$480, the $1,500 blind worker maximum; .33, .05 and x 50% are face-only), the printed zero floors now declared with `max()` (9, 11, 22, Schedule 1 line 7, Schedule 2 line 5) plus 13 == sch1_9 (23 relations), the tax-year begin / end date comments say month and day only, and the MA 2023 separate-option gate failure seen in the tree was the tree's stale base (already fixed on main). Open, disclosed in the pack: lines 40 / 43 (comparison branches), 21 (spans widget-less line 17) and Schedule 2 line 8 -> line 18 (a text cell) carry no relation; the two date widgets have no tighter maxlen so a free-form "Jan 15" stays fillable; the knowledge pack lacks the .33 / .05 / x 50% rates.
    - **NE Form 1040N 2024 — DONE 2026-10-09** (`formpacks/states/ne/2024/f1040n`, a RE-MAP of the 2023 pack; TY2024 now has 27 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). revenue.nebraska.gov/sites/default/files/doc/tax-forms/2024/f_1040N.pdf (sha256 ad3550fd…, 232,602 bytes, PDF ModDate 2025-01-08), stamp 8-417-2024, 3 pages (2023: 2), AcroForm, no XFA. 151 widgets / 150 fields; against the 2023 pack 6 SAME, 32 MOVED, 2 CHANGED, 6 changed page, 97 GONE (renamed in place or re-numbered), 103 new. 149 lines bind 148 of 150 fields (62 money, 64 text, 23 checkbox); only the print / reset pushbuttons are unmapped. Page 2 re-laid out with seven new credit lines (28-31, 46-48) and the withholding split into lines 34-36, so lines are renumbered from 28 on; penalty, use tax, refund / direct deposit and signature move to page 3. Face deltas: standard deduction $8,350 / $16,700 / $12,250, exemption $166, Schedule I line 39. Verify PASS on provenance, widget dump, renders and every binding; three low findings answered with no pack change (the six SSN segments and High School District Code / 58a / 58c: `comb: true` is the filler's input contract, not a mirror of the widget bit, and the cross-pack convention is disclosed; the Wayback CDX capture count could not be re-checked while the Archive was offline, the SHA-1 itself recomputes; lines 55 / 56 print left-aligned because the DOR widgets carry no /Q and the schema has no alignment key). Open, disclosed in the pack: that alignment, the NE 2023 / 2024 / 2025 comb convention.
    - **DE PIT-RES 2024 — DONE 2026-10-09** (`formpacks/states/de/2024/pit_res`, a RE-MAP of the 2023 pack generated from the shipped 2025 sibling, since the 2024 blank already carries the 2025 structure; TY2024 now has 28 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). revenuefiles.delaware.gov/2024/PIT_2024_Forms/PIT-RES_2024-01_PaperInteractive.pdf (sha256 8c98cff7…, 553,120 bytes, created 2024-08-21), printed "Revision 20240821", 4 pages (2023: 3), AcroForm, no XFA. 198 widgets / 183 fields; against the 2023 pack 20 SAME, 74 MOVED, 56 changed page, 2 CHANGED, 24 GONE, 33 new widgets on 28 names; against the 2025 pack 166 SAME, 11 CHANGED, 2 GONE (ln08aColA/B), 1 MOVED (a kid-pairing artefact). 191 line entries over 180 fields / 195 widgets (only machPrintID and the print / reset pushbuttons unmapped), 12 relations, `cross_form` 1b == f1040.11. The 2024 revision inserted line 16 (active labor organization dues) and renumbered every later line and widget name by +1, added the pages-2-4 NAME / TAXPAYER ID header row (one field, three kids) and moved the amended return to page 4; 22 ReadOnly computed cells on 11 lines (4, 9, 10, 17, 19, 22, 23, 26, 33, 41, 42). Differences from 2025: ln12 is not ReadOnly, ln23 is, the three phone boxes keep /MaxLen 10, dmvStateID is not a comb, the line 60-62 Yes/No kids keep /YES / /NO. 180 of 180 sentinels audited on renders plus a second fill of the 11 unselected group options, 191 of 191 entries proven. Verify PASS on provenance, widget dump, line numbers and every binding; four comment-only banner fixes (the "formerly Form 200-01" claim dropped, the /Parent chain sentence corrected, line 48 added to the OMITTED relations, and the amendedChk script that also hides lines 41-47 disclosed) and the median-shift figure dropped. Open, disclosed in the pack: knowledge/states/de/2024.yaml names the balance-due / refund mailing lines 45 / 46 where the face prints 46 / 47 and prints the payment ZIP as 19899-508 (reported, not edited); the line-40 "page 3" cross-reference is the DOR's own printing; taxfill does not run the DOR amended-return show / hide script.
    - **MD Form 502 2024 — DONE 2026-10-14** (`formpacks/states/md/2024/md502`, a RE-MAP of the 2023 pack; TY2024 now has 29 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). marylandcomptroller.gov/content/dam/mdcomp/tax/forms/2024/502.pdf (sha256 e7250095…, 837,707 bytes, Last-Modified 12 Jun 2025; the old marylandtaxes.gov/forms/24_forms path 301s to a 404), "MARYLAND FORM 502 RESIDENT INCOME TAX RETURN 2024", stamp COM/RAD-009 08/24 on all four pages, AcroForm, no XFA. 175 widgets / 161 fields; against the 2023 pack 22 SAME, 120 MOVED, 6 CHANGED, 22 GONE, 19 new; against the 2025 pack 28 SAME, 115 MOVED, 7 CHANGED, 22 GONE, 17 new — but the 2024 face keeps the 2023 line numbers (1 through 51d) while the 2025 face adds 17c, 20a, 21b, 39, 42 and 51a and renumbers, so the 2023 pack is the base and every 2023 key is kept. 169 lines over all 161 fields (nothing unmapped; no ReadOnly, comb or pushbutton widget), 13 relations, `cross_form` 1 == f1040.11. The six 2023 filing-status fields became one six-kid "Check One Box"; the deduction method, the line-22 Maryland EIC pair and the 51a account type are two-kid fields; 51d name on the account now carries the NAME the 2023 blank gave the preparer's printed name ("Text Box 102", some 206 pt higher), so a name-only port would print the preparer on the bank row; line 39 lost its cents widget (the face prints "00"); 64 widgets gained /MaxLen 10 and the SSN boxes 9 (`ssn_digits_only`). Face deltas: 1e investment income $11,000 -> $11,600, line 49 reworded, year tokens moved; no line added, removed or renumbered. 161 of 161 sentinels audited on renders, plus a distinct-value fill and every option proven alone. Verify PASS, then three fix rounds: relation 48 == 46 - 47 and four banner corrections; `maxlen: 6` on the three line-49 boxes (a seventh digit is refused, not clipped), relations 15 (total subtractions) and exemption D == A + B + C, the /Ff and rect figures; then the Form 502LU note behind the "See instructions" on lines 6 and 15 (502LU 2024 prints its lines as Reserved, so both are plain sums this year) and line 17's conditional (17a - 17b only under the itemized method) stated. The reverify PASSed. Open, disclosed in the pack: the 1e key keeps the 2023 figure in its name; the md/2023 and md/2025 packs omit the same two sums (a separate, identical change); knowledge/states/md/2024.yaml does not record the $11,600 threshold the face prints (reported, not edited).
    - **ME Form 1040ME 2023 lines 21-23 re-bound — DONE 2026-10-14** (pitfall P-032; found by the JS5 1040ME 2024 port's semantic verifier on 2026-10-04 and re-created from its transcript after the scratch loss). Page 2 names three money widgets "1040ME Nonresident credit", "1040ME Total tax" and "1040ME Tax credits" and prints them rotated against those captions — "Total tax" on the row printed 21 NONRESIDENT CREDIT, "Tax credits" on 22 TOTAL TAX, "Nonresident credit" on 23 NONREFUNDABLE TAX CREDITS — so the 2023 pack's name-bound lines put a filer's line-21 amount in the line-23 box, 22's in 21's and 23's in 22's, while the relations 22 == 20 + 20a - 21 and 24 == 22 - 23, written against the keys, passed. The pack now binds the three lines by position as the 2024 and 2025 ports do (keys and relations unchanged, each comment naming the widget that merely sits on the row); test_me1040_lines_21_23.py pins the (key, widget) map offline for every shipped 1040ME year and reads the number printed left of each bound widget on the year's own blank; CONVENTIONS.md gains the rule "a widget's name is a hint, not a binding: bind by the caption printed on its row".
    - **MT Form 2 2025 line 10 floored at zero — DONE 2026-10-15** (found by the MT Form 2 2024 port's semantic verify). Line 10 prints "Subtract line 9 from line 8." with no floor, and the pack declared `10 == 8 - 9`; the 2025 instructions (Schedule III, Part I, printed page 30 of 42) say "Nonrefundable credits reduce the amount of tax you owe but cannot reduce your tax liability below zero", so a filer whose credits exceed the tax enters 0 on line 10 and that correct return FAILED verify. The relation is now `10 == max(0, 8 - 9)`, as in the 2024 port; test_mt_form2_line10_floor.py pins it on both years.
    - **OK Form 511 2024 — DONE 2026-10-14** (`formpacks/states/ok/2024/form511`, a RE-MAP of the 2023 pack generated from the shipped 2025 sibling body; TY2024 now has 30 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). oklahoma.gov/content/dam/ok/en/tax/documents/forms/individuals/past-year/2024/511-Pkt-2024.pdf (sha256 570f7186…, 1,786,828 bytes, Last-Modified 19 Nov 2025), the 52-page 2024 forms packet, return pages 42-51 (Form 511 pages 1-8 and Form 538-S pages 1-2), flat AcroForm, no XFA, no revision stamp. 328 widgets / 297 top-level fields; against the 2023 pack 163 SAME, 112 MOVED, 11 GONE, 4 changed page, 14 new; against the 2025 pack 289 MOVED, 4 GONE, 15 new. 313 fields, 24 relations, `cross_form` 1 == f1040.11. The 2024 face adds line 29 (homeschool credit, Form 591-D, plus a student-count box) and renumbers lines 30-42 by one, adds lines to Schedules 511-A / B / C and drops one 511-H organization (the total moves to line 4); several widget names survive with a new meaning (the "neighbour theft" list in the banner), so every binding was re-read by its printed row. Continuation headers mapped: `identifying_number_page2` / `f538s.identifying_number_page2` (SSN) and `name.full` / `f538s.name.full` (names), the latter two with upper-case Helvetica-10 budgets 43 / 50 because the blank's /DR has no /Cour; `mailing_address.country` maxlen 12, 538-S zip 11. 295 of 295 sentinels audited on renders. The first verify failed on the Courier-based name budgets (the blank's /DR has no /Cour, so the filler draws Helvetica) and on a mis-stated reason for omitting two multiply relations; fixed (budgets re-derived and probe-filled at the limit, relations 11 == 11.count * 1000 and 538-S 15 == 15.count * 40.0 declared), and the reverify PASSed. Open, disclosed in the pack: both 538-S occupation fields are deliberately unmapped (their widgets sit inside the signature boxes; the shipped 2023 pack still maps them there, a separate fix); `f538s.refund.send_as.debit_card` stays unmapped (the kid's /AS does not take /DebitCard); the /Cour-not-in-/DR Helvetica fallback is repo-wide.
    - **MT Form 2 2025 — DONE 2026-10-14** (`formpacks/states/mt/2025/form2`, a RE-MAP of the 2023 pack that is in fact a new map by widget position; TY2025 now has all 42 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). revenue.mt.gov/files/Forms/Montana-Individual-Income-Tax-Return-Form-2/2025_Montana_Individual_Income_Tax_Return_Form_2.pdf (sha256 4671aef6…6ba2b37, 425,811 bytes, stamp "2025v3 12/2025"), 10 pages, AcroForm, no XFA, encrypted with an empty user password. 351 widgets / 314 fields against the 2023 blank's 791 / 755: 42 field names survive (41 mapped ones moved /Rect, so each was re-read on the render), 713 of the base pack's mapped fields are gone with the forms they sat on, 285 widgets (272 fields) are new and all mapped. 313 of 314 fields bound (336 lines, 56 checkbox lines; only the "Clear Form" pushbutton is unbound). The 2025 face reaches federal taxable income first (line 1 from Form 1040 line 11b), prints one money column instead of Columns A / B, and carries its own Schedules I-V and 2EC. Filing status (the "Married Filing Jointly" kid is /2a) and the four-option residency status changed their on_states. 45 relations, `cross_form` 1 == f1040.11a. Digit combs are `comb: true`; the eight ratio boxes and the letter-bearing combs are maxlen-only; fills of ratios, rates and dashed UCRNs were rendered one character per cell. 313 of 313 sentinels audited on renders, pages 1-10 read. The verifier passed with three low findings, all fixed: the "Clear Form" census wording, the left-out relations list (2EC lines 22 / 30, Schedule IV line 1), and the `tax_calc.1 == 7` relation, which was dropped because the instructions' refund-only paths (ND Reciprocity, Nonresident Military Spouse, 30 Day Nonresident Exclusion) skip the page-2 worksheet and the relation gave a false failure there; the fix touched no binding. Open, outside the pack: knowledge/states/mt/2025.yaml words the Elderly Homeowner/Renter residency test "more than nine months" where the 2025 Schedule 2EC face prints "a minimum of nine months", and it records neither Schedule I Part II's $4,600 per-taxpayer MSA limit nor 2EC line 19's 12,600 standard exclusion.)
    - **ME Form 1040ME 2024 — DONE 2026-10-15** (`formpacks/states/me/2024/f1040me`, a RE-MAP of the 2023 pack whose page-1 / 2 / 3 body follows the TY2025 sibling, since the 2024 and 2025 pages line up to within 2 pt on 98-99 % of the printed words of pages 1 and 2; TY2024 now has 31 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). maine.gov/revenue/sites/maine.gov.revenue/files/inline-files/24_Form%201040ME_ff.pdf (the file name carries an encoded space; sha256 885c3844…, 1,931,026 bytes, Last-Modified 17 Jan 2025), "2024 MAINE INDIVIDUAL INCOME TAX / FORM 1040ME", barcode *2402100*, no revision stamp, 3 pages, flat AcroForm, no XFA. 129 widgets / 115 fields (2023: 129 / 114); against the 2023 pack 35 SAME, 66 MOVED, 1 changed page (line 18, now $5,000 at the head of page 2), 9 GONE, 10 new. 125 lines bind 112 fields (only the CLEAR / PRINT pushbuttons unmapped; no ReadOnly or comb widget). The refund-deposit block moved to the top of page 3 as lines 34c-34e (the DOR's own spellings "Rounting Number" / "Foriegn account" bound as spelled; Checking and Savings became two separate /Btn fields, group account_type), the underpayment penalty is now line 32 and the net overpayment line 33, line 35 is Total Amount Due, and the health-coverage block (kept from the 2023 pack) is renumbered 36a-36e; new line 17a. Lines 21 / 22 / 23 are bound by position, not by the widget names (P-032). `cross_form` 14 == f1040.11; relations as 2025 (16, 22, 24, 25f, 27). Sentinel audit 111 distinct fields over 125 lines, verify_fails [], pages 1-3 read, plus five extra rounds that put every other radio kid on a render. Two verifiers PASSed with no findings (provenance and widget dump; placement of every value on its printed row); a fixer round on the original 2026-10-04 build's verifier findings corrected the ZIP and foreign-province comments, the banner's /MaxLen paragraph and the two tax_period.begin TIGHTER_THAN_WIDGET reasons. Shared tables: filer_address_lines.json row (= the 2023 row), test_verify.py comment, TIGHTER_THAN_WIDGET rows for tax_period.begin.month / .day (pack 2, widget 10). Open, disclosed outside the pack: the ME 2025 pack banner still says the 2023 pack binds 21 / 22 / 23 by name (true when written; 585eb77 re-bound it), a comment-only follow-up.)
    - **IA 1040 2024 — DONE 2026-10-14** (`formpacks/states/ia/2024/ia1040`, a RE-MAP of the 2023 pack whose body follows the TY2025 sibling, since the 2024 blank is the 2025 return minus line 1f and Schedule 1 lines 14 and 18; TY2024 now has 32 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). revenue.iowa.gov/media/4090/download (sha256 5d758975…, 765,539 bytes, two downloads agree, "2024 IA 1040", stamps 41-001a to 41-001f), 6 pages, AcroForm, no XFA; media/4091 is the flat print variant with no fields. 247 widgets / 230 fields, all mapped (238 rows); against the 2025 pack 187 SAME, 43 MOVED, 6 GONE (1f and the two Schedule 1 lines, each with cents), 0 new; against the 2023 pack 22 SAME, 80 MOVED, 96 on another page, 19 GONE, 33 new widgets. Step 4 line 1 is now 1a-1e (`cross_form` 1a-1e == f1040.9 / .10 / .11 / .12 / .13, and 2 == f1040.15; six rules), 31 splits into 31a / 31b, the two line-35 method boxes are one field with two kids, and Schedule 1 is renumbered. 22 relations; line 12 is `12 == max(7 - 11, 0)` because the 2024 instructions (media/4152) keep the zero floor the face dropped, and `31a == max(30 - 22, 0)`. Sentinel audit 230 of 230 written on renders, verify_fails []. The verifier's FAIL on the line-12 floor was fixed (plus the 31a declaration, the format-script disclosure and three comment corrections (the Step 5 caption delta, the line-21 box width, the line-20 citation); no binding changed) and the re-verifier PASSed with no findings. Open, disclosed: line 34 is not declared, since the instructions add the 31b excess to line 34 on an amended return; Schedule 1 line 5 vs federal 6b is not in `cross_form` (a ref splits at its first dot, so `s1.5b` would be skipped at runtime); the page-4 header SSN widgets sit about 10 pt right of their printed cells (DOR geometry, one shared field, no pack key can move it). Outside the pack: the IA 2023 and 2025 packs carry the same unfloored `12 == 7 - 11` relation, and knowledge/states/ia/2024.yaml still places the low-income box "between Steps 4 and 5", cites "lines 25, 30, 31, 32", describes the school-district surtax as Step 6, says "Schedule 1 line 17b" (the 2024 Schedule 1 line 17 is one box) and cites media/4091.)
    - **KS K-40 2024 — DONE 2026-10-15** (`formpacks/states/ks/2024/k40`, a RE-MAP of the 2023 pack onto the TY2024 face, whose exemptions block is now priced in dollars; TY2024 now has 33 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). ksrevenue.gov/pdf/k-4024.pdf (sha256 f5198ecb…, 2,255,123 bytes, Last-Modified 21 Feb 2025, two downloads agree; a re-post of the July 2024 revision), "K-40 (Rev. 7-24)" / "2024", 2 pages, flat AcroForm, no XFA. 139 widgets / 139 fields (112 text + 27 checkbox; 2023: 134); against the 2023 pack 74 SAME, 32 MOVED, 1 CHANGED (the phone gains /MaxLen 10), 27 GONE (three old exemptions fields and dependent rows 2-7), 32 new, all mapped. The exemptions block is rebuilt (a Check One Box pair, joint $18,320 or single / separate / HoH $9,160, HoH $2,320, dependents x $2,320, disabled veterans x $2,250, Total Kansas Exemptions count and Total Kansas Exemption Amount); the dependents table has 6 rows (2023: 7); page-2 line 5 now reads the exemption amount. `cross_form` 1 == f1040.11; 4 relations (exemption total, 5 == that total, 6 == 4 + 5, 19 == max(0, 16 - 17 - 18)). Text maxlens re-measured at Courier 12; lines D and H of the Food Sales Tax Credit block retyped text -> money. Sentinel audit 139 of 139 on renders (every other group option over extra passes), verify_fails []. Three fix rounds, all re-checked on renders: the first after verify-sem / verify-place (residency geometry, 2-2-4 part-year blanks, D / H typing, line-33 / 34 geometry note); a second, comment-only (line-9 grid, text-layer wording, two stray periods, part-year and negative-slit comments), whose re-verifier FAILed on one low finding (the line-9 'six dividers inside the box' claim); and a third, comment-only, that re-measured the line-9 grid (five dividers inside the 106.5 pt widget, the sixth 1.5 pt past it, the seventh cell outside). The final re-verifier PASSed with no findings. Shared tables: filer_address_lines.json row (= the 2023 row), test_verify.py comment, two TIGHTER_THAN_WIDGET rows (42.school_district_number, 43.historic_site_number; pack 5, widget 10). Open, disclosed in the pack banner: the 2023 relation `12 == 8 + 11` is not carried because line 12 branches for nonresidents (house call, as in the 2025 sibling); the line-9 box prints a 7-cell grid wider than its plain right-aligned widget, so "100.0000" is one run over the cells, not one glyph per cell.)
    - **IN Form IT-40 2024 — DONE 2026-10-14** (`formpacks/states/in/2024/it40`, a RE-MAP of the 2023 pack onto the TY2024 face, built from the shipped TY2025 pack whose widget names this blank already carries; TY2024 now has 34 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). forms.in.gov/Download.aspx?id=16344 ("IT-40 (9-24) Fillable.pdf", sha256 40a74cf9…, 210,281 bytes, two downloads and a 2026-10-15 re-download agree), "Form IT-40" / "State Form 154" / "(R23 / 9-24)" / "2024" / due April 15, 2025, 2 pages, AcroForm, no XFA. 70 fields over 72 widgets (64 text, 5 single /Yes checkboxes, one 3-kid radio; 2023: 72 over 72); against the 2023 pack 0 SAME, 8 MOVED, 64 GONE, 64 NEW, all mapped, nothing left unmapped; against the TY2025 pack 47 SAME, 12 CHANGED (/MaxLen only), 11 MOVED (lines 1-11 sit 48 pt higher), counted per field (per widget 49 / 12 / 11 = 72). Line 22c "Account Type" is now one radio (Checking / Savings / Hoosier Works MC) rather than three separate boxes; line 8 prints 3.05% (2023: 3.15%), agreeing with the knowledge pack. `cross_form` 1 == f1040.11; 7 relations (3, 5, 7, 11, 14, 15, 26). Sentinel audit 72 of 72 on renders, three radio fills, verify_fails []. Two verification rounds, the second re-checked on renders by a re-verifier that PASSed. Shared tables: filer_address_lines.json row (= the 2023 row), test_verify.py comment. Open, disclosed in the pack banner: line 18 (`18 == 16 - 17`) is not declared as a relation because its operands are the conditional line 16 and the capped line 17 (the 2023 and 2025 packs omit it identically; a filer who skips to line 23 leaves 16, 17 and 18 blank together, so no amount lands wrong).)
    - **AL Form 40 2024 — DONE 2026-10-14** (`formpacks/states/al/2024/al40`, a RE-MAP of the 2023 pack onto the 41-page TY2024 booklet, which gained one Schedule OC page; TY2024 now has 35 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). revenue.alabama.gov/wp-content/uploads/2025/01/24f40.pdf (sha256 4f6c357f…, 2,199,984 bytes, two downloads agree), "FORM 40" / "Alabama" / "2024" / stamp "*24110140*", UltraForms AcroForm, no XFA. 2,288 mapped fields over a blank of 2,493 field names on 2,513 widgets (2,124 text, 190 checkboxes, 179 pushbuttons); of the 2023 pack's 2,260 mappings 2,257 widget names survive, 3 are GONE (CHECKOFF18 / CHECKOFF19, SCHOCLINE9PR) and 43 new Schedule OC names are all mapped; 26 data widgets stay unmapped (11 UltraForms barcode helpers UF_InfoA-K, 14 baked-in DOR banners and captions, Schedule A line 11 "Reserved for future use"). Page 1's keys are re-keyed to the printed numbers (5a, 5b, 20a, 20b, 21-34), fixing the defect the 2023 pack carried (P-031), as the 2025 port did; every set of alternative checkboxes now shares a `group`, each confirmed by filling every member on the render; Schedule DC prints 16 funds (2023: 18), Schedule OC Part Y is now the Volunteer First Responder Mileage credit with a new Part Z and the Capital Credit moved to Part AA. 63 text lines carry a budget below the widget's /MaxLen plus four boxes with no /MaxLen (PRESEMPNAMEADR2, the second Schedule KRCC-I copy's 3a / 3b / 3c), each confirmed by a fill on the render; 8 relations; `cross_form` empty. The 72 mapped widgets that ship Hidden|Print (/F 6) stay mapped under P-027 and the filler un-hides them. Two verification rounds, the second re-checked on renders by a re-verifier that PASSed (8 findings: 5 fixed, 3 disclosed; the header's false "comb cells" clause was dropped after a census found 0 of 2,513 widgets with the Comb bit). Shared tables: filer_address_lines.json row (= the 2023 row), test_verify.py comment, test_readonly_widget_mapping.py row (583), test_pack_maxlen.py rows, test_scaffold_state_year.py (the newest AL base below 2025 is now 2024). Open, disclosed in the pack banner (NOT RESOLVED): three DOR rectangles overprint printed text and the pack schema has no rect / inset / alignment key to move them (page 1 COUNTRY starts about 10 pt left of the Foreign Country rule, so "Canada" reads "C|anada"; page 2 Part IV line 4 FEDTXINC's last digit touches the "a" of "as reported"; Schedule KRCC-I's ending-year box starts on the printed "0" of "20"), all three unchanged from the 2023 blank; Schedule DC row o prints "Department of Mental Health – 2023" on the 2024 face, as written. Not touched: the live 2025 pack's "Money vs text" header repeats the same false comb clause (its blank was not censused).)
    - **VT Form IN-111 2024 — DONE 2026-10-14** (`formpacks/states/vt/2024/in111`, a RE-MAP of the 2023 pack ported from the TY2025 pack's position-and-label table, the two blanks carrying the same 89 field names; TY2024 now has 36 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). tax.vermont.gov/sites/tax/files/documents/IN-111-2024.pdf (sha256 7a6744b2…, two downloads agree), "2024 Form IN-111" / Rev. 10/24 / scan lines "*241111100*" and "*241111200*", AcroForm, 2 pages. 99 widgets on 89 names (2023: 109) with 85 mapped lines; of the 2023 pack's 92 mappings 47 kept their rect, 7 moved, 4 changed /MaxLen or /DA, 1 changed page and 33 are GONE, against 28 new widgets (27 names). THE TRAP (P-001): Line21, Line22, Line29, Line30 and Line31 survive by name but print different lines, because the face inserts a new line 21 (child care contributions) and renumbers everything after it; every one is bound by the line printed beside it. Line 15 is now two boxes either side of a printed decimal point (15.whole / 15.decimal), the fifteen signature-date cells became five single "Date (MMDDYYYY)" boxes, the four voluntary funds are in a third order (24a Children's Trust, 24b Veterans, 24c Green Up, 24d Nongame), and a new FARMER / FISHERMAN box is mapped. Face figures: standard deduction 7,400 / 14,850 / 7,400 / 11,100 / 14,850, line 5e $5,100; `cross_form` 1 == f1040.11. 14 relations (the five floor / cap lines and 29 == 27 - 28a - 28b included; lines 8, 12, 16, 21, 22, 27 and 30 deliberately omitted, each with its reason). Two verification rounds, the second re-checked on renders by a re-verifier that PASSed (audit: 85 mapped, 0 verify fails; 4 findings fixed in the banner and relations, 1 rejected and disclosed). Shared tables: filer_address_lines.json row (= the 2023 row), test_verify.py comment, test_pack_maxlen.py rows (15.whole, 15.decimal, the 911 street and Foreign Country boxes at 28, the five date boxes at 8). Open, disclosed in the pack banner: Sig-SP-Phone's rect sits 2 pt higher than its row-mates (the schema has no rect override; value not clipped), and Line11 / Line12 are 62.0 / 60.8 pt wide and hold 8 of /MaxLen 9 digits. Knowledge mismatches reported, not edited (`knowledge/states/vt/2024.yaml`): "$4,850 per exemption" (face $5,100), the QW standard deduction "the same $14,050" (face $14,850), and the extra standard deduction "$1,150" vs "+$1,200".
    - **MI-1040 2024 — DONE 2026-10-15** (`formpacks/states/mi/2024/mi1040`, a RE-MAP of the 2023 pack onto the 2024 three-page face; TY2024 now has 37 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). michigan.gov/taxes/-/media/Project/Websites/taxes/Forms/IIT/TY2024/MI-1040.pdf (sha256 5ba97732…, 502,185 bytes, linked URL and bare path agree), "Michigan Department of Treasury (Rev. 04-24)" / "2024 MICHIGAN Individual Income Tax Return MI-1040" / due April 15, 2025 / scan lines "2024 05 01/02/03 27", AcroForm, 3 pages, no XFA, encrypted with an empty user password. 95 widgets on 88 fields (2023: 95 widgets on 86 fields; the filing-status split adds two), all 95 at the identical /Rect except the 32a / 32b boxes (1-2 pt taller); of the 85 mapped 2023 names 56 survive and 29 are GONE; 28 are pure renames at the identical position and the 29th, 'Filing status', split into three single-widget fields (renames, page 1: the 5b spouse box, the spouse full-name box, the 8a-8c residency boxes, the 9a-9d counts and 9a-9f totals, the 9e dependent box and "line 10"; page 2: 31a / 31b -> 32a / 32b; page 3: Text1-6 and three preparer boxes). The filing status split from one three-kid /Btn into three single-widget fields with the same on-states (group 7_filing_status). 88 lines on 87 data fields, line keys identical to the 2023 pack; the Reset button and the FSSN repeats on pages 2-3 stay unmapped. Face figures: exemptions $5,600 / $3,300 / $500 / $5,600, rate 4.25%, EITC 30% of the federal credit; `cross_form` 10 == f1040.11. 5 relations (12, 24, 27b == 27a * 0.30, 33, 37). Two verification rounds; second round: semantic verifier low findings, placement verifier PASS on renders; the fixer's changes (27b relation, banner, test comment) were checked by its own audit re-run (bindings and renders unchanged), not by an independent re-verifier (sentinel audit: 84 lines mapped, 87 fields written, 0 verify fails). Open, disclosed in the pack banner: the line 9f sum is not declared as a relation because the relation grammar cannot tokenize the `9a_amount` .. `9e_amount` keys, its omission is the house style for a sum the grammar cannot express. Shared tables: filer_address_lines.json row (= the 2023 row), test_verify.py comment. Knowledge check: `knowledge/states/mi/2024.yaml` agrees with the face, no mismatches.)
    - **CO DR 0104 2024 — DONE 2026-10-15** (`formpacks/states/co/2024/dr0104`, a RE-MAP of the 2023 pack onto the 8-page 2024 face; TY2024 now has 38 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). tax.colorado.gov/sites/tax/files/documents/DR_0104_2024.pdf (sha256 24ea1546…, 1,181,586 bytes), "DR 0104 (10/15/24)" / "2024 Colorado Individual Income Tax Return" / "Page 1 of 8" / barcode stamp 240104 19999, AcroForm, 8 pages, no XFA. 150 widgets on 122 fields (2023: 98 on 90); all 90 mapped 2023 names are GONE (opaque TextNN ids became descriptive "Form Question N" names), so every row was re-bound by position and printed label and the line keys are this face's printed numbers. 122 of 122 fields mapped; new: the five-row dependents block (30 fields) and money lines 5, 18 and 29; line 8 Other Additions (2023 line 7) is a money widget beside its explain box; the two line-25 boxes keep their 2023 keys although the DOR names their widgets "C7 - Deceased Dependent 6/7", and the 2023 DR 0108 box has no successor; the name / SSN header is one field painted on all 8 pages, so header_name is dropped. Residency C1 / C2 / C3 are plain /Btn fields (C1 / C2 group residency_status, C3 Abroad an independent flag); direct deposit RB1-RB3 and third-party designee RB4 / RB5 are grouped radio-style sets. 11 relations (9, 11, 15, 20, 30, 34, 36, 37 == max(0, 36 - 20), 39, 40 == max(0, 20 - 36), 44); `cross_form` 1 == f1040.15 and 31 == f1040.11. Two verification rounds, the last a read-verify that PASSed (sentinel audit: 118 mapped lines, 122 fields written, 0 verify fails; all 44 money lines confirmed on 170 dpi renders). Verifier finding fixed in comments only: the line 34 and line 43 widget tooltips are DOR copy errors ("lines 30 through 33" vs the printed 31 through 33; line 42's caption repeated on 43) and the printed caption governs. Open, disclosed in the pack banner: `31 == f1040.11` fails on a return that leaves the TABOR block empty, and a correct negative line 1 fails the `1 == f1040.15` leg; grouping C1 / C2 is the 2025 pack's choice, supported by Book 104. Shared tables: filer_address_lines.json row (= the 2023 row), test_verify.py comment. Knowledge check: `knowledge/states/co/2024.yaml` agrees with the printed TABOR tiers, no mismatches.)
    - **CA Form 540 2024 — DONE 2026-10-15** (`formpacks/states/ca/2024/form540`, a RE-MAP of the 2023 pack onto the 2024 six-side face; TY2024 now has 39 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). ftb.ca.gov/forms/2024/2024-540.pdf (sha256 7729c31d…, 231,837 bytes; independent downloads agree), "TAXABLE YEAR 2024 / California Resident Income Tax Return / FORM 540", footers "333 3101243 Form 540 2024 Side 1" .. "Side 6 Form 540 2024 333 3106243", AcroForm, 6 pages, no XFA. 180 widgets on 162 fields (2023: 180 on 167); all 167 mapped 2023 names are GONE (the FTB prefixed every name with "540-" and renumbered the ids), so every row was re-bound by position and printed label: Sides 1-3 reuse the 2025 pack's entries with the "540-" prefix (149 of its 169 fields match by nearest rect and full name, against 135 of the 2023 pack's 167) and Sides 4-6 were rebuilt from the blank's own widget dump. 171 lines bind 179 of 180 widgets; the one unbound widget is line 74's ReadOnly 540-3014, which now prints "Reserved for future use". Re-authored by the FTB: filing status is one radio field with five kids (2023: five checkboxes), line 113 one radio, the account-type, Yes/No and use-tax radios name their kids after the captions (both kids of every one bound); contribution codes 440 and 444 are gone and 431 and 447 are new (mapped), so line 110's relation sums 18 codes. Face figures: exemption credits $149 / $461, standard deduction $5,540 / $11,080, line 32 AGI threshold $244,857. New lines: 91.no_use_tax_owed, 431, 447, the 116 / 117 account-type kids, health_care_coverage.yes, third_party_designee.allow_yes; dropped: 74, 440, 444 and the two single account_type keys. 19 relations (78 omits 74), 8 groups, `cross_form` 13 == f1040.11. Verify, fix and re-verify rounds, the last a PASS on an independent render (sentinel audit: 160 mapped lines, 161 fields written, 0 verify fails; every sentinel read on its printed row on all 6 sides). Verifier findings fixed in comments only (the apt / PMB budget clips at the 13th digit in all three boxes, "STE 1234ABCD" loses part of its last glyph in all three, the layout-diff wording). Open, disclosed in the pack banner: the three Apt. / PMB boxes lost their 2023 /MaxLen, so each carries a budget of 12 measured in digits, which is not a guarantee for wide capitals (verify's 0.5-em clipping scan flags none of those fills). Shared tables: filer_address_lines.json row (= the 2023 row), test_verify.py comment. Knowledge check: `knowledge/states/ca/2024.yaml` agrees with every printed figure, no mismatches.)
    - **CA Form 540NR 2024 — DONE 2026-10-15** (`formpacks/states/ca/2024/form540nr`, a RE-MAP of the 2023 pack built from the shipped 2025 pack, because the 2024 blank already carries the 2025 "540NR_form_*" widget names; TY2024 stays at 39 jurisdictions, CA already counted; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). ftb.ca.gov/forms/2024/2024-540nr.pdf (sha256 9190db55…, 220,604 bytes; independent downloads agree), "TAXABLE YEAR 2024 / California Nonresident or Part-Year Resident Income Tax Return / FORM 540NR", footers "333 3131243 Form 540NR 2024 Side 1" .. "Side 6 Form 540NR 2024 333 3136243", AcroForm, 6 pages, no XFA. 181 widgets on 165 fields (2025: 183 on 169); all 169 mapped 2023 names are GONE, and against the 2025 pack 148 mapped widgets are SAME, 5 CHANGED, 10 MOVED (the Side 6 block by 35-36 pt) and 6 GONE. 172 lines bind 164 of 165 fields; the one unbound widget is line 84's ReadOnly 540NR_form_3018, which now prints "Reserved for future use" (left unmapped, so the line-88 relation omits 84). Re-authored by the FTB: the two direct-deposit account-type pairs of checkboxes became radios (kids /0 Checking, /1 Savings, bound as 126 / 127.account_type.checking / .savings), filing status is one radio with kids /0../4, Side 4 prints codes 410 and 425 (mapped) and drops 448 / 449, and Side 6 has no paid-preparer name / phone row. Face figures: exemption credits $149 / $461, line 39 AGI threshold $244,857. New lines vs 2023: 431, 447, the 126 / 127 account-type kids, health_care_info.yes / .no, third_party_designee.yes; dropped: 84, 440, 444 and the three single keys they replace. 18 relations, `cross_form` 13 == f1040.11 and f1040nr.11. Verify, fix and re-verify rounds, the last a PASS on an independent render (sentinel audit: 162 lines written, 164 fields written, 0 verify fails; every sentinel read in its printed box on all 6 sides); the three low findings (two census / word-shift figures, the 54.int alignment note) were fixed in comments only. Open, disclosed in the pack banner: the Apt. / PMB boxes have no /MaxLen, so each carries a budget of 12 measured in digits (a probe fill clips the 13th), which is not a guarantee for wide capitals; the shipped 2025 540NR pack budgets 13 on the same rects and font and probably needs the same cut to 12. Shared tables: filer_address_lines.json row (= the 2023 row), test_verify.py comment. Knowledge check: `knowledge/states/ca/2024.yaml` agrees with every printed figure, no mismatches.)
    - **CA Schedule CA (540) 2024 — DONE 2026-10-15** (`formpacks/states/ca/2024/sched_ca_540`, a RE-MAP of the 2023 pack onto the six-side 2024 face, carried from the shipped 2025 pack because the 2024 blank already uses the 2025 naming scheme; TY2024 stays at 39 jurisdictions, CA already counted; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). ftb.ca.gov/forms/2024/2024-540-ca.pdf (sha256 e6efd18c…, 165,808 bytes; independent downloads agree), "TAXABLE YEAR 2024 / SCHEDULE CA (540) / California Adjustments — Residents", footers "7731243 Schedule CA (540) 2024 Side 1" .. "Side 6 Schedule CA (540) 2024 7736243", AcroForm, 6 pages, no XFA. 250 widgets on 250 fields, all mapped (240 money / 9 text / 1 checkbox; the 2023 blank has 247 fields, 246 text + 1 button); all 247 mapped 2023 names are GONE (the FTB prefixed every id with "540ca_form - "), but 243 of the 247 sit at the identical rect, so rows were re-bound by position and printed label. Side 2 gains line 8v (digital assets received as ordinary income, three new boxes, mapped) and the 8z row moves down 24 pt and is renumbered, so the surviving ids 2034-2037 mean different lines than in 2023. The two SSN / ITIN boxes now carry /MaxLen 12 (2023: none), so their pack maxlens are 12. Face figures: line 29 thresholds $244,857 / $367,291 / $489,719, line 30 standard deduction $5,540 / $11,080. New line vs 2023: 8v; none dropped. 19 Part II relations (4A, 5d, 7 / 10 / 14 / 17 per column, 18, 22, 25, 26, 28; zero floors on lines 4 and 25), `cross_form: []` as in 2023 and 2025; Part I totals and Part II lines 3, 5e, 8e, 24, 29 and 30 are left undeclared, each with its reason in the banner. Verify, fix and re-verify rounds: both verifiers PASS on independent renders (sentinel audit: 250 lines written, 0 verify fails; every sentinel read on its printed row and column on all 6 sides). All three low findings from the last verifier round were fixed: (1) no relations declared although the Part II chains are single-column, fixed by declaring the 19 relations (added after that round, so they were not independently re-verified; each was re-read against the face text of Sides 5 and 6 and every operand key checked against the pack); (2) and (3) are comment-only: (2) warns that the line 8a / 8d / 8s column-A boxes already print "( )", so enter a positive amount, and (3) gives the measured width of the five description boxes (no /MaxLen). Shared tables: filer_address_lines.json row (empty, as in 2023 and 2025), test_verify.py comment. Knowledge check: `knowledge/states/ca/2024.yaml` agrees with the standard deduction and the AGI thresholds, no mismatches; it does not record the line 5e cap.)
    - **CA Schedule CA (540NR) 2024 — DONE 2026-10-15** (`formpacks/states/ca/2024/sched_ca_540nr`, a RE-MAP of the 2023 pack onto the five-side 2024 face, carried from the shipped 2025 pack's widget table re-keyed to the 2024 ids; TY2024 stays at 39 jurisdictions, CA already counted; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). ftb.ca.gov/forms/2024/2024-540nr-ca.pdf (sha256 42d85891…, 212,179 bytes; independent downloads agree), "TAXABLE YEAR 2024 / SCHEDULE CA (540NR) / California Adjustments — Nonresidents or Part-Year Residents", stamps "7741243 Schedule CA (540NR) 2024 Side 1" .. "Side 5 … 7745243", AcroForm, 5 pages, no XFA. 418 widgets (411 text + 7 button) on 414 fields (2023: 411 widgets); all 411 mapped 2023 names are GONE (the FTB prefixed every id with "540NR CA - " and renumbered them: the six residency checkboxes became two radio fields, so later Side 1 ids are the base id minus 4), so every row was re-bound by widget position and printed label. 416 lines (374 money / 35 text / 7 checkbox) bind 409 of 411 text widgets plus all 7 buttons; the two unmapped widgets are the only ReadOnly ones, Section C line 22 and Part III line 8d ("Reserved for future use"; the class-3 exclusion, as in the 2025 pack, with the reason for keeping 22 excluded despite line 26's range recorded in the banner). Section B lines 1 and 2a moved to the foot of Side 1, line 8v (digital assets, five columns) is new, grid money boxes now carry /MaxLen 11 (2023: 12), and the Part I date boxes are 8-cell combs with the slashes printed between cells, so 15 keys are `comb: true` (value MMDDYYYY; fill_form refuses a slashed date). Face figures: Part III line 29 thresholds $244,857 / $367,291 / $489,719, line 30 standard deduction $5,540 / $11,080. New keys vs 2023: B8v_A..E; none dropped. 30 relations (the 2023 pack declared none): Part II line 27 per column and the single-box Part III / IV sums, each left-out sum with its reason in the banner. Verify, fix and re-verify rounds, the last verifier a PASS on an independent render (sentinel audit: 412 mapped / 412 written, 0 verify fails); the nine low findings were fixed in comments and banner, plus 15 further relations added in the last fix pass (checked by a relation harness on a blank, a consistent and a perturbed return, not re-verified by an independent verifier). Disclosed in the pack banner: the second printed slash of each date comb falls inside the first year digit's cell, so that digit touches the slash by about 1 pt (blank geometry); the parenthesised 8a / 8d / 8s boxes take positive amounts. Repo-wide follow-up: the 2023 and 2025 Schedule CA (540NR) packs and both Schedule CA (540) packs word the left-hand "a" box on lines 2-6 as the taxable amount, but the 2024 instructions make it the federal 1040 line 2a-6a figure; and the 2023 / 2025 Schedule CA (540NR) packs ship no relations. Shared tables: filer_address_lines.json row (empty, as in 2023 and 2025), test_verify.py comment. Knowledge check: `knowledge/states/ca/2024.yaml` agrees with the standard deduction and the AGI thresholds, no mismatches; it does not record the line 5e cap.)
    - **MT Form 2 2024 — DONE 2026-10-15** (`formpacks/states/mt/2024/form2`, a RE-MAP of the 2023 pack that is in fact a new map by widget position, because 2024 is Montana's first simplification year; TY2024 now has 40 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). revenue.mt.gov/files/Forms/Montana-Individual-Income-Tax-Return-Form-2/2024_Montana_Individual_Income_Tax_Return_Form_2.pdf (sha256 126be01d…cfbdee6, 536,013 bytes, stamps "2024v5" / "11/2024"), 12 pages, AcroForm, no XFA, AES-256 encrypted with print allowed. 587 widgets / 545 fields against the 2023 blank's 791 / 755: 42 field names survive (all moved /Rect), 712 of the base pack's mapped fields are gone with the forms they sat on, 517 widgets are new. 568 lines over 544 fields (56 checkbox lines); only the "Clear Form" pushbutton is unbound. The 2024 face starts from federal AGI (line 1 from Form 1040 line 11), prints one money column, uses the five federal filing statuses ("Married Filing Jointly" really carries /2a) and carries Schedules I-V, 2EC and a Transition Schedule. Residency keeps three options but its on_states change to /Resident /Part-year Resident /1; the page-12 "Type of Adjustment" kids are cross-labelled and keyed by printed label. 63 relations, `cross_form` 1 == f1040.11; lines 3, 7 and 10 are floored at zero on the 2024 instructions' authority (the face prints no floor). Digit combs are `comb: true`; ratio boxes, state codes and the dashed UCRN / JGI boxes are maxlen-only. The semantic verifier returned FAIL with one high, one medium and two low findings, all fixed in the pack (the high one: line 10 had no zero floor, so a correct return whose Schedule III credits exceed line 8 failed one of its two relations; now `10 == max(0, 8 - 9)`); the fixes touched banner comments and that one relation, and the re-verifier passed (bindings and renders unchanged). Open, outside the pack: the live TY2025 pack (`formpacks/states/mt/2025/form2/pack.yaml`) carries the same unfloored `10 == 8 - 9` and needs the same one-relation fix, which the 2025 Schedule III instructions' sentence supports. Shared tables: filer_address_lines.json row (the four mailing_address lines), test_pack_maxlen.py rows (two page-2 printed-name boxes), test_verify.py comment; the existing MT adjudication rows in test_pack_invariants.py cover this pack, their deceased and residency wording extended to 2024. Knowledge check: `knowledge/states/mt/2024.yaml` agrees with the face, no mismatches.)
    - **WV IT-140 2024 — DONE 2026-10-15** (`formpacks/states/wv/2024/it140`, a RE-MAP of the 2023 pack onto a renumbered page 2 and Schedule M; TY2024 now has 41 jurisdictions; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). tax.wv.gov/Documents/PIT/2024/it140.2024.pdf (sha256 1b9a3c71…1261, 2,524,481 bytes; independent downloads agree), page 1 prints "IT-140 F", "2024" and scan line P40202401F with no revision stamp, 45 pages, AcroForm with document JavaScript, AES-256 with print allowed. 643 widgets / 556 names against the 2023 blank's 640: of the 377 widgets the 2023 pack mapped, 222 kept name and /Rect, 116 kept the name but moved, 39 are gone; 46 are new (44 mapped, two "Click here to go to Form IT-140" pushbuttons not). 378 lines over 384 widgets (397 field entries); 54 mapped ReadOnly widgets, each with its own calculate script. Page 2 gained a line-12 penalty box and line 21 A/B/C (property-tax credits) and renumbers 2023 lines 12-26 by one or two; Schedule M renumbers +2 (27-59 become 29-61) and line 34 gained a 34(c) cell, so a surviving widget name such as M29A now sits on a different printed line and every key was re-bound by /Rect. Dropped keys: preparer.not_efile and heptc.8.yes/no (box or widget gone from the face) and preparer.signature (an /FT /Sig widget that the 2023 pack mapped as text; fill_form writes a /V no viewer renders, so it is left for a hand signature). Schedule H now maps the disabled taxpayer's SSN and the physician's state and ZIP. 5 relations plus cross_form 1 == f1040.11; line 28 is deliberately not declared, because a balance-due filer who donates breaks 28 == 25 - 26 - 27. RECAP line 18 prints "(§11-21-26)" on the rendered face while the text layer drops the digits (settled on a 200 dpi render). The semantic and placement verifiers' low findings (preparer EIN / telephone print in the Printed Name band, tax_method nonresident box offset 10 pt from its square, recap.25 and the extended-due-date dropdown overlap) are recorded as field comments; the one medium (signature) was fixed and the re-verifier passed. Open, outside the pack: the TY2023 WV pack still maps preparer.signature as text onto the same /Sig widget, and no test asserts that a mapped field is not /FT /Sig; `knowledge/states/wv/2024.yaml` says the new refundable property-tax credits go on the Recap Schedule, but the face claims them on IT-140 line 21 A/B/C (summed into line 23), and it quotes "Child and Dependent Care Credit" where RECAP 18 prints "Child and Development Care Credit". Shared tables: filer_address_lines.json row (the five mailing_address lines), test_pack_maxlen.py (name.suffix), test_readonly_widget_mapping.py (54 computed ReadOnly widgets and the line-6 default), test_verify.py comment.)
- [ ] **JS6 — Nonresident / part-year state returns (old J4 = C2)** (XL, per pack) [PJ-16]
  - **Phase K (2026-10-09):** AL 40NR, AZ 140NR, AZ 140PY and DE PIT-NON 2023 land through **JK0** if the wave re-creates them and they pass KG1; the three CT forms and the part-year allocation golden are **deferred (on demand, Phase K re-plan)**; JK1 closes this box.
  - 9 discovery rows were recovered (wf_fe623a11-933).
  - Pack the AcroForm rows at TY2023 first, each re-checked against its recorded sha256: AL 40NR, AR1000NR, AZ 140NR, AZ 140PY, CO DR 0104PN, DE PIT-NON.
  - The three CT forms go through JS4 or hand-fill manifests.
  - **Acceptance, per pack:** as JS5, plus a part-year allocation golden.
  - *Progress (2026-10-02):* the six AcroForm rows run as a resumable wave (new-pack builder mode: the state's resident
    2023 pack is a conventions reference only; each pack ships with a part-year probe — a consistent synthetic
    allocation that verifies, then one broken input that must fail).
    - **CO DR 0104PN 2023 — DONE 2026-10-02** (`formpacks/states/co/2023/dr0104pn`, a NEW schedule pack of the DR 0104).
      tax.colorado.gov/…/DR0104PN_2023.pdf ("DR 0104PN (11/08/23)"), 46 fields / 59 widgets, all mapped: the name and SSN
      fields each carry one widget per page header (one write fills all three), lines 1-3 are four-option radios, and
      lines 4-36 alternate a Federal and a Colorado column. Six relations from the face plus cross_form legs 4 = f1040.1z,
      22 = f1040.10, 24 = f1040.11 and 36 = dr0104.11; the probe's consistent part-year return verifies, and one
      changed Colorado-column input fails exactly its relation.
    - **AR1000NR 2023 — DONE 2026-10-02** (`formpacks/states/ar/2023/ar1000nr`, a NEW nonresident / part-year return).
      dfa.arkansas.gov's 2023 AR1000NR (footers R 7/3/2023 … R 7/5/2023, barcodes ITNR231-233), 3 pages; a flat AcroForm
      with generic widget names ("ARNR-1-5"), so every row was bound by position against the printed label. Each income
      line carries a total column and an Arkansas column (keys .a / .c), and lines 38a-38d apportion the tax by the
      Arkansas-income ratio. 20 relations from the face; the probe's consistent part-year return verifies, and a changed
      38a or 8.c fails exactly its relation.
    - **DE PIT-NON 2023 — DONE 2026-10-14** (`formpacks/states/de/2023/pit_non`, a NEW nonresident / part-year return; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). revenuefiles.delaware.gov/2023/PIT-NON_2023-01_PaperInteractive.pdf (sha256 0646ee65…, 535,354 bytes, created 2023-11-13), "Revision 20231113", 3 pages, AcroForm, no XFA. 186 widgets / 177 fields; 174 lines bind 174 fields, with only the print / reset pushbuttons and the ReadOnly machPrintID margin id unmapped. Page 1 is a two-column table (A = FEDERAL, B = DELAWARE SOURCE) for lines 1-29 with the single-cell allocation lines 30a and 30b; page 2 prorates the tax on line 42 (30a / 30b) and the 43a / 43b credits; page 3 is the amended-return block, hidden until the form's script shows it. Seven shared radio groups, each option bound to its printed label by /Rect; 40 ReadOnly calculated cells, all class 4. 25 relations from the face (the proration decimal is text, so line 42 and 43a / 43b products are not declared), no cross_form legs (Column A is headed only "FEDERAL"). The probe's consistent part-year return verifies 25 of 25; a changed 42 Box A fails exactly its relation, and a changed line-1 Delaware cell fails exactly line 15. The verifier's findings were fixed: the mailing block now routes amended returns by lines 71 / 72 (PO Box 508 / 8710, all other amended returns 8711) as page 3 and the instructions print them. Open: knowledge/states/de/2023.yaml still keys its mailing addresses off lines 59 / 60 only and prints the ZIP as "19899-508" (the blank prints 19899-0508). TY2023 now has 45 state packs.)
    - **AZ Form 140NR 2023 — DONE 2026-10-15** (`formpacks/states/az/2023/az140nr`, a NEW nonresident return; TY2023 stays at 42 jurisdictions, AZ already counted; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). azdor.gov/sites/default/files/2023-12/FORMS_INDIVIDUAL_2023_140NR_f.pdf (sha256 c7b67205…, 349,610 bytes; independent downloads agree), "Arizona Form 140NR / Nonresident Personal Income Tax Return / FOR CALENDAR YEAR 2023", footers "ADOR 10177 (23)", AcroForm, 6 pages. 379 widgets on 360 field names (276 text, 103 button, none ReadOnly); 364 pack lines bind 358 of them, with only "Filing Status" and the cmdPrintForm pushbutton unmapped. Lines 15-24 are a two-column table (FEDERAL | ARIZONA, keys .federal / .arizona) and the name and SSN boxes carry one widget per page header; the ratio boxes 27 and 8C are `text`, comb: false. 31 relations from the face (23 per column; 87 declared as max(0, 67 + 85 - 70), which holds on both the tax-due and the overpayment path) plus the cross_form leg 25 == f1040.11. A synthetic nonresident return verifies, and a changed Arizona-column 15 or 24 fails exactly its relation. Open points, disclosed in the banner: Filing Status (lines 4-7) is a radio whose four kids carry no /AP, so it is ticked by hand; the name and relationship boxes use the width / 5 maxlen convention. Engine change landing with the pack: that same field made pypdf's get_fields() raise KeyError('/AP'), so `filler._field_names` and `verify.pdf_field_dicts` fall back to a field-tree walk for exactly that error (`scaffold_state_year` triage uses it too; 3 new tests in `test_apless_radio_fallback.py`).
    - **AZ Form 140PY 2023 — DONE 2026-10-15** (`formpacks/states/az/2023/az140py`, a NEW part-year resident return; TY2023 stays at 42 jurisdictions, AZ already counted; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). azdor.gov/sites/default/files/2023-12/FORMS_INDIVIDUAL_2023_140PY_f.pdf (sha256 082ee7ac…, 376,871 bytes; independent downloads agree), "Arizona Form 140PY / Part-Year Resident Personal Income Tax Return / FOR CALENDAR YEAR 2023", footers "ADOR 10149 (23)" / "ADOR 10413 (23)", AcroForm, 6 pages. 436 widgets on 418 field names (324 text, 112 button, none ReadOnly); 419 pack lines bind 415 of them, with only "Filing Status", "Res Status" and the cmdPrintForm pushbutton unmapped. Lines 15-24 are a two-column table (FEDERAL | ARIZONA, keys .federal / .arizona); line 27, the Arizona income ratio, is `text`, comb: false; the name and SSN boxes carry one widget per page header. 32 relations from the face (23 per column) plus the cross_form leg 25 == f1040.11. A synthetic part-year return verifies 32 of 32, and a changed Arizona-column 15 or 20 fails exactly its relations. Open points, disclosed in the banner: Filing Status (lines 4-7) and Residency Status (lines 12-13) are radios whose kids carry no /AP, so both are ticked by hand and a fill reports success with them blank; nine single checkboxes carry no /AP and rely on the viewer drawing the cross; the name and relationship boxes use the width / 5 maxlen convention (a long mixed-case name can clip). Knowledge gaps not edited here: knowledge/states/az/2023.yaml lacks the 140PY line map (exemptions at 46-49, Dependent Tax Credit at 59), the line-27 ratio, the line-37 25% subtraction and the page-6 $2,500 pension cap. The Form 140NR engine fallback (`filler._field_names`, `verify.pdf_field_dicts`) covers this blank's /AP-less radios; only its docstrings changed. TY2023 now has 47 state packs.)
    - **AL Form 40NR 2023 — DONE 2026-10-15** (`formpacks/states/al/2023/al40nr`, a NEW nonresident return; TY2023 stays at 42 jurisdictions, AL already counted; reconstructed from its build transcripts after the 2026-10-04 scratch loss and re-verified on renders). revenue.alabama.gov/wp-content/uploads/2024/03/23f40nr.pdf (sha256 a41dd6a3…, 1,799,044 bytes; independent downloads agree), "FORM 40NR Alabama 2023 Individual Income Tax Return NONRESIDENTS ONLY", scan lines 2311014N / 2300024N, 35 pages (a two-page return plus the booklet of fill-in schedules and forms), flat AcroForm with document JavaScript, UltraForms SDK. 1,987 widgets; 164 are JavaScript pushbuttons (print / reset / GoTo, 50 UF_L* barcode slots, VERCTRL, 35 printlid covers), left unmapped; 1,786 of the other 1,823 widgets are mapped, one line each (1,537 text, 89 money, 160 checkboxes), and 23 names are instruction panels, captions and UF_Info stamps, not taxpayer lines. Page 1 carries three income columns (A Alabama tax withheld, B All Sources, C Alabama Income; keys .a / .b / .c) and line 10 is the Alabama percentage. 28 relations from the face; a synthetic return verifies 28 of 28, and a changed 5.c fails exactly 7.c == 5.c + 6.c. The NOL-85A copies on pages 20-29 are covered by NoView + Print lids spanning 72.6-83.1% of the page, which P-027b hides. Open points, disclosed in the banner: CKNRA (the "NRA" box beside filing status 3) ships checked and printable with no group, so a caller whose spouse is not a nonresident alien must write false; 522 ReadOnly form-computed fields stay mapped for the caller to write; 68 boxes are held tighter than the widget's /MaxLen and 33 carry a measured maxlen on widgets with none; several left-aligned cells start on a printed bullet (cosmetic); the allocation lines (line 10, Part IV line 3, the dollar-times-percentage products) carry no relation. cross_form is empty (the face cites no federal line). TY2023 now has 48 state packs.)
- [ ] **JS7 — TY2026 state sprint** (XL, per pack; external: states' 2026 blanks, Dec 2026 – Feb 2027)
  - Re-triage from each state's NEWEST shipped base (`--base newest`), after the federal JT6.
  - **Acceptance, per pack:** as JS5; the re-triage table is committed.
  - **Phase K (2026-10-09): re-scoped** → **JS7a** (the JK9 tier-1 states, each port behind the JK10 label-adjacency guard) and JS7b (every other state: fallback-only, deferred on demand). TY2024 leftovers no longer fold in. This box closes with JS7a.

**Not scheduled** (backlog; disclosed as not modeled):
*(Phase K priority 5, 2026-10-09: unchanged.)*

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
- **2026-10-09:** the remaining open items are re-homed in Phase K (its tables, Deferred and Dropped lists). The "D2 → … JS7" route above no longer holds: the TY2024 → JS7 fold is dropped 2026-10-09 (see Phase K, Dropped); D2's remainder is deferred on demand.

## Phased sequencing (recommended order)

> **Superseded 2026-10-09 by Phase K** for every open item; kept as the record of the Phase J order.

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
     *(2026-10-09: this fold is dropped; see Phase K, Dropped.)*

**Tranche size.** Every tranche is at most about a day of work (M). Multi-pack tranches commit per pack. So a spend-limit death costs at most one sub-tranche.

**Parallelism.** The default is one tranche at a time, because the spend limit kills wide fleets. When budget allows, these touch disjoint files and may run alongside the JF/JR tranches:
* JT0a–c;
* JA1;
* JEa/b.

JT6 pre-empts everything when `check_finals` reports the finals. By the 2025 precedent that is late Dec 2026 – Feb 2027 (an inference).

**No remaining item needs a new heavyweight dependency:**
* the overlay filler exists (branch `phase-j2-overlay` → JS4a–d);
  *(2026-10-09: merged by JS4a; the branch was deleted in JD2.)*
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
