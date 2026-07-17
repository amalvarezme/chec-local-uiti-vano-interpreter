---
description: "OpenCode adapter for @agrupamiento-circuitos [fecha_inicio fecha_fin]. Generate the standalone local circuit-clustering HTML only."
mode: subagent
model: openai/gpt-5.4
permission:
  bash: ask
  edit: deny
---

# Circuit Clustering Adapter (OpenCode)

Use this adapter for:

```text
@agrupamiento-circuitos
@agrupamiento-circuitos <fecha_inicio> <fecha_fin>
```

This is a thin runtime adapter. Business behavior stays in `src/chec_local_interpreter/circuit_clustering_contract.py`, which reuses `plot_interactive_circuit_clustering`.

## Run sequence

1. Preflight through the shared contract:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.circuit_clustering_contract preflight [fecha_inicio fecha_fin] --runtime opencode
   ```

2. If dates were omitted, use the resolved full dataset range from the contract.
3. State the resolved date range once and ask the user to confirm before continuing.
4. After confirmation, render the standalone HTML:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.circuit_clustering_contract render [fecha_inicio fecha_fin] --runtime opencode
   ```

5. Return the local `output_html` path.

## Boundaries

- Local-only workflow.
- No external LLM calls.
- Do not publish.
- Do not mutate site assets.
- Do not duplicate clustering logic outside `circuit_clustering_contract`.
