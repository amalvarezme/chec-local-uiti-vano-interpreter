---
name: reporte-lote
description: "Run /skill:reporte-lote <grupo> [fecha_inicio fecha_fin] in Pi to batch the canonical CHEC report flow across one criticality group or the whole fleet."
license: Apache-2.0
metadata:
  runtime: pi
  canonical_skill: ../../../.claude/skills/reporte-lote/SKILL.md
---

# Pi Batch-Report Skill

Use this Pi entry point as:

```text
/skill:reporte-lote <grupo>
/skill:reporte-lote <grupo> <fecha_inicio> <fecha_fin>
```

This is a thin Pi wrapper over the canonical Claude skill.

## Source of truth

- `.claude/skills/reporte-lote/SKILL.md` is the full batch-report contract.
- `.claude/skills/report/SKILL.md` remains the per-circuit report runbook it reuses.

## Pi compatibility

- Read the canonical Claude skill before running the flow.
- Keep the same group-resolution, confirmation, and alert-and-continue semantics.
- Do not duplicate or replace the shared batch-report contract.
