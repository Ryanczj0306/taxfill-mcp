## Summary

<!-- What does this PR change, and why? Link related issues. -->

## Checklist

- [ ] Tests pass locally (`uv run pytest`) and new behavior is covered by tests
- [ ] **No real taxpayer data anywhere** — tests, evals, fixtures, and examples use synthetic identities only
- [ ] All content is in English (code, comments, docs, examples)
- [ ] **Bug fix?** Added an entry to `knowledge/pitfalls.yaml` **plus a regression test** (and an intake-question fix if the bug traces to an intake answer) — CI will fail if a pitfall lacks a test once the coverage gate lands (M6)
- [ ] **New knowledge topic or position-relevant rule?** Added a backing entry in `knowledge/sources.yaml` (official .gov `url`, `answers`, `cadence`) — no topic without a source
- [ ] **Form pack added/changed?** `source_url` points to the official .gov PDF and `pdf_sha256` matches it; **no blank PDFs committed** (they are fetched at runtime and checksum-verified)
- [ ] No numbers hardcoded that lack final IRS guidance (store the lookup path; track via `effective_law_changes` status)
- [ ] Does not weaken the safety framing: no e-filing, not tax advice, output is a review draft the human reviews, signs, and files

## Notes for reviewers

<!-- Anything that needs extra scrutiny? Sources consulted? -->
