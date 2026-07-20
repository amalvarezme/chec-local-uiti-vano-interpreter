---
name: informe-gerencial
description: "Run /skill:informe-gerencial <grupo> [fecha_inicio fecha_fin] in Pi to produce the canonical CHEC cross-circuit managerial report."
license: Apache-2.0
metadata:
  runtime: pi
  canonical_skill: ../../../.claude/skills/informe-gerencial/SKILL.md
---

# Pi Managerial-Report Skill

Use this Pi entry point as:

```text
/skill:informe-gerencial <grupo>
/skill:informe-gerencial <grupo> <fecha_inicio> <fecha_fin>
```

This is a thin Pi wrapper over the canonical Claude skill.

## Source of truth

- `.claude/skills/informe-gerencial/SKILL.md` is the full managerial-report contract.
- `.claude/skills/report/SKILL.md` remains the per-circuit report runbook it reuses for missing runs.

## Pi compatibility

- Read the canonical Claude skill before running the flow.
- Keep the same sampling, confirmation, and render semantics.
- Do not duplicate or replace the shared managerial-report contract.
