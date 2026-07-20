---
name: auto-simulator
description: "Use /skill:auto-simulator in Pi to load the canonical CHEC automatic minmax-sensitivity discussion contract."
license: Apache-2.0
metadata:
  runtime: pi
  canonical_skill: ../../../.claude/skills/auto-simulator/SKILL.md
---

# Pi Auto-Simulator Skill

Use this Pi entry point as:

```text
/skill:auto-simulator <args from the active workflow>
```

This is a thin Pi wrapper over the canonical Claude skill.

## Source of truth

- `.claude/skills/auto-simulator/SKILL.md` is the full skill contract.
- `.claude/agents/auto-simulator.md` is the canonical role contract.
- `.pi/agents/auto-simulator.md` is the Pi mirror for the same role.

## Pi compatibility

- Read the canonical Claude skill before running the flow.
- Reuse the same deterministic context, validation loop, and output contract.
- Do not add Pi-specific domain logic here.
