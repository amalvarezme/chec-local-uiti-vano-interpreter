---
name: reporte
description: "Run the full end-to-end CHEC UITI_VANO report pipeline for one circuit: deterministic data prep, the historical/base diagnosis, the inference/MGCECDL interpretation, expert-alignment comparison, and the final HTML report. Trigger: /reporte, full circuit report, end-to-end interpretability run."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  rules: .claude/agents/rules/invariants.md
  orchestrator: src/chec_local_interpreter/report_pipeline.py
  invokes_skills:
    - .claude/skills/historical/SKILL.md
    - .claude/skills/inference/SKILL.md
    - .claude/skills/expert-alignment/SKILL.md
    - .claude/skills/auto-simulator/SKILL.md
---

## Overview

`/reporte` is the single entry point for the whole CHEC UITI_VANO local-interpretability flow. It
is **different in kind** from `historical`/`inference`/`expert-alignment`: those three are
single-agent role Skills — each one authors and validates one JSON envelope for one persona. This
Skill does not author a report itself. It is the **orchestrating runbook**: a step-by-step sequence
that runs the deterministic Python stages in
[`report_pipeline.py`](../../../src/chec_local_interpreter/report_pipeline.py) and, between them,
invokes the three existing agent Skills in order, so the run_dir on disk carries validated JSON
from one stage to the next. Read this Skill top to bottom as a checklist, not as reasoning
guidance — the actual domain reasoning for each stage lives in that stage's own Skill
(`historical`, `inference`, `expert-alignment`).

Supersedes the interactive notebook `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`
in full, including its phase 9-11 automatic min/max ("second tab") discussion — now step 4b below,
via the `auto-simulator` agent. That notebook was deleted once this Skill's coverage was proven
equivalent (see git history for its prior content).

## When to Use

Load this Skill when the user asks for a full circuit report — `/reporte <circuito>` with optional
dates — rather than a single agent's isolated diagnosis. If the user only wants one agent's output
in isolation (e.g. "just the historical diagnosis"), use that agent's own Skill directly instead.

## Argument contract

- `circuito` — **required**. Must be a circuit id present in the dataset (`available_circuits`).
- `fecha_inicio` / `fecha_fin` — **optional, as a PAIR**:
  - Both omitted: both default via `data_loader.circuit_date_range(frame, circuito)` to the
    circuit's full available date range.
  - Both given: passed through unchanged.
  - **Exactly one given is a usage error.** Reject it immediately with a usage message (e.g. "give
    both fecha_inicio and fecha_fin, or omit both") — do not guess, do not silently default only
    the missing bound. This is enforced in code, not just prose: `report_pipeline.prepare(...)`
    raises `ReportPipelineError` before touching the dataset when exactly one date is given, so
    even a direct call bypassing this Skill's own argument check fails closed.

Examples:

| Invocation | Result |
|---|---|
| `/reporte C1` | Both dates default to C1's full range |
| `/reporte C1 2026-01-01 2026-02-01` | Both dates pass through unchanged |
| `/reporte C1 2026-01-01` | **Rejected** — usage error, `fecha_fin` missing |

## Allowed tools

- **Bash** — restricted to invoking the orchestrator's own Python stages
  (`chec_local_interpreter.report_pipeline.prepare` / `.prepare_expert_alignment` / `.render`, e.g.
  via `python -c "from chec_local_interpreter.report_pipeline import ...; ..."`) and nothing else.
  This Skill never gets a general shell — same structural guarantee as the `historical`,
  `inference`, and `expert-alignment` roles (`.claude/agents/rules/invariants.md`, Rule 1).
- **Skill** — to invoke `historical`, `inference`, and `expert-alignment` in the sequence below.
  Each of those Skills governs its own agent's Bash/Read restrictions independently; this runbook
  does not relax or bypass them.
- **Read** — to inspect run_dir artifacts (`*.bc.json`, `*.out.json`) between stages.

No distinct `.claude/agents/reporte.md` role file is introduced. This Skill is a deterministic
runbook, not an LLM-authoring persona that itself needs a restricted-Bash role contract scoped to a
dedicated CLI verb (unlike `historical`/`inference`/`expert-alignment`, which each shell out to
their own `agent_tools.*` CLI because they author and validate one persona's JSON output). Adding a
role file here would either duplicate a CLI module that does not exist in this change's scope (no
`agent_tools.report_pipeline` CLI was built — `report_pipeline.py`'s stages are plain importable
Python functions) or require building one purely to mirror a pattern that does not apply to an
orchestrator. The Skill-only shape is the cheaper-to-maintain choice; revisit only if a future
change adds a headless/non-interactive invocation path for `/reporte` that needs its own CLI
boundary.

## Run sequence

Given `circuito` (and optionally `fecha_inicio`/`fecha_fin` as a validated pair):

1. **Validate arguments.** Reject a lone date per the argument contract above before doing
   anything else.
2. **`prepare`** — run
   `report_pipeline.prepare(circuito, fecha_inicio, fecha_fin)`. Writes
   `run_dir/historical.bc.json`, `run_dir/inference.bc.json`, `run_dir/l1_state.json`. Raises
   `ReportPipelineError` (circuit not found, or zero events in the resolved window) before writing
   anything — report the error to the user and stop; do not invoke any agent.

   As of this change, `prepare` also runs the real MGCECDL/SHAP scenario simulator (read-only: it
   only *loads* the most recent trained classifier and Optuna study already on disk — it never
   trains a model or launches an Optuna search). This is load-and-infer only, not the separate
   "simulador automático mínimo/máximo" (still untouched, out of scope). Three outcomes, none of
   them a `ReportPipelineError`:
   - **Healthy**: model and Optuna study both load; up to four scenario contexts
     (severity/frequency × período completo/fechas de interés) are computed, each surviving
     scenario's `fig_barras`/`fig_radar` PNGs saved under `run_dir/inference_figures/` and its
     `grafo_interactivo` HTML under `run_dir/inference_graphs/`, with a run_dir-relative path map
     written to `run_dir/inference_render_assets.json`.
   - **No trained model on disk (structural gap)**: `inference.bc.json` gets `features: []`,
     `escenarios: []`, `modelo` stays the placeholder label — the simulator never runs at all, no
     sidecar is written. The report still generates; the `inference` agent's own guardrails force
     this gap into prose.
   - **Model present, Optuna study missing**: falls back to `rbf_sigma=1.0` — this is NOT the gap
     above; the simulator still runs fully and `features`/`escenarios` populate normally.
   - **Per-scenario skip**: any one of the four scenario types with too few events for a valid SHAP
     computation is skipped individually (`escenarios` simply omits it) — the other scenarios in the
     same run are unaffected, and this alone never raises `ReportPipelineError`. If ALL four are
     skipped, `escenarios: []` but `features` stays non-empty and `modelo` is the real loaded
     model's class name (distinguishes this data-availability gap from the "no trained model" gap
     above, which has `features: []` too).
3. **Invoke `historical`** — load this Skill (`.claude/skills/historical/SKILL.md`), give it
   `run_dir/historical.bc.json`'s envelope via `agent_tools.historical build-context`/`validate`,
   and have it write its validated response to `run_dir/historical.out.json` as
   `{"ok": true, "data": <response>}` once `validate` returns exit code `0`. If validation retries
   are exhausted, stop the whole `/reporte` run for this circuit here — do not proceed to
   `inference` or beyond, and report the last validation errors to the user.
4. **Invoke `inference`** — same pattern as step 3, using `run_dir/inference.bc.json` and this
   Skill's own `agent_tools.inference build-context`/`validate` verbs, writing
   `run_dir/inference.out.json`. Steps 3 and 4 may run in either order (both must complete
   successfully before step 5) — the design places no ordering requirement between historical and
   inference, only that both precede expert-alignment.
4b. **Invoke `auto-simulator`** — `prepare` (step 2) already ran the automatic min/max sensitivity
   simulator as a side effect, using the same loaded MGCECDL model as the inference/SHAP simulator.
   If `run_dir/auto-simulator.bc.json` exists, load `.claude/skills/auto-simulator/SKILL.md`, give it
   that envelope via `agent_tools.auto_simulator build-context`/`validate`, and have it write its
   validated response to `run_dir/auto-simulator.out.json` as `{"ok": true, "data": <response>}` once
   `validate` returns exit code `0`. Unlike steps 3/4/6, a validation-retries-exhausted outcome here
   does **not** stop the whole `/reporte` run — degrade to skip (proceed to step 5 without an
   `auto-simulator.out.json`; `render`'s `automatic_simulation_analysis` kwarg simply stays `None`),
   since this is a supplementary discussion section, not a required stage. If
   `run_dir/auto-simulator.bc.json` is absent (R3 gap: no trained model, or zero events for this
   circuit/window in the automatic simulator's re-derived mask), skip this step entirely — there is
   nothing to build a prompt from.
5. **`prepare_expert_alignment`** — run
   `report_pipeline.prepare_expert_alignment(run_dir)`. Reads the validated
   `historical.out.json`/`inference.out.json` from steps 3-4, pools report dates, matches the
   already-extracted PDF-discussion table, and writes `run_dir/expert-alignment.bc.json`. Raises
   `ReportPipelineError` if either agent's validated output is missing or `ok: false` — stop and
   report if so (this should not happen if steps 3-4 completed successfully).
6. **Invoke `expert-alignment`** — same validate-gated pattern, using
   `run_dir/expert-alignment.bc.json` and `agent_tools.expert_alignment build-context`/`validate`,
   writing `run_dir/expert-alignment.out.json`.
7. **`render`** — run `report_pipeline.render(run_dir)`. Reads all three validated outputs and
   calls `plotting.render_llm_analysis`, now also merging in the 5 `automatic_simulation_*` kwargs
   (table, agent analysis, cost context, softmax curves, vano-risk table) when
   `run_dir/auto_simulation_assets.json` and/or `run_dir/auto-simulator.out.json` exist — every
   kwarg stays `None` when the corresponding file is absent (no crash either way, same degrade
   shape as the inference-simulator sidecar below). Raises `ReportPipelineError` if the
   expert-alignment output is missing/invalid; no HTML is written in that case.

   `render` stays model-free: it never reloads the MGCECDL classifier or recomputes SHAP. If
   `prepare` persisted `run_dir/inference_render_assets.json` (the healthy-run case above), `render`
   resolves every figure/graph path in it against `run_dir` and passes a populated
   `inference_results` mapping into `plotting.render_llm_analysis`, so the bars/radar/estimated-graph
   section actually renders. If the sidecar is absent (no trained model, or every scenario was
   skipped), `inference_results` stays `None` — the inference-figures section is empty, same as
   before this change, and this is never a crash or a `ReportPipelineError`.
8. **Publish to the site** — run `web_export.export_latest_interpretability_report(html_path)`, where
   `html_path` is step 7's return value. This is the step that used to happen at the end of the
   deprecated notebook (deleted once this Skill's coverage was proven equivalent) and has no other
   caller in this codebase — skipping it means `/reporte` runs generate a report on disk but never
   refresh `src/assets/site/results/latest_interpretability_report.html`, so the published GitHub
   Pages site goes stale. Not gated by any prior stage's success/failure beyond step 7 itself having
   produced an `html_path` — if step 7 raised, there is nothing to publish and this step does not run.
9. **Report the result** — tell the user the returned HTML `Path` (and, once published, that it was
   copied into the site assets). Do not claim the report is final if any stage above raised and
   stopped the run early.

## Error handling summary

| Failure | Where | User-facing outcome |
|---|---|---|
| Lone date given | Step 1 (this Skill) / `prepare` | Usage error, no stage runs |
| Circuit not found | `prepare` | `ReportPipelineError`, no run_dir created, no agent invoked |
| Zero events in window | `prepare` | `ReportPipelineError`, no run_dir created, no agent invoked |
| Agent validation retries exhausted | Steps 3, 4, or 6 | Stop this circuit's run; surface the last `validate` errors; never invoke a later stage |
| Missing/invalid validated output reaching a later stage | `prepare_expert_alignment` / `render` | `ReportPipelineError`; the affected artifact is never written |

### Simulator degrade paths (NOT `ReportPipelineError`)

These are graceful-degradation outcomes from the MGCECDL/SHAP simulator inside `prepare` — the run
always continues, the report always generates:

| Case | Where | Resulting shape |
|---|---|---|
| No trained model file on disk | `prepare` (`_load_mgcecdl_model_and_sigma`) | `features: []`, `escenarios: []`, `modelo` stays the placeholder label; no `inference_render_assets.json` sidecar; `render` gets `inference_results=None` |
| Model present, Optuna study file missing | `prepare` (`_load_mgcecdl_model_and_sigma`) | Falls back to `rbf_sigma=1.0`; simulator runs fully, NOT the gap above |
| One scenario (of four) has too few events for valid SHAP | `prepare` (`_compute_inference_scenarios`) | That scenario is silently omitted from `escenarios`; the other surviving scenarios are unaffected |
| All four scenarios have too few events | `prepare` (`_compute_inference_scenarios`) | `escenarios: []` but `features` non-empty and `modelo` is the real model's class name — distinguishes this from the "no trained model" row above |
| Graph-output directory can't be created (`graph_dir.mkdir`), or one scenario's interactive graph HTML can't be written (`mostrar_grafo_interactivo_muestras`/`construir_grafo_interactivo_muestras`) | `prepare` (`_compute_inference_scenarios`) | `OSError`/`PermissionError` caught, never propagates out of `prepare`. A failed `graph_dir.mkdir` degrades the WHOLE call (`escenarios: []`, `features` still populated) since no scenario can persist a graph without a writable directory; a failed per-scenario HTML write degrades only THAT scenario (omitted from `escenarios`, others unaffected) — both cases warn clearly, the run always completes |
| `inference_render_assets.json` sidecar write fails (`save_json_artifact` raises `OSError`/`PermissionError`, e.g. disk-full) | `prepare` (top-level, after `_run_inference_simulator` returns) | `OSError` caught, never propagates out of `prepare`; `historical.bc.json`/`inference.bc.json`/`l1_state.json` are still written and `inference.bc.json`'s `escenarios`/`features` stay populated (already computed before this write) — only the sidecar is missing, so `render` degrades exactly like the "sidecar absent" row below |
| `inference_render_assets.json` sidecar present at render time | `render` | Figures/graphs resolved against `run_dir` and embedded (PNGs as base64 `<img>`, HTML graphs as an iframe) |
| Sidecar absent at render time | `render` | `inference_results=None`, inference-figures section stays empty, no crash |

## Related artifacts

- Orchestrator (L1, pure Python, no LLM call anywhere in this module):
  [`src/chec_local_interpreter/report_pipeline.py`](../../../src/chec_local_interpreter/report_pipeline.py)
- Per-circuit date-range default: `data_loader.circuit_date_range`
- Invoked agent Skills, in run order: `historical`, `inference` (either order between them),
  `expert-alignment`
  - [`.claude/skills/historical/SKILL.md`](../historical/SKILL.md) /
    [`.claude/agents/historical.md`](../../agents/historical.md)
  - [`.claude/skills/inference/SKILL.md`](../inference/SKILL.md) /
    [`.claude/agents/inference.md`](../../agents/inference.md)
  - [`.claude/skills/expert-alignment/SKILL.md`](../expert-alignment/SKILL.md) /
    [`.claude/agents/expert-alignment.md`](../../agents/expert-alignment.md)
- Binding invariants (shared with every agent role above): `.claude/agents/rules/invariants.md`
- Architecture and envelope contract: `docs/agents-guide.md`
- `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb` — deleted; this Skill supersedes it
  in full (see git history for its prior content).
- Tests: `tests/test_report_pipeline.py` (argument-pair contract, simulator wiring/degrade paths, the
  real-simulator integration tests using the committed model/Optuna/Variables artifacts, and the
  end-to-end smoke test with canned validated outputs and no live LLM call);
  `tests/test_report_pipeline_inference_simulator.py` (unit tests for the standalone
  `_load_mgcecdl_model_and_sigma`/`_compute_inference_scenarios`/`_run_inference_simulator`
  functions, also against the real committed artifacts, read-only)
