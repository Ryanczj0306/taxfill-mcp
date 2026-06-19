# TaxFill — Completion Roadmap (remaining work)

The design spec is [`docs/DEV_PLAN.md`](DEV_PLAN.md). This is the forward-looking
plan for what is **not yet done**, as of the current state.

## Where we are

Done and on `main` (1222 tests): M0 scaffold · M1 engine · M2 federal packs
(f1040, f1040-NR, f8843, sched 1/2/3/A/B/C/OI — audited) · M3 intake + knowledge
(intake_checklist, estimate_refund, get_sources, file_and_pay, filing_summary;
federal knowledge 2019–2024 fully cited) · M4 MCP server (21 tools, stdio, image
content, in-memory e2e tests) · M5 state support (state_scope, no-income-tax
states, **knowledge packs for all 41 income-tax states + DC**, cited credits for
all of them) · M6 code (SKILL.md cookbook, §14 eval harness, §13 README, MCPB
build recipe) · Phase B (`extract_document`, resumable workspace + `taxfill
purge`) · introspect pack-authoring CLI · Phase A launch packaging + drift CI.

**Form packs that can be FILLED today (all introspect→vision-map→adversarial-
audit→golden):** federal — f1040, f1040-NR, f8843, Schedule 1/2/3/A/B/C/OI/SE,
**Schedule D, Schedule E, Form 8863, Form 2555** (#6 priority set complete);
state — CA Form 540 + 540NR + **Schedule CA 540 + 540NR**, **NY IT-201 + IT-203**,
**IL IL-1040**, **PA PA-40**, **OH IT 1040 (13-page bundle)** — 5 states fillable.
40 form packs total.

**Quality bar (non-negotiable, applies to every item below):** no invented
numbers — every figure cited to a .gov/.us source or shipped with an explicit
`unverified` caveat; every form-pack field map adversarially **vision-audited**
before it ships; tests green; feature-branch → `--no-ff` merge.

The eight remaining workstreams, with the phase that schedules each:

---

## 1. State form packs — the biggest gap (Phase C)

**STATUS (2026-06-19):** **5 states now fillable** — CA (540, 540NR, Schedule CA
540 + 540NR), NY (IT-201 + IT-203), **IL (IL-1040)**, **PA (PA-40)**, **OH (IT
1040 full 13-page bundle)**. Rolling out by population; next tranche: GA → NC →
MI → NJ → MA → …, then each state's nonresident/part-year form where it is a
separate form (IL Schedule NR, OH IT NRC, etc.).

**Why:** ~45 jurisdictions can still only be *scoped*, not filled.

**Scope:** 36 states + DC have fillable AcroForms (resident + nonresident/part-
year forms) + their adjustment schedules (Schedule-CA equivalents); plus 5 hard
states (IA/NM flat-or-XFA, CT/SC print-only, MA fetch-recheck).

**Method:** the proven CA pipeline — `scripts/introspect_pdf.py` (sentinel
sweep) → per-page vision-mapping workflow → `assemble_*` → adversarial vision
audit → `test_formpacks_states.py` golden round-trip. Roll out by population:
NY → IL → PA → OH → GA → NC → MI → NJ → MA → … (~top 10 ≈ most of the US).

**Steps:** per state: (a) introspect the resident form; (b) vision-map (6 agents);
(c) assemble pack.yaml (relations from printed labels; cross_form line = federal
AGI; flat AcroForm); (d) audit every page, fix, re-audit; (e) repeat for the
nonresident/part-year form + adjustment schedule. Then the hard states: XFA
handling (federal already does XFA), an OCR-positioned overlay filler for
print-only forms, or a documented "print + hand-fill from computed values"
fallback.

**Acceptance:** each pack loads, golden round-trip clean (fill→verify→render all
pages), field map audited clean. **Effort: XL.** **Deps:** none (pipeline ready);
hard states depend on the new overlay-filler engine work.

## 2. State credits data — 41 states (Phase C, parallel with #1)

**Why:** only CA's knowledge pack has a `credits` block; the other 41 show no
`benefits_candidates` in state_scope.

**Method:** one fetch-and-verify workflow wave (like the all-states knowledge
fetch) gathering each state's common credits (state EITC, renter's/property
credits, child-care) with eligibility predicates + cited amounts; assemble into
the existing `credits` block of each `knowledge/states/<st>/<year>.yaml`.

**Acceptance:** each state pack gains a cited `credits` block (or an explicit
"no notable credits" note); state_scope surfaces them with the unverified-caveat
plumbing already in place. **Effort: M.** **Deps:** state knowledge packs (done).

## 3. `extract_document` tool (Phase B)

**Why:** the §2 "extract & confirm" step is the one §8 tool not built; the agent
currently reads documents with its own vision and the user confirms.

**Method:** a `taxfill_core.extract` module + MCP tool that parses common docs
(W-2, 1099-NEC/INT/DIV/B, 1098-T, I-94, I-20) into structured fields **with
per-field provenance** (file, page). Hard rule preserved: missing = null, never
guessed. v1 can wrap the agent's vision output into the confirm-table contract
(server validates + structures) rather than bundling OCR; a later pass adds
on-device OCR.

**Acceptance:** `extract_document(path, kind_hint?)` returns typed fields +
provenance + a gap list; round-trips into `estimate_refund`/`fill_form`; tests
with synthetic documents. **Effort: L.** **Deps:** none.

## 4. Resumable workspace + `taxfill purge` + RECONCILIATION.md (Phase B)

**Why:** §2 promises a resumable on-disk workspace; today state lives only in the
conversation, and RECONCILIATION.md is agent-maintained (not generated).

**Method:** `taxfill_core.workspace` — `taxfill-workspace/<year>/` holding
`profile.json`, `documents/`, `drafts/`, a generated `RECONCILIATION.md` (the
position/authority audit trail) and `CHECKLIST.md`; load/save/resume; a
`taxfill purge <year>` CLI that securely wipes it. Wire the MCP server to
read/write the workspace so any client resumes from state.

**Acceptance:** a filing can stop and resume across sessions; RECONCILIATION.md
is generated from recorded positions; `purge` removes all PII-bearing files;
tests. **Effort: L.** **Deps:** none (but improves #3's confirm flow).

## 5. Launch ops — ship v0.1 (Phase A)

**Why:** nothing is installable by a normal user until this lands.

**Steps:** (a) publish `taxfill-mcp` to PyPI (enables `uvx taxfill-mcp`);
(b) build + sign the `.mcpb` bundle per [`bundle/README.md`](../bundle/README.md);
(c) record the 60-second demo GIF; (d) run the §13 non-developer 20-minute
acceptance test and fix what blocks a non-technical user.

**Acceptance:** `uvx taxfill-mcp` and the one-click `.mcpb` both work; a
non-developer reaches a filled sample form in <20 min following only the README.
**Effort: S–M (mostly ops + needs publish credentials).** **Deps:** maintainer
PyPI access.

## 6. More federal forms beyond the M2 set (Phase C, as scenarios need)

**STATUS (2026-06-19): COMPLETE for the listed priority set.** Schedule SE,
Schedule D, Schedule E, Form 8863, Form 2555 are all shipped (2023), audited, and
golden round-trip green. Further forms can be added on the same pipeline as
scenarios demand.

**Why:** common situations need forms M2 didn't include.

**Scope (priority order, all DONE):** Schedule SE, Schedule D (cap gains),
Schedule E (rental/K-1), Form 8863 (education credits), Form 2555 (foreign earned
income exclusion). Each via the M2 pipeline (introspect → map → audit) + its
`calc`/relations as needed.

**Acceptance:** per form: pack audited + golden round-trip; any new computed line
backed by cited `calc` data. **Effort: M–L.** **Deps:** none.

## 7. M7 scale-out — tooling + new form types (Phase D)

**Scope:** a pack-authoring CLI (`taxfill introspect blank.pdf` → pack skeleton;
`scripts/introspect_pdf.py` is the seed) to mechanize #1/#6; amended returns
(1040-X), extensions (4868), estimated-tax vouchers (1040-ES), ITIN (W-7); more
tax years; a community pack-contribution pipeline.

**Acceptance:** the CLI emits a skeleton pack from any fillable PDF; each new form
type is audited + tested. **Effort: L–XL.** **Deps:** #1 (validates the CLI on
real state packs).

## 8. Nightly drift CI (Phase A)

**Why:** §7 freshness protocol promises a job that catches moved pages / new form
revisions / changed addresses.

**Method:** confirm/extend the scheduled job in `.github/workflows/ci.yml` to
re-fetch `sources.yaml` URLs + form `source_url`s + mailing addresses and fail
loudly on PDF-checksum or address drift (it already runs the network goldens on a
schedule — extend it to the drift checks).

**Acceptance:** a scheduled CI run flags any drifted source/address/checksum.
**Effort: S.** **Deps:** none.

---

## Phased sequencing

- **Phase A — Ship v0.1 (small, high-leverage):** #5 launch ops + #8 drift CI →
  the project becomes installable and self-maintaining.
- **Phase B — Single-user completeness:** #3 extract_document + #4 workspace →
  the federal flow is truly self-serve and resumable across days.
- **Phase C — Coverage breadth (the big rollout, parallelizable):** #1 state form
  packs (by population) ‖ #2 state credits ‖ #6 more federal forms.
- **Phase D — Scale-out:** #7 pack-authoring CLI + new form types (1040-X, 4868,
  1040-ES, W-7), which in turn accelerates the tail of Phase C.

Phases A and B are mostly independent and can run before/alongside C. Within C,
state form packs are the long pole; the pack-authoring CLI (#7) is the force
multiplier — pulling a slice of #7 forward (the CLI only) would speed #1/#6.
