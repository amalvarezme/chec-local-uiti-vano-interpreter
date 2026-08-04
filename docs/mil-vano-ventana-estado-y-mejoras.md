# MIL vano x ventana: estado, acople a 06 y mejoras pendientes

Estado al 2026-08-04. Modelo: `data/models/mil_vano_ventana_v1.pt`.

## 1. Qué hay hoy

| | |
|---|---|
| Configuración | `fusion="film"`, `LAMBDA_CLASE=1.0`, `TEMPERATURA_CLASE=0.01`, 30 épocas |
| macro-F1 (CV agrupada, 62.114 bolsas) | **0,870982** |
| Referencia RandomForest estructural | **0,881231** |
| Barra A1 pre-registrada | +5,0 puntos sobre la mejor línea base |
| **Veredicto A1** | **NEGATIVO** (−1,02 puntos) |

El cuaderno 05 (MIL) corre por defecto como **visor** (`EJECUCION="visualizacion"`,
segundos) y reentrena con `EJECUCION="entrenamiento"` (~40 min).

### Desempeño por grupo

| grupo | precision | recall | F1 | soporte | F1 del RF |
|---|---|---|---|---|---|
| Bajo | 0,8443 | 0,8252 | **0,8346** | 13.323 | 0,8079 |
| Medio | 0,8295 | 0,8514 | 0,8403 | 27.229 | 0,8562 |
| Medio-Alto | 0,8571 | 0,8453 | 0,8512 | 15.220 | 0,8835 |
| Alto | 0,9741 | 0,9421 | 0,9578 | 6.342 | 0,9773 |

accuracy 0,8535 · **ninguna clase abandonada** · el error es casi siempre de
vecino inmediato (confundir Bajo con Alto ocurre 1 vez en 13.323).

## 2. Acople a 06

El SEAM de la celda 5 de `06_uiti_vano_explicabilidad_simulador` debe quedar así:

```python
# --- SEAM D1: MIL -------------------------------------------------------
from chec_impacto.data.bags import codificar_cod_causa, construir_matriz_instancias
from chec_impacto.models.mil_persistencia import cargar_modelo_mil
from chec_impacto.interpretability import mil_vano_ventana

# El modelo MIL corre sobre p=80 columnas, NO sobre las 70 que
# procesar_dataset_completo entrega: le faltan la frecuencia de COD_CAUSA y sus
# 9 indicadores. Pasarle la matriz equivocada NO lanza error por si solo --
# puntua columnas distintas y devuelve un mapa creible y falso.
df_causa, encoding = codificar_cod_causa(
    datos['df_original_copy'].reset_index(drop=True), min_frecuencia_relativa=0.01,
)
X_MIL, FEATURES_MIL = construir_matriz_instancias(
    datos, df_causa, encoding, datos['features'],
)

MODEL_PATH = MODEL_DIR / 'mil_vano_ventana_v1.pt'
MODELO = cargar_modelo_mil(MODEL_PATH, device=DEVICE, features_esperadas=FEATURES_MIL)
PREDICT_FN = mil_vano_ventana.predict_fn

_probe = PREDICT_FN(MODELO, X_MIL[: min(len(X_MIL), 8)], device=DEVICE, batch_size=8)
assert _probe['fused_probs'].shape[1] == 4
```

Y todo consumo posterior de `X` para el modelo debe usar `X_MIL`. `X_MIL` está
alineado fila a fila con `context_df`, igual que `X`.

Verificado contra los datos reales: `X` 70 columnas → `X_MIL` 80, contrato
`fused_probs (8,4)` correcto, y la guarda **rechaza** las 70 crudas.

### Semántica que el simulador debe respetar

`predict_fn` trata **cada fila como una bolsa singleton con `n_obs = 1`**. La
clase sale de `asignar_clase(n_obs, û, geometria)`, y `n_obs` es una de las dos
coordenadas. Al simular sobre eventos individuales eso es correcto; si alguna
vez se simula una ventana completa hay que pasar el `n_obs` real, o la clase
saldrá sistemáticamente baja.

## 3. Mejoras pendientes, por prioridad

### P0 — Determinismo. Bloquea todo lo demás

**Dos corridas de la misma configuración dieron 0,801150 y 0,870982: 7 puntos.**
El RandomForest da 0,881231 bit a bit idéntico en las seis corridas, así que la
dispersión es enteramente del modelo en torch/MPS.

Con ±7 puntos, ninguna comparación posterior significa nada: ni entre brazos, ni
Optuna, ni "esta mejora funcionó". **Es un prerrequisito, no una mejora.**

- Medir el ruido real: 3-5 repeticiones de la misma configuración (~42 min c/u).
- Evaluar CPU (determinista) contra MPS: medir primero la razón de tiempos.
- Si se queda MPS: promediar cada configuración sobre k semillas y no aceptar
  ninguna diferencia menor al ruido medido.

### P1 — Selección de época

Hoy se evalúa la época 30 sin criterio. La pérdida NO es monótona: picos
reproducibles en todos los pliegues (0,6728 → 2,3512 en la época 18). El modelo
evaluado puede caer en un rebote. Un split de validación con selección de mejor
época es casi gratis.

### P2 — Los λ del grafo son decorativos

`reconstrucción` y `MI` están acotados en [0,1] con λ = 0,01 cada uno: entre los
dos mueven el total como máximo **0,02**, contra un término supervisado que se
movió entre 0,35 y 6,8. Con estos valores el grafo casi no participa del
gradiente. Subirlos ×100, o hacer `alpha` aprendible, o correr `alpha=0` como
ablación para saber si el grafo aporta algo.

### P3 — Ponderación KDE como sospechosa de la inestabilidad

Los pesos son `1/densidad` normalizados **por lote**. Con `log1p(u)` de cola
pesada, un lote con una bolsa extrema recibe un peso enormemente mayor, y la
normalización por lote hace que la ponderación efectiva dependa de qué cayó en
ese lote. Un brazo con MSE plano lo falsea.

### P4 — `n_obs` explícito en el head de bolsa

Medido: `n_obs` explica el **9,1%** de la varianza de `log1p(u)` (pendiente
0,825), y el modelo es estructuralmente incapaz de representarlo por la
invariancia de cardinalidad. Usarlo **no es fuga**: `asignar_clase` ya lo lee.

### P5 — Head no lineal

El head de bolsa es un `Linear`. Un MLP de dos capas agrega no linealidad justo
donde hoy no hay.

## 4. Hipótesis ya falseadas — no reintentar sin evidencia nueva

| hipótesis | cómo se falseó |
|---|---|
| "El modelo abandona la clase Alto" | Matriz de confusión: `Alto` es su **mejor** clase (F1 0,958) |
| "Está subentrenado" | 30 épocas contra 2 no cierran nada |
| "Acierta el orden y falla el nivel; calibrar cierra la brecha" | Techo isotónico **con fuga**: +0,026 puntos. La afín empeora, y sus coeficientes (a=0,956, b=0,186) muestran que no había error sistemático de nivel |
| "Las compuertas están degeneradas (ARI 0,106)" | Ese ARI es la guarda A3 de proxy univariante sobre datos **observados**: no depende del modelo. No hay medición de degeneración de compuertas |
| "Falta capacidad de interacción cruzada (FiLM)" | FiLM solo: 0,720099, **peor** que concat. Con término de clase: +0,6, dentro del ruido |
| "El pipeline de datos limita el rendimiento" | Perfilado: 98,9% del tiempo es forward+backward; armado del lote y transferencia a GPU suman 1,2% |

## 5. Trampas de medición confirmadas en esta máquina

1. **Calentamiento de MPS.** La primera corrida de un proceso paga la
   compilación de kernels. Me distorsionó tres mediciones distintas. Correr cada
   configuración dos veces y descartar la primera; una época de calentamiento
   no alcanza.
2. **Tareas de fondo mueren a los ~25-30 min.** Seis vigilantes matados, cero
   corridas perdidas desde que se desacoplan con `nohup ... & disown` y se
   vigilan desde un proceso desechable aparte.
3. **`EXIT=$?` después de un pipe a `tail` reporta el código de `tail`.** Dio
   `EXIT=0` mientras papermill fallaba.
4. **Este checkout es compartido con otra sesión.** Una corrida larga puede
   quedar sin su código a mitad de camino; usar un worktree propio.
