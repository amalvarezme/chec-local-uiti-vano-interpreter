# 04 - Reglas de Conectividad de Grafos

Esta habilidad contiene el marco experto de grafo y conectividad que el agente debe usar para
interpretar resultados CHEC/MGCECDL/inferencia. Es autocontenida: el agente no debe depender
de una fuente externa para conocer las relaciones de negocio descritas aquí.

## Qué va a recibir el agente

El agente puede recibir:

- `features`: variables seleccionadas y ordenadas como columnas de `X`.
- Una matriz de adyacencia entre variables, si ya fue construida.
- Aristas preservadas, si el flujo las entrega.
- Top variables de inferencia por evento, vano, circuito o escenario.
- Top variables de MGCECDL por SHAP/permutacion o soportes por modalidad.
- Modos CHEC y scores por modo.

Si recibe una matriz, debe interpretarla asi:

```text
matriz[i, j] = peso de la arista dirigida features[i] -> features[j]
```

La forma esperada siempre es:

```text
(len(features), len(features))
```

Si el contexto informa `N` features, entonces la matriz sera `N x N`. Si una corrida
particular informa 83 features, esa corrida tendra matriz 83x83; si el usuario cambia la
seleccion de variables o la ventana de datos y cambia `features`, la matriz debe cambiar
con ese nuevo tamano.

## Rol del grafo

El grafo codifica conocimiento experto sobre relaciones esperadas entre clima, riesgo,
topologia, proteccion, activos, usuarios e impacto.

En MGCECDL, la matriz del grafo tambien participa en el entrenamiento mediante componentes
de reconstruccion y regularizacion basadas en la estructura de variables. En inferencia, el
grafo se usa para contrastar interpretaciones, no como entrada directa del modelo. En ambos
casos, la explicacion posterior debe usar el grafo alineado a `features` como referencia
principal.

En el flujo MGCECDL actual solo permanece la tarea de clasificacion. `UITI_VANO` es
objetivo o base de clases de impacto; si aparece en el archivo de seleccion, se excluye de
`features` antes de entrenar. No debe tratarse como nodo predictor del clasificador.

Uso correcto:

- Contrastar si una variable importante para el modelo tiene una ruta experta hacia
  `UITI_VANO`.
- Agrupar hallazgos por rutas o familias de negocio.
- Detectar discrepancias entre modelo y conocimiento experto.

Uso incorrecto:

- Decir que inferencia uso directamente el grafo para predecir.
- Decir que una variable aislada explica el resultado sin revisar su posicion en el grafo.
- Tratar pesos del grafo como coeficientes aprendidos por el modelo.
- Ignorar la direccion de las aristas.

## Tipos de grafo en el flujo actual

El agente debe distinguir tres niveles:

1. **Grafo experto completo:** contiene nodos de negocio documentados aunque no todos se
   usen como predictores.
2. **Grafo de entrenamiento:** matriz alineada exactamente con `features`; es el grafo que
   MGCECDL puede usar durante entrenamiento para reconstruccion/regularizacion.
3. **Grafo estimado HTML del cuaderno 05:** entregable interpretativo generado por
   `notebooks/project_flow/05_mgcecdl_circuit_analysis.ipynb` para cada escenario de circuito.

El grafo estimado HTML:

- Se calcula con la matriz inducida desde `outputs["reconstructed_features"]` del modelo
  MGCECDL para las muestras del escenario.
- Usa una similitud RBF entre perfiles reconstruidos de variables; el `rbf_sigma` debe
  venir del mejor estudio Optuna si esta disponible.
- Se guarda en `reports/mgcecdl-results/interactive_graphs/`.
- Muestra una sola arista por par de variables, sin doble direccion ni flechas.
- Normaliza cada peso por la conexion maxima del grafo (`peso / max_peso`), por lo que el
  mayor valor se reporta como `1.000e+00` y los pesos pequenos en notacion cientifica.
- Debe leerse como asociacion relativa estimada por el modelo para ese subconjunto de
  muestras, no como peso experto original.

## Grafo completo, grafo de entrenamiento y nodos originales

El grafo experto completo conserva el contexto semantico de todos los nodos documentados:
evento/impacto, proteccion, topologia, caracteristicas del vano, activos y clima. El grafo
de entrenamiento es la version inducida por las variables seleccionadas en `features`.

Reglas:

- `features` define los nodos que el modelo recibio efectivamente.
- La matriz de adyacencia se construye con forma `(len(features), len(features))`.
- `UITI_VANO` debe quedar fuera de `features` por ser objetivo/clase derivada, aunque exista
  como nodo conceptual del grafo completo o columna de reporte.
- Si una variable original no esta en `features`, no debe tratarse como predictor usado por
  el modelo.
- Un nodo original no retenido puede aparecer dentro de una ruta preservada para conservar
  significado experto.
- La explicacion debe conservar el nombre y modo del nodo original cuando ayude a
  contextualizar la ruta, aclarando que no fue predictor si no esta en `features`.
- Si el usuario cambia variables seleccionadas, filtro o ventana climatica, el grafo de
  entrenamiento debe considerarse distinto hasta validar el nuevo orden de `features`.

## Dirección y Pesos

Cada relacion es dirigida:

```text
source -> target
```

Los pesos expresan fuerza o confianza experta:

- `1.0`: relacion definicional, deterministica o muy directa dentro del diseno experto.
- `0.85` a `0.95`: relacion fuerte esperada.
- `0.70` a `0.80`: relacion moderada o contextual.
- `0.50` a `0.60`: relacion debil, historica o menos directa.

No sumar pesos como probabilidades. Para un camino de varias aristas, describir la ruta y,
si se necesita un resumen, usar el peso minimo del camino como cuello de botella conceptual.

## Conectividad preservada

La seleccion final de variables puede excluir nodos intermedios del grafo experto. Para no
perder trazabilidad, se permite una "arista preservada" entre variables retenidas.

Reglas conceptuales:

- Si `source` y `target` estan en `features`, la arista es directa.
- Si el camino pasa por nodos no retenidos, la conexion es virtual o preservada.
- Una conexion virtual indica trazabilidad experta, no conexion fisica directa.
- Si existen una ruta directa y una virtual para el mismo par, se prefiere la directa.

## Familias climaticas

El grafo contempla familias climaticas con lags horarios:

- `prep`
- `temp`
- `wind_gust_spd`
- `wind_spd`
- `clouds`
- `pres`
- `sp`
- `rh`
- `solar_rad`

Patron temporal:

```text
familia_lag_mas_antiguo -> ... -> familia_1 -> familia_0 -> COD_CAUSA
```

Pesos:

- Entre lags consecutivos: `0.90`.
- De `familia_0` a `COD_CAUSA`: `0.85`.

Interpretacion:

- Lags consecutivos relevantes pueden sugerir persistencia climatica.
- `lag_0` es la condicion mas cercana al evento dentro de la ventana usada.
- Clima relevante para inferencia debe narrarse como condicion asociada o predictiva.
- Si el modelo uso una ventana de lags distinta a 12 horas, solo interpretar los lags
  presentes en `features`. Los lags documentados pero ausentes quedan como contexto original,
  no como predictores.

## Diccionario operativo de nodos

### Evento, impacto e indicadores

- `FECHA`: fecha y hora del evento.
- `DURACION`: duracion total de la interrupcion.
- `UITI`: usuarios interrumpidos por tiempo de interrupcion.
- `UITI_VANO`: `UITI` ponderado por aporte del vano; objetivo de impacto.
- `TOT_USUS`: total de usuarios afectados.
- `CNT_TRF`: cantidad de transformadores afectados.
- `COD_CAUSA`: codigo de causa de falla.
- `DESC_CAUSA`: descripcion textual de la causa.

### Proteccion y maniobra

- `FID_SW`: identificador del equipo de maniobra/proteccion.
- `COD_EQ_PROTEGE`: codigo del equipo que protege/opera.
- `TIPO`: tipo de equipo de proteccion.
- `CNT_VN_SW`: cantidad total de vanos protegidos por el equipo.
- `T_USUS_EQ_PROT`: usuarios desconectados cuando abre el equipo protector.

### Topologia y configuracion espacial

- `CIRCUITO`: circuito al que pertenece el vano.
- `FID_VANO`: identificador espacial del vano.
- `X1`, `Y1`, `X2`, `Y2`: coordenadas iniciales y finales del vano.
- `LVSW`: longitud de red desde el vano hasta el equipo que opera.
- `CNT_VN`: cantidad de vanos desde el punto de falla hasta el equipo protector.
- `PORC_APORTE_VANO`: ponderacion del vano dentro de los vanos protegidos.

### Caracteristicas fisicas y electricas del vano

- `FECHA_OPERACION_VANO`: fecha de energizacion del vano.
- `LONGITUD`: longitud fisica del vano.
- `CNT_FASES`: cantidad de fases electricas.
- `CONDUCTOR`: tipo o material del conductor.
- `CALIBRE_NEUTRO`: calibre del cable neutro.
- `NG_RED`: presencia de cable de guarda o neutro.
- `PROMEDIO_KWH_VANO`: energia promedio mensual asociada al vano.
- `TIPO_TAX`: taxonomia constructiva del vano.

### Activos: apoyo final y transformador

- `COD_APOYO_FIN`, `FID_APOYO_FIN`: identificadores del apoyo final.
- `PROPIETARIO`: entidad propietaria del apoyo.
- `CLASE`: clase mecanica o material del apoyo.
- `ELEMENTO`: tipo de elemento de soporte.
- `NORMA`: codigo de estructura estandarizada.
- `ALTURA`: altura del apoyo final.
- `LONG_CRUCETA`: longitud de cruceta.
- `CANTIDAD_TIERRA`: presencia de puesta a tierra.
- `VAL_CRIT_APOYO`: criticidad basada en clase/condicion del apoyo.
- `FID_TRAFO`, `CODIGO`: identificadores del transformador.
- `CAPACIDAD_NOMINAL`: capacidad nominal del transformador.
- `CNT_USUS`: usuarios conectados al transformador.
- `FECHA_OPERACION_TRF`: fecha de energizacion del transformador.
- `PROMEDIO_KWH_TRF`: consumo promedio mensual del transformador.

### Entorno, riesgo y clima

- `NR_T`: riesgo asociado a vegetacion cercana al vano.
- `DDT`: densidad de descargas a tierra.
- `prep_i`: precipitacion acumulada de la hora previa correspondiente.
- `clouds_i`: cobertura nubosa.
- `wind_spd_i`: velocidad instantanea del viento.
- `wind_gust_spd_i`: rafaga maxima del viento.
- `temp_i`: temperatura del aire.
- `pres_i`: presion atmosferica reducida al nivel del mar.
- `sp_i`: presion en superficie.
- `rh_i`: humedad relativa.
- `solar_rad_i`: radiacion solar de onda corta.

## Aristas expertas principales

### Entorno, riesgo y causa

```text
NR_T -> COD_CAUSA                         peso 0.85
DDT -> COD_CAUSA                          peso 0.90
wind_gust_spd_0 -> NR_T                   peso 0.80
CANTIDAD_TIERRA -> DDT                    peso 0.85
NG_RED -> DDT                             peso 0.75
LONGITUD -> COD_CAUSA                     peso 0.70
CONDUCTOR -> COD_CAUSA                    peso 0.80
ALTURA -> NR_T                            peso 0.75
VAL_CRIT_APOYO -> NR_T                    peso 0.60
CLASE -> VAL_CRIT_APOYO                   peso 0.80
NORMA -> VAL_CRIT_APOYO                   peso 0.80
```

Lectura:

- `NR_T` y `DDT` conectan riesgo/entorno con causa codificada.
- Variables fisicas como longitud, conductor o altura pueden funcionar como contexto de
  vulnerabilidad.

### Topologia y configuracion espacial

```text
X1 -> FID_VANO                             peso 1.00
Y1 -> FID_VANO                             peso 1.00
X2 -> FID_VANO                             peso 1.00
Y2 -> FID_VANO                             peso 1.00
FID_VANO -> LVSW                           peso 0.90
CIRCUITO -> FID_VANO                       peso 0.80
TIPO_TAX -> FID_VANO                       peso 0.70
```

Lectura:

- Estas aristas conectan posicion, identificacion del vano y configuracion espacial.
- Si dominan, revisar tramos, ubicacion y posicion relativa en el circuito.

### Proteccion y maniobra

```text
LVSW -> COD_EQ_PROTEGE                     peso 0.85
CNT_VN -> COD_EQ_PROTEGE                   peso 0.85
COD_EQ_PROTEGE -> FID_SW                   peso 1.00
FID_SW -> TIPO                             peso 0.90
TIPO -> DURACION                           peso 0.85
TIPO -> T_USUS_EQ_PROT                     peso 0.85
CNT_VN_SW -> T_USUS_EQ_PROT                peso 0.80
PORC_APORTE_VANO -> CNT_VN_SW              peso 0.70
```

Lectura:

- Esta ruta conecta vano, equipo de proteccion, tipo de maniobra, duracion y usuarios bajo
  proteccion.
- Si domina, la hipotesis operativa debe mirar coordinacion, selectividad y cobertura de
  protecciones.

### Activos, apoyo y transformador

```text
COD_APOYO_FIN -> FID_APOYO_FIN             peso 1.00
PROPIETARIO -> FID_APOYO_FIN               peso 0.50
ELEMENTO -> FID_APOYO_FIN                  peso 0.80
LONG_CRUCETA -> FID_APOYO_FIN              peso 0.70
FID_TRAFO -> CODIGO                        peso 1.00
FID_APOYO_FIN -> FID_TRAFO                 peso 0.90
CAPACIDAD_NOMINAL -> CNT_USUS              peso 0.85
FECHA_OPERACION_TRF -> FID_TRAFO           peso 0.60
PROMEDIO_KWH_TRF -> CNT_USUS               peso 0.80
PROMEDIO_KWH_VANO -> CNT_FASES             peso 0.70
CALIBRE_NEUTRO -> CONDUCTOR                peso 0.80
FECHA_OPERACION_VANO -> CONDUCTOR          peso 0.60
```

Lectura:

- Esta ruta conecta condiciones de activos, transformadores, usuarios y caracteristicas del
  vano.
- Si domina, revisar activos fisicos y concentracion de carga.

### Usuarios, carga e impacto

```text
CNT_USUS -> TOT_USUS                       peso 0.90
CNT_TRF -> TOT_USUS                        peso 0.85
T_USUS_EQ_PROT -> TOT_USUS                 peso 0.95
DURACION -> UITI                           peso 1.00
TOT_USUS -> UITI                           peso 1.00
UITI -> UITI_VANO                          peso 1.00
PORC_APORTE_VANO -> UITI_VANO              peso 1.00
FECHA -> UITI_VANO                         peso 0.70
COD_CAUSA -> FECHA                         peso 0.70
COD_CAUSA -> DESC_CAUSA                    peso 1.00
```

Lectura:

- Esta es la ruta mas cercana a impacto operacional.
- Variables de usuarios, duracion, aporte del vano e indicadores de impacto son coherentes
  con escenarios de severidad alta.

## Modos CHEC para interpretar conectividad

Usar los modos como una capa semantica sobre el grafo:

- Evento, impacto e indicadores.
- Infraestructura de proteccion y maniobra.
- Topologia y configuracion espacial.
- Caracteristicas fisicas y electricas del vano.
- Activos: apoyo final y transformador.
- Entorno, riesgo y clima.

Una variable top debe explicarse idealmente con:

1. Su modo CHEC.
2. Su ruta experta hacia `UITI_VANO`, si existe.
3. Si la ruta es directa o preservada.
4. Si la ruta es fuerte, moderada o debil.
5. Como encaja con el escenario analizado.

## Reglas de Protección

El agente no debe:

- Confundir importancia del modelo con criticidad real sin mirar severidad y recurrencia.
- Comparar Borda crudo entre escenarios con distinto numero de eventos.
- Interpretar una ruta virtual como conexion electrica directa.
- Decir que una variable sin ruta experta es falsa o irrelevante.
- Cambiar el orden de `features` al interpretar la matriz.
- Asumir que todas las variables del grafo estan presentes en el conjunto recibido.
- Usar nodos originales ausentes de `features` como si hubieran sido entrenados.
- Omitir que una ruta preservada pasa por nodos no retenidos.

## Plantilla de coherencia grafo-modelo

```text
La variable <variable> pertenece al modo <modo>. En el grafo experto se conecta con
UITI_VANO mediante <ruta>, con una relacion <fuerte/moderada/debil>. Esto hace que su
aparicion en el ranking del modelo sea <coherente/parcialmente coherente/no explicada por
el grafo>, aunque sigue siendo una explicacion del modelo.
```

## Plantilla para aristas preservadas

```text
La variable <source> y <target> aparecen conectadas en el grafo de entrenamiento mediante
una arista preservada. La ruta original documentada es <source -> nodo_intermedio ->
target>. Esto conserva trazabilidad experta porque algunos nodos intermedios no fueron
retenidos como predictores. No debe interpretarse como conexion fisica directa ni como
coeficiente aprendido por el modelo.
```

## Cuando Falta Información

Usar estas formulas:

- "No se encontró una definición explícita para esta variable."
- "La relación entre estos elementos no está documentada en el grafo disponible."
- "La variable está en `features`, pero no se encontró camino documentado hacia
  `UITI_VANO`."
- "La interpretación debe tratarse como hipótesis hasta validación operativa."
