# Contributing to taxfill-mcp

Thanks for your interest in contributing! taxfill-mcp is an open-source (MIT) execution
layer for AI tax prep: guided intake, deterministic form filling, mandatory verification,
and file-and-pay instructions, consumable by any MCP client.

**Project status:** v0.1 is in development. The design spec is complete
([docs/DEV_PLAN.md](docs/DEV_PLAN.md)), nothing is published to PyPI yet, and the
install/usage flows described in the docs are the *planned* v0.1 experience.

A few ground rules up front:

- **Repo language is English only** — code, docs, comments, examples, commit messages.
  (Community translations of user-facing docs, like `README.zh.md`, are welcome.)
- **This project is not tax advice and not a tax preparer.** It produces a review
  draft; the human reviews, signs, and files on paper. There is no e-filing, by design.
  Contributions must never weaken this framing.
- **Privacy is a feature:** 100% local, no telemetry, the only outbound traffic is
  downloading blank forms from official .gov URLs.
- Be kind. Reviews focus on correctness and data quality, not on people.

## Ways to contribute (ordered by leverage)

1. **Form packs** — new forms or new tax years (`formpacks/`). Each pack is pure data;
   the engine is form- and jurisdiction-agnostic, so a new pack extends coverage with
   zero engine changes. Highest-impact contribution.
2. **State knowledge packs** — thresholds, residency rules, credits, treaty
   conformity, payment portals, mailing addresses for a state
   (`knowledge/states/<st>/<year>.yaml` plus its `sources.yaml` block).
3. **Pitfall reports from real filings** — a bug or near-miss you hit while actually
   filing is gold. Report it (redact all PII); it becomes a permanent verifier rule,
   a regression test, and often an intake-question fix.
4. **Eval scenarios** — synthetic taxpayer scenarios with expected line values
   (`evals/`). These keep agents honest across releases.
5. **Docs and translations** — README improvements, troubleshooting entries,
   community translations of user-facing docs.

## Authoring a form pack

Form packs live at `formpacks/<jurisdiction>/<year>/<form>/pack.yaml`. Federal and
state forms use the **same schema** — see [docs/DEV_PLAN.md §5](docs/DEV_PLAN.md) for
the authoritative spec. Annotated example:

```yaml
form: 1040-NR
jurisdiction: federal            # or: states/ca
tax_year: 2022
source_url: https://www.irs.gov/pub/irs-prior/f1040nr--2022.pdf
pdf_sha256: "..."                # checksum of the official blank PDF
acroform_root: "topmostSubform[0]"   # varies per form (Sched OI: form1040-NR[0])
fields:
  - line: "identifying_number"   # logical line name agents fill against
    field: "Page1[0].f1_7[0]"    # AcroForm field path under acroform_root
    type: text
    maxlen: 9
    comb: true                   # comb cells take digits only
    format: ssn_digits_only      # dashes overflow comb cells (pitfall P-001)
  - line: "filing_status.single"
    field: "Page1[0].c1_1[0]"
    type: checkbox
    on_state: "/1"               # the widget's actual "on" export value
  - line: "1a"
    field: "Page1[0].f1_28[0]"
    type: money
relations:                       # math enforced by the verifier
  - "1z == sum(1a..1h)"
  - "11 == 9 - 10"
cross_form:                      # consistency across forms in one filing
  - "1k == sched_oi.L1e"
  - "8 == sched_1.10"
identity_fields: [name, identifying_number, mailing_address]  # must match across the filing
signature: { page: 2, standalone_only: false }  # e.g. 8843: sign only when filed alone
mailing:
  no_payment: "Department of the Treasury, IRS, Austin, TX 73301-0215"
  with_payment: "IRS, P.O. Box 1303, Charlotte, NC 28201-1303"
  verify_url: "https://www.irs.gov/filing/..."
```

Pack-authoring checklist:

- **`source_url` + `pdf_sha256` are mandatory.** `source_url` must point to the
  official government URL (irs.gov, state DOR/FTB) for that exact form revision —
  use `irs.gov/pub/irs-prior/` for prior years. `pdf_sha256` is the checksum of
  that blank PDF.
- **Never commit blank PDFs.** Official PDFs are downloaded at runtime from their
  `source_url` and checksum-verified against `pdf_sha256` — they are never vendored
  in the repo. PRs containing form PDFs will be rejected.
- **Map every line you support** to its AcroForm field, with `type`
  (`text` / `checkbox` / `money`), and `maxlen` / `comb` / `format` where the form
  uses comb cells or constrained boxes. Checkboxes need the real `on_state` export
  value (set `/V` and widget `/AS`).
- **Encode the form's math as `relations`** and its links to other forms as
  `cross_form` — these are what the verifier enforces, so the more you encode,
  the safer every filing gets.
- **Declare `identity_fields`**, the **`signature`** location (and whether the form
  is signed only when filed standalone), and the **`mailing`** block with both
  with-payment and no-payment addresses plus an official `verify_url`.
- Add a golden-file test with a **synthetic** taxpayer (see Testing below).

## Knowledge packs and sources

Jurisdiction knowledge ships as data in `knowledge/`. Rules from
[docs/DEV_PLAN.md §7](docs/DEV_PLAN.md):

- **No topic without a source.** Every topic in a knowledge pack — and anything a
  position decision can rely on — must be backed by an entry in
  `knowledge/sources.yaml` with `url` (official .gov source), `answers` (what
  questions it resolves), and `cadence` (when it updates). State blocks ship
  together with each state's knowledge pack.
- **Never hardcode numbers that lack final IRS guidance.** When a law is enacted but
  the IRS has not published final caps/phase-outs/form lines, the pack stores the
  *lookup path* (which source answers it), not a guessed number. Agents resolve it
  at runtime via the freshness protocol.
- **`effective_law_changes` lifecycle.** Enacted-law deltas relevant to a filing
  year live in `knowledge/<jurisdiction>/<year>.yaml`, each with a citation and a
  status that moves through `enacted` → `irs_guidance_pending` →
  `final_form_published`. Update the status (and only then any hardcoded numbers)
  as official guidance lands.
- Blogs and forum posts are never authority — at most a lead to a .gov citation.

## The pitfall rule (every bug fix)

Per [docs/DEV_PLAN.md §10](docs/DEV_PLAN.md), every bug found in real use compounds
into permanent protection. **Every bug-fix PR must include:**

1. An entry in `knowledge/pitfalls.yaml` (id, incident description with PII redacted,
   permanent countermeasure);
2. A **regression test** covering it — CI will fail if a pitfall lacks a test
   (the coverage gate lands with the eval harness, M6);
3. Where applicable, an **intake-question fix** (if the bug traces back to a question
   users predictably answer wrong, fix the question's built-in disambiguation too).

This is enforced via the PR template today, and via CI once the coverage gate
lands — not on the honor system.

## Development setup

The packages are not on PyPI yet, but local development works today:

```bash
git clone https://github.com/Ryanczj0306/taxfill-mcp
cd taxfill-mcp
uv sync          # install dependencies
uv run pytest    # run the test suite
```

Repo layout, architecture, and milestones are documented in
[docs/DEV_PLAN.md](docs/DEV_PLAN.md) — read it before making non-trivial changes;
it is the single source of truth for the design.

## Testing

- Golden-file tests compare field dumps of filled forms against golden YAML.
- Render snapshot tests catch visual regressions (clipping, missing checkboxes).
- Pack schema validation runs in CI; a nightly drift job (planned — see
  [docs/DEV_PLAN.md §7](docs/DEV_PLAN.md)) will re-fetch official sources and
  flag checksum and mailing-address drift.
- Every pitfall in `knowledge/pitfalls.yaml` must have a regression test.

## PII rule (hard rule)

**Never commit real taxpayer data.** No real names, SSNs/ITINs, addresses, account
numbers, or document scans — anywhere, including tests, evals, fixtures, golden
files, issue reports, and screenshots. All test and eval data uses **synthetic
identities only**. If you are reporting a pitfall from a real filing, redact every
identifying detail first.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
