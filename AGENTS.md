# CHEC Local UITI_VANO Interpreter

## Project Purpose

This repo is a local interpreter for `UITI_VANO`. It loads one wide structured dataset,
filters by circuits and dates, detects relevant points in the `UITI_VANO` daily series,
builds a structured context package, and has five coding-agent-native LLM roles explain the
behavior in Spanish and compare it against expert PDF reports — all with **zero external LLM
API key**: the agent invoking this repo (Claude Code or Pi / el Gentleman) does the reasoning
itself, never a Python call to Gemini/OpenAI.

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
- `/experimento-kaggle <descripción>` (`.claude/skills/experimento-kaggle/SKILL.md`) is a
  standalone code/model-experiment workflow: propose a Mermaid block diagram, build a
  `smoke`/`full` notebook, gate on explicit user approval, then push/poll/pull it on Kaggle via
  the official `kaggle` CLI. It never runs unattended and never touches the 5 LLM agent roles or
  `report_pipeline.py`.
- `/clima` (`.claude/skills/clima/SKILL.md`) is the interactive weather-enrichment runbook that
  replaces both climate notebooks. It first asks the mode: **A** update `data/Indicadores_vano_v3.csv`
  by event (25 lags, transactional, pass-through when nothing is new), or **B** query a
  user-chosen points table for a **day or date range**, appending wide `hours × variables` columns
  and embedding an `origen_id` so same-origin outputs can be unified/concatenated. Engine:
  `src/chec_local_interpreter/clima_engine.py`; it never touches the 5 LLM agent roles.

## Agent-native architecture

Each of the 5 LLM roles follows the same pattern: a deterministic two-verb CLI
(`python -m chec_local_interpreter.agent_tools.<role> build-context` / `validate`) builds the
context/prompt and validates the response's shape — the invoking coding agent itself authors
the JSON response, never a Python `call_llm()`. Role definitions:
- Claude Code: `.claude/agents/<role>.md` (role/tool contract) + `.claude/skills/<role>/SKILL.md`
  (persona, invariants, run sequence).
- Pi / el Gentleman: `.pi/agents/<role>.md` (thin mirror pointing back to the canonical Claude
  role and skill) + `.pi/skills/<role>/SKILL.md`.

Do not add Databricks, Dash, FastAPI, RAG, or vector stores to `src/chec_local_interpreter` or
any of the 5 LLM agent roles (`historical`, `inference`, `expert-alignment`, `auto-simulator`,
`pdf-discussion-extraction`). Predictive model inference and forecasting language are prohibited
in `historical`'s base explanations, EXCEPT within outputs validated by
`validar_respuesta_inferencia`, where predictive analysis and final evidence report generation
are fully permitted and encouraged.

**Sanctioned exception**: the `/subir-*-databricks` and `/app-*` commands under `.claude/commands/`
perform a manual, on-demand migration to a Databricks workspace. They upload only the data that
notebooks `01`-`06` and `/report` actually read, and publish those notebooks as Databricks Apps.
They never modify `report_pipeline.py`, any of the 5 LLM agent roles, or the local pipeline's
runtime dependencies. All of them follow
`.claude/commands/_contrato-despliegue-databricks.md`. This is a standalone command tree driven by
the Databricks CLI — not an automation pipeline, and not a reversal of this repo's
notebook-to-Python migration for the local interpreter itself.

The earlier Lakeview AI/BI PoC (`notebooks/databricks/`, `/deploy-databricks-dashboard`) was
retired: Lakeview runs neither Python nor arbitrary JS, so it could never show the notebooks' real
analysis. Nothing in this repo creates Delta tables, views or dashboards any more.

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
