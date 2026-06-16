Version del prompt: {prompt_version}

Analiza el comportamiento de `UITI_VANO` para los circuitos y periodo seleccionados.
Usa los puntos criticos entregados como evidencia y produce un diagnostico
consolidado del periodo.

Conecta la caracterización del circuito con la evolución temporal de `events` y `UITI_VANO`.
El campo `circuit_characterization` es un objeto. DEBES:
1. `text`: Síntesis de la criticidad del circuito.
2. `p97_vanos_uiti_vano` y `p97_vanos_eventos`: Copiar los vanos top P97 del contexto.
3. `probable_justifications_rules`: Presentar al menos 3 ítems con las principales relaciones descriptivas analizadas de las variables que pueden estar aportando más a los puntos críticos y los vanos más afectados. Cada ítem debe tener:
   - `modo`: El grupo o modo (Ej. Series Climáticas, Entorno y Riesgo, Físicas y Eléctricas, Topología, Activos Finales) analizado según la Tabla 3.1.
   - `variables_asociadas`: Las variables específicas de la Tabla 3.1 que estás conectando en este ítem.
   - `justificacion_fisico_logica`: La justificación técnica (eléctrica/física/climática) aplicada al caso, basándose estrictamente en la "Tabla 3.1 Tabla Descriptiva de Conexiones Clave" del contexto.
   - `analisis_causas`: Pequeña descripción o análisis de cómo estas conexiones explican los valores del vector de datos en los puntos críticos.

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
