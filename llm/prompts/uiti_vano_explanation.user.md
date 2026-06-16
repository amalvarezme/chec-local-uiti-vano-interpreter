Version del prompt: {prompt_version}

Analiza el comportamiento de `UITI_VANO` para los circuitos y periodo seleccionados.
Usa los puntos criticos entregados como evidencia y produce un diagnostico
consolidado del periodo.

Conecta la caracterización del circuito con la evolución temporal de `events` y `UITI_VANO`.
El campo `circuit_characterization` es un objeto. DEBES:
1. `text`: Síntesis de la criticidad del circuito.
2. `p97_vanos_uiti_vano` y `p97_vanos_eventos`: Copiar los vanos top P97 del contexto.
3. `probable_justifications_rules`: Presentar al menos 3 ítems con las principales relaciones descriptivas analizadas de las variables que pueden estar aportando más a los puntos críticos y los vanos más afectados. Cada ítem debe tener:
   - `relacion_descriptiva`: Relación de las variables y su impacto (basado en el análisis por Modos de `ContextoProyectoSimuladorCHEC.md`).
   - `analisis_causas`: Pequeña descripción o análisis de las posibles causas de estos comportamientos basándose en los valores del vector de datos.

Usa los valores de `top_rows` en los días críticos, correlacionando modos de clima, infraestructura, y físicas/eléctricas. Reporta `FID_VANO`.

Contexto:
```json
{context_json}
```

Schema de salida:
```json
{output_schema_json}
```

Incluye `<think>...</think>` con razonamiento ANTES del JSON.
Luego de `</think>`, devuelve solo JSON valido en español.

**PROHIBIDO:** rag, bitacora, normativa, modelo predictivo, mascara, what-if, simulacion, reporte final, causó definitivamente, demuestra que, la causa fue.
**IDs:** Usa solo los `critical_point_id` del contexto. Si no aplica, usa `null`.
