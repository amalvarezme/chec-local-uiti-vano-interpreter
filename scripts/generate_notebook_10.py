"""Committed generator for notebook 10 -- multiple-instance learning (MIL)
over 01.4's vano x window bags.

Follows the convention recovered from commit `28e8dfe`
(`scripts/generate_notebook_12.py`, since deleted alongside notebooks
02.1/11/12): this module is the single source of truth for
`notebooks/project_flow/05_*.ipynb`. The notebook itself is GENERATED
OUTPUT, never hand-edited.

Pipeline (`main`): build the in-memory notebook -> assign deterministic cell
ids -> reject forbidden literals -> `ast.parse` every code cell ->
`nbformat.validate` -> write to disk. Running the notebook (smoke or full)
is a separate, MANUAL step this module never launches -- doing so trains the
MIL model on 288,632 instance rows, and no MIL training has ever been timed
on this machine (design #530's Cost section). The generated notebook itself
carries a mandatory self-timing forecast cell for exactly that reason.

References:
  - spec: sdd/notebook-10-mil-vano-ventana/spec
  - design: sdd/notebook-10-mil-vano-ventana/design (revision 2)
  - PR1: src/chec_impacto/data/bags.py
  - PR2: src/chec_impacto/models/criticality_assignment.py,
         scripts/extract_geometrias_014.py
  - PR3: src/chec_impacto/models/mgcecdl_mil.py
  - PR4: src/chec_impacto/interpretability/mil_vano_ventana.py
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_10_PATH = REPO_ROOT / "notebooks" / "project_flow" / "05_mil_vano_ventana.ipynb"

# `p` (instance feature count) must never be hardcoded -- it is always
# derived at runtime from `CodCausaEncoding`/`X_inst_bolsas.shape[1]` (obs
# #536 corrected an earlier design-time estimate of "81-85"; the real,
# pinned-threshold value is 80, and this generator must never spell it out).
# `E == 64` is the OPPOSITE case: design's Assertion Placement table requires
# it printed and asserted literally, so 64 is deliberately NOT forbidden.
FORBIDDEN_LITERALS = ("80", "81", "82", "83", "84", "85")

_KERNELSPEC = {
    "display_name": "Python 3 (ipykernel)",
    "language": "python",
    "name": "python3",
}
_LANGUAGE_INFO = {
    "name": "python",
    "pygments_lexer": "ipython3",
    "codemirror_mode": {"name": "ipython", "version": 3},
    "file_extension": ".py",
    "mimetype": "text/x-python",
    "nbconvert_exporter": "python",
    "version": "3.11",
}


# ---------------------------------------------------------------------------
# Cell source constants -- every cell body below uses `'''...'''` at the
# Python level (this file); no cell body contains a Python docstring, which
# would terminate the outer raw string (same GOTCHA as notebook 12's
# generator).
# ---------------------------------------------------------------------------


_MD_ENTRENAMIENTO = '''\
---

# Reentrenamiento desde cero

Todo lo que sigue corre SOLO con `EJECUCION = "entrenamiento"`. Con el valor
por defecto (`"visualizacion"`) cada celda de aqui en adelante no hace nada, y
el cuaderno termina en segundos.

Reentrenar con `mode = "full"` toma alrededor de 40 minutos y SOBREESCRIBE
`data/models/mil_vano_ventana_v1.pt`, que es el artefacto que consume el
simulador de 01.5.
'''

_MD_ARQUITECTURA = '''\
## Arquitectura

Cada **bolsa** es una celda `(CIRCUITO, FID_VANO, ventana)`; cada **instancia**
es un evento de falla dentro de ella. El modelo predice un escalar por bolsa,
`p_bag ~ log1p(uiti_acumulado)`, y la **clase de criticidad se deriva** con la
regla de vecino mas cercano que 01.4 ya calculo -- nunca se reajusta aqui.

```mermaid
flowchart TD
    X["x_inst (n_inst x p)<br/>+ instance_bag (CSR)"] --> E1
    subgraph PASO1["Paso 1 -- fuente de la compuerta"]
        E1["encoders por modalidad<br/>estructural (30) | climatica (50)"] --> Z1["z1 (n_inst x 128)"]
        Z1 --> AP["SegmentAttentionPool<br/>invariante a cardinalidad"]
        AP --> ZB["z_bag (n_bags x 128)"]
        ZB --> GD["PerSampleEdgeGateDecoder<br/>g = 2*sigmoid(W z_bag)"]
    end
    GD --> PROP["propagacion sobre el grafo experto FIJO<br/>x' = x + alpha * g * A^T x"]
    X --> PROP
    PROP --> E2
    subgraph PASO2["Paso 2 -- el MISMO modulo base"]
        E2["encoders + decoders"] --> Z2["z2 (n_inst x 128)"]
        E2 --> REC["reconstructed_features"]
        Z2 --> AP2["la MISMA atencion<br/>(pesos compartidos)"]
        AP2 --> ZB2["z_bag_2 (n_bags x 128)"]
    end
    ZB2 --> FUS{"fusion"}
    FUS -->|concat| H1["Linear(128 -> 1)"]
    FUS -->|film| H2["z_est * (1 + gamma(z_clim)) + beta(z_clim)<br/>Linear(64 -> 1)"]
    FUS -->|reliability| H3["sum_m r_m * p_m"]
    H1 --> P["p_bag"]
    H2 --> P
    H3 --> P
    P --> CLS["asignar_clase(n_obs OBSERVADO, expm1(p_bag), geometria de 01.4)<br/>-> Bajo | Medio | Medio-Alto | Alto"]
```

**Tres propiedades que no son detalles:**

- **Invariancia de cardinalidad.** Duplicar todas las instancias de una bolsa
  deja `p_bag` identico. Sin eso el modelo podria leer `num_eventos` por la
  puerta de atras, y `num_eventos` es exactamente el target que se descarto.
- **`n_obs` es OBSERVADO, nunca predicho.** De las dos coordenadas que deciden
  la clase, el modelo solo aporta `u`.
- **El grafo es fijo y las columnas de grado 0 quedan intactas.** `index_add`
  solo escribe en `edge_cols`; los indicadores `COD_CAUSA_*` sin aristas pasan
  sin tocarse.
'''

_MD_PERDIDA = '''\
## Funcion de costo

```
total = 1.00 * supervisado
      + 0.01 * reconstruccion_suave
      + 0.01 * perdida_informacion_mutua
      + 0.00 * desviacion_de_compuertas
      + LAMBDA_CLASE * perdida_de_clase
```

| termino | que mide | por que esta |
|---|---|---|
| **supervisado** | `KernelDensityWeightedMSELoss(p_bag, log1p(u))` | MSE ponderado por densidad INVERSA. El KDE se ajusta SOLO sobre el pliegue de entrenamiento (higiene de pliegue) y los pesos se normalizan a media 1 por lote, para que la cola alta de UITI no se ahogue bajo la masa central |
| **reconstruccion** | `raw/(1+raw)` con `raw = MSE(reconstruido, entrada estandarizada)` | Se calcula contra el `x_inst` ORIGINAL, nunca contra `x'`: si no, la compuerta podria bajar la perdida simplificando su propio objetivo en vez de mejorar la representacion. La forma `raw/(1+raw)` acota en [0,1) SIN matar el gradiente, a diferencia de un recorte |
| **informacion mutua** | MI cuadratica de Renyi entre un kernel RBF sobre los perfiles de variables reconstruidas y el kernel del grafo fijo, normalizada por `log(p)`; la perdida es `1 - MI_norm` | Ata la representacion aprendida a la estructura del grafo experto |
| **desviacion de compuertas** | `lambda * media(abs(g - 1))` | Ancla las compuertas a la identidad. Apagado (`lambda = 0`) |
| **clase** | entropia cruzada sobre `softmax(-d^2 / T)` contra la clase observada, diferenciable a traves de `u_hat` | Sin el, nada en el costo sabe donde estan las fronteras entre centroides -- que es exactamente lo que mide la metrica |

**Dos advertencias medidas, no teoricas:**

- `TEMPERATURA_CLASE` **no** hereda el `1.0` de `distribucion_suave`. Con
  distancias de mediana 0.038, esa temperatura deja la softmax 99,9% uniforme
  (entropia 1.3850 contra `ln(4) = 1.3863`) y el termino queda en su piso desde
  la primera epoca, aportando una constante y ningun gradiente. `T = 0.01` es
  el valor medido sobre la geometria real.
- Los terminos del grafo estan acotados en [0,1] y pesan 0.01 cada uno: entre
  los dos pueden mover el total como maximo 0.02, contra un termino supervisado
  que se movio entre 0.35 y 6.8. Con estos lambda, el grafo casi no participa
  del gradiente.
'''

_MD_VISOR = '''\
## Modelo entrenado: carga y verificacion

Lee el artefacto guardado y las predicciones fuera de pliegue de la corrida
base. El artefacto lleva sus propios nombres de features y el cargador RECHAZA
un desajuste: puntuar columnas equivocadas no lanza error por si solo, solo
devuelve un mapa creible y falso.
'''

_CODE_VISOR = '''\
RUTA_MODELO = PROJECT_ROOT / "data" / "models" / "mil_vano_ventana_v1.pt"
RUTA_OOF = DERIVED_DIR / "oof_mil_full_film_clase1.0.npz"

if ENTRENAR:
    print("Modo entrenamiento: el visor se salta y el modelo se reentrena mas abajo.")
    predictor_guardado = None
    oof = None
else:
    predictor_guardado = cargar_modelo_mil(RUTA_MODELO, device=str(DEVICE))
    meta = predictor_guardado.metadatos
    # El desglose viaja DENTRO del artefacto: `data/models/**` esta versionado
    # y `data/derived/*` no, asi que depender del .npz haria que el visor
    # fallara en cualquier checkout limpio. El .npz queda como extra opcional
    # para analisis mas profundos.
    oof = np.load(RUTA_OOF) if RUTA_OOF.exists() else None
    print(f"Modelo: {RUTA_MODELO.name}")
    print(f"  fusion={meta.get('fusion')!r} lambda_clase={meta.get('lambda_clase')} "
          f"temperatura_clase={meta.get('temperatura_clase')} epocas={meta.get('epochs')}")
    print(f"  p (features de instancia) = {len(predictor_guardado.feature_names)}")
    print(f"  macro-F1 en validacion cruzada = {meta.get('macro_f1_cv')}")
    print(f"  referencia RandomForest       = {meta.get('macro_f1_randomforest_referencia')}")
    print(f"  NOTA: {meta.get('macro_f1_cv_nota')}")
    print(f"  bolsas evaluadas              = {meta['desglose_por_clase']['modelo']['n']:,}")
    print(f"Predicciones fuera de pliegue (.npz, opcional): "
          f"{'presentes' if oof is not None else 'ausentes -- el desglose sale del artefacto'}")
'''

_MD_VARIABLES = '''\
## Variables de entrada

Una fila por variable: su modalidad y su papel en el grafo experto fijo.
`grado_entrada` es lo que la propagacion puede CAMBIAR de esa variable, asi que
grado de entrada 0 significa que pasa por el grafo intacta.
`aristas_cruzadas` cuenta las aristas que unen las dos modalidades -- el unico
camino cruzado que el grafo aporta.
'''

_CODE_VARIABLES = '''\
if not ENTRENAR:
    _payload = torch.load(RUTA_MODELO, map_location="cpu", weights_only=False)
    tabla_vars = tabla_variables(
        _payload["features"], _payload["modalidades"], _payload["adjacency"],
    )
    resumen_modalidad = (
        tabla_vars.groupby("modalidad")
        .agg(variables=("variable", "size"),
             en_grafo=("en_grafo", "sum"),
             aristas_cruzadas=("aristas_cruzadas", "sum"))
        .reset_index()
    )
    print(f"p = {len(tabla_vars)} variables de instancia")
    print(resumen_modalidad.to_string(index=False))
    print()
    print("Variables que el grafo NO toca (grado de entrada 0):")
    _sin = tabla_vars.loc[tabla_vars["grado_entrada"] == 0, "variable"].tolist()
    print(f"  {len(_sin)} de {len(tabla_vars)}: {_sin}")
    print()
    display(tabla_vars)
'''

_MD_DESEMPENO = '''\
## Desempeno del modelo base

Matriz de confusion en CONTEO y en PORCENTAJE por fila observada, mas el
desempeno por grupo y global. El porcentaje se normaliza por fila para que
cada una responda "de las bolsas que ERAN de este grupo, a donde fueron" --
la vista de recall, que es en la que una clase abandonada aparece como una
fila con la diagonal en cero.
'''

_CODE_DESEMPENO = '''\
if not ENTRENAR:
    _desglose = predictor_guardado.metadatos["desglose_por_clase"]

    for _nombre in ("modelo", "estructural (RandomForest)"):
        _d = _desglose[_nombre]
        print(f"===== {_nombre} =====")
        _conteo = pd.DataFrame(np.asarray(_d["matriz_confusion"]), index=GRUPOS, columns=GRUPOS)
        _conteo.index.name = "OBSERVADA \\ PREDICHA"
        print("\\nMatriz de confusion (conteo)")
        display(_conteo)
        _pct = pd.DataFrame(
            matriz_confusion_porcentaje(np.asarray(_d["matriz_confusion"])).round(2),
            index=GRUPOS, columns=GRUPOS,
        )
        _pct.index.name = "OBSERVADA \\ PREDICHA (%)"
        print("Matriz de confusion (% por fila observada)")
        display(_pct)
        print("Desempeno por grupo")
        display(pd.DataFrame(_d["por_clase"])[
            ["grupo", "precision", "recall", "f1", "soporte"]
        ].round(4))
        print(f"GLOBAL: accuracy={_d['accuracy']:.4f}  macro-F1={_d['macro_f1']:.4f}  "
              f"n={_d['n']:,}  clases nunca predichas={_d['clases_abandonadas']}")
        print()

    _resumen = pd.DataFrame([
        {"arm": k, "accuracy": v["accuracy"], "macro_f1": v["macro_f1"], "n": v["n"]}
        for k, v in _desglose.items()
    ]).sort_values("macro_f1", ascending=False)
    print("Comparacion global de todos los brazos")
    display(_resumen.round(6))
'''

_MD_GUARDADO = '''\
## Guardado del modelo (solo al reentrenar)

Persiste el modelo ajustado con sus nombres de features, su grafo y la
geometria, para que 01.5 pueda cargarlo. Sin esto, el modelo final vivia solo
en memoria y el simulador no tenia nada que levantar.
'''

_CODE_GUARDADO = '''\
if ENTRENAR and PROCEDER_CON_ENTRENAMIENTO_COMPLETO and mode == "full":
    ruta_modelo = guardar_modelo_mil(
        PROJECT_ROOT / "data" / "models" / "mil_vano_ventana_v1.pt",
        modelo=resultado_final["model"],
        features=features_inst,
        modalidades=modality_indices,
        adjacency=A_adyacencia,
        edges=preserved_edges,
        geometria=geometria,
        hiperparametros={
            "hidden_dim": HIDDEN_DIM, "embed_dim": EMBED_DIM, "dropout": DROPOUT,
            "alpha": ALPHA, "attn_dim": ATTN_DIM,
        },
        metadatos={
            "fusion": FUSION,
            "film_modulated_modality": FILM_MODULATED_MODALITY if FUSION == "film" else None,
            "lambda_clase": LAMBDA_CLASE,
            "temperatura_clase": TEMPERATURA_CLASE,
            "epochs": EPOCHS,
            "seed": RANDOM_STATE,
            "macro_f1_cv": float(tabla_arms.loc[tabla_arms["arm"] == "modelo", "macro_f1"].iloc[0]),
            "macro_f1_randomforest_referencia": float(
                tabla_arms.loc[tabla_arms["arm"] == "estructural", "macro_f1"].iloc[0]
            ),
            "ventana_climatica_horas": 12,
            "min_frecuencia_relativa_cod_causa": 0.01,
        },
    )
    print(f"Modelo guardado en: {ruta_modelo}")
else:
    print("Guardado OMITIDO -- solo se guarda al reentrenar con mode='full'.")
'''


_MD_TITLE = '''\
# 10. Aprendizaje de instancias multiples (MIL) sobre bolsas vano x ventana de 01.4

Cada **bolsa** es una celda `(CIRCUITO, FID_VANO, ventana)` de
`01.4_uiti_vano_trayectorias_vano.ipynb`; cada **instancia** es un evento de
falla dentro de esa celda. Las 11 ventanas de 01.3/01.4 se solapan (mes
calendario mas la cruzada del 15 al 15), asi que un mismo evento puede caer
en dos bolsas del mismo vano -- se duplica, nunca se filtra.

El modelo codifica cada instancia con `MGCECDLRegressor._encode_modalities`
(reutilizado sin cambios), agrupa las instancias de una bolsa con atencion
invariante a cardinalidad, decodifica UNA compuerta de arista por bolsa sobre
el grafo experto fijo (`PerSampleEdgeGateDecoder`, tambien reutilizado),
propaga esa compuerta hacia las instancias, vuelve a codificar y a agrupar, y
lee un escalar por bolsa `p_bag ~ log1p(uiti_acumulado)`. La clase de
criticidad reportada es la regla de vecino-mas-cercano que 01.4 ya calculo
con KMeans -- no se reajusta aqui.

Generado por `scripts/generate_notebook_10.py` (COMMITTED, reproducible).
Ver `sdd/notebook-10-mil-vano-ventana/{spec,design}` para el contrato
completo.

**Este cuaderno se genera SIN ejecutar el entrenamiento.** Ninguna corrida
MIL se ha cronometrado nunca en esta maquina -- la celda 6 mide UNA corrida
corta y proyecta el costo total antes de proponer lanzar la validacion
cruzada completa; la decision de correrla queda en manos de quien ejecute
este cuaderno.
'''

_MD_DIAGRAM = '''\
## Diagrama del flujo de datos

```mermaid
flowchart TD
    A["procesar_dataset_completo (seleccion compartida)"] --> B["codificar_cod_causa (D4)"]
    B --> C["construir_matriz_instancias -> X_inst, p features"]
    C --> D["construir_matriz_adyacencia_mgcecdl -> A, E aristas"]
    A --> E["construir_indice_bolsas (11 ventanas de 01.4) -> BagIndex"]
    F["extract_geometrias_014.py -> geometrias_014.json"] --> G["cargar_geometria_014 + verificar_sha1_geometrias"]
    C --> H["X_inst_bolsas = X_inst[bag_index.instance_rows]"]
    E --> H
    H --> I["StratifiedGroupKFold(groups=CIRCUITO|FID_VANO)"]
    I --> J["MILBagRegressor + MILBagLoss (por pliegue)"]
    J --> K["BagPredictor -> u_hat, clase (nearest-centroid con G)"]
    K --> L["evaluar_arms vs 3 baselines, subconjunto de variacion intra-vano"]
```
'''

_CODE_PARAMETERS = '''\
# Celda de parametros (papermill). Sobrescribir con `-p mode full` para la corrida real.
# El default es "smoke" a proposito, mismo patron que la libreta 12.
mode = "smoke"

# COMO se ejecuta este cuaderno:
#   "visualizacion" (default) -> NO entrena. Lee el modelo guardado y las
#        predicciones fuera de pliegue, y reporta arquitectura, costo,
#        variables y desempeno. Corre en segundos.
#   "entrenamiento"           -> reentrena de cero (~40 min con mode="full")
#        y sobreescribe el artefacto.
EJECUCION = "visualizacion"

# Diales de BRAZO. Viven aqui, y no en la celda de configuracion, para que
# papermill pueda fijarlos con -p: atribuir un cambio exige una corrida por
# brazo, y tres cuadernos generados por separado se desincronizan solos.
#   "concat"      -> head lineal sobre el latente concatenado (brazo original)
#   "film"        -> el clima MODULA la representacion estructural
#   "reliability" -> fusion ponderada por confiabilidad a grano de bolsa
FUSION = "film"
FILM_MODULATED_MODALITY = "estructurales"
# Peso de la entropia cruzada sobre las clases de 01.4. 0.0 la apaga.
LAMBDA_CLASE = 1.0
# NO se hereda el 1.0 de distribucion_suave: con d^2 de mediana 0.038 esa
# temperatura deja la softmax 99,9% uniforme (entropia 1.3850 contra
# ln(4) = 1.3863) y el termino queda en su piso desde la primera epoca.
TEMPERATURA_CLASE = 0.01
'''

_MD_BOOTSTRAP = '''\
## Bootstrap: raiz del repo, `sys.path` y guarda de precondiciones

Falla rapido y con un mensaje accionable si los modulos de PR1-4 no son
importables. Ninguno de ellos se re-exporta desde `chec_impacto.data`,
`chec_impacto.models` o `chec_impacto.interpretability` -- se importan por
ruta completa, igual que en sus propios tests.
'''

_CODE_BOOTSTRAP = '''\
import sys
from pathlib import Path


def resolve_project_root():
    cwd = Path.cwd().resolve()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / "src" / "chec_impacto").exists() and (candidate / "data").exists():
            return candidate
    raise FileNotFoundError(
        "No se encontro la raiz del proyecto (se busco un directorio con src/chec_impacto/ "
        "y data/ subiendo desde el cwd). Ejecuta este cuaderno desde el checkout."
    )


PROJECT_ROOT = resolve_project_root()
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
DERIVED_DIR = DATA_DIR / "derived"

for path_to_add in (PROJECT_ROOT, SRC_DIR):
    if str(path_to_add) not in sys.path:
        sys.path.insert(0, str(path_to_add))
DERIVED_DIR.mkdir(parents=True, exist_ok=True)

print("PROJECT_ROOT:", PROJECT_ROOT)
print("DATA_DIR:    ", DATA_DIR)

try:
    from chec_impacto.data.bags import (
        CodCausaEncoding,
        cachear_bolsas,
        codificar_cod_causa,
        construir_indice_bolsas,
        construir_matriz_instancias,
    )
    from chec_impacto.models.criticality_assignment import (
        GEOMETRIAS_SHA1_ESPERADO,
        asignar_clase,
        cargar_geometria_014,
        distribucion_suave,
        GRUPOS,
        verificar_sha1_geometrias,
    )
    from chec_impacto.models.mgcecdl_mil import MILBagLoss, MILBagRegressor, entrenar_mil
    from chec_impacto.models.mil_persistencia import cargar_modelo_mil, guardar_modelo_mil
    from chec_impacto.interpretability.mil_vano_ventana import (
        BARRA_ACEPTACION_A1_PUNTOS,
        BagPredictor,
        baseline_estructural,
        baseline_mayoritaria,
        baseline_persistencia,
        construir_folds_agrupados,
        desglose_por_circuito,
        desglose_por_clase,
        contraste_u,
        predecir_u_estructural,
        formatear_desglose_por_clase,
        matriz_confusion_porcentaje,
        tabla_variables,
        evaluar_arms,
        evaluar_diagnostico_temporal,
        grafo_por_grupo_si_no_colapsado,
        guardia_proxy_univariante_mil,
        particion_bloque_temporal,
        predict_fn,
        subconjunto_variacion_intravano,
    )
    from chec_impacto.data import construir_matriz_adyacencia_mgcecdl, procesar_dataset_completo
    from chec_impacto.models import GraphEdgeIndex, construir_edge_index
    from chec_impacto.models.mgcecdl import KernelDensityWeightedMSELoss, MGCECDLRegressor
    from chec_impacto.training import (
        calcular_estadisticas_reconstruccion_mgcecdl,
        construir_modalidades_mgcecdl,
        resolve_training_device,
    )
    from scripts.extract_geometrias_014 import DEFAULT_OUTPUT_PATH, extraer_geometrias_014
except ImportError as exc:
    raise SystemExit(
        "Los modulos de PR1-4 (data/bags.py, models/criticality_assignment.py, "
        "models/mgcecdl_mil.py, interpretability/mil_vano_ventana.py) no son importables "
        f"desde {SRC_DIR}. Verifica que corres desde el checkout y que el entorno tiene "
        "torch/scikit-learn/shap instalados (pip install -r requirements.txt)."
    ) from exc

print("Guarda OK: modulos PR1-4 importables.")
'''

_CODE_IMPORTS = '''\
import time

import numpy as np
import pandas as pd
import shap
import torch
from sklearn.ensemble import RandomForestRegressor

RANDOM_STATE = 42
DEVICE = resolve_training_device("auto")
print("Dispositivo de entrenamiento resuelto:", DEVICE)
if DEVICE.type == "cpu":
    print("AVISO: se entrenara en CPU. Con mode='full' esto puede tardar horas.")
'''

_MD_CONFIG = '''\
## Configuracion del presupuesto (`smoke` vs `full`)

`N_SPLITS = 5` (D8, `StratifiedGroupKFold`) es fijo en ambos modos. Los demas
hiperparametros del modelo (`HIDDEN_DIM`, `EMBED_DIM`, `ALPHA`, los `LAMBDA_*`)
son valores fijos razonables -- este cuaderno no corre una busqueda de
hiperparametros (a diferencia de la libreta 12, aqui no hay un objetivo de
Optuna definido en el diseno).
'''

_CODE_CONFIG = '''\
if EJECUCION not in ("visualizacion", "entrenamiento"):
    raise ValueError(
        f"EJECUCION desconocida: {EJECUCION!r} -- se esperaba 'visualizacion' o 'entrenamiento'."
    )
ENTRENAR = EJECUCION == "entrenamiento"
print(f"EJECUCION={EJECUCION!r} -> "
      + ("REENTRENA de cero y sobreescribe el artefacto."
         if ENTRENAR else "solo LEE el modelo guardado; no entrena nada."))

if FUSION not in ("concat", "film", "reliability"):
    raise ValueError(f"FUSION desconocida: {FUSION!r}")
if mode not in ("smoke", "full"):
    raise ValueError(f"mode desconocido: {mode!r} -- se esperaba 'smoke' o 'full'.")

N_SPLITS = 5
HIDDEN_DIM = 128
EMBED_DIM = 64
DROPOUT = 0.1
ALPHA = 0.2
ATTN_DIM = 64
LAMBDA_RECONSTRUCTION = 0.01
LAMBDA_MUTUAL_INFORMATION = 0.01
LAMBDA_GATE_DEVIATION = 0.0
# "reliability": la fusion ocurre a grano de BOLSA y revive
# base.modality_regressors / base.modality_reliability_heads, que bajo
# "concat" reciben gradiente cero. Expone `reliabilities` por bolsa.
# Supervisa la prediccion de cada modalidad por separado; es lo que
# mantiene legibles las confiabilidades (ver MILBagLoss.compute_components).
LAMBDA_MODALITY_SUPERVISED = 0.0
LR = 1e-3
WEIGHT_DECAY = 1e-5
BAG_BATCH_SIZE = 256

if mode == "smoke":
    EPOCHS = 2
    COST_CEILING_SECONDS = 900.0
else:
    EPOCHS = 30
    # Techo declarado por quien ejecuta el cuaderno para la fase costosa (validacion
    # cruzada completa): si la proyeccion de la celda de pronostico lo supera, NO se
    # lanza el entrenamiento completo.
    COST_CEILING_SECONDS = 6.0 * 3600.0

print(f"mode={mode!r} | N_SPLITS={N_SPLITS} | EPOCHS={EPOCHS} | "
      f"COST_CEILING_SECONDS={COST_CEILING_SECONDS}")
print(f"fusion={FUSION!r} | LAMBDA_MODALITY_SUPERVISED={LAMBDA_MODALITY_SUPERVISED} | "
      f"LAMBDA_CLASE={LAMBDA_CLASE} | TEMPERATURA_CLASE={TEMPERATURA_CLASE}")
'''

_MD_DATA_LOAD = '''\
### Datos e instancias

`procesar_dataset_completo` + `codificar_cod_causa` (umbral 1,0%) ->
`construir_matriz_instancias` agrega la frecuencia de `COD_CAUSA` y sus
indicadores. `p` se deriva en tiempo de ejecucion, nunca se escribe a mano.
'''

_CODE_DATA_LOAD = '''\
resultado = procesar_dataset_completo(
    path_clima=DATA_DIR / "Indicadores_vano_v3.csv",
    path_variables_seleccion=DATA_DIR / "Variables_seleccion.xlsx",
    use_sampling=False,
    target="UITI_VANO",
    filtro_uiti_max=None,
    ventana_climatica_horas=12,
)
df_identidad = resultado["df_original_copy"].reset_index(drop=True)

df_causa, encoding = codificar_cod_causa(df_identidad, min_frecuencia_relativa=0.01)
print(f"Codigos propios (frecuencia >= 1.0%%): {len(encoding.codigos_propios)} "
      f"-> {encoding.codigos_propios}")
print(f"Indicadores COD_CAUSA_*: {encoding.nombres_indicadores}")

X_inst_original, features_inst = construir_matriz_instancias(
    resultado, df_causa, encoding, resultado["features"],
)
p_derivado = len(features_inst)
assert p_derivado == X_inst_original.shape[1], "p debe coincidir con el ancho de X_inst_original."
print(f"p (features de instancia, derivado en tiempo de ejecucion) = {p_derivado}")
assert features_inst.count("COD_CAUSA") == 1, (
    "'COD_CAUSA' debe aparecer exactamente una vez -- cualquier otro nombre borra el "
    "nodo del grafo experto (D4)."
)
'''

_MD_GRAPH = '''\
### Grafo experto fijo

`construir_matriz_adyacencia_mgcecdl` sobre las features de instancia.
`COD_CAUSA` debe quedar como sumidero (aristas de entrada, ninguna de salida).
'''

_CODE_GRAPH = '''\
A_adyacencia, preserved_edges = construir_matriz_adyacencia_mgcecdl(
    features_inst, ventana_climatica_horas=12,
)
edge_index = construir_edge_index(A_adyacencia, features_inst, preserved_edges)
print(f"p={len(features_inst)}  E={edge_index.n_edges}")
assert edge_index.n_edges == 64, (
    f"E={edge_index.n_edges} pero el diseno D4 deriva 64 (56 base + 8 de entrada a "
    "COD_CAUSA) para el grafo experto fijo mas la seleccion de variables actual."
)

pos_cod_causa = features_inst.index("COD_CAUSA")
in_edges_cod_causa = int((A_adyacencia[:, pos_cod_causa] != 0).sum())
out_edges_cod_causa = int((A_adyacencia[pos_cod_causa, :] != 0).sum())
print(f"COD_CAUSA: {in_edges_cod_causa} aristas de entrada, {out_edges_cod_causa} de salida")
assert in_edges_cod_causa == 8 and out_edges_cod_causa == 0, (
    "COD_CAUSA debe ser un sumidero puro (8 entradas, 0 salidas) -- D4."
)

modality_indices = construir_modalidades_mgcecdl(features_inst)
print("Modalidad estructural:", len(modality_indices["estructurales"]), "features")
print("Modalidad climatica:  ", len(modality_indices["climaticos"]), "features")
'''

_MD_GEOMETRIA = '''\
### Geometria de 01.4

Se reutiliza la geometria KMeans que 01.4 ya exporto, verificada por sha1. La
clase de criticidad NO se reajusta aqui.
'''

_CODE_GEOMETRIA = '''\
geometrias_path = DEFAULT_OUTPUT_PATH
if not geometrias_path.exists():
    geometrias_path = extraer_geometrias_014()
    print("Geometrias extraidas en:", geometrias_path)
else:
    print("Cache de geometrias existente, reutilizada:", geometrias_path)

geometria = cargar_geometria_014(geometrias_path)

geometrias_sha1_real, geometrias_sha1_coincide = verificar_sha1_geometrias(geometrias_path)
print(f"sha1 esperado de 'geometrias': {GEOMETRIAS_SHA1_ESPERADO}")
print(f"sha1 real de 'geometrias':     {geometrias_sha1_real}")
assert geometrias_sha1_coincide, (
    "La geometria KMeans extraida de 01.4 cambio de VALORES respecto al 2026-08-02 "
    f"(esperado={GEOMETRIAS_SHA1_ESPERADO}, real={geometrias_sha1_real}). Esto "
    "significa que 01.4 movio los centroides -- las clases de criticidad se "
    "correrian en silencio si se continua sin revisar. Deten la corrida y reconcilia "
    "contra sdd/notebook-10-mil-vano-ventana/estado-ramas antes de seguir."
)
'''

_MD_BAGS = '''\
### Bolsas vano x ventana

Las 11 ventanas de 01.4 se solapan: un evento puede caer en dos bolsas del
mismo vano y se duplica, nunca se filtra.
'''

_CODE_BAGS = '''\
_meses = pd.period_range(df_causa["FECHA"].min(), df_causa["FECHA"].max(), freq="M")
_fin = _meses[-1].to_timestamp(how="end").normalize() + pd.Timedelta(days=1)
_cortes = []
for _k, _m in enumerate(_meses):
    _ini = _m.to_timestamp()
    _f = _meses[_k + 1].to_timestamp() if _k + 1 < len(_meses) else _fin
    _cortes.append((_ini, _f))
    _cortes.append((_ini + pd.Timedelta(days=14), _f + pd.Timedelta(days=14)))
_cortes = sorted(c for c in _cortes if c[1] <= _fin)
print(f"{len(_cortes)} ventanas (esperado: 11, identico a 01.4)")

ventanas_bolsas = [
    (f"V{k + 1}", ((df_causa["FECHA"] >= a) & (df_causa["FECHA"] < b)).to_numpy())
    for k, (a, b) in enumerate(_cortes)
]
bag_index = construir_indice_bolsas(df_causa, ventanas_bolsas, target_col="UITI_VANO")

n_bags = len(bag_index.offsets) - 1
n_inst = len(bag_index.instance_bag)
fraccion_singleton = float((bag_index.counts == 1).mean())
n_bolsas_uiti_cero = int((bag_index.y == 0).sum())

print(f"bolsas={n_bags:,}  instancias={n_inst:,}  singleton={fraccion_singleton:.3%}  "
      f"bolsas con uiti_acumulado==0: {n_bolsas_uiti_cero}")
assert n_bags == 111233, f"n_bags={n_bags}, esperado 111233 (obs #524)."
assert n_inst == 288632, f"n_inst={n_inst}, esperado 288632 (obs #524)."
assert abs(fraccion_singleton - 0.527) < 0.001, f"fraccion singleton={fraccion_singleton}"
assert n_bolsas_uiti_cero == 0, "0 bolsas deben tener uiti_acumulado == 0 (obs #524)."

X_inst_bolsas = X_inst_original[bag_index.instance_rows]
assert X_inst_bolsas.shape == (n_inst, p_derivado)

cache_path = DERIVED_DIR / f"bolsas_mil_{mode}.joblib"
cachear_bolsas(cache_path, X_inst_bolsas, bag_index, features_inst, encoding)
print("Bolsas cacheadas en:", cache_path)
'''

_MD_CLASE_OBSERVADA = '''\
### Clase observada

`n_obs` es SIEMPRE observado; `u` es observado en la verdad y predicho (`u_hat`)
para el modelo.
'''

_CODE_CLASE_OBSERVADA = '''\
n_obs_observado = bag_index.counts.astype(np.float64)
u_observado = bag_index.y.astype(np.float64)
clase_observada, n_clamped_observado = asignar_clase(n_obs_observado, u_observado, geometria)
print(f"Distribucion de clase observada: "
      f"{pd.Series(clase_observada).value_counts().sort_index().to_dict()}")
assert n_clamped_observado == 0, (
    "El camino OBSERVADO nunca debe clampar (0 de 111.233 bolsas tienen "
    "uiti_acumulado == 0, obs #524)."
)

circuito_por_bolsa = bag_index.keys["CIRCUITO"].to_numpy()
'''

_MD_HELPERS = '''\
### Utilidades de pliegue

Subindices de bolsas, promedio por bolsa y el ciclo ajustar-evaluar que cada
pliegue reutiliza.
'''

_CODE_HELPERS = '''\
from chec_impacto.data.bags import BagIndex


def format_duration(seconds):
    seconds = int(max(seconds, 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def construir_subindice_bolsas(bag_index, X_bolsas, indices_bolsa):
    # Reconstruye un BagIndex sobre SOLO `indices_bolsa`, remapeado a un layout CSR
    # denso 0..len(indices_bolsa)-1, junto con la matriz de instancias correspondiente.
    indices_bolsa = np.asarray(indices_bolsa, dtype=np.int64)
    counts_sub = bag_index.counts[indices_bolsa]
    offsets_sub = np.zeros(len(indices_bolsa) + 1, dtype=np.int64)
    offsets_sub[1:] = np.cumsum(counts_sub)
    tramos = [
        np.arange(int(bag_index.offsets[b]), int(bag_index.offsets[b + 1]), dtype=np.int64)
        for b in indices_bolsa
    ]
    filas = np.concatenate(tramos) if tramos else np.array([], dtype=np.int64)
    instance_bag_sub = np.repeat(np.arange(len(indices_bolsa), dtype=np.int64), counts_sub)

    bag_index_sub = BagIndex(
        keys=bag_index.keys.iloc[indices_bolsa].reset_index(drop=True),
        instance_bag=instance_bag_sub,
        offsets=offsets_sub,
        counts=counts_sub,
        y=bag_index.y[indices_bolsa],
        group=bag_index.group[indices_bolsa],
        instance_rows=bag_index.instance_rows[filas],
    )
    return bag_index_sub, X_bolsas[filas]


def promedio_por_bolsa(X_bolsas, bag_index, columnas=None):
    Xc = X_bolsas if columnas is None else X_bolsas[:, columnas]
    n_bags_local = len(bag_index.offsets) - 1
    suma = np.zeros((n_bags_local, Xc.shape[1]), dtype=np.float64)
    np.add.at(suma, bag_index.instance_bag, Xc)
    return suma / bag_index.counts.reshape(-1, 1).astype(np.float64)


def construir_modelo_y_perdida(feature_mean, feature_std, kernel_loss):
    base = MGCECDLRegressor(
        modality_feature_indices=modality_indices,
        hidden_dim=HIDDEN_DIM, embed_dim=EMBED_DIM, dropout=DROPOUT,
    )
    modelo = MILBagRegressor(
        base=base, adjacency=A_adyacencia, edge_index=edge_index, alpha=ALPHA, attn_dim=ATTN_DIM,
        fusion=FUSION,
        film_modulated_modality=FILM_MODULATED_MODALITY if FUSION == "film" else None,
    ).to(DEVICE)
    perdida = MILBagLoss(
        feature_mean=feature_mean, feature_std=feature_std, adjacency_matrix=A_adyacencia,
        kernel_loss=kernel_loss, lambda_reconstruction=LAMBDA_RECONSTRUCTION,
        lambda_mutual_information=LAMBDA_MUTUAL_INFORMATION,
        lambda_gate_deviation=LAMBDA_GATE_DEVIATION,
        lambda_modality_supervised=LAMBDA_MODALITY_SUPERVISED,
        lambda_clase=LAMBDA_CLASE, geometria=geometria,
        temperatura_clase=TEMPERATURA_CLASE,
        reconstruction_normalization="soft",
    ).to(DEVICE)
    return modelo, perdida


def evaluar_lote_completo(modelo, X_bolsas_sub, bag_index_sub):
    # Corre el modelo una vez sobre TODAS las bolsas de `bag_index_sub` y devuelve
    # tanto u_hat como las compuertas por bolsa (para A4 mas abajo).
    modelo.eval()
    with torch.no_grad():
        x_tensor = torch.as_tensor(X_bolsas_sub, dtype=torch.float32, device=DEVICE)
        bag_tensor = torch.as_tensor(bag_index_sub.instance_bag, dtype=torch.long, device=DEVICE)
        n_bags_sub = len(bag_index_sub.offsets) - 1
        salida = modelo(x_tensor, bag_tensor, n_bags_sub)
    u_hat = np.expm1(salida["p_bag"].detach().cpu().numpy())
    gates = salida["edge_gates"].detach().cpu().numpy()
    return u_hat, gates


def ajustar_y_evaluar_pliegue(train_idx, test_idx, *, epochs, seed):
    bag_index_train, X_train_bag = construir_subindice_bolsas(bag_index, X_inst_bolsas, train_idx)
    bag_index_test, X_test_bag = construir_subindice_bolsas(bag_index, X_inst_bolsas, test_idx)

    feature_mean, feature_std = calcular_estadisticas_reconstruccion_mgcecdl(X_train_bag)
    kernel_loss = KernelDensityWeightedMSELoss.from_targets(np.log1p(bag_index_train.y))
    modelo, perdida = construir_modelo_y_perdida(feature_mean, feature_std, kernel_loss)

    resultado_fit = entrenar_mil(
        modelo, perdida, X_train_bag, bag_index_train, epochs=epochs,
        bag_batch_size=BAG_BATCH_SIZE, lr=LR, weight_decay=WEIGHT_DECAY, seed=seed, device=DEVICE,
        verbose=True,
    )
    modelo_ajustado = resultado_fit["model"]

    u_hat_test, gates_test = evaluar_lote_completo(modelo_ajustado, X_test_bag, bag_index_test)
    n_obs_test = bag_index_test.counts.astype(np.float64)
    clase_test, _ = asignar_clase(n_obs_test, u_hat_test, geometria)
    return modelo_ajustado, u_hat_test, clase_test, gates_test
'''

_MD_COST_FORECAST = '''\
### Pronostico de costo (compuerta obligatoria)

Cronometra un pliegue de referencia y proyecta la validacion cruzada completa
contra `COST_CEILING_SECONDS` antes de lanzarla.
'''

_CODE_COST_FORECAST = '''\
_pliegues_referencia = construir_folds_agrupados(bag_index, clase_observada, n_splits=N_SPLITS, seed=RANDOM_STATE)
_train_idx_ref, _test_idx_ref = _pliegues_referencia[0]

_forecast_t0 = time.time()
ajustar_y_evaluar_pliegue(_train_idx_ref, _test_idx_ref, epochs=EPOCHS, seed=RANDOM_STATE)
single_run_seconds = time.time() - _forecast_t0

N_RUNS = N_SPLITS
projected_total_seconds = single_run_seconds * N_RUNS

print(f"Un pliegue MIL de dos pasadas (epochs={EPOCHS}): "
      f"{single_run_seconds:.2f}s ({format_duration(single_run_seconds)})")
print(f"Proyeccion para los {N_RUNS} pliegues de la validacion cruzada completa: "
      f"{format_duration(projected_total_seconds)}")
print(f"Techo declarado (COST_CEILING_SECONDS): {format_duration(COST_CEILING_SECONDS)}")

PROCEDER_CON_ENTRENAMIENTO_COMPLETO = projected_total_seconds <= COST_CEILING_SECONDS
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    print("GO: la proyeccion cabe dentro del techo declarado -- se procede con la "
          "validacion cruzada completa.")
else:
    print("NO-GO: la proyeccion EXCEDE el techo declarado -- la validacion cruzada "
          "completa NO se lanza. Sube COST_CEILING_SECONDS o reduce EPOCHS/N_SPLITS "
          "conscientemente para continuar.")
'''

_MD_CV_LOOP = '''\
### Validacion cruzada agrupada + subconjunto intra-vano

`StratifiedGroupKFold(groups=bag_index.group)` evita que las bolsas de un mismo
vano crucen pliegues. El subconjunto de variacion intra-vano se congela ANTES
de la validacion.
'''

_CODE_CV_LOOP = '''\
folds = construir_folds_agrupados(bag_index, clase_observada, n_splits=N_SPLITS, seed=RANDOM_STATE)
subconjunto_variacion = subconjunto_variacion_intravano(bag_index, clase_observada)
print(f"Bolsas en el subconjunto de variacion intra-vano: {int(subconjunto_variacion.sum()):,} "
      f"de {n_bags:,}")

oof_clase_modelo = np.full(n_bags, -1, dtype=int)
oof_u_hat = np.full(n_bags, np.nan, dtype=np.float64)
oof_gates = np.full((n_bags, edge_index.n_edges), np.nan, dtype=np.float64)
oof_clase_mayoritaria = np.full(n_bags, -1, dtype=int)
oof_clase_estructural = np.full(n_bags, -1, dtype=int)
oof_u_estructural = np.full(n_bags, np.nan, dtype=np.float64)
oof_clase_persistencia = np.full(n_bags, -1, dtype=int)
oof_tiene_persistencia = np.zeros(n_bags, dtype=bool)

X_bag_estructural = promedio_por_bolsa(X_inst_bolsas, bag_index, modality_indices["estructurales"])

if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    segundos_acumulados_pliegues = 0.0
    for fold_i, (train_idx, test_idx) in enumerate(folds):
        print(f"--- pliegue {fold_i + 1}/{N_SPLITS} ---")
        _pliegue_t0 = time.perf_counter()
        _, u_hat_test, clase_test, gates_test = ajustar_y_evaluar_pliegue(
            train_idx, test_idx, epochs=EPOCHS, seed=RANDOM_STATE + fold_i,
        )
        segundos_pliegue = time.perf_counter() - _pliegue_t0
        segundos_acumulados_pliegues += segundos_pliegue
        pliegues_completados = fold_i + 1
        pliegues_restantes = N_SPLITS - pliegues_completados
        segundos_restantes_pliegues = pliegues_restantes * (
            segundos_acumulados_pliegues / pliegues_completados
        )
        print(f"    pliegue {pliegues_completados}/{N_SPLITS} completado en "
              f"{format_duration(segundos_pliegue)} | ETA pliegues restantes: "
              f"{format_duration(segundos_restantes_pliegues)}")
        oof_clase_modelo[test_idx] = clase_test
        oof_u_hat[test_idx] = u_hat_test
        oof_gates[test_idx] = gates_test

        oof_clase_mayoritaria[test_idx] = baseline_mayoritaria(
            clase_observada[train_idx], len(test_idx),
        )
        # UN solo ajuste del RandomForest, dos salidas: la clase que publica la
        # linea base y la `u` con que la calcula. Llamar a baseline_estructural
        # ademas de esto lo ajustaria dos veces por pliegue.
        u_est_test = predecir_u_estructural(
            X_bag_estructural[train_idx], bag_index.y[train_idx], X_bag_estructural[test_idx],
            seed=RANDOM_STATE,
        )
        oof_u_estructural[test_idx] = u_est_test
        oof_clase_estructural[test_idx], _ = asignar_clase(
            bag_index.counts[test_idx].astype(np.float64), u_est_test, geometria,
        )

        test_mask_fold = np.zeros(n_bags, dtype=bool)
        test_mask_fold[test_idx] = True
        pred_persistencia_fold, tiene_persistencia_fold = baseline_persistencia(
            bag_index, clase_observada, test_mask_fold,
        )
        test_idx_ordenado = np.flatnonzero(test_mask_fold)
        oof_clase_persistencia[test_idx_ordenado] = pred_persistencia_fold
        oof_tiene_persistencia[test_idx_ordenado] = tiene_persistencia_fold

    print("Validacion cruzada completa: OK.")
else:
    print("Validacion cruzada completa OMITIDA (compuerta de costo NO-GO en la celda 7).")
'''

_MD_A1_BASELINES = '''\
### Compuerta A1 contra la mejor linea base

El modelo debe superar por >= 5,0 puntos de macro-F1 a la MEJOR linea base, no
solo a persistencia. No cumplirla se reporta como resultado negativo explicito.
'''

_CODE_A1_BASELINES = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    predicciones_arms = {
        "modelo": oof_clase_modelo[subconjunto_variacion],
        "mayoritaria": oof_clase_mayoritaria[subconjunto_variacion],
        "estructural": oof_clase_estructural[subconjunto_variacion],
    }
    subconjunto_con_persistencia = subconjunto_variacion & oof_tiene_persistencia
    tabla_arms = evaluar_arms(
        clase_observada, {
            "modelo": oof_clase_modelo[subconjunto_con_persistencia],
            "mayoritaria": oof_clase_mayoritaria[subconjunto_con_persistencia],
            "estructural": oof_clase_estructural[subconjunto_con_persistencia],
            "persistencia": oof_clase_persistencia[subconjunto_con_persistencia],
        },
        subconjunto_con_persistencia,
    )
    print(tabla_arms)
    print()
    print(tabla_arms.attrs["veredicto"])
else:
    print("Evaluacion A1 OMITIDA -- requiere las predicciones out-of-fold de la celda 8.")
'''

_MD_POR_CLASE = '''\
## 9.1 Desglose por clase (matriz de confusion, precision/recall/F1, accuracy)

macro-F1 no distingue "mediocre parejo" de "abandono una clase", y aqui esa
es la pregunta: `Alto` es el 10,21%% del subconjunto de variacion intra-vano
(6.342 de 62.114 bolsas) y es la clase que le importa a CHEC. Un brazo que
acierte perfecto las otras tres y NUNCA prediga `Alto` saca 89,8%% de
accuracy y 0,75 de macro-F1 -- y el modelo observado saca 0,7704, lo bastante
cerca de 3/4 como para que la pregunta no se pueda esquivar.

`accuracy` se reporta al lado, nunca como titular: la linea base mayoritaria
ya saca 0,4384 de accuracy contra 0,1524 de macro-F1.

Esta celda ademas PERSISTE las predicciones fuera de pliegue. Sin eso, de una
corrida de 40 minutos solo sobrevive un escalar y texto impreso, y cualquier
diagnostico posterior obliga a reentrenar.
'''

_CODE_POR_CLASE = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    desglose_clases = desglose_por_clase(
        clase_observada, {
            "modelo": oof_clase_modelo[subconjunto_con_persistencia],
            "estructural": oof_clase_estructural[subconjunto_con_persistencia],
            "persistencia": oof_clase_persistencia[subconjunto_con_persistencia],
            "mayoritaria": oof_clase_mayoritaria[subconjunto_con_persistencia],
        },
        subconjunto_con_persistencia,
    )
    print(formatear_desglose_por_clase(desglose_clases))

    # Las predicciones fuera de pliegue son el unico artefacto reutilizable de
    # la corrida: sin ellas, re-leer el resultado con otra metrica cuesta otro
    # entrenamiento completo. El nombre lleva el brazo para que dos corridas
    # con distinta configuracion no se pisen.
    # Contraste en espacio de `u`: los dos brazos regresan la MISMA cantidad y
    # pasan por la MISMA regla de centroide mas cercano, asi que una brecha de
    # macro-F1 vive en la regresion o en el mapeo. Comparar clases no los separa.
    print(contraste_u(
        bag_index.y,
        {
            "modelo": oof_u_hat[subconjunto_con_persistencia],
            "estructural": oof_u_estructural[subconjunto_con_persistencia],
        },
        subconjunto_con_persistencia,
    ).to_string(index=False))
    print()

    ruta_oof = DERIVED_DIR / f"oof_mil_{mode}_{FUSION}_clase{LAMBDA_CLASE}.npz"
    np.savez_compressed(
        ruta_oof,
        clase_observada=clase_observada,
        oof_clase_modelo=oof_clase_modelo,
        oof_u_hat=oof_u_hat,
        oof_clase_estructural=oof_clase_estructural,
        oof_u_estructural=oof_u_estructural,
        oof_clase_persistencia=oof_clase_persistencia,
        oof_clase_mayoritaria=oof_clase_mayoritaria,
        oof_tiene_persistencia=oof_tiene_persistencia,
        subconjunto_variacion=subconjunto_variacion,
        subconjunto_con_persistencia=subconjunto_con_persistencia,
        n_obs=bag_index.counts,
        y_uiti=bag_index.y,
    )
    print(f"Predicciones fuera de pliegue guardadas en: {ruta_oof}")
else:
    print("Desglose por clase OMITIDO -- requiere las predicciones out-of-fold.")
'''

_MD_DESGLOSE = '''\
## 10. Desglose por circuito (reporte, nunca un piso de aceptacion)

La unidad de decision es el agregado global de la celda 9; este desglose
informa, no condiciona -- se reporta pase o no pase la barra A1.
'''

_CODE_DESGLOSE = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    tabla_desglose = desglose_por_circuito(
        clase_observada,
        {
            "modelo": oof_clase_modelo[subconjunto_con_persistencia],
            "persistencia": oof_clase_persistencia[subconjunto_con_persistencia],
        },
        subconjunto_con_persistencia,
        circuito_por_bolsa,
    )
    print(f"{len(tabla_desglose)} circuitos en el desglose.")
    print(tabla_desglose.head(10))
else:
    print("Desglose por circuito OMITIDO -- requiere la celda 8/9.")
'''

_MD_A3 = '''\
### A3: guarda de proxy univariante

Comprueba si alguna feature observada funciona como proxy univariante de la
clase observada. No depende del modelo.
'''

_CODE_A3 = '''\
X_bag_completo = promedio_por_bolsa(X_inst_bolsas, bag_index)
tabla_proxy = guardia_proxy_univariante_mil(
    clase_observada, X_bag_completo, features_inst, seed=RANDOM_STATE,
)
print(tabla_proxy.head(10))
print("anulado:", tabla_proxy.attrs["voided"], "| max_ari:", tabla_proxy.attrs["max_ari"])
if tabla_proxy.attrs["voided"]:
    print("GUARDIA DE PROXY DISPARADA: una sola variable reproduce la clase observada.")
'''

_MD_A4 = '''\
### A4: colapso de compuertas

Si las compuertas no colapsaron, reconstruye un grafo por grupo de criticidad.
'''

_CODE_A4 = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    resultado_a4 = grafo_por_grupo_si_no_colapsado(
        oof_gates, edge_index, clase_observada, len(features_inst),
    )
    print("Colapso de compuerta:", resultado_a4["colapso"]["is_collapsed"])
    if resultado_a4["voided"]:
        print("A4: compuerta colapsada -- el grafo por grupo de criticidad se reporta VACIO.")
    else:
        print(f"A4: compuerta NO colapsada -- {len(resultado_a4['grafos_por_grupo'])} "
              "grafos por grupo de criticidad reconstruidos.")
else:
    print("A4 OMITIDO -- requiere las compuertas out-of-fold de la celda 8.")
'''

_MD_A6 = '''\
### A6: split temporal (diagnostico secundario)

Bloque de ventanas de entrenamiento -> bloque de prueba. Nunca reselecciona la
metrica principal; se reporta al lado.
'''

_CODE_A6 = '''\
train_mask_temporal, test_mask_temporal = particion_bloque_temporal(
    bag_index, ["V1", "V2", "V3", "V4", "V5", "V6", "V7"], ["V8", "V9", "V10", "V11"],
)
print(f"Bloque temporal: {int(train_mask_temporal.sum()):,} bolsas de entrenamiento, "
      f"{int(test_mask_temporal.sum()):,} de prueba.")

if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    _, _, clase_temporal, _ = ajustar_y_evaluar_pliegue(
        np.flatnonzero(train_mask_temporal), np.flatnonzero(test_mask_temporal),
        epochs=EPOCHS, seed=RANDOM_STATE,
    )
    predicciones_temporal_completo = np.full(n_bags, -1, dtype=int)
    predicciones_temporal_completo[test_mask_temporal] = clase_temporal
    tabla_temporal = evaluar_diagnostico_temporal(
        clase_observada,
        {"modelo": predicciones_temporal_completo[test_mask_temporal]},
        test_mask_temporal,
    )
    print(tabla_temporal)
    print(tabla_temporal.attrs["nota"])
else:
    print("A6 OMITIDO -- requiere la compuerta de costo GO de la celda 7.")
'''

_MD_SHAP = '''\
### Kernel SHAP -> ranking Borda

Relevancias por bolsa agregadas por (circuito, vano, ventana), en formato largo
con la nota de exposicion/severidad por variable.
'''

_CODE_SHAP = '''\
from chec_impacto.interpretability.circuit_analysis import KernelShapTopVarsExtractor
from chec_impacto.interpretability.mil_vano_ventana import construir_ranking_borda

# La cola SHAP -> Borda vive en la libreria, con tests
# (tests/test_mil_ranking_borda.py). Estuvo aqui como codigo suelto de celda y
# acumulo dos defectos que solo se ejecutaban con mode='full': tratar la lista
# que devuelve `calcular_top_vars` como si fuera un dict, y colgar la nota de
# exposicion/severidad de una columna `_var` que `agregar_borda` no emite.

TOP_N_VANOS = 97

if PROCEDER_CON_ENTRENAMIENTO_COMPLETO and mode == "full":
    modelo_final, _ = construir_modelo_y_perdida(
        *calcular_estadisticas_reconstruccion_mgcecdl(X_inst_bolsas),
        KernelDensityWeightedMSELoss.from_targets(np.log1p(bag_index.y)),
    )
    resultado_final = entrenar_mil(
        modelo_final, MILBagLoss(
            *calcular_estadisticas_reconstruccion_mgcecdl(X_inst_bolsas), A_adyacencia,
            kernel_loss=KernelDensityWeightedMSELoss.from_targets(np.log1p(bag_index.y)),
            lambda_reconstruction=LAMBDA_RECONSTRUCTION,
            lambda_mutual_information=LAMBDA_MUTUAL_INFORMATION,
            lambda_gate_deviation=LAMBDA_GATE_DEVIATION, reconstruction_normalization="soft",
        ), X_inst_bolsas, bag_index, epochs=EPOCHS, bag_batch_size=BAG_BATCH_SIZE,
        lr=LR, weight_decay=WEIGHT_DECAY, seed=RANDOM_STATE, device=DEVICE,
        verbose=True,
    )
    predictor_final = BagPredictor(resultado_final["model"], features_inst, geometria, device=str(DEVICE))

    rng_shap = np.random.default_rng(RANDOM_STATE)
    indices_muestra = rng_shap.choice(n_bags, size=min(TOP_N_VANOS, n_bags), replace=False)
    extractor = KernelShapTopVarsExtractor(predictor_final, X_bag_completo, features_inst)
    top_vars_por_bolsa = extractor.calcular_top_vars(indices_muestra)

    ranking_borda = construir_ranking_borda(bag_index.keys, indices_muestra, top_vars_por_bolsa)
    print(f"Ranking Borda: {len(ranking_borda)} filas (grupo x variable) "
          f"sobre {len(indices_muestra)} bolsas muestreadas.")
    print(ranking_borda.head(15))
    n_anotadas = int((ranking_borda["nota_exposicion_severidad"] != "").sum())
    print(f"Filas marcadas como exposicion/severidad por construccion: {n_anotadas}")
else:
    print("SHAP OMITIDO -- solo corre con mode='full' y la compuerta de costo en GO.")
'''

_MD_SIMULATOR = '''\
## 15. Contrato del simulador (`predict_fn`), sin correr el simulador

`predict_fn` fija el contrato `{"fused_probs": (n, 4), "predicted_classes":
(n,)}` que `chec_local_interpreter/simulator.py` espera -- el simulador en si
NO se construye ni se corre aqui.
'''

_CODE_SIMULATOR = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO and mode == "full":
    salida_simulador = predict_fn(predictor_final, X_bag_completo[:5])
    assert salida_simulador["fused_probs"].shape == (5, 4)
    assert salida_simulador["predicted_classes"].shape == (5,)
    print("Contrato predict_fn verificado sobre 5 filas de ejemplo:", salida_simulador["predicted_classes"])
else:
    print("Verificacion de predict_fn OMITIDA -- requiere un modelo final ajustado (celda 14).")
'''

_MD_LIMITACION = '''\
## 16. Techo interpretativo honesto

El techo teorico de este problema es la varianza intra-vano medida por 01.4:
39.1%% de la varianza de clase vive DENTRO del vano, el 60.9%% restante lo
explica la identidad del vano por si sola (obs #524) -- cualquier metrica
global hereda gratis ese 60.9%%, que es exactamente lo que la linea base de
persistencia captura con ventaja informacional. Este cuaderno NO reclama
haber superado esa varianza intra-vano mas alla de lo que la barra A1
efectivamente mida.
'''

_MD_SUMMARY = '''\
## 17. Resumen final

Cantidades DERIVADAS en tiempo de ejecucion (nunca literales, salvo las
poblacionales pineadas y verificadas en la celda 4): `p`, `E`, `K`
(indicadores COD_CAUSA), tamano de poblacion, resultado A1, y el sha1 de la
geometria de 01.4.
'''

_CODE_SUMMARY = '''\
if ENTRENAR:
    resumen_final = {
        "ejecucion": EJECUCION,
        "mode": mode,
        "p": p_derivado,
        "E": edge_index.n_edges,
        "K_indicadores_cod_causa": len(encoding.codigos_propios) + 1,
        "n_bolsas": n_bags,
        "n_instancias": n_inst,
        "fraccion_singleton": fraccion_singleton,
        "geometrias_sha1_coincide": geometrias_sha1_coincide,
        "entrenamiento_completo_ejecutado": bool(PROCEDER_CON_ENTRENAMIENTO_COMPLETO),
    }
else:
    _m = predictor_guardado.metadatos
    resumen_final = {
        "ejecucion": EJECUCION,
        "modelo": RUTA_MODELO.name,
        "p": len(predictor_guardado.feature_names),
        "fusion": _m.get("fusion"),
        "lambda_clase": _m.get("lambda_clase"),
        "temperatura_clase": _m.get("temperatura_clase"),
        "macro_f1_cv": _m.get("macro_f1_cv"),
        "macro_f1_randomforest": _m.get("macro_f1_randomforest_referencia"),
        "bolsas_evaluadas": _m["desglose_por_clase"]["modelo"]["n"],
        "entrenamiento_completo_ejecutado": False,
    }
for key, value in resumen_final.items():
    print(f"{key}: {value}")
'''



def _solo_entrenamiento(codigo: str) -> str:
    """Indenta el cuerpo de una celda bajo `if ENTRENAR:`.

    El cuaderno corre por defecto sin entrenar, asi que toda la tuberia cara
    -- cargar el CSV, construir bolsas, la validacion cruzada -- queda detras
    de una sola bandera en vez de repartida en guardas por celda que se
    desincronizan.
    """
    lineas = codigo.rstrip("\n").split("\n")
    cuerpo = "\n".join(f"    {linea}" if linea.strip() else "" for linea in lineas)
    return "if ENTRENAR:\n" + cuerpo + "\n"


def _cell(kind: str, source: str, *, tags: list[str] | None = None) -> nbformat.NotebookNode:
    if kind == "markdown":
        return new_markdown_cell(source)
    cell = new_code_cell(source)
    if tags:
        cell["metadata"]["tags"] = list(tags)
    return cell


def build_notebook() -> nbformat.NotebookNode:
    """Assemble the (unexecuted) notebook-10 skeleton -- pure, no training."""
    cells = [
        _cell("markdown", _MD_TITLE),
        _cell("code", _CODE_PARAMETERS, tags=["parameters"]),
        _cell("markdown", _MD_BOOTSTRAP),
        _cell("code", _CODE_BOOTSTRAP),
        _cell("code", _CODE_IMPORTS),
        _cell("markdown", _MD_CONFIG),
        _cell("code", _CODE_CONFIG),
        # ---- documentacion: siempre visible, no depende de EJECUCION ----
        _cell("markdown", _MD_ARQUITECTURA),
        _cell("markdown", _MD_PERDIDA),
        # ---- visor: lee el modelo guardado ----
        _cell("markdown", _MD_VISOR),
        _cell("code", _CODE_VISOR),
        _cell("markdown", _MD_VARIABLES),
        _cell("code", _CODE_VARIABLES),
        _cell("markdown", _MD_DESEMPENO),
        _cell("code", _CODE_DESEMPENO),
        # ---- entrenamiento: solo con EJECUCION="entrenamiento" ----
        _cell("markdown", _MD_ENTRENAMIENTO),
        _cell("markdown", _MD_DIAGRAM),
        _cell("markdown", _MD_DATA_LOAD),
        _cell("code", _solo_entrenamiento(_CODE_DATA_LOAD)),
        _cell("markdown", _MD_GRAPH),
        _cell("code", _solo_entrenamiento(_CODE_GRAPH)),
        _cell("markdown", _MD_GEOMETRIA),
        _cell("code", _solo_entrenamiento(_CODE_GEOMETRIA)),
        _cell("markdown", _MD_BAGS),
        _cell("code", _solo_entrenamiento(_CODE_BAGS)),
        _cell("markdown", _MD_CLASE_OBSERVADA),
        _cell("code", _solo_entrenamiento(_CODE_CLASE_OBSERVADA)),
        _cell("markdown", _MD_HELPERS),
        _cell("code", _solo_entrenamiento(_CODE_HELPERS)),
        _cell("markdown", _MD_COST_FORECAST),
        _cell("code", _solo_entrenamiento(_CODE_COST_FORECAST)),
        _cell("markdown", _MD_CV_LOOP),
        _cell("code", _solo_entrenamiento(_CODE_CV_LOOP)),
        _cell("markdown", _MD_A1_BASELINES),
        _cell("code", _solo_entrenamiento(_CODE_A1_BASELINES)),
        _cell("markdown", _MD_POR_CLASE),
        _cell("code", _solo_entrenamiento(_CODE_POR_CLASE)),
        _cell("markdown", _MD_DESGLOSE),
        _cell("code", _solo_entrenamiento(_CODE_DESGLOSE)),
        _cell("markdown", _MD_A3),
        _cell("code", _solo_entrenamiento(_CODE_A3)),
        _cell("markdown", _MD_A4),
        _cell("code", _solo_entrenamiento(_CODE_A4)),
        _cell("markdown", _MD_A6),
        _cell("code", _solo_entrenamiento(_CODE_A6)),
        _cell("markdown", _MD_SHAP),
        _cell("code", _solo_entrenamiento(_CODE_SHAP)),
        _cell("markdown", _MD_GUARDADO),
        _cell("code", _CODE_GUARDADO),
        _cell("markdown", _MD_SIMULATOR),
        _cell("code", _solo_entrenamiento(_CODE_SIMULATOR)),
        _cell("markdown", _MD_LIMITACION),
        _cell("markdown", _MD_SUMMARY),
        _cell("code", _CODE_SUMMARY),
    ]
    notebook = new_notebook(cells=cells)
    notebook["metadata"]["kernelspec"] = _KERNELSPEC
    notebook["metadata"]["language_info"] = _LANGUAGE_INFO
    return notebook


def assign_deterministic_cell_ids(notebook: nbformat.NotebookNode) -> None:
    """Assign stable, index-derived ids -- required by nbformat >= 4.5, and
    deterministic so re-generation never produces a spurious diff on ids alone."""
    for index, cell in enumerate(notebook.cells):
        cell["id"] = f"cell-{index:03d}"


def _ensure_no_forbidden_literals(notebook: nbformat.NotebookNode) -> None:
    pattern = re.compile(r"(?<![\w.])(" + "|".join(FORBIDDEN_LITERALS) + r")(?![\w])")
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        match = pattern.search(cell.source)
        if match:
            raise ValueError(
                f"Forbidden literal {match.group(0)!r} found in a generated code cell -- "
                "'p' (instance feature count) must always be derived at runtime."
            )


def _ensure_code_cells_parse(notebook: nbformat.NotebookNode) -> None:
    for cell in notebook.cells:
        if cell.cell_type == "code":
            ast.parse(cell.source)


def generate(out_path: Path) -> nbformat.NotebookNode:
    notebook = build_notebook()
    assign_deterministic_cell_ids(notebook)
    _ensure_no_forbidden_literals(notebook)
    _ensure_code_cells_parse(notebook)
    nbformat.validate(notebook)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, out_path)
    return notebook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=NOTEBOOK_10_PATH,
        help="Output path for the generated notebook (defaults to notebooks/project_flow/05_*.ipynb).",
    )
    args = parser.parse_args()

    notebook = generate(args.out)
    print(f"Notebook 10 written to {args.out} ({len(notebook.cells)} cells).")


if __name__ == "__main__":
    main()
