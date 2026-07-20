# Expert-Alignment Agent Role (Pi mirror)

Same role as the Claude Code agent at `.claude/agents/expert-alignment.md`.
Read that file plus `.claude/skills/expert-alignment/SKILL.md` for the full persona,
invariants, workflow, and validation contract.

This Pi mirror is intentionally thin. It exists only so Pi can expose the same role entry point
without redefining domain behavior.

## Pi role notes

- Treat the Claude role file as the canonical role contract.
- Treat the Claude skill file as the canonical reasoning contract.
- Keep tool use conceptually identical: read context, invoke only the role's approved CLI verbs,
and rely on the shared validator for artifact writes.
- Do not add Pi-specific business logic or alternate output rules here.
