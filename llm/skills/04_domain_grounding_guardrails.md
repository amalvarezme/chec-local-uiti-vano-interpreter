# Domain Grounding Guardrails

Use domain context from `ContextoProyectoSimuladorCHEC.md` only as grounding for the
structured dataset. Treat it as interpretive guidance, not proof.

## Compact Domain Guidance

- Weather lags can indicate accumulated environmental stress.
- `NR_T` (nivel de riesgo de vegetación) y `DDT` (densidad de descargas a tierra) son variables **siempre presentes** en la tabla de estudio; deben analizarse en todos los informes como posibles moduladores de eventos y `UITI_VANO`.
- Precipitation, wind, and gusts can support environmental hypotheses alongside `NR_T` and `DDT`.
- Conductor, length, phases, neutral/guard wire, and taxonomy describe susceptibility.
- `LVSW`, `CNT_VN`, `FID_VANO`, and `CIRCUITO` describe topology and propagation context.
- Protection equipment and users protected help explain impact scope and restoration context.
- Asset variables help describe vulnerability and exposure.
- Duration and affected users help explain event-level interruption impact.

## Prohibited Language

- "causo definitivamente"
- "demuestra que"
- "la causa fue"
- "segun la normativa"
- "la bitacora evidencia"
- "el modelo predice"
- "no se tienen datos de DDT"
- "DDT no está disponible"
- "no hay información de vegetación"
- "NR_T no está disponible"
- "no contamos con datos de DDT"
- cualquier frase que indique ausencia de datos para `DDT` o `NR_T`

## Prohibited Associations

- **CRÍTICO**: Evita relacionar operaciones manuales (manual operations) con causas, caracterizaciones o justificaciones de fallo. Las operaciones manuales son intervenciones controladas por el personal de la empresa y no afectan el funcionamiento principal del circuito.

## Preferred Language

- "sugiere"
- "es compatible con"
- "podria estar asociado con"
- "la evidencia tabular muestra"
- "dentro de las variables disponibles"
- "no se puede confirmar con esta version local"
