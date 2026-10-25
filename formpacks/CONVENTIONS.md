# Form pack conventions (binding)

These rules are **binding** for every pack under `formpacks/`. The test
modules below enforce them, and **which one enforces a given rule decides which packs
it actually covers** — read this before trusting the word "binding":

| module | discovers | enforces |
|---|---|---|
| `packages/core/tests/test_formpacks_federal.py` | `formpacks/federal/*/*/pack.yaml` | schema, sha256, line-id grammar, relations parse, the form-specific `sched_d`/`sched_e` pins, golden round-trip |
| `packages/core/tests/test_formpacks_states.py` | `formpacks/states/*/*/*/pack.yaml` | schema/jurisdiction, sha256, relations parse, golden round-trip |
| `packages/core/tests/test_pack_invariants.py` | **every** pack, federal and state | `cross_form` target resolution, the checkbox `group` rules, identity page mirrors, year tokens in line keys |
| `packages/core/tests/test_readonly_widget_mapping.py` | **every** pack, federal and state | which packs may bind an AcroForm ReadOnly widget |
| `packages/core/tests/test_signature_widget_mapping.py` | **every** pack, federal and state | no line binds a digital-signature (`/FT /Sig`) widget |
| `packages/core/tests/test_signature_line_mapping.py` | **every** `pack.yaml` and `handfill.yaml` | no line types a value onto an ink-signature line outside the allow-list |
| `packages/core/tests/test_page_header_mirrors.py` | every pack that declares `mirrors` | each declared mirror is built from demo page-1 identity values on the real blank and verifies (network-marked); the CA Sides 2-6 declarations pinned (every pack's are validated by the schema at load) |

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
- **A numbered key equals the line number printed on its row (P-031).** A pack
  ported from an older face can carry the old numbering one line off, and its
  relations — written against the same keys — still pass, so verify cannot see
  the shift. Read the printed number beside every numbered widget on the
  year's own blank. A letter is part of a key only where the face prints it:
  a second box on line N that the face does not number (a "Describe:" box, a
  "$" sub-amount, an input the line multiplies) is keyed "N.<what>" named for
  what it holds ("4.description", "40.penalty", "17.spouse_vagi"), never "Na",
  and the box the face numbers N keeps the bare "N" (Phase K JK10, 2026-10-24).
- **Bind each option widget to the label printed beside it, never by the
  widgets' order (P-030).** A row can print an option that has no widget — NJ-1040
  line 6 prints its "Self" oval solid black because every filer takes it — and
  keying the remaining widgets left to right then shifts every key by one. A
  pre-printed, widget-less option gets no line.
- **A widget's name is a hint, not a binding: bind by the caption printed on
  its row (P-032).** Form 1040ME names three page-2 widgets "Nonresident
  credit", "Total tax" and "Tax credits" and prints them rotated against those
  captions ("Total tax" on the row printed 21 NONRESIDENT CREDIT, "Tax credits"
  on 22 TOTAL TAX, "Nonresident credit" on 23 NONREFUNDABLE TAX CREDITS), so
  binding by name put every filer's line-21 amount in the line-23 box. Measure
  the widget rect against the printed line number before trusting a
  descriptive name, and when the name and the row disagree, say so in the
  field's comment ("the widget NAMED X sits on this row").
- **The label-adjacency gate holds every pack to P-031 and P-032 (Phase K JK10,
  2026-10-24).** packages/core/tests/test_label_adjacency.py (network) runs
  scripts/label_adjacency.py on every shipped pack: each numbered key must equal
  the line the pack-blind anchor reads beside its widget on the pack's own blank.
  A key whose trailing letter names a COLUMN of printed line N rather than a
  sub-line (Delaware's "1a" / "1b" = line 1, Column A / Column B; Form 8962's
  monthly columns; Schedule NEC's rate columns) is declared once in
  formpacks/column_keys.yaml — the packs, the line range, what each letter
  means and the column header the face prints — never by renaming keys; the
  gate checks the header against the blank and refuses a covered line the
  blank prints as a sub-line. A disagreement that a blind vision check of the
  row finds is not a pack defect goes in formpacks/label_adjacency_exceptions.yaml
  as one row per widget naming exactly that disagreement (pack, field, widget
  index, the key's line, the anchor's line) in a family that carries the
  adjudicated reason; every other one is fixed in the pack. The table clears
  itself: a row that matches no live disagreement any more fails the gate as
  stale, and a second row for one widget is refused.
  `scripts/scaffold_state_year.py --triage` runs the same gate on the base
  pack a port starts from (BASE-MISBOUND) and turns a PORTABLE verdict into
  RE-MAP when a mapped widget's /Rect moved.
  A family keyed in a shape KEY_RULE does not read ("1_wages_fed",
  "line19_d01", "A1a_A") declares one regex in formpacks/key_shapes.yaml
  (named groups `n` = the printed line number, `x` = its sub-line letter),
  checked on each listed pack's own face: every line it maps a key to is
  printed there; a column shape also names the column headings its faces print
  (`header`, checked like a convention's). formpacks/label_adjacency_coverage.yaml
  records, per pack, the line-bearing keys, how many a rule or shape maps and how
  many the gate compared. LINE-BEARING is not "what the gate can map" (that
  denominator was circular: MS 80-105's "13.a" keys reported OK 26/26 with every
  main line unchecked): a key is line-bearing when it carries a line-like token
  (a 1-3 digit run with at most two letters, "line"/"ln" + digits; not an age
  threshold) outside the ledger's short `not_lines` list (identity values,
  household-member rows, rows numbered by position), or when a rule maps it. A
  pack below its floor names the reason (no text layer, the anchor reads no
  designators, a key shape not declared, no numbered lines), no pack at or above
  it has more undeclared line-like keys than checked ones, and the gate fails
  when a pack's coverage drops below its row (a regression) or rises past it (a
  stale row: update it with `--write-ledger`). A fraction cannot see a whole
  schedule left dark (OH's Schedule of Business Income, 22 undeclared keys, read
  OK at 121/152), so a DARK key family — the key with its line tokens as "#"
  ("schedITbus_#"), holding 5+ undeclared keys or 5+ line-bearing keys none of
  which is checked — puts the pack below the floor whatever its fraction; its
  ledger row names the family (`dark`) and the reason (Phase K JK10, fixer round
  4). THE DECLARE-ME RULE (fixer round 5, 2026-10-24): an undeclared line-like
  key beside one of whose widgets the anchor reads a printed line puts its pack
  below the floor whatever its family's size, until a shape or convention
  declares it or `not_lines` lists it with its reason; the row names those
  families (`declare`), and no row at or above the floor holds such a key (a
  test holds it over every pack). AZ 140's seven-key charitable worksheet
  ("ws3_1c_..." ... "ws3_7c_..."; the anchor reads 1c-7c) and MT 2023's four
  LTC-rent rows ("ltc.1"-"ltc.4") had reported OK. A key's FAMILY is the key up
  to and including its first line token, the descriptive tail dropped, digit
  runs as "#" ("ws#_#"); the 5-key DARK threshold governs only the families the
  anchor reads no line beside. A `not_lines` family that holds on one form only
  lists its `packs`. Keys of a named block that carry no line number ("age65_blind.*" on MS
  line 8) are declared with the block's printed `line`. Triage calls a base below the
  floor UNCHECKED or PARTIAL n/m, never OK, and the row BASE-UNCHECKED: check its
  line binding by hand (a handfill.yaml base has no binding to check and keeps
  its port status; vision-check its overlay boxes on port). A new pack keyed "N.<what>" ("4c.rollover", "9.primary")
  joins the generic `line-boxes` shape once its face check passes.
  **What the gate cannot see** (fixer round 6, 2026-10-24; the same list as
  scripts/label_adjacency.py's docstring and the ledger header). A line-number
  check stops at four blind spots; the ledger COUNTS each one per pack, and the
  gate fails when a count goes stale (`--write-ledger` re-measures it):
  (a) `same_row` — a SAME-ROW COLUMN SWAP: two boxes of one printed row claim
  the row's one line (federal <-> state amount, Column A <-> Column B, dollars
  <-> cents, two digit cells of one comb); (b) `unread` — a box the anchor
  reads NO line beside, inside any family, declared or not (Form 8962's monthly
  rows, AZ 140's page-4/5 rows); (c) `cross_section` — a swap between SECTIONS
  THAT PRINT THE SAME LINE NUMBER (OK 511 / 511-A / 511-B line 1, OH IT 1040 /
  Schedule A / Schedule of Business Income, MT Form 2's tax calculation /
  Schedule I Part II, WI Schedules 1 / 2, NY IT-201 items D2 / E / F, CA
  Schedule CA's B7_A / 7_A / II7_A, Schedule 1-A 2026's 1 / 28a / 28b): each box
  reads the line its key claims, so a swap between sections passes — a
  section-aware comparison is an open item; (d) `descriptive` — a box the
  anchor reads a line beside whose key the gate compares nothing for: it
  carries no line token (UT TC-40's withholding_*, IA 1040's
  spouse_net_income, NY IT-203's D2_months_you_yonkers, VA 760's
  exemptions_section_a_total_count), or a `not_lines` family leaves it out
  (MT Form 2's dd529 item boxes, AZ 140's *_more_space, RI-1040's Schedule W
  rows). Keys on boxes the exceptions table excuses count in (a) and (c) too:
  an exception matches the widget and the lines, so another key claiming the
  same line passes at that box. On round 1's planted swaps the gate caught 238 of 249
  and its 11 misses were all same-row column swaps; the later re-verifier
  rounds' planted misses fell in (b), (c) and `not_lines` families and their
  census found (d), which is why the list is counted rather than chased. A line that is only a letter
  (MT Form 2 2023's exemption rows a-d) is in no shape the gate can express:
  its pack reads PARTIAL with that reason. Every counted key is the vision
  audit's and the relations' to check.
- **The pack-blind anchor is a second reader, not a binding (Phase K JK15,
  2026-10-24).** `taxfill_core.anchor` reads each widget's printed line from
  the blank alone, for forms with no pack. scripts/anchor_benchmark.py scores
  it against the shipped packs' numbered keys ("21", "5a", "line_21",
  "21.col_b"; every other key shape is unscored), so a disagreement there is
  either an anchor miss or a pack rotation, settled by a blind vision check.
  Its tiers are "anchored (unverified line map)" (the top tier, never
  "high"), "med", "low" and "none". Even the top tier is an unverified line
  map, and nothing above "low" is emitted until
  knowledge/anchor/benchmark.yaml has passed.

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
`maxlen`, because verify's hard MaxLen check still guards it. A widget with NO
`/MaxLen` gets the count a probe fill renders whole, read on a high-dpi render
(a budget is the filler's refusal, so it is read off the render, not inferred). Probe a numeric box
(SSN, FEIN, ZIP, apartment number) with digits and a name, initial or code box
with a cycle of capitals A-Z (an all-caps entry is the widest realistic one);
a Helvetica date box budgets its date shape ("MM/DD/YY" renders whole where 8
bare digits do not), and an auto-size (`0 Tf`) box, which never cuts, holds
the longest probe still drawn at 6 pt. Lower the pack `maxlen` when it allows
more than renders, pin the box, its probe and its fit in
`MEASURED_WITHOUT_MAXLEN` (same module), and give one box one budget in every
year — the CA 540NR "Apt. no/ste. no." box, identical in 2023-2025, carried
14 / 12 / 13 until JK27 (2026-10-16) measured 12, and the OH IT 1040
preparer-name box 25 / 25 / 21 until JK28 measured 21.

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

- Name a new mirror for the page it fills: `page<N>_<what>` (`page2_ssn`,
  `page3_name_last`) or `<what>_page<N>` (`identifying_number_page2`);
  `_page1` is NOT a mirror. Every mirror-shaped line (the full list of key and
  AcroForm field shapes is under "What the harness enforces, and what it does
  not" below) must be declared in `mirrors` (next section) or listed, with the
  printed reason, in `test_pack_invariants.NOT_A_MIRROR`.
- A plain one-source mirror (`"{line}"`) must agree with its source on `type`
  and `format`, and may be a comb only when its source is one. Harness
  enforced. If the mirror and its source keys bind the SAME field, the mirror
  key is redundant — one write already fills both widgets (PA-40's `your_ssn`
  is one field whose widget repeats).
- `maxlen` tracks each widget's OWN `/MaxLen` and may legitimately differ
  between mirror and source (a DOR often prints a narrower continuation box).
  The filler enforces the pack `maxlen`. Since Phase J J0 (P-007(b)), verify's
  clipping scan also widget-scans a MAPPED ReadOnly mirror (its own `/MaxLen` and
  width) whenever its value differs from the pinned blank's; an unmapped ReadOnly
  widget (a DOR banner or caption) is still skipped — so never map one as a line.
- **The mirror's VALUE** — that it repeats its source — is what `mirrors:`
  declares (next section, Phase K JK28). `relations` is arithmetic over money
  lines and `identity_fields` drives a cross-FORM check, so before JK28
  `page4_name_last == name.last` had no home: a caller that filled a mirror
  differently filed an internally inconsistent return and no gate caught it.
  Now `mirrors` says what each one repeats, fill_form builds it when the caller
  leaves it out, verify_form FAILs a header that says something else, and the
  harness refuses a mirror-shaped line that is not declared.

### Page-header mirrors (`mirrors`)

A pack declares how each mirror it maps is built from its own lines, as a
template (Phase K JK28, 2026-10-16). The JK5 release-candidate walkthrough
filled a CA Form 540 whose Sides 2-6 printed blank "Your name:" and "Your SSN
or ITIN:" headers, and verify_form passed; the CA packs now say:

```yaml
mirrors:
  name.full: "{name.first} {name.middle_initial} {name.last} {name.suffix}"  # "Your name:"
  identifying_number.page6: "{identifying_number}"                          # "Your SSN or ITIN:"
mirror_abbreviations:
  name.full: [name.first, name.middle_initial]                              # a name too wide for the box
```

Quote the template: a YAML value that starts with `{` is a mapping.

| syntax | meaning |
|---|---|
| `{line}` | the line's value as `fill_form` renders it, after the line's own formatting (`ssn_digits_only` strips dashes, `ssn_dash_cells` writes `ddd-dd-dddd`, a money line is whole dollars, comma-grouped on a `money_comma_cells` line) |
| `{line[a:b]}` | a Python-style character slice of it: `[0:3]`, `[3:5]` and `[5:]` split a 9-digit SSN across three boxes, `[:10]` is "first 10 characters of your last name"; a negative bound counts from the end; there is no step, and an index is refused. A slice of a line in an SSN format (`ssn_digits_only`, `ssn_dash_cells`) counts its DIGITS, so `[3:5]` is the middle two digits whether the line holds `999887777` or `999-88-7777` |
| `[ ... ]` | an optional segment, kept only when a placeholder inside it renders non-empty: `{name.first} {name.last}[ & {spouse.first} {spouse.last}]` prints the spouse's part only on a joint return. Segments do not nest |

Each placeholder's value is whitespace-collapsed and stripped before it is
sliced. The rendered template is whitespace-collapsed and stripped, and when
every placeholder renders empty it renders empty, literal text included, so
nothing is written. Braces and square brackets are syntax only.

**What the schema refuses at load** (every pack): a key that is not a TEXT
line of the pack; a mirror whose AcroForm field another line also binds (one
write already fills every widget of a shared field — PA-40's `your_ssn`); a
placeholder that names no line of the pack, a checkbox line, or the mirror
itself; mirrors that read each other in a cycle (a mirror MAY read another
mirror, and is then built after it); and a malformed template — an unclosed or
stray brace or bracket, a nested or placeholder-less segment, an index, a step,
a slice that is empty for every value (`[5:2]`, or any stop of 0: `[:0]`,
`[-1:0]`), or no placeholder at all (a constant is a value the filler would
invent).

**A name too wide for its box (`mirror_abbreviations`).** A template says what a
header repeats, not how to shorten it, and the CA booklets give no rule for a
name too wide for the Sides 2-6 box (their page 11 speaks of abbreviating only
country names: "Do not abbreviate the country name."). So a pack may name, per
mirror, the placeholders whose words the header may shorten to a leading part —
an initial, with or without a period — or leave out; every other placeholder and
all literal text must still appear whole and in order. The CA packs list
`name.first` and `name.middle_initial` for `name.full`: "A Q WASHINGTON" and "A.
WASHINGTON" both abbreviate "ALEXANDRA Q WASHINGTON", while "ALEXANDRA Q
WASHING" (the last name cut) and "SAM Q WASHINGTON" (another first name) do not.
`name.suffix` stays whole: a generational suffix ("JR", "III") has no initial.
The schema refuses a key that is not a mirror; a comb or `ssn_digits_only`
mirror (an identifying number is compared digit for digit, never abbreviated);
an empty list, a line its template does not read, or one named twice; and a list
that covers every placeholder, since initials alone would then pass.

**How a mirror is measured** (`taxfill_core.textfit`, the one measure the filler
and verify share; Phase K JK28, 2026-10-16). A value fits its box when it is
within the line's `maxlen` and its ink at the widget's /DA font and size ends
inside the widget's width less its border on each side: pdfium draws from inside
the border (1 pt when the widget declares none, its /BS /W otherwise) and clips
inside the far one, the model the measured rows of
`packages/core/tests/test_pack_maxlen.py` pin. The ink is the advance less the
side bearings of the first and last glyphs, laid out by the box's /Q (from the
left inset, ending at the right one, or centred, so a centred value overruns on
both sides), give or take 0.5 pt (Phase K JEe, P-035: a value that filled the
rect edge to edge printed cut); verify's clipping scan measures every
single-line value the same way. Helvetica and Arial advance by
Adobe's Core-14 Helvetica AFM widths (`overlay.text_width`), Courier and Courier
New by 0.6 em a glyph. Any other face whose AcroForm /DR font carries a /Widths
array (ND-1's Verdana, IA 1040's Calibri) advances by those widths, the layout
every viewer uses whatever face it substitutes, with its ink counted to the full
advance (Phase K JEe3, `textfit.font_widths`); a face with neither is measured
as Helvetica. Size such a box's budget by its /Widths, not by Helvetica's: a
Verdana digit is 0.636 em, so ND-1's 43.6 pt signature-date box holds MM/DD/YY,
not MM/DD/YYYY. A field with
a widget on several pages must fit each one, in practice its narrowest; an
auto-size /DA (`0 Tf`) always fits; a multiline or zero-width widget is not
measured. A comb box is not measured by width either: its `maxlen`, digits-only
and 'NRA' rules stay refusals. CA's "Your name:" box is 125.9-127.0 pt wide at
Helv 10, so it holds 123.9 pt, about 18 capitals. "ALEXANDRA Q WASHINGTON" is
142.8 pt, and P-001's 0.5-em estimate (110 pt) passed it.

**`font_size`: a box sized edge to edge for its glyphs** (Phase K JEe2,
2026-10-25). Some blanks size a box for exactly the glyphs it takes at its /DA
size, so the widest value loses ink inside the border (RI-1040's 57.6 pt date of
birth holds 8 Courier New 12 digits with no room for the 1 pt border). A text or
money line may then carry `font_size` (points, > 0, at most the widget's own /DA
size): `fill_form` writes that widget's /DA at that size, font and colour kept,
before any appearance is built, so pypdf's appearance, a viewer that regenerates
it and verify's width check (which reads the /DA off the filled PDF) all use it.
Choose the LARGEST size at which the widest value the box takes prints whole by
the ink model above (overrun at most 0 pt, not the 0.5 pt tolerance) and on a
pdfium render, and record the measurement in a pack comment. `fill_form` refuses
a `font_size` above the widget's /DA size, or on an auto-size (`0 Tf`) box. A
line without `font_size` is never touched; use it only for a box the measure
says cuts the value the line is meant to hold, never to fit an over-long value
(shorten the value instead).

**What `fill_form` does.** After the caller's values are validated and rendered,
every mirror the caller left out (absent or blank) is built from them, in
dependency order, measured against the blank's own widgets, and written like any
other line; `FillResult.mirrored` lists those lines (the MCP tool returns
`mirrored`). It writes the first value of `schemas.formpack.mirror_ladder` that
its box holds: the template's full value; then, for a mirror whose
`mirror_abbreviations` cover a word of it, every such word cut to its first
letter ("A Q WASHINGTON"); then only the first of them kept, as its initial ("A
WASHINGTON"). An abbreviation comes with an informational warning that names
both values and their widths. When nothing fits — a surname too wide for the box
on its own, or a pack that allows no abbreviation — the mirror is left BLANK,
and a warning gives the measured and available widths and says to hand-write it
in the box after printing. A built value the box refuses for its form (comb
digits only, the P-026 'NRA' refusal) is also left blank, with a warning saying
why. A mirror the caller passes is written as given: never rebuilt, and not
measured at fill time (verify measures it). Rehearsal fills take the same path;
a hand-fill pack (`handfill.yaml`) has no `mirrors`, and its overlay stamps
exactly the values it is given.

**What verify checks.** `verify_form`, and `verify_filing` for each item, add
one `identity` check per mirror, labelled `page-header mirror <line>` (prefixed
`<form_key>: ` in a filing). The value the header must hold is computed as the
filler computes it, with the same ladder and measure, from the PDF's ON-DISK
source values and the widgets read off the PDF. Values compare
whitespace-collapsed and case-insensitively: digits only on a comb or
`ssn_digits_only` mirror, and whenever both are written with digits, dashes and
spaces alone (CA's plain-text "Your SSN or ITIN:" box may hold 999-88-0101 while
Side 1 holds 999880101). PASS when the header repeats the full value and its
box holds it, or when it abbreviates the value as `mirror_abbreviations` allow
while the full value does NOT fit and the abbreviation does. FAIL, which flips
`ok`, when the header is cut off, abbreviates a value that fits ("EXAMPLE" for
"RILEY EXAMPLE"), is blank while a value that fits exists, or holds anything
else; each detail names the value to write (or, when the box refuses the value
for its form, what to pass instead). SKIPPED when the template renders empty
(nothing to mirror), when the header is blank because no allowed value fits (the
detail says to hand-write it after printing), and when the header abbreviates a
value whose box could not be measured (a field dump verified with no widgets).
A mirror of a mirror is checked against its source as written on disk, so a
blank source FAILs once, on the source. P-002 never reads a mirror check as the
return address.

**When to declare one.** For every line that repeats other lines of the same
pack — a page-header name or SSN, or a fixed slice of one — once you have read
the printed header and the instruction that governs it. Quote both in a comment,
check that the mirror's widget `/MaxLen` holds the source AS RENDERED (a dashed
SSN is 11 characters; the CA 2024 Form 540's Side 1 box takes 9, so a dashed SSN
never reaches its mirror), record the box's width and /DA font, and build the
name from the pack's own page-1 lines. Do not declare a box the form lets the
filer word differently from its source: the check would FAIL a correct return.
Nor a box the face says to leave blank: Schedule E page 2 prints "Do not enter
name and social security number if shown on other side.", and page 1 always
shows them, so its `name_page2` / `identifying_number_page2` are listed in
`NOT_A_MIRROR` instead. A name too wide for its box is the one exception, and
`mirror_abbreviations` declares which parts may shorten, keeping the last name
whole; add it only when a long demo name (measured with `taxfill_core.textfit`
on the real widget) overflows the box. The CA Form 540 and 540NR packs were the
pilot (2026-10-16); the sweep (Phase K JK28, 2026-10-23) declared the rest of
the mirrors the harness can find.

**What the harness enforces, and what it does not.** `test_pack_invariants.py`
("Identity page mirrors") fails a pack that maps a MIRROR-SHAPED line without
declaring it in `mirrors:` or listing it in `NOT_A_MIRROR` with the printed
reason. A line is mirror-shaped when its key has a page shape (`page2_name`,
`name_page2`, `name_pg2`, `name_p2`, `identifying_number.page6`,
`tp_ssn_page_header`, `identifying_number.echo`) or is a `header.` /
`header_` identity key (`header.name`, `header.taxpayer_id`, `header_name`:
one field with a widget on each later page), or, for a text line, when its
AcroForm field is named like a copy (`..._COPY`, `... again`, a name or SSN cell
ending `pgN`, or one starting `pgN` and then naming the cell: GA's
`TP_FIRSTNAME_COPY`, AL's `PG2NAME`). It also pins each pack's declared count. A
plain `"{line}"` mirror must share its source's `type` and `format`, and may be
a comb only when its source is one (DE's plain "TAXPAYER ID" header mirrors the
page-1 comb). It cannot see a mirror whose key AND field read like any other
line (AL Form 40NR's `NAME`, `SCHOCSSN`, ...), and it cannot see a header field
the pack leaves unmapped (GA 2023's `SSN_COPY` until Phase K JK28): those are
found by reading every page's header on the blank, and once declared the count
pins them. The follow-ups the sweep named were closed on 2026-10-23: GA 2023
`ga500` maps `SSN_COPY` as `tp_ssn_page_header`; AL 2023 `al40nr` declares its
34 schedule headers, while page 4's `PG2NAME` / `SSSNB2A` and Schedule HOF's
boxes print "(Do not enter name and social security number if shown on other
side)" and are not built; DE `pit_res` 2024-2025 declare `header.name` /
`header.taxpayer_id`, IA `ia1040` 2023-2025 `header.name`, and the new key
shape found CO `dr0104` 2023's `header_name`, now declared too.

### Lines filled only when the form is filed by itself (`standalone_only_lines`)

Forms 8843, 8606 and 5329 print "Fill in your address(es) only if you are
filing this form by itself and not with your (U.S.) tax return". Attached to
the return those boxes are correctly blank, and verify must not call that an
identity mismatch or a missing current address (P-002). Declare such lines in
`standalone_only_lines` (Phase K JK27):

- List every line the caption governs (`mailing_address`, `home_country_address`
  on 8843; the `mailing_address.*` lines on 8606 and 5329), and quote the
  caption in a comment. The schema refuses a key that names no line.
- verify_filing honours it only when the filing holds a Form 1040, 1040-SR,
  1040-NR or 1040-X (the Form 8606 instructions file a revised 8606 "with Form
  1040-X"). Beside a claim (Form 843), an ITIN application (W-7), a state return
  or another standalone form, the lines are required as usual, and a form
  verified alone counts as filed by itself.
- A filled value is still checked: against the confirmed current address, and
  against any other form that maps the same line key.
- test_standalone_only_lines.py pins the shipped declarations; a new form with
  such a caption adds its packs there.

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

**The one exception: a path the face marks with a box** (Phase K JK28,
2026-10-16). Some faces print a checkbox that tells the reader a line is
computed another way. IA 1040's Step 5 box reads "Check if using alternate
tax (line 5), tax reduction calculation (line 12), or low-income exemption",
and the Income Tax Reduction Worksheet (41-146) puts its own amount on line 12:
"Enter the smaller number here and on IA 1040, line 12. Check the box on IA
1040, step 5 if the amount on line 3 is used". A relation that holds on every
path except the one such a box marks ends in ` unless <line>`, where `<line>`
is a CHECKBOX line key of the same pack:

```yaml
relations:
  - "12 == max(7 - 11, 0) unless alt_tax_method"
```

- verify reports the relation SKIPPED while the box is checked in the filled
  PDF (its export value, not `/Off`). SKIPPED is visible in the report and in
  the MCP summary's `skipped` list, and it never fails `ok`. While the box is
  unchecked the relation is checked as usual. A bare `relations()` call with
  no field dump reads every box as unchecked.
- The pack load refuses a malformed clause: a second `unless`, nothing (or
  more than one word) after it, no equation before it, a capitalised keyword,
  or a guard that names no line or a money / text line. `cross_form` rules
  take no guard, and the load refuses one there too.
- Guard only what the face or its instructions tie to the box, and quote both
  beside the relation. One box often marks several methods: IA's suspends
  line 12 for the alternate-tax and low-income returns too, where the floor
  still holds. Say so in the comment. The IA 2023-2025 packs guard
  `12 == max(7 - 11, 0)` (the worksheet) and `8 == d` (the low-income
  filer who claims only the Iowa EITC is told to "Skip lines 5 through 19").
  `7 == 5 + 6` stays unguarded, because the alternate tax replaces line 5's
  amount and line 7 still adds lines 5 and 6.
- `unless` is a reserved word in relations: no line key may spell it.

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

**Never map a digital-signature (`/FT /Sig`) widget.** Some DOR blanks put one
on an ink-signature line (WV IT-140's "Preparer’s Signature", AR1000F's
Signature1-3). fill_form writes the string as the field's `/V` and counts it
written, but nothing renders it. Leave the line unmapped with a comment naming
the widget: the filer signs on paper, and `signature: {page: N}` says where.
Also check what a widget near a signature line really sits in: OK Form 538-S
2023 / 2024 name their "Occupation" widgets for the box below, but place them
inside the signature box (JK27, 2026-10-16;
`packages/core/tests/test_signature_widget_mapping.py`,
`test_ok538s_occupation_mapping.py`).

**Never map an ink-signature line either, whatever its widget type.** Some DOR
blanks put an ordinary /Tx widget on the rule the filer signs: KS K-40
2023-2025 ("Signature of taxpayer", "Signature of spouse", "Signature of
preparer"), KY 740 2023-2024 (the same three, capitalized), IL-1040 2025
("Paid preparer’s signature"). A typed value prints there, so a mapped key
puts a typed name on the line the state asks the filer to sign: "Your income
tax return must be signed" (KS booklet), "Each return must be signed by the
taxpayer" (KY 740 instructions), "the paid preparer must also sign and date
your return" (IL-1040 instructions). Treat the line like a /Sig widget: leave
it unmapped with a comment that quotes the face and the instructions, and give
the pack `signature: {page: N}`. Keep a signature line mapped only where the
state's own face or instructions make an entered name a signature, and record
that quote on an allow-list row. The one case is MO-1040 2023-2025, whose
page-5 declaration reads "By signing or entering my name in the “Signature”
field(s) below, I am providing the Department of Revenue with my signature as
required under Section 143.561, RSMo." Even there the default is the ink
signature: the pack comment above the lines tells an agent not to fill them
unless the filer asks (MO's "AGENT RULE", pinned in
`test_signature_line_mapping.py`), because a pack field carries no note the
agent would see. A Sign Here block with no widget on any signature line
(IL-1040 2023 and 2024) still gets `signature: {page: N}`. The date, phone,
driver's-license, PTIN and printed-name boxes of a signature block are ordinary
data and stay mapped, and so do yes/no questions such as MO's "failtosignYES" /
"failtosignNO" (Phase K JK28, 2026-10-16;
`packages/core/tests/test_signature_line_mapping.py` pins the dropped keys,
carries the allow-list, and sweeps every pack's line keys and widget labels for
a signature line outside it).

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
mirrors, year tokens), the ReadOnly adjudication and the two signature checks
(no `/FT /Sig` widget bound, no ink-signature line typed onto) — these cover
federal AND state packs, so run them whichever lane you touched:

```
uv run python -m pytest packages/core/tests/test_pack_invariants.py
uv run python -m pytest packages/core/tests/test_readonly_widget_mapping.py
uv run python -m pytest packages/core/tests/test_signature_widget_mapping.py
uv run python -m pytest packages/core/tests/test_signature_line_mapping.py
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
- **A viewer guard is never mapped.** A widget covering 85% or more of its page's VISIBLE area (the CropBox — AL 40's
  worksheet pages crop a short window out of a Letter MediaBox) that is a pushbutton or
  a ReadOnly text panel is the form's guard, not a taxpayer line: AL 40's yellow "PLEASE USE A DIFFERENT
  PDF VIEWER" `VERCTRL` (viewable and printable) and its white `printlid.N` (NoView + Print, so it prints
  over the page), MO-1040's white `printlid.N` ("PLEASE, USE THE PRINT BUTTON ON THE FORM"). `fill_form`
  sets each one Hidden and lists it in `FillResult.guards_hidden`; `filler.is_viewer_guard` is the rule.
  A `/Btn` pushbutton flagged NoView + Print counts from half the visible page up (P-027b): it shows on no screen and
  prints on paper, so a large one is treated as a print lid — AL Form 40NR's NOL-85A lids cover 73-83% of the page.
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

## Comb boxes and their printed separators (P-033)

A comb widget's cells are its `/Rect` split into `/MaxLen` equal parts, whatever the page prints under it. On the IRS
Form 1040 and 1040-X SSN boxes (2023-2026) the dotted 3-2-4 separators follow a narrower grid than the widget, and
before Phase K JK28 the dots crossed the third and fifth digits. `fill_form` now corrects that itself,
deterministically:

- **A crossing comb is narrowed to its printed grid.** When a visible separator printed inside a written comb falls
  inside a character's cell, the filler reshapes the widget's `/Rect` (horizontally only) to the uniform grid the
  separators imply, starting at the box's left rule, before any appearance is built; `FillResult.combs_aligned`
  names each widget moved (`filler.comb_cell_grid` is the rule). Map the line as usual (`comb: true`, and
  `format: ssn_digits_only` on an SSN); no pack key is involved.
- **Everything else is left as printed.** A comb that already clears its separators; a bordered, filled or rotated
  widget; separators in a pale tint (luminance 200 of 255 or paler: the tinted cells of the DE, IA, IL, LA, MA, OR
  and VA blanks, even where the tint crosses a digit, as on the IA 1040 and the MA Form 1 ZIP box) or printed as
  text (the CA Schedule CA slashes); and a box no uniform comb fits, such as AZ Form 140NR 2023 worksheet line 8C,
  whose fifth box is narrower. Describe such a box in the pack banner (as the CA Schedule CA 2024 banner does) and
  check it on the render.
- **A cell that sits on a printed dash takes the dash: `format: ssn_dash_cells`.** An 11-cell SSN comb printed as
  3 boxes, a dash, 2 boxes, a dash and 4 boxes (every Oregon Form OR-40 SSN box, 2023-2025) spends cells 4 and 7
  on the dashes, so 9 bare digits fill the first nine cells and every digit from the 4th on lands one or two cells
  off its printed box. Map such a line `comb: true`, `maxlen: 11`, `format: ssn_dash_cells`: `fill_form` takes the
  SSN or ITIN with or without dashes and spaces, writes it `ddd-dd-dddd` (each dash cell gets the dash), refuses
  anything but 9 digits, and refuses the format on a pack line or a blank widget that is not an 11-cell comb.
  `verify_form`, the cross-form identity checks and page-header mirrors compare the line by its digits, so a value
  written either way verifies. Phase K JK28 (2026-10-23): `test_pack_invariants.py` requires every SSN-like comb
  line with `maxlen: 11` to use the format or to sit in `ELEVEN_CELL_SSN_COMBS_WITHOUT_DASH_CELLS` with what its
  box prints (VT IN-111 2023: a plain box whose widget has no Comb flag), and the network-marked
  `test_an_eleven_cell_ssn_comb_widget_writes_its_dash_cells` reads the BLANK: a line bound to an 11-cell Comb widget
  (`/Ff` comb bit, `/MaxLen 11`) whose key is SSN-like must use the format whatever the pack's own `comb` says, or sit
  in `ELEVEN_CELL_SSN_COMB_WIDGETS_WITHOUT_DASH_CELLS` with what its box prints. MO-1040's page-1 `SSN_1` / `SSN_2`
  (2023-2025: three printed boxes of 3, 2 and 4 digits with a dash printed between them, no cell rules) are such
  combs and use the format too (Phase K JK28, 2026-10-23). The separators there are expected inside cells 4 and 7,
  and the filler leaves the widget alone.
- **A money cell that sits on a printed comma takes the comma: `format: money_comma_cells`.** A money line is written
  in bare whole dollars (`1234567`), which suits a plain box and a comb whose printed commas sit ON the rule between
  two digit cells (the LA IT-540, MA Form 1 and VA 760 dollar boxes). The Oregon Form OR-40 dollar boxes (2023-2025,
  lines 7-55b) instead spend cells on the commas: an 11-cell right-aligned comb (`/Q 2`) printed as 3 cells, a comma
  cell, 3, a comma cell, 3, then `.` and a printed `0 0`. Bare digits fill it from the right with no regard for the
  comma cells: 1234567 printed `123[4]567` with the 4 in a comma cell, 12345 put its 2 in one, and only amounts under
  1,000 landed right (1,234,567 could be read as 123,567). Map such a line `type: money`, `comb: true`, `maxlen: <the
  widget's /MaxLen>`, `format: money_comma_cells`: `fill_form` rounds to whole dollars as always, then writes the
  amount comma-grouped (`1,234,567`), so each comma cell gets the comma and each digit its printed cell. A negative
  amount keeps its sign, and the minus always takes a DIGIT cell: the one left of the first digit (`-5`, `-12,345`,
  `-1,234,567`), except that for an amount of 3 or 6 digits that cell is a printed comma cell, so it is left blank and
  the minus goes one cell further left (`- 123`, `- 123,456`; Phase K JK28 fix, 2026-10-23: written `-123,456`, the
  minus sat on the printed comma in cell 4, where a reader taking it for the separator loses the sign). The OR-40 face
  prints no loss box or sign cell, and the OR-40 instructions (2023-2025) give no rule for a negative entry on the
  form; the only one they print, on the amended-return worksheet, is "If less than 0, use a minus sign." (Form OR-40
  Instructions, https://www.oregon.gov/dor/forms/FormsPubs/form-or-40-inst_101-040-1_2025.pdf, sha256
  4ee45bad719499e2..., and the 2024 and 2023 editions, 697d45e372fa352d... and 200c94c973eacb56..., each downloaded
  twice 2026-10-23 with matching digests; their line instructions say only "Don't enter cents."). The filler refuses
  an amount the cells cannot hold (an 11-cell box holds at most 999,999,999, and -99,999,999 when negative: the minus
  spends a digit cell, and the refusal names the limit for the amount's sign) with what to do, refuses the format on a
  pack line that is not a comb money line (the schema) and on a blank widget that is not a right-aligned comb of the
  pack's `maxlen` cells. `verify_form` reads the value back through `parse_money`, which drops the commas (and the
  blank cell of `- 123`), so assertions, relations and the independent recompute see the number. Phase K JK28
  (2026-10-23): the network-marked `test_a_money_comb_widget_writes_its_separator_cells_or_is_listed` in
  `test_pack_invariants.py` reads the BLANK: every money line bound to a Comb widget uses the format, or its pack sits
  in `MONEY_COMBS_WITHOUT_COMMA_CELLS` saying what its boxes print; and the offline
  `test_money_comma_cells_is_used_only_where_the_census_rendered_comma_cells` holds the other direction: the format is
  used only by a pack in `MONEY_COMBS_WITH_COMMA_CELLS` (the census's comma-cell packs, OR-40 2023-2025), because on a
  comb whose commas sit on the rules the fill-time widget check passes and the commas would take digit cells. The
  census behind it (every money comb in every pack, rendered at 600 dpi) is the comment block next to the format in
  `schemas/formpack.py`.

## A blank inside a booklet (`source_pages`)

Some agencies publish the print-only return only inside a booklet or packet (NM's 2025 PIT-1 is pages
57-58 of the 136-page PIT packet; WV's 2025 IT-140 is pages 3-4 of its forms-and-instructions booklet).
The manifest then pins the booklet (`source_url`, `pdf_sha256`) and names the form's pages in
`source_pages`; `fill_form` stamps and writes ONLY those pages, in that order, so every overlay `page`
counts within them (1 = the first listed page), `verify_form` reads that output, and the worksheet tells
the filer which pages to print. A listed page beyond the booklet's count is refused — the agency
re-paginated, so re-read the booklet and fix `source_pages` (and the digest if the file changed).

## A scanned form's own filing tips (`money_style`, `blank_zero_computes`)

Some print-only forms tell the filer how the scanner wants the digits. WV's IT-140 booklet (Tips on
Filing a Paper Return) says **"NEVER USE COMMAS when filling in dollar amounts"** and **"Lines where no
entry is required should be left blank. Do not fill in with zeros."** The engine's defaults (comma-grouped
money, a `compute` that prints `0` when every input is blank) break both, so a manifest declares the
form's own style:

- `money_style: plain` prints money as digits only (`98500`, `-8300`) on the worksheet and the stamp;
  the default `grouped` prints `98,500`. Digit `cells` drop the separators under either style.
- `blank_zero_computes: true` leaves a computed money line **blank** when every line its `compute`
  resolved is blank (a `sum(21a..21c)` range counts each member) and the result is `0`; the blank line is
  blank for the computes after it too. The compute is still evaluated (a malformed one raises on the empty
  build as before), an entered `0` still prints, a compute with any non-blank operand prints its result
  (`0` included), and so does a non-zero result from a literal term — the IRS-style default (`false`)
  prints `0` as before.

The worksheet's instructions say which of the two the pack set, so nobody "corrects" the output by hand
(P-029). Quote the form's own tip in the manifest banner and in `printing_guidance`.
