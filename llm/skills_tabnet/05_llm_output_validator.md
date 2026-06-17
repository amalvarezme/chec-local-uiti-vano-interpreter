# 05 - LLM Output Validator TabNet CHEC

Esta skill valida la salida de un agente que analiza resultados TabNet/CHEC para un
circuito elegido por el usuario. La salida debe depender de los datos recibidos, no de
valores quemados.

## Formatos permitidos

El agente puede producir:

- Markdown ejecutivo.
- JSON estructurado.
- Markdown con tablas y un bloque JSON de respaldo.

Si la salida sera consumida por otro agente, preferir JSON. Si la salida sera leida por
personas, preferir markdown con tablas cortas y conclusiones operativas.

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
    "modelo": "<modelo_recibido>",
    "metodo_explicacion": "Kernel SHAP + Borda ponderado"
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
  "limitaciones": ["<limitaciones>"]
}
```

No dejar placeholders en la salida final. Si un valor no existe, usar `null` y explicar por
que falta.

## Validaciones obligatorias

Antes de entregar, verificar:

- El circuito reportado coincide con el circuito recibido.
- El periodo reportado coincide con el periodo recibido.
- Las fechas de interes reportadas coinciden con las recibidas o se marcan como ausentes.
- `n_features` coincide con la longitud real de `features`.
- Si se reporta matriz de adyacencia, su forma es `(n_features, n_features)`.
- Cada escenario incluye criterio de seleccion.
- Cada escenario distingue Top-N configurado de Top-N efectivo si ambos existen.
- Cada variable top tiene modo CHEC o queda marcada como `modo_no_identificado`.
- Los scores normalizados estan entre `0` y `1`.
- Las rutas del grafo respetan direccion `source -> target`.
- Las afirmaciones sobre SHAP dicen que explican la salida del modelo.

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

## Validaciones de lenguaje

Reemplazar frases fuertes:

| Evitar | Usar |
|---|---|
| "X causo la falla" | "El modelo asigno alta relevancia a X" |
| "X demuestra el origen del evento" | "X es coherente con una hipotesis operativa" |
| "El grafo prueba causalidad" | "El grafo codifica una relacion experta" |
| "TabNet uso el grafo" | "El grafo se usa para contrastar la interpretacion" |
| "El vano es malo" | "El vano aparece como prioritario en este escenario" |

## Validaciones numericas

- No reportar valores fijos si no vienen del contexto.
- No comparar puntajes Borda crudos entre escenarios con distinto numero de eventos.
- No interpretar diferencias pequenas en scores normalizados como grandes brechas.
- No reportar porcentajes si no se calcularon explicitamente.
- No mezclar `UITI_VANO`, `UITI_VANO_PROM`, `UITI_CIRCUITO` y frecuencia.
- No hablar de un Top-N especifico si el Top-N efectivo fue distinto.

## Validaciones de grafo

Para cada variable mencionada en coherencia grafo-modelo:

- Confirmar si existe en `features`.
- Confirmar si pertenece a algun modo CHEC.
- Confirmar direccion hacia `UITI_VANO` cuando se afirma camino.
- Marcar `sin_camino_experto_detectado` si no hay ruta conocida.
- Si la ruta es preservada o virtual, decirlo explicitamente.
- No convertir peso del grafo en probabilidad o efecto causal.

## Limitaciones minimas

Toda salida interpretativa debe incluir limitaciones equivalentes a:

- Kernel SHAP explica comportamiento del modelo, no causalidad operacional comprobada.
- La normalizacion min-max facilita comparacion dentro de cada escenario.
- TabNet no usa directamente la matriz de adyacencia del grafo experto.
- Las fechas de interes solo explican eventos presentes en el periodo filtrado.
- Los resultados dependen del circuito, periodo, filtro y variables recibidos.

Si el contexto informa filtros especificos, incluirlos con sus valores reales. No asumirlos.

## Checklist final

Antes de responder, el agente debe poder contestar "si" a:

- Use circuito, periodo, features y modelo recibidos.
- Diferencie severidad, frecuencia y fechas de interes.
- Interprete variables mediante modos CHEC.
- Contraste con el grafo sin afirmar causalidad.
- Valide scores, nombres de variables y granularidad.
- Evite valores quemados no presentes en el contexto.
