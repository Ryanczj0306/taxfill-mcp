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
python scripts/scaffold_state_year.py --base newest --target-year 2025 --triage \
    --rows scripts/state_discovery_rows.json
```

`--base newest` triages each form against its newest shipped year below the
target, not a fixed base year. `--rows` supplies URLs found by hand on a DOR's
forms index (with the digest that was pinned), for states whose file names
cannot be derived (a renamed folder, a revision date in the name). `--triage`
looks in the cache first, downloads only what is missing, and diffs each
candidate's AcroForm against the base pack's field map, so each row comes with
its real cost; add `--offline` to classify only what is already cached:

| verdict | what it means | work |
|---|---|---|
| `PORTABLE` | the blank carries every field name the base pack maps | swap URL + digest, then **still vision-audit every page** |
| `NEAR-PORT` | a handful of fields moved | re-map those fields, then audit |
| `RE-MAP` | the naming scheme changed (every CA pack, yearly) | full introspect + vision map |
| `URL-DEAD` | the derived URL 404s | find the year's blank on the DOR forms index |
| `no-year-token` | no substitutable year in the URL | same, plus a digest-verified `mirror_urls` Wayback snapshot where the host 403s (MA) |

**`PORTABLE` is not "done".** Identical field names do NOT prove the state kept
its line numbering — a form that renumbered lines while keeping positional field
names (`f1_12[0]`) will fill the wrong lines and only the render catches it.
Open an issue naming the row(s) you are taking.

**Which states get a new-year pack.** From TY2026 only the tier-1 states in
[`scripts/tier1_states.yaml`](../../scripts/tier1_states.yaml) get one (JS7a);
every other state goes through the no-pack fallback until someone needs it.
That table ranks the income-tax states by IRS SOI return count and records each
tier-1 state's resident and NR/PY forms, how it amends (a box on the same
return, or a separate X form) and the line its last pack maps the amended box
to. `--tier1` limits the work-list to those states:

```bash
python scripts/scaffold_state_year.py --base newest --target-year 2026 --probe --tier1 \
    --out scripts/worklists/tier1_ty2026_<date>.json
```

The 2026-10-24 run is committed as `scripts/worklists/tier1_ty2026_2026-10-24.json`,
taken before the 2026 blanks posted, so most rows are 404s; re-run it with
`--triage` when they post. A port to a state that amends on the same return
maps the amended box, and its row in the table is updated when the pack ships.

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
taxfill introspect blank.pdf --form 1040 --jurisdiction federal --year 2025 \
  --source-url https://www.irs.gov/pub/irs-pdf/f1040.pdf --out skeleton/ --render
```

This writes `pack.skeleton.yaml` (every fillable AcroForm field with its type and
page, line keys still the raw field paths; pushbuttons hold no value, so they are
left out and listed in one `MAPPING_TODO.md` entry, "pushbutton, not fillable"),
`MAPPING_TODO.md`, and `fields.json`: one
row per widget with its `kind` (text, checkbox, radio, pushbutton, choice or
signature), its tooltip (`/TU`), the `/Ff` bits as named flags (`read_only`,
`required`, `multiline`, `comb`, `password`, `do_not_scroll`, `radio`,
`pushbutton`, `no_toggle_to_off`), a choice field's `options` (`/Opt`), the
`/DA` font and size, the `/Q` alignment, `calculated` (the widget carries an
`/AA` calculate script, or a format script that is not one standard Acrobat
format call), `format_action` (any `/AA` format script) and `javascript`. A calculated or ReadOnly
widget is usually a total or a mirror the form's own script fills: check it on
the render before you map it (P-007). `--render` also renders the sentinel
sweep for step 3. For a year-over-year
port, diff the skeleton against the prior year's pack: identical field topology
means you port the map and re-audit; changed topology means you re-map from
scratch. A print-only form (no AcroForm) becomes a `handfill.yaml` manifest
instead (see CT/HI/NM/SC).

## Step 3 — map lines to fields (with your own eyes)

Render each page (`render_form`) and map form lines to field names by LOOKING:
comb fields get `format` hints (`ssn_digits_only` — P-001; `ssn_dash_cells` for an
11-cell SSN comb whose printed dashes take cells 4 and 7; `money_comma_cells` for a money
comb whose printed commas take cells of their own, as on Oregon Form OR-40; see
`formpacks/CONVENTIONS.md`, "Comb boxes and their printed separators"), checkbox groups get
their export values, and every computed line gets a `relations` entry
(`"38 == 13 + 21 + 30 + 37"`) so `verify_form` can recompute it.

Then declare the page-header mirrors. When a later page repeats the filer's
name or SSN in a box of its own (a separate AcroForm field, not a second widget
of the page-1 one), map it under a mirror key (`page2_name`,
`identifying_number_page2`) and declare it in the pack's `mirrors:` as a
template over the page-1 lines, with a comment quoting the printed caption:
`page2_name: "{name.first} {name.last}"  # "Name(s) shown on Form X"`. Use a
slice for a box that asks for one (`"{tp_last_name[:10]}"` for "Last Name
(First 10 Characters)") and an optional segment for the spouse
(`[ & {spouse.first} {spouse.last}]`). `fill_form` then builds each header from
page 1 and `verify_form` checks it; `test_pack_invariants.py` fails a
mirror-shaped line left undeclared. See `formpacks/CONVENTIONS.md`, "Identity
page mirrors" and "Page-header mirrors (`mirrors`)", for the syntax, the
`mirror_abbreviations` rule and the boxes that are not mirrors.

## Step 4 — adversarial audit

A second pass whose goal is to BREAK the map: fill every field with a
distinctive value, render, and check every page visually — clipped combs,
wrong-box hits, silent checkbox groups, off-page fields. For a state pack, the
knowledge side (rates, credits, addresses, deadlines) needs its own two-pass
verification: two independent official documents, or one document read twice by
independent readers (DEV_PLAN §7). Record what would not verify in
`unverified`.
A TY2026+ state knowledge pack written in schema v2 records it in `gaps` instead
(`about: unverified`). v2 is for TY2026+ packs; TY2023-2025 stay v1 until JK26. The
shape is summarised in [CONTRIBUTING](../../.github/CONTRIBUTING.md#knowledge-packs-and-sources).

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

The finals are watched by `scripts/check_finals.py` (its own workflow, `.github/workflows/finals.yml`,
Phase J JT0c): it HEADs `irs.gov/pub/irs-prior/<form>--<year>.pdf` for every draft pack plus Pub 1040,
the Form 1040 instructions and Pub 501, and opens or updates one `ty<year>-finals: re-pin now` issue.
The same workflow runs `scripts/check_watches.py` (Phase K JK8), whose named watches each open their own
issue: a newer irs-dft Schedule NEC / OI (Form 1040-NR) draft (JT5g), the next year's inflation
Rev. Proc. (read from the IRS newsroom), a revised current revision of a non-draft pack's form, and the
tier-1 states' blanks (JS7a). It runs weekly in October and November and daily from December 15 to March 15.

**A form whose own final revision is the authority** (Phase J JT0c). The estimated-tax voucher for the
year in progress is final in that year's January (the 2026 Form 1040-ES, `irs-prior/f1040es--2026.pdf`)
and its vouchers fall due before the year's return forms are final. Its pack sets
`filing_grade_basis: own_final_revision` and fills and verifies without rehearsal in a provisional year.
The basis is allowlisted (`OWN_FINAL_REVISION_FORMS`, federal 1040-ES only) and needs a FINAL pack on an
`irs-prior` URL; every other pack keeps the default `year_knowledge`.

## What reviewers will do

Re-render your filled golden PDF and look at it; spot-check two or three cited
figures against the cited documents; check the `unverified` list is honest; and
reject any number whose citation they cannot open.
