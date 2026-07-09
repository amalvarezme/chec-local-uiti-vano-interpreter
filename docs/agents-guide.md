# Agents Guide

This is the map for the CHEC-native agent framework. Read this file first if you are new to
`.claude/agents/`, `.claude/skills/`, or `llm/skills_expert_alignment/` — it exists specifically
to stop you from conflating three things that are easy to confuse because they're all informally
called "skills" in conversation.

## The three meanings of "skills" (read this before anything else)

| Term | Artifact | Has frontmatter? | Consumed by |
|---|---|---|---|
| Prompt **playbook** | `llm/skills_expert_alignment/*.md` (existing, pre-dates this framework) | No | `assemble_skill_bundle()` in `chec_local_interpreter.llm_skills`, used by the pre-existing notebook flow |
| Claude Code **Skill** | `.claude/skills/expert-alignment/SKILL.md` (new — lands in WU5b) | Yes | Claude Code's `Skill` tool |
| Agent **role** | `.claude/agents/expert-alignment.md` (new) | Yes | The Claude Code agent runtime (this is what you invoke as a headless/interactive agent) |

Given any file path in this repo, classify it with this rule: does it live under `llm/skills*/`?
It's a **playbook** (prompt content, no frontmatter, only consumed by the notebook-era
`assemble_skill_bundle` helper). Does it live under `.claude/skills/`? It's a **Skill** (has
frontmatter, loaded by the `Skill` tool). Does it live under `.claude/agents/`? It's a **role**
(has frontmatter, defines an agent you can run). If you can't answer from the path alone, you
haven't been given enough information to classify it — ask, don't guess.

Why this distinction exists: the expert-alignment pilot **ports** the three
`llm/skills_expert_alignment/*.md` playbook files into one Claude Code Skill body (see WU5b) —
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
                           .claude/skills/expert-alignment/SKILL.md (Skill, WU5b)
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

## Agent roles

| Role | Status | Role file | Rules | Skill | Tool contract |
|---|---|---|---|---|---|
| `expert-alignment` | Implemented (this slice) | `.claude/agents/expert-alignment.md` | `.claude/agents/rules/invariants.md` | `.claude/skills/expert-alignment/SKILL.md` (WU5b) | `python -m chec_local_interpreter.agent_tools.expert_alignment` |
| historical / base (Agent1) | Stub — not yet ported | — | — | — | Follow-on (out of this slice) |
| inference / SHAP (Agent2) | Stub — not yet ported | — | — | — | Follow-on (out of this slice) |

Only the `expert-alignment` role is implemented in this slice. The historical/base and
inference/SHAP agents are explicitly out of scope here; a dedicated "Follow-on (out of this
slice)" section listing them and the other deferred items is appended to this guide once the
slice's wrap-up work unit runs.

## Related artifacts

- Role definition: [`.claude/agents/expert-alignment.md`](../.claude/agents/expert-alignment.md)
- Rules (binding invariants): [`.claude/agents/rules/invariants.md`](../.claude/agents/rules/invariants.md)
- Claude Code Skill: `.claude/skills/expert-alignment/SKILL.md` — **not created yet**, arrives in
  WU5b (ports `llm/skills_expert_alignment/01_pdf_report_comparison.md`,
  `02_predictive_variable_prioritization.md`, and `03_graph_context_for_alignment.md`).
- L1 deterministic Python: `src/chec_local_interpreter/expert_alignment.py`
- L2 CLI: `src/chec_local_interpreter/agent_tools/expert_alignment.py`
- L4 batch runner: `src/chec_local_interpreter/agent_tools/batch.py`
- Frozen-model guard (tests): `tests/test_frozen_model_guard.py`
