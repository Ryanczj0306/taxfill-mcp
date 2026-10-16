# v0.1 acceptance test — non-developer, ≤20 minutes

The ship gate from dev plan §13: a person who is **not** a developer should reach
a filled, reviewable sample form in under 20 minutes using only the README and the
user guide it links ([docs/USER_GUIDE.md](../USER_GUIDE.md)). Run
this on a machine that has never had the repo. Check every box; any miss is a
release blocker, not a "known issue".

## Setup (target: ≤5 min)

- [ ] Install the client (Claude Desktop, or Claude Code) per its own docs.
- [ ] **Published path:** `claude mcp add --scope user taxfill -- uvx taxfill-mcp` — completes
      with no error; `uvx` bootstraps Python with no separate install.
      **Pre-publish path:** follow the README [Quickstart](../../README.md#quickstart).
- [ ] Restart/refresh the client; the `taxfill` tools appear in the tool list.
- [ ] No Python/uv error text is shown to the user at any point.

## Guided filing (target: ≤12 min) — use the sample W-2, never real PII

*This walkthrough is journey 1 of `packages/mcp-server/tests/test_journeys.py`, which holds every figure quoted below.*

The sample is a demo persona's 2025 Form W-2 (a hypothetical new-grad software engineer; every name, number and
identifier on it is fictitious, and a SAMPLE watermark crosses it). Download
[w2_2025_synthetic.png](../samples/w2_2025_synthetic.png) (or the
[PDF](../samples/w2_2025_synthetic.pdf)) from the repository page — nothing else is needed. Whenever the assistant
asks about the filer, answer as the persona: **Jordan Q. Taxpayer**, SSN **999-88-0425**, U.S. citizen, single,
lived and worked in Washington all of 2025, current address **123 Sample Ave Apt 4, Seattle, WA 98000**; decline
direct deposit (a demo has no bank account). The expected figures below are what the tools return for this sample.

- [ ] Attach the sample W-2 image and say: *"Help me start my 2025 federal
      return."* The assistant runs intake and shows a **confirm table** of
      extracted figures: **wages $168,100** (box 1) and **federal tax withheld $30,487**
      (box 2); the boxes the sample leaves blank (7, 8, 10, 11 and 16–20) stay blank (nothing invented), and
      box 9, shaded on the 2025 Form W-2, is never read.
- [ ] Correct one figure in the confirm step (say box 2 is $30,000) → the assistant
      accepts the correction and does not silently overwrite it later. Then change it
      back to $30,487, so the figures below match.
- [ ] The assistant scopes state filing (`state_scope`) and explains in plain language
      that Washington does not tax wages, so there is no state return.
- [ ] `estimate_refund` produces numbers — **a refund of about $1,076** — and cites its `.gov`
      sources, and **each `calc` result carries its own citation** (line 16's tax, line 12's standard
      deduction); ask "where does line 16 come from?" and get a source ($29,411, from the 2025 tax
      rate schedule), not a guess.
- [ ] `list_forms` → `fetch_blank` downloads the official 2025 Form 1040 blank from irs.gov;
      `fill_form` fills it; `render_form` shows page 1 of the filled 1040 (lines 1a, 9 and
      11a read 168100).
- [ ] `fill_form`, `filing_summary` and `file_and_pay` each carry the disclaimer: a review draft,
      not tax advice, for paper filing only (TaxFill does not e-file).

## Review & file (target: ≤3 min)

- [ ] `filing_summary`'s headline starts **Federal 2025: refund $1,076** and, because the persona
      declined direct deposit, adds that paper refund checks are being phased out; `file_and_pay`
      prints the mailing address (**Ogden, UT 84201-0002**) and the refund options, cited.
- [ ] The filled PDF opens in a normal PDF viewer and the mapped fields are in
      the right boxes (spot-check the name — **Jordan Q** in "first name and middle initial",
      **Taxpayer** in "last name" — the SSN 999880425 in its nine cells, wages 168100, AGI 168100).
      The form's printed dashes in the SSN box can cross a digit: viewers space the nine digits
      across the whole box, a cosmetic offset only.
- [ ] Nothing was transmitted anywhere except the blank-form download from
      `.gov`; no account, no telemetry.

## Pass criteria

- [ ] Total elapsed time < 20 min.
- [ ] No dead-ends that required reading code, editing config by hand, or
      searching outside the README and the user guide.
- [ ] Every dollar figure on the draft is traceable to a citation or explicitly
      flagged unverified.

> Engine happy-path sanity (developers, pre-release): the read-only tool surface
> is exercised end-to-end by the test suite and by
> `scripts/check_drift.py` (live source freshness). The packaging self-contained
> check runs in CI's `packaging` job on every push.
