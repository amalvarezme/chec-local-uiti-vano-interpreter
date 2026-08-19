## graphify

For any question about this repo's architecture, structure, components, or how to add/modify/find
code, your first action should be `graphify query "<question>"` when `graphify-out/graph.json`
exists. Use `graphify path "<A>" "<B>"` for relationship questions and `graphify explain "<concept>"`
for focused-concept questions. These return a scoped subgraph, usually much smaller than the full
report or raw grep output.

Triggers: "how do I…", "where is…", "what does … do", "add/modify a <component>",
"explain the architecture", or anything that depends on how files or classes relate.

If `graphify-out/wiki/index.md` exists, use it for broad navigation. Read `graphify-out/GRAPH_REPORT.md`
only for broad architecture review or when query/path/explain do not surface enough context. Only read
source files when (a) modifying/debugging specific code, (b) the graph lacks the needed detail, or
(c) the graph is missing or stale.

Type `/graphify` in Copilot Chat to build or update the graph.

## This repository's commands

The canonical contract for every command, skill and agent role lives under `.claude/`.
`AGENTS.md` in the repository root carries the project's scope, coding style and LLM-safety
rules and applies here too.

Copilot gets its own discovery paths through generated mirrors:

- `.github/prompts/*.prompt.md` — one per invocable command (`/report`, `/reporte-lote`,
  `/informe-gerencial`, `/clima`, `/redaccion-es`, `/limpiar-corridas`,
  `/subir-a-databricks`, `/app-local-criticidadCHEC`, and the role entry points).
- `.github/agents/*.agent.md` — one per LLM role (`historical`, `inference`,
  `expert-alignment`, `pdf-discussion-extraction`).

Those files are **generated** by `scripts/portabilidad_agentes.py` and hold no rule of their
own: each one names the canonical `.claude/` file to read before doing anything. Change the
canonical contract, then run:

```bash
PYTHONPATH=src .venv/bin/python scripts/portabilidad_agentes.py generar
```

`tests/test_portabilidad_agentes.py` fails when a mirror is missing, stale or orphaned, so a
new skill without mirrors turns the suite red instead of quietly working in one editor only.

## Running anything in this repository

Every CLI verb runs from the repository root as `PYTHONPATH=src .venv/bin/python -m ...`.
Bare `python`/`python3` cannot import `chec_local_interpreter`; that is not a broken
environment, it is the wrong invocation.
