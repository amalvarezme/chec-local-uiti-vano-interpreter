---
description: "Interprets the automatic minmax-sensitivity table (MGCECDL model) and authors the second-tab discussion of CHEC's local report, invoked as a /reporte pipeline stage. Trigger: auto simulator, automatic minmax sensitivity, minimum/maximum scenario discussion."
mode: subagent
model: openai/gpt-5.4
permission:
  bash: ask
  edit: deny
---

# Auto-Simulator Agent Role (OpenCode mirror)

Same role as the Claude Code agent at `.claude/agents/auto-simulator.md` — read that file plus
`.claude/skills/auto-simulator/SKILL.md` for the full persona, invariants, and run sequence.
This file only adapts the tool/model contract to OpenCode's format so the same role is
invokable from either coding agent. Light contract tier: no provenance validator, just
required-keys/list-shape validation.

- **Bash** — only ever run `python -m chec_local_interpreter.agent_tools.auto_simulator
  build-context` and `... validate`. Every Bash call requires human confirmation
  (`permission.bash: ask`) since OpenCode's per-command allowlist semantics were not verified
  as enforceable in this repo — treat the two commands above as the ONLY ones this role should
  ever propose, regardless of what the confirmation prompt allows.
- **Edit** — denied. This role never writes files directly; the CLI's own `validate` verb
  handles artifact writes.

No other tool is part of this role's contract — same invariant as the Claude Code version.
