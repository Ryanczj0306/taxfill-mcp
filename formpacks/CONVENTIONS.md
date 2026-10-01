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
- `<form_key>` MUST be one of these 38 federal keys (forms, then schedules):

  `f1040`, `f1040es`, `f1040nr`, `f1040x`, `f1116`, `f2210`, `f2441`, `f2555`, `f4868`, `f5329`, `f8316`, `f843`, `f8606`, `f8833`, `f8843`, `f8863`, `f8889`, `f8938`, `f8949`, `f8959`, `f8960`, `f8962`, `fw7`

  `sched_1`, `sched_1a`, `sched_2`, `sched_3`, `sched_3a`, `sched_8812`, `sched_a`, `sched_a_nr`, `sched_b`, `sched_c`, `sched_d`, `sched_e`, `sched_nec`, `sched_oi`, `sched_se`

  This list IS `KNOWN_FORM_KEYS` in `test_formpacks_federal.py` — a test holds the two equal, so a new
  key lands in both places in the same change. State
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
  `heptc.required_federal_return.yes`/`.no` was the last live Yes/No instance
  (`homesteadY_checkbox` / `homesteadN_checkbox`, both written with zero
  warnings until it got its group). The same holds for N options that are not
  yes/no — a filing status, residency or account type on one field per box.
  `test_separate_widget_option_sets_are_adjudicated` (test_pack_invariants.py,
  Phase J JEb) requires every such set to share one `group` or to carry an
  `INDEPENDENT` / `PARTIAL` row in `SEPARATE_OPTION_SETS_ADJUDICATED` that
  quotes the printed row ("Check applicable boxes", one box per spouse, ...).

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
   mapped with a leave-blank comment and `reserved: true`, so the key survives
   the revision that un-reserves it (`fill_form` warns when a value lands on a
   reserved line and `scripts/audit_pack.py` skips it; a test holds the flag
   equal to the `RESERVED_LINE_KEEPS` table);
4. the FORM owns the value (a DOR running total, a page-header identity
   mirror, or a cell the form only unlocks on another answer) → it MUST stay
   mapped, because taxfill never runs the propagation and an unmapped one
   ships blank.

**Never map a DOR instruction banner or caption.** A ReadOnly widget whose
blank already carries printed text (an instruction line or a heading) is
class 1, whatever its name suggests. AL-40 2023 (`Instructions`,
`Instructions1`–`11`) and MO-1040 2023/2024 (`Texto7`–`9`, `MOAText`,
`lblNRI`) mapped banners. Once verify began scanning MAPPED ReadOnly widgets
(Phase J J0.3), a real one-line fill FAILed P-001 on every one of them. The
round-trip tests missed it, because their sentinel values overwrote the
banners.

**`maxlen` tracks the widget's own `/MaxLen`.** A pack `maxlen` is never above
the widget's: the filler enforces the pack value, so a higher one lets through
what the PDF then truncates. A pack `maxlen` below the widget's is allowed only
as an adjudicated budget, when the printed box cannot physically hold the
widget's count. Each such row is listed with the measured box in
`TIGHTER_THAN_WIDGET` (`packages/core/tests/test_pack_maxlen.py`, network-
marked, self-clearing). A text line whose widget carries a `/MaxLen` may omit
`maxlen`, because verify's hard MaxLen check still guards it.

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
  The filler enforces the pack `maxlen`. Since Phase J J0 (P-007(b)), verify's
  clipping scan also widget-scans a MAPPED ReadOnly mirror (its own `/MaxLen` and
  width) whenever its value differs from the pinned blank's; an unmapped ReadOnly
  widget (a DOR banner or caption) is still skipped — so never map one as a line.
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
docstring). A line id may be dotted (`10.a`, `ai.27.d`; since Phase J JP5c).
Write a printed factor as a float (`* 4.0`, `* 0.25`): a bare integer is a
LINE reference whenever the pack maps that key. A relation must hold on every
filing path, including a legitimately BLANK part (a schedule the filer does not
use reads as zeros), or it is not declared.

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
- A state pack's `source_url` is the state tax agency's own file on a government host (`.gov`,
  `.mil`, `*.state.<xx>.us`). The one exception is a host an agency itself serves its forms
  from that is not a government name: it is listed, with how that was verified, in
  `taxfill_core.fetch.PINNED_ONLY_BLANK_HOSTS`, and a blank from it is accepted ONLY against
  a pinned `pdf_sha256`. Today that is NM TRD's document library (Phase J JS4d).
- Blank PDFs are NEVER committed. `fetch_blank` downloads them into the
  gitignored shared cache `.cache/blanks/`.
- `mirror_urls` (optional) is for a host that refuses non-browser fetchers
  (mass.gov answers 403). Each entry is the EXACT Wayback snapshot
  `https://web.archive.org/web/<14-digit timestamp>id_/<source_url>` whose
  bytes hash to `pdf_sha256` (the schema enforces the shape). `fetch_blank`
  tries it only on a 401/403, and caches it only when the digest matches.
  A mismatch fails closed. Find the snapshot by fetching
  `web.archive.org/web/<year>id_/<source_url>` and reading the redirect's
  timestamp; hash each capture and pin the one that matches. The drift job
  digest-checks the NEWEST capture of a refused host, so a re-issue behind
  the bot wall still shows up.

## Signature and mailing

| form | `signature` | `mailing` |
|---|---|---|
| `f8843` | its own block; `standalone_only: true` (signed only when filed alone — attached to a 1040-NR it is NOT separately signed) | its own fixed where-to-file: set it |
| `f1040nr` | page 2 block | its own fixed where-to-file: set it |
| `f1040` | page 2 block | `null` — the address is STATE-dependent; knowledge packs own it in M3 |
| schedules (`sched_*`) | `null` (no signature block of their own) | `null` (mailed inside the parent return's envelope) |

`mailing.verify_url` must be the official irs.gov where-to-file page.

## Hand-fill packs (`handfill.yaml`)

A form with no fillable AcroForm ships as `handfill.yaml` beside where its `pack.yaml` would sit
(`formpacks/states/<st>/<year>/<form_key>/handfill.yaml`, or `formpacks/federal/<year>/fincen114/`).
The schema is `taxfill_core.schemas.handfill.HandFillPack`; `hand_fill_worksheet(form, year,
jurisdiction, values?)` turns it into a line→value worksheet. Five ship today: the four print-only
state returns — CT `ct1040`, HI `n11`, NM `pit1`, SC `sc1040` — and FinCEN Form 114 (the FBAR), in
every federal year 2023–2026.

- `render_mode: hand_fill`, and `source_url` is the blank to PRINT — it is never filled.
- `lines` lists the printed lines in printed order: `line` (the same line-id grammar as a
  `pack.yaml` field), `label` (the printed label), `type` (`money`, `text` or `checkbox`),
  optional `note`, and optional `compute` — an expression over OTHER line ids in the relation
  grammar (`max(0, 4 - 5)`, `sum(1a..1h)`), which the engine evaluates so the filer copies a
  derived figure instead of doing the arithmetic. Money lines only.
- `mailing` states where to file or is `null` to defer to the knowledge layer; `signature_note`
  reminds the filer to sign the paper form in ink.
- `instructions` overrides the default "print the blank and hand-write each value" text. Set it
  only when printing is WRONG: the FBAR is e-file only ("IRS will not accept paper filings ... or
  a printed FinCEN Form 114"), so its worksheet gathers values for the BSA E-Filing System instead.
- `efile_only: true` marks a form that is filed only electronically (the FBAR). Its `source_url` is a
  reference document, not a blank, so `fetch_blank` and `fill_form` refuse it. It requires
  `instructions` and forbids `overlay` blocks.
- `printing_guidance` quotes the agency's own rules for entries on the paper form (ink, one
  character per box, machine print), each with `quote` (verbatim), `source` and `url`, or records
  that the agency sets none. `stamp_overlay` returns the rules with every stamp. `min_font_size`
  holds the agency's minimum point size when it publishes one: the overlay never shrinks below it.
  For 2023, none of CT, HI, NM or SC publishes one. HI's N-11 is machine-read ("Enter One Letter Or
  Number In Each Box"), so its overlay entries are combs.
- Hand-fill packs are NOT returned by `list_forms`; an empty `list_forms` for those four states is
  expected. `fincen114` is a directory name, not a `KNOWN_FORM_KEYS` form key — it has no
  `pack.yaml`.

### Overlay coordinates (`overlay:`)

A hand-fill line may also carry an `overlay` block; then `fill_form` STAMPS the worksheet value onto
the print blank (`taxfill_core.overlay.stamp_overlay`, base-14 Helvetica merged over the flat page)
instead of leaving it to be hand-written, and `verify_form` returns the OVERLAY verdict. Lines
without a block stay hand-written rows (`hand_written_lines`).

- **Frame.** PDF points in the page's USER space, origin bottom-left, the frame a content
  stream's `x y Td` uses. `x` is the entry box's left edge, `y` the text BASELINE, `w` its width;
  `page` is 1-based and is checked against the blank's page count at fill time. `h` is an
  optional authoring note for the vision check and never sizes text.
- **Anchor, don't guess.** `taxfill locate <blank.pdf> --page N <label>...` prints each printed
  label's tight box from the blank's text layer, in this same frame. A label's `y0` is its
  baseline when it has no descender (a line number); a caption's `y0` is its descender. Start
  the box right of the label and END it before any pre-printed cents box (`.00`), because the
  verdict reads the whole declared box.
- **Alignment and size.** Money is right-aligned (ending at `x + w`), text and checkboxes left /
  centred. `align: left|right` and `font_size` override per line, and `overlay_defaults` per
  pack (9 pt, money right). A value wider than `w` shrinks toward a 6 pt floor and warns, and
  past the floor it spills and warns — it is never clipped silently. `comb: <pitch>` centres one
  character per cell and drops separators (a comb has no cell for a dash, P-001).
- **Uneven cells and repeated placements (JS4c).** When a form prints per-character cells at
  uneven spacing — an SSN split 3-2-4 around printed dashes, an MM-DD-YYYY date, digits either
  side of a pre-printed decimal point, a scanned form's one-character boxes — give
  `cells: [left edge of each cell]` and `cell_w`. Each character is centred in its cell, and
  separators (space, `-`, `/`, `.`) are dropped because the form prints its own. `x`/`w` stay the
  declared white box, and every cell must lie inside it. Measure the cells from the blank's
  underline strokes (pypdfium2 path objects under the box), never by eye. When the form prints
  the SAME value in several places (the CT-1040's SSN in every page header), `overlay` may be a
  list of boxes: the value is stamped in each, and each is verified.
- **Machine-read forms: painted ovals, minus boxes, digit cells (JS4d, HI N-11).** A form that
  says "Fill in ovals completely" gets `mark: fill` on each checkbox box. The mark paints the box
  solid in the shape scannable forms print — straight sides, round ends of radius min(w, h) / 2 —
  so here `y` is the box's BOTTOM edge and `h` is required. Declare the printed outline's OUTER
  edge: pdfium's bounds for a stroked path include the whole stroke width on each side, so take
  half of it back off, or the paint spills past the outline. A form that shows a loss by shading
  a printed minus gets `minus: {x, y, w, h}` on the money box. A negative value paints that
  rectangle and stamps the digits unsigned. Declare exactly what the form's own example darkens:
  on N-11, the minus glyph inside the pink square, not the square. Money in `cells` fills from
  the RIGHT (the ones digit in the last cell) and drops commas, and a negative value in cells
  with no `minus` is refused, because the sign would silently vanish. The verdict reads both
  kinds of mark from a render: a painted box must be at least 60% dark and an unpainted one
  under 20%.
- **The OVERLAY verdict** keeps only glyphs drawn in the stamp font (unembedded Helvetica; the
  CT, HI and SC blanks embed every font they print). It requires the declared box to hold
  exactly the value, read left to right, and a blank line's box to hold nothing. It trusts the
  coordinates and cannot see printed art, so render every stamped page and vision-check it.

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

## Viewer guards and hidden widgets (P-027)

Some DOR blanks are built for Adobe Reader and its JavaScript. The script shows and hides widgets at
run time; taxfill never runs it (P-007 class 4), so the filler does the viewer's work, deterministically:

- **A hidden mapped widget is still mapped.** A blank may ship a data widget with the annotation
  Hidden (bit 2) or NoView (bit 6) flag and show it only from its script (OH IT 1040's MFS spouse SSN
  `SP_SSN_SEP`, DE PIT-RES's amended-return lines, GA 500's voucher, every AL Form 40 data widget on
  page 1). Map it like any other line. `fill_form` clears Hidden and NoView and sets Print on every
  widget it writes, so the value shows on screen and prints in any viewer.
- **A viewer guard is never mapped.** A widget covering 85% or more of its page that is a pushbutton or
  a ReadOnly text panel is the form's guard, not a taxpayer line: AL 40's yellow "PLEASE USE A DIFFERENT
  PDF VIEWER" `VERCTRL` (viewable and printable) and its white `printlid.N` (NoView + Print, so it prints
  over the page), MO-1040's white `printlid.N` ("PLEASE, USE THE PRINT BUTTON ON THE FORM"). `fill_form`
  sets each one Hidden and lists it in `FillResult.guards_hidden`; `filler.is_viewer_guard` is the rule.
- **verify reads the flags back.** Pitfall check P-027 FAILs a filled PDF whose written widget is still
  Hidden, NoView or without Print, or whose viewer guard is still viewable or printable
  (`verify.widget_flag_problems`); the golden round trips assert it on every pack.
- **The vision audit needs the pass.** `scripts/audit_pack.py` fills through `fill_form`, so its renders
  show the form; a render of the raw blank (or of a file filled any other way) shows AL 40's warning page
  and nothing else — that is what every earlier AL 40 audit was looking at.
- **A selected group member clears its siblings (P-028).** When a fill turns on one member of a checkbox
  `group` whose members are separate fields, `fill_form` writes `/Off` to every other member the caller
  did not name, so a blank that ships one option pre-checked (GA 500's voucher "Paper Return") cannot
  leave two ticks on a one-answer question. An unanswered group is left as the blank had it.
