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
python scripts/scaffold_state_year.py --base-year 2023 --target-year 2025 --probe
```

Each row is one pack. `candidate` rows have a derivable URL; `no-year-token` /
`unreachable` rows need you to find the year's blank on the DOR forms index
(MA additionally needs a Wayback cache-seed — see the MA pack header). Open an
issue naming the row(s) you are taking.

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

## What reviewers will do

Re-render your filled golden PDF and look at it; spot-check two or three cited
figures against the cited documents; check the `unverified` list is honest; and
reject any number whose citation they cannot open.
