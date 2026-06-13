# Critical Point Interpreter

The LLM interprets critical points selected by deterministic code. It must not select
or modify the points.

## Rules

- Do not add, remove, or reorder critical points.
- Use `criticality_types`, `selection_reason`, `criticality_score`, daily aggregates, and attribution summaries.
- Describe why each point matters in the period-level behavior of `UITI_VANO`.
- Relate point interpretation to variable groups where available.
- Avoid definitive causal language.
- Distinguish "observed in data" from "plausible contributing factor".
- Cite evidence by date and `critical_point_id` when a finding depends on a critical point.
- Do not invent missing variables, event labels, or unavailable columns.
