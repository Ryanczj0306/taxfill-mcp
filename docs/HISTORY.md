# TaxFill — history of the completed phases

Moved verbatim from docs/ROADMAP.md on 2026-09-28 (Phase J JD2): the ROADMAP keeps the open work, and this file the record of how the finished phases were built. Nothing here is open — every box below is `[x]`.

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

- [x] **A THIRD checkbox-topology blind spot, MEASURED 2026-08-26 (Phase I2).** → Phase J **JEb** — CLOSED 2026-09-28 (see JEb).
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
- [x] **`maxlen` on the 11-wide plain SSN widget is pinned two different ways
      (found 2026-08-26).** → Phase J **JEa** — CLOSED 2026-09-28: 11, the widget's own `/MaxLen`, repo-wide (test_pack_maxlen.py). `sched_b` / `sched_c` / `sched_8812` / `f2555` / `f8889`
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

## Phase I — Retirement-account, HSA, equity-comp and treaty-disclosure decision surfaces (Effort: L)

> **Scope: six decision surfaces the engine did not model** — IRA pro-rata, the Roth
> conversion and its NIIT crossing, the HSA payroll tier, ESPP basis, the capital-loss
> carryover, and treaty disclosure. Every figure they need already shipped verified in the
> knowledge packs (`rate_schedules`, `standard_deduction`, `niit`, `contribution_limits`,
> `capital_gains_brackets`; Rev. Proc. 2025-32 / Notice 2025-67 / Rev. Proc. 2025-19); what
> was missing is the *decision surface*, the same failure signature `FIELD_NOTES.md`
> records for Phase H. Eval `s` pins each decision on its own synthetic fixture (demo
> numbers).

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
      rolled**. Illustrative (demo numbers): rolling a $42,000 pretax
      401(k) into a traditional IRA makes a $6,000 backdoor 87.5% taxable, which costs
      **$1,680 in year 1 and $9,904 over ten years** at 32% versus rolling it into
      the new employer's 401(k), and the failure mode is invisible —
      no error, no warning, just a larger tax bill and a Form 8606 basis the filer
      must track for life. Build: **`calc.ira_pro_rata`** (per-account year-end
      balances + cumulative nondeductible basis + conversion amount → taxable
      amount, basis consumed, basis carried forward); **`calc.roth_conversion`**
      covering BOTH paths, which behave differently and are routinely conflated —
      (a) plan → Roth IRA *direct* rollover (Notice 2008-30: taxable = the pretax
      portion, and **pro-rata does not apply** because no IRA is involved), and
      (b) traditional IRA → Roth (pro-rata applies) — each surfacing bracket
      headroom and the NIIT threshold crossing (demo numbers: a joint return
      converting a $38,000 old plan directly moves MAGI 236,000 → 274,000, crossing
      the $250,000 §1411 threshold and creating $160 of NIIT on other investment
      income the filers had no way to anticipate, while spilling $30,400 out of the
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
      cannot help them disclose. (b) **Form 8938** pack + an **FBAR
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
      re-runs the SIX Phase I decisions on independent synthetic fixtures (demo
      numbers) against the ops I1-I4 shipped, and pins the numbers the engine
      produces: the 401(k) rollover destination under IRC 408(d)(2) (a polluted
      $42,000 pool makes 87.5% of a $6,000 backdoor taxable and sticks $5,250 of
      basis; a clean one is fully non-taxable), a joint $38,000 direct plan-to-Roth
      conversion with its 7,600 of 22%-bracket headroom, the $30,400 spill into 24%
      and the section 1411 crossing that costs $160, the HSA payroll saving and its
      Medicare-only tier, the ESPP basis correction
      (corrected basis minus broker basis equals the ordinary income exactly — that
      difference IS the double taxation) plus the qualifying-sale-at-a-loss cell that
      recognises zero ordinary income, the $3,000 cap with a character-preserving
      carryover, and a treaty exemption whose disclosure the engine can finally name
      (a treaty-disclosure check on its own hypothetical fixture, Korea Art. 21(1),
      $2,000). It also pins the two guards the reviews added: `roth_conversion` REFUSING the
      input whose income it does not price, and `foreign_asset_reporting` refusing to
      decide until its elicitation questions are answered. The file's own scenario
      census ("sixteen scenarios (a–p)") was stale by three and is corrected.
      *(original scope below)*
- [x] **I6 scope as planned — an eval for the six decisions.** Encode the six
      decisions as an eval scenario so these gaps cannot silently reopen.
      **Acceptance:** i14 runs green and fails loudly if any of I1–I4 regresses.

**Sequencing within Phase I:** I1 → I2 (I1 has the higher consequence
and no dependencies) → I3 (its `f8949` is a prerequisite for a *complete* Schedule D
filing path, so it arguably outranks I2 — decide on whether the user base sells
stock) → I5 leftovers → I4 (highest stakes but the most research) → I6 last, since it
asserts everything above. **Deps:** none external. Phase A is orthogonal and should
not wait for any of this.

---

