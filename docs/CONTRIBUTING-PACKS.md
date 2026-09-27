# Contributing a form pack (author → audit → PR)

This is the community pack-contribution pipeline (ROADMAP D2, seeded by the
`taxfill introspect` CLI). It exists so a new form pack — a new state, a new
year, a new federal form — always travels the same quality gate the shipped
packs traveled. **The gate is the product**: a pack that skips a step is how a
wrong number reaches a real return.

## The non-negotiables (read first)

1. **No invented numbers.** Every figure in a pack is transcribed from an
   official source (.gov/.us) you actually opened, and cited with a pinpoint
   (document title + section/page/line). Anything you could not verify ships in
   an explicit `unverified` list — never silently.
2. **Every field map is vision-audited** against the rendered PDF before it
   ships. Field-name dumps lie (see pitfall P-001); pixels do not.
3. **Tests are CI-derived.** New packs auto-enroll in the glob-parametrized
   suites; your job is to make the golden test pass honestly, not to write a
   bespoke one.

## Step 0 — claim the work

For a year tranche, generate the work-list first:

```bash
python scripts/scaffold_state_year.py --base-year 2023 --target-year 2025 --triage
```

`--triage` downloads each derived candidate and diffs its AcroForm against the
base pack's field map, so each row comes with its real cost:

| verdict | what it means | work |
|---|---|---|
| `PORTABLE` | the blank carries every field name the base pack maps | swap URL + digest, then **still vision-audit every page** |
| `NEAR-PORT` | a handful of fields moved | re-map those fields, then audit |
| `RE-MAP` | the naming scheme changed (every CA pack, yearly) | full introspect + vision map |
| `URL-DEAD` | the derived URL 404s | find the year's blank on the DOR forms index |
| `no-year-token` | no substitutable year in the URL | same, plus MA needs a Wayback cache-seed |

**`PORTABLE` is not "done".** Identical field names do NOT prove the state kept
its line numbering — a form that renumbered lines while keeping positional field
names (`f1_12[0]`) will fill the wrong lines and only the render catches it.
Open an issue naming the row(s) you are taking.

## Step 1 — fetch the blank, pin the digest

```bash
# download the official blank, record its SHA-256
python -c "from taxfill_core.fetch import compute_sha256; print(compute_sha256('blank.pdf'))"
```

Confirm on the PDF itself (not the URL) that the revision year and form title
are the ones you claim. The digest goes in the pack as `pdf_sha256`; the URL as
`source_url`. The weekly drift CI re-fetches and flags moved/changed blanks.

## Step 2 — introspect to a skeleton

```bash
taxfill introspect blank.pdf > pack-skeleton.yaml
```

This emits every AcroForm field with its type and page. For a year-over-year
port, diff the skeleton against the prior year's pack: identical field topology
means you port the map and re-audit; changed topology means you re-map from
scratch. A print-only form (no AcroForm) becomes a `handfill.yaml` manifest
instead (see CT/HI/NM/SC).

## Step 3 — map lines to fields (with your own eyes)

Render each page (`render_form`) and map form lines to field names by LOOKING:
comb fields get `format` hints (`ssn_digits_only` — P-001), checkbox groups get
their export values, and every computed line gets a `relations` entry
(`"38 == 13 + 21 + 30 + 37"`) so `verify_form` can recompute it.

## Step 4 — adversarial audit

A second pass whose goal is to BREAK the map: fill every field with a
distinctive value, render, and check every page visually — clipped combs,
wrong-box hits, silent checkbox groups, off-page fields. For a state pack, the
knowledge side (rates, credits, addresses, deadlines) needs its own two-pass
verification: two independent official documents, or one document read twice by
independent readers (DEV_PLAN §7). Record what would not verify in
`unverified`.

## Step 5 — golden test

Add the golden fixture (a filled+verified round-trip). The glob suites
(`test_formpacks_states.py`, `test_state_knowledge.py`, `test_knowledge_years.py`)
auto-enroll new packs — run the full offline suite and the sync gates:

```bash
uv run pytest -m "not network"
python scripts/sync_test_count.py --check
python scripts/assemble_state_sources.py --check   # state knowledge packs only
uvx ruff check .
```

## Step 6 — PR

The PR template requires: the source URLs you fetched, the digest, what the
vision audit caught (an audit that caught nothing is suspicious — say so
explicitly if it truly caught nothing), the `unverified` list, and — if your
work fixes a bug — a new
`knowledge/pitfalls.yaml` entry with its regression test (enforced by
`test_pitfall_coverage.py`).

Run the gates ON THE EXACT TREE YOU PUSH. A lint or suite run from before your
last edit is not a gate (this exact failure shipped once; see the 2026-08-09
lint-fix commit).

## Drafts-first (a year whose forms are still drafts)

Every coming year's forms post as drafts at `irs.gov/pub/irs-dft/` months before the finals, and the IRS
draft cover sheet says "there are never any changes to the last posted draft of the form and the final
revision of the form". A pack may therefore be authored against the draft (Phase J JT0a):

- set `source_status: draft`, `draft_created` to the draft footer's `Created <date>` stamp, and the
  `irs-dft` URL (a final pack may not use one — the schema refuses it);
- only in a PROVISIONAL year: `test_no_draft_packs_in_a_filing_grade_year` fails a draft pack whose
  year's knowledge pack is filing-grade;
- run the golden test in REHEARSAL mode — core-only `fill_form(..., rehearsal=True)` /
  `verify_form(..., rehearsal=True)`, never reachable through MCP — which stamps every page
  "REHEARSAL — DRAFT FORM — NOT FOR FILING"; MCP `fill_form` keeps refusing the year;
- when the IRS re-posts the draft, `scripts/check_drift.py` reports "draft re-posted: re-audit" as a
  warning (not drift): re-read the face and re-pin the digest;
- the knowledge pack's `provisional.second_passes` record each second pass with its own
  `source_status`; `Provisional.removal_blockers()` lists what keeps the marker on — a block still
  deliberately absent, or one verified only against a draft.

Drafts of instructions and publications DO change, so a figure read from a draft instruction stays
projection-grade until the final posts.

## What reviewers will do

Re-render your filled golden PDF and look at it; spot-check two or three cited
figures against the cited documents; check the `unverified` list is honest; and
reject any number whose citation they cannot open.
