# 01 - Structured Context Builder CHEC

Esta skill indica como leer el paquete de contexto que recibe un agente para analizar un
circuito elegido por el usuario en los flujos CHEC/MGCECDL/inferencia. No debe asumir
circuito, fechas, Top-N, numero de features ni rutas fijas: esos valores vienen del
cuaderno, del usuario o del `context_package` generado antes de la interpretacion.

El eje de interpretacion es el grafo usado para entrenar o contrastar el modelo. Ese grafo
no es un grafo generico fijo: se reconstruye o carga alineado al vector `features` de la
corrida. Por eso, todo resultado de interpretabilidad debe leerse junto con:

- Las variables seleccionadas que llegaron a `X`.
- El orden exacto de `features`.
- La matriz de adyacencia alineada a ese orden, si esta disponible.
- Las aristas preservadas que conectan variables retenidas pasando por nodos originales no
  retenidos.
- El contexto semantico original de los modos CHEC, aunque el modelo haya usado solo un
  subconjunto de nodos o variables.

En el flujo MGCECDL actual solo se documenta la rama de clasificacion. `UITI_VANO` puede
estar marcado en el Excel de seleccion, pero el preprocesamiento lo excluye de `features`
porque es el objetivo o la base para generar clases de impacto. El agente debe tratarlo
como objetivo, criterio de priorizacion o columna de reporte, nunca como predictor usado
por el clasificador.

## Que va a recibir el agente

El agente puede recibir todo o parte de estos elementos:

- `circuito_interes`: circuito seleccionado por el usuario.
- `fecha_inicio` y `fecha_fin`: ventana temporal de analisis.
- `fechas_interes`: fechas puntuales o dias criticos que se quieren contrastar.
- `top_n_vanos`: cantidad maxima de vanos a priorizar por escenario.
- `top_k_vars`: cantidad de variables explicativas retenidas por evento o escenario.
- `filtro_uiti_max`: umbral usado para excluir valores extremos antes de entrenar o analizar.
- `ventana_climatica_horas`: cantidad de lags climaticos incluidos.
- `dataset_path`: fuente de eventos/indicadores.
- `variables_seleccion_path`: fuente de variables seleccionadas.
- `model_path`: modelo de clasificacion ya entrenado.
- `X`: matriz numerica filtrada para el circuito-periodo.
- `features`: nombres de columnas de `X`, en el mismo orden.
- `base`: dataframe original filtrado, alineado posicionalmente con `X`.
- `modos`: agrupacion de variables en modos CHEC.
- `shap_extractor`: explicador Kernel SHAP configurado sobre el mismo `X`.
- `tabla_periodo`: agregacion por vano para el periodo filtrado.
- `graph_adjacency_matrix`: matriz dirigida de relaciones entre variables retenidas.
- `graph_preserved_edges`: lista de conexiones directas o virtuales preservadas entre
  variables retenidas.
- `graph_feature_order`: orden de variables usado al guardar/cargar la matriz del grafo.
- `graph_output_dir`: carpeta donde el cuaderno 05 guarda grafos HTML, usualmente
  `reports/mgcecdl-results/interactive_graphs/`.
- `graph_html_paths`: rutas HTML generadas por escenario, por ejemplo
  `top_uiti_periodo.html`, `top_frecuencia_periodo.html`, `top_uiti_fechas.html` y
  `top_frecuencia_fechas.html`.
- `estimated_graph_source`: fuente del grafo estimado; para MGCECDL debe describirse como
  reconstruccion del modelo + similitud RBF entre perfiles de variables.
- `estimated_graph_rbf_sigma`: sigma RBF tomado del mejor estudio Optuna cuando este
  disponible.
- `modelo_tipo`: `clasificacion`, `mgcecdl` o `inferencia`, si el contexto lo
  informa.

Si un campo no viene explicito, el agente debe buscarlo en las salidas del cuaderno o
marcarlo como no disponible. No debe inventarlo.

## Como interpretar el contexto

La estructura minima que hace valido el analisis es:

1. Un circuito seleccionado.
2. Una ventana temporal.
3. Eventos filtrados de ese circuito y ventana.
4. `X` y `base` con el mismo numero de filas.
5. `features` con el mismo numero de columnas que `X`.
6. Un modelo compatible con esas features.
7. Un explicador SHAP inicializado sobre ese mismo subconjunto.
8. Modos CHEC construidos a partir de las variables disponibles.
9. Si hay grafo, matriz y aristas alineadas exactamente con `features`.

Si falta alguno de estos puntos, el agente puede describir lo que falta, pero no debe
producir conclusiones de criticidad.

## Flujo conceptual del cuaderno

El cuaderno sigue este patron, aunque los valores concretos cambien por usuario:

1. Cargar datos procesados y variables seleccionadas.
2. Filtrar por circuito elegido y periodo elegido.
3. Crear `X` filtrado y `base` filtrada con indices reiniciados.
4. Crear una columna de dia (`_FECHA_DIA`) para comparar con fechas de interes.
5. Cargar el modelo entrenado de clasificacion.
6. Crear el explicador Kernel SHAP para ese circuito-periodo.
7. Agregar eventos por `FID_VANO`.
8. Construir modos CHEC usando las features disponibles.
9. Ejecutar escenarios de severidad, frecuencia, fechas de interes por severidad y fechas
   de interes por frecuencia.
10. Interpretar barras de variables, radar por modos y coherencia con el grafo de
    entrenamiento.
11. Guardar un grafo HTML por escenario cuando el cuaderno lo solicite. En el cuaderno 05
    estos grafos se estiman desde la capa de reconstruccion MGCECDL para las muestras del
    escenario, se normalizan por la conexion maxima y se escriben en disco sin incrustarlos
    como visualizacion del notebook.

## Invariantes que no se deben romper

- `X` y `base` deben estar alineados fila a fila.
- `base` debe usar indice posicional continuo despues del filtro, porque el cache SHAP usa
  indices enteros de `X`.
- `features` define el orden de columnas de `X`.
- Si `UITI_VANO` aparece en el archivo de seleccion, debe quedar excluido de `features`.
  Su presencia en tablas agregadas (`UITI_VANO`, `UITI_VANO_PROM`) no implica que haya sido
  predictor.
- Cualquier matriz de adyacencia entre variables debe respetar exactamente el orden de
  `features`.
- `UITI_VANO` es la variable objetivo. No debe tratarse como predictor si el flujo la separo
  de `X`.
- Los modos CHEC solo pueden agrupar variables que existan en `features`.
- Si la matriz fue construida con una seleccion previa de variables, no debe reutilizarse
  para otra corrida con distinto `features`.
- Una arista preservada indica trazabilidad en el grafo experto original, no conexion
  fisica directa ni relacion aprendida por el modelo.
- Una variable importante nunca debe interpretarse aislada: revisar su modo, sus rutas y su
  cercania conceptual a `UITI_VANO`.

## Chequeos minimos antes de interpretar

Antes de narrar resultados, verificar y reportar:

- Circuito recibido.
- Periodo recibido.
- Fechas de interes recibidas, si aplica.
- Numero de eventos filtrados.
- Numero de vanos unicos.
- Numero de features.
- Que `len(X) == len(base)`.
- Que `len(features) == X.shape[1]`.
- Que el Top-N efectivo no excede los vanos disponibles.
- Que el escenario de fechas tiene eventos antes de interpretarlo.
- Si hay matriz de adyacencia, que su forma sea `(len(features), len(features))`.
- Si hay aristas preservadas, distinguir `is_virtual=True` de aristas directas.
- Si hay grafos HTML del cuaderno 05, reportar sus rutas como entregables guardados, no
  como figuras inline del notebook.
- Si se usa grafo estimado por reconstruccion, distinguirlo del grafo experto de
  entrenamiento.
- Si se mencionan variables que no aparecen en `features`, tratarlas solo como contexto de
  nodos originales y no como predictores usados.

## Salida esperada del contexto

El agente puede representar el contexto con valores reales del paquete recibido:

```json
{
  "circuito": "<circuito_recibido>",
  "periodo": {
    "inicio": "<fecha_inicio_recibida>",
    "fin": "<fecha_fin_recibida>"
  },
  "fechas_interes": ["<fechas_recibidas_si_aplican>"],
  "n_eventos": "<valor_observado>",
  "n_vanos": "<valor_observado>",
  "n_features": "<valor_observado>",
  "top_n_configurado": "<valor_recibido>",
  "top_n_efectivo": "<valor_observado>",
  "top_k_vars": "<valor_recibido>",
  "modelo": "<modelo_recibido>",
  "features": "<lista_o_resumen_de_features_recibidas>",
  "grafo": {
    "matriz_shape": ["<n_features>", "<n_features>"],
    "n_aristas_preservadas": "<valor_observado>",
    "orden_alineado_a_features": "<true_false_o_desconocido>",
    "html_estimados": ["<ruta_html_si_existe>"],
    "fuente_html": "reconstruccion_mgcecdl_rbf_o_null"
  },
  "explicador": "Kernel SHAP + Borda ponderado",
  "normalizacion_graficos": "min-max 0-1 dentro de cada escenario"
}
```

Los placeholders deben reemplazarse por valores reales. Si un valor no esta disponible,
usar `null` o una nota explicita de ausencia.

## Contexto minimo de variables y modos

El agente puede usar estas definiciones sin depender de otros documentos:

- `CIRCUITO`: codigo del circuito al que pertenece el vano.
- `FID_VANO`: identificador espacial del vano; es la unidad operativa de agregacion.
- `FECHA`: fecha y hora del evento.
- `DURACION`: duracion total de la interrupcion.
- `TOT_USUS`: total de usuarios afectados por la falla.
- `UITI`: indicador de usuarios interrumpidos por tiempo de interrupcion.
- `UITI_VANO`: `UITI` ponderado por el aporte relativo del vano; es el objetivo de impacto.
- `PORC_APORTE_VANO`: participacion del vano dentro del conjunto protegido por el equipo.
- `FID_SW`, `COD_EQ_PROTEGE`, `TIPO`: identifican equipo y tipo de proteccion/maniobra.
- `T_USUS_EQ_PROT`: usuarios desconectados por la apertura del equipo protector.
- `LVSW`, `CNT_VN`, `CNT_VN_SW`: distancia/cantidad de vanos hacia o bajo proteccion.
- `X1`, `Y1`, `X2`, `Y2`: coordenadas de inicio y fin del vano.
- `LONGITUD`, `CNT_FASES`, `CONDUCTOR`, `CALIBRE_NEUTRO`, `NG_RED`, `TIPO_TAX`:
  caracteristicas fisicas y electricas del tramo.
- `COD_APOYO_FIN`, `FID_APOYO_FIN`, `ALTURA`, `CANTIDAD_TIERRA`, `CLASE`, `ELEMENTO`,
  `NORMA`, `VAL_CRIT_APOYO`, `LONG_CRUCETA`: contexto del apoyo final.
- `FID_TRAFO`, `CODIGO`, `CAPACIDAD_NOMINAL`, `CNT_USUS`, `FECHA_OPERACION_TRF`,
  `PROMEDIO_KWH_TRF`: contexto del transformador y usuarios asociados.
- `NR_T`: nivel de riesgo asociado a vegetacion cercana al vano.
- `DDT`: densidad de descargas a tierra promedio en la zona.
- Familias climaticas con lags: `prep`, `temp`, `wind_gust_spd`, `wind_spd`, `clouds`,
  `pres`, `sp`, `rh`, `solar_rad`. El sufijo `_i` representa una ventana horaria previa al
  evento; `0` es la mas cercana al evento.

Modos CHEC:

- Evento, impacto e indicadores.
- Infraestructura de proteccion y maniobra.
- Topologia y configuracion espacial.
- Caracteristicas fisicas y electricas del vano.
- Activos: apoyo final y transformador.
- Entorno, riesgo y clima.
