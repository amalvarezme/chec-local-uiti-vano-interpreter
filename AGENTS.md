# CHEC Local UITI_VANO Interpreter

## Project Purpose

This repo is a local interpreter for `UITI_VANO`. It loads one wide structured dataset,
filters by circuits and dates, detects relevant points in the `UITI_VANO` daily series,
builds a structured context package, and has five coding-agent-native LLM roles explain the
behavior in Spanish and compare it against expert PDF reports — all with **zero external LLM
API key**: the agent invoking this repo (Claude Code or OpenCode) does the reasoning itself,
never a Python call to Gemini/OpenAI.

## Scope

- Circuit/vano selection, deterministic critical-point detection, and semantic diagnosis
  (`historical`), MGCECDL/SHAP predictive interpretation (`inference`), expert-PDF alignment
  (`expert-alignment`), automatic min/max sensitivity discussion (`auto-simulator`), and
  PDF-discussion-table extraction (`pdf-discussion-extraction`) are all in scope and
  implemented — see `docs/agents-guide.md` for the full architecture.
- `/reporte <circuito>` (`.claude/skills/reporte/SKILL.md`) is the primary entry point: it
  orchestrates `historical` + `inference` + `auto-simulator` + `expert-alignment` into one
  local HTML report. It never publishes to the site automatically — that's a deliberate,
  separate action (`web_export.export_latest_interpretability_report`), not a `/reporte` side
  effect.
- Use structured tabular data, variable descriptions, variable modes, and relationship rules.
- Keep the workflow local and lightweight.

## Agent-native architecture

Each of the 5 LLM roles follows the same pattern: a deterministic two-verb CLI
(`python -m chec_local_interpreter.agent_tools.<role> build-context` / `validate`) builds the
context/prompt and validates the response's shape — the invoking coding agent itself authors
the JSON response, never a Python `call_llm()`. Role definitions:
- Claude Code: `.claude/agents/<role>.md` (role/tool contract) + `.claude/skills/<role>/SKILL.md`
  (persona, invariants, run sequence).
- OpenCode: `.opencode/agent/<role>.md` (mirrors the same role; OpenCode reads
  `.claude/skills/` directly, so only the agent role file needs a separate copy).

Do not add Databricks, Dash, FastAPI, RAG, or vector stores to `src/chec_local_interpreter` or
any of the 5 LLM agent roles (`historical`, `inference`, `expert-alignment`, `auto-simulator`,
`pdf-discussion-extraction`). Predictive model inference and forecasting language are prohibited
in `historical`'s base explanations, EXCEPT within outputs validated by
`validar_respuesta_inferencia`, where predictive analysis and final evidence report generation
are fully permitted and encouraged.

**Sanctioned exception**: `notebooks/databricks/` hosts a manual, one-time Databricks AI/BI PoC
(circuit-clustering + geo-exploration dashboard) that imports and reuses
`plotting.compute_circuit_criticality_groups` for exact parity with the local pipeline, but never
modifies `report_pipeline.py`, any of the 5 LLM agent roles, or the local pipeline's runtime
dependencies. It is a standalone, headless-run data-prep/dashboard script invoked via the
Databricks CLI — not an automation pipeline, and not a reversal of this repo's notebook-to-Python
migration for the local interpreter itself.

## Coding Style

- Prefer pure functions under `src/chec_local_interpreter`.
- Keep notebook cells short and readable.
- Treat identifiers as strings.
- Parse `FECHA` with `pd.to_datetime(errors="coerce")`.
- Coerce numeric analysis columns only in derived frames.
- Keep optional columns optional and record unavailable variables in context metadata.

## LLM Safety And Quality

- Deterministic Python code selects circuits, periods, series, critical points, and attribution summaries.
- The LLM only interprets the structured context package.
- The LLM must return JSON matching the project schema.
- The LLM must cite dates, `critical_point_id`, variables, and summaries present in context.
- The LLM is encouraged to use Chain-of-Thought (CoT) reasoning (via `<think>` blocks) to deeply debate graph information, variable definitions, time series of critical points, and root causes before emitting final JSON.
- Save the exact prompt and structured context for every run.
- Do not log secrets or raw credentials.
- Avoid dumping the full raw dataset in logs.

## Missing Optional Columns

The workflow must continue when optional columns are absent. Missing optional columns
must appear in `metadata.unavailable_optional_columns`, and LLM output should mention
the resulting data gaps without claiming those variables were observed.

## Invalid LLM Output

If LLM output does not validate, save the raw invalid output and validation errors
under `reports/interpretability/artifacts/`, print a clear notebook message, and do not present it as final analysis.

## Testing Expectations

Run `pytest -q` and `python evals/run_llm_eval.py` before considering changes complete.
