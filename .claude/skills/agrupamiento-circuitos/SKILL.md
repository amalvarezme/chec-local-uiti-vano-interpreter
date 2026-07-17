---
name: agrupamiento-circuitos
description: "Trigger: /agrupamiento-circuitos, circuit clustering chart, clustering only chart. Generate the standalone local HTML for the circuit-clustering chart using the shared contract and the existing plot_interactive_circuit_clustering logic."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  runtime: claude
  canonical_contract: src/chec_local_interpreter/circuit_clustering_contract.py
---

## Activation Contract

Use this skill when the user wants only the circuit-clustering chart as a standalone HTML, not the full report.

Invocation:

```text
/agrupamiento-circuitos [fecha_inicio fecha_fin]
```

## Hard Rules

- Keep the workflow local-only.
- No external LLM calls and no full-report orchestration.
- Do not duplicate clustering logic; reuse `plot_interactive_circuit_clustering` through the shared contract.
- Dates are optional as a pair.
- If dates are omitted, resolve the full dataset range first.
- Before generation, state the resolved `fecha_inicio`/`fecha_fin` once and ask the user to confirm.
- If exactly one date is given, stop with a usage error.
- Return the local HTML path produced by the render step.
- Do not publish or mutate site assets.

## Execution Steps

**Environment bootstrap.** Run commands from the repository root with `PYTHONPATH=src .venv/bin/python`.

Invocation:

```text
/agrupamiento-circuitos
/agrupamiento-circuitos <fecha_inicio> <fecha_fin>
```

1. Normalize and preflight through the shared contract:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.circuit_clustering_contract preflight [fecha_inicio fecha_fin] --runtime claude
   ```

2. Read the JSON outcome and resolve the final date window.
3. State the resolved window once and ask the user to confirm before rendering.
4. After confirmation, generate the standalone chart HTML:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.circuit_clustering_contract render [fecha_inicio fecha_fin] --runtime claude
   ```

5. Return only the local HTML path from `output_html`.

## Output Contract

Return:
- the confirmed `fecha_inicio` and `fecha_fin`;
- the local `output_html` path;
- any execution error from the shared contract when generation fails.

## References

- `src/chec_local_interpreter/circuit_clustering_contract.py`
- `src/chec_local_interpreter/plotting.py`
- `docs/agents-guide.md`
