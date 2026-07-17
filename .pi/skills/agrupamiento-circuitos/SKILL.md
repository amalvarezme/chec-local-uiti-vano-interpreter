---
name: agrupamiento-circuitos
description: "Run /skill:agrupamiento-circuitos [fecha_inicio fecha_fin] in Pi to generate the standalone local circuit-clustering HTML only."
license: Apache-2.0
metadata:
  runtime: pi
  canonical_skill: ../../../.claude/skills/agrupamiento-circuitos/SKILL.md
---

# Pi Circuit Clustering Skill

Use this skill for:

```text
/skill:agrupamiento-circuitos
/skill:agrupamiento-circuitos <fecha_inicio> <fecha_fin>
```

This is a thin Pi adapter over `src/chec_local_interpreter/circuit_clustering_contract.py`. The shared contract reuses `plot_interactive_circuit_clustering` and owns date resolution plus HTML generation.

## Rules

- Dates are optional as a pair.
- If both dates are omitted, resolve the full dataset range first.
- Ask the user to confirm the resolved date range before render.
- If exactly one date is given, stop with a usage error.
- Return only the local `output_html` path.
- Keep the workflow local-only.

## Run sequence

1. Preflight via the shared contract:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.circuit_clustering_contract preflight [fecha_inicio fecha_fin] --runtime pi
   ```

2. State the resolved date range once and ask the user to confirm it.
3. After confirmation, render the standalone chart HTML:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.circuit_clustering_contract render [fecha_inicio fecha_fin] --runtime pi
   ```

4. Return the local HTML path from `output_html`.

## Boundaries

- No external LLM calls.
- No publishing.
- No site asset mutation.
- No model training or Optuna search.
- No duplicated clustering logic.
