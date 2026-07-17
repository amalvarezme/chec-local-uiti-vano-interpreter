# Agents Guide

This is the map for the CHEC-native agent framework. Read this file first if you are new to
`.claude/agents/`, `.claude/skills/`, or the per-agent `.claude/skills/<agent>/prompt/` playbook
subdirectories — it exists specifically to stop you from conflating three things that are easy to
confuse because they're all informally called "skills" in conversation.

## The three meanings of "skills" (read this before anything else)

| Term | Artifact | Has frontmatter? | Consumed by |
|---|---|---|---|
| Prompt **playbook** | `.claude/skills/<agent>/prompt/*.md` (relocated from the retired top-level `llm` directory, see `sdd/retire-llm-directory`) | No | `assemble_skill_bundle()` in `chec_local_interpreter.llm_skills`, used by the pre-existing notebook flow |
| Claude Code **Skill** | `.claude/skills/expert-alignment/SKILL.md` (new) | Yes | Claude Code's `Skill` tool |
| Agent **role** | `.claude/agents/expert-alignment.md` (new) | Yes | The Claude Code agent runtime (this is what you invoke as a headless/interactive agent) |

Shared prompt templates and output-schema JSON that are not agent-specific playbooks (the
historical/base agent's system/user templates and the output schemas consumed by
`llm_contracts.py`/`inference_validation.py`) live in
`src/chec_local_interpreter/prompt_assets/` — a package-relative, code-owned home resolved off
`__file__`, not a fourth "meaning of skills."

Given any file path in this repo, classify it with this rule: does it live under
`.claude/skills/<agent>/prompt/`? It's a **playbook** (prompt content, no frontmatter, only
consumed by the notebook-era `assemble_skill_bundle` helper). Is it `.claude/skills/<agent>/SKILL.md`
itself (directly under `.claude/skills/<agent>/`, not inside `prompt/`)? It's a **Skill** (has
frontmatter, loaded by the `Skill` tool). Does it live under `.claude/agents/`? It's a **role**
(has frontmatter, defines an agent you can run). If you can't answer from the path alone, you
haven't been given enough information to classify it — ask, don't guess.

Why this distinction exists: the expert-alignment pilot **ports** the three
`.claude/skills/expert-alignment/prompt/*.md` playbook files into one Claude Code Skill body (see
[`.claude/skills/expert-alignment/SKILL.md`](../.claude/skills/expert-alignment/SKILL.md)) —
it does **not** delete the playbooks (the notebook flow still consumes them) and it does **not**
duplicate their content by hand — the Skill is authored by porting, once, from the playbooks.

## The 4-layer architecture

```
[L1 Deterministic Python]  chec_local_interpreter.expert_alignment
                           Frozen behavior: load the Excel of expert PDF discussions, extract
                           dates, select the top temporal matches, build context, build the
                           prompt, VALIDATE the agent's JSON response. Selection/detection never
                           moves out of this layer.
        |  in-process import
[L2 Tool-adapter CLI]      python -m chec_local_interpreter.agent_tools.expert_alignment
                           Verbs:
                             build-context  -> emits the envelope (context + prompt + allowed sets)
                             validate       -> runs the L1 validators, writes a failure artifact on
                                               error, returns an exit code (see "Exit codes" below)
        |  Bash tool: stdin/stdout, JSON only
[L3 Claude Code agent]     .claude/agents/expert-alignment.md (role) +
                           .claude/skills/expert-alignment/SKILL.md (Skill)
                           Reads the envelope -> reasons/authors the 7-key JSON + provenance ->
                           calls `validate` -> retries on failure, up to the retry limit.
        |
[L4 Batch orchestration]   python -m chec_local_interpreter.agent_tools.batch
                           One isolated agent invocation per circuit, a run manifest, and it
                           never publishes invalid output.
```

**Why a CLI boundary, not a direct import.** The agent shells out to a whitelisted command over
JSON; it never imports Python directly, so it *structurally cannot* open the model artifact or
call the restricted model-fitting code (see `.claude/agents/rules/invariants.md`, Rule 1, and
`tests/test_frozen_model_guard.py`). Frozen-model safety is a property of the wiring, not a
promise in a docstring.

## The envelope contract (L1 -> L2 -> L3)

`build-context` reads the already-built
`expert_alignment.construir_contexto_expert_alignment(...)` JSON directly from stdin (no raw
circuit/date inputs, deterministic selection/assembly stays entirely upstream in
`report_pipeline.prepare_expert_alignment()` — Rule 2) and emits this envelope on stdout:

```json
{
  "meta": {"circuito": "...", "periodo": {"inicio": "YYYY-MM-DD", "fin": "YYYY-MM-DD"}, "tool_version": "expert-alignment-agent-tools/0.1.0"},
  "context": { "...": "compact context, from compactar_contexto_expert_alignment_para_prompt" },
  "prompt": "the full prompt string, from construir_prompt_expert_alignment",
  "allowed": {
    "dates": ["2026-01-09", "2026-01-10", "..."],
    "variables": ["CNT_TRF", "..."],
    "pdf_row_indexes": ["3", "..."],
    "sources": ["Agente Descriptor", "Agente predictivo", "..."]
  }
}
```

`allowed` is precomputed so the agent knows its citable universe up front — the same sets gate
`validate` afterwards, so nothing the agent didn't already see can pass. The agent authors the 7
required keys (`contexto`, `coincidencias`, `diferencias`, `hallazgos_expertos_no_cubiertos`,
`hallazgos_modelo_no_respaldados_por_pdf`, `variables_a_priorizar`, `sintesis_final`) plus an
optional `provenance` object per claim (see "Provenance" below), and hands the result to
`validate` as `{"response_text": "<the JSON string>", "context": <the envelope's "context">}`.

### Provenance (additive, optional per claim)

Each item in `coincidencias`, `diferencias`, or `variables_a_priorizar` MAY carry:

```json
"provenance": {
  "data_ref": ["2026-01-10", "CNT_TRF", "pdf_row_index:3"],
  "agent": "expert-alignment",
  "rule": "02_predictive_variable_prioritization"
}
```

`data_ref` entries must resolve against the envelope's own `allowed` sets. `agent` must equal
`expert-alignment`. `rule` must be one of the three playbook ids ported into the Skill:
`01_pdf_report_comparison`, `02_predictive_variable_prioritization`,
`03_graph_context_for_alignment`. Omitting `provenance` never fails validation (it's additive,
not required) — but every claim that traces back to a specific date/variable/PDF row should carry
one.

### Exit codes from `validate`

| Exit code | Meaning | What it means for the caller |
|---|---|---|
| `0` | Both the schema validator and the provenance validator passed. | The response is a valid report; publish it. |
| `1` | A validation failure — schema, provenance, or both (errors are combined). | Not a valid report. The raw response and errors were saved under the agent's own artifacts root (`reports/interpretability/artifacts/{circuito}/` for expert-alignment, `reports/interpretability/artifacts/historical/{circuito}/` for the historical agent). Retry with the errors fed back into the prompt, up to the retry limit. Never present this output as final. |
| `2` | The request to `validate` (or `build-context`) itself was malformed (invalid/empty JSON on stdin, a non-object payload, or a missing required field). | This is a wiring/integration defect in how the CLI was invoked — not a content problem with the report. Do not retry it as if it were a validation failure; it means something is wrong with how the agent (or batch runner) is calling the tool. |
| `3` | An unexpected error — anything else, including a genuinely unanticipated failure while reading/parsing stdin (e.g. non-UTF-8 bytes) or while running the verb's own handler. | The full traceback is logged to stderr only; stdout still contains exactly one JSON document (`{"ok": false, "errors": [...]}`), via the shared `agent_tools/cli_support.py::dispatch` contract both CLIs delegate to. Treat this as an infrastructure/bug signal, not a content problem with the report. |

## The historical/base agent's envelope contract (L1 -> L2 -> L3)

The historical agent's `build-context` reads the already-built
`context_builder.build_context_package(...)` JSON directly from stdin (no DataFrames, deterministic
selection stays entirely upstream — Rule 2) and emits this envelope on stdout:

```json
{
  "meta": {"circuito": "...", "tool_version": "historical-agent-tools/0.1.0"},
  "context": { "...": "the same context_builder.build_context_package(...) output, unchanged" },
  "prompt": "the full prompt string, from render_prompt(..., skill_bundle=assemble_skill_bundle(profile=\"base\"))",
  "allowed": {
    "dates": ["2026-01-01", "2026-01-02", "..."],
    "critical_point_ids": ["cp-2026-01-02", "..."],
    "unavailable_columns": ["..."]
  }
}
```

`meta.circuito` is `"_".join(context["metadata"]["circuitos"])` — the same multi-circuit join
convention used elsewhere in the codebase. The agent authors the ten required base keys (`source`,
`prompt_version`, `headline`, `section_title`, `executive_summary`, `key_findings`,
`circuit_characterization`, `period_synthesis`, `data_gaps`, `recommended_actions`) plus an
optional per-`key_finding` `provenance` object (see below), and hands the result to `validate` as
`{"response_text": "<the JSON string>", "context": <the envelope's "context">}`.

### Historical provenance (additive, optional per `key_finding`)

Each item in `key_findings` MAY carry:

```json
"provenance": {
  "data_ref": ["2026-01-02", "cp-2026-01-02", "UITI_VANO"],
  "agent": "historical",
  "rule": "03_uiti_vano_behavior_explainer"
}
```

`data_ref` entries resolve against the envelope's own `allowed` sets (dates, critical-point ids) or
the context's `domain.variable_groups` variable universe (never a variable marked unavailable for
that context). `agent` must equal `historical`. `rule` must be one of the seven base playbook ids
ported into `.claude/skills/historical/SKILL.md`: `01_structured_context_builder`,
`02_critical_point_interpreter`, `03_uiti_vano_behavior_explainer`, `04_domain_grounding_guardrails`,
`05_llm_output_validator`, `06_base_repair`, `07_base_output_contract`. Omitting `provenance` never
fails validation (it's additive, not required).

The historical agent's `validate` verb runs a **two-stage gate**: the schema/guardrail validator
(`validate_llm_response`, reused unmodified) first, then — only if that passes — the additive
provenance validator (`validar_provenance_base`), combining both error lists. Exit code `0`
requires both stages to pass; failure artifacts are written under
`reports/interpretability/artifacts/historical/{circuito}/`.

## How to run headless

```bash
python -m chec_local_interpreter.agent_tools.batch \
  --circuits path/to/circuits.json \
  [--agent expert-alignment|historical|inference] \
  [--max-retries 2] \
  [--manifest-out path/to/run-manifest.json]
```

- `--circuits` accepts one or more JSON file paths. Each file contains either a single circuit
  context-build payload (an object with a `circuito` key, shaped like the selected agent's
  `build-context` stdin) or a list of such payload objects (a circuits manifest). Multiple
  `--circuits` arguments concatenate, in order.
- `--agent` selects which registered `AgentSpec` to run (default `expert-alignment`); the three
  registered roles today are `expert-alignment`, `historical`, and `inference`.
- `--max-retries` overrides `MAX_VALIDATION_RETRIES` (default `2`) without a code change.
- `--manifest-out` additionally writes the run manifest to a file (it is always printed to
  stdout).
- The batch runner's agent command is injectable (`DEFAULT_AGENT_COMMAND = ("claude", "-p")` in
  `agent_tools/batch.py`) — this is the point where the L3 agent-role wiring plugs in.
- A circuit that fails every retry is marked `FAILED` and the batch **continues** to the next
  circuit — it never aborts. If the configured agent command isn't on `PATH`, or the invocation
  times out, the circuit is marked `FAILED` with a clear `error` string in the manifest, not a
  crash.
- The batch process's own exit code is `1` if any circuit failed, `0` if every circuit succeeded.

### Run manifest shape

```json
{
  "tool_version": "expert-alignment-agent-tools/0.1.0",
  "generated_at": "20260709T120000Z",
  "circuits": [
    {
      "circuito": "DON23L13",
      "status": "ok",
      "artifact_paths": ["reports/interpretability/published/expert-alignment/DON23L13.json"],
      "tool_version": "expert-alignment-agent-tools/0.1.0",
      "timestamp": "20260709T120000Z",
      "retries": 0
    },
    {
      "circuito": "OTHER01",
      "status": "FAILED",
      "artifact_paths": ["reports/interpretability/artifacts/OTHER01/invalid_....json"],
      "tool_version": "expert-alignment-agent-tools/0.1.0",
      "timestamp": "20260709T120005Z",
      "retries": 2,
      "error": "validation failed after exhausting retries",
      "errors": ["..."]
    }
  ]
}
```

`retries`, `error`, and `errors` are additive fields on top of the base
`{circuito, status, artifact_paths, tool_version, timestamp}` shape. The published path is always
role-namespaced (`published/{agent_role}/{circuito}.json`, per `AgentSpec.role` — spec:
agent-namespaced-reports) so two agents processing the same circuit can never overwrite each
other's report; `--agent` selects which registered `AgentSpec` (`expert-alignment`, `historical`,
or `inference`) the batch runner uses, defaulting to `expert-alignment`.

### Manifest `status` values

| Status | Meaning |
|---|---|
| `ok` | The response passed `validate` (schema + provenance) and was published under `reports/interpretability/published/{agent_role}/{circuito}.json`. |
| `FAILED` | A validation failure after exhausting retries, an unhandled/unexpected error while building context or invoking the agent, or an infrastructure issue like a missing agent command / invocation timeout — a normal run failure, not published. |
| `AGENT_ERROR` | The agent subprocess itself exited non-zero (auth error, crash) — an infrastructure failure distinct from a validation failure; it does not consume the retry budget, and `error` carries the captured stderr. |
| `SKIPPED_DUPLICATE` | Input hygiene: this `circuito` was already processed earlier in the same batch (by on-disk publish identity, case/punctuation-insensitive) — skipped to avoid silently overwriting the first run's published report. Not a run failure. |

## Agent roles

| Role | Status | Role file | Rules | Skill | Tool contract |
|---|---|---|---|---|---|
| `expert-alignment` | Implemented | `.claude/agents/expert-alignment.md` | `.claude/agents/rules/invariants.md` | `.claude/skills/expert-alignment/SKILL.md` | `python -m chec_local_interpreter.agent_tools.expert_alignment` |
| `historical` / base (Agent1) | Implemented (`historical-inference-agents` change, Slice 1b) | `.claude/agents/historical.md` | `.claude/agents/rules/invariants.md` | `.claude/skills/historical/SKILL.md` | `python -m chec_local_interpreter.agent_tools.historical` |
| `inference` / MGCECDL-SHAP (Agent2) | Implemented (`report-command-pipeline` change, Slice A) | `.claude/agents/inference.md` | `.claude/agents/rules/invariants.md` | `.claude/skills/inference/SKILL.md` | `python -m chec_local_interpreter.agent_tools.inference` |

`expert-alignment`, `historical`, and `inference` are all implemented and registered in
`agent_tools/batch.py`'s `AGENT_SPECS`. The inference agent's validator
(`inference_validation.validar_respuesta_inferencia_strict` + `validar_provenance_inferencia`)
reaches expert-alignment-grade rigor per the constraint recorded in
`sdd/historical-inference-agents/spec` — full 9-key schema coverage (jsonschema
`additionalProperties: false`), dedicated test files
(`tests/test_inference_validation_strict.py`, `tests/test_agent_tools_inference.py`), and the
shared provenance-core wrapper — replacing the old frozen, 2-of-9-key
`chec_impacto.interpretability.circuit_analysis.validar_respuesta_inferencia` for every code path
governed by this framework (that frozen function itself is untouched and still covered by its own
`tests/test_inference_validation.py`).

## Related artifacts

### expert-alignment

- Role definition: [`.claude/agents/expert-alignment.md`](../.claude/agents/expert-alignment.md)
- Rules (binding invariants): [`.claude/agents/rules/invariants.md`](../.claude/agents/rules/invariants.md)
- Claude Code Skill: [`.claude/skills/expert-alignment/SKILL.md`](../.claude/skills/expert-alignment/SKILL.md)
  — ports `.claude/skills/expert-alignment/prompt/01_pdf_report_comparison.md`,
  `02_predictive_variable_prioritization.md`, and `03_graph_context_for_alignment.md`.
- L1 deterministic Python: `src/chec_local_interpreter/expert_alignment.py`
- L2 CLI: `src/chec_local_interpreter/agent_tools/expert_alignment.py`

### historical

- Role definition: [`.claude/agents/historical.md`](../.claude/agents/historical.md)
- Rules (binding invariants, shared with expert-alignment): [`.claude/agents/rules/invariants.md`](../.claude/agents/rules/invariants.md)
- Claude Code Skill: [`.claude/skills/historical/SKILL.md`](../.claude/skills/historical/SKILL.md)
  — ports `.claude/skills/historical/prompt/01_structured_context_builder.md`,
  `02_critical_point_interpreter.md`, `03_uiti_vano_behavior_explainer.md`,
  `04_domain_grounding_guardrails.md`, `05_llm_output_validator.md`, `06_base_repair.md`, and
  `07_base_output_contract.md`.
- L1 deterministic Python: `src/chec_local_interpreter/context_builder.py`,
  `src/chec_local_interpreter/llm_contracts.py`, `src/chec_local_interpreter/llm_validation.py`
  (`validar_provenance_base` and the public `allowed_dates`/`allowed_critical_point_ids`/
  `unavailable_columns` accessors)
- L2 CLI: `src/chec_local_interpreter/agent_tools/historical.py`

### inference

- Role definition: [`.claude/agents/inference.md`](../.claude/agents/inference.md)
- Rules (binding invariants, shared with expert-alignment/historical): [`.claude/agents/rules/invariants.md`](../.claude/agents/rules/invariants.md)
- Claude Code Skill: [`.claude/skills/inference/SKILL.md`](../.claude/skills/inference/SKILL.md)
  — ports `.claude/skills/inference/prompt/01_structured_context_builder.md`,
  `02_circuit_scenario_interpreter.md`, `03_uiti_vano_behavior_explainer.md`,
  `04_graph_connectivity_guardrails.md`, `05_llm_output_validator.md`, and
  `06_inference_output_contract.md`.
- L1 deterministic Python: `src/chec_local_interpreter/inference_validation.py`
  (`validar_respuesta_inferencia_strict`, `validar_provenance_inferencia`, and the public
  `allowed_dates`/`allowed_critical_point_ids`/`allowed_variables`/`allowed_scenario_names`
  accessors), `src/chec_local_interpreter/prompt_assets/inference.output_schema.json`
- L2 CLI: `src/chec_local_interpreter/agent_tools/inference.py`
- Frozen boundary: the L1/L2 layers above never import the frozen
  `chec_impacto.interpretability.circuit_analysis` module's model-implementation subpackage or its
  weak `validar_respuesta_inferencia` — that function stays untouched and is still covered by its
  own `tests/test_inference_validation.py`; the new strict validator is a separate, additive
  module living inside `chec_local_interpreter`.

### Shared

- Canonical circuit identity: `src/chec_local_interpreter/circuit_identity.py`
- Shared L2 CLI stdin/dispatch contract: `src/chec_local_interpreter/agent_tools/cli_support.py`
- L4 batch runner (`AgentSpec`-generalized): `src/chec_local_interpreter/agent_tools/batch.py`
- Frozen-model guard (tests): `tests/test_frozen_model_guard.py`
- Offline eval gate (no API call): `evals/run_llm_eval.py` — run it directly with
  `python evals/run_llm_eval.py`; it validates synthetic expert-alignment AND historical
  responses (including a resolving-provenance case for each) through both the schema validator and
  their respective provenance validators, alongside the pre-existing base-agent eval case in the
  same file.

### Report orchestrator (multi-runtime adapters)

The full report entry point is runtime-native but contract-compatible across supported coding-agent
runtimes:

| Runtime | Invocation |
|---|---|
| Claude Code | `/report <circuito> [fecha_inicio fecha_fin]` |
| OpenCode | `@report <circuito> [fecha_inicio fecha_fin]` fallback until project slash commands are verified |
| Codex | `$report <circuito> [fecha_inicio fecha_fin]` |
| Pi / el Gentleman | `/skill:report <circuito> [fecha_inicio fecha_fin]` |

This report entry point is **not** a fourth entry in the "Agent roles" table above — it does not
itself author or validate one persona's JSON output, so it does not fit that table's L1/L2/L3/L4
shape. It is a thin runtime adapter over a shared contract that sequences the existing agent roles
(`historical` -> `inference` -> `auto-simulator` -> `expert-alignment`, with the first three
parallel-capable where supported) around a pure-Python, LLM-call-free orchestrator, and produces the
final local HTML report.

- Shared contract: [`src/chec_local_interpreter/report_contract.py`](../src/chec_local_interpreter/report_contract.py)
  — normalizes runtime requests, preflight outcomes, metadata, and JSON lifecycle states.
- Claude Code Skill (runbook): [`.claude/skills/report/SKILL.md`](../.claude/skills/report/SKILL.md).
- OpenCode fallback adapter: [`.opencode/agent/report.md`](../.opencode/agent/report.md).
- Codex skill adapter: [`.codex/skills/report/SKILL.md`](../.codex/skills/report/SKILL.md).
- Pi skill adapter: [`.pi/skills/report/SKILL.md`](../.pi/skills/report/SKILL.md).
- Runtime contract docs: [`docs/report-runtime-contract.md`](report-runtime-contract.md).
- Orchestrator (L1, pure Python, no LLM call in this module):
  `src/chec_local_interpreter/report_pipeline.py` — `preflight(circuito, fecha_inicio=None,
  fecha_fin=None) -> ReportPreflight`, `prepare(circuito, fecha_inicio=None, fecha_fin=None) -> Path`,
  `prepare_expert_alignment(run_dir) -> Path`, `render(run_dir) -> Path`.
- Per-circuit date-range default: `data_loader.circuit_date_range(frame, circuito)`.
- Argument contract: `circuito` required; `fecha_inicio`/`fecha_fin` optional as a pair — giving
  exactly one is a usage error, rejected by `prepare` itself (`ReportPipelineError`) before touching
  the dataset, not just documented in the Skill.
- Supersedes phases 1-8 of `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`
  (deprecated in place, not deleted — see that notebook's own top cell); phases 9-11 are untouched.
- Tests: `tests/test_report_pipeline.py`.

**Per-stage usage and duration accounting.** `token_usage.json` (per-stage `{"total": n}` or
`{"input": n, "output": n}`) and the newer `stage_timing.json` (per-stage `{"duration_seconds":
float}`) are two independent, optional sidecars written into `run_dir` by the `record-usage` and
`record-duration` CLI verbs (`report_contract.py`), respectively. `record-usage` captures the
sub-agent's own reported token total (Claude Code's `Agent` tool completion notification's
`subagent_tokens` field, or Pi's `subagent_run` result's `usage` field); `record-duration` captures
the orchestrating Skill's own wall-clock delta around each stage's dispatch — a source that does not
depend on any field the sub-agent returns, so it is available identically on both Claude Code and
Pi. Both verbs are additive and never gate run success: a stage missing either sidecar entry
degrades to an estimate (tokens: `chars // 4`) or `N/D` (duration), never an error. There is
deliberately no `verify-duration` counterpart to `verify-usage` — duration never participates in
the strict fail-closed token-verification path. At render time, `report_pipeline.render()` resolves
both sidecars per stage and passes a `stage_breakdown` list into
`plotting.render_llm_analysis`, which renders it as a per-stage table (Etapa / Tokens / Tiempo) for
each of `historical`/`inference`/`auto-simulator`/`expert-alignment`, shown beneath the pre-existing
whole-run totals line (`tokens_total` + `elapsed_seconds`) — the whole-run line is preserved
unchanged, not replaced. Both sidecars are optional and backward-compatible: their absence in older
`run_dir`s renders identically to before this accounting existed.

**Non-goal: OpenCode is out of scope for this accounting.** The `record-usage`/`record-duration`
capture instructions above are wired into the Claude Code (`.claude/skills/report/SKILL.md`) and Pi
(`.pi/skills/report/SKILL.md`) runbooks only. OpenCode's fallback adapter
(`.opencode/agent/report.md`) does not receive matching capture instructions, and its generic
worker/subagent completion notification has not been investigated for an equivalent token/duration
signal — this is a deliberate, documented gap (not an oversight), left for a future change if
OpenCode's subagent API is confirmed to expose one.

### Standalone circuit-clustering chart (multi-runtime adapters)

The standalone circuit-clustering chart is also runtime-native and local-only:

| Runtime | Invocation |
|---|---|
| Claude Code | `/agrupamiento-circuitos [fecha_inicio fecha_fin]` |
| OpenCode | `@agrupamiento-circuitos [fecha_inicio fecha_fin]` |
| Pi / el Gentleman | `/skill:agrupamiento-circuitos [fecha_inicio fecha_fin]` |

This entry point renders only the circuit-clustering HTML, not the full report. It is a thin adapter
over a shared contract that resolves the date window, asks the user to confirm it, then reuses
`plot_interactive_circuit_clustering` to write a standalone local HTML artifact.

- Shared contract: `src/chec_local_interpreter/circuit_clustering_contract.py`.
- Claude Code skill: `.claude/skills/agrupamiento-circuitos/SKILL.md`.
- OpenCode adapter: `.opencode/agent/agrupamiento-circuitos.md`.
- Pi skill: `.pi/skills/agrupamiento-circuitos/SKILL.md`.
- Date behavior: dates are optional as a pair; omitting both resolves the full dataset range, which
  must be confirmed with the user before render.
- Output: local standalone HTML only; no publishing and no site-asset mutation.
- Plot source of truth: `src/chec_local_interpreter/plotting.py::plot_interactive_circuit_clustering`.

## Follow-on (out of this slice)

Agent2 (inference/SHAP) remains unported. The following items are explicitly deferred, listed
verbatim from the design's own "Open items carried to tasks" and "Rejected alternatives"
sequencing:

- **(a) `llm_client.py` multi-provider retirement** (google/openai/ollama branches) — blocked on
  (b); do not start this before the characterization tests below exist.
- **(b) Characterization tests for `web_export.py` and `graph_extractor.py`** (golden-file on
  `interpretabilidad.json` / `src/assets/site/results/*` shape) — required BEFORE any
  `llm_client.py` removal, since both currently have zero tests and must not regress silently.
- **(c) Agent2 (inference/SHAP) port** to the agent-role pattern established for `expert-alignment`
  and `historical` — stub only in the Agent roles table above. Its validator MUST reach
  expert-alignment-grade rigor (full 9-key coverage, dedicated test files) before it can be called
  "Implemented" — it MUST NOT ship with today's 2-of-9-key `validar_respuesta_inferencia`. (Note:
  this item previously also required "the shared causal-language fix" — that guard was
  subsequently removed from the codebase in a later, separate change; see Known Limitation #3
  below.)
- **(d) Expert-Correction Metric measurement** — requires observing real CHEC domain-expert
  correction rates over time; cannot be satisfied by a one-time code change, so it stays open
  indefinitely until that observation process exists.
- **(e) Retry-count tuning** based on observed `claude -p` run behavior — starting point is
  `MAX_VALIDATION_RETRIES = 2` (see WU4 / `agent_tools/batch.py`), exposed as an overridable
  `--max-retries` CLI flag precisely so this tuning needs no code change later.

Also recorded, for completeness (rejected during design, not follow-on work — do not revisit
without a new proposal): an MCP tool server for the Python tools (adds a server/framework surface
adjacent to the FastAPI prohibition); an additional LLM-provider branch in `llm_client.py`; a
parallel provenance/vector store (violates the no-RAG/vector-store prohibition); a convention-only
frozen-model guard (no automated check); and deleting `llm_client.py` in this pilot.

*Historical note*: an earlier revision of this section deferred adding provenance fields to the
base agent's `output_schema.json` "until the base agent itself is ported" — that porting has now
happened (`historical-inference-agents` change, Slice 1b): `provenance` is an additive, optional
per-`key_finding` property (see "The historical/base agent's envelope contract" above), so the
`additionalProperties: false` concern that motivated the original deferral was resolved by making
the new property explicit and optional, not by working around it.

## Known Limitations (Pilot Slice)

Four rounds of Judgment Day adversarial dual-review ran against this slice. Rounds 1–3 findings
were fixed and re-verified. The Round 4 findings below were consciously accepted as known
limitations rather than fixed in this slice — each is narrow, has a concrete trigger condition,
and is cheaper to fix correctly as follow-on work than to patch under review pressure. Items
#1–#3 were subsequently CLOSED by the `historical-inference-agents` change's shared-infra
hardening slice (Slice 1a): see the "Closed" column below.

| # | Severity | Description | Trigger | Status |
|---|---|---|---|---|
| 1 | CRITICAL | `_write_failure_artifact` (`agent_tools/expert_alignment.py`) derives its artifact directory from `sanitize_circuito_dirname(circuito)` alone, while the batch runner's publish/dedup path (`agent_tools/batch.py`) uses the fuller `_canonical_circuit_identity` (sanitize + `normalizar_circuito`). Circuits whose raw `circuito` differs only by case/punctuation (e.g. `"don23l13"`, `"DON23L13"`, `"DON-23-L13"`) write validation-failure artifacts to different directories even though they publish to the same canonical filename on success. | A circuit's raw ID varies in case/punctuation across runs and validation fails. | **CLOSED** — `canonical_circuit_identity` now lives in the single shared module `src/chec_local_interpreter/circuit_identity.py`, imported by both `_write_failure_artifact` and `agent_tools/batch.py` (`_publish_report`/`_dedupe_key`). A regression test (`test_write_failure_artifact_directory_matches_canonical_publish_identity` in `tests/test_agent_tools_expert_alignment.py`) pins the two paths converging. |
| 2 | CRITICAL | The standalone L2 CLI's `main()` (`agent_tools/expert_alignment.py`) only wraps the `build-context`/`validate` verb dispatch in its Round 3 catch-all (exit code 3); it does not wrap the earlier stdin-loading/payload-parsing step. Malformed byte sequences on stdin (e.g. non-UTF-8 bytes) crash uncaught with an interpreter traceback: empty stdout, exit code 1 (Python's default), which collides with the documented "exit 1 = validation failure" contract. | The direct CLI (not the batch runner) receives non-UTF-8 or otherwise unparseable bytes on stdin. | **CLOSED** — `main()` now delegates entirely to the shared `agent_tools/cli_support.py::dispatch`, which wraps stdin loading (`load_stdin_object`) AND verb dispatch inside the same outer catch-all, guaranteeing exactly one JSON document on stdout with the correct 0/1/2/3 exit code on every path. Pinned by `tests/test_cli_support.py`. |
| 3 | WARNING | The causal-language guard (`validar_respuesta_expert_alignment` in `expert_alignment.py`) uses the regex `\bcausa\b`, which correctly rejects the singular noun "causa" but does not catch the plural "causas" (e.g. "las causas probables") or adjective forms "causal"/"causales" (e.g. "existe una relación causal"). | An LLM response phrases a causal claim using the plural or adjective form instead of the bare singular noun. | **CLOSED** (historical — subsequently REMOVED, see note below) — the shared `src/chec_local_interpreter/causal_language.py::find_causal_language` broadened matching to plural/adjective/participle/noun forms (`causa(s)`, `causal(es)`, `causante(s)`, `causad[oa](s)`, `causalidad(es)`, `causó/causo`), while still excluding unrelated words like `encausar`. Was used by both `expert_alignment.py`'s validator and `llm_validation._guardrail_errors` (closing the base agent's latent gap too). Was pinned by `tests/test_causal_language.py` and `tests/test_expert_alignment.py`. **Note (added later, documentation-only correction): this guard, its module, and the two pinning test files were deliberately removed in a later, separate change (not part of this table's original slice). The causal-language guard no longer exists in `llm_validation.py` or `expert_alignment.py`, and `src/chec_local_interpreter/causal_language.py` / `tests/test_causal_language.py` no longer exist. This row is kept for historical record of the original fix; it no longer reflects the current codebase.** |
| 4 | WARNING (theoretical, not currently reachable) | `atomic_write_text` (`agent_tools/_atomic_io.py`) reads and restores the process umask non-atomically (`os.umask(0)` then `os.umask(mask)`), which is not thread-safe. | Batch processing is currently strictly sequential (`run_batch` has no concurrency), so this is currently harmless. Would become a real, narrow permissions-widening race only if batch processing is ever parallelized. | Flagged for whoever parallelizes the batch runner in the future. |
| 5 | WARNING (theoretical, not currently reachable) | In `main()` (`agent_tools/expert_alignment.py`), if JSON serialization of the response raises partway through writing to stdout, the exception handler could write a second JSON document after a partial first one, violating the "exactly one JSON document on stdout" contract. | Not reachable via any current input path (all fields are pre-validated JSON-safe types). | Worth hardening (e.g. serialize to a string first, write once) if new fields are ever added. |
| 6 | SUGGESTION | The batch runner's `--manifest-out` write (`agent_tools/batch.py`) uses a plain `Path.write_text()` instead of the shared `atomic_write_text` helper used everywhere else (`_publish_report`, `_write_failure_artifact`). A crash mid-write could leave a truncated manifest file. | Pre-existing, not introduced by any Judgment Day round. | Low-severity cleanup; grouped with the other follow-on items rather than fixed in isolation. |

Items #1–#3 are closed as of the `historical-inference-agents` change's Slice 1a. Items #4–#6
remain open follow-on work; none are blocking.
