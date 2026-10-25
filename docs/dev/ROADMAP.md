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

Done and on `main` (**15,143 tests** — offline 11,645 + live-.gov 3498; derived
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
network tests quarantined until 2027-01-11 (twenty since 2026-10-23: JK27's and JK28's signature sweeps add two MA cases each, and JK28's measured text budgets six). The 2026-10-19 run was red on two upstream revisions of pinned blanks: Oregon re-issued the 2023 OR-40
(an accessibility re-tag that replaced two radio fields with checkboxes) and the IRS re-created the 2026 Form 1040-X draft
(10/9/26: line 22's direct deposit dropped, page 2 renumbered). JK29 (2026-10-23) re-mapped both packs. The next run (dispatched 2026-10-23) passed its network tests; its drift job failed only on
uscode.house.gov links while that site runs in a temporary format, all 18 quarantined under JK30 (2026-10-24).

> **Status (2026-10-15):** JK2 landed (978fc2f): the MN booklet citations re-pointed, fetch and finals-watch retries,
> a CI blank cache and the ten MA quarantine rows. The scheduled runs of 2026-10-19 and 10-26 are the proof; issue #3
> closes after the first green one. The code CI (ci.yml) is green.

- **M0 scaffold · M1 engine · M2 federal packs · M3 intake + knowledge · M4 MCP
  server (23 tools, stdio, image content) · M5 state support · M6 code/docs.**
- **MCP server — 23 tools, CI-gated** (`packages/mcp-server/tests/test_server_e2e.py:408` asserts exactly
  23, and CI's offline suite runs it): list_forms, get_form_map, fetch_blank, fill_form, verify_form,
  verify_filing, render_form (vision Image), calc, residency, intake_checklist,
  list_document_kinds, extract_document, workspace_save, workspace_load,
  workspace_record_position, workspace_reconcile, state_scope, estimate_refund,
  compare_scenarios,
  get_sources, filing_summary, file_and_pay, hand_fill_worksheet (print-only
  states). The `calc` tool carries **40** deterministic ops (`packages/mcp-server/tests/test_skills_sync.py:55` pins the count; Phase J added 8 without adding an MCP tool): the 25 of Phase H (tax, tax_with_preferential_rates, standard_deduction, se_tax, additional_medicare_tax, niit, taxable_social_security, excess_ss, student_loan_interest_deduction, education_credits, ptc_annual, ptc_monthly, child_tax_credit, eitc, dependent_care_credit, treaty_benefit, schedule_1a_deductions, employee_fica, estimated_tax_safe_harbor, annualize_ytd, contribution_limits, ira_contribution_eligibility, marginal_dollar_savings, magi_ladder, state_tax), Phase I's seven (ira_pro_rata, roth_conversion, hsa_deduction, espp_disposition, capital_loss_limitation, foreign_tax_credit_election, foreign_asset_reporting) and Phase J's eight (withholding_projection JP1c, elective_deferral_room JP2, ira_net_income_attributable JR2a, ira_recharacterization JR2b, charitable_deduction JF9, paystub_to_w2 JP3b, claim_of_right_repayment JP4, underpayment_penalty JP5a).
- **Phase B — single-user completeness: DONE.** `extract_document` (W-2,
  1099-NEC/MISC/INT/DIV/G/B/R, SSA-1099, 1095-A, 1098-T/E, 1042-S, and — since
  2026-08-10 — **Schedule K-1 (Form 1065)**, with per-field provenance — and, since Phases I2/I3/I5, 1099-SA, 5498-SA, 3921, 3922, 1099-K, 1099-Q, W-2G, 1095-B, 1095-C, 5498, K-1 (1120-S) and K-1 (1041), since JR2c the IRA custodian statement, since JF8 Form 1098-VLI, and since JP3a the pay stub: **29 kinds** per `list_document_kinds()`) and the resumable
  workspace (`workspace_*` tools + `taxfill purge` CLI, generated RECONCILIATION.md
  / CHECKLIST.md) are implemented, merged, and tested.
- **Federal form packs — priority set DONE.** **115 packs across 2019–2025**
  (2019:1, 2020:1, 2021:1, 2022:5, 2023:35, 2024:35, 2025:37, plus 36 TY2026 planning packs: 151 `pack.yaml` in all — f1040nr +
  Schedule OI joined 2024 on 2026-08-10, and the 2026-08 batch backfilled the
  rest of the 2023 set into 2024/2025: identical-topology ports off the 2023
  packs, digests pinned to the year's blanks, vision-audited page by page). M2 base
  set + Schedule SE/D/E + Form 8863 + Form 2555 all ship (2023), audited, golden;
  + **all four Phase-D new form types** — **Form 4868** (extension), **Form 1040-ES**
  (estimated-tax vouchers), **Form 1040-X** (amended return; TY2023-2025 map the current Rev. 12-2025 since JK27,
  the revision an amendment filed now uses), and
  **Form W-7** (ITIN application, Rev. 12-2024) — all audited.
- **Repo-wide pack gates — every rule now covers the packs it claims to.**
  `test_pack_invariants.py` (2026-08-21) sweeps all **281** packs, federal (151) and
  state (130), for `cross_form` target resolution, the checkbox-`group` rules,
  identity page mirrors and year tokens in line keys;
  `test_readonly_widget_mapping.py` does the same for ReadOnly bindings (**3,810**
  across 25 state packs, pinned per pack by count; 1,390 across 11 at the 2026-09-24 count — J0 re-pinned AL-40 2023 580→568 and
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
  verify. The re-map and URL-dead rows the JS5 ports and JK0 did not reach are deferred (on demand, Phase K re-plan).
- **State credits — DONE for all 42 jurisdictions** (41 income-tax states + DC):
  every `knowledge/states/<st>/2023.yaml` carries a cited `credits` block (**177**
  entries; the 2024 and 2025 packs carry 182 and 187); `state_scope` surfaces them as `benefits_candidates`.
- **Drift CI — DONE** (restored 2026-08-10 after a spell as workflow_dispatch-only,
  i.e. never running). `freshness.yml` runs `scripts/check_drift.py` (form-blank
  SHA256 + source URLs + mailing addresses) AND the live-.gov golden round-trips
  weekly, in its own workflow so monitoring failures never repaint the code badge.
- **Pack-authoring CLI — DONE.** `taxfill introspect <blank.pdf>` emits a pack
  skeleton (`packbuild.py` + `cli.py`), tested.

**Form packs that can be FILLED today (introspect→vision-map→adversarial-audit→
golden):** federal — f1040, f1040-NR, f8843, Schedule 1/2/3/A/B/C/OI/SE/D/E/8812,
Schedule A (1040-NR), Schedule NEC, Forms 8863, 2555, 4868, 1040-ES, 1040-X, W-7,
8959, 8960, 8962, 2441, 843 (Rev. 12-2024), 8316, 8606, 8889, 8949, 8833, 1116, 8938, 5329 (2023–2025), Form 2210 and Schedule 1-A (2025), and FinCEN 114 as a hand-fill worksheet. state — **all 42 income-tax
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
scripts/sync_doc_counts.py); JK1 (2026-10-15) re-derived the unanchored ones from disk: the calc ops
(40, pinned at packages/mcp-server/tests/test_skills_sync.py:55), the document kinds, the federal pack
summary, the pack-gate sweep, the pinned ReadOnly bindings and the state credits.

---

## History

The completed phases — 0, E, F, G and I — moved VERBATIM to [`docs/HISTORY.md`](HISTORY.md) (now `docs/dev/HISTORY.md`) on 2026-09-28 (Phase J JD2), so this file carries the open work. Their cross-references ("see Phase G", tranche ids) resolve there. Phases C, D and H stay here: each still has a box open under a Phase J tranche. *(C and D closed 2026-10-15; see the next paragraph.)* In the commit that lands the 2026-10-09 re-plan (Phase K JK1), the completed Phase J tranches follow them verbatim, under "Phase J — completed tranches"; their ids resolve there too.

Since 2026-10-15 (Phase K JK1) Phases C and D hold no open box: C2 and D2 are closed as deferred (on demand, Phase K re-plan), each keeping its "Left" list here, and their progress notes moved verbatim to HISTORY.md ("Phase C / D — progress notes"). JS2c (done), JS5 and JS6 (deferred) moved to HISTORY.md's Phase J Block 7.

## Phase K — Pointer-first re-plan (approved 2026-10-09)

> **Decision (the user, 2026-10-09; the rebuilt draft reviewed and committed 2026-10-15; record: [ADR-0001](adr/ADR-0001-pointer-first.md)).** TaxFill points an agent at the right official form, rule and figure. Packs stay for **high-volume, current-year forms only**: a PDF field name → printed line map cannot be derived safely at use time (the ME 1040ME 2023 pack had lines 21-23 rotated one box, and every relation still passed). Calc ops and relation verify stay. The new order:
> 0. let the running recovery wave finish re-creating and integrating its 23 packs (sunk cost: 6 had a pack on disk, 17 survived only as replay logs; KG1 applied to each — **done 2026-10-15, all 23 landed**), then **stop** TY2024-and-earlier state backfill and the rest of JS6 except on demand (see the on-demand rule under Deferred);
> 1. **release** (Phase A: PyPI, tag, `.mcpb`, demo, acceptance; user-held steps stay the user's);
> 2. **TY2026 readiness**: federal finals Dec-Feb (JT5g/JT6); JS7 cut down to the high-volume states (JS7a), with the rest using the fallback;
> 3. a **no-pack fallback fill path** for the long tail: introspect the official blank, anchor fields to printed labels, fill and verify at use time, label confidence honestly, and never claim filing-grade;
> 4. **slim the knowledge layer** to pointers, verbatim quotes and the figures calc ops read. Narrative duplicates official text and drifts: JS2c logged 25 mismatches, all in narrative or figures calc does not apply (ROADMAP JS2c; the applied figures are calc.py:10985-11019; `tax_line` and every `tax.notes` entry are still emitted in calc output at :11037-11042, so JK23/JK26 cover them); *(2026-10-15: JS2c is done and its box is in HISTORY.md; new mismatches go to a JK27-style fix tranche.)*
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
| KG9 | User-held steps stay the user's: the PyPI publisher/token, the mcp<2 decision, the v0.1.0 tag and upload, the demo GIF, the acceptance tester, branch protection (JD2.3), the JT6 early-flip policy, the rendering of RI-1040's edge-to-edge boxes (JEe: dependent dates of birth, middle initials, suffixes, signature and preparer dates), and the DC exception named in Phase J's "The external gates are" list (below, in Phase J; "any DC exception before 2026-10-15"; what it is was not found in the repo — the user confirms it or lets it lapse). |
| KG10 | Public repo: demo personas only. This covers the sample W-2, the journey goldens, benchmark fixtures and pilot forms. |
| KG11 | Refuse what cannot be anchored. In unmapped mode `fill_form` refuses any value whose target widget is anchored `none`, and `low` unless the user confirms that field on the rendered page (a per-field override recorded in the response). Refused fields come back as "hand-write these". |

**Collision order** for Dec 2026 – Mar 2027: JT6 > JS7a (+ JK10 label-adjacency guard) > the fallback (JK16-JK18) > the knowledge layer. Release support (JK7, JK12) takes the next free slot. A dated tranche never interrupts one in progress.

**Calendar** (latest starts; the RC date is under agent control, the upload date is the user's):

| Date | What |
|---|---|
| 2026-10-12 | weekly freshness run (freshness.yml:30); expected red on MA until JK2 |
| 2026-10-14 / 10-15 | **done:** JK0, JK0a, JK2, JK3, JK4, JA1 |
| 2026-10-15 | TY2025 extension deadline. v0.1 cannot meet it because JA2 is user-held, so its TY2025 audience is late filers, amended returns and rehearsal users |
| 2026-10-16 | JK1 (lands with the user's OK on this re-plan), JS2c close-out — **both done 2026-10-15** |
| 2026-10-21 / 10-23 | JK5 dry run / **release candidate ready**; the upload waits only on JA2 — **JK5 done 2026-10-16**: the RC is main at 050e84d and the A6 flip waits on branch `release/a6-flip` |
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
| 1 | JS2c close-out | S | JK0 | — | **done 2026-10-15** |
| 2 | JK1 ROADMAP truth-up + backfill freeze | S | JK0, JS2c | other workflow idle | **done 2026-10-15** |
| 3 | JK2 Honest health signal (MA red, finals retry) | S–M | — | the 10-19 / 10-26 scheduled runs | **done 2026-10-15** |
| 4 | JK3 JF5a MFS follow-ups, verify first | S | — | — | **done 2026-10-15** |
| 5 | JK4 CI runner + action pins | S | — | — | **done 2026-10-15** |
| 6 | JA1 Phase A agent half (trimmed) | M–L | — | — | **done 2026-10-15** |
| 6a | JK27 Fix wave: the defects the JK0 verifiers and the JK6 / JK21 goldens found | M–L | — | — | **done 2026-10-16** |
| 7 | JK5 Release-candidate dry run | M | all done (JK27 2026-10-16) | — | **done 2026-10-16** |
| 7a | JK28 JK27's and JK5's open follow-ups: NR/PY form citations, signature lines, unmeasured budgets, IA line 12, workspace paths, page-header mirrors, state credits, the SSN comb | M | — | — | **done 2026-10-23** |
| 7b | JK29 Freshness drift fix: OR-40 2023 re-issue, 2026 Form 1040-X draft re-post, comb boxes whose printed separators take cells | S–M | — | — | **done 2026-10-23** |
| 7c | JK30 US Code citations while uscode.house.gov runs in a temporary format | S | — | the site restored, or the quarantine expiry | 2026-12-15 |
| 7d | JK31 Quote fix wave: the JK23 first report's mismatches | M | JK23 | — | after JK25 (value fixes stay allowed in the freeze) |
| 8 | JK6 Five journey goldens | M | JA1.3 | — | **done 2026-10-15** |
| 9 | JA2 Phase A user half (+ JD2.3) | user | JK5 | the user | user's call (RC 2026-10-23) |
| 10 | JK7 A6 flip + `.mcpb` on the release | S | JA2 upload | PyPI upload | upload + 1 day |
| 11 | JK13 Fallback surface + guardrail ADR | S | — | user accepts or amends | **done 2026-10-16** (ADR-0002 Proposed) |
| 12 | JK14 Introspect + pack-less fetch | M | JK13 | — | **done 2026-10-24** |
| 13 | JK15 Anchor + blind benchmark (DONE 2026-10-24) | L | JK14 | — | 2026-11-16 |
| 14 | JK21 Golden-diff harness over every tool | M | — | — | **done 2026-10-15** |
| 15 | JK20 Hoist citations into `sources` | M | JK0, JS2c (done), JK21 | — | **done 2026-10-24** |
| 16 | JK22 Drop never-read TY2025 blocks (zero-output) | M | JK20, JK21 | — | **done 2026-10-24** |
| 17 | JK16 Pack-less fill | L | JK14, JK15 | — | 2026-11-23 |
| 18 | JK8 Watch coverage | M | JK2, JK9 (state rows) | — | **done 2026-10-24** |
| 19 | JK9 Tier-1 state triage table | S–M | JK0 | IRS SOI state data | **done 2026-10-24** |
| 20 | JK10 Label-adjacency guard (base pack + every port) (DONE 2026-10-25) | M | — | — | 2026-11-30 |
| 21 | JEe Text width vs widget padding (agent half done 2026-10-24) | M | JK0 | the user: RI edge-to-edge boxes | 2026-11-30 |
| 22 | JK17 Pack-less verify + grade label | M | JK16 | — | 2026-11-30 |
| 23 | JK23 Quote-verbatim checker (report mode) | M | — | — | **done 2026-10-24** |
| 24 | JK24 Schema v2 models + dual loader | M | JK20, JK21 | — | **done 2026-10-24** |
| 25 | JK25 2026 scaffold emits v2 (optional) | S | JK24, JK23 | — | **done 2026-10-24** |
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
- **JS2c — DONE 2026-10-15** (closed by JK1; its box moved verbatim to HISTORY.md, Phase J Block 7). JK0's nine knowledge corrections landed 2026-10-15 (AL AZ CO DE IA MD MT VT WV, each re-checked against the cited booklet); the MN 2025 line-11 caption was decided no change, and its one other open item, wv/2025's widowed-spouse disabled veteran entry (it repeats the Recap Schedule attribution JS2c corrected for 2024), moved to JK27.
- [x] **JK1 — ROADMAP truth-up and the backfill freeze — DONE 2026-10-15** (S; deps JK0 committed and the other workflow idle; latest start 2026-10-16) — the swap landed in 2ec411a, and the truth-up re-derived the unanchored "Where we are" counts from disk (calc ops 35 → 40, pinned at test_skills_sync.py:55, not :54; document kinds 28 → 29; federal packs 111 → 115 for 2019–2025 plus 36 TY2026 planning packs; the pack-invariant sweep 172 → 281; pinned ReadOnly bindings 1,390 across 11 packs → 3,810 across 25; state credits ~174 → 177). JS2c closed done and JS5, JS6, C2 and D2 closed deferred (on demand, Phase K re-plan) with their Left lists; JS2c, JS5 and JS6 moved verbatim to HISTORY.md's Phase J Block 7, and the C2 / D2 progress notes to its "Phase C / D — progress notes".
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
- [x] **JK27 — Fix wave: the defects the JK0 verifiers and the JK6 / JK21 goldens found — DONE 2026-10-16** (M–L; before JK5) (KG2) — every item is fixed with a test that fails before and passes after, or closed with a written reason; the four strict xfails in test_journeys.py are ordinary tests now. Built in five verified fix chains plus the main loop; each chain's adversarial verifier passed.
  - **Privacy.** A refusal no longer echoes the absolute path of the installed data directory: `datadir.display_path` renders it relative to the data root (discovery, handfill, knowledge, sources, the pack schema; test_message_paths.py).
  - **Crashes.** NM: the 12 New Mexico citations the Citation model rejected (2023-2025) point to .gov pages, so filing_summary and file_and_pay answer for NM 2025; two sweeps replace the host allow-list that hid it (every citation-shaped mapping in every state pack validates as a Citation; file_and_pay and filing_summary run on all 126 packs). FL: state_scope raised a ValidationError for every Florida resident in every year, because the no-income-tax list cited floridarevenue.com; it now cites the Florida Constitution (Art. VII, s. 5(a), flsenate.gov) and names the revenue site in its reason. The JK21 goldens had stored all three crashes as answers: `test_no_snapshot_records_a_crash_as_the_answer` fails any golden that stores an error other than a refusal.
  - **Amended returns.** file_and_pay and filing_summary model them (manifest flag `amended`; a form number ending in X counts without it). A Form 1040-X follows the current instructions, Rev. December 2025, whatever year it amends: the 1040-X Where To File table (a Georgia resident mails to Austin 73301-0052, not the Form 1040 box), the check to "U.S. Treasury" enclosed loose with no voucher, the completed and updated Form 1040 behind it (new in that revision), the refund by check on paper, the 3-year / 2-year claim window. A state amendment follows the pack's `amended_return` block, written for Georgia 2023-2025 from each year's Form 500X, IT-511 and 525-TV (PO Box 740318; line 38, 2023: line 37, "Pay in full with this Return", with the UET, late-payment and interest lines the filer adds; the 525-TV with its "Amended Return" box, which the JK6 xfail had wrongly called a defect; the 3-year claim and 180-day federal-change rules); a state without one gets no address, voucher or due date, and a pointer to the DOR. **Revision decision:** a TY2024 or TY2023 amendment filed now uses Rev. December 2025 (a continuous-use form whose instructions "can be used with the December 2025 and later revisions" and work their examples on a 2024 return), so the f1040x 2023 and 2024 packs map that blank: QBI on line 4a, and line 4b held at 0 before 2025 by three relations. Recipe B5 in SKILL.md. The final adversarial review (five lenses over the merged diff) then found the 1040-X checklist dropping what the Form 1040 one does: it now sends a W-7 package to the ITIN Operation with the W-7 signed, carries the §6013(g)/(h) statement and Pub 519's amended-return steps, marks the updated return of a dual-status year, and gives a paper 1040-NR amendment the instructions' p. 2 procedure (name, address and TIN only on page 1; "Amended" across the new return). Amended names are read from the whole form number ("MI-1040X-12", "IA 1040X", "1040 X" and Unicode dashes; not "511-TX"), only a Form 1040-family item gets the 1040-X checklist, and a state without amended rules is pointed at its revenue department's home page (a vetted map of all 42; the first cut guessed it from citation hosts, several of them file CDNs). A narrow re-verification then added: file_and_pay takes `today` as filing_summary does, so a year outside "the current or two prior tax periods" is told to file on paper and a passed claim window says so; a postponed due date (TY2019, TY2020) moves the window; Nebraska's 1040XN and Rhode Island's RI-1040X-R/-NR read as amended; and a revised Form 8606 filed "with Form 1040-X" may leave its address blank.
  - **Verify false failures.** IA 1040 2023 and 2025 floor line 12 at zero (the 2023 face prints the rule; the 2025 instructions keep it). Forms 8843, 8606 and 5329 declare their "fill in your address only if you are filing this form by itself" boxes as `standalone_only_lines`: in a filing that holds a Form 1040, 1040-SR, 1040-NR or 1040-X a blank there passes the identity and confirmed-address checks, a filled one is still checked against the confirmed current address and any form mapping the same line, and a form verified alone, or beside only a claim (Form 843) or an ITIN application (W-7), still needs its address. Mutation tests hold each of those rules.
  - **Wrong pointers.** get_sources builds a state's block from the requested year's own pack (`taxfill_core.state_sources`, shared with the generator); a year with no pack gets the newest pack's sources and a note naming its year. The goldens snapshot get_sources in every year. VA: state_scope adds a pack's `forms.citations.<role>`; VA 2023-2025 cite the Form 760PY instructions and return for a part-year filer and Form 763's for a nonresident.
  - **Follow-ups.** WV 2023 preparer.signature and nine Arkansas AR1000F 2023-2025 signature keys no longer bind /FT /Sig widgets (a written value never prints there), with a repo-wide sweep test; OK 2023's Form 538-S occupation keys are unmapped (their widgets sit in the signature row); the CA 540NR Apt. / PMB budget is 12 in every year (a 13th digit clips); the ME 2025 banner, MT 2024/2025's "at least nine months" (Schedule 2EC; MCA 15-30-2338), WV 2025's widowed-spouse credit on IT-140 line 21 box B, and calc's dependents refusal (IL named only for 2023) are corrected; IA 2023-2025 knowledge places the low-income box and the line-19 surtax as each face prints them, with the instructions' older wording kept as quotes. Found on the way and fixed: HI 2024's food/excise and renters credits said "nine months during 2023", and the pack carried the 2023 pack's labels throughout: its due date read 2025-04-22 where the 2024 N-11 and N-15 instructions say April 21, 2025, and its mailing and deadline citations named form lines 7 and 10. Two refusals still named a home-folder path (list_forms' missing-formpacks error, the offline-fetch cache hint); they show the data-relative name or `~` now, with the $TAXFILL_DATA_DIR hint. And a release blocker the ADR-0002 review surfaced: verify_overlay converted its render to a Pillow image, which taxfill-core does not depend on (it reached the dev environment through reportlab), so on a clean install every Hawaii N-11 overlay check raised ImportError; it reads the bitmap buffer now, mapped from the CropBox, and test_no_pillow_at_runtime.py runs the real verify with Pillow removed.
  - **Left open, with reasons (not defects fixed here; items 1, 3 and 4 are JK28):** (1) 41 TY2025 packs name a part-year or nonresident form but carry no `forms.citations` for it (NY IT-203, MD 505 among them): the mechanism is in place, each needs a sourced citation (JK27 fixed VA, the one a journey found; JK28). (2) The source-registry generator keeps the first description per (topic, url) and drops the differing ones (86 / 215 / 233 in the 2023 / 2024 / 2025 packs before JK27; 88 / 221 / 236 after, JK27's GA, HI, NM and VA edits adding the difference); merging them changes routing in many states, so it moves to JK20 (citations into `sources`), whose box now carries it. (3) KS K-40, KY 740, MO-1040 and IL-1040 2025 map ink-signature lines onto ordinary text widgets, so a typed name would print there; whether that is acceptable is a question for each face and its instructions (JK28). (4) 1,590 text lines in 123 packs carry a maxlen on a widget without /MaxLen; only the 11 CA address rows are render-measured (JK28). (5) realfile.tax.newmexico.gov does not serve every year's files (the 2023 and 2024 names answer 404 while 2022 ones answer 200), so the NM 2025 citations may need re-pointing if their files drop; check_drift flags it. (6) The IA 2023 / 2024 / 2025 instructions still print wording their faces dropped ("line 17b", "between Steps 4 and 5"); the packs quote it beside what the face prints.
- [x] **JK28 — JK27's and JK5's open follow-ups — DONE 2026-10-23** (M; no deps) (KG2) — every item is fixed with a test that fails before and passes after, or closed with a written reason. Built 2026-10-16 in nine adversarially verified chains; that session ended before integration (the machine slept), so on 2026-10-23 the verified trees were integrated, the page-header mirrors finished (a fix round, a sweep over every pack that repeats a header, and the follow-ups the sweep found), the exemption credits extended past California, and a three-lens final review run (no blocker or major; its minors fixed).
  - **NR / PY form citations.** All 41 remaining TY2025 state packs (VA since JK27) carry `forms.citations.part_year` and `.nonresident`: the role's own who-files sentence quoted verbatim with its printed page, plus the role's form or schedule, every PDF fetched twice with matching sha256. NJ's `part_year_or_nonresident` text is corrected. In PA, MI, GA and NJ the `forms` block sits after `all_citations`, so the source registry's first-description-wins rule (JK20) does not displace another block's route. Four group test modules and test_state_role_citations_nrpy_gate.py (every TY2025-and-later pack, one rule set) hold them.
  - **Signature lines on text widgets.** A sentinel typed into each candidate box printed on the signature rule, and the instructions require a signature ("Your income tax return must be signed", KS; "Each return must be signed by the taxpayer", KY; "the paid preparer must also sign and date your return", IL). So 16 keys are dropped: KS K-40 2023-2025 and KY 740 2023-2024 `signature.taxpayer`, `signature.spouse` and `preparer.signature`, and IL-1040 2025 `preparer_signature`. MO-1040 2023-2025 keep `t.signature` / `t.spousesignature`: the face reads "By signing or entering my name in the “Signature” field(s) below" (§143.561 RSMo), and a pack comment tells the agent to leave them blank unless the filer asks. MO gains `signature: {page: 5}` and IL-1040 2023-2025 `signature: {page: 2}`. test_signature_line_mapping.py sweeps every pack and hand-fill worksheet.
  - **Unmeasured text budgets.** The tier-1 TY2025 census found 26 text lines whose pack maxlen sits on a widget without /MaxLen (the 1,590 figure above counted every pack and year). Each was probe-rendered at 600 dpi and pinned in MEASURED_WITHOUT_MAXLEN, now a record of budget, width, size, face, probe and fit (58 rows).
  - **IA 1040 line 12.** A relation may end in ` unless <checkbox line>`: verify reports it SKIPPED while that box is checked on disk, it never fails `ok`, and the MCP summary lists the skipped checks under their form. The clause is validated at load and refused in `cross_form`. IA 1040 2023-2025 guard `12 == max(7 - 11, 0)` (the Income Tax Reduction Worksheet, 41-146) and `8 == d` (the filer who claims only the Iowa EITC and is told to "Skip lines 5 through 19") with the Step 5 box `alt_tax_method`.
  - **Paths.** Decision: results keep absolute paths, because an agent hands them to its own file tools and many of those take only absolute paths. Every tool and CLI path argument, and the TAXFILL_WORKSPACE, TAXFILL_BLANKS_CACHE and TAXFILL_DATA_DIR settings, accept `~/...`. A refusal that only names a path shows the home folder as `~`. docs/USER_GUIDE.md's privacy section states it.
  - **Page-header mirrors.** A pack declares `mirrors:` (templates over its own lines: `{line}`, `{line[a:b]}`, `[optional]`) and `mirror_abbreviations`. fill_form builds every mirror the caller leaves out (`mirrored`) and measures it against its box with real glyph widths (taxfill_core.textfit): a name too wide is abbreviated as the pack allows, with an informational warning, or left blank with a "hand-write it" warning. verify_form and verify_filing check every declared mirror in the identity section, and get_form_map shows them. 56 packs declare 367 mirrors: CA 540/540NR 2023-2025 (the JK5 defect), federal f8863, f8949 and the 2026 Schedule E Part V, and AL, CO, DE, GA, IA, ME, MS, NC, NJ, OH, OK, PA, RI, VA and WI. GA 2023's SSN_COPY, which had shipped blank on pages 2-5 and 7-28, is mapped. The pack gate requires every mirror-shaped line, by key or AcroForm field shape, to be declared or listed in NOT_A_MIRROR: Schedule E 2023-2025 page 2 and AL's page 4 and Schedule HOF print "Do not enter name and social security number if shown on other side". Pitfall P-034.
  - **State exemption credits.** `tax.exemption_credits`, with calc `state_tax`'s new `exemption_credit_counts` and `federal_agi`, returns `exemption_credits`: each line's credit, the total after any AGI rule, and the tax after credits. `tax` keeps its meaning, and a state without the block is byte-identical. CA 2023-2025 (lines 7-11, the line 32 AGI Limitation Worksheet, line 33); TY2025 AR, DE, IA, NE and OR, with OR's AGI ceilings as `agi_ceiling` (OR-40 instructions pp. 17-18) and DE's line 32 limited to the tax. OH, KY, AZ, ME and UT are closed: none has a per-person exemption credit (the reasons are in test_state_exemption_credits.py).
  - **SSN comb offset.** Fixed rather than closed: fill_form narrows a written comb widget to the grid its printed separators imply (P-033; the blank's vector strokes, comb widgets only) and reports `combs_aligned`. Over the 2,229 comb widgets of 265 cached blanks it moves exactly the 22 federal SSN boxes whose dots crossed a digit: 2023-2026 Form 1040 and 1040-X own and spouse, 2023/2024 dependents, and line 26. Pale tinted cell outlines (DE, IA, IL, LA, MA, OR, VA) are left as printed.
  - **W-2 code titles by year.** The 2019-2026 Instructions for Forms W-2 and W-3, each fetched twice, show F and S gaining the Roth SEP / Roth SIMPLE words in the 2025 edition, not in 2023 as this box assumed. M's closing period (2019-2024) and P's "or intelligence community" (2026) vary too. V25 shows the W-2's own year's title. Code II starts with the 2024 W-2 (the table had dated it 2019), so V22 now flags II on a 2019-2023 W-2.
  - **Left open, with reasons:** (1) 1,545 text lines in 106 packs outside tier-1 TY2025 still carry an unmeasured budget; each is measured when its pack is next touched. (2) The registry keeps the first description per (topic, url), which is JK20's. (3) CA's blind and senior counts for a qualifying surviving spouse are checked against the joint column; the separate-return maximum of 2 for AR, DE and OR fits only their combined separate return; AR's senior_special within senior and OR's disabled_child within dependent are stated in notes, not enforced. (4) MO's typed-signature rule lives in pack comments, not in a fill-time warning. (5) The gate cannot see a header field a pack leaves unmapped, as GA 2023's was; a blank scan for unmapped mirror-shaped fields would. (6) AL's "Name(s)" header mirrors print the primary filer only, as the DOR's own script does, while ME and OK add the spouse in an optional segment. (7) The four NR/PY group test modules share copied helpers.
- [x] **JK29 — Freshness drift fix and comb separator cells — DONE 2026-10-23** (S–M; found by the 2026-10-19 freshness run and the re-map's verifiers) (KG2, KG3) — each fix has a test that fails before and passes after.
  - **OR-40 2023 re-issue.** Oregon re-tagged the 2023 blank for accessibility (PDF ModDate 2026-10-14; the printed revision is still "150-101-040 (Rev. 03-21-24, ver. 01)") and replaced the filing-status and account-type radio fields with separate checkboxes, so a filing-status fill failed with "field not found". The seven lines are re-bound by rectangle against the printed captions and pdf_sha256 is re-pinned. OR-40 2024 and 2025 still match their pins.
  - **2026 Form 1040-X draft re-post.** The IRS re-created the draft (Created 10/9/26): line 22 drops direct deposit (22a becomes 22; 22b-22d are gone) and the page-2 widgets below it moved and were renumbered. Ten lines of the old map would have filled other cells without a warning, because their old field names still exist and name different cells. The pack is re-mapped and re-pinned; test_reissued_blank_remaps.py fills both blanks and checks every value's cell.
  - **SSN boxes whose printed dashes take cells.** `format: ssn_dash_cells` writes "ddd-dd-dddd" into an 11-cell comb whose cells 4 and 7 sit on printed dashes; verify still compares digits. OR-40 2023-2025 (15 lines) and MO-1040 2023-2025 (SSN_1/SSN_2) use it; before, the 4th digit landed on the first printed dash. A widget-level gate reads each blank, and a mirror that slices an SSN slices its digits.
  - **Money boxes whose printed commas take cells.** `format: money_comma_cells` writes "1,234,567" into an OR-40 money comb (lines 7-55b, 2023-2025, 142 lines): bare digits put a digit in a comma cell, so 1,234,567 could read as 123,567. A minus never lands in a comma cell ("- 123,456"). A census of every money comb (576 lines in 12 packs) found the LA, MA and VA boxes print their commas on the cell rules, so they need no format; two gates hold both lists.
  - **Left open:** verify does not yet fail a bare-digit value on disk in a comma-cell or dash-cell box written by another tool; identity checks match by line key, so MO-1040's SSN_1 is not compared with a Form 1040's identifying_number; the VA 760 line 17 widget is narrower than its printed cells; IA 1040 2023 lines 32a/32b (routing and account numbers) are mapped as money.
- [ ] **JK30 — US Code citations while uscode.house.gov runs in a temporary format** (S; watch; latest 2026-12-15, when the quarantine rows expire) (KG3)
  - The freshness run dispatched on 2026-10-23 (40016970383) passed its network tests, but its drift job failed on the uscode.house.gov view.xhtml section pages the source registries cite: 15 answered HTTP 500 that day, and all 18 answer 404 since. The site's home page reads "The uscode.house.gov website is currently operating in a temporary format. While the United States Code remains available from its authoritative source, some website features and functionality are temporarily unavailable." The 18 URLs are quarantined in scripts/freshness_quarantine.yaml (kind drift, expiring 2026-12-15).
  - The knowledge packs cite more view.xhtml sections than the registries do (6038D, 5314, 224, 21, 164, 86, 4973, 1641 among them); those links are dead too while the site is in this format, and the drift check does not see them.
  - **Acceptance:** the pages resolve again and the rows are deleted; or, by 2026-12-15, every uscode.house.gov citation is re-pointed to the same section on govinfo.gov, each re-read so its quoted text still holds, and the rows are deleted.
- [ ] **JK31 — Quote fix wave: the JK23 first report's mismatches** (M; deps JK23; KG8 allows value fixes after 2026-12-01) (KG2)
  - Work the 295 mismatches with JS2c's procedure (docs/dev/HISTORY.md, JS2c): re-read each span at its cited source, then correct the pack's quote, re-point a miscited span (the 40 citation-class ones, e.g. MD 2024 credits[0] verbatim in Form 502 but citing the resident booklet), or record the checker's false positive. Highest value first: the federal f1040.ctc / f1040.actc `printed` captions that lost their first letter to a drop-cap text layer ("hild tax credit", "dditional child tax credit", most of 2019-2026); LA 2025's treaty note quoting "Line 11" where the 2025 IT-540 booklet prints "Line 11b"; MS 2025's treaty note silently correcting the DOR FAQ's "counties"; MO 2024/2025's law-change rates written in quote marks; MS 2025's check payee dropping "the".
  - Read the 179 unchecked spans another way where it matters (DC's garbled books by rendered page; mass.gov through its digest-verified mirror).
  - **Acceptance:** every mismatch fixed with the source re-read, or closed as a false positive with the reason; the checker re-run shows the drop.
- [x] **JK5 — Release-candidate dry run — DONE 2026-10-16** (M; deps JK0, JK0a, JK1-JK4, JA1, JK27; latest start 2026-10-21) — cut at 2a77d2d once its CI was green; the findings are fixed in 050e84d, and the A6 flip waits on branch `release/a6-flip`.
  - **The dry run.** Both wheels build (scripts/stage_data.py, then uv build); `uvx twine check dist/*` passes; scripts/release_smoke.py in a clean venv sees 23 tools and the derived pack counts; mcpb 2.1.2 `validate` and `pack` pass; PUBLISHING.md:146's grep, widened to packages/, finds only the gate test's own pattern list. An agent then ran ACCEPTANCE.md end to end over stdio against the installed RC: the TY2025 demo persona's Form 1040 in Washington, plus California Form 540, behind a logging proxy and lsof (traffic only to irs.gov and ftb.ca.gov). Every figure matched.
  - **What it found, fixed in 050e84d.** A three-lens review and a re-verify of the fixes found more, fixed in the same commit:
    - Filled hybrid IRS forms kept their XFA layer, which Acrobat and Reader can draw (empty) instead of the AcroForm values. The filler now unlinks /XFA and empties its packets.
    - serverInfo.version was the MCP SDK's 1.30.0.
    - "Not tax advice, paper filing only" lived only in intake_checklist's worksheet.
    - The state "By check" sentence quoted the whole check_payee note as the payee. Indiana's payee read "DOR", and the generic memo line contradicted six last-four-digits states.
    - Every render of a hybrid form logged pdfium's no-XFA notice.
    - Washington read income_tax true and gave a flat 7%. The 2025 2.9% tier is now cited to RCW 82.87.040.
    - The W-2 spec had no box 8. "NaN" in a money box crashed extract_document, and "1e999999999" hung it.
    - A failed relation always sent the agent to calc.
    - ACCEPTANCE.md now matches what the tools return.
  - **Left to JK28:** page-header mirrors (the 540's blank Sides 2-6 headers), state credits past the rate-schedule line, the SSN comb offset, W-2 code titles by year.
  - **Left to the user (JA2):** open one filled 2025 Form 1040 in Adobe Acrobat Reader before the upload (the XFA fix follows the format and pdftk's drop_xfa; it was not observed in Acrobat), and record the demo GIF.
  - Cut from a pushed, CI-green commit after the JK0 wave stops committing.
  - **Acceptance:** both wheels build. `uvx twine check dist/*` passes. The clean-venv smoke shows 23 tools and the derived pack counts. `mcpb validate` passes. An agent runs ACCEPTANCE.md end to end on the TY2025 demo persona (Form 1040 + one high-volume state). The A6 diff (JK7's file list) and the release notes are pre-drafted on a branch. `grep -rn -i "not on PyPI yet\|not yet published\|coming with v0.1\|IN DEVELOPMENT" packages` (PUBLISHING.md:146's grep, widened) is empty on the RC. This is a developer dry run, not the non-developer test.
- [x] **JK6 — Five journey goldens — DONE 2026-10-15** (M; deps JA1.3; latest start 2026-11-02) (KG10) — packages/mcp-server/tests/test_journeys.py runs five journeys of the TY2025 filing season through the MCP tools in-process, on demo personas: the W-2 employee of ACCEPTANCE.md (in Washington, so its state step is "nothing to file"; the "big state" case is carried by journeys 2 and 3), an F-1 student (Form 1040-NR, Schedule OI, Form 8843), a Virginia-to-California part-year mover, an Ohio school-district filer, and a TY2024 Form 1040-X with the Georgia Form 500X. Each step records pack, pointer or refusal (no fallback exists yet), and arithmetic figures are recomputed through calc. A module-level guard fails any non-pack step that claims filing-grade; the adversarial verify tightened it (a negation counts only right before the claim, keys are normalized, "ready for filing" and "is final" count, and a pack step may not carry the unmapped grade). Offline in CI: 30 tests plus 3 strict xfails; the fill, verify and render steps run in the weekly network job (4 plus 1 strict xfail). The strict xfails are the defects it found, now in JK27: file_and_pay has no amended-return model (federal 1040-X and Georgia 500X), Virginia's Form 760PY is cited only to the resident instructions, and verify_filing fails an attached Form 8843 whose address boxes are blank. ACCEPTANCE.md names the golden that holds it. *(2026-10-16: JK27 fixed all four; the journeys hold no xfail now.)*
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

- [x] **JK8 — Watches as triggers — DONE 2026-10-24** (M; deps JK2, JK9) (KG4) — the finals cron runs weekly on October-November Mondays, on December 1 and 8 (closing a 15-day hole before the daily run), then daily from December 15 through **March 15** (it stopped on 02-15). scripts/check_watches.py, a second step in .github/workflows/finals.yml, watches four named targets, each with its own issue so one signal cannot hide another:
  - **JT5g:** the irs-dft f1040nrn / f1040nro drafts fire when a draft newer than the recorded 2025 one posts (its "Created" footer and printed year decide; Last-Modified only when the footer cannot be read, so a re-upload of the 2025 draft stays quiet).
  - **The TY2027 inflation Rev. Proc.:** read from the IRS newsroom month pages (the release links the Rev. Proc. the day it drops; the IRB prints it weeks later). Its issue says to record the Rev. Proc. for JT6 and not to add knowledge/federal/2027.yaml yet; every watch follows the OLDEST provisional year, so an early 2027 pack cannot silence the TY2026 triggers.
  - **The five non-draft 2026 packs** (f1040es, f8316, f843, f8833, fw7): fire when irs-pdf's current file no longer matches the pinned digest.
  - **JS7a, the tier-1 state blanks:** all 18 tier-1 forms from the JK9 table; a candidate fires only on a 200 whose first page prints 2026 (IL's and NJ's rotating slots are read by content; michigan.gov ignores the `?rev=&hash=` query, so MI's derived path is live). A host that refuses scripts (mass.gov's 403), a page that is not a not-found page, or a year that cannot be read is BLIND: it opens the issue under "check by hand", never quiet. A transient failure past JK2's retries exits 1.
  - Closing an issue acknowledges it: while the watch finds the same rows (a signature in the body; the finals issue's signature is its posted forms) it stays closed, and anything new files a fresh one. The real dry run on 2026-10-24: 34 finals 404; drafts, Rev. Proc. and revised forms quiet; states 17 quiet, MA blind. The manual check stays booked for 2027-03-15 (calendar above). Built, verified (a fail: the Rev. Proc. issue's advice would have moved every watch to TY2027), fixed, re-verified and its minors fixed.
- [x] **JK9 — Tier-1 state triage table — DONE 2026-10-24** (S–M; deps JK0) — scripts/tier1_states.yaml ranks the 42 income-tax jurisdictions by number of individual returns from IRS SOI Historic Table 2, tax year 2023 (https://www.irs.gov/pub/irs-soi/23in55cmcsv.csv, column N1 at AGI_STUB 0, fetched twice; the newest year on the index page on 2026-10-24). Tier 1 is the top 12, volume only, 62.1% of the returns from income-tax jurisdictions: **CA, NY, PA, IL, OH, NC, GA, MI, NJ, VA, MA, AZ** (the plans' eleven plus AZ; IN, MD and CO follow closely, so 12 is the roadmap's "about 12", not a natural break).
  - Per tier-1 state the table records the resident and NR/PY forms, the NR/PY packs a port can start from, the amend route quoted from each state's 2025 instructions (same form with an indicator: CA, PA, OH, NC, MI, VA, MA; a separate X form: NY IT-201-X / IT-203-X, IL-1040-X, GA 500X, NJ-1040X, AZ 140X), and which line of each 2025 pack maps the amended indicator. test_tier1_states.py holds every claim to the packs' line keys, so a re-map cannot leave the table stale.
  - `scaffold_state_year.py --tier1` filters to the table (it refuses a table whose tier-1 rows are not the top of the ranking); the TY2026 work-list is staged at scripts/worklists/tier1_ty2026_2026-10-24.json (18 forms: 15 answer 404 until the 2026 blanks post, MA 403, IL and NJ carry no year token).
  - **Pending, the user's call (KG9):** the recommendation to weight the ranking toward where nonresident-alien students cluster is recorded as `recommendation.status: pending` and not applied; accepting it needs .gov student counts (e.g. ICE SEVIS by the Numbers), fetched and cited.
  - **For JS7a / JK8:** AZ's NR/PY lineage is the 2023 140NR / 140PY packs only (no 2024/2025 port), while JS7a's box names only CA 540NR and NY IT-203; OH's CHK_AMD carries the ReadOnly flag on the 2025 blank (mapped on purpose) and needs re-checking on the 2026 blank; JK8's watch must tell MA's 403 from "not posted" and read IL's and NJ's rotating URLs by content.
- [x] **JK10 — Label-adjacency guard on the base pack and every port — DONE 2026-10-25** (M; latest start 2026-11-30)
  - The real failures are in the **base** pack, not in a widget that moved between years: the ME 1040ME 2023 widget names are rotated against their printed captions and the 2024 and 2025 blanks carry the same names on the same rows (measured by the ME 1040ME 2024 port's verifier, 2026-10-04); AL Form 40 2023's keys were one number high and the relations matched (docs/dev/ROADMAP.md:2391, P-031). A name or /Rect diff between years reports these as unchanged and carries the mis-bind forward; today's triage diffs names only (scripts/scaffold_state_year.py:170-177).
  - Primary check: for every mapped widget, read the printed line number beside it and require it to equal the pack's line key. Generalise the existing per-form tests (packages/core/tests/test_al40_line_designators.py, P-031; the ME test from JK0a, P-032) into one gate. Run it on the base pack and on every port.
  - Secondary signal: `scaffold_state_year.py --triage` also diffs each widget's /Rect against the prior-year blank (`extract_fields` reads rects, packages/core/src/taxfill_core/packbuild.py:67-94); a moved widget forces a re-map.
  - **Acceptance:** two real base-pack rotations are caught: the ME 1040ME 2023 3-cycle (on 063f293's pack) and the AL 40 2023 one-high shift (on its pre-P-031 keys). It runs on every JS7a port and every on-demand port, and on the base pack each port starts from.
  - *As built (2026-10-25).* One gate, `packages/core/tests/test_label_adjacency.py` and `scripts/label_adjacency.py` (network-marked, all 281 packs in about 20 s with xdist), compares each numbered key's line with the designator `taxfill_core.anchor` reads beside its widget. Six column conventions (`formpacks/column_keys.yaml`: DE PIT-RES / PIT-NON Columns A and B, Form 8962's monthly and alternative columns, Schedule NEC's rate columns) and 41 key shapes (`formpacks/key_shapes.yaml`, two-column state forms, schedule keys, worksheet rows), each checked on its own face, map the keys. A disagreement fails unless the self-clearing `formpacks/label_adjacency_exceptions.yaml` lists it with an adjudicated reason (465 rows in 41 families; a stale or duplicate row fails). The P-031 / P-032 per-form network reads are folded in, and both mandatory rotations fail it (ME 1040ME 2023 on 063f293's map; AL Form 40 2023 at b132055^). `scaffold_state_year.py --triage` runs the check on the base pack each port starts from (BASE-MISBOUND, BASE-UNCHECKED) and diffs mapped widgets' /Rect against the base blank.
  - Real defects found and re-keyed (P-031, each with a test): OK 511 2023-2025's 4a / 4b / 40a-41a / 40b-41b (now 4.description, 4, N.penalty, N.interest); VA 760 2023-2025's 17a (now 17, the inline box 17.spouse_vagi, and line 18's relation declared); WI Form 1 2023's 14a (now 14 and 14.federal_credit); NY IT-203 2023-2025's line-74 withdrawal date, keyed 73; GA 500 2023's s3.10 rows, printed 10a; MT Form 2 2023's Schedule 1 sch1.8o, printed 8p. Blind and spot-checked vision reads found no rotation of the ME / AL kind.
  - Coverage is measured, not assumed. The self-clearing ledger `formpacks/label_adjacency_coverage.yaml` holds each pack's checked, line-bearing and mapped keys and four counted limits of a line-number check: a same-row column swap, a box the anchor reads no line beside, a swap between sections that print the same number, and a key the gate compares nothing for. The denominator counts every line-like key outside an explicit allow-list. A pack under 70%, or holding an undeclared key family the anchor cannot read, or any undeclared key the anchor can read, reads PARTIAL and names why (83 packs). Repo-wide 19,211 of 30,354 line-bearing keys are checked.
  - *Review:* six independent verifier passes, each closed structurally: zero-coverage packs reported OK; a circular denominator; whole undeclared schedules; keys with descriptive tails; repeats across sections and allow-list holes; the limit counts themselves.
  - *Open:* a section-aware comparison (the anchor reading which schedule a row sits in); lines that are only a letter (MT Form 2 2023's exemption rows a-d); NY IT-203's 12_farm_income_fed names the wrong row (cosmetic); MT Form 2 2023's nrcredits.15a.year is the tax-credit-code box.
- **JEe** (kept; latest start 2026-11-30, before the 2026 maps are made; deps JK0 so the sweep covers the integrated packs). Agent half DONE 2026-10-24 (P-035: verify measures where a value's ink ends inside the widget's border, by its alignment and weight). The user decides how RI-1040's edge-to-edge boxes render: the dependent dates of birth, the middle initials, the suffixes and the signature and preparer dates (KG9).
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

- [x] **JK13 — Surface and guardrail ADR — DONE 2026-10-16** (S; **no deps**: it must not wait on the user-held release; latest start 2026-11-02) — [ADR-0002](adr/ADR-0002-fallback-surface.md) is committed with Status: Proposed (main @ ccf02d2 for its line references). It rides the existing tools (`form="unmapped"` on fetch_blank / get_form_map / fill_form / verify_form; 23 tools), writes KG5, KG6, KG7 and KG11 out in full with where each is enforced, and lists 15 refusal rules. Drafted, then reviewed adversarially for code references and for fidelity to this ROADMAP and ADR-0001, then fixed. **The user decides its 17 open questions** (among them: KG7's format-action rule, which as written refuses 43% of the text widgets on the cached blanks where a narrower rule would refuse 5.6%; a floor for `med`; and the OCR check, since the repo has no OCR engine). Until the user accepts it, the ROADMAP and ADR-0001 wording binds JK14-JK19. Its review also found the overlay's Pillow dependency that JK27 fixed.
  - Decide the MCP surface. Recommendation: ride the existing tools, `fetch_blank` / `fill_form` / `verify_form` / `get_form_map` with `form="unmapped"` + `source_url`, keeping **23 tools**. The overlay precedent is server.py:181-195 / test_overlay_tools.py:54. The cost is that pack and unmapped results share a schema, so `grade: "unmapped_draft"` must appear in **every** response, not only the summary.
  - The alternative is a 24th tool, which edits every hard-coded "23": ci.yml:115, test_cli.py:69/:78, test_server_e2e.py:19/:397, bundle/manifest.json, test_overlay_tools.py:54, docs/dev/PUBLISHING.md:89 and :135, docs/TOOLS.md:3, and packages/mcp-server/pyproject.toml:4 (the PyPI description; immutable once uploaded, which is why JA1 makes it count-free).
  - Riding the existing tools changes their input schema and response shape; KG8 allows it only as additive, opt-in, unmapped-only parameters and fields with the pack path byte-identical (JK21).
  - Write down the refusal rules: XFA-only or scanned pages; page-1 year or title not matching the request; a non-official host; ReadOnly or pushbutton targets.
  - **Acceptance:** ADR-0002 is committed under docs/dev/adr/ (ADR-0001 records this re-plan), and KG5-KG7 and KG11 are written into it.
- [x] **JK14 — Introspect + pack-less fetch — DONE 2026-10-24** (M; deps JK13) — core only: no MCP tool, parameter or response changed (still 23 tools); ADR-0002 is still Proposed, so this box's wording bound it.
  - **Introspect.** packbuild.extract_fields reports each widget's kind (text, checkbox, radio, pushbutton, choice with its /Opt values, signature), the named /Ff flags (read-only, required, multiline, password, comb, do-not-scroll, radio, pushbutton, no-toggle-to-off), /TU, the /DA font and size, /Q, and `calculated` when the field or widget carries an /AA /C or /F action (KG7), plus `javascript`. `type` keeps its meaning; build_skeleton skips pushbuttons and lists them in one TODO entry (they used to get a "/BBox" on-state). `taxfill introspect` also writes fields.json; CONTRIBUTING-PACKS step 2 now matches the CLI.
  - **Pack-less fetch.** fetch.fetch_unmapped_blank: https and an official host on every redirect hop; always downloads, never touching the pack cache, into a namespace keyed by sha256 with a (url, sha256, fetched_at) record; a pinned-only host (NM's document API) and a 401/403 host are refused with a pointer to save the PDF in a browser and pass it as `local_blank` (no Wayback mirror without a digest); a local blank needs a PDF header in its first 1024 bytes (ADR-0002 rule 5) and an official source_url and is stored under the year's workspace, so `taxfill purge` removes it; XFA-only, needs-rendering, locked and scanned (no text on the form's first page) blanks are refused. The form's first page must print the requested year at title size; a revision date is refused for every tax year; `expected_title` is matched as whole tokens. load_unmapped_blank re-runs every check on a stored copy, so a wrong-year blank is refused cached or fresh. Every refusal carries a `.reason` code and the next step.
  - **Measured** over the 250 cached non-draft pack blanks: 219 pass, 22 are refused as revision-dated (Forms 1040-X, 843, 8316, 8833, 8938, W-7) and 9 as having no printed year (DC D-40 2023-2025, whose title block has no year in its text layer, and NY IT-201 / IT-203 2023-2025, whose title year is vector art). A sweep of 290 blanks at their own year and the years either side found no false accept.
  - **Left open:** ADR-0002 rule 1 (a shipped pack wins), rule 5's typed-value check on a local blank and rule 9's any-page text check are not built: they belong with JK16, the first tranche that accepts a request; the stored record has no jurisdiction yet (a JK16 surface decision); a pack-path golden over get_form_map is due before JK16 merges its first unmapped branch.
- [x] **JK15 — Anchor + blind benchmark — DONE 2026-10-24** (L; deps JK14; latest start 2026-11-16) (KG6)
  - Dump every text run with its box. Pair each widget with its nearest printed label (left or above, same row) plus the line-number token. Cross-check with /TU. Emit a per-field anchor confidence: high, med, low or none.
  - Run blind on **≥30 shipped packs**, federal and state, and compare each with the pack's line map. The ME 1040ME 2023 3-cycle (063f293's pack) and the AL 40 2023 one-high shift are mandatory cases and must be flagged; every disagreement with a pack is adjudicated by a vision check before the pack counts as ground truth.
  - **Acceptance:** the accuracy table is committed, with per-field precision **and** a per-form "any mis-anchored field" rate. "high" is emitted only where measured per-field precision is ≥99%, and the response wording is "anchored (unverified line map)". If precision is lower, JK16 is skipped and the fallback ships inspect + worksheet only.
  - *As built (2026-10-24).* `taxfill_core.anchor` is pack-blind (it never reads a pack): it dumps every text run with its box and anchors every widget with a `printed_line`, a `label`, a `confidence` and the `evidence` behind it; a field's confidence is its lowest widget's. The top tier is worded "anchored (unverified line map)" and "high" is never emitted. Tiers come only from the committed table `knowledge/anchor/benchmark.yaml`, read when `passed` is exactly true for the current method, and the top tier is licensed per widget group (`top_tier_kinds`: text only; checkboxes measured 9/10). A missing or malformed licence fails closed, and `anchor_basis()` names the table.
  - The top tier needs the printed designator to identify ONE box. These cap at `med`: a box on a multi-column row; a box sharing its row band with another field's box, unless every box there has its own distinct designator printed beside it (the Form 1040 "2a [box] b [box]" layout); a designator printed once per Part on one page; and any box whose designator another field's box on the page also carries, has printed before it, or names in its /TU or field name.
  - The benchmark (`scripts/anchor_benchmark.py`, knowledge/anchor/) takes one pack per form family, split DEV 33 / TEST 38 (12 federal, 26 state from 22 states; sibling forms on opposite sides are disclosed). The method was tuned on DEV only. TEST was measured four times, each run in the table's history with what changed. Every disagreement (186, including the mandatory cases' 20) and a seeded 48-widget sample of unscored top-tier text widgets were judged blind from crops (one read per item, candidates unsided). Final, method jk15-v4: scored top-tier text 1086/1086 (95% Wilson 99.65-100%), unscored sample 48/48, combined estimate 100% (97.9-100%), per-form "any mis-anchored top-tier widget" 0/36, med 555/561. Both mandatory cases are flagged: ME 1040ME 2023 lines 21-23 on 063f293's map, and all 15 AL Form 40 2023 shifted keys (b132055^).
  - *Review:* four independent verifier passes each found a new way for a designator to point at the wrong box (Delaware's spouse column; helper boxes beside the amount box on GA 500, IT-201 and Form 1040-X; helper boxes a printed line apart on WI Form 1 and Form 2555). Each was closed by a broader invariant and a TEST re-run. The fourth pass, sweeping all 348 cached blanks for further variants and judging about 45 flagged crops itself, passed. The fail-closed cost: 126 top-tier widgets across the 348 cached blanks (1.5%) drop to `med`, where a fill needs the user's confirmation.
  - *Known limits (documented in the module and the table):* a designator that a second schedule on the page prints again with no box beside that copy is not counted (WI Form 1 page 4's Schedule 1 line 7 and Schedule 2 line 8 keep the top tier); widgets hidden by their annotation flags are anchored like any other; text outside a page's crop box is read.
  - *Open:* keys that name a column rather than the printed designator (DE PIT-RES/PIT-NON "Na"/"Nb", MO 1040 "28Y") are for JK10; JK16 consumes `anchor_widgets` and must refuse hidden (/F Hidden or NoView) widgets like ReadOnly and calculated ones.
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

- [x] **JK21 — Golden-diff harness — DONE 2026-10-15** (M; latest start 2026-11-05) — scripts/golden_snapshots.py snapshots every tool that reads state knowledge, through the same functions the MCP tools call: calc `state_tax` over a demo grid per filing status, `state_scope` for three demo profiles, `filing_summary`, `file_and_pay` and `get_sources`, for all 126 state jurisdiction-years plus the no-income-tax states, into packages/core/tests/goldens/state_knowledge/ (127 files, 5.3 MB). test_state_knowledge_goldens.py fails on any drift with the file and the first differing key, in about 5 seconds. The TY2025 pins are in test_state_knowledge.py: OH's $342.00 / $2,394.32 discontinuity, AZ line 49 and the IL IL-E / EIC caveats. Verified in the main loop because the verifier agent never outlived the service stalls: the snapshots are identical under two hash seeds and time zones; a California bracket-rate change and an Ohio tax.notes change are caught, and a YAML comment is not. It found a live bug on its first run: filing_summary and file_and_pay crash for New Mexico 2025 (JK27); the NM 2025 golden records that error until the fix regenerates it.
  - Snapshot the output of every MCP tool that reads state knowledge (state_tax via calc.py, state_scope via statescope.py, file_and_pay, filing_summary, and get_sources through sources_states.yaml, sources.py:107-112) over every jurisdiction and year. The residency tool is not included: it calls `_classify` only (server.py:1041-1078) and residency.py reads no state knowledge.
  - Add the missing TY2025 pins now: the OH $342.00 / $2,394.32 discontinuity (knowledge/states/oh/2025.yaml:293-303; no test pins "342.00" today), AZ Line 49 and the IL IL-E/EIC caveats for 2025. The existing pins test TY2023 only (packages/core/tests/test_state_knowledge.py:411-414 asserts OH 2023's "360.69"; :298 is AZ 2023; :319-324 is IL 2023).
  - **Acceptance:** the harness runs in CI. It is the gate for JK20, JK22, JK24 and JK26.
- [x] **JK20 — Hoist citations into a `sources` table — DONE 2026-10-24** (M; deps JK0, JS2c, JK21) — zero-output apart from get_sources, as K-K requires before 2026-12-01.
  - **The table.** Every TY2025 state pack (42) carries a top-level `sources:` list, generated once by scripts/hoist_state_sources.py from the pack's own .gov citations: one row per (registry topic, url), `{id, topic, url, descriptions}`, every distinct inline description kept verbatim (519 rows). The inline citations stay, so no consumer changes; the 2023 and 2024 packs stay frozen and untouched. knowledge.StateSourceEntry refuses a duplicate id or (topic, url), an unknown topic, a non-.gov url and an empty description at load.
  - **The builder.** state_sources.state_block reads the table when a pack has one and walks the inline citations otherwise. Both paths now MERGE the descriptions of one (topic, url), joined by " || " with the first description first; the registry used to keep the first and drop the rest (89 / 222 / 328 in the 2023 / 2024 / 2025 packs). Tests hold the table to the inline citations (every inline .gov citation is in it, every row is backed by one; JK22 relaxes the second half when it drops blocks) and the table's block to the walked block, byte for byte.
  - **Routing.** A plain merge moved 360 of 2,646 routes (21 queries over every state-year), 74 of them to the wrong topic: the catch-all booklet topic out-counted the specific one, or a stray word of a joined description ("Who must file", "income earned while a resident") turned a clean miss into a false match. So get_sources' scorer reads a joined description only when ONE description names the whole query as a literal run of words, and scores the primary description otherwise (federal answers carry no separator, so federal routing is byte-identical). 105 routes still move, each to a topic whose own text names the query (most were clean misses: CA "due date" now reaches filing_logistics). packages/core/tests/goldens/state_source_routes.json pins every matched route, and 12 canonical routes are pinned with their reasons.
  - **Goldens.** get_sources moved in 119 of the 127 JK21 files; every other section is byte-identical, and no (state, year, topic, url) left the registry. knowledge/sources_states.yaml is regenerated.
  - **Left open:** the tables add about 470 KB to the TY2025 packs (every description copied verbatim), which JK22 and JK24's id references should take back; NY 2025 "where to file" now ties to the IT-201-I booklet entry (the same PDF) rather than filing_logistics; the literal rule does not match inflections ("Filing Due Dates", "PART-YEAR RESIDENTS") or abbreviations (Michigan's "EITC"); the JK28 NR/PY test modules' inner comments still describe the first-description-wins registry.
- [x] **JK22 — Drop never-read blocks from the TY2025 state packs — DONE 2026-10-24** (M; deps JK20, JK21) — zero output change: every JK21 golden is byte-identical, get_sources included, and no registry entry was lost (2,824 before and after).
  - **Dropped** from all 42 TY2025 state packs (2,112,863 -> 1,827,941 bytes): `residency` (62.6 KB), `filing_requirement` (44.5 KB), `starts_from` (9.5 KB), every credit's `amount` and `income_limit_2025` (362 fields, 90.8 KB), and the header comment diaries (83.6 KB gross; 79.4 KB net of the one-line `# Provenance: see git history (git show 7a90a06:...)` header that replaces each). Each kind was first dropped alone in a scratch copy with no golden change, and a negative control (renaming the read `deadlines` block) showed the harness reads the scratch data. The 13 citations that lived only in dropped blocks stay in each pack's `sources` table (JK20), so get_sources lost nothing; test_state_sources_table.py exempts exactly those rows from "backed by an inline citation".
  - **Kept, because read:** credit names, eligibility and citations (state_scope) and `credits_verification` (state_scope's warning). test_state_pack_never_read_blocks.py keeps the dropped blocks and fields out of the TY2025 packs.
  - **Left open (JK26):** about 75 KB of column-0 body comments remain (39 KB of them JK20's sources-table note), so the box's "~107 KB" counted more than the header diaries; 17 `effective_law_changes[].affects` entries in 16 packs still name dropped blocks (no tool emits them); some body comments point at the removed header; state_scope's "Credit amounts/limits are not independently verified" warning and the `credits_verification` text still speak of amounts the packs no longer carry (rewording it moves the state_scope goldens); the writer scripts (assemble_state_knowledge.py, assemble_state_credits.py) still emit the dropped shapes, so a TY2026 cohort needs JK25's v2 scaffold or a writer change.
- [x] **JK23 — Quote-verbatim checker — DONE 2026-10-24** (M) — scripts/check_quotes.py collects every quoted span (state prose of all years including tax.notes and credit text, federal form_lines `printed` captions 2019-2026, v2 Quotes and conversion wordings), reads each candidate URL once into a text cache keyed by url + sha256 (the shared blank cache first), normalises both sides and reports each span VERBATIM, MISMATCH (with the closest source passage and a class: wording, citation, punctuation, case) or UNCHECKED (with the reason: a refused host, a TLS failure, a garbled text layer, no candidate). Report mode exits 0; `--strict` (for JK26) exits 1 on a mismatch. The weekly freshness workflow runs it in report mode (continue-on-error, summary on the run page, JSON artifact); ci.yml stays offline. A seeded paraphrase is reported, and a dash between two digits stays a separator, so figures cannot merge.
  - **First report** (2026-10-24, from a developer machine): 3,025 spans; 2,551 verbatim, 295 mismatched (216 wording, 40 citation, 22 punctuation, 17 case), 179 unchecked (DC's garbled D-40 books 86, mass.gov 34, tax.idaho.gov's TLS chain 18, maine.gov 15). They go to JK31.
  - **Left open:** an ASCII-offset font (some Arkansas DFA PDFs) reads as text, so its spans show as mismatches instead of unchecked; a column heading or footer inside a source sentence reads as a wording mismatch; straight double quotes nested in a straight-quoted span split it; the form_lines designator relaxation (the line number within 300 characters) is loose.
- [x] **JK24 — Schema v2 models + dual-version loader — DONE 2026-10-24** (M; deps JK20, JK21) — no data and no consumer changed; every JK21 golden is byte-identical.
  - **Models** (packages/core/src/taxfill_core/knowledge_v2.py, design in its docstring): SourceRef (a `sources` row id, which of its descriptions, an optional pinpoint), Quote (verbatim, at most 400 characters, with a SourceRef; the cap and edge check are shared with FormLineEntry.printed, now also capped), and StateKnowledgeV2 (`schema_version: 2`, extra keys forbidden): treaty, base_line, tax with typed `caveats`, credits as pointers (no amounts), law_changes with quotes (the JS2 rule enforced), convenience_rule, forms with per-role refs, logistics (mailing, deadlines, payment, amended return), gaps, and the JK20 `sources` table. A TY2026+ pack may say only what its sources say: every caveat, treaty note and eligibility is a Quote, or a caveat `{not_modeled, ref}` (200 characters, no figures in digits or words). Free `{text}` exists only for converted TY2025 packs (capped, and declared in `gaps`).
  - **Loader.** load_state_knowledge reads `schema_version` (absent or 1 is v1, 2 is v2, anything else is refused, as is v2 for a year before 2025) and returns a v2 pack as its v1 projection, so today's consumers read a TY2026 v2 pack unchanged; load_state_knowledge_v2 returns the v2 model. state_sources.state_block projects a raw v2 mapping too.
  - **Parity.** scripts/convert_state_pack_v2.py converts a TY2025 v1 pack; the PA, CA, GA and NY 2025 packs are converted into packages/core/tests/fixtures/state_knowledge_v2/, and each, swapped into a copy of the tree, reproduces every JK21 golden byte for byte. In a scratch run all 42 TY2025 packs converted (27% smaller) and all 127 goldens matched. Every raw-YAML repo gate runs over the four fixtures and a TY2026 shape pack.
  - Built, verified (a fail: free text bound nothing for a 2026 author), fixed, re-verified (a fail: the own-sources gate would have turned red on the first v2 pack), fixed again and re-checked.
  - **Left open:** for JK25, the scaffold must emit caveats as `{quote, ref}` or `{not_modeled, ref}` and a law-change record; for JK26, a SourceRef points at a description by position (append-only is documented, not enforced), the `sources` descriptions and several plain strings (tax_line, exemption notes, logistics notes) are still uncapped prose, and a bare number of three digits or fewer, or one spelled out, still passes the not-modeled filter.
- [x] **JK25 — The 2026 state scaffold emits v2 — DONE 2026-10-24** (S; deps JK24, JK23) — from TY2026 on, scripts/assemble_state_knowledge.py hands each state to scripts/state_knowledge_v2_writer.py, which writes a StateKnowledgeV2 pack in one pass (the tax-block and credits results come in through `--tax-dir` and `--credits`; assemble_state_tax_blocks.py and assemble_state_credits.py refuse TY2026+ and say so). The writer builds the `sources` table from the input's citations, fills each v2 slot, validates, loads the pack through the v1 projection, recomputes the tax vectors through calc.state_tax and restores the file if anything fails. Input it cannot carry honestly is refused with the field named and what to drop or reword: the blocks JK22 dropped, prose treaty notes and eligibility, free text, tax.notes, a caveat that is neither a quote nor a not-modeled statement, a credit amount anywhere (including a figure in a credit's caveat or name), a non-.gov citation, malformed tax brackets or rates, and a state named twice; one refusal lists every bad key. TY2025 and earlier keep their v1 output byte for byte.
  - **Acceptance:** the committed demo input (packages/core/tests/fixtures/state_scaffold_v2/nc_2026_demo_input.json, demo data built from the 2025 NC D-401 and D-400, each fetched twice) becomes a v2 pack that validates, works through state_tax, state_scope, file_and_pay and filing_summary, passes every raw-YAML gate, and passes check_quotes.py offline with 0 mismatches (a reworded quote turns into one). No knowledge/states/*/2026.yaml is added: TY2026 cohorts come with JS7a.
  - **Left open:** a credit's `line` text and the law-change description are not figure-checked; bracket bounds are not type-checked; duplicate `--tax-dir` files still stop the whole run; the writer does not run the networked quote check itself (CONTRIBUTING tells the author to).
- [ ] **JK26 — Migrate TY2025 to v2** (XL; deps JK21-JK24 and the end of KG8; **starts no earlier than 2027-04-16**; done before TY2027 state work, ~2027-10)
  - Triage the 486 TY2025 tax.notes into base_line, typed caveats or dropped diaries, with a two-verifier wave and a per-state diff the user can review. tax.notes is "Cited disclosures/quirks the calc op must surface" (knowledge.py:2978-2981) and state_tax prints every one (calc.py:11037), so the user's "keep every figure a calc op reads" includes the disclosures the op must surface: every note naming a not-modeled add-on, surcharge, recapture or form-computed amount survives as a typed caveat that state_tax still prints. The OH $342.00 discontinuity, AZ Line 49 and the IL IL-E/EIC caveats must survive, guarded by the TY2025 pins JK21 adds (the existing pins, test_state_knowledge.py:411-414, :298, :319-324, are TY2023).
  - Rewrite the consumers: calc.py:11021-11040, statescope.py:196-254, file_and_pay.py:938-966, filing_summary.py:270-280. Rewrite the narrative-pinning tests (test_state_knowledge.py:96-131, :219, :298, :324, :397, :414, :431; test_statescope.py:108-220; the test_state_law_change_sweep.py:36 count). JK23 becomes enforcing.
  - Rewrite the stale comment at statescope.py:283 ("No pack carries convenience rules yet"; state packs now carry them) with the consumer (2026-10-09 ledger).
  - **Acceptance:** the state_tax golden is defined as the tax figure plus the set of calc-surfaced caveats, and every one is unchanged (the work string's wording may change). state_scope still names each credit with its line and link. The registry loses no URL.

### Deferred (on demand, Phase K re-plan)

**On-demand rule.** A deferred pack (any TY2024-or-earlier state form, any JS6/C2 NR/PY form outside tier 1, any JS7b state) is opened only on an explicit request from the user or a filed GitHub issue naming the form and the tax year. Amendment eligibility alone is never a request. The request gets its own JK-style tranche id in this file. The pack must pass JS5's per-pack acceptance, the JK10 label-adjacency guard and KG1 before it ships. Until it lands, the fallback serves the form as a labeled draft (or refuses it, per JK14's host rules).

- **JS5 remainder:** MA Form 1 2024 (no Wayback capture of the current bytes; the fallback refuses it too, JK19). JK0 landed all 23 packs and dropped none under KG1, and with it every other resident return lineage under formpacks/states ships TY2023, TY2024 and TY2025 (derived 2026-10-15), so the D2 re-measure's ~20 re-maps and ~26 URL-discovery tasks are spent. The fallback (JK13-JK18) covers any further old year, where JK14's host rules allow, until a user asks for a pack.
- **JS6 remainder:** the three CT nonresident / part-year forms (overlay or hand-fill), the TY2024 and TY2025 years of the six TY2023 NR/PY packs (AL 40NR, AR1000NR, AZ 140NR, AZ 140PY, CO DR 0104PN, DE PIT-NON), and the part-year allocation golden (it ships with the first on-demand NR/PY pack).
- **C2:** folded into the JS6 deferral. Tier-1 NR/PY forms with a lineage are in JS7a.
- **D2:** closed after JK0; any further old year is on demand.
- **JS7b:** non-tier-1 TY2026 states.
- **knowledge/pitfalls.yaml to docs/dev:** it is a developer registry, not tax knowledge; an optional move with no runtime effect (2026-10-09 ledger).
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

- [x] Add the separate nonresident/part-year return for each state that has one
      (IL Schedule NR, OH IT NRC, PA part-year, etc.) + the adjustment schedule.
      **CLOSED 2026-10-15: deferred (on demand, Phase K re-plan)** (Phase K JK1); its routing notes moved verbatim to
      [HISTORY.md](HISTORY.md) ("Phase C / D — progress notes"), and JS6's box there holds the packs it shipped. NR/PY
      packs on disk: CA 540NR and Schedule CA (540NR) and NY IT-203 for TY2023–TY2025; AL 40NR, AR1000NR, AZ 140NR,
      AZ 140PY, CO DR 0104PN and DE PIT-NON for TY2023.
      **Left (deferred, on demand):** the separate NR/PY return of every other state that has one (the long tail uses
      the no-pack fallback, JK13–JK18; tier-1 NR/PY forms with a pack lineage are in JS7a); the JS6 remainder — the
      three CT nonresident / part-year forms, the part-year allocation golden and the
      TY2024/TY2025 years of the six TY2023 NR/PY packs; and the part-year income allocation calc op.

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
      *(Superseded 2026-10-16, Phase K JK27: an amendment filed now uses the current Rev. 12-2025, whose
      instructions handle a pre-2025 year (QBI on line 4a, line 4b blank); the 2023 and 2024 packs map it.)*
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

- [x] More tax years for the state packs — **CLOSED 2026-10-15: deferred (on demand, Phase K re-plan)** (Phase K JK1).
      The coverage summary below is kept current by scripts/sync_doc_counts.py; the box's progress text moved verbatim
      to [HISTORY.md](HISTORY.md) ("Phase C / D — progress notes").
      State *knowledge* now spans three COMPLETE years: **2023 42/42, 2024 42/42,
      2025 42/42** (RI 2025 closed the cohort 2026-08-07), every pack carrying the
      same 18 blocks incl. a typed `tax` block, auto-enrolled into the suite by the
      glob at `test_state_knowledge.py:26`. State *form* packs are **no longer
      TY2023-only**: 130 packs across TY2023 (48) / TY2024 (41) / TY2025 (41), so
      **42 of the 42 jurisdictions** can fill a post-2023 year —
      TY2024 for **41** (AL, AR, AZ, CA, CO, CT, DC, DE, GA, HI, IA, ID, IL, IN, KS, KY, LA, MD, ME, MI, MN, MO, MS, MT, NC, ND, NE, NJ, NM, NY, OH, OK, OR, PA, RI, SC, UT, VA, VT, WI, WV) and TY2025 for **42** (AL, AR, AZ, CA, CO, CT, DC, DE, GA, HI, IA, ID, IL, IN, KS, KY, LA, MA, MD, ME, MI, MN, MO, MS, MT, NC, ND, NE, NJ, NM, NY, OH, OK, OR, PA, RI, SC, UT, VA, VT, WI, WV). For the
      other **0**, a 2024/2025 return still computes but cannot be filled.
      **Left (deferred, on demand):** MA Form 1 2024 (JS5's remainder: no Wayback capture of the current bytes, and
      mass.gov refuses scripts) — every other resident return lineage ships TY2023, TY2024 and TY2025; the TY2024/TY2025
      years of the six TY2023 NR/PY packs (C2 / JS6); and any further old year, which opens only under Phase K's
      on-demand rule.
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
      remainder is still open. *(Superseded 2026-10-15: JK0 shipped that remainder; what is left is deferred on demand, see Phase K.)*

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
    - **Form 1040-X** (Rev. 12-2026, Created 8/19/26): a wholesale redesign that tracks the 2026 Form 1040 — 194 widgets, 191 mapped (line 9's three reserved cells stay unmapped, RESERVED_LINES_UNMAPPED). Re-posted Created 10/9/26 (line 22's direct deposit dropped, page 2 renumbered): 190 widgets, 187 mapped, re-mapped by JK29 (2026-10-23).
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
- [~] **JEe — Text width vs the widget's inner padding — AGENT HALF DONE 2026-10-24** (M; found by the JS5 RI-1040 2025 port's fixer, 2026-10-02)
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
  - *As built (agent half, 2026-10-24, P-035).* `taxfill_core.textfit` stays the one measure fill_form and verify share, now with the two things the edge-to-edge check missed. The room is the widget's width less its border on each side (`widget_inset`: /BS /W, else /Border, else 1 pt; a beveled or inset style counts twice), measured on pdfium renders at 1, 2 and 3 pt borders (AR, CO, GA, KY, ND, AL and PA boxes). A value fits when its INK stays inside the room, laid out by the box's /Q (from the left inset, ending at the right one, or centred, so a centred value overruns on both sides): its advance in the box's weight (Helvetica's or Helvetica-Bold's AFM widths, the wider of the two when the weight is unknown, Courier 0.6 em) less the side bearings of its first and last glyphs in that weight (`ink_overrun`; bearing tables for the four faces measured on pdfium's renders and re-measured by a test), give or take 0.5 pt. verify's clipping scan uses it for every single-line box; a comb box with a /MaxLen is not width-measured, and the multiline row estimate keeps the full width. The arithmetic reproduces the measured cuts (RI DOB 0.64 vs 0.58 pt rendered, CA 540 Apt. 1.32 vs 1.33 pt) and passes the IRS's own 4-digit year boxes (at most 0.14 pt). The sweep lowered by one glyph the 18 of 201 TIGHTER_THAN_WIDGET budgets that filled their box edge to edge (AL Form 40 2024 Schedule AAC 81.7 pt cells 15 to 14 and Schedule RS "Reason Exempt" 23 to 22, the Schedule OC L2 cell 9 to 8 in AL 40 2024 and 40NR 2023, ID Form 40 2023 preparer state 6 to 4, MA Form 1 2023/2025 line 43a 2 to 1), MD 502 2023's spouse signature date went from 8 to 7, and a network test now re-checks every row with the model. The Helvetica measure itself changed: the 0.5-em average under-measured a digit by a tenth and a capital by up to half, so verify now uses Helvetica's AFM widths for every single-line box. The golden round-trips' synthetic values became realistic (a one-letter middle initial, short dates, counts as digits), because the old ones only passed under the edge-to-edge check. verify now FAILs values it used to pass when their ink is cut, such as a 10-character date in RI-1040's and NC D-400's signature-date boxes, an 8-digit date in the MA Form 1 and MD 502 2023 ones, or 10 Helvetica digits in NE 2023's 49 pt preparer-phone box; the remedy is a shorter form of the value.
  - *Review (2026-10-24):* an independent verifier failed the first cut: the RI exception passed ANY width FAIL on the DOB box (a slashed date in RI 2023, which has no budget, passed); the measure ignored /Q, so right-aligned money boxes were cut on the LEFT unseen and a centred KY 740 ZIP+4 false-FAILed; and the sweep had missed RI's middle initials and suffixes and MD 2023's spouse date. All fixed: the exception now covers only a value that passed the pre-JEe check, on all three verify paths; the measure lays the value out by /Q; render tests pin a left cut on Form 1040 line 1a (right-aligned) and a whole centred KY ZIP+4. A re-verification then found bold boxes measured in regular widths (a bold name on Form W-7 2025 passed and printed 4.9 pt cut, which the old check had caught); the advance now follows the weight, with a W-7 render test, and RI-1040's 72 pt signature and preparer date boxes joined the pending decision.
  - *Open items:* faces other than Helvetica and Courier (ND-1's Verdana, Calibri, Open Sans) are still measured as Helvetica, which under-measures Verdana's digits; 1,201 pack budgets admit a budget-length digit string their box cannot print, mostly budgets equal to the widget's own /MaxLen, which the maxlen convention keeps, so verify judges the actual value there.
  - *User half (KG9), open:* RI-1040 sizes four kinds of box for their Courier New 12 glyphs edge to edge. The dependent date-of-birth box (57.6 pt) holds 7 digits whole: MMDDYYYY loses about 0.6 pt of its last digit, MMDDYY fits, and 8 digits fit whole at 11 pt. The centred middle-initial box (7.2 pt, one glyph) cuts a wide initial such as M or W by up to 0.9 pt a side (I fits). The suffix box (21.6 pt) cuts III by about 0.6 pt (JR and SR fit). The signature and preparer date boxes (72 pt) cut a 10-character date by about 0.6 pt (01/15/24 fits). Until the user chooses a shorter date, a smaller font or a documented clip, `verify.PENDING_CLIP_DECISIONS` keeps those boxes' old verdict (PASS, with the measured cut in the check's detail); recording the choice deletes the row.
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
- *Done — moved verbatim to [HISTORY.md](HISTORY.md) in the commit that lands this ROADMAP (Phase K JK1, planned 2026-10-09):* JS3a, JS3b, JS3c, JS4a, JS4b, JS4c, JS4d, JS4h.
- *Done — moved verbatim to [HISTORY.md](HISTORY.md) on 2026-10-15 (Phase K JK1):* JS2c (done); JS5 and JS6 (closed: deferred, on demand — Phase K re-plan; what is left is in each box there and in Phase K's Deferred list).
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
