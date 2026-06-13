# Structured Context Builder

Build the structured context before any LLM call. Deterministic Python code selects the
circuits, period, daily series, critical points, periods, and attribution summaries.

## Inputs

- Filtered dataframe for the selected circuits and date window.
- Daily `UITI_VANO` series.
- Critical points selected by code.
- Attribution summaries for each critical point.
- Domain variable groups.
- Relationship rules.

## Output

A compact JSON-serializable context package that can be saved and replayed.

## Rules

- Include only data derived from the selected circuits and selected date window.
- Include unavailable optional variables explicitly in metadata.
- Keep IDs as strings.
- Summarize raw rows instead of sending the full dataset when the window is large.
- Include enough event rows around each critical point for interpretation.
- Include the daily series in compact form.
- Include guardrails inside the context package.
- Do not add external evidence, documents, vector stores, models, masks, simulations, or final report material.
