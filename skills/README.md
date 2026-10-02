# Skills

The agent skill layer: workflow instructions that teach any MCP client to run the nine-step flow (intake → extract &
confirm → estimate & roadmap → residency & scope → positions → fill → verify → summary → file & pay) with the
project's hard rules — never invent data; the user confirms extracted values before anything is filled; the verify
gate is mandatory (calc results feed `independent`); everything is a review draft; the human signs and files on paper
(no e-filing).

```
skills/
├── claude/SKILL.md            # Claude Code / Claude Desktop / Cowork
├── codex/AGENTS.md            # Codex CLI
└── copilot/instructions.md    # GitHub Copilot
```

`claude/SKILL.md` is the canonical file: it carries the cookbook recipes (copy-paste tool-call sequences per
scenario), the freshness protocol for tax years newer than the shipped knowledge, and a no-MCP fallback that uses
`taxfill_core` directly. The Codex and Copilot files are condensed mirrors of its rules and tool list that point back
to it. How to install each one is in the [README quickstart](../README.md#quickstart).
`packages/mcp-server/tests/test_skills_sync.py` keeps them in step with the live tool surface, so a tool or calc op
the server gains cannot go unmentioned here.
