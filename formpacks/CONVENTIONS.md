# Form pack conventions (binding)

These rules are **binding** for every pack under `formpacks/`. Three test
modules enforce them, and **which one enforces a given rule decides which packs
it actually covers** — read this before trusting the word "binding":

| module | discovers | enforces |
|---|---|---|
| `packages/core/tests/test_formpacks_federal.py` | `formpacks/federal/*/*/pack.yaml` | schema, sha256, line-id grammar, relations parse, the form-specific `sched_d`/`sched_e` pins, golden round-trip |
| `packages/core/tests/test_formpacks_states.py` | `formpacks/states/*/*/*/pack.yaml` | schema/jurisdiction, sha256, relations parse, golden round-trip |
| `packages/core/tests/test_pack_invariants.py` | **every** pack, federal and state | `cross_form` target resolution, the checkbox `group` rules, identity page mirrors, year tokens in line keys |
| `packages/core/tests/test_readonly_widget_mapping.py` | **every** pack, federal and state | which packs may bind an AcroForm ReadOnly widget |

Until 2026-08-21 the `cross_form` and checkbox-`group` rules below lived in the
FEDERAL module and so had never run over a single state pack, while this
document called them harness-enforced. Three dangling `f1040.11` references and
two packs' worth of missing `group` ids shipped through that gap. If you add a
rule here, put its test in a module whose discovery glob matches the rule's
claimed scope.

The pack schema itself lives in
`packages/core/src/taxfill_core/schemas/formpack.py` (dev plan section 5).

## Directory layout

```
formpacks/federal/<tax_year>/<form_key>/pack.yaml
formpacks/states/<st>/<tax_year>/<form_key>/pack.yaml
```

- `<tax_year>` is the 4-digit filing year and MUST equal the pack's
  `tax_year` field.
- `<form_key>` MUST be one of:

  `f8843`, `f8863`, `f2555`, `f1040nr`, `f1040`, `sched_1`, `sched_1a`,
  `sched_2`, `sched_3`, `sched_a`, `sched_b`, `sched_c`, `sched_d`,
  `sched_e`, `sched_oi`, `sched_se`

  (the full list is `KNOWN_FORM_KEYS` in `test_formpacks_federal.py`). State
  packs use the state's own form name as `<form_key>` (`it201`, `pa40`,
  `d400`), which is not whitelisted — the state module pins the pack's declared
  `jurisdiction` against the path instead.

- `(tax_year, <form_key>)` must be UNIQUE across the whole repo, federal and
  state together, because that pair is what `cross_form` refs and `FilingItem`
  keys resolve against. Harness enforced.

## Line-id grammar

A line id is one or more dot-separated segments; each segment is either a
printed line label or a lowercase word:

```
line_id := segment ('.' segment)*
segment := printed | word
printed := [0-9]+[a-z]?        # the form's printed line label, lowercased
word    := [a-z][a-z0-9_]*     # namespaced block / identity names
```

Equivalent regex (the harness enforces exactly this):

```
^(?:[0-9]+[a-z]?|[a-z][a-z0-9_]*)(?:\.(?:[0-9]+[a-z]?|[a-z][a-z0-9_]*))*$
```

Rules and examples:

| kind | rule | examples |
|---|---|---|
| printed lines | the form's printed line label, lowercased, nothing added | `1a`, `16`, `23`, `25d` |
| namespaced blocks | block name + dot + option/member | `filing_status.single`, `digital_assets.yes`, `dependent_1.ssn` |
| identity fields | exactly these ids so cross-form identity checks line up | `name`, `identifying_number`, `mailing_address` |
| address splits | when the form splits the address, suffix the parts | `mailing_address.street`, `mailing_address.city`, `mailing_address.state`, `mailing_address.zip` |

Never invent ids like `Line1a`, `L16`, or uppercase variants. The id is
what agents type into `fill_form` — it must read like the paper form.

### The option separator: `.`, `::` and `_`

The grammar above is the FEDERAL rule and the state packs do not all follow
it. In practice three spellings ship, all of them in quantity:

| separator | example | packs |
|---|---|---|
| `.` (the documented grammar) | `digital_assets.yes` | every federal pack, plus ky/wv and others |
| `::` | `residency_taxpayer::yes`, `filing_status::mfj` | 22 state packs (az, co, ma, mi, mn, nc, nj, ny it201, oh, pa, va, wi, …) |
| `_` | `B_itemized_federal_yes` | ny it203 2023/2024/2025 |

Prefer `.` in a new pack. What is **binding** is that a gate must accept all
three: the yes/no group check only knew `.` until 2026-08-21, so NC's five
Yes/No questions were invisible to it even after the pack glob was widened.
`_yesno_pairs` in `test_pack_invariants.py` tries each separator in turn and
keeps the first that yields a `yes`/`no` token. Do not add a fourth spelling.

### Year tokens in line keys

A line key is the pack's API surface, so it has to be both honest and stable,
and those collide whenever a printed row names a year. The rule, settled
2026-08-21 from a sweep of every year-bearing key in all 150 packs, and
enforced by `test_year_bearing_line_keys_keep_their_offset_from_tax_year`
(which pins `tax_year - year` per key family, so a forgotten roll fails):

1. **The year LABELS its own widget → keep it, and re-derive it on every
   port.** Form 8843 line 4a prints a box per year (offsets `{0,1,2}` from
   `tax_year`), lines 7 and 11 print six prior-year boxes (`{1..6}`),
   Schedule OI item H prints three (`{0,1,2}`), and NJ-1040 line 5's
   qualifying-widow ovals print two (`{1,2}`). Here the year picks WHICH BOX,
   so dropping it would lose information — and rolling it is mandatory,
   because the widget bindings usually do NOT move between years. Getting
   this wrong is silent: `federal/2024/sched_oi` shipped keying
   `h.2021/h.2022/h.2023` against a face printed `2022, 2023, and 2024`, so
   every day-count landed one year off and `h.2024` raised "unknown line
   key" (found by this gate 2026-08-21, rolled to `h.2022/h.2023/h.2024`
   against the same widgets 2026-08-24).
2. **The year merely DESCRIBES the meaning → keep it out of the key.** A row
   reading "credit to your 2025 tax" or "applied to your 2025 taxes" moves
   with `tax_year` and does not select a widget, so name the ROLE relative to
   the pack's own year (`line69_credit_to_next_year_tax_d01`,
   `refund_applied_to_next_year`, `..._from_prior_year`) and put the printed
   year in the inline comment, where a per-year fact belongs. Every shipped
   instance conforms as of 2026-08-24: `states/nj/{2023,2024}/nj1040`,
   `states/ut/{2023,2024}/tc40`, `states/id/2023/form40`, and
   `states/ny/{2023,2024,2025}/it203` (the last three years all renamed in
   one pass, so the key is one spelling across every shipped IT-203 year).
3. **Best of all, key by the printed line NUMBER** when the form gives one
   (`"48"  # 48 Amount to be applied to 2026 estimated tax`). The line number
   is what the form itself is stable about.
4. **Do NOT "keep the stale year and document it."** A key that says the money
   went to 2024 tax while the state applies it to 2025 inverts the DIRECTION
   of the money for any caller mapping by key name, and a banner caveat does
   not travel with the key. `states/ny/{2024,2025}/it203` documented exactly
   that; it was treated as a defect, not a caveat, and both packs took the
   year-free rename 2026-08-24.
5. **A year-SHAPED token is not always a year.** `az140`'s
   `..._pollution_facility_1990` is a statutory year fixed by law, and
   `it540`'s `22b.amount_from_r19000a` is a FORM NUMBER. Both are pinned with
   an empty offset tuple so the check skips them.
6. **Before renaming an existing key, grep it** (`grep -rn '<key>' .`). Only
   its own pack refers to it → rename and say so in the pack banner. A calc
   op, extractor, fixture, test or `cross_form` rule refers to it → the rename
   is a reviewed change across every referencing site, not a port edit.

## Checkboxes and radio groups

- The yes/no boxes (or the N options) of ONE question share a `group` id,
  e.g. both `digital_assets.yes` and `digital_assets.no` carry
  `group: digital_assets`. A `required: true` on any member makes the
  whole group required (pitfall P-003 audit).
- Real IRS forms often implement an option block as ONE `/Btn` field with
  kid widgets (filing status, digital assets). Map **each option as its own
  line** with the SAME `field` and that option's `on_state` (`"/1"`,
  `"/2"`, ...). The filler resolves the group: `/V` on the shared field,
  `/AS` only on the kid that defines the chosen state, siblings `/Off`.
- Checkbox lines that share one `field` MUST share one `group`, and no two
  options on one field may reuse an `on_state` (harness enforced over EVERY
  pack — the synthetic-fill harness selects exactly one option per
  group/field, and a reused `on_state` is a mis-mapping, not a group).
- Find the real `on_state` values by dumping the blank PDF's field
  appearance states — never guess them.

### The two topologies are not equally dangerous

Which one you are looking at decides how bad a missing `group` is, and the
answer is NOT "the same either way":

- **N options on ONE AcroForm field.** The PDF holds a single `/V`, so the
  contradictory state cannot exist in the file, and `fill_form` refuses a
  double answer before it opens the blank. A missing `group` is a convention
  gap: it cannot file a wrong return, but `verify`'s `checkbox_audit` builds
  its groups from `group`/`required` alone and so emits NO check for an
  ungrouped set — nothing then confirms a required question was answered. 21
  state packs carry this debt in `SHARED_FIELD_OPTIONS_WITHOUT_GROUP_ID`,
  counts pinned, with the guard proved by execution for all 120 sets.
- **Options on SEPARATE single-widget `/Btn` fields.** Nothing in the PDF makes
  these exclusive and nothing in the engine can infer it, so the `group` id is
  the only thing preventing a return that answers one question both Yes and
  No. This shape gets no exemption. `states/wv/2023/it140`'s
  `heptc.required_federal_return.yes`/`.no` is the live instance:
  `homesteadY_checkbox` and `homesteadN_checkbox`, and `fill_form` writes BOTH
  with zero warnings.

When you map a printed "fill in one circle only" set, decide which topology it
is by dumping the widgets — never by the line-key spelling.

## Reserved, shaded and ReadOnly widgets

There is no single rule for the AcroForm ReadOnly bit (`/Ff` bit 1), and
"the widget is ReadOnly, so it is intentionally unfillable" is the premise
pitfall **P-007** overturned. Only the printed row text decides. The four
classes, the two-sided allowlists, and every per-pack adjudication live in
`packages/core/tests/test_readonly_widget_mapping.py` — read its module
docstring before mapping or unmapping a flagged widget, and do not restate its
verdicts here (a second copy is how the wrong version propagates). In short:

1. the widget already HOLDS a printed constant → never map it;
2. the printed text makes a correct entry IMPOSSIBLE → the line key must not
   exist, so `fill_form` raises;
3. a printed, numbered line reading "Reserved for future use" → may stay
   mapped with a leave-blank comment, so the key survives the revision that
   un-reserves it;
4. the FORM owns the value (a DOR running total, a page-header identity
   mirror, or a cell the form only unlocks on another answer) → it MUST stay
   mapped, because taxfill never runs the propagation and an unmapped one
   ships blank.

Two traps worth knowing before you audit a blank: `pdfinfo`'s
"JavaScript: yes" is satisfied by `AFNumber_Format`-style FORMATTING scripts
and says nothing about whether a form computes; and flag/action diffs must be
read at FIELD level, walking `/Parent`, because DORs re-author fields between
terminal and parent+kid shapes and an annotation-level diff then reports
phantom `/AA`, `/DA` and `/MaxLen` changes while hiding real ones.

## Identity page mirrors

Many forms repeat the filer's name and SSN at the top of every continuation
page. The DOR propagates the value itself — embedded JavaScript, or an XFA
`<bind match="global"/>` — and taxfill runs neither, so **each mirror needs
its own line key or it ships blank on the filed return** (class 4 above; it
happened to ri1040 on 12 widgets and to it1040_oh on 11 pages).

- Name a mirror for the page it fills: `page<N>_<what>` (`page2_ssn`,
  `page3_name_last`) or `<what>_page<N>` (`identifying_number_page2`). Both
  house shapes are recognised by the harness; `_page1` is NOT a mirror.
- A mirror must bind a DIFFERENT AcroForm field from its source, and must
  agree with it on `type`, `comb` and `format`. Harness enforced. If the two
  keys bind the SAME field, the mirror key is redundant — one write already
  fills both widgets (PA-40's `your_ssn` is one field whose widget repeats).
- `maxlen` tracks each widget's OWN `/MaxLen` and may legitimately differ
  between mirror and source (a DOR often prints a narrower continuation box).
  That is also what keeps ReadOnly mirrors inside `_pack_maxlen_checks`' reach,
  since the geometry half of the clipping scan skips ReadOnly widgets.
- **One thing the schema cannot express:** that the mirror's VALUE equals its
  source's. `relations` is arithmetic over money lines and `identity_fields`
  drives a cross-FORM check, so `page4_name_last == name.last` has no home. A
  caller that fills a mirror differently files an internally inconsistent
  return and no gate will catch it.

## Cross-form references (`cross_form`)

```
<ref> == <ref>
ref   := <line>                # a line of THIS pack (no dot)
       | <form_key>.<line>     # a line of another form in the filing
```

- `form_key` MUST be a real pack directory name — a federal form key, or a
  state one (e.g. `8 == sched_1.10`, `1k == sched_oi.1e`).
- Refs are split at the FIRST dot, so only undotted (printed-label) lines
  of other forms can be referenced — which is all that cross-form math
  ever needs.
- Undotted refs must exist in this pack's `fields[]`.
- A target is a `(form_key, LINE KEY OF THAT YEAR'S PACK)` pair, **never a line
  number remembered from a prior year.** Every target is resolved against the
  real pack for `(this pack's tax_year, form_key)` — over every pack, federal
  and state, since 2026-08-21.
- When a federal line SPLITS, target the **defining** line, not the
  restatement. TY2025 Form 1040 split line 11 into `11a` ("Subtract line 10
  from line 9. This is your adjusted gross income") and `11b` ("Amount from
  line 11a"), and a state FAGI line must point at `11a`. Re-point **per year**:
  the 2023/2024 state legs citing `f1040.11` are correct for their own years
  and must not be "harmonised".
- Reading a WRAPPED printed citation: when a label wraps mid-list — "from
  federal Form 1040, 1040-SR, or / 1040-NR, line 11a" — the single trailing
  line citation governs the WHOLE list of form names, it is not scoped to the
  last one. Cross-check by confirming the cited line means the same thing on
  each named form. Misreading this exact wrap is what produced the dangling
  `f1040.11` on OR-40.
- A target that cannot resolve yet goes in `CROSS_FORM_TARGET_ALLOWLIST`
  (`test_pack_invariants.py`) with a reason. Rows are checked for STALENESS:
  once the awaited pack ships, the row must be deleted, because a stale row is
  a live check quietly switched off.

## Relations (`relations`)

Only math that is **printed on the form face** ("add lines 1a through 1h",
"subtract line 10 from line 9") belongs in `relations`. Tax-table lookups,
worksheets, and instruction-only math belong to `calc` and the knowledge
packs, never here. Grammar: `<expr> == <expr>` with `+ - * /`,
parentheses, `max()`, `min()`, `sum(1a..1h)` (see the `verify` module
docstring).

## Source URL and checksum

- `source_url` is the official irs.gov URL, nothing else:
  - current-year forms: `https://www.irs.gov/pub/irs-pdf/<file>.pdf`
  - prior-year revisions: `https://www.irs.gov/pub/irs-prior/<file>--<year>.pdf`
- `pdf_sha256` is the REAL digest of that exact file — the placeholder
  `"..."` never ships (harness enforced; `fetch_blank` refuses it).
  Compute it with `taxfill_core.fetch.compute_sha256(path)` or
  `shasum -a 256 <file>`.
- Before pinning the digest: render page 1 of the downloaded PDF and READ
  the printed revision year and form title. A wrong-revision pack is worse
  than no pack (freshness protocol, dev plan section 7).
- Blank PDFs are NEVER committed. `fetch_blank` downloads them into the
  gitignored shared cache `.cache/blanks/`.

## Signature and mailing

| form | `signature` | `mailing` |
|---|---|---|
| `f8843` | its own block; `standalone_only: true` (signed only when filed alone — attached to a 1040-NR it is NOT separately signed) | its own fixed where-to-file: set it |
| `f1040nr` | page 2 block | its own fixed where-to-file: set it |
| `f1040` | page 2 block | `null` — the address is STATE-dependent; knowledge packs own it in M3 |
| schedules (`sched_*`) | `null` (no signature block of their own) | `null` (mailed inside the parent return's envelope) |

`mailing.verify_url` must be the official irs.gov where-to-file page.

## Validating your pack (the harness)

Every module parametrizes over the packs its glob discovers — adding a
directory is enough, no test edits needed. Note `pytest` alone is broken in
this checkout (stale venv shebang): use `uv run python -m pytest`, and do NOT
add your own `-q` (pyproject already sets it, and a second `-q` hides the
summary).

Offline structural checks for one pack (schema, sha256 not placeholder,
line-id grammar, relations parse):

```
uv run python -m pytest packages/core/tests/test_formpacks_federal.py -m "not network" -k "<tax_year>-<form_key>"
uv run python -m pytest packages/core/tests/test_formpacks_states.py  -m "not network" -k "<st>_<tax_year>_<form_key>"
```

The repo-wide invariants (cross-form targets, checkbox groups, identity
mirrors, year tokens) and the ReadOnly adjudication — these cover federal AND
state packs, so run them whichever lane you touched:

```
uv run python -m pytest packages/core/tests/test_pack_invariants.py
uv run python -m pytest packages/core/tests/test_readonly_widget_mapping.py
```

Golden round-trip (downloads the blank, fills every mapped line with
synthetic data, verifies, renders every page — needs network or a warm cache;
drop the `-m` filter), plus the single-pack audit:

```
uv run python -m pytest packages/core/tests/test_formpacks_federal.py -k "<tax_year>-<form_key>"
uv run python scripts/audit_pack.py <pack>
```

Omit `-k` to validate all packs. Synthetic data only: SSN-style values look
like `999-88-7777` / `000-00-0000` — obviously fake, never real PII.

Prefer the cached blanks in `.cache/blanks/` and verify a cached file's sha256
against its pack's pin — then a full audit needs no network at all. If you must
fetch, one URL per call with `--connect-timeout 20 --max-time 90 --retry 1`;
never loop curl over a list of state DOR hosts.
