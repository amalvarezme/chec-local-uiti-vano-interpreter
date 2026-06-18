# 03 - UITI_VANO Behavior Explainer

Esta skill explica como traducir `UITI_VANO`, resultados TabNet y atribuciones a lenguaje
de negocio electrico. El agente debe adaptar la explicacion al circuito, periodo y eventos
que reciba, sin asumir valores fijos.

## Que va a recibir el agente

El agente puede recibir:

- Valores de `UITI_VANO` por evento.
- `UITI_VANO_PROM` agregado por vano.
- Rankings de vanos por severidad o recurrencia.
- Variables Top-K explicadas por SHAP/TabNet.
- Modos CHEC con scores normalizados.
- Fechas de interes o subconjuntos de eventos.

El agente debe distinguir siempre la granularidad:

- Evento: una fila de interrupcion/indicador.
- Vano: agregacion por `FID_VANO`.
- Circuito: agregacion o filtro superior.
- Escenario: subconjunto analitico definido por severidad, frecuencia o fechas.

## Que representa UITI_VANO

`UITI_VANO` es una medida de impacto de interrupcion a nivel de vano. Operativamente
relaciona usuarios afectados, tiempo de interrupcion y aporte del vano dentro del evento o
del circuito analizado.

En la logica experta del proyecto, el impacto se entiende mediante rutas como:

```text
DURACION + TOT_USUS -> UITI -> UITI_VANO
PORC_APORTE_VANO -> UITI_VANO
```

Por tanto, valores altos pueden estar asociados a:

- Duraciones mayores.
- Mas usuarios afectados.
- Mayor participacion del vano en el impacto del evento.
- Concentracion de usuarios aguas abajo de una proteccion.
- Condiciones fisicas, topologicas, de activos o entorno que el modelo encontro predictivas.

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

## Clasificacion TabNet

El flujo TabNet de clasificacion discretiza `UITI_VANO` en clases ordinales de impacto.
El numero exacto de clases, umbrales o percentiles debe leerse del contexto del modelo o
del cuaderno que genero el resultado.

Si el agente recibe probabilidades o atribuciones SHAP, debe aclarar:

- La explicacion corresponde a la salida del modelo usada por el explicador.
- No necesariamente resume todas las clases ordinales.
- La importancia de una variable no equivale a causalidad operacional.

## Lectura por modos CHEC

### Evento, impacto e indicadores

Incluye variables de tiempo del evento, duracion, usuarios, transformadores, causa
codificada e indicadores de impacto.

Interpretacion:

- Dominancia de este modo significa que el modelo explica el resultado desde la huella
  operacional del evento.
- Puede indicar que la severidad esta muy ligada a usuarios afectados, duracion o causa
  registrada.

### Infraestructura de proteccion y maniobra

Incluye identificadores de equipos, tipo de proteccion, cantidad de vanos asociados y
usuarios bajo proteccion.

Interpretacion:

- Dominancia de este modo sugiere revisar configuracion de protecciones, maniobra,
  selectividad y concentracion de usuarios aguas abajo.

### Topologia y configuracion espacial

Incluye circuito, vano, coordenadas, relaciones topologicas y aporte relativo del vano.

Interpretacion:

- Dominancia de este modo sugiere que la ubicacion del vano o su posicion en el circuito
  ayuda a explicar el patron del modelo.

### Caracteristicas fisicas y electricas del vano

Incluye longitud, fases, conductor, neutro, tipo de red, consumo asociado y antiguedad o
fecha de operacion del vano.

Interpretacion:

- Dominancia de este modo orienta la discusion a condicion fisica, configuracion electrica
  o caracteristicas estructurales del tramo.

### Activos: apoyo final y transformador

Incluye apoyo final, transformador, propietario, clase, elemento, norma, altura, cruceta,
puesta a tierra, capacidad, usuarios y consumo del transformador.

Interpretacion:

- Dominancia de este modo sugiere revisar activos asociados, concentracion de carga,
  transformadores y condiciones del apoyo.

### Entorno, riesgo y clima

Incluye indicadores de riesgo, descargas o amenaza, y familias climaticas con lags.

Interpretacion:

- Dominancia de este modo sugiere que el modelo encontro informacion predictiva en entorno
  o clima.
- Lags cercanos al evento apuntan a condiciones contemporaneas.
- Lags previos pueden sugerir persistencia, acumulacion o contexto meteorologico anterior.

## Como hablar de impacto

Usar:

- "El vano aparece priorizado por impacto promedio."
- "El patron combina severidad y recurrencia."
- "El modelo asigno alta relevancia a variables del modo..."
- "La lectura operativa sugiere revisar..."

Evitar:

- "Esta variable causo la falla."
- "El modelo probo el origen del evento."
- "El grafo demuestra causalidad real."
- "El vano falla por esta variable."
- NUNCA uses términos como "causó definitivamente" o "la causa fue".

## Reglas Estrictas de Generación (Obligatorio)

- **Usa siempre un lenguaje de hipótesis**, nunca afirmes causalidad definitiva operativa.
- **Fechas**: Solo utiliza fechas que estén explícitamente en el contexto entregado. No infieras, ni resumas, ni inventes fechas.
- **data_gaps**: Si no hay datos faltantes (es decir, no hay variables en `unavailable_optional_columns`), el array `data_gaps` debe ir obligatoriamente vacío: `[]`. NUNCA inventes que falta una variable (como DDT) si no está explícitamente en la lista de no disponibles. Solo rellena el array si efectivamente se te indican variables faltantes en el contexto.
- **Extensión de la Discusión**: El análisis genera exactamente dos banners de discusión, uno por variable objetivo: "Número de Eventos" y "UITI_VANO". Cada banner proviene del campo `interpretacion` del escenario correspondiente. Sé conciso: máximo un párrafo sustantivo por banner.

## Narrativa recomendada

Un parrafo interpretativo debe unir:

1. Escenario recibido.
2. Variables o modos dominantes.
3. Lectura electrica.
4. Relacion con severidad o recurrencia.
5. Cautela metodologica.

Plantilla:

```text
En el escenario <nombre>, el modelo concentra la explicacion en <modo/variables>. Para el
circuito y periodo analizados, esto sugiere que los vanos priorizados se distinguen por
<lectura_operativa>. La conclusion describe el comportamiento del modelo sobre los eventos
filtrados y debe contrastarse con inspeccion operativa antes de afirmar causalidad.
```
