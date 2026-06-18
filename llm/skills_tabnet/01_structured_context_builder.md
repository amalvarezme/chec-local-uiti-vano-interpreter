# 01 - Structured Context Builder TabNet CHEC

Esta skill indica como leer el paquete de contexto que recibe un agente para analizar un
circuito elegido por el usuario en el flujo TabNet/CHEC. No debe asumir circuito, fechas,
Top-N, numero de features ni rutas fijas: esos valores vienen del cuaderno, del usuario o
del `context_package` generado antes de la interpretacion.

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
- `model_path`: modelo TabNet de clasificacion ya entrenado.
- `X`: matriz numerica filtrada para el circuito-periodo.
- `features`: nombres de columnas de `X`, en el mismo orden.
- `base`: dataframe original filtrado, alineado posicionalmente con `X`.
- `modos`: agrupacion de variables en modos CHEC.
- `shap_extractor`: explicador Kernel SHAP configurado sobre el mismo `X`.
- `tabla_periodo`: agregacion por vano para el periodo filtrado.
- `graph_knowledge`: Resumen de grafo extraído por Graphify (opcional).

Si un campo no viene explicito, el agente debe buscarlo en las salidas del cuaderno o
marcarlo como no disponible. No debe inventarlo.

## Como interpretar el contexto

La estructura minima que hace valido el analisis es:

1. Un circuito seleccionado.
2. Una ventana temporal.
3. Eventos filtrados de ese circuito y ventana.
4. `X` y `base` con el mismo numero de filas.
5. `features` con el mismo numero de columnas que `X`.
6. Un modelo TabNet compatible con esas features.
7. Un explicador SHAP inicializado sobre ese mismo subconjunto.
8. Modos CHEC construidos a partir de las variables disponibles.

Si falta alguno de estos puntos, el agente puede describir lo que falta, pero no debe
producir conclusiones de criticidad.

## Flujo conceptual del cuaderno

El cuaderno sigue este patron, aunque los valores concretos cambien por usuario:

1. Cargar datos procesados y variables seleccionadas.
2. Filtrar por circuito elegido y periodo elegido.
3. Crear `X` filtrado y `base` filtrada con indices reiniciados.
4. Crear una columna de dia (`_FECHA_DIA`) para comparar con fechas de interes.
5. Cargar el modelo TabNet de clasificacion.
6. Crear el explicador Kernel SHAP para ese circuito-periodo.
7. Agregar eventos por `FID_VANO`.
8. Construir modos CHEC usando las features disponibles.
9. Ejecutar escenarios de severidad, frecuencia y fechas de interes.
10. Interpretar barras de variables, radar por modos y coherencia con grafo experto.

## Invariantes que no se deben romper

- `X` y `base` deben estar alineados fila a fila.
- `base` debe usar indice posicional continuo despues del filtro, porque el cache SHAP usa
  indices enteros de `X`.
- `features` define el orden de columnas de `X`.
- Cualquier matriz de adyacencia entre variables debe respetar exactamente el orden de
  `features`.
- `UITI_VANO` es la variable objetivo. No debe tratarse como predictor de TabNet si el flujo
  la separo de `X`.
- Los modos CHEC solo pueden agrupar variables que existan en `features`.

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
  "explicador": "Kernel SHAP + Borda ponderado",
  "normalizacion_graficos": "min-max 0-1 dentro de cada escenario"
}
```

Los placeholders deben reemplazarse por valores reales. Si un valor no esta disponible,
usar `null` o una nota explicita de ausencia.
