# Agents Guide

This is the map for the CHEC-native agent framework. Read this file first if you are new to
`.claude/agents/`, `.claude/skills/`, or `llm/skills_expert_alignment/` — it exists specifically
to stop you from conflating three things that are easy to confuse because they're all informally
called "skills" in conversation.

## The three meanings of "skills" (read this before anything else)

| Term | Artifact | Has frontmatter? | Consumed by |
|---|---|---|---|
| Prompt **playbook** | `llm/skills_expert_alignment/*.md` (existing, pre-dates this framework) | No | `assemble_skill_bundle()` in `chec_local_interpreter.llm_skills`, used by the pre-existing notebook flow |
| Claude Code **Skill** | `.claude/skills/expert-alignment/SKILL.md` (new) | Yes | Claude Code's `Skill` tool |
| Agent **role** | `.claude/agents/expert-alignment.md` (new) | Yes | The Claude Code agent runtime (this is what you invoke as a headless/interactive agent) |

Given any file path in this repo, classify it with this rule: does it live under `llm/skills*/`?
It's a **playbook** (prompt content, no frontmatter, only consumed by the notebook-era
`assemble_skill_bundle` helper). Does it live under `.claude/skills/`? It's a **Skill** (has
frontmatter, loaded by the `Skill` tool). Does it live under `.claude/agents/`? It's a **role**
(has frontmatter, defines an agent you can run). If you can't answer from the path alone, you
haven't been given enough information to classify it — ask, don't guess.

Why this distinction exists: the expert-alignment pilot **ports** the three
`llm/skills_expert_alignment/*.md` playbook files into one Claude Code Skill body (see
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

`build-context` reads a circuit's inputs from stdin JSON and emits this envelope on stdout:

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
| `1` | A validation failure — schema, provenance, or both (errors are combined). | Not a valid report. The raw response and errors were saved under `reports/interpretability/artifacts/{circuito}/`. Retry with the errors fed back into the prompt, up to the retry limit. Never present this output as final. |
| `2` | The request to `validate` itself was malformed (invalid JSON on stdin, or a missing required field). | This is a wiring/integration defect in how the CLI was invoked — not a content problem with the report. Do not retry it as if it were a validation failure; it means something is wrong with how the agent (or batch runner) is calling the tool. |

## How to run headless

```bash
python -m chec_local_interpreter.agent_tools.batch \
  --circuits path/to/circuits.json \
  [--max-retries 2] \
  [--manifest-out path/to/run-manifest.json]
```

- `--circuits` accepts one or more JSON file paths. Each file contains either a single circuit
  context-build payload (an object with a `circuito` key, shaped like `build-context`'s stdin) or
  a list of such payload objects (a circuits manifest). Multiple `--circuits` arguments
  concatenate, in order.
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
      "artifact_paths": ["reports/interpretability/published/DON23L13.json"],
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
`{circuito, status, artifact_paths, tool_version, timestamp}` shape.

### Manifest `status` values

| Status | Meaning |
|---|---|
| `ok` | The response passed `validate` (schema + provenance) and was published under `reports/interpretability/published/{circuito}.json`. |
| `FAILED` | A validation failure after exhausting retries, an unhandled/unexpected error while building context or invoking the agent, or an infrastructure issue like a missing agent command / invocation timeout — a normal run failure, not published. |
| `AGENT_ERROR` | The agent subprocess itself exited non-zero (auth error, crash) — an infrastructure failure distinct from a validation failure; it does not consume the retry budget, and `error` carries the captured stderr. |
| `SKIPPED_DUPLICATE` | Input hygiene: this `circuito` was already processed earlier in the same batch (by on-disk publish identity, case/punctuation-insensitive) — skipped to avoid silently overwriting the first run's published report. Not a run failure. |

## Agent roles

| Role | Status | Role file | Rules | Skill | Tool contract |
|---|---|---|---|---|---|
| `expert-alignment` | Implemented (this slice) | `.claude/agents/expert-alignment.md` | `.claude/agents/rules/invariants.md` | `.claude/skills/expert-alignment/SKILL.md` | `python -m chec_local_interpreter.agent_tools.expert_alignment` |
| historical / base (Agent1) | Stub — not yet ported | — | — | — | Follow-on (out of this slice) |
| inference / SHAP (Agent2) | Stub — not yet ported | — | — | — | Follow-on (out of this slice) |

Only the `expert-alignment` role is implemented in this slice. The historical/base and
inference/SHAP agents are explicitly out of scope here — see "Follow-on (out of this slice)"
below for the full deferred-work ledger.

## Related artifacts

- Role definition: [`.claude/agents/expert-alignment.md`](../.claude/agents/expert-alignment.md)
- Rules (binding invariants): [`.claude/agents/rules/invariants.md`](../.claude/agents/rules/invariants.md)
- Claude Code Skill: [`.claude/skills/expert-alignment/SKILL.md`](../.claude/skills/expert-alignment/SKILL.md)
  — ports `llm/skills_expert_alignment/01_pdf_report_comparison.md`,
  `02_predictive_variable_prioritization.md`, and `03_graph_context_for_alignment.md`.
- L1 deterministic Python: `src/chec_local_interpreter/expert_alignment.py`
- L2 CLI: `src/chec_local_interpreter/agent_tools/expert_alignment.py`
- L4 batch runner: `src/chec_local_interpreter/agent_tools/batch.py`
- Frozen-model guard (tests): `tests/test_frozen_model_guard.py`
- Offline eval gate (no API call): `llm/evals/run_llm_eval.py` — run it directly with
  `python llm/evals/run_llm_eval.py`; it validates a synthetic expert-alignment response through
  both the schema validator and the provenance validator, alongside the existing base-agent eval
  case in the same file.

## Follow-on (out of this slice)

This slice ports the expert-alignment pilot only. The following items are explicitly deferred,
listed verbatim from the design's own "Open items carried to tasks" and "Rejected alternatives"
sequencing:

- **(a) `llm_client.py` multi-provider retirement** (google/openai/ollama branches) — blocked on
  (b); do not start this before the characterization tests below exist.
- **(b) Characterization tests for `web_export.py` and `graph_extractor.py`** (golden-file on
  `interpretabilidad.json` / `src/assets/site/results/*` shape) — required BEFORE any
  `llm_client.py` removal, since both currently have zero tests and must not regress silently.
- **(c) Agent1 (historical/base) and Agent2 (inference/SHAP) ports** to the agent-role pattern
  this slice establishes for `expert-alignment` — stubs only in the Agent roles table above.
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
frozen-model guard (no automated check); deleting `llm_client.py` in this pilot; and adding
provenance fields to the base agent's `output_schema.json` in this slice (that schema's
`additionalProperties: false` risks breaking existing base-agent fixtures — deferred to whenever
the base agent itself is ported).

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
| 3 | WARNING | The causal-language guard (`validar_respuesta_expert_alignment` in `expert_alignment.py`) uses the regex `\bcausa\b`, which correctly rejects the singular noun "causa" but does not catch the plural "causas" (e.g. "las causas probables") or adjective forms "causal"/"causales" (e.g. "existe una relación causal"). | An LLM response phrases a causal claim using the plural or adjective form instead of the bare singular noun. | **CLOSED** — the shared `src/chec_local_interpreter/causal_language.py::find_causal_language` broadens matching to plural/adjective/participle/noun forms (`causa(s)`, `causal(es)`, `causante(s)`, `causad[oa](s)`, `causalidad(es)`, `causó/causo`), while still excluding unrelated words like `encausar`. Used by both `expert_alignment.py`'s validator and `llm_validation._guardrail_errors` (closing the base agent's latent gap too). Pinned by `tests/test_causal_language.py` and `tests/test_expert_alignment.py`. |
| 4 | WARNING (theoretical, not currently reachable) | `atomic_write_text` (`agent_tools/_atomic_io.py`) reads and restores the process umask non-atomically (`os.umask(0)` then `os.umask(mask)`), which is not thread-safe. | Batch processing is currently strictly sequential (`run_batch` has no concurrency), so this is currently harmless. Would become a real, narrow permissions-widening race only if batch processing is ever parallelized. | Flagged for whoever parallelizes the batch runner in the future. |
| 5 | WARNING (theoretical, not currently reachable) | In `main()` (`agent_tools/expert_alignment.py`), if JSON serialization of the response raises partway through writing to stdout, the exception handler could write a second JSON document after a partial first one, violating the "exactly one JSON document on stdout" contract. | Not reachable via any current input path (all fields are pre-validated JSON-safe types). | Worth hardening (e.g. serialize to a string first, write once) if new fields are ever added. |
| 6 | SUGGESTION | The batch runner's `--manifest-out` write (`agent_tools/batch.py`) uses a plain `Path.write_text()` instead of the shared `atomic_write_text` helper used everywhere else (`_publish_report`, `_write_failure_artifact`). A crash mid-write could leave a truncated manifest file. | Pre-existing, not introduced by any Judgment Day round. | Low-severity cleanup; grouped with the other follow-on items rather than fixed in isolation. |

Items #1–#3 are closed as of the `historical-inference-agents` change's Slice 1a. Items #4–#6
remain open follow-on work; none are blocking.
