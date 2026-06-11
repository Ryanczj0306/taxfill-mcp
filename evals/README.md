# Evals

This directory will hold the eval harness: **synthetic taxpayer scenarios**
(no real PII, ever) with expected line values, used to prove the whole
pipeline — intake, residency, fill, verify, summary — produces correct,
verifiable drafts.

Planned v1 scenarios (see [`docs/DEV_PLAN.md`](../docs/DEV_PLAN.md),
section 14): F-1 back-filing with treaty + 1099-NEC; simple W-2 federal + CA
resident; part-year CA nonresident with remote work; refund with direct
deposit; balance due paid online vs by check; no-income-tax state
("nothing to file"); F-1 to H-1B mid-year transition claiming a
student-article treaty benefit; moved-after-tax-year address handling; a
post-2025 law change that the agent must resolve via `get_sources` with a
.gov citation — hallucinated numbers fail the eval; and estimate accuracy &
honesty: the early W-2-only estimate must bracket the final computed refund,
tighten as intake completes, and never be presented without its assumption
list or as a fake-exact point value.

Every pitfall in `knowledge/pitfalls.yaml` must have a corresponding
regression test; CI will fail if one lacks it (the gate lands with the eval
harness in M6).

**Status: empty by design.** The eval harness and all scenarios are delivered
in **milestone M6**.
