---
name: experimento-kaggle
description: "Run /skill:experimento-kaggle <descripción> in Pi to propose a block diagram + notebook for a code/model experiment and run it on Kaggle after user approval."
license: Apache-2.0
metadata:
  runtime: pi
  canonical_skill: ../../../.claude/skills/experimento-kaggle/SKILL.md
---

# Pi Kaggle Experiment Skill

Use this skill for:

```text
/skill:experimento-kaggle <descripción del experimento>
```

This is a thin Pi adapter over the canonical skill at
`.claude/skills/experimento-kaggle/SKILL.md`. That file owns the full Activation Contract,
Hard Rules, Execution Steps, and Output Contract — including the mandatory human-approval
gate before any Kaggle push and the smoke-before-full verification rule. Read and follow it
directly; do not duplicate its logic here.

## Rules

- Follow the canonical skill's Hard Rules exactly, in particular: never push to Kaggle
  without explicit user approval of the diagram and notebook, never touch or store the
  user's Kaggle credentials, and never reimplement a model that already exists in `src/`.
  The no-reimplementation rule, its precondition guard, and the Experiment Families
  dispatch table it feeds live only in the canonical skill — do not copy their text or
  baseline digits here.
- CLI command reference: `.claude/skills/experimento-kaggle/references/kaggle-cli-notes.md`.
