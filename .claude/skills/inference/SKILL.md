---
name: inference
description: "Interpret the MGCECDL/SHAP predictive-model signals for CHEC's selected circuit(s) and period — scenario variable/mode importance, estimated graph-model coherence, and cautious predictive hypotheses — citing only already-selected structured context, with optional per-item provenance. Trigger: inference analysis, MGCECDL interpretation, SHAP scenario interpretation, graph connectivity coherence, predictive hypothesis synthesis."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  role: .claude/agents/inference.md
  rules: .claude/agents/rules/invariants.md
  ported_from:
    - .claude/skills/inference/prompt/01_structured_context_builder.md
    - .claude/skills/inference/prompt/02_circuit_scenario_interpreter.md
    - .claude/skills/inference/prompt/03_uiti_vano_behavior_explainer.md
    - .claude/skills/inference/prompt/04_graph_connectivity_guardrails.md
    - .claude/skills/inference/prompt/05_llm_output_validator.md
    - .claude/skills/inference/prompt/06_inference_output_contract.md
---

## Overview

This Skill is the single, current source of the inference/MGCECDL agent's reasoning guidance. It
**ports** (does not duplicate) the six prompt playbooks listed in `ported_from` above into one
Skill body with frontmatter, per `docs/agents-guide.md`'s three-meanings-of-"skills" table,
matching the `historical` port precedent. The `prompt/` subdir IS the machine-fed source:
`assemble_skill_bundle(profile="inferencia")` loads those same files directly from
`.claude/skills/inference/prompt/` (relocated from `llm/skills_inference/` in
`sdd/retire-llm-directory`); `SKILL.md` is this English condensation for human/agent context, not
a separate copy. Going forward, author and revise the inference reasoning guidance in the
`prompt/` playbooks, and keep this condensation in sync.

This Skill governs how the `inference` agent role (`.claude/agents/inference.md`) authors its
predictive-model interpretation. Every binding invariant (frozen boundaries, validator-gated
output, prohibited components, provenance, and the language register below) is defined once in
`.claude/agents/rules/invariants.md` — this Skill focuses on the domain-specific reasoning
content, not the invariants themselves.

## When to Use

Load this Skill when authoring the inference/MGCECDL predictive-model interpretation for one or
more circuits: translating scenario variable/mode importance, estimated graph associations, and
graph-model coherence into cautious business language, using only the already-built structured
context and estimated-graph deliverables the agent received — never new selection, detection, or
model invocation.

## Structured context construction (ported from `01_structured_context_builder.md`)

The deterministic Python layer builds the inference context **before** any call to this agent:
circuit, period, dates of interest, the selected `features` (with `UITI_VANO` always excluded from
that set — it is the target/impact-class basis, never a predictor), the per-scenario aggregated
tables, and (when available) the graph adjacency matrix and preserved edges aligned exactly to
`features`.

Rules this agent must honor about the context it receives:

- `UITI_VANO` is the target of the flow. Even if it appears in the variable-selection file, it is
  excluded from `features` before the model is fit and must never be narrated as a predictor the
  model used.
- Any adjacency matrix or preserved-edge list respects exactly the order of `features`.
- A graph shape is always `(len(features), len(features))` — never assume a fixed size.
- Estimated graph HTML deliverables (from the MGCECDL reconstruction + RBF-similarity layer) are
  reported as saved artifacts, not required inline visualizations, and are distinguished from the
  expert model-fitting graph.
- Variables mentioned that do not appear in `features` are context/original-node references only,
  never predictors the model actually used.
- If a required piece (circuit, period, `features`, an initialized explainer) is missing, describe
  the gap — never fabricate criticality conclusions from an incomplete context.

## Circuit scenario interpretation (ported from `02_circuit_scenario_interpreter.md`)

The operative unit is `FID_VANO` within the selected circuit. Four scenario types may appear in
the context, each with its own selection criterion — never reorder or reinterpret one as another:

- **Severity** (`UITI_VANO_PROM` descending): average impact per vano; does not by itself measure
  recurrence.
- **Frequency** (`N_APARICIONES` descending, `UITI_VANO_PROM` as tiebreak): recurrence; high
  frequency with low average impact reads as chronic-but-contained, not high-priority.
- **Dates of interest** (filtered to `fechas_interes`, then by severity): a temporal focus window —
  a date with zero events after filtering must never be narrated as evidence.
- **Frequency in dates of interest** (filtered to `fechas_interes`, then by frequency, severity as
  tiebreak): recurrence within the critical-dates subset, not general severity.

For every top variable in a scenario: confirm it is in `features`, identify its CHEC mode, contrast
it against the graph (direct route, preserved/virtual route via non-retained nodes, or no
documented route), and translate the route to operational language — always with the model-usage
phrasing below. Never compare raw Borda scores across scenarios with a different event count, and
never over-interpret small differences between normalized scores.

## Predictive-model behavior explanation (ported from `03_uiti_vano_behavior_explainer.md`)

Produce cautious, synthesis-level (not per-variable-exhaustive) narrative connecting model
importance, CHEC mode, graph route, and operational meaning for the 3-5 leading variables per
scenario. Distinguish predictor (in `features`, used by the model), target (`UITI_VANO` or a class
derived from it — never a predictor even if it appears in the selection file), and original
context node (part of the expert graph, may be outside `features`, still useful to explain a
preserved route).

- Never mix severity (`UITI_VANO`/`UITI_VANO_PROM`) with recurrence (`N_APARICIONES`) — state which
  one a finding is about.
- `discusion_grafos` synthesizes at most two general readings — `seccion: "periodo_completo"` and
  `seccion: "puntos_criticos"` — each connecting relevant variables/modes to the estimated graph's
  relative associations; never one entry per scenario, and never delivered as a dict instead of a
  list.
- Estimated graph HTML weights are normalized by the graph's own maximum and read as relative
  associations for that scenario's samples — never as expert/model-fitting-graph weights, and
  never interpreted with direction/double-arrows (the clean deliverable uses undirected edges).
- When no documented route exists for a variable, use the explicit acknowledgment template: "No se
  encontró una relación documentada entre `<variable>` y `UITI_VANO` dentro del grafo disponible.
  Su relevancia debe leerse como comportamiento del modelo, no como explicación experta validada."

## Graph connectivity guardrails (ported from `04_graph_connectivity_guardrails.md`)

The graph is a self-contained expert framework of directed relationships (`source -> target`,
weighted `0.50`-`1.0` by expected strength) spanning six CHEC modes: evento/impacto, protección y
maniobra, topología, características físicas del vano, activos, and entorno/riesgo/clima. Three
distinct graph levels must never be conflated:

1. The full expert graph (all documented business nodes, not all used as predictors).
2. The model-fitting graph (matrix aligned exactly to `features`).
3. The estimated HTML graph per scenario (from the MGCECDL reconstruction layer + RBF similarity
   over the scenario's samples) — a relative-association deliverable, not the expert matrix.

Never:

- State that inference used the graph matrix directly to predict.
- Treat weights as probabilities to be summed, or as coefficients the model learned.
- Interpret a preserved/virtual edge (routed through a non-retained node) as a direct physical
  connection.
- Say a variable without a documented expert route is false or irrelevant — only that its
  relevance is model behavior requiring operational validation.
- Ignore edge direction or reorder `features` when reading an adjacency matrix.

Coherence template: "La variable `<variable>` pertenece al modo `<modo>`. En el grafo experto se
conecta con `UITI_VANO` mediante `<ruta>`, con una relación `<fuerte/moderada/débil>`. Esto hace
que su aparición en el ranking del modelo sea `<coherente/parcialmente coherente/no explicada por
el grafo>`, aunque sigue siendo una explicación del modelo."

## Output validation (ported from `05_llm_output_validator.md`)

Every response is validated before being presented as an analysis. A valid response:

- Is valid JSON, complies with `inference.output_schema.json`.
- Includes every scenario present in the context's `escenarios`, using the exact same `nombre`.
- Never invents a variable, mode, date, critical-point id, or scenario name outside the context.
- `discusion_grafos` is a list of `{seccion, lectura}` objects (never a dict), covering
  `periodo_completo` and `puntos_criticos` when estimated graphs exist for both.
- Never claims the model used the graph directly, or that an isolated variable — without checking
  its mode/route — explains the result.
- Includes `limitaciones` and distinguishes severity, frequency, and dates-of-interest scenarios.
- Every list-shaped field caps at 5 items, prioritizing the best-supported findings when more
  exist.

Forbidden causal/model-boundary language (rejected outright, mirrored in
`INFERENCE_PROVENANCE_RULES`'s guardrail stage — do not phrase around this, honor it):

- "demuestra que", "demuestra el origen del evento", "demonstrates that" — use "es coherente con
  una hipótesis operativa" instead.
- "inferencia usó el grafo" — use "el grafo se usa para contrastar la interpretación" instead.
- "la variable aislada explica el resultado" — use "la variable se interpreta junto con su modo y
  ruta en el grafo" instead.

If validation fails, the raw invalid output and validation errors are saved for review under
`reports/interpretability/artifacts/inference/{circuito}/` (this Skill's own agent-namespaced
artifacts root — see `.claude/agents/rules/invariants.md`, Rule 3) — the invalid output is never
presented as the final analysis.

## Inference output contract (ported from `06_inference_output_contract.md`)

Role: interpreter of the MGCECDL predictive model's scenarios, variables, modes, SHAP/Borda scores,
and referenced graph HTML deliverables, for electrical distribution networks.

Return exactly the nine required keys: `contexto`, `entregables`, `escenarios`, `discusion_grafos`,
`coherencia_grafo_modelo`, `hallazgos`, `limitaciones`, `inferencias_predictivas`,
`hipotesis_modelo_predictivo` — only valid JSON, in Spanish, no markdown/`<think>`/text outside the
JSON object, every array and the root object fully closed.

- `escenarios`: one `{nombre, interpretacion}` (plus optional `provenance`) per context scenario,
  using the exact `nombre` received — never copy `tabla_top_vanos` verbatim; synthesize patterns.
- `discusion_grafos`: up to two `{seccion, lectura}` entries as described above.
- `coherencia_grafo_modelo`: items describing whether a variable has a documented route to
  `UITI_VANO`, its route type (directa/preservada/sin camino), and how that coherence reads against
  the scenario.
- `inferencias_predictivas`: `{horizonte, riesgo, justificacion_modelo}` items — cautious risk
  language for the analyzed period, never presented as an operational forecast (Rule 5's
  no-forecasting-outside-this-flow boundary is what this key IS the validated exception for; it
  still must never assert a definitive future outcome).
- `hipotesis_modelo_predictivo`: `{periodo_completo, puntos_criticos}`, each a list capped at 5
  items, synthesizing (not repeating) the corresponding findings/scenarios/graph discussion in the
  same executive style as the historical agent's own hypothesis note — cautious language only
  ("el modelo sugiere", "es consistente con", "podría estar asociado", "requiere validación").

Style: tabular-evidence language throughout; every narrative field is one closed paragraph; list
blocks cap at 5 items, prioritizing the best-supported findings (dates, scenarios, variables, graph
routes) when more exist.

## Provenance contract

Add an optional `provenance` object to any `escenarios` or `discusion_grafos` item that traces back
to a specific source, per `.claude/agents/rules/invariants.md` Rule 6:

```json
"provenance": {
  "data_ref": ["2026-01-02", "cp-2026-01-02", "UITI_VANO"],
  "agent": "inference",
  "rule": "04_graph_connectivity_guardrails"
}
```

- `data_ref` entries resolve against the citable universe advertised in the envelope's `allowed`
  block: an ISO date, a derived `cp-YYYY-MM-DD` critical-point id, a `features` variable name
  (case-insensitive), or an exact context scenario name — anything else, or a reference outside
  that universe, fails validation.
- `agent` must always be the literal string `"inference"`.
- `rule` must be one of the six playbook ids ported into this Skill (`ported_from` above, stripped
  of their `NN_` prefix and `.md` suffix): `01_structured_context_builder`,
  `02_circuit_scenario_interpreter`, `03_uiti_vano_behavior_explainer`,
  `04_graph_connectivity_guardrails`, `05_llm_output_validator`, `06_inference_output_contract` —
  the exact set `INFERENCE_PROVENANCE_RULES` (`inference_validation.py`) enforces.
- Omitting `provenance` on an `escenarios`/`discusion_grafos` item never fails validation — it is
  optional per item, not required.

## Language register

Report content stays in the cautious Spanish register (this is the same register the schema
validator and `.claude/agents/rules/invariants.md` Rule 7 enforce):

- Mantén lenguaje cauteloso: sugiere, es coherente con, podría estar asociado, requiere validación.
- No afirmes que el modelo usó el grafo directamente, ni que inferencias predictivas equivalen a un
  pronóstico operacional.

## Related artifacts

- Agent role: `.claude/agents/inference.md`
- Binding rules: `.claude/agents/rules/invariants.md`
- Architecture and envelope contract: `docs/agents-guide.md`
- L1 deterministic Python: `src/chec_local_interpreter/inference_validation.py`,
  `src/chec_local_interpreter/prompt_assets/inference.output_schema.json`
- L2 CLI: `src/chec_local_interpreter/agent_tools/inference.py`
- Ported-from playbooks (the machine-fed source, loaded by
  `assemble_skill_bundle(profile="inferencia")`):
  `.claude/skills/inference/prompt/01_structured_context_builder.md`,
  `.claude/skills/inference/prompt/02_circuit_scenario_interpreter.md`,
  `.claude/skills/inference/prompt/03_uiti_vano_behavior_explainer.md`,
  `.claude/skills/inference/prompt/04_graph_connectivity_guardrails.md`,
  `.claude/skills/inference/prompt/05_llm_output_validator.md`,
  `.claude/skills/inference/prompt/06_inference_output_contract.md`
