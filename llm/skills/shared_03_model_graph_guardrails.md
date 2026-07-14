# Shared Model and Graph Guardrails

These guardrails apply whenever an agent discusses MGCECDL, SHAP, Borda, inference outputs, graph routes, graph HTML artifacts, or simulator outputs.

## Model explanation boundaries

- MGCECDL in this project must be treated as a classification flow unless the context explicitly says otherwise.
- `UITI_VANO` is the target, impact criterion, or class basis; do not report it as a predictor used by the classifier when excluded from `features`.
- SHAP, Borda, attention, permutation importance, modal support, and softmax curves explain model behavior, not proven operational causes.
- Do not compare raw Borda scores across scenarios with different event counts.
- Do not report percentages, thresholds, class counts, or top-N values unless the context provides them.

## Graph interpretation

- `features` defines the ordered model input variables.
- A graph adjacency matrix must align exactly with `features`; expected shape is `(len(features), len(features))`.
- A graph route is expert or estimated context, not proof of physical causality.
- Graph weights are relative/expert or estimated association strengths, not probabilities or learned causal coefficients.
- If a route passes through nodes absent from `features`, those nodes preserve semantic context but were not predictors.
- Direct edges, preserved/virtual edges, and absent routes must be distinguished explicitly when the profile requires graph discussion.

## Graph HTML artifacts

- Graph HTML files from the MGCECDL analysis notebook are saved deliverables, not evidence that must be re-read from disk by the LLM.
- Estimated graph HTML should be described as relative association estimated for a scenario, commonly from reconstructed features and RBF similarity when the context says so.
- Do not interpret arrows, doubled direction, or graph weights as operational causality.
- If graph paths are missing or unavailable, mention the limitation instead of inventing a graph reading.

## Recommended phrasing

- "El modelo asignó relevancia a <variable>."
- "La relación en el grafo es coherente con una hipótesis operativa, no una prueba causal."
- "No se encontró una ruta documentada hacia `UITI_VANO`; la variable queda como señal del modelo pendiente de validación experta."
