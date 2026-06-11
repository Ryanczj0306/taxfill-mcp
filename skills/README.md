# Skills

This directory will hold the **agent skill layer**: the workflow instructions
that teach any MCP client to run the nine-step flow (intake → extract &
confirm → estimate & roadmap → residency & scope → positions → fill →
verify → summary → file & pay) with the project's hard rules — never invent data, user confirms
extracted values before filling, the verify gate is mandatory, everything is
a review draft, and the human signs and files (paper print-and-mail; no
e-filing).

Planned layout (see [`docs/DEV_PLAN.md`](../docs/DEV_PLAN.md), sections 3
and 11):

```
skills/
├── claude/SKILL.md            # Claude Code / Cowork workflow skill
├── codex/AGENTS.md
└── copilot/instructions.md
```

The skill files ship with cookbook recipes (copy-paste tool-call sequences
per scenario), the freshness protocol for tax years newer than the shipped
knowledge packs, and a no-MCP fallback appendix using `packages/core`
directly.

**Status: empty by design.** Skill files are delivered in **milestone M6**.
