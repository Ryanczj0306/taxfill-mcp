# Field notes — gaps found by end-to-end drives

A running log of gaps surfaced by driving an agent end to end through **hypothetical
demo cases**, as opposed to the static persona reviews that produced Phase F/G. Each
entry records the situation, what the engine/intake did with it, and the smallest
honest fix. Roadmap items derived from these live in [`ROADMAP.md`](ROADMAP.md).

---

## Planning-surface gap catalogue (N-1 to N-15) — multi-period visa timelines, multi-taxpayer households, planning-year budgets

> **Privacy note.** Every entry uses HYPOTHETICAL demo cases. Example amounts are
> illustrative demo numbers; statutory figures (limits, brackets, phase-out thresholds) are
> public tax law. Keep it that way when adding entries: field notes record what the product
> got wrong, and none of that needs a real person's facts.

**Where the items come from.** Each N-item below states its own trigger; they come from
separate illustrations, not one household. The multi-segment visa timeline behind N-1 is
pinned by eval r for TY2025 (`evals/test_scenarios.py`): F-1 student → F-1 OPT → a
**cap-exempt** H-1B (a nonprofit research employer, whose H-1B can start on any date) from
July 15 leaves only the 170 H-1B days of the transition year countable, 170 < 183, so the
filer is a confirmed **nonresident** for that year despite full-year presence.

**How the gaps are grouped.** The N-items below are grouped by the kind of gap —
elicitation, planning computation, shipped knowledge, interaction shape; the ids are
stable and are what `ROADMAP.md` cites.

### Elicitation: the data model is right, the questions collapse it

Every identity fact in cases like these is **multi-period**: a visa status can change
twice in three years, a partner's status runs on its own clock, and the home and work
states each need date ranges. An agent that elicits the situation with coarse single-choice
buckets — one "status" word (an "F-1 / J-1 student or scholar" bucket), one "state" word
(a named state, "no-income-tax state", "moved mid-year") — gets no honest answer to any of
them. The failure is **not** an engine limitation:
`VisaPeriod` (`packages/core/src/taxfill_core/schemas/profile.py:104`) is already a
`{status, start, end}` *period list*, and `StateFootprintYear`
(`…/schemas/profile.py:293`) is already `lived[] / worked[]` date ranges with a `remote`
flag. The data model is right; the **elicitation** is what collapses multi-period reality
into one word.

#### N-1 — Visa status has no sub-status vocabulary, and no per-period tax attributes

`VisaPeriod.status` is a free-form string (`…/schemas/profile.py:107`, example values
`'F-1' / 'H-1B' / 'J-1'`), categorized downstream only by prefix match:
`residency._categorize_status` (`…/residency.py:364`) and the intake helpers
`_has_f1_period` / `_has_f_or_j_period` (`…/intake.py:170,178`, `startswith("F")`).

Consequences for a multi-segment visa timeline:

- **OPT / STEM OPT / cap-gap are invisible.** All three are F-1 (so the prefix match is
  *correct* for the exempt-individual rules), but they are the periods where the filer is
  **working full-time**, and they are the periods whose **end date** sets the H-1B
  boundary. Nothing in the profile distinguishes "F-1 studying" from "F-1 working on OPT".
- **No per-period FICA attribute.** The single biggest cash-flow fact of the transition
  year — employee FICA (7.65%) switching **on** at the H-1B start date (the split is pinned
  by `test_fica_switches_on_at_the_status_boundary` in
  `packages/core/tests/test_projection_ops.py`) — is derivable only by re-inferring it from
  status strings at every call site. G6 (Form 843/8316) handles the *erroneously withheld*
  case retroactively; there is no forward-looking per-period model.
- **No per-period work-authorization attribute**, so intake cannot ask the right income
  questions per segment (on-campus vs OPT wages vs H-1B wages).
- **The H-1B start date is easily under-specified.** A filer can give the offer date or the
  onboarding date; the tax-relevant date is the **I-797 start date** — and for a cap-exempt
  employer it can fall on any day of the year.

**Fix shape:** a controlled `sub_status` (or `work_authorization`) enum on `VisaPeriod` —
`student / opt / stem_opt / cap_gap / employment / dependent / other` — plus a derived,
citable `fica_exempt` per period; intake asks for the timeline **segment by segment** with
a worked example, and validates that consecutive periods are contiguous and that an H-1B
period's start is sourced from the I-797.

#### N-2 — An unmarried partner cannot be represented at all

The household model has exactly two slots for other humans: `Spouse`
(`…/schemas/profile.py:191`, complete with its own `Immigration` / `ResidencyFacts` — so
the *NRA-spouse* persona is well covered) and `Dependent` (`…/schemas/profile.py:172`).
There is nothing for an **unmarried cohabiting partner**, a common household shape.

Why it matters even though they file separately:

- A **household** budget means two returns, one rent, one cash-flow question. The agent
  has to carry the second person entirely out-of-band.
- Two conclusions the tool should be *stating*, not leaving to the agent's memory:
  (a) unmarried ⇒ **no MFJ**, each files their own return (`single` for an NRA — see the
  intake confirmation at `…/intake.py:455`); (b) an NRA partner generally **cannot** be
  claimed as a dependent (the dependent must be a U.S. citizen/national/resident), which
  is exactly the mistake a no-experience filer makes after reading "qualifying relative".
- For an unmarried couple in which one partner is a U.S. citizen or resident (or becomes a
  resident during the year) and the other a nonresident alien, a marriage makes the
  §6013(g)/(h) election (already built, Tier 2) a planning lever. The election is not
  available to every couple: §6013(g) needs one spouse to be a U.S. citizen or resident at
  year end, and §6013(h) needs one spouse to become resident during the year, so two NRAs
  who both stay nonresident cannot make it. Where it is available, the tool can price it
  only if the second person exists in the model *before* the marriage.

**Fix shape:** a `household.other_taxpayers[]` (name/status/own profile ref, relationship =
`unmarried_partner | roommate | …`), used for (a) explicit "you file separately" guidance,
(b) the anti-dependent guard, (c) a household-level budget roll-up across two profiles, and
(d) a "if you marry in <year>" planning branch.

#### N-3 — State footprint is one open-ended question

Intake asks it once (`…/intake.py:661`): *"For the tax year, where did you LIVE and where
did you WORK, with date ranges?"* — with a one-sentence disambiguation. For someone who has
never filed, that question does not surface the things that actually create a second state
return. This is why a first-time filer cannot answer the state question in one line.

**Fix shape:** replace the single question with a **segment loop** (one row per date range:
lived-state / worked-state / remote / employer state) plus an explicit trigger checklist the
agent must walk: mid-year move, cross-state remote work, >~30-day out-of-state assignment,
school in one state + internship in another, W-2 Box 15 ≠ state of residence, periods
outside the U.S., and — the counter-intuitive one — **no-income-tax-state segments still
need their dates**, because the *other* segment is what forces a return.

#### N-5 — Nothing for a user with zero filing experience to fill in

There was no artifact to hand a no-experience filer. The fix is
[`INTAKE_WORKSHEET.md`](INTAKE_WORKSHEET.md) (canonical English; localized copies ship
alongside it, see the file header) — a fill-in worksheet whose three opening
rules are *"don't guess, write 'don't know'"*, *"every identity/address fact is a date
range, not a word"*, and *"one worksheet per person; unmarried ⇒ two taxpayers"*. It should
be a first-class, localized, canonical-in-English product surface, emitted by
`intake_checklist` itself rather than living only as a doc.

### Planning computations the engine could not do

Planning years need forward-year ops the engine did not have (N-4). A multi-scenario
filing-posture comparison (N-9) needs primitives the engine lacked (N-6 – N-8).
Supplemental-wage withholding (N-12) belongs with the forward-year withholding ops.

#### N-4 — No forward-year support and no planning/budget mode

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

#### The filing-posture what-if (N-6 – N-9) and bonus withholding (N-12)

- **N-6 — Schedule 1-A (OBBBA) is not modeled at all.** The 2026 return carries four new
  deductions (tips / overtime / car-loan interest / senior) on a new schedule that
  *explicitly attaches to Form 1040-NR too* (line 38 → "Form 1040-NR, line 13c"), plus the
  new §170(p) non-itemizer charitable deduction and the new 0.5%-AGI floor for itemized
  charity. Two of its mechanisms bear directly on any marriage what-if: the overtime
  deduction is **forfeited by anyone married who does not file jointly** ("If married, you
  must file jointly to claim this deduction" — Part III caution), and each part's MAGI
  phase-out is a separate test whose MAGI and threshold both change when a couple starts
  filing jointly — so marrying and filing jointly can move a deduction into (or out of)
  its phase-out. Needed: a `sched_1a` knowledge block (caps, thresholds, the
  $100-per-$1,000-rounded-down vs $200-per-$1,000-rounded-**up** asymmetry between Parts
  III and IV) and a calc op.
- **N-7 — no employee-FICA-by-status-period op** (already scoped as H4), and the related
  trap: the F/J student FICA exemption is **status-based, not marital**, so a §6013(g)
  election does not start FICA on the wages of a spouse who is still an exempt F/J
  student — but nothing in the engine states that, and on a spouse's full-time wages it
  can be a four-figure annual question.
- **N-8 — the NRA bank-deposit-interest exclusion (§871(i)(2)(A)) was not modeled. DONE
  (Phase J0.4; see `knowledge/pitfalls.yaml` P-013).** The bank sends a 1099-INT; on a
  1040-NR that interest is exempt, and it becomes taxable the moment a §6013(g) election
  makes the payee a resident. `extract_document` structured the 1099-INT with no note that
  the payee's status decides whether it is income at all, and `estimate_refund` taxed it
  with an amount-less "may OVERTAX" hedge. Now: `IncomeSnapshot.bank_deposit_interest`
  (the deposit subset of `interest`) is excluded for a nonresident before Total income
  (ledger slot `deposit_interest_exclusion`) with the amount and the 871(i)(1)-(3) / Pub 519
  ch. 3 / 1040-NR line 2b Exception 3 pinpoints disclosed; interest entered without that
  character is taxed and said to be; an MFJ (election) figure taxes it and says the
  election, not the marriage, ended the exclusion. `intake_checklist` asks
  `income_documents.interest_character` for a confirmed nonresident with a 1099-INT, the
  1099-INT DocSpec note names the field, and `get_sources` routes "871(i)" to
  `nonresident_fdap`. Still open: the dual-status year (nonresident-period deposit
  interest) — Phase J JF5b.3.
- **N-9 — there is no "compare filing scenarios" surface.** A filing-posture what-if for an
  unmarried couple in which one partner is a nonresident alien is a three-way
  comparison (unmarried / married-MFS / married-with-§6013(g)-election). The engine has every primitive and no way to say "run
  these three and diff them"; the estimator answers one scenario at a time. This is the
  shape a *planning* question always takes.
- **N-12 — supplemental-wage withholding.** When the employer uses the optional flat 22%
  (Pub 15 (2026)), a filer in the 32% bracket owes more than that on the bonus — a predictable
  April shortfall that no current surface would forecast. Belongs with H4's withholding work.
  The flat rate has preconditions (Treas. Reg. 31.3402(g)-1(a)(7)(i): the bonus separately
  stated or not paid with regular wages, and income tax withheld from regular wages this year
  or last); otherwise the aggregate procedure applies (P-017, JF1a).

### Knowledge the engine did not ship

- **N-10 — no knowledge of tax-advantaged account limits, and none of their SCOPING.**
  Contribution limits are scoped four different ways: §402(g) $24,500 is **per person
  across all employers** (and traditional + Roth share it), §415(c) $72,000 is **per
  employer plan** (which is what makes a mega-backdoor possible), the HSA limit is **per
  coverage tier** (so two people, each with self-only HDHP coverage, get 2 × the
  statutory $4,400 self-only limit = $8,800, *more* than the $8,750 family limit), and
  §125(i) $3,400 is **per employee per employer**.
  None of this is in the repo. Needed: a `contribution_limits` knowledge block, and a
  ranking op — "what does one marginal dollar save in each bucket" — which must know that
  a payroll HSA/FSA/commuter dollar also saves FICA while a 401(k) dollar does not, and that
  above the SS wage base the FICA saving is only 1.45% + 0.9%, not 7.65%.
- **N-11 — no Roth-vs-pre-tax modeling, and no excess-contribution detection.** Two separate
  findings, both worth real money: (a) a filer's Roth 401(k) share changes AGI, which cascades
  into six different phase-outs — the tool has no way to represent "of my elective deferral,
  this portion is Roth and the rest is pre-tax"; (b) a filer whose MAGI sits above the
  filing status's phase-out ($153,000–$168,000 single, $242,000–$252,000 joint, $0–$10,000
  married filing separately when the spouses lived together at any time in the year) is
  **ineligible to contribute directly to a Roth IRA**, and a direct contribution made anyway
  is a 6%-per-year excise-tax error.
  As a what-if (demo numbers): a married filer filing separately at MAGI $150,000 who
  contributes $6,000 directly to a Roth IRA has a $6,000 excess, $360/yr of excise until
  corrected. A tool holding both the profile and the limits should flag that
  automatically, and the same contribution is *compliant* on a joint return, because IRA
  eligibility follows the year-end filing status.
- **N-13 — MAGI needs to be a first-class object.** A planning question can touch
  at least six MAGI tests with different thresholds (NIIT $200k/$250k, 8959's wage test,
  Roth IRA $153–168k/$242–252k, deductible-IRA $81k/$129k, Schedule 1-A $100k/$150k/$300k,
  §221 $85k/$175k). A common UX question is why MAGI comes out *below* the headline
  salary: the answer is a **ladder** (gross → box 1 → AGI → each test's MAGI), and
  the tool should render it, because every planning lever works by moving a number up or
  down that ladder.

### Interaction shape

- **N-14 — labels invite wrong conclusions; the tool should state the distinction
  unprompted.** For a nonresident spouse, the **§6013(g) election**, not the marriage
  itself, is what ends the bank-deposit-interest exclusion. The Schedule 1-A overtime
  deduction covers only the FLSA **premium half** and sits **below the AGI line**, so
  overtime pay still raises every MAGI test. The product should volunteer both rules rather
  than answer the question as asked.
- **N-15 — planning is iterative; one-shot answers are the wrong shape.** Planning facts can
  be revised mid-conversation — a residency day count, for example — and every revision
  means a full re-computation of every scenario in the comparison. H7's comparison surface
  must therefore be a **persisted, re-runnable model** over the workspace profile, not a
  single call — "change this one fact and re-diff" is the actual interaction.

### Status of these gaps

| Gap | Shipped as |
|---|---|
| N-4 forward-year support | H5, the provisional TY2026 pack; H4, the PROJECTION mode and ops |
| N-6 Schedule 1-A deductions and their MAGI phase-outs | H6, calc op `schedule_1a_deductions` |
| N-7 employee FICA by status period (the F/J exemption under §6013(g)) | H4, calc op `employee_fica` |
| N-8 the NRA bank-deposit-interest exclusion | Phase J J0, pitfall P-013 |
| N-9 / N-15 a re-runnable multi-scenario diff with per-line attribution | H7, MCP tool `compare_scenarios` |
| §6654 safe harbor (90% current-year / 100%-or-110% prior-year prongs) | H4, calc op `estimated_tax_safe_harbor` |
| N-10 / N-11 / N-13 limits, Roth IRA eligibility, the MAGI ladder | H8, `contribution_limits` / `ira_contribution_eligibility` / `magi_ladder` |

The general lesson is the DEV_PLAN §1 thesis: citable per-year data belongs in shipped
packs, with a deterministic op over it, so an agent never has to supply it itself.
