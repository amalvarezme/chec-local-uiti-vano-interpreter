# Reglas de Anclaje de Dominio

Usa el contexto de dominio de `ContextoProyectoSimuladorCHEC.md` únicamente como anclaje
para el dataset estructurado. Trátalo como guía interpretativa, no como prueba.

## Guía Compacta de Dominio

- Los rezagos climáticos pueden indicar estrés ambiental acumulado.
- `NR_T` (nivel de riesgo de vegetación) y `DDT` (densidad de descargas a tierra) son variables **siempre presentes** en la tabla de estudio; deben analizarse en todos los informes como posibles moduladores de eventos y `UITI_VANO`.
- La precipitación, el viento y las ráfagas pueden respaldar hipótesis ambientales junto con `NR_T` y `DDT`.
- El conductor, la longitud, las fases, el neutro/cable de guarda y la taxonomía describen susceptibilidad.
- `LVSW`, `CNT_VN`, `FID_VANO` y `CIRCUITO` describen la topología y el contexto de propagación.
- Los equipos de protección y los usuarios protegidos ayudan a explicar el alcance del impacto y el contexto de restablecimiento.
- Las variables de activos ayudan a describir vulnerabilidad y exposición.
- La duración y los usuarios afectados ayudan a explicar el impacto de la interrupción a nivel de evento.

## Lenguaje Prohibido

- "demuestra que"
- "segun la normativa"
- "la bitacora evidencia"
- "el modelo predice"
- "no se tienen datos de DDT"
- "DDT no está disponible"
- "no hay información de vegetación"
- "NR_T no está disponible"
- "no contamos con datos de DDT"
- cualquier frase que indique ausencia de datos para `DDT` o `NR_T`

## Lenguaje Preferido

- "sugiere"
- "es compatible con"
- "podría estar asociado con"
- "la evidencia tabular muestra"
- "dentro de las variables disponibles"
- "no se puede confirmar con esta versión local"
