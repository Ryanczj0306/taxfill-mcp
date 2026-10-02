# Maintainer scripts

Run them from the repo root with `uv run python scripts/<name>.py`. None is needed to *use* taxfill.

| Script | What it does |
|---|---|
| `sync_test_count.py` | Keeps the test count quoted in the README badge and the roadmap equal to `pytest --collect-only` (`--write` / `--check`; CI runs `--check`) |
| `sync_doc_counts.py` | Same for every other quoted number (tools, calc ops, document kinds, packs), and generates the tables in `docs/COVERAGE.md` |
| `sync_bundle_manifest.py` | Keeps the `.mcpb` bundle manifest's calc entry equal to the running server (a test checks the tool names) |
| `check_drift.py` | Freshness check: re-fetches the official sources, blanks and addresses (the weekly freshness workflow) |
| `freshness_quarantine.py` + `.yaml` | Known freshness reds behind an expiring allowlist, so only a NEW red fails |
| `check_finals.py` | Watches for the IRS final revision of each form a draft pack mirrors |
| `scaffold_state_year.py` | Starts a state form-pack year: derives and probes candidate blank-PDF URLs, triages each form against its base year |
| `state_discovery_rows.json` | The verified blank-URL discoveries `scaffold_state_year.py --rows` consumes |
| `introspect_pdf.py` | Dumps a blank AcroForm's widgets, for authoring a new pack |
| `audit_pack.py` | Field-map audit harness for one pack |
| `stage_data.py` | Copies `knowledge/` and `formpacks/` into the core package before a build (release step) |
| `assemble_state_sources.py` | Regenerates `knowledge/sources_states.yaml` from the state knowledge packs' own citations; re-run it after changing a state pack's citations (`--check` runs in the test suite) |
| `assemble_state_knowledge.py`, `assemble_state_tax_blocks.py`, `assemble_state_credits.py` | Build state knowledge packs, their `tax:` blocks and their credits from a cited research fetch (JSON) given on the command line — how the state knowledge was first assembled |
| `assemble_ca540.py`, `assemble_ca540nr.py` | One-time generators of the 2023 CA Form 540 / 540NR packs from a vision-mapping file that is not in the repo; kept as the record of how those packs were made |
