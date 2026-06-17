# 04 - Graph Connectivity Guardrails

Esta skill contiene el marco experto de grafo y conectividad que el agente debe usar para
interpretar resultados TabNet/CHEC. Es autocontenida: el agente no debe depender de una
fuente externa para conocer las relaciones de negocio descritas aqui.

## Que va a recibir el agente

El agente puede recibir:

- `features`: variables seleccionadas y ordenadas como columnas de `X`.
- Una matriz de adyacencia entre variables, si ya fue construida.
- Aristas preservadas, si el flujo las entrega.
- Top variables de TabNet por evento, vano, circuito o escenario.
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

Uso correcto:

- Contrastar si una variable importante para TabNet tiene una ruta experta hacia
  `UITI_VANO`.
- Agrupar hallazgos por rutas o familias de negocio.
- Detectar discrepancias entre modelo y conocimiento experto.

Uso incorrecto:

- Decir que TabNet uso directamente el grafo para predecir.
- Tratar pesos del grafo como coeficientes aprendidos por TabNet.
- Afirmar causalidad operacional solo porque existe una ruta experta.
- Ignorar la direccion de las aristas.

## Direccion y pesos

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
- Clima relevante para TabNet debe narrarse como condicion asociada o predictiva, no como
  causa demostrada.

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

## Guardrails

El agente no debe:

- Afirmar causalidad fisica solo por SHAP, Borda, atencion o grafo.
- Confundir importancia del modelo con criticidad real sin mirar severidad y recurrencia.
- Comparar Borda crudo entre escenarios con distinto numero de eventos.
- Interpretar una ruta virtual como conexion electrica directa.
- Decir que una variable sin ruta experta es falsa o irrelevante.
- Cambiar el orden de `features` al interpretar la matriz.
- Asumir que todas las variables del grafo estan presentes en el conjunto recibido.

## Plantilla de coherencia grafo-modelo

```text
La variable <variable> pertenece al modo <modo>. En el grafo experto se conecta con
UITI_VANO mediante <ruta>, con una relacion <fuerte/moderada/debil>. Esto hace que su
aparicion en el ranking del modelo sea <coherente/parcialmente coherente/no explicada por
el grafo>, aunque sigue siendo una explicacion del modelo y no una prueba causal.
```
