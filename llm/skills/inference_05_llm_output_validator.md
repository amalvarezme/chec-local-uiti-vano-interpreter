# 05 - Validador de Salida del LLM CHEC

Esta habilidad valida la salida del agente de inferencia que analiza resultados CHEC/MGCECDL
para un circuito elegido por el usuario. Aplica primero las skills compartidas de seguridad
JSON, lenguaje de dominio y guardrails modelo/grafo; esta skill agrega el contrato específico
del reporte de inferencia.

## Formato obligatorio en este notebook

Cuando la salida sea consumida por `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`,
el agente debe producir **solo un objeto JSON válido**. No usar markdown, tablas markdown,
bloques de código, texto antes del JSON, texto después del JSON ni etiquetas `<think>`.

La respuesta debe preservar el análisis y mantener una estructura apta para el reporte HTML:

- Incluir todos los escenarios recibidos en `contexto.escenarios`, usando exactamente el mismo
  valor de `nombre`.
- Incluir las `top_variables` necesarias para explicar el escenario sin inventar variables.
- Incluir los `modos` necesarios para explicar el escenario sin inventar modos.
- No copiar `tabla_top_vanos` completa; sintetizar los patrones relevantes.
- `discusion_grafos` debe incluir hasta dos lecturas generales: una para
  `seccion="periodo_completo"` y otra para `seccion="puntos_criticos"` cuando existan grafos
  HTML en ambas secciones.
- `discusion_grafos` debe ser siempre un arreglo/lista de objetos con claves `seccion` y
  `lectura`; no debe ser un diccionario con claves `periodo_completo` y `puntos_criticos`.
- Cada lectura de `discusion_grafos` debe ser apta para renderizarse como viñeta del apartado
  correspondiente del reporte, sin afirmar causalidad.
- `coherencia_grafo_modelo` debe incluir las entradas necesarias para explicar la relación entre
  modelo y grafo.
- `hallazgos`, `limitaciones` e `interpretacion` deben contener el detalle necesario para no
  comprometer el análisis.
- Cada conclusión o bloque presentado como items debe tener máximo 5 items; si hay más
  información, priorizar la más relevante para el reporte.
- La presentación final debe consolidar la discusión general en una sola conclusión con dos
  aspectos: `Número de Eventos` y `UITI_VANO`. La sección de puntos críticos debe seguir el
  mismo patrón cuando existan ambos escenarios.
- Incluir `hipotesis_modelo_predictivo` con dos listas de items: `periodo_completo` y
  `puntos_criticos`. Cada lista debe tener máximo 5 items y debe sintetizar la discusión
  general junto con la discusión de grafos correspondiente.

## Esquema JSON recomendado

Usar placeholders solo como nombres de campos; los valores deben venir del contexto real:

```json
{
  "contexto": {
    "circuito": "<circuito_recibido>",
    "periodo": {"inicio": "<fecha_inicio_recibida>", "fin": "<fecha_fin_recibida>"},
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
      "modos": [{"modo": "<modo_chec>", "score_normalizado": "<0_a_1>"}],
      "interpretacion": "<lectura_del_escenario>",
      "cautelas": ["<limitacion_aplicable>"]
    }
  ],
  "discusion_grafos": [
    {"seccion": "periodo_completo", "lectura": "<lectura_general_de_los_grafos_estimados>"},
    {"seccion": "puntos_criticos", "lectura": "<lectura_general_de_los_grafos_estimados>"}
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
    "periodo_completo": ["<hipotesis_para_periodo_completo>"],
    "puntos_criticos": ["<hipotesis_para_puntos_criticos>"]
  }
}
```

No dejar placeholders en la salida final. Si un valor no existe, usar `null` y explicar por qué
falta. No inventar variables fuera de las que vienen en el contexto compacto.

## Validaciones obligatorias específicas

Antes de entregar, verificar:

- El circuito, periodo y fechas reportadas coinciden con el contexto recibido.
- `n_features` coincide con la longitud real de `features`.
- Si se reporta matriz de adyacencia, su forma es `(n_features, n_features)`.
- Si se reportan aristas preservadas, se distinguen de aristas directas.
- `UITI_VANO` no aparece como predictor cuando el flujo lo separó de `features`.
- Si existen grafos HTML del periodo completo y de puntos críticos, `discusion_grafos` contiene
  ambas secciones como objetos de lista.
- `hipotesis_modelo_predictivo.periodo_completo` integra hallazgos, escenarios del periodo
  completo y grafos de periodo completo.
- `hipotesis_modelo_predictivo.puntos_criticos` integra escenarios y grafos de puntos críticos.
- Cada escenario incluye criterio de selección y distingue Top-N configurado de Top-N efectivo
  cuando ambos existan.
- Cada variable top tiene modo CHEC o `modo_no_identificado`, indica si estuvo en `features`, y
  usa scores normalizados entre `0` y `1`.
- Las rutas del grafo respetan dirección `source -> target` cuando se afirme una ruta dirigida.

## Validaciones de escenarios

### Severidad por UITI_VANO

- Indicar selección por `UITI_VANO_PROM` descendente o criterio equivalente recibido.
- Leer severidad promedio; no medir recurrencia por sí solo.

### Recurrencia por frecuencia

- Indicar selección por `N_APARICIONES` descendente o criterio equivalente recibido.
- Si existe desempate por impacto, mencionarlo.
- Recordar que recurrencia e impacto pueden divergir.

### Fechas de interés

- Indicar filtro por días o fechas de interés recibidas.
- Si no hay eventos, no producir interpretación inventada.

### Frecuencia en fechas de interés

- Indicar selección por `N_APARICIONES` dentro de esas fechas y desempate por `UITI_VANO_PROM`
  si existe.
- Recordar que describe recurrencia puntual en fechas críticas, no severidad general.

## Limitaciones mínimas de inferencia

Toda salida interpretativa debe incluir limitaciones equivalentes a:

- Kernel SHAP explica comportamiento del modelo, no causalidad operacional comprobada.
- La normalización min-max facilita comparación dentro de cada escenario.
- Inferencia no usa directamente la matriz de adyacencia del grafo experto.
- MGCECDL puede incorporar el grafo en entrenamiento, pero sus importancias siguen siendo
  explicaciones del modelo y requieren validación operativa.
- Los grafos HTML muestran asociaciones estimadas para un escenario; no son prueba causal ni
  sustituyen la lectura de SHAP+Borda y modos.
- Los resultados dependen del circuito, periodo, filtro y variables recibidos.
