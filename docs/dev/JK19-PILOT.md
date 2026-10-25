# JK19 pilot: five long-tail forms through the no-pack fallback

- **Status:** pilot report for Phase K JK19 (docs/dev/ROADMAP.md, the "JK19 —" box), run 2026-10-25 on branch jk19
  (base main 634ccab). It is JK19's acceptance artifact and the "JK19 pilot report" that KG6 and JK12 name.
- **No form here is promoted to filing-grade.** Every draft below is an UNMAPPED DRAFT — NOT FILING-GRADE. Only a real
  pack makes a form filing-grade.
- **Binding documents:** [ADR-0002](adr/ADR-0002-fallback-surface.md) (accepted 2026-10-25), Recipe U in
  [skills/claude/SKILL.md](../../skills/claude/SKILL.md), and [docs/TOOLS.md](../TOOLS.md#forms-with-no-pack-formunmapped).
- **Reproduce:** `uv run python scripts/jk19_pilot.py --out <scratch dir outside the repo> --ma-local-blank <saved MA
  Form 1 2024>`. It needs network access. It runs each form through the MCP tools in-process (the SDK's in-memory
  client, as packages/mcp-server/tests/test_unmapped_tools.py does) and writes each form's `record.json`, field list,
  sweep PNGs and draft PNGs under `--out`. The renders and drafts hold demo values only, and they stay out of git.
  The values and box confirmations in the script's `PLAN` were chosen by looking at each rendered sweep page.
- **Demo data only (KG10):** fictitious names, 999-88-xxxx SSNs and "Example" addresses. Every computed line
  carries the "agent-computed, unverified" label.

## How each form was run

The agent's part and the user's part were played by the same reviewer. For each form, in Recipe U order:

1. Confirm no shipped pack: check `list_forms` and `formpacks/` for that jurisdiction and year.
2. `fetch_blank(form="unmapped", source_url, form_title)`.
3. `get_form_map`, then `render_form` on every sweep page. The reviewer looked at the numbered boxes and confirmed
   only the `low`/`med` fields whose number sat in the box that the field's printed line or caption names.
4. `fill_form` with demo values for the lines a filer of that form fills, then `verify_form` (with
   `declared_relations` where the form prints its arithmetic).
5. `render_form` on every page. The reviewer looked at every page and zoomed in (`render_pdf` crops) on combs,
   checkboxes and stamps.

The pilot used three runs: run 1 found the defects, run 2 re-ran after the first two fixes, and run 3 is the final
run after all three fixes. Every blank was downloaded once per run. Each one had the same sha256 in all three runs,
and runs 2 and 3 produced identical `written` maps. The timings below are run 3's tool time, from fetch to the last
render. The reviewer's time was spent mostly on reading the sweep and draft pages: about 5 to 15 minutes per form.

## Results at a glance

| Slot | Form | Host | Outcome | Fields (fillable) | Written / attempted | hand_write | verify | Wrong box |
|---|---|---|---|---|---|---|---|---|
| City return | Philadelphia School Income Tax return, TY2023 | phila.gov | stamped draft | 52 (43) | 14 / 14 | 0 | ok | 0 |
| Rare federal | Schedule H (Form 1040), TY2025 | irs.gov/pub/irs-pdf | stamped draft | 72 (53) | 19 / 20 | 1 (unanchored) | ok | 0 |
| CT NR/PY | CT-1040NR/PY, TY2025 | portal.ct.gov | worksheet only (flat blank) | 0 | 0 / 9 | 9 (worksheet) | n/a | n/a |
| TY2023 state | Oregon OR-40-N, TY2023 | oregon.gov | stamped draft | 203 (159) | 12 / 17 | 5 (custom format) | ok | 0 after fix (1 before: D1) |
| TY2025 non-tier-1 | Wisconsin 1NPR, TY2025 | revenue.wi.gov | stamped draft | 272 (240) | 17 / 20 | 3 (2 custom format, 1 unanchored) | ok | 0 |
| Refusal case | Massachusetts Form 1, TY2024 | mass.gov | refused at fetch (HTTP 403) with the local_blank pointer; the local_blank route then drafted | 163 (99) | 9 / 11 | 2 (custom format) | ok | 0 |
| (first city candidate) | Grand Rapids GR-1040PR, TY2025 | grandrapidsmi.gov | refused at fetch (rule 9: page 6 is a scanned image) | n/a | n/a | n/a | n/a | n/a |

Every written value landed in the box its printed line names, once D1 was fixed. Across the five drafts, 71 values
were written: 22 anchored at the top tier, 16 `med` and 33 `low`. Every `med` and `low` value was written only after
the reviewer confirmed it on the sweep page. The stamp printed on every page of every draft (23 pages), never over a
box. No draft read as final.

## Per-form results

### City return: Philadelphia School Income Tax (SIT) return, TY2023

- **URL:** https://www.phila.gov/media/20240102133536/2023-School-Income-Tax-return.pdf
- **sha256:** 95afef5a9a96679c83c58db90b50c3e88d8db7dc346209729fdcd5bf34f8e88e
- **Blank:** `acroform`, 1 page. First-page check: printed year 2023, title found.
- **Rule 1:** the Pennsylvania 2023 packs are PA-40 only, and Philadelphia's city taxes have no pack. The pilot used
  `jurisdiction="states/pa"` because the tools have no local jurisdiction (see Q6).
- **Fields:** 52, of which 43 are fillable. Refused: 6 `unanchored` (the day and year boxes of the residency and cease
  dates) and 3 `signature`. Tiers: 16 at the top tier (lines 1-15b, each on its printed line), 27 `low` (the identity
  boxes and checkboxes) and 9 `none`.
- **Filled:** 14 of 14 written: SSN, name, address, city, state and ZIP (all `low`, confirmed on the sweep), and lines
  1, 2, 9, 10, 11, 12 and 14 (top tier). Line 12 is the form's printed rate (.037500) times line 11, labeled
  agent-computed.
- **verify:** ok. Every section passed: record 7, round_trip 14, unchanged 53, clipping 14, flags 14, stamp 1,
  anchors 14, declared_relations 2 (`Line9 == Line1 + Line2`, `Line11 == Line9 - Line10`).
- **Render:** each value is in its box (SSN in the comb at top right, lines 1/2/9/10/11/12/14 in their right-column
  boxes). The stamp is at the top-left margin, clear of the title.
- **What confused the flow:**
  - The first fetch, with `form_title="SIT"` (the footer code), was refused. The refusal told the agent to "pass it as
    expected_title", a taxfill_core argument that fetch_blank does not take (D2, fixed). The printed name is "SCHOOL
    INCOME TAX", and that passed.
  - The checkbox labels are shifted one caption to the left (D3): "Amended Return?" is labelled "Address Change" and
    "Final Return?" is labelled "Amended Return".
- **Tool time:** 2.1 s.

### Rare federal: Schedule H (Form 1040), Household Employment Taxes, TY2025

- **URL:** https://www.irs.gov/pub/irs-pdf/f1040sh.pdf (the final revision, not irs-dft)
- **sha256:** d04de932bd7d960ba09b3a913cde9bf35c1deec34c5c9b51cdff8c0b1bfdf83a
- **Blank:** `acroform_xfa_hybrid`, 2 pages. Year 2025, title "SCHEDULE H" found. Rule 1: no federal Schedule H pack in
  any year.
- **Fields:** 72, of which 53 are fillable. Refused: 19 `unanchored`, among them the second box of each IRS Yes/No pair
  (A "No", B "No", C "Yes", 9 "Yes") and most of the line 17 table cells. Tiers: 18 top, 10 `med`, 25 `low`, 19 `none`.
- **Filled:** 20 values attempted, 19 written. The written values: name, SSN and EIN (comb), A "Yes", lines 1, 2, 3, 4
  and 8; lines 10, 11 and 12 "Yes", line 13 "Michigan", lines 14, 15, 16, 25 and 26, and line 27 "Yes". Line 9 "Yes"
  (`c1_4[0]`) came back in `hand_write` as `unanchored`, although every filer who reaches Part II must check it. The
  demo figures: line 2 = 30,000 x 12.4% = 3,720 and line 4 = 30,000 x 2.9% = 870 (the rates the form prints on those
  lines); line 15 = 7,000, the FUTA wage base the 2025 Instructions for Schedule H state ("include on line 15 only the
  first $7,000 of that employee's cash wages", i1040sh.pdf, fetched twice, sha256 3e4b07dd08673863...); line 16 =
  7,000 x 0.6% = 42.
- **verify:** ok. round_trip 19, unchanged 74, clipping 14, flags 19, stamp 2, anchors 19, and 3 declared relations
  (line 2 = line 1 x 0.124, line 8 = 2 + 4, line 26 = 16 + 25).
- **Render:** each value is in its box. A zoomed crop put lines 10-12's checks in the "Yes" column. The EIN filled
  its 9 comb cells. The stamp is at the top-left on both pages.
- **What confused the flow:** the sweep numbers on Part II's small checkboxes ("#20" to "#25") are barely legible at
  110 dpi; they needed a zoom. An unanchored box shows no number on the sweep, so the user cannot even confirm it.
- **Tool time:** 1.5 s.

### Connecticut nonresident/part-year: CT-1040NR/PY, TY2025

- **URL:** https://portal.ct.gov/-/media/drs/forms/2025/income/ct-1040nrpy_1225.pdf
- **sha256:** abddac561c4471ec08b0d27c537ced1a820716d7ea535d6a8a944b963b13846a
- **Blank:** `flat` (no widget), 4 pages. Year 2025 and title found (the "(Rev. 12/25)" mark did not trip the
  revision-date rule). Rule 1: the CT 2025 hand-fill pack is CT-1040, a different printed name.
- **Result:** rule 10 applied, so no PDF was written. `fill_form` returned `status: "worksheet_only"` with all 9 values
  in `hand_write`, keyed by the printed line as the reviewer read it, each labelled "agent-computed, unverified". The
  `money_fields` passed with the call had no effect on that path (D4, fixed: they now round to whole dollars there
  too).
- **What confused the flow:** nothing on the tool side. For a user this is the least helpful outcome: a list of lines
  to copy, with no map to the page.
- **Tool time:** 1.1 s.

### TY2023 state form: Oregon Form OR-40-N, TY2023

- **URL:** https://www.oregon.gov/dor/forms/FormsPubs/form-or-40-n_101-048_2023.pdf
- **sha256:** 3c8df6a2c139fbbda3377198618033991f05b51918240594b2b48a8915fb73fe
- **Blank:** `acroform`, 11 pages. Year 2023 and title found; the "(Rev. 03-21-24)" footer did not trip the rule.
  Rule 1: the Oregon 2023 pack is the resident OR-40 only.
- **Fields:** 203, of which 159 are fillable. Refused: 29 `custom_format_script`, 14 `unanchored` and 1 `pushbutton`
  ("Clear form"). Tiers: 44 top (lines 6a-6e and 36-76), 72 `med` (the F and S column pairs, read as "7f"/"7s" from the printed
  "7F."/"7S."), 72 `low` and 15 `none`.
- **Filled:** 17 attempted, 12 written: date of birth, SSN (a comb whose dash cells take the dashes), ZIP, filing
  status Single, 6a, 6e, 7F, 7S, 8F, 20F, 20S and 57. Five went to `hand_write` as `custom_format_script`: first name,
  last name, address, city and state. Each of those boxes carries `event.value = event.value.toUpperCase();` (see Q2).
  The last-name box has a widget in every page header (11 pages), so the filer hand-writes the name 12 times.
- **verify:** ok. round_trip 12, unchanged 214, clipping 21, flags 22, stamp 11, anchors 22, and 1 declared relation.
- **Render, before the fix: one value in the wrong cells (D1).** The dollar boxes are right-aligned 11-cell combs that
  print a comma in every 4th cell from the right, and the form's own format, `AFNumber_Format(0, 0, ...)`, groups
  thousands. "48000" was written as bare digits, so its "8" sat on the printed comma ("4 8 000", zoomed at 250 dpi).
  verify passed it: no section looks at comb cells. The pack path had already met this on the OR-40
  (`format: money_comma_cells`, JK28).
- **Render, after the fix:** 7F reads "48,000", 7S "12,000", 20F "48,150" and 20S "12,000", with each digit in its
  printed cell. 8F's "150" and line 57's "540" are right-aligned in the last group. The SSN, DOB and ZIP combs are
  cell-exact, the SSN mirror shows in every page header, and the stamp is at the top-left on all 11 pages. The blank's
  own blue "Clear form" pushbutton shows at the top-right, on the blank's own render too, and the stamp is clear of it.
- **Tool time:** 3.2 s.

### TY2025 state form outside tier 1: Wisconsin Form 1NPR, TY2025

- **URL:** https://www.revenue.wi.gov/TaxForms2025/2025-Form1NPRf.pdf (Wisconsin ranks 16th in
  scripts/tier1_states.yaml, below the cut of 12)
- **sha256:** 8da43c44c083ecaeeab7ff426218fb45df1aac191cf945b3753072ae02c0a113
- **Blank:** `acroform`, 5 pages. Year 2025, title "1NPR" found. Rule 1: the WI 2025 pack is Form 1 only.
- **Fields:** 272, of which 240 are fillable. Refused: 21 `read_only`, 4 `calculated`, 3 `pushbutton`, 2
  `custom_format_script` and 2 `unanchored`. Tiers: 44 top, 93 `med` (the Federal and Wisconsin column pairs on one
  printed line), 122 `low` and 13 `none`.
- **Filled:** 20 attempted, 17 written: name, the SSN in three boxes, address, city, ZIP, filing status Single (the
  on-state "/single" of a 5-widget checkbox), lines 1-2 in both columns, 16 in both columns, 30 and 31. In `hand_write`:
  State (`custom_format_script`, uppercase), the state of residence (the same), and the Resident status box
  (`resident1`, `unanchored`). A 1NPR filer must mark one of those, so a nonresident's draft leaves it to be written
  by hand.
- **verify:** ok. round_trip 17, unchanged 277, clipping 16, flags 21, stamp 5, anchors 21, and 3 declared relations.
- **Render:** each value is in its box: A column under "A. Federal column", B under "B. Wisconsin column", and the
  checkmark on "Single". The page 2 header name and SSN are `read_only` boxes filled by the form's script, so they stay
  blank, as the LIMITS say. The page-1 stamp moved to the top centre, between the blank's yellow help box and its
  Save/Print/Clear buttons; on pages 2-5 it sits at the top-left.
- **Tool time:** 5.1 s.

## The refusal case: Massachusetts Form 1, TY2024

- **What the ROADMAP expected:** mass.gov answers 403, so the fallback should refuse with a pointer, or take a blank
  the user supplies. The brief expected rule 1 to fire first if a shipped MA pack covered the form.
- **Rule 1 did not fire.** The shipped MA packs are 2023 and 2025 (formpacks/states/ma/); there is no 2024 pack.
- **The fetch:** `fetch_blank(form="unmapped", year=2024, jurisdiction="states/ma",
  source_url="https://www.mass.gov/doc/2024-form-1-massachusetts-resident-income-tax-return/download",
  form_title="Form 1")` was refused under rule 4 in 0.3 s. The refusal names the next step: "the official host answered
  HTTP 403 ... it refuses non-browser downloads. A pack falls back to a Wayback snapshot verified against its pinned
  sha256; a form with no pack has no digest, so no mirror is used. Open the URL in a browser, save the PDF, and pass
  the saved file as local_blank together with this source_url. Nothing was stored and no PDF was written. The form's
  official source: <the URL>." It held no value and no local path.
- **The local_blank route.** The reviewer opens no browser in a pilot (no host apps), so a stand-in played the user's
  browser save: the Wayback raw capture (`id_`) of that exact mass.gov URL, captured 2025-09-13, downloaded twice, with
  the same sha256 each time (dbc084ac0bed161e969b282020ee5435dd6e89b0c20df2f0d1d1e350f2597cf3). The tools cannot tell
  how a local file was saved. That these are the bytes mass.gov serves today is not shown.
  - **Fetch:** `origin: "local_blank"`, `acroform`, 4 pages, year 2024, title found; stored under the year's workspace
    (`<workspace>/2024/unmapped_blanks/`), so `taxfill purge 2024` removes it.
  - **Map:** 163 fields, 99 of them fillable. Refused: 63 `custom_format_script` and 1 `unanchored`. 63 of MA's dollar
    boxes carry `event.value = event.value.toString().replace("-", "")` (a loss is marked in a separate box), so nearly
    every amount on Form 1 is hand-write (see Q2).
  - **Fill:** 11 attempted, 9 written: name, SSN, address, city, state, ZIP, filing status Single (radio), and line 18
    (4,400 right-aligned in the dollar cells before the printed "00"). Lines 2a and 3 went to `hand_write` as
    `custom_format_script`. verify was ok.
  - **Render:** each value is in its box. Lines 12, 13 and 45 print the blank's own zero defaults ("Reserved for future
    use"); the draft did not write them. The page-1 stamp sits right of the red title "Massachusetts Resident Income Tax
    Return", in a similar red, inside the form's scan-registration frame. It does not overprint anything, but it
    reads close to the title (see Q1). Pages 2-4 carry it beside the top barcode.
- **Verdict:** the refusal is correct and names the next step. The local_blank route works end to end.

## The first city candidate, refused: Grand Rapids GR-1040PR, TY2025

- **URL:** https://www.grandrapidsmi.gov/media/zrqn423z/2025-part-year-fillable-form-revised.pdf (6 pages, 285
  widgets).
- **The refusal (rule 9):** "page 6 ... draws content but has no text layer (a scanned image, drawn art, or only an
  invisible OCR layer) ... look on the agency's forms page for a fillable or text version, or fill the printed form by
  hand. Nothing was stored and no PDF was written."
- **Page 6:** a scanned mailing-address and "please remember to" page with no widget. All 285 widgets sit on pages
  1-5, whose text layers are intact.
- **The other Grand Rapids forms** (resident and nonresident, "printable") are flat. Columbus's IR-25 (columbus.gov)
  answered 403 to a script, and the St. Louis E-1 carries no tax year. Philadelphia's return was the first city form
  that passed.

## What worked

- **Refusals.** Every refusal said that nothing was written and named a next step: rules 4, 7, 9 and 10 in this pilot.
  None echoed a value or a home path.
- **Labels, grade and stamp.** The grade, the LIMITS and the "agent-computed, unverified" label were on every
  response. The stamp printed on all 23 draft pages (and the sweep pages) and never covered a box. verify's stamp
  section checked each page.
- **Anchoring.** Top-tier anchors were right every time they were written (22 of 22). Its printed-line reading
  handled F/S and A/B column pairs, "15a"/"15b", and a two-widget line 18.
- **The sweep page.** It made the KG11 confirmation quick and reliable: the numbered boxes showed which box each `low`
  or `med` field is. The 49 confirmed values all landed in the box the sweep showed.
- **Combs.** The SSN, date, ZIP and EIN combs filled cell-exact. Oregon's dash cells took the dashes as given.
- **The local_blank route.** It handled a host that refuses scripts and kept the blank in the purgeable workspace.
- **Speed.** Tool time was 1-6 s per form. The work was the human review of the pages.

## What did not work

- **Many boxes that filers need come back as hand-write.**
  - MA Form 1: 63 dollar boxes (a minus-strip script).
  - OR-40-N: 29 identity boxes: names, initials, address, country and the dependents' codes (an uppercase script).
  - WI 1NPR: the resident-status box (unanchored).
  - Schedule H: the line 9 "Yes" box (unanchored).
  - Flat forms (CT-1040NR/PY): everything.

  The draft then carries the easy boxes, and the user must still hand-write the hard ones.
- **Checkbox anchoring is the weak spot.**
  - Labels shift by one caption (D3).
  - The second box of a stacked Yes/No pair is often unanchored (D5).
  - Several left-column checkboxes on OR-40-N are unanchored.
- **verify does not look at comb cells.** It passed D1's misplaced digit. The fix removes that case from the fill,
  but verify still cannot see one.

## Defects

| ID | Defect | Evidence | Status |
|---|---|---|---|
| D1 | A money amount in a right-aligned comb whose own format groups thousands (`AFNumber_Format(0, 0, ...)`) was written as bare digits, so a digit sat on a printed comma cell: OR-40-N 7F "48000" read "4 8 000". verify passed it. | Run 1 render, page 3 (zoom); the OR-40 pack had already needed `money_comma_cells` (JK28). | **Fixed** (wip 4ba5689). `money_fields` on such a comb are written comma-grouped (`money_comma_cells_text`). A bare digit string of 4 or more digits there, outside `money_fields`, is refused with what to do next. The LIMITS wording names the exception. Tests: `test_jk19_a_money_value_in_a_comma_cell_comb_is_written_comma_grouped` and `test_jk19_bare_digits_for_a_comma_cell_comb_outside_money_fields_are_refused` (packages/core/tests/test_unmapped_fill.py); both failed before the fix ("{'wages': '48000'} != {'wages': '48,000'}"; "DID NOT RAISE"). |
| D2 | fetch_blank's title refusal said "pass it as expected_title", the taxfill_core argument; the MCP parameter is `form_title`. | Philadelphia, first fetch with "SIT". | **Fixed** (wip af54d03). The server's refusal text names `form_title`. Test: `test_a_title_refusal_names_the_mcp_parameter_form_title` (packages/mcp-server/tests/test_unmapped_tools.py), which failed before the fix. |
| D3 | A checkbox's `label` is often the caption to its left, which is the previous option's caption, where captions sit to the right of their boxes. get_form_map, `hand_write` and the worksheet show it, and Recipe U step 3 tells the agent to name a hand-write box by its label. So an agent that relays a refused checkbox, or picks boxes by label instead of the sweep, names the wrong box. | Philadelphia: "Amended Return?" labelled "Address Change", "Final Return?" labelled "Amended Return". OR-40-N: filing-status Check Box4 (married filing jointly) labelled "Single", Check Box6 labelled "1". MA: `Checktp1.0.1` labelled "Taxpayer" for the spouse oval. | **Open.** No value was written into a wrong box: `low`/`med` need the sweep confirmation, and the sweep shows the truth. The fix changes anchoring, which KG6 benchmarks (method jk15-v4, knowledge/anchor/benchmark.yaml), so it belongs in a JK15 re-run, not this pilot. See Q5. |
| D4 | On a flat blank, `money_fields` had no effect: the worksheet showed a cents amount unrounded, with no warning, unlike the same call on a fillable blank. | CT-1040NR/PY call passed `money_fields`. | **Fixed** (wip 3844467). The worksheet rounds money lines to whole dollars and warns, and a non-number is refused. Test: `test_jk19_money_fields_on_a_flat_blank_get_whole_dollar_rendering_too`, which failed before the fix ("[52000.6, '75'] != ['52001', '75']"). |
| D5 | The second box of an IRS stacked Yes/No pair is anchored `none`, so it can be neither confirmed nor written. Schedule H line 9 "Yes" is one of them, and every filer who reaches Part II must check it. | Schedule H fields c1_1[1], c1_2[1], c1_3[1] and c1_4[0] (`unanchored`); they show no number on the sweep. | **Open** (anchor recall; also a JK15 matter). It is a coverage gap, not a wrong box: the value comes back in `hand_write`. |

No value landed in a wrong box after D1's fix. No draft was missing its stamp. No draft could pass for final: every
page carries the stamp, and every response carries the grade, the LIMITS and the label. ADR-0002's review trigger ("a
draft read as final despite the grade, the stamp and the LIMITS") did not fire.

## Questions for the user (stamp and label policy; nothing here is applied)

- **Q1. The stamp's size and place.**
  - What the pilot saw: the stamp is a single 10 pt red line at the top margin. It was legible on every page, but
    small.
  - On MA Form 1 page 1 it sits beside the red form title, in a similar red, inside the scan-registration frame. On WI
    1NPR page 1 it sits between the form's own coloured buttons.
  - A printed draft could lose it to a trim, or a reader could take it for part of the header.
  - Should the stamp grow (a larger size, or a second line at the foot of each page), or should it stay as ADR-0002
    wrote it? The pilot found no draft that read as final, so the ADR's trigger did not fire.
- **Q2. Format scripts that cannot change the value.**
  - What the pilot saw: three scripts drove most of the hand-write list.
    - MA Form 1's 63 dollar boxes: `event.value = event.value.toString().replace("-", "")`.
    - OR-40-N's 29 identity boxes (names, initials, address, country, the dependents' codes): `event.value = event.value.toUpperCase();`.
    - WI 1NPR's state boxes: the same uppercase script.
  - These scripts are refused as `custom_format_script` under KG7 as amended (Open question 1).
  - Should the fallback write a value into such a box when the script provably leaves that value unchanged (an
    uppercase-only value under the uppercase script, a value with no "-" under the minus-strip script)? This would
    move most of MA Form 1's amounts and OR-40-N's identity boxes out of hand-write.
- **Q3. A scanned page with no widget.**
  - What the pilot saw: GR-1040PR was refused (rule 9) for page 6, a scanned mailing page with no widget. All 285
    widgets are on pages 1-5, which have text.
  - Open question 14 (decided: partly scanned blanks stay refused) covers this form. Should a scanned page that
    carries no widget stop counting?
- **Q4. A text box that is a signature line.**
  - What the pilot saw: MA Form 1's "YOUR SIGNATURE" (`Signature`) and spouse's signature (`Spsignature`) boxes are
    text fields (/Tx), not /Sig, so they are fillable (`low`). KG7 refuses only /FT /Sig. An agent could type a name onto the
    signature line.
  - Should a text field whose caption or name says "signature" be refused like a signature widget?
- **Q5. Checkbox labels (D3).** Until a JK15 re-run reads the caption to the right of a box, which should happen?
  - get_form_map withholds `label` for checkboxes and radios (keeping `printed_line` and the sweep index).
  - Recipe U tells the agent to name a hand-write checkbox by its field name and sweep number rather than its label.
  - The label stays as it is.
- **Q6. A local jurisdiction.** The tools take `federal` or `states/<xx>`, so the pilot filed the Philadelphia return
  under `states/pa` and tried Grand Rapids under `states/mi`. Rule 1 then compares the form with that state's packs,
  and a manifest would place the city return under the state. Should the fallback gain a `local/<xx>/<place>`
  jurisdiction?

## Open items

- **D3 and D5:** checkbox labels and paired-checkbox recall, for a JK15 anchoring re-run, with the re-benchmark that
  KG6 needs.
- **A refused checkbox in `hand_write`:** an unanchored checkbox comes back with `printed_line` and `label` null and
  its raw on-state as the value (Schedule H line 9 "Yes": `{field: ...c1_4[0], value: '/2', reason: 'unanchored'}`),
  so the user cannot tell which box to mark from the entry alone. It should say "mark this box" and give its page and
  position (or a sweep marker); part of D5's fix.
- **D1's guard after the review:** a value for a comma-cell comb outside `money_fields` is now refused when it holds
  four or more digits in a row ("48000", "48000.00", "$48000"); before the review only a bare digit string was.
- **verify and comb cells:** verify has no check that a written comb value matches its printed cell grid; that is how
  D1 passed. The fill now refuses or formats the one case found, but a verify section for it is not built.
- **Sweep legibility:** the sweep's "#nn" tags on small checkboxes need a zoom at the default render size.
- **The MA local blank:** the bytes are a Wayback raw capture standing in for a browser save; that mass.gov serves the
  same bytes today was not checked.
- **JK12's KG6 gate:** this report's path (docs/dev/JK19-PILOT.md) is the file the v0.2 release check should test for.
