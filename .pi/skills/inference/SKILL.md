---
name: inference
description: "Use /skill:inference in Pi to load the canonical CHEC MGCECDL/SHAP inference contract for one circuit context."
license: Apache-2.0
metadata:
  runtime: pi
  canonical_skill: ../../../.claude/skills/inference/SKILL.md
---

# Pi Inference Skill

Use this Pi entry point as:

```text
/skill:inference <args from the active workflow>
```

This is a thin Pi wrapper over the canonical Claude skill.

## Source of truth

- `.claude/skills/inference/SKILL.md` is the full skill contract.
- `.claude/agents/inference.md` is the canonical role contract.
- `.pi/agents/inference.md` is the Pi mirror for the same role.

## Pi compatibility

- Read the canonical Claude skill before running the flow.
- Reuse the same deterministic context, validation loop, and output contract.
- Do not add Pi-specific domain logic here.
