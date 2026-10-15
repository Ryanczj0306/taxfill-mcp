# ADR-0001 — Pointer-first: packs for high-volume current-year forms, a guarded no-pack fallback for the rest

- **Status:** Accepted by the user on 2026-10-09; the rebuilt draft was reviewed and committed on 2026-10-15.
- **Scope:** which forms get a curated form pack, what the agent does when none exists, and what the knowledge layer holds.
- **Tracked in:** docs/dev/ROADMAP.md, Phase K (tranches JK0, JK0a, JK1–JK26, with the kept ids JA1, JA2, JD2.3, JEe, JS2c, JT5g, JT6 and JS7a). This file lands in the same commit as that ROADMAP (JK1).
- **Repo state when decided:** main @ 063f293. Line references below are as of that commit.

## Context

TaxFill is an MCP server. Its job is to point an agent at the right official form, rule and figure for a US return, compute the deterministic parts and verify the fill. On 2026-10-09 it shipped 23 tools (server.py, gated at ci.yml:115) and 40 calc ops (packages/mcp-server/tests/test_skills_sync.py:54). Pack counts: federal packs for 2019–2026; state packs for TY2023 (all 42 income-tax jurisdictions), TY2024 (26) and TY2025 (41). A recovery wave is re-creating and integrating a further 23 state packs: on 2026-10-09 only 6 of them had a pack on disk in scratch (al24, de24, depitnon23, md24, ne24, ok24); the other 17 survive only as replay logs and are being re-created, each under KG1, with a 2026-10-23 cut-off.

Three findings drove the decision:

1. **The pack-everything backfill no longer pays.** Phase J's state lanes (JS5/JS6) were porting TY2024 and earlier returns and nonresident/part-year forms one at a time. Each costs a vision re-map, an adversarial verify and a golden test. The remaining work was ~20 re-maps plus ~26 URL-discovery tasks (ROADMAP D2, 2026-09-28 re-measure) for years whose original due dates had passed. Meanwhile there is no installable release (PyPI names unregistered on 2026-10-09; no tag, no CHANGELOG, no release.yml).
2. **A field → printed-line map cannot be derived safely at use time.** The ME 1040ME 2023 pack had lines 21–23 rotated one box, and every relation still passed. Relations check arithmetic consistency under the map; they cannot see a consistent mis-map. This is why the packs exist, and it is why a pack-less path must never claim filing-grade. The defect is still on main at 063f293 (formpacks/states/me/2023/f1040me/pack.yaml:356-363 binds line 21 to the widget named "1040ME Nonresident credit", which sits on another printed row); the fix (bind by printed row, pitfall P-032, a label-adjacency test) is built and verified in scratch but not committed, and lands as JK0a. The same class hit AL Form 40 2023 (P-031, docs/dev/ROADMAP.md:2391): keys one number high, relations matched, verify never flagged it. In both cases the rotation sits in the base pack, so a year-to-year field diff cannot see it.
3. **The knowledge layer duplicates official text, and the duplicate drifts.** Calc applies roughly 4% of state knowledge bytes and ~11% of federal leaf bytes. About 1.2 MB of state prose is read by nothing at runtime. The JS2c corrections (25 mismatches surfaced by the last port wave) were all in narrative, pointer labels or figures calc does not apply: "line 11" vs "11a", GA's 30% vs 50% credit rate, MA's $1,700 vs $700 line 2c. None were in a figure that `calc.state_tax` applies (the exemption, standard-deduction, flat-rate and bracket arithmetic at calc.py:10985-11019). Narrative still reaches calc output, though: state_tax emits `params.tax_line` and every `tax.notes` entry in its work string (calc.py:11037-11042), so drift like MN's "line 11" vs "11a" caption is printed by a calc op even though it is not applied arithmetic. JK23 and JK26 cover that text.

What already exists toward a pack-less path: `render_form(pdf_path)` is already a shipped MCP tool that renders any PDF with no pack (server.py:410-424), so the vision check runs at use time today. The rest exist as core or CLI authoring tools: `fetch_blank` with sha256=None (but refused for a pinned-only host, fetch.py:335-340, and mirror-served only digest-verified, :224-225), `extract_fields` (packbuild.py:67), `overlay.locate_labels`, `clipping_scan`, `widget_flag_problems`, and the rehearsal stamp (filler.py:785-793; an unprinted annotation, see KG5). Label anchoring has prior art as a test pattern: packages/core/tests/test_al40_line_designators.py (P-031) reads the printed number beside every numbered page-1 widget. None of the fill, verify or fetch tools runs without a pack: each starts at `_load_any_pack` (server.py:181-195). Today the only no-pack guidance is the skill telling the agent to "fall back to `get_sources` + the official blank" (skills/claude/SKILL.md:180-182, :291-292).

## Options considered

| Option | What it means | For | Against |
|---|---|---|---|
| **A. Status quo: pack everything** | Keep porting every state × year × form type (JS5, JS6, JS7 for all states), and keep the knowledge layer's narrative | Every supported form is filing-grade; one quality bar | Unbounded: about 42 jurisdictions × years × NR/PY/amended variants, each a vision re-map. The long tail (city and local returns, rare schedules, old years) never gets covered. Release and the TY2026 season compete with backfill for the same weeks. The narrative keeps drifting. |
| **B. Pure pointer, no packs** | Return the official URL, quotes and calc figures. The agent fills any blank itself at use time. | Smallest maintenance surface; covers every form nominally | Unsafe for the forms most people file. A rotated anchor passes every relation (finding 2), so the high-volume returns would lose their only proof of correct placement. It would discard the shipped, audited packs. |
| **C. Hybrid, pointer-first (chosen)** | Curated packs for high-volume current-year forms (federal set; tier-1 states). A guarded no-pack fallback for everything else, always labeled a draft. The knowledge layer slimmed to pointers, verbatim quotes and the figures calc reads. | Keeps filing-grade where the volume is. Covers the long tail honestly. Bounds pack maintenance to about 12 states plus federal per year. Removes the drift surface. | Two paths to explain. The fallback needs a measured anchor precision before it may say "high". The knowledge migration touches consumers and tests (test_state_knowledge.py, test_statescope.py). |

## Decision

Option C, with this priority order (ROADMAP Phase K):

0. Let the running recovery wave finish re-creating and integrating its 23 packs (JK0), dropping any that fail a gate (KG1) or miss the 2026-10-23 cut-off, and land the ME 1040ME 2023 re-bind (JK0a, KG2). Then **stop** TY2024-and-earlier state backfill and the rest of JS6, except on demand.
1. **Release v0.1** (JA1 agent half, JK2–JK7). A release candidate by 2026-10-23. The PyPI publisher, the mcp<2 decision, the tag, the demo GIF and the acceptance tester stay the user's (JA2).
2. **TY2026 readiness.** Federal finals (JT5g, JT6) with working triggers (JK8) and the user's flip decisions made in advance (JK11). JS7 is re-scoped to about 12 high-volume states (JK9 triage, JS7a), each port behind a label-adjacency guard run on the base pack and the port (JK10). Every other state goes through the fallback (JS7b, deferred).
3. **No-pack fallback** (JK13–JK19). Introspect the official blank, anchor widgets to printed labels, fill and verify at use time. Confidence labels are honest, and the path refuses to claim filing-grade.
4. **Slim the knowledge layer** (JK20–JK26) to pointers, verbatim quotes and calc-read figures. Before 2026-12-01 only zero-output-change steps. The TY2025 schema migration happens after 2027-04-15.
5. The Not-scheduled backlog (AMT, ISO/83(b)/RSU, wash sales, IRC 32(d)(2)(B), past-year Medicare/402(g), the extra DocSpecs) is unchanged.

**What makes a form "pack-worthy":** a current-year (or prior-year, while it is being filed or amended) federal form in the shipped set, or a tier-1 state's resident return **for the current filing-season year** (TY2025 now, TY2026 from JS7a). Tier-1 means ranked by IRS SOI individual-return counts in the committed JK9 table (high volume, the user's criterion; weighting toward where nonresident-alien students cluster is a recommendation the user may accept or reject in JK9, not part of this decision). A tier-1 NR/PY form qualifies where a pack lineage exists (CA 540NR, NY IT-203). TY2024-and-earlier state packs are built only on a specific user request under the ROADMAP's on-demand rule (Phase K, Deferred), never because the year can still be amended. Anything else gets a pack only on demand.

**MCP surface:** the recommendation is to keep 23 tools and ride the existing ones (`form="unmapped"` + `source_url` on fetch_blank / fill_form / verify_form / get_form_map), on the overlay precedent (server.py:181-195; test_overlay_tools.py:54). The final call is ADR-0002 (JK13). If the existing tools are ridden, `grade: "unmapped_draft"` appears in every response field, not only the summary. Riding them adds input parameters and response fields to four shipped tools, which KG8 permits during the 2026-12-01 → 2027-04-15 freeze only as additive, opt-in, unmapped-only changes with every pack-path response byte-identical under the JK21 golden diff. A 24th tool would edit every hard-coded "23": ci.yml:115, test_cli.py:69/:78, test_server_e2e.py:19/:397, bundle/manifest.json, test_overlay_tools.py:54, docs/dev/PUBLISHING.md:89 and :135, docs/TOOLS.md:3, and packages/mcp-server/pyproject.toml:4 (the PyPI description, immutable once v0.1 is uploaded; JA1 makes it count-free).

## Guardrails for the fallback path

| id | Rule | Where it is enforced |
|---|---|---|
| KG5 | **Never filing-grade.** Every response carries `grade: "unmapped_draft"`, and every page is stamped "UNMAPPED DRAFT — NOT FILING-GRADE". The stamp is drawn into the page content stream (flattened): the rehearsal stamp (filler.py:785-793) is a pypdf FreeText annotation without the /F Print flag (pypdf sets PRINT only on Highlight, annotations/_markup_annotations.py:302), so it would not print and can be deleted. No flag, prompt or knowledge-pack state lifts the grade or the stamp. `provisional_marker` returns None for a jurisdiction with no pack (knowledge.py:2702-2712), so the grade must not depend on it. | JK16 (content-stream stamp; print path rasterised and OCR-checked on every page), JK17 (grade; verify fails on a page without the stamp), JK6/JK18 (journey goldens and evals assert it) |
| KG6 | **Measured before trusted.** Anchoring is benchmarked blind against ≥30 shipped packs, federal and state. The ME 1040ME 2023 3-cycle and the AL 40 2023 shift are mandatory cases, and every disagreement with a pack is vision-adjudicated before the pack counts as ground truth. The table reports per-field precision and a per-form "any mis-anchored field" rate. The top tier needs measured per-field precision ≥99% and is worded "anchored (unverified line map)", never a bare "high". If the benchmark fails, the fallback ships inspect + worksheet only, with no PDF fill. | JK15 |
| KG7 | **No model arithmetic presented as computed.** A value no calc op produced is labeled "agent-computed, unverified". ReadOnly, pushbutton, viewer-guard and calculated (/AA calculate or format action) widgets are never filled; they come back as "hand-write these". | JK14 (/AA detection), JK16, JK17, JK18 |
| KG11 | **Refuse what cannot be anchored.** Unmapped `fill_form` refuses a value whose target widget is anchored `none`, and `low` unless the user confirms that field on the rendered page (recorded per field). Refused fields come back as "hand-write these". | JK16 (a planted unanchorable widget is refused), ADR-0002 (JK13) |
| — | **Verified before "done".** The unmapped fill response says `status: "unverified_draft"` with the next step (verify_form, then render_form on every page). A passing verify returns a `verified_at` token bound to the output sha256. Evals assert the agent never says "done" or "complete" before verify has run on that sha. | JK16, JK17, JK18 |
| — | **Official source, right revision.** Official host only. sha256 recorded, not pinned, except where today's rules require a pin: a pinned-only host (fetch.py:88-95, :335-340; NM today) and a Wayback mirror for a 403 host (fetch.py:224-225; mass.gov) are refused with a pointer, or served from a user-supplied local blank whose page-1 check stands in for the pin. A pack-less fetch force-refreshes rather than trusting the cache (fetch.py:352-354 returns any cached copy when sha256 is None; IL-1040 and OK 511 are rotating "current" URLs). The page-1 printed year and title must match the request, on a cached copy as well as a fresh one. XFA-only and scanned blanks are refused. | JK14 |
| — | **Explicit LIMITS.** Every verify result lists what it could not check: no line map, no relations of record, no identity or cross_form checks, no P-003 groups, no revision pin. This follows OVERLAY_VERDICT_LIMITS (overlay.py:219-230). `ok: true` never implies filing-grade. | JK17 |
| — | **Pack-free checks that still run:** round trip of exactly the written names; regression_diff against the fetched blank (nothing else changed); PDF /MaxLen and width clipping (P-001); widget flags (P-027); render plus the agent's vision check of every page. | JK17, JK18 |
| KG10 | Benchmarks, pilots and goldens use demo personas only (public repo). | JK6, JK15, JK19 |

Companion guardrails for the pack path:
- **KG1:** a scratch pack that fails a gate is dropped, not patched.
- **JK0a:** the ME 1040ME 2023 re-bind (P-032) lands before the release candidate (KG2).
- **JK10:** a label-adjacency guard (the printed line number beside each mapped widget must equal the pack's line key) runs on the base pack and on every port; it is what catches the rotation class, because the ME and AL rotations sat in the base pack and a year-to-year field diff reports them as unchanged. A /Rect diff between years is kept as a secondary signal.
- **KG8:** output freeze from 2026-12-01 to 2027-04-15 for the pack path and the knowledge consumers; additive, opt-in, unmapped-only fields are allowed with the pack path byte-identical.

## Consequences

- **Positive.**
  - A release can ship this month: the RC is agent-controlled, and the upload is gated only on the user's JA2 steps.
  - Pack work per year is bounded: federal plus about 12 states.
  - The long tail (city and local returns, rare schedules, old years, non-tier-1 states) gets a usable, honestly labeled draft instead of "no pack".
  - Knowledge drift shrinks to quotes that a checker holds to the source (JK23, enforcing from JK26).
- **Negative / accepted.**
  - TY2024 stays at whatever JK0 lands (every jurisdiction but MA only if all 23 are re-created and pass KG1; 17 of them exist only as replay logs). Older years and the three CT NR/PY forms are fallback-only.
  - Users in non-tier-1 states get a draft, not a filing-grade return, for TY2026.
  - The fallback cannot detect a consistent mis-anchoring without a pack. Render plus vision review is probabilistic, so the unconditional label is the real guard.
  - Riding the existing tools means pack and unmapped results share one schema.
  - New TY2026 state packs may still be born in schema v1 if JK24/JK25 miss 2026-12-01, and migrate later.
- **Neutral.** The calc ops and relation verify are unchanged. The tool count stays 23 unless ADR-0002 decides otherwise.

## What we stop doing

- Porting TY2024-and-earlier state returns, and nonresident/part-year state forms outside tier 1, except when a user asks (JS5/JS6/C2/D2 remainders: deferred).
- URL discovery for old-year state blanks (the "20 never-started states plus OK, MA and NE" pool).
- Folding TY2024 leftovers into the TY2026 state sprint.
- Re-triaging and packing every state for a new tax year. JS7 becomes tier-1-only.
- Writing state narrative that paraphrases official text. New text is a verbatim quote with a source ref, or a pointer (`ref` + page). Figures go in only if a calc op reads them. After the freeze, YAML header diaries move to commit messages.
- Growing the knowledge layer for the long tail. The local-collector table and the NYC rate-schedule op the user-journey plan proposed are not adopted (on demand only).

## Review triggers

Revisit this ADR in any of these cases:
- JK15's benchmark cannot reach ≥99% precision on any confidence tier.
- The JK19 pilot shows drafts being mistaken for finals.
- Observed demand for a non-tier-1 state or an old year exceeds what the fallback serves. The ROADMAP's on-demand rule (Phase K, Deferred: an explicit user request or a filed issue naming form and year opens its own JK tranche, which must pass JS5's acceptance, the JK10 guard and KG1) then promotes that form to a pack.
