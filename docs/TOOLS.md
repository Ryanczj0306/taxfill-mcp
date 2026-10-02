# Tool reference

All 23 tools are available today (from source); the server registers exactly 23 (CI-asserted).

A typical session calls them in this order: `intake_checklist` → read and confirm each document
(`list_document_kinds`, `extract_document`) → `estimate_refund` → `residency` / `state_scope` → `list_forms` /
`get_form_map` → `fetch_blank` → `fill_form` → `verify_form` / `verify_filing` (loop until clean) → `render_form`
(vision-review every page) → `filing_summary` (the user approves the bottom line) → `file_and_pay`. The agent skill
files in [`skills/`](../skills/) teach this flow, with copy-paste recipes per scenario.

## MCP tools

| Tool | Purpose |
|---|---|
| `intake_checklist` | Next interview questions + required documents |
| `list_document_kinds` | The supported tax-document types and their official box layouts — read this before `extract_document` |
| `extract_document` | Structure + validate your reading of a W-2/1099/1098/1042-S/etc. into provenance-tagged fields |
| `residency` | Federal NRA/RA/dual-status via the Substantial Presence Test, work shown |
| `state_scope` | Which states to file, in what role, with which forms and candidate benefits |
| `list_forms` / `get_form_map` | Discover form packs; line-to-field maps + math relations |
| `fetch_blank` | Download the official blank PDF, checksum-verify |
| `fill_form` | Deterministic fill; comb/format handling; rejects unknown lines |
| `verify_form` / `verify_filing` | Assertion diffs, relation math, clipping scan, checkbox audit, cross-form consistency |
| `render_form` | Page PNGs returned as MCP image content for agent vision review |
| `calc` | Deterministic tax math — 40 ops (`calc(op, args)`). Tax computation: `tax`, `tax_with_preferential_rates`, `standard_deduction`, `se_tax`, `additional_medicare_tax`, `niit`, `taxable_social_security`, `excess_ss`, `employee_fica`, `capital_loss_limitation`, `state_tax`; Credits and deductions: `child_tax_credit`, `eitc`, `dependent_care_credit`, `education_credits`, `ptc_annual`, `ptc_monthly`, `foreign_tax_credit_election`, `student_loan_interest_deduction`, `schedule_1a_deductions`, `charitable_deduction`, `hsa_deduction`, `treaty_benefit`, `claim_of_right_repayment`; Retirement and equity: `contribution_limits`, `elective_deferral_room`, `ira_contribution_eligibility`, `ira_pro_rata`, `ira_net_income_attributable`, `ira_recharacterization`, `roth_conversion`, `espp_disposition`; Planning and payments: `estimated_tax_safe_harbor`, `underpayment_penalty`, `withholding_projection`, `paystub_to_w2`, `annualize_ytd`, `marginal_dollar_savings`, `magi_ladder`, `foreign_asset_reporting` |
| `estimate_refund` | Early refund/owed range from a partial profile, with composition and assumption list — labeled ESTIMATE for a closed year and PROJECTION for a planning year (a provisional pack, today TY2026) |
| `compare_scenarios` | Two or more what-if scenarios diffed against the first, with an exact per-slot ledger and a sequential input walk that telescopes to the headline delta |
| `get_sources` | Ranked official .gov sources per topic (freshness protocol) |
| `filing_summary` | Plain-language bottom line per jurisdiction before printing |
| `file_and_pay` | Personalized pay/print/sign/assemble/mail checklist |
| `hand_fill_worksheet` | A line→value worksheet for the print-only state forms (CT, HI, NM, SC; WV for TY2025) and FinCEN Form 114, which have no fillable AcroForm |
| `workspace_save` / `workspace_load` | Persist and resume the intake profile in the local workspace (`~/taxfill-workspace/<year>/`) |
| `workspace_record_position` / `workspace_reconcile` | Record each decided position with its authority, then generate RECONCILIATION.md and CHECKLIST.md |

## Calling the tools from a shell (non-MCP agents)

An agent that can run a shell command but doesn't speak MCP (Codex CLI, a script,
CI) can reach the **same tools** through the bundled `taxfill` CLI. It dispatches
through the same FastMCP registry as the stdio server, so it always covers every
tool with no extra wiring:

```bash
uv run taxfill tools                  # discover: tool names + which args each takes
uv run taxfill tools --json           # machine-readable (name, description, inputSchema)

uv run taxfill call list_forms '{"jurisdiction": "federal", "year": 2023}'
echo '{"path": "w2.png", "kind": "W-2", "fields": {}}' | uv run taxfill call extract_document --stdin
uv run taxfill call render_form '{"pdf_path": "filled.pdf", "pages": [1], "dpi": 150}' --out-dir ./pages
```

From a source checkout the CLI runs through `uv run` — inside the checkout, or from anywhere with
`uv run --project /ABSOLUTE/PATH/TO/taxfill-mcp taxfill …`. Once taxfill is installed from PyPI, `taxfill` is on
your `PATH` and the `uv run` prefix goes away.

`call` prints the tool's structured result as JSON on stdout; `render_form`'s page
images are written to files (their paths returned under `"images"`). A tool that
raises exits non-zero with a JSON error on stderr — so shell agents can branch on
the exit code.

## When a state website refuses the download

If a state host refuses every non-browser fetcher (HTTP 403), `fetch_blank` first tries the
pack's `mirror_urls` — an exact Wayback snapshot of the official URL, used only when its
bytes hash to the pinned digest. Failing that, save the PDF from a browser and seed it:
`uv run taxfill seed-blank saved.pdf --pack formpacks/states/ma/2023/form1/pack.yaml` (or
`--url <source_url> --sha256 <pdf_sha256>`). The file is digest-checked before it is cached.
