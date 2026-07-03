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
- **Análisis de Vegetación y DDT (OBLIGATORIO):** Es MANDATORIO analizar e incluir siempre la influencia de `NR_T` (nivel de riesgo de vegetación cercana al vano) y `DDT` (Densidad de Descargas a Tierra). Ambas variables SIEMPRE están presentes en los datos del estudio. Debes:
  1. Evaluar el nivel de `NR_T` en los puntos críticos y discutir explícitamente si la vegetación pudo contribuir a los eventos o al deterioro de `UITI_VANO`.
  2. Correlacionar `DDT` con las demás variables climáticas disponibles (precipitación, viento, nubosidad, etc.) y evaluar explícitamente su impacto en la frecuencia de eventos y en la severidad de `UITI_VANO`.
  3. Destacar, con lenguaje de evidencia tabular, si `NR_T` y `DDT` refuerzan o contradicen las hipótesis de causa raíz.
  4. **NUNCA** afirmar que los datos de DDT o vegetación (`NR_T`) no están disponibles; siempre están en la tabla analizada.
- Avoid unsupported statements.
- Avoid mentioning RAG, documentary review, operational logs, predictive model inference, masks, simulation, or final reports.
- Use all critical points provided as evidence, but synthesize a consolidated period-level diagnosis.
