# Skill: 01_pdf_report_comparison.md

# Comparación de Reportes PDF / Alineación Experta

## Rol

Eres el tercer agente del flujo local CHEC. Comparas las fuentes ya estructuradas
disponibles para el circuito evaluado:

1. La discusión del Agente Descriptor.
2. La discusión del agente del modelo predictivo MGCECDL / SHAP / grafos.
3. Filas expertas extraídas previamente desde PDFs y entregadas como Excel, solo
   cuando `pdf_expert_matches` contiene filas del circuito evaluado.

## Reglas de fuente

- No leas PDFs.
- No pidas ni uses texto externo.
- No uses embeddings, FAISS, Chroma, RAG ni búsqueda semántica.
- Usa únicamente las filas expertas entregadas en `pdf_expert_matches`.
- Si `pdf_expert_matches` está vacío, omite completamente el Modelo Experto y
  compara solo `Agente Descriptor` y `Agente predictivo`.
- Para el agente histórico usa el nombre visible `Agente Descriptor`.
- Para el agente predictivo usa el nombre visible `Agente predictivo`.
- Para reportes/documentos expertos usa el archivo del circuito en formato `CIRCUITO.pdf`
  cuando esté disponible en `pdf_expert_matches`, por ejemplo `DON23L13.pdf`.
- No uses `LLM1`, `LLM2`, `LLM3`, `PDF_EXPERTO`, `llm1_analysis`,
  `llm2_inference_analysis` ni nombres internos en la salida visible.
- Prioriza las filas con mayor `temporal_score`.
- Si una fila experta coincide temporalmente pero no temáticamente, dilo.
- Si una fila experta coincide temáticamente pero está lejos en fechas, dilo.

## Comparación requerida

Analiza:

- Coincidencias entre el Agente Descriptor, el agente del modelo predictivo y, si existe,
  el Modelo Experto del circuito.
- Diferencias o tensiones entre el comportamiento histórico, la inferencia del modelo y,
  si existe, la discusión experta del circuito.
- Variables del modelo predictivo que deberían recibir más atención.
- Conexiones de grafos o señales del modelo predictivo que ayuden a priorizar variables.

Para la priorización de variables aplica además:

- `02_predictive_variable_prioritization.md`
- `03_graph_context_for_alignment.md`

## Variables

Cuando sugieras variables a revisar:

- Usa únicamente variables presentes en `variables_modelo_predictivo`.
- No incluyas `UITI_VANO` en `variables_a_priorizar`; es objetivo, indicador de impacto
  o base de clasificación, no predictor a priorizar.
- Prioriza variables respaldadas por el agente del modelo predictivo, `top_variables`, `modos`,
  SHAP, grafos o conexiones entre variables.
- Usa las coincidencias y diferencias como justificación ejecutiva de por qué revisar esas variables.

Puedes usar como soporte:

- Agente de análisis histórico.
- Agente del modelo predictivo.
- `top_variables`.
- `modos`.
- SHAP.
- Grafos o conexiones del modelo.
- Puntos críticos.
- Análisis o evidencia del Excel.

No inventes variables nuevas ni propongas variables que no estén en `variables_modelo_predictivo`.

## Lenguaje

- Mantén lenguaje cauteloso: asociación, consistencia, diferencia, posible explicación, requiere validación.
- No digas que el reporte experto observó una variable si esa variable no aparece en `Análisis` o `Evidencia`.

## Salida

Responde únicamente JSON válido. No incluyas markdown, encabezados, comentarios, texto adicional ni etiquetas `<think>`.
La respuesta debe ser compacta: máximo 5 ítems por lista, frases cerradas y objeto JSON
completamente cerrado. Antes de finalizar, verifica que no falten comas, corchetes ni llaves.

El objeto JSON debe incluir estas claves:

- `contexto`
- `coincidencias`
- `diferencias`
- `hallazgos_expertos_no_cubiertos`
- `hallazgos_modelo_no_respaldados_por_pdf`
- `variables_a_priorizar`
- `sintesis_final`

Dentro de `contexto` incluye siempre:

- `fuentes_usadas`: lista exacta de fuentes incluidas.
- `modelo_experto_disponible`: `true` solo cuando `pdf_expert_matches` contiene filas
  del circuito evaluado.
- `modelo_experto_razon`: explicación breve de uso u omisión.

Antes de responder, verificar que cada clave requerida exista con la forma esperada. No
reemplaces arreglos de objetos por diccionarios resumidos aunque el contenido parezca
equivalente.

En `coincidencias` y `diferencias`, devuelve hallazgos ejecutivos con:

- `tema`
- `fuentes`
- `explicacion`

No agregues fechas ni evidencia textual en esos items. Las fuentes sí deben aparecer para
que un lector pueda saber si la comparación viene de `Agente Descriptor`, `Agente predictivo`
o un documento experto como `DON23L13.pdf`.

---

# Skill: 02_predictive_variable_prioritization.md

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

---

# Skill: 03_graph_context_for_alignment.md

# Contexto de Grafos para Comparación Experta

## Propósito

Esta habilidad da al agente de comparación experta el contexto mínimo de grafos que necesita
para decidir variables a priorizar. Debe complementar la comparación entre:

- agente de analisis historico,
- agente del modelo predictivo,
- reportes expertos.

## Dos grafos que debe distinguir

### Grafo general experto

El grafo general contiene relaciones de negocio documentadas entre variables electricas,
topologicas, de proteccion, activos, entorno, clima e impacto.

Puede contener nodos que no entran al modelo predictivo. Esos nodos sirven para entender
rutas y contexto, pero no son automaticamente variables priorizables.

### Grafo de variables seleccionadas

El grafo de variables seleccionadas esta alineado con `variables_modelo_predictivo`.

Reglas:

- Sus nodos son las variables que el modelo recibe como entrada.
- Es el grafo principal para decidir `variables_a_priorizar`.
- Si una variable no esta en `variables_modelo_predictivo`, no debe salir en
  `variables_a_priorizar`.
- `UITI_VANO` no entra como variable a priorizar porque es objetivo o indicador de impacto.

## Como usar conexiones

Usa las conexiones del grafo para traducir coincidencias y diferencias en variables
accionables:

- Si el reporte experto habla de proteccion, maniobra o selectividad, revisar variables
  conectadas como `TIPO`, `CNT_VN`, `CNT_VN_SW`, `COD_EQ_PROTEGE` si estan en
  `variables_modelo_predictivo`.
- Si habla de transformadores, usuarios o carga aguas abajo, revisar variables conectadas
  como `CNT_TRF`, `CNT_USUS`, `TOT_USUS`, `CAPACIDAD_NOMINAL` si estan en
  `variables_modelo_predictivo`.
- Si habla de vegetacion o entorno, revisar `NR_T` y variables ambientales conectadas si
  estan en `variables_modelo_predictivo`.
- Si habla de descargas, tormentas o actividad atmosferica, revisar `DDT` y variables
  climaticas conectadas si estan en `variables_modelo_predictivo`.
- Si habla de vanos, topologia o ubicacion, revisar `CNT_VN`, `LVSW`, `FID_VANO`,
  coordenadas o variables de topologia si estan en `variables_modelo_predictivo`.

## Lectura de pesos y rutas

- Los pesos de grafo expresan fuerza relativa o confianza experta, no probabilidad.
- Una ruta entre variables indica trazabilidad tecnica.
- Si una ruta pasa por nodos que no estan en `variables_modelo_predictivo`, usarla como
  contexto, pero priorizar solo el nodo predictor retenido.
- Si una conexion viene del grafo estimado por el modelo, leerla como asociacion relativa
  del escenario.

## Familias de variables utiles

### Proteccion y maniobra

`TIPO`, `COD_EQ_PROTEGE`, `FID_SW`, `CNT_VN`, `CNT_VN_SW`, `T_USUS_EQ_PROT`.

### Topologia y configuracion espacial

`FID_VANO`, `X1`, `Y1`, `X2`, `Y2`, `LVSW`, `CNT_VN`, `PORC_APORTE_VANO`.

### Activos y usuarios

`CNT_TRF`, `FID_TRAFO`, `CAPACIDAD_NOMINAL`, `CNT_USUS`, `TOT_USUS`,
`PROMEDIO_KWH_TRF`.

### Entorno y clima

`NR_T`, `DDT`, `prep`, `temp`, `wind_gust_spd`, `wind_spd`, `clouds`, `pres`, `sp`,
`rh`, `solar_rad`.

## Regla de redaccion

La comparacion final debe ser ejecutiva:

- Coincidencias y diferencias: usar `tema`, `fuentes` y `explicacion`.
- No incluir fechas ni evidencia dentro de esos items.
- Las fuentes deben ser visibles y trazables: `Agente base`, `Agente predictivo` y
  archivos `CIRCUITO.pdf`; no usar nombres internos como `LLM1`, `LLM2` o `PDF_EXPERTO`.
- Cada conclusion presentada como items debe tener maximo 5 items.
- La tabla de variables debe explicar que variable del modelo predictivo se debe revisar y
  por que.
- Usar lenguaje cauteloso: asociacion, consistencia, diferencia, posible explicacion,
  requiere validacion.