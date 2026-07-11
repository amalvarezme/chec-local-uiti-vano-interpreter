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
