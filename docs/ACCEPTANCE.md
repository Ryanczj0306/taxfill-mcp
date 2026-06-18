# v0.1 acceptance test — non-developer, ≤20 minutes

The ship gate from dev plan §13: a person who is **not** a developer should reach
a filled, reviewable sample form in under 20 minutes using only the README. Run
this on a machine that has never had the repo. Check every box; any miss is a
release blocker, not a "known issue".

## Setup (target: ≤5 min)

- [ ] Install the client (Claude Desktop, or Claude Code) per its own docs.
- [ ] **Published path:** `claude mcp add taxfill -- uvx taxfill-mcp` — completes
      with no error; `uvx` bootstraps Python with no separate install.
      **Pre-publish path:** follow the README "Today — from a source checkout".
- [ ] Restart/refresh the client; the `taxfill` tools appear in the tool list.
- [ ] No Python/uv error text is shown to the user at any point.

## Guided filing (target: ≤12 min) — use the bundled SAMPLE W-2, never real PII

- [ ] Attach the sample W-2 image and say: *"Help me start my 2023 federal
      return."* The assistant runs intake and shows a **confirm table** of
      extracted figures; blanks are blanks (nothing invented).
- [ ] Correct one figure in the confirm step → the assistant accepts the
      correction and does not silently overwrite it later.
- [ ] The assistant scopes state filing (`state_scope`) and explains residency in
      plain language.
- [ ] `estimate_refund` / `calc` produces numbers, and **each line shows a
      citation** (a `.gov` source); ask "where does line X come from?" and get a
      source, not a guess.
- [ ] `list_forms` → `fetch_blank` downloads the official blank from irs.gov;
      `fill_form` fills it; `render_form` shows page 1 of the filled 1040.
- [ ] The draft carries the disclaimer (review draft, not tax advice, paper
      filing only).

## Review & file (target: ≤3 min)

- [ ] `file_and_pay` prints the correct mailing address + payment options for the
      return, cited.
- [ ] The filled PDF opens in a normal PDF viewer and the mapped fields are in
      the right boxes (spot-check name, SSN-less ID fields, wages, AGI).
- [ ] Nothing was transmitted anywhere except the blank-form download from
      `.gov`; no account, no telemetry.

## Pass criteria

- [ ] Total elapsed time < 20 min.
- [ ] No dead-ends that required reading code, editing config by hand, or
      searching outside the README.
- [ ] Every dollar figure on the draft is traceable to a citation or explicitly
      flagged unverified.

> Engine happy-path sanity (developers, pre-release): the read-only tool surface
> is exercised end-to-end by the test suite and by
> `scripts/check_drift.py` (live source freshness). The packaging self-contained
> check runs in CI's `packaging` job on every push.
