Version del prompt: {prompt_version}

Analiza el comportamiento de `UITI_VANO` para los circuitos y periodo seleccionados.
Usa todos los puntos criticos entregados como evidencia y produce un diagnostico
consolidado del periodo, no un diagnostico independiente por punto.

Es **obligatorio** que tu análisis conecte la caracterización estructural del circuito (ej. su perfil en el cluster de criticidad "Muy Alta", "Alta", etc., provisto en `circuit_characterization`) con la evolución temporal explícita de `event_count` y `UITI_VANO` a lo largo del periodo.

Contexto estructurado:

```json
{context_json}
```

Esquema obligatorio de salida:

```json
{output_schema_json}
```

Devuelve solamente JSON valido en espanol.

**REGLA ESTRICTA DE VOCABULARIO:** No utilices NINGUNA de estas palabras o sus variaciones bajo ninguna circunstancia: rag, bitacora, bitácora, normativa, modelo predictivo, predice, mascara, máscara, what-if, simulacion, simulación, simulaciones, reporte final, causó definitivamente, demuestra que, la causa fue.

**REGLA DE IDENTIFICADORES:** Para `critical_point_id`, usa EXCLUSIVAMENTE los IDs literales que aparecen en el contexto. No inventes IDs nuevos (como "period-2025..."). Si un hallazgo aplica a un periodo general o no corresponde a un ID exacto del contexto, usa `null`.
