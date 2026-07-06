# 05 - Validador de Salida del LLM CHEC

Esta habilidad valida la salida de un agente que analiza resultados CHEC/MGCECDL/inferencia para
un circuito elegido por el usuario. La salida debe depender de los datos recibidos, no de
valores quemados. Toda explicación debe usar el grafo de entrenamiento y las variables
seleccionadas como marco principal.

## Formato obligatorio en este notebook

Cuando la salida sea consumida por `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`,
el agente debe producir **solo un objeto JSON valido**. No usar markdown, tablas markdown,
bloques de codigo, texto antes del JSON, texto despues del JSON ni etiquetas `<think>`.

La respuesta debe preservar el analisis y mantener una estructura apta para el reporte HTML:

- Incluir todos los escenarios recibidos en `contexto.escenarios`, usando exactamente el
  mismo valor de `nombre`.
- Incluir las `top_variables` necesarias para explicar el escenario sin inventar variables.
- Incluir los `modos` necesarios para explicar el escenario sin inventar modos.
- No copiar `tabla_top_vanos` completa; sintetizar los patrones relevantes.
- `discusion_grafos` debe incluir hasta dos lecturas generales: una para
  `seccion="periodo_completo"` y otra para `seccion="puntos_criticos"` cuando existan
  grafos HTML en ambas secciones.
- Cada lectura de `discusion_grafos` debe ser apta para renderizarse como viñeta del
  apartado correspondiente del reporte, sin afirmar causalidad.
- `coherencia_grafo_modelo` debe incluir las entradas necesarias para explicar la relacion
  entre modelo y grafo.
- `hallazgos`, `limitaciones` e `interpretacion` deben contener el detalle necesario para
  no comprometer el analisis.
- Cada conclusion o bloque presentado como items debe tener maximo 5 items; si hay mas
  informacion, priorizar la mas relevante para el reporte.
- La presentacion final debe consolidar la discusion general en una sola conclusion con dos
  aspectos: `Número de Eventos` y `UITI_VANO`. La seccion de puntos criticos debe seguir el
  mismo patron cuando existan ambos escenarios.
- Incluir `hipotesis_modelo_predictivo` con dos listas de items:
  `periodo_completo` y `puntos_criticos`. Cada lista debe tener maximo 5 items y debe
  sintetizar la discusion general junto con la discusion de grafos correspondiente.

## Esquema JSON recomendado

Usar placeholders solo como nombres de campos; los valores deben venir del contexto real:

```json
{
  "contexto": {
    "circuito": "<circuito_recibido>",
    "periodo": {
      "inicio": "<fecha_inicio_recibida>",
      "fin": "<fecha_fin_recibida>"
    },
    "fechas_interes": ["<fechas_recibidas_si_aplican>"],
    "n_eventos": "<valor_observado>",
    "n_vanos": "<valor_observado>",
    "n_features": "<valor_observado>",
    "matriz_adyacencia_shape": ["<n_features>", "<n_features>"],
    "n_aristas_preservadas": "<valor_o_null>",
      "features_usadas": ["<feature_1>", "<feature_2>"],
      "modelo": "<modelo_recibido>",
      "metodo_explicacion": "Kernel SHAP + Borda ponderado"
  },
  "entregables": {
    "grafos_html": [
      {
        "escenario": "<nombre_escenario>",
        "path": "<ruta_html_generada>",
        "fuente": "reconstruccion_mgcecdl_rbf",
        "pesos": "normalizados_0_1_por_maximo"
      }
    ]
  },
  "escenarios": [
    {
      "nombre": "<nombre_escenario>",
      "criterio": "<criterio_usado>",
      "n_vanos_efectivo": "<valor_observado>",
      "n_eventos": "<valor_observado>",
      "top_variables": [
        {
          "variable": "<variable>",
          "score_normalizado": "<0_a_1>",
          "modo": "<modo_chec_o_modo_no_identificado>",
          "en_features": "<true_false>",
          "ruta_grafo": "<ruta_o_null>",
          "tipo_conexion_grafo": "<directa_preservada_sin_camino_o_desconocida>",
          "lectura": "<interpretacion_operativa>"
        }
      ],
      "modos": [
        {
          "modo": "<modo_chec>",
          "score_normalizado": "<0_a_1>"
        }
      ],
      "interpretacion": "<lectura_del_escenario>",
      "cautelas": ["<limitacion_aplicable>"]
    }
  ],
  "discusion_grafos": [
    {
      "seccion": "periodo_completo",
      "lectura": "<lectura_general_de_los_grafos_estimados_del_periodo_completo>"
    },
    {
      "seccion": "puntos_criticos",
      "lectura": "<lectura_general_de_los_grafos_estimados_de_puntos_criticos>"
    }
  ],
  "coherencia_grafo_modelo": [
    {
      "variable": "<variable>",
      "tiene_camino_a_uiti_vano": "<true_false_o_desconocido>",
      "ruta_resumida": "<ruta_si_existe>",
      "tipo_conexion": "<directa_preservada_sin_camino_o_desconocida>",
      "peso_minimo_ruta": "<valor_si_existe>",
      "lectura": "<coherencia_con_el_escenario>"
    }
  ],
  "hallazgos": ["<hallazgos_principales>"],
  "limitaciones": ["<limitaciones>"],
  "hipotesis_modelo_predictivo": {
    "periodo_completo": [
      "<hipotesis_del_modelo_para_periodo_completo_basada_en_escenarios_y_grafos>"
    ],
    "puntos_criticos": [
      "<hipotesis_del_modelo_para_puntos_criticos_basada_en_escenarios_y_grafos>"
    ]
  }
}
```

No dejar placeholders en la salida final. Si un valor no existe, usar `null` y explicar por
que falta. No inventar variables fuera de las que vienen en el contexto compacto.

## Validaciones obligatorias

Antes de entregar, verificar:

- El circuito reportado coincide con el circuito recibido.
- El periodo reportado coincide con el periodo recibido.
- Las fechas de interes reportadas coinciden con las recibidas o se marcan como ausentes.
- `n_features` coincide con la longitud real de `features`.
- Si se reporta matriz de adyacencia, su forma es `(n_features, n_features)`.
- Si se reportan aristas preservadas, se distinguen de aristas directas.
- Si `UITI_VANO` aparece en el archivo de seleccion, confirmar que no se reporte como
  predictor en `features`.
- Si se reportan grafos HTML del cuaderno 05, incluir ruta, escenario y fuente
  `reconstruccion_mgcecdl_rbf`.
- Si se reportan grafos HTML del cuaderno 05, incluir en `discusion_grafos` una lectura para
  `periodo_completo` y otra para `puntos_criticos` cuando existan grafos en ambas secciones,
  con asociaciones relativas y modos, sin repetir una discusión por escenario.
- `discusion_grafos` debe ser lista de objetos con claves `seccion` y `lectura`; no debe ser
  un diccionario con claves `periodo_completo` y `puntos_criticos`.
- No entregar el JSON final si `entregables.grafos_html` incluye grafos de periodo completo y
  puntos criticos pero `discusion_grafos` no tiene ambas secciones como objetos de lista.
- `hipotesis_modelo_predictivo.periodo_completo` integra hallazgos, escenarios del periodo
  completo y grafos de periodo completo.
- `hipotesis_modelo_predictivo.puntos_criticos` integra escenarios y grafos de puntos
  criticos.
- Cada escenario incluye criterio de seleccion.
- Cada escenario distingue Top-N configurado de Top-N efectivo si ambos existen.
- Cada variable top tiene modo CHEC o queda marcada como `modo_no_identificado`.
- Cada variable top indica si estuvo en `features`.
- Cada variable top con interpretacion operativa tiene ruta de grafo o una nota clara de
  ausencia de relacion documentada.
- Los scores normalizados estan entre `0` y `1`.
- Las rutas del grafo respetan direccion `source -> target`.
- Las afirmaciones sobre SHAP dicen que explican la salida del modelo.
- La salida no interpreta nodos originales ausentes como predictores usados.

## Validaciones de escenarios

### Severidad por UITI_VANO

Debe indicar:

- Seleccion por `UITI_VANO_PROM` descendente o criterio equivalente recibido.
- Lectura de severidad promedio.
- Que no mide recurrencia por si solo.

### Recurrencia por frecuencia

Debe indicar:

- Seleccion por `N_APARICIONES` descendente o criterio equivalente recibido.
- Si existe desempate por impacto, mencionarlo.
- Lectura de recurrencia.
- Que recurrencia e impacto pueden divergir.

### Fechas de interes

Debe indicar:

- Filtro por dias o fechas de interes recibidas.
- Si las fechas se analizan juntas o por separado.
- Si no hay eventos, no producir interpretacion inventada.

### Frecuencia en fechas de interes

Debe indicar:

- Filtro por dias o fechas de interes recibidas.
- Seleccion por `N_APARICIONES` descendente dentro de esas fechas.
- Si existe desempate por `UITI_VANO_PROM`, mencionarlo.
- Que describe recurrencia puntual en fechas criticas, no severidad general.
- Si no hay eventos en fechas, no producir interpretacion inventada.

## Validaciones de lenguaje

Reemplazar frases fuertes:

| Evitar | Usar |
|---|---|
| "X causo la falla" | "El modelo asigno alta relevancia a X" |
| "X demuestra el origen del evento" | "X es coherente con una hipotesis operativa" |
| "El grafo prueba causalidad" | "El grafo codifica una relacion experta" |
| "inferencia uso el grafo" | "El grafo se usa para contrastar la interpretacion" |
| "La variable aislada explica el resultado" | "La variable se interpreta junto con su modo y ruta en el grafo" |
| "El vano es malo" | "El vano aparece como prioritario en este escenario" |

## Validaciones Numéricas

- No reportar valores fijos si no vienen del contexto.
- No comparar puntajes Borda crudos entre escenarios con distinto numero de eventos.
- No interpretar diferencias pequenas en scores normalizados como grandes brechas.
- No reportar porcentajes si no se calcularon explicitamente.
- No mezclar `UITI_VANO`, `UITI_VANO_PROM`, `UITI_CIRCUITO` y frecuencia.
- No hablar de un Top-N especifico si el Top-N efectivo fue distinto.
- No describir la clasificacion MGCECDL como regresion o prediccion continua de
  `UITI_VANO`.

## Validaciones de grafo

Para cada variable mencionada en coherencia grafo-modelo:

- Confirmar si existe en `features`.
- Confirmar si pertenece a algun modo CHEC.
- Confirmar direccion hacia `UITI_VANO` cuando se afirma camino.
- Marcar `sin_camino_experto_detectado` si no hay ruta conocida.
- Si la ruta es preservada o virtual, decirlo explicitamente.
- No convertir peso del grafo en probabilidad o efecto causal.
- Si la ruta usa nodos originales no retenidos, aclarar que esos nodos contextualizan la
  relacion pero no fueron predictores.
- Si una variable esta ausente de `features`, no incluirla como variable explicativa del
  modelo; solo puede aparecer como nodo intermedio o contexto original.
- Para grafos HTML estimados por el cuaderno 05, confirmar que:
  - Se describen como asociaciones relativas estimadas por reconstruccion MGCECDL + RBF.
  - Los pesos se leen en escala `0-1` normalizada por el maximo del grafo.
  - No se interpretan flechas o doble direccion, porque el entregable limpio usa aristas no
    dirigidas.
  - La ruta HTML se reporta como archivo guardado, no como visualizacion obligatoria en el
    notebook.

## Validaciones por modelo

### MGCECDL

- Puede usar el grafo durante entrenamiento mediante matriz de adyacencia, reconstruccion o
  regularizacion asociada a variables.
- En este proyecto raiz, MGCECDL debe tratarse como flujo de clasificacion. No validar ni
  exigir resultados de regresion.
- `UITI_VANO` es objetivo/clase derivada y no predictor; cualquier interpretacion que lo use
  como feature del modelo debe rechazarse.
- Si se reportan modalidades del modelo, distinguirlas de los seis modos interpretativos
  CHEC. Las modalidades de entrenamiento MGCECDL pueden ser climaticos/exogenos y
  estructurales/endogenos, mientras que los modos CHEC son una capa semantica para explicar.
- Si se reporta atencion o soporte por modalidad, aclarar que es comportamiento del modelo,
  no causalidad.

### inferencia

- No decir que inferencia uso directamente la matriz del grafo para predecir.
- Las mascaras/atenciones o SHAP de inferencia deben contrastarse con el grafo como validacion
  semantica externa.

## Limitaciones minimas

Toda salida interpretativa debe incluir limitaciones equivalentes a:

- Kernel SHAP explica comportamiento del modelo, no causalidad operacional comprobada.
- La normalizacion min-max facilita comparacion dentro de cada escenario.
- inferencia no usa directamente la matriz de adyacencia del grafo experto.
- MGCECDL puede incorporar el grafo en entrenamiento, pero sus importancias siguen siendo
  explicaciones del modelo y requieren validacion operativa.
- Los grafos HTML del cuaderno 05 muestran asociaciones estimadas para un escenario; no son
  prueba causal ni sustituyen la lectura de SHAP+Borda y modos.
- Las fechas de interes solo explican eventos presentes en el periodo filtrado.
- Los resultados dependen del circuito, periodo, filtro y variables recibidos.
- Las relaciones no documentadas deben marcarse como ausentes o hipoteticas.

Si el contexto informa filtros especificos, incluirlos con sus valores reales. No asumirlos.

## Checklist final

Antes de responder, el agente debe poder contestar "si" a:

- Use circuito, periodo, features y modelo recibidos.
- Diferencie severidad, frecuencia y fechas de interes.
- Interprete variables mediante modos CHEC.
- Contraste con el grafo sin afirmar causalidad.
- Conserve contexto de nodos originales sin tratarlos como predictores si no estan en
  `features`.
- Valide scores, nombres de variables y granularidad.
- Evite valores quemados no presentes en el contexto.
