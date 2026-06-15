Version del prompt: {prompt_version}

Analiza el comportamiento de `UITI_VANO` para los circuitos y periodo seleccionados.
Usa los puntos criticos entregados como evidencia y produce un diagnostico
consolidado del periodo.

Conecta la caracterización del circuito con la evolución temporal de `events` y `UITI_VANO`.
El campo `circuit_characterization` es un objeto. DEBES:
1. `text`: Síntesis de la criticidad del circuito.
2. `p97_vanos_uiti_vano` y `p97_vanos_eventos`: Copiar los vanos top P97 del contexto.
3. `top_3_modes_related`: 3 modos más relacionados con los targets.
4. `probable_justifications_rules`: Causas probables según reglas físico-lógicas.

Usa los valores de `top_rows` en los días críticos, correlacionando clima e infraestructura. Reporta `FID_VANO`.

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
