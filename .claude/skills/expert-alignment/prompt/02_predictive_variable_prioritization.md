# Priorización de Variables del Modelo Predictivo

## Propósito

Esta habilidad define cómo el agente de comparación experta debe convertir coincidencias y
diferencias en variables a priorizar para revisión operacional.

El público esperado son expertos en redes eléctricas. La salida debe ser clara sin exigir
conocimiento de agentes, LLMs o nombres internos como LLM1/LLM2.

## Nombres de fuentes

Usa estos nombres en lenguaje natural:

- `Agente base`: interpreta el comportamiento historico de datos.
- `Agente predictivo`: interpreta la inferencia, variables, SHAP, modos y grafos.
- `CIRCUITO.pdf`: filas extraidas desde documentos tecnicos en Excel. Usa el nombre
  real del circuito de la fila experta, por ejemplo `DON23L13.pdf`.

No uses `LLM1`, `LLM2`, `LLM3`, `PDF_EXPERTO`, `reportes expertos` ni nombres internos
en la redaccion visible cuando exista un archivo de circuito disponible.

## Variable objetivo

`UITI_VANO` es variable objetivo, criterio de impacto o base de clasificacion.

Reglas:

- No incluir `UITI_VANO` en `variables_a_priorizar`.
- No tratar `UITI_VANO` como predictor del modelo.
- Si aparece en textos, grafo completo, filas expertas o hallazgos, usarlo solo como
  indicador de impacto o nodo objetivo conceptual.
- La priorizacion debe enfocarse en variables que el modelo predictivo recibe como entrada.

## Variables permitidas

Las variables priorizables son unicamente las presentes en `variables_modelo_predictivo`.

Reglas:

- No inventar variables.
- No proponer variables que no esten en `variables_modelo_predictivo`.
- No convertir nombres descriptivos en variables nuevas.
- Si una variable aparece en los reportes expertos pero no esta en
  `variables_modelo_predictivo`, mencionarla solo como contexto dentro de coincidencias o
  diferencias, no como variable priorizada.

## Alias descriptivos

Si las fuentes usan nombres descriptivos, traducirlos al identificador tecnico solo cuando
ese identificador exista en `variables_modelo_predictivo`:

- cantidad de transformadores, `cantidad_transformadores`, transformadores -> `CNT_TRF`
- cantidad de vanos, `cantidad_vanos`, vanos -> `CNT_VN`
- tipo de equipo, `tipo_equipo`, proteccion, maniobra -> `TIPO`
- vegetacion -> `NR_T`
- descargas a tierra, rayos, descargas atmosfericas -> `DDT`

Si el identificador tecnico no existe en `variables_modelo_predictivo`, no priorizarlo.

## Cómo Decidir Prioridad

Prioriza una variable cuando haya consistencia entre al menos dos de estas senales:

- Coincidencia entre analisis historico y modelo predictivo.
- Coincidencia entre modelo predictivo y reportes expertos.
- Diferencia relevante que sugiera una revision operacional.
- Presencia en `top_variables`.
- Presencia en modos CHEC relevantes.
- Peso o lectura relevante en SHAP, Borda, radar o salida equivalente.
- Ruta o conexion en el grafo general o en el grafo de variables seleccionadas.

Cuando una variable no coincida literalmente con un reporte experto, puedes priorizarla si
el grafo muestra una conexion tecnica razonable con el hallazgo comparado. La redaccion debe
decir "asociada", "conectada" o "consistente con".

## Salida esperada

En `variables_a_priorizar` usa objetos con:

- `variable`: identificador tecnico exacto presente en `variables_modelo_predictivo`.
- `prioridad`: `alta`, `media` o `baja`.
- `fuentes_que_la_respaldan`: nombres legibles de fuentes, no codigos internos. Usa
  `Agente base`, `Agente predictivo` y archivos `CIRCUITO.pdf`.
- `justificacion`: una frase ejecutiva.
- `tipo_de_validacion_sugerida`: una accion de revision operacional o tecnica.

Mantener maximo 5 variables cuando exista evidencia suficiente. Si hay menos evidencia,
usar menos variables. Si hay mas candidatas, priorizar las de mayor soporte combinado entre
coincidencias, diferencias, señales del modelo y grafos.
