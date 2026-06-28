Version del prompt: {prompt_version}

Analiza el comportamiento de `UITI_VANO` para los circuitos y periodo seleccionados.
Usa los puntos criticos entregados como evidencia y produce un diagnostico
consolidado del periodo.

Conecta la caracterización del circuito con la evolución temporal de `events` y `UITI_VANO`.
El campo `circuit_characterization` es un objeto. DEBES:
1. `text`: Síntesis de la criticidad del circuito.
2. `top_vanos_percentile`, `p97_vanos_uiti_vano` y `p97_vanos_eventos`: Copiar el percentil configurado y los vanos top por percentil del contexto.
3. `probable_justifications_rules`: Presentar al menos 3 ítems con las principales relaciones descriptivas analizadas de las variables que pueden estar aportando más a los puntos críticos y los vanos más afectados. Cada ítem debe tener:
   - `modo`: El grupo o modo (Ej. Series Climáticas, Entorno y Riesgo, Físicas y Eléctricas, Topología, Activos Finales) analizado según la Tabla 3.1.
   - `variables_asociadas`: Las variables específicas de la Tabla 3.1 que estás conectando en este ítem.
   - `justificacion_fisico_logica`: La justificación técnica (eléctrica/física/climática) aplicada al caso, basándose estrictamente en la "Tabla 3.1 Tabla Descriptiva de Conexiones Clave" del contexto.
   - `analisis_causas`: Pequeña descripción o análisis de cómo estas conexiones explican los valores del vector de datos en los puntos críticos.

Usa los valores de `top_rows` en los días críticos, correlacionando modos de clima, infraestructura, y físicas/eléctricas. Reporta `FID_VANO`.

**OBLIGATORIO — Vegetación y DDT:** Uno de los ítems en `probable_justifications_rules` DEBE corresponder al modo "Entorno y Riesgo" con variables `NR_T` y `DDT`. Evalúa explícitamente:
- Si el nivel de `NR_T` en los puntos críticos sugiere que la vegetación pudo contribuir a los eventos o al deterioro de `UITI_VANO`.
- Si los valores de `DDT` correlacionan con mayor frecuencia de eventos o con valores elevados de `UITI_VANO`.
Ambas variables SIEMPRE están disponibles en la tabla; NUNCA afirmes que no se tienen datos de `DDT` o `NR_T`.

Contexto:
```json
{context_json}
```

Schema de salida:
```json
{output_schema_json}
```

Devuelve solo JSON valido en español. No incluyas `<think>`, markdown, comentarios, bloque ```json, ni texto antes o despues del JSON.

Mantén la salida compacta para evitar truncamiento:
- `executive_summary`: máximo 4 frases.
- `key_findings`: máximo 4 hallazgos.
- En cada hallazgo, máximo 3 evidencias y máximo 3 eventos referenciados.
- `probable_justifications_rules`: exactamente 3 ítems.
- `data_gaps`, `limitations` y `recommended_actions`: máximo 5 ítems cada uno.
- Cada texto explicativo debe ser breve, de 1 a 3 frases.

**PROHIBIDO:** rag, bitacora, normativa, modelo M-GCECDL, mascara, what-if, simulacion, reporte final, causó definitivamente, demuestra que, la causa fue.
**IDs:** Usa solo los `critical_point_id` del contexto. Si no aplica, usa `null`.
