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
asks **during** the year, i.e. the highest-frequency question there is. Beyond the missing
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
