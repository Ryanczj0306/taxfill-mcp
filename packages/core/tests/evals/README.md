# Evals — end-to-end synthetic scenarios

`test_scenarios.py` runs synthetic taxpayers (no real PII, ever) through the whole engine — intake, residency,
estimate, fill, verify, summary, file & pay — and asserts the behaviours the design spec calls out per scenario
([DEV_PLAN §14](../../../../docs/dev/DEV_PLAN.md)). Each scenario is a lettered group of tests; the module docstring
lists them: F-1 back-filing, a simple W-2 return with a state, part-year and nonresident state cases, joint vs
separate filing, families with children, dual-status years, planning-year projections that must refuse to look like
a filing, and more.

The rules every scenario enforces: early estimates bracket the final number and always carry their assumptions;
no value is invented; a law change the shipped data does not cover is resolved from a cited `.gov` source, never
from memory.

They run with the core suite (`uv run pytest packages/core/tests`), or alone:

```bash
uv run pytest packages/core/tests/evals -m "not network"
```

`test_unmapped_ready_to_file.py` (scenario v, Phase K JK18) asks "is this ready to file?" of a form with no pack: every
skill file must answer no (an unmapped draft is never filing-grade) and carry the no-pack rules, and no tool response
for an unmapped draft — a passing verify included — may claim filing-grade. The journeys' done guard
(`packages/mcp-server/tests/test_journeys.py`) holds the order: no "done" before verify_form ok on that output's sha256.

Multi-form fill + verify on the real IRS PDFs is covered by `packages/core/tests/test_filing_integration.py`.
