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

Supersedes phases 1-8 of the interactive notebook
(`notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`, deprecated in place — see that
notebook's own top cell). Phases 9-11 of the notebook (saved artifacts, the LLM
skills/contracts/validation section, and HTML export) are untouched by this Skill.

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
   calls `plotting.render_llm_analysis` (no `automatic_simulation_*` kwargs — no simulator in this
   flow) to produce the final HTML report. Raises `ReportPipelineError` if the expert-alignment
   output is missing/invalid; no HTML is written in that case.
8. **Report the result** — tell the user the returned HTML `Path`. Do not claim the report is final
   if any stage above raised and stopped the run early.

## Error handling summary

| Failure | Where | User-facing outcome |
|---|---|---|
| Lone date given | Step 1 (this Skill) / `prepare` | Usage error, no stage runs |
| Circuit not found | `prepare` | `ReportPipelineError`, no run_dir created, no agent invoked |
| Zero events in window | `prepare` | `ReportPipelineError`, no run_dir created, no agent invoked |
| Agent validation retries exhausted | Steps 3, 4, or 6 | Stop this circuit's run; surface the last `validate` errors; never invoke a later stage |
| Missing/invalid validated output reaching a later stage | `prepare_expert_alignment` / `render` | `ReportPipelineError`; the affected artifact is never written |

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
- Deprecated (in-place, not deleted) notebook this Skill supersedes for phases 1-8:
  `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`
- Tests: `tests/test_report_pipeline.py` (includes the argument-pair contract and the final
  end-to-end smoke test with canned validated outputs and no live LLM call)
