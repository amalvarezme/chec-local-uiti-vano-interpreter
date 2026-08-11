---
name: report
description: "Run the full end-to-end CHEC UITI_VANO report pipeline for one circuit: deterministic data prep, the historical/base diagnosis over the window series, the inference interpretation of the MIL bag model, expert-alignment comparison, and the final HTML report. Three agents, one model. Trigger: /report, /reporte legacy alias, full circuit report, end-to-end interpretability run."
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
    - .claude/skills/vault-circuito/SKILL.md
---

## Overview

`/report` is the canonical entry point for the whole CHEC UITI_VANO local-interpretability flow. It
is **different in kind** from `historical`/`inference`/`expert-alignment`: those three are
single-agent role Skills — each one authors and validates one JSON envelope for one persona. This
Skill does not author a report itself. It is the **orchestrating runbook**: a step-by-step sequence
that runs the deterministic Python stages in
[`report_pipeline.py`](../../../src/chec_local_interpreter/report_pipeline.py) and, between them,
invokes the three existing agent Skills in order, so the run_dir on disk carries validated JSON
from one stage to the next. Read this Skill top to bottom as a checklist, not as reasoning
guidance — the actual domain reasoning for each stage lives in that stage's own Skill
(`historical`, `inference`, `expert-alignment`).

Supersedes the interactive notebook `the retired interactive notebook` in full. That notebook
was deleted once this Skill's coverage was proven equivalent (see git history).

**The model changed, and with it the unit.** The predictive layer used to be MGCECDL scoring one
ROW per event; it is now the **MIL bag model of notebook 05**, scoring one BAG — a
`(vano, ventana)` cell. That is the unit notebook 04 defines criticality on and the unit notebook
06's simulator moves, so the report and the dashboard finally answer with the same model. Two
consequences run through every step below:

- **One scenario is one WINDOW**, not a percentile of rows. Findings anchor to a window label.
- **The model predicts `uiti_acumulado`, and only that.** Event count is an axis of the KMeans
  space that fixes the class, never a model output. The historian reports frequency as observed
  data; the inference validator REJECTS any response attributing it to the model.

**The `auto-simulator` agent is retired.** Its automatic min/max sensitivity sweep is exactly what
`relevancia_hacia_uiti_minimo` replaced in notebook 06 — with sign, and probing the interior of
each range rather than only its endpoints, which is where 10 of the 15 numeric controls have their
best value. Its content now travels inside each scenario's relevance table, so the flow is **three
agents** and the report no longer carries two tables answering the same question by different
methods.

## When to Use

Load this Skill when the user asks for a full circuit report — `/report <circuito>` with optional
dates — rather than a single agent's isolated diagnosis. If the user only wants one agent's output
in isolation (e.g. "just the historical diagnosis"), use that agent's own Skill directly instead.

## Argument contract

Invocation: `/report <circuito> [fecha_inicio fecha_fin]`. Legacy alias: `/reporte <circuito> [fecha_inicio fecha_fin]`.

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
| `/report C1` | Both dates default to C1's full range |
| `/report C1 2026-01-01 2026-02-01` | Both dates pass through unchanged |
| `/report C1 2026-01-01` | **Rejected** — usage error, `fecha_fin` missing |

## Single user checkpoint (start of flow only)

`circuito` and the resolved `fecha_inicio`/`fecha_fin` window are the **only** things this Skill
ever corroborates with the user, and only **once**, at the very start of the run, before step 2
(`prepare`) does any work. Once that single checkpoint clears, the entire rest of the run (steps
2-8) proceeds **without asking the user anything else** — no "should I run these in parallel?", no
"should I proceed automatically?", no intermediate status check-ins. Silence between steps is the
expected behavior; the next thing the user sees is either an alert (a hard failure below) or the
step 8 result.

## Allowed tools

- **Bash** — restricted to invoking the shared report contract and orchestrator's own Python stages
  (`chec_local_interpreter.report_contract` plus `chec_local_interpreter.report_pipeline.preflight` /
  `.prepare` / `.prepare_expert_alignment` / `.render`, e.g. via `python -m
  chec_local_interpreter.report_contract ...` or `python -c "from
  chec_local_interpreter.report_pipeline import ...; ..."`) and nothing else.
  This Skill never gets a general shell — same structural guarantee as the `historical`,
  `inference`, and `expert-alignment` roles (`.claude/agents/rules/invariants.md`, Rule 1).
- **Skill** — to invoke `historical`, `inference`, and `expert-alignment` in the sequence below.
  Each of those Skills governs its own agent's Bash/Read restrictions independently; this runbook
  does not relax or bypass them.
- **Read** — to inspect run_dir artifacts (`*.bc.json`, `*.out.json`) between stages.

No distinct `.claude/agents/report.md` role file is introduced. This Skill is a deterministic
runbook, not an LLM-authoring persona that itself needs a restricted-Bash role contract scoped to a
dedicated CLI verb (unlike `historical`/`inference`/`expert-alignment`, which each shell out to
their own `agent_tools.*` CLI because they author and validate one persona's JSON output). Adding a
role file here would either duplicate a CLI module that does not exist in this change's scope (no
`agent_tools.report_pipeline` CLI was built — `report_pipeline.py`'s stages are plain importable
Python functions) or require building one purely to mirror a pattern that does not apply to an
orchestrator. The Skill-only shape is the cheaper-to-maintain choice; revisit only if a future
change adds a headless/non-interactive invocation path for `/report` that needs its own CLI
boundary.

## Run sequence

**Environment bootstrap.** Run report-contract and role CLI commands from the repository root with `PYTHONPATH=src .venv/bin/python`. Do not treat a bare `python`/`python3` import failure as an unavailable project environment before trying this supported local command.

Given `circuito (and optionally `fecha_inicio`/`fecha_fin` as a validated pair):

1. **Validate arguments, resolve the window, and get the one-time user confirmation.** Before
   touching `prepare` or any agent:
   1. Reject a lone date per the argument contract above (usage error, stop here — no dataset
      load needed to catch this case).
   2. Load the dataset and check `circuito` against `data_loader.available_circuits(frame)`. If it
      is not present, **generate an alert** (e.g. "Circuito `<circuito>` no encontrado en el
      dataset — verifica el id") and stop. Do not create a run_dir, do not invoke `prepare`, do not
      ask a follow-up question — this is a hard stop, not a clarification.
   3. Resolve the date window through the shared preflight contract whenever possible:
      `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract preflight <circuito> [fecha_inicio fecha_fin] --runtime claude`.
      This delegates to `report_pipeline.preflight(...)`, which uses the same `data_loader.circuit_date_range`,
      circuit-presence, and zero-event checks as `prepare` without creating a run directory. If the resolved/given
      window has zero events, **generate an alert** naming the window that failed and, when available, the circuit's
      actual full range from `circuit_date_range` — then stop, same as the circuit-not-found case.
   4. Once `circuito` and the window both check out, state them back to the user once (circuit id
      + resolved `fecha_inicio`..`fecha_fin`) and get their confirmation before proceeding. This is
      the single checkpoint described above — do not repeat it, and do not add any other
      confirmation prompt later in the run.
2. **`prepare`** — run
   `report_pipeline.prepare(circuito, fecha_inicio, fecha_fin)` after confirmation. Writes
   `run_dir/historical.bc.json`, `run_dir/inference.bc.json`, `run_dir/l1_state.json`. Raises
   `ReportPipelineError` (circuit not found, or zero events in the resolved window) before writing
   anything — report the error to the user and stop; do not invoke any agent.

   As of this change, `prepare` also builds the MIL inference layer (read-only: it loads
   `mil_vano_ventana_v1.pt` and the bag cache, never trains). Outcomes:

   - **Healthy**: model and bag cache both load; one scenario per window the circuit actually
     has, each with its per-vano relevance towards minimum UITI and its critical-vano diagnosis.
   - **No model artifact**: `escenarios: []` and `sin_artefacto_de_modelo: true`. The context
     still declares model, unit and metric — a report that cannot tell "the model found nothing"
     from "there was no model" is worse than one that stays silent about the model.
   - **Circuit with no bags in a window**: that window simply produces no scenario. A quiet
     circuit is a real outcome, not a failure.

**Steps 3, 4, and 4b are independent of one another** — `historical`, `inference`, and
each read their own `*.bc.json` envelope and write their own distinct
`*.out.json` file, sharing no mutable state. On any runtime where the invoking tool supports
dispatching independent calls together (e.g. Claude Code issuing independent Agent/Skill calls in
one turn), they **MUST** be issued that way — parallel dispatch is the default behavior, not an
option to weigh or ask the user about. Do not fall back to running them one at a time "to be safe"
or to check in between; that only degrades runtime, it buys no safety since the three stages share
no state. Sequential execution is reserved strictly for a runtime where concurrent dispatch is
unconfirmed or unavailable — a technical fallback, never a discretionary choice, and never
something to surface to the user as a question.

**Role-dispatch safety contract:** every dispatched role-authoring task must name exactly one role
in its first line (`historical` or `inference`) and exactly one source envelope
path (`run_dir/<role>.bc.json`) plus exactly one target output path (`run_dir/<role>.out.json`). Before
delegating, verify that the selected agent can run that role's `agent_tools.<role> build-context` and
`validate` commands and can write the target output. A read-only/research-only worker cannot author a
role: do not delegate to it. If no capable role agent exists, the parent must execute the role directly.

If the runtime uses a generic worker/subagent abstraction, launch one unambiguous task per role; never
launch multiple identical generic workers with a shared prompt that asks them to infer which role they
own. If any worker asks which role it has, the orchestration is invalid: cancel that attempt, do not
render, and relaunch with explicit one-role instructions. Before `prepare_expert_alignment` or `render`, require
`historical.out.json` and `inference.out.json` to exist and validate successfully; otherwise stop and
report the stalled role.

**Scratch-file collision avoidance (mandatory on EVERY `/report` run, not just multi-circuit
batches).** A runtime's scratchpad directory is shared per session, not per dispatched agent. This
bites even a single circuit's own steps 3/4/4b: those three roles are dispatched *concurrently by
design* (see above — parallel dispatch is the default, not optional), so `historical`, `inference`,
for the SAME circuit are live agents writing to the same scratchpad at
the same time. A `circuito`-only prefix is not enough to separate them — confirmed in production:
one circuit's `inference` agent had its own `<circuito>_envelope.json` silently overwritten by that
same circuit's concurrently-running `historical` agent, and in a multi-circuit
`informe-gerencial` batch the same failure mode recurred across circuits despite per-circuit
prefixing. Under batch dispatch (`reporte-lote`/`informe-gerencial`'s missing-run loop), the risk
compounds: N circuits × 3-4 roles each, all sharing one scratchpad.

Every dispatch prompt for a role-authoring task MUST instruct the agent to:
1. Prefix any scratch file it writes with BOTH the current `circuito` AND its own role name, plus a
   uniqueness token it generates itself (its PID, a timestamp, or a random suffix) — e.g.
   `<circuito>_<role>_<pid>_envelope.json`, never a bare `<circuito>_envelope.json` shared across
   roles.
2. Re-read back any scratch file immediately after writing it, and confirm its content actually
   matches what it just wrote (e.g. check the envelope's own role-specific key shape:
   `historical.bc.json`'s ten-key schema vs. `inference.bc.json`'s nine-key schema vs.
   `inference.bc.json`'s schema) before relying on it for the next step. This
   self-check is what let agents recover from a live collision in production; skipping it lets a
   silently-clobbered file poison the rest of that role's work.

This is orchestrator-side boilerplate to add to the dispatch prompt, not a fix in `agent_tools.*` or
`report_pipeline.py` — those modules have no scratch-file involvement; the collision happens purely
in agent-authored intermediate files. The orchestrator itself also has a duty here: after any stage
completion notification, verify the stage's OWN target output file (`run_dir/<role>.out.json`) has
the expected role-specific key shape before recording usage/duration or advancing to the next step —
never trust a sub-agent's self-report of success without that direct check, since a collision can
leave the target file holding another role's content even when the reporting agent believes its own
`validate` passed.

Either way, all of steps 3 and 4 must complete successfully before step 5. Only `expert-alignment`
(steps 5-6) has an ordering dependency: it requires BOTH `historical` and `inference` to have
already completed — dispatch it alone, immediately once both are done, without pausing for input.

3. **Invoke `historical`** — load this Skill (`.claude/skills/historical/SKILL.md`), give it
   `run_dir/historical.bc.json`'s envelope via `agent_tools.historical build-context`/`validate`,
   and have it write its validated response to `run_dir/historical.out.json` as
   `{"ok": true, "data": <response>}` once `validate` returns exit code `0`. If validation retries
   are exhausted, stop the whole `/report` run for this circuit here — do not proceed to
   `inference` or beyond, and report the last validation errors to the user.

   **Capture usage + duration for this stage (mandatory when available — this is the FIRST
   action taken on this stage's completion, before reading its prose result, before verifying its
   output file, before dispatching or reacting to anything else).** When this stage runs as a real
   sub-agent (Claude Code's `Agent` tool or an equivalent runtime), its completion notification
   carries a `<usage>` block with `subagent_tokens` and `duration_ms` already measured by the
   harness — read those two fields directly rather than tracking your own separate wall-clock
   before/after (manual tracking is what silently drops this under multi-circuit parallel fan-out,
   see the note below). As soon as the notification for this stage arrives, in the same turn call
   BOTH, before doing anything else with that notification:
   - `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract record-usage
     --run-dir <run_dir> --stage historical --total <subagent_tokens>` — the combined token figure
     from the notification's `<usage>` block (never a `chars // 4` estimate passed off as
     measured). If your runtime exposes no token total, omit `record-usage` for THIS stage only
     (it degrades to the char/4 estimate).
   - `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract record-duration
     --run-dir <run_dir> --stage historical --seconds <duration_ms / 1000>` — from the SAME
     notification's `<usage><duration_ms>`. If your runtime does not expose a duration figure in
     the completion (no `<usage>` block at all), fall back to your own wall-clock delta noted
     immediately BEFORE dispatching and immediately AFTER `validate` returns exit code `0`. Record
     the FINAL successful attempt's value only (do not sum abandoned validation retries).

   Do not scrape prose, session history, or output sizes for either value.

   **Multi-circuit parallel fan-out reminder (`reporte-lote`/`informe-gerencial`'s missing-run
   loop).** When several circuits' stages are dispatched concurrently, their completion
   notifications arrive interleaved, one at a time, over the course of the run. The failure mode
   observed in practice is processing a notification's text summary and moving straight to the
   next action (verifying a file, dispatching the next circuit) WITHOUT calling `record-usage`/
   `record-duration` first — silently leaving every stage's timing/token sidecar unwritten and the
   final report's "Tiempo por etapa"/tokens columns showing `N/D` for the whole run, even though
   the measurement was available in the notification the whole time. Treat these two calls as a
   blocking part of handling ANY stage-completion notification, never a follow-up to get back to.
4. **Invoke `inference`** — same pattern as step 3, using `run_dir/inference.bc.json` and this
   Skill's own `agent_tools.inference build-context`/`validate` verbs, writing
   `run_dir/inference.out.json`. Independent of step 3 (see above) — steps 3 and 4 may run in
   either order, or in parallel where the runtime supports it (both must complete successfully
   before step 5) — the design places no ordering requirement between historical and inference,
   only that both precede expert-alignment.

   **Capture usage + duration for this stage (mandatory when available — the FIRST action on this
   stage's completion notification, before anything else).** Same pattern as step 3: read
   `subagent_tokens`/`duration_ms` directly from the completion notification's `<usage>` block (own
   wall-clock only as a fallback when no `<usage>` block exists), then in the same turn call BOTH
   `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract record-usage
   --run-dir <run_dir> --stage inference --total <subagent_tokens>` (omit only if your runtime
   exposes no token total) and `PYTHONPATH=src .venv/bin/python -m
   chec_local_interpreter.report_contract record-duration --run-dir <run_dir> --stage inference
   --seconds <duration_ms / 1000>`. Record the FINAL successful attempt's value only. Do not scrape
   prose, session history, or output sizes for either value. Under multi-circuit parallel
   dispatch, do this BEFORE reacting to any other notification — see step 3's fan-out reminder.
5. **`prepare_expert_alignment`** — run
   `report_pipeline.prepare_expert_alignment(run_dir)`. Reads the validated
   `historical.out.json`/`inference.out.json` from steps 3-4, pools report dates, matches the
   already-extracted PDF-discussion table, and writes `run_dir/expert-alignment.bc.json`. Raises
   `ReportPipelineError` if either agent's validated output is missing or `ok: false` — stop and
   report if so (this should not happen if steps 3-4 completed successfully).
6. **Invoke `expert-alignment`** — same validate-gated pattern, using
   `run_dir/expert-alignment.bc.json` and `agent_tools.expert_alignment build-context`/`validate`,
   writing `run_dir/expert-alignment.out.json`.

   **Capture usage + duration for this stage (mandatory when available — the FIRST action on this
   stage's completion notification, before anything else).** Same pattern as steps 3/4: read
   `subagent_tokens`/`duration_ms` directly from the completion notification's `<usage>` block (own
   wall-clock only as a fallback when no `<usage>` block exists), then in the same turn call BOTH
   `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract record-usage
   --run-dir <run_dir> --stage expert-alignment --total <subagent_tokens>` (omit only if your
   runtime exposes no token total) and `PYTHONPATH=src .venv/bin/python -m
   chec_local_interpreter.report_contract record-duration --run-dir <run_dir> --stage
   expert-alignment --seconds <duration_ms / 1000>`. Record the FINAL successful attempt's value
   only. Do not scrape prose, session history, or output sizes for either value. Under
   multi-circuit parallel dispatch, do this before reacting to any other notification — see step
   3's fan-out reminder.
7. **`render`** — prefer the shared contract render command. Pass runtime metadata explicitly when your runtime exposes it; otherwise let the contract resolve the effective runtime model from execution evidence:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract render <circuito> --run-dir <run_dir> --runtime <runtime> [--provider <provider>] [--model <model>]
   ```

   Direct Python callers may instead run `report_pipeline.render(run_dir, llm_provider="<provider>", llm_model="<model>")`. The report must label the model that actually orchestrated *this* run, not a static markdown frontmatter default. Resolution priority is: explicit flags/kwargs, `CHEC_LLM_PROVIDER` / `CHEC_LLM_MODEL`, runtime session/configuration, then `"Desconocido"`. For Pi / el Gentleman, the contract reads Pi session history and falls back to `~/.pi/agent/settings.json`, so changing Pi's active model updates the report label without editing this runbook. Getting this wrong (or skipping all runtime evidence)
   silently degrades the report header, it never raises. The report header then shows
   `"<Provider> (<model>)"`, e.g. `"Claude Code (claude-sonnet-5)"`, plus an input/output token line
   whose source is labeled `medidos` (measured), `medidos/estimados` (mixed), or `aproximados`
   (estimated) — see the optional `token_usage.json` sidecar note after step 4b below. Beneath that
   preserved whole-run total line, the header now also shows a per-stage breakdown (tokens + tiempo
   for each of historical/inference/expert-alignment), sourced from the capture
   calls above plus the new `stage_timing.json` sidecar (see the "Per-stage duration sidecar" note
   below).
   `report_pipeline._resolve_token_usage` resolves this per `run_dir`: explicit `tokens_input`/
   `tokens_output` kwargs (pass them yourself only if you have a better count on hand) beat the
   sidecar, which beats the `characters // 4` fallback estimate.

   **Measured token accounting (host-provided only).** If your runtime exposes actual structured per-call token usage, immediately invoke `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract record-usage --run-dir <run_dir> --stage <role> --total <n>` or `--input <n> --output <n>`. The host must pass the measured result; do not scrape prose, session history, or output sizes, and do not assume an unknown runtime API. Before render, invoke `verify-usage` with explicit expected/executed roles; strict callers must fail closed on missing or invalid measurements. Legacy flat `token_usage.json` remains supported.

**Optional: real token counts.** If your runtime exposes actual per-call token usage (input/output
   tokens for the historical/inference/expert-alignment Skill invocations in steps
   3/4/4b/6), write it to `run_dir/token_usage.json` before calling `render` in step 7 — a JSON object
   mapping stage name to `{"input": <int>, "output": <int>}`, e.g. `{"historical": {"input": 1500,
   "output": 400}, "inference": {"input": 2100, "output": 600}}`. Partial coverage is fine (any stage
   you omit falls back to the char/4 estimate for that stage only, and the header shows
   `medidos/estimados`). Skip this file entirely when your runtime does not expose usage — `render`
   degrades to the estimate exactly as before, no error either way.

   **When a stage runs as a real sub-agent (`{"total": int}` shape).** If a stage was dispatched via
   a runtime's real sub-agent tool — e.g. Claude Code's `Agent` tool or Pi's subagent runner — its
   completion notification may report a single combined usage figure with no input/output split.
   In that case, write that stage's `token_usage.json` entry as `{"total": <measured_subagent_tokens>}`
   instead of the `{"input", "output"}` shape. This is mandatory whenever the runtime exposes that
   measured total: do not show a `chars // 4` artifact estimate as if it were the all-stage run usage.
   Both shapes are valid per stage and mixable within the same sidecar file — e.g. one stage measured
   via `{"total": ...}` because it ran as a sub-agent, another via `{"input", "output"}`, another omitted
   entirely and left to the char/4 estimate. The report header's "Tokens totales" line reflects the
   best available number per stage across both shapes; a stage's own `{"input"}`/`{"output"}` entries
   are unaffected by (and never populated from) a `"total"`-only entry for that same stage.

   **Total elapsed time — no extra bookkeeping needed.** `render()` also auto-computes
   `elapsed_seconds` (the run's total wall-clock execution time, from `prepare()` creating `run_dir`
   to `render()` being called) directly from `run_dir`'s own folder-name timestamp — zero extra
   orchestration effort, no sidecar file, nothing to write. The `elapsed_seconds` kwarg on `render()`
   exists only as an optional explicit override for callers with a better/external timer; you do not
   need to compute or pass it in the normal flow.

   **Per-stage duration sidecar.** The `record-duration` calls above (steps 3/4/4b/6) accumulate
   into an optional `run_dir/stage_timing.json` (one `{"duration_seconds": <float>}` entry per
   stage) — the timing counterpart to `token_usage.json`. It is fully additive and independent:
   `render` reads it to show a per-stage "Tiempo" column alongside the per-stage "Tokens" column;
   any stage missing from it (or the whole file absent) renders `N/D` for that stage, never an
   error. The whole-run "Tiempo total de ejecución" line above is computed separately from the
   run_dir timestamp and does not depend on this sidecar.

   Reads all three validated outputs and calls `plotting.render_llm_analysis`, now also merging in
   the 5 `automatic_simulation_*` kwargs (table, agent analysis, cost context, softmax curves,
   vano-risk table) when `run_dir/auto_simulation_assets.json` and/or
   absent (no crash either way, same degrade shape as the inference-simulator sidecar below).
   Raises `ReportPipelineError` if the expert-alignment output is missing/invalid; no HTML is
   written in that case.

   `render` stays model-free in the ML-inference sense: it never reloads the MIL model or
   recomputes SHAP (the `llm_model` kwarg above is unrelated — it just labels which *agent* produced
   the report, not a model `render` itself calls). If `prepare` persisted
   `run_dir/inference_render_assets.json` (the healthy-run case above), `render` resolves every
   figure/graph path in it against `run_dir` and passes a populated `inference_results` mapping into
   `plotting.render_llm_analysis`, so the bars/radar/estimated-graph section actually renders. If the
   sidecar is absent (no trained model, or every scenario was skipped), `inference_results` stays
   `None` — the inference-figures section is empty, same as before this change, and this is never a
   crash or a `ReportPipelineError`.

   `render` also now passes the *full*, unfiltered multi-circuit dataset (loaded fresh from
   `state["data_path"]`, before the single-circuit `filter_events` call) into
   `plotting.render_llm_analysis` as `all_circuits_df`, so the circuit-clustering chart benchmarks
   the studied circuit against the whole fleet (colored by risk cluster, studied circuit highlighted
   with an "X") instead of only ever showing one point.
8. **Report the result** — tell the user the returned HTML `Path`. `/report` is local-only by
   design: it never touches `site/assets/site/results/`, so a run never changes what the published
   GitHub Pages site shows. Publishing a specific report there is a deliberate, separate action —
   call `web_export.export_latest_interpretability_report(html_path)` yourself when you actually
   want a given report to go live, never as an automatic side effect of generating one. Do not claim
   the report is final if any stage above raised and stopped the run early.
9. **Vault note + graphify (post-report, alert-and-continue).** After step 8 has already reported the
   HTML path — this step never blocks or delays that report — load
   [`.claude/skills/vault-circuito/SKILL.md`](../vault-circuito/SKILL.md) with `circuito` and run its
   two-step sequence: (1) project the run's 3 validated `*.out.json` narratives into
   `reports/vault/<circuito>.md` via `chec_local_interpreter.vault_note_contract render <circuito>`
   (upsert, latest-run-wins), then (2) chain the real `/graphify reports/vault --update` slash-command
   so the vault stays incrementally indexed. Both the vault write and the graphify chain follow
   **alert-and-continue**, never alert-and-stop: a `skipped_incomplete`/`usage_error`/
   `execution_error` outcome from the vault projection, or a failure of the chained `/graphify`
   invocation, is surfaced as a clear message but never rolls back the already-reported HTML from
   step 8, never re-raises into this run, and never turns into a question back to the user. See
   `vault-circuito/SKILL.md`'s own "Error handling summary" for the exact per-outcome behavior. This
   step is additive only — it does not change step 8's own report or `report_pipeline.py`'s
   `prepare`/`render` behavior in any way.

## Error handling summary

| Failure | Where | User-facing outcome |
|---|---|---|
| Lone date given | Step 1 (this Skill) | Usage error, no stage runs |
| Circuit not found | Step 1 pre-flight (this Skill), re-checked by `prepare` | Alert at step 1, before any run_dir exists — `prepare` would raise `ReportPipelineError` on the same check if step 1 were ever bypassed, so this fails closed either way |
| Zero events in window | Step 1 pre-flight (this Skill), re-checked by `prepare` | Alert at step 1, before any run_dir exists — same defense-in-depth as above via `prepare`'s `ReportPipelineError` |
| Agent validation retries exhausted | Steps 3, 4, or 6 | Stop this circuit's run; surface the last `validate` errors; never invoke a later stage; never turn this into a follow-up question — report it and stop |
| Missing/invalid validated output reaching a later stage | `prepare_expert_alignment` / `render` | `ReportPipelineError`; the affected artifact is never written |
| Vault note projection or chained `/graphify --update` fails | Step 9 (`vault-circuito`) | **Alert-and-continue, NOT alert-and-stop** — step 8's HTML report already succeeded and is never rolled back; see `vault-circuito/SKILL.md`'s own error table |

None of the rows above, nor any other mid-run condition, should turn into a question back to the
user — the single checkpoint is step 1 only (see "Single user checkpoint" above). Every failure from
step 2 through step 8 is an alert-and-stop, not a prompt; step 9 is the sole exception and is
alert-and-continue by design (see step 9 above), since the report it might degrade has already
completed successfully.

### Simulator degrade paths (NOT `ReportPipelineError`)

These are graceful-degradation outcomes from the MIL inference layer inside `prepare` — the run
always continues, the report always generates:

| Case | Where | Resulting shape |
|---|---|---|
| No trained model file on disk | `prepare` (`cargar_recursos_mil`) | `escenarios: []`, `sin_artefacto_de_modelo: true`; `render` gets `inference_results=None` |
| One scenario (of four) has too few events for valid SHAP | `prepare` (`_compute_inference_scenarios`) | That scenario is silently omitted from `escenarios`; the other surviving scenarios are unaffected |
| Circuit has no bags in any window | `prepare` (`escenarios_de_circuito`) | `escenarios: []` but the model summary is real — distinguishes this from the "no trained model" row above |
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
- Post-report step 9 (alert-and-continue, additive only):
  [`.claude/skills/vault-circuito/SKILL.md`](../vault-circuito/SKILL.md) /
  [`src/chec_local_interpreter/vault_note_contract.py`](../../../src/chec_local_interpreter/vault_note_contract.py)
- Binding invariants (shared with every agent role above): `.claude/agents/rules/invariants.md`
- Architecture and envelope contract: `docs/agents-guide.md`
- `the retired interactive notebook` — deleted; this Skill supersedes it
  in full (see git history for its prior content).
- Tests: `tests/test_report_pipeline.py` (argument-pair contract, simulator wiring/degrade paths, the
  real-simulator integration tests using the committed model/Optuna/Variables artifacts, and the
  end-to-end smoke test with canned validated outputs and no live LLM call);
  `tests/test_mil_inferencia.py` (unit tests for the MIL predictive layer: relevance on UITI,
  the critical-vano diagnosis, one scenario per window, and the model summary)
