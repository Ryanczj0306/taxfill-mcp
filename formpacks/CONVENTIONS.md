# Form pack conventions (binding)

These rules are **binding** for every pack under `formpacks/`. They are
machine-enforced by the data-driven harness
`packages/core/tests/test_formpacks_federal.py`, which auto-discovers every
`formpacks/federal/<tax_year>/<form_key>/pack.yaml` — a pack that violates
this document fails CI. The pack schema itself lives in
`packages/core/src/taxfill_core/schemas/formpack.py` (dev plan section 5).

## Directory layout

```
formpacks/federal/<tax_year>/<form_key>/pack.yaml
```

- `<tax_year>` is the 4-digit filing year and MUST equal the pack's
  `tax_year` field.
- `<form_key>` MUST be one of:

  `f8843`, `f1040nr`, `f1040`, `sched_1`, `sched_2`, `sched_3`,
  `sched_a`, `sched_b`, `sched_c`, `sched_oi`

  These keys are also the only valid cross-form reference targets (below).

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
- Checkbox lines that share one `field` MUST share one `group` (harness
  enforced — the synthetic-fill harness selects exactly one option per
  group/field).
- Find the real `on_state` values by dumping the blank PDF's field
  appearance states — never guess them.

## Cross-form references (`cross_form`)

```
<ref> == <ref>
ref   := <line>                # a line of THIS pack (no dot)
       | <form_key>.<line>     # a line of another form in the filing
```

- `form_key` MUST be one of the directory form keys above
  (e.g. `8 == sched_1.10`, `1k == sched_oi.1e`).
- Refs are split at the FIRST dot, so only undotted (printed-label) lines
  of other forms can be referenced — which is all that cross-form math
  ever needs.
- Undotted refs must exist in this pack's `fields[]`.

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

The harness parametrizes over every discovered pack — adding a directory is
enough, no test edits needed.

Offline structural checks (schema, sha256 not placeholder, line-id grammar,
relations parse, cross-form targets):

```
cd /Users/ryan/Desktop/tax_tool/taxfill-mcp && uv run --no-sync pytest packages/core/tests/test_formpacks_federal.py -q -m "not network" -k "<tax_year>-<form_key>"
```

Golden round-trip (downloads the blank, fills every mapped line with
synthetic data, verifies, renders page 1 — needs network or a warm cache;
drop the `-m` filter):

```
cd /Users/ryan/Desktop/tax_tool/taxfill-mcp && uv run --no-sync pytest packages/core/tests/test_formpacks_federal.py -q -k "<tax_year>-<form_key>"
```

Omit `-k` to validate all packs. Synthetic data only: SSN-style values look
like `999-88-7777` / `000-00-0000` — obviously fake, never real PII.
