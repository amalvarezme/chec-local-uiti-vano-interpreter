---
name: pdf-discussion-extraction
description: "Use /skill:pdf-discussion-extraction in Pi to load the canonical CHEC PDF discussion batch-extraction contract."
license: Apache-2.0
metadata:
  runtime: pi
  canonical_skill: ../../../.claude/skills/pdf-discussion-extraction/SKILL.md
---

# Pi PDF-Discussion-Extraction Skill

Use this Pi entry point as:

```text
/skill:pdf-discussion-extraction <args from the active workflow>
```

This is a thin Pi wrapper over the canonical Claude skill.

## Source of truth

- `.claude/skills/pdf-discussion-extraction/SKILL.md` is the full skill contract.
- `.claude/agents/pdf-discussion-extraction.md` is the canonical role contract.
- `.pi/agents/pdf-discussion-extraction.md` is the Pi mirror for the same role.

## Pi compatibility

- Read the canonical Claude skill before running the flow.
- Reuse the same deterministic context, validation loop, and output contract.
- Do not add Pi-specific domain logic here.
