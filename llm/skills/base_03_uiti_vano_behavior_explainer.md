# Explicador del Comportamiento de `UITI_VANO`

Produce el análisis final en español como JSON estructurado.

## Estructura de Salida Requerida

- `headline`
- `executive_summary`
- `key_findings`
- `period_synthesis`
- `cause_hypothesis_note`
- `evidence`
- `data_gaps`
- `limitations`
- `recommended_actions`

## Reglas

- Enfócate en `UITI_VANO`.
- Explica el comportamiento en el tiempo, no solo días aislados.
- Agrupa los hallazgos por mecanismos dominantes cuando sea posible: evento/impacto, protección, topología, características físicas/eléctricas, activos y entorno/riesgo/clima.
- Incluye fechas y valores críticos.
- En la propiedad `cause_hypothesis_note`, estima la posible causa raíz basándote en el grafo de conocimiento, las justificaciones técnicas (`ContextoProyectoSimuladorCHEC.md`), las variables analizadas, la cantidad de eventos y el impacto en `UITI_VANO`. Ajusta tus análisis para que las justificaciones sean más detalladas, resaltando explícitamente cuáles columnas o variables específicas guardan mayor relación con las causas propuestas.
- **Análisis de Vegetación y DDT:** Analiza la influencia de `NR_T` (nivel de riesgo de vegetación cercana al vano) y `DDT` (Densidad de Descargas a Tierra) cuando estén presentes en el contexto entregado. Debes:
  1. Si `NR_T` aparece en el contexto, evaluar su nivel en los puntos críticos y discutir explícitamente si la vegetación pudo contribuir a los eventos o al deterioro de `UITI_VANO`.
  2. Si `DDT` aparece en el contexto, correlacionarlo con las demás variables climáticas disponibles (precipitación, viento, nubosidad, etc.) y evaluar explícitamente su impacto en la frecuencia de eventos y en la severidad de `UITI_VANO`.
  3. Destacar, con lenguaje de evidencia tabular, si las variables disponibles refuerzan o contradicen las hipótesis de causa raíz.
  4. Si `NR_T` o `DDT` no aparecen en el contexto entregado, repórtalo como brecha de datos y no inventes observaciones.
- Evita afirmaciones sin soporte.
- Evita mencionar RAG, revisión documental, bitácoras operativas, inferencia de modelos predictivos, máscaras, simulación o reportes finales.
- Usa todos los puntos críticos proporcionados como evidencia, pero sintetiza un diagnóstico consolidado a nivel del periodo.
