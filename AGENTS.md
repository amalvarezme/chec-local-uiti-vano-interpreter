# CHEC Local UITI_VANO Interpreter

## Project Purpose

This repo is a local, notebook-first interpreter for `UITI_VANO`. It loads one wide
structured dataset, filters by circuits and dates, detects relevant points in the
`UITI_VANO` daily series, builds a structured context package, and optionally asks an
LLM to explain the behavior in Spanish.

## Scope

- Implement only steps 1 to 3 of the CHEC architecture flow.
- Use structured tabular data, variable descriptions, variable modes, and relationship rules.
- Keep the workflow local and lightweight.

## Prohibited Additions

Do not add Databricks, Dash, FastAPI, RAG, vector stores, feature importance masks,
or what-if simulation.
Predictive model inference and forecasting language are strictly prohibited in base explanations, EXCEPT when generating outputs validated by `validar_respuesta_inferencia`, where predictive analysis of the second LLM and final evidence report generation is fully permitted and encouraged.

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
under `outputs/`, print a clear notebook message, and do not present it as final analysis.

## Testing Expectations

Run `pytest -q` and `python llm/evals/run_llm_eval.py` before considering changes complete.
