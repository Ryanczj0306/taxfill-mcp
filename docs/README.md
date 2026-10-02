# Documentation

New here? Start with the [project README](../README.md), then the user guide.

## Using taxfill

| Page | What's in it |
|---|---|
| [User guide](USER_GUIDE.md) | Install and connect, how a session works, what to prepare, a sample first return, privacy, troubleshooting, FAQ |
| [Intake worksheet](INTAKE_WORKSHEET.md) · [中文版](INTAKE_WORKSHEET.zh-CN.md) | Everything to gather before you start, as a fill-in checklist |
| [Coverage](COVERAGE.md) | Every supported form by tax year, federal and state — generated from the packs |
| [Tool reference](TOOLS.md) | The MCP tools and calc ops, and the `taxfill` shell CLI for agents without MCP |
| [Agent skills](../skills/) | The workflow instructions for Claude, Codex and Copilot |

## Contributing and maintaining

| Page | What's in it |
|---|---|
| [Contributing](../.github/CONTRIBUTING.md) | Ground rules, dev setup, the pitfall rule, testing, the PII rule |
| [Pack-authoring guide](dev/CONTRIBUTING-PACKS.md) | How a new form or tax year goes from blank PDF to audited pack |
| [Form-pack conventions](../formpacks/CONVENTIONS.md) | The binding rules every `pack.yaml` follows, and which test enforces each |
| [Design spec](dev/DEV_PLAN.md) | The single source of truth for the design |
| [Roadmap](dev/ROADMAP.md) | The remaining work, as the current plan |
| [History](dev/HISTORY.md) | How the completed phases were built |
| [Field notes](dev/FIELD_NOTES.md) | Gaps found by driving an agent end to end through hypothetical demo cases |
| [Publishing](dev/PUBLISHING.md) | The release runbook (PyPI, the `.mcpb` bundle) |
| [Acceptance test](dev/ACCEPTANCE.md) | The v0.1 ship gate: a non-developer reaches a filled form in under 20 minutes |
| [Demo storyboard](dev/DEMO.md) | The planned demo GIF |
| [Security policy](../.github/SECURITY.md) | How to report a vulnerability privately |

## Repository layout

```
taxfill-mcp/
├── packages/
│   ├── core/          # pure-Python engine: intake, residency, calc, fill, verify, render, workspace
│   │   └── tests/     # unit + integration tests; evals/ holds the end-to-end synthetic scenarios
│   ├── mcp-server/    # thin MCP wrapper (stdio) + the `taxfill` CLI; bundle/ is the .mcpb recipe
│   └── conftest.py    # shared pytest fixtures and the freshness-quarantine hook
├── formpacks/         # per-form field maps + verifier relations (federal/<year>/<form>, states/<st>/<year>/<form>)
├── knowledge/         # per-year tax law as cited YAML: federal, states, treaties, sources, pitfalls
├── skills/            # agent workflow instructions (Claude, Codex, Copilot)
├── scripts/           # maintainer tooling: count sync, drift and finals checks, pack scaffolding
└── docs/              # this folder; dev/ holds the maintainer docs
```

The engine is form- and jurisdiction-agnostic: federal and state forms share one `pack.yaml` schema, so coverage
grows by adding data packs, never by changing engine code. Blank PDFs are downloaded at runtime from the tax agencies' own sites
(or an exact Internet Archive copy when a state site blocks scripts) and checksum-verified — never stored in the repo.
