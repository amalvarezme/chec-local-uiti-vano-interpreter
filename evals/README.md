# Offline LLM Evals

These checks render prompts from synthetic contexts and validate synthetic LLM outputs.
They do not call an API.

```bash
python evals/run_llm_eval.py
```

`pytest -q` covers the same entry point through `tests/test_offline_eval_smoke.py`, so a
broken eval fails the suite too — the manual command stays as the documented gate.

## What it covers

One eval loop per role the report dispatches. Each one builds a synthetic response from
its fixture and pushes it through the same two code-level validators the agent's
`validate` verb runs: schema plus guardrails first, provenance second.

| Fixture glob | Role | Validators |
|---|---|---|
| `synthetic_context_*.json` | base agent (prompt render + response) | `validate_llm_response` |
| `synthetic_historical_context_*.json` | `historical` | `validate_llm_response` + `validar_provenance_base` |
| `synthetic_inference_context_*.json` | `inference` | `validar_respuesta_inferencia_strict` + `validar_provenance_inferencia` |
| `synthetic_expert_alignment_context_*.json` | `expert-alignment` | `validar_respuesta_expert_alignment` + `validar_provenance_expert_alignment` |

Fixtures are discovered **by glob**, so adding a case is dropping a file next to the
others — no registry to update. A file that does not match its role's pattern is never
executed, which is the one failure mode worth knowing about.

## About the fixtures

They are synthetic but not invented: `synthetic_inference_context_01.json` was produced by
calling `construir_contexto_inferencia_mil` — the same function `prepare` calls — over a
fake `RecursosMIL`, then compacted with `compactar_grafo_del_escenario` exactly as
`prepare` does before writing `inference.bc.json`. Hand-writing it would have frozen the
shape somebody believed the context has, rather than the one the code produces.

The circuit (`SIN23L99`) and the vano ids are fake; the model, unit, metric, window labels
and lever names are the real contract.

## Why the provenance case matters

Provenance is **optional per item** in all three roles. A synthetic response without it
passes both stages while exercising nothing, so every response here carries a resolving
`provenance` on each section its validator inspects. Verified by mutation: an unknown
window, a wrong `agent`, a rule outside the allow-list, a date outside the context, an
invented scenario name and — for `inference` — a sentence hanging the event count on the
model are each rejected. The MIL predicts `uiti_acumulado`; the event count is an axis of
the KMeans space that fixes the class, never a model output.
