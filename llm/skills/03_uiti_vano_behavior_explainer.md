# UITI_VANO Behavior Explainer

Produce the final analysis in Spanish as structured JSON.

## Required Output Structure

- `headline`
- `executive_summary`
- `key_findings`
- `period_synthesis`
- `evidence`
- `data_gaps`
- `limitations`
- `recommended_actions`

## Rules

- Focus on `UITI_VANO`.
- Explain behavior over time, not only isolated days.
- Group findings by dominant mechanisms when possible: event/impact, protection, topology, physical/electrical characteristics, assets, and environment/risk/weather.
- Include critical dates and values.
- Avoid unsupported statements.
- Avoid mentioning RAG, documentary review, operational logs, predictive model inference, masks, simulation, or final reports.
- Use all critical points provided as evidence, but synthesize a consolidated period-level diagnosis.
