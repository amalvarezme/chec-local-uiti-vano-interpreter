# Domain Grounding Guardrails

Use domain context from `ContextoProyectoSimuladorCHEC.md` only as grounding for the
structured dataset. Treat it as interpretive guidance, not proof.

## Compact Domain Guidance

- Weather lags can indicate accumulated environmental stress.
- `NR_T`, `DDT`, precipitation, wind, and gusts can support environmental hypotheses.
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

## Prohibited Associations

- **CRÍTICO**: Evita relacionar operaciones manuales (manual operations) con causas, caracterizaciones o justificaciones de fallo. Las operaciones manuales son intervenciones controladas por el personal de la empresa y no afectan el funcionamiento principal del circuito.

## Preferred Language

- "sugiere"
- "es compatible con"
- "podria estar asociado con"
- "la evidencia tabular muestra"
- "dentro de las variables disponibles"
- "no se puede confirmar con esta version local"
