# Contexto de Grafos para Comparación Experta

## Propósito

Esta habilidad da al agente de comparación experta el contexto mínimo de grafos que necesita
para decidir variables a priorizar. Aplica además las skills compartidas de dominio CHEC y
guardrails modelo/grafo; esta skill conserva las reglas específicas de comparación experta.

Debe complementar la comparación entre:

- Agente Descriptor.
- Agente predictivo.
- Reportes expertos del circuito, cuando existan filas en `pdf_expert_matches`.

## Dos grafos que debe distinguir

### Grafo general experto

Contiene relaciones de negocio documentadas entre variables eléctricas, topológicas, de
protección, activos, entorno, clima e impacto. Puede contener nodos que no entran al modelo
predictivo. Esos nodos sirven para entender rutas y contexto, pero no son automáticamente
variables priorizables.

### Grafo de variables seleccionadas

Está alineado con `variables_modelo_predictivo`.

Reglas:

- Sus nodos son las variables que el modelo recibe como entrada.
- Es el grafo principal para decidir `variables_a_priorizar`.
- Si una variable no está en `variables_modelo_predictivo`, no debe salir en
  `variables_a_priorizar`.
- `UITI_VANO` no entra como variable a priorizar porque es objetivo o indicador de impacto.

## Cómo usar conexiones

Usa las conexiones del grafo para traducir coincidencias y diferencias en variables accionables:

- Si el reporte experto habla de protección, maniobra o selectividad, revisar variables
  conectadas como `TIPO`, `CNT_VN`, `CNT_VN_SW`, `COD_EQ_PROTEGE` si están en
  `variables_modelo_predictivo`.
- Si habla de transformadores, usuarios o carga aguas abajo, revisar variables conectadas como
  `CNT_TRF`, `CNT_USUS`, `TOT_USUS`, `CAPACIDAD_NOMINAL` si están en
  `variables_modelo_predictivo`.
- Si habla de vegetación o entorno, revisar `NR_T` y variables ambientales conectadas si están
  en `variables_modelo_predictivo`.
- Si habla de descargas, tormentas o actividad atmosférica, revisar `DDT` y variables climáticas
  conectadas si están en `variables_modelo_predictivo`.
- Si habla de vanos, topología o ubicación, revisar `CNT_VN`, `LVSW`, `FID_VANO`, coordenadas o
  variables de topología si están en `variables_modelo_predictivo`.

## Lectura de pesos y rutas

- Los pesos de grafo expresan fuerza relativa o confianza experta, no probabilidad.
- Una ruta entre variables indica trazabilidad técnica, no causalidad demostrada.
- Si una ruta pasa por nodos que no están en `variables_modelo_predictivo`, usarla como contexto,
  pero priorizar solo el nodo predictor retenido.
- Si una conexión viene del grafo estimado por el modelo, leerla como asociación relativa del
  escenario, no como arista física ni causalidad.

## Familias útiles para priorización

- Protección y maniobra: `TIPO`, `COD_EQ_PROTEGE`, `FID_SW`, `CNT_VN`, `CNT_VN_SW`,
  `T_USUS_EQ_PROT`.
- Topología y configuración espacial: `FID_VANO`, `X1`, `Y1`, `X2`, `Y2`, `LVSW`, `CNT_VN`,
  `PORC_APORTE_VANO`.
- Activos y usuarios: `CNT_TRF`, `FID_TRAFO`, `CAPACIDAD_NOMINAL`, `CNT_USUS`, `TOT_USUS`,
  `PROMEDIO_KWH_TRF`.
- Entorno y clima: `NR_T`, `DDT`, `prep`, `temp`, `wind_gust_spd`, `wind_spd`, `clouds`,
  `pres`, `sp`, `rh`, `solar_rad`.

## Regla de redacción

La comparación final debe ser ejecutiva:

- Coincidencias y diferencias: usar `tema`, `fuentes` y `explicacion`.
- No incluir fechas ni evidencia dentro de esos items.
- Las fuentes deben ser visibles y trazables: `Agente Descriptor`, `Agente predictivo` y
  archivos `CIRCUITO.pdf`; no usar nombres internos como `LLM1`, `LLM2` o `PDF_EXPERTO`.
- Cada conclusión presentada como items debe tener máximo 5 items.
- La tabla de variables debe explicar qué variable del modelo predictivo se debe revisar y por
  qué.
- Usar lenguaje cauteloso: asociación, consistencia, diferencia, posible explicación, requiere
  validación.
