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
- Explica el comportamiento en el tiempo sobre la rejilla de VENTANAS, no sobre días aislados.
- Agrupa los hallazgos por mecanismos dominantes cuando sea posible: evento/impacto, protección, topología, características físicas/eléctricas, activos y entorno/riesgo/clima.
- Incluye las ventanas estudiadas con sus periodos y valores.
- En la propiedad `cause_hypothesis_note`, estima la posible causa raíz basándote en las justificaciones técnicas (`ContextoProyectoSimuladorCHEC.md`), las variables analizadas, la cantidad de eventos y el impacto en `UITI_VANO`. Ajusta tus análisis para que las justificaciones sean más detalladas, resaltando explícitamente cuáles columnas o variables específicas guardan mayor relación con las causas propuestas.
- La causa raíz se escribe en el lenguaje de quien opera el circuito: qué está pasando en la red y por qué. Nombra el fenómeno físico o eléctrico —vegetación que invade la servidumbre, descargas atmosféricas sobre un tramo, un conductor o un calibre que no da para la carga, una puesta a tierra ausente—, no el procedimiento que lo detectó. Un identificador de regla, un nombre de función o un nombre de proceso interno en este campo no aportan nada y hacen ilegible lo único que el lector se va a llevar. Al citar las variables que sostienen la hipótesis, escríbelas con su nombre en castellano y su código entre paréntesis, como indica `04_domain_grounding_guardrails`.
- **Análisis de Vegetación y DDT (OBLIGATORIO):** Es MANDATORIO analizar e incluir siempre la influencia de `NR_T` (nivel de riesgo de vegetación cercana al vano) y `DDT` (Densidad de Descargas a Tierra). Ambas variables SIEMPRE están presentes en los datos del estudio. Debes:
  1. Evaluar el nivel de `NR_T` en las ventanas estudiadas y discutir explícitamente si la vegetación pudo contribuir a los eventos o al deterioro de `UITI_VANO`.
  2. Correlacionar `DDT` con las demás variables climáticas disponibles (precipitación, viento, nubosidad, etc.) y evaluar explícitamente su impacto en la frecuencia de eventos y en la severidad de `UITI_VANO`.
  3. Destacar, con lenguaje de evidencia tabular, si `NR_T` y `DDT` refuerzan o contradicen las hipótesis de causa raíz.
  4. **NUNCA** afirmar que los datos de DDT o vegetación (`NR_T`) no están disponibles; siempre están en la tabla analizada.
- Evita afirmaciones sin soporte.
- Evita mencionar RAG, revisión documental, bitácoras operativas, inferencia de modelos predictivos, máscaras, simulación o reportes finales.
- Usa las ventanas estudiadas como evidencia, pero sintetiza un diagnóstico consolidado a nivel del periodo.
