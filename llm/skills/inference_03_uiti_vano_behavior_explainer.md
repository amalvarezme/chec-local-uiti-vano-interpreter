# 03 - Explicador del Comportamiento de `UITI_VANO`

Esta habilidad explica cómo traducir `UITI_VANO`, resultados MGCECDL/inferencia y atribuciones
a lenguaje de negocio eléctrico. Aplica las skills compartidas de dominio CHEC y guardrails de
modelo/grafo; esta skill conserva solo las reglas específicas de inferencia y reporte.

La interpretación debe unir cuatro piezas: importancia del modelo, modo CHEC, relación en el
grafo y significado operativo. En la salida JSON del notebook principal, esta explicación debe
ser sintética: priorizar 3 a 5 variables por escenario, agrupar por modo cuando sea posible y
dejar el detalle visual a barras, radares y grafos HTML.

## Qué va a recibir el agente

El agente puede recibir:

- Valores observados de `UITI_VANO` por evento y `UITI_VANO_PROM` por vano.
- Rankings de vanos por severidad o recurrencia.
- Variables Top-K explicadas por SHAP, Borda, atención, soporte modal, permutación o salida
  equivalente.
- Modos CHEC con scores normalizados.
- Fechas de interés o subconjuntos de eventos.
- Matriz de adyacencia, aristas preservadas y rutas HTML de grafos estimados por escenario.

Distinguir siempre la granularidad:

- Evento: una fila de interrupción/indicador.
- Vano: agregación por `FID_VANO`.
- Circuito: agregación o filtro superior.
- Escenario: subconjunto analítico definido por severidad, frecuencia o fechas.

## Qué representa `UITI_VANO`

`UITI_VANO` mide impacto de interrupción a nivel de vano. Relaciona usuarios afectados, tiempo
de interrupción y aporte relativo del vano dentro del evento o circuito analizado.

En la lógica experta del proyecto, el impacto se entiende mediante rutas como:

```text
DURACION + TOT_USUS -> UITI -> UITI_VANO
PORC_APORTE_VANO -> UITI_VANO
```

Valores altos pueden estar asociados a duraciones mayores, más usuarios afectados, mayor
participación del vano, concentración de usuarios bajo protección o condiciones físicas,
topológicas, de activos o entorno que el modelo encontró informativas.

## Predictor, objetivo y contexto

- Predictor: variable presente en `features` y usada por el modelo.
- Objetivo: variable que el modelo clasifica o predice; en estos flujos es `UITI_VANO` o una
  clase derivada.
- Contexto original: nodo/modo del grafo experto que puede no estar en `features`, pero conserva
  significado para explicar una arista preservada o ruta conceptual.

Si `UITI_VANO` aparece en `Variables_seleccion.xlsx`, esto no cambia la regla: el
preprocesamiento lo omite de `X` para evitar fuga de información.

## Severidad, recurrencia y fechas

No mezclar estos conceptos:

- `UITI_VANO` o `UITI_VANO_PROM`: severidad/impacto.
- `N_APARICIONES`: recurrencia/frecuencia.
- Top por fechas de interés: foco temporal sobre eventos específicos.

Lecturas típicas:

- Alto impacto y alta frecuencia: vano prioritario por criticidad y recurrencia.
- Alto impacto y baja frecuencia: evento o vano severo, pero no necesariamente crónico.
- Baja severidad y alta frecuencia: comportamiento repetitivo con impacto contenido.
- Alto impacto en fechas de interés: contribución relevante a días críticos seleccionados.

## Clasificación

El flujo de clasificación discretiza `UITI_VANO` en clases ordinales de impacto. El número de
clases, umbrales o percentiles debe leerse del contexto del modelo o del cuaderno que generó el
resultado. No hablar de predicción puntual continua de `UITI_VANO` salvo que el contexto entregue
un valor agregado observado, como `UITI_VANO_PROM`.

## Grafos HTML como entregable interpretativo

Los grafos HTML generados por escenario en `reports/mgcecdl-results/interactive_graphs/`:

- Complementan barras SHAP+Borda y radar por modos; no los reemplazan.
- Deben sintetizarse en `discusion_grafos` como máximo en dos entradas generales:
  `seccion="periodo_completo"` y `seccion="puntos_criticos"` cuando apliquen.
- Deben leerse como asociaciones relativas del escenario, no como causalidad.
- Deben reportarse como archivos guardados, no como visualizaciones obligatorias inline.

La forma JSON obligatoria de esas lecturas es una lista de objetos:

```json
[
  {"seccion": "periodo_completo", "lectura": "..."},
  {"seccion": "puntos_criticos", "lectura": "..."}
]
```

No devolver `discusion_grafos` como diccionario. Si existen grafos de ambas secciones, ambas
entradas son obligatorias.

## Cómo conectar variable, grafo e impacto

Para explicar una variable top:

1. Confirmar si está en `features`.
2. Identificar su modo CHEC.
3. Buscar su ruta hacia `UITI_VANO`, si existe.
4. Indicar si la ruta es directa o preservada por nodos no retenidos.
5. Traducir la ruta a lenguaje operativo con cautela.

Ejemplos de lectura soportada por el grafo:

- `DURACION -> UITI -> UITI_VANO`: relación directa con cálculo de impacto.
- `TOT_USUS -> UITI -> UITI_VANO`: usuarios afectados conectan con magnitud de impacto.
- `PORC_APORTE_VANO -> UITI_VANO`: ponderación del vano en el impacto.
- `TIPO -> DURACION` y `TIPO -> T_USUS_EQ_PROT -> TOT_USUS`: protección puede contextualizar
  tiempos y usuarios expuestos.
- `prep_i` u otra familia climática `-> ... -> COD_CAUSA`: clima con lags aporta contexto
  ambiental asociado a causa registrada.

Si una variable no tiene ruta documentada, reportar la relevancia como comportamiento del modelo
pendiente de validación experta.

## Narrativa recomendada

Un párrafo interpretativo debe unir:

1. Escenario recibido.
2. Variables o modos dominantes.
3. Lectura eléctrica.
4. Relación con severidad o recurrencia.
5. Cautela metodológica.
6. Relación con el grafo de entrenamiento.

Plantilla:

```text
En el escenario <nombre>, el modelo concentra la explicación en <modo/variables>. Para el
circuito y periodo analizados, esto sugiere que los vanos priorizados se distinguen por
<lectura_operativa>. En el grafo, <variable/ruta> conecta con <nodo_objetivo_o_intermedio>
mediante <tipo_de_conexion>. La conclusión describe el comportamiento del modelo sobre los
eventos filtrados y debe contrastarse con inspección operativa antes de afirmar causalidad.
```
