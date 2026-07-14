# Reglas de Anclaje de Dominio

Usa el contexto de dominio de `ContextoProyectoSimuladorCHEC.md` únicamente como anclaje
para el dataset estructurado. Trátalo como guía interpretativa, no como prueba.

## Guía Compacta de Dominio

- Los rezagos climáticos pueden indicar estrés ambiental acumulado.
- `NR_T` (nivel de riesgo de vegetación) y `DDT` (densidad de descargas a tierra) son variables opcionales según el contexto entregado; cuando estén disponibles, deben analizarse como posibles moduladores de eventos y `UITI_VANO`.
- La precipitación, el viento y las ráfagas pueden respaldar hipótesis ambientales junto con `NR_T` y `DDT` cuando esas variables estén disponibles.
- El conductor, la longitud, las fases, el neutro/cable de guarda y la taxonomía describen susceptibilidad.
- `LVSW`, `CNT_VN`, `FID_VANO` y `CIRCUITO` describen la topología y el contexto de propagación.
- Los equipos de protección y los usuarios protegidos ayudan a explicar el alcance del impacto y el contexto de restablecimiento.
- Las variables de activos ayudan a describir vulnerabilidad y exposición.
- La duración y los usuarios afectados ayudan a explicar el impacto de la interrupción a nivel de evento.

## Lenguaje Prohibido

- "causo definitivamente"
- "demuestra que"
- "la causa fue"
- "segun la normativa"
- "la bitacora evidencia"
- "el modelo predice"
- afirmar que `NR_T` o `DDT` fueron observadas si no aparecen en el contexto entregado
- afirmar que `NR_T` o `DDT` no influyeron sin evidencia tabular
- presentar brechas de `NR_T` o `DDT` como fallas del dataset completo cuando solo faltan en el contexto local

## Asociaciones Prohibidas

- **CRÍTICO**: Evita relacionar operaciones manuales con causas, caracterizaciones o justificaciones de fallo. Las operaciones manuales son intervenciones controladas por el personal de la empresa y no afectan el funcionamiento principal del circuito.

## Lenguaje Preferido

- "sugiere"
- "es compatible con"
- "podría estar asociado con"
- "la evidencia tabular muestra"
- "dentro de las variables disponibles"
- "no se puede confirmar con esta versión local"
