---
name: expert-alignment
description: "Use /skill:expert-alignment in Pi to load the canonical CHEC expert-alignment comparison contract for one circuit context."
license: Apache-2.0
metadata:
  runtime: pi
  canonical_skill: ../../../.claude/skills/expert-alignment/SKILL.md
---

# Pi Expert-Alignment Skill

Use this Pi entry point as:

```text
/skill:expert-alignment <args from the active workflow>
```

This is a thin Pi wrapper over the canonical Claude skill.

## Source of truth

- `.claude/skills/expert-alignment/SKILL.md` is the full skill contract.
- `.claude/agents/expert-alignment.md` is the canonical role contract.
- `.pi/agents/expert-alignment.md` is the Pi mirror for the same role.

## Pi compatibility

- Read the canonical Claude skill before running the flow.
- Reuse the same deterministic context, validation loop, and output contract.
- Do not add Pi-specific domain logic here.
