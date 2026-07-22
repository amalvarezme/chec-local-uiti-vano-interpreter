# 03 - Explicador del Comportamiento de `UITI_VANO`

Esta habilidad explica cómo traducir `UITI_VANO`, resultados MGCECDL/inferencia y atribuciones a
lenguaje de negocio eléctrico. El agente debe adaptar la explicación al circuito, periodo y
eventos que reciba, sin asumir valores fijos.

La interpretación debe apoyarse en el grafo de entrenamiento. Una variable relevante para
el modelo se explica mejor cuando se conectan cuatro piezas: importancia del modelo,
modo CHEC, relación en el grafo y significado operativo.

En la salida JSON del notebook principal, esta explicación debe ser sintética. No escribir
una explicación larga por cada variable. Priorizar las 3 a 5 variables principales de cada
escenario, agrupar lecturas por modo cuando sea posible y dejar el detalle visual a las
barras, radares y grafos HTML.

En MGCECDL, el flujo vigente es de clasificación. `UITI_VANO` se usa como objetivo,
criterio de severidad o base para clases ordinales de impacto; aunque aparezca en el Excel
de selección de variables, debe excluirse de `features` y no debe narrarse como predictor
del modelo.

## Qué va a recibir el agente

El agente puede recibir:

- Valores de `UITI_VANO` por evento.
- `UITI_VANO_PROM` agregado por vano.
- Rankings de vanos por severidad o recurrencia.
- Variables Top-K explicadas por SHAP/inferencia.
- Variables Top-K explicadas por SHAP, atención, soporte modal o importancia por
  permutación.
- Modos CHEC con scores normalizados.
- Fechas de interes o subconjuntos de eventos.
- Matriz de adyacencia y aristas preservadas del grafo usado por la corrida.
- Rutas HTML de grafos estimados por escenario generados desde
  `notebooks/project_flow/05_mgcecdl_circuit_analysis.ipynb`.

El agente debe distinguir siempre la granularidad:

- Evento: una fila de interrupcion/indicador.
- Vano: agregacion por `FID_VANO`.
- Circuito: agregacion o filtro superior.
- Escenario: subconjunto analitico definido por severidad, frecuencia o fechas.

## Qué Representa `UITI_VANO`

`UITI_VANO` es una medida de impacto de interrupción a nivel de vano. Operativamente
relaciona usuarios afectados, tiempo de interrupción y aporte del vano dentro del evento o
del circuito analizado.

En la logica experta del proyecto, el impacto se entiende mediante rutas como:

```text
DURACION + TOT_USUS -> UITI -> UITI_VANO
PORC_APORTE_VANO -> UITI_VANO
```

Donde:

- `DURACION` y `TOT_USUS` son entradas definicionales de `UITI`.
- `UITI` y `PORC_APORTE_VANO` son entradas definicionales o directas de `UITI_VANO`.
- `FECHA` puede conectar contexto temporal con `UITI_VANO`, pero con interpretacion
  contextual.
- Variables aguas arriba como clima, riesgo, topologia, proteccion, activos o conductor
  deben narrarse como contexto predictivo o hipotesis operativa.

Por tanto, valores altos pueden estar asociados a:

- Duraciones mayores.
- Mas usuarios afectados.
- Mayor participacion del vano en el impacto del evento.
- Concentracion de usuarios aguas abajo de una proteccion.
- Condiciones fisicas, topologicas, de activos o entorno que el modelo encontro predictivas.

## Diferencia entre predictor, objetivo y contexto

- Predictor: variable presente en `features` y usada por el modelo.
- Objetivo: variable que el modelo intenta predecir o clasificar; en estos flujos es
  `UITI_VANO` o una clase derivada de `UITI_VANO`.
- Contexto original: nodo/modo del grafo experto que puede no estar en `features`, pero
  conserva significado para explicar una arista preservada o una ruta conceptual.

Si `UITI_VANO` no esta en `features`, no debe describirse como variable explicativa del
modelo. Puede describirse como objetivo y como nodo final de rutas del grafo.
Si `UITI_VANO` aparece en `Variables_seleccion.xlsx`, esto no cambia la regla: el
preprocesamiento lo omite de `X` para evitar fuga de informacion.

## Como interpretar severidad y recurrencia

No mezclar estos conceptos:

- `UITI_VANO` o `UITI_VANO_PROM`: severidad/impacto.
- `N_APARICIONES`: recurrencia/frecuencia.
- Top por fechas de interes: foco temporal sobre eventos especificos.

Lecturas tipicas:

- Alto impacto y alta frecuencia: vano prioritario por criticidad y recurrencia.
- Alto impacto y baja frecuencia: evento o vano severo, pero no necesariamente cronico.
- Baja severidad y alta frecuencia: comportamiento repetitivo con impacto contenido.
- Alto impacto en fechas de interes: contribucion relevante a dias criticos seleccionados.

## Clasificación

El flujo de clasificacion discretiza `UITI_VANO` en clases ordinales de impacto. El numero
exacto de clases, umbrales o percentiles debe leerse del contexto del modelo o del cuaderno
que genero el resultado.

Los resultados de clasificacion deben narrarse como clase, probabilidad o nivel de impacto.
No hablar de prediccion puntual continua de `UITI_VANO` salvo que el contexto entregue
explicitamente un valor agregado observado, como `UITI_VANO_PROM`.

Si el agente recibe probabilidades o atribuciones SHAP, debe aclarar:

- La explicacion corresponde a la salida del modelo usada por el explicador.
- No necesariamente resume todas las clases ordinales.

## Grafos HTML como entregable interpretativo

El cuaderno 05 puede generar grafos interactivos HTML por escenario en
`reports/mgcecdl-results/interactive_graphs/`. Estos grafos:

- Se estiman con la capa de reconstruccion del clasificador MGCECDL para las muestras del
  escenario.
- Usan similitud RBF entre perfiles reconstruidos de variables.
- Muestran pesos normalizados por la conexion maxima del grafo (`0-1`) en notacion
  cientifica.
- Eliminan doble direccion y flechas.
- Complementan barras SHAP+Borda y radar por modos; no los reemplazan.

Al narrarlos, usar frases como "el grafo estimado muestra asociacion relativa entre..." y
evitar "el grafo demuestra que...".

En salidas JSON del cuaderno `02_local_uiti_vano_interpretability_v3.ipynb`, los grafos
HTML recibidos deben sintetizarse en dos entradas generales de `discusion_grafos` cuando
apliquen: `seccion="periodo_completo"` para los grafos del periodo completo y
`seccion="puntos_criticos"` para los grafos de fechas o puntos criticos. Cada lectura debe
conectar variables o modos relevantes con asociaciones relativas del grafo estimado, sin
repetir solo rutas de archivo y sin duplicar discusion por
escenario.

La forma JSON obligatoria de esas lecturas es una lista de objetos:

```json
[
  {"seccion": "periodo_completo", "lectura": "..."},
  {"seccion": "puntos_criticos", "lectura": "..."}
]
```

No devolver `discusion_grafos` como diccionario. Si existen grafos de ambas secciones, ambas
entradas son obligatorias.

## Lectura por modos CHEC

### Evento, impacto e indicadores

Incluye `FECHA`, `DURACION`, `UITI`, `TOT_USUS`, `CNT_TRF`, `COD_CAUSA`, `DESC_CAUSA` e
indicadores cercanos al objetivo.

Interpretacion:

- Dominancia de este modo significa que el modelo explica el resultado desde la huella
  operacional del evento.
- Puede indicar que la severidad esta muy ligada a usuarios afectados, duracion o causa
  registrada.

### Infraestructura de proteccion y maniobra

Incluye `FID_SW`, `COD_EQ_PROTEGE`, `TIPO`, `CNT_VN`, `CNT_VN_SW` y
`T_USUS_EQ_PROT`.

Interpretacion:

- Dominancia de este modo sugiere revisar configuracion de protecciones, maniobra,
  selectividad y concentracion de usuarios aguas abajo.

### Topologia y configuracion espacial

Incluye `CIRCUITO`, `FID_VANO`, `X1`, `Y1`, `X2`, `Y2`, `LVSW`, `CNT_VN` y
`PORC_APORTE_VANO`.

Interpretacion:

- Dominancia de este modo sugiere que la ubicacion del vano o su posicion en el circuito
  ayuda a explicar el patron del modelo.

### Caracteristicas fisicas y electricas del vano

Incluye `FECHA_OPERACION_VANO`, `LONGITUD`, `CNT_FASES`, `CONDUCTOR`,
`CALIBRE_NEUTRO`, `NG_RED`, `PROMEDIO_KWH_VANO` y `TIPO_TAX`.

Interpretacion:

- Dominancia de este modo orienta la discusion a condicion fisica, configuracion electrica
  o caracteristicas estructurales del tramo.

### Activos: apoyo final y transformador

Incluye `COD_APOYO_FIN`, `FID_APOYO_FIN`, `PROPIETARIO`, `CLASE`, `ELEMENTO`, `NORMA`,
`ALTURA`, `LONG_CRUCETA`, `CANTIDAD_TIERRA`, `VAL_CRIT_APOYO`, `FID_TRAFO`, `CODIGO`,
`CAPACIDAD_NOMINAL`, `CNT_USUS`, `FECHA_OPERACION_TRF` y `PROMEDIO_KWH_TRF`.

Interpretacion:

- Dominancia de este modo sugiere revisar activos asociados, concentracion de carga,
  transformadores y condiciones del apoyo.

### Entorno, riesgo y clima

Incluye `NR_T`, `DDT` y familias climaticas con lags: `prep`, `temp`,
`wind_gust_spd`, `wind_spd`, `clouds`, `pres`, `sp`, `rh` y `solar_rad`.

Interpretacion:

- Dominancia de este modo sugiere que el modelo encontro informacion predictiva en entorno
  o clima.
- Lags cercanos al evento apuntan a condiciones contemporaneas.
- Lags previos pueden sugerir persistencia, acumulacion o contexto meteorologico anterior.

## Cómo Conectar Variable, Grafo e Impacto

Para explicar una variable top:

1. Confirmar si esta en `features`.
2. Identificar su modo CHEC.
3. Buscar su ruta dirigida hacia `UITI_VANO`, si existe.
4. Indicar si la ruta es directa o preservada por nodos no retenidos.
5. Traducir la ruta a lenguaje operativo.

Ejemplos de lectura soportada por el grafo:

- `DURACION -> UITI -> UITI_VANO`: relacion directa con calculo de impacto.
- `TOT_USUS -> UITI -> UITI_VANO`: usuarios afectados conectan con magnitud de impacto.
- `PORC_APORTE_VANO -> UITI_VANO`: ponderacion del vano en el impacto.
- `TIPO -> DURACION` y `TIPO -> T_USUS_EQ_PROT -> TOT_USUS`: proteccion puede explicar
  tiempos y usuarios expuestos.
- `X1/Y1/X2/Y2 -> FID_VANO -> LVSW -> COD_EQ_PROTEGE`: coordenadas/topologia contextualizan
  posicion del tramo y relacion con proteccion.
- `prep_i` u otra familia climatica `-> ... -> COD_CAUSA`: clima con lags aporta contexto
  ambiental asociado a causa registrada.

Si una variable no tiene ruta documentada:

```text
No se encontró una ruta documentada entre <variable> y UITI_VANO. La relevancia se reporta
como comportamiento del modelo y requiere validación experta antes de usarla como hipótesis
operativa.
```

## Cómo Hablar de Impacto

Usar:

- "El vano aparece priorizado por impacto promedio."
- "El patron combina severidad y recurrencia."
- "El modelo asigno alta relevancia a variables del modo..."
- "La lectura operativa sugiere revisar..."

Evitar:

- "El modelo probo el origen del evento."
- "El vano falla por esta variable."

## Narrativa recomendada

Un parrafo interpretativo debe unir:

1. Escenario recibido.
2. Variables o modos dominantes.
3. Lectura electrica.
4. Relacion con severidad o recurrencia.
5. Cautela metodologica.
6. Relacion con el grafo de entrenamiento.

Plantilla:

```text
En el escenario <nombre>, el modelo concentra la explicacion en <modo/variables>. Para el
circuito y periodo analizados, esto sugiere que los vanos priorizados se distinguen por
<lectura_operativa>. En el grafo, <variable/ruta> conecta con <nodo_objetivo_o_intermedio>
mediante <tipo_de_conexion>. La conclusion describe el comportamiento del modelo sobre los
eventos filtrados y debe contrastarse con inspeccion operativa.
```
