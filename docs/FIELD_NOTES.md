# Field notes — gaps found in real sessions

A running log of gaps surfaced by **real users driving a real agent**, as opposed to the
synthetic persona reviews that produced Phase F/G. Each entry records the situation, what
the user actually said, what the engine/intake did with it, and the smallest honest fix.
Roadmap items derived from these live in [`ROADMAP.md`](ROADMAP.md).

---

## 2026-08-04 — Two unmarried NRAs, one household; F-1 OPT → H-1B; TY2026 *budget*

**Situation.** User asked for a **forward-looking 2026 tax budget** (not a filing) for a
household of two unmarried nonresident aliens: user is F-1 OPT transitioning to H-1B during
2026; partner is an NRA on OPT. The filer's own words are omitted here for privacy
(see the privacy note at the head of this entry).

**What went wrong (before any tool was called).** The agent (me) opened with a three-option
multiple-choice question — tax year / "status" / state — with coarse buckets (an "F-1 / J-1 student or
scholar" status bucket; a state bucket of two named states, "no-income-tax state" and "moved mid-year"). The filer rejected it as too coarse, twice,
and was right both times. Note the failure is **not** an engine limitation:
`VisaPeriod` (`packages/core/src/taxfill_core/schemas/profile.py:104`) is already a
`{status, start, end}` *period list*, and `StateFootprintYear`
(`…/schemas/profile.py:293`) is already `lived[] / worked[]` date ranges with a `remote`
flag. The data model is right; the **elicitation** is what collapses multi-period reality
into one word.

### N-1 — Visa status has no sub-status vocabulary, and no per-period tax attributes

`VisaPeriod.status` is a free-form string (`…/schemas/profile.py:107`, example values
`'F-1' / 'H-1B' / 'J-1'`), categorized downstream only by prefix match:
`residency._categorize_status` (`…/residency.py:364`) and the intake helpers
`_has_f1_period` / `_has_f_or_j_period` (`…/intake.py:170,178`, `startswith("F")`).

Consequences for exactly this user:

- **OPT / STEM OPT / cap-gap are invisible.** All three are F-1 (so the prefix match is
  *correct* for the exempt-individual rules), but they are the periods where the user is
  **working full-time**, and they are the periods whose **end date** sets the H-1B
  boundary. Nothing in the profile distinguishes "F-1 studying" from "F-1 working on OPT".
- **No per-period FICA attribute.** The single biggest cash-flow fact in this user's 2026 —
  employee FICA (7.65%) switching **on** at the H-1B start date — is derivable only by
  re-inferring it from status strings at every call site. G6 (Form 843/8316) handles the
  *erroneously withheld* case retroactively; there is no forward-looking per-period model.
- **No per-period work-authorization attribute**, so intake cannot ask the right income
  questions per segment (on-campus vs OPT wages vs H-1B wages).
- **The H-1B start date is under-specified in the prompt.** Users routinely give the offer
  date or the onboarding date; the tax-relevant date is the **I-797 start date**.

**Fix shape:** a controlled `sub_status` (or `work_authorization`) enum on `VisaPeriod` —
`student / opt / stem_opt / cap_gap / employment / dependent / other` — plus a derived,
citable `fica_exempt` per period; intake asks for the timeline **segment by segment** with
a worked example, and validates that consecutive periods are contiguous and that an H-1B
period's start is sourced from the I-797.

### N-2 — An unmarried partner cannot be represented at all

The household model has exactly two slots for other humans: `Spouse`
(`…/schemas/profile.py:191`, complete with its own `Immigration` / `ResidencyFacts` — so
the *NRA-spouse* persona is well covered) and `Dependent` (`…/schemas/profile.py:172`).
There is nothing for an **unmarried cohabiting partner**, which is the modal
international-student-couple household.

Why it matters even though they file separately:

- The user asked for a **household** budget. Two returns, one rent, one cash-flow question.
  The agent has to carry the second person entirely out-of-band.
- Two conclusions the tool should be *stating*, not leaving to the agent's memory:
  (a) unmarried ⇒ **no MFJ**, each files their own return (`single` for an NRA — see the
  intake confirmation at `…/intake.py:455`); (b) an NRA partner generally **cannot** be
  claimed as a dependent (the dependent must be a U.S. citizen/national/resident), which
  is exactly the mistake a no-experience filer makes after reading "qualifying relative".
- If they marry mid-year, the §6013(g)/(h) election (already built, Tier 2) becomes a
  large-dollar planning lever — but only if the second person exists in the model *before*
  the wedding.

**Fix shape:** a `household.other_taxpayers[]` (name/status/own profile ref, relationship =
`unmarried_partner | roommate | …`), used for (a) explicit "you file separately" guidance,
(b) the anti-dependent guard, (c) a household-level budget roll-up across two profiles, and
(d) a "if you marry in <year>" planning branch.


### N-3 — State footprint is one open-ended question

Intake asks it once (`…/intake.py:661`): *"For the tax year, where did you LIVE and where
did you WORK, with date ranges?"* — with a one-sentence disambiguation. For someone who has
never filed, that question does not surface the things that actually create a second state
return. The filer's complaint — that the state question could not be answered in one line — is about this.

**Fix shape:** replace the single question with a **segment loop** (one row per date range:
lived-state / worked-state / remote / employer state) plus an explicit trigger checklist the
agent must walk: mid-year move, cross-state remote work, >~30-day out-of-state assignment,
school in one state + internship in another, W-2 Box 15 ≠ state of residence, periods
outside the U.S., and — the counter-intuitive one — **no-income-tax-state segments still
need their dates**, because the *other* segment is what forces a return.

### N-4 — No forward-year support and no planning/budget mode

`calc` for TY2026 fails closed (correctly, and with a good message):

```
no knowledge pack for jurisdiction 'federal', tax year 2026 — looked for
knowledge/federal/2026.yaml … follow the freshness protocol (DEV_PLAN §7)
```

`list_forms {"year": 2026}` → `[]`. Both are the designed behavior, but they mean the
product cannot answer *"what will I owe / what should I set aside"* — which is what a user
asks **during** the year, i.e. the highest-frequency question there is.

> **Update 2026-08-07 — this premise no longer holds.** `knowledge/federal/2026.yaml`
> shipped as a `provisional: planning_only` pack (H5 first tranche), so **8 of the 17
> `calc` ops now succeed for TY2026** (tax, standard_deduction, the preferential-rate
> path, se_tax, the two surtaxes, …); the 9 that still fail closed are the ones whose
> 2026 authority is unpublished (ptc, taxable_social_security, student_loan_interest,
> education_credits, dependent_care, and the M3 logistics blocks). `list_forms {"year":
> 2026}` is still `[]`. The gap this note describes has therefore **moved**: the problem
> is no longer that 2026 fails closed, it is that (a) `estimate_refund` will happily
> return a confident-looking `ESTIMATE` for 2026 — exactly what H4 exists to prevent —
> and (b) nothing stops a provisional pack from backing a filed return. Beyond the missing
year pack, budgeting needs ops that do not exist:

- **employee FICA by status period** (7.65% on/off at a status boundary, SS wage base cap);
- **withholding adequacy / §6654 safe harbor** (90% current year vs 100/110% prior year) —
  needs prior-year AGI + total tax, which the profile does not collect (`PriorFilings`
  holds `filed_years` / `late_filing_context` only, `…/schemas/profile.py:338`);
- **annualization** from YTD paystub figures + a per-period wage projection;
- and an output contract that is clearly a **PROJECTION** (distinct from the existing
  `ESTIMATE` label, which means "partial data for a *closed* year").

### N-5 — Nothing for a user with zero filing experience to fill in

There was no artifact to hand the user. Written in this session:
[`INTAKE_WORKSHEET.zh-CN.md`](INTAKE_WORKSHEET.zh-CN.md) — a fill-in worksheet whose three
opening rules are *"don't guess, write 不知道"*, *"every identity/address fact is a date
range, not a word"*, and *"one worksheet per person; unmarried ⇒ two taxpayers"*. It should
become a first-class, localized, canonical-in-English product surface, ideally emitted by
`intake_checklist` itself rather than living only as a doc.

**Follow-up (same session, after the real numbers came in).** The household asked for a
marry-vs-stay-single comparison. Running it exposed four more gaps, all of which had to be
computed OUTSIDE the engine in a scratch script — every one of them changed the answer by
hundreds to thousands of dollars:

- **N-6 — Schedule 1-A (OBBBA) is not modeled at all.** The 2026 return carries four new
  deductions (tips / overtime / car-loan interest / senior) on a new schedule that
  *explicitly attaches to Form 1040-NR too* (line 38 → "Form 1040-NR, line 13c"), plus the
  new §170(p) non-itemizer charitable deduction and the new 0.5%-AGI floor for itemized
  charity. Two of their marry-vs-single deltas came entirely from this: the overtime
  deduction is **forfeited by anyone married who does not file jointly** ("If married, you
  must file jointly to claim this deduction" — Part III caution), and the car-loan interest
  deduction phases out at a MAGI the household crosses only *after* marrying. Needed: a
  `sched_1a` knowledge block (caps, thresholds, the $100-per-$1,000-rounded-down vs
  $200-per-$1,000-rounded-**up** asymmetry between Parts III and IV) and a calc op.
- **N-7 — no employee-FICA-by-status-period op** (already scoped as H4), and the related
  trap: the F/J student FICA exemption is **status-based, not marital**, so a §6013(g)
  election does not start FICA on an OPT spouse's wages — but nothing in the engine states
  that, and on a two-earner NRA household it is a four-figure annual question.
- **N-8 — the NRA bank-deposit-interest exclusion (§871(i)(2)(A)) is not modeled.** The
  bank sends a 1099-INT; on a 1040-NR that interest is exempt, and it becomes taxable the
  moment a §6013(g) election makes the payee a resident. `extract_document` happily structures
  the 1099-INT with no note that the payee's status decides whether it is income at all.
- **N-9 — there is no "compare filing scenarios" surface.** The whole deliverable was a
  three-way comparison (unmarried / married-MFS / married-with-§6013(g)-election). The
  engine has every primitive and no way to say "run these three and diff them"; the
  estimator answers one scenario at a time. This is the shape a *planning* question always
  takes.

### The coverage verdict (the most useful thing this session produced)

Of the **22 MCP tools**, the session used **four** — `intake_checklist`, `state_scope`,
`get_sources`, and `calc` — and within `calc`, **five of its 17 ops** (`standard_deduction`,
`tax_with_preferential_rates`, `additional_medicare_tax`, `niit`, plus `treaty_benefit`).
Every number that actually **decided the user's answer** was produced outside the engine, in
a throwaway scratch script over hand-verified irs.gov figures:

| What decided the answer | Where it came from |
|---|---|
| Schedule 1-A phase-outs (overtime, car-loan interest) | hand-coded from the form PDF |
| The three-scenario diff and its per-line attribution | scratch script |
| Employee FICA, and the F/J exemption surviving §6013(g) | hand reasoning + Pub 519 |
| NRA bank-deposit-interest exclusion | Pub 519 ch. 3, hand-applied |
| 401(k)/HSA/IRA/FSA/commuter limits and their scoping | Notice 2025-67, Rev. Proc. 2025-19/-32 |
| §6654 safe harbor (110% rule) | Form 1040-ES (2026), hand-read |
| Excess Roth IRA contribution detection | noticed by the agent, not the tool |

The engine's job — "stop agents rediscovering versioned knowledge every session" (README) —
is exactly what did **not** happen: this session rediscovered a large pile of citable 2026
data that should have been shipped as pack data. That is the gap to close, and it is a
data/knowledge gap far more than an engine gap.

### Later-session gaps (same 2026-08-04 session, after the numbers landed)

- **N-10 — no knowledge of tax-advantaged account limits, and none of their SCOPING.** The
  user's actual question was *"is the 401(k) limit one per person?"* — and the interesting
  answer is that the four limits are scoped four different ways: §402(g) $24,500 is **per
  person across all employers** (and traditional + Roth share it), §415(c) $72,000 is **per
  employer plan** (which is what makes a mega-backdoor possible), the HSA limit is **per
  coverage tier** (so two unmarried people with self-only HDHPs get $4,400 × 2 = $8,800,
  *more* than the $8,750 family limit), and §125(i) $3,400 is **per employee per employer**.
  None of this is in the repo. Needed: a `contribution_limits` knowledge block, and a
  ranking op — "what does one marginal dollar save in each bucket" — which must know that
  a payroll HSA/FSA/commuter dollar also saves FICA while a 401(k) dollar does not, and that
  above the SS wage base the FICA saving is only 1.45% + 0.9%, not 7.65%.
- **N-11 — no Roth-vs-pre-tax modeling, and no excess-contribution detection.** Two separate
  findings, both worth real money: (a) a filer's Roth 401(k) share changes AGI, which cascades
  into six different phase-outs — the tool has no way to represent "of my elective deferral,
  this portion is Roth and the rest pre-tax"; (b) the session surfaced a live **Roth IRA contribution made while ineligible** (a single
  filer whose MAGI sat above the $153,000–$168,000 phase-out) — a 6%-per-year excise-tax error that a
  tool holding both the profile and the limits should flag automatically, and which flips to
  *compliant* if they marry and file jointly, because IRA eligibility is tested at year end.
- **N-12 — supplemental-wage withholding.** A bonus is withheld at the flat 22%
  (Pub 15 (2026)) while a filer in the 32% bracket owes more than that on it — an April shortfall
  that no current surface would predict. Belongs with H4's withholding work.
- **N-13 — MAGI needs to be a first-class object.** This session used at least six MAGI
  tests with different thresholds (NIIT $200k/$250k, 8959's wage test, Roth IRA
  $153–168k/$242–252k, deductible-IRA $81k/$129k, Schedule 1-A $100k/$150k/$300k, §221
  $85k/$175k). The UX signal was the filer asking why their MAGI came out below their
  headline salary: the answer is a **ladder** (gross → box 1 → AGI → each
  test's MAGI), and the tool should render it, because every planning lever works by moving
  a number up or down that ladder.
- **N-14 — naming misleads, and the tool should push back.** The user twice reached a wrong
  conclusion straight from a label: *"married ⇒ she loses the NRA interest exclusion"* (no —
  the **§6013(g) election** does, not the marriage) and *"no tax on overtime ⇒ overtime is
  untaxed"* (no — only the **premium half** is deductible, and it is a **below-AGI**
  deduction, so the overtime still raises every MAGI test above). Both are places where the
  product should state the distinction unprompted rather than answer the question as asked.
- **N-15 — planning is iterative; one-shot answers are the wrong shape.** The user revised
  four facts mid-session (a residency day-count, which household member a debt belonged to, the
  Roth/traditional 401(k) split, a newly-disclosed bonus), and each revision required a full
  re-computation of all three scenarios. H7's comparison surface must therefore be a
  **persisted, re-runnable model** over the workspace profile, not a single call — "change
  this one fact and re-diff" is the actual interaction.
