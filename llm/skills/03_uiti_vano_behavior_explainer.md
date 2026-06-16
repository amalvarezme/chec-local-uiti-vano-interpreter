# UITI_VANO Behavior Explainer

Produce the final analysis in Spanish as structured JSON.

## Required Output Structure

- `headline`
- `executive_summary`
- `key_findings`
- `period_synthesis`
- `cause_hypothesis_note`
- `evidence`
- `data_gaps`
- `limitations`
- `recommended_actions`

## Rules

- Focus on `UITI_VANO`.
- Explain behavior over time, not only isolated days.
- Group findings by dominant mechanisms when possible: event/impact, protection, topology, physical/electrical characteristics, assets, and environment/risk/weather.
- Include critical dates and values.
- En la propiedad `cause_hypothesis_note`, estima la posible causa raíz basándote en el grafo de conocimiento, las justificaciones técnicas (`ContextoProyectoSimuladorCHEC.md`), las variables analizadas, la cantidad de eventos y el impacto en `UITI_VANO`. Ajusta tus análisis para que las justificaciones sean más detalladas, resaltando explícitamente cuáles columnas o variables específicas guardan mayor relación con las causas propuestas.
- **Análisis de DDT y Clima:** Es MANDATORIO analizar e incluir siempre la influencia de la variable `DDT` (Densidad de Descargas a Tierra). Debes buscar y explicar explícitamente posibles correlaciones entre `DDT`, las demás variables climáticas disponibles (precipitación, viento, nubosidad, etc.) y las salidas de interés: la frecuencia (número de eventos) y la severidad (`UITI_VANO`).
- Avoid unsupported statements.
- Avoid mentioning RAG, documentary review, operational logs, predictive model inference, masks, simulation, or final reports.
- Use all critical points provided as evidence, but synthesize a consolidated period-level diagnosis.
